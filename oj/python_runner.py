"""Execute a Python submission and report uncaught allocator failures separately.

This probe distinguishes Python's real exception object from stderr text and
excludes known exception-injection sites. Other C extensions can still synthesize
MemoryError indistinguishably. It is course instrumentation, not a tamper-proof
channel for hostile submissions.
"""

from collections import deque
import dis
from importlib.machinery import SourceFileLoader
from pathlib import Path
import sys
from types import ModuleType


def allocation_failure(error: BaseException, replay_sites=()) -> bool:
    """Exclude explicit raises and observed exception injection/replay sites."""
    if type(error) is not MemoryError:
        return False
    trace = error.__traceback__
    if trace is None:
        return False
    while trace.tb_next is not None:
        trace = trace.tb_next
    if trace.tb_lasti < 0:  # An unstarted generator on older supported Python versions.
        return False
    if (id(error), id(trace.tb_frame), trace.tb_lasti) in replay_sites:
        return False
    operation = dis.opname[trace.tb_frame.f_code.co_code[trace.tb_lasti]]
    return operation not in {
        "RAISE_VARARGS",
        "RERAISE",
        "YIELD_VALUE",
        "YIELD_FROM",
        "RETURN_GENERATOR",
        "GEN_START",
    }


def main() -> int:
    evidence, source = sys.argv[1:3]
    # Open before the submission consumes memory, and retain a small reporting reserve.
    with open(evidence, "wb", buffering=0) as signal_file:
        reserve = bytearray(64 * 1024)
        sys.argv = [source]
        if not sys.flags.isolated:
            sys.path[0] = str(Path(source).resolve().parent)
        script = ModuleType("__main__")
        script.__file__ = source
        script.__loader__ = SourceFileLoader("__main__", source)
        script.__package__ = None
        script.__spec__ = None
        script.__cached__ = None
        sys.modules["__main__"] = script
        # Keep bounded scalar evidence, without retaining submission frames/objects.
        replay_sites = deque(maxlen=128)

        def remember_replay(frame, event, function):
            if event != "c_exception" or function.__name__ != "result":
                return
            future_type = getattr(sys.modules.get("_asyncio"), "Future", None)
            receiver = function.__self__
            if future_type is not None and isinstance(receiver, future_type):
                if not future_type.done(receiver) or future_type.cancelled(receiver):
                    return
                # Call the base implementation: a subclass may override exception().
                error = future_type.exception(receiver)
                if type(error) is MemoryError:
                    replay_sites.append((id(error), id(frame), frame.f_lasti))

        previous_profile = sys.getprofile()
        profile_intact = True
        sys.setprofile(remember_replay)
        try:
            try:
                program = compile(Path(source).read_bytes(), source, "exec", dont_inherit=True)
                exec(program, script.__dict__)
            finally:
                profile_intact = sys.getprofile() is remember_replay
                if profile_intact:
                    sys.setprofile(previous_profile)
        except SystemExit:
            raise
        except BaseException as error:
            del reserve
            if profile_intact and allocation_failure(error, replay_sites):
                signal_file.write(b"OOM\n")
            trace = error.__traceback__
            while trace is not None and trace.tb_frame.f_code.co_filename == __file__:
                trace = trace.tb_next
            sys.excepthook(type(error), error, trace)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
