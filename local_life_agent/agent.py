"""Main orchestration entry for the local life agent runtime.

Drives the execution graph as a state machine. The routing decisions
follow `todo/02_状态转移与路由决策表.md` — every transition is a
first-class rule in the transition table, not ad-hoc if/else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import logging
from time import perf_counter
from typing import Any
from . import config
from .observability.file_logger import get_python_service_logger, log_kv, reset_log_context, set_log_context
from .observability.metrics import record_turn_metric
from .observability.trace import build_turn_trace
from .location_utils import normalize_location_payload


_GRAPH_CACHE: Any = None
_FILE_LOGGER = get_python_service_logger()


def _observed_nodes(final_state: dict[str, Any]) -> list[str]:
    observed: list[str] = []
    for item in final_state.get("event_log", []) or []:
        if not isinstance(item, dict):
            continue
        node = str(item.get("node", "") or "").strip()
        if node and node not in observed:
            observed.append(node)
    return observed


def _expected_core_nodes(final_state: dict[str, Any]) -> list[str]:
    response_mode = str(final_state.get("response_mode", "") or "")
    top_intent = str(final_state.get("top_intent", "") or "")
    nodes = ["intake_guard_router"]
    if top_intent == "local_life":
        nodes.extend(
            [
                "understanding_subgraph",
                "orchestration_router_shadow",
                "workflow_runner",
                "planning_subgraph",
                "execution_review_subgraph",
                "response_subgraph",
                "state_update_plan",
            ]
        )
    elif response_mode:
        nodes.extend(["response_subgraph", "state_update_plan"])
    return nodes


def _audit_turn_completeness(final_state: dict[str, Any]) -> dict[str, Any]:
    observed = _observed_nodes(final_state)
    expected = _expected_core_nodes(final_state)
    tool_results = final_state.get("tool_result_set") or final_state.get("tool_results") or {}
    failed_tools = [
        call_id
        for call_id, result in (tool_results.items() if isinstance(tool_results, dict) else [])
        if str(_debug_dump(getattr(result, "result_status", None) or (result.get("result_status") if isinstance(result, dict) else ""))).lower()
        in {"failed", "unknown", "circuit_open", "unsupported"}
    ]
    return {
        "observed_nodes": observed,
        "missing_nodes": [node for node in expected if node not in observed],
        "llm_called": bool(final_state.get("llm_called") or final_state.get("planning_llm_called") or final_state.get("llm_verbalizer_called")),
        "tool_call_count": len(tool_results) if isinstance(tool_results, dict) else 0,
        "failed_tool_calls": failed_tools,
        "has_final_response": bool(str(final_state.get("final_response", "") or "").strip()),
        "answer_source": final_state.get("answer_source", ""),
    }


def _extract_response_text(final_state: dict[str, Any]) -> str:
    """Best-effort terminal answer extraction for legacy bypass compatibility.

    The graph should prefer ``final_response`` as the authoritative field,
    but some legacy paths still only populate the directive / draft fields.
    Keep this extraction order narrow and deterministic so the terminal
    response remains non-empty without changing graph semantics.
    """
    for key in ("final_response", "draft_response", "preview_text"):
        text = str(final_state.get(key, "") or "").strip()
        if text:
            return text

    directive = final_state.get("response_directive")
    for attr in ("final_response", "answer_text", "preview_text"):
        text = str(getattr(directive, attr, "") or "").strip()
        if text:
            return text

    contract = final_state.get("response_contract_v1")
    for attr in ("answer_text", "preview_text"):
        text = str(getattr(contract, attr, "") or "").strip()
        if text:
            return text

    contract_v2 = final_state.get("response_contract_v2")
    for attr in ("answer_text", "preview_text", "final_response"):
        text = str(getattr(contract_v2, attr, "") or "").strip()
        if text:
            return text

    return ""


def _debug_dump(value: Any, _seen: set[int] | None = None) -> Any:
    if isinstance(value, Enum):
        return value.value
    if _seen is None:
        _seen = set()
    if isinstance(value, (dict, list)) or hasattr(value, "__dict__"):
        obj_id = id(value)
        if obj_id in _seen:
            return "<recursive>"
        _seen = _seen | {obj_id}
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
    turn_trace: dict = field(default_factory=dict)
    semantic_frame: dict = field(default_factory=dict)
    execution_plan: dict = field(default_factory=dict)
    tool_results: dict = field(default_factory=dict)
    evidence_pack: dict = field(default_factory=dict)
    session_state_before: dict = field(default_factory=dict)
    session_state_after: dict = field(default_factory=dict)
    state_update_plan: dict = field(default_factory=dict)
    answer_source: str = ""
    answer_fallback_reason: str = ""
    fallback_reason: str = ""
    llm_verbalizer_error: str | None = None
    generated_llm_answer_before_fallback: str = ""
    llm_verbalizer_violation: str | None = None
    answer_verify_passed: bool = True
    answer_verify_violations: list = field(default_factory=list)
    rewrite_needed: bool = False
    rewrite_count: int = 0
    rewrite_reason: str = ""
    final_safety_status: str = "safe"




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
                "turn_trace": _debug_dump(self.debug.turn_trace),
                "semantic_frame": _debug_dump(self.debug.semantic_frame),
                "execution_plan": _debug_dump(self.debug.execution_plan),
                "tool_results": _debug_dump(self.debug.tool_results),
                "evidence_pack": _debug_dump(self.debug.evidence_pack),
                "session_state_before": _debug_dump(self.debug.session_state_before),
                "session_state_after": _debug_dump(self.debug.session_state_after),
                "state_update_plan": _debug_dump(self.debug.state_update_plan),
                "answer_source": self.debug.answer_source,
                "answer_fallback_reason": self.debug.answer_fallback_reason,
                "fallback_reason": self.debug.fallback_reason,
                "llm_verbalizer_error": self.debug.llm_verbalizer_error,
                "generated_llm_answer_before_fallback": self.debug.generated_llm_answer_before_fallback,
                "llm_verbalizer_violation": self.debug.llm_verbalizer_violation,
                "answer_verify_passed": self.debug.answer_verify_passed,
                "answer_verify_violations": self.debug.answer_verify_violations,
                "rewrite_needed": self.debug.rewrite_needed,
                "rewrite_count": self.debug.rewrite_count,
                "rewrite_reason": self.debug.rewrite_reason,
                "final_safety_status": self.debug.final_safety_status,
            }


        else:
            result["debug"] = {}
        return result


# ---------------------------------------------------------------------------
# LangGraph entry  (todo/05 — StateGraph alternative to the state-machine loop)
# ---------------------------------------------------------------------------


def run_agent(input_text: str, session_id: str = "") -> AgentResponse:
    """Public entry point; thin wrapper around the LangGraph runtime."""
    return run_agent_graph(input_text, session_id=session_id)


def run_agent_graph(
    input_text: str,
    session_id: str = "",
    *,
    trace_id: str | None = None,
    turn_id: str | None = None,
    user_context: Any | None = None,
    user_location: dict[str, Any] | None = None,
) -> AgentResponse:
    """Execute one full turn via ``StateGraph`` (todo/05 LangGraph entry).

    This is the LangGraph-based alternative to ``run_agent()``.
    It builds the graph, invokes it with the initial state, and
    returns an ``AgentResponse`` built from the final state.
    """
    started_at = perf_counter()
    final_state: dict[str, Any] = {}
    from .engine.graph_builder import build_graph

    trace_id = str(trace_id or f"trace_{id(input_text)}_{session_id or 'anon'}")
    turn_id = str(turn_id or "")
    log_kv(
        _FILE_LOGGER,
        logging.INFO,
        "[TURN_START]",
        tone="route",
        trace_id=trace_id,
        session_id=session_id or "",
        input_text=input_text,
    )
    turn_context_token = set_log_context(trace_id=trace_id, session_id=session_id or "")

    global _GRAPH_CACHE
    if _GRAPH_CACHE is None:
        _GRAPH_CACHE = build_graph()
    graph = _GRAPH_CACHE

    initial = {
        "raw_text": input_text,
        "session_id": session_id or "",
        "trace_id": trace_id,
        "turn_id": turn_id,
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
        "answer_fallback_reason": "",
        "llm_called": False,
        "answer_source": "",
        "llm_verbalizer_error": None,
        "generated_llm_answer_before_fallback": "",
        "llm_verbalizer_violation": None,
        "comparison_target_resolution": None,
        "reference_resolution_source": "",
        "answer_verify_passed": True,
        "answer_verify_violations": [],
        "rewrite_needed": False,
        "rewrite_reason": "",
        "final_safety_status": "safe",
        "recommendation_query": "",
        "user_context": normalize_location_payload(user_context),
        "user_location": normalize_location_payload(user_location or user_context),
    }
    # Some valid multi-turn paths exceed LangGraph's default recursion limit
    # of 25 because every node transition counts as a step.
    try:
        final_state = graph.invoke(initial, config={"recursion_limit": 64})

        answer = _extract_response_text(final_state)
        trace_id = final_state.get("trace_id", "")
        sid = final_state.get("session_id", session_id)
        event_log = final_state.get("event_log", [])
        elapsed_ms = (perf_counter() - started_at) * 1000.0
        turn_trace = build_turn_trace(final_state, user_text=input_text, total_duration_ms=int(elapsed_ms))

        response = AgentResponse(
            answer_text=answer,
            trace_id=trace_id,
            session_id=sid,
            debug=DebugInfo(
                execution_trace=event_log,
                turn_trace=turn_trace.to_dict(),
                semantic_frame=_debug_dump(final_state.get("semantic_frame") or {}),
                execution_plan=_debug_dump(final_state.get("validated_plan") or final_state.get("execution_plan") or {}),
                tool_results=_debug_dump(final_state.get("tool_result_set") or final_state.get("tool_results") or {}),
                evidence_pack=_debug_dump(final_state.get("evidence_pack") or {}),
                session_state_before=_debug_dump(final_state.get("session_state_before") or {}),
                session_state_after=_debug_dump(final_state.get("session_state_after") or {}),
                state_update_plan=_debug_dump(final_state.get("state_update_plan") or {}),
                answer_source=final_state.get("answer_source", ""),
                answer_fallback_reason=final_state.get("answer_fallback_reason", ""),
                fallback_reason=final_state.get("fallback_reason", ""),
                llm_verbalizer_error=final_state.get("llm_verbalizer_error"),
                generated_llm_answer_before_fallback=final_state.get("generated_llm_answer_before_fallback", ""),
                llm_verbalizer_violation=final_state.get("llm_verbalizer_violation"),
                answer_verify_passed=final_state.get("answer_verify_passed", True),
                answer_verify_violations=final_state.get("answer_verify_violations", []),
                rewrite_needed=final_state.get("rewrite_needed", False),
                rewrite_count=final_state.get("rewrite_count", 0),
                rewrite_reason=final_state.get("rewrite_reason", ""),
                final_safety_status=final_state.get("final_safety_status", "safe"),
            ) if config.DEBUG_ENABLED else None,
        )
        log_kv(
            _FILE_LOGGER,
            logging.INFO,
            "[TURN_AUDIT]",
            tone="route",
            trace_id=trace_id,
            session_id=sid,
            audit=_audit_turn_completeness(final_state),
        )
        log_kv(
            _FILE_LOGGER,
            logging.INFO,
            "[TURN_END]",
            tone="route",
            trace_id=trace_id,
            session_id=sid,
            task_type=final_state.get("task_type", ""),
            top_intent=final_state.get("top_intent", ""),
            answer_source=final_state.get("answer_source", ""),
            tool_count=len((final_state.get("tool_result_set") or final_state.get("tool_results") or {})),
            final_status=final_state.get("final_safety_status", "safe"),
            final_response=answer,
            event_count=len(event_log),
        )
        return response
    finally:
        elapsed_ms = (perf_counter() - started_at) * 1000.0
        record_turn_metric(final_state.get("trace_id", initial.get("trace_id", "")), elapsed_ms)
        reset_log_context(turn_context_token)

