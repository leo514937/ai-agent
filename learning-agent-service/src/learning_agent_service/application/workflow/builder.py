from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .runner import SequentialWorkflowRunner, _update_phase5_trace
from .services import WorkflowServices
from ...domain.errors import TerminalEvent
from .subgraphs import (
    run_plan_execute_subgraph,
    run_rag_subgraph,
    run_recommendation_subgraph,
    run_tool_subgraph,
    run_understand_turn,
    route_decider,
    route_gate,
    route_after_load_context,
    route_after_rag,
    route_after_understand,
)

try:
    from langgraph.graph import END, StateGraph
except ImportError:  # pragma: no cover - optional dependency
    END = "__end__"
    StateGraph = None


LANGGRAPH_AVAILABLE = StateGraph is not None
_CHECKPOINT_FALLBACKS: dict[str, dict[str, Any]] = {}


@dataclass
class _CheckpointSnapshot:
    values: dict[str, Any]


class _CheckpointAwareGraphProxy:
    def __init__(self, graph) -> None:
        self._graph = graph

    def invoke(self, state, config=None):
        thread_id = _thread_id_from_config(config) or _thread_id_from_state(state)
        if thread_id:
            _CHECKPOINT_FALLBACKS[thread_id] = deepcopy(state)
        result = self._graph.invoke(state, config=config)
        if thread_id:
            _CHECKPOINT_FALLBACKS[thread_id] = deepcopy(result)
        return result

    def get_state(self, config=None):
        thread_id = _thread_id_from_config(config)
        if thread_id and thread_id in _CHECKPOINT_FALLBACKS:
            return _CheckpointSnapshot(values=deepcopy(_CHECKPOINT_FALLBACKS[thread_id]))
        getter = getattr(self._graph, "get_state", None)
        if callable(getter):
            try:
                snapshot = getter(config)
            except Exception:
                snapshot = None
            if snapshot is not None and getattr(snapshot, "values", None):
                return snapshot
        return _CheckpointSnapshot(values={})

    def __getattr__(self, item):
        return getattr(self._graph, item)


def _thread_id_from_config(config: Any) -> str | None:
    if not isinstance(config, dict):
        return None
    configurable = config.get("configurable")
    if not isinstance(configurable, dict):
        return None
    thread_id = configurable.get("thread_id")
    text = str(thread_id or "").strip()
    return text or None


def _thread_id_from_state(state: Any) -> str | None:
    if not isinstance(state, dict):
        return None
    runtime = state.get("runtime")
    session_id = getattr(runtime, "session_id", None) if runtime is not None else None
    text = str(session_id or "").strip()
    return text or None


class LangGraphWorkflowRunner(SequentialWorkflowRunner):
    def __init__(
        self,
        services: WorkflowServices,
        workflow_version: str = "learn-agent/v1",
        checkpointer: object | None = None,
    ) -> None:
        super().__init__(services=services, workflow_version=workflow_version, runner_kind="langgraph")
        self._checkpointer = checkpointer
        self._graph = _CheckpointAwareGraphProxy(_build_langgraph_runner(services, checkpointer=checkpointer))

    def run_state(self, state):
        state = self._annotate_runner_context(state)
        if self._is_terminal(state):
            result = self._finalize_terminal(state)
            self._record_checkpoint_fallback(result)
            return self._annotate_runner_context(result)

        try:
            result = self._graph.invoke(state, config=_build_graph_config(state))
        except Exception as exc:
            result = self._record_unexpected_error(state, "langgraph.invoke", exc)
            result = self._finalize_terminal(result)
            self._record_checkpoint_fallback(result)
            return self._annotate_runner_context(result)

        runtime = result["runtime"]
        if runtime.emitted_events:
            if runtime.terminal_event is None:
                default_terminal = TerminalEvent.ERROR if runtime.errors else TerminalEvent.FINAL
                result["runtime"] = runtime.model_copy(update={"terminal_event": default_terminal})
            self._record_checkpoint_fallback(result)
            return self._annotate_runner_context(result)

        if result["runtime"].terminal_event == TerminalEvent.ERROR:
            result = self._finalize_terminal(result)
            self._record_checkpoint_fallback(result)
            return self._annotate_runner_context(result)
        result = self._finalize_terminal(result, default_terminal=TerminalEvent.FINAL)
        self._record_checkpoint_fallback(result)
        return self._annotate_runner_context(result)

    def _annotate_runner_context(self, state):
        return _update_phase5_trace(
            state,
            runner_kind=self.runner_kind,
            runner_backend="langgraph",
            graph_runtime="langgraph",
            runner_class=self.__class__.__name__,
            compare_ready=True,
        )

    def _record_checkpoint_fallback(self, state):
        if self._checkpointer is None:
            return
        thread_id = _thread_id_from_state(state)
        if thread_id:
            _CHECKPOINT_FALLBACKS[thread_id] = deepcopy(state)


def _build_graph_config(state):
    runtime = state["runtime"]
    return {"configurable": {"thread_id": runtime.session_id}}


_LANGGRAPH_TOPOLOGY = {
    "entry_point": "load_context",
    "terminal": "END",
    "nodes": [
        "load_context",
        "understand_turn",
        "route_gate",
        "plan_execute_subgraph",
        "rag_subgraph",
        "recommendation_subgraph",
        "tool_subgraph",
        "compose_answer",
        "persist_session",
        "emit_final",
    ],
    "edges": [
        ("START", "load_context"),
        ("load_context", "understand_turn"),
        ("load_context", "compose_answer"),
        ("understand_turn", "plan_execute_subgraph"),
        ("understand_turn", "route_gate"),
        ("route_gate", "compose_answer"),
        ("route_gate", "tool_subgraph"),
        ("route_gate", "rag_subgraph"),
        ("route_gate", "recommendation_subgraph"),
        ("rag_subgraph", "tool_subgraph"),
        ("rag_subgraph", "compose_answer"),
        ("recommendation_subgraph", "compose_answer"),
        ("tool_subgraph", "compose_answer"),
        ("plan_execute_subgraph", "compose_answer"),
        ("compose_answer", "persist_session"),
        ("persist_session", "emit_final"),
        ("emit_final", "END"),
    ],
}


def describe_langgraph_topology() -> dict[str, Any]:
    return {
        "entry_point": _LANGGRAPH_TOPOLOGY["entry_point"],
        "terminal": _LANGGRAPH_TOPOLOGY["terminal"],
        "nodes": list(_LANGGRAPH_TOPOLOGY["nodes"]),
        "edges": [tuple(edge) for edge in _LANGGRAPH_TOPOLOGY["edges"]],
    }


def export_langgraph_mermaid() -> str:
    lines = ["graph TD"]
    for left, right in _LANGGRAPH_TOPOLOGY["edges"]:
        lines.append(f"  {left} --> {right}")
    return "\n".join(lines)


def _build_langgraph_runner(services: WorkflowServices, checkpointer: object | None = None):
    if not LANGGRAPH_AVAILABLE:
        raise RuntimeError("langgraph is not installed")

    graph = StateGraph(dict)
    graph.add_node("load_context", lambda state: services.load_context(state))
    graph.add_node("understand_turn", lambda state: run_understand_turn(state, services.understand_turn))
    graph.add_node("route_gate", lambda state: route_gate(state))
    graph.add_node(
        "plan_execute_subgraph",
        lambda state: run_plan_execute_subgraph(state, services.plan_execute_subgraph),
    )
    graph.add_node("rag_subgraph", lambda state: run_rag_subgraph(state, services.rag_subgraph))
    graph.add_node("recommendation_subgraph", lambda state: run_recommendation_subgraph(state, services.rag_subgraph))
    graph.add_node("tool_subgraph", lambda state: run_tool_subgraph(state, services.tool_subgraph))
    graph.add_node("compose_answer", lambda state: services.compose_answer(state))
    graph.add_node("persist_session", lambda state: services.persist_session(state))
    graph.add_node("emit_final", lambda state: services.emit_final(state))

    graph.set_entry_point("load_context")
    graph.add_conditional_edges(
        "load_context",
        route_after_load_context,
        {
            "understand_turn": "understand_turn",
            "compose_answer": "compose_answer",
        },
    )
    graph.add_conditional_edges(
        "understand_turn",
        route_after_understand,
        {
            "plan_execute_subgraph": "plan_execute_subgraph",
            "route_gate": "route_gate",
        },
    )
    graph.add_conditional_edges(
        "route_gate",
        route_decider,
        {
            "clarify": "compose_answer",
            "tool": "tool_subgraph",
            "rag": "rag_subgraph",
            "rag_plus_tool": "rag_subgraph",
            "recommendation": "recommendation_subgraph",
            "direct": "compose_answer",
        },
    )
    graph.add_conditional_edges(
        "rag_subgraph",
        route_after_rag,
        {
            "tool_subgraph": "tool_subgraph",
            "compose_answer": "compose_answer",
        },
    )
    graph.add_edge("recommendation_subgraph", "compose_answer")
    graph.add_edge("tool_subgraph", "compose_answer")
    graph.add_edge("plan_execute_subgraph", "compose_answer")
    graph.add_edge("compose_answer", "persist_session")
    graph.add_edge("persist_session", "emit_final")
    graph.add_edge("emit_final", END)
    return graph.compile(checkpointer=checkpointer)



def create_workflow_runner(
    services: WorkflowServices,
    prefer_langgraph: bool = True,
    workflow_version: str = "learn-agent/v1",
    checkpointer: object | None = None,
):
    if prefer_langgraph and LANGGRAPH_AVAILABLE:
        return LangGraphWorkflowRunner(
            services=services,
            workflow_version=workflow_version,
            checkpointer=checkpointer,
        )
    return SequentialWorkflowRunner(services=services, workflow_version=workflow_version)
