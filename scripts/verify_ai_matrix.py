"""Opt-in, repeatable live acceptance matrix for DeepSeek problem authoring.

The command is deliberately inert unless ``--live`` is present.  A live run
uses a fresh run id, creates independent durable authoring sessions, observes
their real stage/percentage transitions, and writes only redacted summaries to
``runtime``.  Generated statements, reference solutions and hidden tests are
never persisted by this verifier.
"""

from __future__ import annotations

import argparse
import bisect
from collections import deque
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import time
from typing import Any, Callable
import uuid

import httpx

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admintestpassword"
EXPECTED_PROVIDER = "https://api.deepseek.com"
EXPECTED_MODEL = "deepseek-v4-flash"
EXPECTED_DIFFICULTIES = {
    "luogu.1": "入门",
    "luogu.2": "普及-",
    "luogu.3": "普及",
    "luogu.4": "普及+/提高-",
    "luogu.5": "提高",
    "luogu.6": "提高+/省选-",
    "luogu.7": "省选/NOI-",
    "luogu.8": "NOI/NOI+/CTS",
}
ACTIVE_STATUSES = {"pending", "running"}
TERMINAL_STATUSES = {"completed", "failed", "cancelled", "service_restarted"}
RETRYABLE_HTTP_STATUSES = {502, 503, 504}
EVIDENCE_FIELDS = {
    "case_id",
    "category",
    "difficulty",
    "task_id",
    "session_id",
    "status",
    "elapsed_seconds",
    "progress_trace",
    "usage_summary",
    "error_code",
    "result_digest",
}

DEADLOCK_REQUIREMENT = (
    "多线程死锁检测：设计一道与多线程资源竞争有关的题目。"
    "给出若干线程获取锁的先后关系，要求判断这些线程是否可能发生死锁。"
    "题目不依赖真实线程运行，预期将锁的依赖关系转换为有向图，"
    "并使用拓扑排序或环检测算法完成判断。"
)


def _case(case_id, category, difficulty, knowledge, requirement):
    return {
        "case_id": case_id,
        "category": category,
        "difficulty": difficulty,
        "knowledge_point_ids": tuple(knowledge),
        "requirement": requirement,
    }


# The first three entries intentionally repeat the user's exact original
# wording.  They remain separate cases and receive separate session/task ids.
CASES = (
    *(
        _case(
            f"deadlock.repeat-{index}",
            "deadlock",
            "luogu.4",
            ("engineering.deadlock", "graph.cycle-directed"),
            DEADLOCK_REQUIREMENT,
        )
        for index in range(1, 4)
    ),
    _case(
        "matrix.input-output",
        "input-output",
        "luogu.1",
        ("language.input-output", "language.numeric-types"),
        "设计一道标准输入输出入门题：读入若干整数，按题目定义输出总和与最大值。"
        "输入数量和整数范围必须明确，并覆盖只有一个数、负数和零。",
    ),
    _case(
        "matrix.strings",
        "strings",
        "luogu.2",
        ("string.parsing", "string.frequency"),
        "设计一道字符串规范化与频次统计题。输入含大小写字母和空格，"
        "明确空行、大小写处理和并列时的输出顺序。",
    ),
    _case(
        "matrix.arrays",
        "arrays",
        "luogu.3",
        ("linear.array", "programming.sliding-window"),
        "设计一道数组连续区间题：在给定约束下求满足条件的最短连续子数组。"
        "覆盖无解、单元素即满足和答案位于边界。",
    ),
    _case(
        "matrix.sorting",
        "sorting",
        "luogu.3",
        ("sort.custom-order", "sort.stability"),
        "设计一道记录排序题，要求按多关键字排序并保留完全相同关键字记录的输入顺序。"
        "题面必须明确稳定性和并列规则。",
    ),
    _case(
        "matrix.binary-search",
        "binary-search",
        "luogu.3",
        ("search.binary", "search.lower-upper-bound"),
        "设计一道在非降序数组中查询目标值首次和末次出现位置的题。"
        "覆盖重复值、目标不存在、首尾位置和空查询集合。",
    ),
    _case(
        "matrix.stack",
        "stack",
        "luogu.2",
        ("linear.stack", "string.parentheses"),
        "设计一道多种括号序列合法性判断题，并要求输出首个不匹配位置。"
        "明确空串、提前闭合与最终仍有未闭合括号的规则。",
    ),
    _case(
        "matrix.queue",
        "queue",
        "luogu.2",
        ("linear.queue", "programming.simulation"),
        "设计一道服务窗口排队模拟题，按到达顺序处理入队、服务和查询操作。"
        "明确同一时刻事件顺序以及空队列操作。",
    ),
    _case(
        "matrix.graph",
        "graph",
        "luogu.4",
        ("graph.representation", "graph.connected-components"),
        "设计一道无向图连通分量统计题，同时输出每个分量的最小编号。"
        "覆盖孤立点、重边、不连通图和只有一个顶点。",
    ),
    _case(
        "matrix.bfs",
        "bfs",
        "luogu.3",
        ("graph.bfs", "graph.shortest-unweighted"),
        "设计一道网格最短路题，只允许上下左右移动并避开障碍。"
        "明确起点等于终点、不可达和多条最短路时的输出。",
    ),
    _case(
        "matrix.dfs",
        "dfs",
        "luogu.3",
        ("graph.dfs", "graph.flood-fill"),
        "设计一道网格区域计数题，使用深度优先搜索或洪水填充。"
        "明确四连通定义，覆盖全空、全满与边界相接区域。",
    ),
    _case(
        "matrix.greedy",
        "greedy",
        "luogu.4",
        ("greedy.interval", "greedy.exchange"),
        "设计一道选择最多互不冲突闭开区间的贪心题。"
        "明确端点相接是否冲突，并包含能击败按开始时间选择的测例。",
    ),
    _case(
        "matrix.dynamic-programming",
        "dynamic-programming",
        "luogu.4",
        ("dp.knapsack-01", "dp.state-design"),
        "设计一道零一背包变体题，在容量限制内最大化收益，且每件物品最多选择一次。"
        "覆盖零容量、单件物品和多种方案同收益。",
    ),
    _case(
        "matrix.mathematics",
        "mathematics",
        "luogu.2",
        ("math.gcd", "math.euclidean"),
        "设计一道基于最大公约数的整数题。输入多组正整数，输出约分后的结果。"
        "明确范围，覆盖相等、互质和一个数整除另一个数。",
    ),
    _case(
        "matrix.simulation",
        "simulation",
        "luogu.3",
        ("programming.simulation", "programming.state-machine"),
        "设计一道电梯运行过程模拟题，根据指令更新楼层和状态。"
        "明确越界指令、同层请求和指令先后顺序。",
    ),
    _case(
        "matrix.boundaries",
        "boundary-cases",
        "luogu.3",
        ("engineering.boundaries", "engineering.overflow"),
        "设计一道大整数区间统计题，重点考查最小边界、最大边界和溢出规避。"
        "Python参考解仍需说明其他固定宽度语言的安全计算顺序。",
    ),
    _case(
        "matrix.grid-dp",
        "dynamic-programming",
        "luogu.5",
        ("dp.grid", "dp.transition"),
        "设计一道带障碍和权值的网格动态规划题，只能向右或向下移动并求最优值。"
        "覆盖起终点障碍、不可达、负权与只有一行或一列。",
    ),
)


@dataclass(frozen=True)
class SemanticOracle:
    """Independent, deterministic semantics for one matrix problem family."""

    contract: str
    terms: tuple[tuple[str, ...], ...]
    solve: Callable[[str], str]
    typical_wrong: Callable[[str], str]


def _integer_tokens(raw: str) -> list[int]:
    tokens = raw.split()
    if not tokens or any(re.fullmatch(r"[+-]?\d+", token) is None for token in tokens):
        raise ValueError("expected integer tokens")
    return [int(token) for token in tokens]


def _directed_deadlock(raw: str, *, undirected: bool = False) -> str:
    values = _integer_tokens(raw)
    if len(values) < 2:
        raise ValueError("missing graph header")
    n, m = values[:2]
    if n < 1 or m < 0 or len(values) != 2 + 2 * m:
        raise ValueError("invalid graph shape")
    edges = list(zip(values[2::2], values[3::2]))
    if any(not 1 <= endpoint <= n for edge in edges for endpoint in edge):
        raise ValueError("invalid vertex")
    if undirected:
        parent = list(range(n + 1))

        def find(value):
            while parent[value] != value:
                parent[value] = parent[parent[value]]
                value = parent[value]
            return value

        for left, right in edges:
            left_root, right_root = find(left), find(right)
            if left_root == right_root:
                return "YES"
            parent[left_root] = right_root
        return "NO"
    adjacency = [[] for _ in range(n)]
    indegree = [0] * n
    for left, right in edges:
        adjacency[left - 1].append(right - 1)
        indegree[right - 1] += 1
    pending = deque(index for index, degree in enumerate(indegree) if degree == 0)
    visited = 0
    while pending:
        node = pending.popleft()
        visited += 1
        for neighbour in adjacency[node]:
            indegree[neighbour] -= 1
            if indegree[neighbour] == 0:
                pending.append(neighbour)
    return "YES" if visited != n else "NO"


def _input_output(raw: str, *, wrong: bool = False) -> str:
    values = _integer_tokens(raw)
    n, numbers = values[0], values[1:]
    if n < 1 or len(numbers) != n:
        raise ValueError("invalid sequence")
    extreme = min(numbers) if wrong else max(numbers)
    return f"{sum(numbers)}\n{extreme}"


def _string_frequency(raw: str, *, wrong: bool = False) -> str:
    value = raw.rstrip("\r\n")
    if "\n" in value or "\r" in value or re.fullmatch(r"[A-Za-z ]*", value) is None:
        raise ValueError("invalid text")
    normalized = value.replace(" ", "")
    if not wrong:
        normalized = normalized.lower()
    if not normalized:
        return "EMPTY\nEMPTY 0"
    counts = {character: normalized.count(character) for character in set(normalized)}
    best = min(counts, key=lambda character: (-counts[character], character))
    return f"{normalized}\n{best} {counts[best]}"


def _shortest_subarray(raw: str, *, wrong: bool = False) -> str:
    values = _integer_tokens(raw)
    if len(values) < 2:
        raise ValueError("missing array header")
    n, target, *numbers = values
    if n < 1 or target < 1 or len(numbers) != n or any(value < 0 for value in numbers):
        raise ValueError("invalid array")
    if wrong:
        return str(n if sum(numbers) >= target else 0)
    best = n + 1
    left = 0
    total = 0
    for right, value in enumerate(numbers):
        total += value
        while total >= target:
            best = min(best, right - left + 1)
            total -= numbers[left]
            left += 1
    return "0" if best == n + 1 else str(best)


def _record_sort(raw: str, *, wrong: bool = False) -> str:
    lines = raw.strip().splitlines()
    if not lines or re.fullmatch(r"\d+", lines[0].strip()) is None:
        raise ValueError("missing record count")
    n = int(lines[0])
    if n < 1 or len(lines) != n + 1:
        raise ValueError("invalid records")
    records = []
    for ordinal, line in enumerate(lines[1:]):
        fields = line.split()
        if len(fields) != 3 or any(re.fullmatch(r"[+-]?\d+", item) is None for item in fields[1:]):
            raise ValueError("invalid record")
        records.append((fields[0], int(fields[1]), int(fields[2]), ordinal))
    if wrong:
        ordered = sorted(records, key=lambda item: item[1])
    else:
        ordered = sorted(records, key=lambda item: (item[1], -item[2]))
    return "\n".join(item[0] for item in ordered)


def _binary_positions(raw: str, *, wrong: bool = False) -> str:
    values = _integer_tokens(raw)
    if len(values) < 2:
        raise ValueError("missing query header")
    n, q = values[:2]
    if n < 1 or q < 1 or len(values) != 2 + n + q:
        raise ValueError("invalid queries")
    numbers = values[2 : 2 + n]
    if numbers != sorted(numbers):
        raise ValueError("unsorted input")
    answers = []
    for target in values[2 + n :]:
        left = bisect.bisect_left(numbers, target)
        right = bisect.bisect_right(numbers, target) - 1
        if left == n or numbers[left] != target:
            answers.append("-1 -1")
        else:
            offset = 0 if wrong else 1
            answers.append(f"{left + offset} {right + offset}")
    return "\n".join(answers)


def _bracket_match(raw: str, *, wrong: bool = False) -> str:
    value = raw.strip()
    if re.fullmatch(r"[()\[\]{}]*", value) is None:
        raise ValueError("invalid brackets")
    if wrong:
        balance = 0
        for index, character in enumerate(value, start=1):
            balance += 1 if character in "([{" else -1
            if balance < 0:
                return f"NO\n{index}"
        return "YES" if balance == 0 else f"NO\n{len(value) + 1}"
    pairs = {")": "(", "]": "[", "}": "{"}
    stack = []
    for index, character in enumerate(value, start=1):
        if character in "([{":
            stack.append((character, index))
        elif not stack or stack[-1][0] != pairs[character]:
            return f"NO\n{index}"
        else:
            stack.pop()
    return f"NO\n{stack[0][1]}" if stack else "YES"


def _queue_simulation(raw: str, *, wrong: bool = False) -> str:
    lines = [line.strip() for line in raw.strip().splitlines()]
    if not lines or re.fullmatch(r"\d+", lines[0]) is None:
        raise ValueError("missing operation count")
    count = int(lines[0])
    if count < 1 or len(lines) != count + 1:
        raise ValueError("invalid operations")
    waiting = deque()
    output = []
    for line in lines[1:]:
        fields = line.split()
        if len(fields) == 2 and fields[0] == "IN" and re.fullmatch(r"[A-Za-z0-9_]+", fields[1]):
            waiting.append(fields[1])
        elif fields == ["OUT"]:
            if waiting:
                waiting.pop() if wrong else waiting.popleft()
            else:
                output.append("EMPTY")
        elif fields == ["FRONT"]:
            output.append((waiting[-1] if wrong else waiting[0]) if waiting else "EMPTY")
        else:
            raise ValueError("invalid operation")
    return "\n".join(output)


def _components(raw: str, *, wrong: bool = False) -> str:
    values = _integer_tokens(raw)
    if len(values) < 2:
        raise ValueError("missing graph header")
    n, m = values[:2]
    if n < 1 or m < 0 or len(values) != 2 + 2 * m:
        raise ValueError("invalid graph")
    adjacency = [[] for _ in range(n + 1)]
    active = set()
    for left, right in zip(values[2::2], values[3::2]):
        if not 1 <= left <= n or not 1 <= right <= n:
            raise ValueError("invalid vertex")
        adjacency[left].append(right)
        adjacency[right].append(left)
        active.update((left, right))
    vertices = sorted(active) if wrong else list(range(1, n + 1))
    visited, minima = set(), []
    for start in vertices:
        if start in visited:
            continue
        stack = [start]
        visited.add(start)
        component = []
        while stack:
            node = stack.pop()
            component.append(node)
            for neighbour in adjacency[node]:
                if neighbour not in visited:
                    visited.add(neighbour)
                    stack.append(neighbour)
        minima.append(min(component))
    return f"{len(minima)}\n{' '.join(map(str, minima))}"


def _parse_grid(raw: str, allowed: str) -> tuple[int, int, list[str]]:
    lines = raw.strip().splitlines()
    if not lines:
        raise ValueError("missing grid")
    header = lines[0].split()
    if len(header) != 2 or any(re.fullmatch(r"\d+", item) is None for item in header):
        raise ValueError("invalid grid header")
    rows, columns = map(int, header)
    grid = lines[1:]
    if rows < 1 or columns < 1 or len(grid) != rows or any(len(row) != columns for row in grid):
        raise ValueError("invalid grid shape")
    if any(character not in allowed for row in grid for character in row):
        raise ValueError("invalid grid cell")
    return rows, columns, grid


def _grid_shortest(raw: str, *, wrong: bool = False) -> str:
    rows, columns, grid = _parse_grid(raw, ".#ST")
    starts = [(r, c) for r in range(rows) for c in range(columns) if grid[r][c] == "S"]
    targets = [(r, c) for r in range(rows) for c in range(columns) if grid[r][c] == "T"]
    if len(starts) != 1 or len(targets) != 1:
        raise ValueError("invalid endpoints")
    start, target = starts[0], targets[0]
    if wrong:
        return str(abs(start[0] - target[0]) + abs(start[1] - target[1]))
    pending = deque([(start[0], start[1], 0)])
    visited = {start}
    while pending:
        row, column, distance = pending.popleft()
        if (row, column) == target:
            return str(distance)
        for next_row, next_column in (
            (row - 1, column),
            (row + 1, column),
            (row, column - 1),
            (row, column + 1),
        ):
            if (
                0 <= next_row < rows
                and 0 <= next_column < columns
                and grid[next_row][next_column] != "#"
                and (next_row, next_column) not in visited
            ):
                visited.add((next_row, next_column))
                pending.append((next_row, next_column, distance + 1))
    return "-1"


def _regions(raw: str, *, wrong: bool = False) -> str:
    rows, columns, grid = _parse_grid(raw, "01")
    directions = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    if wrong:
        directions += [(-1, -1), (-1, 1), (1, -1), (1, 1)]
    visited, count = set(), 0
    for row in range(rows):
        for column in range(columns):
            if grid[row][column] != "1" or (row, column) in visited:
                continue
            count += 1
            stack = [(row, column)]
            visited.add((row, column))
            while stack:
                current_row, current_column = stack.pop()
                for row_delta, column_delta in directions:
                    next_cell = current_row + row_delta, current_column + column_delta
                    if (
                        0 <= next_cell[0] < rows
                        and 0 <= next_cell[1] < columns
                        and grid[next_cell[0]][next_cell[1]] == "1"
                        and next_cell not in visited
                    ):
                        visited.add(next_cell)
                        stack.append(next_cell)
    return str(count)


def _interval_schedule(raw: str, *, wrong: bool = False) -> str:
    values = _integer_tokens(raw)
    n, endpoints = values[0], values[1:]
    if n < 1 or len(endpoints) != 2 * n:
        raise ValueError("invalid intervals")
    intervals = list(zip(endpoints[::2], endpoints[1::2]))
    if any(left >= right for left, right in intervals):
        raise ValueError("invalid interval")
    ordered = sorted(intervals, key=(lambda item: item[0]) if wrong else (lambda item: item[1]))
    chosen = 0
    end = -math.inf
    for left, right in ordered:
        if left >= end:
            chosen += 1
            end = right
    return str(chosen)


def _knapsack(raw: str, *, wrong: bool = False) -> str:
    values = _integer_tokens(raw)
    if len(values) < 2:
        raise ValueError("missing knapsack header")
    n, capacity, *items = values
    if n < 1 or capacity < 0 or len(items) != 2 * n:
        raise ValueError("invalid knapsack")
    pairs = list(zip(items[::2], items[1::2]))
    if any(weight <= 0 for weight, _ in pairs):
        raise ValueError("invalid weight")
    if n * max(1, capacity) > 5_000_000:
        raise ValueError("oracle work bound exceeded")
    best = [0] * (capacity + 1)
    for weight, value in pairs:
        positions = range(weight, capacity + 1) if wrong else range(capacity, weight - 1, -1)
        for current in positions:
            best[current] = max(best[current], best[current - weight] + value)
    return str(best[capacity])


def _reduce_pairs(raw: str, *, wrong: bool = False) -> str:
    values = _integer_tokens(raw)
    count, pairs = values[0], values[1:]
    if count < 1 or len(pairs) != 2 * count or any(value <= 0 for value in pairs):
        raise ValueError("invalid positive pairs")
    output = []
    for left, right in zip(pairs[::2], pairs[1::2]):
        divisor = math.gcd(left, right)
        output.append(str(divisor) if wrong else f"{left // divisor} {right // divisor}")
    return "\n".join(output)


def _elevator(raw: str, *, wrong: bool = False) -> str:
    lines = [line.strip() for line in raw.strip().splitlines()]
    if not lines:
        raise ValueError("missing elevator header")
    header = _integer_tokens(lines[0])
    if len(header) == 3:
        floors, current, count = header
        operations = lines[1:]
    elif len(header) == 2 and len(lines) >= 2 and re.fullmatch(r"[+-]?\d+", lines[1]) is not None:
        floors, current = header
        count = int(lines[1])
        operations = lines[2:]
    else:
        raise ValueError("invalid elevator header")
    if floors < 1 or not 1 <= current <= floors or count < 1 or len(operations) != count:
        raise ValueError("invalid elevator state")
    output = []
    for line in operations:
        fields = line.split()
        if (
            len(fields) != 2
            or fields[0] not in {"UP", "DOWN", "GOTO"}
            or re.fullmatch(r"[+-]?\d+", fields[1]) is None
        ):
            raise ValueError("invalid elevator command")
        operation, target_text = fields
        target = int(target_text)
        if wrong:
            current = min(floors, max(1, target))
        elif operation == "UP" and target > 0 and current + target <= floors:
            current += target
        elif operation == "DOWN" and target > 0 and current - target >= 1:
            current -= target
        elif operation == "GOTO" and 1 <= target <= floors and target != current:
            current = target
        output.append(str(current))
    return "\n".join(output)


def _divisible_interval(raw: str, *, wrong: bool = False) -> str:
    values = _integer_tokens(raw)
    if len(values) != 2 or values[0] > values[1]:
        raise ValueError("invalid interval")
    left, right = values
    if wrong:
        return str((right - left) // 3)
    return str(right // 3 - (left - 1) // 3)


def _weighted_grid(raw: str, *, wrong: bool = False) -> str:
    lines = [line.strip() for line in raw.strip().splitlines()]
    if not lines:
        raise ValueError("missing weighted grid")
    header = _integer_tokens(lines[0])
    if len(header) != 2:
        raise ValueError("invalid weighted grid header")
    rows, columns = header
    if rows < 1 or columns < 1 or len(lines) != rows + 1:
        raise ValueError("invalid weighted grid shape")
    grid = []
    for line in lines[1:]:
        tokens = line.split()
        if len(tokens) != columns:
            raise ValueError("invalid weighted row")
        row = []
        for token in tokens:
            if token == "X":
                row.append(None)
            elif re.fullmatch(r"[+-]?\d+", token):
                row.append(int(token))
            else:
                raise ValueError("invalid weighted cell")
        grid.append(row)
    choose = min if wrong else max
    unreachable = None
    best = [[unreachable] * columns for _ in range(rows)]
    if grid[0][0] is not None:
        best[0][0] = grid[0][0]
    for row in range(rows):
        for column in range(columns):
            if grid[row][column] is None or (row == 0 and column == 0):
                continue
            candidates = []
            if row and best[row - 1][column] is not None:
                candidates.append(best[row - 1][column])
            if column and best[row][column - 1] is not None:
                candidates.append(best[row][column - 1])
            if candidates:
                best[row][column] = choose(candidates) + grid[row][column]
    result = best[-1][-1]
    return "IMPOSSIBLE" if result is None else str(result)


def _oracle(contract, terms, solve, wrong) -> SemanticOracle:
    return SemanticOracle(contract, terms, solve, wrong)


ORACLES = {
    "deadlock": _oracle(
        "输入第一行为 n m，随后 m 行为线程等待依赖有向边 u v；存在有向环输出 YES，否则输出 NO。",
        (("有向", "directed"), ("环", "cycle"), ("yes",), ("no",)),
        _directed_deadlock,
        lambda raw: _directed_deadlock(raw, undirected=True),
    ),
    "input-output": _oracle(
        "输入 n 及恰好 n 个整数；第一行输出总和，第二行输出最大值。",
        (("总和", "sum"), ("最大", "maximum")),
        _input_output,
        lambda raw: _input_output(raw, wrong=True),
    ),
    "strings": _oracle(
        "输入一行仅含大小写字母和空格；删除空格并转小写。第一行输出规范化串（空串为 EMPTY），第二行输出最高频字符和次数，并列取字典序最小；空串的第二行固定输出 EMPTY 0。",
        (
            ("小写", "lowercase"),
            ("空格", "space"),
            ("频", "frequen"),
            ("并列", "字典序", "tie"),
        ),
        _string_frequency,
        lambda raw: _string_frequency(raw, wrong=True),
    ),
    "arrays": _oracle(
        "输入 n S 及 n 个非负整数，其中 n >= 1 且 S >= 1；输出元素和至少为 S 的最短非空连续子数组长度，无解输出 0。",
        (
            ("最短", "shortest"),
            ("连续", "contiguous"),
            ("无解", "不存在", "输出 0", "no solution"),
        ),
        _shortest_subarray,
        lambda raw: _shortest_subarray(raw, wrong=True),
    ),
    "sorting": _oracle(
        "输入 n >= 1，随后 n 行为 name 和两个整数 k1 k2；按 k1 升序、k2 降序稳定排序，逐行输出 name。",
        (
            ("升序", "ascending"),
            ("降序", "descending"),
            ("稳定", "输入顺序", "stable"),
        ),
        _record_sort,
        lambda raw: _record_sort(raw, wrong=True),
    ),
    "binary-search": _oracle(
        "输入 n q（均至少为 1）、n 个非降序整数及 q 个查询；每个查询输出目标首次和末次出现的 1-based 位置，不存在输出 -1 -1。",
        (("首次", "first"), ("末次", "last"), ("1-based", "从 1"), ("-1",)),
        _binary_positions,
        lambda raw: _binary_positions(raw, wrong=True),
    ),
    "stack": _oracle(
        "输入一行括号串；合法时仅输出一行 YES。否则第一行输出 NO，第二行输出首个类型不匹配的右括号位置；若最终未闭合，第二行输出最早未闭合左括号位置（均 1-based）。",
        (("括号", "bracket"), ("位置", "position"), ("1-based", "从 1")),
        _bracket_match,
        lambda raw: _bracket_match(raw, wrong=True),
    ),
    "queue": _oracle(
        "输入 q >= 1 个操作：IN x 入队且不输出；OUT 在非空时移除队首且不输出，"
        "为空时输出 EMPTY；FRONT 输出队首，为空时输出 EMPTY；严格先进先出。",
        (
            ("先进先出", "fifo", "队尾", "end of the queue"),
            ("empty", "空队列"),
            ("front", "队首"),
        ),
        _queue_simulation,
        lambda raw: _queue_simulation(raw, wrong=True),
    ),
    "graph": _oracle(
        "输入 n m 及 m 条无向边；输出连通分量数，下一行升序输出每个分量的最小顶点编号，孤立点也算分量。",
        (("无向", "undirected"), ("孤立", "isolated"), ("最小", "minimum")),
        _components,
        lambda raw: _components(raw, wrong=True),
    ),
    "bfs": _oracle(
        "输入 n m（n,m >= 1 且 n*m >= 2）和恰含一个 S、一个 T 及若干 .、# 的网格；"
        "S 与 T 是两个不同格子，只能四方向移动且不能穿越 #，输出 S 到 T 最短步数，"
        "不可达输出 -1；禁止 1x1 网格或缺少 S/T 的测例。",
        (
            ("四", "上下左右", "four"),
            ("最短", "shortest"),
            ("不可达", "unreachable"),
        ),
        _grid_shortest,
        lambda raw: _grid_shortest(raw, wrong=True),
    ),
    "dfs": _oracle(
        "输入 n m 和 01 网格；按上下左右四连通统计字符 1 的区域数。",
        (
            ("四连通", "上下左右", "4-connected", "four-connected"),
            ("区域", "region", "connected component", "island"),
        ),
        _regions,
        lambda raw: _regions(raw, wrong=True),
    ),
    "greedy": _oracle(
        "输入 n >= 1 个整数端点的左闭右开区间 [l,r)，每个区间 l < r；端点相接不冲突，输出最多可选区间数。",
        (("左闭右开", "[l,r)"), ("端点", "endpoint"), ("最多", "maximum")),
        _interval_schedule,
        lambda raw: _interval_schedule(raw, wrong=True),
    ),
    "dynamic-programming": _oracle(
        "输入 n >= 1、容量 C >= 0 及 n 件物品的正整数重量和整数收益；可不选物品，每件最多一次，输出总重量不超过 C 时的最大总收益。",
        (("最多一次", "at most once"), ("容量", "capacity"), ("最大", "maximum")),
        _knapsack,
        lambda raw: _knapsack(raw, wrong=True),
    ),
    "mathematics": _oracle(
        "输入 T >= 1 组正整数 a b；每行输出同时除以 gcd(a,b) 后的两个整数。",
        (("最大公约数", "gcd"), ("约分", "reduce", "除以")),
        _reduce_pairs,
        lambda raw: _reduce_pairs(raw, wrong=True),
    ),
    "simulation": _oracle(
        "输入 F start 和 q（q 可在首行或单独第二行），随后 q 条 UP x、DOWN x、GOTO x；"
        "越界、同层或方向错误指令忽略，每条指令后输出当前楼层。",
        (
            ("越界", "out of range", "within [1", "within 1.."),
            ("忽略", "ignore"),
            ("当前楼层", "current floor"),
        ),
        _elevator,
        lambda raw: _elevator(raw, wrong=True),
    ),
    "boundary-cases": _oracle(
        "输入可为负且绝对值至 10^18 的闭区间 l r；输出区间内能被 3 整除的整数个数。",
        (("10^18", "1018"), ("闭区间", "inclusive"), ("整除", "divisible")),
        _divisible_interval,
        lambda raw: _divisible_interval(raw, wrong=True),
    ),
    "grid-dp": _oracle(
        "输入 n m 及含整数或 X 障碍的网格；从左上到右下只向右或下，输出可达路径最大权值和，不可达输出 IMPOSSIBLE。",
        (
            ("向右", "right"),
            ("向下", "或下", "down"),
            ("最大", "maximum"),
            ("impossible", "不可达"),
        ),
        _weighted_grid,
        lambda raw: _weighted_grid(raw, wrong=True),
    ),
}

# Each input is small enough to place in the live request and is deliberately
# chosen so the corresponding ``typical_wrong`` implementation disagrees with
# the independent oracle.  Requiring it in the returned test suite turns the
# wrong-solution check into a reproducible coverage gate instead of hoping the
# model happens to invent a discriminator.
DISCRIMINATING_INPUTS = {
    "deadlock": "4 4\n1 2\n1 3\n2 4\n3 4\n",
    "input-output": "4\n-2 0 3 1\n",
    "strings": "Aa b\n",
    "arrays": "6 7\n2 3 1 2 4 3\n",
    "sorting": "4\na 1 2\nb 1 9\nc 0 1\nd 1 9\n",
    "binary-search": "5 3\n1 2 2 2 5\n2 1 4\n",
    "stack": "([)]\n",
    "queue": "5\nIN a\nIN b\nFRONT\nOUT\nOUT\n",
    "graph": "5 2\n1 2\n2 3\n",
    "bfs": "3 4\nS#T.\n....\n####\n",
    "dfs": "2 2\n10\n01\n",
    "greedy": "4\n1 10\n2 3\n3 4\n4 5\n",
    "dynamic-programming": "2 4\n3 5\n2 3\n",
    "mathematics": "2\n6 9\n5 5\n",
    "simulation": "5 3 4\nUP 5\nUP 2\nDOWN 1\nGOTO 8\n",
    "boundary-cases": "-3 3\n",
    "grid-dp": "2 3\n1 9 1\n2 1 8\n",
}


def _oracle_key(case: dict[str, Any]) -> str:
    return "grid-dp" if case["case_id"] == "matrix.grid-dp" else case["category"]


class VerificationError(RuntimeError):
    """Safe verifier failure carrying only a stable, non-secret code."""

    def __init__(self, code: str):
        self.code = _safe_code(code)
        super().__init__(self.code)


def _safe_code(value: Any) -> str:
    text = str(value or "verification_error").strip().lower().replace("-", "_")
    return text if re.fullmatch(r"[a-z0-9_:=]{1,120}", text) else "verification_error"


def _response_data(response: Any) -> Any:
    status = getattr(response, "status_code", None)
    if not isinstance(status, int):
        raise VerificationError("invalid_http_response")
    if status != 200:
        code = f"http_{status}"
        try:
            payload = response.json()
            data = payload.get("data") if isinstance(payload, dict) else None
            error_code = data.get("error_code") if isinstance(data, dict) else None
            if isinstance(error_code, str):
                code = error_code
        except (TypeError, ValueError, UnicodeError):
            pass
        raise VerificationError(code)
    try:
        payload = response.json()
    except (TypeError, ValueError, UnicodeError) as error:
        raise VerificationError("invalid_json_response") from error
    if (
        not isinstance(payload, dict)
        or payload.get("code") != 200
        or not isinstance(payload.get("msg"), str)
        or "data" not in payload
    ):
        raise VerificationError("invalid_api_envelope")
    return payload["data"]


def _request(client, method, path, *, payload=None, attempts=3):
    """Retry ambiguous transport/server failures without changing ``payload``."""

    if attempts < 1:
        raise ValueError("attempts must be positive")
    last_status = None
    for attempt in range(attempts):
        try:
            response = client.request(method, path, json=payload)
        except httpx.TransportError:
            if attempt + 1 == attempts:
                raise VerificationError("network_unavailable") from None
        else:
            last_status = response.status_code
            if response.status_code not in RETRYABLE_HTTP_STATUSES or attempt + 1 == attempts:
                return _response_data(response)
        if attempt + 1 < attempts:
            time.sleep(0.2)
    raise VerificationError(f"http_{last_status}" if last_status else "network_unavailable")


def _current_task(session: Any) -> dict[str, Any]:
    if not isinstance(session, dict):
        raise VerificationError("invalid_authoring_session")
    revision_number = session.get("current_revision")
    revisions = session.get("revisions")
    if not isinstance(revision_number, int) or not isinstance(revisions, list):
        raise VerificationError("invalid_authoring_session")
    matches = [
        item
        for item in revisions
        if isinstance(item, dict) and item.get("revision") == revision_number
    ]
    if len(matches) != 1 or not isinstance(matches[0].get("task"), dict):
        raise VerificationError("invalid_authoring_session")
    return matches[0]["task"]


def _stage(value: Any) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()[:120]
    if re.search(r"(?i)(?:sk-[a-z0-9]{8,}|bearer\s+|api[_ -]?key)", text):
        return "[redacted]"
    return text


def _progress_point(task: dict[str, Any], elapsed: float) -> dict[str, Any]:
    status = task.get("status")
    percent = task.get("progress_percent")
    if status not in ACTIVE_STATUSES | TERMINAL_STATUSES:
        raise VerificationError("invalid_task_status")
    if isinstance(percent, bool) or not isinstance(percent, int) or not 0 <= percent <= 100:
        raise VerificationError("invalid_progress_percent")
    if status == "completed" and percent != 100:
        raise VerificationError("invalid_completed_progress")
    return {
        "elapsed_seconds": round(max(0.0, elapsed), 3),
        "stage": _stage(task.get("progress")),
        "status": status,
        "percent": percent,
    }


def _usage_summary(task: dict[str, Any]) -> dict[str, Any]:
    usage = task.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    result = {}
    for key in ("input_tokens", "output_tokens", "total_tokens", "cost"):
        value = usage.get(key)
        if value is None or (isinstance(value, (int, float)) and not isinstance(value, bool)):
            result[key] = value
    currency = usage.get("currency")
    result["currency"] = currency[:16] if isinstance(currency, str) else None
    source = usage.get("source")
    result["source"] = source[:40] if isinstance(source, str) else None
    incomplete = usage.get("incomplete")
    result["incomplete"] = incomplete if isinstance(incomplete, bool) else None
    calls = task.get("provider_calls")
    result["provider_calls"] = (
        calls if isinstance(calls, int) and not isinstance(calls, bool) else None
    )
    return result


def _result_digest(result: dict[str, Any]) -> str:
    encoded = json.dumps(
        result,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalized_output(value: Any) -> str:
    if not isinstance(value, str):
        raise VerificationError("oracle_invalid_output_type")
    return "\n".join(line.rstrip() for line in value.strip().splitlines())


def _semantic_text(result: dict[str, Any]) -> str:
    values = [
        result.get("title"),
        result.get("description"),
        result.get("input_description"),
        result.get("output_description"),
        result.get("constraints"),
    ]
    translations = result.get("translations")
    english = translations.get("en") if isinstance(translations, dict) else None
    if isinstance(english, dict):
        values.extend(
            english.get(key)
            for key in (
                "title",
                "description",
                "input_description",
                "output_description",
                "constraints",
            )
        )
    return "\n".join(value for value in values if isinstance(value, str)).casefold()


def _validate_semantics(result: dict[str, Any], case: dict[str, Any]) -> None:
    """Validate outputs with an implementation independent from generated code."""

    oracle_id = _oracle_key(case)
    oracle = ORACLES.get(oracle_id)
    if oracle is None:
        raise VerificationError("missing_category_oracle")
    safe_id = oracle_id.replace("-", "_")
    statement = _semantic_text(result)
    for alternatives in oracle.terms:
        if not any(term.casefold() in statement for term in alternatives):
            raise VerificationError(f"oracle_{safe_id}_statement_drift")

    samples = result.get("samples")
    testcases = result.get("testcases")
    pairs = []
    for collection in (samples, testcases):
        for item in collection:
            if not isinstance(item, dict) or not isinstance(item.get("input"), str):
                raise VerificationError(f"oracle_{safe_id}_invalid_case")
            pairs.append((item["input"], item.get("output")))
    if len(testcases) < 3 or len({raw for raw, _ in pairs}) < 3:
        raise VerificationError(f"oracle_{safe_id}_insufficient_cases")
    if not any(
        test.get("input") not in {sample.get("input") for sample in samples}
        for test in testcases
        if isinstance(test, dict)
    ):
        raise VerificationError(f"oracle_{safe_id}_no_hidden_case")
    distinct_outputs = set()
    wrong_discriminated = False
    for raw_input, declared_output in pairs:
        try:
            expected = _normalized_output(oracle.solve(raw_input))
            wrong = _normalized_output(oracle.typical_wrong(raw_input))
        except (ArithmeticError, IndexError, TypeError, ValueError) as error:
            raise VerificationError(f"oracle_{safe_id}_invalid_input") from error
        actual = _normalized_output(declared_output)
        if actual != expected:
            raise VerificationError(f"oracle_{safe_id}_answer_mismatch")
        distinct_outputs.add(expected)
        wrong_discriminated = wrong_discriminated or wrong != expected
    if len(distinct_outputs) < 2:
        raise VerificationError(f"oracle_{safe_id}_no_output_diversity")
    if not wrong_discriminated:
        raise VerificationError(f"oracle_{safe_id}_wrong_solution_survives")


def _validate_result(
    result: Any,
    expected_problem_id: str,
    expected_difficulty: str,
    case: dict[str, Any],
) -> str:
    if not isinstance(result, dict):
        raise VerificationError("missing_consistency_checked_result")
    required = {
        "id",
        "title",
        "description",
        "input_description",
        "output_description",
        "constraints",
        "samples",
        "testcases",
        "time_limit",
        "memory_limit",
        "reference_solution",
        "test_generator",
        "validation_notes",
        "test_generation_notes",
        "translations",
    }
    if not required.issubset(result):
        raise VerificationError("incomplete_consistency_checked_result")
    if result.get("id") != expected_problem_id:
        raise VerificationError("unexpected_problem_id")
    if result.get("difficulty") != expected_difficulty:
        raise VerificationError("unexpected_problem_difficulty")
    if not isinstance(result.get("samples"), list) or not result["samples"]:
        raise VerificationError("invalid_result_samples")
    if not isinstance(result.get("testcases"), list) or not result["testcases"]:
        raise VerificationError("invalid_result_testcases")
    translations = result.get("translations")
    if not isinstance(translations, dict) or not isinstance(translations.get("en"), dict):
        raise VerificationError("invalid_result_translation")
    _validate_semantics(result, case)
    return _result_digest(result)


def _request_body(case: dict[str, Any], expected_problem_id: str) -> dict[str, Any]:
    oracle_id = _oracle_key(case)
    oracle = ORACLES[oracle_id]
    discriminator = json.dumps(DISCRIMINATING_INPUTS[oracle_id], ensure_ascii=False)
    return {
        "requirement": case["requirement"],
        "knowledge_point_ids": list(case["knowledge_point_ids"]),
        "difficulty_id": case["difficulty"],
        "free_prompt": (
            f"题目 id 必须精确使用 {expected_problem_id}。"
            "请生成完整中英双语题面、确定性测试生成器和可直接运行的 Python 参考解法，"
            "并确保题面、样例、测试数据与参考解法通过系统一致性校验。"
            f"为便于独立语义验收，必须严格采用以下 I/O 语义，不得自行改题：{oracle.contract}"
            "所有样例和正式测试点都必须满足上述输入合同；禁止把缺字段、越界值、缺少必需标记等畸形输入当作边界测试。"
            "正式测试点至少 3 个，且必须包含能区分常见错误算法的非样例数据。"
            f"testcases 必须包含与这个输入语义等价的测例，用于击败典型错解：{discriminator}。"
        ),
        "attachments": [],
        "reference_problem_id": None,
    }


def _blank_evidence(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "category": case["category"],
        "difficulty": case["difficulty"],
        "task_id": None,
        "session_id": None,
        "status": "not_started",
        "elapsed_seconds": 0.0,
        "progress_trace": [],
        "usage_summary": {},
        "error_code": None,
        "result_digest": None,
    }


def _write_evidence(path: Path, evidence: list[dict[str, Any]]) -> None:
    if any(set(item) != EVIDENCE_FIELDS for item in evidence):
        raise VerificationError("invalid_evidence_shape")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    temporary.replace(path)


class LiveMatrixVerifier:
    def __init__(
        self,
        client,
        *,
        run_id: str,
        evidence_path: Path,
        timeout_seconds: float = 239.0,
        poll_interval: float = 2.0,
        monotonic=time.monotonic,
        sleep=time.sleep,
    ):
        if not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise ValueError("run_id must be a UUID hex value")
        if not 0 < timeout_seconds < 240:
            raise ValueError("timeout_seconds must be below 240")
        if poll_interval < 0:
            raise ValueError("poll_interval must be non-negative")
        self.client = client
        self.run_id = run_id
        self.run_tag = run_id[:10]
        self.evidence_path = Path(evidence_path)
        self.timeout_seconds = float(timeout_seconds)
        self.poll_interval = float(poll_interval)
        self.monotonic = monotonic
        self.sleep = sleep
        self.evidence: list[dict[str, Any]] = []
        self.last_case_evidence: dict[str, Any] | None = None
        self.active_session_id: str | None = None
        self.seen_sessions: set[str] = set()
        self.seen_tasks: set[str] = set()

    def _guard_configuration(self) -> None:
        _request(
            self.client,
            "POST",
            "/api/auth/login",
            payload={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        )
        config = _request(self.client, "GET", "/api/ai/model-config")
        if not isinstance(config, dict):
            raise VerificationError("invalid_model_configuration")
        provider = str(config.get("provider_url") or "").rstrip("/")
        if provider != EXPECTED_PROVIDER:
            raise VerificationError("unexpected_provider")
        if config.get("model") != EXPECTED_MODEL:
            raise VerificationError("unexpected_model")
        if config.get("api_key_configured") is not True:
            raise VerificationError("api_key_not_configured")

    def _cancel_active(self) -> None:
        if self.active_session_id is None:
            return
        try:
            _request(
                self.client,
                "DELETE",
                f"/api/ai/authoring-sessions/{self.active_session_id}/active-task",
                attempts=1,
            )
        except VerificationError:
            pass
        finally:
            self.active_session_id = None

    def _run_case(self, case: dict[str, Any], ordinal: int) -> dict[str, Any]:
        evidence = _blank_evidence(case)
        self.last_case_evidence = evidence
        expected_problem_id = f"LIVE-{self.run_tag.upper()}-{ordinal:02d}"
        expected_difficulty = EXPECTED_DIFFICULTIES.get(case.get("difficulty"))
        if expected_difficulty is None:
            raise VerificationError("unknown_matrix_difficulty")
        idempotency_key = f"ai-matrix-{self.run_id}-{ordinal:02d}"
        payload = {
            "idempotency_key": idempotency_key,
            "request": _request_body(case, expected_problem_id),
        }
        started_at = self.monotonic()
        try:
            session = _request(
                self.client,
                "POST",
                "/api/ai/authoring-sessions/",
                payload=payload,
            )
            if not isinstance(session, dict):
                raise VerificationError("invalid_authoring_session")
            session_id = session.get("session_id")
            task = _current_task(session)
            task_id = task.get("task_id")
            if not isinstance(session_id, str) or not isinstance(task_id, str):
                raise VerificationError("invalid_authoring_identity")
            if session_id in self.seen_sessions or task_id in self.seen_tasks:
                raise VerificationError("reused_authoring_identity")
            self.seen_sessions.add(session_id)
            self.seen_tasks.add(task_id)
            self.active_session_id = session_id
            evidence["session_id"] = session_id
            evidence["task_id"] = task_id

            previous = None
            while True:
                elapsed = self.monotonic() - started_at
                point = _progress_point(task, elapsed)
                marker = (point["status"], point["percent"], point["stage"])
                if marker != previous:
                    evidence["progress_trace"].append(point)
                    previous = marker
                status = point["status"]
                if status == "completed":
                    if elapsed >= 240:
                        raise VerificationError("case_deadline_exceeded")
                    evidence["status"] = status
                    evidence["elapsed_seconds"] = round(elapsed, 3)
                    evidence["usage_summary"] = _usage_summary(task)
                    evidence["result_digest"] = _validate_result(
                        task.get("result"), expected_problem_id, expected_difficulty, case
                    )
                    self.active_session_id = None
                    self.last_case_evidence = evidence
                    return evidence
                if status in TERMINAL_STATUSES:
                    evidence["status"] = status
                    evidence["elapsed_seconds"] = round(elapsed, 3)
                    evidence["usage_summary"] = _usage_summary(task)
                    evidence["error_code"] = _safe_code(task.get("error_code") or status)
                    self.active_session_id = None
                    raise VerificationError(evidence["error_code"])
                if elapsed >= self.timeout_seconds:
                    raise VerificationError("case_timeout")
                if self.poll_interval:
                    self.sleep(self.poll_interval)
                session = _request(
                    self.client,
                    "GET",
                    f"/api/ai/authoring-sessions/{session_id}",
                )
                next_task = _current_task(session)
                if next_task.get("task_id") != task_id:
                    raise VerificationError("task_identity_changed")
                task = next_task
        except BaseException as error:
            elapsed = max(0.0, self.monotonic() - started_at)
            evidence["elapsed_seconds"] = round(elapsed, 3)
            if evidence["status"] == "completed":
                evidence["status"] = "failed_validation"
            elif evidence["status"] == "not_started":
                evidence["status"] = (
                    "interrupted" if isinstance(error, KeyboardInterrupt) else "failed"
                )
            if evidence["error_code"] is None:
                evidence["error_code"] = (
                    "keyboard_interrupt"
                    if isinstance(error, KeyboardInterrupt)
                    else error.code if isinstance(error, VerificationError) else "unexpected_error"
                )
            self._cancel_active()
            self.last_case_evidence = evidence
            raise

    def run(self, cases=CASES) -> list[dict[str, Any]]:
        self._guard_configuration()
        for ordinal, case in enumerate(cases, start=1):
            current = _blank_evidence(case)
            self.last_case_evidence = current
            try:
                current = self._run_case(case, ordinal)
            except BaseException:
                current = self.last_case_evidence or current
                self.evidence.append(current)
                _write_evidence(self.evidence_path, self.evidence)
                raise
            self.evidence.append(current)
            _write_evidence(self.evidence_path, self.evidence)
        return list(self.evidence)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run 19 real authoring sessions; without this flag no provider call is possible",
    )
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--evidence-dir", default="runtime")
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--timeout", type=float, default=239.0)
    return parser


def main(argv=None, *, client_factory=None) -> int:
    args = build_parser().parse_args(argv)
    if not args.live:
        print("No provider call made. Pass --live to run the acceptance matrix.")
        return 2
    run_id = uuid.uuid4().hex
    evidence_path = Path(args.evidence_dir) / f"ai-matrix-{run_id}.json"
    factory = client_factory or httpx.Client
    try:
        with factory(
            base_url=args.url,
            timeout=httpx.Timeout(15.0, connect=4.0),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            verifier = LiveMatrixVerifier(
                client,
                run_id=run_id,
                evidence_path=evidence_path,
                timeout_seconds=args.timeout,
                poll_interval=args.poll_interval,
            )
            verifier.run()
    except KeyboardInterrupt:
        print(f"Matrix interrupted; cancellation requested. Evidence: {evidence_path}")
        return 130
    except (VerificationError, httpx.HTTPError, OSError, ValueError):
        print(f"Matrix failed. Evidence: {evidence_path}")
        return 1
    print(f"Matrix completed: {len(CASES)} independent sessions. Evidence: {evidence_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
