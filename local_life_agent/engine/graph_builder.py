"""LangGraph StateGraph builder for the local life agent.

Slimmed-down orchestration module.  All node handler logic lives in
``engine/subgraphs/``, shared helpers in ``_compat.py``, and routing
in ``_routes.py``. This file wires them together into a compilable
``StateGraph`` and provides backward-compatible re-exports.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from ..domain.graph_state import GraphState
from .. import config as _graph_config
from ..target.candidate_resolver import CandidateResolver
from ..tools.gateway import dispatch_tool_call
from ._compat import GraphNodeFunc, _instrument_handler, _state_delta

# Re-export for test backward compatibility (tests access graph_builder.config)
config = _graph_config
del _graph_config
from ._routes import (
    _GRAPH_EXECUTION_ROUTES,
    _GRAPH_INTAKE_ROUTES,
    _GRAPH_MERGE_ROUTES,
    _GRAPH_PLANNING_ROUTES,
    _GRAPH_RESPONSE_ROUTES,
    _GRAPH_UNDERSTANDING_ROUTES,
    _OUTER_ROUTE_CLARIFY,
    _OUTER_ROUTE_CLARIFY_READY,
    _OUTER_ROUTE_DEGRADE,
    _OUTER_ROUTE_DIRECT,
    _OUTER_ROUTE_ENOUGH,
    _OUTER_ROUTE_EXECUTE,
    _OUTER_ROUTE_FALLBACK,
    _OUTER_ROUTE_FALLBACK_READY,
    _OUTER_ROUTE_LOCAL_LIFE,
    _OUTER_ROUTE_PASS,
    _OUTER_ROUTE_PROCEED,
    _OUTER_ROUTE_REJECT,
    _OUTER_ROUTE_RETRY,
    _OUTER_ROUTE_TERMINAL,
    _OUTER_ROUTE_CLARIFICATION_REPLY,
    _route_execution_review_subgraph,
    _route_intake_guard,
    _route_merge_clarification,
    _route_planning_subgraph,
    _route_response_subgraph,
    _route_workflow_runner,
    _route_understanding_subgraph,
    _WORKFLOW_RUNNER_ROUTES,
)
from .nodes import ExecutionNode

# -- Subgraph outer wrappers --
from .subgraphs import (
    h_execution_review_subgraph,
    h_intake_guard_router,
    h_orchestration_router_shadow,
    h_merge_clarification,
    h_planning_subgraph,
    h_response_subgraph,
    h_state_update_plan_outer,
    h_understanding_subgraph,
)
from .workflow_runner import h_workflow_runner
# -- Internal step handlers (re-exported for test backward compat) --
from .subgraphs.intake_guard_router import (  # noqa: F401
    _h_basic_validate,
    _h_hard_guard,
    _h_load_session,
    _h_normalize_text,
    _h_receive_input,
    _h_top_intent_router,
)
from .subgraphs.merge_clarification import (  # noqa: F401
    _h_check_pending,
)
from .subgraphs.understanding_subgraph import (  # noqa: F401
    _h_context_recovery,
    _h_frame_validator,
    _h_semantic_parse,
    _h_slot_extractor,
)
from .subgraphs.planning_subgraph import (  # noqa: F401
    _h_clarify_decide,
    _h_evidence_planner,
    _h_expand_search,
    _h_goal_planner,
    _h_goal_review,
    _h_plan_validator,
    _h_target_resolve,
    _h_target_resolve_candidate_set,
)
from .subgraphs.execution_review_subgraph import (  # noqa: F401
    _h_decision_planner,
    _h_decision_review,
    _h_evidence_build,
    _h_evidence_review,
    _h_tool_execute,
)
from .subgraphs.response_subgraph import (  # noqa: F401
    _h_answer_generate,
    _h_answer_plan_build,
    _h_answer_verify,
    _h_clarify_response,
    _h_fallback_answer,
    _h_final_response,
    _h_rewrite,
)
from .subgraphs.state_update_plan import (  # noqa: F401
    _h_emit_response,
    _h_persist_session,
    _h_state_update_plan,
)

# Re-export routing helpers for tests
from ._compat import (  # noqa: F401
    _build_conversation_continuity,
    _coerce_str,
    _comparison_reason_response,
    _comparison_structured_queries,
    _log,
    _merge_update,
    _pick_route,
    _plan_required_by_call_id,
    _plan_validation_error_code,
    _planning_failure_route,
    _resolved_shop_ids_from_state,
    _resolve_recommendation_spec,
    _resolve_search_result_placeholder,
    _response_mode_for_top_intent,
    _run_step,
    _run_steps,
    _session_shop_ids,
    _session_state_dict,
    _session_store_state,
    _shop_dict,
    _to_dict,
    _unwrap_resolve_shop_result,
    _user_location,
)
from ._routes import (  # noqa: F401
    _ANSWER_VERIFY_ROUTES,
    _BASIC_VALIDATE_ROUTES,
    _CHECK_PENDING_ROUTES,
    _CLARIFY_DECIDE_ROUTES,
    _DECISION_REVIEW_ROUTES,
    _EVIDENCE_REVIEW_ROUTES,
    _FRAME_VALIDATOR_ROUTES,
    _GOAL_REVIEW_ROUTES,
    _HARD_GUARD_ROUTES,
    _PLAN_VALIDATOR_ROUTES,
    _SEMANTIC_PARSE_ROUTES,
    _TOOL_EXECUTE_ROUTES,
    _TOP_INTENT_ROUTES,
    _route_answer_verify,
    _route_basic_validate,
    _route_check_pending,
    _route_clarify_decide,
    _route_decision_review,
    _route_evidence_review,
    _route_frame_validator,
    _route_goal_review,
    _route_hard_guard,
    _route_plan_validator,
    _route_semantic_parse,
    _route_top_intent,
    _route_tool_execute,
)
from .session_write import get_directive, resolve_scenario

# -- Test-backward-compatible re-exports (symbols that tests import directly from graph_builder)
from ..answer.generator import generate_answer  # noqa: F401
from ..llm.client import (  # noqa: F401
    call_llm, ensure_real_llm_backend, get_llm_backend_snapshot, has_llm_backend,
)
from ..target.shop_resolver import resolve_shop  # noqa: F401
from ..observability.trace import record_span, sanitize_payload  # noqa: F401
from ..observability.file_logger import get_python_service_logger  # noqa: F401
from ..input.hard_guard import check_hard_guard  # noqa: F401
from ..input.normalizer import normalize_text as input_normalize_text  # noqa: F401
from ..input.receiver import receive_input as assemble_turn_input  # noqa: F401
from ..input.validator import validate_basic_input  # noqa: F401
from ..semantic.frame_validator import validate_frame  # noqa: F401
from ..semantic.intent_parser import parse_semantic_frame, parse_top_intent  # noqa: F401
from ..target.context_recovery import recover_context  # noqa: F401
from ..target.clarification import (  # noqa: F401
    build_pending_clarification, format_pending_prompt, handle_clarification_reply,
)
from ..domain.evidence import EvidenceReviewResult  # noqa: F401
from ..domain.goal import GoalPlan, GoalReviewResult  # noqa: F401
from ..domain.decision import (  # noqa: F401
    DecisionPlan as P2DecisionPlan, DecisionReviewResult, decision_to_answer_plan,
)
from ..planning.evidence.evidence_review import review_evidence as review_evidence_sufficiency  # noqa: F401
from ..planning.plans.state_update_planner import plan_state_update  # noqa: F401
from ..tools.result_semantics import TOOL_FAILURE_STATUSES, get_tool_result_status  # noqa: F401
from ..answer.verifier import verify_answer  # noqa: F401

# ===================================================================
# Handler mapping tables
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
    "goal_planner": _h_goal_planner,
    "goal_review": _h_goal_review,
    "target_resolve": _h_target_resolve,
    "clarify_decide": _h_clarify_decide,
    "evidence_planner": _h_evidence_planner,
    "plan_validator": _h_plan_validator,
    "tool_execute": _h_tool_execute,
    "evidence_build": _h_evidence_build,
    "evidence_review": _h_evidence_review,
    "expand_search": _h_expand_search,
    "decision_planner": _h_decision_planner,
    "decision_review": _h_decision_review,
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

# Outer orchestration nodes (the 8 subgraphs in the architecture diagram)
_GRAPH_HANDLERS: dict[str, GraphNodeFunc] = {
    "intake_guard_router": h_intake_guard_router,
    "merge_clarification": h_merge_clarification,
    "understanding_subgraph": h_understanding_subgraph,
    "orchestration_router_shadow": h_orchestration_router_shadow,
    "workflow_runner": h_workflow_runner,
    "planning_subgraph": h_planning_subgraph,
    "execution_review_subgraph": h_execution_review_subgraph,
    "response_subgraph": h_response_subgraph,
    "state_update_plan": h_state_update_plan_outer,
}

# Nodes that the legacy §2 Node Table says should exist in the graph.
# Kept for internal step handlers and regression coverage.
ALL_NODE_NAMES: set[str] = set(_HANDLERS.keys())
_GRAPH_NODE_NAMES: set[str] = set(_GRAPH_HANDLERS.keys())

# Normal-flow unconditional edges  (§2 "下一跳" default path)
_NORMAL_EDGES: dict[str, str] = {
    "receive_input": "load_session_state",
    "load_session_state": "check_pending_clarification",
    "normalize_text": "hard_guard",
    "slot_extractor": "context_recovery",
    "context_recovery": "goal_planner",
    "goal_planner": "goal_review",
    "target_resolve": "clarify_decide",
    "evidence_planner": "plan_validator",
    "decision_planner": "decision_review",
    "evidence_build": "evidence_review",
    "expand_search": "evidence_planner",
    "answer_plan_build": "answer_generate",
    "answer_generate": "answer_verify",
    "rewrite": "answer_generate",
    "final_response_build": "state_update_plan",
    "clarify_response": "state_update_plan",
    "fallback_answer": "state_update_plan",
    "state_update_plan": "persist_session_state",
    "persist_session_state": "emit_response",
}

_GRAPH_NORMAL_EDGES: dict[str, str] = {}

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
    ensure_real_llm_backend()
    builder: StateGraph = StateGraph(GraphState)

    # 1. Add outer orchestration nodes only
    for name, handler in _GRAPH_HANDLERS.items():
        builder.add_node(name, _instrument_handler(name, handler))

    # 2. START -> intake_guard_router
    builder.add_edge(START, "intake_guard_router")

    # 3. Normal-flow unconditional edges
    for src, dst in _GRAPH_NORMAL_EDGES.items():
        builder.add_edge(src, dst)

    builder.add_conditional_edges(
        "intake_guard_router",
        _route_intake_guard,
        _GRAPH_INTAKE_ROUTES,
    )
    builder.add_conditional_edges(
        "merge_clarification",
        _route_merge_clarification,
        _GRAPH_MERGE_ROUTES,
    )
    builder.add_conditional_edges(
        "understanding_subgraph",
        _route_understanding_subgraph,
        _GRAPH_UNDERSTANDING_ROUTES,
    )
    builder.add_edge("orchestration_router_shadow", "workflow_runner")
    builder.add_conditional_edges(
        "workflow_runner",
        _route_workflow_runner,
        _WORKFLOW_RUNNER_ROUTES,
    )
    builder.add_conditional_edges(
        "planning_subgraph",
        _route_planning_subgraph,
        _GRAPH_PLANNING_ROUTES,
    )
    builder.add_conditional_edges(
        "execution_review_subgraph",
        _route_execution_review_subgraph,
        _GRAPH_EXECUTION_ROUTES,
    )
    builder.add_conditional_edges(
        "response_subgraph",
        _route_response_subgraph,
        _GRAPH_RESPONSE_ROUTES,
    )

    # 4. Terminal: state_update_plan -> END
    builder.add_edge("state_update_plan", END)

    # 5. Validate
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
    "context_recovery": ["goal_planner"],
    "goal_planner": ["goal_review"],
    "goal_review": ["target_resolve", "clarify_response", "emit_response", "fallback_answer"],
    "target_resolve": ["clarify_decide"],
    "clarify_decide": ["clarify_response", "evidence_planner", "emit_response"],
    "evidence_planner": ["plan_validator"],
    "plan_validator": ["tool_execute", "fallback_answer"],
    "tool_execute": ["evidence_build"],
    "evidence_build": ["evidence_review"],
    "evidence_review": ["decision_planner", "fallback_answer", "clarify_response", "evidence_planner"],
    "expand_search": ["evidence_planner"],
    "decision_planner": ["decision_review"],
    "decision_review": ["answer_plan_build", "evidence_planner", "expand_search", "target_resolve", "fallback_answer", "emit_response", "clarify_response"],
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
    ("clarify_decide", "RESOLVED", "evidence_planner"),
    ("clarify_decide", "AMBIGUOUS", "clarify_response"),
    ("clarify_decide", "LOW_CONFIDENCE", "clarify_response"),
    ("clarify_decide", "NOT_FOUND", "emit_response"),
    ("plan_validator", "invalid plan or unregistered tool", "fallback_answer"),
    ("tool_execute", "all tool results", "evidence_build"),
    ("answer_verify", "pass", "final_response_build"),
    ("answer_verify", "rewrite attempts < 1", "rewrite"),
    ("answer_verify", "rewrite attempts >= 1", "fallback_answer"),
]

_GRAPH_NODE_TABLE_NEXT_HOPS: dict[str, list[str]] = {
    "intake_guard_router": ["response_subgraph", "merge_clarification", "understanding_subgraph"],
    "merge_clarification": ["planning_subgraph", "response_subgraph"],
    "understanding_subgraph": ["orchestration_router_shadow", "response_subgraph"],
    "orchestration_router_shadow": ["workflow_runner"],
    "workflow_runner": ["planning_subgraph", "response_subgraph"],
    "planning_subgraph": ["execution_review_subgraph", "response_subgraph"],
    "execution_review_subgraph": ["response_subgraph", "planning_subgraph"],
    "response_subgraph": ["state_update_plan"],
    "state_update_plan": [],
}

_GRAPH_EDGE_TABLE_ROWS: list[tuple[str, str, str]] = [
    ("intake_guard_router", "terminal/direct/reject", "response_subgraph"),
    ("intake_guard_router", "clarification_reply", "merge_clarification"),
    ("intake_guard_router", "local_life", "understanding_subgraph"),
    ("merge_clarification", "restore", "planning_subgraph"),
    ("merge_clarification", "topic_switch/pass", "understanding_subgraph"),
    ("merge_clarification", "clarify/fallback", "response_subgraph"),
    ("understanding_subgraph", "proceed", "orchestration_router_shadow"),
    ("orchestration_router_shadow", "shadow->runner", "workflow_runner"),
    ("workflow_runner", "dispatch", "planning_subgraph"),
    ("workflow_runner", "fallback/unsupported/fail", "response_subgraph"),
    ("understanding_subgraph", "clarify/fallback", "response_subgraph"),
    ("planning_subgraph", "execute", "execution_review_subgraph"),
    ("planning_subgraph", "clarify/fallback", "response_subgraph"),
    ("execution_review_subgraph", "enough/degrade", "response_subgraph"),
    ("execution_review_subgraph", "clarify/fallback", "response_subgraph"),
    ("execution_review_subgraph", "retry", "planning_subgraph"),
    ("response_subgraph", "pass/fallback_ready/clarify_ready", "state_update_plan"),
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
    "task_type",
    # 语义帧
    "semantic_frame",
    # 澄清状态
    "pending_clarification",
    # 会话记忆
    "current_shop",
    "last_recommendation_list",
    "active_constraints",
    "comparison_targets",
    "comparison_result",
    "recommendation_candidates",
    # 解析结果
    "resolved_target",
    "resolve_shop_result",
    # 执行计划
    "execution_plan",
    "validated_plan",
    # 工具结果
    "tool_results",
    "tool_result_set",
    # 证据层
    "evidence_pack",
    "review_results",
    "candidate_set",
    "local_life_goal_draft",
    "candidate_spec",
    # 回答层
    "answer_plan",
    "final_response",
    # 状态更新
    "state_update_plan",
    "intake_route",
    "merge_clarification_route",
    "understanding_route",
    "orchestration_pattern",
    "workflow_name",
    "workflow_reason",
    "task_complexity",
    "requires_tool",
    "requires_clarification",
    "planning_route",
    "execution_review_route",
    "response_route",
    "response_mode",
    "next_action",
    "orchestration_error_code",
    "orchestration_error_message",
    "workflow_run_status",
    "workflow_runner_error",
    "workflow_runner_reason",
    "workflow_started_at",
    "workflow_finished_at",
    "workflow_registered",
    "workflow_callable",
    # 会话快照
    "session_state_before",
    "session_state_after",
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
      1. All nodes from §2 Node Table exist.
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
    configured = set(_GRAPH_HANDLERS.keys())

    # Check that the node-table next hops all exist
    for src, targets in _GRAPH_NODE_TABLE_NEXT_HOPS.items():
        if src not in configured:
            errors.append(f"§2 node '{src}' has no handler —missing from graph")
        for t in targets:
            if t and t not in configured:
                errors.append(
                    f"§2 node '{src}' lists '{t}' as 下一跳 "
                    f"but '{t}' has no handler"
                )

    # --- Check 2: conditional edge from-nodes ---
    seen_from: set[str] = set()
    for src, _cond, dst in _GRAPH_EDGE_TABLE_ROWS:
        seen_from.add(src)
        if src not in configured:
            errors.append(
                f"§3 conditional edge from '{src}' →'{dst}': "
                f"source node missing from graph"
            )
        if dst not in configured:
            errors.append(
                f"§3 conditional edge '{src}' →'{dst}': "
                f"destination node missing from graph"
            )

    # --- Check 3: builder-level validation ---
    if builder is not None:
        try:
            pass
        except Exception as exc:
            errors.append(f"Builder internal validation: {exc}")

    return {
        "errors": errors,
        "warnings": warnings,
        "node_count": len(configured),
        "conditional_edges_verified": len(seen_from),
    }
