"""Execution node definitions for the state machine.

Mirrors the node table from `todo/05_LangGraph节点边状态字段表.md`
and the transition rules from `todo/02_状态转移与路由决策表.md`.
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Any


class ExecutionNode(str, Enum):
    """All possible nodes in the execution graph."""

    # --- Input & Session ---
    RECEIVE_INPUT = "receive_input"
    LOAD_SESSION_STATE = "load_session_state"
    CHECK_PENDING_CLARIFICATION = "check_pending_clarification"
    BASIC_INPUT_VALIDATE = "basic_input_validate"
    NORMALIZE_TEXT = "normalize_text"

    # --- Guard & Intent ---
    HARD_GUARD = "hard_guard"
    TOP_INTENT_ROUTER = "top_intent_router"

    # --- Semantic ---
    SEMANTIC_PARSE = "semantic_parse"
    SLOT_EXTRACTOR = "slot_extractor"
    FRAME_VALIDATOR = "frame_validator"

    # --- Context & Target ---
    CONTEXT_RECOVERY = "context_recovery"
    TARGET_RESOLVE = "target_resolve"
    CLARIFY_DECIDE = "clarify_decide"

    # --- Planning ---
    TASK_PLAN = "task_plan"
    FACET_PLAN = "facet_plan"
    COMPARISON_PLANNER = "comparison_planner"
    PLAN_VALIDATOR = "plan_validator"

    # --- Execution ---
    TOOL_EXECUTE = "tool_execute"

    # --- Evidence & Answer ---
    EVIDENCE_BUILD = "evidence_build"
    ANSWER_PLAN_BUILD = "answer_plan_build"
    ANSWER_GENERATE = "answer_generate"
    ANSWER_VERIFY = "answer_verify"
    REWRITE = "rewrite"

    # --- Response ---
    CLARIFY_RESPONSE = "clarify_response"
    FALLBACK_ANSWER = "fallback_answer"
    FINAL_RESPONSE_BUILD = "final_response_build"

    # --- State & Emit ---
    STATE_UPDATE_PLAN = "state_update_plan"
    PERSIST_SESSION_STATE = "persist_session_state"
    EMIT_RESPONSE = "emit_response"


@dataclass
class NodeResult:
    """The result produced by executing a single node.

    Every node in the graph produces this structure regardless of
    whether it succeeded, failed, or needs clarification.
    """
    node: ExecutionNode
    status: str
    metadata: dict = field(default_factory=dict)
    rewrite_count: int = 0


@dataclass
class RoutingResult:
    """The output of the routing engine for a single transition.

    Tells the execution loop what to do next.
    """
    next_node: ExecutionNode | None  # None signals end of turn
    emit_response: bool
    session_write: "SessionWriteDirective | None" = None
    emit_content: dict | None = None
