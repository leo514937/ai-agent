"""SQLAlchemy repository for persisted memory trace snapshots."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from learning_agent_service.domain.memory import MemoryTrace
from learning_agent_service.infrastructure.db.models import MemoryTraceModel

from .base import SqlAlchemyRepositoryBase

try:  # pragma: no cover - optional runtime dependency
    from sqlalchemy import select
except ImportError:  # pragma: no cover - depends on runtime installation.
    select = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _trace_to_model_fields(trace: MemoryTrace) -> Dict[str, Any]:
    return {
        "trace_id": trace.trace_id,
        "user_id": trace.user_id,
        "session_id": trace.session_id,
        "turn_id": trace.turn_id,
        "retrieved_memory_ids": list(trace.retrieved),
        "injected_memory_ids": list(trace.injected),
        "skipped_memories": list(trace.skipped),
        "candidate_ids": list(trace.candidate_ids),
        "promoted_memory_ids": list(trace.promoted),
        "rejected_candidates": list(trace.rejected),
        "conflict_resolutions": list(trace.conflict_resolutions),
        "total_memory_tokens": int(trace.total_memory_tokens),
        "qdrant_degraded": bool(trace.qdrant_degraded),
        "created_at": trace.created_at,
    }


def _model_to_trace(model: MemoryTraceModel) -> MemoryTrace:
    return MemoryTrace.model_validate(
        {
            "trace_id": model.trace_id,
            "user_id": model.user_id,
            "session_id": model.session_id,
            "turn_id": model.turn_id,
            "retrieved": list(model.retrieved_memory_ids or []),
            "injected": list(model.injected_memory_ids or []),
            "skipped": list(model.skipped_memories or []),
            "candidates": list(model.candidate_ids or []),
            "promoted": list(model.promoted_memory_ids or []),
            "rejected": list(model.rejected_candidates or []),
            "conflict_resolutions": list(model.conflict_resolutions or []),
            "total_memory_tokens": int(model.total_memory_tokens or 0),
            "qdrant_degraded": bool(model.qdrant_degraded),
            "created_at": model.created_at,
        }
    )


class MemoryTraceRepository(SqlAlchemyRepositoryBase):
    """SQLAlchemy repository for persisted memory trace snapshots."""

    def create(self, trace: MemoryTrace) -> MemoryTrace:
        self._require_sqlalchemy()
        fields = _trace_to_model_fields(trace)
        with self.session_scope() as session:
            instance = session.execute(
                select(MemoryTraceModel).where(MemoryTraceModel.trace_id == fields["trace_id"])
            ).scalar_one_or_none()
            if instance is None:
                instance = MemoryTraceModel(
                    trace_id=fields["trace_id"],
                    user_id=fields["user_id"],
                    session_id=fields["session_id"],
                    turn_id=fields["turn_id"],
                )
            for key, value in fields.items():
                if key == "trace_id":
                    continue
                setattr(instance, key, value)
            if not instance.created_at:
                instance.created_at = fields["created_at"] or _utcnow()
            session.add(instance)
            session.flush()
            return _model_to_trace(instance)

    def get_by_trace_id(self, trace_id: str) -> Optional[MemoryTrace]:
        self._require_sqlalchemy()
        with self.session_scope() as session:
            model = session.execute(
                select(MemoryTraceModel).where(MemoryTraceModel.trace_id == trace_id)
            ).scalar_one_or_none()
            return _model_to_trace(model) if model is not None else None

    def list_by_session(self, session_id: str) -> List[MemoryTrace]:
        self._require_sqlalchemy()
        with self.session_scope() as session:
            models = list(
                session.execute(
                    select(MemoryTraceModel)
                    .where(MemoryTraceModel.session_id == session_id)
                    .order_by(
                        MemoryTraceModel.created_at.desc(),
                        MemoryTraceModel.trace_id.desc(),
                    )
                ).scalars()
            )
        return [_model_to_trace(model) for model in models]

    def list_by_turn(self, turn_id: str) -> List[MemoryTrace]:
        self._require_sqlalchemy()
        with self.session_scope() as session:
            models = list(
                session.execute(
                    select(MemoryTraceModel)
                    .where(MemoryTraceModel.turn_id == turn_id)
                    .order_by(
                        MemoryTraceModel.created_at.desc(),
                        MemoryTraceModel.trace_id.desc(),
                    )
                ).scalars()
            )
        return [_model_to_trace(model) for model in models]

    def list_recent_by_user(self, user_id: str, limit: int = 20) -> List[MemoryTrace]:
        self._require_sqlalchemy()
        with self.session_scope() as session:
            models = list(
                session.execute(
                    select(MemoryTraceModel)
                    .where(MemoryTraceModel.user_id == user_id)
                    .order_by(MemoryTraceModel.created_at.desc())
                    .limit(limit)
                ).scalars()
            )
        return [_model_to_trace(model) for model in models]
