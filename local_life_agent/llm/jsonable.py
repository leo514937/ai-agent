from __future__ import annotations

from dataclasses import is_dataclass, asdict
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel


def to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, BaseModel):
        try:
            return to_jsonable(value.model_dump())
        except Exception:
            return {}
    if is_dataclass(value) and not isinstance(value, type):
        try:
            return to_jsonable(asdict(cast(Any, value)))
        except Exception:
            return {}
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_jsonable(item) for item in value]
    if hasattr(value, "to_dict") and callable(getattr(value, "to_dict")):
        try:
            return to_jsonable(cast(Any, value).to_dict())
        except Exception:
            return str(value)
    if hasattr(value, "model_dump") and callable(getattr(value, "model_dump")):
        try:
            dumped = cast(Any, value).model_dump()
            return to_jsonable(dumped)
        except Exception:
            return str(value)
    if hasattr(value, "__dict__"):
        data = getattr(value, "__dict__", {})
        if isinstance(data, dict):
            return {str(key): to_jsonable(item) for key, item in data.items() if not str(key).startswith("_")}
    return str(value)
