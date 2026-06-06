from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from learning_agent_service.domain.contracts import PersistentSessionContext, TurnRuntimeState
from learning_agent_service.domain.utils import as_mapping as _as_mapping, clean_text as _clean_text


PersistentContext = PersistentSessionContext


def _temporal_scope_from_query(raw_query: str) -> str:
    compact = _clean_text(raw_query).replace(" ", "")
    if any(token in compact for token in ("以后", "从现在开始", "我不再", "我戒掉", "永远", "以后都")):
        return "long_term"
    if any(token in compact for token in ("今天", "这次", "暂时", "先", "先别", "临时")):
        return "session"
    return "neutral"


@dataclass(frozen=True)
class InputContext:
    raw_query: str
    latest_turn_message: str
    session_id: str
    user_id: str | None
    client_context: dict[str, Any] = field(default_factory=dict)
    request_ts: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PerceptionContext:
    raw_query: str
    normalized_query: str | None = None
    explicit_shop: dict[str, Any] | None = None
    client_selected_shop: dict[str, Any] | None = None
    explicit_constraints: dict[str, Any] = field(default_factory=dict)
    detected_facets: list[str] = field(default_factory=list)
    temporal_scope: str = "neutral"
    confidence: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MemoryArbitrationPolicy:
    priority_source: str = "latest_turn_message"
    session_keywords: tuple[str, ...] = ("今天", "这次", "暂时", "先", "先别", "临时")
    long_term_keywords: tuple[str, ...] = ("以后", "从现在开始", "我不再", "我戒掉", "永远", "以后都")
    strict_latest_turn: bool = True


@dataclass(frozen=True)
class MemoryArbitrationResult:
    effective_context: dict[str, Any]
    winning_sources: dict[str, Any]
    suppressed_memories: list[dict[str, Any]] = field(default_factory=list)
    promotion_candidates: list[dict[str, Any]] = field(default_factory=list)
    conflict_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_input_context(
    *,
    raw_query: str,
    latest_turn_message: str | None,
    session_id: str,
    user_id: str | None,
    client_context: Mapping[str, Any] | None,
    request_ts: datetime | None = None,
) -> InputContext:
    return InputContext(
        raw_query=_clean_text(raw_query),
        latest_turn_message=_clean_text(latest_turn_message or raw_query),
        session_id=_clean_text(session_id),
        user_id=_clean_text(user_id) or None,
        client_context=_as_mapping(client_context),
        request_ts=(request_ts or datetime.now(timezone.utc)).isoformat(),
    )


def build_perception_context(
    *,
    raw_query: str,
    normalized_query: str | None = None,
    slots: Any = None,
    client_context: Mapping[str, Any] | None = None,
    session_context: Mapping[str, Any] | None = None,
    confidence: float = 0.5,
) -> PerceptionContext:
    slot_map = _as_mapping(slots)
    client = _as_mapping(client_context)
    session = _as_mapping(session_context)
    explicit_shop = {
        "shop_id": slot_map.get("shop_id") or client.get("shopId") or client.get("shop_id") or session.get("selected_shop_id"),
        "shop_name": slot_map.get("shop_query") or client.get("shopName") or client.get("shop_name") or session.get("selected_shop_name"),
    }
    explicit_shop = {key: value for key, value in explicit_shop.items() if value not in (None, "")}
    client_selected_shop = {
        "shop_id": client.get("shopId") or client.get("shop_id") or session.get("selected_shop_id"),
        "shop_name": client.get("shopName") or client.get("shop_name") or session.get("selected_shop_name"),
    }
    client_selected_shop = {key: value for key, value in client_selected_shop.items() if value not in (None, "")}
    constraints = {
        "city": slot_map.get("city") or client.get("city") or session.get("current_city"),
        "location": slot_map.get("location") or client.get("location") or session.get("current_location"),
        "scene": slot_map.get("scene"),
        "category": slot_map.get("category"),
        "preferences": list(slot_map.get("preferences") or []),
        "avoid": list(slot_map.get("avoid") or []),
    }
    detected_facets: list[str] = []
    for name in ("coupon", "open_status", "distance_eta", "scene_fit", "recommendation", "recommendation_reason"):
        tokens = {
            "coupon": ("券", "优惠", "团购", "代金券"),
            "open_status": ("营业", "开门", "营业时间"),
            "distance_eta": ("距离", "有多远", "导航", "怎么走"),
            "scene_fit": ("约会", "家庭", "安静", "带娃", "适合"),
            "recommendation": ("推荐", "几家", "附近", "周边"),
            "recommendation_reason": ("为什么", "理由", "原因"),
        }.get(name, ())
        compact = _clean_text(raw_query).replace(" ", "")
        if any(token in compact for token in tokens):
            detected_facets.append(name)
    temporal_scope = _temporal_scope_from_query(raw_query)
    return PerceptionContext(
        raw_query=_clean_text(raw_query),
        normalized_query=_clean_text(normalized_query) or None,
        explicit_shop=explicit_shop or None,
        client_selected_shop=client_selected_shop or None,
        explicit_constraints={key: value for key, value in constraints.items() if value not in (None, "", [], {})},
        detected_facets=list(dict.fromkeys(detected_facets)),
        temporal_scope=temporal_scope,
        confidence=float(confidence or 0.5),
    )


def build_memory_arbitration_result(
    *,
    merged_context: Mapping[str, Any],
    winning_sources: Mapping[str, Any] | None = None,
    suppressed_memories: list[dict[str, Any]] | None = None,
    promotion_candidates: list[dict[str, Any]] | None = None,
    conflict_reason: str | None = None,
) -> MemoryArbitrationResult:
    return MemoryArbitrationResult(
        effective_context=_as_mapping(merged_context),
        winning_sources=_as_mapping(winning_sources),
        suppressed_memories=list(suppressed_memories or []),
        promotion_candidates=list(promotion_candidates or []),
        conflict_reason=conflict_reason,
    )


__all__ = [
    "InputContext",
    "MemoryArbitrationPolicy",
    "MemoryArbitrationResult",
    "PersistentContext",
    "PerceptionContext",
    "TurnRuntimeState",
    "build_input_context",
    "build_memory_arbitration_result",
    "build_perception_context",
]
