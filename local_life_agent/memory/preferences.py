from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Iterable
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from ..domain.enums import PreferenceType
from ..domain.schemas import SemanticPreference


class MemoryType(str, Enum):
    taste = "taste"
    budget = "budget"
    scene = "scene"
    location = "location"
    deal = "deal"
    accessibility = "accessibility"
    dietary_restriction = "dietary_restriction"
    allergy = "allergy"
    ambience = "ambience"
    negative_preference = "negative_preference"


class MemoryPolarity(str, Enum):
    like = "like"
    dislike = "dislike"
    require = "require"
    avoid = "avoid"


class MemoryScope(str, Enum):
    global_scope = "global"
    local_life = "local_life"
    restaurant = "restaurant"
    cafe = "cafe"
    hotpot = "hotpot"
    parent_child = "parent_child"
    date_scene = "date_scene"
    business_area = "business_area"


class MemoryStatus(str, Enum):
    active = "active"
    expired = "expired"
    deleted = "deleted"


class MemoryOperation(str, Enum):
    create = "create"
    update = "update"
    delete = "delete"
    no_op = "no_op"


class UserPreferenceMemory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    preference_id: str = ""
    preference_type: MemoryType
    value: str = ""
    polarity: MemoryPolarity = MemoryPolarity.like
    scope: MemoryScope = MemoryScope.local_life
    source: str = "explicit_user_statement"
    confidence: float = 0.0
    evidence_ref: str = ""
    created_at: str = ""
    updated_at: str = ""
    ttl_seconds: int | None = None
    status: MemoryStatus = MemoryStatus.active
    version: int = 1
    last_confirmed_at: str = ""
    conflict_group: str = ""

    def is_expired(self, now: datetime | None = None) -> bool:
        if self.status != MemoryStatus.active:
            return True
        if self.ttl_seconds in (None, 0):
            return False
        reference = now or datetime.now(timezone.utc)
        anchor = _parse_dt(self.updated_at or self.created_at)
        if anchor is None:
            return False
        return reference >= anchor + timedelta(seconds=int(self.ttl_seconds or 0))


class MemoryReadContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = ""
    query_text: str = ""
    query_intent: str = ""
    allowed_scopes: list[str] = Field(default_factory=list)
    max_items: int = 5
    active_preferences: list[UserPreferenceMemory] = Field(default_factory=list)
    memory_used: list[str] = Field(default_factory=list)
    memory_ignored: list[str] = Field(default_factory=list)
    memory_conflicts: list[str] = Field(default_factory=list)


class MemoryUpdatePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: MemoryOperation = MemoryOperation.no_op
    preference: UserPreferenceMemory | None = None
    target_preference_id: str = ""
    reason: str = ""
    source_text: str = ""
    confidence: float = 0.0


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _memory_type_for_preference(preference_type: str, key: str = "", value: Any = "") -> MemoryType:
    pref_text = _normalize_text(preference_type).lower()
    key_text = _normalize_text(key).lower()
    value_text = _normalize_text(value).lower()
    if pref_text in {PreferenceType.value_for_money.value, PreferenceType.relative_price_preference.value}:
        return MemoryType.budget
    if pref_text == PreferenceType.scene_preference.value or "scene" in key_text:
        return MemoryType.scene
    if pref_text == PreferenceType.distance_preference.value or "distance" in key_text:
        return MemoryType.location
    if pref_text == PreferenceType.quality_preference.value:
        return MemoryType.taste
    if "price" in key_text or any(token in value_text for token in ("cheap", "lower_price", "value_for_money", "性价比")):
        return MemoryType.budget
    if "scene" in key_text or any(token in value_text for token in ("date", "约会", "聚餐", "带娃")):
        return MemoryType.scene
    if "distance" in key_text or any(token in value_text for token in ("near", "closer", "附近", "更近")):
        return MemoryType.location
    return MemoryType.taste


def _memory_polarity_for_signal(operator: Any, value: Any) -> MemoryPolarity:
    operator_text = _normalize_text(operator).lower()
    value_text = _normalize_text(value).lower()
    if operator_text in {"avoid", "dislike", "exclude", "forbid", "not"}:
        return MemoryPolarity.avoid
    if operator_text in {"require", "must", "need"}:
        return MemoryPolarity.require
    if any(token in value_text for token in ("不吃", "不要", "别", "避免", "不想")):
        return MemoryPolarity.avoid
    if any(token in value_text for token in ("必须", "一定", "只要", "需要")):
        return MemoryPolarity.require
    return MemoryPolarity.like


def _is_preference_like_key(key: Any) -> bool:
    key_text = _normalize_text(key).lower()
    if not key_text:
        return False
    return any(
        token in key_text
        for token in (
            "price",
            "scene",
            "distance",
            "taste",
            "budget",
            "ambience",
            "value_for_money",
            "quality",
            "preference",
        )
    )


def summarize_preference_memory(preference: UserPreferenceMemory) -> dict[str, Any]:
    return {
        "preference_id": preference.preference_id,
        "preference_type": preference.preference_type.value,
        "value": preference.value,
        "polarity": preference.polarity.value,
        "scope": preference.scope.value,
        "source": preference.source,
        "confidence": preference.confidence,
        "evidence_ref": preference.evidence_ref,
        "status": preference.status.value,
        "version": preference.version,
    }


def preference_memory_key(preference: UserPreferenceMemory) -> str:
    return ":".join(
        [
            preference.preference_type.value,
            preference.polarity.value,
            preference.scope.value,
            _normalize_text(preference.value).lower(),
        ]
    )


def build_preference_memories_from_semantic_frame(
    semantic_frame: Any,
    *,
    user_id: str,
    session_id: str = "",
    evidence_ref: str = "",
) -> list[UserPreferenceMemory]:
    payload = semantic_frame.model_dump(mode="python") if hasattr(semantic_frame, "model_dump") else dict(semantic_frame or {})
    preference_signals = payload.get("preference_signals") or []
    soft_preferences = payload.get("soft_preferences") or {}
    hard_constraints = payload.get("hard_constraints") or {}
    memories: list[UserPreferenceMemory] = []

    def _append_preference(
        *,
        preference_type: Any,
        value: Any,
        key: str = "",
        operator: Any = "",
        source: str = "",
        confidence: float = 0.0,
    ) -> None:
        normalized_value = _normalize_text(value)
        normalized_type = _normalize_text(preference_type)
        if not normalized_value and not normalized_type:
            return
        memory = build_preference_memory(
            user_id=user_id,
            preference_type=_memory_type_for_preference(normalized_type, key=key, value=normalized_value),
            value=normalized_value or normalized_type or key,
            polarity=_memory_polarity_for_signal(operator, normalized_value or normalized_type),
            scope=MemoryScope.local_life,
            source=source or "semantic_frame",
            confidence=confidence,
            evidence_ref=evidence_ref or session_id,
        )
        memories.append(memory)

    for signal in preference_signals:
        if isinstance(signal, SemanticPreference):
            _append_preference(
                preference_type=signal.preference_type.value,
                value=signal.value or signal.text,
                key=signal.preference_type.value,
                operator=signal.operator,
                source=signal.source or "semantic_frame.preference_signals",
                confidence=0.75,
            )
        elif isinstance(signal, dict):
            _append_preference(
                preference_type=signal.get("preference_type", ""),
                value=signal.get("value", "") or signal.get("text", ""),
                key=str(signal.get("preference_type", "") or ""),
                operator=signal.get("operator", ""),
                source=str(signal.get("source", "") or "semantic_frame.preference_signals"),
                confidence=0.75,
            )

    if isinstance(soft_preferences, dict):
        for key, value in soft_preferences.items():
            if not _is_preference_like_key(key):
                continue
            _append_preference(
                preference_type=str(key),
                value=value,
                key=str(key),
                operator="like",
                source="semantic_frame.soft_preferences",
                confidence=0.6,
            )

    if isinstance(hard_constraints, dict):
        for key, value in hard_constraints.items():
            if key in {"category", "location", "shop_id", "shop_name"} or not _is_preference_like_key(key):
                continue
            _append_preference(
                preference_type=str(key),
                value=value,
                key=str(key),
                operator="require",
                source="semantic_frame.hard_constraints",
                confidence=0.85,
            )

    deduped: dict[str, UserPreferenceMemory] = {}
    for memory in memories:
        deduped.setdefault(preference_memory_key(memory), memory)
    return list(deduped.values())


def merge_preference_memory_summaries(
    existing: Iterable[dict[str, Any]] | None,
    memories: Iterable[UserPreferenceMemory],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in existing or []:
        if not isinstance(item, dict):
            continue
        preference_type = _normalize_text(item.get("preference_type", ""))
        polarity = _normalize_text(item.get("polarity", ""))
        scope = _normalize_text(item.get("scope", ""))
        value = _normalize_text(item.get("value", "")).lower()
        key = ":".join([preference_type, polarity, scope, value])
        merged[key] = dict(item)
    for memory in memories:
        merged[preference_memory_key(memory)] = summarize_preference_memory(memory)
    return list(merged.values())


class PreferenceMemoryBackend(ABC):
    @abstractmethod
    def list_active(self, user_id: str) -> list[UserPreferenceMemory]:
        raise NotImplementedError

    @abstractmethod
    def upsert(self, preference: UserPreferenceMemory) -> UserPreferenceMemory:
        raise NotImplementedError

    @abstractmethod
    def delete(self, user_id: str, preference_id: str) -> UserPreferenceMemory | None:
        raise NotImplementedError

    @abstractmethod
    def read_context(self, context: MemoryReadContext) -> MemoryReadContext:
        raise NotImplementedError


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _tokenize(text: str) -> set[str]:
    compact = str(text or "").strip().lower()
    if not compact:
        return set()
    tokens: set[str] = set()
    current = []
    for char in compact:
        if char.isalnum() or "\u4e00" <= char <= "\u9fff":
            current.append(char)
        else:
            if current:
                token = "".join(current)
                if len(token) >= 2:
                    tokens.add(token)
                current = []
    if current:
        token = "".join(current)
        if len(token) >= 2:
            tokens.add(token)
    for chunk in ("不吃辣", "吃辣", "安静", "预算", "停车", "包间", "带娃", "排队"):
        if chunk in compact:
            tokens.add(chunk)
    return tokens


def _preference_tokens(preference: UserPreferenceMemory) -> set[str]:
    tokens = _tokenize(preference.value)
    tokens.add(preference.preference_type.value)
    tokens.add(preference.polarity.value)
    return tokens


def _is_scope_allowed(preference: UserPreferenceMemory, allowed_scopes: Iterable[str]) -> bool:
    allowed = {str(item).strip() for item in allowed_scopes if str(item).strip()}
    return not allowed or preference.scope.value in allowed or preference.scope.value == MemoryScope.local_life.value


def _preference_matches_query(preference: UserPreferenceMemory, query_text: str) -> bool:
    query_tokens = _tokenize(query_text)
    pref_tokens = _preference_tokens(preference)
    if not query_tokens or not pref_tokens:
        return False
    if preference.preference_type in {MemoryType.dietary_restriction, MemoryType.allergy, MemoryType.taste}:
        query_text_lower = str(query_text or "").lower()
        if any(token in query_text_lower for token in ("今天就想", "这次就想", "现在就想", "可以吃", "想吃", "要吃")):
            if preference.polarity in {MemoryPolarity.dislike, MemoryPolarity.avoid} and any(token in query_text_lower for token in ("吃辣", "辣", "重口", "刺激")):
                return False
    if query_tokens & pref_tokens:
        return True
    if preference.preference_type in {MemoryType.dietary_restriction, MemoryType.allergy, MemoryType.taste}:
        if any(token in query_text for token in ("想吃", "可以吃", "今天就想", "也可以", "想要", "更想")):
            return True
    return False


class InMemoryPreferenceBackend(PreferenceMemoryBackend):
    def __init__(self) -> None:
        self._store: dict[str, dict[str, UserPreferenceMemory]] = defaultdict(dict)

    def list_active(self, user_id: str) -> list[UserPreferenceMemory]:
        user_store = self._store.get(str(user_id or "").strip(), {})
        now = datetime.now(timezone.utc)
        return [pref for pref in user_store.values() if pref.status == MemoryStatus.active and not pref.is_expired(now)]

    def upsert(self, preference: UserPreferenceMemory) -> UserPreferenceMemory:
        item = preference.model_copy(deep=True)
        if not item.preference_id:
            item.preference_id = f"pref_{uuid4().hex[:12]}"
        now = _utcnow()
        if not item.created_at:
            item.created_at = now
        item.updated_at = now
        item.version = max(1, int(item.version or 1))
        item.status = MemoryStatus.active if item.status == MemoryStatus.active else item.status
        self._store[str(item.user_id or "").strip()][item.preference_id] = item
        return item

    def delete(self, user_id: str, preference_id: str) -> UserPreferenceMemory | None:
        user_store = self._store.get(str(user_id or "").strip(), {})
        pref = user_store.get(str(preference_id or "").strip())
        if pref is None:
            return None
        deleted = pref.model_copy(deep=True)
        deleted.status = MemoryStatus.deleted
        deleted.updated_at = _utcnow()
        user_store[deleted.preference_id] = deleted
        return deleted

    def read_context(self, context: MemoryReadContext) -> MemoryReadContext:
        active = self.list_active(context.user_id)
        related: list[UserPreferenceMemory] = []
        ignored: list[UserPreferenceMemory] = []
        conflicts: list[str] = []
        query = context.query_text or context.query_intent
        for pref in active:
            if not _is_scope_allowed(pref, context.allowed_scopes):
                ignored.append(pref)
                continue
            if _preference_matches_query(pref, query):
                related.append(pref)
            else:
                ignored.append(pref)

        related = sorted(
            related,
            key=lambda pref: (
                pref.preference_type.value not in {context.query_intent, ""},
                pref.polarity.value in {"dislike", "avoid"},
                pref.version,
            ),
        )

        if len(related) > context.max_items > 0:
            ignored.extend(related[context.max_items :])
            related = related[: context.max_items]

        conflict_groups: dict[str, list[UserPreferenceMemory]] = defaultdict(list)
        for pref in related:
            if pref.conflict_group:
                conflict_groups[pref.conflict_group].append(pref)
        for group, items in conflict_groups.items():
            if len(items) > 1:
                conflicts.append(group)

        return context.model_copy(
            update={
                "active_preferences": related,
                "memory_used": [pref.preference_id for pref in related],
                "memory_ignored": [pref.preference_id for pref in ignored],
                "memory_conflicts": conflicts,
            }
        )

    def apply_update_plan(self, plan: MemoryUpdatePlan) -> UserPreferenceMemory | None:
        if plan.operation == MemoryOperation.no_op:
            return None
        if plan.operation == MemoryOperation.delete:
            if plan.preference is not None:
                return self.delete(plan.preference.user_id, plan.preference.preference_id)
            if plan.target_preference_id and plan.preference is not None:
                return self.delete(plan.preference.user_id, plan.target_preference_id)
            return None
        if plan.preference is None:
            return None
        pref = plan.preference.model_copy(deep=True)
        pref.confidence = plan.confidence if plan.confidence else pref.confidence
        pref.evidence_ref = pref.evidence_ref or plan.source_text
        return self.upsert(pref)


def build_preference_memory(
    *,
    user_id: str,
    preference_type: MemoryType,
    value: str,
    polarity: MemoryPolarity = MemoryPolarity.like,
    scope: MemoryScope = MemoryScope.local_life,
    source: str = "explicit_user_statement",
    confidence: float = 0.0,
    evidence_ref: str = "",
    ttl_seconds: int | None = None,
    conflict_group: str = "",
    status: MemoryStatus = MemoryStatus.active,
) -> UserPreferenceMemory:
    now = _utcnow()
    return UserPreferenceMemory(
        user_id=str(user_id or "").strip(),
        preference_id="",
        preference_type=preference_type,
        value=str(value or "").strip(),
        polarity=polarity,
        scope=scope,
        source=source,
        confidence=confidence,
        evidence_ref=evidence_ref,
        created_at=now,
        updated_at=now,
        ttl_seconds=ttl_seconds,
        status=status,
        version=1,
        last_confirmed_at=now,
        conflict_group=conflict_group,
    )
