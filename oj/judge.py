"""Course judge v1: validated language templates and isolated scratch execution."""

from __future__ import annotations

import asyncio
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import sys
import tempfile

from oj.common import APIError
from oj.runner import ProcessResult, run_command

COMPILE_TIMEOUT = 20.0
COMPILE_MEMORY = 512
MESSAGE_LIMIT = 4000
INTERPRETERS = {"python", "python3", "pypy", "pypy3", "node", "ruby", "perl"}
COMPILERS = {"g++", "gcc", "clang++", "clang", "rustc", "javac"}


def _invalid(message: str) -> None:
    raise APIError(400, message)


def _tokens(template: str) -> list[str]:
    if not isinstance(template, str) or not template.strip() or len(template) > 1000:
        _invalid("Language command must be a nonempty string")
    if re.search(r"[\x00-\x1f;&|<>`$]", template):
        _invalid("Unsafe language command")
    try:
        argv = shlex.split(template)
    except ValueError:
        _invalid("Malformed language command")
    if not argv or any("{" in arg or "}" in arg for arg in argv if arg not in {"{src}", "{exe}"}):
        _invalid("Unsupported language placeholder")
    return argv


def _executable_name(executable: str) -> str:
    name = executable.replace("\\", "/").rsplit("/", 1)[-1].removesuffix(".exe")
    if "/" in executable or "\\" in executable:
        allowed = [sys.executable, shutil.which(name)]
        if not any(
            path
            and os.path.normcase(os.path.abspath(executable))
            == os.path.normcase(os.path.abspath(path))
            for path in allowed
        ):
            _invalid("Language executable must be a supported installed tool")
    return name


def _validate_command(template: str, *, compile_stage: bool, compiled: bool) -> None:
    argv = _tokens(template)
    if argv[0] == "{exe}":
        if compile_stage or not compiled or len(argv) != 1:
            _invalid("Executable placeholder needs a compilation command")
        return
    executable = _executable_name(argv[0])
    arguments = argv[1:]
    if compile_stage:
        if executable not in COMPILERS or "{src}" not in arguments or "{exe}" not in arguments:
            _invalid("Compilation needs a supported compiler, source and executable")
        safe = {"{src}", "{exe}", "-o", "-O0", "-O1", "-O2", "-O3", "-Wall", "-Wextra", "-pipe"}
        for argument in arguments:
            if argument not in safe and not re.fullmatch(
                r"-std=(?:c\+\+|gnu\+\+|c|gnu)\d+", argument
            ):
                _invalid("Unsupported compiler option")
        if arguments.count("-o") != 1 or arguments.index("-o") + 1 >= len(arguments):
            _invalid("Compilation must name its output")
        if arguments[arguments.index("-o") + 1] != "{exe}":
            _invalid("Compiler output must use the executable placeholder")
    elif executable in INTERPRETERS:
        if arguments not in (["{src}"], ["-u", "{src}"], ["-I", "{src}"]):
            _invalid("Interpreter command must execute only the source file")
    elif executable == "go" and arguments == ["run", "{src}"]:
        return
    else:
        _invalid("Unsupported or unsafe language executable")


def validate_language(value: dict) -> dict:
    """Validate commands without executing tools; preserve absent limit semantics."""
    if not isinstance(value, dict):
        _invalid("Language must be an object")
    name, extension = value.get("name"), value.get("file_ext")
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_+.-]{0,63}", name):
        _invalid("Invalid language name")
    if not isinstance(extension, str) or not re.fullmatch(r"\.[A-Za-z0-9]{1,10}", extension):
        _invalid("Invalid source extension")
    compile_command = value.get("compile_cmd") or None
    if value.get("compile_cmd") not in (None, "") and not isinstance(value.get("compile_cmd"), str):
        _invalid("Compilation command must be a string")
    run = value.get("run_cmd")
    _validate_command(run, compile_stage=False, compiled=compile_command is not None)
    if compile_command:
        _validate_command(compile_command, compile_stage=True, compiled=True)
    normalized = {
        "name": name,
        "file_ext": extension,
        "run_cmd": run.strip(),
        "compile_cmd": compile_command.strip() if compile_command else None,
    }
    for key in ("time_limit", "memory_limit"):
        limit = value.get(key)
        if limit is not None:
            valid = type(limit) is int if key == "memory_limit" else type(limit) in (int, float)
            try:
                valid = valid and limit > 0 and math.isfinite(limit)
            except OverflowError:
                valid = False
            if not valid:
                _invalid("Language limits must be positive finite numbers")
        normalized[key] = limit
    return normalized


def resolve_limits(problem: dict, language: dict) -> tuple[float, int]:
    values = []
    for key, default in (("time_limit", 3.0), ("memory_limit", 128)):
        value = problem.get(key)
        if value is None:
            value = language.get(key)
        values.append(default if value is None else value)
    return float(values[0]), int(values[1])


def normalize_output(value: str) -> str:
    # Only actual line endings split lines; form feeds are not newlines.
    lines = value.replace("\r\n", "\n").split("\n")
    lines = [line.rstrip() for line in lines]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def _argv(template: str, source: Path, executable: Path) -> list[str]:
    arguments = [
        str(source) if part == "{src}" else str(executable) if part == "{exe}" else part
        for part in _tokens(template)
    ]
    if arguments[0] in {"python", "python3"}:
        arguments[0] = sys.executable
    return arguments


def _classification(result: ProcessResult, *, compile_stage: bool = False) -> str:
    if result.reason in {"spawn", "monitor", "policy"} or (
        result.returncode == 125 and result.stderr == "OJ_RUNNER_EXEC_FAILED"
    ):
        return "UNK"
    if compile_stage:
        return "AC" if result.reason == "ok" and result.returncode == 0 else "CE"
    if result.reason == "timeout" or result.returncode == -getattr(signal, "SIGXCPU", 24):
        return "TLE"
    if result.reason == "memory":
        return "MLE"
    if result.reason == "output":
        return "RE"
    if result.returncode:
        return "RE"
    return "AC"


def _message(text: str, directory: Path) -> str:
    """Remove host paths while retaining useful traceback locations."""

    runner = Path(__file__).with_name("python_runner.py").resolve()
    runner_directory = runner.parent
    project_root = runner_directory.parent
    substitutions = (
        (runner, "[runner]/python_runner.py"),
        (directory.resolve(), "[submission]"),
        (runner_directory, "[runner]"),
        (project_root, "[runner]"),
    )
    sanitized = str(text)
    flags = re.IGNORECASE if os.name == "nt" else 0
    for path, replacement in substitutions:
        variants = sorted({str(path), path.as_posix()}, key=len, reverse=True)
        for variant in variants:
            sanitized = re.sub(
                re.escape(variant), lambda _match: replacement, sanitized, flags=flags
            )

    # A neutral placeholder is part of the public contract; normalize only the
    # placeholder-qualified paths so source snippets and escape sequences stay intact.
    sanitized = re.sub(
        r"\[(runner|submission)\](?:[\\/][^\"\r\n]*)?",
        lambda match: match.group(0).replace("\\", "/"),
        sanitized,
    )
    return sanitized[:MESSAGE_LIMIT]


async def judge_submission(problem: dict, language: dict, code: str) -> dict:
    cases = problem.get("testcases", [])
    output = {
        "status": "success",
        "score": 0,
        "counts": 10 * len(cases),
        "compile_info": None,
        "run_info": None,
        "error_info": None,
        "details": [],
    }
    try:
        language = validate_language(language)
        if not cases:
            raise ValueError("No testcases")
        time_limit, memory_limit = resolve_limits(problem, language)
        with tempfile.TemporaryDirectory(prefix="oj-submission-") as temporary:
            directory = Path(temporary)
            source = directory / ("main" + language["file_ext"])
            executable = directory / ("program.exe" if os.name == "nt" else "program")
            memory_evidence = directory / "allocation-evidence"
            source.write_text(code, encoding="utf-8")
            if language["compile_cmd"]:
                compile_argv = _argv(language["compile_cmd"], source, executable)
                if sys.platform.startswith("linux") and _executable_name(compile_argv[0]) in {
                    "g++",
                    "clang++",
                }:
                    header = Path(__file__).with_name("cpp_memory_probe.hpp").resolve()
                    compile_argv.extend(
                        [
                            "-include",
                            str(header),
                            "-DOJ_MEMORY_SIGNAL_PATH=" + json.dumps(str(memory_evidence)),
                        ]
                    )
                compile_result = await run_command(
                    compile_argv,
                    directory,
                    "",
                    COMPILE_TIMEOUT,
                    COMPILE_MEMORY,
                )
                verdict = _classification(compile_result, compile_stage=True)
                output["compile_info"] = {
                    "result": "success" if verdict == "AC" else "error",
                    "message": _message(compile_result.stderr, directory)
                    or ("Compilation exceeded its limit" if verdict == "CE" else ""),
                }
                if verdict != "AC":
                    output["details"] = [
                        {"id": index, "result": verdict, "time": 0.0, "memory": 0.0}
                        for index in range(1, len(cases) + 1)
                    ]
                    if verdict == "UNK":
                        error = (
                            "Operating system execution policy blocked the compiler (4551)"
                            if compile_result.reason == "policy"
                            else "Compiler dependency unavailable"
                        )
                        output.update(status="error", error_info=error)
                    return output
            errors = []
            diagnostic = ""
            for index, case in enumerate(cases, 1):
                memory_evidence.unlink(missing_ok=True)
                run_argv = _argv(language["run_cmd"], source, executable)
                is_current_python = os.path.normcase(
                    os.path.abspath(run_argv[0])
                ) == os.path.normcase(os.path.abspath(sys.executable))
                if is_current_python:
                    wrapper = Path(__file__).with_name("python_runner.py").resolve()
                    run_argv = [*run_argv[:-1], str(wrapper), str(memory_evidence), str(source)]
                result = await run_command(
                    run_argv,
                    directory,
                    case["input"],
                    time_limit,
                    memory_limit,
                    memory_evidence=memory_evidence,
                )
                verdict = _classification(result)
                if verdict == "AC" and normalize_output(result.stdout) != normalize_output(
                    case["output"]
                ):
                    verdict = "WA"
                output["details"].append(
                    {
                        "id": index,
                        "result": verdict,
                        "time": round(result.time, 6),
                        "memory": round(result.memory, 6),
                    }
                )
                if verdict == "AC":
                    output["score"] += 10
                else:
                    if verdict not in errors:
                        errors.append(verdict)
                    if result.stderr and not diagnostic:
                        diagnostic = _message(result.stderr, directory)
                if verdict == "UNK":
                    error = (
                        "Operating system execution policy blocked the program (4551)"
                        if result.reason == "policy"
                        else "Execution dependency unavailable"
                    )
                    output.update(status="error", error_info=error)
            output["run_info"] = {
                "result": "finished" if output["status"] == "success" else "error",
                "message": (
                    f"{len(cases)} test cases finished"
                    + ("\nOverall errors: " + ", ".join(errors) if errors else "")
                    + ("\n" + diagnostic if diagnostic else "")
                )[:MESSAGE_LIMIT],
            }
    except asyncio.CancelledError:
        raise
    except Exception:
        output.update(status="error", error_info="Judge could not complete this submission")
        completed = len(output["details"])
        output["details"].extend(
            {"id": index, "result": "UNK", "time": 0.0, "memory": 0.0}
            for index in range(completed + 1, len(cases) + 1)
        )
    return output
