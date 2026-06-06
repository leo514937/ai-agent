from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from learning_agent_service.domain.memory import (
    MemoryRecord,
    MemoryScope,
    MemorySource,
    MemoryStatus,
    MemoryType,
)
from learning_agent_service.memory.models import MemoryPromotionInput, SemanticMemoryFact

_CLARIFICATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"问题还不够具体"),
    re.compile(r"请补充(?:对象|范围|目标|条件|场景|信息|细节|范围)?"),
    re.compile(r"你可以继续展开"),
    re.compile(r"可以继续展开"),
    re.compile(r"需要更具体"),
    re.compile(r"请提供(?:更多|具体)?"),
    re.compile(r"能否补充"),
    re.compile(r"麻烦补充"),
)

_AMBIGUOUS_QUERY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^附近有什么好的推荐"),
    re.compile(r"^有什么好的推荐"),
    re.compile(r"^推荐.*$"),
    re.compile(r"^怎么.*$"),
    re.compile(r"^如何.*$"),
)

_SESSION_EVENT_FACT_TYPES = {
    "session_fact",
    "session_summary",
    "session_event",
    "clarification_result",
    "clarification_event",
    "missing_slots",
    "ambiguous_query",
}

_LONG_TERM_SCOPES = {MemoryScope.USER, MemoryScope.PROJECT, MemoryScope.GLOBAL}


def _text_blob(*values: Any) -> str:
    parts: list[str] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, Mapping):
            parts.append(" ".join(f"{key}:{item}" for key, item in value.items() if item is not None))
        elif isinstance(value, (list, tuple, set)):
            parts.append(" ".join(str(item) for item in value if item is not None))
        else:
            parts.append(str(value))
    return " ".join(part for part in parts if part).lower()


def _normalized_text(*values: Any) -> str:
    return re.sub(r"\s+", "", _text_blob(*values))


@dataclass(frozen=True)
class MemoryPromotionGateDecision:
    allow_long_term: bool
    should_vectorize: bool
    scope: MemoryScope
    status: MemoryStatus
    ttl_seconds: int | None
    reason: str


@dataclass(frozen=True)
class MemoryPromotionGateConfig:
    long_term_confidence_threshold: float = 0.7
    long_term_stability_threshold: float = 0.7
    long_term_importance_threshold: float = 0.6
    guest_user_ids: tuple[str, ...] = ("guest",)
    turn_ttl_seconds: int = 3600
    session_ttl_seconds: int = 86400


@dataclass
class MemoryPromotionGate:
    config: MemoryPromotionGateConfig = field(default_factory=MemoryPromotionGateConfig)

    def should_promote_semantic_fact(
        self,
        payload: MemoryPromotionInput,
        fact: SemanticMemoryFact,
    ) -> MemoryPromotionGateDecision:
        fact_metadata = dict(fact.metadata or {})
        source = str(
            fact_metadata.get("source")
            or payload.extra.get("source")
            or payload.extra.get("memory_source")
            or MemorySource.SYSTEM_EVENT.value
        ).strip().lower()
        fact_type = str(
            fact_metadata.get("fact_type")
            or payload.extra.get("fact_type")
            or fact.fact_type
            or ""
        ).strip().lower()
        summary = _text_blob(payload.query, payload.answer_text, fact.content, fact.topic, fact_metadata.get("summary"))
        if self._is_session_event(source, fact_type) or self._is_clarification_event(payload, fact, summary):
            return self._session_only_decision(
                reason=self._session_reason(source=source, fact_type=fact_type, payload=payload, fact=fact, summary=summary),
                status=MemoryStatus.EPHEMERAL if self._looks_like_clarification(summary) else MemoryStatus.OBSERVED,
            )
        if self._is_guest(payload.user_id):
            return self._session_only_decision(
                reason="guest_user_session_only",
                status=MemoryStatus.EPHEMERAL,
            )

        confidence = float(fact_metadata.get("confidence") or fact.strength or 0.0)
        stability = float(fact_metadata.get("stability") or fact_metadata.get("stability_score") or fact.strength or 0.0)
        importance = float(fact_metadata.get("importance") or fact.strength or 0.0)
        if confidence < self.config.long_term_confidence_threshold or stability < self.config.long_term_stability_threshold:
            return self._session_only_decision(
                reason="low_confidence_or_stability",
                status=MemoryStatus.OBSERVED,
            )
        if importance < self.config.long_term_importance_threshold:
            return self._session_only_decision(
                reason="importance_too_low",
                status=MemoryStatus.OBSERVED,
            )
        if self._is_ambiguous_query(payload.query, summary):
            return self._session_only_decision(
                reason="ambiguous_query",
                status=MemoryStatus.OBSERVED,
            )

        scope = self._resolve_scope(fact_metadata.get("scope"))
        status = self._resolve_status(fact_metadata.get("status"))
        return MemoryPromotionGateDecision(
            allow_long_term=True,
            should_vectorize=True,
            scope=scope,
            status=status,
            ttl_seconds=None,
            reason="long_term_semantic_fact",
        )

    def _session_only_decision(self, *, reason: str, status: MemoryStatus) -> MemoryPromotionGateDecision:
        return MemoryPromotionGateDecision(
            allow_long_term=False,
            should_vectorize=False,
            scope=MemoryScope.SESSION,
            status=status,
            ttl_seconds=self.config.session_ttl_seconds,
            reason=reason,
        )

    def _session_reason(
        self,
        *,
        source: str,
        fact_type: str,
        payload: MemoryPromotionInput,
        fact: SemanticMemoryFact,
        summary: str,
    ) -> str:
        if source == MemorySource.SYSTEM_EVENT.value and fact_type in _SESSION_EVENT_FACT_TYPES:
            return "system_event_session_fact"
        if payload.extra.get("clarification_result"):
            return "clarification_event"
        if payload.extra.get("missing_slots"):
            return "missing_slots_event"
        if self._looks_like_clarification(summary):
            return "clarification_template"
        if self._is_ambiguous_query(payload.query, summary):
            return "ambiguous_query"
        if fact_type in _SESSION_EVENT_FACT_TYPES:
            return fact_type
        return "session_only"

    def _is_session_event(self, source: str, fact_type: str) -> bool:
        return fact_type in _SESSION_EVENT_FACT_TYPES or source == MemorySource.SYSTEM_EVENT.value and fact_type in _SESSION_EVENT_FACT_TYPES

    def _is_clarification_event(self, payload: MemoryPromotionInput, fact: SemanticMemoryFact, summary: str) -> bool:
        if payload.extra.get("clarification_result") or payload.extra.get("missing_slots"):
            return True
        if self._looks_like_clarification(summary):
            return True
        if self._looks_like_clarification(_text_blob(payload.query, payload.answer_text, fact.content)):
            return True
        return False

    def _looks_like_clarification(self, summary: str) -> bool:
        return any(pattern.search(summary) for pattern in _CLARIFICATION_PATTERNS)

    def _is_ambiguous_query(self, query: str, summary: str) -> bool:
        normalized = (query or "").strip()
        if not normalized:
            return True
        if len(normalized) <= 8:
            return True
        if any(pattern.search(normalized) for pattern in _AMBIGUOUS_QUERY_PATTERNS):
            return True
        if ("推荐" in normalized or "附近" in normalized) and not any(
            marker in normalized for marker in ("具体", "哪家", "预算", "人均", "口味", "距离", "时间", "商圈", "区域")
        ):
            return True
        return bool(self._looks_like_clarification(summary))

    def _is_guest(self, user_id: str) -> bool:
        return (user_id or "").strip().lower() in {value.lower() for value in self.config.guest_user_ids}

    def _resolve_scope(self, scope_value: Any) -> MemoryScope:
        if hasattr(scope_value, "value"):
            scope_value = scope_value.value
        try:
            scope = MemoryScope(str(scope_value or "").strip().lower())
        except Exception:
            scope = MemoryScope.USER
        return scope if scope in _LONG_TERM_SCOPES else MemoryScope.USER

    @staticmethod
    def _resolve_status(status_value: Any) -> MemoryStatus:
        if hasattr(status_value, "value"):
            status_value = status_value.value
        try:
            status = MemoryStatus(str(status_value or "").strip().lower())
        except Exception:
            status = MemoryStatus.CONFIRMED
        return status if status in {MemoryStatus.ACTIVE, MemoryStatus.CONFIRMED} else MemoryStatus.CONFIRMED


@dataclass(frozen=True)
class MemoryVectorizationGateDecision:
    allowed: bool
    reason: str


@dataclass(frozen=True)
class MemoryVectorizationGateConfig:
    min_importance: float = 0.6
    min_stability: float = 0.6
    allow_entity_vectorization: bool = False


@dataclass
class MemoryVectorizationGate:
    config: MemoryVectorizationGateConfig = field(default_factory=MemoryVectorizationGateConfig)

    def should_vectorize(self, record: MemoryRecord) -> MemoryVectorizationGateDecision:
        if not bool(record.should_vectorize):
            return MemoryVectorizationGateDecision(False, "record_disabled_vectorization")
        if record.type not in {MemoryType.SEMANTIC, MemoryType.EPISODIC, MemoryType.PROCEDURAL}:
            if record.type == MemoryType.ENTITY and self._entity_vectorization_allowed(record):
                pass
            else:
                return MemoryVectorizationGateDecision(False, "memory_type_not_indexed")
        if record.scope not in _LONG_TERM_SCOPES:
            return MemoryVectorizationGateDecision(False, "non_long_term_scope")
        if record.status not in {MemoryStatus.ACTIVE, MemoryStatus.CONFIRMED}:
            return MemoryVectorizationGateDecision(False, "inactive_status")
        if not getattr(record, "is_active", True):
            return MemoryVectorizationGateDecision(False, "record_inactive")
        now = datetime.now(timezone.utc)
        if record.effective_to is not None and record.effective_to <= now:
            return MemoryVectorizationGateDecision(False, "effective_to_expired")
        if record.valid_until is not None and record.valid_until <= now:
            return MemoryVectorizationGateDecision(False, "valid_until_expired")
        if float(record.importance or 0.0) < self.config.min_importance:
            return MemoryVectorizationGateDecision(False, "importance_too_low")
        if float(record.stability or 0.0) < self.config.min_stability:
            return MemoryVectorizationGateDecision(False, "stability_too_low")
        if self._is_session_event(record):
            return MemoryVectorizationGateDecision(False, "session_event_not_vectorized")
        if self._is_guest(record):
            return MemoryVectorizationGateDecision(False, "guest_user_long_term_blocked")
        if self._looks_like_clarification(record):
            return MemoryVectorizationGateDecision(False, "clarification_event")
        if self._is_ambiguous_query(record):
            return MemoryVectorizationGateDecision(False, "ambiguous_query")
        return MemoryVectorizationGateDecision(True, "vectorization_allowed")

    def _entity_vectorization_allowed(self, record: MemoryRecord) -> bool:
        if not self.config.allow_entity_vectorization:
            return False
        tags = {str(tag).strip().lower() for tag in record.tags or []}
        normalized_key = str(record.normalized_key or "").strip().lower()
        summary = _text_blob(record.summary, record.content, record.topic, record.entities)
        return bool(
            tags.intersection({"profile_summary", "preference_summary", "current_profile"})
            or normalized_key in {"current_profile", "profile_summary", "preference_summary"}
            or "profile summary" in summary
            or "preference summary" in summary
        )

    def _is_session_event(self, record: MemoryRecord) -> bool:
        source_value = self._enum_value(record.source)
        fact_type = self._content_value(record, "fact_type")
        return fact_type in _SESSION_EVENT_FACT_TYPES or source_value == MemorySource.SYSTEM_EVENT.value and fact_type in _SESSION_EVENT_FACT_TYPES

    def _is_guest(self, record: MemoryRecord) -> bool:
        return (record.user_id or "").strip().lower() == "guest"

    def _looks_like_clarification(self, record: MemoryRecord) -> bool:
        summary_text = _normalized_text(record.summary, record.content, record.tags)
        return any(marker in summary_text for marker in ("问题还不够具体", "请补充", "继续展开", "需要更具体"))

    def _is_ambiguous_query(self, record: MemoryRecord) -> bool:
        text = _normalized_text(record.summary, record.content, record.tags, record.topic)
        return (
            any(pattern.search(text) for pattern in _AMBIGUOUS_QUERY_PATTERNS)
            or ("推荐" in text or "附近" in text) and not any(marker in text for marker in ("具体", "预算", "人均", "口味", "距离", "时间", "商圈", "区域"))
        )

    @staticmethod
    def _enum_value(value: Any) -> str:
        return value.value if hasattr(value, "value") else str(value or "")

    @staticmethod
    def _content_value(record: MemoryRecord, key: str) -> str:
        content = record.content
        if isinstance(content, Mapping):
            value = content.get(key)
            if value is not None:
                return str(value)
        metadata = record.raw_evidence or {}
        if isinstance(metadata, Mapping):
            value = metadata.get(key)
            if value is not None:
                return str(value)
        return ""
