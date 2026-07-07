"""State update planner for session state writes.

Separates two orthogonal status systems:
- ToolResultStatus (result_status): execution outcome of a tool call
- ResolveShopResult.status (resolve_shop_status): outcome of shop resolution

These must NEVER be conflated. A tool can succeed (result_status=ok) but the
shop resolution can fail (resolve_shop_status=NOT_FOUND).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ...domain.enums import TaskType
from ...domain.serialization import to_plain_dict
from ...domain.state import SessionValueMeta
from ...location_utils import normalize_location_payload
from ...tools.result_semantics import TOOL_FAILURE_STATUSES, get_tool_result_status
from ...target.clarification import build_pending_clarification


def _to_dict(value: Any) -> dict[str, Any]:
    return to_plain_dict(value)


def _plan_required_by_call_id(plan: Any | None) -> dict[str, bool]:
    result: dict[str, bool] = {}
    plan_dict = _to_dict(plan)
    for call in plan_dict.get("tool_calls", []) or []:
        call_dict = _to_dict(call)
        call_id = str(call_dict.get("call_id", "")).strip()
        if call_id:
                result[call_id] = bool(call_dict.get("required", True))
    return result


def _first_nonempty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _location_context(turn_context: dict[str, Any]) -> dict[str, Any]:
    for key in ("user_location", "location_context", "session_location_context"):
        value = normalize_location_payload(turn_context.get(key))
        if value:
            return value
    return {}


def _merged_active_constraints(turn_context: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    current = _to_dict(turn_context.get("active_constraints"))
    if current:
        merged.update(current)
    semantic_frame = _to_dict(turn_context.get("semantic_frame"))
    for key in ("hard_constraints", "soft_preferences"):
        value = semantic_frame.get(key)
        if isinstance(value, dict) and value:
            merged.update({str(k): v for k, v in value.items() if v not in (None, "", [], {}, False)})
    location = normalize_location_payload(semantic_frame.get("location"))
    if location and "location" not in merged:
        merged["location"] = location
    return merged


def _ttl_from_pending(pending_dict: dict[str, Any] | None) -> int | None:
    if not pending_dict:
        return None
    created_at = pending_dict.get("created_at")
    expires_at = pending_dict.get("expires_at")
    if isinstance(created_at, datetime) and isinstance(expires_at, datetime):
        ttl_seconds = int((expires_at - created_at).total_seconds())
        return max(ttl_seconds, 0)
    return None


def _evidence_ref_from_pack(evidence_pack: Any, *, target_shop_id: str = "") -> str:
    evidence_dict = _to_dict(evidence_pack)
    for item in evidence_dict.get("evidence_items", []) or []:
        item_dict = _to_dict(item)
        item_shop_id = str(item_dict.get("shop_id", "") or "").strip()
        if target_shop_id and item_shop_id and item_shop_id != target_shop_id:
            continue
        evidence_ref = _first_nonempty(item_dict.get("evidence_id"), item_dict.get("call_id"))
        if evidence_ref:
            return evidence_ref
    comparison_matrix = _to_dict(evidence_dict.get("comparison_matrix"))
    if comparison_matrix.get("matrix_id"):
        return str(comparison_matrix.get("matrix_id", "")).strip()
    ranking_snapshot = _to_dict(evidence_dict.get("ranking_snapshot"))
    if ranking_snapshot.get("snapshot_id"):
        return str(ranking_snapshot.get("snapshot_id", "")).strip()
    return ""


def _should_promote_recommendation_reference(
    turn_context: dict[str, Any],
    *,
    task_type_value: str,
    resolved_shop: dict[str, Any],
    resolve_shop_status: str,
    active_turn_route: str,
    reference_resolution_source: str,
    comparison_targets: list[dict[str, Any]],
) -> bool:
    if resolve_shop_status != "RESOLVED" or not resolved_shop:
        return False
    if str(task_type_value or "").strip() != TaskType.recommendation.value:
        return False

    target_resolution = _to_dict(
        turn_context.get("target_resolution") or turn_context.get("resolved_target") or turn_context.get("resolve_shop_result")
    )
    target_source = _first_nonempty(target_resolution.get("source"), reference_resolution_source)
    reference_type = _first_nonempty(target_resolution.get("reference_type"), target_resolution.get("resolution_reason"))

    if active_turn_route in {
        "shop_coupon",
        "shop_status",
        "shop_distance",
        "shop_review_summary",
        "shop_scene_fit",
        "shop_price",
    }:
        return True

    if comparison_targets:
        return True

    if target_source == "last_recommendation_list" and reference_type in {
        "ordinal_reference",
        "reference_dependency",
        "ordinal",
    }:
        return True

    return False


def _session_value_meta(
    turn_context: dict[str, Any],
    *,
    source: str = "",
    evidence_ref: str = "",
    ttl: int | None = None,
    resume_strategy: str = "",
) -> SessionValueMeta:
    return SessionValueMeta(
        source=_first_nonempty(source),
        ttl=ttl,
        evidence_ref=_first_nonempty(evidence_ref),
        location_context=_location_context(turn_context),
        resume_strategy=_first_nonempty(resume_strategy),
    )


def plan_state_update(
    turn_context: dict,
    task_type: str,
    resolve_shop_status: str,
    pending_check_result: str | None = None,
) -> dict:
    """Compute the session state delta for this turn.

    Args:
        turn_context: Full turn context dict.
        task_type: Normalised task type string.
        resolve_shop_status: Outcome of shop resolution — one of
            RESOLVED, AMBIGUOUS, LOW_CONFIDENCE, NOT_FOUND, or "".
            This is ResolveShopResult.status, NOT ToolResultStatus.
        pending_check_result: Optional pending-clarification check outcome.

    Returns:
        State update directive dict with set_fields, clear_fields, etc.
    """
    turn_context = turn_context or {}
    task_type_value = str(task_type or "").strip()
    workflow_name = str(turn_context.get("workflow_name", "") or "").strip()
    canonical_entity = _to_dict(turn_context.get("canonical_shop_entity"))
    canonical_entities = list(turn_context.get("canonical_shop_entities") or [])
    shop_resolution_trace = list(turn_context.get("shop_resolution_trace") or [])
    resolved_target = turn_context.get("resolved_target") or turn_context.get("resolved_shop")
    resolved_target_dict = _to_dict(resolved_target)
    resolved_shop = resolved_target_dict.get("resolved_shop") or resolved_target_dict.get("shop") or {}
    if hasattr(resolved_shop, "model_dump"):
        resolved_shop = resolved_shop.model_dump()
    if not isinstance(resolved_shop, dict):
        resolved_shop = {}

    pending = turn_context.get("pending_clarification")
    pending_dict = _to_dict(pending) if pending is not None else None
    recommendation_list = turn_context.get("last_recommendation_list")
    evidence_dict = _to_dict(turn_context.get("evidence_pack"))
    ranking_snapshot = _to_dict(evidence_dict.get("ranking_snapshot"))
    ranked_recommendations = [
        _to_dict(item)
        for item in (ranking_snapshot.get("ranked") or ranking_snapshot.get("ranked_shops") or [])
        if _to_dict(item)
    ]
    if not recommendation_list:
        recommendation_list = evidence_dict.get("last_recommendation_list") or ranked_recommendations
    exploration_recommendation_list = evidence_dict.get("last_recommendation_list") if turn_context.get("evidence_pack") is not None else []
    if workflow_name == "exploration_planning" and exploration_recommendation_list:
        recommendation_list = exploration_recommendation_list
    if recommendation_list:
        recommendation_list = [_to_dict(item) for item in recommendation_list if _to_dict(item)]
    goal_dict = _to_dict(turn_context.get("local_life_goal_draft"))
    candidate_source = str(goal_dict.get("candidate_source", "") or "").strip()
    active_turn_result = _to_dict(turn_context.get("active_turn_result"))
    active_turn_route = str(active_turn_result.get("route", "") or "").strip()
    reference_resolution_source = str(turn_context.get("reference_resolution_source", "") or "").strip()
    target_resolution = _to_dict(turn_context.get("target_resolution"))
    comparison_targets = turn_context.get("comparison_targets")
    if comparison_targets is None:
        comparison_targets = []
    comparison_targets_source = str(turn_context.get("comparison_targets_source", "") or "").strip()
    comparison_resolution = _to_dict(turn_context.get("comparison_target_resolution"))
    comparison_resolution_status = str(comparison_resolution.get("status", "") or "").upper()
    comparison_resolution_targets = [
        _to_dict(item)
        for item in (comparison_resolution.get("targets") or [])
        if str(_to_dict(item).get("shop_id", "") or "").strip() or str(_to_dict(item).get("shop_name", "") or "").strip()
    ]
    if comparison_resolution_status == "RESOLVED" and comparison_resolution_targets:
        comparison_targets = comparison_resolution_targets
    comparison_result = turn_context.get("comparison_result")
    evidence_pack = turn_context.get("evidence_pack")
    if comparison_result is None and evidence_pack is not None:
        comparison_result = _to_dict(evidence_pack).get("comparison_matrix")
    if not comparison_targets_source:
        if comparison_targets:
            comparison_targets_source = "comparison_targets"
        elif comparison_resolution_targets:
            comparison_targets_source = "comparison_target_resolution"
        elif comparison_result is not None:
            comparison_targets_source = "comparison_result_fallback"

    def _clarification_candidates() -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []

        def _append(source: Any) -> None:
            if not source:
                return
            if isinstance(source, dict):
                source = source.get("candidate_targets") or source.get("targets") or source.get("candidates") or []
            if not isinstance(source, list):
                return
            for item in source:
                item_dict = _to_dict(item)
                shop = _to_dict(item_dict.get("resolved_shop") or item_dict.get("shop") or item_dict)
                shop_id = str(shop.get("shop_id", "") or "").strip()
                shop_name = str(shop.get("shop_name", "") or "").strip()
                if not shop_id and not shop_name:
                    continue
                key = (shop_id, shop_name)
                if any((str(existing.get("shop_id", "") or "").strip(), str(existing.get("shop_name", "") or "").strip()) == key for existing in collected):
                    continue
                collected.append({
                    "shop_id": shop_id,
                    "shop_name": shop_name,
                    "address": str(shop.get("address", "") or item_dict.get("address", "") or "").strip(),
                })

        _append(pending)
        _append(turn_context.get("resolve_shop_result"))
        _append(comparison_resolution)
        _append(comparison_targets)
        _append(comparison_resolution_targets)
        _append(recommendation_list)
        return collected

    should_synthesize_pending = False
    if comparison_resolution_status in {"NEED_CLARIFICATION", "PARTIAL", "AMBIGUOUS", "NOT_FOUND", "TOO_MANY"}:
        should_synthesize_pending = True
    elif task_type_value in {
        TaskType.single_shop_query.value,
        TaskType.coupon_query.value,
        TaskType.comparison.value,
    } and resolve_shop_status in {"AMBIGUOUS", "LOW_CONFIDENCE", "NOT_FOUND"}:
        should_synthesize_pending = True

    if pending_dict is None and should_synthesize_pending:
        synthesized_candidates = _clarification_candidates()
        if synthesized_candidates:
            original_task_type = task_type_value or str(turn_context.get("task_type", "") or "")
            if comparison_resolution_status in {"NEED_CLARIFICATION", "PARTIAL", "AMBIGUOUS", "NOT_FOUND", "TOO_MANY"}:
                original_task_type = "comparison"
            elif original_task_type in {"", "discovery"}:
                original_task_type = "single_shop_query" if resolve_shop_status in {"AMBIGUOUS", "LOW_CONFIDENCE", "NOT_FOUND"} else original_task_type
            try:
                pending = build_pending_clarification(
                    original_text=str(turn_context.get("raw_text", "") or ""),
                    original_semantic_frame=turn_context.get("semantic_frame") or {},
                    original_task_type=original_task_type,
                    candidate_targets=synthesized_candidates,
                    reason=str(comparison_resolution.get("reason", "") or turn_context.get("workflow_reason", "") or "clarification_needed"),
                    source_node=str(turn_context.get("workflow_name", "") or "state_update_planner"),
                )
                pending_dict = pending.model_dump() if hasattr(pending, "model_dump") else _to_dict(pending)
            except Exception:
                pass
    resolution_stage = str(turn_context.get("resolution_stage", "") or "").strip()
    tool_results = turn_context.get("tool_result_set") or turn_context.get("tool_results") or {}
    execution_plan_dict = _to_dict(turn_context.get("validated_plan") or turn_context.get("execution_plan"))
    has_tool_calls = bool(execution_plan_dict.get("tool_calls"))
    required_by_call_id = _plan_required_by_call_id(
        turn_context.get("validated_plan") or turn_context.get("execution_plan")
    )

    # Tool execution failure detection — reads ONLY ToolResultStatus.
    tool_failed = False
    if isinstance(tool_results, dict):
        observed_call_ids = {str(call_id) for call_id in tool_results.keys()}
        required_call_ids = {call_id for call_id, required in required_by_call_id.items() if required}
        for call_id, result in tool_results.items():
            required = required_by_call_id.get(str(call_id), True)
            if required and get_tool_result_status(_to_dict(result)) in TOOL_FAILURE_STATUSES:
                tool_failed = True
                break
        if has_tool_calls and required_call_ids and not tool_failed:
            missing_required_calls = required_call_ids - observed_call_ids
            if missing_required_calls:
                tool_failed = True
    elif has_tool_calls:
        tool_failed = True

    set_fields: dict[str, Any] = {}
    clear_fields: list[str] = []

    if canonical_entity:
        set_fields["canonical_shop_entity"] = canonical_entity
    if canonical_entities:
        set_fields["canonical_shop_entities"] = canonical_entities
    if shop_resolution_trace:
        set_fields["shop_resolution_trace"] = shop_resolution_trace
    merged_active_constraints = _merged_active_constraints(turn_context)
    if merged_active_constraints:
        set_fields["active_constraints"] = merged_active_constraints

    if tool_failed and task_type_value != TaskType.comparison.value:
        if not (resolve_shop_status == "RESOLVED" and resolved_shop):
            return {
                "set_fields": {},
                "clear_fields": [],
                "task_type": task_type,
                "resolve_shop_status": resolve_shop_status,
                "pending_check_result": pending_check_result,
            }

    if pending_check_result in {"invalid", "out_of_range"}:
        return {
            "set_fields": {},
            "clear_fields": [],
            "task_type": task_type,
            "resolve_shop_status": resolve_shop_status,
            "pending_check_result": pending_check_result,
        }

    if pending_check_result in {"expired", "cancelled", "topic_switch"}:
        return {
            "set_fields": {},
            "clear_fields": ["pending_clarification", "pending_clarification_meta"],
            "task_type": task_type,
            "resolve_shop_status": resolve_shop_status,
            "pending_check_result": pending_check_result,
        }

    if pending_dict is not None and not tool_failed and workflow_name != "exploration_planning":
        set_fields["pending_clarification"] = pending_dict
        set_fields["pending_clarification_meta"] = _session_value_meta(
            turn_context,
            source=_first_nonempty(pending_dict.get("source_node"), active_turn_route, task_type),
            evidence_ref=_first_nonempty(pending_dict.get("pending_id"), pending_dict.get("source_node")),
            ttl=_ttl_from_pending(pending_dict),
            resume_strategy=_first_nonempty(pending_dict.get("resume_strategy"), "resume_original_task"),
        )
        clear_fields = [field for field in clear_fields if field != "pending_clarification"]
        return {
            "set_fields": set_fields,
            "clear_fields": clear_fields,
            "task_type": task_type,
            "resolve_shop_status": resolve_shop_status,
            "pending_check_result": pending_check_result,
        }

    # Shop resolution branching — reads ResolveShopResult.status.
    # CANDIDATE_SET_RESOLVED is a valid "resolved" state (multi-candidate with no single target).
    # It follows the same RESOLVED paths for comparison/recommendation, but
    # single_shop_query must NEVER reach CANDIDATE_SET_RESOLVED (it would be AMBIGUOUS).
    is_resolved = resolve_shop_status in ("RESOLVED", "CANDIDATE_SET_RESOLVED")
    if not is_resolved:
        is_resolved = bool(target_resolution.get("resolved")) or str(_to_dict(turn_context.get("resolved_target")).get("status", "") or "").upper() == "RESOLVED"
    if resolve_shop_status == "AMBIGUOUS":
        set_fields["pending_clarification"] = pending_dict
        set_fields["pending_clarification_meta"] = _session_value_meta(
            turn_context,
            source=_first_nonempty(pending_dict.get("source_node") if pending_dict else "", active_turn_route, task_type),
            evidence_ref=_first_nonempty(pending_dict.get("pending_id") if pending_dict else "", pending_dict.get("source_node") if pending_dict else ""),
            ttl=_ttl_from_pending(pending_dict),
            resume_strategy=_first_nonempty(pending_dict.get("resume_strategy") if pending_dict else "", "resume_original_task"),
        )
        return {
            "set_fields": set_fields,
            "clear_fields": [],
            "task_type": task_type,
            "resolve_shop_status": resolve_shop_status,
            "pending_check_result": pending_check_result,
        }

    if resolve_shop_status in {"LOW_CONFIDENCE", "NOT_FOUND"}:
        if pending_dict is not None:
            set_fields["pending_clarification"] = pending_dict
            set_fields["pending_clarification_meta"] = _session_value_meta(
                turn_context,
                source=_first_nonempty(pending_dict.get("source_node"), active_turn_route, task_type),
                evidence_ref=_first_nonempty(pending_dict.get("pending_id"), pending_dict.get("source_node")),
                ttl=_ttl_from_pending(pending_dict),
                resume_strategy=_first_nonempty(pending_dict.get("resume_strategy"), "resume_original_task"),
            )
        clear_fields.extend(["current_shop", "current_shop_meta"])
        return {
            "set_fields": set_fields,
            "clear_fields": clear_fields,
            "task_type": task_type,
            "resolve_shop_status": resolve_shop_status,
            "pending_check_result": pending_check_result,
        }

    if task_type == TaskType.recommendation.value:
        if recommendation_list:
            set_fields["last_recommendation_list"] = recommendation_list
            set_fields["last_recommendation_list_meta"] = _session_value_meta(
                turn_context,
                source=_first_nonempty(candidate_source, active_turn_route, workflow_name or task_type, "recommendation"),
                evidence_ref=_evidence_ref_from_pack(evidence_pack),
                ttl=None,
            )
        # Pure discovery turns only persist the ranked list. If the router
        # has already narrowed this to a deterministic single-shop route
        # (for example, "第二家有券吗"), then the resolved target should
        # still become the current anchor.
        if _should_promote_recommendation_reference(
            turn_context,
            task_type_value=task_type_value,
            resolved_shop=resolved_shop,
            resolve_shop_status=resolve_shop_status,
            active_turn_route=active_turn_route,
            reference_resolution_source=reference_resolution_source,
            comparison_targets=[item for item in comparison_targets if _to_dict(item)],
        ):
            set_fields["current_shop"] = resolved_shop
            set_fields["current_shop_meta"] = _session_value_meta(
                turn_context,
                source=_first_nonempty(reference_resolution_source, active_turn_route, task_type, "target_resolve"),
                evidence_ref=_evidence_ref_from_pack(evidence_pack, target_shop_id=str(resolved_shop.get("shop_id", "") or "")),
                ttl=None,
            )
        else:
            clear_fields.extend(["current_shop", "current_shop_meta"])
        clear_fields.extend(["pending_clarification", "pending_clarification_meta"])

    if is_resolved:
        if task_type in (TaskType.single_shop_query.value, TaskType.coupon_query.value):
            # Only write current_shop for true RESOLVED (single target), never CANDIDATE_SET_RESOLVED
            if resolve_shop_status == "RESOLVED" or (resolved_shop and is_resolved):
                should_set_current_shop = not tool_failed
                if resolved_shop and should_set_current_shop:
                    set_fields["current_shop"] = resolved_shop
                    set_fields["current_shop_meta"] = _session_value_meta(
                        turn_context,
                        source=_first_nonempty(reference_resolution_source, active_turn_route, task_type, "target_resolve"),
                        evidence_ref=_evidence_ref_from_pack(evidence_pack, target_shop_id=str(resolved_shop.get("shop_id", "") or "")),
                        ttl=None,
                    )
            clear_fields.extend(["pending_clarification", "last_recommendation_list"])
            clear_fields.extend(["pending_clarification_meta", "last_recommendation_list_meta"])
        elif task_type == TaskType.comparison.value:
            if comparison_resolution_status == "RESOLVED":
                if comparison_targets:
                    set_fields["comparison_targets"] = comparison_targets
                    set_fields["comparison_targets_meta"] = _session_value_meta(
                        turn_context,
                        source=_first_nonempty(comparison_targets_source, reference_resolution_source, active_turn_route, task_type),
                        evidence_ref=_evidence_ref_from_pack(evidence_pack),
                        ttl=None,
                    )
                if comparison_result is not None:
                    set_fields["comparison_result"] = comparison_result
                clear_fields.extend(["pending_clarification", "pending_clarification_meta"])
                clear_fields.extend(["current_shop", "current_shop_meta"])
            elif comparison_resolution_status in {"NEED_CLARIFICATION", "PARTIAL", "AMBIGUOUS", "NOT_FOUND", "TOO_MANY"}:
                if pending_dict is not None:
                    set_fields["pending_clarification"] = pending_dict
                    set_fields["pending_clarification_meta"] = _session_value_meta(
                        turn_context,
                        source=_first_nonempty(pending_dict.get("source_node"), active_turn_route, task_type),
                        evidence_ref=_first_nonempty(pending_dict.get("pending_id"), pending_dict.get("source_node")),
                        ttl=_ttl_from_pending(pending_dict),
                        resume_strategy=_first_nonempty(pending_dict.get("resume_strategy"), "resume_original_task"),
                    )
                else:
                    clear_fields.append("pending_clarification")
                    clear_fields.append("pending_clarification_meta")
                clear_fields.append("current_shop")
                clear_fields.append("current_shop_meta")
            elif comparison_targets:
                set_fields["comparison_targets"] = comparison_targets
                set_fields["comparison_targets_meta"] = _session_value_meta(
                    turn_context,
                    source=_first_nonempty(comparison_targets_source, reference_resolution_source, active_turn_route, task_type),
                    evidence_ref=_evidence_ref_from_pack(evidence_pack),
                    ttl=None,
                )
                if comparison_result is not None:
                    set_fields["comparison_result"] = comparison_result
                if pending_dict is not None:
                    set_fields["pending_clarification"] = pending_dict
                    set_fields["pending_clarification_meta"] = _session_value_meta(
                        turn_context,
                        source=_first_nonempty(pending_dict.get("source_node"), active_turn_route, task_type),
                        evidence_ref=_first_nonempty(pending_dict.get("pending_id"), pending_dict.get("source_node")),
                        ttl=_ttl_from_pending(pending_dict),
                        resume_strategy=_first_nonempty(pending_dict.get("resume_strategy"), "resume_original_task"),
                    )
                else:
                    clear_fields.append("pending_clarification")
                    clear_fields.append("pending_clarification_meta")
                clear_fields.append("current_shop")
                clear_fields.append("current_shop_meta")
        else:
            clear_fields.append("pending_clarification")
            clear_fields.append("pending_clarification_meta")

        return {
            "set_fields": set_fields,
            "clear_fields": clear_fields,
            "task_type": task_type,
            "resolve_shop_status": resolve_shop_status,
            "pending_check_result": pending_check_result,
        }

    if resolve_shop_status in {"NOT_FOUND", ""} and workflow_name != "exploration_planning":
        if task_type_value == TaskType.recommendation.value and recommendation_list:
            pass
        elif task_type_value == TaskType.comparison.value and (
            comparison_result is not None
            or comparison_targets
            or comparison_resolution_targets
            or comparison_target_resolution
            or pending_dict is not None
        ):
            pass
        else:
            return {
                "set_fields": {},
                "clear_fields": [],
                "task_type": task_type,
                "resolve_shop_status": resolve_shop_status,
                "pending_check_result": pending_check_result,
            }

    if workflow_name == "exploration_planning":
        clear_fields.extend(["current_shop", "current_shop_meta"])
        clear_fields.extend(["last_recommendation_list", "last_recommendation_list_meta"])
        clear_fields.extend(["pending_clarification", "pending_clarification_meta"])
        return {
            "set_fields": set_fields,
            "clear_fields": clear_fields,
            "task_type": task_type,
            "resolve_shop_status": resolve_shop_status,
            "pending_check_result": pending_check_result,
        }

    return {
        "set_fields": set_fields,
        "clear_fields": clear_fields,
        "task_type": task_type,
        "resolve_shop_status": resolve_shop_status,
        "pending_check_result": pending_check_result,
    }
