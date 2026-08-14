from __future__ import annotations

import re
from typing import Any

# Delimiters intentionally exclude a bare slash so names such as TCP/IP stay intact.
_PROTOCOL_SPLIT_RE = re.compile(r"(?:\r?\n|[,;|+]|\s+/\s+)")
_PROTOCOL_ORDER = ["TCP", "UDP", "RS232", "RS422", "RS485", "DDS"]
_PROTOCOL_ORDER_MAP = {name.lower(): index for index, name in enumerate(_PROTOCOL_ORDER)}


def split_protocols(value: Any) -> list[str]:
    values: list[Any]
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        values = [value]

    seen: set[str] = set()
    result: list[str] = []
    for item in values:
        if item is None:
            continue
        parts = _PROTOCOL_SPLIT_RE.split(str(item))
        for part in parts:
            text = str(part or "").strip()
            if not text or text == "-":
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            result.append(text)
    fixed = [item for item in result if item.lower() in _PROTOCOL_ORDER_MAP]
    custom = [item for item in result if item.lower() not in _PROTOCOL_ORDER_MAP]
    fixed.sort(key=lambda item: _PROTOCOL_ORDER_MAP[item.lower()])
    return fixed + custom


def normalize_protocol_string(value: Any) -> str | None:
    values = split_protocols(value)
    return ", ".join(values) if values else None
