"""Bootstrap-friendly Postgres runtime factories."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from learning_agent_service.config.settings import PostgresSettings

from .errors import InfrastructureConfigurationError, require_dependency
from .models import Base, SQLALCHEMY_AVAILABLE

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
    return create_engine(
        settings.dsn,
        echo=settings.echo,
        pool_size=settings.pool_size,
        max_overflow=settings.max_overflow,
        pool_pre_ping=settings.pool_pre_ping,
        future=True,
    )


def build_session_factory(settings: PostgresSettings, engine: Optional[Any] = None) -> Any:
    """Create a SQLAlchemy session factory bound to the configured engine."""

    if not SQLALCHEMY_AVAILABLE or sessionmaker is None:
        require_dependency("sqlalchemy", "Postgres durable storage")
    bound_engine = engine or build_engine(settings)
    return sessionmaker(bind=bound_engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)


def build_postgres_runtime(settings: PostgresSettings) -> PostgresRuntime:
    """Build the full Postgres runtime bundle."""

    engine = build_engine(settings)
    return PostgresRuntime(engine=engine, session_factory=build_session_factory(settings, engine=engine))


def create_schema(engine: Any) -> None:
    """Create tables directly from metadata for local bootstrap and smoke tests."""

    if not SQLALCHEMY_AVAILABLE:
        require_dependency("sqlalchemy", "schema creation")
    Base.metadata.create_all(bind=engine)

