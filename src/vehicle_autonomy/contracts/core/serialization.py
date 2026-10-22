"""Deterministic conversion of immutable contract values to JSON primitives."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
import math


def to_json_value(value: object) -> object:
    """Return JSON-native values, rejecting unsupported or non-finite data."""

    if isinstance(value, Enum):
        return to_json_value(value.value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON contracts reject NaN and infinity")
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("JSON datetime must be timezone-aware")
        utc = value.astimezone(timezone.utc).isoformat()
        return utc[:-6] + "Z" if utc.endswith("+00:00") else utc
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("JSON object keys must be strings")
        return {key: to_json_value(value[key]) for key in sorted(value)}
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: to_json_value(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, (tuple, list)):
        return [to_json_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        raise TypeError("sets are not JSON values")
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")
