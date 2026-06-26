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
    EvidenceReviewResult,
    FacetEvidence,
    ToolStatus,
)
from ...observability.file_logger import log_kv
from ..policies.review_policy import NextAction
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

    # Classify required facets
    for fe in required_evidence:
        if fe.status == ToolStatus.OK:
            result.required_ok.append(fe.facet)
        elif fe.status == ToolStatus.EMPTY:
            result.required_empty.append(fe.facet)
        elif fe.status == ToolStatus.UNKNOWN:
            result.required_unknown.append(fe.facet)
        elif fe.status in (ToolStatus.FAILED, ToolStatus.TIMEOUT, ToolStatus.UNSUPPORTED):
            result.required_failed.append(fe.facet)

    # Classify optional facets
    for fe in optional_evidence:
        if fe.status == ToolStatus.OK:
            result.optional_ok.append(fe.facet)
        elif fe.status == ToolStatus.EMPTY:
            result.optional_empty.append(fe.facet)
        elif fe.status == ToolStatus.UNKNOWN:
            result.optional_unknown.append(fe.facet)
        elif fe.status in (ToolStatus.FAILED, ToolStatus.TIMEOUT, ToolStatus.UNSUPPORTED):
            result.optional_failed.append(fe.facet)

    # Detect unknown_as_false and failed_as_empty
    result.unknown_as_false_detected = _detect_unknown_as_false(
        required_evidence, optional_evidence, evidence_pack,
    )
    if tool_results is not None:
        result.failed_as_empty_detected = _detect_failed_as_empty(tool_results)

    # --- Decision logic ---
    all_required_determinate = (
        not result.required_unknown and not result.required_failed
    )
    all_optional_determinate = (
        not result.optional_unknown and not result.optional_failed
    )
    has_required = bool(req)
    total_required = len(req)

    if not has_required or total_required == 0:
        # No required facets → sufficient by default
        result.next_action = NextAction.FINISH
        result.status = "sufficient"
        result.reason = "no_required_facets"
    elif all_required_determinate:
        if all_optional_determinate:
            result.next_action = NextAction.FINISH
            result.status = "sufficient"
            result.reason = "all_facets_determinate"
        else:
            # Optional indeterminate → can degrade
            result.next_action = NextAction.DEGRADE_ANSWER
            result.can_degrade = True
            result.status = "degraded_optional"
            unknown_or_failed = result.optional_unknown + result.optional_failed
            result.reason = f"optional_facets_indeterminate: {unknown_or_failed}"
    else:
        # Some required facets are indeterminate
        unknown_or_failed = result.required_unknown + result.required_failed
        all_required_indeterminate = len(unknown_or_failed) == total_required

        if all_required_indeterminate:
            # All required facets failed / unknown → FALLBACK
            result.next_action = NextAction.FALLBACK
            result.status = "insufficient"
            result.reason = f"all_required_facets_indeterminate: {unknown_or_failed}"
        elif unknown_or_failed and result.required_ok:
            # Some required OK, some not → DEGRADE_ANSWER if retriable would be wasteful
            # For P1, degrade rather than full replan (no expand_search loop)
            if result.unknown_as_false_detected or result.failed_as_empty_detected:
                result.next_action = NextAction.DEGRADE_ANSWER
                result.can_degrade = True
                result.status = "degraded_with_warnings"
                result.reason = (
                    f"required_facets_indeterminate: {unknown_or_failed}"
                    f" (unknown_as_false={result.unknown_as_false_detected}"
                    f", failed_as_empty={result.failed_as_empty_detected})"
                )
            else:
                # P1: REPLAN_EVIDENCE degrades to DEGRADE_ANSWER (no expand_search loop)
                result.next_action = NextAction.REPLAN_EVIDENCE
                result.can_degrade = True
                result.status = "partial_insufficient"
                result.reason = f"required_facets_indeterminate: {unknown_or_failed}"
        else:
            # Some required unknown/failed but no OK results yet
            # Check retriability heuristic
            result.next_action = NextAction.REPLAN_EVIDENCE
            result.status = "insufficient"
            result.reason = f"required_facets_indeterminate_no_ok: {unknown_or_failed}"

    tool_results_missing = not isinstance(tool_results, dict) or not bool(tool_results)
    result.evidence_incomplete = tool_results_missing or result.next_action in (
        NextAction.REPLAN_EVIDENCE,
        NextAction.CLARIFY,
        NextAction.FALLBACK,
    )

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
    }

    _logger.debug(
        "EvidenceReview: next_action=%s status=%s required_ok=%d required_failed=%d",
        result.next_action, result.status,
        len(result.required_ok), len(result.required_failed),
    )

    return result


def review_evidence_with_llm(
    goal: LocalLifeGoalDraft,
    evidence_pack: dict[str, Any],
    tool_results: dict[str, Any] | None = None,
    *,
    candidate_review: Any = None,
    llm_call: Callable[..., dict[str, Any]] | None = None,
    strict: bool = False,
) -> tuple[EvidenceReviewResult | None, dict[str, Any]]:
    """Run evidence sufficiency review through an LLM."""
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
    replacements = {
        "{{GOAL_PLAN}}": goal.model_dump() if hasattr(goal, "model_dump") else dict(goal),
        "{{EVIDENCE_PACK}}": evidence_pack,
        "{{TOOL_RESULTS}}": tool_results or {},
        "{{CANDIDATE_REVIEW}}": candidate_review.model_dump() if hasattr(candidate_review, "model_dump") else (candidate_review or {}),
    }
    try:
        llm_result = invoke_structured_llm(
            prompt_name="evidence_sufficiency_review",
            replacements=replacements,
            response_validator=EvidenceReviewResult.model_validate,
            llm_call=llm_call,
        )
    except Exception as exc:
        error = {"error_code": "EVIDENCE_REVIEW_PROMPT_ERROR", "error_message": str(exc), "llm_backend": "", "raw": ""}
        log_kv(_logger, logging.ERROR, "[EVIDENCE_REVIEW_ERROR]", tone="error", error=error)
        if strict:
            return None, error
        review = review_evidence(goal, evidence_pack, tool_results)
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
        review = review_evidence(goal, evidence_pack, tool_results)
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
        review = review_evidence(goal, evidence_pack, tool_results)
        log_kv(_logger, logging.WARNING, "[EVIDENCE_REVIEW_FALLBACK]", tone="warn", review=review, error=error)
        return review, error

    review = model
    review.review_source = review.review_source or "llm_evidence_review"
    review.recommended_next_action = review.recommended_next_action or str(getattr(review.next_action, "value", review.next_action))
    log_kv(
        _logger,
        logging.INFO,
        "[EVIDENCE_REVIEW_RESULT]",
        tone="llm",
        llm_backend=llm_result.get("llm_backend", ""),
        review=review,
    )
    return review, {
        "error_code": "",
        "error_message": "",
        "llm_backend": llm_result.get("llm_backend", ""),
        "raw": llm_result.get("raw", ""),
    }
