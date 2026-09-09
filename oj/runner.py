"""Bounded course process runner; this is not a hostile-code security sandbox."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time

import psutil

OUTPUT_LIMIT = 1024 * 1024
POLL_INTERVAL = 0.005


@dataclass
class ProcessResult:
    reason: str
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    time: float = 0.0
    memory: float = 0.0


class _WindowsJob:
    """Kill-on-close job owns descendants even if their direct parent has exited."""

    def __init__(self, process: subprocess.Popen):
        import ctypes
        from ctypes import wintypes

        class BasicLimits(ctypes.Structure):
            _fields_ = [
                ("process_time", ctypes.c_longlong),
                ("job_time", ctypes.c_longlong),
                ("flags", wintypes.DWORD),
                ("minimum_working_set", ctypes.c_size_t),
                ("maximum_working_set", ctypes.c_size_t),
                ("active_process_limit", wintypes.DWORD),
                ("affinity", ctypes.c_size_t),
                ("priority_class", wintypes.DWORD),
                ("scheduling_class", wintypes.DWORD),
            ]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [
                ("basic", BasicLimits),
                ("io_counters", ctypes.c_ulonglong * 6),
                ("process_memory_limit", ctypes.c_size_t),
                ("job_memory_limit", ctypes.c_size_t),
                ("peak_process_memory", ctypes.c_size_t),
                ("peak_job_memory", ctypes.c_size_t),
            ]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel.SetInformationJobObject.restype = wintypes.BOOL
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel.QueryInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.c_void_p,
        ]
        kernel.QueryInformationJobObject.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        self.kernel, self.handle = kernel, kernel.CreateJobObjectW(None, None)
        self.limit_structure = ExtendedLimits
        if not self.handle:
            raise OSError("Process job could not be created")
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        configured = kernel.SetInformationJobObject(
            self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        )
        assigned = configured and kernel.AssignProcessToJobObject(self.handle, int(process._handle))
        if not assigned:
            self.close()
            if process.poll() is None:
                raise OSError("Process job could not be assigned")

    def peak_memory(self) -> float:
        import ctypes

        if not self.handle:
            return 0.0
        information = self.limit_structure()
        if not self.kernel.QueryInformationJobObject(
            self.handle, 9, ctypes.byref(information), ctypes.sizeof(information), None
        ):
            raise OSError("Process job accounting unavailable")
        return information.peak_job_memory / (1024 * 1024)

    def close(self) -> None:
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def child_environment(directory: Path) -> dict[str, str]:
    """Use an allowlist so model keys, cookies and app configuration never inherit."""
    allowed = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "LANG", "LC_ALL"}
    environment = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    environment.update(
        {
            "HOME": str(directory),
            "USERPROFILE": str(directory),
            "TMP": str(directory),
            "TEMP": str(directory),
            "TMPDIR": str(directory),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    return environment


def _kill_tree(process: subprocess.Popen, known: dict[int, psutil.Process]) -> None:
    try:
        root = psutil.Process(process.pid)
        known.update({child.pid: child for child in root.children(recursive=True)})
    except psutil.Error:
        pass
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    for child in reversed(list(known.values())):
        try:
            child.kill()
        except psutil.Error:
            pass
    if process.poll() is None:
        process.kill()
    process.wait(timeout=5)
    psutil.wait_procs(list(known.values()), timeout=1)


def _execute(
    argv: list[str],
    directory: Path,
    stdin: str,
    time_limit: float,
    memory_limit: int,
    output_limit: int,
    cancel: threading.Event,
) -> ProcessResult:
    command = argv
    if sys.platform.startswith("linux"):
        # Apply rlimits in a fresh interpreter, avoiding unsafe preexec_fn in threads.
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            str(memory_limit),
            str(time_limit),
            str(output_limit),
            *argv,
        ]
    options = {"start_new_session": True} if os.name == "posix" else {}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    known: dict[int, psutil.Process] = {}
    result = ProcessResult("ok")
    process = None
    job = None
    started = time.monotonic()
    with (
        tempfile.TemporaryFile(dir=directory) as input_file,
        tempfile.TemporaryFile(dir=directory) as output_file,
        tempfile.TemporaryFile(dir=directory) as error_file,
    ):
        input_file.write(stdin.encode("utf-8"))
        input_file.seek(0)
        try:
            process = subprocess.Popen(
                command,
                cwd=directory,
                env=child_environment(directory),
                stdin=input_file,
                stdout=output_file,
                stderr=error_file,
                shell=False,
                **options,
            )
            # Windows application control can spend seconds in CreateProcess.
            # Charge the child's wall-clock execution, not OS admission latency.
            started = time.monotonic()
            if os.name == "nt":
                job = _WindowsJob(process)
            try:
                root = psutil.Process(process.pid)
            except psutil.NoSuchProcess:
                root = None
            while True:
                running = process.poll() is None
                try:
                    if root is not None:
                        known.update({child.pid: child for child in root.children(recursive=True)})
                except psutil.Error:
                    pass
                usage = 0
                members = ([root] if root is not None else []) + list(known.values())
                for member in members:
                    try:
                        info = member.memory_info()
                        usage += max(info.rss, getattr(info, "peak_wset", 0))
                    except psutil.NoSuchProcess:
                        continue
                    except psutil.AccessDenied:
                        result.reason = "monitor"
                result.memory = max(result.memory, usage / (1024 * 1024))
                if job is not None:
                    result.memory = max(result.memory, job.peak_memory())
                elapsed = time.monotonic() - started
                output_size = os.fstat(output_file.fileno()).st_size
                error_size = os.fstat(error_file.fileno()).st_size
                if cancel.is_set():
                    result.reason = "cancelled"
                elif result.memory > memory_limit:
                    result.reason = "memory"
                elif output_size + error_size > output_limit:
                    result.reason = "output"
                elif running and elapsed > time_limit:
                    result.reason = "timeout"
                if not running or result.reason != "ok":
                    break
                cancel.wait(POLL_INTERVAL)
        except (OSError, psutil.Error) as error:
            result.reason = "policy" if getattr(error, "winerror", None) == 4551 else "spawn"
        finally:
            result.time = time.monotonic() - started
            if job is not None:
                job.close()
            if process is not None:
                _kill_tree(process, known)
                result.returncode = process.returncode
            output_file.seek(0)
            error_file.seek(0)
            result.stdout = output_file.read(output_limit).decode("utf-8", errors="replace")
            result.stderr = error_file.read(output_limit).decode("utf-8", errors="replace")
    return result


async def run_command(
    argv: list[str],
    directory: Path,
    stdin: str,
    time_limit: float,
    memory_limit: int,
    output_limit: int = OUTPUT_LIMIT,
) -> ProcessResult:
    """Cancellation waits for the worker to kill descendants before scratch cleanup."""
    cancel = threading.Event()
    worker = asyncio.create_task(
        asyncio.to_thread(
            _execute, argv, directory, stdin, time_limit, memory_limit, output_limit, cancel
        )
    )
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        cancel.set()
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                # Reset and shutdown may both cancel; never abandon tree cleanup.
                continue
        worker.result()
        raise


def _linux_entry() -> None:
    import resource

    try:
        memory, timeout, output = int(sys.argv[1]), float(sys.argv[2]), int(sys.argv[3])
        memory_bytes = memory * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        cpu_limit = max(1, math.ceil(timeout))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_limit, cpu_limit + 1))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_FSIZE, (max(output, 32 * 1024 * 1024),) * 2)
        os.execvpe(sys.argv[4], sys.argv[4:], os.environ)
    except (OSError, OverflowError, ValueError):
        sys.stderr.write("OJ_RUNNER_EXEC_FAILED")
        sys.exit(125)


if __name__ == "__main__":
    _linux_entry()
