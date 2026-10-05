"""Tiny dotted-path resolver for Tool.response_extract (app/schemas/tool.py).
Supports "a.b", "a.b[0]", and a wildcard "a[*].b" that collects a value from
every element of a list. Deliberately not a JSONPath library — the syntax an
agent-tool response needs is this small, and it keeps the self-host story
dependency-free the way app/services/knowledge.py does.
"""

import re
from typing import Any

_SEGMENT = re.compile(r"([^.\[\]]+)|\[(\*|\d+)\]")


def _tokenize(path: str) -> list[tuple[str, str | int]]:
    """Turns "a.b[0].c[*]" into [("key","a"), ("key","b"), ("index",0),
    ("key","c"), ("wildcard","*")]."""
    tokens: list[tuple[str, str | int]] = []
    for match in _SEGMENT.finditer(path):
        key, bracket = match.groups()
        if key is not None:
            tokens.append(("key", key))
        elif bracket == "*":
            tokens.append(("wildcard", "*"))
        else:
            tokens.append(("index", int(bracket)))
    return tokens


def _get(value: Any, tokens: list[tuple[str, str | int]]) -> Any:
    if not tokens:
        return value
    kind, tok = tokens[0]
    rest = tokens[1:]
    if kind == "key":
        if not isinstance(value, dict) or tok not in value:
            return None
        return _get(value[tok], rest)
    if kind == "index":
        if not isinstance(value, list) or not (-len(value) <= tok < len(value)):
            return None
        return _get(value[tok], rest)
    # wildcard: collect this remaining path from every element of a list
    if not isinstance(value, list):
        return None
    return [_get(item, rest) for item in value]


def extract_path(data: Any, path: str) -> Any:
    """Returns None if any segment along the path is missing — a Tool's
    response_extract entry should describe an optional field, not assume
    the response always has the exact shape it was configured against."""
    return _get(data, _tokenize(path))
