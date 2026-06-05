from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from learning_agent_service.domain.memory import MemoryPersistenceScope
from learning_agent_service.domain.utils import utcnow as _utcnow


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").lower())


def _contains_any(text: str, needles: Sequence[str]) -> bool:
    return any(needle and needle in text for needle in needles)


_SESSION_CUES = (
    "今天",
    "这次",
    "这回",
    "最近",
    "暂时",
    "先",
    "本周",
    "这周",
    "目前",
    "临时",
)

_PROFILE_CUES = (
    "以后",
    "今后",
    "从现在",
    "现在开始",
    "我不再",
    "不再",
    "戒",
    "长期",
    "一直",
    "以后都",
)

_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("food.spicy_preference", ("辣", "spicy", "微辣", "少辣", "重辣", "吃辣", "不吃辣", "忌辣", "戒辣")),
    ("food.allergy", ("过敏", "allergy", "忌口", "不能吃", "不吃", "花生", "海鲜", "牛奶", "鸡蛋")),
    ("dining.budget_per_person", ("预算", "人均", "每人", "多少钱", "块钱", "元", "块")),
    ("dining.preferred_area", ("区域", "商圈", "附近", "地段", "地铁", "位置", "商场")),
    ("answer_style.preference", ("风格", "回答风格", "answer style", "简洁", "详细", "啰嗦", "简短", "幽默")),
    ("project.current_topic", ("项目", "当前话题", "当前主题", "topic", "任务")),
)


@dataclass(frozen=True)
class PreferenceMemorySignal:
    preference_key: str
    current_value: str
    normalized_text: str
    persistence_scope: MemoryPersistenceScope = MemoryPersistenceScope.PROFILE
    should_update_profile: bool = False
    should_update_qdrant: bool = False
    requires_clarification: bool = False
    confidence: float = 0.0
    reason: str = ""
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    source_session_id: str | None = None
    source_turn_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PreferenceRule:
    key: str
    tokens: tuple[str, ...]

    def matches(self, normalized_text: str) -> bool:
        return _contains_any(normalized_text, self.tokens)


class PreferenceRegistry:
    """集中管理偏好 key / value / scope / session hint 规则。"""

    def __init__(self, rules: Iterable[PreferenceRule] | None = None) -> None:
        if rules is None:
            self._rules = tuple(PreferenceRule(key=key, tokens=tokens) for key, tokens in _RULES)
        else:
            self._rules = tuple(rules)
        self._rule_index = {rule.key: rule for rule in self._rules}

    @property
    def rules(self) -> tuple[PreferenceRule, ...]:
        return self._rules

    def normalize_key(self, text: str) -> str | None:
        normalized = _normalize_text(text)
        if not normalized:
            return None
        for rule in self._rules:
            if rule.matches(normalized):
                return rule.key
        return None

    def normalize_value(self, key: str, text: str) -> str | None:
        normalized = _normalize_text(text)
        if not normalized:
            return "unknown"

        if key == "food.spicy_preference":
            if _contains_any(normalized, ("不吃辣", "不想吃辣", "别吃辣", "少吃辣", "忌辣", "戒辣", "无辣", "免辣")):
                if _contains_any(normalized, _SESSION_CUES) or "最近" in normalized:
                    return "avoid_spicy_temporarily"
                return "no_spicy"
            if _contains_any(normalized, ("爱吃辣", "喜欢吃辣", "能吃辣", "吃辣", "重辣")):
                return "likes_spicy"
            if _contains_any(normalized, ("微辣", "少辣")):
                return "mild_only"
            return "unknown"

        if key == "food.allergy":
            for item in ("花生", "海鲜", "牛奶", "鸡蛋"):
                if item in normalized:
                    return f"avoid_{item}"
            if _contains_any(normalized, ("过敏", "忌口", "不能吃", "不吃")):
                return "avoid_unknown"
            return "unknown"

        if key == "dining.budget_per_person":
            match = re.search(r"(\d+(?:\.\d+)?)\s*(?:元|块|人民币)?", normalized)
            if match:
                return match.group(1)
            return normalized or "unknown"

        if key == "dining.preferred_area":
            for token in ("附近", "商圈", "地铁", "位置", "商场", "区域", "地段"):
                if token in normalized:
                    return token
            return normalized or "unknown"

        if key == "answer_style.preference":
            if _contains_any(normalized, ("简洁", "简短", "短一点", "少说点")):
                return "concise"
            if _contains_any(normalized, ("详细", "展开", "说细一点", "多说点")):
                return "detailed"
            if _contains_any(normalized, ("幽默", "风趣")):
                return "humorous"
            return "unknown"

        if key == "project.current_topic":
            return normalized or "unknown"

        return normalized or "unknown"

    def infer_scope(self, text: str, *, key: str | None = None) -> MemoryPersistenceScope:
        normalized = _normalize_text(text)
        if _contains_any(normalized, _SESSION_CUES):
            return MemoryPersistenceScope.SESSION
        if _contains_any(normalized, _PROFILE_CUES) or key in {
            "food.spicy_preference",
            "food.allergy",
            "dining.budget_per_person",
            "dining.preferred_area",
            "answer_style.preference",
        }:
            return MemoryPersistenceScope.PROFILE
        return MemoryPersistenceScope.LONG_TERM

    def requires_clarification(self, key: str, text: str, value: str) -> bool:
        normalized = _normalize_text(text)
        if key == "food.spicy_preference" and "最近" in normalized and value in {
            "avoid_spicy_temporarily",
            "unknown",
        }:
            return True
        if _contains_any(normalized, ("最近", "暂时", "先")) and key in self._rule_index:
            return True
        return False

    def is_long_term_intent(self, text: str, *, key: str | None = None) -> bool:
        normalized = _normalize_text(text)
        if _contains_any(normalized, _PROFILE_CUES):
            return True
        if key in {
            "food.spicy_preference",
            "food.allergy",
            "dining.budget_per_person",
            "dining.preferred_area",
            "answer_style.preference",
        }:
            return not _contains_any(normalized, _SESSION_CUES)
        return False

    def project_session_preferences(self, preferences: Mapping[str, Any] | Iterable[Mapping[str, Any]]) -> dict[str, Any]:
        if isinstance(preferences, Mapping):
            items = list(preferences.items())
        else:
            items = []
            for item in preferences:
                if not isinstance(item, Mapping):
                    continue
                key = str(item.get("preference_key") or "")
                value = item.get("current_value")
                if key:
                    items.append((key, value))

        projected: dict[str, Any] = {}
        local_life_preferences: list[str] = []
        local_life_avoid: list[str] = []
        profile_projection: dict[str, Any] = {}
        ignored_keys = {"current_profile", "local_life_preferences", "local_life_avoid", "answer_style_counter"}
        for raw_key, raw_value in items:
            key = str(raw_key or "").strip()
            if not key or key in ignored_keys:
                continue
            value = raw_value
            if isinstance(value, Mapping):
                value = value.get("current_value") or value.get("value")
            if value is None:
                continue
            value_text = str(value)
            profile_projection[key] = value_text
            if key == "food.spicy_preference":
                if value_text in {"likes_spicy", "mild_only"}:
                    local_life_preferences.append("spicy")
                elif value_text in {"no_spicy", "avoid_spicy_temporarily"}:
                    local_life_avoid.append("spicy")
            elif key == "food.allergy":
                local_life_avoid.append(value_text)
            elif key == "dining.preferred_area":
                local_life_preferences.append(value_text)
            elif key == "dining.budget_per_person":
                local_life_preferences.append(f"人均{value_text}元")
            elif key == "answer_style.preference":
                projected["preferred_output_style"] = value_text
            elif key == "project.current_topic":
                projected["current_topic"] = value_text

        if profile_projection:
            projected["current_profile"] = profile_projection
            projected.update(profile_projection)
        if local_life_preferences:
            projected["local_life_preferences"] = list(dict.fromkeys(local_life_preferences))
        if local_life_avoid:
            projected["local_life_avoid"] = list(dict.fromkeys(local_life_avoid))
        return projected

    def materialize_context(self, preferences: Mapping[str, Any] | Iterable[Mapping[str, Any]]) -> dict[str, Any]:
        return self.project_session_preferences(preferences)

    def normalize_signal(
        self,
        *,
        text: str,
        session_id: str | None = None,
        turn_id: str | None = None,
        answer_text: str | None = None,
    ) -> PreferenceMemorySignal | None:
        combined = " ".join(part for part in [text, answer_text or ""] if part).strip()
        key = self.normalize_key(combined)
        if key is None:
            return None

        normalized_value = self.normalize_value(key, combined)
        normalized_text = _normalize_text(combined)
        persistence_scope = self.infer_scope(combined, key=key)
        requires_clarification = self.requires_clarification(key, combined, normalized_value or "unknown")
        if requires_clarification:
            persistence_scope = MemoryPersistenceScope.SESSION
        confidence = 0.92 if persistence_scope == MemoryPersistenceScope.PROFILE else 0.68
        if _contains_any(normalized_text, ("现在开始", "以后", "从现在", "我不再", "以后都", "现在不吃辣了")):
            confidence = 0.96
        return PreferenceMemorySignal(
            preference_key=key,
            current_value=normalized_value or "unknown",
            normalized_text=normalized_text,
            persistence_scope=persistence_scope,
            should_update_profile=persistence_scope in {MemoryPersistenceScope.PROFILE, MemoryPersistenceScope.LONG_TERM}
            and not requires_clarification,
            should_update_qdrant=False,
            requires_clarification=requires_clarification,
            confidence=confidence,
            reason="session_only" if persistence_scope == MemoryPersistenceScope.SESSION else "profile_preference",
            effective_from=_utcnow(),
            source_session_id=session_id,
            source_turn_id=turn_id,
        )


DEFAULT_PREFERENCE_REGISTRY = PreferenceRegistry()
