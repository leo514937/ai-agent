"""SQLAlchemy repository for the async outbox used by log and audit side effects."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, List, Optional

from learning_agent_service.infrastructure.db.models import OutboxEventModel

from .base import SqlAlchemyRepositoryBase
from .records import OutboxEventRecord

try:
    from sqlalchemy import select
except ImportError:  # pragma: no cover - depends on optional runtime installation.
    select = None


class OutboxRepository(SqlAlchemyRepositoryBase):
    """Queue and track deferred side effects without blocking the main response path."""

    def enqueue(self, event: OutboxEventRecord) -> OutboxEventModel:
        return self.enqueue_many([event])[0]

    def enqueue_many(self, events: Iterable[OutboxEventRecord]) -> List[OutboxEventModel]:
        self._require_sqlalchemy()
        saved = []
        with self.session_scope() as session:
            for event in events:
                instance = session.execute(
                    select(OutboxEventModel).where(OutboxEventModel.dedupe_key == event.dedupe_key)
                ).scalar_one_or_none()
                if instance is None:
                    instance = OutboxEventModel(
                        aggregate_type=event.aggregate_type,
                        aggregate_id=event.aggregate_id,
                        event_type=event.event_type,
                        dedupe_key=event.dedupe_key,
                    )
                instance.payload = dict(event.payload)
                instance.status = event.status
                instance.available_at = event.available_at or datetime.now(timezone.utc)
                instance.trace_id = event.trace_id
                instance.attempts = event.attempts
                instance.last_error = event.last_error
                session.add(instance)
                saved.append(instance)
            session.flush()
            return saved

    def claim_pending(self, limit: int, now: Optional[datetime] = None) -> List[OutboxEventModel]:
        self._require_sqlalchemy()
        claim_time = now or datetime.now(timezone.utc)
        with self.session_scope() as session:
            pending = list(
                session.execute(
                    select(OutboxEventModel)
                    .where(
                        OutboxEventModel.status == "pending",
                        OutboxEventModel.available_at <= claim_time,
                    )
                    .order_by(OutboxEventModel.available_at.asc())
                    .limit(limit)
                ).scalars()
            )
            for row in pending:
                row.status = "processing"
                row.attempts = int(row.attempts or 0) + 1
                session.add(row)
            session.flush()
            return pending

    def mark_published(self, event_id: str) -> Optional[OutboxEventModel]:
        self._require_sqlalchemy()
        with self.session_scope() as session:
            instance = session.get(OutboxEventModel, event_id)
            if instance is None:
                return None
            instance.status = "published"
            instance.published_at = datetime.now(timezone.utc)
            instance.last_error = None
            session.add(instance)
            session.flush()
            return instance

    def mark_failed(self, event_id: str, error_message: str) -> Optional[OutboxEventModel]:
        self._require_sqlalchemy()
        with self.session_scope() as session:
            instance = session.get(OutboxEventModel, event_id)
            if instance is None:
                return None
            instance.status = "failed"
            instance.last_error = error_message
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
    ) -> List[OutboxEventModel]:
        self._require_sqlalchemy()
        with self.session_scope() as session:
            query = select(OutboxEventModel)
            if aggregate_type:
                query = query.where(OutboxEventModel.aggregate_type == aggregate_type)
            if event_type_prefix:
                query = query.where(OutboxEventModel.event_type.like(f"{event_type_prefix}%"))
            if trace_id:
                query = query.where(OutboxEventModel.trace_id == trace_id)
            models = list(
                session.execute(
                    query.order_by(
                        OutboxEventModel.available_at.desc(),
                        OutboxEventModel.created_at.desc(),
                    ).limit(limit)
                ).scalars()
            )
        return models
