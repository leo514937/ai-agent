from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from learning_agent_service.domain import GraphRuntimeMeta, PersistentSessionContext
from learning_agent_service.domain.protocols import SessionContextPort
from learning_agent_service.infrastructure.observability.outbox import (
    AsyncLogWriteRequest,
    TypedAsyncLogEvent,
    normalize_async_log_request,
)


@dataclass
class InMemorySessionContextStore(SessionContextPort):
    sessions: Dict[Tuple[str, str], PersistentSessionContext] = field(default_factory=dict)

    def load(self, session_id: str, user_id: str) -> PersistentSessionContext:
        return deepcopy(self.sessions.get((session_id, user_id), PersistentSessionContext()))

    def save(self, context: PersistentSessionContext, runtime: GraphRuntimeMeta) -> None:
        self.sessions[(runtime.session_id, runtime.user_id)] = deepcopy(context)

    def load_any(self, session_id: str) -> PersistentSessionContext:
        for (stored_session_id, _), context in self.sessions.items():
            if stored_session_id == session_id:
                return deepcopy(context)
        return PersistentSessionContext()


@dataclass
class InMemoryTopicMasteryStore:
    """兼容壳：保留旧测试/导入入口，不再参与运行时装配。"""

    records: Dict[Tuple[str, str], Dict[str, Any]] = field(default_factory=dict)

    def get(self, user_id: str, topic: str) -> Dict[str, Any]:
        return deepcopy(self.records.get((user_id, topic), {"topic": topic}))

    def upsert(self, user_id: str, topic: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        merged = self.get(user_id, topic)
        merged.update(payload)
        merged["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.records[(user_id, topic)] = deepcopy(merged)
        return deepcopy(merged)

    def list_for_user(self, user_id: str) -> List[Dict[str, Any]]:
        items = [value for (stored_user_id, _), value in self.records.items() if stored_user_id == user_id]
        return deepcopy(sorted(items, key=lambda item: item.get("updated_at", ""), reverse=True))


@dataclass
class InMemoryAsyncLogStore:
    entries: List[Dict[str, Any]] = field(default_factory=list)

    def append(self, entry: Dict[str, Any] | AsyncLogWriteRequest | TypedAsyncLogEvent) -> None:
        normalized = normalize_async_log_request(entry)
        self.entries.append(
            deepcopy(
                {
                    "aggregate_type": normalized.aggregate_type,
                    "aggregate_id": normalized.aggregate_id,
                    "event_type": normalized.event_type,
                    "dedupe_key": normalized.dedupe_key,
                    "payload": dict(normalized.payload),
                    "trace_id": normalized.trace_id,
                    "available_at": normalized.available_at.isoformat(),
                }
            )
        )
