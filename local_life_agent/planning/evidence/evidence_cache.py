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


def normalize_cache_scope(scope: Any) -> str:
    if scope is None:
        return "global"
    if isinstance(scope, str):
        return scope.strip() or "global"
    if isinstance(scope, dict):
        items = {str(key): str(val) for key, val in sorted(scope.items()) if str(val).strip()}
        return _canonical_payload(items)
    return str(scope)


def fingerprint_payload(payload: Any) -> str:
    raw = _canonical_payload(payload)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class EvidenceCacheRecord:
    cache_scope: str
    cache_key: str
    fingerprint: str
    payload: dict[str, Any]


class EvidenceCache:
    """Small in-memory cache with explicit scope boundaries."""

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], EvidenceCacheRecord] = {}

    def make_key(self, scope: Any, payload: Any) -> EvidenceCacheRecord:
        cache_scope = normalize_cache_scope(scope)
        fingerprint = fingerprint_payload(payload)
        cache_key = f"{cache_scope}:{fingerprint[:16]}"
        return EvidenceCacheRecord(cache_scope=cache_scope, cache_key=cache_key, fingerprint=fingerprint, payload={})

    def get(self, scope: Any, payload: Any) -> EvidenceCacheRecord | None:
        key = self.make_key(scope, payload)
        return self._store.get((key.cache_scope, key.fingerprint))

    def set(self, scope: Any, payload: Any, result: dict[str, Any]) -> EvidenceCacheRecord:
        key = self.make_key(scope, payload)
        record = EvidenceCacheRecord(cache_scope=key.cache_scope, cache_key=key.cache_key, fingerprint=key.fingerprint, payload=dict(result))
        self._store[(record.cache_scope, record.fingerprint)] = record
        return record

    def get_or_build(self, scope: Any, payload: Any, builder: Callable[[], dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
        record = self.get(scope, payload)
        if record is not None:
            result = dict(record.payload)
            result["evidence_cache_hit"] = True
            result["evidence_cache_key"] = record.cache_key
            result["evidence_cache_scope"] = record.cache_scope
            return result, {
                "cache_hit": True,
                "cache_key": record.cache_key,
                "cache_scope": record.cache_scope,
                "cache_fingerprint": record.fingerprint,
            }

        result = dict(builder())
        record = self.set(scope, payload, result)
        result["evidence_cache_hit"] = False
        result["evidence_cache_key"] = record.cache_key
        result["evidence_cache_scope"] = record.cache_scope
        return result, {
            "cache_hit": False,
            "cache_key": record.cache_key,
            "cache_scope": record.cache_scope,
            "cache_fingerprint": record.fingerprint,
        }


_DEFAULT_EVIDENCE_CACHE = EvidenceCache()


def get_default_evidence_cache() -> EvidenceCache:
    return _DEFAULT_EVIDENCE_CACHE
