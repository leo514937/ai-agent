"""Independent workflow for multi-subgoal exploration planning.

Phase 8 keeps this workflow intentionally small:
- recognize 2-3 exploration subgoals and simple temporal order
- run at most two tool rounds with existing tools only
- build ExplorationPlan / EvidencePack / AnswerPlan
- verify the generated answer before returning
- fall back to the existing clarification / fallback workflow when the
  request is underspecified, over-constrained, or tool execution fails
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from ...answer.verifier import verify_answer
from ...domain.graph_state import GraphState
from ...domain.schemas import AnswerPlan, EvidencePack, ExplorationPlan, ExplorationSubgoal, ExecutionPlan, OrchestrationDecision, ToolResult
from ...engine._compat import _log, _to_dict
from ...observability.file_logger import get_python_service_logger, log_kv
from ...planning.evidence.evidence_builder import build_evidence
from ...tools.gateway import dispatch_tool_call as _default_dispatch_tool_call
from .clarification_fallback_workflow import run_clarification_fallback_workflow

_LOGGER = get_python_service_logger()
dispatch_tool_call = _default_dispatch_tool_call

_SEQ_MARKERS = ("然后", "再", "之后", "接着", "最后", "接下来")
_SEQ_SPLIT_RE = re.compile(r"(?:然后|再|之后|接着|最后|接下来|并且|同时|以及|；|;|，|,|。|、)+")

_TASK_TEMPLATES: dict[str, list[dict[str, str]]] = {
    "coffee_then_dinner": [
        {"kind": "coffee", "query": "咖啡店", "temporal_relation": "before"},
        {"kind": "dinner", "query": "餐厅", "temporal_relation": "after"},
    ],
    "date_plan": [
        {"kind": "coffee_or_dessert", "query": "咖啡店 甜品店 约会", "temporal_relation": "before"},
        {"kind": "dinner", "query": "约会餐厅 晚餐", "temporal_relation": "middle"},
        {"kind": "activity", "query": "公园 散步 约会", "temporal_relation": "after"},
    ],
    "family_activity_plan": [
        {"kind": "meal", "query": "亲子餐厅", "temporal_relation": "before"},
        {"kind": "activity", "query": "儿童乐园 游乐场", "temporal_relation": "middle"},
        {"kind": "rest", "query": "公园 甜品店", "temporal_relation": "after"},
    ],
    "local_trip_plan": [
        {"kind": "sightseeing", "query": "景点", "temporal_relation": "before"},
        {"kind": "meal", "query": "餐厅", "temporal_relation": "middle"},
        {"kind": "rest", "query": "咖啡店", "temporal_relation": "after"},
    ],
    "eat_and_play_plan": [
        {"kind": "meal", "query": "餐厅", "temporal_relation": "before"},
        {"kind": "activity", "query": "游玩 地点", "temporal_relation": "middle"},
        {"kind": "dessert", "query": "咖啡店 甜品", "temporal_relation": "after"},
    ],
}

_FALLBACK_REASONS = {
    "missing_location": "exploration_missing_location",
    "too_many_subgoals": "exploration_too_many_subgoals",
    "tool_failure": "exploration_tool_failure",
    "no_result": "exploration_no_result",
    "unsupported": "exploration_unsupported",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _session_value(state: dict[str, Any], field: str) -> Any:
    session_state = state.get("session_state")
    if isinstance(session_state, dict):
        return session_state.get(field)
    session_state_before = state.get("session_state_before")
    if isinstance(session_state_before, dict):
        return session_state_before.get(field)
    return state.get(field)


def _extract_user_location(state: dict[str, Any]) -> dict[str, Any]:
    candidates = [
        state.get("user_context"),
        state.get("turn_input"),
        _session_value(state, "user_context"),
    ]
    for item in candidates:
        item_dict = _to_dict(item)
        lat = item_dict.get("lat")
        lng = item_dict.get("lng")
        if lat is None or lng is None:
            continue
        try:
            return {
                "lat": float(lat),
                "lng": float(lng),
                "label": str(item_dict.get("location_name", item_dict.get("label", "")) or ""),
            }
        except Exception:
            continue
    return {}


def _normalize_task_type(state: dict[str, Any], decision: OrchestrationDecision) -> str:
    semantic_frame = _to_dict(state.get("semantic_frame"))
    task_type = str(state.get("task_type") or semantic_frame.get("task_type") or decision.workflow_name or "").strip()
    if task_type:
        return task_type
    primary_task = str(semantic_frame.get("primary_task", "") or "").strip()
    return primary_task


def _split_sequence_text(raw_text: str) -> list[str]:
    parts = [segment.strip() for segment in _SEQ_SPLIT_RE.split(raw_text) if segment and segment.strip()]
    return parts


def _extract_text_hints(state: dict[str, Any]) -> dict[str, Any]:
    semantic_frame = _to_dict(state.get("semantic_frame"))
    raw_text = str(state.get("raw_text", "") or state.get("normalized_text", "") or "")
    hard_constraints = _to_dict(semantic_frame.get("hard_constraints"))
    soft_preferences = _to_dict(semantic_frame.get("soft_preferences"))
    ranking_signals = _to_dict(semantic_frame.get("ranking_signals"))
    need_context = bool(semantic_frame.get("need_context", False))
    facets = semantic_frame.get("facets") or []
    facet_names: list[str] = []
    for item in facets:
        item_dict = _to_dict(item)
        name = str(item_dict.get("name", item_dict.get("facet", "")) or "").strip()
        if name:
            facet_names.append(name)
    return {
        "raw_text": raw_text,
        "hard_constraints": hard_constraints,
        "soft_preferences": soft_preferences,
        "ranking_signals": ranking_signals,
        "need_context": need_context,
        "facet_names": facet_names,
    }


def _template_subgoals(task_type: str, hints: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    template = _TASK_TEMPLATES.get(task_type, [])
    if not template:
        return [], False
    hard_constraints = hints.get("hard_constraints") or {}
    soft_preferences = hints.get("soft_preferences") or {}
    ranking_signals = hints.get("ranking_signals") or {}
    context_terms: list[str] = []
    for source in (hard_constraints, soft_preferences, ranking_signals):
        for key, value in _to_dict(source).items():
            if isinstance(value, (str, int, float)) and str(value).strip():
                context_terms.append(str(value).strip())
            elif isinstance(value, list):
                context_terms.extend([str(item).strip() for item in value if str(item).strip()])
            elif isinstance(value, dict):
                context_terms.extend([str(item).strip() for item in value.values() if str(item).strip()])
            elif str(key).strip():
                context_terms.append(str(key).strip())
    enriched: list[dict[str, Any]] = []
    for idx, item in enumerate(template, start=1):
        query = str(item.get("query", "") or "").strip()
        if context_terms:
            query = f"{query} {' '.join(context_terms[:2])}".strip()
        enriched.append(
            {
                "subgoal_id": f"subgoal_{idx}",
                "kind": str(item.get("kind", "") or f"step_{idx}"),
                "query": query,
                "sequence_order": idx,
                "temporal_relation": str(item.get("temporal_relation", "") or ""),
                "require_location": True,
                "max_candidates": 3,
                "tool_rounds": [],
                "selected_candidate": None,
                "candidate_shops": [],
                "note": f"template:{task_type}",
            }
        )
    return enriched, True


def _build_subgoals(state: dict[str, Any], decision: OrchestrationDecision) -> tuple[list[dict[str, Any]], bool, str | None]:
    task_type = _normalize_task_type(state, decision)
    hints = _extract_text_hints(state)
    raw_text = hints["raw_text"]
    template_subgoals, has_temporal_sequence = _template_subgoals(task_type, hints)
    if template_subgoals:
        return template_subgoals, has_temporal_sequence, None

    sequence_parts = _split_sequence_text(raw_text)
    if len(sequence_parts) > 3:
        return [], True, _FALLBACK_REASONS["too_many_subgoals"]
    if len(sequence_parts) >= 2:
        subgoals: list[dict[str, Any]] = []
        for idx, part in enumerate(sequence_parts[:3], start=1):
            subgoals.append(
                {
                    "subgoal_id": f"subgoal_{idx}",
                    "kind": f"step_{idx}",
                    "query": part,
                    "sequence_order": idx,
                    "temporal_relation": "ordered" if idx > 1 else "first",
                    "require_location": True,
                    "max_candidates": 3,
                    "tool_rounds": [],
                    "selected_candidate": None,
                    "candidate_shops": [],
                    "note": "sequence_from_text",
                }
            )
        return subgoals, True, None

    facet_names = hints.get("facet_names") or []
    if facet_names:
        subgoals = []
        for idx, facet in enumerate(facet_names[:3], start=1):
            subgoals.append(
                {
                    "subgoal_id": f"subgoal_{idx}",
                    "kind": facet,
                    "query": facet,
                    "sequence_order": idx,
                    "temporal_relation": "parallel",
                    "require_location": True,
                    "max_candidates": 3,
                    "tool_rounds": [],
                    "selected_candidate": None,
                    "candidate_shops": [],
                    "note": "facet-derived",
                }
            )
        return subgoals, len(subgoals) > 1, None

    if task_type:
        subgoal = {
            "subgoal_id": "subgoal_1",
            "kind": task_type,
            "query": task_type,
            "sequence_order": 1,
            "temporal_relation": "single",
            "require_location": True,
            "max_candidates": 3,
            "tool_rounds": [],
            "selected_candidate": None,
            "candidate_shops": [],
            "note": "task_type_fallback",
        }
        return [subgoal], False, None

    return [], False, _FALLBACK_REASONS["too_many_subgoals"]


def _search_query_for_subgoal(subgoal: dict[str, Any]) -> str:
    query = str(subgoal.get("query", "") or "").strip()
    if query:
        return query
    kind = str(subgoal.get("kind", "") or "").strip()
    return kind or "附近商家"


def _build_exploration_plan(
    *,
    state: dict[str, Any],
    decision: OrchestrationDecision,
    subgoals: list[dict[str, Any]],
    location: dict[str, Any],
    tool_names_used: list[str],
    tool_rounds_used: int,
    fallback_reason: str = "",
) -> ExplorationPlan:
    task_type = _normalize_task_type(state, decision)
    expected_output = "按顺序给出最多三个子目标的探索安排，并标明每一步查到的商家选择。"
    if len(subgoals) == 2:
        expected_output = "按顺序给出两个子目标的探索安排，并标明每一步查到的商家选择。"
    sanitized_subgoals = [{key: value for key, value in subgoal.items() if key != "location"} for subgoal in subgoals]
    plan = ExplorationPlan.model_validate(
        {
            "plan_id": f"exploration_{task_type or 'unknown'}",
            "task_type": task_type,
            "goal_type": str(decision.orchestration_pattern or "exploration_planning"),
            "has_temporal_sequence": len(subgoals) > 1,
            "expected_output": expected_output,
            "subgoal_limit": 3,
            "expansion_round_limit": 2,
            "subgoals": sanitized_subgoals,
            "tool_rounds_used": tool_rounds_used,
            "location_required": True,
            "location_available": bool(location),
            "tool_names_used": list(dict.fromkeys(tool_names_used)),
            "notes": ["phase_8_exploration_planning"],
            "fallback_reason": fallback_reason,
        }
    )
    return plan


def _normalize_shop_item(item: Any) -> dict[str, Any]:
    item_dict = _to_dict(item)
    return {
        "shop_id": str(item_dict.get("shop_id", "") or "").strip(),
        "shop_name": str(item_dict.get("shop_name", item_dict.get("name", "")) or "").strip(),
        "address": str(item_dict.get("address", "") or "").strip(),
        "rating": item_dict.get("rating"),
        "avg_price": item_dict.get("avg_price"),
        "distance_km": item_dict.get("distance_km"),
        "eta_minutes": item_dict.get("eta_minutes"),
        "open_status": item_dict.get("open_status"),
        "coupon_count": item_dict.get("coupon_count"),
    }


def _tool_round_search(
    *,
    subgoals: list[dict[str, Any]],
    location: dict[str, Any],
    dispatch_tool_call,
) -> tuple[dict[str, list[dict[str, Any]]], list[str], bool]:
    results: dict[str, list[dict[str, Any]]] = {}
    tool_names_used: list[str] = ["search_shops"]
    any_failure = False
    for subgoal in subgoals:
        query = _search_query_for_subgoal(subgoal)
        raw = dispatch_tool_call("search_shops", {"query": query, "location": location, "limit": 3})
        raw_dict = _to_dict(raw)
        if raw_dict.get("success") is False or str(raw_dict.get("result_status", "") or "").lower() in {"failed", "error", "unknown"} and not raw_dict.get("data"):
            any_failure = True
        items = raw_dict.get("data")
        if isinstance(items, dict):
            items = items.get("items", [])
        if not isinstance(items, list):
            items = []
        normalized = [_normalize_shop_item(item) for item in items if str(_to_dict(item).get("shop_id", "") or "").strip()]
        results[str(subgoal.get("subgoal_id", ""))] = normalized
        subgoal["tool_rounds"].append({"round": 1, "tool_name": "search_shops", "query": query, "result_count": len(normalized)})
        subgoal["candidate_shops"] = normalized
        if not normalized:
            any_failure = True
    return results, tool_names_used, any_failure


def _tool_round_expand(
    *,
    subgoals: list[dict[str, Any]],
    dispatch_tool_call,
) -> tuple[dict[str, ToolResult], list[str], bool]:
    tool_results: dict[str, ToolResult] = {}
    tool_names_used: list[str] = []
    failure = False
    call_index = 0
    for subgoal in subgoals:
        candidates = list(subgoal.get("candidate_shops") or [])
        if not candidates:
            failure = True
            continue
        chosen = candidates[0]
        shop_id = str(chosen.get("shop_id", "") or "").strip()
        if not shop_id:
            failure = True
            continue
        subgoal["selected_candidate"] = chosen
        selected_tools: list[tuple[str, dict[str, Any]]] = [
            ("get_shop_detail", {"shop_id": shop_id}),
            ("check_open_status", {"shop_id": shop_id}),
            ("get_distance_eta", {"shop_id": shop_id, "from_location": subgoal.get("location", {})}),
        ]
        if any(token in str(subgoal.get("query", "") or "") for token in ("评价", "口碑", "评论", "review")):
            selected_tools.append(("get_shop_review_summary", {"shop_ids": [shop_id]}))
        for tool_name, kwargs in selected_tools:
            call_index += 1
            tool_names_used.append(tool_name)
            call_id = f"{subgoal['subgoal_id']}_{call_index}"
            payload = dispatch_tool_call(tool_name, {**kwargs, "call_id": call_id})
            result = _to_dict(payload)
            try:
                tool_results[call_id] = ToolResult.model_validate(
                    {
                        "call_id": call_id,
                        "shop_id": shop_id,
                        "tool_name": tool_name,
                        "success": bool(result.get("success", False)),
                        "result_status": result.get("result_status", "unknown"),
                        "data": result.get("data"),
                        "error_code": result.get("error_code") or None,
                        "error_message": str(result.get("error_message", "") or ""),
                        "source": str(result.get("source", "") or result.get("backend_source", "") or ""),
                        "degraded": bool(result.get("degraded", False)),
                        "retriable": not bool(result.get("success", False)),
                        "backend_source": str(result.get("backend_source", "") or result.get("source", "") or ""),
                        "http_status": result.get("http_status"),
                        "endpoint": result.get("endpoint"),
                        "fallback_from": result.get("fallback_from"),
                    }
                )
            except Exception:
                failure = True
                continue
            if not bool(result.get("success", False)) and str(result.get("result_status", "") or "").lower() in {"failed", "error", "unsupported", "unknown"}:
                failure = True
        subgoal["tool_rounds"].append({"round": 2, "tool_names": [name for name, _ in selected_tools]})
    return tool_results, tool_names_used, failure


def _compose_final_response(plan: ExplorationPlan, evidence: dict[str, Any]) -> str:
    evidence_dict = _to_dict(evidence)
    items = evidence_dict.get("evidence_items") or []
    by_shop: dict[str, dict[str, Any]] = {}
    for item in items:
        item_dict = _to_dict(item)
        shop_id = str(item_dict.get("shop_id", "") or "").strip()
        if not shop_id:
            continue
        bucket = by_shop.setdefault(
            shop_id,
            {
                "shop_name": str(item_dict.get("shop_name", "") or "").strip(),
                "open_status": "unknown",
                "distance_km": None,
                "eta_minutes": None,
                "summary": [],
            },
        )
        facet = str(item_dict.get("facet", "") or "")
        if facet == "open_status":
            value = _to_dict(item_dict.get("value"))
            if isinstance(value, dict):
                bucket["open_status"] = str(value.get("open_status", value.get("status", "unknown")) or "unknown")
        elif facet == "distance":
            value = _to_dict(item_dict.get("value"))
            if isinstance(value, dict):
                bucket["distance_km"] = value.get("distance_km")
                bucket["eta_minutes"] = value.get("eta_minutes")
        elif facet in {"review_summary", "deal", "coupon", "detail"}:
            value = item_dict.get("value")
            if isinstance(value, dict):
                bucket["summary"].append(str(value.get("summary", "") or "").strip())
    subgoal_texts: list[str] = []
    for subgoal in plan.subgoals:
        chosen = subgoal.selected_candidate or {}
        shop_id = str(chosen.get("shop_id", "") or "").strip()
        shop_name = str(chosen.get("shop_name", "") or "").strip() or shop_id or "这一步"
        extra = by_shop.get(shop_id, {})
        parts = [shop_name]
        open_status = str(extra.get("open_status", "") or "").strip()
        if open_status and open_status != "unknown":
            parts.append("营业中" if open_status in {"open", "opened"} else "未营业" if open_status in {"closed", "close"} else open_status)
        distance_km = extra.get("distance_km")
        if distance_km is not None:
            parts.append(f"距离约 {distance_km} 公里")
        eta_minutes = extra.get("eta_minutes")
        if eta_minutes is not None:
            parts.append(f"预计 {eta_minutes} 分钟")
        summary = "；".join([item for item in extra.get("summary", []) if item])
        if summary:
            parts.append(summary)
        subgoal_texts.append("，".join(parts))
    if subgoal_texts:
        if plan.has_temporal_sequence:
            return "按顺序安排如下：" + "；".join(f"{idx + 1}. {text}" for idx, text in enumerate(subgoal_texts))
        return "可按下面的顺序探索：" + "；".join(f"{idx + 1}. {text}" for idx, text in enumerate(subgoal_texts))
    return "我已经整理好了这次探索安排。"


def _build_success_patch(
    *,
    state: dict[str, Any],
    decision: OrchestrationDecision,
    plan: ExplorationPlan,
    evidence: EvidencePack,
    answer_plan: AnswerPlan,
    final_response: str,
    verifier_result: dict[str, Any],
) -> dict[str, Any]:
    timestamp = _utc_now_iso()
    passed = bool(verifier_result.get("passed", False))
    return {
        "workflow_name": "exploration_planning",
        "orchestration_pattern": "exploration_planning",
        "workflow_reason": str(decision.workflow_reason or "exploration planning workflow"),
        "workflow_run_status": "completed" if passed else "fallback",
        "workflow_runner_error": "" if passed else "exploration_verifier_rejected",
        "workflow_runner_reason": str(decision.workflow_reason or "exploration planning workflow"),
        "workflow_started_at": timestamp,
        "workflow_finished_at": timestamp,
        "workflow_callable": "run_exploration_planning_workflow",
        "workflow_registered": True,
        "response_mode": "exploration_plan" if passed else "fallback",
        "next_action": "run_workflow" if passed else "fallback",
        "exploration_plan": plan,
        "evidence_pack": evidence,
        "answer_plan": answer_plan,
        "final_response": final_response,
        "draft_response": final_response,
        "answer_source": "exploration_planning_workflow",
        "verifier_result": "pass" if passed else "fallback",
        "answer_verify_passed": passed,
        "answer_verify_violations": list(verifier_result.get("issues") or []),
        "fallback_reason": "" if passed else "exploration_verifier_rejected",
        "answer_fallback_reason": "" if passed else "exploration_verifier_rejected",
        "final_safety_status": "safe" if passed else "fallback",
        "llm_verbalizer_called": False,
        "llm_called": False,
        "llm_backend": "deterministic",
        **_log(state, "exploration_planning_workflow", workflow_name="exploration_planning", status="completed" if passed else "fallback"),
    }


def run_exploration_planning_workflow(
    state: GraphState,
    decision: OrchestrationDecision | None = None,
    *,
    dispatch_tool_call=None,
) -> dict[str, Any]:
    """Run the Phase 8 exploration planning workflow."""

    if dispatch_tool_call is None:
        dispatch_tool_call = globals()["dispatch_tool_call"]

    decision = decision or _to_dict(state.get("orchestration_decision"))
    if not isinstance(decision, OrchestrationDecision):
        decision = OrchestrationDecision.model_validate(
            _to_dict(decision)
            or {
                "orchestration_pattern": "exploration_planning",
                "workflow_name": "exploration_planning",
                "workflow_reason": "exploration planning workflow",
                "task_complexity": "high",
                "requires_tool": True,
                "requires_clarification": False,
                "response_mode": "exploration_plan",
                "confidence": 0.0,
                "missing_fields": [],
                "next_action": "run_workflow",
            }
        )

    semantic_frame = _to_dict(state.get("semantic_frame"))
    task_type = _normalize_task_type(state, decision)
    location = _extract_user_location(state)
    log_kv(
        _LOGGER,
        20,
        "[SUBGRAPH_ENTER]",
        tone="route",
        subgraph="exploration_planning_workflow",
        trace_id=state.get("trace_id", ""),
        session_id=state.get("session_id", ""),
        turn_id=state.get("turn_id", ""),
        task_type=task_type,
        workflow_name="exploration_planning",
    )

    subgoals, has_temporal_sequence, fallback_reason = _build_subgoals(state, decision)
    if fallback_reason == _FALLBACK_REASONS["too_many_subgoals"] or len(subgoals) > 3:
        return run_clarification_fallback_workflow(
            {
                **state,
                "task_type": task_type,
                "workflow_name": "exploration_planning",
                "workflow_reason": fallback_reason or _FALLBACK_REASONS["too_many_subgoals"],
                "response_mode": "clarify",
                "next_action": "clarify",
            },
            decision,
        )

    if not location:
        return run_clarification_fallback_workflow(
            {
                **state,
                "task_type": task_type,
                "workflow_name": "exploration_planning",
                "workflow_reason": _FALLBACK_REASONS["missing_location"],
                "response_mode": "clarify",
                "next_action": "clarify",
            },
            decision,
        )

    if not subgoals:
        return run_clarification_fallback_workflow(
            {
                **state,
                "task_type": task_type,
                "workflow_name": "exploration_planning",
                "workflow_reason": _FALLBACK_REASONS["too_many_subgoals"],
                "response_mode": "clarify",
                "next_action": "clarify",
            },
            decision,
        )

    for subgoal in subgoals:
        subgoal["location"] = location

    search_results, tool_names_used, search_failure = _tool_round_search(
        subgoals=subgoals,
        location=location,
        dispatch_tool_call=dispatch_tool_call,
    )
    if search_failure:
        return run_clarification_fallback_workflow(
            {
                **state,
                "task_type": task_type,
                "workflow_name": "exploration_planning",
                "workflow_reason": _FALLBACK_REASONS["no_result"],
                "response_mode": "fallback",
                "next_action": "fallback",
            },
            decision,
        )

    tool_results, expand_tool_names, expand_failure = _tool_round_expand(
        subgoals=subgoals,
        dispatch_tool_call=dispatch_tool_call,
    )
    tool_names_used.extend(expand_tool_names)
    if expand_failure:
        return run_clarification_fallback_workflow(
            {
                **state,
                "task_type": task_type,
                "workflow_name": "exploration_planning",
                "workflow_reason": _FALLBACK_REASONS["tool_failure"],
                "response_mode": "fallback",
                "next_action": "fallback",
            },
            decision,
        )

    execution_plan = ExecutionPlan.model_validate(
        {
            "plan_id": f"exploration_{task_type or 'unknown'}",
            "task_type": task_type,
            "tool_calls": [],
            "stages": [],
            "target_shop_ids": [
                str((subgoal.get("selected_candidate") or {}).get("shop_id", "")).strip()
                for subgoal in subgoals
                if str((subgoal.get("selected_candidate") or {}).get("shop_id", "")).strip()
            ],
            "query_terms": [str(subgoal.get("query", "") or "") for subgoal in subgoals if str(subgoal.get("query", "") or "").strip()],
            "scene_terms": [str(subgoal.get("kind", "") or "") for subgoal in subgoals if str(subgoal.get("kind", "") or "").strip()],
            "open_now_preferred": any("open" in str(subgoal.get("kind", "") or "").lower() for subgoal in subgoals),
            "coupon_preferred": any("coupon" in str(subgoal.get("query", "") or "").lower() for subgoal in subgoals),
            "nearby_preferred": True,
            "plan_source": "exploration_planning_workflow",
            "planning_notes": ["phase_8_exploration_planning"],
            "assumptions_used": ["existing_tools_only", "max_two_tool_rounds"],
        }
    )

    evidence = EvidencePack.model_validate(
        build_evidence(
            tool_results=tool_results,
            resolved_target={},
            execution_plan=execution_plan,
            recommendation_candidates=[],
            comparison_targets=[],
        )
    )

    answer_plan = AnswerPlan.model_validate(
        {
            "answer_type": "exploration_plan",
            "target_shop_ids": list(evidence.target_shop_ids or []),
            "response_sections": [
                {
                    "section_id": "exploration_summary",
                    "section_type": "exploration_plan",
                    "status": "ok" if evidence.facet_results else "unknown",
                    "required": False,
                }
            ],
            "allowed_claims": [],
            "required_claims": [],
            "must_mention_unknowns": [],
            "forbidden_claims": [],
            "ranking_snapshot_id": "",
            "comparison_matrix_id": "",
            "tone": "neutral",
            "fallback_template_type": "exploration_plan",
        }
    )

    plan = _build_exploration_plan(
        state=state,
        decision=decision,
        subgoals=subgoals,
        location=location,
        tool_names_used=tool_names_used,
        tool_rounds_used=2 if tool_results else 1,
    )

    final_response = _compose_final_response(plan, evidence.model_dump())
    verifier_result = verify_answer(final_response, evidence.model_dump(), "exploration_plan")
    if not verifier_result.get("passed", False):
        return run_clarification_fallback_workflow(
            {
                **state,
                "task_type": task_type,
                "workflow_name": "exploration_planning",
                "workflow_reason": "exploration_verifier_rejected",
                "response_mode": "fallback",
                "next_action": "fallback",
            },
            decision,
        )

    patch = _build_success_patch(
        state=state,
        decision=decision,
        plan=plan,
        evidence=evidence,
        answer_plan=answer_plan,
        final_response=final_response,
        verifier_result=verifier_result,
    )
    patch["subgoals"] = plan.subgoals
    patch["has_temporal_sequence"] = plan.has_temporal_sequence
    patch["expected_output"] = plan.expected_output
    patch["exploration_round_count"] = plan.tool_rounds_used
    patch["tool_availability"] = {
        "search_shops": True,
        "get_shop_detail": True,
        "check_open_status": True,
        "get_distance_eta": True,
        "get_shop_review_summary": True,
        "get_coupon_list": True,
        "get_deal_list": True,
    }
    patch["location_status"] = "provided" if location else "missing"
    patch["user_location"] = location
    patch["workflow_run_status"] = "completed"
    patch["workflow_runner_error"] = ""
    patch["workflow_runner_reason"] = str(decision.workflow_reason or "exploration planning workflow")
    patch["workflow_started_at"] = patch.get("workflow_started_at") or _utc_now_iso()
    patch["workflow_finished_at"] = _utc_now_iso()
    patch["workflow_callable"] = "run_exploration_planning_workflow"
    patch["workflow_registered"] = True
    patch["response_mode"] = "exploration_plan"
    patch["next_action"] = "run_workflow"
    patch["evidence_pack"] = evidence
    patch["answer_plan"] = answer_plan
    patch["final_response"] = final_response
    patch["draft_response"] = final_response
    patch["answer_source"] = "exploration_planning_workflow"
    patch["verifier_result"] = "pass"
    patch["answer_verify_passed"] = True
    patch["answer_verify_violations"] = []
    patch["fallback_reason"] = ""
    patch["answer_fallback_reason"] = ""
    patch["final_safety_status"] = "safe"
    patch["llm_verbalizer_called"] = False
    patch["llm_called"] = False
    patch["llm_backend"] = "deterministic"
    patch["state_keys_changed"] = list(patch.keys())
    patch.update(_log(state, "exploration_planning_workflow", workflow_name="exploration_planning", status="completed", tool_rounds_used=plan.tool_rounds_used, subgoal_count=len(plan.subgoals)))
    return patch
