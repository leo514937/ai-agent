"""Session persistence for the local life agent."""

from __future__ import annotations

import json
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from time import time
from typing import Any, Protocol, runtime_checkable

from .. import config
from ..domain.serialization import to_plain_dict
from ..domain.state import SessionState
from .policy import (
    SESSION_FIELD_PARTITION_MAP,
    SESSION_PARTITION_DEFAULT,
    partition_for_field,
    partitions,
    ttl_seconds_for_partition,
)


def _state_to_plain(state: SessionState | dict[str, Any] | None) -> dict[str, Any]:
    if state is None:
        return {}
    if isinstance(state, dict):
        return dict(state)
    model_dump = getattr(state, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        return dumped if isinstance(dumped, dict) else {}
    return to_plain_dict(state)


def _state_from_plain(payload: dict[str, Any] | SessionState | None) -> SessionState:
    if isinstance(payload, SessionState):
        return payload.model_copy(deep=True)
    if not payload:
        return SessionState()
    try:
        return SessionState.model_validate(payload)
    except Exception:
        return SessionState()


def _field_default(field_name: str) -> Any:
    field = SessionState.model_fields.get(field_name)
    if field is None:
        return None
    default_factory = getattr(field, "default_factory", None)
    if callable(default_factory):
        try:
            return default_factory()
        except Exception:
            return None
    if not field.is_required():
        return deepcopy(getattr(field, "default", None))
    return None


def _field_has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (str, bytes)):
        return bool(str(value).strip())
    if isinstance(value, dict):
        return bool(value)
    if isinstance(value, (list, tuple, set)):
        return len(value) > 0
    return True


def _state_partitions(state: SessionState | dict[str, Any] | None) -> dict[str, list[str]]:
    payload = _state_to_plain(state)
    partitions_map: dict[str, list[str]] = {}
    for field_name, value in payload.items():
        partition = partition_for_field(field_name)
        if _field_has_value(value):
            partitions_map.setdefault(partition, []).append(field_name)
    return partitions_map


def _session_key_prefix() -> str:
    return str(getattr(config, "SESSION_REDIS_KEY_PREFIX", "local_life:session") or "local_life:session")


def _redis_data_key(prefix: str, session_id: str) -> str:
    return f"{prefix}:{session_id}:data"


def _redis_meta_key(prefix: str, session_id: str) -> str:
    return f"{prefix}:{session_id}:meta"


def _redis_partition_key(prefix: str, partition: str, session_id: str) -> str:
    return f"{prefix}:{partition}:{session_id}"


def _decode_redis_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    return str(value)


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        if isinstance(dumped, dict):
            return dumped
        return dumped
    if isinstance(value, set):
        return sorted(str(item) for item in value)
    return str(value)


@runtime_checkable
class SessionStore(Protocol):
    def load(self, session_id: str) -> SessionState: ...

    def save(self, session_id: str, state: SessionState) -> None: ...

    def delete(self, session_id: str) -> None: ...

    def touch(self, session_id: str) -> None: ...

    def partition_ttl(self, partition: str) -> int: ...


@dataclass
class _StoredSession:
    state: SessionState = field(default_factory=SessionState)
    partition_expiries: dict[str, float] = field(default_factory=dict)


class InMemorySessionStore:
    """Simple in-memory session store with TTL metadata."""

    def __init__(self) -> None:
        self._sessions: dict[str, _StoredSession] = {}

    def _active_partition_expiries(self, state: SessionState | dict[str, Any], *, now: float | None = None) -> dict[str, float]:
        now = float(time() if now is None else now)
        expiries: dict[str, float] = {}
        for partition, field_names in _state_partitions(state).items():
            ttl = ttl_seconds_for_partition(partition)
            if ttl <= 0:
                continue
            expiries[partition] = now + float(ttl)
        return expiries

    def _prune_expired(self, session_id: str, stored: _StoredSession, *, now: float | None = None) -> SessionState:
        now = float(time() if now is None else now)
        state = stored.state.model_copy(deep=True)
        for partition, expiry in list(stored.partition_expiries.items()):
            if expiry > now:
                continue
            for field_name, field_partition in SESSION_FIELD_PARTITION_MAP.items():
                if field_partition == partition:
                    setattr(state, field_name, _field_default(field_name))
            stored.partition_expiries.pop(partition, None)
        stored.state = state
        self._sessions[session_id] = stored
        return state

    def load(self, session_id: str) -> SessionState:
        if not session_id:
            return SessionState()
        stored = self._sessions.get(session_id)
        if stored is None:
            return SessionState()
        return self._prune_expired(session_id, stored)

    def save(self, session_id: str, state: SessionState) -> None:
        if not session_id or state is None:
            return
        session_state = state.model_copy(deep=True) if hasattr(state, "model_copy") else _state_from_plain(state)
        self._sessions[session_id] = _StoredSession(
            state=session_state,
            partition_expiries=self._active_partition_expiries(session_state),
        )

    def delete(self, session_id: str) -> None:
        if not session_id:
            return
        self._sessions.pop(session_id, None)

    def clear(self, session_id: str) -> None:
        self.delete(session_id)

    def touch(self, session_id: str) -> None:
        if not session_id:
            return
        stored = self._sessions.get(session_id)
        if stored is None:
            return
        stored.partition_expiries = self._active_partition_expiries(stored.state)
        self._sessions[session_id] = stored

    def partition_ttl(self, partition: str) -> int:
        return ttl_seconds_for_partition(partition)

    def snapshot(self) -> dict[str, Any]:
        return {sid: record.state.model_copy(deep=True) for sid, record in self._sessions.items()}


class RedisSessionStore:
    """Redis-backed session store with Redis-native partition TTLs."""

    def __init__(
        self,
        client: Any,
        *,
        key_prefix: str | None = None,
        now_fn: Callable[[], float] | None = None,
    ) -> None:
        self.client = client
        self.key_prefix = key_prefix or _session_key_prefix()
        self._now_fn = now_fn or time

    @classmethod
    def create_from_config(cls) -> RedisSessionStore:
        import redis

        pool = redis.ConnectionPool.from_url(
            str(config.SESSION_REDIS_URL),
            decode_responses=True,
            max_connections=int(getattr(config, "SESSION_REDIS_MAX_CONNECTIONS", 10)),
            socket_timeout=float(getattr(config, "SESSION_REDIS_SOCKET_TIMEOUT_SECONDS", 2.0)),
            socket_connect_timeout=float(getattr(config, "SESSION_REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS", 2.0)),
        )
        client = redis.Redis(connection_pool=pool)
        client.ping()
        return cls(client, key_prefix=_session_key_prefix())

    def _now(self) -> float:
        return float(self._now_fn())

    def _data_key(self, session_id: str) -> str:
        return _redis_data_key(self.key_prefix, session_id)

    def _meta_key(self, session_id: str) -> str:
        return _redis_meta_key(self.key_prefix, session_id)

    def _partition_key(self, session_id: str, partition: str) -> str:
        return _redis_partition_key(self.key_prefix, partition, session_id)

    def _partition_payloads(self, payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        for field_name, value in payload.items():
            if not _field_has_value(value):
                continue
            partition = partition_for_field(field_name)
            grouped.setdefault(partition, {})[field_name] = value
        return grouped

    def _active_partition_expiries(self, state: SessionState | dict[str, Any], *, now: float | None = None) -> dict[str, float]:
        now = float(self._now() if now is None else now)
        expiries: dict[str, float] = {}
        for partition in _state_partitions(state):
            ttl = ttl_seconds_for_partition(partition)
            if ttl <= 0:
                continue
            expiries[partition] = now + float(ttl)
        return expiries

    def _read_expiries(self, session_id: str) -> dict[str, float]:
        raw = self.client.hgetall(self._meta_key(session_id)) or {}
        expiries: dict[str, float] = {}
        for partition in partitions():
            value = raw.get(partition)
            if value is None:
                continue
            try:
                expiries[partition] = float(value)
            except Exception:
                continue
        return expiries

    def _write_payload(self, session_id: str, payload: dict[str, Any], expiries: dict[str, float]) -> None:
        meta_key = self._meta_key(session_id)
        partition_payloads = self._partition_payloads(payload)
        active_partitions = set(partition_payloads)

        for partition in partitions():
            partition_key = self._partition_key(session_id, partition)
            partition_payload = partition_payloads.get(partition)
            if not partition_payload:
                self.client.delete(partition_key)
                continue
            json_payload = json.dumps(partition_payload, ensure_ascii=False, sort_keys=True, default=_json_default)
            self.client.set(partition_key, json_payload)
            ttl = ttl_seconds_for_partition(partition)
            if ttl > 0:
                self.client.expire(partition_key, ttl)

        # New writes use partition keys; remove the legacy whole-session key so
        # stale data cannot be used if all partition keys later expire.
        self.client.delete(self._data_key(session_id))
        if expiries:
            self.client.hset(meta_key, mapping={partition: str(expiry) for partition, expiry in expiries.items() if partition in active_partitions})
            ttl = max(ttl_seconds_for_partition(partition) for partition in active_partitions)
            if ttl > 0:
                self.client.expire(meta_key, ttl)
        else:
            self.client.delete(meta_key)

    def _prune_expired_fields(self, state: SessionState, expiries: dict[str, float]) -> SessionState:
        now = self._now()
        pruned = state.model_copy(deep=True)
        for partition, expiry in expiries.items():
            if expiry > now:
                continue
            for field_name, field_partition in SESSION_FIELD_PARTITION_MAP.items():
                if field_partition == partition:
                    setattr(pruned, field_name, _field_default(field_name))
        return pruned

    def load(self, session_id: str) -> SessionState:
        if not session_id:
            return SessionState()
        payload: dict[str, Any] = {}
        for partition in partitions():
            raw_partition = self.client.get(self._partition_key(session_id, partition))
            if not raw_partition:
                continue
            try:
                partition_payload = json.loads(raw_partition)
            except Exception:
                continue
            if isinstance(partition_payload, dict):
                payload.update(partition_payload)

        if not payload:
            raw = self.client.get(self._data_key(session_id))
            if not raw:
                return SessionState()
            try:
                payload = json.loads(raw)
            except Exception:
                return SessionState()
        state = _state_from_plain(payload)
        expiries = self._read_expiries(session_id)
        if expiries:
            state = self._prune_expired_fields(state, expiries)
        return state

    def save(self, session_id: str, state: SessionState) -> None:
        if not session_id or state is None:
            return
        session_state = state.model_copy(deep=True) if hasattr(state, "model_copy") else _state_from_plain(state)
        expiries = self._active_partition_expiries(session_state)
        self._write_payload(session_id, _state_to_plain(session_state), expiries)

    def delete(self, session_id: str) -> None:
        if not session_id:
            return
        keys = [self._data_key(session_id), self._meta_key(session_id)]
        keys.extend(self._partition_key(session_id, partition) for partition in partitions())
        self.client.delete(*keys)

    def clear(self, session_id: str) -> None:
        self.delete(session_id)

    def touch(self, session_id: str) -> None:
        if not session_id:
            return
        state = self.load(session_id)
        if state.model_dump() == SessionState().model_dump():
            return
        self.save(session_id, state)

    def partition_ttl(self, partition: str) -> int:
        return ttl_seconds_for_partition(partition)

    def snapshot(self) -> dict[str, SessionState]:
        result: dict[str, SessionState] = {}
        pattern = f"{self.key_prefix}:*"
        scan_iter = getattr(self.client, "scan_iter", None)
        if not callable(scan_iter):
            return result
        for key in scan_iter(match=pattern):
            key_text = _decode_redis_value(key)
            suffix = key_text[len(self.key_prefix) + 1 :] if key_text.startswith(f"{self.key_prefix}:") else ""
            partition, _, session_id = suffix.partition(":")
            if partition not in partitions() or not session_id:
                continue
            state = self.load(session_id)
            if state.model_dump() != SessionState().model_dump():
                result[session_id] = state
        return result


def _create_default_store() -> SessionStore:
    backend = str(getattr(config, "SESSION_STORE_BACKEND", "memory") or "memory").strip().lower()
    if backend in {"redis", "auto"}:
        try:
            return RedisSessionStore.create_from_config()
        except Exception:
            return InMemorySessionStore()
    return InMemorySessionStore()


_SESSION_STORE: SessionStore = _create_default_store()


def get_session_store() -> SessionStore:
    """Return the process-wide session store used by the graph runtime."""

    return _SESSION_STORE


def set_session_store(store: SessionStore) -> None:
    """Replace the process-wide session store. Useful for isolated tests."""

    global _SESSION_STORE
    _SESSION_STORE = store


def reset_session_store() -> None:
    """Reset the process-wide session store to a fresh instance."""

    set_session_store(_create_default_store())
