from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TopologyEdge:
    source: str
    target: str
    label: str | None = None


@dataclass(frozen=True)
class GraphTopology:
    entry_point: str
    terminal: str
    nodes: tuple[str, ...]
    edges: tuple[TopologyEdge, ...]


_MAIN_GRAPH_NODES = (
    "load_context",
    "request_legality",
    "illegal_request_response",
    "hard_guard",
    "clarification_or_reject",
    "query_safety",
    "safety_reject_response",
    "query_merge_for_local_life",
    "merged_query_safety",
    "understand_turn",
    "top_level_intent_router",
    "identity_answer",
    "capability_answer",
    "direct_chat_answer",
    "out_of_scope_response",
    "resolve_target_shop",
    "clarification_node",
    "build_answer_contract",
    "build_source_contract",
    "complexity_router",
    "direct_executor",
    "rule_review",
    "workflow_executor",
    "select_required_sources",
    "rag_executor",
    "tool_executor",
    "recommendation_executor",
    "merge_or_rank",
    "contract_review",
    "planner_node",
    "plan_validator",
    "plan_executor",
    "execute_plan_step",
    "rag_executor_complex",
    "tool_executor_complex",
    "recommendation_executor_complex",
    "rank_executor",
    "merge_executor",
    "compose_draft",
    "collect_step_result",
    "all_steps_done?",
    "complex_review",
    "final_answer",
    "final_answer_safety",
    "final_safety_fallback",
    "repair_answer",
    "final_with_limitations",
    "response_builder",
    "persist_session",
    "emit_final",
)

_MAIN_GRAPH_EDGES = (
    TopologyEdge("START", "load_context"),
    TopologyEdge("load_context", "request_legality"),
    TopologyEdge("request_legality", "illegal_request_response", "blocked"),
    TopologyEdge("request_legality", "hard_guard", "normal"),
    TopologyEdge("illegal_request_response", "final_answer"),
    TopologyEdge("hard_guard", "clarification_or_reject", "invalid / low_info"),
    TopologyEdge("hard_guard", "query_safety", "valid"),
    TopologyEdge("clarification_or_reject", "final_answer"),
    TopologyEdge("query_safety", "safety_reject_response", "unsafe"),
    TopologyEdge("query_safety", "query_merge_for_local_life", "safe"),
    TopologyEdge("safety_reject_response", "final_answer"),
    TopologyEdge("query_merge_for_local_life", "merged_query_safety"),
    TopologyEdge("merged_query_safety", "safety_reject_response", "unsafe"),
    TopologyEdge("merged_query_safety", "understand_turn", "safe"),
    TopologyEdge("understand_turn", "top_level_intent_router"),
    TopologyEdge("top_level_intent_router", "identity_answer", "identity"),
    TopologyEdge("top_level_intent_router", "capability_answer", "capability"),
    TopologyEdge("top_level_intent_router", "direct_chat_answer", "direct_chat"),
    TopologyEdge("top_level_intent_router", "out_of_scope_response", "out_of_scope"),
    TopologyEdge("top_level_intent_router", "safety_reject_response", "unsafe"),
    TopologyEdge("top_level_intent_router", "final_answer", "direct_answer_fallback"),
    TopologyEdge(
        "top_level_intent_router",
        "resolve_target_shop",
        "local_life / recommendation / comparison / planning",
    ),
    TopologyEdge("identity_answer", "final_answer"),
    TopologyEdge("capability_answer", "final_answer"),
    TopologyEdge("direct_chat_answer", "final_answer"),
    TopologyEdge("out_of_scope_response", "final_answer"),
    TopologyEdge("resolve_target_shop", "clarification_node", "missing_target"),
    TopologyEdge("resolve_target_shop", "build_answer_contract", "resolved"),
    TopologyEdge("clarification_node", "final_answer"),
    TopologyEdge("build_answer_contract", "build_source_contract"),
    TopologyEdge("build_source_contract", "complexity_router"),
    TopologyEdge("complexity_router", "clarification_node", "clarify"),
    TopologyEdge("complexity_router", "direct_executor", "simple"),
    TopologyEdge("complexity_router", "workflow_executor", "standard"),
    TopologyEdge("complexity_router", "planner_node", "complex"),
    TopologyEdge("direct_executor", "rule_review"),
    TopologyEdge("rule_review", "final_answer", "pass"),
    TopologyEdge("rule_review", "repair_answer", "repair_answer"),
    TopologyEdge("rule_review", "final_with_limitations", "degrade"),
    TopologyEdge("workflow_executor", "select_required_sources"),
    TopologyEdge("select_required_sources", "rag_executor", "need_rag"),
    TopologyEdge("select_required_sources", "tool_executor", "need_tool"),
    TopologyEdge("select_required_sources", "recommendation_executor", "need_recommendation"),
    TopologyEdge("rag_executor", "merge_or_rank"),
    TopologyEdge("tool_executor", "merge_or_rank"),
    TopologyEdge("recommendation_executor", "merge_or_rank"),
    TopologyEdge("merge_or_rank", "contract_review"),
    TopologyEdge("contract_review", "final_answer", "pass"),
    TopologyEdge("contract_review", "repair_answer", "repair_answer"),
    TopologyEdge("contract_review", "rag_executor", "retry_rag"),
    TopologyEdge("contract_review", "tool_executor", "retry_tool"),
    TopologyEdge("contract_review", "final_with_limitations", "degrade"),
    TopologyEdge("planner_node", "plan_validator"),
    TopologyEdge("plan_validator", "plan_executor"),
    TopologyEdge("plan_executor", "execute_plan_step"),
    TopologyEdge("execute_plan_step", "rag_executor_complex", "rag_step"),
    TopologyEdge("execute_plan_step", "tool_executor_complex", "tool_step"),
    TopologyEdge("execute_plan_step", "recommendation_executor_complex", "recommendation_step"),
    TopologyEdge("execute_plan_step", "rank_executor", "rank_step"),
    TopologyEdge("execute_plan_step", "merge_executor", "merge_step"),
    TopologyEdge("execute_plan_step", "compose_draft", "compose_step"),
    TopologyEdge("rag_executor_complex", "collect_step_result"),
    TopologyEdge("tool_executor_complex", "collect_step_result"),
    TopologyEdge("recommendation_executor_complex", "collect_step_result"),
    TopologyEdge("rank_executor", "collect_step_result"),
    TopologyEdge("merge_executor", "collect_step_result"),
    TopologyEdge("compose_draft", "collect_step_result"),
    TopologyEdge("collect_step_result", "all_steps_done?"),
    TopologyEdge("all_steps_done?", "execute_plan_step", "no"),
    TopologyEdge("all_steps_done?", "complex_review", "yes"),
    TopologyEdge("complex_review", "final_answer", "pass"),
    TopologyEdge("complex_review", "repair_answer", "repair_answer"),
    TopologyEdge("complex_review", "execute_plan_step", "retry_step"),
    TopologyEdge("complex_review", "planner_node", "replan"),
    TopologyEdge("complex_review", "final_with_limitations", "degrade"),
    TopologyEdge("repair_answer", "final_answer"),
    TopologyEdge("final_with_limitations", "final_answer"),
    TopologyEdge("final_answer", "final_answer_safety"),
    TopologyEdge("final_answer_safety", "final_safety_fallback", "unsafe"),
    TopologyEdge("final_answer_safety", "response_builder", "safe"),
    TopologyEdge("final_safety_fallback", "response_builder"),
    TopologyEdge("response_builder", "persist_session"),
    TopologyEdge("persist_session", "emit_final"),
    TopologyEdge("emit_final", "END"),
)

MAIN_GRAPH_TOPOLOGY = GraphTopology(
    entry_point="load_context",
    terminal="END",
    nodes=_MAIN_GRAPH_NODES,
    edges=_MAIN_GRAPH_EDGES,
)


def describe_langgraph_topology() -> dict[str, Any]:
    return {
        "entry_point": MAIN_GRAPH_TOPOLOGY.entry_point,
        "terminal": MAIN_GRAPH_TOPOLOGY.terminal,
        "nodes": list(MAIN_GRAPH_TOPOLOGY.nodes),
        "edges": [
            {"source": edge.source, "target": edge.target, "label": edge.label}
            for edge in MAIN_GRAPH_TOPOLOGY.edges
        ],
    }


def export_langgraph_mermaid() -> str:
    lines = ["graph TD"]
    for edge in MAIN_GRAPH_TOPOLOGY.edges:
        if edge.label:
            lines.append(f"  {edge.source} -->|{edge.label}| {edge.target}")
        else:
            lines.append(f"  {edge.source} --> {edge.target}")
    return "\n".join(lines)
