"""Shared utility functions extracted from graph_builder.py.

These helpers are used across multiple subgraph modules and by the
graph builder itself. Extracted here to avoid circular imports and
duplication.
"""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from datetime import datetime, timezone
from enum import Enum
from time import perf_counter, time
from typing import Any

from .. import config
from ..domain.candidate import (
    CandidateSet,
    CandidateSource,
    CandidateSpec,
    GoalType,
    LocalLifeGoalDraft,
    ResolvedCandidate,
)
from ..domain.enums import TaskType, TopIntent
from ..domain.graph_state import GraphState
from ..domain.schemas import (
    ResolveShopResult,
    SemanticFrame,
    ShopRef,
    ToolResult,
)
from ..domain.state import SessionState
from ..observability.file_logger import current_log_context, get_python_service_logger, log_kv, reset_log_context, set_log_context, summarize_for_log
from ..observability.trace import record_span, sanitize_payload
from ..planning.policies.replan_policy import increment_expand_search, increment_replan_evidence

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TRACE_STAGE_MAP: dict[str, str] = {
    "receive_input": "input_received",
    "load_session_state": "input_received",
    "check_pending_clarification": "pending_clarification_checked",
    "basic_input_validate": "input_received",
    "normalize_text": "input_received",
    "hard_guard": "hard_guard",
    "top_intent_router": "top_intent_router",
    "intake_guard_router": "input_received",
    "merge_clarification": "pending_clarification_checked",
    "understanding_subgraph": "semantic_parse",
    "orchestration_router_shadow": "orchestration_router",
    "workflow_runner": "workflow_runner",
    "planning_subgraph": "execution_plan",
    "execution_review_subgraph": "evidence_review",
    "response_subgraph": "answer_generate",
    "semantic_parse": "semantic_parse",
    "slot_extractor": "semantic_parse",
    "frame_validator": "semantic_parse",
    "context_recovery": "context_recovery",
    "target_resolve": "shop_resolver",
    "clarify_decide": "reference_resolver",
    "evidence_planner": "execution_plan",
    "evidence_review": "evidence_review",
    "plan_validator": "execution_plan",
    "tool_execute": "tool_call",
    "evidence_build": "evidence_builder",
    "answer_generate": "answer_generate",
    "answer_verify": "answer_verify",
    "rewrite": "rewrite",
    "final_response_build": "final_response",
    "clarify_response": "final_response",
    "fallback_answer": "fallback_answer",
    "state_update_plan": "final_response",
    "persist_session_state": "final_response",
    "emit_response": "final_response",
}

_OUTER_WRAPPER_EXCLUDE_FIELDS = {"final_response", "event_log", "trace_spans"}

_FILE_LOGGER = get_python_service_logger()

_GRAPH_REWRITE_LIMIT = max(1, config.MAX_REWRITE_ATTEMPTS - 1)

# Type alias
GraphNodeFunc = Any  # Callable[[GraphState], dict] — acceptable typing overhead


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _log(state: GraphState, node: str, **extra: Any) -> dict:
    """Return a partial update that appends an event-log entry."""
    log = list(state.get("event_log", []))
    entry = {"node": node, **sanitize_payload(extra)}
    log.append(entry)

    sanitized = sanitize_payload(extra)
    if state.get("trace_id"):
        sanitized["trace_id"] = str(state.get("trace_id", "") or "")
    if state.get("session_id"):
        sanitized["session_id"] = str(state.get("session_id", "") or "")
    if state.get("turn_id"):
        sanitized["turn_id"] = str(state.get("turn_id", "") or "")
    if state.get("raw_text"):
        sanitized["raw_text_preview"] = str(state.get("raw_text", "") or "")[:120]
    if state.get("top_intent") is not None:
        sanitized["top_intent"] = _coerce_str(state.get("top_intent"))
    if state.get("task_type") is not None:
        sanitized["task_type"] = _coerce_str(state.get("task_type"))
    detail_parts = []
    for k, v in sanitized.items():
        if isinstance(v, bool):
            detail_parts.append(f"{k}={str(v).lower()}")
        elif v is not None and v != "":
            detail_parts.append(f"{k}={summarize_for_log(v, max_len=180)}")
    detail_str = " ".join(detail_parts) if detail_parts else ""
    try:
        log_kv(_FILE_LOGGER, logging.INFO, "[NODE_EVENT]", tone="node", node=node, **sanitized)
    except Exception:
        pass
    return {"event_log": log}


# ---------------------------------------------------------------------------
# State & dict helpers
# ---------------------------------------------------------------------------


def _pick_route(
    state: GraphState,
    status_field: str,
    route_map: dict[str, str],
    default: str,
) -> str:
    """Read *status_field* from state and return the matching route name."""
    val = state.get(status_field, "")
    for key, route in route_map.items():
        if val == key:
            return route
    return default


def _plan_validation_error_code(errors: list[str]) -> str:
    """Map validator errors to the runtime error_code used by graph routing."""
    joined = " | ".join(errors)
    if "not registered" in joined:
        return "TOOL_NOT_REGISTERED"
    if "forbidden" in joined:
        return "INVALID_ARGUMENT"
    if "Circular dependency" in joined:
        return "INVALID_ARGUMENT"
    if "not produced by legitimate resolve" in joined or "shop_id mismatch" in joined:
        return "INVALID_ARGUMENT"
    if "comparison_target_limit_exceeded" in joined:
        return "INVALID_ARGUMENT"
    if "INVALID_ARGUMENT" in joined:
        return "INVALID_ARGUMENT"
    if "SCHEMA_VALIDATION_FAILED" in joined:
        return "SCHEMA_VALIDATION_FAILED"
    if "exceeds max_tool_calls" in joined:
        return "INVALID_ARGUMENT"
    return "SCHEMA_VALIDATION_FAILED"


def _to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        return dumped if isinstance(dumped, dict) else {}
    return dict(getattr(value, "__dict__", {}) or {})


def _user_location(state: GraphState) -> dict[str, Any]:
    """Extract user location from graph state without inventing defaults."""
    loc = state.get("user_location")
    if isinstance(loc, dict) and loc.get("lat") is not None and loc.get("lng") is not None:
        return dict(loc)
    user_context = state.get("user_context")
    if isinstance(user_context, dict) and user_context.get("lat") is not None and user_context.get("lng") is not None:
        status = str(user_context.get("location_status", "") or "").lower()
        source = str(user_context.get("location_source", "") or "").lower()
        if status in {"provided", "test_mock"} or source in {"provided", "test_mock"}:
            return dict(user_context)
    session = state.get("session_state_before") or state.get("session_state") or {}
    if isinstance(session, SessionState):
        location = getattr(session, "location", None)
        if isinstance(location, dict) and location.get("lat") is not None and location.get("lng") is not None:
            return dict(location)
    return {}


def _coerce_str(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "value"):
        value = getattr(value, "value")
    return str(value)


def _merge_update(state: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    merged = dict(state)
    merged.update(update)
    return merged


def _run_step(state: Any, handler: GraphNodeFunc) -> dict[str, Any]:
    state_dict = _to_dict(state)
    update = handler(state_dict)
    if not isinstance(update, dict):
        update = _to_dict(update)
    return _merge_update(state_dict, update)


def _run_steps(state: Any, handlers: list[GraphNodeFunc]) -> dict[str, Any]:
    working = _to_dict(state)
    for handler in handlers:
        working = _run_step(working, handler)
    return working


def _state_delta(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    always_include: set[str] | None = None,
    exclude: set[str] | None = None,
) -> dict[str, Any]:
    delta: dict[str, Any] = {}
    always = always_include or set()
    excluded = exclude or set()
    for key, value in after.items():
        if key in excluded:
            continue
        if key in always or before.get(key) != value:
            delta[key] = value
    return delta


# ---------------------------------------------------------------------------
# Trace / instrumentation
# ---------------------------------------------------------------------------


def _trace_input_summary(state: GraphState, node_name: str) -> dict[str, Any]:
    semantic_frame = _to_dict(state.get("semantic_frame"))
    summary = {
        "raw_text": str(state.get("raw_text", "") or "")[:120],
        "top_intent": _coerce_str(state.get("top_intent") or semantic_frame.get("top_intent"))[:64],
        "task_type": _coerce_str(state.get("task_type") or semantic_frame.get("task_type"))[:64],
        "pending_clarification": bool(state.get("pending_clarification")),
        "rewrite_count": int(state.get("rewrite_count", 0) or 0),
    }
    if node_name == "tool_execute":
        summary["tool_calls"] = len(getattr(state.get("validated_plan") or state.get("execution_plan"), "tool_calls", []) or [])
    return sanitize_payload(summary)


def _trace_output_summary(update: dict[str, Any]) -> dict[str, Any]:
    tool_results = _to_dict(update.get("tool_results"))
    legacy_tool_result_set = _to_dict(update.get("tool_result_set"))
    output = {
        "keys": sorted(str(key) for key in update.keys()),
        "error_code": _coerce_str(update.get("error_code"))[:64],
        "answer_source": _coerce_str(update.get("answer_source"))[:64],
        "verify_result": _coerce_str(update.get("verify_result"))[:64],
        "tool_result_count": len(tool_results) if tool_results else len(legacy_tool_result_set),
    }
    event_log = update.get("event_log") or []
    if event_log and isinstance(event_log, list) and isinstance(event_log[-1], dict):
        output["event"] = dict(event_log[-1])
    return sanitize_payload(output)


def _event_status(node_name: str, update: dict[str, Any], event_entry: dict[str, Any]) -> str:
    status = str(event_entry.get("status", "") or "").strip().lower()
    if status:
        return str(event_entry.get("status"))
    if update.get("error_code"):
        return "failed"
    if node_name == "rewrite":
        return "success"
    return "success"


def _instrument_handler(node_name: str, handler: GraphNodeFunc) -> GraphNodeFunc:
    stage = _TRACE_STAGE_MAP.get(node_name, node_name)

    def wrapped(state: GraphState) -> dict:
        started_at = perf_counter()
        timestamp_ms = int(time() * 1000)
        input_summary = _trace_input_summary(state, node_name)
        trace_id = state.get("trace_id", "")
        session_id = state.get("session_id", "")
        turn_id = state.get("turn_id", "")
        context_token = set_log_context(
            trace_id=trace_id,
            session_id=session_id,
            turn_id=turn_id,
            node=node_name,
            stage=stage,
            workflow_name=str(state.get("workflow_name", "") or ""),
            semantic_task_type=str(state.get("task_type", "") or ""),
        )

        # — Node entry log —
        log_kv(
            _FILE_LOGGER,
            logging.INFO,
            "[NODE_ENTER]",
            tone="node",
            node=node_name,
            stage=stage,
            trace_id=trace_id,
            session_id=session_id,
            turn_id=turn_id,
            input_summary=input_summary,
        )

        try:
            update = handler(state)
        except Exception as exc:
            duration_ms = int((perf_counter() - started_at) * 1000)
            log_kv(
                _FILE_LOGGER,
                logging.ERROR,
                "[NODE_EXIT]",
                tone="error",
                node=node_name,
                stage=stage,
                status="failed",
                duration_ms=duration_ms,
                error_message=str(exc),
            )
            try:
                trace_id = str(state.get("trace_id", "") or "")
                if trace_id:
                    record_span(
                        trace_id,
                        node_name,
                        {
                            "session_id": str(state.get("session_id", "") or "") or None,
                            "turn_id": str(state.get("turn_id", "") or ""),
                            "stage": stage,
                            "status": "failed",
                            "timestamp_ms": timestamp_ms,
                            "duration_ms": duration_ms,
                            "input_summary": input_summary,
                            "output_summary": {},
                            "error_code": "TRACE_HANDLER_EXCEPTION",
                            "error_message": str(exc),
                            "metadata": {"node": node_name, "trace_safe": True},
                        },
                    )
            except Exception:
                pass
            reset_log_context(context_token)
            raise

        try:
            log = list(update.get("event_log", []) or [])
            event_entry = log[-1] if log and isinstance(log[-1], dict) and str(log[-1].get("node", "")) == node_name else {}
            status = _event_status(node_name, update, event_entry)
            duration_ms = int((perf_counter() - started_at) * 1000)
            error_code = _coerce_str(update.get("error_code")) or ""
            output_summary = _trace_output_summary(update)

            # — Node exit log —
            log_kv(
                _FILE_LOGGER,
                logging.INFO if status == "success" else logging.WARNING,
                "[NODE_EXIT]",
                tone="node" if status == "success" else "warn",
                node=node_name,
                stage=stage,
                status=status,
                duration_ms=duration_ms,
                error_code=error_code or "none",
                output_summary=output_summary,
            )
            log_kv(
                _FILE_LOGGER,
                logging.DEBUG,
                "[NODE_DELTA]",
                tone="node",
                changed_keys=sorted(str(key) for key in update.keys()),
                delta=sanitize_payload(update),
                context=current_log_context(),
            )

            metadata = {
                key: value
                for key, value in event_entry.items()
                if key not in {
                    "node", "stage", "status", "timestamp_ms", "duration_ms",
                    "input_summary", "output_summary", "error_code", "error_message", "metadata",
                }
            }
            standardized = {
                "node": node_name,
                "stage": stage,
                "status": status,
                "timestamp_ms": timestamp_ms,
                "duration_ms": duration_ms,
                "input_summary": input_summary,
                "output_summary": output_summary,
                "error_code": error_code or None,
                "error_message": _coerce_str(update.get("error_message")) or None,
                "metadata": sanitize_payload(metadata),
            }
            if event_entry:
                event_entry.update(standardized)
            else:
                log.append(standardized)
            update["event_log"] = log
            trace_id = str(state.get("trace_id", "") or update.get("trace_id", "") or "")
            if trace_id:
                record_span(
                    trace_id,
                    node_name,
                    {
                        "session_id": str(state.get("session_id", "") or update.get("session_id", "") or "") or None,
                        "turn_id": str(state.get("turn_id", "") or update.get("turn_id", "") or ""),
                        **standardized,
                    },
                )
        except Exception:
            reset_log_context(context_token)
            return update
        reset_log_context(context_token)
        return update

    return wrapped


# ---------------------------------------------------------------------------
# Session & shop helpers
# ---------------------------------------------------------------------------


def _session_state_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        return dumped if isinstance(dumped, dict) else {}
    return dict(getattr(value, "__dict__", {}) or {})


def _shop_dict(value: Any) -> dict[str, Any]:
    data = _session_state_dict(value)
    if data:
        return data
    if hasattr(value, "resolved_shop"):
        return _session_state_dict(getattr(value, "resolved_shop"))
    if hasattr(value, "shop"):
        return _session_state_dict(getattr(value, "shop"))
    return {}


def _session_store_state(state: GraphState) -> SessionState:
    loaded = state.get("session_state")
    if isinstance(loaded, SessionState):
        return loaded
    return SessionState()


def _session_shop_ids(state: GraphState) -> list[str]:
    ids: list[str] = []
    current_shop = _session_state_dict(state.get("current_shop"))
    if current_shop.get("shop_id"):
        ids.append(str(current_shop.get("shop_id")))
    for item in state.get("last_recommendation_list", []) or []:
        shop = _session_state_dict(item)
        sid = str(shop.get("shop_id", "")).strip()
        if sid:
            ids.append(sid)
    deduped: list[str] = []
    for sid in ids:
        if sid and sid not in deduped:
            deduped.append(sid)
    return deduped


def _resolved_shop_ids_from_state(state: GraphState) -> set[str]:
    """Collect legitimate resolved shop IDs from the current turn state."""
    sf = state.get("semantic_frame")
    sf_dict = _to_dict(sf)
    sf_task_type = sf_dict.get("task_type") or getattr(sf, "task_type", None) if sf is not None else None
    resolved_ids: set[str] = set()
    if sf_task_type == TaskType.recommendation or sf_task_type == TaskType.recommendation.value:
        for item in state.get("recommendation_candidates", []) or []:
            data = _to_dict(item)
            sid = str(data.get("shop_id", "")).strip()
            if sid:
                resolved_ids.add(sid)
    candidate_set = state.get("candidate_set") or state.get("effective_candidate_set")
    if candidate_set is not None:
        candidate_data = _to_dict(candidate_set)
        for item in candidate_data.get("candidates", []) or []:
            data = _to_dict(item)
            sid = str(data.get("shop_id", "")).strip()
            if sid:
                resolved_ids.add(sid)
    for source in (state.get("resolved_target"), state.get("resolve_shop_result")):
        if source is None:
            continue
        data = _to_dict(source)
        if data.get("status") == "RESOLVED":
            resolved_shop = data.get("resolved_shop") or data.get("shop") or {}
            if not isinstance(resolved_shop, dict) and hasattr(resolved_shop, "model_dump"):
                resolved_shop = resolved_shop.model_dump()
            if isinstance(resolved_shop, dict):
                sid = str(resolved_shop.get("shop_id", "")).strip()
                if sid:
                    resolved_ids.add(sid)
        sid = str(data.get("shop_id", "")).strip()
        if sid:
            resolved_ids.add(sid)
    for item in state.get("comparison_targets", []) or []:
        data = _to_dict(item)
        resolved_shop = data.get("resolved_shop") or data.get("shop") or {}
        if not isinstance(resolved_shop, dict) and hasattr(resolved_shop, "model_dump"):
            resolved_shop = resolved_shop.model_dump()
        if isinstance(resolved_shop, dict):
            sid = str(resolved_shop.get("shop_id", "")).strip()
            if sid:
                resolved_ids.add(sid)
        sid = str(data.get("shop_id", "")).strip()
        if sid:
            resolved_ids.add(sid)
    return resolved_ids


def _unwrap_resolve_shop_result(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    data = raw.get("data")
    if isinstance(data, dict) and "status" in data:
        return data
    return raw


def _plan_required_by_call_id(plan: Any | None) -> dict[str, bool]:
    result: dict[str, bool] = {}
    if plan is None:
        return result
    plan_dict = _to_dict(plan)
    for call in plan_dict.get("tool_calls", []) or []:
        call_dict = _to_dict(call)
        call_id = str(call_dict.get("call_id", "")).strip()
        if call_id:
            result[call_id] = bool(call_dict.get("required", True))
    return result


# ---------------------------------------------------------------------------
# Conversation continuity
# ---------------------------------------------------------------------------


def _build_conversation_continuity(state: GraphState) -> dict[str, Any]:
    """Build a lightweight ``conversation_continuity`` dict from graph state.

    This is injected into the verbalizer prompt as metadata only — it
    is **not** a source of factual claims. The verbalizer must still
    derive all facts from ``DecisionPlan`` fields.
    """
    cc: dict[str, Any] = {}

    session_state = state.get("session_state_before") or state.get("session_state")
    if session_state is None:
        return cc

    # Determine if this turn is a follow-up by inspecting the semantic frame
    sf = state.get("semantic_frame")
    if sf is not None:
        sf_dict = _to_dict(sf)
        fu = sf_dict.get("follow_up") or {}
        if isinstance(fu, dict) and fu.get("is_follow_up"):
            cc["is_follow_up"] = True
            ra = fu.get("refine_action")
            if ra:
                cc["follow_up_action"] = str(ra)

    # Session-derived continuity hints (shop names only, no IDs)
    if isinstance(session_state, dict):
        raw = session_state
    else:
        raw = _to_dict(session_state)

    current_raw = raw.get("current_shop") or {}
    if isinstance(current_raw, dict):
        name = str(current_raw.get("shop_name", "") or current_raw.get("name", "") or "")
        if name:
            cc["previous_focus"] = name

    # Inherited task type
    last_task = raw.get("last_task_type") or raw.get("task_type") or ""
    if last_task:
        cc["previous_task_type"] = str(last_task)

    # Inherited constraints (short keys only)
    active_raw = raw.get("active_constraints") or {}
    if isinstance(active_raw, dict) and active_raw:
        cc["inherited_constraints"] = dict(active_raw)

    return cc


# ---------------------------------------------------------------------------
# Recommendation / search helpers
# ---------------------------------------------------------------------------


def _resolve_search_result_placeholder(value: Any, search_result: Any) -> Any:
    if not isinstance(value, str) or not value.startswith("$search_result"):
        return value
    if value == "$search_result.shop_ids":
        items = []
        if isinstance(search_result, dict):
            items = list(search_result.get("data", []) or [])
        return [str(item.get("shop_id", "")).strip() for item in items if isinstance(item, dict) and str(item.get("shop_id", "")).strip()]
    if value == "$search_result.shop_names":
        items = []
        if isinstance(search_result, dict):
            items = list(search_result.get("data", []) or [])
        return [str(item.get("shop_name", "")).strip() for item in items if isinstance(item, dict) and str(item.get("shop_name", "")).strip()]
    if not value.startswith("$search_result[") or "].shop_id" not in value:
        return value
    try:
        index_part = value.split("[", 1)[1].split("]", 1)[0]
        index = int(index_part)
    except Exception:
        return value
    items = []
    if isinstance(search_result, dict):
        items = list(search_result.get("data", []) or [])
    if 0 <= index < len(items):
        item = items[index] if isinstance(items[index], dict) else {}
        return str(item.get("shop_id", "")).strip()
    return ""


def _resolve_recommendation_spec(spec: Any, search_result: Any) -> dict[str, Any]:
    call = spec.model_dump() if hasattr(spec, "model_dump") else _to_dict(spec)
    args = dict(call.get("args", {}) or {})
    resolved_args = {key: _resolve_search_result_placeholder(value, search_result) for key, value in args.items()}
    resolved_target_shop_id = _resolve_search_result_placeholder(call.get("target_shop_id", ""), search_result)
    return {
        **call,
        "args": resolved_args,
        "target_shop_id": resolved_target_shop_id,
    }


def _comparison_structured_queries(semantic_frame: Any) -> list[str]:
    frame = _to_dict(semantic_frame)
    queries: list[str] = []
    for item in frame.get("comparison_targets", []) or []:
        target = _to_dict(item)
        reference = str(target.get("reference", "") or "").strip()
        if reference != "explicit":
            continue
        query = str(target.get("shop_name", "") or target.get("source_text", "")).strip()
        if query and query not in queries:
            queries.append(query)
    for mention in frame.get("merchant_mentions", []) or []:
        query = str(mention or "").strip()
        if query and query not in queries:
            queries.append(query)
    return queries


def _comparison_reason_response(reason: str) -> str:
    if reason == "comparison_requires_at_least_two_shops":
        return "对比至少需要两家不同的店，请补充另一家店名。"
    if reason == "comparison_too_many_shops":
        return "最多支持 5 家店对比，请缩小范围后再试。"
    if reason == "pronoun_without_current_shop":
        return "你说的“这家”还不明确，请告诉我是刚才推荐里的哪一家。"
    if reason == "ordinal_out_of_range":
        return "你提到的编号超出了上一次推荐范围，请换一个编号或店名。"
    return ""


# ---------------------------------------------------------------------------
# Routing helpers
# ---------------------------------------------------------------------------


def _response_mode_for_top_intent(intent: Any) -> str:
    intent_value = intent.value if hasattr(intent, "value") else str(intent or "")
    if intent_value in {"chat", "capability"}:
        return "direct"
    if intent_value in {"unsafe", "out_of_scope", "invalid"}:
        return "reject"
    return "reject"


def _planning_failure_route(state: dict[str, Any]) -> str:
    from ._routes import _OUTER_ROUTE_CLARIFY, _OUTER_ROUTE_EXECUTE, _OUTER_ROUTE_FALLBACK

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
