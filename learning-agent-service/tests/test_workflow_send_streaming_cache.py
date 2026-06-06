from __future__ import annotations

import tempfile
import unittest

from learning_agent_service.application.workflow.builder import write_langgraph_visualizations
from learning_agent_service.application.workflow.graphs import export_recommendation_graph_mermaid
from learning_agent_service.application.workflow.services import RagSubgraphServices
from learning_agent_service.application.workflow.subgraphs import run_recommendation_subgraph
from learning_agent_service.domain.contracts import Citation, ChatTurnCommand, EvidenceItem, EvidencePack, RoutingContract
from learning_agent_service.domain.state import build_initial_state


class WorkflowSendStreamingCacheTests(unittest.TestCase):
    def _build_state(self):
        command = ChatTurnCommand(
            trace_id="trace-day7",
            session_id="session-day7",
            turn_id="turn-day7",
            user_id="user-day7",
            message="帮我推荐附近的店",
        )
        state = build_initial_state(command=command, workflow_version="test/v1")
        state["turn"] = state["turn"].model_copy(
            update={
                "routing_contract": RoutingContract(
                    required_action="recommendation",
                    candidate_shop_ids=[11, 22, 33],
                    recommendation_mode=True,
                    rag_allowed=True,
                    tool_allowed=False,
                ),
                "extra": {"candidate_shop_ids": [11, 22, 33]},
            }
        )
        state["runtime_context"]["recommendation_expand_max_rounds"] = 3
        return state

    def test_recommendation_subgraph_reduces_parallel_shop_analyses(self) -> None:
        def hybrid_retrieve(state):
            shop_id = getattr(state["turn"].routing_contract, "target_shop_id", None)
            score = float(shop_id or 0)
            state["turn"] = state["turn"].model_copy(
                update={
                    "evidence_pack": EvidencePack(
                        items=[
                            EvidenceItem(
                                chunk_id=f"chunk-{shop_id}",
                                content=f"shop-{shop_id}",
                                score=score,
                                document_id=str(shop_id),
                                chunk_type="shop",
                                metadata={"shop_id": shop_id},
                            )
                        ],
                        top_scores=[score],
                        evidence_status="OK",
                        extra={"shop_id": shop_id},
                    ),
                    "citations": [
                        Citation(
                            chunk_id=f"chunk-{shop_id}",
                            document_id=str(shop_id),
                            source_type="recommendation",
                            version="v1",
                            score=score,
                            title=f"shop-{shop_id}",
                            locator=None,
                        )
                    ],
                    "extra": {**dict(state["turn"].extra), "target_shop_name": f"shop-{shop_id}"},
                }
            )
            return state

        services = RagSubgraphServices(
            hybrid_retrieve=hybrid_retrieve,
            evaluate_evidence=lambda state: state,
            citation_builder=lambda state: state,
        )
        state = self._build_state()

        updated = run_recommendation_subgraph(state, services)

        self.assertEqual(len(updated["shop_analyses"]), 3)
        self.assertEqual(updated["shop_analyses"][0]["shop_id"], 33)
        self.assertEqual(updated["runtime"].metrics.get("recommendation_shop_count"), 3)
        self.assertEqual(updated["turn"].extra.get("recommendation_top_shop_id"), 33)
        self.assertEqual(updated["turn"].extra.get("recommendation_top_shop_name"), "shop-33")

    def test_recommendation_mermaid_matches_exported_topology(self) -> None:
        mermaid = export_recommendation_graph_mermaid()
        self.assertIn("graph TD", mermaid)
        self.assertIn("prepare_recommendation --> dispatch_shop_analysis", mermaid)
        self.assertIn("analyze_one_shop --> reduce_shop_results", mermaid)

    def test_visualization_files_are_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            written = write_langgraph_visualizations(tmp_dir)
            self.assertIn("main_graph.mmd", written)
            self.assertIn("recommendation_graph.mmd", written)


if __name__ == "__main__":
    unittest.main()
