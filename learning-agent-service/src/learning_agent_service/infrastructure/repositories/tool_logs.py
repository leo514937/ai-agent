"""SQLAlchemy repository for asynchronously persisted tool invocation logs."""

from __future__ import annotations

from typing import Iterable, List

from learning_agent_service.infrastructure.db.models import ToolInvocationLogModel

from .base import SqlAlchemyRepositoryBase
from .records import ToolInvocationLogEntry

try:
    from sqlalchemy import select
except ImportError:  # pragma: no cover - depends on optional runtime installation.
    select = None


class ToolInvocationLogRepository(SqlAlchemyRepositoryBase):
    """Read/write access for durable tool invocation logging."""

    def append_many(self, entries: Iterable[ToolInvocationLogEntry]) -> List[ToolInvocationLogModel]:
        self._require_sqlalchemy()
        saved = []
        with self.session_scope() as session:
            for entry in entries:
                instance = session.execute(
                    select(ToolInvocationLogModel).where(ToolInvocationLogModel.tool_call_id == entry.tool_call_id)
                ).scalar_one_or_none()
                if instance is None:
                    instance = ToolInvocationLogModel(
                        session_id=entry.session_id,
                        turn_id=entry.turn_id,
                        tool_name=entry.tool_name,
                        tool_call_id=entry.tool_call_id,
                    )
                instance.status = entry.status
                instance.duration_ms = entry.duration_ms
                instance.degraded_to = entry.degraded_to
                instance.error_code = entry.error_code
                instance.input_summary = dict(entry.input_summary)
                instance.output_summary = dict(entry.output_summary)
                instance.extra = dict(entry.extra)
                session.add(instance)
                saved.append(instance)
            session.flush()
            return saved
