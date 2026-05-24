from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, List, Optional

from learning_agent_service.infrastructure.db.models import MemoryOutboxModel

from .base import SqlAlchemyRepositoryBase
from .records import MemoryOutboxRecord

try:
    from sqlalchemy import select
except ImportError:  # pragma: no cover - depends on optional runtime installation.
    select = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MemoryOutboxRepository(SqlAlchemyRepositoryBase):
    """Durable outbox for memory and vector sync side effects."""

    def enqueue(self, event: MemoryOutboxRecord) -> MemoryOutboxModel:
        return self.enqueue_many([event])[0]

    def enqueue_many(self, events: Iterable[MemoryOutboxRecord]) -> List[MemoryOutboxModel]:
        self._require_sqlalchemy()
        saved: List[MemoryOutboxModel] = []
        with self.session_scope() as session:
            for event in events:
                instance = session.execute(
                    select(MemoryOutboxModel).where(MemoryOutboxModel.dedupe_key == event.dedupe_key)
                ).scalar_one_or_none()
                if instance is None:
                    instance = MemoryOutboxModel(
                        aggregate_type=event.aggregate_type,
                        aggregate_id=event.aggregate_id,
                        memory_id=event.memory_id,
                        user_id=event.user_id,
                        event_type=event.event_type,
                        dedupe_key=event.dedupe_key,
                    )
                instance.payload = dict(event.payload)
                instance.status = event.status
                instance.session_id = event.session_id
                instance.turn_id = event.turn_id
                instance.available_at = event.available_at or _utcnow()
                instance.trace_id = event.trace_id
                instance.attempts = event.attempts
                instance.last_error = event.last_error
                instance.vector_id = event.vector_id
                instance.extra = dict(event.extra)
                session.add(instance)
                saved.append(instance)
            session.flush()
            return saved

    def enqueue_in_session(self, session: Any, event: MemoryOutboxRecord) -> MemoryOutboxModel:
        instance = session.execute(
            select(MemoryOutboxModel).where(MemoryOutboxModel.dedupe_key == event.dedupe_key)
        ).scalar_one_or_none()
        if instance is None:
            instance = MemoryOutboxModel(
                aggregate_type=event.aggregate_type,
                aggregate_id=event.aggregate_id,
                memory_id=event.memory_id,
                user_id=event.user_id,
                event_type=event.event_type,
                dedupe_key=event.dedupe_key,
            )
        instance.payload = dict(event.payload)
        instance.status = event.status
        instance.session_id = event.session_id
        instance.turn_id = event.turn_id
        instance.available_at = event.available_at or _utcnow()
        instance.trace_id = event.trace_id
        instance.attempts = event.attempts
        instance.last_error = event.last_error
        instance.vector_id = event.vector_id
        instance.extra = dict(event.extra)
        session.add(instance)
        session.flush()
        return instance

    def claim_pending(self, limit: int, now: Optional[datetime] = None) -> List[MemoryOutboxModel]:
        self._require_sqlalchemy()
        claim_time = now or _utcnow()
        with self.session_scope() as session:
            pending = list(
                session.execute(
                    select(MemoryOutboxModel)
                    .where(
                        MemoryOutboxModel.status == "pending",
                        MemoryOutboxModel.available_at <= claim_time,
                    )
                    .order_by(MemoryOutboxModel.available_at.asc())
                    .limit(limit)
                ).scalars()
            )
            for row in pending:
                row.status = "processing"
                row.attempts = int(row.attempts or 0) + 1
                session.add(row)
            session.flush()
            return pending

    def mark_published(self, event_id: str) -> Optional[MemoryOutboxModel]:
        self._require_sqlalchemy()
        with self.session_scope() as session:
            instance = session.get(MemoryOutboxModel, event_id)
            if instance is None:
                return None
            instance.status = "published"
            instance.published_at = _utcnow()
            instance.last_error = None
            session.add(instance)
            session.flush()
            return instance

    def mark_failed(self, event_id: str, error_message: str, retry_delay_seconds: int = 60) -> Optional[MemoryOutboxModel]:
        self._require_sqlalchemy()
        with self.session_scope() as session:
            instance = session.get(MemoryOutboxModel, event_id)
            if instance is None:
                return None
            instance.status = "pending"
            instance.last_error = error_message
            if retry_delay_seconds > 0:
                from datetime import timedelta

                instance.available_at = _utcnow() + timedelta(seconds=retry_delay_seconds)
            session.add(instance)
            session.flush()
            return instance

    def list_recent(
        self,
        limit: int = 50,
        *,
        aggregate_type: Optional[str] = None,
        event_type_prefix: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> List[MemoryOutboxModel]:
        self._require_sqlalchemy()
        with self.session_scope() as session:
            query = select(MemoryOutboxModel)
            if aggregate_type:
                query = query.where(MemoryOutboxModel.aggregate_type == aggregate_type)
            if event_type_prefix:
                query = query.where(MemoryOutboxModel.event_type.like(f"{event_type_prefix}%"))
            if trace_id:
                query = query.where(MemoryOutboxModel.trace_id == trace_id)
            models = list(
                session.execute(
                    query.order_by(
                        MemoryOutboxModel.available_at.desc(),
                        MemoryOutboxModel.created_at.desc(),
                    ).limit(limit)
                ).scalars()
            )
        return models
