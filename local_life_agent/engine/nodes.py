"""Execution node definitions for the state machine.

Mirrors the node table from `todo/05_LangGraph鑺傜偣杈圭姸鎬佸瓧娈佃〃.md`
and the transition rules from `todo/02_鐘舵€佽浆绉讳笌璺敱鍐崇瓥琛?md`.
"""
from __future__ import annotations
from enum import Enum
from dataclasses import dataclass, field
from typing import Any

from ..domain.state import SessionWriteDirective


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

    # --- P2: Goal Planning ---
    GOAL_PLANNER = "goal_planner"
    GOAL_REVIEW = "goal_review"

    # --- Planning ---
    EVIDENCE_PLANNER = "evidence_planner"
    PLAN_VALIDATOR = "plan_validator"

    # --- Execution ---
    TOOL_EXECUTE = "tool_execute"

    # --- Evidence & Answer ---
    EVIDENCE_BUILD = "evidence_build"
    EVIDENCE_REVIEW = "evidence_review"
    ANSWER_PLAN_BUILD = "answer_plan_build"

    # --- P2: Decision Planning ---
    DECISION_PLANNER = "decision_planner"
    DECISION_REVIEW = "decision_review"

    # --- Answer ---
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

