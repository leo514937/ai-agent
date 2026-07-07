"""Shared serialization helpers for domain and state contracts."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any


def to_plain_dict(value: Any) -> dict[str, Any]:
    """Convert common Python / Pydantic / dataclass objects into a plain dict."""

    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if is_dataclass(value):
        try:
            dumped = asdict(value)
            return dumped if isinstance(dumped, dict) else {}
        except Exception:
            return {}
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        if isinstance(dumped, dict):
            return dumped
    dict_method = getattr(value, "dict", None)
    if callable(dict_method):
        dumped = dict_method()
        if isinstance(dumped, dict):
            return dumped
    try:
        return dict(value)
    except Exception:
        return {}


def to_plain_list(value: Any) -> list[Any]:
    """Convert common list-like values into a plain list."""

    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, (tuple, set)):
        return list(value)
    if isinstance(value, dict):
        return [dict(value)]
    if is_dataclass(value):
        try:
            return [asdict(value)]
        except Exception:
            return []
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        if isinstance(dumped, list):
            return list(dumped)
        if isinstance(dumped, (tuple, set)):
            return list(dumped)
        if isinstance(dumped, dict):
            return [dumped]
        return [dumped]
    return [value]
