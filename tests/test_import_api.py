"""Two-step problem imports are previewed safely and committed atomically."""

from io import BytesIO
import json
import zipfile

import httpx
import pytest

from oj.main import create_app


def archive(entries):
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for path, value in entries.items():
            target.writestr(path, value)
    return output.getvalue()


def native_archive(problem_id="ARCH-1", title="本地归档题"):
    manifest = {
        "schema": "oj.problem-archive.v1",
        "problem": {
            "id": problem_id,
            "title": title,
            "title_en": "Local archive problem",
            "source": "原创",
            "author": "课程组",
            "difficulty": "入门",
            "tags": ["输入输出"],
        },
        "judge": {"type": "standard", "time_limit": 1.5, "memory_limit": 128},
        "statements": {
            "zh-CN": {
                name: f"statements/zh-CN/{name}.md"
                for name in (
                    "description",
                    "input_description",
                    "output_description",
                    "constraints",
                    "hint",
                )
            },
            "en": {
                name: f"statements/en/{name}.md"
                for name in (
                    "description",
                    "input_description",
                    "output_description",
                    "constraints",
                )
            },
        },
        "samples": [{"input": "data/sample/1.in", "output": "data/sample/1.out"}],
        "testcases": [{"input": "data/secret/1.in", "output": "data/secret/1.out"}],
    }
    entries = {
        "problem.json": json.dumps(manifest, ensure_ascii=False),
        "statements/zh-CN/description.md": "计算两个数的和。",
        "statements/zh-CN/input_description.md": "输入两个整数。",
        "statements/zh-CN/output_description.md": "输出和。",
        "statements/zh-CN/constraints.md": "绝对值不超过十亿。",
        "statements/zh-CN/hint.md": "使用加法。",
        "statements/en/description.md": "Add two integers.",
        "statements/en/input_description.md": "Read two integers.",
        "statements/en/output_description.md": "Print their sum.",
        "statements/en/constraints.md": "Absolute values are at most one billion.",
        "data/sample/1.in": "1 2\n",
        "data/sample/1.out": "3\n",
        "data/secret/1.in": "SECRET_INPUT\n",
        "data/secret/1.out": "SECRET_OUTPUT\n",
    }
    return archive(entries)


async def login(client, username="admin", password="admintestpassword"):
    response = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200


def checked(response, status=200):
    assert response.status_code == status, response.text
    body = response.json()
    assert body["code"] == status and set(body) == {"code", "msg", "data"}
    return body["data"]


async def upload(client, raw):
    return checked(
        await client.post(
            "/api/problem-imports/uploads/",
            params={"filename": "problem.zip", "media_type": "application/zip"},
            content=raw,
        )
    )


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_native_preview_hides_cases_commit_is_idempotent_and_translation_ready(tmp_path):
    app = create_app(tmp_path / "imports.sqlite3", bcrypt_rounds=4, ai_config={})
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            unauthenticated = await client.post(
                "/api/problem-imports/uploads/",
                params={"filename": "problem.zip", "media_type": "application/zip"},
                content=native_archive(),
            )
            checked(unauthenticated, 401)
            await login(client)
            uploaded = await upload(client, native_archive())
            preview = checked(
                await client.post(
                    "/api/problem-imports/previews/",
                    json={"upload_id": uploaded["upload_id"], "source_format": "native-v1"},
                )
            )
            rendered = json.dumps(preview, ensure_ascii=False)
            assert preview["can_commit"] is True
            assert preview["cases"] == {"samples": 1, "testcases": 1}
            assert "SECRET_INPUT" not in rendered and "SECRET_OUTPUT" not in rendered

            path = f"/api/problem-imports/previews/{preview['preview_id']}/commit"
            committed = checked(await client.post(path, json={"overwrite": False}))
            assert committed["problem_id"] == "ARCH-1"
            assert committed["created"] is True
            assert committed["translation_imported"] is True
            assert checked(await client.post(path, json={"overwrite": False})) == committed

            localized = checked(await client.get("/api/problems/ARCH-1", params={"locale": "en"}))
            assert localized["content"]["resolved_locale"] == "en"
            assert localized["content"]["fields"]["title"] == "Local archive problem"
            assert localized["testcases"] == [
                {"input": "SECRET_INPUT\n", "output": "SECRET_OUTPUT\n"}
            ]


@pytest.mark.anyio
async def test_conflict_requires_explicit_digest_and_detects_races(tmp_path):
    app = create_app(tmp_path / "conflict.sqlite3", bcrypt_rounds=4, ai_config={})
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            await login(client)
            first_upload = await upload(client, native_archive())
            first_preview = checked(
                await client.post(
                    "/api/problem-imports/previews/",
                    json={"upload_id": first_upload["upload_id"], "source_format": "native-v1"},
                )
            )
            checked(
                await client.post(
                    f"/api/problem-imports/previews/{first_preview['preview_id']}/commit",
                    json={},
                )
            )

            changed_upload = await upload(client, native_archive(title="更新标题"))
            changed_preview = checked(
                await client.post(
                    "/api/problem-imports/previews/",
                    json={
                        "upload_id": changed_upload["upload_id"],
                        "source_format": "native-v1",
                    },
                )
            )
            assert changed_preview["conflict"]["exists"] is True
            commit_path = f"/api/problem-imports/previews/{changed_preview['preview_id']}/commit"
            checked(await client.post(commit_path, json={}), 409)
            checked(await client.post(commit_path, json={"overwrite": True}), 409)

            existing = checked(await client.get("/api/problems/ARCH-1"))
            existing["title"] = "并发编辑"
            existing.pop("content")
            checked(await client.put("/api/problems/ARCH-1", json=existing))
            checked(
                await client.post(
                    commit_path,
                    json={
                        "overwrite": True,
                        "expected_digest": changed_preview["conflict"]["current_digest"],
                    },
                ),
                409,
            )
            assert checked(await client.get("/api/problems/ARCH-1"))["title"] == "并发编辑"


@pytest.mark.anyio
async def test_luogu_data_requires_metadata_and_unsafe_archives_fail_structured(tmp_path):
    app = create_app(tmp_path / "luogu.sqlite3", bcrypt_rounds=4, ai_config={})
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            await login(client)
            raw = archive({"1.in": "1\n", "1.out": "1\n"})
            uploaded = await upload(client, raw)
            preview = checked(
                await client.post(
                    "/api/problem-imports/previews/",
                    json={
                        "upload_id": uploaded["upload_id"],
                        "source_format": "luogu-flat-v1",
                    },
                )
            )
            assert preview["can_commit"] is False and "id" in preview["missing_fields"]
            checked(
                await client.post(
                    f"/api/problem-imports/previews/{preview['preview_id']}/commit", json={}
                ),
                400,
            )

            unsafe = await upload(client, archive({"../1.in": "secret", "../1.out": "secret"}))
            failure = await client.post(
                "/api/problem-imports/previews/",
                json={"upload_id": unsafe["upload_id"], "source_format": "luogu-flat-v1"},
            )
            error = checked(failure, 400)
            assert error["error_code"] == "ARCHIVE_UNSAFE"
            assert "secret" not in failure.text


@pytest.mark.anyio
async def test_import_upload_and_preview_are_owner_only(tmp_path):
    app = create_app(tmp_path / "owner.sqlite3", bcrypt_rounds=4, ai_config={})
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            await login(client)
            uploaded = await upload(client, native_archive())
            checked(
                await client.post(
                    "/api/users/",
                    json={"username": "alice", "password": "password123"},
                )
            )
            await login(client, "alice", "password123")
            checked(
                await client.post(
                    "/api/problem-imports/previews/",
                    json={"upload_id": uploaded["upload_id"], "source_format": "native-v1"},
                ),
                404,
            )
