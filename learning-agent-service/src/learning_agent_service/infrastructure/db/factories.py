"""Aggregated client builders for infrastructure bootstrap code."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from learning_agent_service.config.settings import ServiceSettings

from .errors import InfrastructureError
from .openai_client import OpenAIRuntime, build_openai_runtime
from .postgres import PostgresRuntime, build_postgres_runtime
from .qdrant import QdrantRuntime, build_qdrant_runtime
from .redis import RedisRuntime, build_redis_runtime


@dataclass(frozen=True)
class InfrastructureClients:
    """Container for optionally assembled infrastructure adapters."""

    postgres: Optional[PostgresRuntime] = None
    redis: Optional[RedisRuntime] = None
    qdrant: Optional[QdrantRuntime] = None
    openai: Optional[OpenAIRuntime] = None
    bootstrap_errors: tuple = ()


def build_infrastructure_clients(settings: ServiceSettings, allow_partial: bool = True) -> InfrastructureClients:
    """Build infrastructure adapters with optional partial success."""

    errors = []
    postgres_runtime = None
    redis_runtime = None
    qdrant_runtime = None
    openai_runtime = None

    for name, builder in (
        ("postgres", lambda: build_postgres_runtime(settings.postgres)),
        ("redis", lambda: build_redis_runtime(settings.redis)),
        ("qdrant", lambda: build_qdrant_runtime(settings.qdrant)),
        ("openai", lambda: build_openai_runtime(settings.openai)),
    ):
        try:
            runtime = builder()
        except InfrastructureError as exc:
            if not allow_partial:
                raise
            errors.append((name, str(exc)))
            continue
        if name == "postgres":
            postgres_runtime = runtime
        elif name == "redis":
            redis_runtime = runtime
        elif name == "qdrant":
            qdrant_runtime = runtime
        elif name == "openai":
            openai_runtime = runtime

    return InfrastructureClients(
        postgres=postgres_runtime,
        redis=redis_runtime,
        qdrant=qdrant_runtime,
        openai=openai_runtime,
        bootstrap_errors=tuple(errors),
    )
