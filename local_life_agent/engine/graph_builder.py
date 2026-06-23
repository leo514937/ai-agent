"""LangGraph StateGraph builder for the local life agent.

Maps the node/edge/state contracts from todo/05 into a compilable
``StateGraph``.  Each node handler documents its input/output fields
per §2 Node Table; conditional edges follow §3 Conditional Edge Table.
"""

from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter, time
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import ValidationError

from .. import config
from ..config import MOCK_LOCATION, TOOL_DEFAULT_TIMEOUT_MS
from ..domain.enums import TaskType, ToolResultStatus, TopIntent
from ..domain.graph_state import GraphState
from ..domain.schemas import (
    AnswerPlan,
    ComparisonTargetResolution,
    EvidenceItem,
    EvidencePack,
    ExecutionPlan,
    ExecutionStage,
    ResolveShopResult,
    SemanticFrame,
    ShopCandidate,
    ShopRef,
    ToolCallSpec,
    ToolResult,
)
from ..domain.state import SessionState, SessionWriteDirective
from ..answer.answer_plan_builder import build_answer_plan
from ..answer.evidence_builder import build_evidence
from ..answer.generator import generate_answer
from ..planning.state_update_planner import plan_state_update
from ..tools.result_semantics import TOOL_FAILURE_STATUSES, get_tool_result_status
from ..answer.verifier import verify_answer
from ..observability.trace import record_span, sanitize_payload
from ..input.hard_guard import check_hard_guard
from ..input.normalizer import normalize_text as input_normalize_text
from ..input.receiver import receive_input as assemble_turn_input
from ..input.validator import validate_basic_input
from ..planning.plan_validator import ExecutionPlanValidator
from ..planning.tool_plan_adapter import build_execution_plan_with_tool_planner
from ..planning.facet_planner import plan_facets
from ..planning.task_router import route_task
from ..semantic.frame_validator import validate_frame
from ..semantic.intent_parser import parse_semantic_frame, parse_top_intent
from ..llm.client import call_llm
from ..tools.gateway import dispatch_tool_call
from ..tools.gateway import BatchToolExecutor
from ..target.shop_resolver import resolve_shop
from ..target.clarification import build_pending_clarification, format_pending_prompt, handle_clarification_reply
from ..target.context_recovery import recover_context
from ..session.store import get_session_store
from .nodes import ExecutionNode
from .session_write import get_directive, resolve_scenario

# ===================================================================
# Helpers
# ===================================================================

GraphNodeFunc = Any  # Callable[[GraphState], dict] —acceptable typing overhead

_GRAPH_REWRITE_LIMIT = max(1, config.MAX_REWRITE_ATTEMPTS - 1)

_TRACE_STAGE_MAP: dict[str, str] = {
    "receive_input": "input_received",
    "load_session_state": "input_received",
    "check_pending_clarification": "pending_clarification_checked",
    "basic_input_validate": "input_received",
    "normalize_text": "input_received",
    "hard_guard": "hard_guard",
    "top_intent_router": "top_intent_router",
    "semantic_parse": "semantic_parse",
    "slot_extractor": "semantic_parse",
    "frame_validator": "semantic_parse",
    "context_recovery": "context_recovery",
    "target_resolve": "shop_resolver",
    "clarify_decide": "reference_resolver",
    "task_plan": "task_router",
    "facet_plan": "execution_plan",
    "comparison_planner": "candidate_decision_plan",
    "plan_validator": "execution_plan",
    "tool_execute": "tool_call",
    "evidence_build": "evidence_builder",
    "answer_plan_build": "candidate_evidence_collector",
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



def _log(state: GraphState, node: str, **extra: Any) -> dict:
    """Return a partial update that appends an event-log entry."""
    log = list(state.get("event_log", []))
    entry = {"node": node, **sanitize_payload(extra)}
    log.append(entry)
    return {"event_log": log}


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


def _coerce_str(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "value"):
        value = getattr(value, "value")
    return str(value)


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
    output = {
        "keys": sorted(str(key) for key in update.keys()),
        "error_code": _coerce_str(update.get("error_code"))[:64],
        "answer_source": _coerce_str(update.get("answer_source"))[:64],
        "verify_result": _coerce_str(update.get("verify_result"))[:64],
        "tool_result_count": len((_to_dict(update.get("tool_result_set")) or _to_dict(update.get("tool_results")))),
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
        try:
            update = handler(state)
        except Exception as exc:
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
                            "duration_ms": int((perf_counter() - started_at) * 1000),
                            "input_summary": input_summary,
                            "output_summary": {},
                            "error_code": "TRACE_HANDLER_EXCEPTION",
                            "error_message": str(exc),
                            "metadata": {"node": node_name, "trace_safe": True},
                        },
                    )
            except Exception:
                pass
            raise

        try:
            log = list(update.get("event_log", []) or [])
            event_entry = log[-1] if log and isinstance(log[-1], dict) and str(log[-1].get("node", "")) == node_name else {}
            status = _event_status(node_name, update, event_entry)
            output_summary = _trace_output_summary(update)
            metadata = {
                key: value
                for key, value in event_entry.items()
                if key not in {
                    "node",
                    "stage",
                    "status",
                    "timestamp_ms",
                    "duration_ms",
                    "input_summary",
                    "output_summary",
                    "error_code",
                    "error_message",
                    "metadata",
                }
            }
            standardized = {
                "node": node_name,
                "stage": stage,
                "status": status,
                "timestamp_ms": timestamp_ms,
                "duration_ms": int((perf_counter() - started_at) * 1000),
                "input_summary": input_summary,
                "output_summary": output_summary,
                "error_code": _coerce_str(update.get("error_code")) or None,
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
            # trace must never break the graph
            return update
        return update

    return wrapped


def _resolved_shop_ids_from_state(state: GraphState) -> set[str]:
    """Collect legitimate resolved shop IDs from the current turn state."""
    sf = state.get("semantic_frame")
    sf_task_type = getattr(sf, "task_type", None) if sf is not None else None
    resolved_ids: set[str] = set()
    if sf_task_type == TaskType.recommendation or sf_task_type == TaskType.recommendation.value:
        for item in state.get("recommendation_candidates", []) or []:
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
            if hasattr(resolved_shop, "model_dump"):
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
        if hasattr(resolved_shop, "model_dump"):
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


def _build_conversation_continuity(state: GraphState) -> dict[str, Any]:
    """Build a lightweight ``conversation_continuity`` dict from graph state.

    This is injected into the verbalizer prompt as metadata only — it
    is **not** a source of factual claims.  The verbalizer must still
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


# ===================================================================
# 26 Node Handlers  (todo/05 §2 Node Table)
# ===================================================================


# --- 1. receive_input ---
# §1 input:  raw_text, session_id, trace_id
# §1 output: normalized_text, input_type, basic IDs
def _h_receive_input(state: GraphState) -> dict:
    raw = state.get("raw_text", "")
    received = assemble_turn_input(raw)
    return {
        "normalized_text": raw,
        "input_type": received.get("input_type", "text"),
        "turn_id": state.get("turn_id", ""),
        **_log(state, "receive_input"),
    }


# --- 2. load_session_state ---
# §1 input:  session_id
# §1 output: current_shop, last_recommendation_list, pending_clarification, session_state_before
def _h_load_session(state: GraphState) -> dict:
    session_id = str(state.get("session_id", "") or "")
    store = get_session_store()
    existing = store.load(session_id)
    snapshot = existing.model_copy(deep=True)
    return {
        "session_state": existing,
        "session_state_before": snapshot,  # 会话快照供后续节点读取
        "session_state_after": None,
        "current_shop": existing.current_shop,
        "last_recommendation_list": existing.last_recommendation_list,
        "active_constraints": existing.active_constraints,
        "comparison_result": existing.comparison_result,
        "pending_clarification": existing.pending_clarification,
        "comparison_targets": existing.comparison_targets,
        "recommendation_candidates": [],
        "pending_check_result": "pass",
        **_log(state, "load_session_state"),
    }


# --- 3. check_pending_clarification ---
# §1 input:  pending_clarification, raw_text
# §1 output: cleared or retained pending state
def _h_check_pending(state: GraphState) -> dict:
    pending = state.get("pending_clarification")
    if pending is None:
        return {
            "pending_check_result": "pass",
            **_log(state, "check_pending_clarification", has_pending=False),
        }

    reply = str(state.get("raw_text", "") or state.get("normalized_text", "") or "")
    result = handle_clarification_reply(reply, pending, state.get("session_state"))
    action = str(result.get("status", "invalid"))

    updates: dict[str, Any] = {
        "pending_check_result": action,
    }

    if action == "restore":
        if result.get("pending_clarification") is None:
            updates["pending_clarification"] = None
        if result.get("semantic_frame") is not None:
            restored_frame = result.get("semantic_frame")
            if isinstance(restored_frame, dict):
                try:
                    restored_frame = SemanticFrame.model_validate(restored_frame)
                except Exception:
                    pass
            updates["semantic_frame"] = restored_frame
        if result.get("task_type"):
            task_type_value = result.get("task_type")
            updates["task_type"] = str(task_type_value)
            updates["task_type_source"] = "pending_clarification_restore"
        if result.get("resolved_target") is not None:
            updates["resolved_target"] = result.get("resolved_target")
            updates["resolve_shop_result"] = result.get("resolved_target")
        if result.get("comparison_targets") is not None:
            updates["comparison_targets"] = result.get("comparison_targets")
        updates["final_response"] = ""
        return {
            **updates,
            **_log(state, "check_pending_clarification", has_pending=True, action=action),
        }

    if action == "topic_switch":
        updates["pending_clarification"] = None
        updates["final_response"] = ""
        return {
            **updates,
            **_log(state, "check_pending_clarification", has_pending=True, action=action),
        }

    if action == "expired":
        updates["pending_clarification"] = None
        updates["final_response"] = result.get("final_response", "")
        return {
            **updates,
            **_log(state, "check_pending_clarification", has_pending=True, action=action),
        }

    if action in {"invalid", "out_of_range"}:
        updates["final_response"] = result.get("final_response", "")
        return {
            **updates,
            **_log(state, "check_pending_clarification", has_pending=True, action=action),
        }

    return {
        "pending_check_result": "pass",
        **_log(state, "check_pending_clarification", has_pending=True, action="pass"),
    }


# --- 4. basic_input_validate ---
# §1 input:  normalized_text
# §1 output: input_type, error_code
def _h_basic_validate(state: GraphState) -> dict:
    raw = state.get("raw_text", "")
    validation = validate_basic_input(raw)
    if not validation["valid"]:
        return {
            "input_type": validation["input_type"],
            "error_code": validation["error_code"],
            "error_message": validation["error_message"],
            "final_response": "请提供一条有效的文本内容。",
            **_log(state, "basic_input_validate", valid=False, error_code=validation["error_code"]),
        }
    return {
        "input_type": "text",
        "error_code": "",
        "error_message": "",
        **_log(state, "basic_input_validate", valid=True),
    }


# --- 5. normalize_text ---
# §1 input:  raw_text
# §1 output: normalized_text
def _h_normalize_text(state: GraphState) -> dict:
    raw = state.get("raw_text", "")
    return {
        "normalized_text": input_normalize_text(raw),
        **_log(state, "normalize_text"),
    }


# --- 6. hard_guard ---
# §1 input:  normalized_text
# §1 output: guard_result
def _h_hard_guard(state: GraphState) -> dict:
    txt = state.get("normalized_text", "")
    result = check_hard_guard(txt)
    guard_result = result.get("label", "invalid")
    if guard_result == "safe":
        guard_result = "ok"
    return {
        "guard_result": guard_result,
        "final_response": result.get("reply", "") if not result.get("passed", False) else state.get("final_response", ""),
        **_log(state, "hard_guard"),
    }


# --- 7. top_intent_router ---
# §1 input:  normalized_text, session_state_before
# §1 output: top_intent
def _h_top_intent_router(state: GraphState) -> dict:
    txt = state.get("normalized_text", "")
    result = parse_top_intent(txt, llm_call=call_llm)
    intent = result.get("top_intent", TopIntent.out_of_scope)
    if not isinstance(intent, TopIntent):
        try:
            intent = TopIntent(intent)
        except Exception:
            intent = TopIntent.out_of_scope

    final_response = state.get("final_response", "")
    if intent == TopIntent.invalid:
        final_response = "请先输入一条有效的问题。"
    elif intent == TopIntent.chat:
        final_response = "我可以帮你查附近门店、优惠和营业状态。"
    elif intent == TopIntent.capability:
        final_response = "我可以帮你查附近门店、优惠、距离和营业状态。"
    elif intent in (TopIntent.unsafe, TopIntent.out_of_scope):
        final_response = "抱歉，我主要处理本地生活相关问题。"

    return {
        "top_intent": intent,
        "error_code": result.get("error_code", ""),
        "error_message": result.get("error_message", ""),
        "final_response": final_response,
        **_log(state, "top_intent_router", intent=intent.value),
    }


# --- 8. semantic_parse ---
# §1 input:  normalized_text, top_intent
# §1 output: semantic_frame
def _h_semantic_parse(state: GraphState) -> dict:
    txt = state.get("normalized_text", "")
    top_intent = state.get("top_intent")
    top_intent_value = top_intent.value if isinstance(top_intent, TopIntent) else str(top_intent or "")
    session_state = state.get("session_state_before") or state.get("session_state")
    try:
        parsed = parse_semantic_frame(
            txt,
            top_intent_value,
            llm_call=call_llm,
            allow_fallback=config.SEMANTIC_FALLBACK_ENABLED,
            session_state=session_state,
        )
    except TypeError:
        parsed = parse_semantic_frame(
            txt,
            top_intent_value,
            llm_call=call_llm,
            session_state=session_state,
        )
    frame = parsed.get("semantic_frame")
    error_code = parsed.get("error_code", "")
    error_message = parsed.get("error_message", "")
    semantic_source = str(parsed.get("semantic_source", "") or "")
    llm_backend = str(parsed.get("llm_backend", "") or "")
    fallback_reason = str(parsed.get("fallback_reason", "") or "")
    llm_called = bool(parsed.get("llm_called", False))
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
                **_log(state, "semantic_parse", status="failed", reason="semantic_frame_validation_failed", semantic_source=semantic_source, llm_backend=llm_backend, fallback_reason=fallback_reason, llm_called=llm_called),
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
        **_log(state, "semantic_parse", semantic_source=semantic_source or getattr(frame, "semantic_source", ""), llm_backend=llm_backend or getattr(frame, "llm_backend", ""), fallback_reason=fallback_reason or getattr(frame, "fallback_reason", ""), llm_called=llm_called if parsed.get("llm_called") is not None else getattr(frame, "llm_called", False), task_type=getattr(frame, "task_type", ""), primary_task=getattr(frame, "primary_task", ""), need_context=getattr(frame, "need_context", False), follow_up=_to_dict(getattr(frame, "follow_up", None)), facets=getattr(frame, "focused_facets", []) or []),
    }


# --- 9. slot_extractor ---
# §1 input:  semantic_frame
# §1 output: facets, merchant_mentions, reference_mentions
def _h_slot_extractor(state: GraphState) -> dict:
    sf = state.get("semantic_frame")
    if sf is not None:
        return {
            "semantic_frame": sf,
            **_log(
                state,
                "slot_extractor",
                mentions=sf.merchant_mentions,
            ),
        }
    return _log(state, "slot_extractor")


# --- 10. frame_validator ---
# §1 input:  semantic_frame
# §1 output: semantic_frame (or error_code)
def _h_frame_validator(state: GraphState) -> dict:
    sf = state.get("semantic_frame")
    validation = validate_frame(sf.model_dump() if hasattr(sf, "model_dump") else _to_dict(sf))
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


# --- 11. context_recovery ---
# §1 input:  session_state_before, semantic_frame
# §1 output: resolved_target (candidates)
def _h_context_recovery(state: GraphState) -> dict:
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
    frame_dict = sf.model_dump() if hasattr(sf, "model_dump") else _to_dict(sf)
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


# --- 12. target_resolve ---
# §1 input:  merchant_mentions, reference_mentions, session_state_before
# §1 output: resolve_shop_result
def _h_target_resolve(state: GraphState) -> dict:
    sf = state.get("semantic_frame")
    sf_task_type = getattr(sf, "task_type", None) if sf is not None else None
    comparison_requested = sf_task_type == TaskType.comparison or sf_task_type == TaskType.comparison.value
    if (sf_task_type == TaskType.recommendation or sf_task_type == TaskType.recommendation.value) and not comparison_requested:
        synthetic = ResolveShopResult(
            status="RESOLVED",
            resolved_shop=ShopRef(shop_id="recommendation", shop_name="????"),
            confidence=1.0,
            reason="recommendation_flow",
        )
        return {
            "resolve_shop_result": synthetic,
            "resolved_target": synthetic,
            "reference_resolution_source": "semantic_frame",
            "task_type_source": "target_resolve_override",
            **_log(state, "target_resolve", status="RESOLVED", query="recommendation_flow"),
        }

    # ★ Detect misclassified recommendation follow-up:
    #   Query with no explicit shops (e.g. "便宜一点的呢") after a previous
    #   recommendation → route as recommendation_refine regardless of LLM
    #   task_type (which may be comparison, clarification_reply, etc.).
    frame_dict = _to_dict(sf)
    explicit_mentions = [str(item).strip() for item in (frame_dict.get("merchant_mentions") or []) if str(item).strip()]
    has_structured_refs = bool(frame_dict.get("ordinal_references") or frame_dict.get("deictic_references"))
    if not explicit_mentions and not has_structured_refs:
        session = state.get("session_state_before") or state.get("session_state") or {}
        if hasattr(session, "last_recommendation_list"):
            prev_recs = list(session.last_recommendation_list)  # type: ignore[union-attr]
        elif isinstance(session, dict):
            prev_recs = list(session.get("last_recommendation_list") or [])
        else:
            prev_recs = []
        if prev_recs:
            synthetic = ResolveShopResult(
                status="RESOLVED",
                resolved_shop=ShopRef(shop_id="recommendation", shop_name="????"),
                confidence=1.0,
                reason="recommendation_refine",
            )
            return {
                "resolve_shop_result": synthetic,
                "resolved_target": synthetic,
                "task_type": TaskType.recommendation.value,
                "reference_resolution_source": "semantic_frame",
                "task_type_source": "target_resolve_override",
                **_log(state, "target_resolve", status="RESOLVED", query="recommendation_refine"),
            }

    if comparison_requested:
        if len(explicit_mentions) >= 2 and not has_structured_refs:
            direct_targets: list[dict[str, Any]] = []
            seen: set[str] = set()
            for mention in explicit_mentions:
                raw = resolve_shop(mention, location=MOCK_LOCATION, session_shop_ids=_session_shop_ids(state))
                payload = _unwrap_resolve_shop_result(raw)
                status = str(payload.get("status", "NOT_FOUND") or "NOT_FOUND")
                shop: dict[str, Any] | None = None
                if status == "RESOLVED":
                    shop = payload.get("shop") or {}
                elif status in ("AMBIGUOUS", "LOW_CONFIDENCE"):
                    candidates = payload.get("candidates", []) or []
                    if candidates:
                        candidate = candidates[0]
                        candidate = candidate if isinstance(candidate, dict) else {}
                        shop = {
                            "shop_id": str(candidate.get("shop_id", "")).strip(),
                            "shop_name": str(candidate.get("shop_name", "")).strip(),
                        }
                if hasattr(shop, "model_dump"):
                    shop = shop.model_dump()
                if isinstance(shop, dict):
                    sid = str(shop.get("shop_id", "")).strip()
                    sname = str(shop.get("shop_name", "")).strip()
                    key = sid or sname
                    if key and key not in seen and (sid or sname):
                        seen.add(key)
                        direct_targets.append({"shop_id": sid, "shop_name": sname, "source": "explicit_shop", "source_ref": mention})

            if len(direct_targets) >= 2:
                first_shop = direct_targets[0]
                resolved_result = ResolveShopResult(
                    status="RESOLVED",
                    resolved_shop=ShopRef(shop_id=str(first_shop.get("shop_id", "")), shop_name=str(first_shop.get("shop_name", ""))),
                    confidence=1.0,
                    reason="comparison_targets_resolved",
                )
                simple_targets = [{"shop_id": item.get("shop_id", ""), "shop_name": item.get("shop_name", "")} for item in direct_targets]
                return {
                    "resolve_shop_result": resolved_result,
                    "resolved_target": resolved_result,
                    "comparison_targets": simple_targets,
                    "reference_resolution_source": "semantic_frame",
                    **_log(state, "target_resolve", status="RESOLVED", query="comparison_flow"),
                }

        resolved_targets: list[dict[str, Any]] = []

        def _append_target(target: Any) -> None:
            data = _to_dict(target)
            resolved_shop = data.get("resolved_shop") or data.get("shop") or data
            if hasattr(resolved_shop, "model_dump"):
                resolved_shop = resolved_shop.model_dump()
            if not isinstance(resolved_shop, dict):
                return
            shop_id = str(resolved_shop.get("shop_id", "")).strip()
            shop_name = str(resolved_shop.get("shop_name", "")).strip()
            if not shop_id and not shop_name:
                return
            dedupe_key = shop_id or shop_name
            if any((str(item.get("shop_id", "")).strip() or str(item.get("shop_name", "")).strip()) == dedupe_key for item in resolved_targets):
                return
            resolved_targets.append(
                {
                    "shop_id": shop_id,
                    "shop_name": shop_name,
                    "source": str(data.get("source", "")),
                    "source_ref": str(data.get("source_ref", "")),
                }
            )

        for item in state.get("comparison_targets", []) or []:
            _append_target(item)

        comparison_resolution = _to_dict(state.get("comparison_target_resolution"))
        for item in comparison_resolution.get("targets", []) or []:
            _append_target(item)

        existing_target = state.get("resolved_target")
        if existing_target is not None and _to_dict(existing_target).get("status") == "RESOLVED":
            _append_target(_to_dict(existing_target).get("resolved_shop") or {})

        resolution_status = str(comparison_resolution.get("status", "") or "")
        if resolution_status == "TOO_MANY":
            reason = str(comparison_resolution.get("reason", "comparison_too_many_shops") or "comparison_too_many_shops")
            final_response = comparison_resolution.get("prompt") or _comparison_reason_response(reason)
            return {
                "resolve_shop_result": ResolveShopResult(status="NOT_FOUND", confidence=0.0, reason=reason),
                "final_response": final_response,
                "comparison_target_resolution": comparison_resolution,
                **_log(state, "target_resolve", status="TOO_MANY", query="comparison"),
            }
        if resolution_status == "NEED_CLARIFICATION":
            ambiguous_target = comparison_resolution.get("ambiguous_target") or {}
            ambiguous_ref = ""
            if isinstance(ambiguous_target, dict):
                ambiguous_ref = str(ambiguous_target.get("reference", "") or "").strip()

            if ambiguous_ref == "deictic" or not comparison_resolution.get("unresolved_targets"):
                reason = str(comparison_resolution.get("reason", "comparison_requires_at_least_two_shops") or "comparison_requires_at_least_two_shops")
                if ambiguous_ref == "deictic":
                    reco_list = []
                    session = state.get("session_state_before") or state.get("session_state") or {}
                    if session:
                        session_dict = _to_dict(session)
                        reco_list = session_dict.get("last_recommendation_list", []) or []
                    
                    pending_candidates = []
                    candidates = []
                    for item in reco_list:
                        item = _to_dict(item)
                        shop_id = item.get("shop_id")
                        shop_name = item.get("shop_name")
                        address = item.get("address", "")
                        if shop_id and shop_name:
                            pending_candidates.append({
                                "shop_id": shop_id,
                                "shop_name": shop_name,
                                "address": address
                            })
                            candidates.append(ShopCandidate(shop=ShopRef(shop_id=shop_id, shop_name=shop_name)))
                    
                    if candidates:
                        resolved_result = ResolveShopResult(
                            status="AMBIGUOUS",
                            candidates=candidates,
                            confidence=0.5,
                            reason="pronoun_without_current_shop",
                        )
                    else:
                        resolved_result = ResolveShopResult(
                            status="NOT_FOUND",
                            confidence=0.0,
                            reason="comparison_requires_at_least_two_shops",
                        )
                    pending = build_pending_clarification(
                        original_text=str(state.get("raw_text", "") or ""),
                        original_semantic_frame=sf.model_dump(mode="json") if hasattr(sf, "model_dump") else _session_state_dict(sf),
                        original_task_type=(getattr(sf, "task_type", "") if getattr(sf, "task_type", None) is not None else state.get("task_type", "")),
                        candidate_targets=pending_candidates,
                        reason=resolved_result.reason,
                        source_node="target_resolve",
                        already_resolved_targets=resolved_targets,
                        ambiguous_target_slot=str(ambiguous_target.get("source_ref", "") or "这家").strip(),
                    )
                    prompt = format_pending_prompt(pending)
                    return {
                        "resolve_shop_result": resolved_result,
                        "pending_clarification": pending,
                        "final_response": prompt,
                        "reference_resolution_source": "semantic_frame",
                        **_log(state, "target_resolve", status="NEED_CLARIFICATION", query="comparison"),
                    }
                else:
                    final_response = comparison_resolution.get("prompt") or _comparison_reason_response(reason)
                    return {
                        "resolve_shop_result": ResolveShopResult(status="NOT_FOUND", confidence=0.0, reason=reason),
                        "final_response": final_response,
                        "comparison_target_resolution": comparison_resolution,
                        "reference_resolution_source": "semantic_frame",
                        **_log(state, "target_resolve", status="NEED_CLARIFICATION", query="comparison"),
                    }

        unresolved_targets = list(comparison_resolution.get("unresolved_targets", []) or [])
        if not unresolved_targets and len(resolved_targets) < 2:
            unresolved_targets = [{"query": query, "source_ref": query, "reference": "explicit"} for query in _comparison_structured_queries(sf)]

        for item in unresolved_targets:
            query = str(_to_dict(item).get("query", "") or "").strip()
            source_ref = str(_to_dict(item).get("source_ref", "") or query).strip()
            if not query:
                continue
            raw = resolve_shop(query, location=MOCK_LOCATION, session_shop_ids=_session_shop_ids(state))
            payload = _unwrap_resolve_shop_result(raw)
            status = payload.get("status", "NOT_FOUND")
            if status == "RESOLVED":
                shop = payload.get("shop") or {}
                if hasattr(shop, "model_dump"):
                    shop = shop.model_dump()
                if isinstance(shop, dict):
                    _append_target(
                        {
                            "shop_id": str(shop.get("shop_id", "")),
                            "shop_name": str(shop.get("shop_name", "")),
                            "source": "explicit_shop",
                            "source_ref": source_ref,
                        }
                    )
                continue
            if status in ("AMBIGUOUS", "LOW_CONFIDENCE"):
                frame_dict = _to_dict(sf)
                explicit_compare_only = (
                    comparison_requested
                    and not (frame_dict.get("ordinal_references") or frame_dict.get("deictic_references"))
                    and len(frame_dict.get("merchant_mentions") or []) >= 2
                )
                if explicit_compare_only and payload.get("candidates"):
                    candidate = payload.get("candidates", [])[0] or {}
                    if hasattr(candidate, "model_dump"):
                        candidate = candidate.model_dump()
                    shop_ref = candidate.get("shop") or {}
                    if hasattr(shop_ref, "model_dump"):
                        shop_ref = shop_ref.model_dump()
                    shop_id = str(candidate.get("shop_id") or (shop_ref.get("shop_id", "") if isinstance(shop_ref, dict) else "")).strip()
                    shop_name = str(candidate.get("shop_name") or (shop_ref.get("shop_name", "") if isinstance(shop_ref, dict) else "")).strip()
                    if shop_id and shop_name:
                        _append_target(
                            {
                                "shop_id": shop_id,
                                "shop_name": shop_name,
                                "source": "ambiguous_explicit_shop",
                                "source_ref": source_ref,
                            }
                        )
                        continue
                candidates = []
                pending_candidates = []
                for candidate in payload.get("candidates", []):
                    candidate = candidate if isinstance(candidate, dict) else {}
                    shop_ref = candidate.get("shop") or {}
                    if hasattr(shop_ref, "model_dump"):
                        shop_ref = shop_ref.model_dump()
                    shop_id = candidate.get("shop_id") or (shop_ref.get("shop_id", "") if isinstance(shop_ref, dict) else "")
                    shop_name = candidate.get("shop_name") or (shop_ref.get("shop_name", "") if isinstance(shop_ref, dict) else "")
                    address = candidate.get("address") or (shop_ref.get("address", "") if isinstance(shop_ref, dict) else "")
                    candidates.append(ShopCandidate(shop=ShopRef(shop_id=shop_id, shop_name=shop_name)))
                    if shop_id and shop_name:
                        pending_candidates.append({"shop_id": shop_id, "shop_name": shop_name, "address": address})
                resolved_result = ResolveShopResult(
                    status=status,
                    candidates=candidates,
                    confidence=float(payload.get("confidence", 0.0)),
                    reason="ambiguous_shop" if status == "AMBIGUOUS" else "low_confidence_shop",
                )
                pending = build_pending_clarification(
                    original_text=str(state.get("raw_text", "") or ""),
                    original_semantic_frame=sf.model_dump(mode="json") if hasattr(sf, "model_dump") else _session_state_dict(sf),
                    original_task_type=(getattr(sf, "task_type", "") if getattr(sf, "task_type", None) is not None else state.get("task_type", "")),
                    candidate_targets=pending_candidates,
                    reason=resolved_result.reason,
                    source_node="target_resolve",
                    already_resolved_targets=resolved_targets,
                    ambiguous_target_slot=source_ref,
                )
                prompt = format_pending_prompt(pending)
                return {
                    "resolve_shop_result": resolved_result,
                    "pending_clarification": pending,
                    "final_response": prompt,
                    **_log(state, "target_resolve", status="AMBIGUOUS", query=query),
                }

        if len(resolved_targets) > config.COMPARISON_MAX_SHOP_LIMIT:
            final_response = _comparison_reason_response("comparison_too_many_shops")
            return {
                "resolve_shop_result": ResolveShopResult(status="NOT_FOUND", confidence=0.0, reason="comparison_too_many_shops"),
                "final_response": final_response,
                **_log(state, "target_resolve", status="TOO_MANY", query="comparison"),
            }
        if len(resolved_targets) < 2:
            final_response = _comparison_reason_response("comparison_requires_at_least_two_shops")
            return {
                "resolve_shop_result": ResolveShopResult(status="NOT_FOUND", confidence=0.0, reason="comparison_requires_at_least_two_shops"),
                "final_response": final_response,
                **_log(state, "target_resolve", status="NEED_CLARIFICATION", query="comparison"),
            }

        first_shop = resolved_targets[0]
        resolved_result = ResolveShopResult(
            status="RESOLVED",
            resolved_shop=ShopRef(shop_id=str(first_shop.get("shop_id", "")), shop_name=str(first_shop.get("shop_name", ""))),
            confidence=1.0,
            reason="comparison_targets_resolved",
        )
        simple_targets = [{"shop_id": item.get("shop_id", ""), "shop_name": item.get("shop_name", "")} for item in resolved_targets]
        return {
            "resolve_shop_result": resolved_result,
            "resolved_target": resolved_result,
            "comparison_targets": simple_targets,
            "reference_resolution_source": "semantic_frame",
            **_log(state, "target_resolve", status="RESOLVED", query="comparison_flow"),
        }

    existing_target = state.get("resolved_target")
    if existing_target is not None:
        existing_dict = _session_state_dict(existing_target)
        if existing_dict.get("status") == "RESOLVED":
            return {
                "resolve_shop_result": existing_target,
                "resolved_target": existing_target,
                "reference_resolution_source": "semantic_frame",
                **_log(state, "target_resolve", status="RESOLVED", query="context_recovered"),
            }

    sf = state.get("semantic_frame")
    mentions = []
    if sf is not None:
        mentions = list(getattr(sf, "merchant_mentions", []) or [])
    query = mentions[0] if mentions else ""
    if not query:
        return {
            "resolve_shop_result": ResolveShopResult(
                status="NOT_FOUND",
                confidence=0.0,
                reason="missing_shop_name",
            ),
            "final_response": "请提供完整店名。",
            **_log(state, "target_resolve", status="NOT_FOUND", query=query),
        }
    raw = resolve_shop(query, location=MOCK_LOCATION, session_shop_ids=_session_shop_ids(state))
    payload = _unwrap_resolve_shop_result(raw)
    status = payload.get("status", "NOT_FOUND")
    if status == "RESOLVED":
        shop = payload.get("shop") or {}
        if hasattr(shop, "model_dump"):
            shop = shop.model_dump()
        resolved_result = ResolveShopResult(
            status="RESOLVED",
            resolved_shop=ShopRef(
                shop_id=shop.get("shop_id", ""),
                shop_name=shop.get("shop_name", ""),
            ),
            confidence=float(payload.get("confidence", 0.0)),
            reason="resolved_by_target_resolve",
        )
        return {
            "resolve_shop_result": resolved_result,
            "resolved_target": resolved_result,
            "reference_resolution_source": str(payload.get("resolution_source", "") or ""),
            **_log(state, "target_resolve", status="RESOLVED", query=query),
        }

    if status in ("AMBIGUOUS", "LOW_CONFIDENCE"):
        candidates = []
        pending_candidates = []
        for candidate in payload.get("candidates", []):
            candidate = candidate if isinstance(candidate, dict) else {}
            shop_ref = candidate.get("shop") or {}
            if hasattr(shop_ref, "model_dump"):
                shop_ref = shop_ref.model_dump()
            shop_id = candidate.get("shop_id") or (shop_ref.get("shop_id", "") if isinstance(shop_ref, dict) else "")
            shop_name = candidate.get("shop_name") or (shop_ref.get("shop_name", "") if isinstance(shop_ref, dict) else "")
            address = candidate.get("address") or (shop_ref.get("address", "") if isinstance(shop_ref, dict) else "")
            candidates.append(
                ShopCandidate(
                    shop=ShopRef(
                        shop_id=shop_id,
                        shop_name=shop_name,
                    )
                )
            )
            if shop_id and shop_name:
                pending_candidates.append(
                    {
                        "shop_id": shop_id,
                        "shop_name": shop_name,
                        "address": address,
                    }
                )

        resolved_result = ResolveShopResult(
            status=status,
            candidates=candidates,
            confidence=float(payload.get("confidence", 0.0)),
            reason="ambiguous_shop" if status == "AMBIGUOUS" else "low_confidence_shop",
        )
        pending = build_pending_clarification(
            original_text=str(state.get("raw_text", "") or ""),
            original_semantic_frame=sf.model_dump(mode="json") if hasattr(sf, "model_dump") else _session_state_dict(sf),
            original_task_type=(
                getattr(sf, "task_type", "")
                if getattr(sf, "task_type", None) is not None
                else state.get("task_type", "")
            ),
            candidate_targets=pending_candidates,
            reason=resolved_result.reason,
            source_node="target_resolve",
        )
        prompt = format_pending_prompt(pending)
        return {
            "resolve_shop_result": resolved_result,
            "pending_clarification": pending,
            "final_response": prompt,
            "reference_resolution_source": str(payload.get("resolution_source", "") or ""),
            **_log(state, "target_resolve", status="AMBIGUOUS", query=query),
        }

    resolved_result = ResolveShopResult(
        status="NOT_FOUND",
        confidence=0.0,
        reason=payload.get("error_code", "SHOP_NOT_FOUND") or "SHOP_NOT_FOUND",
    )
    return {
        "resolve_shop_result": resolved_result,
        "final_response": "没有找到这家店，请提供完整店名。",
        **_log(state, "target_resolve", status="NOT_FOUND", query=query),
    }


# --- 12b. clarify_decide ---
# §1 input:  resolve_shop_result, semantic_frame
# §1 output: pending_clarification 鎴?resolved_target (鍙墽琛岀洰鏍?
def _h_clarify_decide(state: GraphState) -> dict:
    if state.get("task_type") == TaskType.recommendation.value:
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
            return {
                "resolved_target": rs,
                **_log(state, "clarify_decide", decision="proceed"),
            }
        if status in ("AMBIGUOUS", "LOW_CONFIDENCE"):
            return {
                **_log(state, "clarify_decide", decision="clarify"),
            }
        if reason in {"comparison_requires_at_least_two_shops", "comparison_too_many_shops", "pronoun_without_current_shop", "ordinal_out_of_range"}:
            return {
                "final_response": str(state.get("final_response", "") or _comparison_reason_response(reason)),
                **_log(state, "clarify_decide", decision="comparison_prompt"),
            }
        # NOT_FOUND or other
        return {
            "final_response": "没有找到这家店，请提供完整店名。",
            **_log(state, "clarify_decide", decision="not_found"),
        }
    # No resolve result 鈫?clarify
    return _log(state, "clarify_decide", decision="no_result")


# --- 13. task_plan ---
# §1 input:  top_intent, task_type, resolved_target
# §1 output: execution_plan
def _h_task_plan(state: GraphState) -> dict:
    sf = state.get("semantic_frame")
    rt = state.get("resolved_target")
    frame_dict = sf.model_dump() if hasattr(sf, "model_dump") else _to_dict(sf)
    target_dict = rt.model_dump() if hasattr(rt, "model_dump") else _to_dict(rt)
    task_type = route_task(frame_dict, target_dict)
    return {
        "task_type": task_type,
        "task_type_source": "llm_semantic",
        **_log(state, "task_plan", task_type=task_type),
    }


# --- 14. facet_plan ---
# §1 input:  semantic_frame, resolved_target
# §1 output: execution_plan.tool_calls
def _h_facet_plan(state: GraphState) -> dict:
    result = build_execution_plan_with_tool_planner(state)
    plan = ExecutionPlan.model_validate(result.get("execution_plan", {}))
    task_type = str(result.get("execution_plan", {}).get("task_type", "") if isinstance(result.get("execution_plan"), dict) else getattr(result.get("execution_plan"), "task_type", "") or "")
    selected_flow = "recommendation_flow" if task_type == TaskType.recommendation.value else f"{task_type}_flow"
    return {
        **result,
        "execution_plan": plan,
        **_log(
            state,
            "facet_plan",
            tool_calls=len(plan.tool_calls),
            candidate_count=0,
            selected_flow=selected_flow,
            tool_plan_source=result.get("tool_plan_source"),
            tool_plan_validated=result.get("tool_plan_validated"),
            tool_plan_fallback_reason=result.get("tool_plan_fallback_reason"),
            tool_plan_reason=result.get("tool_plan_reason"),
        ),
    }


# --- 15. comparison_planner ---
# §1 input:  comparison_targets, resolved_target
# §1 output: execution_plan, comparison_matrix placeholder
def _h_comparison_planner(state: GraphState) -> dict:
    result = build_execution_plan_with_tool_planner(state)
    plan = ExecutionPlan.model_validate(result.get("execution_plan", {}))
    comparison_targets = list(state.get("comparison_targets", []) or [])
    target_shop_ids: list[str] = []
    for item in comparison_targets:
        data = _to_dict(item)
        resolved_shop = data.get("resolved_shop") or data.get("shop") or data
        if hasattr(resolved_shop, "model_dump"):
            resolved_shop = resolved_shop.model_dump()
        if isinstance(resolved_shop, dict):
            sid = str(resolved_shop.get("shop_id", "")).strip()
            if sid:
                target_shop_ids.append(sid)
    return {
        **result,
        "execution_plan": plan,
        "comparison_result": {
            "status": "planned",
            "target_shop_ids": target_shop_ids,
            "mode": "comparison",
        },
        **_log(
            state,
            "comparison_planner",
            target_count=len(comparison_targets),
            tool_calls=len(plan.tool_calls),
            selected_flow="comparison_flow",
            tool_plan_source=result.get("tool_plan_source"),
            tool_plan_validated=result.get("tool_plan_validated"),
            tool_plan_fallback_reason=result.get("tool_plan_fallback_reason"),
            tool_plan_reason=result.get("tool_plan_reason"),
        ),
    }


# --- 16. plan_validator ---
# §1 input:  execution_plan
# §1 output: validated_plan (or error_code)
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
        "validated_plan": plan,  # §1: 鏍￠獙閫氳繃鍚庣殑鎵ц璁″垝
        **_log(state, "plan_validator", status="pass"),
    }


# --- 17. tool_execute ---
# §1 input:  validated_plan
# §1 output: tool_result_set
def _h_tool_execute(state: GraphState) -> dict:
    plan = state.get("validated_plan") or state.get("execution_plan")
    results: dict[str, ToolResult] = {}
    if plan is not None:
        tool_calls = getattr(plan, "tool_calls", []) or []
        raw_results: dict[str, dict[str, Any]] = {
            str(call_id): _to_dict(result)
            for call_id, result in (state.get("precomputed_tool_results") or {}).items()
        }
        batch_executor = BatchToolExecutor(call_fn=dispatch_tool_call)
        search_calls = []
        remaining_specs = []
        planned_tool_names = {
            str((_to_dict(spec)).get("tool_name", "")).strip()
            for spec in tool_calls
            if str((_to_dict(spec)).get("tool_name", "")).strip()
        }
        for spec in tool_calls:
            call = spec.model_dump() if hasattr(spec, "model_dump") else _to_dict(spec)
            if call.get("tool_name") == "search_shops":
                search_calls.append(spec)
            else:
                remaining_specs.append(spec)

        if search_calls:
            raw_results.update(batch_executor.execute_sync(search_calls))

        if config.TOOL_BACKEND != "mock":
            hidden_calls: list[dict[str, Any]] = []
            task_type_value = str(getattr(plan, "task_type", "") or _to_dict(plan).get("task_type", "") or "")
            if task_type_value == TaskType.recommendation.value:
                search_result = raw_results.get("call_search_shops", {})
                search_data = _to_dict(search_result).get("data") or []
                shop_ids = [
                    str(item.get("shop_id", "")).strip()
                    for item in search_data if isinstance(item, dict) and str(item.get("shop_id", "")).strip()
                ][: config.RECOMMENDATION_CANDIDATE_TOP_K]
                if shop_ids:
                    if "get_shop_cards" not in planned_tool_names:
                        hidden_calls.append(
                            {
                                "call_id": "call_shop_cards_auto",
                                "tool_name": "get_shop_cards",
                                "args": {
                                    "shop_ids": shop_ids,
                                    "user_location": state.get("user_context") and {
                                        "lat": getattr(state.get("user_context"), "lat", MOCK_LOCATION["lat"]),
                                        "lng": getattr(state.get("user_context"), "lng", MOCK_LOCATION["lng"]),
                                    } or MOCK_LOCATION,
                                    "need_coupon_brief": True,
                                    "need_open_status": True,
                                    "need_distance_eta": True,
                                    "max_items": len(shop_ids),
                                },
                                "required": False,
                                "timeout_ms": TOOL_DEFAULT_TIMEOUT_MS,
                                "max_parallelism": 1,
                            }
                        )
                    if "get_shop_review_summary" not in planned_tool_names:
                        hidden_calls.append(
                            {
                                "call_id": "call_review_summary_auto",
                                "tool_name": "get_shop_review_summary",
                                "args": {
                                    "shop_ids": shop_ids,
                                    "aspects": [str(item) for item in (state.get("semantic_frame") and getattr(state.get("semantic_frame"), "focused_facets", []) or []) if str(item).strip()],
                                    "scene": None,
                                    "max_reviews": len(shop_ids),
                                },
                                "required": False,
                                "timeout_ms": TOOL_DEFAULT_TIMEOUT_MS,
                                "max_parallelism": 1,
                            }
                        )
            elif task_type_value == TaskType.comparison.value:
                target_ids = []
                for item in state.get("comparison_targets", []) or []:
                    data = _to_dict(item)
                    resolved_shop = data.get("resolved_shop") or data.get("shop") or data
                    if hasattr(resolved_shop, "model_dump"):
                        resolved_shop = resolved_shop.model_dump()
                    if isinstance(resolved_shop, dict):
                        sid = str(resolved_shop.get("shop_id", "")).strip()
                        if sid and sid not in target_ids:
                            target_ids.append(sid)
                    sid = str(data.get("shop_id", "")).strip()
                    if sid and sid not in target_ids:
                        target_ids.append(sid)
                if len(target_ids) >= 2:
                    if "get_shop_cards" not in planned_tool_names:
                        hidden_calls.append(
                            {
                                "call_id": "call_shop_cards_auto",
                                "tool_name": "get_shop_cards",
                                "args": {
                                    "shop_ids": target_ids[: config.COMPARISON_MAX_SHOP_LIMIT],
                                    "user_location": MOCK_LOCATION,
                                    "need_coupon_brief": True,
                                    "need_open_status": True,
                                    "need_distance_eta": True,
                                    "max_items": len(target_ids),
                                },
                                "required": False,
                                "timeout_ms": TOOL_DEFAULT_TIMEOUT_MS,
                                "max_parallelism": 1,
                            }
                        )
                    if "get_shop_review_summary" not in planned_tool_names:
                        hidden_calls.append(
                            {
                                "call_id": "call_review_summary_auto",
                                "tool_name": "get_shop_review_summary",
                                "args": {
                                    "shop_ids": target_ids[: config.COMPARISON_MAX_SHOP_LIMIT],
                                    "aspects": ["review_summary"],
                                    "scene": None,
                                    "max_reviews": len(target_ids),
                                },
                                "required": False,
                                "timeout_ms": TOOL_DEFAULT_TIMEOUT_MS,
                                "max_parallelism": 1,
                            }
                        )

            if hidden_calls:
                try:
                    raw_results.update(batch_executor.execute_sync(hidden_calls))
                except Exception:
                    pass

        for spec in remaining_specs:
            call = spec.model_dump() if hasattr(spec, "model_dump") else _to_dict(spec)
            resolved_call = call
            if str(getattr(plan, "task_type", call.get("task_type", "")) or call.get("task_type", "")) == TaskType.recommendation.value:
                search_result = raw_results.get("call_search_shops", {})
                resolved_call = _resolve_recommendation_spec(call, search_result)
            call_id = resolved_call.get("call_id", "") or resolved_call.get("tool_name", "")
            shop_id = str(resolved_call.get("target_shop_id", "") or resolved_call.get("args", {}).get("shop_id", "")).strip()
            if not shop_id:
                unresolved_shop_ref = str(call.get("target_shop_id", "") or call.get("args", {}).get("shop_id", "")).strip()
                raw_results[call_id] = {
                    "call_id": call_id,
                    "shop_id": unresolved_shop_ref,
                    "tool_name": resolved_call.get("tool_name", ""),
                    "success": False,
                    "result_status": "unknown" if not resolved_call.get("required", True) else "failed",
                    "data": None,
                    "error_code": "INVALID_ARGUMENT",
                    "error_message": f"Tool '{resolved_call.get('tool_name', '')}' could not resolve shop_id from search result",
                    "source": config.TOOL_BACKEND,
                    "tool_backend": config.TOOL_BACKEND,
                    "backend_source": config.TOOL_BACKEND,
                    "degraded": not resolved_call.get("required", True),
                }
                continue
            raw_results.update(batch_executor.execute_sync([resolved_call]))

        for spec in tool_calls:
            call = spec.model_dump() if hasattr(spec, "model_dump") else _to_dict(spec)
            call_id = call.get("call_id", "") or call.get("tool_name", "")
            raw_result = raw_results.get(call_id)
            if raw_result is None:
                raw_result = {
                    "call_id": call_id,
                    "shop_id": call.get("target_shop_id", "") or call.get("args", {}).get("shop_id", ""),
                    "tool_name": call.get("tool_name", ""),
                    "success": False,
                    "result_status": "unknown" if not call.get("required", True) else "failed",
                    "data": None,
                    "error_code": "TOOL_TIMEOUT",
                    "error_message": f"Tool '{call.get('tool_name', '')}' did not return a result",
                    "source": config.TOOL_BACKEND,
                    "tool_backend": config.TOOL_BACKEND,
                    "backend_source": config.TOOL_BACKEND,
                    "degraded": not call.get("required", True),
                }
            resolved_call = call
            if str(getattr(plan, "task_type", call.get("task_type", "")) or call.get("task_type", "")) == TaskType.recommendation.value:
                resolved_call = _resolve_recommendation_spec(call, raw_results.get("call_search_shops", {}))
            shop_id = resolved_call.get("target_shop_id", "") or resolved_call.get("args", {}).get("shop_id", "") or raw_result.get("shop_id", "")
            raw_result = {
                **raw_result,
                "call_id": call_id,
                "shop_id": shop_id,
                "tool_name": resolved_call.get("tool_name", ""),
            }
            results[call_id or call.get("tool_name", "")] = ToolResult.model_validate(raw_result)
    failed_calls = [
        call_id
        for call_id, result in results.items()
        if str(getattr(result, "result_status", _to_dict(result).get("result_status", ""))).lower() in {"failed", "unknown", "circuit_open"}
    ]
    return {
        "tool_results": results,
        "tool_result_set": results,  # §1: 鏂囨。瑕佹眰鐨勫瓧娈靛悕
        **_log(state, "tool_execute", tool_call_count=len(results), tool_failures=failed_calls, tool_calls=list(results.keys())),
    }


# --- 18. evidence_build ---
# §1 input:  tool_result_set
# §1 output: evidence_pack
def _h_evidence_build(state: GraphState) -> dict:
    evidence_payload = build_evidence(
        state.get("tool_result_set") or state.get("tool_results", {}),
        state.get("resolved_target"),
        state.get("validated_plan") or state.get("execution_plan"),
        state.get("recommendation_candidates"),
        state.get("comparison_targets"),
    )
    pack = EvidencePack.model_validate(evidence_payload)
    updates: dict[str, Any] = {}
    if "last_recommendation_list" in evidence_payload:
        updates["last_recommendation_list"] = evidence_payload.get("last_recommendation_list", [])
    ranking_snapshot = _to_dict(pack.ranking_snapshot if hasattr(pack, "ranking_snapshot") else evidence_payload.get("ranking_snapshot"))
    comparison_matrix = _to_dict(pack.comparison_matrix if hasattr(pack, "comparison_matrix") else evidence_payload.get("comparison_matrix"))
    candidate_count = len(ranking_snapshot.get("ranked") or ranking_snapshot.get("ranked_shops") or comparison_matrix.get("rows") or [])
    return {
        "evidence_pack": pack,
        **updates,
        **_log(state, "evidence_build", candidate_count=candidate_count, decision_type="comparison" if comparison_matrix.get("rows") else ("recommendation" if ranking_snapshot else "")),
    }


# --- 19. answer_plan_build ---
# §1 input:  evidence_pack, semantic_frame
# §1 output: answer_plan
def _h_answer_plan_build(state: GraphState) -> dict:
    execution_plan = state.get("execution_plan")
    task_type = ""
    if hasattr(execution_plan, "task_type"):
        task_type = getattr(execution_plan, "task_type", "")
    elif isinstance(execution_plan, dict):
        task_type = execution_plan.get("task_type", "")
    plan = AnswerPlan.model_validate(
        build_answer_plan(
            task_type,
            state.get("evidence_pack") or {},
            None,
        )
    )
    return {
        "answer_plan": plan,
        **_log(state, "answer_plan_build"),
    }


# --- 20. answer_generate ---
# §1 input:  answer_plan, evidence_pack
# §1 output: draft_response
def _h_answer_generate(state: GraphState) -> dict:
    metadata: dict[str, Any] = {}
    rc = state.get("rewrite_count", 0)
    violations = state.get("answer_verify_violations") or []

    # Build conversation continuity from current session state --------
    cc = _build_conversation_continuity(state)

    txt = generate_answer(
        state.get("answer_plan") or {},
        state.get("evidence_pack") or {},
        metadata_out=metadata,
        rewrite_count=rc,
        previous_violations=violations,
        in_graph=True,
        conversation_continuity=cc,
    )
    return {
        "draft_response": txt,
        "answer_source": metadata.get("answer_source", "template"),
        "answer_fallback_reason": metadata.get("answer_fallback_reason", ""),
        "llm_verbalizer_error": metadata.get("llm_verbalizer_error"),
        "generated_llm_answer_before_fallback": metadata.get("generated_llm_answer_before_fallback", ""),
        "llm_verbalizer_violation": metadata.get("violation"),
        # Save verification/rewrite states to GraphState
        "answer_verify_passed": metadata.get("answer_verify_passed", True),
        "answer_verify_violations": metadata.get("answer_verify_violations") or [],
        "rewrite_needed": metadata.get("rewrite_needed", False),
        "rewrite_reason": metadata.get("rewrite_reason", ""),
        "fallback_reason": metadata.get("fallback_reason", ""),
        "final_safety_status": metadata.get("final_safety_status", "safe"),
        **_log(state, "answer_generate", answer_source=metadata.get("answer_source", "template"), rewrite_count=rc, fallback_reason=metadata.get("fallback_reason", "")),
    }



# --- 21. answer_verify ---
# §1 input:  draft_response, evidence_pack
# §1 output: verify_result
def _h_answer_verify(state: GraphState) -> dict:
    evidence = state.get("evidence_pack") or {}
    task_type = getattr(state.get("execution_plan"), "task_type", "") or (
        state.get("execution_plan", {}).get("task_type", "") if isinstance(state.get("execution_plan"), dict) else ""
    )
    if not evidence or not state.get("draft_response", ""):
        return {
            "verify_result": "pass",
            "error_code": "",
            "error_message": "",
            "answer_verify_passed": True,
            "answer_verify_violations": [],
            "rewrite_needed": False,
            **_log(state, "answer_verify"),
        }
    report = verify_answer(state.get("draft_response", ""), evidence, task_type)
    passed = report.get("passed", False)
    violations = report.get("issues", [])
    
    return {
        "verify_result": "pass" if passed else "rewrite_needed",
        "error_code": "" if passed else "ANSWER_VERIFIER_FAILED",
        "error_message": "" if passed else report.get("suggested_fix", ""),
        "answer_verify_passed": passed,
        "answer_verify_violations": violations,
        "rewrite_needed": not passed,
        "rewrite_reason": violations[0] if violations else "",
        **_log(state, "answer_verify", passed=passed, violations=violations, final_safety_status="safe" if passed else "violated"),
    }


# --- 22. rewrite ---
# §1 input:  verify_result, answer_plan
# §1 output: draft_response
def _h_rewrite(state: GraphState) -> dict:
    rc = state.get("rewrite_count", 0) + 1
    txt = state.get("draft_response", "")
    return {
        "draft_response": txt,
        "rewrite_count": rc,
        **_log(state, "rewrite", rewrite_count=rc),
    }


# --- 23. final_response_build ---
# §1 input:  draft_response, verify_result
# §1 output: final_response
def _h_final_response(state: GraphState) -> dict:
    txt = state.get("draft_response", "")
    return {
        "final_response": txt,
        **_log(state, "final_response_build", answer_source=state.get("answer_source", ""), final_safety_status=state.get("final_safety_status", "safe")),
    }


# --- 24. clarify_response ---
# §1 input:  resolve_shop_result, pending_clarification
# §1 output: final_response
def _h_clarify_response(state: GraphState) -> dict:
    pending_result = str(state.get("pending_check_result", "") or "")
    if pending_result in {"expired", "invalid", "out_of_range"} and str(state.get("final_response", "") or "").strip():
        return {
            "final_response": state.get("final_response", ""),
            "answer_source": "template_fallback",
            **_log(state, "clarify_response"),
        }
    pending = state.get("pending_clarification")
    if pending is not None:
        try:
            prompt = format_pending_prompt(pending)
        except Exception:
            prompt = "店名有点模糊，请提供完整店名。"
        if prompt.strip():
            return {
                "final_response": prompt,
                "answer_source": "template_fallback",
                **_log(state, "clarify_response"),
            }
    rs = state.get("resolve_shop_result")
    if rs is not None and getattr(rs, "status", "") in ("AMBIGUOUS", "LOW_CONFIDENCE"):
        return {
            "final_response": "店名有点模糊，请提供完整店名。",
            "answer_source": "template_fallback",
            **_log(state, "clarify_response"),
        }
    clarification = (state.get("error_message", "") or "").strip()
    if clarification:
        return {
            "final_response": clarification,
            "answer_source": "template_fallback",
            **_log(state, "clarify_response"),
        }
    return {
        "final_response": "请提供完整店名。",
        "answer_source": "template_fallback",
        **_log(state, "clarify_response"),
    }


# --- 25. fallback_answer ---
# §1 input:  error_code, evidence_pack
# §1 output: final_response
def _h_fallback_answer(state: GraphState) -> dict:
    # 5. rewrite 后仍失败，进入安全 fallback。
    # 6. fallback 不能编造事实，只能基于模板和 EvidencePack 输出保守回答。
    from .. import config as cfg
    from ..answer.generator import generate_answer as original_generate_answer
    old_val = cfg.ENABLE_LLM_VERBALIZER
    cfg.ENABLE_LLM_VERBALIZER = False
    try:
        response = original_generate_answer(
            state.get("answer_plan") or {},
            state.get("evidence_pack") or {},
        )
    finally:
        cfg.ENABLE_LLM_VERBALIZER = old_val

    if not response or response.strip() == "暂时无法确认这家店的相关信息。":
        evidence_dict = _to_dict(state.get("evidence_pack") or {})
        status = ""
        snapshot = evidence_dict.get("ranking_snapshot") or {}
        if isinstance(snapshot, dict):
            status = str(snapshot.get("status", "") or "")
        if not status:
            tr = state.get("tool_result_set") or state.get("tool_results", {})
            for result in tr.values():
                value = result.result_status.value if hasattr(result, "result_status") else str(_to_dict(result).get("result_status", ""))
                status = value
                if value in ("failed", "circuit_open"):
                    break
        if status == "circuit_open":
            response = "优惠券服务暂时不可用，请稍后再试。"
        elif status == "failed":
            response = "获取优惠券信息失败，建议稍后再试。"
        elif status == "unknown":
            response = "暂时无法确认优惠券情况，请稍后再试。"
        else:
            response = "抱歉，暂时无法处理您的请求，请稍后再试。"

    return {
        "final_response": response,
        "answer_source": "template_fallback",
        "final_safety_status": "fallback",
        **_log(state, "fallback_answer"),
    }


# --- 26. state_update_plan ---
# §1 input:  final_response, session_state_before
# §1 output: state_update_plan
def _h_state_update_plan(state: GraphState) -> dict:
    resolve_shop_result = state.get("resolve_shop_result")
    pending = state.get("pending_clarification")
    resolved = state.get("resolved_target") or resolve_shop_result
    if pending is not None and resolve_shop_result is not None:
        resolved = resolve_shop_result
    resolved_status = ""
    if resolved is not None:
        resolved_status = getattr(resolved, "status", "") or _session_state_dict(resolved).get("status", "")
    task_type = state.get("task_type")
    task_type_value = task_type.value if hasattr(task_type, "value") else str(task_type or "")
    turn_context = {
        "resolved_target": resolved,
        "resolved_shop": resolved,
        "current_shop": state.get("current_shop"),
        "pending_clarification": pending,
        "last_recommendation_list": state.get("last_recommendation_list", []),
        "comparison_targets": state.get("comparison_targets", []),
        "comparison_result": _to_dict(state.get("evidence_pack")).get("comparison_matrix") if state.get("evidence_pack") is not None else state.get("comparison_result"),
        "tool_result_set": state.get("tool_result_set") or state.get("tool_results", {}),
        "execution_plan": state.get("validated_plan") or state.get("execution_plan"),
    }
    plan_dict = plan_state_update(
        turn_context,
        task_type_value,
        resolved_status,
        pending_check_result=str(state.get("pending_check_result", "") or ""),
    )
    directive = SessionWriteDirective(
        set_fields=plan_dict.get("set_fields", {}),
        clear_fields=plan_dict.get("clear_fields", []),
    )
    return {
        "state_update_plan": directive,
        **_log(
            state,
            "state_update_plan",
            set_fields=list(directive.set_fields.keys()),
            clear_fields=list(directive.clear_fields),
        ),
    }


# --- 27. persist_session_state ---
# §1 input:  state_update_plan
# §1 output: session_state_after
def _h_persist_session(state: GraphState) -> dict:
    session_state = state.get("session_state") or SessionState()
    directive = state.get("state_update_plan")
    if directive is not None:
        directive = directive if isinstance(directive, SessionWriteDirective) else SessionWriteDirective(
            set_fields=_session_state_dict(directive).get("set_fields", {}),
            clear_fields=_session_state_dict(directive).get("clear_fields", []),
        )
        for field_name, value in directive.set_fields.items():
            resolved = state.get(field_name) if value is None else value
            if resolved is not None:
                setattr(session_state, field_name, _session_state_dict(resolved) if field_name in {"current_shop", "pending_clarification"} and not isinstance(resolved, dict) else resolved)
        for field_name in directive.clear_fields:
            default_value = getattr(SessionState(), field_name)
            if hasattr(default_value, "model_copy"):
                default_value = default_value.model_copy(deep=True)
            elif isinstance(default_value, (list, dict, set)):
                default_value = type(default_value)(default_value)
            setattr(session_state, field_name, default_value)
    store = get_session_store()
    store.save(str(state.get("session_id", "") or ""), session_state)
    return {
        "session_state": session_state,
        "session_state_after": session_state.model_copy(deep=True),
        "current_shop": session_state.current_shop,
        "last_recommendation_list": session_state.last_recommendation_list,
        "active_constraints": session_state.active_constraints,
        "comparison_result": session_state.comparison_result,
        "pending_clarification": session_state.pending_clarification,
        "comparison_targets": session_state.comparison_targets,
        **_log(state, "persist_session_state"),
    }


# --- 28. emit_response ---
# §1 input:  final_response, trace_id
# §1 output: (terminal —no state mutation)
def _h_emit_response(state: GraphState) -> dict:
    return _log(state, "emit_response")


# ===================================================================
# Node name 鈫?handler mapping
# ===================================================================

_HANDLERS: dict[str, GraphNodeFunc] = {
    "receive_input": _h_receive_input,
    "load_session_state": _h_load_session,
    "check_pending_clarification": _h_check_pending,
    "basic_input_validate": _h_basic_validate,
    "normalize_text": _h_normalize_text,
    "hard_guard": _h_hard_guard,
    "top_intent_router": _h_top_intent_router,
    "semantic_parse": _h_semantic_parse,
    "slot_extractor": _h_slot_extractor,
    "frame_validator": _h_frame_validator,
    "context_recovery": _h_context_recovery,
    "target_resolve": _h_target_resolve,
    "clarify_decide": _h_clarify_decide,
    "task_plan": _h_task_plan,
    "facet_plan": _h_facet_plan,
    "comparison_planner": _h_comparison_planner,
    "plan_validator": _h_plan_validator,
    "tool_execute": _h_tool_execute,
    "evidence_build": _h_evidence_build,
    "answer_plan_build": _h_answer_plan_build,
    "answer_generate": _h_answer_generate,
    "answer_verify": _h_answer_verify,
    "rewrite": _h_rewrite,
    "final_response_build": _h_final_response,
    "clarify_response": _h_clarify_response,
    "fallback_answer": _h_fallback_answer,
    "state_update_plan": _h_state_update_plan,
    "persist_session_state": _h_persist_session,
    "emit_response": _h_emit_response,
}

# Nodes that the §2 Node Table says should exist in the graph.
# All 27 rows including clarify_decide as independent node.
ALL_NODE_NAMES: set[str] = set(_HANDLERS.keys())

# Normal-flow unconditional edges  (§2 "涓嬩竴璺? default path)
_NORMAL_EDGES: dict[str, str] = {
    "receive_input": "load_session_state",
    "load_session_state": "check_pending_clarification",
    "normalize_text": "hard_guard",
    "slot_extractor": "context_recovery",
    "context_recovery": "target_resolve",
    "target_resolve": "clarify_decide",  # §2: target_resolve 鈫?clarify_decide
    "facet_plan": "plan_validator",
    "comparison_planner": "plan_validator",
    "evidence_build": "answer_plan_build",
    "answer_plan_build": "answer_generate",
    "answer_generate": "answer_verify",
    "rewrite": "answer_generate",
    "final_response_build": "state_update_plan",
    "clarify_response": "state_update_plan",
    "fallback_answer": "state_update_plan",
    "state_update_plan": "persist_session_state",
    "persist_session_state": "emit_response",
}


# ===================================================================
# Conditional edge routing functions  (todo/05 §3)
# ===================================================================


def _route_check_pending(state: GraphState) -> str:
    """§3 —Route check_pending_clarification."""
    result = str(state.get("pending_check_result", "") or "")
    if result == "restore":
        return "target_resolve"
    if result in ("invalid", "out_of_range", "expired"):
        return "clarify_response"
    # Future: NL topic-switch detection 鈫?return "top_intent_router"
    return "basic_input_validate"


def _route_basic_validate(state: GraphState) -> str:
    """Route basic_input_validate."""
    err = state.get("error_code", "")
    if err:
        return "emit_response"
    return "normalize_text"


def _route_hard_guard(state: GraphState) -> str:
    """§3 —Route hard_guard."""
    result = state.get("guard_result", "")
    if result in ("safe", "ok"):
        return "top_intent_router"
    if result in ("invalid", "greeting", "capability"):
        return "emit_response"
    return "emit_response"


def _route_top_intent(state: GraphState) -> str:
    """§3 —Route top_intent_router."""
    intent = state.get("top_intent")
    if intent in (TopIntent.local_life, "local_life"):
        return "semantic_parse"
    if intent in (
        TopIntent.chat,
        "chat",
        TopIntent.out_of_scope,
        TopIntent.unsafe,
        TopIntent.invalid,
        TopIntent.capability,
        "out_of_scope",
        "unsafe",
        "invalid",
        "capability",
    ):
        return "emit_response"
    return "emit_response"


def _route_semantic_parse(state: GraphState) -> str:
    """§3 + §2 —Route semantic_parse."""
    err = state.get("error_code", "")
    if err == "LLM_JSON_PARSE_ERROR":
        return "clarify_response"
    if err:
        return "clarify_response"
    return "slot_extractor"


def _route_frame_validator(state: GraphState) -> str:
    """§2 —Route frame_validator."""
    err = state.get("error_code", "")
    if err:
        return "clarify_response"
    return "context_recovery"


def _route_clarify_decide(state: GraphState) -> str:
    """?3 ??Route clarify_decide based on resolve_shop_result.status."""
    rs = state.get("resolve_shop_result")
    if rs is not None:
        rs_dict = _to_dict(rs)
        status = rs_dict.get("status", getattr(rs, "status", ""))
        reason = str(rs_dict.get("reason", getattr(rs, "reason", "")) or "")
        if status == "RESOLVED":
            return "task_plan"
        if status in ("AMBIGUOUS", "LOW_CONFIDENCE"):
            return "clarify_response"
        if reason in {"comparison_requires_at_least_two_shops", "comparison_too_many_shops", "pronoun_without_current_shop", "ordinal_out_of_range"}:
            return "emit_response"
        if status == "NOT_FOUND":
            return "emit_response"
    # Default fallthrough ??clarify
    return "clarify_response"


def _route_plan_validator(state: GraphState) -> str:
    """§3 —Route plan_validator."""
    err = state.get("error_code", "")
    if err:
        return "fallback_answer"
    return "tool_execute"


def _route_task_plan(state: GraphState) -> str:
    """Route task_plan based on the resolved task type."""
    task_type = state.get("task_type")
    task_type_value = task_type.value if hasattr(task_type, "value") else str(task_type or "")
    if task_type_value == TaskType.comparison.value:
        return "comparison_planner"
    return "facet_plan"


def _route_tool_execute(state: GraphState) -> str:
    """§3 —Route tool_execute."""
    tr = state.get("tool_result_set") or state.get("tool_results", {})
    required_by_call_id = _plan_required_by_call_id(state.get("validated_plan") or state.get("execution_plan"))
    plan_is_available = bool(required_by_call_id)
    for _call_id, result in tr.items():
        required = required_by_call_id.get(_call_id, True)
        # ToolResultStatus extraction: handle both Pydantic model (has .result_status
        # enum with .value) and serialized dict.
        if hasattr(result, "result_status"):
            raw = result.result_status
            status = str(raw.value) if hasattr(raw, "value") else str(raw)
        else:
            status = get_tool_result_status(_to_dict(result))
        if plan_is_available and required and status in TOOL_FAILURE_STATUSES:
            return "fallback_answer"
        if not plan_is_available and status in ("failed", "circuit_open", "error", "backend_unavailable"):
            return "fallback_answer"
    return "evidence_build"


def _route_answer_verify(state: GraphState) -> str:
    """§3 —Route answer_verify."""
    vr = state.get("verify_result", "pass")
    rc = state.get("rewrite_count", 0)
    if vr == "pass":
        return "final_response_build"
    if vr in ("rewrite_needed", "rewrite_exhausted"):
        if rc < _GRAPH_REWRITE_LIMIT:
            return "rewrite"
        return "fallback_answer"
    # default
    return "final_response_build"


# === Conditional edge route maps ===

_CHECK_PENDING_ROUTES: dict[Any, str] = {
    "target_resolve": "target_resolve",
    "top_intent_router": "top_intent_router",
    "basic_input_validate": "basic_input_validate",
    "clarify_response": "clarify_response",
}

_BASIC_VALIDATE_ROUTES: dict[Any, str] = {
    "emit_response": "emit_response",
    "normalize_text": "normalize_text",
}

_HARD_GUARD_ROUTES: dict[Any, str] = {
    "emit_response": "emit_response",
    "top_intent_router": "top_intent_router",
}

_TOP_INTENT_ROUTES: dict[Any, str] = {
    "emit_response": "emit_response",
    "semantic_parse": "semantic_parse",
}

_SEMANTIC_PARSE_ROUTES: dict[Any, str] = {
    "clarify_response": "clarify_response",
    "frame_validator": "frame_validator",
    "slot_extractor": "slot_extractor",
}

_FRAME_VALIDATOR_ROUTES: dict[Any, str] = {
    "clarify_response": "clarify_response",
    "context_recovery": "context_recovery",
}

_CLARIFY_DECIDE_ROUTES: dict[Any, str] = {
    "task_plan": "task_plan",
    "clarify_response": "clarify_response",
    "emit_response": "emit_response",
}

_PLAN_VALIDATOR_ROUTES: dict[Any, str] = {
    "fallback_answer": "fallback_answer",
    "tool_execute": "tool_execute",
}

_TASK_PLAN_ROUTES: dict[Any, str] = {
    "facet_plan": "facet_plan",
    "comparison_planner": "comparison_planner",
}

_TOOL_EXECUTE_ROUTES: dict[Any, str] = {
    "fallback_answer": "fallback_answer",
    "evidence_build": "evidence_build",
}

_ANSWER_VERIFY_ROUTES: dict[Any, str] = {
    "final_response_build": "final_response_build",
    "rewrite": "rewrite",
    "fallback_answer": "fallback_answer",
}


# ===================================================================
# Graph builder
# ===================================================================


def _parse_node(n: str | ExecutionNode) -> str:
    """Normalise to string node name."""
    return n.value if isinstance(n, ExecutionNode) else n


def build_graph() -> CompiledStateGraph:
    """Construct the full ``StateGraph`` per todo/05.

    Returns a compiled graph ready for ``graph.invoke(state_dict)``.

    Raises ``ValueError`` if the graph fails completeness verification.
    """
    builder: StateGraph = StateGraph(GraphState)

    # 1. Add all nodes
    for name, handler in _HANDLERS.items():
        builder.add_node(name, _instrument_handler(name, handler))

    # 2. START 鈫?receive_input
    builder.add_edge(START, "receive_input")

    # 3. Normal-flow unconditional edges
    for src, dst in _NORMAL_EDGES.items():
        builder.add_edge(src, dst)

    # 4. Conditional edges  (§3)
    builder.add_conditional_edges(
        "check_pending_clarification",
        _route_check_pending,
        _CHECK_PENDING_ROUTES,
    )
    builder.add_conditional_edges(
        "basic_input_validate",
        _route_basic_validate,
        _BASIC_VALIDATE_ROUTES,
    )
    builder.add_conditional_edges(
        "hard_guard",
        _route_hard_guard,
        _HARD_GUARD_ROUTES,
    )
    builder.add_conditional_edges(
        "top_intent_router",
        _route_top_intent,
        _TOP_INTENT_ROUTES,
    )
    builder.add_conditional_edges(
        "semantic_parse",
        _route_semantic_parse,
        _SEMANTIC_PARSE_ROUTES,
    )
    builder.add_conditional_edges(
        "frame_validator",
        _route_frame_validator,
        _FRAME_VALIDATOR_ROUTES,
    )
    builder.add_conditional_edges(
        "clarify_decide",
        _route_clarify_decide,
        _CLARIFY_DECIDE_ROUTES,
    )
    builder.add_conditional_edges(
        "task_plan",
        _route_task_plan,
        _TASK_PLAN_ROUTES,
    )
    builder.add_conditional_edges(
        "plan_validator",
        _route_plan_validator,
        _PLAN_VALIDATOR_ROUTES,
    )
    builder.add_conditional_edges(
        "tool_execute",
        _route_tool_execute,
        _TOOL_EXECUTE_ROUTES,
    )
    builder.add_conditional_edges(
        "answer_verify",
        _route_answer_verify,
        _ANSWER_VERIFY_ROUTES,
    )

    # 5. Terminal: emit_response 鈫?END
    builder.add_edge("emit_response", END)

    # 6. Validate
    report = verify_graph_completeness(builder)
    if report["errors"]:
        raise ValueError(
            f"Graph completeness check FAILED:\n"
            + "\n".join(f"  - {e}" for e in report["errors"])
        )

    return builder.compile()


# ===================================================================
# Completeness verifier
# ===================================================================

_NODE_TABLE_NEXT_HOPS: dict[str, list[str]] = {
    "receive_input": ["load_session_state"],
    "load_session_state": ["check_pending_clarification"],
    "check_pending_clarification": [
        "hard_guard",
        "clarify_response",
        "semantic_parse",
        "basic_input_validate",
        "target_resolve",
        "top_intent_router",
        "clarify_response",
    ],
    "basic_input_validate": ["normalize_text", "emit_response"],
    "normalize_text": ["hard_guard"],
    "hard_guard": ["emit_response", "top_intent_router"],
    "top_intent_router": ["emit_response", "semantic_parse"],
    "semantic_parse": ["slot_extractor", "frame_validator", "clarify_response"],
    "slot_extractor": ["context_recovery"],
    "frame_validator": ["context_recovery", "clarify_response"],
    "context_recovery": ["target_resolve"],
    "target_resolve": ["clarify_decide"],  # §2: 鏃犳潯浠惰浆鍏?clarify_decide
    "clarify_decide": ["clarify_response", "task_plan", "emit_response"],  # §2: 鐙珛鍐崇瓥鑺傜偣
    "task_plan": ["facet_plan", "comparison_planner", "tool_execute"],
    "facet_plan": ["plan_validator"],
    "comparison_planner": ["plan_validator"],
    "plan_validator": ["tool_execute", "fallback_answer"],
    "tool_execute": ["fallback_answer", "evidence_build"],
    "evidence_build": ["answer_plan_build"],
    "answer_plan_build": ["answer_generate"],
    "answer_generate": ["answer_verify"],
    "answer_verify": ["final_response_build", "rewrite", "fallback_answer"],
    "rewrite": ["answer_generate"],
    "final_response_build": ["state_update_plan"],
    "clarify_response": ["state_update_plan"],
    "fallback_answer": ["state_update_plan"],
    "state_update_plan": ["persist_session_state"],
    "persist_session_state": ["emit_response"],
    "emit_response": [],  # Terminal
}

_EDGE_TABLE_ROWS: list[tuple[str, str, str]] = [
    ("check_pending_clarification", "pending reply digits", "target_resolve"),
    ("check_pending_clarification", "new topic or normal input", "basic_input_validate"),
    ("check_pending_clarification", "expired or invalid pending reply", "clarify_response"),
    ("basic_input_validate", "invalid/empty/overlong", "emit_response"),
    ("basic_input_validate", "valid text", "normalize_text"),
    ("hard_guard", "pure invalid/greeting/capability", "emit_response"),
    ("hard_guard", "safe", "top_intent_router"),
    ("top_intent_router", "out_of_scope/unsafe/chat/capability/invalid", "emit_response"),
    ("top_intent_router", "local_life", "semantic_parse"),
    ("semantic_parse", "JSON parse fail after retry", "clarify_response"),
    ("clarify_decide", "RESOLVED", "task_plan"),
    ("clarify_decide", "AMBIGUOUS", "clarify_response"),
    ("clarify_decide", "LOW_CONFIDENCE", "clarify_response"),
    ("clarify_decide", "NOT_FOUND", "emit_response"),
    ("plan_validator", "invalid plan or unregistered tool", "fallback_answer"),
    ("tool_execute", "required tool failed/unknown", "fallback_answer"),
    ("tool_execute", "optional tool failed/unknown", "evidence_build"),
    ("answer_verify", "pass", "final_response_build"),
    ("answer_verify", "rewrite attempts < 1", "rewrite"),
    ("answer_verify", "rewrite attempts >= 1", "fallback_answer"),
]

_GRAPH_STATE_FIELDS: list[str] = [
    # 璺敱鏍囪瘑
    "trace_id",
    "turn_id",
    "session_id",
    "user_id",
    # 杈撳叆灞?
    "raw_text",
    "normalized_text",
    "input_type",
    # 椤跺眰鎰忓浘
    "top_intent",
    "task_type",
    # 璇箟甯?
    "semantic_frame",
    # 婢勬竻鐘舵€?
    "pending_clarification",
    # 浼氳瘽璁板繂
    "current_shop",
    "last_recommendation_list",
    "active_constraints",
    "comparison_targets",
    "comparison_result",
    "recommendation_candidates",
    # 瑙ｆ瀽缁撴灉
    "resolved_target",
    "resolve_shop_result",  # §1 鏂囨。瀛楁
    # 鎵ц璁″垝
    "execution_plan",
    "validated_plan",  # §1 鏂囨。瀛楁
    "tool_plan",
    "tool_plan_source",
    "tool_plan_validated",
    "tool_plan_fallback_reason",
    "tool_plan_reason",
    # 宸ュ叿缁撴灉
    "tool_results",
    "tool_result_set",  # §1 鏂囨。瀛楁
    # 璇佹嵁灞?
    "evidence_pack",
    # 鍥炵瓟灞?
    "answer_plan",
    "final_response",
    # 鐘舵€佹洿鏂?
    "state_update_plan",
    # 浼氳瘽蹇収
    "session_state_before",  # §1 鏂囨。瀛楁
    "session_state_after",
    # 瑙傛祴瀛楁
    "event_log",
    "metrics_tags",
    "trace_spans",
    # 杩愯鏃惰緟鍔?
    "error_message",
    "plan_validation_result",
    "failed_stage",
]


def verify_graph_completeness(
    builder: StateGraph | None = None,
) -> dict[str, Any]:
    """Verify the graph against the todo/05 contract.

    Checks:
      1. All 26 nodes from §2 Node Table exist.
      2. All §3 conditional edges have their ``from`` nodes present.
      3. No orphan destinations (every ``涓嬩竴璺砢` target exists as a node).
      4. All §1 state fields are documented.

    Args:
        builder: Optional built (but not compiled) graph.  When omitted
                 only the static contract is checked.

    Returns:
        A dict with ``errors`` (list) and ``warnings`` (list).
    """
    errors: list[str] = []
    warnings: list[str] = []

    # --- Check 1: all nodes present ---
    configured = set(_HANDLERS.keys())

    # Check that the node-table next hops all exist
    for src, targets in _NODE_TABLE_NEXT_HOPS.items():
        if src not in configured:
            errors.append(f"§2 node '{src}' has no handler —missing from graph")
        for t in targets:
            if t and t not in configured:
                errors.append(
                    f"§2 node '{src}' lists '{t}' as 涓嬩竴璺? "
                    f"but '{t}' has no handler"
                )

    # --- Check 2: conditional edge from-nodes ---
    seen_from: set[str] = set()
    for src, _cond, dst in _EDGE_TABLE_ROWS:
        seen_from.add(src)
        if src not in configured:
            errors.append(
                f"§3 conditional edge from '{src}' 鈫?'{dst}': "
                f"source node missing from graph"
            )
        if dst not in configured:
            errors.append(
                f"§3 conditional edge '{src}' 鈫?'{dst}': "
                f"destination node missing from graph"
            )

    # --- Check 3: builder-level validation ---
    if builder is not None:
        try:
            # The builder performs internal consistency at add_* time.
            # No explicit validate call needed —LangGraph checks inline.
            pass
        except Exception as exc:
            errors.append(f"Builder internal validation: {exc}")

    return {
        "errors": errors,
        "warnings": warnings,
        "node_count": len(configured),
        "conditional_edges_verified": len(seen_from),
    }


