from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from learning_agent_service.domain.contracts import PersistentSessionContext as DomainPersistentSessionContext

from .models import AsyncLogEvent, PreferenceProfileWrite, SemanticMemoryFact, SessionPersistenceContext


class SessionStore(Protocol):
    def load(self, session_id: str, user_id: str) -> DomainPersistentSessionContext:
        ...

    def save(self, context: DomainPersistentSessionContext, runtime: SessionPersistenceContext) -> None:
        ...


@runtime_checkable
class SupportsLoadAny(Protocol):
    def load_any(self, session_id: str) -> DomainPersistentSessionContext:
        ...


class PreferenceStore(Protocol):
    def get(self, user_id: str) -> Any:
        ...

    def upsert(self, profile: PreferenceProfileWrite) -> Any:
        ...


class AsyncLogStore(Protocol):
    def append(self, entry: AsyncLogEvent | Mapping[str, Any]) -> None:
        ...


class SemanticMemoryStore(Protocol):
    def search(self, user_id: str, query: str, limit: int = 5) -> Sequence[SemanticMemoryFact]:
        ...

    def upsert(self, user_id: str, fact: SemanticMemoryFact) -> None:
        ...

    def mark_indexed_state(self, user_id: str, topic: str, indexed: bool) -> None:
        ...


@dataclass
class NoOpSemanticMemoryStore:
    indexed_topics: dict[tuple[str, str], bool] = field(default_factory=dict)

    def search(self, user_id: str, query: str, limit: int = 5) -> Sequence[SemanticMemoryFact]:
        return ()

    def upsert(self, user_id: str, fact: SemanticMemoryFact) -> None:
        return None

    def mark_indexed_state(self, user_id: str, topic: str, indexed: bool) -> None:
        self.indexed_topics[(user_id, topic)] = indexed
