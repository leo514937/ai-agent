from __future__ import annotations

from types import SimpleNamespace

import pytest

from local_life_agent import config
from local_life_agent.domain.state import SessionState
from local_life_agent.session import (
    InMemorySessionStore,
    RedisSessionStore,
    SessionStore,
    get_session_store,
    reset_session_store,
    set_session_store,
    ttl_seconds_for_partition,
)
from local_life_agent.session.policy import (
    SESSION_PARTITION_COMPARISON_CONTEXT,
    SESSION_PARTITION_CONVERSATION_CONTEXT,
    SESSION_PARTITION_DEFAULT,
    SESSION_PARTITION_FOCUS_CONTEXT,
    SESSION_PARTITION_PENDING_CLARIFICATION,
    SESSION_PARTITION_RECOMMENDATION_CONTEXT,
    SESSION_PARTITION_USER_PREFERENCE_SUMMARY,
    partition_for_field,
)


class _FakeRedisClient:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.hashes: dict[str, dict[str, str]] = {}
        self.expire_calls: list[tuple[str, int]] = []
        self.deleted: list[str] = []

    def ping(self) -> bool:
        return True

    def set(self, key: str, value: str) -> None:
        self.values[key] = value

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def hset(self, key: str, mapping: dict[str, str]) -> None:
        self.hashes.setdefault(key, {}).update(mapping)

    def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.hashes.get(key, {}))

    def expire(self, key: str, ttl: int) -> None:
        self.expire_calls.append((key, ttl))

    def delete(self, *keys: str) -> None:
        for key in keys:
            self.values.pop(key, None)
            self.hashes.pop(key, None)
            self.deleted.append(key)

    def scan_iter(self, match: str | None = None):
        for key in list(self.values):
            if match is None or key.startswith(match.rstrip("*")):
                yield key


def test_session_store_interface_is_implemented_by_inmemory_store():
    store = InMemorySessionStore()

    assert isinstance(store, SessionStore)
    assert store.partition_ttl("pending_clarification") > 0
    assert store.partition_ttl("unknown") == ttl_seconds_for_partition(SESSION_PARTITION_DEFAULT)


def test_session_partition_mapping_and_config_ttls(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "SESSION_TTL_CONVERSATION_CONTEXT_SECONDS", 11, raising=False)
    monkeypatch.setattr(config, "SESSION_TTL_FOCUS_CONTEXT_SECONDS", 12, raising=False)
    monkeypatch.setattr(config, "SESSION_TTL_RECOMMENDATION_CONTEXT_SECONDS", 13, raising=False)
    monkeypatch.setattr(config, "SESSION_TTL_COMPARISON_CONTEXT_SECONDS", 14, raising=False)
    monkeypatch.setattr(config, "SESSION_TTL_PENDING_CLARIFICATION_SECONDS", 15, raising=False)
    monkeypatch.setattr(config, "SESSION_TTL_USER_PREFERENCE_SUMMARY_SECONDS", 16, raising=False)
    monkeypatch.setattr(config, "SESSION_TTL_EXECUTION_COUNTERS_SECONDS", 17, raising=False)
    monkeypatch.setattr(config, "SESSION_TTL_DEFAULT_SECONDS", 99, raising=False)

    assert partition_for_field("current_shop") == SESSION_PARTITION_FOCUS_CONTEXT
    assert partition_for_field("last_recommendation_list") == SESSION_PARTITION_RECOMMENDATION_CONTEXT
    assert partition_for_field("comparison_result") == SESSION_PARTITION_COMPARISON_CONTEXT
    assert partition_for_field("pending_clarification") == SESSION_PARTITION_PENDING_CLARIFICATION
    assert partition_for_field("active_constraints") == SESSION_PARTITION_USER_PREFERENCE_SUMMARY
    assert partition_for_field("replan_counters") == "execution_counters"
    assert partition_for_field("unknown_field") == SESSION_PARTITION_CONVERSATION_CONTEXT

    assert ttl_seconds_for_partition(SESSION_PARTITION_CONVERSATION_CONTEXT) == 11
    assert ttl_seconds_for_partition(SESSION_PARTITION_FOCUS_CONTEXT) == 12
    assert ttl_seconds_for_partition(SESSION_PARTITION_RECOMMENDATION_CONTEXT) == 13
    assert ttl_seconds_for_partition(SESSION_PARTITION_COMPARISON_CONTEXT) == 14
    assert ttl_seconds_for_partition(SESSION_PARTITION_PENDING_CLARIFICATION) == 15
    assert ttl_seconds_for_partition(SESSION_PARTITION_USER_PREFERENCE_SUMMARY) == 16
    assert ttl_seconds_for_partition("execution_counters") == 17
    assert ttl_seconds_for_partition("unknown") == 99


def test_inmemory_session_store_partition_ttl_and_roundtrip(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "SESSION_TTL_FOCUS_CONTEXT_SECONDS", 5, raising=False)
    monkeypatch.setattr(config, "SESSION_TTL_PENDING_CLARIFICATION_SECONDS", 1, raising=False)
    monkeypatch.setattr(config, "SESSION_TTL_DEFAULT_SECONDS", 5, raising=False)
    monkeypatch.setattr("local_life_agent.session.store.time", lambda: 0.0)

    store = InMemorySessionStore()
    store.save(
        "sess_1",
        SessionState(
            current_shop={"shop_id": "s1", "shop_name": "测试店"},
            pending_clarification={"pending_id": "pc1", "reason": "missing_shop"},
            last_recommendation_list=[{"shop_id": "r1", "shop_name": "推荐店"}],
        ),
    )

    monkeypatch.setattr("local_life_agent.session.store.time", lambda: 2.0)
    loaded = store.load("sess_1")

    assert loaded.current_shop == {"shop_id": "s1", "shop_name": "测试店"}
    assert loaded.last_recommendation_list == [{"shop_id": "r1", "shop_name": "推荐店"}]
    assert loaded.pending_clarification is None

    store.touch("sess_1")
    store.delete("sess_1")
    assert store.load("sess_1").current_shop is None


def test_redis_session_store_roundtrip_and_delete():
    client = _FakeRedisClient()
    store = RedisSessionStore(client, key_prefix="session:test", now_fn=lambda: 100.0)

    session = SessionState(
        current_shop={"shop_id": "s1", "shop_name": "测试店"},
        last_recommendation_list=[{"shop_id": "r1", "shop_name": "推荐店"}],
        comparison_targets=[{"shop_id": "c1", "shop_name": "对比店"}],
        pending_clarification={"pending_id": "pc1", "reason": "missing_shop"},
        active_constraints={"price": "cheap"},
        replan_counters={"expand_search": 1, "replan_evidence": 0, "rewrite": 0},
    )

    store.save("sess_redis", session)
    loaded = store.load("sess_redis")

    assert loaded.current_shop == session.current_shop
    assert loaded.last_recommendation_list == session.last_recommendation_list
    assert loaded.comparison_targets == session.comparison_targets
    assert loaded.pending_clarification == session.pending_clarification
    assert loaded.active_constraints == session.active_constraints
    assert loaded.replan_counters == session.replan_counters
    assert "session:test:focus_context:sess_redis" in client.values
    assert "session:test:recommendation_context:sess_redis" in client.values
    assert "session:test:comparison_context:sess_redis" in client.values
    assert "session:test:pending_clarification:sess_redis" in client.values
    assert "session:test:user_preference_summary:sess_redis" in client.values
    assert "session:test:execution_counters:sess_redis" in client.values
    assert "session:test:sess_redis:data" not in client.values
    assert client.hashes
    assert ("session:test:focus_context:sess_redis", ttl_seconds_for_partition("focus_context")) in client.expire_calls
    assert ("session:test:pending_clarification:sess_redis", ttl_seconds_for_partition("pending_clarification")) in client.expire_calls

    store.delete("sess_redis")
    assert store.load("sess_redis").current_shop is None
    assert store.partition_ttl("pending_clarification") == ttl_seconds_for_partition("pending_clarification")


def test_redis_session_store_reads_legacy_whole_session_payload():
    client = _FakeRedisClient()
    store = RedisSessionStore(client, key_prefix="session:test", now_fn=lambda: 100.0)
    client.set(
        "session:test:legacy:data",
        '{"current_shop": {"shop_id": "legacy", "shop_name": "旧店"}}',
    )

    loaded = store.load("legacy")

    assert loaded.current_shop == {"shop_id": "legacy", "shop_name": "旧店"}


def test_redis_create_from_config_uses_configured_connection_pool(monkeypatch: pytest.MonkeyPatch):
    created: dict[str, object] = {}

    class _FakeConnectionPool:
        @classmethod
        def from_url(cls, url: str, **kwargs):
            created["url"] = url
            created["pool_kwargs"] = kwargs
            return "pool"

    class _FakeRedis:
        def __init__(self, *, connection_pool):
            created["connection_pool"] = connection_pool

        def ping(self) -> bool:
            created["ping"] = True
            return True

    fake_redis_module = SimpleNamespace(ConnectionPool=_FakeConnectionPool, Redis=_FakeRedis)

    monkeypatch.setitem(__import__("sys").modules, "redis", fake_redis_module)
    monkeypatch.setattr(config, "SESSION_REDIS_URL", "redis://example:6379/2", raising=False)
    monkeypatch.setattr(config, "SESSION_REDIS_MAX_CONNECTIONS", 17, raising=False)
    monkeypatch.setattr(config, "SESSION_REDIS_SOCKET_TIMEOUT_SECONDS", 1.5, raising=False)
    monkeypatch.setattr(config, "SESSION_REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS", 2.5, raising=False)

    store = RedisSessionStore.create_from_config()

    assert isinstance(store, RedisSessionStore)
    assert created["url"] == "redis://example:6379/2"
    assert created["connection_pool"] == "pool"
    assert created["pool_kwargs"] == {
        "decode_responses": True,
        "max_connections": 17,
        "socket_timeout": 1.5,
        "socket_connect_timeout": 2.5,
    }
    assert created["ping"] is True


def test_redis_fallback_to_inmemory(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "SESSION_STORE_BACKEND", "redis", raising=False)
    monkeypatch.setattr(RedisSessionStore, "create_from_config", classmethod(lambda cls: (_ for _ in ()).throw(RuntimeError("redis down"))))

    reset_session_store()
    store = get_session_store()

    assert isinstance(store, InMemorySessionStore)

    reset_session_store()


def test_session_roundtrip_preserves_core_context_fields():
    store = InMemorySessionStore()
    pending = {"pending_id": "pc_1", "reason": "missing_shop"}
    state = SessionState(
        current_shop={"shop_id": "s1", "shop_name": "测试店"},
        last_recommendation_list=[{"shop_id": "r1", "shop_name": "推荐店"}],
        pending_clarification=pending,
    )

    store.save("roundtrip", state)
    loaded = store.load("roundtrip")

    assert loaded.current_shop == state.current_shop
    assert loaded.last_recommendation_list == state.last_recommendation_list
    assert loaded.pending_clarification == pending
