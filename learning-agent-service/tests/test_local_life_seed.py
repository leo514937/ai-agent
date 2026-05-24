from __future__ import annotations

import io
import uuid
import unittest
from dataclasses import dataclass
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

import _bootstrap  # noqa: F401

from learning_agent_service.local_life.schemas import BlogRecord, ShopRecord, ShopTypeRecord, VoucherRecord


@dataclass
class _FakeCollectionInfo:
    size: int
    distance: str = "Cosine"

    @property
    def config(self):
        return type(
            "Config",
            (),
            {
                "params": type(
                    "Params",
                    (),
                    {
                        "vectors": type("Vectors", (), {"size": self.size, "distance": self.distance})(),
                    },
                )()
            },
        )()


class _FakeEmbeddingAdapter:
    def __init__(self, dimension: int = 4096) -> None:
        self.dimension = dimension
        self.calls: list[str] = []

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        return [0.0] * self.dimension


class _FakeQdrantClient:
    def __init__(self, *, existing_size: int | None = None) -> None:
        self.existing_size = existing_size
        self.collection_exists_calls: list[str] = []
        self.get_collection_calls: list[str] = []
        self.create_collection_calls: list[dict[str, object]] = []
        self.create_payload_index_calls: list[dict[str, object]] = []
        self.upsert_calls: list[dict[str, object]] = []
        self.delete_calls: list[dict[str, object]] = []

    def collection_exists(self, collection_name: str) -> bool:
        self.collection_exists_calls.append(collection_name)
        return self.existing_size is not None

    def get_collection(self, collection_name: str):
        self.get_collection_calls.append(collection_name)
        if self.existing_size is None:
            raise RuntimeError("collection missing")
        return _FakeCollectionInfo(self.existing_size)

    def create_collection(self, **kwargs):
        self.create_collection_calls.append(dict(kwargs))
        return None

    def create_payload_index(self, **kwargs):
        self.create_payload_index_calls.append(dict(kwargs))
        return None

    def upsert(self, **kwargs):
        self.upsert_calls.append(dict(kwargs))
        return None

    def delete(self, **kwargs):
        self.delete_calls.append(dict(kwargs))
        return type("DeleteResult", (), {"deleted_count": 3})()


class _ExistingIndexQdrantClient(_FakeQdrantClient):
    def create_payload_index(self, **kwargs):
        self.create_payload_index_calls.append(dict(kwargs))
        raise RuntimeError("payload index already exists")


class _FakeJavaBusinessClient:
    def __init__(self) -> None:
        self._shop_types = [
            ShopTypeRecord(id=1, name="家常菜", icon="🍚", sort=1),
            ShopTypeRecord(id=2, name="火锅", icon="🍲", sort=2),
        ]
        self._shops = {
            1: ShopRecord(
                id=1001,
                name="某某家常菜",
                type_id=1,
                type_name="家常菜",
                area="望京",
                address="北京市朝阳区望京街道1号",
                avg_price=145,
                comments=1820,
                score=4.8,
                open_hours="11:00-21:30",
                parking=True,
                quiet_score=0.92,
                family_friendly=True,
                elder_friendly=True,
                tags=["quiet", "family_dinner", "parking"],
                review_summary="环境安静，适合家庭聚餐。",
                evidence_texts=["评论多次提到环境安静", "有停车位", "高峰期偶尔要排队"],
                source="java",
            ),
        }
        self._vouchers = {
            1001: [
                VoucherRecord(
                    id=2001,
                    shop_id=1001,
                    shop_name="某某家常菜",
                    title="家庭聚餐券",
                    sub_title="150减30",
                    rules="满150元可用",
                    pay_value=120,
                    actual_value=150,
                    stock=36,
                    begin_time="2026-05-01 00:00:00",
                    end_time="2026-06-30 23:59:59",
                    source="java",
                )
            ]
        }
        self._blogs = {
            1001: [
                BlogRecord(
                    id=3001,
                    shop_id=1001,
                    user_id=501,
                    title="带爸妈去吃这家，真的挺安静",
                    content="店里灯光舒服，服务员会主动帮长辈拉椅子，适合家庭聚餐。",
                    liked=86,
                    comments=12,
                    source="java",
                ),
                BlogRecord(
                    id=3002,
                    shop_id=1001,
                    user_id=502,
                    title="周末去吃火锅的小记录",
                    content=(
                        "这是一段很长的探店笔记。" * 120
                        + "高峰时段可能需要预约，停车不算特别方便，但整体环境仍然比较安静。"
                    ),
                    liked=46,
                    comments=8,
                    source="java",
                )
            ]
        }

    def list_shop_types(self):
        return list(self._shop_types)

    def search_shops_by_type(self, *, type_id: int, current: int = 1, x=None, y=None):  # noqa: D401
        shop = self._shops.get(int(type_id))
        return [shop] if shop is not None else []

    def get_shop_detail(self, shop_id: int):
        return self._shops[int(shop_id)]

    def get_coupon_list(self, shop_id: int):
        return list(self._vouchers.get(int(shop_id), []))

    def get_shop_blogs(self, shop_id: int, limit: int = 5):
        return list(self._blogs.get(int(shop_id), []))[:limit]
class LocalLifeSeedTestCase(unittest.TestCase):
    def test_build_local_life_seed_chunks_covers_five_source_types(self) -> None:
        from learning_agent_service.rag.local_life_seed import build_local_life_knowledge_chunks

        chunks = build_local_life_knowledge_chunks(_FakeJavaBusinessClient())

        source_types = {chunk.source_type for chunk in chunks}
        self.assertEqual(
            source_types,
            {
                "merchant_profile",
                "merchant_review",
                "package_description",
                "platform_rule",
                "local_guide",
            },
        )
        profile = next(chunk for chunk in chunks if chunk.source_type == "merchant_profile")
        self.assertEqual(profile.category, "local_life")
        self.assertEqual(profile.metadata["shop_id"], 1001)
        self.assertEqual(profile.metadata["shop_type_id"], 1)
        self.assertTrue(profile.metadata["is_active"])
        self.assertEqual(profile.metadata["entity_type"], "shop")
        self.assertEqual(profile.metadata["entity_id"], "shop:1001")
        self.assertEqual(profile.metadata["parent_id"], "shop:1001")
        self.assertEqual(profile.metadata["chunk_role"], "merchant_profile")
        self.assertIn("sibling_roles", profile.metadata)

    def test_build_local_life_seed_chunks_create_parent_child_metadata(self) -> None:
        from learning_agent_service.rag.local_life_seed import build_local_life_knowledge_chunks

        chunks = build_local_life_knowledge_chunks(_FakeJavaBusinessClient())
        shop_chunks = [chunk for chunk in chunks if chunk.metadata.get("shop_id") == 1001]
        parent_chunks = [chunk for chunk in shop_chunks if chunk.chunk_level == "parent"]
        child_chunks = [chunk for chunk in shop_chunks if chunk.chunk_level == "child"]

        self.assertGreaterEqual(len(shop_chunks), 5)
        self.assertGreaterEqual(len(parent_chunks), 1)
        self.assertGreaterEqual(len(child_chunks), 1)
        self.assertTrue(all(chunk.parent_id == "shop:1001" for chunk in shop_chunks))
        self.assertTrue(all(chunk.metadata.get("parent_id") == "shop:1001" for chunk in shop_chunks))
        self.assertTrue(all(chunk.metadata.get("parent_title") == "某某家常菜" for chunk in shop_chunks))
        self.assertTrue(all(chunk.metadata.get("entity_type") in {"shop", "voucher", "blog"} for chunk in child_chunks))
        parent = next(chunk for chunk in parent_chunks if chunk.metadata.get("chunk_role") == "merchant_parent_summary")
        self.assertEqual(parent.chunk_level, "parent")
        self.assertEqual(parent.parent_chunk_id, "local-life:shop:1001:parent-summary")
        self.assertIn("local-life:shop:1001:merchant-profile:chunk-001", parent.child_chunk_ids)
        self.assertIn("merchant_profile", parent.child_roles)

    def test_build_local_life_seed_chunks_splits_long_blog_and_keeps_short_blog_whole(self) -> None:
        from learning_agent_service.rag.local_life_seed import build_local_life_knowledge_chunks

        chunks = build_local_life_knowledge_chunks(_FakeJavaBusinessClient())
        blog_long_chunks = [
            chunk
            for chunk in chunks
            if chunk.metadata.get("chunk_role") == "merchant_blog_note" and chunk.metadata.get("blog_id") == 3002
        ]
        blog_short_chunks = [
            chunk
            for chunk in chunks
            if chunk.metadata.get("chunk_role") == "merchant_blog_note" and chunk.metadata.get("blog_id") == 3001
        ]

        self.assertGreater(len(blog_long_chunks), 1)
        self.assertEqual(len(blog_short_chunks), 1)
        self.assertTrue(all(chunk.metadata.get("entity_type") == "blog" for chunk in blog_long_chunks))
        self.assertTrue(all(chunk.metadata.get("parent_id") == "shop:1001" for chunk in blog_long_chunks))

    def test_build_local_life_seed_chunks_uses_rule_based_summary_only(self) -> None:
        from learning_agent_service.rag.local_life_seed import build_local_life_knowledge_chunks

        chunks = build_local_life_knowledge_chunks(_FakeJavaBusinessClient())
        review_summary = next(
            chunk for chunk in chunks if chunk.metadata.get("chunk_role") == "merchant_review_summary"
        )

        self.assertIn("好评点", review_summary.text)
        self.assertIn("适合场景", review_summary.text)
        self.assertIn("不适合场景", review_summary.text)

    def test_build_local_life_seed_chunks_keeps_merchant_profile_single_chunk(self) -> None:
        from learning_agent_service.rag.local_life_seed import build_local_life_knowledge_chunks

        chunks = build_local_life_knowledge_chunks(_FakeJavaBusinessClient())
        profile_chunks = [
            chunk
            for chunk in chunks
            if chunk.source_type == "merchant_profile"
            and chunk.metadata.get("shop_id") == 1001
            and chunk.chunk_level == "child"
            and chunk.metadata.get("chunk_role") == "merchant_profile"
        ]
        parent_chunks = [
            chunk
            for chunk in chunks
            if chunk.source_type == "merchant_profile"
            and chunk.metadata.get("shop_id") == 1001
            and chunk.chunk_level == "parent"
            and chunk.metadata.get("chunk_role") == "merchant_parent_summary"
        ]

        self.assertEqual(len(profile_chunks), 1)
        self.assertEqual(len(parent_chunks), 1)
        self.assertEqual(profile_chunks[0].metadata.get("chunk_role"), "merchant_profile")

    def test_seed_local_life_knowledge_uses_local_life_collection_and_4096_dimensions(self) -> None:
        from learning_agent_service.rag.local_life_seed import LOCAL_LIFE_HYBRID_COLLECTION, seed_local_life_knowledge

        qdrant = _FakeQdrantClient()
        embedder = _FakeEmbeddingAdapter()

        result = seed_local_life_knowledge(
            business_client=_FakeJavaBusinessClient(),
            qdrant_client=qdrant,
            embedding_adapter=embedder,
            collection_name=LOCAL_LIFE_HYBRID_COLLECTION,
            vector_size=4096,
        )

        self.assertEqual(result.collection_name, LOCAL_LIFE_HYBRID_COLLECTION)
        self.assertEqual(result.vector_size, 4096)
        self.assertEqual(qdrant.create_collection_calls[0]["collection_name"], LOCAL_LIFE_HYBRID_COLLECTION)
        vectors_config = qdrant.create_collection_calls[0]["vectors_config"]
        self.assertIn("embedding", vectors_config)
        self.assertEqual(vectors_config["embedding"].size, 4096)
        self.assertEqual(str(vectors_config["embedding"].distance).lower(), "cosine")
        self.assertGreater(len(qdrant.upsert_calls), 0)
        self.assertGreater(result.chunk_count, 0)
        self.assertGreater(len(embedder.calls), 0)
        self.assertGreater(len(qdrant.create_payload_index_calls), 0)
        self.assertIn("category", result.payload_index_fields)
        self.assertIn("source_type", result.payload_index_fields)
        self.assertIn("shop_id", result.payload_index_fields)
        self.assertEqual(sum(result.source_type_counts.values()), result.chunk_count)
        self.assertGreater(result.source_type_counts["merchant_review"], 1)
        self.assertEqual(sum(result.chunk_role_counts.values()), result.chunk_count)
        self.assertGreater(result.chunk_role_counts["merchant_review_summary"], 0)
        self.assertGreater(result.chunk_role_counts["merchant_scene_fit"], 0)
        self.assertGreater(result.chunk_role_counts["merchant_pitfall_summary"], 0)
        self.assertGreater(result.chunk_role_counts["merchant_blog_note"], 0)
        self.assertTrue(result.deleted_point_count >= 0)
        self.assertGreater(result.duration_seconds, 0.0)

    def test_seed_helpers_use_distinct_hybrid_and_parent_child_collections(self) -> None:
        from learning_agent_service.rag.local_life_seed import (
            seed_local_life_hybrid_knowledge_from_settings,
            seed_local_life_parent_child_knowledge_from_settings,
        )

        settings = SimpleNamespace(
            qdrant=SimpleNamespace(
                local_life_hybrid_collection="local_life_hybrid_chunks",
                local_life_parent_child_collection="local_life_parent_child_chunks",
                knowledge_collection="knowledge_chunks",
                knowledge_vector_name="embedding",
                knowledge_vector_size=4096,
            )
        )

        hybrid_result = seed_local_life_hybrid_knowledge_from_settings(
            settings=settings,
            business_client=_FakeJavaBusinessClient(),
            qdrant_client=_FakeQdrantClient(),
            embedding_adapter=_FakeEmbeddingAdapter(),
            cleanup_stale_points=False,
        )
        parent_child_result = seed_local_life_parent_child_knowledge_from_settings(
            settings=settings,
            business_client=_FakeJavaBusinessClient(),
            qdrant_client=_FakeQdrantClient(),
            embedding_adapter=_FakeEmbeddingAdapter(),
            cleanup_stale_points=False,
        )

        self.assertEqual(hybrid_result.collection_name, "local_life_hybrid_chunks")
        self.assertEqual(parent_child_result.collection_name, "local_life_parent_child_chunks")
        self.assertNotEqual(hybrid_result.collection_name, parent_child_result.collection_name)

    def test_seed_local_life_knowledge_uses_named_vectors_and_uuid_point_ids(self) -> None:
        from learning_agent_service.rag.local_life_seed import seed_local_life_knowledge

        qdrant = _FakeQdrantClient()
        embedder = _FakeEmbeddingAdapter()

        result = seed_local_life_knowledge(
            business_client=_FakeJavaBusinessClient(),
            qdrant_client=qdrant,
            embedding_adapter=embedder,
            vector_size=4096,
        )

        self.assertGreater(result.point_count, 0)
        upsert_points = [point for call in qdrant.upsert_calls for point in call["points"]]
        self.assertTrue(all(isinstance(point.id, uuid.UUID) for point in upsert_points))
        self.assertTrue(all(list(point.vector.keys()) == ["embedding"] for point in upsert_points))
        self.assertTrue(all(str(point.id) == str(uuid.UUID(str(point.id))) for point in upsert_points))
        self.assertTrue(all(call["wait"] is True for call in qdrant.upsert_calls))
        self.assertTrue(all("parent_id" in point.payload for point in upsert_points))

    def test_seed_local_life_knowledge_is_idempotent_with_stable_point_ids(self) -> None:
        from learning_agent_service.rag.local_life_seed import seed_local_life_knowledge

        qdrant = _FakeQdrantClient()
        embedder = _FakeEmbeddingAdapter()

        first = seed_local_life_knowledge(
            business_client=_FakeJavaBusinessClient(),
            qdrant_client=qdrant,
            embedding_adapter=embedder,
            vector_size=4096,
            cleanup_stale_points=False,
        )
        first_call_count = len(qdrant.upsert_calls)
        first_ids = [point.id for call in qdrant.upsert_calls for point in call["points"]]

        second = seed_local_life_knowledge(
            business_client=_FakeJavaBusinessClient(),
            qdrant_client=qdrant,
            embedding_adapter=embedder,
            vector_size=4096,
            cleanup_stale_points=False,
        )
        second_ids = [point.id for call in qdrant.upsert_calls[first_call_count:] for point in call["points"]]

        self.assertEqual(first.collection_name, second.collection_name)
        self.assertEqual(first_ids, second_ids)

    def test_dedupe_chunks_removes_duplicate_chunk_ids(self) -> None:
        from learning_agent_service.rag.local_life_seed import _dedupe_chunks, build_local_life_knowledge_chunks

        chunks = build_local_life_knowledge_chunks(_FakeJavaBusinessClient())
        duplicated = _dedupe_chunks([*chunks, *chunks])

        self.assertEqual(len(duplicated), len(chunks))
        self.assertEqual([chunk.chunk_id for chunk in duplicated], [chunk.chunk_id for chunk in chunks])

    def test_empty_text_does_not_generate_empty_blog_chunk(self) -> None:
        from learning_agent_service.rag.local_life_seed import _build_blog_note_chunks

        business_client = _FakeJavaBusinessClient()
        shop = business_client._shops[1]
        chunks = _build_blog_note_chunks(
            shop=shop,
            shop_type=ShopTypeRecord(id=1, name="家常菜", icon="🍚", sort=1),
            blogs=[BlogRecord(id=9999, shop_id=1001, user_id=5, title="", content="", liked=0, comments=0, source="java")],
        )

        self.assertEqual(chunks, [])

    def test_seed_local_life_knowledge_rejects_existing_collection_with_wrong_vector_size(self) -> None:
        from learning_agent_service.rag.local_life_seed import (
            LocalLifeQdrantCollectionShapeError,
            seed_local_life_knowledge,
        )

        qdrant = _FakeQdrantClient(existing_size=1536)

        with self.assertRaises(LocalLifeQdrantCollectionShapeError):
            seed_local_life_knowledge(
                business_client=_FakeJavaBusinessClient(),
                qdrant_client=qdrant,
                embedding_adapter=_FakeEmbeddingAdapter(),
                vector_size=4096,
            )

    def test_seed_local_life_knowledge_skips_existing_payload_indexes(self) -> None:
        from learning_agent_service.rag.local_life_seed import seed_local_life_knowledge

        qdrant = _ExistingIndexQdrantClient()

        result = seed_local_life_knowledge(
            business_client=_FakeJavaBusinessClient(),
            qdrant_client=qdrant,
            embedding_adapter=_FakeEmbeddingAdapter(),
            vector_size=4096,
        )

        self.assertGreater(result.chunk_count, 0)
        self.assertGreater(len(qdrant.create_payload_index_calls), 0)
        self.assertGreater(len(result.payload_index_fields), 0)

    def test_seed_local_life_knowledge_cleans_stale_points(self) -> None:
        from learning_agent_service.rag.local_life_seed import seed_local_life_knowledge

        qdrant = _FakeQdrantClient()

        seed_local_life_knowledge(
            business_client=_FakeJavaBusinessClient(),
            qdrant_client=qdrant,
            embedding_adapter=_FakeEmbeddingAdapter(),
            vector_size=4096,
            cleanup_stale_points=True,
        )

        self.assertEqual(len(qdrant.delete_calls), 1)
        delete_call = qdrant.delete_calls[0]
        self.assertEqual(delete_call["collection_name"], "local_life_hybrid_chunks")
        self.assertTrue(delete_call["wait"])

    def test_parent_child_resolver_expands_sibling_hits_for_same_shop(self) -> None:
        from learning_agent_service.rag.local_life_seed import build_local_life_knowledge_chunks
        from learning_agent_service.rag.models import RecallHit
        from learning_agent_service.rag.retrieval import ParentChildResolver

        chunks = build_local_life_knowledge_chunks(_FakeJavaBusinessClient())
        resolver = ParentChildResolver(chunks)
        review_summary = next(
            chunk for chunk in chunks if chunk.metadata.get("chunk_role") == "merchant_review_summary"
        )
        base_hit = RecallHit(
            chunk=review_summary,
            score=0.93,
            route="dense",
            rank=1,
            source_chunk_id=review_summary.chunk_id,
            citation_chunk_id=review_summary.chunk_id,
        )

        expanded_hits = resolver.resolve_hits([base_hit])
        expanded_roles = [hit.chunk.metadata.get("chunk_role") for hit in expanded_hits]

        self.assertGreater(len(expanded_hits), 1)
        self.assertIn("merchant_profile", expanded_roles)
        self.assertIn("merchant_scene_fit", expanded_roles)
        self.assertIn("merchant_pitfall_summary", expanded_roles)
        self.assertIn("merchant_blog_note", expanded_roles)
        self.assertTrue(all(hit.chunk.metadata.get("parent_id") == "shop:1001" for hit in expanded_hits))

    def test_cli_parser_exposes_seed_controls(self) -> None:
        from learning_agent_service.rag.local_life_seed import build_arg_parser

        parser = build_arg_parser()
        args = parser.parse_args(
            [
                "--collection-name",
                "local_life_hybrid_chunks",
                "--shop-id",
                "1001",
                "--voucher-id",
                "2001",
                "--no-cleanup-stale-points",
            ]
        )

        self.assertEqual(args.collection_name, "local_life_hybrid_chunks")
        self.assertEqual(args.shop_ids, [1001])
        self.assertEqual(args.voucher_ids, [2001])
        self.assertFalse(args.cleanup_stale_points)

    def test_main_prints_chunk_role_summary(self) -> None:
        from learning_agent_service.rag.local_life_seed import LocalLifeKnowledgeSeedResult, main

        fake_result = LocalLifeKnowledgeSeedResult(
            collection_name="local_life_hybrid_chunks",
            vector_name="embedding",
            vector_size=4096,
            chunk_count=5,
            point_count=5,
            chunk_ids=("a", "b", "c", "d", "e"),
            source_type_counts={"merchant_review": 3, "merchant_profile": 1, "package_description": 1},
            chunk_role_counts={"merchant_review_summary": 1, "merchant_scene_fit": 1, "merchant_blog_note": 2},
            upsert_batches=(("1", "2"), ("3", "4"), ("5",)),
            payload_index_fields=("category", "source_type"),
            deleted_point_count=0,
            duration_seconds=1.23,
        )

        stdout = io.StringIO()
        with (
            patch("learning_agent_service.rag.local_life_seed.get_settings") as get_settings_mock,
            patch("learning_agent_service.rag.local_life_seed.JavaBusinessClient") as business_client_mock,
            patch("learning_agent_service.rag.local_life_seed.build_openai_runtime"),
            patch("learning_agent_service.rag.local_life_seed.build_qdrant_runtime"),
            patch("learning_agent_service.rag.local_life_seed.OpenAIEmbeddingAdapter"),
            patch("learning_agent_service.rag.local_life_seed.seed_local_life_knowledge", return_value=fake_result),
            redirect_stdout(stdout),
        ):
            get_settings_mock.return_value = type(
                "SettingsStub",
                (),
                {
                    "openai": type("OpenAIStub", (), {"embedding_model": "qwen/qwen3-embedding-8b"})(),
                    "qdrant": object(),
                },
            )()
            business_client_mock.return_value = type("BusinessClientStub", (), {"close": lambda self: None})()
            exit_code = main([])

        output = stdout.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("本地生活 Qdrant 灌库完成", output)
        self.assertIn("chunk_role_counts:", output)
        self.assertIn("merchant_review_summary:1", output)
        self.assertIn("merchant_scene_fit:1", output)


if __name__ == "__main__":
    unittest.main()
