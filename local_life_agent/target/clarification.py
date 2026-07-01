"""Clarification handling for pending multi-turn questions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from .. import config
from ..domain.schemas import PendingClarification, ResolveShopResult, ShopRef
from ..domain.state import SessionState


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


def _pending_candidates(pending: PendingClarification | dict[str, Any] | None) -> list[dict[str, Any]]:
    if pending is None:
        return []
    data = _as_dict(pending)
    candidates: list[dict[str, Any]] = []
    for item in data.get("candidate_targets", []) or []:
        candidate = _as_dict(item)
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
    already_resolved_targets: list[dict[str, Any]] | None = None,
    ambiguous_target_slot: str = "",
) -> PendingClarification:
    """Construct a pending clarification payload with TTL metadata."""
    now = datetime.now(timezone.utc)
    frame = _as_dict(original_semantic_frame)
    task_type_value = original_task_type.value if hasattr(original_task_type, "value") else str(original_task_type or "")
    prepared_candidates = []
    for candidate in candidate_targets:
        item = _as_dict(candidate)
        if item.get("shop_id") and item.get("shop_name"):
            prepared_candidates.append(
                {
                    "shop_id": str(item.get("shop_id", "")),
                    "shop_name": str(item.get("shop_name", "")),
                    "address": str(item.get("address", "")),
                }
            )
    return PendingClarification(
        pending_id=f"pc_{uuid4().hex[:12]}",
        original_task_type=task_type_value,
        candidate_targets=prepared_candidates,
        expected_reply_type=expected_reply_type,
        created_at=now,
        expires_at=now + timedelta(seconds=config.CLARIFICATION_TTL_SECONDS),
        original_text=original_text,
        original_semantic_frame=frame or None,
        already_resolved_targets=[_as_dict(item) for item in (already_resolved_targets or []) if _as_dict(item)],
        ambiguous_target_slot=ambiguous_target_slot,
        reason=reason,
        source_node=source_node,
    )


def format_pending_prompt(pending: PendingClarification | dict[str, Any]) -> str:
    """Format the clarification prompt shown to the user."""
    candidates = _pending_candidates(pending)
    reason = str(_as_dict(pending).get("reason", "") or "")
    if reason == "comparison_requires_at_least_two_shops":
        return "对比至少需要两家不同的店，请补充另一家店名。"
    if reason == "comparison_too_many_shops":
        return "最多支持 5 家店对比，请缩小范围后再试。"
    if not candidates:
        return "店名有点模糊，请提供完整店名。"

    lines = ["我找到了几个可能的店，你想查哪一家？"]
    for index, candidate in enumerate(candidates, start=1):
        lines.append(f"{index}. {candidate.get('shop_name', '')}")
    lines.append("请回复编号或店名。")
    return "\n".join(lines)


def _should_treat_as_topic_switch(text: str) -> bool:
    compact = (text or "").strip()
    if not compact:
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

    compact = (text or "").strip()
    if compact in {"取消", "算了", "不用了", "不查了", "别查了", "重新来", "先不看了", "放弃", "不选了"}:
        return {
            "status": "cancelled",
            "pending_clarification": None,
            "final_response": "",
        }
    if any(term in compact for term in ("取消", "算了", "不用了", "不查了", "别查了", "放弃", "不选了")) and _should_treat_as_topic_switch(compact):
        return {
            "status": "topic_switch",
            "pending_clarification": None,
            "final_response": "",
        }

    if _pending_expired(pending_data):
        return {
            "status": "expired",
            "pending_clarification": None,
            "final_response": "之前的问题已过期，请重新说明店名。",
        }

    selection = _parse_selection(compact)
    selected_candidate = None
    if selection is not None:
        if 1 <= selection <= len(candidates):
            selected_candidate = candidates[selection - 1]
        else:
            return {
                "status": "out_of_range",
                "pending_clarification": pending_data,
                "final_response": f"没有第 {selection} 个选项，请回复 1-{len(candidates)}。",
                "selection_index": selection,
            }
    else:
        matched_index, matched_candidate = _match_candidate_text(compact, candidates)
        if matched_candidate is not None:
            selected_candidate = matched_candidate
            selection = matched_index

    if selected_candidate is not None:
        restored_task_type = str(
            pending_data.get("original_task_type")
            or pending_data.get("task_type")
            or "coupon_query"
        )
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
        restored_targets.append(dict(selected_candidate))
        return {
            "status": "restore",
            "pending_clarification": None,
            "semantic_frame": original_frame,
            "task_type": restored_task_type,
            "restored_task": restored_task_type,
            "resolved_target": resolved_target,
            "selected_candidate": dict(selected_candidate),
            "selected_index": selection,
            "comparison_targets": restored_targets,
            "final_response": "",
        }

    if selection is not None:
        return {
            "status": "out_of_range",
            "pending_clarification": pending_data,
            "final_response": f"没有第 {selection} 个选项，请回复 1-{len(candidates)}。",
            "selection_index": selection,
        }

    if _should_treat_as_topic_switch(compact):
        return {
            "status": "topic_switch",
            "pending_clarification": None,
            "final_response": "",
        }

    return {
        "status": "invalid",
        "pending_clarification": pending_data,
        "final_response": "请回复编号或店名。",
    }
