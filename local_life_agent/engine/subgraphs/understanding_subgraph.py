"""understanding_subgraph — semantic parsing and context recovery.

Parses user intent into a structured semantic frame, validates slot types,
and resolves contextual references (pronouns / ordinals / comparison targets).
"""

from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import ValidationError

from .._compat import (
    _log,
    _run_steps,
    _state_delta,
    _to_dict,
    _unwrap_resolve_shop_result,
    _OUTER_WRAPPER_EXCLUDE_FIELDS,
)
from .._routes import (
    _OUTER_ROUTE_CLARIFY,
    _OUTER_ROUTE_PROCEED,
)
from ...domain.graph_state import GraphState
from ...domain.schemas import SemanticFrame
from ...planning.goal.goal_planner import _infer_explicit_mentions_from_text
from ...semantic.frame_validator import validate_frame
from ...semantic.intent_parser import parse_semantic_frame
from ... import config
from ...observability.file_logger import get_python_service_logger, log_kv

_LOGGER = get_python_service_logger()


def h_understanding_subgraph(state: GraphState) -> dict:
    """Outer wrapper: parse → validate → context recovery → route."""
    before = dict(state)
    log_kv(_LOGGER, logging.INFO, "[SUBGRAPH_ENTER]", tone="route", subgraph="understanding_subgraph", trace_id=state.get("trace_id", ""), top_intent=state.get("top_intent", ""))
    working = _run_steps(state, [_h_semantic_parse])
    if working.get("error_code"):
        after = {
            **working,
            "understanding_route": _OUTER_ROUTE_CLARIFY,
            "response_mode": _OUTER_ROUTE_CLARIFY,
        }
        log_kv(_LOGGER, logging.WARNING, "[ROUTE_DECISION]", tone="warn", subgraph="understanding_subgraph", route=_OUTER_ROUTE_CLARIFY, response_mode=_OUTER_ROUTE_CLARIFY, error_code=working.get("error_code", ""))
        return _state_delta(
            before,
            after,
            always_include={"understanding_route", "response_mode"},
            exclude=_OUTER_WRAPPER_EXCLUDE_FIELDS,
        )
    working = _run_steps(working, [_h_slot_extractor, _h_frame_validator, _h_context_recovery])
    if working.get("error_code"):
        after = {
            **working,
            "understanding_route": _OUTER_ROUTE_CLARIFY,
            "response_mode": _OUTER_ROUTE_CLARIFY,
        }
        log_kv(_LOGGER, logging.WARNING, "[ROUTE_DECISION]", tone="warn", subgraph="understanding_subgraph", route=_OUTER_ROUTE_CLARIFY, response_mode=_OUTER_ROUTE_CLARIFY, error_code=working.get("error_code", ""))
        return _state_delta(
            before,
            after,
            always_include={"understanding_route", "response_mode"},
            exclude=_OUTER_WRAPPER_EXCLUDE_FIELDS,
        )
    after = {
        **working,
        "understanding_route": _OUTER_ROUTE_PROCEED,
        "response_mode": "answer",
    }
    log_kv(_LOGGER, logging.INFO, "[ROUTE_DECISION]", tone="route", subgraph="understanding_subgraph", route=_OUTER_ROUTE_PROCEED, response_mode="answer", semantic_source=working.get("semantic_source", ""))
    return _state_delta(
        before,
        after,
        always_include={"understanding_route", "response_mode"},
        exclude=_OUTER_WRAPPER_EXCLUDE_FIELDS,
    )


# ---------------------------------------------------------------------------
# Internal step handlers
# ---------------------------------------------------------------------------


def _h_semantic_parse(state: GraphState) -> dict:
    txt = state.get("normalized_text", "")
    # lazy-import via graph_builder for test monkeypatch compat
    from ..graph_builder import call_llm as _call_llm
    from ..graph_builder import ensure_real_llm_backend as _ensure_llm_backend
    top_intent = state.get("top_intent")
    top_intent_value = str(getattr(top_intent, "value", top_intent or ""))
    session_state = state.get("session_state_before") or state.get("session_state")
    _ensure_llm_backend()
    try:
        parsed = parse_semantic_frame(
            txt,
            top_intent_value,
            llm_call=_call_llm,
            allow_fallback=config.SEMANTIC_FALLBACK_ENABLED,
            session_state=session_state,
        )
    except TypeError:
        parsed = parse_semantic_frame(
            txt,
            top_intent_value,
            llm_call=_call_llm,
            session_state=session_state,
        )
    frame = parsed.get("semantic_frame")
    error_code = parsed.get("error_code", "")
    error_message = parsed.get("error_message", "")
    semantic_source = str(parsed.get("semantic_source", "") or "")
    llm_backend = str(parsed.get("llm_backend", "") or "")
    fallback_reason = str(parsed.get("fallback_reason", "") or "")
    llm_called = bool(parsed.get("llm_called", False))
    safe_validation_message = "本地生活相关问题请提供完整店名或重新描述。"
    if error_code == "SCHEMA_VALIDATION_FAILED":
        return {
            "semantic_frame": None,
            "error_code": error_code,
            "error_message": safe_validation_message,
            "semantic_source": semantic_source,
            "llm_backend": llm_backend,
            "fallback_reason": fallback_reason or "semantic_frame_validation_failed",
            "llm_called": llm_called,
            "dropped_facets": parsed.get("dropped_facets", []),
            **_log(state, "semantic_parse", status="failed",
                   reason=fallback_reason or "semantic_frame_validation_failed",
                   semantic_source=semantic_source, llm_backend=llm_backend,
                   fallback_reason=fallback_reason, llm_called=llm_called),
        }
    if frame is None:
        return {
            "semantic_frame": None,
            "error_code": error_code,
            "error_message": error_message,
            "semantic_source": semantic_source,
            "llm_backend": llm_backend,
            "fallback_reason": fallback_reason,
            "llm_called": llm_called,
            "dropped_facets": parsed.get("dropped_facets", []),
            **_log(state, "semantic_parse", status="failed" if error_code else "skipped",
                   reason=fallback_reason or error_code or "semantic_frame_missing",
                   semantic_source=semantic_source, llm_backend=llm_backend,
                   fallback_reason=fallback_reason, llm_called=llm_called),
        }
    if not isinstance(frame, SemanticFrame):
        try:
            frame = SemanticFrame.model_validate(frame or {})
        except ValidationError as exc:
            return {
                "semantic_frame": None,
                "error_code": "SCHEMA_VALIDATION_FAILED",
                "error_message": safe_validation_message,
                "semantic_source": semantic_source,
                "llm_backend": llm_backend,
                "fallback_reason": fallback_reason or "semantic_frame_validation_failed",
                "llm_called": llm_called,
                **_log(state, "semantic_parse", status="failed",
                       reason="semantic_frame_validation_failed",
                       semantic_source=semantic_source, llm_backend=llm_backend,
                       fallback_reason=fallback_reason, llm_called=llm_called),
            }
    if not error_code:
        validation = validate_frame(frame.model_dump())
        if not validation.get("valid", False):
            issues = validation.get("issues", [])
            if "missing_task_type" in issues:
                error_code = "MISSING_TASK_TYPE"
            elif any(issue.startswith("forbidden_field:") for issue in issues):
                error_code = "SCHEMA_VALIDATION_FAILED"
            elif "invalid_task_type" in issues:
                error_code = "INVALID_ARGUMENT"
            elif "missing_merchant_mentions" in issues or "needs_context" in issues:
                error_code = ""
            else:
                error_code = "SEMANTIC_FRAME_INVALID"
            error_message = validation.get("clarification", "")
    dropped_facets = parsed.get("dropped_facets", [])
    return {
        "semantic_frame": frame,
        "error_code": error_code,
        "error_message": error_message,
        "semantic_source": semantic_source or getattr(frame, "semantic_source", ""),
        "llm_backend": llm_backend or getattr(frame, "llm_backend", ""),
        "fallback_reason": fallback_reason or getattr(frame, "fallback_reason", ""),
        "llm_called": llm_called if parsed.get("llm_called") is not None else getattr(frame, "llm_called", False),
        "dropped_facets": dropped_facets,
        **_log(state, "semantic_parse",
               semantic_source=semantic_source or getattr(frame, "semantic_source", ""),
               llm_backend=llm_backend or getattr(frame, "llm_backend", ""),
               fallback_reason=fallback_reason or getattr(frame, "fallback_reason", ""),
               llm_called=llm_called if parsed.get("llm_called") is not None else getattr(frame, "llm_called", False),
               task_type=getattr(frame, "task_type", ""),
               primary_task=getattr(frame, "primary_task", ""),
               need_context=getattr(frame, "need_context", False),
               follow_up=_to_dict(getattr(frame, "follow_up", None)),
               facets=getattr(frame, "focused_facets", []) or []),
    }


def _h_slot_extractor(state: GraphState) -> dict:
    sf = state.get("semantic_frame")
    if sf is not None and hasattr(sf, "model_copy"):
        sf = sf.model_copy(deep=True)
        raw_text = str(state.get("raw_text", "") or "")
        merchant_mentions = [str(item).strip() for item in (sf.merchant_mentions or []) if str(item).strip()]
        inferred_mentions = _infer_explicit_mentions_from_text(raw_text)
        if inferred_mentions and not merchant_mentions:
            sf.merchant_mentions = inferred_mentions
        if not list(sf.deictic_references or []):
            deictics = [token for token in ("这家", "那家", "它", "这间", "那间") if token in raw_text]
            if deictics:
                sf.deictic_references = deictics
        if not list(sf.ordinal_references or []):
            ordinal_matches = [match.group(0) for match in re.finditer(r"第\s*[1-9一二三四五六七八九十]\s*(个|家|间|店)?", raw_text)]
            if ordinal_matches:
                sf.ordinal_references = ordinal_matches
    if sf is not None:
        return {
            "semantic_frame": sf,
            **_log(state, "slot_extractor", mentions=sf.merchant_mentions),
        }
    return _log(state, "slot_extractor")


def _h_frame_validator(state: GraphState) -> dict:
    sf = state.get("semantic_frame")
    frame_dict = sf.model_dump() if sf is not None and hasattr(sf, "model_dump") else _to_dict(sf)
    validation = validate_frame(frame_dict)
    err = ""
    if not validation.get("valid", False):
        issues = validation.get("issues", [])
        if "missing_task_type" in issues:
            err = "MISSING_TASK_TYPE"
        elif "missing_merchant_mentions" in issues:
            err = "MISSING_MERCHANT_MENTION"
        elif "invalid_task_type" in issues:
            err = "INVALID_ARGUMENT"
        elif any(issue.startswith("forbidden_field:") for issue in issues):
            err = "SCHEMA_VALIDATION_FAILED"
        elif "needs_context" in issues:
            err = ""
        else:
            err = "SEMANTIC_FRAME_INVALID"
    return {
        "error_code": err,
        "error_message": validation.get("clarification", "") if err else "",
        "semantic_frame": sf,
        **_log(state, "frame_validator"),
    }


def _h_context_recovery(state: GraphState) -> dict:
    from ...target.clarification import build_pending_clarification
    from ...target.context_recovery import recover_context

    sf = state.get("semantic_frame")
    recovered = recover_context(
        session_state=state.get("session_state_before") or state.get("session_state"),
        semantic_frame=state.get("semantic_frame"),
        text=str(state.get("raw_text", "") or ""),
    )
    updates: dict[str, Any] = {}
    if recovered.get("resolved_target") is not None:
        updates["resolved_target"] = recovered.get("resolved_target")
    if recovered.get("comparison_targets") is not None:
        updates["comparison_targets"] = recovered.get("comparison_targets")
    if recovered.get("comparison_target_resolution") is not None:
        updates["comparison_target_resolution"] = recovered.get("comparison_target_resolution")
    if recovered.get("reference_resolution_source"):
        updates["reference_resolution_source"] = str(recovered.get("reference_resolution_source", "") or "")
    elif recovered.get("context_resolution") and isinstance(recovered.get("context_resolution"), dict):
        updates["reference_resolution_source"] = str(recovered.get("context_resolution", {}).get("resolution_source", "") or "")

    comparison_resolution = _to_dict(recovered.get("comparison_target_resolution"))
    comparison_status = str(comparison_resolution.get("status", "") or "").upper()
    if comparison_status in {"NEED_CLARIFICATION", "NOT_FOUND", "TOO_MANY", "PARTIAL"}:
        candidate_targets = list(recovered.get("comparison_targets") or [])
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
                    candidate_dict = _to_dict(candidate.get("shop") if isinstance(candidate, dict) else candidate)
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
                for item in list(recovered.get("comparison_targets") or [])
                if str(_to_dict(item).get("shop_id", "") or "").strip() not in resolved_target_ids
                and str(_to_dict(item).get("shop_name", "") or "").strip() not in resolved_target_names
            ]
        if not candidate_targets:
            session_state = state.get("session_state_before") or state.get("session_state")
            session_candidates = []
            if session_state is not None:
                if isinstance(session_state, dict):
                    session_candidates = list(session_state.get("last_recommendation_list", []) or [])
                else:
                    session_candidates = list(getattr(session_state, "last_recommendation_list", []) or [])
            candidate_targets = [
                {
                    "shop_id": str(item.get("shop_id", "")).strip(),
                    "shop_name": str(item.get("shop_name", "")).strip(),
                }
                for item in session_candidates
                if str(item.get("shop_id", "")).strip() and str(item.get("shop_name", "")).strip()
            ]
            already_resolved_targets = list(candidate_targets)
        if candidate_targets:
            pending = build_pending_clarification(
                original_text=str(state.get("raw_text", "") or ""),
                original_semantic_frame=sf.model_dump(mode="json") if hasattr(sf, "model_dump") else _to_dict(sf),
                original_task_type=getattr(sf, "task_type", "") or state.get("task_type", "") or "comparison",
                candidate_targets=candidate_targets,
                reason=str(comparison_resolution.get("reason", "") or "comparison_targets_need_clarification"),
                source_node="context_recovery",
                already_resolved_targets=already_resolved_targets,
            )
            updates["pending_clarification"] = pending
    frame_dict = sf.model_dump() if sf is not None and hasattr(sf, "model_dump") else _to_dict(sf)
    raw_text = str(state.get("raw_text", "") or "")
    task_type_value = str(getattr(getattr(sf, "task_type", None), "value", frame_dict.get("task_type", "")) or "")

    if updates.get("pending_clarification") is None and updates.get("resolved_target") is None:
        inferred_mentions = _infer_explicit_mentions_from_text(raw_text)
        if len(inferred_mentions) == 1:
            brand_like_mention = str(inferred_mentions[0] or "").strip()
            if brand_like_mention and "(" not in brand_like_mention and "（" not in brand_like_mention and "店" not in brand_like_mention:
                try:
                    from ...target.shop_resolver import resolve_shop as _resolve_shop
                except Exception:
                    _resolve_shop = None
                if _resolve_shop is not None and task_type_value in {"coupon_query", "single_shop_query", "recommendation"}:
                    try:
                        resolved = _unwrap_resolve_shop_result(_to_dict(_resolve_shop(brand_like_mention, location={})))
                    except Exception:
                        resolved = {}
                    if str(resolved.get("status", "") or "").upper() == "AMBIGUOUS":
                        candidate_targets = sorted(
                            [
                                {
                                    "shop_id": str(item.get("shop_id", "") or "").strip(),
                                    "shop_name": str(item.get("shop_name", "") or "").strip(),
                                    "address": str(item.get("address", "") or "").strip(),
                                }
                                for item in (resolved.get("candidates") or [])
                                if str(item.get("shop_id", "") or "").strip() and str(item.get("shop_name", "") or "").strip()
                            ],
                            key=lambda item: (-len(str(item.get("shop_id", "") or "")), str(item.get("shop_id", "") or ""), str(item.get("shop_name", "") or "")),
                        )
                        if candidate_targets:
                            updates["pending_clarification"] = build_pending_clarification(
                                original_text=raw_text,
                                original_semantic_frame=frame_dict,
                                original_task_type=task_type_value or "single_shop_query",
                                candidate_targets=candidate_targets,
                                reason=str(resolved.get("error_code", "") or "AMBIGUOUS_SHOP"),
                                source_node="context_recovery",
                            )

    semantic_refs = {
        "ordinal_references": list(frame_dict.get("ordinal_references", []) or []),
        "deictic_references": list(frame_dict.get("deictic_references", []) or []),
        "comparison_targets": list(frame_dict.get("comparison_targets", []) or []),
    }
    return {
        **updates,
        **_log(
            state,
            "context_recovery",
            status=str((recovered.get("context_resolution") or {}).get("status", "")),
            context_recovery_input_text=str(state.get("raw_text", "") or ""),
            context_recovery_used_semantic_refs=semantic_refs,
            context_recovery_result=_to_dict(recovered.get("comparison_target_resolution") or recovered.get("context_resolution")),
            reference_resolution_source=str(recovered.get("reference_resolution_source") or (recovered.get("context_resolution") or {}).get("resolution_source", "") or ""),
        ),
    }
