"""EvidenceReview — checks evidence sufficiency and prevents unknown_as_false / failed_as_empty.

P1 responsibility:
  - Check required facets have determinate results (ok / empty)
  - Detect indeterminate results (unknown / failed / timeout / unsupported)
  - Prevent unknown_as_false: unknown must not be verbalised as "no"
  - Prevent failed_as_empty: failed must not be verbalised as "none"
  - Decide next_action: FINISH / REPLAN_EVIDENCE / DEGRADE_ANSWER / FALLBACK / CLARIFY
  - Not modify ToolResult or EvidencePack facts
  - Write review_results.evidence_review to GraphState
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from ...domain.candidate import GoalType, LocalLifeGoalDraft
from ...domain.evidence import (
    FAILURE_STATUSES,
    FINAL_STATUSES,
    EvidenceReviewAction,
    EvidenceReviewResult,
    FacetEvidence,
    ToolFailure,
    ToolFailureType,
    ToolStatus,
)
from ...observability.file_logger import log_kv
from ..policies.review_policy import NextAction
from ..freshness.freshness_policy import FreshnessClass, freshness_policy_for_facet
from ..llm_utils import invoke_structured_llm, model_validate_or_error

_logger = logging.getLogger(__name__)


def _classify_status(raw_status: str) -> ToolStatus:
    """Map any status string to the canonical ToolStatus set."""
    s = str(raw_status).strip().lower()
    if s in ("ok", "partial"):
        return ToolStatus.OK
    if s in ("empty",):
        return ToolStatus.EMPTY
    if s in ("timeout",):
        return ToolStatus.TIMEOUT
    if s in ("unsupported",):
        return ToolStatus.UNSUPPORTED
    if s in ("failed", "error", "circuit_open", "backend_unavailable"):
        return ToolStatus.FAILED
    return ToolStatus.UNKNOWN


def _facet_statuses_from_evidence_pack(
    evidence_pack: dict[str, Any],
    required_facets: list[str],
    optional_facets: list[str],
) -> tuple[list[FacetEvidence], list[FacetEvidence]]:
    """Extract per-facet status from EvidencePack.

    Returns (required_evidence, optional_evidence) lists.
    """
    facet_results = list(evidence_pack.get("facet_results") or [])
    evidence_items = list(evidence_pack.get("evidence_items") or [])

    required_list: list[FacetEvidence] = []
    optional_list: list[FacetEvidence] = []
    seen: set[str] = set()

    for item in facet_results:
        if not isinstance(item, dict):
            continue
        facet = str(item.get("facet", "") or "").strip()
        if not facet:
            continue
        # Deduplicate by facet
        if facet in seen:
            continue
        seen.add(facet)

        raw_status = str(item.get("result_status") or item.get("status") or "unknown")
        is_required = facet in required_facets
        fe = FacetEvidence(
            shop_id=str(item.get("shop_id", "") or ""),
            shop_name=str(item.get("shop_name", "") or ""),
            facet=facet,
            tool_name=str(item.get("tool_name", "") or ""),
            status=_classify_status(raw_status),
            required=is_required,
            payload=item,
        )
        if is_required:
            required_list.append(fe)
        else:
            optional_list.append(fe)

    # If facet_results is empty, fall back to evidence_items
    if not facet_results:
        for item in evidence_items:
            if not isinstance(item, dict):
                continue
            facet = str(item.get("facet", "") or "").strip()
            if not facet or facet in seen:
                continue
            seen.add(facet)
            raw_status = str(item.get("result_status") or "unknown")
            is_required = facet in required_facets
            fe = FacetEvidence(
                shop_id=str(item.get("shop_id", "") or ""),
                shop_name=str(item.get("shop_name", "") or ""),
                facet=facet,
                tool_name=str(item.get("tool_name", "") or ""),
                status=_classify_status(raw_status),
                required=is_required,
                payload=item,
            )
            if is_required:
                required_list.append(fe)
            else:
                optional_list.append(fe)

    # Add required_facets with no result as UNKNOWN
    for rf in required_facets:
        if rf not in seen:
            required_list.append(
                FacetEvidence(facet=rf, status=ToolStatus.UNKNOWN, required=True)
            )

    return required_list, optional_list


def _detect_unknown_as_false(
    required_list: list[FacetEvidence],
    optional_list: list[FacetEvidence],
    evidence_pack: dict[str, Any],
) -> bool:
    """Detect if any indeterminate status could be verbalised as false/negative.

    Heuristic: if a facet result has unknown/failed/timeout/unsupported status
    but the EvidencePack contains no corresponding unknown_items entry,
    there is a risk of unknown_as_false.
    """
    unknown_items = list(evidence_pack.get("unknown_items", []) or [])
    unknown_facets_in_pack = {
        str(u.get("facet", "")).strip() for u in unknown_items if isinstance(u, dict)
    }
    all_items = required_list + optional_list
    for fe in all_items:
        if fe.status in FAILURE_STATUSES:
            if fe.facet not in unknown_facets_in_pack:
                return True
    return False


def _detect_failed_as_empty(
    tool_results: dict[str, Any],
) -> bool:
    """Detect if a failed tool result is being treated as empty.

    Checks if any tool result has a failure status but the associated facet
    result shows 'empty' or 'ok' status (i.e. the status was not propagated).
    """
    if not isinstance(tool_results, dict):
        return False
    for call_id, result in tool_results.items():
        if not isinstance(result, dict):
            continue
        raw_status = str(result.get("result_status") or "unknown")
        success = bool(result.get("success", False))
        # If the tool says failed but result_status is ok/empty -> mismatch
        if not success and raw_status in ("ok", "empty"):
            return True
        # If result_status is failure but there's no error_code -> suspicious
        if raw_status in ("failed", "error", "timeout") and not result.get("error_code"):
            return True
    return False


def _tool_failure_type(status: ToolStatus, raw_status: str) -> ToolFailureType:
    if status == ToolStatus.TIMEOUT or raw_status == "timeout":
        return ToolFailureType.TIMEOUT
    if raw_status in {"network_error", "network"}:
        return ToolFailureType.NETWORK_ERROR
    if raw_status in {"backend_error", "backend_unavailable", "circuit_open"}:
        return ToolFailureType.BACKEND_ERROR
    if raw_status in {"invalid_response", "invalid", "malformed"}:
        return ToolFailureType.INVALID_RESPONSE
    if status == ToolStatus.UNSUPPORTED or raw_status == "unsupported":
        return ToolFailureType.UNSUPPORTED_FACET
    if raw_status in {"missing_input", "missing", "invalid_argument"}:
        return ToolFailureType.MISSING_INPUT
    if raw_status == "empty":
        return ToolFailureType.EMPTY_RESULT
    return ToolFailureType.UNKNOWN


def _is_retryable_failure(failure_type: ToolFailureType) -> bool:
    return failure_type in {
        ToolFailureType.TIMEOUT,
        ToolFailureType.NETWORK_ERROR,
        ToolFailureType.BACKEND_ERROR,
    }


def _normalise_str_list(values: Any) -> list[str]:
    result: list[str] = []
    if isinstance(values, (list, tuple, set)):
        iterable = values
    elif values is None:
        iterable = []
    else:
        iterable = [values]
    for item in iterable:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _has_location_required_failure(tool_results: dict[str, Any] | None) -> bool:
    if not isinstance(tool_results, dict):
        return False
    for result in tool_results.values():
        if isinstance(result, dict):
            result_dict = result
        else:
            model_dump = getattr(result, "model_dump", None)
            result_dict = model_dump() if callable(model_dump) else {}
        if str(result_dict.get("error_code", "") or "").strip().upper() == "LOCATION_REQUIRED":
            return True
    return False


def _semantic_snapshot_from_pack(evidence_pack: dict[str, Any]) -> dict[str, Any]:
    semantic_frame = dict(evidence_pack.get("semantic_frame") or {})
    exploration_stages = [
        item if isinstance(item, dict) else {}
        for item in (evidence_pack.get("exploration_stages") or semantic_frame.get("exploration_stages") or [])
    ]
    stage_queries = _normalise_str_list(evidence_pack.get("stage_queries") or semantic_frame.get("stage_queries"))
    stage_evidence_requirements = [
        _normalise_str_list(item)
        for item in (evidence_pack.get("stage_evidence_requirements") or semantic_frame.get("stage_evidence_requirements") or [])
    ]
    stage_statuses = _normalise_str_list(evidence_pack.get("stage_statuses") or semantic_frame.get("stage_statuses"))
    unknown_fields = _normalise_str_list(evidence_pack.get("unknown_fields") or semantic_frame.get("unknown_fields"))
    failed_tools = _normalise_str_list(evidence_pack.get("failed_tools") or semantic_frame.get("failed_tools"))
    partial_fields = _normalise_str_list(evidence_pack.get("partial_fields") or semantic_frame.get("partial_fields"))
    unsupported_reasons = _normalise_str_list(evidence_pack.get("unsupported_reasons") or semantic_frame.get("unsupported_reasons"))
    router_policy_conflicts = _normalise_str_list(evidence_pack.get("router_policy_conflicts") or semantic_frame.get("router_policy_conflicts"))
    grounding_status = str(evidence_pack.get("grounding_status") or semantic_frame.get("grounding_status") or "").strip().lower()
    missing_slot_type = str(evidence_pack.get("missing_slot_type") or semantic_frame.get("missing_slot_type") or "").strip().lower()
    comparison_support_status = str(evidence_pack.get("comparison_support_status") or semantic_frame.get("comparison_support_status") or "").strip().lower()
    facet_statuses = dict(evidence_pack.get("facet_statuses") or semantic_frame.get("facet_statuses") or {})
    grounded_facts = dict(evidence_pack.get("grounded_facts") or semantic_frame.get("grounded_facts") or {})
    facet_reasons = dict(evidence_pack.get("facet_reasons") or semantic_frame.get("facet_reasons") or {})
    evidence_status = str(evidence_pack.get("evidence_status") or "").strip().lower()
    if not evidence_status:
        if any(status in {"failed", "timeout", "unsupported"} for status in stage_statuses) or failed_tools:
            evidence_status = "failed"
        elif any(status in {"partial"} for status in stage_statuses) or partial_fields:
            evidence_status = "partial"
        elif any(status in {"unknown"} for status in stage_statuses) or unknown_fields:
            evidence_status = "unknown"
        elif any(status in {"empty"} for status in stage_statuses):
            evidence_status = "empty"
        else:
            evidence_status = "grounded" if semantic_frame or evidence_pack.get("facet_results") else "unknown"
    return {
        "semantic_frame": semantic_frame,
        "semantic_parse_source": str(evidence_pack.get("semantic_parse_source") or semantic_frame.get("semantic_parse_source") or "").strip(),
        "grounding_status": grounding_status,
        "missing_slot_type": missing_slot_type,
        "router_policy_decision": dict(evidence_pack.get("router_policy_decision") or semantic_frame.get("router_policy_decision") or {}),
        "router_policy_conflicts": router_policy_conflicts,
        "conversation_continuity": dict(evidence_pack.get("conversation_continuity") or semantic_frame.get("conversation_continuity") or {}),
        "exploration_stages": exploration_stages,
        "stage_queries": stage_queries,
        "stage_evidence_requirements": stage_evidence_requirements,
        "stage_statuses": stage_statuses,
        "scene": str(evidence_pack.get("scene") or semantic_frame.get("scene") or "").strip(),
        "time": str(evidence_pack.get("time") or semantic_frame.get("time") or "").strip(),
        "location": dict(evidence_pack.get("location") or semantic_frame.get("location") or {}),
        "facet_statuses": facet_statuses,
        "grounded_facts": grounded_facts,
        "facet_reasons": facet_reasons,
        "evidence_status": evidence_status,
        "comparison_support_status": comparison_support_status,
        "ranking_preserved": bool(evidence_pack.get("ranking_preserved", semantic_frame.get("ranking_preserved", True))),
        "unsupported_reasons": unsupported_reasons,
        "unknown_fields": unknown_fields,
        "failed_tools": failed_tools,
        "partial_fields": partial_fields,
    }


def _candidate_count_from_pack(evidence_pack: dict[str, Any]) -> int:
    ranking_snapshot = evidence_pack.get("ranking_snapshot") or {}
    comparison_matrix = evidence_pack.get("comparison_matrix") or {}
    targets = evidence_pack.get("target_shop_ids") or []
    ranked = ranking_snapshot.get("ranked") or ranking_snapshot.get("ranked_shops") or ranking_snapshot.get("shops") or []
    rows = comparison_matrix.get("rows") or comparison_matrix.get("overall_ranked") or []
    if isinstance(rows, list) and rows:
        return len(rows)
    if isinstance(ranked, list) and ranked:
        return len(ranked)
    if isinstance(targets, list):
        return len([item for item in targets if str(item).strip()])
    return 0


def _evidence_count_from_pack(evidence_pack: dict[str, Any]) -> int:
    facet_results = evidence_pack.get("facet_results") or []
    evidence_items = evidence_pack.get("evidence_items") or []
    unknown_items = evidence_pack.get("unknown_items") or []
    counts = 0
    for item in (facet_results, evidence_items, unknown_items):
        if isinstance(item, list):
            counts += len(item)
    return counts


def _compact_candidate_review(candidate_review: Any) -> dict[str, Any]:
    if candidate_review is None:
        return {}
    review = candidate_review.model_dump() if hasattr(candidate_review, "model_dump") else (candidate_review if isinstance(candidate_review, dict) else {})
    if not isinstance(review, dict):
        return {}
    compact: dict[str, Any] = {}
    for key in ("status", "reason", "next_action", "review_source", "candidate_count", "missing_fields", "uncertain_fields"):
        if key in review and review.get(key) not in (None, "", [], {}):
            compact[key] = review.get(key)
    candidates = review.get("candidates") or review.get("ranked") or []
    if isinstance(candidates, list):
        compact["candidates"] = []
        for item in candidates[:5]:
            if isinstance(item, dict):
                compact["candidates"].append(
                    {
                        "shop_id": item.get("shop_id", ""),
                        "shop_name": item.get("shop_name", ""),
                        "status": item.get("status", ""),
                        "reason": item.get("reason", ""),
                    }
                )
    return compact


def _build_evidence_review_summary(
    goal: LocalLifeGoalDraft,
    evidence_pack: dict[str, Any],
    tool_results: dict[str, Any] | None,
    candidate_review: Any,
    precheck: EvidenceReviewResult,
) -> dict[str, Any]:
    semantic_snapshot = _semantic_snapshot_from_pack(evidence_pack)
    summary = {
        "goal": {
            "goal_type": getattr(goal.goal_type, "value", goal.goal_type),
            "required_facets": list(goal.required_facets or []),
            "optional_facets": list(goal.optional_facets or []),
        },
        "precheck": {
            "status": precheck.status,
            "next_action": str(getattr(precheck.next_action, "value", precheck.next_action)),
            "reason": precheck.reason,
            "candidate_count": _candidate_count_from_pack(evidence_pack),
            "evidence_count": _evidence_count_from_pack(evidence_pack),
        },
        "evidence": {
            "semantic_parse_source": semantic_snapshot["semantic_parse_source"],
            "grounding_status": semantic_snapshot["grounding_status"],
            "missing_slot_type": semantic_snapshot["missing_slot_type"],
            "evidence_status": semantic_snapshot["evidence_status"],
            "comparison_support_status": semantic_snapshot["comparison_support_status"],
            "ranking_preserved": semantic_snapshot["ranking_preserved"],
            "facet_statuses": semantic_snapshot["facet_statuses"],
            "grounded_facts": semantic_snapshot["grounded_facts"],
            "facet_reasons": semantic_snapshot["facet_reasons"],
            "failed_tools": semantic_snapshot["failed_tools"],
            "unknown_fields": semantic_snapshot["unknown_fields"],
            "partial_fields": semantic_snapshot["partial_fields"],
            "candidate_count": _candidate_count_from_pack(evidence_pack),
            "evidence_count": _evidence_count_from_pack(evidence_pack),
            "tool_results": {
                key: {
                    "tool_name": value.get("tool_name", ""),
                    "result_status": value.get("result_status", ""),
                    "error_code": value.get("error_code", ""),
                }
                for key, value in (tool_results or {}).items()
                if isinstance(value, dict)
            },
        },
        "candidate_review": _compact_candidate_review(candidate_review),
    }
    return summary


def review_evidence(
    goal: LocalLifeGoalDraft,
    evidence_pack: dict[str, Any],
    tool_results: dict[str, Any] | None = None,
    *,
    required_facets: list[str] | None = None,
    optional_facets: list[str] | None = None,
) -> EvidenceReviewResult:
    """Check evidence sufficiency and produce an EvidenceReviewResult.

    Args:
        goal: The local life goal draft.
        evidence_pack: The EvidencePack dict (or serialised EvidencePack).
        tool_results: Raw tool results for failed_as_empty detection.
        required_facets: Override for required facets (default from goal).
        optional_facets: Override for optional facets (default from goal).

    Returns:
        EvidenceReviewResult with next_action and detailed trace.
    """
    req = required_facets if required_facets is not None else list(goal.required_facets or [])
    opt = optional_facets if optional_facets is not None else list(goal.optional_facets or [])

    required_evidence, optional_evidence = _facet_statuses_from_evidence_pack(
        evidence_pack, req, opt,
    )

    fr = evidence_pack.get("facet_results") if isinstance(evidence_pack, dict) else []
    _logger.debug(
        "review_evidence req=%s opt=%s required=%s optional=%s facet_results=%d",
        req,
        opt,
        [
            {"facet": fe.facet, "status": str(fe.status), "tool_name": fe.tool_name}
            for fe in required_evidence
        ],
        [
            {"facet": fe.facet, "status": str(fe.status), "tool_name": fe.tool_name}
            for fe in optional_evidence
        ],
        len(list(fr or [])),
    )

    result = EvidenceReviewResult()
    semantic_snapshot = _semantic_snapshot_from_pack(evidence_pack)
    result.semantic_frame = semantic_snapshot["semantic_frame"]
    result.semantic_parse_source = semantic_snapshot["semantic_parse_source"]
    result.grounding_status = semantic_snapshot["grounding_status"]
    result.missing_slot_type = semantic_snapshot["missing_slot_type"]
    result.router_policy_decision = semantic_snapshot["router_policy_decision"]
    result.router_policy_conflicts = list(semantic_snapshot["router_policy_conflicts"])
    result.conversation_continuity = semantic_snapshot["conversation_continuity"]
    result.exploration_stages = list(semantic_snapshot["exploration_stages"])
    result.stage_queries = list(semantic_snapshot["stage_queries"])
    result.stage_evidence_requirements = list(semantic_snapshot["stage_evidence_requirements"])
    result.stage_statuses = list(semantic_snapshot["stage_statuses"])
    result.scene = semantic_snapshot["scene"]
    result.time = semantic_snapshot["time"]
    result.location = semantic_snapshot["location"]
    result.facet_statuses = dict(semantic_snapshot["facet_statuses"])
    result.grounded_facts = dict(semantic_snapshot["grounded_facts"])
    result.facet_reasons = dict(semantic_snapshot["facet_reasons"])
    result.evidence_status = semantic_snapshot["evidence_status"]
    result.comparison_support_status = semantic_snapshot["comparison_support_status"]
    result.ranking_preserved = bool(semantic_snapshot["ranking_preserved"])
    result.unsupported_reasons = list(semantic_snapshot["unsupported_reasons"])
    result.unknown_fields = list(semantic_snapshot["unknown_fields"])
    result.failed_tools = list(semantic_snapshot["failed_tools"])
    result.partial_fields = list(semantic_snapshot["partial_fields"])
    retry_budget_remaining = int(evidence_pack.get("retry_budget_remaining", 1) or 0)
    expand_search_budget_remaining = int(evidence_pack.get("expand_search_budget_remaining", 1) or 0)
    replan_budget_remaining = int(evidence_pack.get("replan_budget_remaining", 1) or 0)
    rewrite_budget_remaining = int(evidence_pack.get("rewrite_budget_remaining", 1) or 0)
    tool_round_budget_remaining = int(evidence_pack.get("tool_round_budget_remaining", 1) or 0)
    facet_enrich_budget_remaining = int(evidence_pack.get("facet_enrich_budget_remaining", 1) or 0)
    deadline_remaining_ms = evidence_pack.get("deadline_remaining_ms")
    budget_context_snapshot = dict(evidence_pack.get("budget_context_snapshot") or {})
    budget_exhausted_reasons = _normalise_str_list(evidence_pack.get("budget_exhausted_reasons"))
    stale_facets = _normalise_str_list(evidence_pack.get("stale_facets"))
    expired_facets = _normalise_str_list(evidence_pack.get("expired_facets"))
    disclaimer_facets = _normalise_str_list(evidence_pack.get("disclaimer_facets"))
    missing_input = [str(item).strip() for item in (evidence_pack.get("missing_input") or []) if str(item).strip()]
    clarification_needed = bool(evidence_pack.get("clarification_needed", False))
    location_required_failure = _has_location_required_failure(tool_results)
    if location_required_failure and "need_user_location" not in missing_input:
        missing_input.append("need_user_location")

    # Classify required facets
    answerable_facets: list[str] = []
    unknown_facets: list[str] = []
    failed_facets: list[str] = []
    retryable_facets: list[str] = []
    tool_failures: list[ToolFailure] = []
    for fe in required_evidence:
        if fe.status == ToolStatus.OK:
            result.required_ok.append(fe.facet)
            if fe.facet not in answerable_facets:
                answerable_facets.append(fe.facet)
        elif fe.status == ToolStatus.EMPTY:
            result.required_empty.append(fe.facet)
            if fe.facet not in unknown_facets:
                unknown_facets.append(fe.facet)
        elif fe.status == ToolStatus.UNKNOWN:
            result.required_unknown.append(fe.facet)
            if fe.facet not in unknown_facets:
                unknown_facets.append(fe.facet)
        elif fe.status in (ToolStatus.FAILED, ToolStatus.TIMEOUT, ToolStatus.UNSUPPORTED):
            result.required_failed.append(fe.facet)
            if fe.facet not in failed_facets:
                failed_facets.append(fe.facet)
            failure_type = _tool_failure_type(fe.status, str(fe.payload.get("result_status") or "unknown").lower())
            retryable = _is_retryable_failure(failure_type)
            if retryable and fe.facet not in retryable_facets:
                retryable_facets.append(fe.facet)
            tool_failures.append(
                ToolFailure(
                    tool_name=fe.tool_name or None,
                    facet=fe.facet or None,
                    target_shop_id=fe.shop_id or None,
                    failure_type=failure_type,
                    retryable=retryable,
                    message=str(fe.payload.get("error_message", "") or "") or None,
                    evidence_ref=str(fe.payload.get("evidence_id", "") or "") or None,
                )
            )

    # Classify optional facets
    for fe in optional_evidence:
        if fe.status == ToolStatus.OK:
            result.optional_ok.append(fe.facet)
            if fe.facet not in answerable_facets:
                answerable_facets.append(fe.facet)
        elif fe.status == ToolStatus.EMPTY:
            result.optional_empty.append(fe.facet)
            if fe.facet not in unknown_facets:
                unknown_facets.append(fe.facet)
        elif fe.status == ToolStatus.UNKNOWN:
            result.optional_unknown.append(fe.facet)
            if fe.facet not in unknown_facets:
                unknown_facets.append(fe.facet)
        elif fe.status in (ToolStatus.FAILED, ToolStatus.TIMEOUT, ToolStatus.UNSUPPORTED):
            result.optional_failed.append(fe.facet)
            if fe.facet not in failed_facets:
                failed_facets.append(fe.facet)
            failure_type = _tool_failure_type(fe.status, str(fe.payload.get("result_status") or "unknown").lower())
            retryable = _is_retryable_failure(failure_type)
            if retryable and fe.facet not in retryable_facets:
                retryable_facets.append(fe.facet)
            tool_failures.append(
                ToolFailure(
                    tool_name=fe.tool_name or None,
                    facet=fe.facet or None,
                    target_shop_id=fe.shop_id or None,
                    failure_type=failure_type,
                    retryable=retryable,
                    message=str(fe.payload.get("error_message", "") or "") or None,
                    evidence_ref=str(fe.payload.get("evidence_id", "") or "") or None,
                )
            )

    semantic_missing = list(dict.fromkeys([
        *(semantic_snapshot["unknown_fields"] or []),
        *(semantic_snapshot["failed_tools"] or []),
        *(semantic_snapshot["partial_fields"] or []),
        *(semantic_snapshot["unsupported_reasons"] or []),
        *(semantic_snapshot["router_policy_conflicts"] or []),
    ]))
    if semantic_missing:
        result.missing_evidence = list(dict.fromkeys(result.missing_evidence + semantic_missing))
    if semantic_snapshot["exploration_stages"]:
        incomplete_stage_statuses = [
            status for status in semantic_snapshot["stage_statuses"]
            if status in {"unknown", "failed", "empty", "partial"}
        ]
        if incomplete_stage_statuses:
            result.unsafe_answer_risks = list(dict.fromkeys(result.unsafe_answer_risks + [
                f"exploration_stage:{status}" for status in incomplete_stage_statuses
            ]))
            result.evidence_incomplete = True
    if semantic_snapshot["missing_slot_type"] in {
        "missing_location",
        "missing_shop",
        "missing_comparison_targets",
        "missing_exploration_location",
        "missing_category",
    }:
        result.clarification_reason = result.clarification_reason or semantic_snapshot["missing_slot_type"]
        result.action = EvidenceReviewAction.CLARIFY
        result.next_action = NextAction.CLARIFY
        result.status = "insufficient"
        result.reason = result.clarification_reason
        result.next_step = "ask_user_for_missing_input"
    elif semantic_snapshot["grounding_status"] in {"unknown", "partial", "unresolved"}:
        result.unsafe_answer_risks = list(dict.fromkeys(result.unsafe_answer_risks + [f"grounding_status:{semantic_snapshot['grounding_status']}"]))
        if not result.reason:
            result.reason = f"grounding_status:{semantic_snapshot['grounding_status']}"
        result.evidence_incomplete = True
    if semantic_snapshot["comparison_support_status"] and semantic_snapshot["comparison_support_status"] not in {"grounded", "supported", "ok", "sufficient"}:
        result.unsafe_answer_risks = list(dict.fromkeys(result.unsafe_answer_risks + [f"comparison_support_status:{semantic_snapshot['comparison_support_status']}"]))
        if not result.failed_facets and not result.required_failed:
            result.missing_evidence = list(dict.fromkeys(result.missing_evidence + ["comparison_support"]))

    # Detect unknown_as_false and failed_as_empty
    result.unknown_as_false_detected = _detect_unknown_as_false(
        required_evidence, optional_evidence, evidence_pack,
    )
    if tool_results is not None:
        result.failed_as_empty_detected = _detect_failed_as_empty(tool_results)

    result.answerable_facets = list(dict.fromkeys(answerable_facets))
    result.unknown_facets = list(dict.fromkeys(unknown_facets))
    result.failed_facets = list(dict.fromkeys(failed_facets))
    result.retryable_facets = list(dict.fromkeys(retryable_facets))
    result.tool_failures = tool_failures
    result.review_source = result.review_source or "deterministic_review"
    result.review_mode = "deterministic"
    result.review_precheck_status = result.status
    result.review_precheck_reason = result.reason
    result.review_retry_count = 0
    result.candidate_count = _candidate_count_from_pack(evidence_pack)
    result.evidence_count = _evidence_count_from_pack(evidence_pack)
    result.retry_budget_remaining = retry_budget_remaining
    result.expand_search_budget_remaining = expand_search_budget_remaining
    result.replan_budget_remaining = replan_budget_remaining
    result.rewrite_budget_remaining = rewrite_budget_remaining
    result.tool_round_budget_remaining = tool_round_budget_remaining
    result.facet_enrich_budget_remaining = facet_enrich_budget_remaining
    result.deadline_remaining_ms = int(deadline_remaining_ms) if isinstance(deadline_remaining_ms, (int, float)) else None
    result.budget_context_snapshot = budget_context_snapshot
    result.budget_exhausted_reasons = list(dict.fromkeys(budget_exhausted_reasons))
    result.stale_facets = list(dict.fromkeys(stale_facets))
    result.expired_facets = list(dict.fromkeys(expired_facets))
    result.disclaimer_facets = list(dict.fromkeys(disclaimer_facets))

    strong_stale_facets: list[str] = []
    weak_stale_facets: list[str] = []
    location_stale_facets: list[str] = []
    for facet in list(dict.fromkeys(stale_facets + expired_facets)):
        policy = freshness_policy_for_facet(facet)
        if policy.freshness_class == FreshnessClass.STRONG_DYNAMIC:
            strong_stale_facets.append(facet)
        elif policy.freshness_class == FreshnessClass.LOCATION_BOUND:
            location_stale_facets.append(facet)
        elif policy.freshness_class == FreshnessClass.WEAK_DYNAMIC:
            weak_stale_facets.append(facet)
        elif facet not in disclaimer_facets:
            disclaimer_facets.append(facet)
    result.disclaimer_facets = list(dict.fromkeys(result.disclaimer_facets + weak_stale_facets))

    if tool_round_budget_remaining <= 0:
        result.budget_exhausted_reasons.append("tool_round_budget")
    if retry_budget_remaining <= 0:
        result.budget_exhausted_reasons.append("retry_budget")
    if expand_search_budget_remaining <= 0:
        result.budget_exhausted_reasons.append("expand_search_budget")
    if rewrite_budget_remaining <= 0:
        result.budget_exhausted_reasons.append("rewrite_budget")
    if facet_enrich_budget_remaining <= 0:
        result.budget_exhausted_reasons.append("facet_enrich_budget")
    if isinstance(result.deadline_remaining_ms, int) and result.deadline_remaining_ms <= 0:
        result.budget_exhausted_reasons.append("deadline_remaining_ms")
    result.budget_exhausted_reasons = list(dict.fromkeys(result.budget_exhausted_reasons))

    if strong_stale_facets or location_stale_facets:
        for facet in strong_stale_facets + location_stale_facets:
            if facet not in result.unknown_facets:
                result.unknown_facets.append(facet)
            if facet not in result.failed_facets and facet in result.required_failed:
                result.failed_facets.append(facet)
        if result.required_ok and (strong_stale_facets or location_stale_facets):
            if tool_round_budget_remaining <= 0 or result.budget_exhausted_reasons:
                result.action = EvidenceReviewAction.DEGRADE if result.required_ok else EvidenceReviewAction.FALLBACK
                result.next_action = NextAction.DEGRADE_ANSWER if result.required_ok else NextAction.FALLBACK
                result.can_degrade = bool(result.required_ok)
                result.status = "degraded_with_warnings" if result.required_ok else "insufficient"
                missing = strong_stale_facets + location_stale_facets
                result.degrade_reason = f"stale_or_location_bound: {missing}" if result.required_ok else ""
                result.fallback_reason = "" if result.required_ok else f"stale_or_location_bound: {missing}"
                result.reason = result.degrade_reason or result.fallback_reason
                result.next_step = "degrade_answer" if result.required_ok else "fallback"
            else:
                result.action = EvidenceReviewAction.DEGRADE if result.required_ok else EvidenceReviewAction.FALLBACK
                result.next_action = NextAction.DEGRADE_ANSWER if result.required_ok else NextAction.FALLBACK
                result.can_degrade = bool(result.required_ok)
                result.status = "degraded_with_warnings" if result.required_ok else "insufficient"
                missing = strong_stale_facets + location_stale_facets
                result.degrade_reason = f"stale_or_location_bound: {missing}" if result.required_ok else ""
                result.fallback_reason = "" if result.required_ok else f"stale_or_location_bound: {missing}"
                result.reason = result.degrade_reason or result.fallback_reason
                result.next_step = "degrade_answer" if result.required_ok else "fallback"
            result.trace_payload = {
                "required": {},
                "optional": {},
                "stale_facets": result.stale_facets,
                "expired_facets": result.expired_facets,
                "disclaimer_facets": result.disclaimer_facets,
                "budget_exhausted_reasons": result.budget_exhausted_reasons,
                "deadline_remaining_ms": result.deadline_remaining_ms,
            }
            return result

    all_required_answerable = not result.required_unknown and not result.required_failed and not result.required_empty
    all_optional_answerable = not result.optional_unknown and not result.optional_failed and not result.optional_empty
    has_missing_input = bool(missing_input)
    has_required = bool(req)

    if clarification_needed or has_missing_input:
        result.action = EvidenceReviewAction.CLARIFY
        result.next_action = NextAction.CLARIFY
        result.status = "insufficient"
        result.clarification_reason = ", ".join(missing_input) if missing_input else "clarification_needed"
        result.reason = result.clarification_reason
        result.next_step = "ask_user_for_missing_input"
    elif result.required_failed and result.retryable_facets and retry_budget_remaining > 0:
        result.action = EvidenceReviewAction.RETRY
        result.next_action = NextAction.REPLAN_EVIDENCE
        result.status = "retryable_failure"
        result.reason = f"retryable_failure: {result.retryable_facets}"
        result.next_step = "retry_failed_tool_calls"
    elif not has_required:
        result.action = EvidenceReviewAction.PROCEED
        result.next_action = NextAction.FINISH
        result.status = "sufficient"
        result.reason = "no_required_facets"
        result.next_step = "proceed"
    elif result.required_ok and not result.required_unknown and not result.required_failed and result.required_empty:
        # Required facets are answerable except for empty results. Treat this as
        # a safe, already-determinate answer path rather than an iterative replan.
        # This avoids turning "coupon ok + distance empty" into a replan loop.
        result.action = EvidenceReviewAction.DEGRADE
        result.next_action = NextAction.FINISH
        result.can_degrade = True
        result.status = "degraded_with_warnings"
        result.degrade_reason = f"partial_information: {result.required_empty}"
        result.reason = result.degrade_reason
        result.next_step = "proceed"
    elif result.required_ok and (result.required_unknown or result.required_failed):
        if replan_budget_remaining > 0 and tool_round_budget_remaining > 0 and not result.budget_exhausted_reasons:
            result.action = EvidenceReviewAction.REPLAN_MISSING_FACETS
            result.next_action = NextAction.REPLAN_EVIDENCE
            result.status = "degraded_with_warnings"
            unknown_or_failed = result.required_unknown + result.required_failed
            result.missing_facets = list(dict.fromkeys(unknown_or_failed))
            result.reason = f"required_facets_indeterminate: {unknown_or_failed}"
            result.next_step = "replan_missing_facets"
        else:
            result.action = EvidenceReviewAction.DEGRADE
            result.next_action = NextAction.DEGRADE_ANSWER
            result.can_degrade = True
            result.status = "degraded_with_warnings"
            unknown_or_failed = result.required_unknown + result.required_failed
            result.degrade_reason = f"partial_information: {unknown_or_failed}"
            result.reason = result.degrade_reason
            result.next_step = "degrade_answer"
    elif result.required_unknown and replan_budget_remaining > 0 and not result.required_failed and tool_round_budget_remaining > 0:
        result.action = EvidenceReviewAction.REPLAN_MISSING_FACETS
        result.next_action = NextAction.REPLAN_EVIDENCE
        result.status = "partial_insufficient"
        result.missing_facets = list(dict.fromkeys(result.required_unknown))
        result.reason = f"missing_facets: {result.missing_facets}"
        result.next_step = "replan_missing_facets"
    elif (result.required_empty or result.optional_empty) and expand_search_budget_remaining > 0 and tool_round_budget_remaining > 0:
        result.action = EvidenceReviewAction.EXPAND_SEARCH
        result.next_action = NextAction.FINISH
        result.status = "sufficient"
        result.unknown_facets = list(dict.fromkeys(result.unknown_facets + result.required_empty + result.optional_empty))
        result.reason = "all_facets_determinate"
        result.next_step = "expand_search"
    elif all_required_answerable and all_optional_answerable:
        result.action = EvidenceReviewAction.PROCEED
        result.next_action = NextAction.FINISH
        result.status = "sufficient"
        result.reason = "all_facets_determinate"
        result.next_step = "proceed"
    elif result.required_ok:
        result.action = EvidenceReviewAction.DEGRADE
        result.next_action = NextAction.DEGRADE_ANSWER
        result.can_degrade = True
        result.status = "degraded_with_warnings"
        unknown_or_failed = result.required_unknown + result.required_failed + result.required_empty + result.optional_unknown + result.optional_failed + result.optional_empty
        result.degrade_reason = f"partial_information: {unknown_or_failed}"
        result.reason = result.degrade_reason
        result.next_step = "degrade_answer"
    else:
        result.action = EvidenceReviewAction.FALLBACK
        result.next_action = NextAction.FALLBACK
        result.status = "insufficient"
        unknown_or_failed = result.required_unknown + result.required_failed + result.required_empty + result.optional_unknown + result.optional_failed + result.optional_empty
        result.fallback_reason = f"no_answerable_facets: {unknown_or_failed}" if unknown_or_failed else "no_answerable_facets"
        result.reason = result.fallback_reason
        result.next_step = "fallback"

    tool_results_missing = not isinstance(tool_results, dict) or not bool(tool_results)
    result.evidence_incomplete = tool_results_missing or result.next_action in (
        NextAction.REPLAN_EVIDENCE,
        NextAction.CLARIFY,
        NextAction.FALLBACK,
    )
    if not result.required_unknown and not result.required_failed and not result.required_empty:
        result.missing_facets = list(dict.fromkeys(result.missing_facets))

    # Build trace payload
    result.trace_payload = {
        "required": {
            "ok": result.required_ok,
            "empty": result.required_empty,
            "unknown": result.required_unknown,
            "failed": result.required_failed,
        },
        "optional": {
            "ok": result.optional_ok,
            "empty": result.optional_empty,
            "unknown": result.optional_unknown,
            "failed": result.optional_failed,
        },
        "unknown_as_false_detected": result.unknown_as_false_detected,
        "failed_as_empty_detected": result.failed_as_empty_detected,
        "evidence_incomplete": result.evidence_incomplete,
        "next_action": result.next_action,
        "status": result.status,
        "reason": result.reason,
        "action": result.action,
        "review_mode": result.review_mode,
        "review_precheck_status": result.review_precheck_status,
        "review_precheck_reason": result.review_precheck_reason,
        "review_retry_count": result.review_retry_count,
        "candidate_count": result.candidate_count,
        "evidence_count": result.evidence_count,
        "retry_budget_remaining": result.retry_budget_remaining,
        "expand_search_budget_remaining": result.expand_search_budget_remaining,
        "replan_budget_remaining": result.replan_budget_remaining,
        "rewrite_budget_remaining": result.rewrite_budget_remaining,
        "tool_round_budget_remaining": result.tool_round_budget_remaining,
        "facet_enrich_budget_remaining": result.facet_enrich_budget_remaining,
        "deadline_remaining_ms": result.deadline_remaining_ms,
        "budget_exhausted_reasons": result.budget_exhausted_reasons,
        "stale_facets": result.stale_facets,
        "expired_facets": result.expired_facets,
        "disclaimer_facets": result.disclaimer_facets,
        "semantic_frame": result.semantic_frame,
        "semantic_parse_source": result.semantic_parse_source,
        "grounding_status": result.grounding_status,
        "missing_slot_type": result.missing_slot_type,
        "router_policy_decision": result.router_policy_decision,
        "router_policy_conflicts": result.router_policy_conflicts,
        "conversation_continuity": result.conversation_continuity,
        "exploration_stages": result.exploration_stages,
        "stage_queries": result.stage_queries,
        "stage_evidence_requirements": result.stage_evidence_requirements,
        "stage_statuses": result.stage_statuses,
        "scene": result.scene,
        "time": result.time,
        "location": result.location,
        "evidence_status": result.evidence_status,
        "comparison_support_status": result.comparison_support_status,
        "ranking_preserved": result.ranking_preserved,
        "unsupported_reasons": result.unsupported_reasons,
        "unknown_fields": result.unknown_fields,
        "failed_tools": result.failed_tools,
        "partial_fields": result.partial_fields,
    }

    _logger.debug(
        "EvidenceReview: next_action=%s status=%s required_ok=%d required_failed=%d",
        result.next_action, result.status,
        len(result.required_ok), len(result.required_failed),
    )

    return result


def _deep_dump(obj: Any) -> Any:
    """Recursively convert Pydantic models to dicts for JSON-safe serialization."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    if isinstance(obj, dict):
        return {k: _deep_dump(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_deep_dump(v) for v in obj]
    return obj


def review_evidence_with_llm(
    goal: LocalLifeGoalDraft,
    evidence_pack: dict[str, Any],
    tool_results: dict[str, Any] | None = None,
    *,
    candidate_review: Any = None,
    llm_call: Callable[..., dict[str, Any]] | None = None,
    strict: bool = False,
) -> tuple[EvidenceReviewResult | None, dict[str, Any]]:
    """Run evidence sufficiency review through an LLM.

    Note: tool_results values are sanitised via ``_deep_dump`` to ensure
    JSON-serialisable dicts (ToolResult BaseModel → dict).
    """
    log_kv(
        _logger,
        logging.INFO,
        "[EVIDENCE_REVIEW_START]",
        tone="llm",
        goal=goal,
        evidence_pack=evidence_pack,
        tool_results=tool_results or {},
        candidate_review=candidate_review,
        strict=strict,
    )
    precheck = review_evidence(goal, evidence_pack, tool_results)
    precheck.review_mode = "deterministic_precheck"
    precheck.review_precheck_status = precheck.status
    precheck.review_precheck_reason = precheck.reason
    precheck.review_retry_count = 0
    precheck.candidate_count = _candidate_count_from_pack(evidence_pack)
    precheck.evidence_count = _evidence_count_from_pack(evidence_pack)

    should_call_llm = strict or precheck.next_action in {NextAction.REPLAN_EVIDENCE, NextAction.EXPAND_SEARCH}
    if not should_call_llm:
        meta = {
            "error_code": "",
            "error_message": "",
            "llm_backend": "",
            "raw": "",
            "review_mode": "deterministic_precheck",
            "precheck_status": precheck.status,
            "precheck_reason": precheck.reason,
            "candidate_count": precheck.candidate_count,
            "evidence_count": precheck.evidence_count,
        }
        log_kv(
            _logger,
            logging.INFO,
            "[EVIDENCE_REVIEW_SKIP_LLM]",
            tone="route",
            review=precheck,
            review_mode=meta["review_mode"],
            precheck_status=meta["precheck_status"],
            precheck_reason=meta["precheck_reason"],
            candidate_count=meta["candidate_count"],
            evidence_count=meta["evidence_count"],
        )
        return precheck, meta

    replacements = {
        "{{GOAL_PLAN}}": goal.model_dump() if hasattr(goal, "model_dump") else dict(goal),
        "{{EVIDENCE_PACK}}": _build_evidence_review_summary(goal, evidence_pack, tool_results, candidate_review, precheck),
        "{{TOOL_RESULTS}}": _deep_dump(tool_results) if tool_results else {},
        "{{CANDIDATE_REVIEW}}": _compact_candidate_review(candidate_review),
    }
    try:
        llm_result = invoke_structured_llm(
            prompt_name="evidence_sufficiency_review",
            replacements=replacements,
            response_validator=EvidenceReviewResult.model_validate,
            llm_call=llm_call,
            max_retries=0,
        )
    except Exception as exc:
        error = {"error_code": "EVIDENCE_REVIEW_PROMPT_ERROR", "error_message": str(exc), "llm_backend": "", "raw": ""}
        log_kv(_logger, logging.ERROR, "[EVIDENCE_REVIEW_ERROR]", tone="error", error=error)
        if strict:
            return None, error
        review = precheck
        log_kv(_logger, logging.WARNING, "[EVIDENCE_REVIEW_FALLBACK]", tone="warn", review=review, error=error)
        return review, error

    if not llm_result.get("ok"):
        error = {
            "error_code": llm_result.get("error_code") or "EVIDENCE_REVIEW_LLM_FAILED",
            "error_message": llm_result.get("error_message") or "evidence review llm failed",
            "llm_backend": llm_result.get("llm_backend", ""),
            "raw": llm_result.get("raw", ""),
        }
        log_kv(_logger, logging.WARNING, "[EVIDENCE_REVIEW_LLM_FAILED]", tone="warn", error=error)
        if strict:
            return None, error
        review = precheck
        log_kv(_logger, logging.WARNING, "[EVIDENCE_REVIEW_FALLBACK]", tone="warn", review=review, error=error)
        return review, error

    model, validation_error = model_validate_or_error(EvidenceReviewResult, llm_result.get("payload") or {})
    if model is None:
        error = {
            "error_code": "EVIDENCE_REVIEW_SCHEMA_INVALID",
            "error_message": validation_error,
            "llm_backend": llm_result.get("llm_backend", ""),
            "raw": llm_result.get("raw", ""),
        }
        log_kv(_logger, logging.WARNING, "[EVIDENCE_REVIEW_SCHEMA_INVALID]", tone="warn", error=error)
        if strict:
            return None, error
        review = precheck
        log_kv(_logger, logging.WARNING, "[EVIDENCE_REVIEW_FALLBACK]", tone="warn", review=review, error=error)
        return review, error

    review = model
    review.review_source = review.review_source or "llm_evidence_review"
    review.recommended_next_action = review.recommended_next_action or str(getattr(review.next_action, "value", review.next_action))
    review.review_mode = "llm"
    review.review_precheck_status = precheck.status
    review.review_precheck_reason = precheck.reason
    review.review_retry_count = 0
    review.candidate_count = precheck.candidate_count
    review.evidence_count = precheck.evidence_count
    log_kv(
        _logger,
        logging.INFO,
        "[EVIDENCE_REVIEW_RESULT]",
        tone="llm",
        llm_backend=llm_result.get("llm_backend", ""),
        review=review,
        review_mode=review.review_mode,
        precheck_status=review.review_precheck_status,
        precheck_reason=review.review_precheck_reason,
        candidate_count=review.candidate_count,
        evidence_count=review.evidence_count,
    )
    return review, {
        "error_code": "",
        "error_message": "",
        "llm_backend": llm_result.get("llm_backend", ""),
        "raw": llm_result.get("raw", ""),
        "review_mode": review.review_mode,
        "precheck_status": review.review_precheck_status,
        "precheck_reason": review.review_precheck_reason,
        "candidate_count": review.candidate_count,
        "evidence_count": review.evidence_count,
    }
