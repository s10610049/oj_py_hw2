"""Security and contract tests for pure problem-archive parsing."""

from io import BytesIO
import json
import stat
import struct
import zipfile

import pytest

from frontend.import_template import native_problem_template
from oj.problem_import import (
    ImportError,
    parse_luogu_archive,
    parse_native_archive,
    parse_problem_archive,
)
from oj.safe_archive import ArchivePolicy, SafeArchiveError, read_safe_zip


def make_zip(entries, *, compression=zipfile.ZIP_STORED):
    target = BytesIO()
    with zipfile.ZipFile(target, "w", compression=compression) as archive:
        for name, value in entries.items():
            if isinstance(name, zipfile.ZipInfo):
                archive.writestr(name, value)
            else:
                archive.writestr(name, value)
    return target.getvalue()


def test_downloadable_native_template_is_deterministic_and_immediately_parseable():
    first = native_problem_template()
    second = native_problem_template()
    parsed = parse_native_archive(first)

    assert first == second
    assert parsed.can_commit and parsed.problem["id"] == "MY-PROBLEM-001"
    assert parsed.sample_count == 1 and parsed.testcase_count == 1
    assert parsed.problem["translations"]["en"]["title"] == "A + B"


def native_entries(*, english=True, wrapper=""):
    prefix = f"{wrapper}/" if wrapper else ""
    manifest = {
        "schema": "oj.problem-archive.v1",
        "problem": {
            "id": "ARCH-001",
            "title": "两数之和",
            "source": "原创",
            "author": "课程组",
            "difficulty": "入门",
            "tags": ["输入输出", "整数"],
        },
        "judge": {"type": "standard", "time_limit": 1.5, "memory_limit": 128},
        "statements": {
            "zh-CN": {
                field: f"statements/zh-CN/{field}.md"
                for field in (
                    "description",
                    "input_description",
                    "output_description",
                    "constraints",
                    "hint",
                )
            }
        },
        "samples": [{"input": "data/sample/1.in", "output": "data/sample/1.out"}],
        "testcases": [
            {"input": "data/secret/1.in", "output": "data/secret/1.ans"},
            {"input": "data/secret/2.in", "output": "data/secret/2.out"},
        ],
    }
    entries = {
        "problem.json": json.dumps(manifest, ensure_ascii=False),
        "statements/zh-CN/description.md": "计算两个整数的和。",
        "statements/zh-CN/input_description.md": "输入两个整数。",
        "statements/zh-CN/output_description.md": "输出它们的和。",
        "statements/zh-CN/constraints.md": "绝对值不超过 10^9。",
        "statements/zh-CN/hint.md": "使用加法。",
        "data/sample/1.in": "1 2\n",
        "data/sample/1.out": "3\n",
        "data/secret/1.in": "-1 1\n",
        "data/secret/1.ans": "0\n",
        "data/secret/2.in": "5 8\n",
        "data/secret/2.out": "13\n",
    }
    if english:
        manifest["problem"]["title_en"] = "A + B"
        manifest["statements"]["en"] = {
            field: f"statements/en/{field}.md"
            for field in (
                "description",
                "input_description",
                "output_description",
                "constraints",
            )
        }
        entries["problem.json"] = json.dumps(manifest, ensure_ascii=False)
        entries.update(
            {
                "statements/en/description.md": "Add two integers.",
                "statements/en/input_description.md": "Two integers.",
                "statements/en/output_description.md": "Their sum.",
                "statements/en/constraints.md": "Absolute values at most 1e9.",
            }
        )
    return {prefix + name: value for name, value in entries.items()}


def full_luogu_metadata():
    return {
        "id": "LG-LOCAL-1",
        "title": "本地数据题",
        "description": "计算答案。",
        "input_description": "输入整数。",
        "output_description": "输出结果。",
        "constraints": "数据在整数范围内。",
        "samples": [{"input": "1\n", "output": "1\n"}],
        "difficulty": "普及-",
        "tags": ["模拟"],
    }


def test_native_archive_is_problem_ready_and_public_preview_hides_cases():
    raw = make_zip(native_entries(wrapper="one-problem"))
    parsed = parse_native_archive(raw)

    assert parsed.source_format == "native-v1"
    assert parsed.can_commit
    assert parsed.problem["id"] == "ARCH-001"
    assert parsed.problem["samples"] == [{"input": "1 2\n", "output": "3\n"}]
    assert len(parsed.problem["testcases"]) == 2
    assert parsed.problem["translations"]["en"]["title"] == "A + B"
    preview = parsed.make_preview(preview_id="preview-1", expires_at="2026-09-09T13:00:00Z")
    assert set(preview) == {
        "schema_version",
        "preview_id",
        "archive_sha256",
        "source_format",
        "expires_at",
        "problem",
        "cases",
        "limits",
        "warnings",
        "missing_fields",
        "conflict",
        "can_commit",
    }
    assert preview["schema_version"] == "oj.problem-import-preview.v1"
    assert preview["cases"] == {"samples": 1, "testcases": 2}
    assert "samples" not in preview["problem"] and "testcases" not in preview["problem"]
    assert preview["can_commit"] is True


def test_native_missing_optional_english_is_an_explicit_warning():
    parsed = parse_native_archive(make_zip(native_entries(english=False)))
    assert "translations" not in parsed.problem
    assert [warning["code"] for warning in parsed.warnings] == ["TRANSLATION_MISSING"]


def test_preview_conflict_disables_commit_without_losing_digest():
    parsed = parse_native_archive(make_zip(native_entries()))
    preview = parsed.make_preview(
        preview_id="p",
        expires_at="later",
        conflict_exists=True,
        current_digest="abc123",
    )
    assert preview["conflict"] == {"exists": True, "current_digest": "abc123"}
    assert preview["can_commit"] is False


@pytest.mark.parametrize(
    ("mutator", "code"),
    [
        (lambda item: item["judge"].update(type="special"), "UNSUPPORTED_JUDGE"),
        (lambda item: item.update(extra=True), "MANIFEST_FIELD_UNSUPPORTED"),
        (lambda item: item["problem"].update(id="../bad"), "PROBLEM_ID_INVALID"),
        (lambda item: item["samples"][0].update(output="data/secret/1.ans"), "CASE_PATH_INVALID"),
    ],
)
def test_native_rejects_unsupported_or_inconsistent_manifest(mutator, code):
    entries = native_entries()
    manifest = json.loads(entries["problem.json"])
    mutator(manifest)
    entries["problem.json"] = json.dumps(manifest)
    with pytest.raises(ImportError) as caught:
        parse_native_archive(make_zip(entries))
    assert caught.value.code == code
    assert "ARCH-001" not in caught.value.message


def test_native_rejects_unreferenced_even_if_path_shape_is_known():
    entries = native_entries()
    entries["data/secret/not-referenced.in"] = "secret"
    with pytest.raises(ImportError) as caught:
        parse_native_archive(make_zip(entries))
    assert caught.value.code == "ARCHIVE_UNKNOWN_PATH"


@pytest.mark.parametrize("path", ["../problem.json", "/problem.json", "C:/problem.json"])
def test_archive_rejects_unsafe_paths(path):
    with pytest.raises(SafeArchiveError):
        read_safe_zip(make_zip({path: "x"}))


def test_archive_rejects_backslash_ambiguity_even_if_creator_normalizes_names():
    raw = make_zip({"x/problem.json": "x"}).replace(b"x/problem.json", b"x\\problem.json")
    with pytest.raises(SafeArchiveError) as caught:
        read_safe_zip(raw)
    assert caught.value.code == "ARCHIVE_PATH_AMBIGUOUS"


@pytest.mark.parametrize("replacement", [b"\x00", b"\n"])
def test_archive_rejects_nul_and_control_characters_in_raw_names(replacement):
    raw = make_zip({"x/problem.json": "x"}).replace(
        b"x/problem.json", b"x" + replacement + b"problem.json"
    )
    with pytest.raises(SafeArchiveError) as caught:
        read_safe_zip(raw)
    assert caught.value.code == "ARCHIVE_PATH_INVALID"


def test_archive_rejects_unicode_equivalent_duplicates_and_symlinks():
    with pytest.raises(SafeArchiveError) as duplicate:
        read_safe_zip(make_zip({"café.txt": "a", "cafe\u0301.txt": "b"}))
    assert duplicate.value.code == "ARCHIVE_DUPLICATE_PATH"

    link = zipfile.ZipInfo("link.txt")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with pytest.raises(SafeArchiveError) as special:
        read_safe_zip(make_zip({link: "target"}))
    assert special.value.code == "ARCHIVE_SPECIAL_FILE"


def test_archive_rejects_encrypted_flag_nested_payload_and_compression_bomb():
    ordinary = bytearray(make_zip({"file.txt": "hello"}))
    central = ordinary.find(b"PK\x01\x02")
    assert central > 0
    local_flags = struct.unpack_from("<H", ordinary, 6)[0] | 1
    central_flags = struct.unpack_from("<H", ordinary, central + 8)[0] | 1
    struct.pack_into("<H", ordinary, 6, local_flags)
    struct.pack_into("<H", ordinary, central + 8, central_flags)
    with pytest.raises(SafeArchiveError) as encrypted:
        read_safe_zip(bytes(ordinary))
    assert encrypted.value.code == "ARCHIVE_ENCRYPTED"

    nested = make_zip({"nested.zip": make_zip({"x.txt": "x"})})
    with pytest.raises(SafeArchiveError) as nested_error:
        read_safe_zip(nested)
    assert nested_error.value.code == "ARCHIVE_NESTED"

    bomb = make_zip({"large.txt": "a" * 100_000}, compression=zipfile.ZIP_DEFLATED)
    with pytest.raises(SafeArchiveError) as ratio:
        read_safe_zip(bomb)
    assert ratio.value.code == "ARCHIVE_COMPRESSION_RATIO"


def test_archive_boundaries_are_policy_driven_without_disk_extraction():
    raw = make_zip({"a.txt": "123", "b.txt": "456"})
    with pytest.raises(SafeArchiveError) as count:
        read_safe_zip(raw, policy=ArchivePolicy(max_entries=1))
    assert count.value.code == "ARCHIVE_ENTRY_LIMIT"
    with pytest.raises(SafeArchiveError) as total:
        read_safe_zip(raw, policy=ArchivePolicy(max_total_bytes=5))
    assert total.value.code == "ARCHIVE_TOTAL_SIZE_LIMIT"
    with pytest.raises(SafeArchiveError) as entry:
        read_safe_zip(raw, policy=ArchivePolicy(max_entry_bytes=2))
    assert entry.value.code == "ARCHIVE_ENTRY_SIZE_LIMIT"


def test_luogu_flat_never_pretends_to_contain_problem_metadata():
    raw = make_zip({"1.in": "1\n", "1.out": "1\n", "10.in": "10\n", "10.ans": "10\n"})
    parsed = parse_luogu_archive(raw)
    assert parsed.source_format == "luogu-flat-v1"
    assert parsed.can_commit is False
    assert parsed.missing_fields == (
        "id",
        "title",
        "description",
        "input_description",
        "output_description",
        "constraints",
        "samples",
    )
    assert parsed.testcase_count == 2
    assert parsed.warnings[0]["code"] == "LUOGU_DATA_ONLY"


def test_luogu_case_order_handles_mixed_numeric_and_text_stems():
    raw = make_zip({"2.in": "2", "2.out": "2", "alpha.in": "a", "alpha.out": "a"})
    parsed = parse_luogu_archive(raw)
    assert [case["input"] for case in parsed.problem["testcases"]] == ["2", "a"]


def test_luogu_flat_accepts_complete_metadata_and_strict_safe_config():
    config = {
        "time_limit_ms": 1500,
        "memory_limit_kb": 131072,
        "cases": [
            {
                "input": "1.in",
                "output": "1.out",
                "score": 10,
                "time_limit_ms": 1500,
                "memory_limit_kb": 131072,
            },
            {"input": "2.in", "output": "2.ans", "score": 10},
        ],
    }
    raw = make_zip(
        {
            "1.in": "1\n",
            "1.out": "1\n",
            "2.in": "2\n",
            "2.ans": "2\n",
            "config.yml": json.dumps(config),
        }
    )
    parsed = parse_luogu_archive(raw, metadata=full_luogu_metadata(), config_loader=json.loads)
    assert parsed.can_commit
    assert parsed.problem["time_limit"] == 1.5
    assert parsed.problem["memory_limit"] == 128
    assert parsed.sample_count == 1 and parsed.testcase_count == 2


def test_luogu_flat_metadata_preserves_complete_english_prose_only():
    metadata = full_luogu_metadata()
    metadata["translations"] = {
        "en": {
            "title": "Local Data Problem",
            "description": "Compute the answer.",
            "input_description": "Read one integer.",
            "output_description": "Print the result.",
            "constraints": "The value fits in a signed integer.",
            "hint": "Start with the sample.",
        }
    }
    raw = make_zip({"1.in": "1\n", "1.out": "1\n"})

    parsed = parse_luogu_archive(raw, metadata=metadata)

    assert parsed.problem["translations"] == metadata["translations"]
    assert "testcases" not in parsed.problem["translations"]["en"]


def test_luogu_flat_rejects_mixed_language_english_metadata():
    metadata = full_luogu_metadata()
    metadata["translations"] = {
        "en": {
            "title": "本地题目",
            "description": "Compute the answer.",
            "input_description": "Read one integer.",
            "output_description": "Print the result.",
            "constraints": "The value fits in a signed integer.",
            "hint": "",
        }
    }

    with pytest.raises(ImportError) as caught:
        parse_luogu_archive(make_zip({"1.in": "1", "1.out": "1"}), metadata=metadata)

    assert caught.value.code == "METADATA_TRANSLATION_INVALID"


def test_luogu_promotes_identical_limits_only_when_every_case_defines_them():
    config = {
        "cases": [
            {
                "input": "1.in",
                "output": "1.out",
                "time_limit": 1.5,
                "memory_limit": 128,
            },
            {
                "input": "2.in",
                "output": "2.out",
                "time_limit_ms": 1500,
                "memory_limit_kb": 131072,
            },
        ]
    }
    raw = make_zip(
        {
            "1.in": "1",
            "1.out": "1",
            "2.in": "2",
            "2.out": "2",
            "config.yml": json.dumps(config),
        }
    )
    parsed = parse_luogu_archive(raw, config_loader=json.loads)
    assert parsed.problem["time_limit"] == 1.5
    assert parsed.problem["memory_limit"] == 128


@pytest.mark.parametrize(("field", "value"), [("time_limit", 1), ("memory_limit", 128)])
def test_luogu_rejects_partial_per_case_limit_instead_of_promoting_it(field, value):
    config = {
        "cases": [
            {"input": "1.in", "output": "1.out", field: value},
            {"input": "2.in", "output": "2.out"},
        ]
    }
    raw = make_zip(
        {
            "1.in": "1",
            "1.out": "1",
            "2.in": "2",
            "2.out": "2",
            "config.yml": json.dumps(config),
        }
    )
    with pytest.raises(ImportError) as caught:
        parse_luogu_archive(raw, config_loader=json.loads)
    assert caught.value.code == "UNSUPPORTED_PARTIAL_CASE_LIMITS"
    assert caught.value.field == field


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"cases": [{"input": "1.in", "output": "1.out", "score": 20}]}, "UNSUPPORTED_CASE_WEIGHT"),
        (
            {
                "cases": [
                    {"input": "1.in", "output": "1.out", "time_limit": 1},
                    {"input": "2.in", "output": "2.out", "time_limit": 2},
                ]
            },
            "UNSUPPORTED_HETEROGENEOUS_LIMITS",
        ),
        ({"memory_limit_kb": 1025}, "UNSUPPORTED_MEMORY_PRECISION"),
        ({"subtasks": []}, "UNSUPPORTED_SUBTASK"),
        ({"checker": "checker.cpp"}, "UNSUPPORTED_CHECKER"),
        ({"pretests": [1]}, "UNSUPPORTED_PRETEST"),
    ],
)
def test_luogu_config_rejects_semantics_current_judge_cannot_preserve(change, code):
    config = {"time_limit": 1, "memory_limit": 128}
    if "memory_limit_kb" in change:
        config.pop("memory_limit")
    config.update(change)
    raw = make_zip(
        {
            "1.in": "1",
            "1.out": "1",
            "2.in": "2",
            "2.out": "2",
            "config.yml": json.dumps(config),
        }
    )
    with pytest.raises(ImportError) as caught:
        parse_luogu_archive(raw, config_loader=json.loads)
    assert caught.value.code == code


def test_luogu_rejects_unpaired_unknown_and_bad_encoding_files():
    with pytest.raises(ImportError) as unpaired:
        parse_luogu_archive(make_zip({"1.in": "1", "2.out": "2"}))
    assert unpaired.value.code == "CASE_PAIR_MISSING"
    with pytest.raises(ImportError) as unknown:
        parse_luogu_archive(make_zip({"1.in": "1", "1.out": "1", "readme.md": "x"}))
    assert unknown.value.code == "ARCHIVE_UNSAFE"
    with pytest.raises(ImportError) as encoding:
        parse_luogu_archive(make_zip({"1.in": b"\xff", "1.out": "1"}))
    assert encoding.value.code == "BAD_ENCODING"


def test_format_dispatch_is_explicit_and_does_not_fallback():
    raw = make_zip(native_entries())
    assert parse_problem_archive(raw, source_format="native-v1").problem["id"] == "ARCH-001"
    with pytest.raises(ImportError) as caught:
        parse_problem_archive(raw, source_format="automatic")
    assert caught.value.code == "FORMAT_UNSUPPORTED"


def test_duplicate_manifest_keys_and_nonfinite_numbers_are_rejected():
    entries = native_entries()
    entries["problem.json"] = '{"schema":"oj.problem-archive.v1","schema":"bad"}'
    with pytest.raises(ImportError) as duplicate:
        parse_native_archive(make_zip(entries))
    assert duplicate.value.code == "MANIFEST_DUPLICATE_KEY"

    entries = native_entries()
    manifest = json.loads(entries["problem.json"])
    manifest["judge"]["time_limit"] = float("nan")
    entries["problem.json"] = json.dumps(manifest)
    with pytest.raises(ImportError) as nonfinite:
        parse_native_archive(make_zip(entries))
    assert nonfinite.value.code == "MANIFEST_NUMBER_INVALID"


def test_config_recursive_alias_from_loader_is_rejected_without_recursing_forever():
    recursive = []
    recursive.append(recursive)
    raw = make_zip({"1.in": "1", "1.out": "1", "config.yml": "safe-loader-data"})
    with pytest.raises(ImportError) as caught:
        parse_luogu_archive(raw, config_loader=lambda _: {"cases": recursive})
    assert caught.value.code == "CONFIG_INVALID"
