from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

LOCAL_LIFE_TESTS_DIR = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = TESTS_DIR.parent
SRC_ROOT = PROJECT_ROOT / "src"
for candidate in (str(LOCAL_LIFE_TESTS_DIR), str(TESTS_DIR), str(PROJECT_ROOT), str(SRC_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import _bootstrap  # noqa: F401

from learning_agent_service.rag.models import KnowledgeChunk, RetrievalPlan
from learning_agent_service.rag.retrieval import (
    HeuristicDenseRetriever,
    HeuristicMetadataRetriever,
    HeuristicReranker,
    HybridRetrieverService,
    LocalBM25SparseRetriever,
    ParentChildResolver,
    ReciprocalRankFusion,
)


def _chunk(
    chunk_id: str,
    *,
    document_id: str,
    text: str,
    title: str,
    parent_id: str | None = None,
    chunk_level: str = "child",
    chunk_role: str = "merchant_scene_fit",
    shop_id: int = 5,
    shop_name: str = "海底捞水晶城店",
    business_area: str = "水晶城",
    scene_tags: tuple[str, ...] = ("约会", "环境"),
) -> KnowledgeChunk:
    return KnowledgeChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        text=text,
        title=title,
        chunk_level=chunk_level,
        parent_id=parent_id or f"parent-{shop_id}",
        parent_title=shop_name,
        parent_chunk_id=parent_id or f"parent-{shop_id}",
        chunk_role=chunk_role,
        entity_type="shop",
        entity_id=str(shop_id),
        category="火锅",
        subcategory="火锅",
        source_type=chunk_role,
        chunk_type=chunk_role,
        version="local-life-v1",
        is_latest=True,
        is_active=True,
        tags=scene_tags,
        metadata={
            "shop_id": shop_id,
            "shop_name": shop_name,
            "business_area": business_area,
            "scene_tags": list(scene_tags),
            "facet": chunk_role,
            "chunk_role": chunk_role,
            "parent_id": parent_id or f"parent-{shop_id}",
            "parent_title": shop_name,
            "parent_chunk_id": parent_id or f"parent-{shop_id}",
            "entity_type": "shop",
            "entity_id": str(shop_id),
            "city": "北京",
            "area": business_area,
            "version": "local-life-v1",
            "is_latest": True,
            "is_active": True,
        },
    )


class HybridRetrievalFusionTestCase(unittest.TestCase):
    def test_dense_sparse_metadata_fuse_into_ranked_parent_hits(self) -> None:
        parent = _chunk(
            "parent-5",
            document_id="doc-parent-5",
            text="海底捞水晶城店整体信息。",
            title="海底捞水晶城店",
            chunk_level="parent",
            chunk_role="merchant_profile",
        )
        scene = _chunk(
            "scene-5",
            document_id="doc-scene-5",
            text="环境安静，适合约会。",
            title="适合场景",
            parent_id=parent.chunk_id,
            chunk_role="merchant_scene_fit",
            scene_tags=("约会", "安静"),
        )
        coupon = _chunk(
            "coupon-5",
            document_id="doc-coupon-5",
            text="当前有券，可参考。",
            title="优惠券",
            parent_id=parent.chunk_id,
            chunk_role="package_description",
            scene_tags=("优惠", "券"),
        )
        other = _chunk(
            "scene-9",
            document_id="doc-scene-9",
            text="适合家庭聚餐。",
            title="适合家庭",
            parent_id="parent-9",
            chunk_role="merchant_scene_fit",
            shop_id=9,
            shop_name="新白鹿运河上街店",
            business_area="运河上街",
            scene_tags=("家庭", "聚餐"),
        )

        chunks = (parent, scene, coupon, other)
        resolver = ParentChildResolver(chunks)
        dense = HeuristicDenseRetriever(chunks, resolver)
        sparse = LocalBM25SparseRetriever(chunks, resolver)
        metadata = HeuristicMetadataRetriever(chunks, resolver)
        reranker = HeuristicReranker()
        service = HybridRetrieverService(
            dense_retriever=dense,
            sparse_retriever=sparse,
            metadata_retriever=metadata,
            reranker=reranker,
            config=SimpleNamespace(dense_top_k=10, sparse_top_k=10, metadata_top_k=10, fusion_top_k=10, rerank_top_k=5),
            fusion=ReciprocalRankFusion(),
            parent_child_resolver=resolver,
        )

        result = service.retrieve(
            RetrievalPlan(
                semantic_query="海底捞水晶城店 约会 有券",
                keyword_query="海底捞 水晶城 约会 有券",
                extra={"raw_query": "海底捞水晶城店 约会 有券"},
            )
        )

        self.assertTrue(result.hits)
        self.assertIsNotNone(result.debug_trace)
        self.assertEqual(result.debug_trace.extra["retrieval_strategy"], "dense+sparse+metadata->rrf->rerank")
        self.assertEqual(result.debug_trace.retrieval_mode, "normal")
        self.assertEqual(result.debug_trace.extra["retrieval_mode"], "normal")
        self.assertGreaterEqual(result.debug_trace.kept_count, 1)
        self.assertGreaterEqual(result.debug_trace.rejected_count, 0)
        self.assertEqual(result.debug_trace.extra["kept_count"], result.debug_trace.kept_count)
        self.assertEqual(result.debug_trace.extra["route_hit_counts"]["dense"], len(result.debug_trace.dense_hits))
        self.assertIn("dense", result.debug_trace.extra["working_routes"])
        self.assertIn("sparse", result.debug_trace.extra["working_routes"])
        self.assertIn("metadata", result.debug_trace.extra["working_routes"])
        self.assertGreaterEqual(len({hit.chunk.metadata.get("shop_id") for hit in result.hits if hit.chunk.metadata.get("shop_id") is not None}), 1)


if __name__ == "__main__":
    unittest.main()
