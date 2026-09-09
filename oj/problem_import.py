"""Pure parsers for OJ Problem Archive v1 and Luogu-flat data ZIPs.

Parsing is deliberately separated from preview persistence and database
mutation.  Callers keep the returned :class:`ParsedProblemArchive` server-side
and expose only ``make_preview`` until a user explicitly confirms an import.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import hashlib
import json
import math
import re
from typing import Any

from oj.common import APIError
from oj.safe_archive import ArchiveMember, SafeArchiveError, read_safe_zip
from oj.translations import validate_translation

SCHEMA_VERSION = "oj.problem-import-preview.v1"
NATIVE_SCHEMA = "oj.problem-archive.v1"
MAX_CASES = 200
MAX_CASE_TEXT = 1_000_000

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
_NATIVE_PATH = re.compile(
    r"^(?:[^/]+/)?(?:problem\.json|statements/(?:zh-CN|en)/"
    r"(?:description|input_description|output_description|constraints|hint)\.md|"
    r"data/(?:sample|secret)/[^/]+\.(?:in|out|ans))$"
)
_LUOGU_PATH = re.compile(r"^(?:config\.yml|[^/]+\.(?:in|out|ans))$", re.IGNORECASE)
_REQUIRED_STATEMENT_FIELDS = (
    "description",
    "input_description",
    "output_description",
    "constraints",
)
_OPTIONAL_TEXT_FIELDS = ("hint", "source", "author", "difficulty")


class ImportError(Exception):
    """Stable problem-import error with no uploaded content in its message."""

    def __init__(self, code: str, message: str, *, field: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field

    def as_dict(self) -> dict[str, str | None]:
        return {"code": self.code, "message": self.message, "field": self.field}


@dataclass(frozen=True)
class ParsedProblemArchive:
    source_format: str
    archive_sha256: str
    problem: Mapping[str, Any]
    sample_count: int
    testcase_count: int
    limits: Mapping[str, int | float | None]
    warnings: tuple[Mapping[str, str | None], ...] = field(default_factory=tuple)
    missing_fields: tuple[str, ...] = field(default_factory=tuple)

    @property
    def can_commit(self) -> bool:
        return not self.missing_fields

    def make_preview(
        self,
        *,
        preview_id: str,
        expires_at: str,
        conflict_exists: bool = False,
        current_digest: str | None = None,
    ) -> dict[str, Any]:
        public_problem = {
            key: value for key, value in self.problem.items() if key not in {"samples", "testcases"}
        }
        return {
            "schema_version": SCHEMA_VERSION,
            "preview_id": preview_id,
            "archive_sha256": self.archive_sha256,
            "source_format": self.source_format,
            "expires_at": expires_at,
            "problem": public_problem,
            "cases": {"samples": self.sample_count, "testcases": self.testcase_count},
            "limits": dict(self.limits),
            "warnings": [dict(item) for item in self.warnings],
            "missing_fields": list(self.missing_fields),
            "conflict": {"exists": bool(conflict_exists), "current_digest": current_digest},
            "can_commit": self.can_commit and not conflict_exists,
        }


def _error(code: str, message: str, field: str | None = None) -> None:
    raise ImportError(code, message, field=field)


def _archive_members(raw: bytes, validator: Callable[[str], bool]) -> Mapping[str, ArchiveMember]:
    try:
        return read_safe_zip(raw, path_validator=validator)
    except SafeArchiveError as exc:
        raise ImportError("ARCHIVE_UNSAFE", exc.message) from exc


def _decode(
    data: bytes,
    field_name: str,
    *,
    required: bool = True,
    maximum: int = MAX_CASE_TEXT,
) -> str:
    try:
        value = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        _error("BAD_ENCODING", "Archive text files must use UTF-8.", field_name)
    if len(value) > maximum:
        _error("TEXT_TOO_LARGE", "An archive text field exceeds its limit.", field_name)
    if required and not value.strip():
        _error("FIELD_REQUIRED", "A required archive field is empty.", field_name)
    return value


def _strict_json(data: bytes) -> Any:
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                _error("MANIFEST_DUPLICATE_KEY", "The manifest contains duplicate keys.")
            result[key] = value
        return result

    try:
        text = data.decode("utf-8-sig")
        return json.loads(
            text,
            object_pairs_hook=pairs,
            parse_constant=lambda _: _error(
                "MANIFEST_NUMBER_INVALID", "The manifest contains a non-finite number."
            ),
        )
    except UnicodeDecodeError:
        _error("BAD_ENCODING", "The manifest must use UTF-8.", "problem.json")
    except (json.JSONDecodeError, RecursionError):
        _error("MANIFEST_INVALID", "The problem manifest is not valid JSON.", "problem.json")


def _object(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _error("MANIFEST_FIELD_INVALID", "A manifest object is invalid.", field_name)
    return value


def _strict_keys(value: Mapping[str, Any], allowed: set[str], field_name: str) -> None:
    if set(value) - allowed:
        _error("MANIFEST_FIELD_UNSUPPORTED", "The manifest has an unsupported field.", field_name)


def _text(
    value: Any,
    field_name: str,
    *,
    required: bool = True,
    maximum: int = 200_000,
) -> str:
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
        _error("MANIFEST_FIELD_INVALID", "A manifest text field is invalid.", field_name)
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        _error("BAD_ENCODING", "Manifest text must be valid UTF-8.", field_name)
    return value


def _positive_number(value: Any, field_name: str, *, integer: bool = False) -> int | float:
    valid_type = isinstance(value, int) if integer else isinstance(value, (int, float))
    if isinstance(value, bool) or not valid_type:
        _error("LIMIT_INVALID", "A resource limit is invalid.", field_name)
    if not math.isfinite(value) or value <= 0:
        _error("LIMIT_INVALID", "A resource limit is invalid.", field_name)
    return value


def _native_relative_members(
    members: Mapping[str, ArchiveMember],
) -> tuple[dict[str, ArchiveMember], str]:
    manifests = [
        path for path in members if path == "problem.json" or path.endswith("/problem.json")
    ]
    if len(manifests) != 1:
        _error("MANIFEST_REQUIRED", "The archive must contain exactly one problem.json.")
    manifest_path = manifests[0]
    wrapper = manifest_path[: -len("problem.json")]
    if wrapper and wrapper[:-1].count("/"):
        _error("ARCHIVE_LAYOUT_INVALID", "Only one optional wrapper directory is supported.")
    relative: dict[str, ArchiveMember] = {}
    for path, member in members.items():
        if not path.startswith(wrapper):
            _error("ARCHIVE_LAYOUT_INVALID", "All archive files must share one root.")
        name = path[len(wrapper) :]
        if not name or "/" not in name and name != "problem.json":
            _error("ARCHIVE_LAYOUT_INVALID", "The native archive layout is invalid.")
        relative[name] = member
    return relative, wrapper


def _case_pairs(
    manifest_value: Any,
    *,
    group: str,
    members: Mapping[str, ArchiveMember],
    referenced: set[str],
) -> list[dict[str, str]]:
    if not isinstance(manifest_value, list) or not manifest_value:
        _error("CASE_LIST_INVALID", "Each native case group must be a non-empty list.", group)
    if len(manifest_value) > MAX_CASES:
        _error("CASE_COUNT_LIMIT", "The archive contains too many cases.", group)
    expected_dir = "data/sample/" if group == "samples" else "data/secret/"
    cases: list[dict[str, str]] = []
    for index, raw_pair in enumerate(manifest_value):
        pair = _object(raw_pair, f"{group}[{index}]")
        _strict_keys(pair, {"input", "output"}, f"{group}[{index}]")
        input_path = _text(pair.get("input"), f"{group}[{index}].input", maximum=500)
        output_path = _text(pair.get("output"), f"{group}[{index}].output", maximum=500)
        if (
            not input_path.startswith(expected_dir)
            or not output_path.startswith(expected_dir)
            or not input_path.endswith(".in")
            or not output_path.endswith((".out", ".ans"))
        ):
            _error("CASE_PATH_INVALID", "A case path does not match its case group.", group)
        if input_path.rsplit(".", 1)[0] != output_path.rsplit(".", 1)[0]:
            _error("CASE_PAIR_INVALID", "Case input and output names must match.", group)
        if input_path in referenced or output_path in referenced:
            _error("CASE_DUPLICATE", "A case file is referenced more than once.", group)
        try:
            input_member, output_member = members[input_path], members[output_path]
        except KeyError:
            _error("CASE_FILE_MISSING", "A referenced case file is missing.", group)
        referenced.update({input_path, output_path})
        cases.append(
            {
                "input": _decode(input_member.data, input_path, required=False),
                "output": _decode(output_member.data, output_path, required=False),
            }
        )
    return cases


def parse_native_archive(raw: bytes) -> ParsedProblemArchive:
    """Parse the strict, one-problem ``oj.problem-archive.v1`` format."""

    members = _archive_members(raw, lambda path: bool(_NATIVE_PATH.fullmatch(path)))
    members, _ = _native_relative_members(members)
    manifest = _object(_strict_json(members["problem.json"].data), "problem.json")
    _strict_keys(
        manifest,
        {"schema", "problem", "judge", "statements", "samples", "testcases"},
        "problem.json",
    )
    if manifest.get("schema") != NATIVE_SCHEMA:
        _error("SCHEMA_UNSUPPORTED", "The problem archive schema is not supported.", "schema")

    metadata = _object(manifest.get("problem"), "problem")
    _strict_keys(
        metadata,
        {"id", "title", "title_en", "source", "author", "difficulty", "tags"},
        "problem",
    )
    problem_id = _text(metadata.get("id"), "problem.id", maximum=80)
    if not _ID.fullmatch(problem_id):
        _error("PROBLEM_ID_INVALID", "The problem id is invalid.", "problem.id")
    title = _text(metadata.get("title"), "problem.title", maximum=300)
    tags = metadata.get("tags", [])
    if not isinstance(tags, list) or len(tags) > 50:
        _error("MANIFEST_FIELD_INVALID", "Problem tags are invalid.", "problem.tags")
    tags = [_text(item, "problem.tags", maximum=100) for item in tags]

    judge = _object(manifest.get("judge"), "judge")
    _strict_keys(judge, {"type", "time_limit", "memory_limit"}, "judge")
    if judge.get("type") != "standard":
        _error("UNSUPPORTED_JUDGE", "Only standard output comparison is supported.", "judge.type")
    time_limit = _positive_number(judge.get("time_limit"), "judge.time_limit")
    memory_limit = _positive_number(judge.get("memory_limit"), "judge.memory_limit", integer=True)

    statements = _object(manifest.get("statements"), "statements")
    _strict_keys(statements, {"zh-CN", "en"}, "statements")
    if "zh-CN" not in statements:
        _error("STATEMENT_REQUIRED", "A zh-CN statement is required.", "statements.zh-CN")
    referenced = {"problem.json"}
    translations: dict[str, dict[str, str]] = {}
    for locale, raw_refs in statements.items():
        refs = _object(raw_refs, f"statements.{locale}")
        _strict_keys(refs, set(_REQUIRED_STATEMENT_FIELDS) | {"hint"}, f"statements.{locale}")
        translated: dict[str, str] = {}
        for name in _REQUIRED_STATEMENT_FIELDS:
            path = _text(refs.get(name), f"statements.{locale}.{name}", maximum=500)
            expected = f"statements/{locale}/{name}.md"
            if path != expected or path not in members:
                _error("STATEMENT_PATH_INVALID", "A statement path is invalid.", name)
            referenced.add(path)
            translated[name] = _decode(members[path].data, path, maximum=200_000)
        if "hint" in refs:
            path = _text(refs["hint"], f"statements.{locale}.hint", maximum=500)
            if path != f"statements/{locale}/hint.md" or path not in members:
                _error("STATEMENT_PATH_INVALID", "A statement path is invalid.", "hint")
            referenced.add(path)
            translated["hint"] = _decode(members[path].data, path, required=False, maximum=200_000)
        else:
            translated["hint"] = ""
        translations[locale] = translated
    if "en" in translations:
        translations["en"]["title"] = _text(
            metadata.get("title_en"), "problem.title_en", maximum=300
        )
    elif "title_en" in metadata:
        _error(
            "TRANSLATION_INCOMPLETE",
            "An English title requires a complete English statement.",
            "problem.title_en",
        )

    samples = _case_pairs(
        manifest.get("samples"), group="samples", members=members, referenced=referenced
    )
    testcases = _case_pairs(
        manifest.get("testcases"), group="testcases", members=members, referenced=referenced
    )
    if referenced != set(members):
        _error("ARCHIVE_UNKNOWN_PATH", "The archive contains an unreferenced file.")

    zh = translations["zh-CN"]
    problem: dict[str, Any] = {
        "id": problem_id,
        "title": title,
        **{name: zh[name] for name in _REQUIRED_STATEMENT_FIELDS},
        "hint": zh["hint"],
        "source": _text(metadata.get("source", ""), "problem.source", required=False),
        "author": _text(metadata.get("author", ""), "problem.author", required=False),
        "difficulty": _text(
            metadata.get("difficulty", ""), "problem.difficulty", required=False, maximum=100
        ),
        "tags": tags,
        "samples": samples,
        "testcases": testcases,
        "time_limit": time_limit,
        "memory_limit": memory_limit,
    }
    warnings: list[Mapping[str, str | None]] = []
    if "en" in translations:
        problem["translations"] = {"en": translations["en"]}
    else:
        warnings.append(
            {
                "code": "TRANSLATION_MISSING",
                "message": "No English statement was included.",
                "field": "statements.en",
            }
        )
    return ParsedProblemArchive(
        source_format="native-v1",
        archive_sha256=hashlib.sha256(raw).hexdigest(),
        problem=problem,
        sample_count=len(samples),
        testcase_count=len(testcases),
        limits={"time_limit": time_limit, "memory_limit": memory_limit},
        warnings=tuple(warnings),
    )


def _natural_key(value: str) -> tuple[tuple[int, int | str], ...]:
    return tuple(
        (0, int(piece)) if piece.isdigit() else (1, piece.casefold())
        for piece in re.split(r"(\d+)", value)
    )


def _safe_yaml(data: bytes, loader: Callable[[str], Any] | None) -> dict[str, Any]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        _error("BAD_ENCODING", "config.yml must use UTF-8.", "config.yml")
    if loader is None:
        try:
            import yaml  # type: ignore[import-not-found]
        except ModuleNotFoundError:
            _error(
                "CONFIG_PARSER_UNAVAILABLE",
                "Safe YAML support is not installed for config.yml.",
                "config.yml",
            )
        loader = yaml.safe_load
    try:
        result = loader(text)
    except Exception:
        _error("CONFIG_INVALID", "config.yml could not be parsed safely.", "config.yml")
    return _object(result, "config.yml")


_UNSUPPORTED_CONFIG_KEYS = {
    "subtask": "UNSUPPORTED_SUBTASK",
    "subtasks": "UNSUPPORTED_SUBTASK",
    "dependency": "UNSUPPORTED_SUBTASK",
    "dependencies": "UNSUPPORTED_SUBTASK",
    "spj": "UNSUPPORTED_CHECKER",
    "checker": "UNSUPPORTED_CHECKER",
    "validator": "UNSUPPORTED_CHECKER",
    "output_validator": "UNSUPPORTED_CHECKER",
    "interactor": "UNSUPPORTED_INTERACTOR",
    "interactive": "UNSUPPORTED_INTERACTOR",
    "pretest": "UNSUPPORTED_PRETEST",
    "pretests": "UNSUPPORTED_PRETEST",
}


def _reject_unsupported_config(
    value: Any,
    *,
    seen: set[int] | None = None,
    depth: int = 0,
    count: list[int] | None = None,
) -> None:
    if depth > 20:
        _error("CONFIG_INVALID", "config.yml exceeds the nesting limit.", "config.yml")
    seen = seen if seen is not None else set()
    count = count if count is not None else [0]
    count[0] += 1
    if count[0] > 1_000:
        _error("CONFIG_INVALID", "config.yml contains too many values.", "config.yml")
    if isinstance(value, dict):
        if id(value) in seen:
            _error("CONFIG_INVALID", "config.yml contains a recursive alias.", "config.yml")
        seen.add(id(value))
        for key, child in value.items():
            lowered = str(key).casefold()
            if lowered in _UNSUPPORTED_CONFIG_KEYS:
                _error(
                    _UNSUPPORTED_CONFIG_KEYS[lowered],
                    "config.yml requests an unsupported judge feature.",
                    "config.yml",
                )
            _reject_unsupported_config(child, seen=seen, depth=depth + 1, count=count)
        seen.remove(id(value))
    elif isinstance(value, list):
        if id(value) in seen:
            _error("CONFIG_INVALID", "config.yml contains a recursive alias.", "config.yml")
        seen.add(id(value))
        for child in value:
            _reject_unsupported_config(child, seen=seen, depth=depth + 1, count=count)
        seen.remove(id(value))


def _config_memory(config: Mapping[str, Any], *, prefix: str = "") -> int | None:
    direct = config.get("memory_limit")
    kib = config.get("memory_limit_kb")
    if direct is not None and kib is not None:
        _error("CONFIG_INVALID", "Memory limit fields conflict.", f"{prefix}memory_limit")
    if kib is not None:
        kib = _positive_number(kib, f"{prefix}memory_limit_kb", integer=True)
        if kib % 1024:
            _error(
                "UNSUPPORTED_MEMORY_PRECISION",
                "Memory limits must be a whole number of MiB.",
                f"{prefix}memory_limit_kb",
            )
        return kib // 1024
    if direct is not None:
        return int(_positive_number(direct, f"{prefix}memory_limit", integer=True))
    return None


def _config_time(config: Mapping[str, Any], *, prefix: str = "") -> int | float | None:
    direct = config.get("time_limit")
    millis = config.get("time_limit_ms")
    if direct is not None and millis is not None:
        _error("CONFIG_INVALID", "Time limit fields conflict.", f"{prefix}time_limit")
    if millis is not None:
        return _positive_number(millis, f"{prefix}time_limit_ms") / 1000
    if direct is not None:
        return _positive_number(direct, f"{prefix}time_limit")
    return None


def _parse_luogu_config(
    data: bytes,
    *,
    loader: Callable[[str], Any] | None,
    known_pairs: Mapping[str, tuple[str, str]],
) -> tuple[int | float | None, int | None]:
    config = _safe_yaml(data, loader)
    _reject_unsupported_config(config)
    _strict_keys(
        config,
        {"time_limit", "time_limit_ms", "memory_limit", "memory_limit_kb", "cases"},
        "config.yml",
    )
    global_time, global_memory = _config_time(config), _config_memory(config)
    raw_cases = config.get("cases", [])
    if not isinstance(raw_cases, list):
        _error("CONFIG_INVALID", "config.yml cases must be a list.", "config.yml.cases")
    observed_times: set[int | float] = set()
    observed_memories: set[int] = set()
    explicit_time_limits = 0
    explicit_memory_limits = 0
    seen_inputs: set[str] = set()
    for index, raw_case in enumerate(raw_cases):
        case = _object(raw_case, f"config.yml.cases[{index}]")
        _strict_keys(
            case,
            {
                "input",
                "output",
                "score",
                "time_limit",
                "time_limit_ms",
                "memory_limit",
                "memory_limit_kb",
            },
            f"config.yml.cases[{index}]",
        )
        input_path = _text(case.get("input"), "config.yml.cases.input", maximum=500)
        output_path = _text(case.get("output"), "config.yml.cases.output", maximum=500)
        stem = input_path.rsplit(".", 1)[0]
        if stem not in known_pairs or known_pairs[stem] != (input_path, output_path):
            _error("CONFIG_CASE_MISMATCH", "config.yml references an unknown case.", "cases")
        if input_path in seen_inputs:
            _error("CONFIG_CASE_MISMATCH", "config.yml repeats a case.", "cases")
        seen_inputs.add(input_path)
        score = case.get("score", 10)
        if isinstance(score, bool) or not isinstance(score, (int, float)) or score != 10:
            _error(
                "UNSUPPORTED_CASE_WEIGHT",
                "Only the judge's fixed 10-point case weight is supported.",
                "score",
            )
        case_time = _config_time(case, prefix=f"cases[{index}].")
        case_memory = _config_memory(case, prefix=f"cases[{index}].")
        if case_time is not None:
            observed_times.add(case_time)
            explicit_time_limits += 1
        if case_memory is not None:
            observed_memories.add(case_memory)
            explicit_memory_limits += 1
    if len(observed_times) > 1 or (
        global_time is not None and observed_times and observed_times != {global_time}
    ):
        _error(
            "UNSUPPORTED_HETEROGENEOUS_LIMITS",
            "Per-case time limits must be identical.",
            "time_limit",
        )
    if len(observed_memories) > 1 or (
        global_memory is not None and observed_memories and observed_memories != {global_memory}
    ):
        _error(
            "UNSUPPORTED_HETEROGENEOUS_LIMITS",
            "Per-case memory limits must be identical.",
            "memory_limit",
        )
    if global_time is None and observed_times and explicit_time_limits != len(known_pairs):
        _error(
            "UNSUPPORTED_PARTIAL_CASE_LIMITS",
            "A per-case time limit can only be promoted when every case defines it.",
            "time_limit",
        )
    if global_memory is None and observed_memories and explicit_memory_limits != len(known_pairs):
        _error(
            "UNSUPPORTED_PARTIAL_CASE_LIMITS",
            "A per-case memory limit can only be promoted when every case defines it.",
            "memory_limit",
        )
    return global_time or next(iter(observed_times), None), global_memory or next(
        iter(observed_memories), None
    )


def _metadata_problem(
    metadata: Mapping[str, Any] | None,
    *,
    testcases: list[dict[str, str]],
    time_limit: int | float | None,
    memory_limit: int | None,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    metadata = dict(metadata or {})
    allowed = {
        "id",
        "title",
        "description",
        "input_description",
        "output_description",
        "constraints",
        "hint",
        "source",
        "author",
        "difficulty",
        "tags",
        "samples",
        "time_limit",
        "memory_limit",
        "translations",
    }
    if set(metadata) - allowed:
        _error("METADATA_FIELD_UNSUPPORTED", "Problem metadata has an unsupported field.")
    if "translations" in metadata:
        translations = metadata["translations"]
        if not isinstance(translations, Mapping) or set(translations) != {"en"}:
            _error(
                "METADATA_TRANSLATION_INVALID",
                "English problem metadata must be complete.",
                "translations.en",
            )
        try:
            metadata["translations"] = {"en": validate_translation(translations["en"])}
        except APIError:
            _error(
                "METADATA_TRANSLATION_INVALID",
                "English problem metadata must be complete English text.",
                "translations.en",
            )
    required = (
        "id",
        "title",
        "description",
        "input_description",
        "output_description",
        "constraints",
        "samples",
    )
    missing = tuple(name for name in required if name not in metadata)
    problem: dict[str, Any] = dict(metadata)
    problem.update(
        {
            "testcases": testcases,
            "time_limit": metadata.get("time_limit", time_limit),
            "memory_limit": metadata.get("memory_limit", memory_limit),
        }
    )
    for name in _OPTIONAL_TEXT_FIELDS:
        problem.setdefault(name, "")
    problem.setdefault("tags", [])
    if "id" in problem:
        problem_id = _text(problem["id"], "id", maximum=80)
        if not _ID.fullmatch(problem_id):
            _error("PROBLEM_ID_INVALID", "The problem id is invalid.", "id")
    for name in required[1:-1]:
        if name in problem:
            problem[name] = _text(problem[name], name)
    for name in _OPTIONAL_TEXT_FIELDS:
        maximum = 100 if name == "difficulty" else 200_000
        problem[name] = _text(problem[name], name, required=False, maximum=maximum)
    tags = problem["tags"]
    if not isinstance(tags, list) or len(tags) > 50:
        _error("METADATA_FIELD_INVALID", "Problem tags are invalid.", "tags")
    problem["tags"] = [_text(tag, "tags", maximum=100) for tag in tags]
    if problem["time_limit"] is not None:
        problem["time_limit"] = _positive_number(problem["time_limit"], "time_limit")
    if problem["memory_limit"] is not None:
        problem["memory_limit"] = _positive_number(
            problem["memory_limit"], "memory_limit", integer=True
        )
    if "samples" in problem:
        samples = problem["samples"]
        if not isinstance(samples, list) or not 1 <= len(samples) <= MAX_CASES:
            _error("METADATA_FIELD_INVALID", "At least one public sample is required.", "samples")
        normalized_samples = []
        for case in samples:
            if not isinstance(case, dict) or set(case) != {"input", "output"}:
                _error("METADATA_FIELD_INVALID", "A sample is invalid.", "samples")
            normalized_samples.append(
                {
                    "input": _text(
                        case["input"], "samples.input", required=False, maximum=MAX_CASE_TEXT
                    ),
                    "output": _text(
                        case["output"], "samples.output", required=False, maximum=MAX_CASE_TEXT
                    ),
                }
            )
        problem["samples"] = normalized_samples
    return problem, missing


def parse_luogu_archive(
    raw: bytes,
    *,
    metadata: Mapping[str, Any] | None = None,
    config_loader: Callable[[str], Any] | None = None,
) -> ParsedProblemArchive:
    """Parse a root-flat Luogu test-data ZIP without inventing statement data."""

    members = _archive_members(raw, lambda path: bool(_LUOGU_PATH.fullmatch(path)))
    inputs: dict[str, str] = {}
    outputs: dict[str, str] = {}
    for path in members:
        lower = path.casefold()
        if lower == "config.yml":
            continue
        stem, suffix = path.rsplit(".", 1)
        if suffix.casefold() == "in":
            inputs[stem] = path
        else:
            if stem in outputs:
                _error("CASE_PAIR_AMBIGUOUS", "A case has more than one answer file.")
            outputs[stem] = path
    if not inputs or set(inputs) != set(outputs):
        _error("CASE_PAIR_MISSING", "Every .in file must have one matching .out or .ans file.")
    if len(inputs) > MAX_CASES:
        _error("CASE_COUNT_LIMIT", "The archive contains too many cases.")
    pairs = {stem: (inputs[stem], outputs[stem]) for stem in inputs}
    testcases = [
        {
            "input": _decode(members[pairs[stem][0]].data, pairs[stem][0], required=False),
            "output": _decode(members[pairs[stem][1]].data, pairs[stem][1], required=False),
        }
        for stem in sorted(pairs, key=_natural_key)
    ]
    time_limit: int | float | None = None
    memory_limit: int | None = None
    if "config.yml" in members:
        time_limit, memory_limit = _parse_luogu_config(
            members["config.yml"].data, loader=config_loader, known_pairs=pairs
        )
    problem, missing = _metadata_problem(
        metadata,
        testcases=testcases,
        time_limit=time_limit,
        memory_limit=memory_limit,
    )
    warnings: list[Mapping[str, str | None]] = [
        {
            "code": "LUOGU_DATA_ONLY",
            "message": "This ZIP contains test data, not a complete problem archive.",
            "field": None,
        }
    ]
    if "config.yml" not in members:
        warnings.append(
            {
                "code": "LIMITS_NOT_PROVIDED",
                "message": "No safe config.yml resource limits were provided.",
                "field": "limits",
            }
        )
    return ParsedProblemArchive(
        source_format="luogu-flat-v1",
        archive_sha256=hashlib.sha256(raw).hexdigest(),
        problem=problem,
        sample_count=len(problem.get("samples", [])),
        testcase_count=len(testcases),
        limits={
            "time_limit": problem.get("time_limit"),
            "memory_limit": problem.get("memory_limit"),
        },
        warnings=tuple(warnings),
        missing_fields=missing,
    )


def parse_problem_archive(
    raw: bytes,
    *,
    source_format: str,
    metadata: Mapping[str, Any] | None = None,
    config_loader: Callable[[str], Any] | None = None,
) -> ParsedProblemArchive:
    """Dispatch an explicitly selected archive format (never heuristic fallback)."""

    if source_format == "native-v1":
        if metadata is not None:
            _error("METADATA_NOT_ALLOWED", "Native archives already contain problem metadata.")
        return parse_native_archive(raw)
    if source_format == "luogu-flat-v1":
        return parse_luogu_archive(raw, metadata=metadata, config_loader=config_loader)
    _error("FORMAT_UNSUPPORTED", "The selected problem archive format is not supported.")


__all__ = [
    "ImportError",
    "NATIVE_SCHEMA",
    "ParsedProblemArchive",
    "SCHEMA_VERSION",
    "parse_luogu_archive",
    "parse_native_archive",
    "parse_problem_archive",
]
