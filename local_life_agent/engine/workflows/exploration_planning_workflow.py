"""Independent workflow for multi-subgoal exploration planning.

Phase 8 keeps this workflow intentionally small:
- recognize 2-3 exploration subgoals and simple temporal order
- run at most two tool rounds with existing tools only
- build ExplorationPlan / EvidencePack / AnswerPlan
- verify the generated answer before returning
- emit the same clarification / fallback shape when the
  request is underspecified, over-constrained, or tool execution fails
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from ...domain.graph_state import GraphState
from ...domain.schemas import AnswerPlan, EvidencePack, ExplorationPlan, ExplorationSubgoal, ExecutionPlan, OrchestrationDecision, ToolResult
from ...engine._compat import _log, _to_dict
from ...answer.response_directive import build_response_directive
from ...observability.file_logger import get_python_service_logger, log_kv
from ...planning.shared.evidence_adapter import (
    apply_state_update_plan,
    build_answer_plan_from_evidence,
    build_evidence_pack_from_tool_results,
    verify_answer_plan,
)
from ...planning.budget.budget_context import budget_context_from_state
from ...planning.evidence.evidence_cache import get_default_evidence_cache
from ...target.clarification import build_pending_clarification, format_pending_prompt
from ...tools.gateway import dispatch_tool_call as _default_dispatch_tool_call

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

_FALLBACK_POLICY: dict[str, dict[str, Any]] = {
    "exploration_missing_location": {
        "response_mode": "clarify",
        "next_action": "clarify",
        "answer_type": "clarification",
        "response_text": "还缺少位置信息，请补充后我再继续帮你规划。",
        "section_type": "clarification",
    },
    "exploration_too_many_subgoals": {
        "response_mode": "clarify",
        "next_action": "clarify",
        "answer_type": "clarification",
        "response_text": "你的需求里子目标有点多，请再收敛一点，我再继续帮你拆分。",
        "section_type": "clarification",
    },
    "exploration_tool_failure": {
        "response_mode": "fallback",
        "next_action": "fallback",
        "answer_type": "error",
        "response_text": "相关服务暂时不可用，请稍后再试。",
        "section_type": "fallback",
    },
    "exploration_no_result": {
        "response_mode": "fallback",
        "next_action": "fallback",
        "answer_type": "error",
        "response_text": "暂时没有查到结果，你可以换个说法或补充更多信息再试。",
        "section_type": "fallback",
    },
    "exploration_unsupported": {
        "response_mode": "fallback",
        "next_action": "fallback",
        "answer_type": "error",
        "response_text": "这个能力暂时不支持，我可以继续帮你处理本地生活查询类问题。",
        "section_type": "boundary",
    },
}


def _collect_candidate_targets(state: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for source in (
        state.get("pending_clarification"),
        state.get("comparison_targets"),
        _to_dict(state.get("semantic_frame")).get("comparison_targets"),
    ):
        if not source:
            continue
        if isinstance(source, dict):
            source = source.get("candidate_targets") or source.get("targets") or []
        if not isinstance(source, list):
            continue
        for item in source:
            item_dict = _to_dict(item)
            shop_id = str(item_dict.get("shop_id", "") or item_dict.get("resolved_shop", {}).get("shop_id", "") or "").strip()
            shop_name = str(item_dict.get("shop_name", "") or item_dict.get("resolved_shop", {}).get("shop_name", "") or "").strip()
            if shop_id or shop_name:
                candidates.append(
                    {
                        "shop_id": shop_id,
                        "shop_name": shop_name,
                        "address": str(item_dict.get("address", "") or "").strip(),
                    }
                )
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in candidates:
        key = (str(item.get("shop_id", "")).strip(), str(item.get("shop_name", "")).strip())
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _build_fallback_answer_plan(policy_key: str, response_mode: str) -> AnswerPlan:
    policy = _FALLBACK_POLICY.get(policy_key, _FALLBACK_POLICY["exploration_missing_location"])
    return AnswerPlan.model_validate(
        {
            "answer_type": str(policy.get("answer_type", "clarification") or "clarification"),
            "target_shop_ids": [],
            "response_sections": [
                {
                    "section_id": f"exploration_{policy_key}",
                    "section_type": str(policy.get("section_type", "clarification") or "clarification"),
                    "status": "ok",
                    "required": False,
                },
            ],
            "allowed_claims": [],
            "required_claims": [],
            "must_mention_unknowns": [],
            "forbidden_claims": [],
            "ranking_snapshot_id": "",
            "comparison_matrix_id": "",
            "tone": "neutral",
            "fallback_template_type": response_mode,
        }
    )


def _build_fallback_clarification_request(
    *,
    state: dict[str, Any],
    policy_key: str,
    semantic_frame: dict[str, Any],
) -> dict[str, Any]:
    pending_clarification = _to_dict(state.get("pending_clarification"))
    if pending_clarification:
        return pending_clarification

    pending = build_pending_clarification(
        original_text=str(state.get("raw_text", "") or state.get("normalized_text", "") or ""),
        original_semantic_frame=semantic_frame,
        original_task_type=str(state.get("task_type", "") or semantic_frame.get("task_type", "") or ""),
        candidate_targets=_collect_candidate_targets(state),
        reason=policy_key,
        source_node="exploration_planning_workflow",
    )
    return pending.model_dump()


def _build_fallback_patch(
    *,
    state: dict[str, Any],
    decision: OrchestrationDecision,
    policy_key: str,
    workflow_reason: str,
) -> dict[str, Any]:
    policy = _FALLBACK_POLICY.get(policy_key, _FALLBACK_POLICY["exploration_missing_location"])
    response_mode = str(policy.get("response_mode", "clarify") or "clarify")
    answer_plan = _build_fallback_answer_plan(policy_key, response_mode)
    timestamp = _utc_now_iso()
    semantic_frame = _to_dict(state.get("semantic_frame"))
    final_response = str(policy.get("response_text", "") or "").strip()
    pending_clarification = _build_fallback_clarification_request(state=state, policy_key=policy_key, semantic_frame=semantic_frame)

    if response_mode == "clarify":
        final_response = format_pending_prompt(pending_clarification)
    elif not final_response:
        final_response = str(policy.get("response_text", "") or "抱歉，暂时无法处理您的请求，请稍后再试。")
    response_directive = build_response_directive(
        answer_text=final_response,
        answer_type=str(policy.get("answer_type", "clarification") or "clarification"),
        response_mode=response_mode,
        fallback_reason=policy_key,
        trace_id=str(state.get("trace_id", "") or ""),
        preview_text=final_response,
        answer_source="clarification_fallback_workflow",
        fallback_template_type=response_mode,
    )

    patch: dict[str, Any] = {
        "workflow_name": "clarification_fallback",
        "orchestration_pattern": "clarification_fallback",
        "workflow_reason": str(workflow_reason or f"exploration fallback for {policy_key}"),
        "workflow_run_status": "clarify" if response_mode == "clarify" else "fallback",
        "workflow_runner_error": "",
        "workflow_runner_reason": str(workflow_reason or f"exploration fallback for {policy_key}"),
        "workflow_candidate_reason": str(workflow_reason or f"exploration fallback for {policy_key}"),
        "workflow_started_at": timestamp,
        "workflow_finished_at": timestamp,
        "workflow_callable": "run_exploration_planning_workflow",
        "workflow_registered": True,
        "response_mode": response_mode,
        "next_action": str(policy.get("next_action", "clarify") or "clarify"),
        "workflow_result_status": "clarify" if response_mode == "clarify" else "fallback",
        "workflow_clarification_request": pending_clarification,
        "answer_plan": answer_plan,
        "draft_response": final_response,
        "response_directive": response_directive,
        "answer_source": "clarification_fallback_workflow",
        "verifier_result": "pass",
        "answer_verify_passed": True,
        "answer_verify_violations": [],
        "fallback_reason": policy_key,
        "answer_fallback_reason": policy_key,
        "workflow_fallback_reason": policy_key,
        "final_safety_status": "safe",
        "llm_verbalizer_called": False,
        "llm_called": False,
        "llm_backend": "deterministic",
        "state_keys_changed": [
            "workflow_name",
            "orchestration_pattern",
            "workflow_run_status",
            "workflow_runner_error",
            "workflow_runner_reason",
            "workflow_started_at",
            "workflow_finished_at",
            "workflow_callable",
            "workflow_registered",
            "response_mode",
            "next_action",
            "workflow_result_status",
            "workflow_clarification_request",
            "answer_plan",
            "draft_response",
            "response_directive",
            "answer_source",
            "verifier_result",
            "answer_verify_passed",
            "answer_verify_violations",
            "fallback_reason",
            "answer_fallback_reason",
            "workflow_fallback_reason",
            "final_safety_status",
        ],
    }
    patch["pending_clarification"] = pending_clarification
    patch["state_keys_changed"].append("pending_clarification")
    patch.update(_log(state, "exploration_planning_workflow", workflow_name="clarification_fallback", policy_key=policy_key, status=patch["workflow_run_status"]))
    log_kv(
        _LOGGER,
        20 if response_mode == "clarify" else 30,
        "[WORKFLOW_RUNNER]",
        tone="route" if response_mode == "clarify" else "warn",
        node_name="exploration_planning_workflow",
        workflow_name="clarification_fallback",
        policy_key=policy_key,
        status=patch["workflow_run_status"],
    )
    return patch


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


def _build_subgoal_from_stage(
    *,
    stage: dict[str, Any],
    index: int,
    semantic_frame: dict[str, Any],
    location: dict[str, Any],
) -> dict[str, Any]:
    stage_dict = _to_dict(stage)
    stage_id = str(stage_dict.get("stage_id", "") or f"stage_{index}").strip()
    stage_type = str(stage_dict.get("stage_type", stage_dict.get("kind", stage_dict.get("category", "custom"))) or "custom").strip()
    category = str(stage_dict.get("category", "") or stage_type or "custom").strip()
    candidate_query = str(stage_dict.get("candidate_query", stage_dict.get("query", "") or category) or "").strip()
    if not candidate_query:
        candidate_query = category or stage_type or "探索安排"
    location_value = _to_dict(stage_dict.get("location") or semantic_frame.get("location") or location)
    time_value = str(stage_dict.get("time", "") or semantic_frame.get("time", "") or "").strip()
    scene_value = str(stage_dict.get("scene", "") or semantic_frame.get("scene", "") or "").strip()
    evidence_requirements = stage_dict.get("evidence_requirements") or []
    if not isinstance(evidence_requirements, list):
        evidence_requirements = [str(evidence_requirements)]
    order_raw = stage_dict.get("order", stage_dict.get("sequence_order", index)) or index
    try:
        order = int(order_raw)
    except Exception:
        order = index
    fallback_strategy = str(stage_dict.get("fallback_strategy", "") or ("search_then_select" if location_value else "ask_clarification_again")).strip()
    note = str(stage_dict.get("notes", stage_dict.get("note", "")) or "semantic_stage").strip()
    return {
        "subgoal_id": stage_id.replace("stage_", "subgoal_"),
        "stage_id": stage_id,
        "stage_type": stage_type,
        "kind": stage_type,
        "category": category,
        "location": location_value,
        "time": time_value,
        "scene": scene_value,
        "constraints": _to_dict(stage_dict.get("constraints") or {}),
        "order": order,
        "sequence_order": order,
        "required": bool(stage_dict.get("required", True)),
        "candidate_query": candidate_query,
        "query": candidate_query,
        "evidence_requirements": [str(item).strip() for item in evidence_requirements if str(item).strip()],
        "fallback_strategy": fallback_strategy,
        "status": str(stage_dict.get("status", "planned") or "planned").strip() or "planned",
        "temporal_relation": str(stage_dict.get("temporal_relation", "") or ("first" if order == 1 else "ordered")).strip(),
        "require_location": not bool(location_value),
        "max_candidates": int(stage_dict.get("max_candidates", 3) or 3),
        "tool_rounds": [],
        "selected_candidate": None,
        "candidate_shops": [],
        "note": note,
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
    semantic_frame = _to_dict(state.get("semantic_frame"))
    semantic_stages = [item for item in (semantic_frame.get("exploration_stages") or []) if item]
    if semantic_stages:
        location = _to_dict(semantic_frame.get("location") or _extract_user_location(state))
        subgoals = [
            _build_subgoal_from_stage(
                stage=stage,
                index=idx,
                semantic_frame=semantic_frame,
                location=location,
            )
            for idx, stage in enumerate(semantic_stages[:3], start=1)
        ]
        return subgoals, len(subgoals) > 1, None
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
    semantic_frame = _to_dict(state.get("semantic_frame"))
    expected_output = "按顺序给出最多三个子目标的探索安排，并标明每一步的候选查询与证据需求。"
    if len(subgoals) == 2:
        expected_output = "按顺序给出两个子目标的探索安排，并标明每一步的候选查询与证据需求。"
    allowed_subgoal_keys = set(ExplorationSubgoal.model_fields)
    sanitized_subgoals = [
        {key: value for key, value in subgoal.items() if key in allowed_subgoal_keys}
        for subgoal in subgoals
    ]
    stage_queries = [str(subgoal.get("candidate_query") or subgoal.get("query") or "").strip() for subgoal in subgoals if str(subgoal.get("candidate_query") or subgoal.get("query") or "").strip()]
    stage_evidence_requirements = [
        [str(item).strip() for item in (subgoal.get("evidence_requirements") or []) if str(item).strip()]
        for subgoal in subgoals
    ]
    stage_statuses = [str(subgoal.get("status", "planned") or "planned").strip() or "planned" for subgoal in subgoals]
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
            "stage_queries": stage_queries,
            "stage_evidence_requirements": stage_evidence_requirements,
            "stage_statuses": stage_statuses,
            "tool_rounds_used": tool_rounds_used,
            "location_required": True,
            "location_available": bool(location),
            "tool_names_used": list(dict.fromkeys(tool_names_used)),
            "notes": [
                "phase_5_exploration_planning",
                f"scene={str(semantic_frame.get('scene', '') or '').strip()}",
                f"time={str(semantic_frame.get('time', '') or '').strip()}",
            ],
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
) -> list[str]:
    tool_names_used: list[str] = ["search_shops"]
    for subgoal in subgoals:
        query = _search_query_for_subgoal(subgoal)
        raw = dispatch_tool_call("search_shops", {"query": query, "location": location, "limit": 3})
        raw_dict = _to_dict(raw)
        result_status = str(raw_dict.get("result_status", "") or "").lower()
        items = raw_dict.get("data")
        if isinstance(items, dict):
            items = items.get("items", [])
        if not isinstance(items, list):
            items = []
        normalized = [_normalize_shop_item(item) for item in items if str(_to_dict(item).get("shop_id", "") or "").strip()]
        subgoal["search_result"] = raw_dict
        subgoal["search_result_status"] = result_status or ("ok" if normalized else "empty")
        subgoal["tool_rounds"].append(
            {
                "round": 1,
                "tool_name": "search_shops",
                "query": query,
                "result_count": len(normalized),
                "result_status": subgoal["search_result_status"],
            }
        )
        subgoal["candidate_shops"] = normalized
        subgoal["selected_candidate"] = normalized[0] if normalized else None
    return tool_names_used


def _tool_round_expand(
    *,
    subgoals: list[dict[str, Any]],
    dispatch_tool_call,
) -> list[str]:
    tool_names_used: list[str] = []
    call_index = 0
    for subgoal in subgoals:
        candidates = list(subgoal.get("candidate_shops") or [])
        if not candidates:
            continue
        chosen = candidates[0]
        shop_id = str(chosen.get("shop_id", "") or "").strip()
        if not shop_id:
            continue
        subgoal["selected_candidate"] = chosen
        subgoal.setdefault("tool_results", {})
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
            subgoal["tool_results"][tool_name] = {
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
        subgoal["tool_rounds"].append(
            {
                "round": 2,
                "tool_names": [name for name, _ in selected_tools],
                "result_statuses": {
                    name: str((subgoal.get("tool_results", {}).get(name) or {}).get("result_status", "unknown") or "unknown")
                    for name, _ in selected_tools
                },
            }
        )
    return tool_names_used


def _compose_final_response(plan: ExplorationPlan, evidence: dict[str, Any], answer_plan: dict[str, Any]) -> str:
    evidence_dict = _to_dict(evidence)
    answer_plan_dict = _to_dict(answer_plan)
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
        if facet in {"open_status", "open_now"}:
            value = _to_dict(item_dict.get("value"))
            if isinstance(value, dict):
                bucket["open_status"] = str(value.get("open_status", value.get("status", "unknown")) or "unknown")
        elif facet in {"distance", "travel_time"}:
            value = _to_dict(item_dict.get("value"))
            if isinstance(value, dict):
                bucket["distance_km"] = value.get("distance_km")
                bucket["eta_minutes"] = value.get("eta_minutes")
        elif facet in {"review_summary", "review_tags", "deal", "group_buy", "coupon", "detail"}:
            value = item_dict.get("value")
            if isinstance(value, dict):
                bucket["summary"].append(str(value.get("summary", "") or "").strip())
            elif isinstance(value, list):
                bucket["summary"].extend([str(v).strip() for v in value if str(v).strip()])
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
    response_parts: list[str] = []
    if subgoal_texts:
        prefix = "按顺序安排如下：" if plan.has_temporal_sequence else "可按下面的顺序探索："
        response_parts.append(prefix + "；".join(f"{idx + 1}. {text}" for idx, text in enumerate(subgoal_texts)))
    else:
        response_parts.append("我已经整理好了这次探索安排。")

    disclaimers = [str(item).strip() for item in answer_plan_dict.get("required_disclaimers", []) or [] if str(item).strip()]
    unknown_facets = [str(item).strip() for item in answer_plan_dict.get("unknown_facets", []) or [] if str(item).strip()]
    failed_facets = [str(item).strip() for item in answer_plan_dict.get("failed_facets", []) or [] if str(item).strip()]
    if disclaimers:
        response_parts.append("；".join(disclaimers))
    elif unknown_facets or failed_facets:
        extra_parts: list[str] = []
        if unknown_facets:
            extra_parts.append(f"部分信息暂无法确认: {', '.join(dict.fromkeys(unknown_facets))}")
        if failed_facets:
            extra_parts.append(f"部分工具结果失败: {', '.join(dict.fromkeys(failed_facets))}")
        if extra_parts:
            response_parts.append("；".join(extra_parts))
    return "；".join(part for part in response_parts if part)


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
    response_directive = build_response_directive(
        answer_text=final_response,
        answer_type=str(getattr(answer_plan, "answer_type", "") or ""),
        response_mode="exploration_plan" if passed else "fallback",
        fallback_reason="" if passed else "exploration_verifier_rejected",
        trace_id=str(state.get("trace_id", "") or ""),
        preview_text=final_response,
        answer_source="exploration_planning_workflow",
        fallback_template_type=str(getattr(answer_plan, "fallback_template_type", "") or ""),
    )
    return {
        "workflow_name": "exploration_planning",
        "orchestration_pattern": "exploration_planning",
        "workflow_reason": str(decision.workflow_reason or "exploration planning workflow"),
        "workflow_run_status": "completed" if passed else "fallback",
        "workflow_runner_error": "" if passed else "exploration_verifier_rejected",
        "workflow_runner_reason": str(decision.workflow_reason or "exploration planning workflow"),
        "workflow_candidate_reason": str(decision.workflow_reason or "exploration planning workflow"),
        "workflow_started_at": timestamp,
        "workflow_finished_at": timestamp,
        "workflow_callable": "run_exploration_planning_workflow",
        "workflow_registered": True,
        "response_mode": "exploration_plan" if passed else "fallback",
        "next_action": "run_workflow" if passed else "fallback",
        "exploration_plan": plan,
        "evidence_pack": evidence,
        "answer_plan": answer_plan,
        "draft_response": final_response,
        "response_directive": response_directive,
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
        return _build_fallback_patch(
            state={
                **state,
                "task_type": task_type,
                "workflow_name": "exploration_planning",
            },
            decision=decision,
            policy_key=_FALLBACK_REASONS["too_many_subgoals"],
            workflow_reason=fallback_reason or _FALLBACK_REASONS["too_many_subgoals"],
        )

    if not location:
        return _build_fallback_patch(
            state={
                **state,
                "task_type": task_type,
                "workflow_name": "exploration_planning",
            },
            decision=decision,
            policy_key=_FALLBACK_REASONS["missing_location"],
            workflow_reason=_FALLBACK_REASONS["missing_location"],
        )

    if not subgoals:
        return _build_fallback_patch(
            state={
                **state,
                "task_type": task_type,
                "workflow_name": "exploration_planning",
            },
            decision=decision,
            policy_key=_FALLBACK_REASONS["too_many_subgoals"],
            workflow_reason=_FALLBACK_REASONS["too_many_subgoals"],
        )

    budget = budget_context_from_state(state)
    for subgoal in subgoals:
        subgoal["location"] = location

    tool_names_used = _tool_round_search(
        subgoals=subgoals,
        location=location,
        dispatch_tool_call=dispatch_tool_call,
    )

    deadline_remaining = budget.deadline_remaining_ms
    allow_expand = budget.remaining("tool_round_budget") > 0 and budget.remaining("facet_enrich_budget") > 0
    if isinstance(deadline_remaining, int) and deadline_remaining <= 50:
        allow_expand = False
    if allow_expand:
        expand_tool_names = _tool_round_expand(
            subgoals=subgoals,
            dispatch_tool_call=dispatch_tool_call,
        )
        tool_names_used.extend(expand_tool_names)

    evidence = build_evidence_pack_from_tool_results(
        workflow_name="exploration_planning",
        owner="exploration_planning",
        subgoals=subgoals,
        semantic_facets=semantic_frame.get("facets") or [],
        location_context=location,
        semantic_frame=semantic_frame,
        semantic_parse_source=str(state.get("semantic_parse_source", "") or ""),
        grounding_status=str(state.get("grounding_status", "") or ""),
        missing_slot_type=str(state.get("missing_slot_type", "") or ""),
        router_policy_decision=_to_dict(state.get("router_policy_decision")),
        router_policy_conflicts=list(state.get("router_policy_conflicts") or []),
        conversation_continuity=_to_dict(state.get("conversation_continuity")),
        exploration_stages=list(semantic_frame.get("exploration_stages") or []),
        stage_queries=[str(subgoal.get("candidate_query") or subgoal.get("query") or "").strip() for subgoal in subgoals if str(subgoal.get("candidate_query") or subgoal.get("query") or "").strip()],
        stage_evidence_requirements=[
            [str(item).strip() for item in (subgoal.get("evidence_requirements") or []) if str(item).strip()]
            for subgoal in subgoals
        ],
        stage_statuses=[str(subgoal.get("status", "planned") or "planned").strip() or "planned" for subgoal in subgoals],
        scene=str(semantic_frame.get("scene", "") or "").strip(),
        time=str(semantic_frame.get("time", "") or "").strip(),
        cache=get_default_evidence_cache(),
        cache_scope={
            "workflow": "exploration_planning_workflow",
            "trace_id": state.get("trace_id", ""),
            "session_id": state.get("session_id", ""),
            "turn_id": state.get("turn_id", ""),
        },
    )

    if evidence.failed_facets:
        return _build_fallback_patch(
            state={
                **state,
                "task_type": task_type,
                "workflow_name": "exploration_planning",
            },
            decision=decision,
            policy_key=_FALLBACK_REASONS["tool_failure"],
            workflow_reason=_FALLBACK_REASONS["tool_failure"],
        )

    if not evidence.answerable_facets:
        fallback_reason = _FALLBACK_REASONS["no_result"]
        return _build_fallback_patch(
            state={
                **state,
                "task_type": task_type,
                "workflow_name": "exploration_planning",
            },
            decision=decision,
            policy_key=_FALLBACK_REASONS["no_result"],
            workflow_reason=fallback_reason,
        )

    plan = _build_exploration_plan(
        state=state,
        decision=decision,
        subgoals=subgoals,
        location=location,
        tool_names_used=tool_names_used,
        tool_rounds_used=2 if any(subgoal.get("tool_results") for subgoal in subgoals) else 1,
    )

    answer_plan = build_answer_plan_from_evidence(
        task_type=task_type,
        evidence_pack=evidence,
        exploration_plan=plan,
    )

    final_response = _compose_final_response(plan, evidence.model_dump(), answer_plan.model_dump())
    verifier_result = verify_answer_plan(final_response, evidence.model_dump(), "exploration_plan")
    if not verifier_result.get("passed", False):
        fallback_patch = _build_fallback_patch(
            state={
                **state,
                "task_type": task_type,
                "workflow_name": "exploration_planning",
            },
            decision=decision,
            policy_key=_FALLBACK_REASONS["tool_failure"],
            workflow_reason="exploration_verifier_rejected",
        )
        fallback_patch["answer_verify_passed"] = False
        fallback_patch["answer_verify_violations"] = list(verifier_result.get("issues") or [])
        fallback_patch["verification_errors"] = list(verifier_result.get("issues") or [])
        fallback_patch["verifier_result"] = "fail"
        fallback_patch["fallback_reason"] = "exploration_verifier_rejected"
        fallback_patch["answer_fallback_reason"] = "exploration_verifier_rejected"
        return fallback_patch

    patch = _build_success_patch(
        state=state,
        decision=decision,
        plan=plan,
        evidence=evidence,
        answer_plan=answer_plan,
        final_response=final_response,
        verifier_result=verifier_result,
    )
    patch["tool_results"] = evidence.model_dump().get("tool_results", {})
    patch["tool_result_set"] = patch["tool_results"]
    patch["state_update_plan_preview"] = apply_state_update_plan(
        {
            "workflow_name": "exploration_planning",
            "task_type": task_type,
            "local_life_goal_draft": state.get("local_life_goal_draft"),
            "resolved_target": None,
            "resolved_shop": None,
            "current_shop": None,
            "pending_clarification": state.get("pending_clarification"),
            "last_recommendation_list": [],
            "comparison_targets": [],
            "user_location": location,
            "evidence_pack": evidence.model_dump(),
            "tool_result_set": evidence.model_dump().get("tool_results", {}) or {},
            "execution_plan": plan.model_dump(),
        },
        task_type,
        "",
    )
    patch["exploration_stages"] = semantic_frame.get("exploration_stages", [])
    patch["stage_queries"] = list(plan.stage_queries)
    patch["stage_evidence_requirements"] = list(plan.stage_evidence_requirements)
    patch["stage_statuses"] = list(plan.stage_statuses)
    patch["scene"] = str(semantic_frame.get("scene", "") or "").strip()
    patch["time"] = str(semantic_frame.get("time", "") or "").strip()
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
    patch["draft_response"] = final_response
    patch["answer_source"] = "exploration_planning_workflow"
    patch["preview_text"] = final_response
    patch["preview_policy_result"] = {"verified": True, "allowed": True, "reason": "verified"}
    patch["verifier_result"] = "pass"
    patch["answer_verify_passed"] = True
    patch["answer_verify_violations"] = []
    patch["fallback_reason"] = ""
    patch["answer_fallback_reason"] = ""
    patch["final_safety_status"] = "safe"
    patch["llm_verbalizer_called"] = False
    patch["llm_called"] = False
    patch["llm_backend"] = "deterministic"
    patch["stream_status"] = "completed"
    patch["state_keys_changed"] = list(patch.keys())
    patch.update(_log(state, "exploration_planning_workflow", workflow_name="exploration_planning", status="completed", tool_rounds_used=plan.tool_rounds_used, subgoal_count=len(plan.subgoals)))
    return patch
