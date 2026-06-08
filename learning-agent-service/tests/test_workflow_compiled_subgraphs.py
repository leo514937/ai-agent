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
from learning_agent_service.application.workflow.services import WorkflowServices


class WorkflowCompiledSubgraphTestCase(unittest.TestCase):
    def test_graph_topologies_are_described(self) -> None:
        main_topology = describe_langgraph_topology()
        rag_topology = describe_rag_graph_topology()
        plan_topology = describe_plan_execute_graph_topology()
        tool_topology = describe_tool_graph_topology()
        recommendation_topology = describe_recommendation_graph_topology()

        self.assertEqual(main_topology["entry_point"], "load_context")
        self.assertIn("rule_review", main_topology["nodes"])
        self.assertIn("merge_rank_node", main_topology["nodes"])
        self.assertIn("contract_review", main_topology["nodes"])

        self.assertEqual(rag_topology["entry_point"], "build_retrieval_plan")
        self.assertIn("recall_rag", rag_topology["nodes"])
        self.assertIn("filter_rag", rag_topology["nodes"])
        self.assertIn("rerank_rag", rag_topology["nodes"])
        self.assertIn("build_evidence_pack", rag_topology["nodes"])
        self.assertIn(("recall_rag", "filter_rag"), rag_topology["edges"])
        self.assertIn(("filter_rag", "rerank_rag"), rag_topology["edges"])
        self.assertIn(("rerank_rag", "build_evidence_pack"), rag_topology["edges"])

        self.assertEqual(plan_topology["entry_point"], "planner_node")
        self.assertIn("planner_node", plan_topology["nodes"])
        self.assertIn("plan_executor", plan_topology["nodes"])
        self.assertIn("collect_step_result", plan_topology["nodes"])
        self.assertIn("complex_review", plan_topology["nodes"])
        self.assertIn(("planner_node", "plan_executor"), plan_topology["edges"])
        self.assertIn(("plan_executor", "collect_step_result"), plan_topology["edges"])
        self.assertIn(("collect_step_result", "complex_review"), plan_topology["edges"])

        self.assertEqual(tool_topology["entry_point"], "tool_plan")
        self.assertIn("execute_tool_pipeline", tool_topology["nodes"])
        self.assertIn(("tool_plan", "execute_tool_pipeline"), tool_topology["edges"])

        self.assertEqual(recommendation_topology["entry_point"], "prepare_recommendation")
        self.assertIn("dispatch_shop_analysis", recommendation_topology["nodes"])
        self.assertIn("analyze_one_shop", recommendation_topology["nodes"])
        self.assertIn("reduce_shop_results", recommendation_topology["nodes"])
        self.assertIn(("prepare_recommendation", "dispatch_shop_analysis"), recommendation_topology["edges"])
        self.assertIn(("dispatch_shop_analysis", "analyze_one_shop"), recommendation_topology["edges"])
        self.assertIn(("analyze_one_shop", "reduce_shop_results"), recommendation_topology["edges"])
        self.assertIn(("reduce_shop_results", "finalize_recommendation"), recommendation_topology["edges"])

        self.assertIn("graph TD", export_rag_graph_mermaid())
        self.assertIn("graph TD", export_plan_execute_graph_mermaid())
        self.assertIn("graph TD", export_tool_graph_mermaid())
        self.assertIn("graph TD", export_recommendation_graph_mermaid())

    def test_builders_fail_closed_without_langgraph(self) -> None:
        services = WorkflowServices()
        rag_graph = build_rag_graph(services.rag_subgraph)
        plan_graph = build_plan_execute_graph(services.plan_execute_subgraph)
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
