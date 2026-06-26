"""understanding_subgraph — semantic parsing and context recovery.

Parses user intent into a structured semantic frame, validates slot types,
and resolves contextual references (pronouns / ordinals / comparison targets).
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from .._compat import (
    _log,
    _run_steps,
    _state_delta,
    _to_dict,
    _OUTER_WRAPPER_EXCLUDE_FIELDS,
)
from .._routes import (
    _OUTER_ROUTE_CLARIFY,
    _OUTER_ROUTE_PROCEED,
)
from ...domain.graph_state import GraphState
from ...domain.schemas import SemanticFrame
from ...semantic.frame_validator import validate_frame
from ...semantic.intent_parser import parse_semantic_frame
from ... import config


def h_understanding_subgraph(state: GraphState) -> dict:
    """Outer wrapper: parse → validate → context recovery → route."""
    before = dict(state)
    working = _run_steps(state, [_h_semantic_parse])
    if working.get("error_code"):
        after = {
            **working,
            "understanding_route": _OUTER_ROUTE_CLARIFY,
            "response_mode": _OUTER_ROUTE_CLARIFY,
        }
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
                "error_message": str(exc),
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
        else:
            err = "SEMANTIC_FRAME_INVALID"
    return {
        "error_code": err,
        "error_message": validation.get("clarification", "") if err else "",
        "semantic_frame": sf,
        **_log(state, "frame_validator"),
    }


def _h_context_recovery(state: GraphState) -> dict:
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
    frame_dict = sf.model_dump() if sf is not None and hasattr(sf, "model_dump") else _to_dict(sf)
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
