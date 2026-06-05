from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from learning_agent_service.domain.memory import (
    LongTermMemoryStore,
    MemoryEdge,
    MemoryEdgeType,
    MemoryRecord,
    MemoryRetrievalMode,
    MemoryScope,
    MemorySensitivity,
    MemorySource,
    MemoryStatus,
    MemoryType,
)
from learning_agent_service.infrastructure.db.models import LongTermMemoryModel
from learning_agent_service.infrastructure.repositories.memory_outbox import MemoryOutboxRepository
from learning_agent_service.infrastructure.repositories.memory_record_repository import (
    MemoryRecordRepository,
)
from learning_agent_service.infrastructure.repositories.records import MemoryOutboxRecord
from learning_agent_service.memory.gates import MemoryVectorizationGate
from learning_agent_service.memory.models import SemanticMemoryFact
from learning_agent_service.memory.protocols import SemanticMemoryStore

from learning_agent_service.domain.utils import utcnow as _utcnow

from .qdrant_store import QdrantLongTermMemoryIndex

try:  # pragma: no cover - optional runtime dependency
    from sqlalchemy import select
except Exception:  # pragma: no cover - import-tolerant fallback
    select = None


def _json_ready(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str, ensure_ascii=False))


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


def _record_to_model_fields(record: MemoryRecord) -> dict[str, Any]:
    return {
        "memory_id": record.memory_id or f"{record.user_id}:{record.source_turn_id}:{record.type.value}:{uuid4().hex[:12]}",
        "user_id": record.user_id,
        "session_id": record.session_id,
        "project_id": record.project_id,
        "memory_type": _enum_value(record.type),
        "scope": _enum_value(record.scope),
        "status": _enum_value(record.status),
        "source": _enum_value(record.metadata.source if record.metadata else MemorySource.SYSTEM_EVENT),
        "source_turn_id": record.source_turn_id,
        "source_message_ids": list(record.source_message_ids),
        "content": _json_ready(record.content),
        "summary": record.summary,
        "tags": list(record.tags),
        "entities": list(record.entities),
        "confidence": float(record.confidence),
        "importance": float(record.importance),
        "last_accessed_at": record.last_accessed_at,
        "expires_at": record.expires_at,
        "supersedes": record.supersedes,
        "embedding_id": record.vector_id or record.memory_id or None,
        "schema_version": record.schema_version,
        "extra": {
            "metadata": record.metadata.model_dump(mode="json") if record.metadata else None,
        },
    }


def _model_to_record(model: LongTermMemoryModel) -> MemoryRecord:
    extra = dict(model.extra or {})
    metadata_payload = extra.get("metadata") if isinstance(extra, Mapping) else None
    payload = {
        "memory_id": model.memory_id,
        "user_id": model.user_id,
        "session_id": model.session_id,
        "project_id": model.project_id,
        "type": model.memory_type,
        "scope": model.scope,
        "status": model.status,
        "content": model.content or {},
        "summary": model.summary,
        "tags": list(model.tags or []),
        "entities": list(model.entities or []),
        "source_turn_id": model.source_turn_id,
        "source_message_ids": list(model.source_message_ids or []),
        "confidence": float(model.confidence or 0.0),
        "importance": float(model.importance or 0.0),
        "created_at": model.created_at,
        "updated_at": model.updated_at,
        "last_accessed_at": model.last_accessed_at,
        "expires_at": model.expires_at,
        "supersedes": model.supersedes,
        "embedding_id": model.embedding_id,
        "schema_version": model.schema_version,
    }
    record = MemoryRecord.model_validate(payload)
    if metadata_payload and isinstance(metadata_payload, Mapping):
        record.metadata = record.metadata.model_copy(
            update={
                "source": _enum_or_default(MemorySource, metadata_payload.get("source"), record.metadata.source),
                "tags": list(metadata_payload.get("tags", record.metadata.tags)),
                "entities": list(metadata_payload.get("entities", record.metadata.entities)),
                "confidence": metadata_payload.get("confidence", record.metadata.confidence),
                "importance": metadata_payload.get("importance", record.metadata.importance),
            }
        )
    return record


def _record_to_semantic_fact(record: MemoryRecord) -> SemanticMemoryFact:
    metadata = {}
    if isinstance(record.content, Mapping):
        metadata = dict(record.content.get("metadata") or {})
        content = record.content.get("content") or record.summary or ""
        fact_type = str(record.content.get("fact_type") or (record.tags[0] if record.tags else "semantic"))
        topic = str(record.content.get("topic") or (record.entities[0] if record.entities else record.summary or "topic"))
    else:
        content = record.summary or str(record.content)
        fact_type = record.tags[0] if record.tags else "semantic"
        topic = record.entities[0] if record.entities else record.summary or "topic"
    return SemanticMemoryFact(
        fact_id=record.memory_id,
        topic=str(topic),
        content=str(content),
        fact_type=str(fact_type),
        strength=float(record.confidence or 0.5),
        created_at=record.created_at,
        last_referenced_at=record.last_accessed_at,
        metadata=metadata if metadata else (dict(record.content.get("metadata", {})) if isinstance(record.content, Mapping) else {}),
    )


def _payload_for_qdrant(record: MemoryRecord) -> dict[str, Any]:
    return {
        "memory_id": record.memory_id,
        "user_id": record.user_id,
        "session_id": record.session_id,
        "project_id": record.project_id,
        "memory_type": _enum_value(record.type),
        "scope": _enum_value(record.scope),
        "status": _enum_value(record.status),
        "is_active": bool(record.is_active),
        "should_vectorize": bool(record.should_vectorize),
        "normalized_key": record.normalized_key,
        "topic": record.topic,
        "summary": record.summary,
        "tags": list(record.tags or []),
        "entities": list(record.entities or []),
        "confidence": float(record.confidence or 0.0),
        "importance": float(record.importance or 0.0),
        "stability": float(record.stability or 0.0),
        "sensitivity": _enum_value(record.sensitivity),
        "source": _enum_value(record.source),
        "source_turn_id": record.source_turn_id,
        "source_session_id": record.source_session_id,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        "effective_from": record.effective_from.isoformat() if record.effective_from else None,
        "effective_to": record.effective_to.isoformat() if record.effective_to else None,
        "valid_until": record.valid_until.isoformat() if record.valid_until else None,
        "schema_version": record.schema_version,
    }


def _fact_to_record(user_id: str, fact: SemanticMemoryFact) -> MemoryRecord:
    metadata = dict(fact.metadata or {})
    fact_type = str(metadata.get("fact_type") or fact.fact_type or "semantic").strip().lower()
    session_only_fact = fact_type in {
        "session_fact",
        "session_summary",
        "session_event",
        "clarification_result",
        "clarification_event",
        "missing_slots",
        "ambiguous_query",
    }

    def _enum_value_or(default: str, value: Any, enum_cls: Any) -> Any:
        if value is None:
            return enum_cls(default)
        if hasattr(value, "value"):
            return value
        try:
            return enum_cls(str(value).strip().lower())
        except Exception:
            return enum_cls(default)

    scope_value = metadata.get("scope") or ("session" if session_only_fact else "user")
    status_value = metadata.get("status") or ("observed" if session_only_fact else "confirmed")
    source_value = metadata.get("source") or (MemorySource.SYSTEM_EVENT.value if session_only_fact else MemorySource.MODEL_INFERRED.value)
    should_vectorize = bool(metadata.get("should_vectorize", not session_only_fact))
    confidence = float(metadata.get("confidence") or fact.strength or 0.0)
    importance = float(metadata.get("importance") or fact.strength or 0.0)
    stability = float(metadata.get("stability") or fact.strength or 0.0)
    ttl_seconds = metadata.get("ttl_seconds")
    valid_until = metadata.get("valid_until")
    effective_from = metadata.get("effective_from") or fact.created_at or _utcnow()
    effective_to = metadata.get("effective_to")
    record = MemoryRecord(
        memory_id=str(fact.fact_id or f"{user_id}:{fact.topic}:{uuid4().hex[:12]}"),
        user_id=user_id,
        session_id=metadata.get("session_id"),
        source_session_id=metadata.get("source_session_id") or metadata.get("session_id"),
        project_id=metadata.get("project_id"),
        topic=str(metadata.get("topic") or fact.topic or ""),
        normalized_key=metadata.get("normalized_key"),
        normalized_value=metadata.get("normalized_value"),
        type=_enum_value_or("short_term" if session_only_fact else "semantic", metadata.get("memory_type") or ("short_term" if session_only_fact else "semantic"), MemoryType),
        scope=_enum_value_or("session" if session_only_fact else "user", scope_value, MemoryScope),
        status=_enum_value_or("observed" if session_only_fact else "confirmed", status_value, MemoryStatus),
        source=_enum_value_or("model_inferred", source_value, MemorySource),
        content={
            "topic": fact.topic,
            "content": fact.content,
            "fact_type": fact.fact_type,
            "metadata": metadata,
        },
        summary=fact.content,
        confidence=confidence,
        importance=0.2 if session_only_fact and importance > 0.2 else importance,
        stability=0.2 if session_only_fact and stability > 0.2 else stability,
        sensitivity=_enum_value_or("public", metadata.get("sensitivity") or "public", MemorySensitivity),
        retrieval_mode=_enum_value_or("auto", metadata.get("retrieval_mode") or "auto", MemoryRetrievalMode),
        should_vectorize=False if session_only_fact else should_vectorize,
        ttl_seconds=int(ttl_seconds) if ttl_seconds not in {None, ""} else (3600 if session_only_fact else None),
        valid_until=valid_until,
        tags=list(dict.fromkeys([str(tag) for tag in metadata.get("tags", [])] + [fact.fact_type, fact.topic])),
        entities=list(dict.fromkeys([str(entity) for entity in metadata.get("entities", [])] + [fact.topic])),
        source_turn_id=str(metadata.get("source_turn_id") or fact.fact_id or ""),
        source_message_ids=list(metadata.get("source_message_ids") or []),
        created_at=fact.created_at or _utcnow(),
        updated_at=fact.last_referenced_at or fact.created_at or _utcnow(),
        last_accessed_at=fact.last_referenced_at,
        effective_from=effective_from,
        effective_to=effective_to,
        raw_evidence=dict(metadata.get("raw_evidence") or {}),
    )
    return record


class LongTermMemoryRepository(MemoryRecordRepository):
    """Backward-compatible alias for the governed memory repository."""

    pass


@dataclass
class DurableLongTermMemoryStore(LongTermMemoryStore):
    """Composite long-term memory adapter that writes metadata to Postgres and vectors to Qdrant."""

    repository: LongTermMemoryRepository
    index: QdrantLongTermMemoryIndex | None = None
    memory_outbox_repository: MemoryOutboxRepository | None = None
    vectorization_gate: MemoryVectorizationGate = field(default_factory=MemoryVectorizationGate)
    last_qdrant_error: str | None = None

    @property
    def collection_name(self) -> str:
        return str(getattr(self.index, "collection_name", "") or "")

    def upsert(self, record: MemoryRecord) -> MemoryRecord:
        self.last_qdrant_error = None
        stored = record.model_copy(
            update={
                "memory_id": record.memory_id or f"{record.user_id}:{record.source_turn_id}:{record.type.value}:{uuid4().hex[:12]}",
                "embedding_id": record.vector_id or record.embedding_id or record.memory_id or None,
                "updated_at": _utcnow(),
            }
        )
        stored_record = self.repository.upsert(stored)
        vectorization_decision = self.vectorization_gate.should_vectorize(stored_record)
        if self.index is not None and vectorization_decision.allowed:
            payload = _payload_for_qdrant(stored_record)
            if self.memory_outbox_repository is not None:
                self._enqueue_memory_outbox(
                    event_type="memory.vector.upsert",
                    record=stored_record,
                    payload={
                        "memory_id": stored_record.memory_id,
                        "vector_id": stored_record.vector_id,
                        "payload": payload,
                        "vectorization_reason": vectorization_decision.reason,
                    },
                )
                self.process_memory_outbox_once(limit=10)
            else:
                try:
                    embedding_id = self.index.upsert(stored_record)
                except Exception as exc:
                    self.last_qdrant_error = type(exc).__name__
                    stored_record = stored_record.model_copy(
                        update={
                            "extra": {
                                **dict(stored_record.extra or {}),
                                "qdrant_degraded": True,
                                "qdrant_error": type(exc).__name__,
                            }
                        }
                    )
                else:
                    if getattr(self.index, "last_error", None):
                        self.last_qdrant_error = str(self.index.last_error)
                        stored_record = stored_record.model_copy(
                            update={
                                "extra": {
                                    **dict(stored_record.extra or {}),
                                    "qdrant_degraded": True,
                                    "qdrant_error": str(self.index.last_error),
                                }
                            }
                        )
                    if embedding_id and embedding_id != stored_record.vector_id:
                        stored_record = stored_record.model_copy(update={"embedding_id": embedding_id})
                        stored_record = self.repository.upsert(stored_record)
        return stored_record

    def get(self, memory_id: str) -> MemoryRecord | None:
        return self.repository.get(memory_id)

    def search(
        self,
        query: str,
        user_id: str,
        limit: int = 10,
        memory_types: Sequence[MemoryType] | None = None,
    ) -> Sequence[MemoryRecord]:
        self.last_qdrant_error = None
        if self.index is not None:
            try:
                indexed = list(self.index.search(query, user_id=user_id, limit=limit, memory_types=memory_types))
            except Exception:
                indexed = []
                self.last_qdrant_error = "search_failed"
            else:
                if getattr(self.index, "last_error", None):
                    self.last_qdrant_error = str(self.index.last_error)
            if indexed:
                hydrated: list[MemoryRecord] = []
                memory_types_set = {item.value if hasattr(item, "value") else str(item or "").strip().lower() for item in memory_types or []}
                memory_types_set = {item for item in memory_types_set if item}
                for candidate in indexed:
                    record = self.repository.get(candidate.memory_id)
                    if record is None:
                        continue
                    if memory_types_set and record.type.value not in memory_types_set:
                        continue
                    if not _should_index(record):
                        continue
                    hydrated.append(record)
                    if len(hydrated) >= limit:
                        break
                if hydrated:
                    return hydrated
        return list(self.repository.search(query, user_id=user_id, limit=limit, memory_types=memory_types))

    def list_by_scope(self, user_id: str, scope: MemoryScope) -> Sequence[MemoryRecord]:
        return list(self.repository.list_by_scope(user_id, scope))

    def supersede(
        self,
        memory_id: str,
        superseded_by: str,
        reason: str,
        edge_type: MemoryEdgeType = MemoryEdgeType.SUPERSEDES,
    ) -> None:
        self.repository.mark_superseded(memory_id, superseded_by, reason, edge_type=edge_type)
        current = self.get(memory_id)
        if current is not None and self.index is not None:
            if self.memory_outbox_repository is not None:
                self._enqueue_memory_outbox(
                    event_type="memory.vector.soft_deactivate",
                    record=current,
                    payload={
                        "memory_id": current.memory_id,
                        "vector_id": current.vector_id or current.memory_id,
                        "status": "superseded",
                        "is_active": False,
                        "effective_to": current.effective_to.isoformat() if current.effective_to else None,
                        "superseded_by": superseded_by,
                    },
                )
                self.process_memory_outbox_once(limit=10)
            else:
                self.index.soft_deactivate(
                    current.vector_id or current.memory_id,
                    payload={
                        "memory_id": current.memory_id,
                        "user_id": current.user_id,
                        "status": "superseded",
                        "is_active": False,
                        "effective_to": current.effective_to.isoformat() if current.effective_to else None,
                    },
                )
                if getattr(self.index, "last_error", None):
                    self.last_qdrant_error = str(self.index.last_error)

    def soft_delete(self, memory_id: str, reason: str) -> None:
        self.last_qdrant_error = None
        deleted = self.repository.soft_delete(memory_id, reason)
        if deleted is None:
            return
        current = self.get(memory_id)
        if current is not None and self.index is not None:
            if self.memory_outbox_repository is not None:
                self._enqueue_memory_outbox(
                    event_type="memory.vector.delete",
                    record=current,
                    payload={
                        "memory_id": current.memory_id,
                        "vector_id": current.vector_id or current.memory_id,
                        "status": "deleted",
                        "reason": reason,
                    },
                )
                self.process_memory_outbox_once(limit=10)
            else:
                self.index.delete_many([current.vector_id or current.memory_id])
                if getattr(self.index, "last_error", None):
                    self.last_qdrant_error = str(self.index.last_error)

    def process_memory_outbox_once(self, limit: int = 50) -> dict[str, Any]:
        if self.memory_outbox_repository is None or self.index is None:
            return {"claimed": 0, "published": 0, "failed": 0, "skipped": 0}
        claimed = self.memory_outbox_repository.claim_pending(limit=limit)
        published = 0
        failed = 0
        skipped = 0
        for event in claimed:
            try:
                self._apply_memory_outbox_event(event)
                self.memory_outbox_repository.mark_published(event.id)
                published += 1
            except Exception as exc:
                self.memory_outbox_repository.mark_failed(event.id, str(exc), retry_delay_seconds=0)
                failed += 1
                self.last_qdrant_error = type(exc).__name__
        return {
            "claimed": len(claimed),
            "published": published,
            "failed": failed,
            "skipped": skipped,
        }

    def _enqueue_memory_outbox(self, *, event_type: str, record: MemoryRecord, payload: dict[str, Any]) -> None:
        if self.memory_outbox_repository is None:
            return
        event = MemoryOutboxRecord(
            aggregate_type="memory",
            aggregate_id=record.memory_id,
            memory_id=record.memory_id,
            user_id=record.user_id,
            session_id=record.session_id,
            turn_id=record.source_turn_id,
            event_type=event_type,
            dedupe_key=f"{record.memory_id}:{event_type}",
            payload=dict(payload),
            status="pending",
            trace_id=str(record.extra.get("trace_id")) if isinstance(record.extra, Mapping) and record.extra.get("trace_id") else None,
            vector_id=record.vector_id or record.embedding_id or record.memory_id,
            extra={
                "memory_type": record.type.value,
                "normalized_key": record.normalized_key,
                "normalized_value": record.normalized_value,
            },
        )
        self.memory_outbox_repository.enqueue(event)

    def _apply_memory_outbox_event(self, event: Any) -> None:
        event_type = str(getattr(event, "event_type", "") or "")
        payload = getattr(event, "payload", None) or {}
        memory_id = str(getattr(event, "memory_id", "") or payload.get("memory_id") or "")
        vector_id = str(getattr(event, "vector_id", "") or payload.get("vector_id") or memory_id)
        if event_type == "memory.vector.upsert":
            record = self.get(memory_id)
            if record is None:
                record_payload = payload.get("record")
                if isinstance(record_payload, Mapping):
                    record = MemoryRecord.model_validate(record_payload)
                else:
                    record = self.get(memory_id)
            if record is None:
                return
            self.index.upsert(record)
            if getattr(self.index, "last_error", None):
                raise RuntimeError(str(self.index.last_error))
            return
        if event_type == "memory.vector.soft_deactivate":
            self.index.soft_deactivate(
                vector_id or memory_id,
                payload={
                    "memory_id": memory_id,
                    "user_id": getattr(event, "user_id", None) or payload.get("user_id"),
                    "status": "superseded",
                    "is_active": False,
                    "effective_to": payload.get("effective_to"),
                },
            )
            if getattr(self.index, "last_error", None):
                raise RuntimeError(str(self.index.last_error))
            return
        if event_type == "memory.vector.delete":
            self.index.delete_many([vector_id or memory_id])
            if getattr(self.index, "last_error", None):
                raise RuntimeError(str(self.index.last_error))
            return
        raise RuntimeError(f"unsupported memory outbox event: {event_type}")

    def create_edge(self, edge: MemoryEdge) -> MemoryEdge:
        return self.repository.create_edge(edge)


@dataclass
class DurableSemanticMemoryStore(SemanticMemoryStore):
    """Semantic memory adapter that persists facts as long-term memory records."""

    long_term_store: DurableLongTermMemoryStore
    indexed_topics: dict[tuple[str, str], bool] = field(default_factory=dict)

    def search(self, user_id: str, query: str, limit: int = 5) -> Sequence[SemanticMemoryFact]:
        records = self.long_term_store.search(query, user_id=user_id, limit=limit, memory_types=(MemoryType.SEMANTIC,))
        facts: list[SemanticMemoryFact] = []
        for record in records:
            if record.type != MemoryType.SEMANTIC:
                continue
            facts.append(_record_to_semantic_fact(record))
        return facts

    def upsert(self, user_id: str, fact: SemanticMemoryFact) -> None:
        record = _fact_to_record(user_id, fact)
        self.long_term_store.upsert(record)

    def mark_indexed_state(self, user_id: str, topic: str, indexed: bool) -> None:
        self.indexed_topics[(user_id, topic)] = indexed


def _should_index(record: MemoryRecord) -> bool:
    if record.type not in {MemoryType.EPISODIC, MemoryType.SEMANTIC, MemoryType.PROCEDURAL}:
        return False
    if not getattr(record, "is_active", True):
        return False
    if not bool(getattr(record, "should_vectorize", True)):
        return False
    if record.status.value in {"deleted", "expired", "superseded", "inactive"}:
        return False
    if getattr(record, "effective_to", None) is not None:
        return False
    if getattr(record, "valid_until", None) is not None:
        return False
    return True
