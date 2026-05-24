from __future__ import annotations

import unittest
from types import SimpleNamespace

import _bootstrap  # noqa: F401

from learning_agent_service.rag.local_life_retrieval import (
    LOCAL_LIFE_PARENT_CHILD_COLLECTION,
    LocalLifeParentChildRetriever,
    build_arg_parser,
    get_payload_value,
    infer_role_weights,
)


class _FakeEmbeddingAdapter:
    def __init__(self, dimension: int = 4) -> None:
        self.dimension = dimension
        self.calls: list[str] = []

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        return [0.1] * self.dimension


class _FakePoint:
    def __init__(self, *, point_id: str, score: float, payload: dict[str, object]) -> None:
        self.id = point_id
        self.score = score
        self.payload = payload


class _FakeGroup:
    def __init__(self, *, group_id: str, hits: list[_FakePoint]) -> None:
        self.id = group_id
        self.hits = hits


def _payload(
    *,
    chunk_id: str,
    parent_id: str,
    chunk_role: str,
    score_text: str,
    shop_id: int,
    shop_name: str,
    city: str = "北京",
    area: str = "朝阳",
    category: str = "家常菜",
    shop_type_id: int = 1,
    source_type: str = "merchant_review",
    entity_type: str = "shop",
    entity_id: str | None = None,
    chunk_level: str = "child",
    parent_chunk_id: str | None = None,
    version: str = "local-life-v1",
    is_latest: bool = True,
    is_active: bool = True,
    use_metadata_only: bool = False,
) -> dict[str, object]:
    payload = {
        "chunk_id": chunk_id,
        "document_id": f"doc-{chunk_id}",
        "text": score_text,
        "title": f"title-{chunk_id}",
        "source_type": source_type,
        "chunk_role": chunk_role,
        "chunk_level": chunk_level,
        "parent_id": parent_id,
        "parent_title": shop_name,
        "parent_chunk_id": parent_chunk_id or f"{parent_id}:parent-summary",
        "entity_type": entity_type,
        "entity_id": entity_id or parent_id,
        "shop_id": shop_id,
        "shop_name": shop_name,
        "city": city,
        "area": area,
        "subcategory": category,
        "shop_type_id": shop_type_id,
        "version": version,
        "is_latest": is_latest,
        "is_active": is_active,
        "metadata": {
            "parent_id": parent_id,
            "parent_title": shop_name,
            "entity_type": entity_type,
            "entity_id": entity_id or parent_id,
            "chunk_role": chunk_role,
            "chunk_level": chunk_level,
            "parent_chunk_id": parent_chunk_id or f"{parent_id}:parent-summary",
            "shop_id": shop_id,
            "shop_name": shop_name,
            "city": city,
            "area": area,
            "shop_type_id": shop_type_id,
            "version": version,
            "is_latest": is_latest,
            "is_active": is_active,
        },
    }
    if use_metadata_only:
        return {"metadata": payload["metadata"], "chunk_id": chunk_id, "document_id": f"doc-{chunk_id}", "text": score_text, "title": f"title-{chunk_id}"}
    return payload


class _FallbackOnlyClient:
    def __init__(self, points: list[_FakePoint]) -> None:
        self.points = points
        self.query_points_calls: list[dict[str, object]] = []
        self.scroll_calls: list[dict[str, object]] = []

    def query_points(self, **kwargs):  # noqa: ANN001
        self.query_points_calls.append(dict(kwargs))
        return {"points": self.points}

    def scroll(self, **kwargs):  # noqa: ANN001
        self.scroll_calls.append(dict(kwargs))
        return (self.points, None)


class _GroupedClient(_FallbackOnlyClient):
    def __init__(self, points: list[_FakePoint], groups: list[_FakeGroup], sibling_points: list[_FakePoint]) -> None:
        super().__init__(points)
        self.groups = groups
        self.sibling_points = sibling_points
        self.group_calls: list[dict[str, object]] = []

    def query_points_groups(self, **kwargs):  # noqa: ANN001
        self.group_calls.append(dict(kwargs))
        return SimpleNamespace(groups=self.groups)

    def scroll(self, **kwargs):  # noqa: ANN001
        self.scroll_calls.append(dict(kwargs))
        return (self.sibling_points, None)


class _ShapeInfo:
    def __init__(self, *, size: int, distance: str = "cosine") -> None:
        self.config = SimpleNamespace(
            params=SimpleNamespace(
                vectors={"embedding": SimpleNamespace(size=size, distance=distance)}
            )
        )


class _ShapeClient(_FallbackOnlyClient):
    def __init__(self, points: list[_FakePoint], *, size: int = 4096, distance: str = "cosine") -> None:
        super().__init__(points)
        self._shape_info = _ShapeInfo(size=size, distance=distance)

    def get_collection(self, collection_name: str):  # noqa: ANN001
        self.query_points_calls.append({"get_collection": collection_name})
        return self._shape_info


class LocalLifeParentChildRetrievalTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.embedder = _FakeEmbeddingAdapter()

    def _retriever(self, client):
        return LocalLifeParentChildRetriever(
            qdrant_client=client,
            embedding_adapter=self.embedder,
            collection_name="local_life_hybrid_chunks",
            vector_name="embedding",
        )

    def test_infer_role_weights_prefers_scene_fit_for_date_queries(self) -> None:
        weights = infer_role_weights("适合约会和聚餐的店")

        self.assertGreater(weights["merchant_scene_fit"], weights["merchant_profile"])
        self.assertGreater(weights["merchant_scene_fit"], weights["merchant_review_summary"])

    def test_infer_role_weights_prefers_pitfall_for_problem_queries(self) -> None:
        weights = infer_role_weights("避坑 排队 吵 不好")

        self.assertGreater(weights["merchant_pitfall_summary"], weights["merchant_scene_fit"])

    def test_infer_role_weights_prefers_package_for_coupon_queries(self) -> None:
        weights = infer_role_weights("套餐 优惠 团购 划算")

        self.assertGreater(weights["package_description"], weights["merchant_profile"])

    def test_infer_role_weights_boosts_guide_and_rule_roles_for_rule_queries(self) -> None:
        weights = infer_role_weights("平台规则和攻略怎么选", route="guide_rule_rag")

        self.assertGreater(weights["local_guide"], weights["merchant_profile"])
        self.assertGreater(weights["platform_rule"], weights["merchant_review_summary"])

    def test_get_payload_value_reads_top_level_and_metadata(self) -> None:
        top_level_payload = _payload(
            chunk_id="chunk-1",
            parent_id="shop:1001",
            chunk_role="merchant_profile",
            score_text="text",
            shop_id=1001,
            shop_name="湖畔私房菜",
        )
        metadata_only_payload = _payload(
            chunk_id="chunk-2",
            parent_id="shop:1001",
            chunk_role="merchant_profile",
            score_text="text",
            shop_id=1001,
            shop_name="湖畔私房菜",
            use_metadata_only=True,
        )

        self.assertEqual(get_payload_value(top_level_payload, "parent_id"), "shop:1001")
        self.assertEqual(get_payload_value(metadata_only_payload, "parent_id"), "shop:1001")
        self.assertEqual(get_payload_value(metadata_only_payload, "chunk_role"), "merchant_profile")

    def test_parent_child_parser_defaults_to_dedicated_v2_collection(self) -> None:
        parser = build_arg_parser()
        args = parser.parse_args(["--query", "适合约会的家常菜"])

        self.assertEqual(args.collection_name, LOCAL_LIFE_PARENT_CHILD_COLLECTION)

    def test_child_hits_aggregate_by_parent_and_debug_info_contains_scores(self) -> None:
        points = [
            _FakePoint(
                point_id="p1",
                score=0.96,
                payload=_payload(
                    chunk_id="chunk-1",
                    parent_id="shop:1001",
                    chunk_role="merchant_scene_fit",
                    score_text="适合约会，环境安静。",
                    shop_id=1001,
                    shop_name="湖畔私房菜",
                ),
            ),
            _FakePoint(
                point_id="p2",
                score=0.91,
                payload=_payload(
                    chunk_id="chunk-2",
                    parent_id="shop:1001",
                    chunk_role="merchant_review_summary",
                    score_text="评价口碑不错。",
                    shop_id=1001,
                    shop_name="湖畔私房菜",
                ),
            ),
            _FakePoint(
                point_id="p3",
                score=0.62,
                payload=_payload(
                    chunk_id="chunk-3",
                    parent_id="shop:1002",
                    chunk_role="merchant_profile",
                    score_text="商家介绍。",
                    shop_id=1002,
                    shop_name="川香小馆",
                ),
            ),
        ]
        client = _FallbackOnlyClient(points)
        retriever = self._retriever(client)

        pack = retriever.retrieve_local_life_evidence(
            "朝阳公园附近适合约会的家常菜",
            city="北京",
            area="朝阳",
            category="家常菜",
            shop_type_id=1,
            child_top_k=30,
            parent_top_k=5,
            sibling_limit_per_parent=4,
        )

        self.assertEqual(pack.total_child_hits, 3)
        self.assertEqual(len(pack.parent_evidences), 2)
        first = pack.parent_evidences[0]
        self.assertEqual(first.parent_id, "shop:1001")
        self.assertIn("merchant_scene_fit", first.role_coverage)
        self.assertIn("merchant_review_summary", first.role_coverage)
        self.assertIn("max_child_score", first.debug_info)
        self.assertIn("avg_top_child_score", first.debug_info)
        self.assertIn("role_coverage_score", first.debug_info)
        self.assertIn("preferred_role_coverage_score", first.debug_info)
        self.assertIn("parent_summary_match_score", first.debug_info)
        self.assertIn("freshness_score", first.debug_info)
        self.assertIn("business_boost_score", first.debug_info)

    def test_parent_child_retriever_records_provenance(self) -> None:
        points = [
            _FakePoint(
                point_id="p1",
                score=0.96,
                payload=_payload(
                    chunk_id="chunk-1",
                    parent_id="shop:1001",
                    chunk_role="merchant_scene_fit",
                    score_text="适合约会，环境安静。",
                    shop_id=1001,
                    shop_name="湖畔私房菜",
                ),
            )
        ]
        client = _ShapeClient(points)
        retriever = LocalLifeParentChildRetriever(
            qdrant_client=client,
            embedding_adapter=self.embedder,
            collection_name="local_life_parent_child_chunks",
            vector_name="embedding",
            vector_size=4096,
            distance="cosine",
        )

        pack = retriever.retrieve_local_life_evidence(
            "适合约会的家常菜",
            city="北京",
            area="朝阳",
            category="家常菜",
            shop_type_id=1,
        )

        self.assertEqual(pack.retrieval_kind, "parent_child")
        self.assertEqual(pack.collection_name, "local_life_parent_child_chunks")
        self.assertEqual(pack.source_domain, "local_life_parent_child")
        self.assertEqual(pack.parent_evidences[0].matched_chunks[0].chunk_id, "chunk-1")

    def test_parent_child_retriever_rejects_shape_mismatch(self) -> None:
        client = _ShapeClient([], size=64, distance="cosine")

        with self.assertRaisesRegex(RuntimeError, "Qdrant collection shape mismatch"):
            LocalLifeParentChildRetriever(
                qdrant_client=client,
                embedding_adapter=self.embedder,
                collection_name="local_life_parent_child_chunks",
                vector_name="embedding",
                vector_size=4096,
                distance="cosine",
            )

    def test_sibling_expansion_loads_other_chunks_and_dedupes(self) -> None:
        client = _FallbackOnlyClient([])
        retriever = self._retriever(client)
        retriever._client.scroll = lambda **kwargs: (  # type: ignore[assignment]
            [
                _FakePoint(
                    point_id="s1",
                    score=0.0,
                    payload=_payload(
                        chunk_id="chunk-1",
                        parent_id="shop:1001",
                        chunk_role="merchant_profile",
                        score_text="商家介绍",
                        shop_id=1001,
                        shop_name="湖畔私房菜",
                    ),
                ),
                _FakePoint(
                    point_id="s2",
                    score=0.0,
                    payload=_payload(
                        chunk_id="chunk-2",
                        parent_id="shop:1001",
                        chunk_role="merchant_profile",
                        score_text="商家介绍重复",
                        shop_id=1001,
                        shop_name="湖畔私房菜",
                    ),
                ),
                _FakePoint(
                    point_id="s3",
                    score=0.0,
                    payload=_payload(
                        chunk_id="chunk-3",
                        parent_id="shop:1001",
                        chunk_role="package_description",
                        score_text="套餐说明",
                        shop_id=1001,
                        shop_name="湖畔私房菜",
                    ),
                ),
                _FakePoint(
                    point_id="s4",
                    score=0.0,
                    payload=_payload(
                        chunk_id="chunk-4",
                        parent_id="shop:1001",
                        chunk_role="package_description",
                        score_text="套餐说明二",
                        shop_id=1001,
                        shop_name="湖畔私房菜",
                    ),
                ),
            ],
            None,
        )

        siblings = retriever.load_sibling_chunks(
            "shop:1001",
            preferred_roles=["merchant_profile", "package_description"],
            limit=3,
        )

        self.assertLessEqual(len(siblings), 3)
        self.assertEqual(len({chunk.chunk_id for chunk in siblings}), len(siblings))
        self.assertIn("merchant_profile", [chunk.chunk_role for chunk in siblings])
        self.assertIn("package_description", [chunk.chunk_role for chunk in siblings])

    def test_parent_top_k_limits_final_shop_count(self) -> None:
        points = [
            _FakePoint(
                point_id="p1",
                score=0.94,
                payload=_payload(
                    chunk_id="chunk-1",
                    parent_id="shop:1001",
                    chunk_role="merchant_scene_fit",
                    score_text="适合约会",
                    shop_id=1001,
                    shop_name="湖畔私房菜",
                ),
            ),
            _FakePoint(
                point_id="p2",
                score=0.91,
                payload=_payload(
                    chunk_id="chunk-2",
                    parent_id="shop:1002",
                    chunk_role="merchant_scene_fit",
                    score_text="适合聚餐",
                    shop_id=1002,
                    shop_name="川香小馆",
                ),
            ),
            _FakePoint(
                point_id="p3",
                score=0.89,
                payload=_payload(
                    chunk_id="chunk-3",
                    parent_id="shop:1003",
                    chunk_role="merchant_scene_fit",
                    score_text="适合家庭",
                    shop_id=1003,
                    shop_name="粤味小院",
                ),
            ),
        ]
        retriever = self._retriever(_FallbackOnlyClient(points))

        pack = retriever.retrieve_local_life_evidence(
            "适合家庭聚餐的店",
            city="北京",
            category="家常菜",
            child_top_k=30,
            parent_top_k=2,
        )

        self.assertEqual(len(pack.parent_evidences), 2)

    def test_grouping_api_falls_back_to_python_aggregation_when_missing(self) -> None:
        points = [
            _FakePoint(
                point_id="p1",
                score=0.97,
                payload=_payload(
                    chunk_id="chunk-1",
                    parent_id="shop:1001",
                    chunk_role="merchant_scene_fit",
                    score_text="适合约会",
                    shop_id=1001,
                    shop_name="湖畔私房菜",
                ),
            ),
            _FakePoint(
                point_id="p2",
                score=0.88,
                payload=_payload(
                    chunk_id="chunk-2",
                    parent_id="shop:1001",
                    chunk_role="merchant_review_summary",
                    score_text="评价不错",
                    shop_id=1001,
                    shop_name="湖畔私房菜",
                ),
            ),
        ]
        retriever = self._retriever(_FallbackOnlyClient(points))

        pack = retriever.retrieve_local_life_evidence("适合约会的家常菜")

        self.assertGreater(pack.total_child_hits, 0)
        self.assertEqual(len(pack.parent_evidences), 1)
        self.assertEqual(pack.route, "merchant_reasoning")

    def test_candidate_shop_ids_are_hard_filtered(self) -> None:
        points = [
            _FakePoint(
                point_id="p1",
                score=0.96,
                payload=_payload(
                    chunk_id="chunk-1",
                    parent_id="shop:1001",
                    chunk_role="merchant_scene_fit",
                    score_text="适合约会。",
                    shop_id=1001,
                    shop_name="湖畔私房菜",
                ),
            ),
            _FakePoint(
                point_id="p2",
                score=0.94,
                payload=_payload(
                    chunk_id="chunk-2",
                    parent_id="shop:1002",
                    chunk_role="merchant_scene_fit",
                    score_text="适合聚餐。",
                    shop_id=1002,
                    shop_name="川香小馆",
                ),
            ),
        ]
        retriever = self._retriever(_FallbackOnlyClient(points))

        pack = retriever.retrieve_local_life_evidence(
            "适合约会的家常菜",
            candidate_shop_ids=[1001],
        )

        self.assertEqual([evidence.shop_id for evidence in pack.parent_evidences], [1001])
        self.assertEqual(pack.parent_evidences[0].business_facts["shop_id"], 1001)
        self.assertTrue(pack.parent_evidences[0].business_facts["matches_candidate_filter"])

    def test_empty_retrieval_returns_empty_pack(self) -> None:
        retriever = self._retriever(_FallbackOnlyClient([]))

        pack = retriever.retrieve_local_life_evidence("不存在的查询")

        self.assertEqual(pack.total_child_hits, 0)
        self.assertEqual(pack.parent_evidences, [])
        self.assertEqual(pack.retrieval_strategy, "child_vector_recall->parent_enrich->sibling_supplement->shop_rerank")

    def test_grouping_api_path_is_usable_when_available(self) -> None:
        groups = [
            _FakeGroup(
                group_id="shop:1001",
                hits=[
                    _FakePoint(
                        point_id="p1",
                        score=0.98,
                        payload=_payload(
                            chunk_id="chunk-1",
                            parent_id="shop:1001",
                            chunk_role="merchant_scene_fit",
                            score_text="适合约会",
                            shop_id=1001,
                            shop_name="湖畔私房菜",
                        ),
                    ),
                    _FakePoint(
                        point_id="p2",
                        score=0.9,
                        payload=_payload(
                            chunk_id="chunk-2",
                            parent_id="shop:1001",
                            chunk_role="merchant_review_summary",
                            score_text="口碑不错",
                            shop_id=1001,
                            shop_name="湖畔私房菜",
                        ),
                    ),
                ],
            )
        ]
        client = _GroupedClient(points=[], groups=groups, sibling_points=[])
        retriever = self._retriever(client)

        pack = retriever.retrieve_local_life_evidence("适合约会的家常菜")

        self.assertGreaterEqual(len(client.group_calls), 1)
        self.assertEqual(len(pack.parent_evidences), 1)
        self.assertEqual(pack.parent_evidences[0].parent_id, "shop:1001")

    def test_load_parent_and_child_helpers_respect_chunk_levels(self) -> None:
        points = [
            _FakePoint(
                point_id="parent",
                score=0.0,
                payload=_payload(
                    chunk_id="parent-summary",
                    parent_id="shop:1001",
                    parent_chunk_id="local-life:shop:1001:parent-summary",
                    chunk_role="merchant_parent_summary",
                    chunk_level="parent",
                    score_text="商家整体摘要",
                    shop_id=1001,
                    shop_name="湖畔私房菜",
                ),
            ),
            _FakePoint(
                point_id="child-1",
                score=0.0,
                payload=_payload(
                    chunk_id="child-1",
                    parent_id="shop:1001",
                    parent_chunk_id="local-life:shop:1001:parent-summary",
                    chunk_role="merchant_scene_fit",
                    chunk_level="child",
                    score_text="适合约会",
                    shop_id=1001,
                    shop_name="湖畔私房菜",
                ),
            ),
            _FakePoint(
                point_id="child-2",
                score=0.0,
                payload=_payload(
                    chunk_id="child-2",
                    parent_id="shop:1001",
                    parent_chunk_id="local-life:shop:1001:parent-summary",
                    chunk_role="merchant_review_summary",
                    chunk_level="child",
                    score_text="评价不错",
                    shop_id=1001,
                    shop_name="湖畔私房菜",
                ),
            ),
        ]
        retriever = self._retriever(_FallbackOnlyClient(points))

        parent = retriever.load_parent_chunk("shop:1001")
        children = retriever.load_child_chunks_by_parent("shop:1001")

        self.assertIsNotNone(parent)
        self.assertEqual(parent.chunk_level, "parent")
        self.assertEqual(parent.chunk_role, "merchant_parent_summary")
        self.assertTrue(children)
        self.assertTrue(all(chunk.chunk_level == "child" for chunk in children))
        self.assertTrue(all(chunk.parent_id == "shop:1001" for chunk in children))

    def test_parent_recall_mode_loads_parent_context_and_expands_children(self) -> None:
        points = [
            _FakePoint(
                point_id="parent",
                score=0.99,
                payload=_payload(
                    chunk_id="parent-summary",
                    parent_id="shop:1001",
                    parent_chunk_id="local-life:shop:1001:parent-summary",
                    chunk_role="merchant_parent_summary",
                    chunk_level="parent",
                    score_text="某某家常菜 位于北京朝阳望京，适合家庭聚餐。",
                    shop_id=1001,
                    shop_name="某某家常菜",
                ),
            ),
            _FakePoint(
                point_id="child-1",
                score=0.96,
                payload=_payload(
                    chunk_id="child-1",
                    parent_id="shop:1001",
                    parent_chunk_id="local-life:shop:1001:parent-summary",
                    chunk_role="merchant_scene_fit",
                    chunk_level="child",
                    score_text="适合约会，环境安静。",
                    shop_id=1001,
                    shop_name="某某家常菜",
                ),
            ),
            _FakePoint(
                point_id="child-2",
                score=0.92,
                payload=_payload(
                    chunk_id="child-2",
                    parent_id="shop:1001",
                    parent_chunk_id="local-life:shop:1001:parent-summary",
                    chunk_role="merchant_review_summary",
                    chunk_level="child",
                    score_text="口碑不错。",
                    shop_id=1001,
                    shop_name="某某家常菜",
                ),
            ),
        ]
        retriever = self._retriever(_FallbackOnlyClient(points))

        pack = retriever.retrieve_local_life_evidence(
            "适合家庭聚餐的家常菜",
            enable_parent_recall=True,
        )

        self.assertGreaterEqual(len(pack.parent_evidences), 1)
        evidence = pack.parent_evidences[0]
        self.assertIsNotNone(evidence.parent_context)
        self.assertEqual(evidence.parent_context.chunk_level, "parent")
        self.assertGreaterEqual(len(evidence.sibling_chunks), 1)
        self.assertTrue(any(chunk.chunk_level == "child" for chunk in evidence.sibling_chunks))


if __name__ == "__main__":
    unittest.main()
