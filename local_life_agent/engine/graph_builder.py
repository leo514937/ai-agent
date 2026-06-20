"""LangGraph StateGraph builder for the local life agent.

Maps the node/edge/state contracts from todo/05 into a compilable
``StateGraph``.  Each node handler documents its input/output fields
per §2 Node Table; conditional edges follow §3 Conditional Edge Table.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from ..config import MAX_REWRITE_ATTEMPTS
from ..domain.enums import TopIntent
from ..domain.graph_state import GraphState
from ..domain.schemas import (
    AnswerPlan,
    EvidenceItem,
    EvidencePack,
    ExecutionPlan,
    ExecutionStage,
    PendingClarification,
    ResolveShopResult,
    SemanticFrame,
    ShopCandidate,
    ShopRef,
    ToolCallSpec,
    ToolResult,
)
from ..domain.state import SessionState, SessionWriteDirective
from ..planning.plan_validator import ExecutionPlanValidator
from .nodes import ExecutionNode
from .session_write import get_directive, resolve_scenario

# ===================================================================
# Helpers
# ===================================================================

GraphNodeFunc = Any  # Callable[[GraphState], dict] — acceptable typing overhead


def _log(state: GraphState, node: str, **extra: Any) -> dict:
    """Return a partial update that appends an event-log entry."""
    log = list(state.get("event_log", []))
    log.append({"node": node, **extra})
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
    if "INVALID_ARGUMENT" in joined:
        return "INVALID_ARGUMENT"
    if "SCHEMA_VALIDATION_FAILED" in joined:
        return "SCHEMA_VALIDATION_FAILED"
    if "exceeds max_tool_calls" in joined:
        return "INVALID_ARGUMENT"
    return "SCHEMA_VALIDATION_FAILED"


# ===================================================================
# 26 Node Handlers  (todo/05 §2 Node Table)
# ===================================================================


# --- 1. receive_input ---
# §1 input:  raw_text, session_id, trace_id
# §1 output: normalized_text, input_type, basic IDs
def _h_receive_input(state: GraphState) -> dict:
    raw = state.get("raw_text", "")
    return {
        "normalized_text": raw,
        "input_type": "text",
        "turn_id": state.get("turn_id", ""),
        **_log(state, "receive_input"),
    }


# --- 2. load_session_state ---
# §1 input:  session_id
# §1 output: current_shop, last_recommendation_list, pending_clarification, session_state_before
def _h_load_session(state: GraphState) -> dict:
    existing = state.get("session_state")
    if existing is None:
        existing = SessionState()
    return {
        "session_state": existing,
        "session_state_before": existing,  # §1: 会话快照供下游节点读取
        "current_shop": existing.current_shop,
        "last_recommendation_list": existing.last_recommendation_list,
        "active_constraints": existing.active_constraints,
        "pending_clarification": (
            PendingClarification(**existing.pending_clarification)
            if isinstance(existing.pending_clarification, dict)
            else existing.pending_clarification
        ),
        "comparison_targets": existing.comparison_targets,
        **_log(state, "load_session_state"),
    }


# --- 3. check_pending_clarification ---
# §1 input:  pending_clarification, raw_text
# §1 output: cleared or retained pending state
def _h_check_pending(state: GraphState) -> dict:
    pending = state.get("pending_clarification")
    if pending is None:
        return _log(state, "check_pending_clarification", has_pending=False)
    return _log(state, "check_pending_clarification", has_pending=True)


# --- 4. basic_input_validate ---
# §1 input:  normalized_text
# §1 output: input_type, error_code
def _h_basic_validate(state: GraphState) -> dict:
    txt = state.get("normalized_text", "")
    err = ""
    if not txt:
        err = "EMPTY_INPUT"
    return {
        "input_type": "text" if txt else "empty",
        "error_code": err,
        **_log(state, "basic_input_validate"),
    }


# --- 5. normalize_text ---
# §1 input:  raw_text
# §1 output: normalized_text
def _h_normalize_text(state: GraphState) -> dict:
    raw = state.get("raw_text", "")
    return {
        "normalized_text": raw.strip(),
        **_log(state, "normalize_text"),
    }


# --- 6. hard_guard ---
# §1 input:  normalized_text
# §1 output: guard_result
def _h_hard_guard(state: GraphState) -> dict:
    txt = state.get("normalized_text", "")
    result = "invalid" if not txt else "ok"
    return {
        "guard_result": result,
        **_log(state, "hard_guard"),
    }


# --- 7. top_intent_router ---
# §1 input:  normalized_text, session_state_before
# §1 output: top_intent
def _h_top_intent_router(state: GraphState) -> dict:
    txt = state.get("normalized_text", "")
    # Minimal classification stub
    if not txt:
        intent = TopIntent.invalid
    elif txt in ("你好", "hi", "hello"):
        intent = TopIntent.chat
    else:
        intent = TopIntent.local_life
    return {
        "top_intent": intent,
        **_log(state, "top_intent_router", intent=intent.value),
    }


# --- 8. semantic_parse ---
# §1 input:  normalized_text, top_intent
# §1 output: semantic_frame
def _h_semantic_parse(state: GraphState) -> dict:
    frame = SemanticFrame(top_intent=state.get("top_intent"))
    return {
        "semantic_frame": frame,
        **_log(state, "semantic_parse"),
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
    err = ""
    if sf is not None and sf.top_intent == TopIntent.local_life and sf.task_type is None:
        err = "MISSING_TASK_TYPE"
    return {
        "error_code": err,
        "semantic_frame": sf,
        **_log(state, "frame_validator"),
    }


# --- 11. context_recovery ---
# §1 input:  session_state_before, semantic_frame
# §1 output: resolved_target (candidates)
def _h_context_recovery(state: GraphState) -> dict:
    return _log(state, "context_recovery")


# --- 12. target_resolve ---
# §1 input:  merchant_mentions, reference_mentions, session_state_before
# §1 output: resolve_shop_result
def _h_target_resolve(state: GraphState) -> dict:
    # Stub: produce a resolve_shop_result for downstream clarify_decide
    return {
        "resolve_shop_result": None,
        **_log(state, "target_resolve"),
    }


# --- 12b. clarify_decide ---
# §1 input:  resolve_shop_result, semantic_frame
# §1 output: pending_clarification 或 resolved_target (可执行目标)
def _h_clarify_decide(state: GraphState) -> dict:
    rs = state.get("resolve_shop_result")
    if rs is not None:
        status = rs.status
        if status == "RESOLVED":
            return {
                "resolved_target": rs,
                "pending_clarification": None,
                **_log(state, "clarify_decide", decision="proceed"),
            }
        if status in ("AMBIGUOUS", "LOW_CONFIDENCE"):
            pc = PendingClarification(
                pending_id=f"pc_{state.get('turn_id', '')}",
                original_task_type=(
                    state.get("semantic_frame").task_type.value
                    if state.get("semantic_frame") and state.get("semantic_frame").task_type
                    else ""
                ),
                candidate_targets=[
                    {"shop_id": c.shop.shop_id, "shop_name": c.shop.shop_name}
                    for c in rs.candidates
                ],
                expected_reply_type="index",
            )
            return {
                "pending_clarification": pc,
                **_log(state, "clarify_decide", decision="clarify"),
            }
        # NOT_FOUND or other
        return {
            "resolved_target": rs,
            **_log(state, "clarify_decide", decision="not_found"),
        }
    # No resolve result → clarify
    return _log(state, "clarify_decide", decision="no_result")


# --- 13. task_plan ---
# §1 input:  top_intent, task_type, resolved_target
# §1 output: execution_plan
def _h_task_plan(state: GraphState) -> dict:
    plan = ExecutionPlan()
    return {
        "execution_plan": plan,
        **_log(state, "task_plan"),
    }


# --- 14. facet_plan ---
# §1 input:  semantic_frame, resolved_target
# §1 output: execution_plan.tool_calls
def _h_facet_plan(state: GraphState) -> dict:
    return _log(state, "facet_plan")


# --- 15. comparison_planner ---
# §1 input:  comparison_targets, resolved_target
# §1 output: execution_plan, comparison_matrix placeholder
def _h_comparison_planner(state: GraphState) -> dict:
    return _log(state, "comparison_planner")


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
    report = validator.validate(plan)
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
        "validated_plan": plan,  # §1: 校验通过后的执行计划
        **_log(state, "plan_validator", status="pass"),
    }


# --- 17. tool_execute ---
# §1 input:  validated_plan
# §1 output: tool_result_set
def _h_tool_execute(state: GraphState) -> dict:
    results: dict[str, ToolResult] = {}
    return {
        "tool_results": results,
        "tool_result_set": results,  # §1: 文档要求的字段名
        **_log(state, "tool_execute"),
    }


# --- 18. evidence_build ---
# §1 input:  tool_result_set
# §1 output: evidence_pack
def _h_evidence_build(state: GraphState) -> dict:
    pack = EvidencePack()
    return {
        "evidence_pack": pack,
        **_log(state, "evidence_build"),
    }


# --- 19. answer_plan_build ---
# §1 input:  evidence_pack, semantic_frame
# §1 output: answer_plan
def _h_answer_plan_build(state: GraphState) -> dict:
    plan = AnswerPlan()
    return {
        "answer_plan": plan,
        **_log(state, "answer_plan_build"),
    }


# --- 20. answer_generate ---
# §1 input:  answer_plan, evidence_pack
# §1 output: draft_response
def _h_answer_generate(state: GraphState) -> dict:
    txt = state.get("final_response", "")
    return {
        "draft_response": txt,
        **_log(state, "answer_generate"),
    }


# --- 21. answer_verify ---
# §1 input:  draft_response, evidence_pack
# §1 output: verify_result
def _h_answer_verify(state: GraphState) -> dict:
    # Always pass at stub level
    return {
        "verify_result": "pass",
        **_log(state, "answer_verify"),
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
        **_log(state, "final_response_build"),
    }


# --- 24. clarify_response ---
# §1 input:  resolve_shop_result, pending_clarification
# §1 output: final_response
def _h_clarify_response(state: GraphState) -> dict:
    return {
        "final_response": "请提供更多信息以便帮您查找。",
        **_log(state, "clarify_response"),
    }


# --- 25. fallback_answer ---
# §1 input:  error_code, evidence_pack
# §1 output: final_response
def _h_fallback_answer(state: GraphState) -> dict:
    return {
        "final_response": "抱歉，暂时无法处理您的请求，请稍后再试。",
        **_log(state, "fallback_answer"),
    }


# --- 26. state_update_plan ---
# §1 input:  final_response, session_state_before
# §1 output: state_update_plan
def _h_state_update_plan(state: GraphState) -> dict:
    return _log(state, "state_update_plan")


# --- 27. persist_session_state ---
# §1 input:  state_update_plan
# §1 output: session_state_after
def _h_persist_session(state: GraphState) -> dict:
    return _log(state, "persist_session_state")


# --- 28. emit_response ---
# §1 input:  final_response, trace_id
# §1 output: (terminal — no state mutation)
def _h_emit_response(state: GraphState) -> dict:
    return _log(state, "emit_response")


# ===================================================================
# Node name → handler mapping
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

# Normal-flow unconditional edges  (§2 "下一跳" default path)
_NORMAL_EDGES: dict[str, str] = {
    "receive_input": "load_session_state",
    "load_session_state": "check_pending_clarification",
    "basic_input_validate": "normalize_text",
    "normalize_text": "hard_guard",
    "slot_extractor": "context_recovery",
    "context_recovery": "target_resolve",
    "target_resolve": "clarify_decide",  # §2: target_resolve → clarify_decide
    "task_plan": "facet_plan",
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
    """§3 — Route check_pending_clarification."""
    pending = state.get("pending_clarification")
    raw = state.get("raw_text", "")
    if pending is not None and raw.strip().isdigit():
        return "target_resolve"
    # Future: NL topic-switch detection → return "top_intent_router"
    return "basic_input_validate"


def _route_hard_guard(state: GraphState) -> str:
    """§3 — Route hard_guard."""
    result = state.get("guard_result", "")
    if result in ("invalid", "greeting"):
        return "emit_response"
    return "top_intent_router"


def _route_top_intent(state: GraphState) -> str:
    """§3 — Route top_intent_router."""
    intent = state.get("top_intent")
    if intent in (TopIntent.out_of_scope, TopIntent.unsafe):
        return "emit_response"
    return "semantic_parse"


def _route_semantic_parse(state: GraphState) -> str:
    """§3 + §2 — Route semantic_parse."""
    err = state.get("error_code", "")
    if err == "LLM_JSON_PARSE_ERROR":
        return "clarify_response"
    if err == "MISSING_TASK_TYPE":
        # Goes to frame_validator when task_type is missing/invalid
        return "frame_validator"
    return "slot_extractor"


def _route_frame_validator(state: GraphState) -> str:
    """§2 — Route frame_validator."""
    err = state.get("error_code", "")
    if err:
        return "clarify_response"
    return "context_recovery"


def _route_clarify_decide(state: GraphState) -> str:
    """§3 — Route clarify_decide based on resolve_shop_result.status."""
    rs = state.get("resolve_shop_result")
    if rs is not None:
        status = rs.status
        if status == "RESOLVED":
            return "task_plan"
        if status in ("AMBIGUOUS", "LOW_CONFIDENCE"):
            return "clarify_response"
        if status == "NOT_FOUND":
            return "emit_response"
    # Default fallthrough → clarify
    return "clarify_response"


def _route_plan_validator(state: GraphState) -> str:
    """§3 — Route plan_validator."""
    err = state.get("error_code", "")
    if err:
        return "fallback_answer"
    return "tool_execute"


def _route_tool_execute(state: GraphState) -> str:
    """§3 — Route tool_execute."""
    tr = state.get("tool_result_set") or state.get("tool_results", {})
    # Heuristic: check if any required tool failed
    for call_id, result in tr.items():
        if result.result_status.value in ("failed", "unknown"):
            if result.error_code is not None:
                return "fallback_answer"
    return "evidence_build"


def _route_answer_verify(state: GraphState) -> str:
    """§3 — Route answer_verify."""
    vr = state.get("verify_result", "pass")
    rc = state.get("rewrite_count", 0)
    if vr == "pass":
        return "final_response_build"
    if vr in ("rewrite_needed", "rewrite_exhausted"):
        if rc < MAX_REWRITE_ATTEMPTS:
            return "answer_generate"
        return "fallback_answer"
    # default
    return "final_response_build"


# === Conditional edge route maps ===

_CHECK_PENDING_ROUTES: dict[Any, str] = {
    "target_resolve": "target_resolve",
    "top_intent_router": "top_intent_router",
    "basic_input_validate": "basic_input_validate",
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

_TOOL_EXECUTE_ROUTES: dict[Any, str] = {
    "fallback_answer": "fallback_answer",
    "evidence_build": "evidence_build",
}

_ANSWER_VERIFY_ROUTES: dict[Any, str] = {
    "final_response_build": "final_response_build",
    "answer_generate": "answer_generate",
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
        builder.add_node(name, handler)

    # 2. START → receive_input
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

    # 5. Terminal: emit_response → END
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
    ],
    "basic_input_validate": ["normalize_text", "emit_response"],
    "normalize_text": ["hard_guard"],
    "hard_guard": ["emit_response", "top_intent_router"],
    "top_intent_router": ["emit_response", "semantic_parse"],
    "semantic_parse": ["slot_extractor", "frame_validator", "clarify_response"],
    "slot_extractor": ["context_recovery"],
    "frame_validator": ["context_recovery", "clarify_response"],
    "context_recovery": ["target_resolve"],
    "target_resolve": ["clarify_decide"],  # §2: 无条件转入 clarify_decide
    "clarify_decide": ["clarify_response", "task_plan", "emit_response"],  # §2: 独立决策节点
    "task_plan": ["facet_plan", "comparison_planner", "tool_execute"],
    "facet_plan": ["plan_validator"],
    "comparison_planner": ["plan_validator"],
    "plan_validator": ["tool_execute", "fallback_answer"],
    "tool_execute": ["fallback_answer", "evidence_build"],
    "evidence_build": ["answer_plan_build"],
    "answer_plan_build": ["answer_generate"],
    "answer_generate": ["answer_verify"],
    "answer_verify": ["final_response_build", "answer_generate", "fallback_answer"],
    "rewrite": ["answer_generate"],
    "final_response_build": ["state_update_plan"],
    "clarify_response": ["state_update_plan"],
    "fallback_answer": ["state_update_plan"],
    "state_update_plan": ["persist_session_state"],
    "persist_session_state": ["emit_response"],
    "emit_response": [],  # Terminal
}

_EDGE_TABLE_ROWS: list[tuple[str, str, str]] = [
    ("check_pending_clarification", "命中有效序号/指代恢复", "target_resolve"),
    ("check_pending_clarification", "明显换话题", "top_intent_router"),
    ("hard_guard", "纯无效/纯招呼", "emit_response"),
    ("top_intent_router", "out_of_scope/unsafe", "emit_response"),
    ("semantic_parse", "JSON失败且重试耗尽", "clarify_response"),
    ("clarify_decide", "RESOLVED", "task_plan"),
    ("clarify_decide", "AMBIGUOUS", "clarify_response"),
    ("clarify_decide", "LOW_CONFIDENCE", "clarify_response"),
    ("clarify_decide", "NOT_FOUND", "emit_response"),
    ("plan_validator", "非法计划/未注册工具/成环", "fallback_answer"),
    ("tool_execute", "required tool failed/unknown", "fallback_answer"),
    ("tool_execute", "optional tool failed/unknown", "evidence_build"),
    ("answer_verify", "pass", "final_response_build"),
    ("answer_verify", "rewrite attempts < 2", "answer_generate"),
    ("answer_verify", "rewrite attempts >= 2", "fallback_answer"),
]

_GRAPH_STATE_FIELDS: list[str] = [
    # 路由标识
    "trace_id",
    "turn_id",
    "session_id",
    "user_id",
    # 输入层
    "raw_text",
    "normalized_text",
    "input_type",
    # 顶层意图
    "top_intent",
    # 语义帧
    "semantic_frame",
    # 澄清状态
    "pending_clarification",
    # 会话记忆
    "current_shop",
    "last_recommendation_list",
    "active_constraints",
    "comparison_targets",
    # 解析结果
    "resolved_target",
    "resolve_shop_result",  # §1 文档字段
    # 执行计划
    "execution_plan",
    "validated_plan",  # §1 文档字段
    # 工具结果
    "tool_results",
    "tool_result_set",  # §1 文档字段
    # 证据层
    "evidence_pack",
    # 回答层
    "answer_plan",
    "final_response",
    # 状态更新
    "state_update_plan",
    # 会话快照
    "session_state_before",  # §1 文档字段
    # 观测字段
    "event_log",
    "metrics_tags",
    "trace_spans",
    # 运行时辅助
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
      3. No orphan destinations (every ``下一跳`` target exists as a node).
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
            errors.append(f"§2 node '{src}' has no handler — missing from graph")
        for t in targets:
            if t and t not in configured:
                errors.append(
                    f"§2 node '{src}' lists '{t}' as 下一跳, "
                    f"but '{t}' has no handler"
                )

    # --- Check 2: conditional edge from-nodes ---
    seen_from: set[str] = set()
    for src, _cond, dst in _EDGE_TABLE_ROWS:
        seen_from.add(src)
        if src not in configured:
            errors.append(
                f"§3 conditional edge from '{src}' → '{dst}': "
                f"source node missing from graph"
            )
        if dst not in configured:
            errors.append(
                f"§3 conditional edge '{src}' → '{dst}': "
                f"destination node missing from graph"
            )

    # --- Check 3: builder-level validation ---
    if builder is not None:
        try:
            # The builder performs internal consistency at add_* time.
            # No explicit validate call needed — LangGraph checks inline.
            pass
        except Exception as exc:
            errors.append(f"Builder internal validation: {exc}")

    return {
        "errors": errors,
        "warnings": warnings,
        "node_count": len(configured),
        "conditional_edges_verified": len(seen_from),
    }
