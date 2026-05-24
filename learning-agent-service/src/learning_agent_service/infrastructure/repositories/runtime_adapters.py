"""Runtime adapters that bridge infrastructure repositories into service-friendly stores."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from learning_agent_service.domain import GraphRuntimeMeta, PersistentSessionContext
from learning_agent_service.domain.protocols import SessionContextPort
from learning_agent_service.infrastructure.db.redis import RedisRuntime
from learning_agent_service.infrastructure.observability.outbox import (
    AsyncLogWriteRequest,
    TypedAsyncLogEvent,
    normalize_async_log_request,
)
from learning_agent_service.memory.models import SemanticMemoryFact

from .outbox import OutboxRepository
from .records import (
    OutboxEventRecord,
    UserPreferenceProfileRecord,
    UserProfilePreferenceRecord,
)
from .preferences import UserPreferenceRepository, UserProfileProjectionRepository


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


@dataclass
class RedisSessionContextStore(SessionContextPort):
    """Redis-backed short-term session truth store."""

    runtime: RedisRuntime

    def load(self, session_id: str, user_id: str) -> PersistentSessionContext:
        state_key = self.runtime.keys.session_state(session_id)
        raw = self.runtime.client.get(state_key)
        if not raw:
            return PersistentSessionContext()

        payload = json.loads(raw)
        payload.setdefault("extra", {})
        payload["extra"].setdefault("user_id", user_id)
        return PersistentSessionContext.model_validate(payload)

    def save(self, context: PersistentSessionContext, runtime: GraphRuntimeMeta) -> None:
        state_key = self.runtime.keys.session_state(runtime.session_id)
        summary_key = self.runtime.keys.summary(runtime.session_id)
        clarification_key = self.runtime.keys.clarification(runtime.session_id)
        payload = context.model_dump(mode="json")
        payload.setdefault("extra", {})
        payload["extra"]["user_id"] = runtime.user_id
        self.runtime.client.set(state_key, json.dumps(payload, default=_json_default))

        summary_payload = {
            "current_topic": context.current_topic,
            "last_retrieval_topic": context.last_retrieval_topic,
            "history_summary": context.history_summary,
            "open_questions": list(context.open_questions),
            "confirmed_facts": list(context.confirmed_facts),
            "next_steps": list(context.next_steps),
            "summary_version": context.summary_version,
            "summary_updated_at": context.summary_updated_at.isoformat() if context.summary_updated_at else None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.runtime.client.set(summary_key, json.dumps(summary_payload))

        if context.clarification_result:
            self.runtime.client.set(clarification_key, json.dumps(context.clarification_result, default=_json_default))
        else:
            self.runtime.client.delete(clarification_key)

    def load_any(self, session_id: str) -> PersistentSessionContext:
        return self.load(session_id, "anonymous")


@dataclass
class OutboxAsyncLogStore:
    """Converts fire-and-forget async log writes into outbox records."""

    repository: OutboxRepository
    aggregate_type: str = "async_log"

    def append(self, entry: Mapping[str, Any] | AsyncLogWriteRequest | TypedAsyncLogEvent) -> None:
        request = normalize_async_log_request(entry)
        if request.aggregate_type == "async_log" and self.aggregate_type != "async_log":
            request = AsyncLogWriteRequest(
                aggregate_type=self.aggregate_type,
                aggregate_id=request.aggregate_id,
                event_type=request.event_type,
                dedupe_key=request.dedupe_key,
                payload=deepcopy(request.payload),
                trace_id=request.trace_id,
                available_at=request.available_at,
            )
        record = request.to_record()
        self.repository.enqueue(record)


@dataclass
class NoOpSemanticMemoryStore:
    """Explicit no-op semantic memory adapter used when no real backend is wired."""

    indexed_topics: Dict[Tuple[str, str], bool] = field(default_factory=dict)

    def search(self, user_id: str, query: str, limit: int = 5) -> Sequence[SemanticMemoryFact]:
        return ()

    def upsert(self, user_id: str, fact: SemanticMemoryFact) -> None:
        return None

    def mark_indexed_state(self, user_id: str, topic: str, indexed: bool) -> None:
        self.indexed_topics[(user_id, topic)] = indexed


@dataclass
class DurablePreferenceStore:
    repository: UserPreferenceRepository

    def get(self, user_id: str) -> Any:
        model = self.repository.get(user_id)
        if model is None:
            return None
        return UserPreferenceProfileRecord(
            user_id=model.user_id,
            answer_style=model.answer_style,
            explanation_depth=model.explanation_depth,
            extra=dict(model.extra or {}),
        )

    def upsert(self, payload: Mapping[str, Any] | Any) -> Mapping[str, Any]:
        if isinstance(payload, Mapping):
            user_id = str(payload.get("user_id") or "anonymous")
            answer_style = payload.get("answer_style")
            explanation_depth = payload.get("explanation_depth")
            extra = dict(payload.get("extra", {}))
        else:
            user_id = str(getattr(payload, "user_id", "anonymous"))
            answer_style = getattr(payload, "answer_style", None)
            explanation_depth = getattr(payload, "explanation_depth", None)
            extra = dict(getattr(payload, "extra", {}) or {})
        record = UserPreferenceProfileRecord(
            user_id=user_id,
            answer_style=answer_style,
            explanation_depth=explanation_depth,
            extra=extra,
        )
        model = self.repository.upsert(record)
        return {
            "user_id": model.user_id,
            "answer_style": model.answer_style,
            "explanation_depth": model.explanation_depth,
            "extra": dict(model.extra or {}),
        }


@dataclass
class DurableProfileProjectionStore:
    repository: UserProfileProjectionRepository

    def list_active(self, user_id: str):
        return self.repository.list_active(user_id)

    def get(self, user_id: str, preference_key: str):
        return self.repository.get(user_id, preference_key)

    def upsert(self, payload: Mapping[str, Any] | Any) -> Mapping[str, Any]:
        if isinstance(payload, Mapping):
            record = UserProfilePreferenceRecord(
                user_id=str(payload.get("user_id") or "anonymous"),
                preference_key=str(payload.get("preference_key") or ""),
                current_value=str(payload.get("current_value") or ""),
                confidence=float(payload.get("confidence") or 0.0),
                source_memory_id=payload.get("source_memory_id"),
                effective_from=payload.get("effective_from"),
                effective_to=payload.get("effective_to"),
                status=str(payload.get("status") or "active"),
                is_active=bool(payload.get("is_active", True)),
                source_session_id=payload.get("source_session_id"),
                extra=dict(payload.get("extra", {})),
            )
        else:
            record = UserProfilePreferenceRecord(
                user_id=str(getattr(payload, "user_id", "anonymous")),
                preference_key=str(getattr(payload, "preference_key", "")),
                current_value=str(getattr(payload, "current_value", "")),
                confidence=float(getattr(payload, "confidence", 0.0) or 0.0),
                source_memory_id=getattr(payload, "source_memory_id", None),
                effective_from=getattr(payload, "effective_from", None),
                effective_to=getattr(payload, "effective_to", None),
                status=str(getattr(payload, "status", "active")),
                is_active=bool(getattr(payload, "is_active", True)),
                source_session_id=getattr(payload, "source_session_id", None),
                extra=dict(getattr(payload, "extra", {}) or {}),
            )
        model = self.repository.upsert(record)
        return {
            "user_id": model.user_id,
            "preference_key": model.preference_key,
            "current_value": model.current_value,
            "confidence": float(model.confidence or 0.0),
            "source_memory_id": model.source_memory_id,
            "effective_from": model.effective_from,
            "effective_to": model.effective_to,
            "status": model.status,
            "is_active": bool(model.is_active),
            "source_session_id": model.source_session_id,
            "extra": dict(model.extra or {}),
        }


@dataclass(frozen=True)
class AdapterStatus:
    name: str
    mode: str
    ready: bool
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeDependencyStatus:
    adapters: Tuple[AdapterStatus, ...]
    bootstrap_errors: Tuple[Tuple[str, str], ...] = ()

    @property
    def fallback_names(self) -> Tuple[str, ...]:
        return tuple(adapter.name for adapter in self.adapters if adapter.mode == "fallback")

    def as_dict(self) -> Dict[str, Any]:
        return {
            "adapters": [
                {
                    "name": adapter.name,
                    "mode": adapter.mode,
                    "ready": adapter.ready,
                    "details": dict(adapter.details),
                }
                for adapter in self.adapters
            ],
            "bootstrap_errors": list(self.bootstrap_errors),
            "fallbacks": list(self.fallback_names),
        }


@dataclass(frozen=True)
class RuntimeComponentMode:
    name: str
    mode: str
    ready: bool
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeProfile:
    name: str
    components: Tuple[RuntimeComponentMode, ...]
    bootstrap_errors: Tuple[Tuple[str, str], ...] = ()

    def as_dict(self) -> Dict[str, Any]:
        return {
            "profile": self.name,
            "components": [
                {
                    "name": component.name,
                    "mode": component.mode,
                    "ready": component.ready,
                    "details": dict(component.details),
                }
                for component in self.components
            ],
            "bootstrap_errors": list(self.bootstrap_errors),
        }
