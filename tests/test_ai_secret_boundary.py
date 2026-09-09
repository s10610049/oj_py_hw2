"""Final-result secret boundary, using only a synthetic key and offline transports."""

import asyncio
import json

import httpx
import pytest

from oj.main import create_app


@pytest.mark.asyncio
@pytest.mark.parametrize("generated_field", ["input", "output"])
@pytest.mark.parametrize("secret", ["synthetic-final-boundary-key-only", 'synthetic-"key\\only'])
async def test_generated_case_cannot_publish_configured_key(tmp_path, generated_field, secret):
    encoded = repr(list(map(ord, secret)))
    problem = {
        "id": "audit_generated",
        "title": "Synthetic fixture",
        "description": "Offline final-result boundary regression.",
        "input_description": "An integer or a synthetic string.",
        "output_description": "A synthetic string.",
        "constraints": "Only synthetic audit data.",
        "samples": [{"input": "0", "output": "ok"}],
        "testcases": [{"input": "0", "output": "ok"}],
        "reference_solution": 'print("ok")',
        "test_generator": 'import json\nprint(json.dumps(["1"]))',
        "validation_notes": "Synthetic security-boundary fixture.",
        "test_generation_notes": "One deterministic synthetic generated input.",
        "translations": {
            "en": {
                "title": "Synthetic fixture",
                "description": "Offline final-result boundary regression.",
                "input_description": "Read an integer or a synthetic string.",
                "output_description": "Print a synthetic string.",
                "constraints": "Only synthetic audit data is used.",
                "hint": "Validate the final generated cases before publication.",
            }
        },
    }
    if generated_field == "input":
        problem["test_generator"] = (
            'import json\nprint(json.dumps(["".join(map(chr,' + encoded + "))]))"
        )
    else:
        problem["reference_solution"] = (
            'n=input()\nprint("".join(map(chr,' + encoded + ')) if n=="1" else "ok")'
        )
    raw_candidate = json.dumps(problem)
    assert secret not in raw_candidate
    provider_calls = []

    def provider(request):
        provider_calls.append(request)
        payload = {
            "choices": [{"index": 0, "delta": {"content": raw_candidate}, "finish_reason": "stop"}]
        }
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content="data: " + json.dumps(payload) + "\n\ndata: [DONE]\n\n",
        )

    # Explicit empty config prevents reading local .env during application startup.
    app = create_app(tmp_path / "isolated.sqlite3", bcrypt_rounds=4, ai_config={})
    async with app.router.lifespan_context(app):
        app.state.ai._transport = httpx.MockTransport(provider)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://offline.test"
        ) as client:
            credentials = {"username": "audit_user", "password": "synthetic-password-only"}
            assert (await client.post("/api/users/", json=credentials)).status_code == 200
            assert (await client.post("/api/auth/login", json=credentials)).status_code == 200
            configured = await client.put(
                "/api/ai/model-config",
                json={
                    "provider_url": "https://audit.example/v1",
                    "model": "synthetic-model",
                    "api_key": secret,
                },
            )
            assert configured.status_code == 200
            assert secret not in configured.text
            started = await client.post(
                "/api/ai/problem-tasks/", json={"requirement": "Offline synthetic audit."}
            )
            assert started.status_code == 200
            task_id = started.json()["data"]["task_id"]
            await asyncio.wait_for(app.state.ai._tasks[task_id].future, timeout=15)
            public = await client.get(f"/api/ai/problem-tasks/{task_id}")
            assert public.status_code == 200
            final = public.json()["data"]
            assert secret not in public.text
            if final["result"] is not None:
                assert all(
                    secret not in case[generated_field] for case in final["result"]["testcases"]
                )
            assert final["status"] == "failed"
            assert final["result"] is None
            assert len(provider_calls) == 1  # Secret failures must not become repair prompts.
