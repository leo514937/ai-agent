"""State transition routing engine.

Implements the state transition table from
`todo/02_状态转移与路由决策表.md` §1.

Each rule captures: current node + status → next node, emit decision,
and session write directive.
"""

from __future__ import annotations

from .nodes import ExecutionNode, NodeResult, RoutingResult
from .session_write import SessionScenario, get_directive, resolve_scenario
from ..domain.state import SessionWriteDirective

# ---------------------------------------------------------------------------
# Transition rule: a single row in the decision table
# ---------------------------------------------------------------------------


class TransitionRule:
    """One row in the state transition table."""

    def __init__(
        self,
        node: ExecutionNode,
        status: str,
        next_node: ExecutionNode | None,
        emit: bool,
        session_scenario: SessionScenario | None = None,
    ):
        self.node = node
        self.status = status
        self.next_node = next_node
        self.emit = emit
        self.session_scenario = session_scenario

    def matches(self, result: NodeResult) -> bool:
        return result.node == self.node and result.status == self.status


# ---------------------------------------------------------------------------
# The full transition table (12 rules from doc 02 §1)
# ---------------------------------------------------------------------------

TRANSITION_TABLE: list[TransitionRule] = [
    # 1. semantic_parse → JSON parse fail → clarification (after retry exhausted)
    TransitionRule(
        node=ExecutionNode.SEMANTIC_PARSE,
        status="json_parse_fail",
        next_node=ExecutionNode.CLARIFY_RESPONSE,
        emit=True,
    ),
    # 2. semantic_parse → task_type missing/invalid → frame_validator fix/reject
    TransitionRule(
        node=ExecutionNode.SEMANTIC_PARSE,
        status="task_type_invalid",
        next_node=ExecutionNode.FRAME_VALIDATOR,
        emit=True,
    ),
    # 3. resolve_shop → RESOLVED → task_plan
    TransitionRule(
        node=ExecutionNode.TARGET_RESOLVE,
        status="RESOLVED",
        next_node=ExecutionNode.TASK_PLAN,
        emit=False,
        session_scenario=SessionScenario.SINGLE_SHOP_COUPON_OK,
    ),
    # 4. resolve_shop → AMBIGUOUS → clarify_response
    TransitionRule(
        node=ExecutionNode.TARGET_RESOLVE,
        status="AMBIGUOUS",
        next_node=ExecutionNode.CLARIFY_RESPONSE,
        emit=True,
        session_scenario=SessionScenario.RESOLVE_SHOP_AMBIGUOUS,
    ),
    # 5. resolve_shop → LOW_CONFIDENCE → clarify_response
    TransitionRule(
        node=ExecutionNode.TARGET_RESOLVE,
        status="LOW_CONFIDENCE",
        next_node=ExecutionNode.CLARIFY_RESPONSE,
        emit=True,
        session_scenario=SessionScenario.RESOLVE_SHOP_AMBIGUOUS,
    ),
    # 6. resolve_shop → NOT_FOUND → fallback_answer
    TransitionRule(
        node=ExecutionNode.TARGET_RESOLVE,
        status="NOT_FOUND",
        next_node=ExecutionNode.FALLBACK_ANSWER,
        emit=True,
    ),
    # 7. tool_execute → required_tool unknown/failed → fallback_answer
    TransitionRule(
        node=ExecutionNode.TOOL_EXECUTE,
        status="required_tool_failed",
        next_node=ExecutionNode.FALLBACK_ANSWER,
        emit=True,
        session_scenario=SessionScenario.TOOL_UNKNOWN_FAILED,
    ),
    # 8. tool_execute → optional_tool unknown/failed → continue evidence_build
    TransitionRule(
        node=ExecutionNode.TOOL_EXECUTE,
        status="optional_tool_failed",
        next_node=ExecutionNode.EVIDENCE_BUILD,
        emit=True,
    ),
    # 9. tool_execute → circuit_open → fallback_answer
    TransitionRule(
        node=ExecutionNode.TOOL_EXECUTE,
        status="circuit_open",
        next_node=ExecutionNode.FALLBACK_ANSWER,
        emit=True,
        session_scenario=SessionScenario.TOOL_UNKNOWN_FAILED,
    ),
    # 10. answer_verify → pass → final_response_build
    TransitionRule(
        node=ExecutionNode.ANSWER_VERIFY,
        status="pass",
        next_node=ExecutionNode.FINAL_RESPONSE_BUILD,
        emit=True,
    ),
    # 11. answer_verify → rewrite_attempt < 2 → rewrite
    TransitionRule(
        node=ExecutionNode.ANSWER_VERIFY,
        status="rewrite_needed",
        next_node=ExecutionNode.REWRITE,
        emit=False,
    ),
    # 12. answer_verify → rewrite_attempt >= 2 → fallback_answer
    TransitionRule(
        node=ExecutionNode.ANSWER_VERIFY,
        status="rewrite_exhausted",
        next_node=ExecutionNode.FALLBACK_ANSWER,
        emit=True,
    ),
]


# ---------------------------------------------------------------------------
# Normal flow edges (not in the transition table, but required for routing)
# ---------------------------------------------------------------------------

NORMAL_FLOW: dict[ExecutionNode, ExecutionNode] = {
    ExecutionNode.RECEIVE_INPUT: ExecutionNode.LOAD_SESSION_STATE,
    ExecutionNode.LOAD_SESSION_STATE: ExecutionNode.CHECK_PENDING_CLARIFICATION,
    ExecutionNode.CHECK_PENDING_CLARIFICATION: ExecutionNode.BASIC_INPUT_VALIDATE,
    ExecutionNode.BASIC_INPUT_VALIDATE: ExecutionNode.NORMALIZE_TEXT,
    ExecutionNode.NORMALIZE_TEXT: ExecutionNode.HARD_GUARD,
    ExecutionNode.HARD_GUARD: ExecutionNode.TOP_INTENT_ROUTER,
    ExecutionNode.TOP_INTENT_ROUTER: ExecutionNode.SEMANTIC_PARSE,
    ExecutionNode.SEMANTIC_PARSE: ExecutionNode.SLOT_EXTRACTOR,
    ExecutionNode.SLOT_EXTRACTOR: ExecutionNode.CONTEXT_RECOVERY,
    ExecutionNode.CONTEXT_RECOVERY: ExecutionNode.TARGET_RESOLVE,
    ExecutionNode.TARGET_RESOLVE: ExecutionNode.TASK_PLAN,
    ExecutionNode.TASK_PLAN: ExecutionNode.FACET_PLAN,
    ExecutionNode.FACET_PLAN: ExecutionNode.PLAN_VALIDATOR,
    ExecutionNode.PLAN_VALIDATOR: ExecutionNode.TOOL_EXECUTE,
    ExecutionNode.TOOL_EXECUTE: ExecutionNode.EVIDENCE_BUILD,
    ExecutionNode.EVIDENCE_BUILD: ExecutionNode.ANSWER_PLAN_BUILD,
    ExecutionNode.ANSWER_PLAN_BUILD: ExecutionNode.ANSWER_GENERATE,
    ExecutionNode.ANSWER_GENERATE: ExecutionNode.ANSWER_VERIFY,
    ExecutionNode.ANSWER_VERIFY: ExecutionNode.FINAL_RESPONSE_BUILD,
    ExecutionNode.FINAL_RESPONSE_BUILD: ExecutionNode.STATE_UPDATE_PLAN,
    ExecutionNode.STATE_UPDATE_PLAN: ExecutionNode.PERSIST_SESSION_STATE,
    ExecutionNode.PERSIST_SESSION_STATE: ExecutionNode.EMIT_RESPONSE,
    # Branch terminal nodes that feed back into state/persist
    ExecutionNode.CLARIFY_RESPONSE: ExecutionNode.STATE_UPDATE_PLAN,
    ExecutionNode.FALLBACK_ANSWER: ExecutionNode.STATE_UPDATE_PLAN,
    ExecutionNode.REWRITE: ExecutionNode.ANSWER_GENERATE,
}


# ---------------------------------------------------------------------------
# Routing engine
# ---------------------------------------------------------------------------


def route(result: NodeResult) -> RoutingResult:
    """Determine the next node, emit behavior, and session write directive
    based on the current node result.

    Priority:
    1. Check the transition table for a matching rule (branches/exceptional paths).
    2. Fall back to the normal-flow edge (happy path).
    3. If no edge exists, end the turn (next_node=None).
    """

    # --- 1. Check transition table for matching rule ---
    for rule in TRANSITION_TABLE:
        if rule.matches(result):
            directive = None
            if rule.session_scenario is not None:
                directive = get_directive(rule.session_scenario)
            return RoutingResult(
                next_node=rule.next_node,
                emit_response=rule.emit,
                session_write=directive,
            )

    # --- 2. Normal flow fallback ---
    next_node = NORMAL_FLOW.get(result.node)
    if next_node is not None:
        return RoutingResult(
            next_node=next_node,
            emit_response=False,
            session_write=None,
        )

    # --- 3. Terminal ---
    return RoutingResult(
        next_node=None,
        emit_response=True,
        session_write=None,
    )


def route_with_status(
    node: ExecutionNode,
    status: str,
    rewrite_count: int = 0,
    metadata: dict | None = None,
) -> RoutingResult:
    """Convenience wrapper: construct a NodeResult and route it."""
    return route(NodeResult(
        node=node,
        status=status,
        metadata=metadata or {},
        rewrite_count=rewrite_count,
    ))
