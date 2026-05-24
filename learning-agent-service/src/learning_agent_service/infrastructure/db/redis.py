"""Bootstrap-friendly Redis runtime factories and key helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from learning_agent_service.config.settings import RedisSettings

from .errors import require_dependency

try:
    from redis import Redis
except ImportError:  # pragma: no cover - depends on optional runtime installation.
    Redis = None


@dataclass(frozen=True)
class RedisKeySpace:
    """Centralized Redis key naming for the learning service."""

    prefix: str

    def session_state(self, session_id: str) -> str:
        return "%s:session:%s:state" % (self.prefix, session_id)

    def summary(self, session_id: str) -> str:
        return "%s:session:%s:summary" % (self.prefix, session_id)

    def clarification(self, session_id: str) -> str:
        return "%s:session:%s:clarify" % (self.prefix, session_id)

    def tool_cache(self, session_id: str) -> str:
        return "%s:session:%s:toolcache" % (self.prefix, session_id)

    def embedding_cache(self, embedding_model: str, embedding_model_version: str, normalized_query_hash: str) -> str:
        return "%s:embedding:%s:%s:%s" % (
            self.prefix,
            embedding_model,
            embedding_model_version or "v1",
            normalized_query_hash,
        )


@dataclass(frozen=True)
class RedisRuntime:
    """Holds the Redis client together with the key naming helpers."""

    client: Any
    keys: RedisKeySpace


def build_redis_runtime(settings: RedisSettings) -> RedisRuntime:
    """Create the Redis client and bind the canonical key space."""

    if Redis is None:
        require_dependency("redis", "short-term session storage")
    client = Redis.from_url(settings.url, socket_timeout=settings.socket_timeout_seconds, decode_responses=True)
    return RedisRuntime(client=client, keys=RedisKeySpace(prefix=settings.key_prefix))
