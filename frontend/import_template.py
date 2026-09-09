"""Deterministic downloadable example for ``OJ Problem Archive v1``."""

from __future__ import annotations

from io import BytesIO
import json
import zipfile


def native_problem_template() -> bytes:
    """Return a small, parseable bilingual archive without runtime data."""

    fields = ("description", "input_description", "output_description", "constraints", "hint")
    manifest = {
        "schema": "oj.problem-archive.v1",
        "problem": {
            "id": "MY-PROBLEM-001",
            "title": "两数之和",
            "title_en": "A + B",
            "source": "原创",
            "author": "你的名字",
            "difficulty": "入门",
            "tags": ["输入输出", "整数"],
        },
        "judge": {"type": "standard", "time_limit": 1.0, "memory_limit": 128},
        "statements": {
            locale: {field: f"statements/{locale}/{field}.md" for field in fields}
            for locale in ("zh-CN", "en")
        },
        "samples": [{"input": "data/sample/1.in", "output": "data/sample/1.out"}],
        "testcases": [{"input": "data/secret/1.in", "output": "data/secret/1.out"}],
    }
    entries = {
        "problem.json": json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        "statements/zh-CN/description.md": "计算两个整数的和。\n",
        "statements/zh-CN/input_description.md": "一行两个整数 `a b`。\n",
        "statements/zh-CN/output_description.md": "输出 `a + b`。\n",
        "statements/zh-CN/constraints.md": "`-10^9 <= a, b <= 10^9`\n",
        "statements/zh-CN/hint.md": "读取两个整数后相加。\n",
        "statements/en/description.md": "Add two integers.\n",
        "statements/en/input_description.md": "One line with two integers `a b`.\n",
        "statements/en/output_description.md": "Print `a + b`.\n",
        "statements/en/constraints.md": "`-10^9 <= a, b <= 10^9`\n",
        "statements/en/hint.md": "Read both integers and add them.\n",
        "data/sample/1.in": "1 2\n",
        "data/sample/1.out": "3\n",
        "data/secret/1.in": "-7 12\n",
        "data/secret/1.out": "5\n",
    }
    target = BytesIO()
    with zipfile.ZipFile(target, "w") as archive:
        for name in sorted(entries):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, entries[name].encode("utf-8"))
    return target.getvalue()
