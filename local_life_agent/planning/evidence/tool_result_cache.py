from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        if isinstance(dumped, dict):
            return dumped
    if isinstance(value, set):
        return sorted(str(item) for item in value)
    return str(value)


def _canonical_payload(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=_json_default)


def _make_cache_key(payload: Any) -> str:
    return hashlib.sha256(_canonical_payload(payload).encode("utf-8")).hexdigest()


@dataclass
class ToolResultCacheRecord:
    cache_key: str
    fingerprint: str
    payload: dict[str, Any]


class ToolResultCache:
    """Run-level tool result cache keyed by shop/facet/query scope."""

    def __init__(self) -> None:
        self._store: dict[str, ToolResultCacheRecord] = {}

    @staticmethod
    def fingerprint(payload: Any) -> str:
        return _make_cache_key(payload)

    @staticmethod
    def make_payload(*, tool_name: str, shop_id: str = "", facet: str = "", query_scope: dict[str, Any] | None = None, args: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "tool_name": str(tool_name or ""),
            "shop_id": str(shop_id or ""),
            "facet": str(facet or ""),
            "query_scope": dict(query_scope or {}),
            "args": dict(args or {}),
        }

    def get(self, payload: Any) -> ToolResultCacheRecord | None:
        fingerprint = self.fingerprint(payload)
        return self._store.get(fingerprint)

    def set(self, payload: Any, result: dict[str, Any]) -> ToolResultCacheRecord:
        fingerprint = self.fingerprint(payload)
        record = ToolResultCacheRecord(cache_key=fingerprint[:16], fingerprint=fingerprint, payload=dict(result))
        self._store[fingerprint] = record
        return record

    def get_or_build(self, payload: Any, builder: Callable[[], dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
        record = self.get(payload)
        if record is not None:
            result = dict(record.payload)
            result["tool_result_cache_hit"] = True
            result["tool_result_cache_key"] = record.cache_key
            return result, {"cache_hit": True, "cache_key": record.cache_key}

        result = dict(builder())
        record = self.set(payload, result)
        result["tool_result_cache_hit"] = False
        result["tool_result_cache_key"] = record.cache_key
        return result, {"cache_hit": False, "cache_key": record.cache_key}
