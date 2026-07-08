"""planning_subgraph — goal planning, target resolution, and evidence planning.

This subgraph takes the parsed semantic frame and:
1. Plans the user's goal (GoalPlanner + GoalReview)
2. Resolves target shops / candidates (TargetResolve)
3. Decides whether to clarify or proceed (ClarifyDecide)
4. Plans what evidence to collect (EvidencePlanner)
5. Validates the execution plan (PlanValidator)
"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

from .._compat import (
    _log,
    _run_step,
    _run_steps,
    _state_delta,
    _session_state_dict,
    _session_store_state,
    _to_dict,
    _user_location,
    _unwrap_resolve_shop_result,
    _OUTER_WRAPPER_EXCLUDE_FIELDS,
)
from .._routes import (
    _OUTER_ROUTE_CLARIFY,
    _OUTER_ROUTE_EXECUTE,
    _OUTER_ROUTE_FALLBACK,
    _OUTER_ROUTE_REJECT,
)
from ...domain.candidate import (
    CandidateSet,
    CandidateSource,
    CandidateSpec,
    CandidateStatus,
    GoalType,
    LocalLifeGoalDraft,
    ResolvedCandidate,
    ResolutionStage,
)
from ...domain.enums import TaskType
from ...domain.graph_state import GraphState
from ...domain.schemas import (
    ExecutionPlan,
    ResolveShopResult,
    SemanticFrame,
    ShopCandidate,
    ShopRef,
    ToolCallSpec,
    ToolResult,
)
from ...domain.shop_entity import ShopResolutionStatus
from ...domain.shop_entity import ShopResolutionResult
from ...domain.facets import build_target_resolution_result, normalize_query_facets
from ...domain.state import SessionState
from ...location_utils import normalize_location_payload
from ...domain.contextualized_turn import build_contextual_follow_up
from ...planning.plans.candidate_review import review_candidate_set
from ...planning.evidence.evidence_planner import (
    plan_evidence as plan_evidence_from_candidates,
    plan_evidence_with_llm,
)
from ...planning.plans.execution_plan_builder import build_recommendation_execution_plan
from ...planning.goal.goal_draft import build_candidate_spec, build_local_life_goal_draft
from ...planning.goal.goal_planner import plan_goal as p2_plan_goal, plan_goal_with_llm
from ...planning.goal.goal_review import review_goal as p2_review_goal
from ...planning.plans.plan_validator import ExecutionPlanValidator
from ...planning.policies.replan_policy import increment_expand_search, increment_replan_evidence
from ...planning.policies.review_policy import NextAction
from ...target.candidate_resolver import CandidateResolver
from ...target.clarification import build_pending_clarification, format_pending_prompt, handle_clarification_reply
from ...target.reference_resolver import resolve_comparison_targets
from ...target.shop_resolver import resolve_shop_entities, resolve_shop_entity
from ... import config
from ...observability.file_logger import get_python_service_logger, log_kv
from ...core import PlanningCore

_LOGGER = get_python_service_logger()
_PLANNING_WRAPPER_EXCLUDE_FIELDS = _OUTER_WRAPPER_EXCLUDE_FIELDS - {"event_log"}
_PLANNING_CORE = PlanningCore()
_CANDIDATE_CORE: CandidateResolver | None = None


def _get_candidate_core() -> CandidateResolver:
    """Return the active candidate resolver, honoring test monkeypatches."""
    global _CANDIDATE_CORE
    if _CANDIDATE_CORE is not None:
        return _CANDIDATE_CORE
    try:
        from .. import graph_builder as _graph_builder

        resolver_cls = getattr(_graph_builder, "CandidateResolver", CandidateResolver)
        return resolver_cls()
    except Exception:
        return CandidateResolver()


def _enum_value(value: Any) -> str:
    """统一提取枚举或普通值的字符串值。"""
    return str(getattr(value, "value", value) or "").strip()


def _pending_candidate_targets(candidate_set: CandidateSet) -> list[dict[str, Any]]:
    candidates = list(candidate_set.candidates or [])
    def _candidate_sort_key(candidate: Any) -> tuple[int, int, str, str]:
        shop_id = str(getattr(candidate, "shop_id", "") or "").strip()
        shop_name = str(getattr(candidate, "shop_name", "") or "").strip()
        if shop_id.isdigit():
            # Prefer canonical numeric fixture IDs like 900007 over short
            # placeholders or synthetic ids.
            group = 0 if len(shop_id) >= 6 else 1
            try:
                numeric = int(shop_id)
            except Exception:
                numeric = 0
        elif shop_id.startswith("shop_"):
            group = 2
            numeric = 0
        else:
            group = 3
            numeric = 0
        return (group, numeric, shop_name, shop_id)

    candidates = sorted(candidates, key=_candidate_sort_key)
    pending_candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        shop_id = str(getattr(candidate, "shop_id", "") or "").strip()
        if shop_id and shop_id in seen:
            continue
        if shop_id:
            seen.add(shop_id)
        pending_candidates.append(
            {
                "shop_id": shop_id,
                "shop_name": str(getattr(candidate, "shop_name", "") or "").strip(),
                "address": str((getattr(candidate, "raw", {}) or {}).get("address", "") or ""),
            }
        )
    return pending_candidates


def _candidate_shop_dict(candidate: Any) -> dict[str, Any]:
    """兼容 plain candidate dict 与嵌套 shop 字段两种候选结构。"""
    item = _to_dict(candidate)
    if not item:
        return {}
    shop = item.get("shop") or item.get("resolved_shop") or item
    shop_dict = _to_dict(shop)
    if not shop_dict:
        return {}
    if not shop_dict.get("address") and item.get("address"):
        shop_dict["address"] = item.get("address")
    if not shop_dict.get("alias") and item.get("alias"):
        shop_dict["alias"] = item.get("alias")
    return shop_dict


def _collect_clarification_candidates(state: GraphState, working: dict[str, Any]) -> list[dict[str, Any]]:
    """尽量从现有上下文里收集可用于澄清的候选店。"""
    collected: list[dict[str, Any]] = []

    def _append(candidate: Any) -> None:
        shop_dict = _candidate_shop_dict(candidate)
        if not shop_dict:
            return
        shop_id = str(shop_dict.get("shop_id", "") or "").strip()
        shop_name = str(shop_dict.get("shop_name", "") or "").strip()
        if not shop_id and not shop_name:
            return
        key = (shop_id, shop_name)
        if any((str(item.get("shop_id", "") or "").strip(), str(item.get("shop_name", "") or "").strip()) == key for item in collected):
            return
        collected.append({
            "shop_id": shop_id,
            "shop_name": shop_name,
            "address": str(shop_dict.get("address", "") or "").strip(),
        })

    for item in list(working.get("comparison_targets") or []):
        _append(item)
    _append(working.get("resolve_shop_result"))
    _append(working.get("comparison_target_resolution"))
    session_state = state.get("session_state_before") or state.get("session_state")
    if session_state is not None:
        if isinstance(session_state, dict):
            for item in list(session_state.get("last_recommendation_list", []) or []):
                _append(item)
        else:
            for item in list(getattr(session_state, "last_recommendation_list", []) or []):
                _append(item)

    semantic_frame = _to_dict(working.get("semantic_frame"))
    explicit_mentions = [
        str(item).strip()
        for item in (
            semantic_frame.get("merchant_mentions", [])
            or semantic_frame.get("branch_mentions", [])
            or semantic_frame.get("reference_mentions", [])
        )
        if str(item).strip()
    ]
    if explicit_mentions:
        try:
            from ..graph_builder import resolve_shop as _resolve_shop
        except Exception:
            _resolve_shop = None
        if callable(_resolve_shop):
            for mention in explicit_mentions:
                try:
                    resolved = _unwrap_resolve_shop_result(_to_dict(_resolve_shop(mention, location={})))
                except Exception:
                    resolved = {}
                resolved_status = str(resolved.get("status", "") or "").upper()
                if resolved_status == "RESOLVED":
                    _append(resolved.get("shop") or resolved.get("resolved_shop") or {})
                elif resolved_status == "AMBIGUOUS":
                    for candidate in resolved.get("candidates", []) or []:
                        _append(candidate)

    if not collected:
        raw_text = str(state.get("raw_text", "") or "").strip()
        if raw_text:
            stop_tokens = ("有券", "比呢", "比吧", "比", "对比", "比较", "怎么样", "好不好", "吗", "嘛", "呢", "吧")
            prefix = raw_text
            for token in stop_tokens:
                idx = prefix.find(token)
                if 0 < idx < len(prefix):
                    prefix = prefix[:idx]
                    break
            prefix = prefix.strip(" ，,。！？?!~")
            if prefix and prefix != raw_text:
                try:
                    from ..graph_builder import resolve_shop as _resolve_shop
                except Exception:
                    _resolve_shop = None
                if callable(_resolve_shop):
                    try:
                        resolved = _unwrap_resolve_shop_result(_to_dict(_resolve_shop(prefix, location={})))
                    except Exception:
                        resolved = {}
                    resolved_status = str(resolved.get("status", "") or "").upper()
                    if resolved_status == "RESOLVED":
                        _append(resolved.get("shop") or resolved.get("resolved_shop") or {})
                    elif resolved_status == "AMBIGUOUS":
                        for candidate in resolved.get("candidates", []) or []:
                            _append(candidate)

    return collected


def _location_from_state(state: dict[str, Any]) -> dict[str, Any]:
    semantic_frame = normalize_location_payload(state.get("semantic_frame"))
    for item in (
        state.get("location"),
        semantic_frame.get("location"),
        state.get("user_location"),
        state.get("user_context"),
    ):
        location = normalize_location_payload(item)
        if location.get("lat") is not None and location.get("lng") is not None:
            return {
                "lat": location.get("lat"),
                "lng": location.get("lng"),
                "label": str(location.get("label") or location.get("location_name") or ""),
                "raw": str(location.get("raw") or ""),
                "status": str(location.get("status") or ""),
            }
    return {}


def _resolved_shop_location_from_state(state: dict[str, Any]) -> dict[str, Any]:
    for item in (
        state.get("resolved_target"),
        state.get("current_shop"),
        state.get("target_resolution"),
    ):
        item_dict = normalize_location_payload(item)
        shop = _to_dict(item_dict.get("resolved_shop") or item_dict.get("shop") or item_dict.get("current_shop") or item_dict)
        if shop.get("lat") is not None and shop.get("lng") is not None:
            return {
                "lat": shop.get("lat"),
                "lng": shop.get("lng"),
                "label": str(shop.get("shop_name", "") or shop.get("name", "") or ""),
                "raw": str(shop.get("raw") or ""),
                "status": str(shop.get("status") or ""),
            }
    return {}


def _normalize_distance_tool_calls(plan: ExecutionPlan, state: dict[str, Any]) -> ExecutionPlan:
    user_location = _location_from_state(state)
    resolved_location = _resolved_shop_location_from_state(state)
    tool_calls: list[ToolCallSpec] = []
    changed = False

    for call in list(plan.tool_calls or []):
        call_dict = _to_dict(call)
        tool_name = str(call_dict.get("tool_name", "") or "")
        args = _to_dict(call_dict.get("args"))
        if tool_name in {"get_distance_eta", "calculate_distance_km"}:
            origin = _to_dict(args.get("origin") or args.get("from_location") or user_location)
            destination = _to_dict(args.get("destination") or args.get("to_location") or resolved_location)
            call_dict["tool_name"] = "calculate_distance_km"
            call_dict["args"] = {
                "origin": origin or {},
                "destination": destination or {},
                "mode": "straight_line",
            }
            changed = True
        tool_calls.append(ToolCallSpec.model_validate(call_dict))

    if not changed:
        return plan

    plan.tool_calls = tool_calls
    for stage in list(getattr(plan, "stages", []) or []):
        stage_dict = _to_dict(stage)
        stage_dict["tool_names"] = [
            "calculate_distance_km" if str(name or "") == "get_distance_eta" else str(name or "")
            for name in (stage_dict.get("tool_names") or [])
        ]
        if isinstance(stage, dict):
            stage.update(stage_dict)
    return plan


def _looks_like_specific_shop_mention(mention: str) -> bool:
    text = str(mention or "").strip()
    if not text:
        return False
    if any(token in text for token in ("(", "（", ")", "）")):
        return True
    return any(token in text for token in ("店", "馆", "轩", "居", "坊", "楼", "城", "中心", "广场"))


def _raw_text_shop_prefix(raw_text: str) -> str:
    text = str(raw_text or "").strip()
    if not text:
        return ""
    stop_tokens = ("有券", "比呢", "比吧", "比", "对比", "比较", "怎么样", "好不好", "多久能到", "多久到", "多久", "吗", "嘛", "呢", "吧", "想查", "查下", "查一下")
    prefix = text
    for token in stop_tokens:
        idx = prefix.find(token)
        if 0 < idx < len(prefix):
            prefix = prefix[:idx]
            break
    return prefix.strip(" ，,。！？?!~")


def _candidate_set_from_shop_dicts(
    *,
    source: CandidateSource,
    shops: list[dict[str, Any]],
    requested_count: int = 1,
    min_required: int = 1,
    max_allowed: int = 5,
) -> CandidateSet:
    candidates: list[ResolvedCandidate] = []
    seen: set[str] = set()
    for idx, item in enumerate(shops):
        shop = _to_dict(item)
        shop_id = str(shop.get("shop_id", "") or "").strip()
        shop_name = str(shop.get("shop_name", "") or "").strip()
        if not shop_id or shop_id in seen:
            continue
        seen.add(shop_id)
        candidates.append(
            ResolvedCandidate(
                shop_id=shop_id,
                shop_name=shop_name,
                source=source,
                rank=idx,
                confidence=float(shop.get("confidence", 0.9) or 0.9),
                raw=shop,
            )
        )
    status = CandidateStatus.RESOLVED if candidates else CandidateStatus.NOT_FOUND
    return CandidateSet(
        status=status,
        source=source,
        candidates=candidates,
        requested_count=requested_count,
        min_required=min_required,
        max_allowed=max_allowed,
    )


def h_planning_subgraph(state: GraphState) -> dict:
    """Outer wrapper: goal plan → review → target resolve → evidence → plan validate → route."""
    before = dict(state)
    log_kv(_LOGGER, logging.INFO, "[SUBGRAPH_ENTER]", tone="route", subgraph="planning_subgraph", trace_id=state.get("trace_id", ""), top_intent=state.get("top_intent", ""))
    working = _run_steps(state, [_h_goal_planner, _h_goal_review])
    goal_review = working.get("goal_review_result")
    next_action = str(getattr(goal_review, "next_action", "") or _to_dict(goal_review).get("next_action", "") or "")
    if next_action in {"CLARIFY"}:
        after = {**working, "planning_route": _OUTER_ROUTE_CLARIFY, "response_mode": _OUTER_ROUTE_CLARIFY}
        log_kv(_LOGGER, logging.WARNING, "[ROUTE_DECISION]", tone="warn", subgraph="planning_subgraph", route=_OUTER_ROUTE_CLARIFY, response_mode=_OUTER_ROUTE_CLARIFY, next_action=next_action)
        return _state_delta(before, after, always_include={"planning_route", "response_mode"}, exclude=_PLANNING_WRAPPER_EXCLUDE_FIELDS)
    if next_action in {"UNSUPPORTED_ANSWER"}:
        after = {**working, "planning_route": _OUTER_ROUTE_FALLBACK, "response_mode": _OUTER_ROUTE_REJECT}
        log_kv(_LOGGER, logging.WARNING, "[ROUTE_DECISION]", tone="warn", subgraph="planning_subgraph", route=_OUTER_ROUTE_FALLBACK, response_mode=_OUTER_ROUTE_REJECT, next_action=next_action)
        return _state_delta(before, after, always_include={"planning_route", "response_mode"}, exclude=_PLANNING_WRAPPER_EXCLUDE_FIELDS)
    if next_action in {"FALLBACK"}:
        after = {**working, "planning_route": _OUTER_ROUTE_FALLBACK, "response_mode": _OUTER_ROUTE_FALLBACK}
        log_kv(_LOGGER, logging.WARNING, "[ROUTE_DECISION]", tone="warn", subgraph="planning_subgraph", route=_OUTER_ROUTE_FALLBACK, response_mode=_OUTER_ROUTE_FALLBACK, next_action=next_action)
        return _state_delta(before, after, always_include={"planning_route", "response_mode"}, exclude=_PLANNING_WRAPPER_EXCLUDE_FIELDS)

    task_type_value = _enum_value(state.get("task_type")) or _enum_value(_to_dict(working.get("semantic_frame")).get("task_type"))
    semantic_frame = _to_dict(working.get("semantic_frame"))
    prior_current_shop = _to_dict(state.get("current_shop"))
    has_deictic_reference = bool(
        semantic_frame.get("deictic_references")
        or semantic_frame.get("reference_mentions")
        or semantic_frame.get("comparison_targets")
        or semantic_frame.get("ordinal_references")
    )
    working = _run_steps(working, [_h_target_resolve])
    resolve_result = working.get("resolve_shop_result") or working.get("resolved_target")
    resolve_dict = _to_dict(resolve_result)
    comparison_resolution = _to_dict(working.get("comparison_target_resolution"))
    comparison_status = str(comparison_resolution.get("status", "") or "").upper()
    comparison_needs_clarify = task_type_value == TaskType.comparison.value and comparison_status in {"NEED_CLARIFICATION", "NOT_FOUND", "TOO_MANY", "PARTIAL", "AMBIGUOUS"}

    if comparison_needs_clarify:
        pending = working.get("pending_clarification")
        if pending is None:
            candidate_targets = list(working.get("comparison_targets") or [])
            already_resolved_targets = list(candidate_targets)
            unresolved_targets = list(comparison_resolution.get("unresolved_targets") or [])
            explicit_candidates: list[dict[str, Any]] = []
            try:
                from ..graph_builder import resolve_shop as _resolve_shop
            except Exception:
                _resolve_shop = None
            for unresolved in unresolved_targets:
                unresolved_dict = _to_dict(unresolved)
                if str(unresolved_dict.get("reference", "") or "").strip() != "explicit":
                    continue
                query = str(unresolved_dict.get("query", "") or unresolved_dict.get("source_ref", "") or "").strip()
                if not query or _resolve_shop is None:
                    continue
                try:
                    resolved = _unwrap_resolve_shop_result(_to_dict(_resolve_shop(query, location={})))
                except Exception:
                    resolved = {}
                resolved_dict = _to_dict(resolved)
                resolved_status = str(resolved_dict.get("status", "") or "").upper()
                if resolved_status == "AMBIGUOUS":
                    for candidate in resolved_dict.get("candidates", []) or []:
                        candidate_dict = _candidate_shop_dict(candidate)
                        if candidate_dict.get("shop_id") or candidate_dict.get("shop_name"):
                            explicit_candidates.append(candidate_dict)
                elif resolved_status == "RESOLVED":
                    shop = resolved_dict.get("shop") or resolved_dict.get("resolved_shop") or {}
                    shop_dict = _to_dict(shop)
                    if shop_dict.get("shop_id") or shop_dict.get("shop_name"):
                        explicit_candidates.append(shop_dict)
            if explicit_candidates:
                candidate_targets = explicit_candidates
                resolved_target_ids = {
                    str(item.get("shop_id", "") or "").strip()
                    for item in explicit_candidates
                    if str(item.get("shop_id", "") or "").strip()
                }
                resolved_target_names = {
                    str(item.get("shop_name", "") or "").strip()
                    for item in explicit_candidates
                    if str(item.get("shop_name", "") or "").strip()
                }
                already_resolved_targets = [
                    _to_dict(item)
                    for item in list(comparison_resolution.get("targets") or working.get("comparison_targets") or [])
                    if str(_to_dict(item).get("shop_id", "") or "").strip() not in resolved_target_ids
                    and str(_to_dict(item).get("shop_name", "") or "").strip() not in resolved_target_names
                ]
            if not candidate_targets:
                session_state = state.get("session_state_before") or state.get("session_state")
                if session_state is not None:
                    if isinstance(session_state, dict):
                        candidate_targets = list(session_state.get("last_recommendation_list", []) or [])
                    else:
                        candidate_targets = list(getattr(session_state, "last_recommendation_list", []) or [])
                already_resolved_targets = list(candidate_targets)
            if candidate_targets:
                original_semantic_frame = _to_dict(working.get("semantic_frame"))
                if not original_semantic_frame and working.get("semantic_frame") is not None:
                    original_semantic_frame = _session_state_dict(working.get("semantic_frame"))
                pending = build_pending_clarification(
                    original_text=str(state.get("raw_text", "") or ""),
                    original_semantic_frame=original_semantic_frame,
                    original_task_type=task_type_value or TaskType.comparison.value,
                    candidate_targets=[_to_dict(item) for item in candidate_targets],
                    reason=str(comparison_resolution.get("reason", "") or "comparison_targets_need_clarification"),
                    source_node="planning_subgraph",
                    already_resolved_targets=[_to_dict(item) for item in already_resolved_targets],
                )
        if comparison_status == "RESOLVED":
            working = {
                **working,
                "comparison_targets": list(comparison_resolution.get("targets") or working.get("comparison_targets") or []),
                "pending_clarification": None,
            }
        after = {
            **working,
            "pending_clarification": pending,
            "planning_route": _OUTER_ROUTE_CLARIFY,
            "response_mode": _OUTER_ROUTE_CLARIFY,
        }
        log_kv(
            _LOGGER,
            logging.WARNING,
            "[ROUTE_DECISION]",
            tone="warn",
            subgraph="planning_subgraph",
            route=_OUTER_ROUTE_CLARIFY,
            response_mode=_OUTER_ROUTE_CLARIFY,
            resolve_status=comparison_status or resolve_dict.get("status", ""),
            reason="comparison_target_needs_clarification",
        )
        return _state_delta(before, after, always_include={"planning_route", "response_mode", "pending_clarification"}, exclude=_PLANNING_WRAPPER_EXCLUDE_FIELDS)

    if (
        task_type_value in {TaskType.single_shop_query.value, TaskType.coupon_query.value}
        and has_deictic_reference
        and not prior_current_shop.get("shop_id")
        and not prior_current_shop.get("shop_name")
    ):
        clarification_candidates = _collect_clarification_candidates(state, working)
        if clarification_candidates:
            pending = build_pending_clarification(
                original_text=str(state.get("raw_text", "") or ""),
                original_semantic_frame=semantic_frame,
                original_task_type=task_type_value or TaskType.single_shop_query.value,
                candidate_targets=clarification_candidates,
                reason="deictic_reference_missing_current_shop",
                source_node="planning_subgraph",
            )
            after = {
                **working,
                "pending_clarification": pending,
                "planning_route": _OUTER_ROUTE_CLARIFY,
                "response_mode": _OUTER_ROUTE_CLARIFY,
                "final_response": format_pending_prompt(pending),
            }
            log_kv(
                _LOGGER,
                logging.WARNING,
                "[ROUTE_DECISION]",
                tone="warn",
                subgraph="planning_subgraph",
                route=_OUTER_ROUTE_CLARIFY,
                response_mode=_OUTER_ROUTE_CLARIFY,
                resolve_status=resolve_dict.get("status", ""),
                reason="deictic_reference_missing_current_shop",
            )
            return _state_delta(
                before,
                after,
                always_include={"planning_route", "response_mode", "final_response", "pending_clarification"},
                exclude=_PLANNING_WRAPPER_EXCLUDE_FIELDS,
            )
        after = {
            **working,
            "planning_route": _OUTER_ROUTE_CLARIFY,
            "response_mode": _OUTER_ROUTE_CLARIFY,
            "final_response": "店名有点模糊，请提供完整店名。",
        }
        log_kv(
            _LOGGER,
            logging.WARNING,
            "[ROUTE_DECISION]",
            tone="warn",
            subgraph="planning_subgraph",
            route=_OUTER_ROUTE_CLARIFY,
            response_mode=_OUTER_ROUTE_CLARIFY,
            resolve_status=resolve_dict.get("status", ""),
            reason="deictic_reference_missing_current_shop",
        )
        return _state_delta(
            before,
            after,
            always_include={"planning_route", "response_mode", "final_response"},
            exclude=_PLANNING_WRAPPER_EXCLUDE_FIELDS,
        )

    if working.get("pending_clarification") is not None:
        working = _run_steps(working, [_h_clarify_decide])
        pending_after = _to_dict(working.get("pending_clarification"))
        pending_reason = str(
            pending_after.get("reason", "")
            or pending_after.get("workflow_reason", "")
            or pending_after.get("pending_reason", "")
            or ""
        ).lower()
        if task_type_value == TaskType.comparison.value and (
            (has_deictic_reference and not prior_current_shop.get("shop_id") and not prior_current_shop.get("shop_name"))
            or "deictic" in pending_reason
            or "current_shop" in pending_reason
        ):
            clarification_text = "请提供完整店名，或回复编号/店名。"
            after = {
                **working,
                "pending_clarification": working.get("pending_clarification"),
                "planning_route": _OUTER_ROUTE_CLARIFY,
                "response_mode": _OUTER_ROUTE_CLARIFY,
                "final_response": clarification_text,
            }
            log_kv(
                _LOGGER,
                logging.WARNING,
                "[ROUTE_DECISION]",
                tone="warn",
                subgraph="planning_subgraph",
                route=_OUTER_ROUTE_CLARIFY,
                response_mode=_OUTER_ROUTE_CLARIFY,
                resolve_status=comparison_status or resolve_dict.get("status", ""),
                reason="comparison_deictic_missing_current_shop",
            )
            return _state_delta(
                before,
                after,
                always_include={"planning_route", "response_mode", "final_response", "pending_clarification"},
                exclude=_PLANNING_WRAPPER_EXCLUDE_FIELDS,
            )
        if task_type_value in {TaskType.recommendation.value, TaskType.comparison.value}:
            working = {
                **working,
                "pending_clarification": None,
            }
        else:
            after = {
                **working,
                "planning_route": _OUTER_ROUTE_CLARIFY,
                "response_mode": _OUTER_ROUTE_CLARIFY,
            }
            log_kv(_LOGGER, logging.WARNING, "[ROUTE_DECISION]", tone="warn", subgraph="planning_subgraph", route=_OUTER_ROUTE_CLARIFY, response_mode=_OUTER_ROUTE_CLARIFY, resolve_status=resolve_dict.get("status", ""), reason="pending_clarification_from_target_resolve")
            return _state_delta(before, after, always_include={"planning_route", "response_mode"}, exclude=_PLANNING_WRAPPER_EXCLUDE_FIELDS)

    # Build execution plan regardless of target_resolve outcome.
    # recommendation/discovery queries with 0 candidates still need
    # a search plan; ambiguous shop references also go through tool
    # execution rather than short-circuiting to clarify.
    working = _run_steps(working, [_h_evidence_planner, _h_plan_validator])
    if working.get("error_code"):
        fallback_route = _planning_failure_route(working)
        after = {**working, "planning_route": fallback_route, "response_mode": fallback_route}
        log_kv(_LOGGER, logging.WARNING, "[ROUTE_DECISION]", tone="warn", subgraph="planning_subgraph", route=fallback_route, response_mode=fallback_route, error_code=working.get("error_code", ""), failed_stage=working.get("failed_stage", ""))
        return _state_delta(before, after, always_include={"planning_route", "response_mode"}, exclude=_PLANNING_WRAPPER_EXCLUDE_FIELDS)

    if resolve_dict.get("status") == "RESOLVED":
        after = {**working, "planning_route": _OUTER_ROUTE_EXECUTE, "response_mode": "answer"}
        log_kv(_LOGGER, logging.INFO, "[ROUTE_DECISION]", tone="route", subgraph="planning_subgraph", route=_OUTER_ROUTE_EXECUTE, response_mode="answer", resolve_status="RESOLVED")
        return _state_delta(before, after, always_include={"planning_route", "response_mode"}, exclude=_PLANNING_WRAPPER_EXCLUDE_FIELDS)

    if task_type_value == TaskType.single_shop_query.value:
        current_shop = _to_dict(working.get("current_shop") or state.get("current_shop"))
        if not current_shop.get("shop_id") and not current_shop.get("shop_name"):
            after = {
                **working,
                "planning_route": _OUTER_ROUTE_CLARIFY,
                "response_mode": _OUTER_ROUTE_CLARIFY,
            }
            log_kv(
                _LOGGER,
                logging.WARNING,
                "[ROUTE_DECISION]",
                tone="warn",
                subgraph="planning_subgraph",
                route=_OUTER_ROUTE_CLARIFY,
                response_mode=_OUTER_ROUTE_CLARIFY,
                resolve_status=resolve_dict.get("status", ""),
                reason="single_shop_query_missing_current_shop",
            )
            return _state_delta(
                before,
                after,
                always_include={"planning_route", "response_mode"},
                exclude=_PLANNING_WRAPPER_EXCLUDE_FIELDS,
            )

    # Not RESOLVED — clear pending_clarification so response_subgraph
    # Let Execute → Evidence Review → LLM Answer handle insufficient/ambiguous results naturally.
    after = {
        **working,
        "planning_route": _OUTER_ROUTE_EXECUTE,
        "response_mode": "answer",
        "pending_clarification": None,
        "final_response": "",
    }
    log_kv(_LOGGER, logging.INFO, "[ROUTE_DECISION]", tone="route", subgraph="planning_subgraph", route=_OUTER_ROUTE_EXECUTE, response_mode="answer", resolve_status=resolve_dict.get("status", ""))
    return _state_delta(before, after, always_include={
        "planning_route", "response_mode", "pending_clarification", "final_response",
    }, exclude=_PLANNING_WRAPPER_EXCLUDE_FIELDS)


# ---------------------------------------------------------------------------
# Internal step handlers
# ---------------------------------------------------------------------------


def _h_goal_planner(state: GraphState) -> dict:
    """P2 GoalPlanner: generate a structured GoalPlan from the semantic frame."""
    sf = state.get("semantic_frame")
    session = state.get("session_state_before") or state.get("session_state")
    raw_text = str(state.get("raw_text", "") or "")
    from ..graph_builder import call_llm as _call_llm, get_llm_backend_snapshot as _get_llm_backend_snapshot
    backend_snapshot = _get_llm_backend_snapshot()
    strict_llm = str(backend_snapshot.get("backend_kind", "") or "") not in {"", "fake_llm", "fake"}
    plan, meta = _PLANNING_CORE.plan_goal_with_llm(sf, session, raw_text, llm_call=_call_llm, strict=strict_llm)
    if plan is None:
        result = {
            "goal_plan": None,
            "goal_plan_source": "",
            "planning_llm_backend": meta.get("llm_backend", ""),
            "planning_llm_called": True,
            "planning_failure_code": meta.get("error_code", "GOAL_PLANNER_FAILED"),
            "error_code": meta.get("error_code", "GOAL_PLANNER_FAILED"),
            "error_message": meta.get("error_message", "goal planner llm failed"),
            **_log(state, "goal_planner", status="failed", reason=meta.get("error_code", "GOAL_PLANNER_FAILED")),
        }
        return result
    # ── Backfill task_type ← goal_type (included in result, not mutating state) ──
    goal_type_from_plan = str(getattr(plan, "goal_type", "") or "")
    # ──────────────────────────────────────────────────────────────────────────────
    result: dict[str, Any] = {
        "goal_plan": plan,
        "facet_set": normalize_query_facets(sf, session_state=session, raw_text=raw_text),
        "facets": list(getattr(plan, "facets", []) or []),
        "target_resolution": getattr(plan, "target_resolution", None),
        "conflicting_facets": list(getattr(plan, "conflicting_facets", []) or []),
        "ranking_policy": getattr(plan, "ranking_policy", None),
        "task_type": goal_type_from_plan if (goal_type_from_plan and not state.get("task_type")) else state.get("task_type", ""),
        "goal_plan_source": plan.planner_source or plan.source_origin or "llm_goal_planner",
        "planning_llm_backend": meta.get("llm_backend", ""),
        "planning_llm_called": True,
        "planning_failure_code": "",
        **_log(state, "goal_planner",
              goal_type=plan.goal_type, candidate_source=plan.candidate_source,
              unsupported=plan.unsupported, planner_source=plan.planner_source or "llm_goal_planner"),
    }
    ss = _session_store_state(state)
    ss.active_goal = plan.model_dump()
    result["session_state"] = ss
    return result


def _h_goal_review(state: GraphState) -> dict:
    """P2 GoalReview: check if the goal is clear, executable, and supported."""
    from ...planning.goal.goal_review import review_goal as p2_review_goal
    from ...domain.goal import goal_plan_to_draft, GoalReviewResult

    gp = state.get("goal_plan")
    raw_text = str(state.get("raw_text", "") or "")
    session = state.get("session_state_before") or state.get("session_state")
    if gp is None:
        return {
            "goal_review_result": GoalReviewResult(
                status="unsupported", next_action="UNSUPPORTED_ANSWER", reason="no_goal_plan_produced",
            ),
            **_log(state, "goal_review", status="unsupported", reason="no_goal_plan"),
        }
    review = p2_review_goal(gp, raw_text, session)
    result: dict[str, Any] = {"goal_review_result": review}
    if review.next_action == "FINISH":
        draft = goal_plan_to_draft(gp)
        result["local_life_goal_draft"] = draft
        result["candidate_source_origin"] = gp.candidate_source
    ss = _session_store_state(state)
    rr = dict(ss.review_results or {})
    rr["goal_review"] = review
    ss.review_results = rr
    result["session_state"] = ss
    return {
        **result,
        **_log(state, "goal_review", status=review.status, next_action=review.next_action, reason=review.reason),
    }


def _h_target_resolve(state: GraphState) -> dict:
    sf = state.get("semantic_frame")
    return _h_target_resolve_candidate_set(state, sf)


def _h_target_resolve_candidate_set(state: GraphState, sf: Any) -> dict:
    """CandidateSet resolution path — builds goal → spec → resolver → review → route."""
    session_snapshot = state.get("session_state_before") or state.get("session_state") or SessionState()
    if hasattr(session_snapshot, "model_copy"):
        session_snapshot = session_snapshot.model_copy(deep=True)

    sf_dict = _to_dict(sf)
    if str(state.get("error_code", "") or "") == "SCHEMA_VALIDATION_FAILED" or sf_dict.get("shop_id") or sf_dict.get("tool_name"):
        return {
            "resolve_shop_result": ResolveShopResult(status="NOT_FOUND", confidence=0.0, reason="schema_validation_failed"),
            "target_resolution_status": "NOT_FOUND",
            "session_state_after": session_snapshot,
            **_log(state, "target_resolve", status="NOT_FOUND", reason="schema_validation_failed"),
        }
    target_resolution_seed = build_target_resolution_result(
        sf_dict,
        session_state=session_snapshot,
        raw_text=str(state.get("raw_text", "") or ""),
    )

    pre_resolved_target = state.get("resolved_target")
    if pre_resolved_target is not None:
        resolved_dict = _to_dict(pre_resolved_target)
        if resolved_dict.get("status") == "RESOLVED":
            resolved_shop = _to_dict(resolved_dict.get("resolved_shop") or resolved_dict.get("shop") or {})
            candidate = ResolvedCandidate(
                shop_id=str(resolved_shop.get("shop_id", "") or "").strip(),
                shop_name=str(resolved_shop.get("shop_name", "") or "").strip(),
                source=CandidateSource.CONTEXT,
                confidence=float(resolved_dict.get("confidence", 1.0) or 1.0),
                raw=resolved_shop,
            )
            candidate_set = CandidateSet(
                status=CandidateStatus.RESOLVED, source=CandidateSource.CONTEXT,
                candidates=[candidate], requested_count=1, min_required=1, max_allowed=1,
            )
            result = {
                "resolve_shop_result": pre_resolved_target,
                "resolved_target": pre_resolved_target,
                "target_resolution_status": "RESOLVED",
                "session_state_after": session_snapshot,
                "candidate_set": candidate_set,
                "effective_candidate_set": candidate_set,
                "recommendation_candidates": [candidate.model_dump()],
                "review_results": {
                    "candidate_review": {
                        "stage": "candidate_review", "status": "enough",
                        "next_action": "FINISH", "reason": "resolved_target_short_circuit",
                    }
                },
                "reference_resolution_source": str(state.get("reference_resolution_source") or "context_recovered"),
                **_log(state, "target_resolve", status="RESOLVED", target_resolve_mode="resolved_target",
                      candidate_source=str(state.get("candidate_source_origin") or "context"),
                      candidate_count=1, candidate_review_status="resolved_target",
                      candidate_review_next_action="FINISH", next_action="FINISH"),
            }
            return result

    task_type_value = _enum_value(state.get("task_type")) or _enum_value(sf_dict.get("task_type"))
    current_shop = _to_dict(state.get("current_shop"))
    user_location = _user_location(state)
    canonical_shop_entity: dict[str, Any] | None = None
    canonical_shop_entities: list[dict[str, Any]] = []
    shop_resolution_trace: list[dict[str, Any]] = []
    comparison_target_resolution: dict[str, Any] | None = None
    canonical_specific_shop_hint = False
    canonical_mention = ""

    def _resolve_mentions_for_canonical() -> None:
        nonlocal canonical_shop_entity, canonical_shop_entities, shop_resolution_trace, comparison_target_resolution, canonical_specific_shop_hint, canonical_mention
        if task_type_value == TaskType.comparison.value:
            comparison_target_resolution = _to_dict(
                resolve_comparison_targets(
                    str(state.get("raw_text", "") or ""),
                    session_snapshot,
                    sf_dict,
                )
            )
            resolved_targets = [
                _to_dict(item)
                for item in (comparison_target_resolution.get("targets") or [])
                if str(_to_dict(item).get("shop_id", "") or "").strip() or str(_to_dict(item).get("shop_name", "") or "").strip()
            ]
            if resolved_targets:
                comparison_target_resolution["targets"] = resolved_targets
                canonical_shop_entities = [
                    {
                        "shop_id": str(item.get("shop_id", "") or "").strip(),
                        "shop_name": str(item.get("shop_name", "") or "").strip(),
                    }
                    for item in resolved_targets
                    if str(item.get("shop_id", "") or "").strip() or str(item.get("shop_name", "") or "").strip()
                ]
                shop_resolution_trace = [
                    {
                        "source": "comparison_target_resolution",
                        "shop_id": item.get("shop_id", ""),
                        "shop_name": item.get("shop_name", ""),
                    }
                    for item in resolved_targets
                ]
            elif str(comparison_target_resolution.get("status", "") or "").upper() == "NOT_FOUND":
                comparison_target_resolution = {
                    "status": "NOT_FOUND",
                    "targets": [],
                    "unresolved_targets": [],
                    "reason": "comparison_targets_missing",
                }
            return

        if task_type_value == TaskType.recommendation.value:
            has_explicit_grounding_hint = any(
                _to_dict(sf_dict.get(key))
                for key in ("current_shop", "comparison_targets")
            ) or any(
                str(item).strip()
                for item in (
                    sf_dict.get("merchant_mentions", [])
                    or sf_dict.get("branch_mentions", [])
                    or sf_dict.get("reference_mentions", [])
                    or sf_dict.get("ordinal_references", [])
                    or sf_dict.get("deictic_references", [])
                )
            )
            if not has_explicit_grounding_hint:
                return

        merchant_mentions = [str(item).strip() for item in (sf_dict.get("merchant_mentions", []) or []) if str(item).strip()]
        branch_mentions = [str(item).strip() for item in (sf_dict.get("branch_mentions", []) or []) if str(item).strip()]
        reference_mentions = [str(item).strip() for item in (sf_dict.get("reference_mentions", []) or []) if str(item).strip()]
        shop_target = _to_dict(sf_dict.get("shop_target"))
        shop_target_name = str(shop_target.get("shop_name", "") or "").strip()
        if shop_target_name and shop_target_name not in merchant_mentions:
            merchant_mentions = [shop_target_name] + merchant_mentions
        raw_text_prefix = _raw_text_shop_prefix(str(state.get("raw_text", "") or state.get("normalized_text", "") or ""))
        mention = raw_text_prefix
        if not mention:
            for item in merchant_mentions:
                if _looks_like_specific_shop_mention(item):
                    mention = item
                    break
        if not mention and merchant_mentions and branch_mentions:
            for merchant in merchant_mentions:
                merchant = str(merchant).strip()
                if not merchant:
                    continue
                if _looks_like_specific_shop_mention(merchant):
                    mention = merchant
                    break
                for branch in branch_mentions:
                    branch = str(branch).strip()
                    if branch:
                        mention = f"{merchant}({branch})"
                        break
                if mention:
                    break
        if not mention and merchant_mentions:
            mention = merchant_mentions[0]
        if not mention:
            for item in branch_mentions + reference_mentions + merchant_mentions:
                if item:
                    mention = item
                    break
        if not mention:
            text = str(state.get("raw_text", "") or state.get("normalized_text", "") or "").strip()
            mention = text[:40]
        canonical_specific_shop_hint = _looks_like_specific_shop_mention(mention)
        canonical_mention = mention
        result = resolve_shop_entity(
            mention,
            session_state=session_snapshot,
            current_shop=current_shop,
            user_location=user_location,
            semantic_frame=sf_dict,
        )
        canonical_shop_entity = result.model_dump()
        shop_resolution_trace = list(result.trace or [])

    should_skip_grounding = False
    if task_type_value == TaskType.recommendation.value:
        has_grounding_hint = any(
            str(item).strip()
            for item in (
                sf_dict.get("merchant_mentions", [])
                or sf_dict.get("branch_mentions", [])
                or sf_dict.get("reference_mentions", [])
                or sf_dict.get("ordinal_references", [])
                or sf_dict.get("deictic_references", [])
            )
        ) or bool(_to_dict(sf_dict.get("current_shop"))) or bool(sf_dict.get("comparison_targets"))
        should_skip_grounding = not has_grounding_hint
    if not should_skip_grounding:
        _resolve_mentions_for_canonical()

    if task_type_value in {TaskType.single_shop_query.value, TaskType.coupon_query.value}:
        canonical_status = _enum_value((canonical_shop_entity or {}).get("status")).lower()
        if canonical_status == "ambiguous" or (canonical_status in {"low_confidence", "not_found", "no_mention"} and not canonical_specific_shop_hint):
            canonical_result = ShopResolutionResult.model_validate(canonical_shop_entity)
            if not list(canonical_result.candidates or []):
                import sys

                _graph_builder = sys.modules.get("local_life_agent.engine.graph_builder")
                if _graph_builder is None:
                    try:
                        from .. import graph_builder as _graph_builder  # type: ignore[no-redef]
                    except Exception:
                        _graph_builder = None
                _resolve_shop = getattr(_graph_builder, "resolve_shop", None) if _graph_builder is not None else None
                mention = canonical_mention
                if callable(_resolve_shop) and mention:
                    try:
                        legacy_raw = _unwrap_resolve_shop_result(_to_dict(_resolve_shop(mention, location={})))
                    except Exception:
                        legacy_raw = {}
                    legacy_status = str(legacy_raw.get("status", "") or "").upper()
                    if legacy_status in {"RESOLVED", "AMBIGUOUS"}:
                        candidate_rows = [
                            _candidate_shop_dict(candidate)
                            for candidate in (legacy_raw.get("candidates") or [])
                            if _candidate_shop_dict(candidate)
                        ]
                        if candidate_rows:
                            canonical_result.candidates = [
                                ShopCandidate(
                                    shop_id=str(item.get("shop_id", "") or "").strip(),
                                    shop_name=str(item.get("shop_name", "") or "").strip(),
                                    canonical_name=str(item.get("canonical_name", "") or "").strip(),
                                    branch_name=str(item.get("branch_name", "") or "").strip(),
                                    alias=list(item.get("alias", []) or []),
                                    score=float(item.get("score", 0.0) or 0.0),
                                    source=ShopResolutionSource.reference,
                                    match_reason=str(item.get("match_reason", "") or "legacy_resolve_shop"),
                                    raw=dict(item),
                                )
                                for item in candidate_rows
                                if str(item.get("shop_id", "") or "").strip() or str(item.get("shop_name", "") or "").strip()
                            ]
            legacy_result = ResolveShopResult(
                status=canonical_result.status.value.upper() if hasattr(canonical_result.status, "value") else str(canonical_result.status).upper(),
                resolved_shop=ShopRef(shop_id=str(canonical_result.shop_id or ""), shop_name=str(canonical_result.shop_name or "")) if canonical_result.status == ShopResolutionStatus.resolved else None,
                candidates=[
                    ShopCandidate(
                        shop=ShopRef(shop_id=item.shop_id, shop_name=item.shop_name),
                        match_score=float(item.score or 0.0),
                    )
                    for item in (canonical_result.candidates or [])
                    if item.shop_id or item.shop_name
                ],
                confidence=float(canonical_result.confidence or 0.0),
                reason=str(canonical_result.resolution_reason or canonical_status or "shop_resolution_need_clarification"),
            )
            pending = build_pending_clarification(
                original_text=str(state.get("raw_text", "") or ""),
                original_semantic_frame=sf_dict,
                original_task_type=task_type_value,
                candidate_targets=[
                    {
                        "shop_id": item.shop_id,
                        "shop_name": item.shop_name,
                        "address": _to_dict(getattr(item, "raw", {})).get("address", ""),
                    }
                    for item in (canonical_result.candidates or [])
                    if item.shop_id or item.shop_name
                ],
                reason=str(canonical_result.resolution_reason or canonical_status or "shop_resolution_need_clarification"),
                source_node="target_resolve",
            )
            payload = {
                "canonical_shop_entity": canonical_shop_entity,
                "canonical_shop_entities": canonical_shop_entities,
                "shop_resolution_trace": shop_resolution_trace,
                "resolve_shop_result": legacy_result,
                "pending_clarification": pending,
                "resolved_target": legacy_result if canonical_result.status == ShopResolutionStatus.resolved else None,
                "target_resolution_status": canonical_result.status.value if hasattr(canonical_result.status, "value") else str(canonical_result.status),
                "final_response": format_pending_prompt(pending),
                "session_state_after": session_snapshot,
                "comparison_target_resolution": comparison_target_resolution,
                **_log(state, "target_resolve", status=str(canonical_result.status).upper(), reason=canonical_result.resolution_reason or canonical_status),
            }
            return payload

    # 1. Get goal draft
    goal = state.get("local_life_goal_draft")
    if goal is None:
        goal = build_local_life_goal_draft(sf, state)
    if goal is None or (hasattr(goal, "goal_type") and (goal.goal_type is None or goal.goal_type.value == "unsupported")):
        contextual_follow_up = build_contextual_follow_up(
            semantic_frame=sf or {},
            session_state=state,
            raw_text=str(state.get("raw_text", "") or ""),
        )
        if contextual_follow_up is not None and contextual_follow_up.kind == "recommendation_refine":
            if list(state.get("last_recommendation_list", []) or []):
                goal = LocalLifeGoalDraft(
                    goal_type=GoalType.RECOMMENDATION,
                    candidate_source=CandidateSource.CONTEXT,
                    source_origin="fallback_follow_up",
                )
    if goal is None or (hasattr(goal, "goal_type") and (goal.goal_type is None or goal.goal_type.value == "unsupported")):
        return {
            "resolve_shop_result": ResolveShopResult(status="NOT_FOUND", confidence=0.0, reason="missing_goal_draft"),
            "target_resolution_status": "NOT_FOUND",
            "final_response": "暂时无法确认目标店铺，请补充更明确的店名或筛选条件。",
            "session_state_after": session_snapshot,
            **_log(state, "target_resolve", status="NOT_FOUND", reason="missing_goal_draft"),
        }

    # Comparison follow-ups can carry ordinal references plus an explicit
    # facet request such as "第二家有券吗". Keep that evidence signal alive
    # only when we already have comparison context in session/state.
    if (
        hasattr(goal, "goal_type")
        and goal.goal_type == GoalType.SINGLE_SHOP_QUERY
        and (
            bool(state.get("comparison_result"))
            or bool(state.get("comparison_targets"))
            or bool(_session_store_state(state).comparison_result)
            or bool(_session_store_state(state).comparison_targets)
        )
    ):
        raw_text = str(state.get("raw_text", "") or state.get("normalized_text", "") or "")
        facet_tokens: list[tuple[str, tuple[str, ...]]] = [
            ("coupon", ("有券", "优惠券", "coupon", "团购", "套餐")),
            ("open_status", ("营业", "开门", "open")),
            ("distance", ("距离", "多远", "多久", "eta")),
            ("review_summary", ("评价", "口碑", "review")),
            ("price", ("价格", "多少钱", "人均", "price")),
        ]
        inferred_facet = ""
        for facet_name, tokens in facet_tokens:
            if any(token in raw_text for token in tokens):
                inferred_facet = facet_name
                break
        if inferred_facet:
            session_state = _session_store_state(state)
            existing_facets = {str(item) for item in (getattr(goal, "required_facets", []) or [])}
            existing_facets.update(str(item) for item in (getattr(goal, "optional_facets", []) or []))
            existing_facets.update(str(item) for item in (getattr(goal, "evidence_needs", []) or []))
            if inferred_facet not in existing_facets:
                goal.evidence_needs = list(getattr(goal, "evidence_needs", []) or []) + [inferred_facet]
                if inferred_facet == "coupon":
                    goal.required_facets = list(getattr(goal, "required_facets", []) or [])
                    if inferred_facet not in goal.required_facets:
                        goal.required_facets.append(inferred_facet)
                else:
                    goal.optional_facets = list(getattr(goal, "optional_facets", []) or [])
                    if inferred_facet not in goal.optional_facets:
                        goal.optional_facets.append(inferred_facet)

    # 2. Build candidate spec
    spec = build_candidate_spec(goal, sf, state)

    goal_type_value = str(getattr(goal.goal_type, "value", goal.goal_type) or "")
    candidate_core = _get_candidate_core()
    candidate_set = candidate_core.resolve(goal, spec, state)
    candidate_set.requested_count = goal.requested_count
    candidate_set.min_required = goal.min_required
    candidate_set.max_allowed = goal.max_allowed

    # 4. Review candidates
    review = review_candidate_set(goal, candidate_set)

    # 5. Build state update payload
    payload: dict[str, Any] = {
        "local_life_goal_draft": goal,
        "candidate_spec": spec,
        "target_resolution": target_resolution_seed,
        "target_resolution_status": str(target_resolution_seed.status or "").upper(),
        "candidate_set": candidate_set,
        "effective_candidate_set": candidate_set,
        "canonical_shop_entity": canonical_shop_entity,
        "canonical_shop_entities": canonical_shop_entities,
        "shop_resolution_trace": shop_resolution_trace,
        "comparison_target_resolution": comparison_target_resolution,
        "recommendation_candidates": [
            c.model_dump() if hasattr(c, "model_dump") else _to_dict(c)
            for c in (candidate_set.candidates or [])
        ],
        "review_results": {"candidate_review": review},
        # Propagate comparison_targets from context_recovery through to evidence/state
        "comparison_targets": [
            _to_dict(item)
            for item in (
                (comparison_target_resolution or {}).get("targets")
                or state.get("comparison_targets", [])
                or []
            )
        ],
    }
    if goal.goal_type == GoalType.COMPARISON:
        comparison_rows = [
            {
                "shop_id": str(item.get("shop_id", "") or "").strip(),
                "shop_name": str(item.get("shop_name", "") or "").strip(),
            }
            for item in payload.get("comparison_targets", [])
            if str(item.get("shop_id", "") or "").strip() or str(item.get("shop_name", "") or "").strip()
        ]
        if comparison_rows and not payload.get("comparison_result"):
            payload["comparison_result"] = {"rows": comparison_rows}

    # P2: persist last_candidate_set/spec for multi-turn references
    ss = _session_store_state(state)
    ss.last_candidate_set = [
        c.model_dump() if hasattr(c, "model_dump") else dict(c)
        for c in (candidate_set.candidates or [])
    ]
    ss.last_candidate_spec = (
        spec.model_dump() if hasattr(spec, "model_dump") else _to_dict(spec)
    )
    payload["session_state"] = ss

    candidate_count = len(candidate_set.candidates or [])
    canonical_status = _enum_value((canonical_shop_entity or {}).get("status")).lower()
    if (
        goal.goal_type == GoalType.SINGLE_SHOP_QUERY
        and candidate_count > 1
        and candidate_set.source in {CandidateSource.EXPLICIT, CandidateSource.DISCOVERY, CandidateSource.MIXED}
        and canonical_status != ShopResolutionStatus.resolved.value
    ):
        reason = review.reason or "single_shop_query_multiple_candidates"
        ambiguous_candidates = [
            ShopCandidate(
                shop=ShopRef(shop_id=c.shop_id, shop_name=c.shop_name),
                match_score=float(getattr(c, "confidence", 0.0) or 0.0),
            )
            for c in (candidate_set.candidates or [])
        ]
        resolved = ResolveShopResult(
            status="AMBIGUOUS",
            candidates=ambiguous_candidates,
            confidence=0.0,
            reason=reason,
        )
        pending = build_pending_clarification(
            original_text=str(state.get("raw_text", "") or ""),
            original_semantic_frame=sf.model_dump(mode="json") if hasattr(sf, "model_dump") else _session_state_dict(sf),
            original_task_type=getattr(sf, "task_type", "") or state.get("task_type", ""),
            candidate_targets=_pending_candidate_targets(candidate_set),
            reason=reason,
            source_node="target_resolve",
        )
        payload["resolve_shop_result"] = resolved
        payload["pending_clarification"] = pending
        payload["target_resolution_status"] = "AMBIGUOUS"
        payload["final_response"] = format_pending_prompt(pending)
        payload["session_state_after"] = session_snapshot
        payload["review_results"] = {"candidate_review": review}
        payload.update(_log(state, "target_resolve", status="NEED_CLARIFICATION", target_resolve_mode="candidate_set",
                           candidate_source=candidate_set.source.value,
                           candidate_count=candidate_count,
                           candidate_review_status=str(review.status),
                           candidate_review_next_action=str(review.next_action),
                           next_action="CLARIFY", reason=reason))
        return payload

    # 6. Route based on next_action
    if review.next_action == NextAction.FINISH:
        candidates = list(candidate_set.candidates or [])
        goal_type = getattr(goal, "goal_type", None)
        goal_type_value = goal_type.value if goal_type else ""
        is_multi_candidate = len(candidates) > 1

        if candidates:
            first = candidates[0]
            # RECOMMENDATION/COMPARISON 多候选 → candidate_set_resolved（有候选集，无单一目标）
            # SINGLE_SHOP_QUERY 多候选（如序数引用"第一家"）→ 仍设 resolved_target
            needs_single_target = goal_type_value == GoalType.SINGLE_SHOP_QUERY.value
            if is_multi_candidate and not needs_single_target:
                resolution_stage = ResolutionStage.CANDIDATE_SET_RESOLVED
                # Mulit-candidate: ResolveShopResult with representative shop (NOT winner)
                resolved = ResolveShopResult(
                    status="RESOLVED",
                    resolved_shop=ShopRef(shop_id=first.shop_id, shop_name=first.shop_name),
                    confidence=1.0,
                    reason=f"candidate_set_{candidate_set.source.value}_multi",
                )
                payload["resolve_shop_result"] = resolved
                # Do NOT set resolved_target — no single target was resolved
                payload["target_resolution_status"] = "CANDIDATE_SET_RESOLVED"
                payload["resolution_stage"] = resolution_stage.value
                log_status = "CANDIDATE_SET_RESOLVED"
            else:
                resolution_stage = ResolutionStage.TARGET_RESOLVED
                resolved = ResolveShopResult(
                    status="RESOLVED",
                    resolved_shop=ShopRef(shop_id=first.shop_id, shop_name=first.shop_name),
                    confidence=1.0,
                    reason=f"candidate_set_{candidate_set.source.value}",
                )
                payload["resolve_shop_result"] = resolved
                payload["resolved_target"] = resolved
                payload["target_resolution_status"] = "RESOLVED"
                payload["resolution_stage"] = resolution_stage.value
                log_status = "RESOLVED"
        else:
            payload["target_resolution_status"] = "NOT_FOUND"
            payload["resolution_stage"] = ResolutionStage.TARGET_NOT_FOUND.value
            log_status = "NOT_FOUND"

        payload["reference_resolution_source"] = "candidate_set"
        payload.update(_log(state, "target_resolve", status=log_status, target_resolve_mode="candidate_set",
            candidate_source=candidate_set.source.value,
            candidate_count=len(candidates),
            candidate_review_status=str(review.status),
            candidate_review_next_action=str(review.next_action),
            next_action="FINISH"))
        return payload

    if review.next_action == NextAction.CLARIFY:
        if goal.goal_type == GoalType.RECOMMENDATION:
            resolved = ResolveShopResult(status="NOT_FOUND", confidence=0.0, reason=review.reason or "candidate_set_need_search")
            payload["resolve_shop_result"] = resolved
            payload["target_resolution_status"] = "NOT_FOUND"
            payload["resolution_stage"] = ResolutionStage.TARGET_NOT_FOUND.value
            payload["reference_resolution_source"] = "candidate_set"
            payload.update(_log(
                state,
                "target_resolve",
                status="NOT_FOUND",
                target_resolve_mode="candidate_set",
                candidate_source=candidate_set.source.value,
                candidate_count=len(candidate_set.candidates or []),
                candidate_review_status=str(review.status),
                candidate_review_next_action=str(review.next_action),
                next_action="CONTINUE_SEARCH",
                reason=review.reason or "candidate_set_need_search",
            ))
            return payload
        reason = review.reason or "candidate_set_need_clarification"
        resolved = ResolveShopResult(status="NOT_FOUND", confidence=0.0, reason=reason)
        pending = build_pending_clarification(
            original_text=str(state.get("raw_text", "") or ""),
            original_semantic_frame=sf.model_dump(mode="json") if hasattr(sf, "model_dump") else _session_state_dict(sf),
            original_task_type=getattr(sf, "task_type", "") or state.get("task_type", ""),
            candidate_targets=_pending_candidate_targets(candidate_set),
            reason=reason,
            source_node="target_resolve",
        )
        payload["resolve_shop_result"] = resolved
        payload["pending_clarification"] = pending
        payload["target_resolution_status"] = "NOT_FOUND"
        payload["final_response"] = format_pending_prompt(pending)
        payload["session_state_after"] = session_snapshot
        payload.update(_log(state, "target_resolve", status="NEED_CLARIFICATION",
                           target_resolve_mode="candidate_set",
                           candidate_source=candidate_set.source.value,
                           candidate_count=len(candidate_set.candidates or []),
                           candidate_review_status=str(review.status),
                           candidate_review_next_action=str(review.next_action),
                           next_action="CLARIFY", reason=reason))
        return payload

    resolved = ResolveShopResult(status="NOT_FOUND", confidence=0.0,
                                  reason=review.reason or "candidate_set_unsupported")
    payload["resolve_shop_result"] = resolved
    payload["target_resolution_status"] = "NOT_FOUND"
    payload["final_response"] = "暂时无法完成这个请求，请换个说法试试。"
    payload["candidate_source_origin"] = candidate_set.source.value
    payload["fallback_reason"] = review.reason or "candidate_set_unsupported"
    payload["session_state_after"] = session_snapshot
    payload.update(_log(state, "target_resolve", status="NOT_FOUND",
                       target_resolve_mode="candidate_set",
                       candidate_source=candidate_set.source.value,
                       candidate_count=len(candidate_set.candidates or []),
                       candidate_review_status=str(review.status),
                       candidate_review_next_action=str(review.next_action),
                       next_action="FALLBACK", reason=review.reason))
    return payload


def _h_clarify_decide(state: GraphState) -> dict:
    resolution_stage = state.get("resolution_stage") or ""
    # Multi-candidate (comparison/recommendation): candidate_set_resolved → proceed WITHOUT resolved_target
    if resolution_stage == ResolutionStage.CANDIDATE_SET_RESOLVED.value:
        return {
            "resolution_stage": resolution_stage,
            **_log(state, "clarify_decide", decision="proceed_candidate_set"),
        }
    if state.get("task_type") == TaskType.recommendation.value:
        semantic_frame = _to_dict(state.get("semantic_frame"))
        current_shop = _to_dict(state.get("current_shop"))
        has_deictic_reference = bool(
            semantic_frame.get("deictic_references")
            or semantic_frame.get("reference_mentions")
            or semantic_frame.get("comparison_targets")
        )
        if (
            has_deictic_reference
            and not current_shop.get("shop_id")
            and not current_shop.get("shop_name")
            and state.get("resolved_target") is None
            and state.get("resolve_shop_result") is None
        ):
            return {
                "final_response": "店名有点模糊，请提供完整店名。",
                **_log(state, "clarify_decide", decision="recommendation_needs_clarification"),
            }
        return {
            "resolved_target": state.get("resolved_target") or state.get("resolve_shop_result"),
            **_log(state, "clarify_decide", decision="proceed_recommendation"),
        }
    rs = state.get("resolved_target") or state.get("resolve_shop_result")
    if rs is not None:
        rs_dict = _to_dict(rs)
        status = rs_dict.get("status", getattr(rs, "status", ""))
        reason = str(rs_dict.get("reason", getattr(rs, "reason", "")) or "")
        if status == "RESOLVED":
            return {"resolved_target": rs, "resolution_stage": resolution_stage,
                    **_log(state, "clarify_decide", decision="proceed")}
        if status in ("AMBIGUOUS", "LOW_CONFIDENCE"):
            return {**_log(state, "clarify_decide", decision="clarify")}
        if reason in {"comparison_requires_at_least_two_shops", "comparison_too_many_shops",
                       "pronoun_without_current_shop", "ordinal_out_of_range"}:
            from .._compat import _comparison_reason_response
            return {
                "final_response": str(state.get("final_response", "") or _comparison_reason_response(reason)),
                **_log(state, "clarify_decide", decision="comparison_prompt"),
            }
        return {"final_response": "没有找到这家店，请提供完整店名。",
                **_log(state, "clarify_decide", decision="not_found")}
    return _log(state, "clarify_decide", decision="no_result")


def _h_evidence_planner(state: GraphState) -> dict:
    goal = state.get("local_life_goal_draft")
    candidate_set = state.get("effective_candidate_set") or state.get("candidate_set")
    if goal is None:
        return {
            "error_code": "SCHEMA_VALIDATION_FAILED",
            "error_message": "goal is required",
            "failed_stage": "evidence_planner",
            **_log(state, "evidence_planner", status="failed", evidence_plan_source="strict",
                  missing_goal=goal is None, missing_candidate_set=candidate_set is None,
                  reason="missing_goal"),
        }
    if candidate_set is None:
        return {
            "error_code": "SCHEMA_VALIDATION_FAILED",
            "error_message": "effective_candidate_set is required",
            "failed_stage": "evidence_planner",
            **_log(state, "evidence_planner", status="failed", evidence_plan_source="strict",
                  missing_goal=False, missing_candidate_set=True,
                  reason="missing_effective_candidate_set"),
        }
    semantic_task_type = _enum_value(state.get("task_type")) or _enum_value(_to_dict(state.get("semantic_frame")).get("task_type"))
    goal_type_value = str(getattr(getattr(goal, "goal_type", None), "value", getattr(goal, "goal_type", None)) or "")
    if goal_type_value == GoalType.RECOMMENDATION.value:
        plan_payload = build_recommendation_execution_plan(
            state.get("semantic_frame") or {},
            location=_user_location(state),
            fallback_query=str(state.get("raw_text", "") or ""),
        )
        plan = ExecutionPlan.model_validate(plan_payload.get("plan") or {})
        plan.plan_source = plan.plan_source or "deterministic_recommendation_builder"
        plan = _normalize_distance_tool_calls(plan, state)
        return {
            "execution_plan": plan,
            "execution_plan_source": plan.plan_source,
            "planning_llm_backend": "",
            "planning_llm_called": False,
            "planning_failure_code": "",
            "task_type": plan.task_type,
            "task_type_source": "evidence_planner",
            "reference_resolution_source": "candidate_set",
            **_log(
                state,
                "evidence_planner",
                evidence_plan_source="deterministic_recommendation_builder",
                missing_goal=False,
                missing_candidate_set=True,
                tool_calls=len(plan.tool_calls),
                task_type=plan.task_type,
                planner_source=plan.plan_source or "deterministic_recommendation_builder",
                candidate_count=0,
            ),
        }
    if semantic_task_type == TaskType.comparison.value or goal_type_value == GoalType.COMPARISON.value:
        plan = plan_evidence_from_candidates(
            goal=goal,
            candidate_set=candidate_set,
            location=_user_location(state),
        )
        plan.plan_source = plan.plan_source or "deterministic_comparison_builder"
        plan = _normalize_distance_tool_calls(plan, state)
        return {
            "execution_plan": plan,
            "execution_plan_source": plan.plan_source,
            "planning_llm_backend": "",
            "planning_llm_called": False,
            "planning_failure_code": "",
            "task_type": plan.task_type,
            "task_type_source": "evidence_planner",
            "reference_resolution_source": "candidate_set",
            **_log(
                state,
                "evidence_planner",
                evidence_plan_source="deterministic_comparison_builder",
                missing_goal=False,
                missing_candidate_set=False,
                tool_calls=len(plan.tool_calls),
                task_type=plan.task_type,
                planner_source=plan.plan_source or "deterministic_comparison_builder",
                candidate_count=len(candidate_set.candidates or []),
            ),
        }
    from ..graph_builder import call_llm as _call_llm, get_llm_backend_snapshot as _get_llm_backend_snapshot
    backend_snapshot = _get_llm_backend_snapshot()
    strict_llm = str(backend_snapshot.get("backend_kind", "") or "") not in {"", "fake_llm", "fake"}
    plan, meta = plan_evidence_with_llm(
        goal=goal,
        candidate_set=candidate_set,
        location=_user_location(state),
        semantic_frame=state.get("semantic_frame"),
        raw_text=str(state.get("raw_text", "") or ""),
        llm_call=_call_llm,
        strict=strict_llm,
    )
    fallback_reason = ""
    if plan is None:
        fallback_reason = meta.get("error_code", "EVIDENCE_PLANNER_FAILED")
    elif not plan.tool_calls and not plan.stages:
        fallback_reason = "EXECUTION_PLAN_EMPTY"

    if fallback_reason:
        fallback_plan = plan_evidence_from_candidates(
            goal=goal,
            candidate_set=candidate_set,
            location=_user_location(state),
        )
        fallback_plan.plan_source = fallback_plan.plan_source or "deterministic_evidence_planner"
        fallback_plan.planning_notes = list(fallback_plan.planning_notes or [])
        if fallback_reason not in fallback_plan.planning_notes:
            fallback_plan.planning_notes.append(f"llm_fallback:{fallback_reason}")
        fallback_plan = _normalize_distance_tool_calls(fallback_plan, state)
        return {
            "execution_plan": fallback_plan,
            "execution_plan_source": fallback_plan.plan_source,
            "planning_llm_backend": meta.get("llm_backend", ""),
            "planning_llm_called": True,
            "planning_failure_code": fallback_reason,
            "task_type": fallback_plan.task_type,
            "task_type_source": "evidence_planner",
            "reference_resolution_source": "candidate_set",
            **_log(
                state,
                "evidence_planner",
                evidence_plan_source="deterministic_comparison_fallback" if getattr(goal, "goal_type", None) == GoalType.COMPARISON else "deterministic_evidence_fallback",
                missing_goal=False,
                missing_candidate_set=False,
                tool_calls=len(fallback_plan.tool_calls),
                task_type=fallback_plan.task_type,
                planner_source=fallback_plan.plan_source or "deterministic_evidence_planner",
                candidate_count=len(candidate_set.candidates or []),
                reason=fallback_reason,
            ),
        }
    task_type = str(plan.task_type or "")
    plan = _normalize_distance_tool_calls(plan, state)
    return {
        "execution_plan": plan,
        "execution_plan_source": plan.plan_source or "llm_evidence_planner",
        "planning_llm_backend": meta.get("llm_backend", ""),
        "planning_llm_called": True,
        "planning_failure_code": "",
        "task_type": task_type,
        "task_type_source": "evidence_planner",
        "reference_resolution_source": "candidate_set",
        **_log(state, "evidence_planner", evidence_plan_source="strict",
              missing_goal=False, missing_candidate_set=False,
              tool_calls=len(plan.tool_calls), task_type=task_type,
              planner_source=plan.plan_source or "llm_evidence_planner",
              candidate_count=len(candidate_set.candidates or [])),
    }


def _h_plan_validator(state: GraphState) -> dict:
    plan = state.get("execution_plan")
    if plan is None:
        return {
            "error_code": "SCHEMA_VALIDATION_FAILED",
            "error_message": "execution_plan is required",
            "plan_validation_result": "failed",
            "failed_stage": "plan_validator",
            "validated_plan": None,
            **_log(state, "plan_validator", status="failed", reason="missing_execution_plan"),
        }
    if not plan.tool_calls and not plan.stages:
        return {
            "error_code": "INVALID_PLAN",
            "error_message": "execution_plan must contain tool_calls or stages",
            "plan_validation_result": "failed",
            "failed_stage": "plan_validator",
            "validated_plan": None,
            **_log(state, "plan_validator", status="failed", reason="empty_plan"),
        }
    validator = ExecutionPlanValidator()
    from .._compat import _resolved_shop_ids_from_state, _plan_validation_error_code
    resolved_shop_ids = _resolved_shop_ids_from_state(state)
    report = validator.validate(plan, resolved_shop_ids=resolved_shop_ids or None)
    if not report.passed:
        error_code = _plan_validation_error_code(report.errors)
        error_message = "; ".join(report.errors)
        return {
            "error_code": error_code,
            "error_message": error_message,
            "plan_validation_result": "failed",
            "failed_stage": "plan_validator",
            "validated_plan": None,
            **_log(state, "plan_validator", status="failed", reason=error_code),
        }
    return {
        "error_code": "",
        "error_message": "",
        "plan_validation_result": "pass",
        "failed_stage": "",
        "validated_plan": plan,
        **_log(state, "plan_validator", status="pass"),
    }


def _h_expand_search(state: GraphState) -> dict:
    """P2 expand_search: relax candidate constraints and re-resolve."""
    from ...domain.candidate import CandidateSpec

    goal = state.get("local_life_goal_draft")
    spec = state.get("candidate_spec")
    if goal is None or spec is None:
        return {
            "fallback_reason": "expand_search_missing_goal_or_spec",
            **_log(state, "expand_search", status="FALLBACK", reason="missing_goal_or_candidate_spec"),
        }
    relaxed = deepcopy(spec)
    if isinstance(relaxed, CandidateSpec):
        old_limit = relaxed.limit or 3
        relaxed.limit = old_limit * 2 + 5
    elif isinstance(relaxed, dict):
        old_limit = int(relaxed.get("limit", 3) or 3)
        relaxed["limit"] = old_limit * 2 + 5
    else:
        old_limit = 3
    payload: dict[str, Any] = {
        "candidate_spec": relaxed,
        "candidate_set": state.get("candidate_set"),
        "review_results": dict(state.get("review_results") or {}),
        "expand_search_requested": True,
    }
    ss = _session_store_state(state)
    ss.last_candidate_spec = (
        relaxed.model_dump() if hasattr(relaxed, "model_dump") else deepcopy(relaxed)
    )
    payload["session_state"] = ss
    payload.update(_log(state, "expand_search",
                        old_limit=old_limit,
                        new_limit=relaxed.limit if isinstance(relaxed, CandidateSpec) else relaxed.get("limit"),
                        candidates_before=len(state.get("candidate_set", {}).candidates if hasattr(state.get("candidate_set"), "candidates") else []),
                        candidates_after=len(state.get("candidate_set", {}).candidates if hasattr(state.get("candidate_set"), "candidates") else []),
                        review_action="EXPAND_SEARCH",
                        review_status="pending"))
    return payload


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------


def _planning_failure_route(state: dict[str, Any]) -> str:
    from .._routes import _OUTER_ROUTE_CLARIFY, _OUTER_ROUTE_EXECUTE, _OUTER_ROUTE_FALLBACK

    error_code = str(state.get("error_code", "") or "")
    error_message = str(state.get("error_message", "") or "")
    failed_stage = str(state.get("failed_stage", "") or "")
    if "missing_goal" in error_message or "missing_candidate_set" in error_message or "missing_goal_draft" in error_message:
        return _OUTER_ROUTE_CLARIFY
    if error_code in {"SCHEMA_VALIDATION_FAILED"}:
        if any(token in error_message for token in ("goal", "candidate", "target")):
            return _OUTER_ROUTE_CLARIFY
    if error_code in {"TOOL_NOT_REGISTERED", "INVALID_ARGUMENT"} or failed_stage == "plan_validator":
        return _OUTER_ROUTE_FALLBACK
    if error_code:
        return _OUTER_ROUTE_FALLBACK
    return _OUTER_ROUTE_EXECUTE
