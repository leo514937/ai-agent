from __future__ import annotations

from .runner import SequentialWorkflowRunner
from .services import WorkflowServices
from .subgraphs import (
    run_plan_execute_subgraph,
    run_rag_subgraph,
    run_tool_subgraph,
    run_understand_turn,
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


class LangGraphWorkflowRunner(SequentialWorkflowRunner):
    def __init__(
        self,
        services: WorkflowServices,
        workflow_version: str = "learn-agent/v1",
        checkpointer: object | None = None,
    ) -> None:
        super().__init__(services=services, workflow_version=workflow_version)
        self._graph = _build_langgraph_runner(services, checkpointer=checkpointer)

    def run_state(self, state):
        if self._is_terminal(state):
            return self._finalize_terminal(state)

        try:
            result = self._graph.invoke(state, config=_build_graph_config(state))
        except Exception as exc:
            result = self._record_unexpected_error(state, "langgraph.invoke", exc)

        runtime = result["runtime"]
        if runtime.emitted_events:
            if runtime.terminal_event is None:
                default_terminal = TerminalEvent.ERROR if runtime.errors else TerminalEvent.FINAL
                result["runtime"] = runtime.model_copy(update={"terminal_event": default_terminal})
            return result

        if result["runtime"].terminal_event == TerminalEvent.ERROR:
            return self._finalize_terminal(result)
        return self._finalize_terminal(result, default_terminal=TerminalEvent.FINAL)


def _build_graph_config(state):
    runtime = state["runtime"]
    return {"configurable": {"thread_id": runtime.session_id}}


def _build_langgraph_runner(services: WorkflowServices, checkpointer: object | None = None):
    if not LANGGRAPH_AVAILABLE:
        raise RuntimeError("langgraph is not installed")

    graph = StateGraph(dict)
    graph.add_node("load_context", services.load_context)
    graph.add_node("understand_turn", lambda state: run_understand_turn(state, services.understand_turn))
    graph.add_node(
        "plan_execute_subgraph",
        lambda state: run_plan_execute_subgraph(state, services.plan_execute_subgraph),
    )
    graph.add_node("rag_subgraph", lambda state: run_rag_subgraph(state, services.rag_subgraph))
    graph.add_node("tool_subgraph", lambda state: run_tool_subgraph(state, services.tool_subgraph))
    graph.add_node("compose_answer", services.compose_answer)
    graph.add_node("persist_session", services.persist_session)
    graph.add_node("emit_final", services.emit_final)

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
            "rag_subgraph": "rag_subgraph",
            "tool_subgraph": "tool_subgraph",
            "compose_answer": "compose_answer",
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
