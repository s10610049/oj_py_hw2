"""Conservative execution gate for reference/answer consistency, not a proof of correctness."""

from __future__ import annotations

import ast
from collections.abc import Callable
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile

from oj.common import APIError
from oj.judge import normalize_output
from oj.runner import run_command
from oj.schemas import validate_problem

SOURCE_LIMIT = 100_000
INPUT_LIMIT = 1_000_000
OUTPUT_LIMIT = 2 * 1024 * 1024
CASE_LIMIT = 40
GENERATED_LIMIT = 12
REFERENCE_SECONDS = 3.0
GENERATOR_SECONDS = 5.0
MEMORY_LIMIT = 128

BUILTINS = set(
    "abs all any bool bytes bytearray chr dict divmod enumerate filter float frozenset "
    "input int isinstance iter len list map max min next ord pow print range reversed round "
    "set sorted str sum tuple zip Exception ValueError RuntimeError AssertionError "
    "StopIteration IndexError KeyError TypeError ZeroDivisionError MemoryError".split()
)
FORBIDDEN = set(
    "open eval exec compile getattr setattr delattr globals locals vars type object help "
    "breakpoint dir id hash super property classmethod staticmethod memoryview".split()
)
MODULE_CALLS = {
    "collections": set("deque defaultdict Counter OrderedDict".split()),
    "math": set(
        "ceil floor trunc sqrt isqrt gcd lcm factorial comb perm log log2 log10 exp "
        "sin cos tan asin acos atan atan2 degrees radians hypot fabs fmod copysign "
        "isfinite isinf isnan isclose prod fsum dist".split()
    ),
    "heapq": set(
        "heapify heappush heappop heappushpop heapreplace nlargest nsmallest merge".split()
    ),
    "bisect": set("bisect bisect_left bisect_right insort insort_left insort_right".split()),
    "itertools": set(
        "accumulate chain combinations combinations_with_replacement compress count cycle "
        "dropwhile filterfalse groupby islice pairwise permutations product repeat starmap "
        "takewhile tee zip_longest".split()
    ),
    "functools": {"reduce"},
    "random": set(
        "seed Random randint randrange choice choices sample shuffle random uniform".split()
    ),
    "json": {"dumps", "loads"},
    "sys": set(),
}
MODULE_VALUES = {"math": {"e", "pi", "tau", "inf", "nan"}, "sys": {"stdin", "stdout"}}
STREAM_CALLS = {
    ("sys", "stdin", "read"),
    ("sys", "stdin", "readline"),
    ("sys", "stdin", "readlines"),
    ("sys", "stdout", "write"),
    ("sys", "stdin", "buffer", "read"),
    ("sys", "stdin", "buffer", "readline"),
    ("sys", "stdin", "buffer", "readlines"),
    ("sys", "stdout", "buffer", "write"),
}
STREAM_BUFFERS = {("sys", "stdin", "buffer"), ("sys", "stdout", "buffer")}
METHODS = set(
    "append extend insert pop remove clear index count sort reverse copy add discard "
    "update difference intersection union symmetric_difference issubset issuperset "
    "isdisjoint difference_update intersection_update symmetric_difference_update "
    "get keys values items setdefault popitem fromkeys split rsplit splitlines strip "
    "lstrip rstrip join replace startswith endswith find rfind lower upper casefold "
    "capitalize title swapcase isdigit isalpha isalnum isspace zfill ljust rjust center "
    "partition rpartition encode decode appendleft extendleft popleft rotate most_common "
    "elements subtract".split()
)
RANDOM_METHODS = MODULE_CALLS["random"] - {"Random", "seed"}
METHODS |= RANDOM_METHODS
SAFE_NODES = {
    ast.Module,
    ast.Import,
    ast.ImportFrom,
    ast.alias,
    ast.FunctionDef,
    ast.arguments,
    ast.arg,
    ast.Return,
    ast.Assign,
    ast.AnnAssign,
    ast.AugAssign,
    ast.Expr,
    ast.If,
    ast.For,
    ast.While,
    ast.Break,
    ast.Continue,
    ast.Pass,
    ast.Try,
    ast.ExceptHandler,
    ast.Raise,
    ast.Assert,
    ast.Global,
    ast.Nonlocal,
    ast.Name,
    ast.Constant,
    ast.List,
    ast.Tuple,
    ast.Set,
    ast.Dict,
    ast.Subscript,
    ast.Slice,
    ast.Attribute,
    ast.Call,
    ast.keyword,
    ast.Lambda,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
    ast.comprehension,
    ast.IfExp,
    ast.BoolOp,
    ast.BinOp,
    ast.UnaryOp,
    ast.Compare,
    ast.JoinedStr,
    ast.FormattedValue,
    ast.Starred,
    ast.Load,
    ast.Store,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.LShift,
    ast.RShift,
    ast.BitOr,
    ast.BitXor,
    ast.BitAnd,
    ast.Invert,
    ast.Not,
    ast.UAdd,
    ast.USub,
    ast.And,
    ast.Or,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.Is,
    ast.IsNot,
    ast.In,
    ast.NotIn,
}


def _fail(category: str, case: int | None = None, *, line: int | None = None) -> None:
    suffix = "" if case is None else f":case={case}"
    if line is not None:
        suffix += f":line={line}"
    raise APIError(400, f"authoring_check:{category}{suffix}")


def _size(value: str, category: str, limit: int, case: int | None = None) -> int:
    if not isinstance(value, str):
        _fail(category, case)
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError:
        _fail(category, case)
    if size > limit:
        _fail(category, case)
    return size


def _path(node: ast.AST) -> tuple[str, ...] | None:
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, ast.Attribute):
        base = _path(node.value)
        if base:
            return (*base, node.attr)
    return None


class _SourceGuard(ast.NodeVisitor):
    """Every executable syntax node, callable and attribute must be explicitly allowed."""

    def __init__(self, tree: ast.Module, category: str):
        self.category = category
        self.line = 1
        self.parents = {
            child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)
        }
        self.imports: dict[str, tuple[str, ...]] = {}
        self.functions: set[str] = set()
        for node in ast.walk(tree):
            self.line = getattr(node, "lineno", self.line)
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                self._register_import(node)
            elif isinstance(node, ast.FunctionDef):
                self._name(node.name)
                if node.name in self.functions or node.name in BUILTINS:
                    self.reject()
                self.functions.add(node.name)
        if self.functions & self.imports.keys():
            collision = next(
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef) and node.name in self.imports
            )
            self.reject(collision)
        self.protected = BUILTINS | self.functions | self.imports.keys()
        # Module-level draws need an explicit unconditional seed. Random(seed)
        # instances keep their own state and cannot seed the module singleton.
        self.module_seeded = any(
            isinstance(node, ast.Expr)
            and self._seed_call(node.value)
            and self._origin(node.value.func) == ("random", "seed")
            for node in tree.body
        )
        self.line = 1

    def reject(self, node=None):
        _fail(self.category + "_unsafe_source", line=max(1, getattr(node, "lineno", self.line)))

    def visit(self, node):
        previous = self.line
        self.line = getattr(node, "lineno", previous)
        try:
            return super().visit(node)
        finally:
            self.line = previous

    def _name(self, name):
        if "__" in name or name in FORBIDDEN:
            self.reject()

    def _register_import(self, node):
        if isinstance(node, ast.ImportFrom) and (node.level or node.module not in MODULE_CALLS):
            self.reject()
        for alias in node.names:
            if isinstance(node, ast.Import):
                origin = (alias.name,)
                valid = alias.name in MODULE_CALLS
            else:
                origin = (node.module, alias.name)
                valid = alias.name in MODULE_CALLS[node.module] | MODULE_VALUES.get(
                    node.module, set()
                )
            name = alias.asname or alias.name
            self._name(name)
            if (
                not valid
                or name in BUILTINS
                or (name in self.imports and self.imports[name] != origin)
            ):
                self.reject()
            self.imports[name] = origin

    def _origin(self, node):
        path = _path(node)
        if path and path[0] in self.imports:
            return (*self.imports[path[0]], *path[1:])
        return None

    def _seed_call(self, node):
        if not isinstance(node, ast.Call) or self._origin(node.func) not in {
            ("random", "seed"),
            ("random", "Random"),
        }:
            return False
        return (
            len(node.args) == 1
            and not node.keywords
            and isinstance(node.args[0], ast.Constant)
            and type(node.args[0].value) is int
        )

    def generic_visit(self, node):
        if type(node) not in SAFE_NODES:
            self.reject()
        super().generic_visit(node)

    def visit_Name(self, node):
        self._name(node.id)
        if isinstance(node.ctx, ast.Store) and node.id in self.protected:
            self.reject()
        origin = self.imports.get(node.id)
        parent = self.parents.get(node)
        if origin and len(origin) == 1:
            # Do not turn modules into untracked variable/argument aliases.
            if not isinstance(parent, ast.Attribute) or parent.value is not node:
                self.reject()
        elif origin and origin[0] == "random":
            if not isinstance(parent, ast.Call) or parent.func is not node:
                self.reject()

    def visit_arg(self, node):
        self._name(node.arg)
        if node.arg in self.protected:
            self.reject()
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        if node.decorator_list:
            self.reject()
        self.generic_visit(node)

    def visit_ExceptHandler(self, node):
        if node.name:
            self._name(node.name)
            if node.name in self.protected:
                self.reject()
        self.generic_visit(node)

    def visit_Global(self, node):
        for name in node.names:
            self._name(name)
            if name in self.protected:
                self.reject()

    visit_Nonlocal = visit_Global

    def visit_Attribute(self, node):
        self._name(node.attr)
        if not isinstance(node.ctx, ast.Load):
            self.reject()
        origin = self._origin(node)
        if origin:
            allowed = (
                len(origin) == 2
                and origin[1] in (MODULE_CALLS[origin[0]] | MODULE_VALUES.get(origin[0], set()))
            ) or origin in STREAM_CALLS | STREAM_BUFFERS
            if not allowed:
                self.reject()
            parent = self.parents.get(node)
            if origin in STREAM_BUFFERS:
                if (
                    not isinstance(parent, ast.Attribute)
                    or self._origin(parent) not in STREAM_CALLS
                ):
                    self.reject()
            elif origin in STREAM_CALLS:
                if not isinstance(parent, ast.Call) or parent.func is not node:
                    self.reject()
            if origin[0] == "random":
                if not isinstance(parent, ast.Call) or parent.func is not node:
                    self.reject()
        elif node.attr not in METHODS or isinstance(node.value, ast.Attribute):
            self.reject()
        self.generic_visit(node)

    def visit_Call(self, node):
        origin = self._origin(node.func)
        if origin:
            permitted = (
                len(origin) == 2 and origin[1] in MODULE_CALLS[origin[0]]
            ) or origin in STREAM_CALLS
            if not permitted:
                self.reject()
            if origin[0] == "random":
                if origin[1] in {"seed", "Random"} and not self._seed_call(node):
                    self.reject()
                if origin[1] not in {"seed", "Random"} and not self.module_seeded:
                    _fail(self.category + "_random_seed_scope", line=max(1, self.line))
        elif isinstance(node.func, ast.Name):
            if node.func.id not in BUILTINS | self.functions:
                self.reject()
        elif not isinstance(node.func, ast.Attribute) or node.func.attr not in METHODS:
            self.reject()
        self.generic_visit(node)


def _validate_source(source: str, category: str) -> None:
    _size(source, category + "_source_size", SOURCE_LIMIT)
    if not source.strip():
        _fail(category + "_source_missing")
    try:
        tree = ast.parse(source)
        _SourceGuard(tree, category).visit(tree)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        _fail(category + "_source_syntax")


def _normalize_generated_entrypoint(source: str) -> str:
    """Replace only the conventional final ``__main__`` guard with its safe call.

    Models strongly prefer emitting this harmless boilerplate even when the prompt
    forbids dunder names.  The execution sandbox still rejects every other dunder
    use and validates the rewritten source from scratch; this narrow normalization
    therefore improves generation reliability without widening the allowed language.
    """

    if not isinstance(source, str) or "__main__" not in source or "__name__" not in source:
        return source
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return source
    if not tree.body or not isinstance(tree.body[-1], ast.If):
        return source
    guard = tree.body[-1]
    test = guard.test
    if (
        guard.orelse
        or len(guard.body) != 1
        or not isinstance(guard.body[0], ast.Expr)
        or not isinstance(guard.body[0].value, ast.Call)
        or guard.body[0].value.args
        or guard.body[0].value.keywords
        or not isinstance(guard.body[0].value.func, ast.Name)
        or not isinstance(test, ast.Compare)
        or len(test.ops) != 1
        or not isinstance(test.ops[0], ast.Eq)
        or len(test.comparators) != 1
    ):
        return source
    left, right = test.left, test.comparators[0]
    conventional = (
        isinstance(left, ast.Name)
        and left.id == "__name__"
        and isinstance(right, ast.Constant)
        and right.value == "__main__"
    ) or (
        isinstance(right, ast.Name)
        and right.id == "__name__"
        and isinstance(left, ast.Constant)
        and left.value == "__main__"
    )
    function_names = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    called = guard.body[0].value.func.id
    if not conventional or called not in function_names:
        return source
    tree.body[-1] = guard.body[0]
    ast.fix_missing_locations(tree)
    return ast.unparse(tree) + "\n"


def _normalize_generated_placeholder(source: str) -> str:
    """Rename only the harmless exact ``__`` placeholder used by some models.

    The source guard intentionally rejects every identifier containing a double
    underscore.  Models nevertheless commonly use the exact name ``__`` as an
    unused loop target after being asked to avoid dunder access.  Renaming that
    one identifier to a collision-free ordinary name preserves program meaning;
    attributes, imports, function names, and names such as ``__builtins__`` are
    untouched and therefore remain rejected by the guard.
    """

    if not isinstance(source, str) or "__" not in source:
        return source
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return source
    identifiers = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
        node.arg for node in ast.walk(tree) if isinstance(node, ast.arg)
    }
    if "__" not in identifiers:
        return source
    replacement = "_oj_unused"
    while replacement in identifiers:
        replacement += "_"

    class RenameExactPlaceholder(ast.NodeTransformer):
        def visit_Name(self, node):
            if node.id == "__":
                node.id = replacement
            return node

        def visit_arg(self, node):
            if node.arg == "__":
                node.arg = replacement
            return node

    RenameExactPlaceholder().visit(tree)
    ast.fix_missing_locations(tree)
    return ast.unparse(tree) + "\n"


def _normalize_generated_source(source: str) -> str:
    """Apply only the two audited, semantics-preserving model normalizations."""

    return _normalize_generated_placeholder(_normalize_generated_entrypoint(source))


async def _execute(source: str, stdin: str, category: str, case: int | None = None) -> str:
    try:
        with tempfile.TemporaryDirectory(prefix="oj-authoring-") as temporary:
            directory = Path(temporary)
            path = directory / "program.py"
            path.write_text(source, encoding="utf-8")
            result = await run_command(
                [sys.executable, str(path)],
                directory,
                stdin,
                GENERATOR_SECONDS if category == "generator" else REFERENCE_SECONDS,
                MEMORY_LIMIT,
                OUTPUT_LIMIT,
            )
    except (OSError, UnicodeError):
        _fail(category + "_execution", case)
    if result.reason != "ok" or result.returncode != 0:
        reason = result.reason if result.reason in {"timeout", "memory", "output"} else "execution"
        _fail(category + "_" + reason, case)
    return result.stdout


def _generator_inputs(stdout: str) -> list[str]:
    _size(stdout, "generator_output_size", OUTPUT_LIMIT)
    try:
        values = json.loads(stdout)
    except (ValueError, RecursionError):
        _fail("generator_json")
    if not isinstance(values, list) or len(values) > GENERATED_LIMIT:
        _fail("generator_inputs")
    for index, value in enumerate(values, 1):
        _size(value, "generator_input_size", INPUT_LIMIT, index)
    return values


async def check_generated(problem: dict, progress: Callable[[str], None]) -> dict:
    """Check literal/sample answers, construct generated answers, then return for human review."""
    result = deepcopy(problem)
    try:
        result.update(validate_problem(problem))
    except APIError:
        _fail("problem_schema")
    reference = _normalize_generated_source(problem.get("reference_solution"))
    generator = problem.get("test_generator")
    if generator is not None:
        generator = _normalize_generated_source(generator)
    result["reference_solution"] = reference
    if generator is not None:
        result["test_generator"] = generator
    progress("正在静态检查参考解与测试数据生成器")
    _validate_source(reference, "reference")
    if generator is not None:
        _validate_source(generator, "generator")

    cases = result["testcases"]
    present = {(case["input"], normalize_output(case["output"])) for case in cases}
    for sample in result["samples"]:
        identity = (sample["input"], normalize_output(sample["output"]))
        if identity not in present:
            cases.append(deepcopy(sample))
            present.add(identity)
    literal_count = len(cases)
    if literal_count > CASE_LIMIT:
        _fail("case_limit")
    for index, case in enumerate(cases, 1):
        _size(case["input"], "input_size", INPUT_LIMIT, index)
        _size(case["output"], "answer_size", OUTPUT_LIMIT, index)

    generated = []
    if generator is not None:
        progress("正在执行测试数据生成器（第 1 次）")
        generated = _generator_inputs(await _execute(generator, "", "generator"))
        progress("正在复跑测试数据生成器并检查确定性（第 2 次）")
        repeated = _generator_inputs(await _execute(generator, "", "generator"))
        if generated != repeated:
            _fail("generator_nondeterministic")
    if literal_count + len(generated) > CASE_LIMIT:
        _fail("case_limit")
    cases.extend({"input": value, "output": None} for value in generated)
    output_bytes = sum(len(value.encode("utf-8")) for value in generated)
    if output_bytes > OUTPUT_LIMIT:
        _fail("combined_output_size")
    for index, case in enumerate(cases, 1):
        progress(f"正在校验参考解与答案（{index}/{len(cases)}）")
        answer = await _execute(reference, case["input"], "reference", index)
        output_bytes += _size(answer, "reference_output_size", OUTPUT_LIMIT, index)
        if output_bytes > OUTPUT_LIMIT:
            _fail("combined_output_size", index)
        if index <= literal_count:
            if normalize_output(answer) != normalize_output(case["output"]):
                _fail("answer_mismatch", index)
        else:
            case["output"] = answer
    try:
        validate_problem(result)
    except APIError:
        _fail("generated_problem_schema")
    result["quality"] = {
        "reference_checked": True,
        "checked_cases": len(cases),
        "generated_cases": len(generated),
        "note": "已检查参考解与答案一致性及生成数据重复运行的一致性；不构成数学正确性证明，仍需人工审阅题意、算法和覆盖范围。",
    }
    progress("参考解与答案一致性检查完成，等待人工审阅")
    return result


async def materialize_literal_answers(problem: dict, progress: Callable[[str], None]) -> dict:
    """Replace only literal answers with output from an already-safe reference.

    AI providers occasionally return a coherent statement and reference program
    but miscalculate one or more handwritten answers.  This narrow recovery path
    does not alter the statement, inputs, limits, reference, or generator.  It
    validates the reference with the same allowlist, executes it under the same
    limits, synchronizes duplicate sample/test inputs, and leaves the caller to
    run ``check_generated`` again from scratch.
    """

    result = deepcopy(problem)
    try:
        result.update(validate_problem(problem))
    except APIError:
        _fail("problem_schema")
    reference = _normalize_generated_source(problem.get("reference_solution"))
    result["reference_solution"] = reference
    _validate_source(reference, "reference")

    progress("正在用安全参考解重新计算字面测试答案")
    answers: dict[str, str] = {}
    output_bytes = 0
    ordinal = 0
    for collection in (result["testcases"], result["samples"]):
        for case in collection:
            ordinal += 1
            stdin = case["input"]
            _size(stdin, "input_size", INPUT_LIMIT, ordinal)
            if stdin not in answers:
                answer = await _execute(reference, stdin, "reference", ordinal)
                output_bytes += _size(answer, "reference_output_size", OUTPUT_LIMIT, ordinal)
                if output_bytes > OUTPUT_LIMIT:
                    _fail("combined_output_size", ordinal)
                answers[stdin] = answer
            case["output"] = answers[stdin]

    disclosure = (
        "系统一致性回退：模型连续未能正确手算字面测例，系统已在受限环境中使用"
        "参考解重新生成其答案并将再次执行完整校验；题意与算法正确性仍需人工审阅。"
    )
    existing = str(result.get("validation_notes") or "").strip()
    available = max(0, 100_000 - len(disclosure) - 1)
    result["validation_notes"] = f"{existing[:available]} {disclosure}".strip()
    return result


async def discard_one_unexecutable_testcase(problem: dict, progress: Callable[[str], None]) -> dict:
    """Remove one malformed hidden literal case after bounded provider retries.

    This recovery is deliberately narrower than accepting a broken reference:
    every visible sample must execute, at most one distinct hidden testcase input
    may raise a normal reference execution error, and at least three distinct
    executable hidden inputs must remain.  The caller still runs
    :func:`check_generated` from scratch, so answers, the generator, limits and
    the complete saved problem contract remain subject to the ordinary gate.
    """

    result = deepcopy(problem)
    try:
        result.update(validate_problem(problem))
    except APIError:
        _fail("problem_schema")
    reference = _normalize_generated_source(problem.get("reference_solution"))
    result["reference_solution"] = reference
    _validate_source(reference, "reference")

    progress("正在隔离单个无法执行的隐藏字面测例")
    executed: set[str] = set()
    output_bytes = 0

    async def require_executable(stdin: str, ordinal: int) -> None:
        nonlocal output_bytes
        _size(stdin, "input_size", INPUT_LIMIT, ordinal)
        if stdin in executed:
            return
        answer = await _execute(reference, stdin, "reference", ordinal)
        output_bytes += _size(answer, "reference_output_size", OUTPUT_LIMIT, ordinal)
        if output_bytes > OUTPUT_LIMIT:
            _fail("combined_output_size", ordinal)
        executed.add(stdin)

    ordinal = 0
    for sample in result["samples"]:
        ordinal += 1
        # A visible sample is part of the statement contract and is never dropped.
        await require_executable(sample["input"], ordinal)

    rejected: set[str] = set()
    for case in result["testcases"]:
        ordinal += 1
        try:
            await require_executable(case["input"], ordinal)
        except APIError as error:
            category = error.message.removeprefix("authoring_check:").split(":", 1)[0]
            if category != "reference_execution":
                raise
            rejected.add(case["input"])
            if len(rejected) > 1:
                _fail("reference_recovery_limit")

    if len(rejected) != 1:
        _fail("reference_recovery_unavailable")
    result["testcases"] = [case for case in result["testcases"] if case["input"] not in rejected]
    if len({case["input"] for case in result["testcases"]}) < 3:
        _fail("reference_recovery_insufficient_cases")
    if result.get("test_generator") is not None:
        inputs = []
        for case in result["testcases"]:
            if case["input"] not in inputs:
                inputs.append(case["input"])
            if len(inputs) == 8:
                break
        while True:
            source = (
                "import json\n"
                f"inputs = {json.dumps(inputs, ensure_ascii=True)}\n"
                "print(json.dumps(inputs))\n"
            )
            if len(source.encode("utf-8")) <= 32_000 or not inputs:
                break
            inputs.pop()
        result["test_generator"] = source
        generator_note = (
            "系统安全回退：隔离畸形隐藏测例后，测试生成器已改为重放保留的"
            "正式输入；压力覆盖需在入库前人工复查。"
        )
        existing_generator = str(result.get("test_generation_notes") or "").strip()
        result["test_generation_notes"] = f"{existing_generator} {generator_note}".strip()
    try:
        validate_problem(result)
    except APIError:
        _fail("generated_problem_schema")

    disclosure = (
        "系统一致性回退：模型连续生成了一个会使其参考解异常的隐藏字面测例；"
        "系统已剔除该单个测例并将重新执行完整校验。可见样例未修改，题意、算法"
        "正确性与压力覆盖仍需人工审阅。"
    )
    existing = str(result.get("validation_notes") or "").strip()
    available = max(0, 100_000 - len(disclosure) - 1)
    result["validation_notes"] = f"{existing[:available]} {disclosure}".strip()
    return result
