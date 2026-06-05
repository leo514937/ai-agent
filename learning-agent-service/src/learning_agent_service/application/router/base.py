from __future__ import annotations

import re

from collections.abc import Mapping, Sequence
from typing import Any

from ...config import get_settings
from ...domain.contracts import EvidenceItem, RetrievalEligibility, RoutingDecision


_PUNCT_ONLY_RE = re.compile(r"^[\s\W_]+$", re.UNICODE)
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_+#.:-]+|[\u4e00-\u9fff]+")
_NOISE_REPEAT_RE = re.compile(r"^(.)\1{5,}$", re.UNICODE)

_LOW_INFO_TOKENS = {
    "嗯", "啊", "哦", "唔", "好", "然后", "还有", "那", "这个", "那个",
    "就是", "对", "行", "可以", "额", "呃", "嗯嗯",
}

_GREETING_TOKENS = ("你好", "您好", "嗨", "hello", "hi", "hey")
_THANKS_TOKENS = ("谢谢", "多谢", "感谢", "辛苦了")
_PROFILE_TOKENS = ("你有什么功能", "有什么功能", "能做什么", "你会什么", "你是谁", "你是什么", "怎么用你")

_REFERENCE_TOKENS = (
    "这个呢", "那家呢", "第二个呢", "第二家呢", "第一个呢",
    "它呢", "这家", "那家", "这个店", "那个店", "这个套餐", "那个套餐",
    "第二个", "第二家", "第一个", "前一个", "后一个",
)

_INCOMPLETE_RECOMMEND_TOKENS = (
    "附近有什么推荐", "有什么推荐", "推荐一下", "帮我推荐",
    "有什么好的", "附近有啥", "附近好吃", "周边推荐",
)

_MEMORY_UPDATE_TOKENS = ("以后", "一直", "长期", "记住", "习惯", "不吃辣", "少吃辣", "不吃香菜", "不吃牛肉", "偏好")
_SESSION_ONLY_TOKENS = ("今天", "这次", "暂时", "今晚", "这顿", "这回", "本次")

_RETRIEVAL_ACTIONS = {"rag_retrieval", "rag_plus_tool"}
_NON_RETRIEVAL_ACTIONS = {"direct_answer", "clarify", "memory_update", "no_op", "reject", "tool_call"}
_DIRECT_ACTIONS = {"direct_answer", "clarify", "memory_update", "no_op", "reject"}

_RETRIEVAL_SCORE_THRESHOLD = 0.55

_PHASE0_TRACE_KEY = "phase0_trace"
_PHASE1_TRACE_KEY = "phase1_trace"
_PHASE2_TRACE_KEY = "phase2_trace"
_PHASE3_TRACE_KEY = "phase3_trace"
_PHASE4_TRACE_KEY = "phase4_trace"

_LOCAL_LIFE_QUERY_TOKENS = (
    "附近", "周边", "推荐", "火锅", "烤肉", "火锅店", "餐厅", "饭店", "店",
    "适合", "约会", "带父母", "带长辈", "现在营业", "营业", "开门",
    "还能用", "优惠券", "券", "团购", "套餐", "人均", "不踩雷", "不吵",
)

_UNSERVICEABLE_LOCATION_TOKENS = ("北极", "南极")

_PHASE1_DATA_SOURCE_SLOT = "slot"
_PHASE1_DATA_SOURCE_STATIC_RAG = "static_rag"
_PHASE1_DATA_SOURCE_DYNAMIC_TOOL = "dynamic_tool"
_PHASE1_DATA_SOURCE_CLIENT_CONTEXT = "client_context"
_PHASE1_DATA_SOURCE_MIXED = "mixed"


def _phase1_flags() -> tuple[bool, bool, bool]:
    settings = get_settings()
    return (
        bool(getattr(settings, "enable_route_review", True)),
        bool(getattr(settings, "enable_required_facets", True)),
        bool(getattr(settings, "enable_min_entity_consistency_check", True)),
    )


def _phase1_plan_flags() -> bool:
    settings = get_settings()
    return bool(getattr(settings, "enable_required_facets_to_plans", True))


def _phase2_flags() -> tuple[bool, bool, bool]:
    settings = get_settings()
    return (
        bool(getattr(settings, "enable_partial_grounded", True)),
        bool(getattr(settings, "enable_slot_clarify", True)),
        bool(getattr(settings, "enable_rag_plus_tool_partial_answer", True)),
    )


def _phase3_flags() -> bool:
    settings = get_settings()
    return bool(getattr(settings, "enable_task_plan_for_local_life", True))


def _phase4_flags() -> tuple[bool, str]:
    settings = get_settings()
    return (
        bool(getattr(settings, "enable_answer_verifier", True)),
        str(getattr(settings, "answer_verifier_mode", "warn_only") or "warn_only").strip().lower() or "warn_only",
    )


def _phase4_mode() -> str:
    settings = get_settings()
    return str(getattr(settings, "answer_verifier_mode", "warn_only") or "warn_only").strip().lower() or "warn_only"


def _update_phase0_trace(state: Any, **updates: Any) -> Any:
    turn = state["turn"]
    runtime = state["runtime"]
    turn_extra = dict(getattr(turn, "extra", {}) or {})
    phase0_trace = dict(turn_extra.get(_PHASE0_TRACE_KEY, {}) or {})
    phase0_trace.update(updates)
    turn_extra[_PHASE0_TRACE_KEY] = phase0_trace
    state["turn"] = turn.model_copy(update={"extra": turn_extra})
    runtime_metrics = dict(getattr(runtime, "metrics", {}) or {})
    runtime_phase0_trace = dict(runtime_metrics.get(_PHASE0_TRACE_KEY, {}) or {})
    runtime_phase0_trace.update(updates)
    runtime_metrics[_PHASE0_TRACE_KEY] = runtime_phase0_trace
    state["runtime"] = runtime.model_copy(update={"metrics": runtime_metrics})
    return state


def _update_phase1_trace(state: Any, **updates: Any) -> Any:
    turn = state["turn"]
    runtime = state["runtime"]
    turn_extra = dict(getattr(turn, "extra", {}) or {})
    phase1_trace = dict(turn_extra.get(_PHASE1_TRACE_KEY, {}) or {})
    phase1_trace.update(updates)
    turn_extra[_PHASE1_TRACE_KEY] = phase1_trace
    state["turn"] = turn.model_copy(update={"extra": turn_extra})
    runtime_metrics = dict(getattr(runtime, "metrics", {}) or {})
    runtime_phase1_trace = dict(runtime_metrics.get(_PHASE1_TRACE_KEY, {}) or {})
    runtime_phase1_trace.update(updates)
    runtime_metrics[_PHASE1_TRACE_KEY] = runtime_phase1_trace
    state["runtime"] = runtime.model_copy(update={"metrics": runtime_metrics})
    return state


def _update_phase2_trace(state: Any, **updates: Any) -> Any:
    turn = state["turn"]
    runtime = state["runtime"]
    turn_extra = dict(getattr(turn, "extra", {}) or {})
    phase2_trace = dict(turn_extra.get(_PHASE2_TRACE_KEY, {}) or {})
    phase2_trace.update(updates)
    turn_extra[_PHASE2_TRACE_KEY] = phase2_trace
    state["turn"] = turn.model_copy(update={"extra": turn_extra})
    runtime_metrics = dict(getattr(runtime, "metrics", {}) or {})
    runtime_phase2_trace = dict(runtime_metrics.get(_PHASE2_TRACE_KEY, {}) or {})
    runtime_phase2_trace.update(updates)
    runtime_metrics[_PHASE2_TRACE_KEY] = runtime_phase2_trace
    state["runtime"] = runtime.model_copy(update={"metrics": runtime_metrics})
    return state


def _update_phase3_trace(state: Any, **updates: Any) -> Any:
    turn = state["turn"]
    runtime = state["runtime"]
    turn_extra = dict(getattr(turn, "extra", {}) or {})
    phase3_trace = dict(turn_extra.get(_PHASE3_TRACE_KEY, {}) or {})
    phase3_trace.update(updates)
    turn_extra[_PHASE3_TRACE_KEY] = phase3_trace
    state["turn"] = turn.model_copy(update={"extra": turn_extra})
    runtime_metrics = dict(getattr(runtime, "metrics", {}) or {})
    runtime_phase3_trace = dict(runtime_metrics.get(_PHASE3_TRACE_KEY, {}) or {})
    runtime_phase3_trace.update(updates)
    runtime_metrics[_PHASE3_TRACE_KEY] = runtime_phase3_trace
    state["runtime"] = runtime.model_copy(update={"metrics": runtime_metrics})
    return state


def _update_phase4_trace(state: Any, **updates: Any) -> Any:
    turn = state["turn"]
    runtime = state["runtime"]
    turn_extra = dict(getattr(turn, "extra", {}) or {})
    phase4_trace = dict(turn_extra.get(_PHASE4_TRACE_KEY, {}) or {})
    phase4_trace.update(updates)
    turn_extra[_PHASE4_TRACE_KEY] = phase4_trace
    state["turn"] = turn.model_copy(update={"extra": turn_extra})
    runtime_metrics = dict(getattr(runtime, "metrics", {}) or {})
    runtime_phase4_trace = dict(runtime_metrics.get(_PHASE4_TRACE_KEY, {}) or {})
    runtime_phase4_trace.update(updates)
    runtime_metrics[_PHASE4_TRACE_KEY] = runtime_phase4_trace
    state["runtime"] = runtime.model_copy(update={"metrics": runtime_metrics})
    return state


def _normalize_entity_key(value: Any) -> str | None:
    if value is None:
        return None
    raw = getattr(value, "value", value)
    if raw in (None, "", [], {}, ()):
        return None
    text = str(raw).strip()
    return text or None


def _extract_entity_key_from_evidence_item(item: EvidenceItem) -> str | None:
    metadata = dict(getattr(item, "metadata", {}) or {})
    for key in ("shop_id", "shopId", "merchant_id", "merchantId", "entity_id", "entityId"):
        value = _normalize_entity_key(metadata.get(key))
        if value:
            return value
    return _normalize_entity_key(getattr(item, "parent_chunk_id", None)) or _normalize_entity_key(getattr(item, "document_id", None))


def _extract_entity_key_from_tool_result(tool_result: Any) -> str | None:
    if tool_result is None:
        return None
    payload = getattr(tool_result, "normalized_output", None)
    if not isinstance(payload, Mapping):
        payload = {}
    for key in ("shop_id", "shopId", "merchant_id", "merchantId", "entity_id", "entityId"):
        value = _normalize_entity_key(payload.get(key))
        if value:
            return value
    shop = payload.get("shop") if isinstance(payload.get("shop"), Mapping) else {}
    if isinstance(shop, Mapping):
        for key in ("shop_id", "shopId", "id", "name", "shop_name"):
            value = _normalize_entity_key(shop.get(key))
            if value:
                return value
    data = payload.get("data") if isinstance(payload.get("data"), Mapping) else {}
    if isinstance(data, Mapping):
        for key in ("shop_id", "shopId", "merchant_id", "merchantId", "entity_id", "entityId"):
            value = _normalize_entity_key(data.get(key))
            if value:
                return value
    return None


def _extract_entity_values_from_mapping(mapping: Mapping[str, Any], *keys: str) -> list[str]:
    values: list[str] = []
    for key in keys:
        value = mapping.get(key)
        if value in (None, "", [], {}, ()):
            continue
        if isinstance(value, (list, tuple, set)):
            for item in value:
                normalized = _normalize_entity_key(item)
                if normalized and normalized not in values:
                    values.append(normalized)
            continue
        normalized = _normalize_entity_key(value)
        if normalized and normalized not in values:
            values.append(normalized)
    return values


def _routing_from_turn(turn: Any) -> RoutingDecision | None:
    routing = getattr(turn, "routing_decision", None)
    if isinstance(routing, RoutingDecision):
        return routing
    return None


def routing_trace_payload(routing: RoutingDecision | None) -> dict[str, Any]:
    if routing is None:
        return {}
    return routing.model_dump(mode="json")


def should_run_tool(routing: RoutingDecision | None) -> bool:
    return bool(
        routing is not None
        and not routing.blocked
        and routing.should_call_tool
        and str(routing.required_action).strip().lower() in {"tool_call", "rag_plus_tool"}
    )


def should_persist_memory(routing: RoutingDecision | None) -> bool:
    return bool(routing is not None and routing.should_persist_memory)


def _apply_phase1_routing_extra(turn_extra: dict[str, Any], routing: RoutingDecision | None) -> dict[str, Any]:
    if routing is None:
        return turn_extra
    merged = dict(turn_extra)
    routing_extra = dict(getattr(routing, "extra", {}) or {})
    for key in ("route_review_decision", "required_facets", "optional_facets", "required_facets_source_constraints", "user_need"):
        value = routing_extra.get(key)
        if value is not None:
            merged[key] = value
    return merged
