"""Clarification handling for pending multi-turn questions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4

from .. import config
from ..domain.enums import MissingSlotType
from ..domain.schemas import ClarificationRequest, PendingClarification, ResolveShopResult, ShopRef
from ..domain.state import SessionState
from ..semantic.slot_extractor import extract_slots
from .reference_resolver import resolve_comparison_targets, resolve_references
from .shop_resolver import resolve_shop_entity


_TOPIC_SWITCH_HINTS = (
    "算了",
    "换一家",
    "换个",
    "重新",
    "重新推荐",
    "讲个笑话",
    "笑话",
    "别查了",
    "不查了",
)


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        return dumped if isinstance(dumped, dict) else {}
    return dict(getattr(value, "__dict__", {}) or {})


_MISSING_SLOT_PROMPTS: dict[str, str] = {
    "missing_shop_target": "请提供完整店名。",
    "missing_shop": "请提供完整店名。",
    "ambiguous_shop_name": "我找到了几个可能的店，请再确认具体店名。",
    "ambiguous_shop": "我找到了几个可能的店，请再确认具体店名。",
    "ambiguous_comparison_targets": "请说明要比较哪几家店。",
    "unresolved_reference": "请提供完整店名。",
    "unresolved_deictic_reference": "请提供完整店名。",
    "unresolved_ordinal_reference": "请说明你说的是第几家店。",
    "missing_location": "请提供位置、商圈或附近范围。",
    "missing_category": "请补充你想找的品类。",
    "missing_comparison_targets": "请说明要比较哪几家店。",
    "missing_exploration_location": "请提供出发地、位置或行程起点。",
    "low_confidence_semantic_parse": "我没完全理解你的意思，请换一种说法。",
    "unsupported_facet": "当前暂时无法确认这个服务项，请换一个更具体的查询，或改查优惠券、营业状态、距离等已支持信息。",
    "cancel": "已取消当前问题。",
    "new_task_override": "请直接说明新的需求。",
    "constraint_update": "请补充你想调整的条件。",
    "no_result_refine_constraints": "暂时没有找到结果，可以换个范围、品类或条件再试。",
    "tool_failure_degraded": "相关工具暂时不可用，请稍后重试或换个条件。",
}


def _slot_type_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, MissingSlotType):
        return value.value
    return str(value or "").strip()


def _resume_strategy_for_slot(missing_slot_type: str, reason: str = "") -> str:
    slot = str(missing_slot_type or "").strip()
    reason_lower = str(reason or "").lower()
    if reason_lower in {"cancel", "cancelled"} or slot == "cancel":
        return "cancel_pending_task"
    if reason_lower in {"new_task_override", "topic_switch"} or slot == "new_task_override":
        return "start_new_task"
    if slot == "missing_location":
        return "fill_missing_location"
    if slot == "missing_shop":
        return "fill_missing_shop"
    if slot in {"missing_shop_target", "ambiguous_shop", "unresolved_reference"}:
        return "resolve_shop_reference"
    if slot in {"missing_comparison_targets", "ambiguous_comparison_targets"}:
        return "fill_missing_comparison_targets"
    if slot == "missing_exploration_location":
        return "fill_missing_exploration_location"
    if slot == "missing_category":
        return "ask_clarification_again"
    if slot == "unresolved_deictic_reference":
        return "resolve_deictic_reference"
    if slot == "unresolved_ordinal_reference":
        return "resolve_ordinal_reference"
    if slot == "constraint_update":
        return "apply_constraint_update"
    if slot == "low_confidence_semantic_parse":
        return "ask_clarification_again"
    return "ask_clarification_again"


def _task_type_source_for_strategy(strategy: str) -> str:
    if strategy in {"start_new_task", "cancel_pending_task"}:
        return "clarification_resume"
    if strategy.startswith("fill_") or strategy.startswith("resolve_") or strategy == "apply_constraint_update":
        return "clarification_resume"
    return "clarification_resume"


def _merge_semantic_frame(
    original_frame: dict[str, Any],
    reply_frame: dict[str, Any],
    *,
    selected_candidate: dict[str, Any] | None = None,
    resolved_target: dict[str, Any] | None = None,
    comparison_targets: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    merged = dict(original_frame or {})
    reply = dict(reply_frame or {})
    selective_keys = {
        "task_type",
        "primary_task",
        "workflow_hint",
        "comparison_intent",
        "comparison_structure",
        "comparison_facets",
        "exploration_stages",
        "missing_slots",
        "preferences",
        "preference_signals",
        "location",
        "category",
        "shop_target",
        "reference",
        "location_reference",
        "shop_reference",
        "ordinal_reference",
        "deictic_reference",
        "filters",
        "filter_signals",
        "merchant_mentions",
        "brand_mentions",
        "branch_mentions",
        "surface_hints",
        "alias_hints",
        "reference_mentions",
        "comparison_targets",
        "ordinal_references",
        "deictic_references",
        "focused_facets",
        "comparison_focus",
        "hard_constraints",
        "soft_preferences",
        "ranking_signals",
        "follow_up",
        "confidence",
        "need_context",
        "discourse_marker",
        "constraint_update",
        "new_task_override",
        "cancel_intent",
        "missing_slot_type",
    }
    for key in selective_keys:
        value = reply.get(key)
        if value not in (None, "", [], {}, False):
            merged[key] = value
    if selected_candidate:
        candidate = dict(selected_candidate)
        merged["merchant_mentions"] = [candidate.get("shop_name", "")] if candidate.get("shop_name") else merged.get("merchant_mentions", [])
        merged["shop_target"] = {
            "shop_id": str(candidate.get("shop_id", "") or "").strip(),
            "shop_name": str(candidate.get("shop_name", "") or "").strip(),
        }
    if resolved_target:
        merged["shop_target"] = {
            "shop_id": str(resolved_target.get("shop_id", "") or "").strip(),
            "shop_name": str(resolved_target.get("shop_name", "") or "").strip(),
        }
    if comparison_targets is not None:
        merged["comparison_targets"] = list(comparison_targets)
        if comparison_targets:
            merged["reference_mentions"] = [
                str(item.get("shop_name", "") or item.get("source_text", "") or "").strip()
                for item in comparison_targets
                if str(item.get("shop_name", "") or item.get("source_text", "") or "").strip()
            ]
    return merged


def _infer_missing_slot_type(
    *,
    original_text: str,
    original_semantic_frame: dict[str, Any] | Any,
    original_task_type: str,
    reason: str,
    candidate_targets: list[dict[str, Any]],
) -> str:
    text = str(original_text or "").strip()
    frame = _as_dict(original_semantic_frame)
    task_type = str(original_task_type or frame.get("task_type", "") or "").strip()
    workflow_hint = str(frame.get("workflow_hint", "") or "").strip()
    reason_lower = str(reason or "").lower()
    has_candidate_targets = bool(candidate_targets)
    has_deictic_ref = bool(frame.get("deictic_references") or any(token in text for token in ("这家", "那家", "这间", "那间")))
    has_ordinal_ref = bool(frame.get("ordinal_references") or any(token in text for token in ("第一家", "第二家", "第三家", "第一个", "第二个", "第三个")))
    has_exploration_stage = bool(frame.get("exploration_stages"))

    if reason_lower in {"comparison_targets_need_clarification", "comparison_requires_at_least_two_shops", "comparison_too_many_shops"}:
        return "missing_comparison_targets"
    if reason_lower in {"ambiguous_shop", "ambiguous_shop_name"}:
        return "ambiguous_shop"
    if reason_lower in {"ambiguous_comparison_targets"}:
        return "ambiguous_comparison_targets"
    if reason_lower in {"tool_failure", "tool_failure_degraded"}:
        return "tool_failure_degraded"
    if reason_lower in {"no_result", "no_result_refine_constraints"}:
        return "no_result_refine_constraints"
    if reason_lower in {"low_confidence", "low_confidence_semantic_parse"}:
        return "low_confidence_semantic_parse"

    if task_type in {"comparison", "deal_compare"}:
        if has_candidate_targets and len(candidate_targets) < 2:
            return "missing_comparison_targets"
        if has_deictic_ref or has_ordinal_ref or frame.get("comparison_targets") or frame.get("reference_mentions"):
            return "missing_comparison_targets"
        return "missing_comparison_targets"
    if task_type in {"local_trip_plan", "date_plan", "family_activity_plan", "coffee_then_dinner", "eat_and_play_plan"} or has_exploration_stage:
        return "missing_exploration_location"
    if task_type in {"recommendation", "discovery"} and (frame.get("category") or any(token in text for token in ("火锅", "烧烤", "餐厅", "咖啡", "甜品", "酒店", "景点"))):
        if not frame.get("location_reference") and not frame.get("location"):
            nearby_tokens = ("附近", "周边", "周围", "就近", "离我近", "离我近点")
            if not any(token in text for token in nearby_tokens):
                return "missing_location"

    if has_deictic_ref:
        return "unresolved_deictic_reference"
    if has_ordinal_ref:
        return "unresolved_ordinal_reference"
    if frame.get("reference_mentions") or frame.get("ordinal_references") or frame.get("deictic_references"):
        return "unresolved_reference"
    supported_facet_hints = (
        "券",
        "优惠",
        "营业",
        "开门",
        "关门",
        "打烊",
        "距离",
        "多远",
        "多久能到",
        "评分",
        "人均",
        "评价",
        "推荐",
        "对比",
    )
    unsupported_service_cues = (
        "有没有",
        "是否",
        "能不能",
        "能否",
        "可不可以",
        "提供",
        "支持",
        "服务",
        "设施",
    )
    if (
        (has_candidate_targets or task_type in {"single_shop_query", "coupon_query"} or any(token in text for token in ("店", "店铺", "门店")))
        and any(token in text for token in unsupported_service_cues)
        and not any(token in text for token in supported_facet_hints)
    ):
        return "unsupported_facet"
    if frame.get("comparison_targets") and len(candidate_targets) < 2:
        return "missing_comparison_targets"
    if has_candidate_targets and len(candidate_targets) > 1:
        return "ambiguous_shop"
    if any(token in text for token in ("附近", "周边", "周围", "商圈", "学校附近", "地铁口")):
        return "missing_location"
    if any(token in text for token in ("火锅", "烧烤", "餐厅", "咖啡", "甜品", "酒店", "景点")):
        return "missing_category"
    return "missing_shop"


def _format_missing_slot_prompt(missing_slot_type: str) -> str:
    return _MISSING_SLOT_PROMPTS.get(missing_slot_type, "请补充更明确的信息。")


@lru_cache(maxsize=1)
def _seed_shop_id_mapping() -> dict[str, str]:
    """Load the canonical shop-id mapping used by local seed fixtures."""
    mapping_path = Path(__file__).resolve().parents[2] / "db" / "seed" / "local_life" / "normalized_shop_id_mapping.json"
    try:
        raw = json.loads(mapping_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    mapping: dict[str, str] = {}
    for key, value in raw.items():
        key_text = str(key or "").strip()
        value_text = str(value or "").strip()
        if key_text and value_text:
            mapping[key_text] = value_text
    return mapping


def _canonicalize_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """Normalize fixture ids like shop_007 to the seed canonical ids."""
    item = _as_dict(candidate)
    shop_id = str(item.get("shop_id", "") or "").strip()
    mapped_id = _seed_shop_id_mapping().get(shop_id)
    if mapped_id:
        item["shop_id"] = mapped_id
    return item


def _candidate_sort_key(candidate: dict[str, Any]) -> tuple[int, int, str]:
    shop_id = str(candidate.get("shop_id", "") or "").strip()
    if shop_id.isdigit():
        group = 0 if len(shop_id) >= 6 else 1
        numeric = int(shop_id)
    elif shop_id.startswith("shop_"):
        group = 2
        numeric = 0
    else:
        group = 3
        numeric = 0
    return (group, numeric, str(candidate.get("shop_name", "") or "").strip())


def _pending_candidates(pending: PendingClarification | dict[str, Any] | None) -> list[dict[str, Any]]:
    if pending is None:
        return []
    data = _as_dict(pending)
    candidates: list[dict[str, Any]] = []
    for item in data.get("candidate_targets", []) or []:
        candidate = _canonicalize_candidate(_as_dict(item))
        if candidate.get("shop_id") and candidate.get("shop_name"):
            candidates.append(candidate)
    return candidates


def _session_get(session_state: dict | SessionState | None, field: str) -> Any:
    if session_state is None:
        return None
    if isinstance(session_state, SessionState):
        return getattr(session_state, field, None)
    if isinstance(session_state, dict):
        return session_state.get(field)
    return getattr(session_state, field, None)


def _pending_expired(pending: PendingClarification | dict[str, Any] | None) -> bool:
    data = _as_dict(pending)
    expires_at = data.get("expires_at")
    if expires_at is None:
        created_at = data.get("created_at")
        if created_at is None:
            return False
        try:
            expires_at = created_at + timedelta(seconds=config.CLARIFICATION_TTL_SECONDS)
        except Exception:
            return False

    now = datetime.now(timezone.utc)
    if hasattr(expires_at, "tzinfo") and getattr(expires_at, "tzinfo", None) is not None:
        expiry = expires_at.astimezone(timezone.utc)
    elif hasattr(expires_at, "replace"):
        expiry = expires_at.replace(tzinfo=timezone.utc)
    else:
        return False
    return now >= expiry


def _parse_selection(text: str) -> int | None:
    compact = (text or "").strip().replace(" ", "")
    if not compact:
        return None
    if compact.isdigit():
        return int(compact)

    aliases = {
        "第一个": 1,
        "第一家": 1,
        "第一": 1,
        "第1个": 1,
        "第1家": 1,
        "第2个": 2,
        "第二个": 2,
        "第二家": 2,
        "第二": 2,
        "第3个": 3,
        "第三个": 3,
        "第三家": 3,
        "第三": 3,
    }
    for key, value in aliases.items():
        if key in compact:
            return value
    return None


def _match_candidate_text(text: str, candidates: list[dict[str, Any]]) -> tuple[int | None, dict[str, Any] | None]:
    compact = (text or "").strip()
    if not compact:
        return None, None
    for index, candidate in enumerate(candidates, start=1):
        shop_name = str(candidate.get("shop_name", ""))
        address = str(candidate.get("address", ""))
        alias = str(candidate.get("alias", ""))
        if any(token and token in compact for token in (shop_name, address, alias)):
            return index, candidate
    return None, None


def build_pending_clarification(
    *,
    original_text: str,
    original_semantic_frame: dict[str, Any] | Any,
    original_task_type: str,
    candidate_targets: list[dict[str, Any]],
    reason: str,
    source_node: str = "target_resolve",
    expected_reply_type: str = "shop_selection",
    missing_slot_type: str = "",
    already_resolved_targets: list[dict[str, Any]] | None = None,
    ambiguous_target_slot: str = "",
    resume_strategy: str = "",
) -> PendingClarification:
    """Construct a pending clarification payload with TTL metadata."""
    now = datetime.now(timezone.utc)
    frame = _as_dict(original_semantic_frame)
    task_type_value = original_task_type.value if hasattr(original_task_type, "value") else str(original_task_type or "")
    prepared_candidates = []
    for candidate in candidate_targets:
        item = _canonicalize_candidate(_as_dict(candidate))
        if item.get("shop_id") and item.get("shop_name"):
            prepared_candidates.append(
                {
                    "shop_id": str(item.get("shop_id", "")),
                    "shop_name": str(item.get("shop_name", "")),
                    "address": str(item.get("address", "")),
                }
            )
    prepared_candidates.sort(key=_candidate_sort_key)
    slot_type = str(missing_slot_type or "").strip() or _infer_missing_slot_type(
        original_text=original_text,
        original_semantic_frame=frame,
        original_task_type=task_type_value,
        reason=reason,
        candidate_targets=prepared_candidates,
    )
    resume_strategy_value = str(resume_strategy or "").strip()
    if resume_strategy_value in {"", "resume_original_task"}:
        inferred_resume_strategy = _resume_strategy_for_slot(slot_type, reason=reason)
    else:
        inferred_resume_strategy = resume_strategy_value
    return PendingClarification(
        pending_id=f"pc_{uuid4().hex[:12]}",
        original_task_type=task_type_value,
        candidate_targets=prepared_candidates,
        missing_slot_type=slot_type,
        expected_reply_type=expected_reply_type,
        created_at=now,
        expires_at=now + timedelta(seconds=config.CLARIFICATION_TTL_SECONDS),
        original_text=original_text,
        original_semantic_frame=frame or None,
        already_resolved_targets=[_as_dict(item) for item in (already_resolved_targets or []) if _as_dict(item)],
        ambiguous_target_slot=ambiguous_target_slot,
        resume_strategy=inferred_resume_strategy,
        reason=reason,
        source_node=source_node,
    )


def build_clarification_request(
    pending: PendingClarification | dict[str, Any],
    *,
    question: str = "",
    source_stage: str = "",
    freshness_meta: Any | None = None,
) -> ClarificationRequest:
    """Normalize pending clarification into the unified request DTO."""

    data = _as_dict(pending)
    candidate_options = [
        _canonicalize_candidate(_as_dict(item))
        for item in (data.get("candidate_targets", []) or [])
        if _as_dict(item).get("shop_id") or _as_dict(item).get("shop_name")
    ]
    resume_context = {
        "original_text": str(data.get("original_text", "") or ""),
        "original_task_type": str(data.get("original_task_type", "") or ""),
        "reason": str(data.get("reason", "") or ""),
        "source_node": str(data.get("source_node", "") or ""),
        "resume_strategy": str(data.get("resume_strategy", "") or ""),
        "ambiguous_target_slot": str(data.get("ambiguous_target_slot", "") or ""),
        "already_resolved_targets": [
            _as_dict(item)
            for item in (data.get("already_resolved_targets", []) or [])
            if _as_dict(item)
        ],
    }
    clarification_type = str(data.get("missing_slot_type", "") or data.get("reason", "") or "").strip()
    return ClarificationRequest(
        clarification_id=str(data.get("pending_id", "") or ""),
        clarification_type=clarification_type,
        question=str(question or format_pending_prompt(data)).strip(),
        missing_slots=[clarification_type] if clarification_type else [],
        candidate_options=candidate_options,
        resume_context=resume_context,
        source_stage=str(source_stage or data.get("source_node", "") or "").strip(),
        expires_at=data.get("expires_at"),
        freshness_meta=freshness_meta,
        pending_id=str(data.get("pending_id", "") or ""),
        original_task_type=str(data.get("original_task_type", "") or ""),
        reason=str(data.get("reason", "") or ""),
        resume_strategy=str(data.get("resume_strategy", "") or ""),
    )


def format_pending_prompt(pending: PendingClarification | dict[str, Any]) -> str:
    """Format the clarification prompt shown to the user."""
    candidates = _pending_candidates(pending)
    data = _as_dict(pending)
    reason = str(data.get("reason", "") or "")
    if reason == "comparison_requires_at_least_two_shops":
        return "对比至少需要两家不同的店，请补充另一家店名。"
    if reason == "comparison_too_many_shops":
        return "最多支持 5 家店对比，请缩小范围后再试。"
    missing_slot_type = str(data.get("missing_slot_type", "") or "").strip()
    if not missing_slot_type:
        missing_slot_type = _infer_missing_slot_type(
            original_text=str(data.get("original_text", "") or ""),
            original_semantic_frame=_as_dict(data.get("original_semantic_frame")),
            original_task_type=str(data.get("original_task_type", "") or ""),
            reason=reason,
            candidate_targets=candidates,
        )
    if candidates and (
        reason in {"ambiguous", "ambiguous_shop", "ambiguous_shop_name"}
        or missing_slot_type in {
            "ambiguous_shop",
            "ambiguous_shop_name",
            "ambiguous_comparison_targets",
            "unresolved_reference",
            "unresolved_deictic_reference",
            "unresolved_ordinal_reference",
        }
    ):
        lines = ["我找到了几个可能的店，你想查哪一家？"]
        for index, candidate in enumerate(candidates, start=1):
            lines.append(f"{index}. {candidate.get('shop_name', '')}")
        lines.append("请回复编号或店名。")
        return "\n".join(lines)
    if missing_slot_type in _MISSING_SLOT_PROMPTS:
        return _format_missing_slot_prompt(missing_slot_type)
    if not candidates:
        return "请补充更明确的信息。"
    lines = ["我找到了几个可能的店，你想查哪一家？"]
    for index, candidate in enumerate(candidates, start=1):
        lines.append(f"{index}. {candidate.get('shop_name', '')}")
    lines.append("请回复编号或店名。")
    return "\n".join(lines)


def _should_treat_as_topic_switch(
    text: str,
    *,
    pending_missing_slot_type: str = "",
    reply_frame: dict[str, Any] | None = None,
) -> bool:
    compact = (text or "").strip()
    if not compact:
        return False
    reply = _as_dict(reply_frame)
    pending_slot = str(pending_missing_slot_type or "").strip()
    if pending_slot in {
        "missing_location",
        "missing_shop",
        "missing_shop_target",
        "missing_comparison_targets",
        "missing_exploration_location",
        "missing_category",
        "ambiguous_shop",
        "ambiguous_comparison_targets",
        "unresolved_deictic_reference",
        "unresolved_ordinal_reference",
    }:
        if any(
            reply.get(key)
            for key in (
                "location_reference",
                "location",
                "shop_reference",
                "shop_target",
                "ordinal_reference",
                "deictic_reference",
                "comparison_targets",
                "merchant_mentions",
                "preferences",
                "soft_preferences",
                "hard_constraints",
                "ranking_signals",
                "category",
            )
        ):
            return False
        if pending_slot in {"missing_location", "missing_exploration_location"} and any(token in compact for token in ("附近", "周边", "商圈", "北邮", "北京邮电大学")):
            return False
        if pending_slot in {"missing_shop", "missing_shop_target", "ambiguous_shop", "unresolved_deictic_reference", "unresolved_ordinal_reference"} and any(
            token in compact for token in ("这家", "那家", "第一家", "第二家", "第三家", "第一个", "第二个", "第三个")
        ):
            return False
        if pending_slot == "missing_comparison_targets" and any(token in compact for token in ("第一家", "第二家", "第三家", "这家", "这三家", "这几家")):
            return False
    if any(hint in compact for hint in _TOPIC_SWITCH_HINTS):
        return True
    return len(compact) >= 4 and any(token in compact for token in ("附近", "火锅", "营业", "有券", "推荐", "哪家"))


def handle_clarification_reply(
    text: str,
    pending: PendingClarification | dict[str, Any],
    session_state: dict | SessionState | None,
) -> dict[str, Any]:
    """Process a clarification reply and decide whether to restore the task."""
    pending_data = _as_dict(pending)
    candidates = _pending_candidates(pending)
    original_frame = _as_dict(pending_data.get("original_semantic_frame")) or _as_dict(_session_get(session_state, "semantic_frame"))
    reply_frame = _as_dict(extract_slots(text, "local_life"))
    pending_missing_slot_type = _slot_type_text(pending_data.get("missing_slot_type")) or _infer_missing_slot_type(
        original_text=str(pending_data.get("original_text", "") or ""),
        original_semantic_frame=original_frame,
        original_task_type=str(pending_data.get("original_task_type", "") or ""),
        reason=str(pending_data.get("reason", "") or ""),
        candidate_targets=candidates,
    )
    pending_resume_strategy = str(pending_data.get("resume_strategy", "") or "").strip() or _resume_strategy_for_slot(
        pending_missing_slot_type,
        reason=str(pending_data.get("reason", "") or ""),
    )
    task_type_source = _task_type_source_for_strategy(pending_resume_strategy)
    reply_resume_strategy = _resume_strategy_for_slot(
        _slot_type_text(reply_frame.get("missing_slot_type")),
        reason=str(reply_frame.get("follow_up", {}).get("refine_action", "") if isinstance(reply_frame.get("follow_up"), dict) else ""),
    )

    compact = (text or "").strip()
    if compact in {"取消", "算了", "不用了", "不查了", "别查了", "重新来", "先不看了", "放弃", "不选了"}:
        return {
            "status": "cancelled",
            "pending_clarification": None,
            "final_response": "",
            "resume_strategy": "cancel_pending_task",
            "task_type_source": "clarification_resume",
            "missing_slot_type": pending_missing_slot_type,
            "clarification_resolution": {
                "status": "cancelled",
                "resume_strategy": "cancel_pending_task",
                "missing_slot_type": pending_missing_slot_type,
            },
        }
    if any(term in compact for term in ("取消", "算了", "不用了", "不查了", "别查了", "放弃", "不选了")) and _should_treat_as_topic_switch(
        compact,
        pending_missing_slot_type=pending_missing_slot_type,
        reply_frame=reply_frame,
    ):
        return {
            "status": "topic_switch",
            "pending_clarification": None,
            "final_response": "",
            "resume_strategy": "start_new_task",
            "task_type_source": "clarification_resume",
            "missing_slot_type": pending_missing_slot_type,
            "clarification_resolution": {
                "status": "topic_switch",
                "resume_strategy": "start_new_task",
                "missing_slot_type": pending_missing_slot_type,
            },
        }

    if _pending_expired(pending_data):
        return {
            "status": "expired",
            "pending_clarification": None,
            "final_response": "之前的问题已过期，请重新说明店名。",
            "resume_strategy": "ask_clarification_again",
            "task_type_source": "clarification_resume",
            "missing_slot_type": pending_missing_slot_type,
            "clarification_resolution": {
                "status": "expired",
                "resume_strategy": "ask_clarification_again",
                "missing_slot_type": pending_missing_slot_type,
            },
        }

    if reply_frame.get("new_task_override"):
        merged_frame = _merge_semantic_frame(reply_frame, reply_frame)
        return {
            "status": "topic_switch",
            "pending_clarification": None,
            "semantic_frame": merged_frame,
            "task_type": str(reply_frame.get("task_type") or "recommendation"),
            "restored_task": str(reply_frame.get("task_type") or "recommendation"),
            "resolved_target": None,
            "selected_candidate": None,
            "selected_index": None,
            "comparison_targets": [],
            "final_response": "",
            "resume_strategy": "start_new_task",
            "task_type_source": "clarification_resume",
            "missing_slot_type": pending_missing_slot_type,
            "clarification_resolution": {
                "status": "topic_switch",
                "resume_strategy": "start_new_task",
                "task_type_source": "clarification_resume",
                "missing_slot_type": pending_missing_slot_type,
            },
        }

    if reply_frame.get("constraint_update"):
        merged_frame = _merge_semantic_frame(original_frame, reply_frame)
        return {
            "status": "restore",
            "pending_clarification": None,
            "semantic_frame": merged_frame,
            "task_type": str(pending_data.get("original_task_type") or pending_data.get("task_type") or merged_frame.get("task_type") or "recommendation"),
            "restored_task": str(pending_data.get("original_task_type") or pending_data.get("task_type") or merged_frame.get("task_type") or "recommendation"),
            "resolved_target": None,
            "selected_candidate": None,
            "selected_index": None,
            "comparison_targets": [],
            "final_response": "",
            "resume_strategy": "apply_constraint_update",
            "task_type_source": "clarification_resume",
            "missing_slot_type": pending_missing_slot_type,
            "clarification_resolution": {
                "status": "restore",
                "resume_strategy": "apply_constraint_update",
                "task_type_source": "clarification_resume",
                "missing_slot_type": pending_missing_slot_type,
            },
        }

    selection = _parse_selection(compact)
    selected_candidate = None
    comparison_slot = pending_missing_slot_type in {"missing_comparison_targets", "ambiguous_comparison_targets"}
    if comparison_slot and not candidates:
        session_candidates = _session_get(session_state, "last_recommendation_list") or []
        candidates = [
            _canonicalize_candidate(candidate)
            for candidate in session_candidates
            if _canonicalize_candidate(candidate).get("shop_id") and _canonicalize_candidate(candidate).get("shop_name")
        ]
    if comparison_slot:
        comparison_frame = reply_frame or original_frame
        if not _slot_type_text(_as_dict(comparison_frame).get("task_type")):
            comparison_frame = _merge_semantic_frame(original_frame, reply_frame)
        comparison_resolution = resolve_comparison_targets(compact, session_state, comparison_frame)
        comparison_status = str(comparison_resolution.get("status", "") or "").upper()
        comparison_targets = [dict(item) for item in (comparison_resolution.get("targets") or []) if _as_dict(item)]
        if comparison_status == "RESOLVED" and len(comparison_targets) >= 2:
            merged_frame = _merge_semantic_frame(original_frame, reply_frame, comparison_targets=comparison_targets)
            return {
                "status": "restore",
                "pending_clarification": None,
                "semantic_frame": merged_frame,
                "task_type": str(pending_data.get("original_task_type") or pending_data.get("task_type") or merged_frame.get("task_type") or "comparison"),
                "restored_task": str(pending_data.get("original_task_type") or pending_data.get("task_type") or merged_frame.get("task_type") or "comparison"),
                "resolved_target": None,
                "selected_candidate": None,
                "selected_index": None,
                "comparison_targets": comparison_targets,
                "comparison_target_resolution": comparison_resolution,
                "final_response": "",
                "resume_strategy": "fill_missing_comparison_targets",
                "task_type_source": "clarification_resume",
                "missing_slot_type": pending_missing_slot_type,
                "clarification_resolution": {
                    "status": "restore",
                    "resume_strategy": "fill_missing_comparison_targets",
                    "task_type_source": "clarification_resume",
                    "missing_slot_type": pending_missing_slot_type,
                    "comparison_target_resolution": comparison_resolution,
                },
            }
    if selection is not None:
        if not candidates:
            return {
                "status": "invalid",
                "pending_clarification": pending_data,
                "final_response": "请补充更明确的信息。",
                "resume_strategy": "ask_clarification_again",
                "task_type_source": "clarification_resume",
                "missing_slot_type": pending_missing_slot_type,
                "clarification_resolution": {
                    "status": "invalid",
                    "resume_strategy": "ask_clarification_again",
                    "task_type_source": "clarification_resume",
                    "missing_slot_type": pending_missing_slot_type,
                },
            }
        if 1 <= selection <= len(candidates):
            selected_candidate = candidates[selection - 1]
        else:
            return {
                "status": "out_of_range",
                "pending_clarification": pending_data,
                "final_response": f"没有第 {selection} 个选项，请回复 1-{len(candidates)}。",
                "selection_index": selection,
            }
    elif not comparison_slot:
        matched_index, matched_candidate = _match_candidate_text(compact, candidates)
        if matched_candidate is not None:
            selected_candidate = matched_candidate
            selection = matched_index

    direct_shop_resolution: dict[str, Any] = {}
    comparison_targets: list[dict[str, Any]] = []
    if selected_candidate is None and pending_missing_slot_type in {"missing_shop", "missing_shop_target", "ambiguous_shop", "unresolved_reference", "unresolved_deictic_reference", "unresolved_ordinal_reference"}:
        current_shop = _as_dict(_session_get(session_state, "current_shop"))
        if current_shop.get("shop_id") and current_shop.get("shop_name") and any(token in compact for token in ("这家", "那家", "这间", "那间")):
            selected_candidate = {
                "shop_id": str(current_shop.get("shop_id", "") or ""),
                "shop_name": str(current_shop.get("shop_name", "") or ""),
            }
        elif reply_frame.get("ordinal_references") or any(token in compact for token in ("第一家", "第二家", "第三家", "第一个", "第二个", "第三个")):
            try:
                reference_resolution = _to_dict(resolve_references(compact, session_state, reply_frame or original_frame))
            except Exception:
                reference_resolution = {}
            reference_status = str(reference_resolution.get("status", "") or "").lower()
            if reference_status == "resolved":
                target = _as_dict(reference_resolution.get("target") or reference_resolution.get("resolved_shop") or {})
                if target.get("shop_id") and target.get("shop_name"):
                    selected_candidate = {"shop_id": str(target.get("shop_id", "") or ""), "shop_name": str(target.get("shop_name", "") or "")}
        try:
            direct_shop_resolution = _to_dict(resolve_shop_entity(
                compact,
                session_state=session_state,
                semantic_frame=reply_frame or original_frame,
            ))
        except Exception:
            direct_shop_resolution = {}
        if str(direct_shop_resolution.get("status", "") or "").upper() == "RESOLVED":
            resolved_shop = direct_shop_resolution.get("resolved_shop") or direct_shop_resolution.get("shop") or {}
            selected_candidate = {
                "shop_id": str(_as_dict(resolved_shop).get("shop_id", "") or ""),
                "shop_name": str(_as_dict(resolved_shop).get("shop_name", "") or ""),
            }
    reference_resolution: dict[str, Any] = {}
    if selected_candidate is None and pending_missing_slot_type in {"missing_shop", "missing_shop_target", "ambiguous_shop", "unresolved_reference", "unresolved_deictic_reference", "unresolved_ordinal_reference"}:
        try:
            reference_resolution = _to_dict(resolve_references(compact, session_state, reply_frame or original_frame))
        except Exception:
            reference_resolution = {}
        reference_status = str(reference_resolution.get("status", "") or "").lower()
        if reference_status == "resolved":
            target = _as_dict(reference_resolution.get("target") or reference_resolution.get("resolved_shop") or {})
            if target.get("shop_id") and target.get("shop_name"):
                selected_candidate = {"shop_id": str(target.get("shop_id", "") or ""), "shop_name": str(target.get("shop_name", "") or "")}

    if selected_candidate is not None:
        restored_task_type = str(
            pending_data.get("original_task_type")
            or pending_data.get("task_type")
            or "coupon_query"
        )
        if comparison_slot:
            restored_task_type = "comparison"
        original_frame_dict = _as_dict(pending_data.get("original_semantic_frame"))
        facet_names = {
            str(_as_dict(item).get("name", "") or "").strip()
            for item in (original_frame_dict.get("facets") or [])
            if str(_as_dict(item).get("name", "") or "").strip()
        }
        focused_facets = {
            str(item).strip()
            for item in (original_frame_dict.get("focused_facets") or [])
            if str(item).strip()
        }
        if restored_task_type == "recommendation" and ("coupon" in facet_names or "coupon" in focused_facets):
            restored_task_type = "coupon_query"
        resolved_target = ResolveShopResult(
            status="RESOLVED",
            resolved_shop=ShopRef(
                shop_id=str(selected_candidate.get("shop_id", "")),
                shop_name=str(selected_candidate.get("shop_name", "")),
            ),
            confidence=1.0,
            reason="clarification_reply",
        )
        original_frame = pending_data.get("original_semantic_frame")
        if original_frame is None:
            original_frame = _session_get(session_state, "semantic_frame")
            original_frame = _as_dict(original_frame)
        if not original_frame:
            original_frame = {
                "top_intent": "local_life",
                "task_type": restored_task_type,
                "primary_task": "single_shop_query" if restored_task_type == "coupon_query" else restored_task_type,
                "facets": [{"name": "coupon", "required": True}] if restored_task_type == "coupon_query" else [],
                "merchant_mentions": [str(selected_candidate.get("shop_name", ""))] if selected_candidate.get("shop_name") else [],
                "brand_mentions": [],
                "branch_mentions": [],
                "reference_mentions": [],
                "comparison_targets": [],
                "ordinal_references": [],
                "deictic_references": [],
                "focused_facets": ["coupon"] if restored_task_type == "coupon_query" else [],
                "comparison_focus": "",
                "hard_constraints": {},
                "soft_preferences": {},
                "ranking_signals": {},
                "follow_up": None,
                "confidence": 0.0,
                "need_context": False,
            }
        restored_targets = [
            _as_dict(item) for item in (pending_data.get("already_resolved_targets", []) or []) if _as_dict(item)
        ]
        if comparison_slot:
            original_comparison_targets = [
                _as_dict(item)
                for item in (original_frame_dict.get("comparison_targets") or [])
                if str(_as_dict(item).get("shop_id", "") or "").strip() or str(_as_dict(item).get("shop_name", "") or "").strip()
            ]
            merged_targets: list[dict[str, Any]] = []
            seen_target_keys: set[tuple[str, str]] = set()
            for item in original_comparison_targets + restored_targets + [dict(selected_candidate)]:
                key = (str(_as_dict(item).get("shop_id", "") or "").strip(), str(_as_dict(item).get("shop_name", "") or "").strip())
                if not key[0] and not key[1]:
                    continue
                if key in seen_target_keys:
                    continue
                seen_target_keys.add(key)
                merged_targets.append(_as_dict(item))
            restored_targets = merged_targets
        elif dict(selected_candidate) not in restored_targets:
            restored_targets.append(dict(selected_candidate))
        comparison_targets_for_frame = restored_targets if comparison_slot else None
        comparison_target_resolution_for_return: dict[str, Any] | None = None
        if comparison_slot:
            comparison_target_resolution_for_return = {
                "status": "RESOLVED" if len(restored_targets) >= 2 else "NEED_CLARIFICATION",
                "targets": [
                    _as_dict(item)
                    for item in restored_targets
                    if _as_dict(item).get("shop_id") or _as_dict(item).get("shop_name")
                ],
                "unresolved_targets": [],
                "reason": "comparison_targets_resolved" if len(restored_targets) >= 2 else "comparison_targets_need_clarification",
            }
        merged_frame = _merge_semantic_frame(
            original_frame,
            reply_frame,
            selected_candidate=selected_candidate,
            resolved_target={"shop_id": str(selected_candidate.get("shop_id", "")), "shop_name": str(selected_candidate.get("shop_name", ""))},
            comparison_targets=comparison_targets_for_frame,
        )
        if pending_missing_slot_type in {"missing_location", "missing_exploration_location"} and reply_frame.get("location_reference"):
            merged_frame["location_reference"] = reply_frame.get("location_reference")
            merged_frame["location"] = dict(reply_frame.get("location") or {})
        if pending_missing_slot_type in {"missing_category"} and reply_frame.get("category"):
            merged_frame["category"] = str(reply_frame.get("category", "") or "")
        if reply_frame.get("constraint_update"):
            merged_frame["constraint_update"] = True
        if reply_frame.get("new_task_override"):
            merged_frame["new_task_override"] = True
        return {
            "status": "restore",
            "pending_clarification": None,
            "semantic_frame": merged_frame,
            "task_type": restored_task_type,
            "restored_task": restored_task_type,
            "resolved_target": resolved_target,
            "selected_candidate": dict(selected_candidate),
            "selected_index": selection,
            "comparison_targets": restored_targets,
            "comparison_target_resolution": comparison_target_resolution_for_return,
            "final_response": "",
            "resume_strategy": pending_resume_strategy or reply_resume_strategy,
            "task_type_source": task_type_source,
            "missing_slot_type": pending_missing_slot_type,
            "clarification_resolution": {
                "status": "restore",
                "resume_strategy": pending_resume_strategy or reply_resume_strategy,
                "task_type_source": task_type_source,
                "missing_slot_type": pending_missing_slot_type,
                "selected_index": selection,
                "selected_candidate": dict(selected_candidate),
                "comparison_target_resolution": comparison_target_resolution_for_return,
            },
        }

    if pending_missing_slot_type == "missing_location" and (reply_frame.get("location_reference") or reply_frame.get("location")):
        merged_frame = _merge_semantic_frame(original_frame, reply_frame)
        return {
            "status": "restore",
            "pending_clarification": None,
            "semantic_frame": merged_frame,
            "task_type": str(pending_data.get("original_task_type") or pending_data.get("task_type") or merged_frame.get("task_type") or "recommendation"),
            "restored_task": str(pending_data.get("original_task_type") or pending_data.get("task_type") or merged_frame.get("task_type") or "recommendation"),
            "resolved_target": None,
            "selected_candidate": None,
            "selected_index": None,
            "comparison_targets": [],
            "final_response": "",
            "resume_strategy": "fill_missing_location",
            "task_type_source": "clarification_resume",
            "missing_slot_type": pending_missing_slot_type,
            "clarification_resolution": {
                "status": "restore",
                "resume_strategy": "fill_missing_location",
                "task_type_source": "clarification_resume",
                "missing_slot_type": pending_missing_slot_type,
            },
        }

    if pending_missing_slot_type == "missing_exploration_location" and (reply_frame.get("location_reference") or reply_frame.get("location")):
        merged_frame = _merge_semantic_frame(original_frame, reply_frame)
        return {
            "status": "restore",
            "pending_clarification": None,
            "semantic_frame": merged_frame,
            "task_type": str(pending_data.get("original_task_type") or pending_data.get("task_type") or merged_frame.get("task_type") or "local_trip_plan"),
            "restored_task": str(pending_data.get("original_task_type") or pending_data.get("task_type") or merged_frame.get("task_type") or "local_trip_plan"),
            "resolved_target": None,
            "selected_candidate": None,
            "selected_index": None,
            "comparison_targets": [],
            "final_response": "",
            "resume_strategy": "fill_missing_exploration_location",
            "task_type_source": "clarification_resume",
            "missing_slot_type": pending_missing_slot_type,
            "clarification_resolution": {
                "status": "restore",
                "resume_strategy": "fill_missing_exploration_location",
                "task_type_source": "clarification_resume",
                "missing_slot_type": pending_missing_slot_type,
            },
        }

    if pending_missing_slot_type == "missing_comparison_targets":
        comparison_frame = reply_frame or original_frame
        if not _slot_type_text(_as_dict(comparison_frame).get("task_type")):
            comparison_frame = _merge_semantic_frame(original_frame, reply_frame)
        comparison_resolution = resolve_comparison_targets(compact, session_state, comparison_frame)
        comparison_status = str(comparison_resolution.get("status", "") or "").upper()
        comparison_targets = [dict(item) for item in (comparison_resolution.get("targets") or []) if _as_dict(item)]
        return {
            "status": "invalid",
            "pending_clarification": pending_data,
            "final_response": "请说明要比较哪几家店。",
            "resume_strategy": "ask_clarification_again",
            "task_type_source": "clarification_resume",
            "missing_slot_type": pending_missing_slot_type,
            "clarification_resolution": {
                "status": "need_clarification",
                "resume_strategy": "ask_clarification_again",
                "task_type_source": "clarification_resume",
                "missing_slot_type": pending_missing_slot_type,
                "comparison_target_resolution": comparison_resolution,
            },
        }

    if reply_frame.get("cancel_intent"):
        return {
            "status": "cancelled",
            "pending_clarification": None,
            "final_response": "",
            "resume_strategy": "cancel_pending_task",
            "task_type_source": "clarification_resume",
            "missing_slot_type": pending_missing_slot_type,
            "clarification_resolution": {
                "status": "cancelled",
                "resume_strategy": "cancel_pending_task",
                "task_type_source": "clarification_resume",
                "missing_slot_type": pending_missing_slot_type,
            },
        }

    if selection is not None and not comparison_slot:
        return {
            "status": "out_of_range",
            "pending_clarification": pending_data,
            "final_response": f"没有第 {selection} 个选项，请回复 1-{len(candidates)}。",
            "selection_index": selection,
            "resume_strategy": "ask_clarification_again",
            "task_type_source": "clarification_resume",
            "missing_slot_type": pending_missing_slot_type,
            "clarification_resolution": {
                "status": "out_of_range",
                "resume_strategy": "ask_clarification_again",
                "task_type_source": "clarification_resume",
                "missing_slot_type": pending_missing_slot_type,
                "selection_index": selection,
            },
        }

    if _should_treat_as_topic_switch(
        compact,
        pending_missing_slot_type=pending_missing_slot_type,
        reply_frame=reply_frame,
    ):
        return {
            "status": "topic_switch",
            "pending_clarification": None,
            "final_response": "",
            "resume_strategy": "start_new_task",
            "task_type_source": "clarification_resume",
            "missing_slot_type": pending_missing_slot_type,
            "clarification_resolution": {
                "status": "topic_switch",
                "resume_strategy": "start_new_task",
                "task_type_source": "clarification_resume",
                "missing_slot_type": pending_missing_slot_type,
            },
        }

    return {
        "status": "invalid",
        "pending_clarification": pending_data,
        "final_response": "请回复编号或店名。",
        "resume_strategy": "ask_clarification_again",
        "task_type_source": "clarification_resume",
        "missing_slot_type": pending_missing_slot_type,
        "clarification_resolution": {
            "status": "invalid",
            "resume_strategy": "ask_clarification_again",
            "task_type_source": "clarification_resume",
            "missing_slot_type": pending_missing_slot_type,
        },
    }
