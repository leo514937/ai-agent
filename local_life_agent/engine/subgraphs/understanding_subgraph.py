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
    _user_location,
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
from ...domain.contextualized_turn import ContextualizedTurn
from ...domain.focus_context import FocusContext
from ...domain.freshness import FreshnessMeta
from ...domain.location_context import LocationContext
from ...domain.schemas import SemanticFrame
from ...planning.goal.goal_planner import _infer_explicit_mentions_from_text
from ...semantic.frame_validator import validate_frame
from ...semantic.intent_parser import parse_semantic_frame
from ...target.focus_resolver import build_contextualized_turn as build_focus_contextualized_turn
from ...target.focus_resolver import resolve_focus_context
from ... import config
from ...observability.file_logger import get_python_service_logger, log_kv

_LOGGER = get_python_service_logger()


def _location_fingerprint(location: dict[str, Any]) -> str:
    name = str(location.get("location_name", "") or location.get("name", "") or "").strip()
    lat = location.get("lat")
    lng = location.get("lng")
    status = str(location.get("location_status", "") or "").strip()
    source = str(location.get("location_source", "") or "").strip()
    return "|".join([
        name,
        "" if lat is None else str(lat),
        "" if lng is None else str(lng),
        status,
        source,
    ]).strip("|")


def _build_location_context(state: GraphState) -> LocationContext:
    location = _to_dict(_user_location(state))
    if not location:
        location = _to_dict(state.get("user_location"))
    return LocationContext.from_trace(
        location_name=str(location.get("location_name", "") or location.get("name", "") or ""),
        lat=location.get("lat"),
        lng=location.get("lng"),
        location_status=str(location.get("location_status", "") or state.get("location_status", "") or ""),
        location_source=str(location.get("location_source", "") or location.get("source", "") or ""),
        location_fingerprint=_location_fingerprint(location),
        radius_meters=location.get("radius_meters"),
    )


def _build_freshness_meta(state: GraphState, location_context: LocationContext) -> FreshnessMeta:
    cache_hit = bool(state.get("evidence_cache_hit", False))
    semantic_source = str(state.get("semantic_source", "") or "")
    fallback_reason = str(state.get("fallback_reason", "") or state.get("answer_fallback_reason", "") or "")
    freshness_class = "cached" if cache_hit else ("deterministic" if semantic_source in {"rule_based", "fallback_rules"} else "live")
    if fallback_reason and freshness_class == "live":
        freshness_class = "degraded"
    return FreshnessMeta.from_trace(
        freshness_class=freshness_class,
        is_stale=bool(state.get("answer_source", "") == "fallback" and not cache_hit),
        cache_hit=cache_hit,
        location_fingerprint=location_context.location_fingerprint,
        budget_context_snapshot=_to_dict(state.get("budget_context")),
    )


def _build_contextualized_turn(
    state: GraphState,
    recovered: dict[str, Any],
    active_turn_result: dict[str, Any],
) -> ContextualizedTurn:
    raw_text = str(state.get("raw_text", "") or "")
    semantic_frame = _to_dict(state.get("semantic_frame")) or _to_dict(recovered.get("semantic_frame"))
    session_state = state.get("session_state_before") or state.get("session_state")
    focus_turn = build_focus_contextualized_turn(
        raw_text,
        session_state=session_state,
        semantic_frame=semantic_frame,
        active_turn_result=active_turn_result,
        top_intent=state.get("top_intent"),
    )
    context_used = list(focus_turn.context_used)
    rewrite_type = focus_turn.rewrite_type
    confidence = float(focus_turn.confidence or 0.0)

    if semantic_frame.get("follow_up") or semantic_frame.get("constraint_update"):
        if "semantic_frame.follow_up" not in context_used:
            context_used.append("semantic_frame.follow_up")
        if rewrite_type == "none":
            rewrite_type = "semantic_follow_up"
        confidence = max(confidence, float(semantic_frame.get("confidence", 0.0) or 0.0))

    reference_source = str(recovered.get("reference_resolution_source", "") or "")
    if reference_source:
        context_used.append("context_recovery.reference_signal")
    comparison_signal = _to_dict(recovered.get("comparison_reference_signal"))
    if comparison_signal:
        context_used.append("context_recovery.comparison_reference_signal")
        if rewrite_type == "none":
            rewrite_type = "comparison_reference"
        confidence = max(confidence, 0.5)

    return ContextualizedTurn.from_trace(
        original_text=focus_turn.original_text or raw_text,
        normalized_text=focus_turn.normalized_text or str(state.get("normalized_text", "") or raw_text),
        contextualized_query=focus_turn.contextualized_query or str(state.get("normalized_text", "") or raw_text),
        rewrite_type=rewrite_type,
        mixed_intent=focus_turn.mixed_intent,
        terminal_policy=focus_turn.terminal_policy,
        context_used=context_used,
        confidence=confidence,
    )


def _build_focus_context(
    state: GraphState,
    recovered: dict[str, Any],
    active_turn_result: dict[str, Any],
) -> FocusContext:
    session_before = state.get("session_state_before") or state.get("session_state")
    semantic_frame = _to_dict(state.get("semantic_frame")) or _to_dict(recovered.get("semantic_frame"))
    focus_context = resolve_focus_context(
        str(state.get("raw_text", "") or ""),
        session_state=session_before,
        semantic_frame=semantic_frame,
        active_turn_result=active_turn_result,
    )
    return focus_context


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
    contextualized_turn = build_focus_contextualized_turn(
        str(txt or state.get("raw_text", "") or ""),
        session_state=session_state,
        semantic_frame=state.get("semantic_frame") or {},
        active_turn_result=_to_dict(state.get("active_turn_result")),
        top_intent=top_intent,
    )
    txt = contextualized_turn.contextualized_query or txt
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
    from ...target.context_recovery import recover_context

    sf = state.get("semantic_frame")
    active_turn_result = _to_dict(state.get("active_turn_result"))
    recovered = recover_context(
        session_state=state.get("session_state_before") or state.get("session_state"),
        semantic_frame=state.get("semantic_frame"),
        text=str(state.get("raw_text", "") or ""),
    )
    updates: dict[str, Any] = {}
    location_context = _build_location_context(state)
    freshness_meta = _build_freshness_meta(state, location_context)
    contextualized_turn = _build_contextualized_turn(state, recovered, active_turn_result)
    focus_context = _build_focus_context(state, recovered, active_turn_result)
    updates["location_context"] = location_context
    updates["freshness_meta"] = freshness_meta
    updates["contextualized_turn"] = contextualized_turn
    updates["focus_context"] = focus_context
    frame_dict = sf.model_dump() if sf is not None and hasattr(sf, "model_dump") else _to_dict(sf)
    raw_comparison_targets = list(frame_dict.get("comparison_targets", []) or [])
    if raw_comparison_targets:
        updates["comparison_targets"] = raw_comparison_targets
    elif _to_dict(recovered.get("comparison_reference_signal")).get("comparison_targets"):
        updates["comparison_targets"] = list(_to_dict(recovered.get("comparison_reference_signal")).get("comparison_targets") or [])
    if recovered.get("reference_resolution_source"):
        updates["reference_resolution_source"] = str(recovered.get("reference_resolution_source", "") or "")
    elif recovered.get("context_resolution") and isinstance(recovered.get("context_resolution"), dict):
        updates["reference_resolution_source"] = str(recovered.get("context_resolution", {}).get("resolution_source", "") or "")
    reference_signal = _to_dict(recovered.get("context_resolution", {}).get("reference_signal"))
    return {
        **updates,
        **_log(
            state,
            "context_recovery",
            status=str((recovered.get("context_resolution") or {}).get("status", "")),
            context_recovery_input_text=str(state.get("raw_text", "") or ""),
            context_recovery_used_semantic_refs={
                "ordinal_references": list(frame_dict.get("ordinal_references", []) or []),
                "deictic_references": list(frame_dict.get("deictic_references", []) or []),
                "comparison_targets": list(frame_dict.get("comparison_targets", []) or []),
            },
            context_recovery_result=_to_dict(recovered.get("comparison_reference_signal") or recovered.get("context_resolution")),
            reference_resolution_source=str(recovered.get("reference_resolution_source") or (recovered.get("context_resolution") or {}).get("resolution_source", "") or ""),
            reference_signal=reference_signal,
            contextualized_turn=contextualized_turn.trace_dict(),
            focus_context=focus_context.trace_dict(),
            freshness_meta=freshness_meta.trace_dict(),
            location_context=location_context.trace_dict(),
        ),
    }
