"""Shared repository scaffolding for SQLAlchemy-backed infrastructure adapters."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Callable, Iterator

from learning_agent_service.infrastructure.db.errors import require_dependency
from learning_agent_service.infrastructure.db.models import SQLALCHEMY_AVAILABLE

SessionFactory = Callable[[], Any]


class SqlAlchemyRepositoryBase(object):
    """Small helper that centralizes session lifecycle management."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def _require_sqlalchemy(self) -> None:
        if not SQLALCHEMY_AVAILABLE:
            require_dependency("sqlalchemy", "repository operations")

    @contextmanager
    def session_scope(self) -> Iterator[Any]:
        self._require_sqlalchemy()
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
