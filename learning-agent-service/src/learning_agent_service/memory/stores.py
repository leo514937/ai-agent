from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from learning_agent_service.domain.memory import (
    EntityMemoryStore,
    MemoryEdge,
    MemoryEdgeType,
    LongTermMemoryStore,
    MemoryRecord,
    MemoryScope,
    MemoryStatus,
    SensoryMemoryBuffer,
    ShortTermMemoryStore,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class InMemorySensoryMemoryBuffer(SensoryMemoryBuffer):
    buffers: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def ingest(self, turn_id: str, payload: Mapping[str, Any]) -> None:
        self.buffers[turn_id] = deepcopy(dict(payload))

    def snapshot(self, turn_id: str) -> Mapping[str, Any]:
        return deepcopy(self.buffers.get(turn_id, {}))

    def clear(self, turn_id: str) -> None:
        self.buffers.pop(turn_id, None)


@dataclass
class InMemoryShortTermMemoryStore(ShortTermMemoryStore):
    windows: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    task_contexts: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def append_messages(self, session_id: str, messages: Sequence[Mapping[str, Any]]) -> None:
        window = self.windows.setdefault(session_id, [])
        window.extend(deepcopy([dict(message) for message in messages]))

    def get_window(self, session_id: str, limit: int = 20) -> Sequence[Mapping[str, Any]]:
        return deepcopy(self.windows.get(session_id, [])[-limit:])

    def save_task_context(self, session_id: str, context: Mapping[str, Any]) -> None:
        self.task_contexts[session_id] = deepcopy(dict(context))

    def get_task_context(self, session_id: str) -> Mapping[str, Any]:
        return deepcopy(self.task_contexts.get(session_id, {}))

    def prune(self, session_id: str, limit: int = 20) -> None:
        if session_id in self.windows:
            self.windows[session_id] = self.windows[session_id][-limit:]


@dataclass
class InMemoryLongTermMemoryStore(LongTermMemoryStore):
    records: Dict[str, MemoryRecord] = field(default_factory=dict)

    def upsert(self, record: MemoryRecord) -> MemoryRecord:
        stored = record.model_copy(
            update={
                "updated_at": _utcnow(),
                "is_active": bool(record.is_active and record.status.value not in {"deleted", "expired", "superseded", "inactive"}),
            }
        )
        if not stored.memory_id:
            stored = stored.model_copy(update={"memory_id": f"{stored.user_id}:{stored.source_turn_id}:{stored.type.value}:{len(self.records) + 1}"})
        self.records[stored.memory_id] = deepcopy(stored)
        return deepcopy(stored)

    def get(self, memory_id: str) -> Optional[MemoryRecord]:
        record = self.records.get(memory_id)
        return deepcopy(record) if record is not None else None

    def search(
        self,
        query: str,
        user_id: str,
        limit: int = 10,
        memory_types: Optional[Sequence[MemoryType]] = None,
    ) -> Sequence[MemoryRecord]:
        needle = (query or "").lower().strip()
        allowed_types = {item.value if hasattr(item, "value") else str(item or "").strip().lower() for item in memory_types or []}
        allowed_types = {item for item in allowed_types if item}
        matches: List[MemoryRecord] = []
        now = _utcnow()
        for record in self.records.values():
            if record.user_id and record.user_id != user_id:
                continue
            if allowed_types and record.type.value not in allowed_types:
                continue
            if record.status not in {MemoryStatus.ACTIVE, MemoryStatus.CONFIRMED}:
                continue
            if record.scope not in {MemoryScope.USER, MemoryScope.PROJECT, MemoryScope.GLOBAL}:
                continue
            if not getattr(record, "should_vectorize", True):
                continue
            if not getattr(record, "is_active", True):
                continue
            if getattr(record, "effective_from", None) and record.effective_from > _utcnow():
                continue
            if getattr(record, "effective_to", None) and record.effective_to <= _utcnow():
                continue
            if getattr(record, "valid_until", None) and record.valid_until <= now:
                continue
            haystack = " ".join(
                [
                    record.summary or "",
                    str(record.content),
                    " ".join(record.tags),
                    " ".join(record.entities),
                ]
            ).lower()
            if not needle or needle in haystack:
                matches.append(record)
        matches.sort(key=lambda item: (item.importance, item.confidence, item.updated_at), reverse=True)
        return deepcopy(matches[:limit])

    def list_by_scope(self, user_id: str, scope: MemoryScope) -> Sequence[MemoryRecord]:
        now = _utcnow()
        records = [
            record
            for record in self.records.values()
            if record.user_id == user_id
            and record.scope == scope
            and record.status in {MemoryStatus.ACTIVE, MemoryStatus.CONFIRMED}
            and getattr(record, "should_vectorize", True)
            and getattr(record, "is_active", True)
            and (getattr(record, "effective_from", None) is None or record.effective_from <= now)
            and (getattr(record, "effective_to", None) is None or record.effective_to > now)
            and (getattr(record, "valid_until", None) is None or record.valid_until > now)
        ]
        records.sort(key=lambda item: (item.updated_at, item.importance), reverse=True)
        return deepcopy(records)

    def supersede(
        self,
        memory_id: str,
        superseded_by: str,
        reason: str,
        edge_type: MemoryEdgeType = MemoryEdgeType.SUPERSEDES,
    ) -> None:
        record = self.records.get(memory_id)
        if record is None:
            return
        self.records[memory_id] = record.model_copy(
            update={
                "status": record.status.__class__.SUPERSEDED,
                "supersedes": superseded_by,
                "superseded_by_memory_id": superseded_by,
                "is_active": False,
                "effective_to": _utcnow(),
                "metadata": (record.metadata.model_copy(update={"status": record.status.__class__.SUPERSEDED}) if record.metadata else None),
                "updated_at": _utcnow(),
                "summary": f"{record.summary or ''} [superseded: {reason}]".strip(),
            }
        )

    def create_edge(self, edge: MemoryEdge) -> MemoryEdge:
        return deepcopy(edge)

    def soft_delete(self, memory_id: str, reason: str) -> None:
        record = self.records.get(memory_id)
        if record is None:
            return
        self.records[memory_id] = record.model_copy(
            update={
                "status": record.status.__class__.DELETED,
                "is_active": False,
                "effective_to": _utcnow(),
                "updated_at": _utcnow(),
                "summary": f"{record.summary or ''} [deleted: {reason}]".strip(),
            }
        )


@dataclass
class InMemoryEntityMemoryStore(EntityMemoryStore):
    records: Dict[Tuple[str, str], MemoryRecord] = field(default_factory=dict)

    def upsert(self, record: MemoryRecord) -> MemoryRecord:
        if not record.memory_id:
            record = record.model_copy(update={"memory_id": f"{record.user_id}:{record.type.value}:{len(self.records) + 1}"})
        self.records[(record.user_id, record.memory_id)] = deepcopy(record.model_copy(update={"updated_at": _utcnow()}))
        return deepcopy(self.records[(record.user_id, record.memory_id)])

    def get(self, entity_id: str, user_id: str) -> Optional[MemoryRecord]:
        record = self.records.get((user_id, entity_id))
        return deepcopy(record) if record is not None else None

    def list_by_user(self, user_id: str, entity_type: Optional[str] = None) -> Sequence[MemoryRecord]:
        records = [record for (stored_user, _), record in self.records.items() if stored_user == user_id]
        if entity_type:
            records = [record for record in records if record.type.value == entity_type]
        records.sort(key=lambda item: (item.importance, item.updated_at), reverse=True)
        return deepcopy(records)

    def search(self, user_id: str, query: str, limit: int = 10) -> Sequence[MemoryRecord]:
        needle = (query or "").lower().strip()
        records = []
        for record in self.list_by_user(user_id):
            haystack = " ".join([record.summary or "", str(record.content), " ".join(record.tags), " ".join(record.entities)]).lower()
            if not needle or needle in haystack:
                records.append(record)
        return records[:limit]

    def merge(self, target_entity_id: str, source_entity_ids: List[str], reason: str) -> MemoryRecord:
        target = None
        target_key = None
        for key, record in self.records.items():
            if key[1] == target_entity_id:
                target = record
                target_key = key
                break
        if target is None:
            target = MemoryRecord(memory_id=target_entity_id, user_id="", source_turn_id="", updated_at=_utcnow(), created_at=_utcnow())
            target_key = ("", target_entity_id)
        merged_tags = list(dict.fromkeys(target.tags))
        merged_entities = list(dict.fromkeys(target.entities))
        for source_id in source_entity_ids:
            source = None
            for key, record in self.records.items():
                if key[1] == source_id:
                    source = record
                    break
            if source is None:
                continue
            merged_tags.extend(tag for tag in source.tags if tag not in merged_tags)
            merged_entities.extend(entity for entity in source.entities if entity not in merged_entities)
            self.records[(source.user_id, source.memory_id)] = source.model_copy(update={"status": source.status.__class__.SUPERSEDED})
        merged = target.model_copy(
            update={
                "tags": list(dict.fromkeys(merged_tags)),
                "entities": list(dict.fromkeys(merged_entities)),
                "summary": (target.summary or "") + (f" | merged: {reason}" if reason else ""),
                "updated_at": _utcnow(),
            }
        )
        self.records[target_key] = deepcopy(merged)
        return deepcopy(merged)


@dataclass
class InMemoryMasteryMemoryStore:
    """兼容壳：保留旧测试/导入入口，不再参与运行时装配。"""

    records: Dict[Tuple[str, str], Dict[str, Any]] = field(default_factory=dict)

    def get(self, user_id: str, topic: str) -> Mapping[str, Any]:
        return deepcopy(self.records.get((user_id, topic), {}))

    def upsert(self, user_id: str, topic: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        merged = dict(self.records.get((user_id, topic), {}))
        merged.update(dict(payload))
        merged["updated_at"] = _utcnow().isoformat()
        self.records[(user_id, topic)] = deepcopy(merged)
        return deepcopy(merged)

    def list_for_user(self, user_id: str) -> Sequence[Mapping[str, Any]]:
        records = [value for (stored_user, _), value in self.records.items() if stored_user == user_id]
        records.sort(key=lambda item: (item.get("updated_at", ""), item.get("topic", "")), reverse=True)
        return deepcopy(records)

