from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from learning_agent_service.local_life.debug_retrieve import _format_pack
from learning_agent_service.rag.local_life_retrieval import LocalLifeEvidencePack, ParentEvidence, RetrievedChunk


class LocalLifeDebugRetrieveTestCase(unittest.TestCase):
    def test_format_pack_includes_route_business_facts_and_score_breakdown(self) -> None:
        chunk = RetrievedChunk(
            point_id="point-1",
            chunk_id="chunk-1",
            parent_id="shop:1001",
            chunk_role="merchant_scene_fit",
            source_type="merchant_scene_fit",
            title="适合约会",
            text="环境安静，适合约会。",
            score=0.96,
            payload={"chunk_id": "chunk-1"},
        )
        pack = LocalLifeEvidencePack(
            query="朝阳公园附近适合约会的家常菜",
            filters={"city": "北京"},
            parent_evidences=[
                ParentEvidence(
                    parent_id="shop:1001",
                    parent_title="湖畔私房菜",
                    entity_type="shop",
                    entity_id="shop:1001",
                    shop_id=1001,
                    shop_name="湖畔私房菜",
                    city="北京",
                    area="朝阳",
                    category="家常菜",
                    parent_score=0.92,
                    matched_chunks=[chunk],
                    sibling_chunks=[],
                    role_coverage=["merchant_scene_fit"],
                    score_breakdown={"semantic_parent_score": 0.88, "business_filter_match_score": 1.0},
                    business_facts={"shop_id": 1001, "city": "北京", "area": "朝阳", "category": "家常菜"},
                    debug_info={"semantic_parent_score": 0.88, "business_filter_match_score": 1.0},
                )
            ],
            total_child_hits=1,
            retrieval_strategy="business_candidates->parent_child_rag->shop_rerank",
            route="structured_first",
            route_reason="structured_filters",
        )

        text = _format_pack(pack)

        self.assertIn("route: structured_first", text)
        self.assertIn("retrieval_strategy: business_candidates->parent_child_rag->shop_rerank", text)
        self.assertIn("business facts:", text)
        self.assertIn("score breakdown:", text)
        self.assertIn("semantic evidence:", text)
        self.assertIn("parent_id=shop:1001", text)


if __name__ == "__main__":
    unittest.main()
