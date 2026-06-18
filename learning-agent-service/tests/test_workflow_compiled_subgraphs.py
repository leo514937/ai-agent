import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent
SRC_ROOT = PROJECT_ROOT / "src"
for candidate in (str(TESTS_DIR), str(PROJECT_ROOT), str(SRC_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import _bootstrap  # noqa: F401

from learning_agent_service.application.workflow.graphs import (
    LANGGRAPH_AVAILABLE,
    build_evidence_graph,
    build_recommendation_graph,
    build_plan_execute_graph,
    build_tool_graph,
    describe_langgraph_topology,
    describe_evidence_graph_topology,
    describe_understand_turn_graph_topology,
    describe_recommendation_graph_topology,
    describe_plan_execute_graph_topology,
    describe_tool_graph_topology,
    export_evidence_graph_mermaid,
    export_recommendation_graph_mermaid,
    export_plan_execute_graph_mermaid,
    export_tool_graph_mermaid,
)
from learning_agent_service.application.workflow.builder import _merged_query_safety_route
from learning_agent_service.domain import ChatTurnCommand, PersistentSessionContext, build_initial_state
from learning_agent_service.application.workflow.services import PlanExecuteSubgraphServices, WorkflowServices


class WorkflowCompiledSubgraphTestCase(unittest.TestCase):
    def test_graph_topologies_are_described(self) -> None:
        main_topology = describe_langgraph_topology()
        evidence_topology = describe_evidence_graph_topology()
        plan_topology = describe_plan_execute_graph_topology()
        tool_topology = describe_tool_graph_topology()
        recommendation_topology = describe_recommendation_graph_topology()

        self.assertEqual(main_topology["entry_point"], "load_context")
        self.assertIn("request_legality", main_topology["nodes"])
        self.assertIn("query_safety", main_topology["nodes"])
        self.assertIn("top_level_intent_router", main_topology["nodes"])
        self.assertIn("query_merge_for_local_life", main_topology["nodes"])
        self.assertIn("target_requirement_router", main_topology["nodes"])
        self.assertIn("identity_answer", main_topology["nodes"])
        self.assertIn("capability_answer", main_topology["nodes"])
        self.assertIn("direct_chat_answer", main_topology["nodes"])
        self.assertIn("out_of_scope_response", main_topology["nodes"])
        self.assertIn("hard_guard", main_topology["nodes"])
        self.assertIn("clarification_or_reject", main_topology["nodes"])
        self.assertIn("resolve_target_shop", main_topology["nodes"])
        self.assertIn("resolve_comparison_targets", main_topology["nodes"])
        self.assertIn("prepare_recommendation_context", main_topology["nodes"])
        self.assertIn("build_answer_contract", main_topology["nodes"])
        self.assertIn("build_source_contract", main_topology["nodes"])
        self.assertIn("complexity_router", main_topology["nodes"])
        self.assertIn("clarification_node", main_topology["nodes"])
        self.assertIn("direct_executor", main_topology["nodes"])
        self.assertIn("rule_review", main_topology["nodes"])
        self.assertIn("workflow_executor", main_topology["nodes"])
        self.assertIn("select_required_sources", main_topology["nodes"])
        self.assertIn("source_dispatch", main_topology["nodes"])
        self.assertIn("planner_node", main_topology["nodes"])
        self.assertIn("final_answer_safety", main_topology["nodes"])
        self.assertIn("final_answer", main_topology["nodes"])
        self.assertNotIn("compose_answer", main_topology["nodes"])
        self.assertNotIn("rag_subgraph", main_topology["nodes"])
        self.assertNotIn("recommendation_subgraph", main_topology["nodes"])
        self.assertNotIn("rag_executor", main_topology["nodes"])
        self.assertNotIn("rag_executor_complex", main_topology["nodes"])
        self.assertNotIn("tool_executor_complex", main_topology["nodes"])
        self.assertNotIn("recommendation_executor_complex", main_topology["nodes"])
        self.assertNotIn("rag_gate", main_topology["nodes"])
        self.assertIn(("load_context", "request_legality"), main_topology["edges"])
        self.assertIn(("request_legality", "hard_guard"), main_topology["edges"])
        self.assertIn(("hard_guard", "query_safety"), main_topology["edges"])
        self.assertIn(("query_safety", "understand_turn"), main_topology["edges"])
        self.assertIn(("understand_turn", "top_level_intent_router"), main_topology["edges"])
        self.assertIn(("top_level_intent_router", "query_merge_for_local_life"), main_topology["edges"])
        self.assertIn(("query_merge_for_local_life", "merged_query_safety"), main_topology["edges"])
        self.assertIn(("merged_query_safety", "build_answer_contract"), main_topology["edges"])
        self.assertIn(("build_answer_contract", "target_requirement_router"), main_topology["edges"])
        self.assertIn(("target_requirement_router", "resolve_target_shop"), main_topology["edges"])
        self.assertIn(("target_requirement_router", "resolve_comparison_targets"), main_topology["edges"])
        self.assertIn(("target_requirement_router", "prepare_recommendation_context"), main_topology["edges"])
        self.assertIn(("target_requirement_router", "clarification_node"), main_topology["edges"])
        self.assertIn(("resolve_comparison_targets", "build_source_contract"), main_topology["edges"])
        self.assertIn(("prepare_recommendation_context", "build_source_contract"), main_topology["edges"])
        self.assertIn(("resolve_target_shop", "build_source_contract"), main_topology["edges"])
        self.assertIn(("build_source_contract", "complexity_router"), main_topology["edges"])
        self.assertIn(("complexity_router", "workflow_executor"), main_topology["edges"])
        self.assertIn(("complexity_router", "direct_executor"), main_topology["edges"])
        self.assertIn(("direct_executor", "rule_review"), main_topology["edges"])
        self.assertIn(("rule_review", "final_answer"), main_topology["edges"])
        self.assertIn(("workflow_executor", "select_required_sources"), main_topology["edges"])
        self.assertIn(("select_required_sources", "source_dispatch"), main_topology["edges"])
        self.assertIn(("source_dispatch", "tool_executor"), main_topology["edges"])
        self.assertIn(("source_dispatch", "recommendation_executor"), main_topology["edges"])
        self.assertIn(("tool_executor", "source_dispatch"), main_topology["edges"])
        self.assertIn(("recommendation_executor", "source_dispatch"), main_topology["edges"])
        self.assertIn(("source_dispatch", "merge_or_rank"), main_topology["edges"])
        self.assertIn(("prepare_retry", "workflow_executor"), main_topology["edges"])
        self.assertIn(("planner_node", "plan_validator"), main_topology["edges"])
        self.assertIn(("complex_review", "final_with_limitations"), main_topology["edges"])
        self.assertIn(("contract_review", "final_answer"), main_topology["edges"])
        self.assertIn(("final_answer", "final_answer_safety"), main_topology["edges"])
        self.assertIn(("final_with_limitations", "final_answer"), main_topology["edges"])

        self.assertEqual(evidence_topology["entry_point"], "build_evidence_plan")
        self.assertIn("collect_evidence", evidence_topology["nodes"])
        self.assertIn("filter_evidence", evidence_topology["nodes"])
        self.assertIn("rank_evidence", evidence_topology["nodes"])
        self.assertIn("build_evidence_pack", evidence_topology["nodes"])
        self.assertNotIn("rag_gate", describe_understand_turn_graph_topology()["nodes"])
        self.assertIn(("build_evidence_plan", "collect_evidence"), evidence_topology["edges"])
        self.assertIn(("collect_evidence", "filter_evidence"), evidence_topology["edges"])
        self.assertIn(("filter_evidence", "rank_evidence"), evidence_topology["edges"])
        self.assertIn(("rank_evidence", "build_evidence_pack"), evidence_topology["edges"])

        self.assertEqual(plan_topology["entry_point"], "planner_node")
        self.assertIn("planner_node", plan_topology["nodes"])
        self.assertIn("plan_validator", plan_topology["nodes"])
        self.assertIn("plan_executor", plan_topology["nodes"])
        self.assertIn("execute_plan_step", plan_topology["nodes"])
        self.assertIn("collect_step_result", plan_topology["nodes"])
        self.assertIn("complex_review", plan_topology["nodes"])
        self.assertIn(("planner_node", "plan_validator"), plan_topology["edges"])
        self.assertIn(("plan_validator", "plan_executor"), plan_topology["edges"])
        self.assertIn(("plan_executor", "execute_plan_step"), plan_topology["edges"])
        self.assertIn(("execute_plan_step", "collect_step_result"), plan_topology["edges"])
        self.assertIn(("collect_step_result", "complex_review"), plan_topology["edges"])

        self.assertEqual(tool_topology["entry_point"], "tool_plan")
        self.assertIn("tool_executor", tool_topology["nodes"])
        self.assertIn("finalize_tool", tool_topology["nodes"])
        self.assertIn(("tool_plan", "tool_executor"), tool_topology["edges"])

        self.assertEqual(recommendation_topology["entry_point"], "prepare_recommendation")
        self.assertIn("dispatch_shop_analysis", recommendation_topology["nodes"])
        self.assertIn("analyze_one_shop", recommendation_topology["nodes"])
        self.assertIn("reduce_shop_results", recommendation_topology["nodes"])
        self.assertIn("finalize_recommendation", recommendation_topology["nodes"])
        self.assertIn(("prepare_recommendation", "dispatch_shop_analysis"), recommendation_topology["edges"])
        self.assertIn(("dispatch_shop_analysis", "analyze_one_shop"), recommendation_topology["edges"])
        self.assertIn(("analyze_one_shop", "reduce_shop_results"), recommendation_topology["edges"])
        self.assertIn(("reduce_shop_results", "finalize_recommendation"), recommendation_topology["edges"])

        self.assertIn("graph TD", export_evidence_graph_mermaid())
        self.assertIn("graph TD", export_plan_execute_graph_mermaid())
        self.assertIn("graph TD", export_tool_graph_mermaid())
        self.assertIn("graph TD", export_recommendation_graph_mermaid())

    def test_builders_fail_closed_without_langgraph(self) -> None:
        services = WorkflowServices()
        evidence_graph = build_evidence_graph(services.evidence_subgraph)
        plan_graph = build_plan_execute_graph(PlanExecuteSubgraphServices())
        tool_graph = build_tool_graph(services.tool_subgraph)
        recommendation_graph = build_recommendation_graph(services.evidence_subgraph)

        if LANGGRAPH_AVAILABLE:
            self.assertIsNotNone(evidence_graph)
            self.assertIsNotNone(plan_graph)
            self.assertIsNotNone(tool_graph)
            self.assertIsNotNone(recommendation_graph)
            self.assertTrue(hasattr(evidence_graph, "invoke"))
            self.assertTrue(hasattr(plan_graph, "invoke"))
            self.assertTrue(hasattr(tool_graph, "invoke"))
            self.assertTrue(hasattr(recommendation_graph, "invoke"))
        else:
            self.assertIsNone(evidence_graph)
            self.assertIsNone(plan_graph)
            self.assertIsNone(tool_graph)
            self.assertIsNone(recommendation_graph)

    def test_merged_query_safety_routes_to_answer_contract_when_safe(self) -> None:
        state = build_initial_state(
            ChatTurnCommand(
                trace_id="trace-route",
                session_id="session-route",
                turn_id="turn-route",
                user_id="user-route",
                message="海底捞水晶城店现在营业吗，有券吗，离我多远？",
            ),
            persistent=PersistentSessionContext(),
        )
        state["turn"] = state["turn"].model_copy(
            update={
                "extra": {
                    **dict(state["turn"].extra),
                    "merged_query_safety": {"blocked": False, "allowed": True},
                }
            }
        )

        self.assertEqual(_merged_query_safety_route(state), "build_answer_contract")


if __name__ == "__main__":
    unittest.main()
