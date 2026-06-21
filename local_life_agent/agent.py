"""Main orchestration entry for the local life agent runtime.

Drives the execution graph as a state machine. The routing decisions
follow `todo/02_状态转移与路由决策表.md` — every transition is a
first-class rule in the transition table, not ad-hoc if/else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from . import config
from .domain.state import SessionState, SessionWriteDirective
from .engine import (
    ExecutionNode,
    NodeResult,
    RoutingResult,
    route,
    route_with_status,
)


_GRAPH_CACHE: Any = None


def _debug_dump(value: Any, _seen: set[int] | None = None) -> Any:
    if isinstance(value, Enum):
        return value.value
    if _seen is None:
        _seen = set()
    if isinstance(value, (dict, list)) or hasattr(value, "__dict__"):
        obj_id = id(value)
        if obj_id in _seen:
            return "<recursive>"
        _seen.add(obj_id)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _debug_dump(model_dump(), _seen)
    if isinstance(value, dict):
        return {k: _debug_dump(v, _seen) for k, v in value.items()}
    if isinstance(value, list):
        return [_debug_dump(item, _seen) for item in value]
    if hasattr(value, "__dict__"):
        return {k: _debug_dump(v, _seen) for k, v in vars(value).items() if not str(k).startswith("_")}
    return value


@dataclass
class DebugInfo:
    execution_trace: list = field(default_factory=list)
    semantic_frame: dict = field(default_factory=dict)
    execution_plan: dict = field(default_factory=dict)
    tool_results: dict = field(default_factory=dict)
    evidence_pack: dict = field(default_factory=dict)
    session_state_before: dict = field(default_factory=dict)
    session_state_after: dict = field(default_factory=dict)
    state_update_plan: dict = field(default_factory=dict)
    answer_source: str = ""
    llm_verbalizer_violation: str | None = None



@dataclass
class AgentResponse:
    answer_text: str = ""
    trace_id: str = ""
    session_id: str = ""
    clarification: str | None = None
    cards: list = field(default_factory=list)
    debug: DebugInfo | None = None

    def to_dict(self) -> dict:
        result: dict[str, Any] = {
            "answer_text": self.answer_text,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "clarification": self.clarification,
            "cards": self.cards,
        }
        if config.DEBUG_ENABLED and self.debug is not None:
            result["debug"] = {
                "execution_trace": self.debug.execution_trace,
                "semantic_frame": _debug_dump(self.debug.semantic_frame),
                "execution_plan": _debug_dump(self.debug.execution_plan),
                "tool_results": _debug_dump(self.debug.tool_results),
                "evidence_pack": _debug_dump(self.debug.evidence_pack),
                "session_state_before": _debug_dump(self.debug.session_state_before),
                "session_state_after": _debug_dump(self.debug.session_state_after),
                "state_update_plan": _debug_dump(self.debug.state_update_plan),
                "answer_source": self.debug.answer_source,
                "llm_verbalizer_violation": self.debug.llm_verbalizer_violation,
            }

        else:
            result["debug"] = {}
        return result


# ---------------------------------------------------------------------------
# Node execution stubs — each dispatches to the real implementation module.
# These are thin wrappers so the state machine can treat all nodes uniformly.
# ---------------------------------------------------------------------------

_NODE_EXECUTORS: dict[ExecutionNode, Any] = {}


def _register_node(node: ExecutionNode):
    """Decorator to register an executor function for a node."""
    def wrapper(fn):
        _NODE_EXECUTORS[node] = fn
        return fn
    return wrapper


@_register_node(ExecutionNode.RECEIVE_INPUT)
def _exec_receive_input(ctx: dict) -> NodeResult:
    # TODO: delegate to input/receiver.py
    return NodeResult(node=ExecutionNode.RECEIVE_INPUT, status="ok")


@_register_node(ExecutionNode.LOAD_SESSION_STATE)
def _exec_load_session_state(ctx: dict) -> NodeResult:
    # TODO: load from persistence
    return NodeResult(node=ExecutionNode.LOAD_SESSION_STATE, status="ok")


@_register_node(ExecutionNode.CHECK_PENDING_CLARIFICATION)
def _exec_check_pending(ctx: dict) -> NodeResult:
    # TODO: delegate to target/clarification.py
    return NodeResult(node=ExecutionNode.CHECK_PENDING_CLARIFICATION, status="ok")


@_register_node(ExecutionNode.BASIC_INPUT_VALIDATE)
def _exec_basic_validate(ctx: dict) -> NodeResult:
    return NodeResult(node=ExecutionNode.BASIC_INPUT_VALIDATE, status="ok")


@_register_node(ExecutionNode.NORMALIZE_TEXT)
def _exec_normalize(ctx: dict) -> NodeResult:
    # TODO: delegate to input/normalizer.py
    return NodeResult(node=ExecutionNode.NORMALIZE_TEXT, status="ok")


@_register_node(ExecutionNode.HARD_GUARD)
def _exec_hard_guard(ctx: dict) -> NodeResult:
    # TODO: delegate to input/hard_guard.py
    return NodeResult(node=ExecutionNode.HARD_GUARD, status="ok")


@_register_node(ExecutionNode.TOP_INTENT_ROUTER)
def _exec_top_intent(ctx: dict) -> NodeResult:
    # TODO: delegate to semantic/intent_parser.py
    return NodeResult(node=ExecutionNode.TOP_INTENT_ROUTER, status="ok")


@_register_node(ExecutionNode.SEMANTIC_PARSE)
def _exec_semantic_parse(ctx: dict) -> NodeResult:
    # TODO: delegate to semantic/
    return NodeResult(node=ExecutionNode.SEMANTIC_PARSE, status="ok")


@_register_node(ExecutionNode.SLOT_EXTRACTOR)
def _exec_slot_extract(ctx: dict) -> NodeResult:
    # TODO: delegate to semantic/slot_extractor.py
    return NodeResult(node=ExecutionNode.SLOT_EXTRACTOR, status="ok")


@_register_node(ExecutionNode.CONTEXT_RECOVERY)
def _exec_context_recovery(ctx: dict) -> NodeResult:
    # TODO: delegate to target/context_recovery.py
    return NodeResult(node=ExecutionNode.CONTEXT_RECOVERY, status="ok")


@_register_node(ExecutionNode.TARGET_RESOLVE)
def _exec_target_resolve(ctx: dict) -> NodeResult:
    # TODO: delegate to target/shop_resolver.py
    return NodeResult(node=ExecutionNode.TARGET_RESOLVE, status="ok")


@_register_node(ExecutionNode.CLARIFY_DECIDE)
def _exec_clarify_decide(ctx: dict) -> NodeResult:
    # TODO: delegate to target/clarification.py (clarify_decide logic)
    return NodeResult(node=ExecutionNode.CLARIFY_DECIDE, status="ok")


@_register_node(ExecutionNode.TASK_PLAN)
def _exec_task_plan(ctx: dict) -> NodeResult:
    # TODO: delegate to planning/task_router.py
    return NodeResult(node=ExecutionNode.TASK_PLAN, status="ok")


@_register_node(ExecutionNode.FACET_PLAN)
def _exec_facet_plan(ctx: dict) -> NodeResult:
    # TODO: delegate to planning/facet_planner.py
    return NodeResult(node=ExecutionNode.FACET_PLAN, status="ok")


@_register_node(ExecutionNode.PLAN_VALIDATOR)
def _exec_plan_validator(ctx: dict) -> NodeResult:
    # TODO: delegate to planning/execution_plan_builder.py (validate step)
    return NodeResult(node=ExecutionNode.PLAN_VALIDATOR, status="ok")


@_register_node(ExecutionNode.TOOL_EXECUTE)
def _exec_tool_execute(ctx: dict) -> NodeResult:
    # TODO: delegate to tools/gateway.py + executor.py
    return NodeResult(node=ExecutionNode.TOOL_EXECUTE, status="ok")


@_register_node(ExecutionNode.EVIDENCE_BUILD)
def _exec_evidence_build(ctx: dict) -> NodeResult:
    # TODO: delegate to answer/evidence_builder.py
    return NodeResult(node=ExecutionNode.EVIDENCE_BUILD, status="ok")


@_register_node(ExecutionNode.ANSWER_PLAN_BUILD)
def _exec_answer_plan(ctx: dict) -> NodeResult:
    # TODO: delegate to answer/answer_plan_builder.py
    return NodeResult(node=ExecutionNode.ANSWER_PLAN_BUILD, status="ok")


@_register_node(ExecutionNode.ANSWER_GENERATE)
def _exec_answer_generate(ctx: dict) -> NodeResult:
    # TODO: delegate to answer/generator.py
    return NodeResult(node=ExecutionNode.ANSWER_GENERATE, status="ok")


@_register_node(ExecutionNode.ANSWER_VERIFY)
def _exec_answer_verify(ctx: dict) -> NodeResult:
    # TODO: delegate to answer/verifier.py
    return NodeResult(node=ExecutionNode.ANSWER_VERIFY, status="ok")


@_register_node(ExecutionNode.REWRITE)
def _exec_rewrite(ctx: dict) -> NodeResult:
    # TODO: delegate to answer/verifier.py (rewrite path)
    return NodeResult(node=ExecutionNode.REWRITE, status="ok", rewrite_count=ctx.get("rewrite_count", 0) + 1)


@_register_node(ExecutionNode.CLARIFY_RESPONSE)
def _exec_clarify(ctx: dict) -> NodeResult:
    # TODO: delegate to answer/final_response_builder.py (clarification path)
    return NodeResult(node=ExecutionNode.CLARIFY_RESPONSE, status="ok")


@_register_node(ExecutionNode.FALLBACK_ANSWER)
def _exec_fallback(ctx: dict) -> NodeResult:
    # TODO: delegate to answer/generator.py (fallback path)
    return NodeResult(node=ExecutionNode.FALLBACK_ANSWER, status="ok")


@_register_node(ExecutionNode.FINAL_RESPONSE_BUILD)
def _exec_final_response(ctx: dict) -> NodeResult:
    # TODO: delegate to answer/final_response_builder.py
    return NodeResult(node=ExecutionNode.FINAL_RESPONSE_BUILD, status="ok")


@_register_node(ExecutionNode.STATE_UPDATE_PLAN)
def _exec_state_update(ctx: dict) -> NodeResult:
    # TODO: delegate to answer/state_update_planner.py
    return NodeResult(node=ExecutionNode.STATE_UPDATE_PLAN, status="ok")


@_register_node(ExecutionNode.PERSIST_SESSION_STATE)
def _exec_persist(ctx: dict) -> NodeResult:
    # TODO: persist to redis/db
    return NodeResult(node=ExecutionNode.PERSIST_SESSION_STATE, status="ok")


@_register_node(ExecutionNode.EMIT_RESPONSE)
def _exec_emit(ctx: dict) -> NodeResult:
    # Terminal node — no real work, just marks end of turn
    return NodeResult(node=ExecutionNode.EMIT_RESPONSE, status="ok")


# ---------------------------------------------------------------------------
# Session state apply
# ---------------------------------------------------------------------------


def _apply_session_write(
    state: SessionState,
    directive: SessionWriteDirective | None,
    ctx: dict,
) -> None:
    """Mutate session state according to the write directive.

    set_fields: {field_name: value_or_None}.
        If value is None, the caller must have set `ctx[field_name]`.
    clear_fields: field names to reset.
    """
    if directive is None:
        return

    for field_name, value in directive.set_fields.items():
        resolved = ctx.get(field_name) if value is None else value
        if resolved is not None:
            setattr(state, field_name, resolved)

    for field_name in directive.clear_fields:
        default = _field_default(state, field_name)
        setattr(state, field_name, default)


def _field_default(state: SessionState, name: str) -> Any:
    """Return the default empty value for a session state field."""
    model_fields = state.model_fields
    if name not in model_fields:
        return None
    field_info = model_fields[name]
    # Pydantic v2: default_factory set -> call it; default set -> return it
    if field_info.default_factory is not None:
        return field_info.default_factory()
    if field_info.default is not None:
        return field_info.default
    # A field with no default and no factory -> default to None
    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def _run_agent_legacy(input_text: str, session_id: str = "") -> AgentResponse:
    """Execute one full turn of the local life agent.

    The turn is driven by the state machine defined in
    `todo/02_状态转移与路由决策表.md`:

        1. Execute the current node (producing a NodeResult with status).
        2. Route to the next node via `route()`, which consults the
           12-rule transition table (exceptional branches) and the
           normal-flow edges (happy path).
        3. Apply any SessionWriteDirective from the route decision.
        4. If emit_response is True, the loop ends and the response is built.
        5. Otherwise, advance to the next node and repeat.

    The loop always terminates because:
        - Every node either transitions to a known next node, or
        - The routing engine returns next_node=None (terminal).
    """
    trace_id = f"trace_{id(input_text)}_{session_id or 'anon'}"
    session_state = SessionState()
    debug_trace: list[dict] = []
    ctx: dict[str, Any] = {
        "input_text": input_text,
        "session_id": session_id,
        "trace_id": trace_id,
        "rewrite_count": 0,
        "session_state": session_state,
    }

    # --- Start state machine ---
    current_node: ExecutionNode | None = ExecutionNode.RECEIVE_INPUT
    final_result: NodeResult | None = None

    while current_node is not None:
        executor = _NODE_EXECUTORS.get(current_node)
        if executor is None:
            # Node registered but no executor — safe skip (stub)
            result = NodeResult(node=current_node, status="ok")
        else:
            result = executor(ctx)

        debug_trace.append({
            "node": current_node.value,
            "status": result.status,
        })

        # --- Route ---
        routing: RoutingResult = route(result)

        # --- Apply session write directive ---
        _apply_session_write(session_state, routing.session_write, ctx)

        # --- Emit? ---
        if routing.emit_response:
            final_result = result
            # Continue only to EMIT_RESPONSE via next_node
            # (emit flag means "this transition expects a response build")
            pass

        current_node = routing.next_node

    # --- Build response ---
    response = AgentResponse(
        answer_text="",
        trace_id=trace_id,
        session_id=session_id,
        clarification=None,
        debug=DebugInfo(
            execution_trace=debug_trace,
        ) if config.DEBUG_ENABLED else None,
    )

    return response


# ---------------------------------------------------------------------------
# LangGraph entry  (todo/05 — StateGraph alternative to the state-machine loop)
# ---------------------------------------------------------------------------


def run_agent(input_text: str, session_id: str = "") -> AgentResponse:
    """Public entry point; thin wrapper around the LangGraph runtime."""
    return run_agent_graph(input_text, session_id=session_id)


def run_agent_graph(input_text: str, session_id: str = "") -> AgentResponse:
    """Execute one full turn via ``StateGraph`` (todo/05 LangGraph entry).

    This is the LangGraph-based alternative to ``run_agent()``.
    It builds the graph, invokes it with the initial state, and
    returns an ``AgentResponse`` built from the final state.
    """
    from .domain.graph_state import GraphState
    from .engine.graph_builder import build_graph

    global _GRAPH_CACHE
    if _GRAPH_CACHE is None:
        _GRAPH_CACHE = build_graph()
    graph = _GRAPH_CACHE

    initial = {
        "raw_text": input_text,
        "session_id": session_id or "",
        "trace_id": f"trace_{id(input_text)}_{session_id or 'anon'}",
        "turn_id": "",
        "user_id": "",
        "normalized_text": "",
        "input_type": "text",
        "top_intent": None,
        "task_type": None,
        "semantic_frame": None,
        "pending_clarification": None,
        "current_shop": None,
        "last_recommendation_list": [],
        "active_constraints": {},
        "comparison_targets": [],
        "comparison_result": None,
        "recommendation_candidates": [],
        "precomputed_tool_results": {},
        "resolved_target": None,
        "resolve_shop_result": None,
        "execution_plan": None,
        "validated_plan": None,
        "tool_results": {},
        "tool_result_set": {},
        "evidence_pack": None,
        "answer_plan": None,
        "final_response": "",
        "state_update_plan": None,
        "session_state_before": None,
        "session_state_after": None,
        "event_log": [],
        "metrics_tags": {},
        "trace_spans": [],
        "rewrite_count": 0,
        "session_state": None,
        "pending_check_result": "pass",
        "error_code": "",
        "guard_result": "",
        "verify_result": "",
        "draft_response": "",
        "semantic_source": "",
        "llm_backend": "",
        "fallback_reason": "",
        "llm_called": False,
        "answer_source": "",
        "llm_verbalizer_violation": None,
        "comparison_target_resolution": None,
    }


    final_state = graph.invoke(initial)

    answer = final_state.get("final_response", "")
    trace_id = final_state.get("trace_id", "")
    sid = final_state.get("session_id", session_id)
    event_log = final_state.get("event_log", [])

    response = AgentResponse(
        answer_text=answer,
        trace_id=trace_id,
        session_id=sid,
        debug=DebugInfo(
            execution_trace=event_log,
            semantic_frame=_debug_dump(final_state.get("semantic_frame") or {}),
            execution_plan=_debug_dump(final_state.get("execution_plan") or {}),
            tool_results=_debug_dump(final_state.get("tool_result_set") or final_state.get("tool_results") or {}),
            evidence_pack=_debug_dump(final_state.get("evidence_pack") or {}),
            session_state_before=_debug_dump(final_state.get("session_state_before") or {}),
            session_state_after=_debug_dump(final_state.get("session_state_after") or {}),
            state_update_plan=_debug_dump(final_state.get("state_update_plan") or {}),
            answer_source=final_state.get("answer_source", ""),
            llm_verbalizer_violation=final_state.get("llm_verbalizer_violation"),
        ) if config.DEBUG_ENABLED else None,
    )

    return response
