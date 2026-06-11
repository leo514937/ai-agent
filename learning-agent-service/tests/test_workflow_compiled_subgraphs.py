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
    build_rag_graph,
    build_recommendation_graph,
    build_plan_execute_graph,
    build_tool_graph,
    describe_langgraph_topology,
    describe_rag_graph_topology,
    describe_recommendation_graph_topology,
    describe_plan_execute_graph_topology,
    describe_tool_graph_topology,
    export_rag_graph_mermaid,
    export_recommendation_graph_mermaid,
    export_plan_execute_graph_mermaid,
    export_tool_graph_mermaid,
)
from learning_agent_service.application.workflow.services import PlanExecuteSubgraphServices, WorkflowServices


class WorkflowCompiledSubgraphTestCase(unittest.TestCase):
    def test_graph_topologies_are_described(self) -> None:
        main_topology = describe_langgraph_topology()
        rag_topology = describe_rag_graph_topology()
        plan_topology = describe_plan_execute_graph_topology()
        tool_topology = describe_tool_graph_topology()
        recommendation_topology = describe_recommendation_graph_topology()

        self.assertEqual(main_topology["entry_point"], "load_context")
        self.assertIn("request_legality", main_topology["nodes"])
        self.assertIn("query_safety", main_topology["nodes"])
        self.assertIn("top_level_intent_router", main_topology["nodes"])
        self.assertIn("identity_answer", main_topology["nodes"])
        self.assertIn("capability_answer", main_topology["nodes"])
        self.assertIn("direct_chat_answer", main_topology["nodes"])
        self.assertIn("out_of_scope_response", main_topology["nodes"])
        self.assertIn("hard_guard", main_topology["nodes"])
        self.assertIn("clarification_or_reject", main_topology["nodes"])
        self.assertIn("resolve_target_shop", main_topology["nodes"])
        self.assertIn("build_answer_contract", main_topology["nodes"])
        self.assertIn("build_source_contract", main_topology["nodes"])
        self.assertIn("complexity_router", main_topology["nodes"])
        self.assertIn("clarification_node", main_topology["nodes"])
        self.assertIn("direct_executor", main_topology["nodes"])
        self.assertIn("rule_review", main_topology["nodes"])
        self.assertIn("workflow_executor", main_topology["nodes"])
        self.assertIn("select_required_sources", main_topology["nodes"])
        self.assertIn("planner_node", main_topology["nodes"])
        self.assertIn("final_answer_safety", main_topology["nodes"])
        self.assertIn("final_answer", main_topology["nodes"])
        self.assertNotIn("compose_answer", main_topology["nodes"])
        self.assertNotIn("rag_subgraph", main_topology["nodes"])
        self.assertNotIn("recommendation_subgraph", main_topology["nodes"])
        self.assertIn(("load_context", "request_legality"), main_topology["edges"])
        self.assertIn(("request_legality", "hard_guard"), main_topology["edges"])
        self.assertIn(("hard_guard", "query_safety"), main_topology["edges"])
        self.assertIn(("query_safety", "query_merge_for_local_life"), main_topology["edges"])
        self.assertIn(("top_level_intent_router", "understand_turn"), main_topology["edges"])
        self.assertIn(("understand_turn", "resolve_target_shop"), main_topology["edges"])
        self.assertIn(("resolve_target_shop", "build_answer_contract"), main_topology["edges"])
        self.assertIn(("build_answer_contract", "build_source_contract"), main_topology["edges"])
        self.assertIn(("build_source_contract", "complexity_router"), main_topology["edges"])
        self.assertIn(("complexity_router", "workflow_executor"), main_topology["edges"])
        self.assertIn(("complexity_router", "direct_executor"), main_topology["edges"])
        self.assertIn(("direct_executor", "rule_review"), main_topology["edges"])
        self.assertIn(("rule_review", "final_answer"), main_topology["edges"])
        self.assertIn(("select_required_sources", "planner_node"), main_topology["edges"])
        self.assertIn(("planner_node", "plan_validator"), main_topology["edges"])
        self.assertIn(("complex_review", "merge_or_rank"), main_topology["edges"])
        self.assertIn(("contract_review", "final_answer"), main_topology["edges"])
        self.assertIn(("final_answer", "final_answer_safety"), main_topology["edges"])
        self.assertIn(("final_with_limitations", "persist_session"), main_topology["edges"])

        self.assertEqual(rag_topology["entry_point"], "build_retrieval_plan")
        self.assertIn("rag_executor", rag_topology["nodes"])
        self.assertIn("filter_rag", rag_topology["nodes"])
        self.assertIn("rerank_rag", rag_topology["nodes"])
        self.assertIn("build_evidence_pack", rag_topology["nodes"])
        self.assertIn(("build_retrieval_plan", "rag_executor"), rag_topology["edges"])
        self.assertIn(("rag_executor", "filter_rag"), rag_topology["edges"])
        self.assertIn(("filter_rag", "rerank_rag"), rag_topology["edges"])
        self.assertIn(("rerank_rag", "build_evidence_pack"), rag_topology["edges"])

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
        self.assertIn(("tool_plan", "tool_executor"), tool_topology["edges"])

        self.assertEqual(recommendation_topology["entry_point"], "prepare_recommendation")
        self.assertIn("recommendation_executor", recommendation_topology["nodes"])
        self.assertIn("finalize_recommendation", recommendation_topology["nodes"])
        self.assertNotIn("analyze_one_shop", recommendation_topology["nodes"])
        self.assertNotIn("reduce_shop_results", recommendation_topology["nodes"])
        self.assertIn(("prepare_recommendation", "recommendation_executor"), recommendation_topology["edges"])
        self.assertIn(("recommendation_executor", "finalize_recommendation"), recommendation_topology["edges"])

        self.assertIn("graph TD", export_rag_graph_mermaid())
        self.assertIn("graph TD", export_plan_execute_graph_mermaid())
        self.assertIn("graph TD", export_tool_graph_mermaid())
        self.assertIn("graph TD", export_recommendation_graph_mermaid())

    def test_builders_fail_closed_without_langgraph(self) -> None:
        services = WorkflowServices()
        rag_graph = build_rag_graph(services.rag_subgraph)
        plan_graph = build_plan_execute_graph(PlanExecuteSubgraphServices())
        tool_graph = build_tool_graph(services.tool_subgraph)
        recommendation_graph = build_recommendation_graph(services.rag_subgraph)

        if LANGGRAPH_AVAILABLE:
            self.assertIsNotNone(rag_graph)
            self.assertIsNotNone(plan_graph)
            self.assertIsNotNone(tool_graph)
            self.assertIsNotNone(recommendation_graph)
            self.assertTrue(hasattr(rag_graph, "invoke"))
            self.assertTrue(hasattr(plan_graph, "invoke"))
            self.assertTrue(hasattr(tool_graph, "invoke"))
            self.assertTrue(hasattr(recommendation_graph, "invoke"))
        else:
            self.assertIsNone(rag_graph)
            self.assertIsNone(plan_graph)
            self.assertIsNone(tool_graph)
            self.assertIsNone(recommendation_graph)


if __name__ == "__main__":
    unittest.main()
