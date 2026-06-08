from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ...domain.state import GraphState, clone_graph_state


class StateHandler(Protocol):
    def __call__(self, state: GraphState) -> GraphState:
        ...



def passthrough_handler(state: GraphState) -> GraphState:
    return clone_graph_state(state)


@dataclass
class UnderstandTurnServices:
    parse_intent_slots: StateHandler = passthrough_handler
    resolve_reference: StateHandler = passthrough_handler
    ambiguity_check: StateHandler = passthrough_handler
    rag_gate: StateHandler = passthrough_handler
    rewrite_query: StateHandler = passthrough_handler


@dataclass
class RagSubgraphServices:
    hybrid_retrieve: StateHandler = passthrough_handler
    evaluate_evidence: StateHandler = passthrough_handler
    citation_builder: StateHandler = passthrough_handler


@dataclass
class ToolSubgraphServices:
    tool_planner: StateHandler = passthrough_handler
    tool_executor: StateHandler = passthrough_handler
    tool_result_normalizer: StateHandler = passthrough_handler


@dataclass
class WorkflowServices:
    load_context: StateHandler = passthrough_handler
    consume_pending_clarification: StateHandler = passthrough_handler
    conversation_recap_direct_response: StateHandler = passthrough_handler
    understand_turn: UnderstandTurnServices = field(default_factory=UnderstandTurnServices)
    rag_subgraph: RagSubgraphServices = field(default_factory=RagSubgraphServices)
    tool_subgraph: ToolSubgraphServices = field(default_factory=ToolSubgraphServices)
    compose_answer: StateHandler = passthrough_handler
    persist_session: StateHandler = passthrough_handler
    emit_final: StateHandler = passthrough_handler
