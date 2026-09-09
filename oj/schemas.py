"""Strict input contracts; validation never includes input values in errors."""

import math
import re

from oj.common import APIError

ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")


def text_field(value, field, *, minimum=1, maximum=200_000):
    if not isinstance(value, str) or not minimum <= len(value) <= maximum:
        raise APIError(400, f"Invalid {field}")
    if minimum and not value.strip():
        raise APIError(400, f"Invalid {field}")
    return value


def identifier(value, field="id"):
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise APIError(400, f"Invalid {field}")
    return value


def positive_limit(value, field, *, integer=False):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise APIError(400, f"Invalid {field}")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite or value <= 0 or (integer and not isinstance(value, int)):
        raise APIError(400, f"Invalid {field}")
    return value


def validate_problem(value):
    if not isinstance(value, dict):
        raise APIError(400, "Problem must be an object")
    result = {"id": identifier(value.get("id"))}
    for key in ("title", "description", "input_description", "output_description", "constraints"):
        result[key] = text_field(value.get(key), key)
    for key in ("hint", "source", "author", "difficulty"):
        result[key] = text_field(value.get(key, ""), key, minimum=0)
    tags = value.get("tags", [])
    if not isinstance(tags, list) or len(tags) > 50:
        raise APIError(400, "Invalid tags")
    result["tags"] = [text_field(tag, "tag", maximum=100) for tag in tags]
    for key in ("samples", "testcases"):
        cases = value.get(key)
        if not isinstance(cases, list) or not 1 <= len(cases) <= 200:
            raise APIError(400, f"Invalid {key}")
        result[key] = []
        for case in cases:
            if not isinstance(case, dict):
                raise APIError(400, f"Invalid {key}")
            result[key].append(
                {
                    name: text_field(case.get(name), name, minimum=0, maximum=1_000_000)
                    for name in ("input", "output")
                }
            )
    result["time_limit"] = positive_limit(value.get("time_limit"), "time_limit")
    result["memory_limit"] = positive_limit(value.get("memory_limit"), "memory_limit", integer=True)
    return result


def pagination(query):
    page, size = query.get("page"), query.get("page_size")
    if page is not None and size is None:
        raise APIError(400, "page_size is required with page")
    if size is None:
        return None
    try:
        page, size = int(page or "1"), int(size)
    except (ValueError, TypeError):
        raise APIError(400, "Invalid pagination") from None
    if page < 1 or size < 1:
        raise APIError(400, "Invalid pagination")
    return (page - 1) * size, size


def paginate(items, limits):
    if limits is None:
        return items
    offset, size = limits
    return items[offset : offset + size]
