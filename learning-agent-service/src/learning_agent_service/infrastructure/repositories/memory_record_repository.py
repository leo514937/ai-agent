"""SQLAlchemy repository for governed memory records."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from learning_agent_service.domain.memory import (
    MemoryAccessLog,
    MemoryCandidate,
    MemoryDeletionJob,
    MemoryDeletionStatus,
    MemoryEdge,
    MemoryEdgeType,
    MemoryRecord,
    MemoryScope,
    MemoryStatus,
    MemoryTargetStore,
    MemoryType,
)
from learning_agent_service.infrastructure.db.models import (
    MemoryAccessLogModel,
    MemoryCandidateModel,
    MemoryDeletionJobModel,
    MemoryEdgeModel,
    MemoryRecordModel,
)
from learning_agent_service.domain.utils import utcnow as _utcnow

from .base import SqlAlchemyRepositoryBase

try:  # pragma: no cover - optional runtime dependency
    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError
except ImportError:  # pragma: no cover - depends on runtime installation.
    select: Any = None
    IntegrityError = Exception


def _ensure_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _is_active_at(model: Any, now: datetime) -> bool:
    eff_from = _ensure_aware(getattr(model, "effective_from", None))
    if eff_from is not None and eff_from > now:
        return False
    eff_to = _ensure_aware(getattr(model, "effective_to", None))
    if eff_to is not None and eff_to <= now:
        return False
    val_until = _ensure_aware(getattr(model, "valid_until", None))
    if val_until is not None and val_until <= now:
        return False
    return True


def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _enum_or_default(enum_cls: Any, value: Any, default: Any) -> Any:
    if value is None:
        return default
    if hasattr(value, "value"):
        return value
    try:
        return enum_cls(value)
    except Exception:
        return default


def _json_ready(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str, ensure_ascii=False))


def _is_long_term_scope(value: Any) -> bool:
    text = _enum_value(value).lower()
    return text in {"user", "project", "global"}


def _is_searchable_status(value: Any) -> bool:
    text = _enum_value(value).lower()
    return text in {_enum_value(MemoryStatus.ACTIVE), _enum_value(MemoryStatus.CONFIRMED)}


def _default_memory_id(record: MemoryRecord) -> str:
    topic = record.topic or (record.entities[0] if record.entities else "memory")
    source_turn_id = record.evidence_turn_id or ""
    return f"{record.user_id}:{topic}:{record.memory_type.value}:{source_turn_id or uuid4().hex[:12]}"


def _record_to_model_fields(record: MemoryRecord) -> dict[str, Any]:
    normalized = record.model_copy(
        update={
            "memory_id": record.memory_id or _default_memory_id(record),
            "embedding_id": record.embedding_id or record.memory_id or None,
            "topic": record.topic or (record.entities[0] if record.entities else None),
            "source_session_id": record.source_session_id or record.session_id,
            "evidence_turn_id": record.evidence_turn_id or "",
            "raw_evidence": dict(record.raw_evidence or {}),
            "updated_at": _utcnow(),
        }
    )
    return {
        "memory_id": normalized.memory_id,
        "user_id": normalized.user_id,
        "session_id": normalized.session_id,
        "source_session_id": normalized.source_session_id or normalized.session_id,
        "project_id": normalized.project_id,
        "topic": normalized.topic,
        "normalized_key": normalized.normalized_key,
        "normalized_value": normalized.normalized_value,
        "memory_type": _enum_value(normalized.memory_type),
        "scope": _enum_value(normalized.scope),
        "persistence_scope": _enum_value(normalized.persistence_scope),
        "source": _enum_value(normalized.source),
        "status": _enum_value(normalized.status),
        "is_active": bool(
            normalized.is_active
            and normalized.status
            not in {MemoryStatus.DELETED, MemoryStatus.EXPIRED, MemoryStatus.SUPERSEDED, MemoryStatus.INACTIVE}
        ),
        "summary": normalized.summary,
        "content": _json_ready(normalized.content),
        "confidence": float(normalized.confidence),
        "importance": float(normalized.importance),
        "stability": float(normalized.stability),
        "sensitivity": _enum_value(normalized.sensitivity),
        "retrieval_mode": _enum_value(normalized.retrieval_mode),
        "should_vectorize": bool(normalized.should_vectorize),
        "ttl_seconds": normalized.ttl_seconds,
        "valid_until": normalized.valid_until,
        "tags": list(normalized.tags),
        "entities": list(normalized.entities),
        "evidence_turn_id": normalized.evidence_turn_id or None,
        "source_message_ids": list(normalized.source_message_ids),
        "last_accessed_at": normalized.last_accessed_at,
        "last_seen_at": normalized.last_seen_at,
        "access_count": int(normalized.access_count),
        "effective_from": normalized.effective_from,
        "effective_to": normalized.effective_to,
        "supersedes": normalized.supersedes,
        "superseded_by": normalized.superseded_by,
        "superseded_by_memory_id": normalized.superseded_by_memory_id,
        "vector_id": normalized.vector_id,
        "raw_evidence": _json_ready(normalized.raw_evidence or {}),
        "schema_version": normalized.schema_version,
        "extra": dict(normalized.extra),
    }


def _model_to_record(model: MemoryRecordModel) -> MemoryRecord:
    payload = {
        "memory_id": model.memory_id,
        "user_id": model.user_id,
        "session_id": model.session_id,
        "source_session_id": getattr(model, "source_session_id", model.session_id),
        "project_id": model.project_id,
        "topic": model.topic,
        "normalized_key": getattr(model, "normalized_key", None),
        "normalized_value": getattr(model, "normalized_value", None),
        "type": model.memory_type,
        "scope": model.scope,
        "persistence_scope": getattr(model, "persistence_scope", "long_term"),
        "status": model.status,
        "source": model.source,
        "summary": model.summary,
        "content": model.content or {},
        "confidence": float(model.confidence or 0.0),
        "importance": float(model.importance or 0.0),
        "stability": float(model.stability or 0.5),
        "sensitivity": model.sensitivity,
        "retrieval_mode": model.retrieval_mode,
        "should_vectorize": bool(model.should_vectorize),
        "ttl_seconds": model.ttl_seconds,
        "valid_until": model.valid_until,
        "tags": list(model.tags or []),
        "entities": list(model.entities or []),
        "source_turn_id": model.evidence_turn_id or "",
        "source_message_ids": list(model.source_message_ids or []),
        "created_at": model.created_at,
        "updated_at": model.updated_at,
        "last_accessed_at": model.last_accessed_at,
        "last_seen_at": getattr(model, "last_seen_at", None),
        "access_count": int(model.access_count or 0),
        "is_active": getattr(model, "is_active", True),
        "effective_from": getattr(model, "effective_from", None),
        "effective_to": getattr(model, "effective_to", None),
        "supersedes": model.supersedes,
        "superseded_by": model.superseded_by,
        "superseded_by_memory_id": getattr(model, "superseded_by_memory_id", None),
        "embedding_id": model.vector_id,
        "raw_evidence": dict(model.raw_evidence or {}),
        "schema_version": model.schema_version,
        "extra": dict(model.extra or {}),
    }
    return MemoryRecord.model_validate(payload)


def _memory_edge_to_domain(model: MemoryEdgeModel) -> MemoryEdge:
    return MemoryEdge.model_validate(
        {
            "edge_id": model.edge_id,
            "source_memory_id": model.source_memory_id,
            "target_memory_id": model.target_memory_id,
            "edge_type": model.edge_type,
            "reason": model.reason,
            "created_at": model.created_at,
            "updated_at": model.updated_at,
            "extra": dict(model.extra or {}),
        }
    )


def _access_log_to_domain(model: MemoryAccessLogModel) -> MemoryAccessLog:
    return MemoryAccessLog.model_validate(
        {
            "access_log_id": model.access_log_id,
            "memory_id": model.memory_id,
            "user_id": model.user_id,
            "session_id": model.session_id,
            "turn_id": model.turn_id,
            "action": model.action,
            "accessed_at": model.accessed_at,
            "trace_id": model.trace_id,
            "extra": dict(model.extra or {}),
        }
    )


def _deletion_job_to_domain(model: MemoryDeletionJobModel) -> MemoryDeletionJob:
    return MemoryDeletionJob.model_validate(
        {
            "deletion_job_id": model.deletion_job_id,
            "memory_id": model.memory_id,
            "user_id": model.user_id,
            "session_id": model.session_id,
            "target_store": model.target_store,
            "status": model.status,
            "reason": model.reason,
            "scheduled_at": model.scheduled_at,
            "executed_at": model.executed_at,
            "error_message": model.error_message,
            "vector_id": model.vector_id,
            "extra": dict(model.extra or {}),
        }
    )


def _candidate_to_domain(model: MemoryCandidateModel) -> MemoryCandidate:
    return MemoryCandidate.model_validate(
        {
            "candidate_id": model.candidate_id,
            "memory_id": model.memory_id,
            "user_id": model.user_id,
            "session_id": model.session_id,
            "project_id": model.project_id,
            "topic": model.topic,
            "memory_type": model.memory_type,
            "target_store": model.target_store,
            "source": model.source,
            "status": model.status,
            "summary": model.summary,
            "content": model.content or {},
            "confidence": float(model.confidence or 0.0),
            "importance": float(model.importance or 0.0),
            "stability": float(model.stability or 0.5),
            "sensitivity": model.sensitivity,
            "retrieval_mode": model.retrieval_mode,
            "should_vectorize": bool(model.should_vectorize),
            "ttl_seconds": model.ttl_seconds,
            "valid_until": model.valid_until,
            "evidence_turn_id": model.evidence_turn_id,
            "source_message_ids": list(model.source_message_ids or []),
            "last_accessed_at": model.last_accessed_at,
            "access_count": int(model.access_count or 0),
            "supersedes": model.supersedes,
            "superseded_by": model.superseded_by,
            "vector_id": model.vector_id,
            "raw_evidence": dict(model.raw_evidence or {}),
            "governance_action": model.governance_action,
            "require_confirmation": bool(model.require_confirmation),
            "approval_notes": list(model.approval_notes or []),
            "decision_reason": model.decision_reason,
            "conflict_ids": list(model.conflict_ids or []),
            "deletion_job_ids": list(model.deletion_job_ids or []),
            "skip_reason": model.skip_reason,
            "extra": dict(model.extra or {}),
        }
    )


class MemoryRecordRepository(SqlAlchemyRepositoryBase):
    """SQLAlchemy repository for governed memory records."""

    def create(self, record: MemoryRecord) -> MemoryRecord:
        self._require_sqlalchemy()
        fields = _record_to_model_fields(record)
        for attempt in range(2):
            try:
                with self.session_scope() as session:
                    normalized_key = fields.get("normalized_key")
                    active_rows = []
                    if normalized_key and fields.get("is_active", True):
                        active_rows = list(
                            session.execute(
                                select(MemoryRecordModel).where(
                                    MemoryRecordModel.user_id == fields["user_id"],
                                    MemoryRecordModel.normalized_key == normalized_key,
                                    MemoryRecordModel.is_active.is_(True),
                                )
                            ).scalars()
                        )
                    if active_rows:
                        for row in active_rows:
                            if row.normalized_value == fields.get("normalized_value") and row.status == fields.get("status"):
                                for key, value in fields.items():
                                    if key == "memory_id":
                                        continue
                                    setattr(row, key, value)
                                row.updated_at = _utcnow()
                                row.last_seen_at = fields.get("last_seen_at") or _utcnow()
                                session.add(row)
                                session.flush()
                                return _model_to_record(row)
                            row.status = _enum_value(MemoryStatus.INACTIVE)
                            row.is_active = False
                            row.effective_to = fields.get("effective_from") or _utcnow()
                            row.updated_at = _utcnow()
                            session.add(row)
                    instance = session.execute(
                        select(MemoryRecordModel).where(MemoryRecordModel.memory_id == fields["memory_id"])
                    ).scalar_one_or_none()
                    if instance is None:
                        instance = MemoryRecordModel(memory_id=fields["memory_id"], user_id=fields["user_id"])
                    for key, value in fields.items():
                        if key == "memory_id":
                            continue
                        setattr(instance, key, value)
                    instance.updated_at = _utcnow()
                    session.add(instance)
                    session.flush()
                    return _model_to_record(instance)
            except IntegrityError:
                if attempt == 0:
                    continue
                raise
        raise RuntimeError("Unreachable")

    def upsert(self, record: MemoryRecord) -> MemoryRecord:
        return self.create(record)

    def get(self, memory_id: str) -> MemoryRecord | None:
        self._require_sqlalchemy()
        with self.session_scope() as session:
            model = session.execute(
                select(MemoryRecordModel).where(MemoryRecordModel.memory_id == memory_id)
            ).scalar_one_or_none()
            return _model_to_record(model) if model is not None else None

    def find_active_by_user(self, user_id: str) -> list[MemoryRecord]:
        self._require_sqlalchemy()
        now = _utcnow()
        with self.session_scope() as session:
            models = list(
                session.execute(
                    select(MemoryRecordModel).where(
                        MemoryRecordModel.user_id == user_id,
                        MemoryRecordModel.is_active.is_(True),
                        MemoryRecordModel.status.in_(
                            [
                                _enum_value(MemoryStatus.ACTIVE),
                                _enum_value(MemoryStatus.CONFIRMED),
                            ]
                        ),
                        MemoryRecordModel.scope.in_(["user", "project", "global"]),
                        MemoryRecordModel.should_vectorize.is_(True),
                    )
                ).scalars()
            )
        models.sort(
            key=lambda item: (
                item.last_accessed_at or item.updated_at,
                item.updated_at,
                item.importance,
                item.confidence,
            ),
            reverse=True,
        )
        return [
            _model_to_record(model)
            for model in models
            if _is_active_at(model, now)
        ]

    def iter_reindexable_records(self) -> list[MemoryRecord]:
        self._require_sqlalchemy()
        now = _utcnow()
        with self.session_scope() as session:
            models = list(
                session.execute(
                    select(MemoryRecordModel).where(
                        MemoryRecordModel.is_active.is_(True),
                        MemoryRecordModel.should_vectorize.is_(True),
                        MemoryRecordModel.status.in_(
                            [
                                _enum_value(MemoryStatus.ACTIVE),
                                _enum_value(MemoryStatus.CONFIRMED),
                            ]
                        ),
                        MemoryRecordModel.scope.in_(["user", "project", "global"]),
                        MemoryRecordModel.memory_type.in_(["semantic", "episodic", "procedural"]),
                    )
                ).scalars()
            )
        models.sort(key=lambda item: (item.importance, item.confidence, item.updated_at), reverse=True)
        records: list[MemoryRecord] = []
        for model in models:
            if not _is_active_at(model, now):
                continue
            records.append(_model_to_record(model))
        return records

    def list_by_scope(self, user_id: str, scope: MemoryScope) -> list[MemoryRecord]:
        self._require_sqlalchemy()
        now = _utcnow()
        with self.session_scope() as session:
            models = list(
                session.execute(
                    select(MemoryRecordModel).where(
                        MemoryRecordModel.user_id == user_id,
                        MemoryRecordModel.scope == _enum_value(scope),
                        MemoryRecordModel.is_active.is_(True),
                        MemoryRecordModel.should_vectorize.is_(True),
                        MemoryRecordModel.status.in_(
                            [
                                _enum_value(MemoryStatus.ACTIVE),
                                _enum_value(MemoryStatus.CONFIRMED),
                            ]
                        ),
                    )
                ).scalars()
            )
        models.sort(key=lambda item: (item.importance, item.confidence, item.updated_at), reverse=True)
        return [
            _model_to_record(model)
            for model in models
            if _is_active_at(model, now)
        ]

    def search(
        self,
        query: str,
        user_id: str,
        limit: int = 10,
        memory_types: Sequence[MemoryType] | None = None,
    ) -> list[MemoryRecord]:
        self._require_sqlalchemy()
        needle = (query or "").lower().strip()
        allowed_types = {item.value if hasattr(item, "value") else str(item or "").strip().lower() for item in memory_types or []}
        allowed_types = {item for item in allowed_types if item}
        records = self.find_active_by_user(user_id)
        scored: list[tuple[float, MemoryRecord]] = []
        for record in records:
            if record.status in {MemoryStatus.DELETED, MemoryStatus.EXPIRED, MemoryStatus.SUPERSEDED, MemoryStatus.INACTIVE}:
                continue
            if allowed_types and record.type.value not in allowed_types:
                continue
            if not _is_long_term_scope(record.scope):
                continue
            if not _is_searchable_status(record.status):
                continue
            haystack = " ".join(
                [
                    record.summary or "",
                    json.dumps(record.content or {}, ensure_ascii=False, default=str),
                    " ".join(str(tag) for tag in record.tags or []),
                    " ".join(str(entity) for entity in record.entities or []),
                    record.topic or "",
                ]
            ).lower()
            if needle and needle not in haystack:
                continue
            score = (float(record.importance or 0.0) * 0.6) + (float(record.confidence or 0.0) * 0.4)
            scored.append((score, record))
        scored.sort(key=lambda item: (item[0], item[1].updated_at), reverse=True)
        return [item[1] for item in scored[:limit]]

    def find_potential_conflicts(
        self,
        *,
        user_id: str,
        scope: MemoryScope,
        topic: str | None,
        memory_type: MemoryType,
        normalized_key: str | None = None,
    ) -> list[MemoryRecord]:
        self._require_sqlalchemy()
        with self.session_scope() as session:
            models = list(
                session.execute(
                    select(MemoryRecordModel).where(
                        MemoryRecordModel.user_id == user_id,
                        MemoryRecordModel.scope == _enum_value(scope),
                        MemoryRecordModel.memory_type == _enum_value(memory_type),
                        MemoryRecordModel.is_active.is_(True),
                        MemoryRecordModel.should_vectorize.is_(True),
                        MemoryRecordModel.status.in_(
                            [
                                _enum_value(MemoryStatus.ACTIVE),
                                _enum_value(MemoryStatus.CONFIRMED),
                            ]
                        ),
                    )
                ).scalars()
            )
        candidates = []
        for model in models:
            if _enum_value(model.status) in {
                _enum_value(MemoryStatus.DELETED),
                _enum_value(MemoryStatus.EXPIRED),
                _enum_value(MemoryStatus.SUPERSEDED),
                _enum_value(MemoryStatus.INACTIVE),
            }:
                continue
            if normalized_key and (model.normalized_key or "") != normalized_key:
                continue
            if topic and model.topic and model.topic != topic:
                continue
            candidates.append(_model_to_record(model))
        candidates.sort(key=lambda item: (item.updated_at, item.confidence, item.importance), reverse=True)
        return candidates

    def update_status(self, memory_id: str, status: MemoryStatus) -> MemoryRecord | None:
        self._require_sqlalchemy()
        with self.session_scope() as session:
            model = session.execute(
                select(MemoryRecordModel).where(MemoryRecordModel.memory_id == memory_id)
            ).scalar_one_or_none()
            if model is None:
                return None
            model.status = _enum_value(status)
            model.is_active = status not in {MemoryStatus.DELETED, MemoryStatus.EXPIRED, MemoryStatus.SUPERSEDED, MemoryStatus.INACTIVE}
            if not model.is_active:
                model.effective_to = _utcnow()
            model.updated_at = _utcnow()
            session.add(model)
            session.flush()
            return _model_to_record(model)

    def mark_superseded(
        self,
        memory_id: str,
        superseded_by: str,
        reason: str,
        edge_type: MemoryEdgeType = MemoryEdgeType.SUPERSEDES,
    ) -> MemoryEdge | None:
        self._require_sqlalchemy()
        with self.session_scope() as session:
            source = session.execute(
                select(MemoryRecordModel).where(MemoryRecordModel.memory_id == memory_id)
            ).scalar_one_or_none()
            target = session.execute(
                select(MemoryRecordModel).where(MemoryRecordModel.memory_id == superseded_by)
            ).scalar_one_or_none()
            if source is None:
                return None
            source.status = _enum_value(MemoryStatus.SUPERSEDED)
            source.superseded_by = superseded_by
            source.superseded_by_memory_id = superseded_by
            source.is_active = False
            source.effective_to = _utcnow()
            source.updated_at = _utcnow()
            session.add(source)
            eff_to = _ensure_aware(source.effective_to)
            edge = self._create_edge_row(
                source_memory_id=memory_id,
                target_memory_id=superseded_by,
                edge_type=edge_type,
                reason=reason,
                extra={
                    "source_status": source.status,
                    "target_status": target.status if target is not None else None,
                    "effective_to": eff_to.isoformat() if eff_to else None,
                },
            )
            session.add(edge)
            session.flush()
            return _memory_edge_to_domain(edge)

    def soft_delete(self, memory_id: str, reason: str) -> MemoryRecord | None:
        self._require_sqlalchemy()
        with self.session_scope() as session:
            model = session.execute(
                select(MemoryRecordModel).where(MemoryRecordModel.memory_id == memory_id)
            ).scalar_one_or_none()
            if model is None:
                return None
            if _enum_value(model.status) == _enum_value(MemoryStatus.DELETED):
                return _model_to_record(model)
            model.status = _enum_value(MemoryStatus.DELETED)
            model.is_active = False
            model.effective_to = _utcnow()
            model.updated_at = _utcnow()
            session.add(model)
            jobs = self._build_deletion_jobs(
                memory_id=memory_id,
                user_id=model.user_id,
                session_id=model.session_id,
                vector_id=model.vector_id,
                reason=reason,
            )
            for job in jobs:
                session.add(job)
            session.flush()
            return _model_to_record(model)

    def increment_access_count(self, memory_id: str) -> MemoryRecord | None:
        self._require_sqlalchemy()
        with self.session_scope() as session:
            model = session.execute(
                select(MemoryRecordModel).where(MemoryRecordModel.memory_id == memory_id)
            ).scalar_one_or_none()
            if model is None:
                return None
            model.access_count = int(model.access_count or 0) + 1
            model.last_accessed_at = _utcnow()
            model.updated_at = _utcnow()
            session.add(model)
            session.add(
                MemoryAccessLogModel(
                    access_log_id=f"access:{uuid4().hex}",
                    memory_id=memory_id,
                    user_id=model.user_id,
                    session_id=model.session_id,
                    turn_id=model.evidence_turn_id,
                    action="read",
                    trace_id=None,
                    extra={"access_count": model.access_count},
                )
            )
            session.flush()
            return _model_to_record(model)

    def mark_accessed(self, memory_id: str) -> MemoryRecord | None:
        return self.increment_access_count(memory_id)

    def list_deletion_jobs(
        self,
        *,
        status: MemoryDeletionStatus | None = None,
    ) -> list[MemoryDeletionJob]:
        self._require_sqlalchemy()
        with self.session_scope() as session:
            query = select(MemoryDeletionJobModel)
            if status is not None:
                query = query.where(MemoryDeletionJobModel.status == _enum_value(status))
            models = list(session.execute(query).scalars())
        models.sort(key=lambda item: item.scheduled_at, reverse=True)
        return [_deletion_job_to_domain(model) for model in models]

    def list_access_logs(self, memory_id: str) -> list[MemoryAccessLog]:
        self._require_sqlalchemy()
        with self.session_scope() as session:
            models = list(
                session.execute(
                    select(MemoryAccessLogModel).where(MemoryAccessLogModel.memory_id == memory_id)
                ).scalars()
            )
        models.sort(key=lambda item: item.accessed_at, reverse=True)
        return [_access_log_to_domain(model) for model in models]

    def create_edge(self, edge: MemoryEdge) -> MemoryEdge:
        self._require_sqlalchemy()
        with self.session_scope() as session:
            instance = self._create_edge_row(
                source_memory_id=edge.source_memory_id,
                target_memory_id=edge.target_memory_id,
                edge_type=edge.edge_type,
                reason=edge.reason,
                extra=dict(edge.extra or {}),
                edge_id=edge.edge_id or f"edge:{uuid4().hex}",
            )
            session.add(instance)
            session.flush()
            return _memory_edge_to_domain(instance)

    def create_candidate(self, candidate: MemoryCandidateModel) -> MemoryCandidateModel:
        self._require_sqlalchemy()
        with self.session_scope() as session:
            instance = session.execute(
                select(MemoryCandidateModel).where(MemoryCandidateModel.candidate_id == candidate.candidate_id)
            ).scalar_one_or_none()
            if instance is None:
                instance = candidate
            else:
                for key, value in candidate.__dict__.items():
                    if key.startswith("_"):
                        continue
                    setattr(instance, key, value)
            session.add(instance)
            session.flush()
            return instance

    def get_candidate(self, candidate_id: str) -> MemoryCandidate | None:
        self._require_sqlalchemy()
        with self.session_scope() as session:
            model = session.execute(
                select(MemoryCandidateModel).where(MemoryCandidateModel.candidate_id == candidate_id)
            ).scalar_one_or_none()
            return _candidate_to_domain(model) if model is not None else None

    def update_candidate(
        self,
        candidate_id: str,
        *,
        status: str | None = None,
        governance_action: str | None = None,
        require_confirmation: bool | None = None,
        decision_reason: str | None = None,
        conflict_ids: list[str] | None = None,
        deletion_job_ids: list[str] | None = None,
        skip_reason: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> MemoryCandidate | None:
        self._require_sqlalchemy()
        with self.session_scope() as session:
            model = session.execute(
                select(MemoryCandidateModel).where(MemoryCandidateModel.candidate_id == candidate_id)
            ).scalar_one_or_none()
            if model is None:
                return None
            if status is not None:
                model.status = status
            if governance_action is not None:
                model.governance_action = governance_action
            if require_confirmation is not None:
                model.require_confirmation = require_confirmation
            if decision_reason is not None:
                model.decision_reason = decision_reason
            if conflict_ids is not None:
                model.conflict_ids = list(conflict_ids)
            if deletion_job_ids is not None:
                model.deletion_job_ids = list(deletion_job_ids)
            if skip_reason is not None:
                model.skip_reason = skip_reason
            if extra is not None:
                model.extra = dict(extra)
            model.updated_at = _utcnow()
            session.add(model)
            session.flush()
            return _candidate_to_domain(model)

    def list_candidates(self, user_id: str | None = None) -> list[MemoryCandidate]:
        self._require_sqlalchemy()
        with self.session_scope() as session:
            query = select(MemoryCandidateModel)
            if user_id is not None:
                query = query.where(MemoryCandidateModel.user_id == user_id)
            models = list(session.execute(query).scalars())
        models.sort(key=lambda item: (item.updated_at, item.created_at), reverse=True)
        return [_candidate_to_domain(model) for model in models]

    def mark_deletion_job_running(self, deletion_job_id: str) -> MemoryDeletionJob | None:
        return self._update_deletion_job_status(deletion_job_id, MemoryDeletionStatus.RUNNING)

    def mark_deletion_job_succeeded(self, deletion_job_id: str) -> MemoryDeletionJob | None:
        self._require_sqlalchemy()
        with self.session_scope() as session:
            model = session.execute(
                select(MemoryDeletionJobModel).where(MemoryDeletionJobModel.deletion_job_id == deletion_job_id)
            ).scalar_one_or_none()
            if model is None:
                return None
            model.status = _enum_value(MemoryDeletionStatus.SUCCEEDED)
            model.executed_at = _utcnow()
            model.error_message = None
            session.add(model)
            session.flush()
            return _deletion_job_to_domain(model)

    def mark_deletion_job_failed(self, deletion_job_id: str, error_message: str) -> MemoryDeletionJob | None:
        self._require_sqlalchemy()
        with self.session_scope() as session:
            model = session.execute(
                select(MemoryDeletionJobModel).where(MemoryDeletionJobModel.deletion_job_id == deletion_job_id)
            ).scalar_one_or_none()
            if model is None:
                return None
            model.status = _enum_value(MemoryDeletionStatus.FAILED)
            model.executed_at = _utcnow()
            model.error_message = error_message
            session.add(model)
            session.flush()
            return _deletion_job_to_domain(model)

    def claim_deletion_jobs(self, limit: int = 20) -> list[MemoryDeletionJob]:
        self._require_sqlalchemy()
        with self.session_scope() as session:
            models = list(
                session.execute(
                    select(MemoryDeletionJobModel)
                    .where(
                        MemoryDeletionJobModel.status.in_(
                            [
                                _enum_value(MemoryDeletionStatus.PENDING),
                                _enum_value(MemoryDeletionStatus.FAILED),
                            ]
                        )
                    )
                    .order_by(MemoryDeletionJobModel.scheduled_at.asc())
                    .limit(limit)
                ).scalars()
            )
            for model in models:
                model.status = _enum_value(MemoryDeletionStatus.RUNNING)
                session.add(model)
            session.flush()
        return [_deletion_job_to_domain(model) for model in models]

    def create_edge_row(
        self,
        *,
        source_memory_id: str,
        target_memory_id: str,
        edge_type: MemoryEdgeType,
        reason: str,
        extra: dict[str, Any] | None = None,
        edge_id: str | None = None,
    ) -> MemoryEdgeModel:
        return self._create_edge_row(
            source_memory_id=source_memory_id,
            target_memory_id=target_memory_id,
            edge_type=edge_type,
            reason=reason,
            extra=extra or {},
            edge_id=edge_id,
        )

    def _build_deletion_jobs(
        self,
        *,
        memory_id: str,
        user_id: str,
        session_id: str | None,
        vector_id: str | None,
        reason: str,
    ) -> list[MemoryDeletionJobModel]:
        jobs: list[MemoryDeletionJobModel] = []
        for target_store in (
            MemoryTargetStore.POSTGRES,
            MemoryTargetStore.QDRANT,
            MemoryTargetStore.REDIS,
        ):
            jobs.append(
                MemoryDeletionJobModel(
                    deletion_job_id=f"del:{uuid4().hex}",
                    memory_id=memory_id,
                    user_id=user_id,
                    session_id=session_id,
                    target_store=_enum_value(target_store),
                    status=_enum_value(MemoryDeletionStatus.PENDING),
                    reason=reason,
                    vector_id=vector_id,
                    extra={"reason": reason, "target_store": _enum_value(target_store)},
                )
            )
        return jobs

    def _create_edge_row(
        self,
        *,
        source_memory_id: str,
        target_memory_id: str,
        edge_type: MemoryEdgeType,
        reason: str,
        extra: dict[str, Any] | None = None,
        edge_id: str | None = None,
    ) -> MemoryEdgeModel:
        return MemoryEdgeModel(
            edge_id=edge_id or f"edge:{uuid4().hex}",
            source_memory_id=source_memory_id,
            target_memory_id=target_memory_id,
            edge_type=_enum_value(edge_type),
            reason=reason,
            extra=dict(extra or {}),
        )

    def _update_deletion_job_status(
        self,
        deletion_job_id: str,
        status: MemoryDeletionStatus,
    ) -> MemoryDeletionJob | None:
        self._require_sqlalchemy()
        with self.session_scope() as session:
            model = session.execute(
                select(MemoryDeletionJobModel).where(MemoryDeletionJobModel.deletion_job_id == deletion_job_id)
            ).scalar_one_or_none()
            if model is None:
                return None
            model.status = _enum_value(status)
            if status == MemoryDeletionStatus.RUNNING:
                model.executed_at = None
                model.error_message = None
            session.add(model)
            session.flush()
            return _deletion_job_to_domain(model)
