"""Bootstrap-friendly Postgres runtime factories."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from learning_agent_service.config.settings import PostgresSettings

from .errors import InfrastructureConfigurationError, require_dependency
from .models import SQLALCHEMY_AVAILABLE, Base

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
except ImportError:  # pragma: no cover - depends on optional runtime installation.
    create_engine = None
    sessionmaker = None


@dataclass(frozen=True)
class PostgresRuntime:
    """Holds the SQLAlchemy engine and session factory used by repositories."""

    engine: Any
    session_factory: Any


def build_engine(settings: PostgresSettings) -> Any:
    """Create the SQLAlchemy engine for the durable fact store."""

    if not SQLALCHEMY_AVAILABLE or create_engine is None:
        require_dependency("sqlalchemy", "Postgres durable storage")
    if not settings.dsn:
        raise InfrastructureConfigurationError("LEARNING_AGENT_POSTGRES_DSN must be configured before enabling Postgres")
    connect_args = {}
    dsn_text = str(settings.dsn or "").strip().lower()
    if dsn_text.startswith("postgresql") or dsn_text.startswith("postgres://"):
        # 让不可达的本地 Postgres 尽快失败，避免把服务启动卡死在连接探测上。
        connect_args["connect_timeout"] = 3
    engine_kwargs = dict(
        echo=settings.echo,
        pool_size=settings.pool_size,
        max_overflow=settings.max_overflow,
        pool_pre_ping=settings.pool_pre_ping,
        future=True,
    )
    if connect_args:
        engine_kwargs["connect_args"] = connect_args
    return create_engine(
        settings.dsn,
        **engine_kwargs,
    )


def build_session_factory(settings: PostgresSettings, engine: Any | None = None) -> Any:
    """Create a SQLAlchemy session factory bound to the configured engine."""

    if not SQLALCHEMY_AVAILABLE or sessionmaker is None:
        require_dependency("sqlalchemy", "Postgres durable storage")
    bound_engine = engine or build_engine(settings)
    return sessionmaker(bind=bound_engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)


def build_postgres_runtime(settings: PostgresSettings) -> PostgresRuntime:
    """Build the full Postgres runtime bundle."""

    engine = build_engine(settings)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
    except Exception as exc:
        raise InfrastructureConfigurationError(
            "Postgres unavailable during bootstrap; falling back to in-memory adapters"
        ) from exc
    return PostgresRuntime(engine=engine, session_factory=build_session_factory(settings, engine=engine))


def create_schema(engine: Any) -> None:
    """Create tables directly from metadata for local bootstrap and smoke tests."""

    if not SQLALCHEMY_AVAILABLE:
        require_dependency("sqlalchemy", "schema creation")
    Base.metadata.create_all(bind=engine)

