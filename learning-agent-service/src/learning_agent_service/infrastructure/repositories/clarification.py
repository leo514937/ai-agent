"""SQLAlchemy repository for durable clarification records."""

from __future__ import annotations

from typing import List

from learning_agent_service.infrastructure.db.models import ClarificationRecordModel

from .base import SqlAlchemyRepositoryBase
from .records import ClarificationRecordEntry

try:
    from sqlalchemy import select
except ImportError:  # pragma: no cover - depends on optional runtime installation.
    select = None


class ClarificationRecordRepository(SqlAlchemyRepositoryBase):
    """Read/write access for clarification prompts and user selections."""

    def record(self, entry: ClarificationRecordEntry) -> ClarificationRecordModel:
        self._require_sqlalchemy()
        with self.session_scope() as session:
            instance = ClarificationRecordModel(
                user_id=entry.user_id,
                session_id=entry.session_id,
                turn_id=entry.turn_id,
                ambiguity_type=entry.ambiguity_type,
                question_text=entry.question_text,
                options_json=dict(entry.options_json),
                selected_option_id=entry.selected_option_id,
                selected_option_label=entry.selected_option_label,
                resolution_status=entry.resolution_status,
                resolved_at=entry.resolved_at,
                extra=dict(entry.extra),
            )
            session.add(instance)
            session.flush()
            return instance

    def list_for_session(self, session_id: str, limit: int = 20) -> List[ClarificationRecordModel]:
        self._require_sqlalchemy()
        with self.session_scope() as session:
            return list(
                session.execute(
                    select(ClarificationRecordModel)
                    .where(ClarificationRecordModel.session_id == session_id)
                    .order_by(ClarificationRecordModel.created_at.desc())
                    .limit(limit)
                ).scalars()
            )
