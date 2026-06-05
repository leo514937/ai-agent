from __future__ import annotations

import argparse
import logging
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from learning_agent_service.config.settings import get_settings
from learning_agent_service.infrastructure.db.openai_client import build_openai_runtime
from learning_agent_service.infrastructure.db.qdrant import build_qdrant_runtime
from learning_agent_service.local_life.ranker import rerank_parent_evidences
from learning_agent_service.local_life.schemas import EvidenceClaim

from .strategies.hybrid import infer_role_weights as _infer_role_weights
from .post_processing import format_evidence_pack
from ..models import KnowledgeChunk
from ..retrieval import validate_qdrant_collection_shape

try:  # pragma: no cover - optional runtime dependency
    from qdrant_client import QdrantClient
    from qdrant_client.http.models import FieldCondition, Filter, MatchAny, MatchValue
except Exception:  # pragma: no cover - import-tolerant fallback for tests
    QdrantClient = None

    @dataclass(frozen=True)
    class FieldCondition:  # type: ignore[no-redef]
        key: str
        match: Any = None

    @dataclass(frozen=True)
    class MatchValue:  # type: ignore[no-redef]
        value: Any

    @dataclass(frozen=True)
    class MatchAny:  # type: ignore[no-redef]
        any: Sequence[Any]

    @dataclass(frozen=True)
    class Filter:  # type: ignore[no-redef]
        must: Sequence[Any] | None = None
        must_not: Sequence[Any] | None = None
        should: Sequence[Any] | None = None


_LOGGER = logging.getLogger(__name__)
LOCAL_LIFE_KNOWLEDGE_COLLECTION = "local_life_hybrid_chunks"
LOCAL_LIFE_PARENT_CHILD_COLLECTION = "local_life_parent_child_chunks"
LOCAL_LIFE_VECTOR_NAME = "embedding"
LOCAL_LIFE_VERSION = "local-life-v1"
_DEFAULT_PARENT_TOP_K = 5
_DEFAULT_CHILD_TOP_K = 30
_DEFAULT_SIBLING_LIMIT = 6
_DEFAULT_ROLE_WEIGHTS = {
    "merchant_profile": 1.0,
    "merchant_review_summary": 1.0,
    "merchant_scene_fit": 1.0,
    "merchant_pitfall_summary": 0.92,
    "package_description": 0.92,
    "merchant_blog_note": 0.88,
    "local_guide": 0.84,
    "platform_rule": 0.72,
}
_ROLE_COVERAGE_WEIGHTS = {
    "merchant_profile": 1.0,
    "merchant_review_summary": 1.0,
    "merchant_scene_fit": 1.0,
    "merchant_pitfall_summary": 0.7,
    "package_description": 0.65,
    "merchant_blog_note": 0.45,
    "local_guide": 0.35,
    "platform_rule": 0.25,
}
_ROLE_SIBLING_CAPS = {
    "merchant_profile": 1,
    "merchant_review_summary": 1,
    "merchant_scene_fit": 1,
    "merchant_pitfall_summary": 1,
    "package_description": 2,
    "merchant_blog_note": 2,
    "local_guide": 1,
    "platform_rule": 1,
}
_ROLE_KEYWORDS = {
    "merchant_scene_fit": ("适合", "约会", "聚餐", "家庭", "长辈", "朋友", "商务", "学生", "夜宵"),
    "merchant_pitfall_summary": ("坑", "排队", "吵", "停车", "贵", "服务慢", "不好", "避雷", "拥挤", "等位"),
    "package_description": ("套餐", "券", "优惠", "团购", "几人", "划算", "价格", "折扣"),
    "merchant_review_summary": ("怎么样", "评价", "口碑", "推荐", "好吃吗"),
    "merchant_profile": ("地址", "营业", "商圈", "类型", "介绍"),
    "local_guide": ("攻略", "规则", "平台", "怎么选", "怎么用", "注意事项", "指南"),
    "platform_rule": ("规则", "平台", "活动", "说明", "条款", "限制", "规则说明"),
}
_RETRIEVAL_STRATEGY = "child_vector_recall->parent_enrich->sibling_supplement->shop_rerank"
_PARENT_RECALL_STRATEGY = "parent_vector_recall->child_expand->shop_rerank"
_DEFAULT_CHILD_ENTITY_TYPES = ("shop",)
_DEFAULT_GUIDE_RULE_ENTITY_TYPES = ("shop_type_guide", "platform_rule")


@dataclass(frozen=True)
class RetrievedChunk:
    point_id: str
    chunk_id: str
    parent_id: str
    chunk_role: str
    source_type: str
    title: str
    text: str
    score: float | None
    payload: dict[str, Any]
    parent_chunk_id: str | None = None
    chunk_level: str | None = None
    parent_title: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None


@dataclass(frozen=True)
class ParentEvidence:
    parent_id: str
    parent_title: str
    entity_type: str
    entity_id: str
    shop_id: int | None
    shop_name: str | None
    city: str | None
    area: str | None
    category: str | None
    parent_score: float
    matched_chunks: list[RetrievedChunk] = field(default_factory=list)
    sibling_chunks: list[RetrievedChunk] = field(default_factory=list)
    parent_context: RetrievedChunk | None = None
    role_coverage: list[str] = field(default_factory=list)
    score_breakdown: dict[str, Any] = field(default_factory=dict)
    business_facts: dict[str, Any] = field(default_factory=dict)
    debug_info: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LocalLifeEvidencePack:
    query: str
    filters: dict[str, Any]
    parent_evidences: list[ParentEvidence]
    total_child_hits: int
    retrieval_strategy: str
    retrieval_kind: str = "parent_child"
    collection_name: str = LOCAL_LIFE_PARENT_CHILD_COLLECTION
    source_domain: str = "local_life_parent_child"
    route: str = "merchant_reasoning"
    route_reason: str | None = None
    business_facts: dict[str, Any] = field(default_factory=dict)


class LocalLifeParentChildRetriever:
    def __init__(
        self,
        *,
        qdrant_client: Any,
        embedding_adapter: Any,
        collection_name: str = LOCAL_LIFE_PARENT_CHILD_COLLECTION,
        vector_name: str = LOCAL_LIFE_VECTOR_NAME,
        vector_size: int | None = None,
        distance: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._client = qdrant_client
        self._embedding_adapter = embedding_adapter
        self._collection_name = collection_name
        self._vector_name = vector_name
        self._vector_size = vector_size
        self._distance = distance
        self._logger = logger or _LOGGER
        validate_qdrant_collection_shape(
            self._client,
            collection_name=self._collection_name,
            vector_name=self._vector_name,
            vector_size=self._vector_size,
            distance=self._distance,
            action_hint="use the dedicated parent-child seed or reindex command",
        )

    def infer_role_weights(self, query: str, *, route: str | None = None) -> dict[str, float]:
        return _infer_role_weights(query, route=route)

    def retrieve_local_life_evidence(
        self,
        query: str,
        *,
        route: str | None = None,
        city: str | None = None,
        area: str | None = None,
        category: str | None = None,
        business_area: str | None = None,
        shop_type_id: int | None = None,
        shop_id: int | None = None,
        facet: str | None = None,
        scene_tags: list[str] | None = None,
        allowed_facets: list[str] | None = None,
        forbidden_facets: list[str] | None = None,
        candidate_shop_ids: list[int] | None = None,
        child_top_k: int = _DEFAULT_CHILD_TOP_K,
        parent_top_k: int = _DEFAULT_PARENT_TOP_K,
        sibling_limit_per_parent: int = _DEFAULT_SIBLING_LIMIT,
        enable_parent_recall: bool = False,
    ) -> LocalLifeEvidencePack:
        route_value = str(route or "merchant_reasoning").strip() or "merchant_reasoning"
        use_parent_recall = bool(
            enable_parent_recall
            or route_value in {"compare_multi_parent", "recommend_multi_parent", "parent_recall"}
            or route_value.startswith("compare")
        )
        recall_chunk_level = "parent" if use_parent_recall else "child"
        allowed_entity_types = self._allowed_entity_types_for_route(route_value, use_parent_recall=use_parent_recall)
        filters = {
            "city": city,
            "area": area,
            "category": category,
            "business_area": business_area,
            "shop_type_id": shop_type_id,
            "shop_id": shop_id,
            "facet": facet,
            "scene_tags": list(scene_tags or []),
            "allowed_facets": list(allowed_facets or []),
            "forbidden_facets": list(forbidden_facets or []),
            "candidate_shop_ids": list(candidate_shop_ids or []),
            "child_top_k": int(child_top_k),
            "parent_top_k": int(parent_top_k),
            "sibling_limit_per_parent": int(sibling_limit_per_parent),
            "version": LOCAL_LIFE_VERSION,
            "is_latest": True,
            "is_active": True,
            "chunk_level": recall_chunk_level,
            "entity_types": list(allowed_entity_types),
            "parent_recall_enabled": use_parent_recall,
            "route": route_value,
        }
        vector = self._embed_query(query)
        if not vector:
            return LocalLifeEvidencePack(
                query=query,
                filters=filters,
                parent_evidences=[],
                total_child_hits=0,
                retrieval_strategy=_PARENT_RECALL_STRATEGY if use_parent_recall else _RETRIEVAL_STRATEGY,
                retrieval_kind="parent_child",
                collection_name=self._collection_name,
                source_domain="local_life_parent_child",
                route=route_value,
            )

        query_filter = self._build_query_filter(
            city=city,
            area=area,
            category=category,
            business_area=business_area,
            shop_type_id=shop_type_id,
            shop_id=shop_id,
            facet=facet,
            scene_tags=scene_tags or [],
            allowed_facets=allowed_facets or [],
            forbidden_facets=forbidden_facets or [],
            candidate_shop_ids=candidate_shop_ids or [],
            chunk_level=recall_chunk_level,
            entity_types=allowed_entity_types,
        )

        recall_hits, grouped_hits = self._recall_hits(
            vector=vector,
            query_filter=query_filter,
            filters=filters,
            child_top_k=child_top_k,
            parent_top_k=parent_top_k,
            chunk_level=recall_chunk_level,
        )
        if not recall_hits:
            return LocalLifeEvidencePack(
                query=query,
                filters=filters,
                parent_evidences=[],
                total_child_hits=0,
                retrieval_strategy=_PARENT_RECALL_STRATEGY if use_parent_recall else _RETRIEVAL_STRATEGY,
                retrieval_kind="parent_child",
                collection_name=self._collection_name,
                source_domain="local_life_parent_child",
                route=route_value,
            )

        role_weights = self.infer_role_weights(query, route=route_value)
        grouped = grouped_hits or self._group_hits_by_parent(recall_hits)
        parent_evidences: list[ParentEvidence] = []
        for parent_id, matched_chunks in grouped.items():
            if not matched_chunks:
                continue
            matched_chunks = sorted(
                matched_chunks,
                key=lambda item: (-(item.score or 0.0), item.chunk_id),
            )
            parent_context = self.load_parent_chunk(parent_id, entity_type=matched_chunks[0].entity_type)
            parent_meta = parent_context.payload if parent_context is not None else matched_chunks[0].payload
            if parent_context is None and matched_chunks and matched_chunks[0].chunk_level == "parent":
                parent_context = matched_chunks[0]
                parent_meta = matched_chunks[0].payload
            sibling_roles = self._derive_preferred_roles(matched_chunks, parent_meta, parent_context=parent_context)
            sibling_chunks = self.load_sibling_chunks(
                parent_id,
                preferred_roles=sibling_roles,
                limit=sibling_limit_per_parent,
            )
            matched_chunk_ids = {chunk.chunk_id for chunk in matched_chunks}
            if parent_context is not None:
                matched_chunk_ids.add(parent_context.chunk_id)
            sibling_chunks = [chunk for chunk in sibling_chunks if chunk.chunk_id not in matched_chunk_ids]
            role_coverage = self._role_coverage(
                [chunk.chunk_role for chunk in matched_chunks] + [chunk.chunk_role for chunk in sibling_chunks]
            )
            debug_info = self._build_debug_info(
                query=query,
                role_weights=role_weights,
                matched_chunks=matched_chunks,
                sibling_chunks=sibling_chunks,
                role_coverage=role_coverage,
                filters=filters,
                parent_meta=parent_meta,
                parent_context=parent_context,
                use_parent_recall=use_parent_recall,
            )
            parent_score = self._aggregate_parent_score(debug_info)
            evidence = ParentEvidence(
                parent_id=parent_id,
                parent_title=str(
                    get_payload_value(parent_meta, "parent_title")
                    or get_payload_value(parent_meta, "shop_name")
                    or matched_chunks[0].title
                ),
                entity_type=str(get_payload_value(parent_meta, "entity_type") or "shop"),
                entity_id=str(get_payload_value(parent_meta, "entity_id") or parent_id),
                shop_id=self._to_int(get_payload_value(parent_meta, "shop_id")),
                shop_name=_first_text(get_payload_value(parent_meta, "shop_name"), get_payload_value(parent_meta, "parent_title")),
                city=_first_text(get_payload_value(parent_meta, "city")),
                area=_first_text(get_payload_value(parent_meta, "area")),
                category=_first_text(get_payload_value(parent_meta, "subcategory"), get_payload_value(parent_meta, "shop_type_name")),
                parent_score=parent_score,
                matched_chunks=matched_chunks,
                sibling_chunks=sibling_chunks,
                parent_context=parent_context,
                role_coverage=role_coverage,
                score_breakdown=dict(debug_info.get("score_breakdown") or {}),
                business_facts=self._build_business_facts(parent_meta, filters, debug_info=debug_info),
                debug_info=debug_info,
            )
            parent_evidences.append(evidence)

        parent_evidences = rerank_parent_evidences(
            parent_evidences,
            route=route,
        )
        parent_evidences = parent_evidences[: max(0, int(parent_top_k))]
        return LocalLifeEvidencePack(
            query=query,
            filters=filters,
            parent_evidences=parent_evidences,
            total_child_hits=len(recall_hits),
            retrieval_strategy=_PARENT_RECALL_STRATEGY if use_parent_recall else _RETRIEVAL_STRATEGY,
            retrieval_kind="parent_child",
            collection_name=self._collection_name,
            source_domain="local_life_parent_child",
            route=route_value,
        )

    def load_parent_chunk(self, parent_id: str, *, entity_type: str | None = None) -> RetrievedChunk | None:
        query_filter = self._build_parent_filter(parent_id, entity_type=entity_type)
        points = self._scroll_or_query(
            collection_name=self._collection_name,
            query_filter=query_filter,
            limit=3,
        )
        candidates = [chunk for chunk in (self._point_to_retrieved_chunk(point) for point in points) if chunk is not None]
        for candidate in candidates:
            if candidate.chunk_level == "parent" and candidate.parent_id == parent_id:
                return candidate
        return candidates[0] if candidates else None

    def load_parent_chunks(self, parent_ids: Sequence[str]) -> dict[str, RetrievedChunk]:
        normalized_ids = [str(parent_id).strip() for parent_id in parent_ids if str(parent_id).strip()]
        if not normalized_ids:
            return {}
        query_filter = self._build_parent_filter(None, parent_ids=normalized_ids)
        points = self._scroll_or_query(
            collection_name=self._collection_name,
            query_filter=query_filter,
            limit=max(1, len(normalized_ids) * 3),
        )
        loaded: dict[str, RetrievedChunk] = {}
        for chunk in (self._point_to_retrieved_chunk(point) for point in points):
            if chunk is None or chunk.chunk_level != "parent":
                continue
            loaded.setdefault(chunk.parent_id, chunk)
        return loaded

    def load_child_chunks_by_parent(self, parent_id: str, *, limit: int = 50) -> list[RetrievedChunk]:
        query_filter = self._build_child_filter(parent_id)
        points = self._scroll_or_query(
            collection_name=self._collection_name,
            query_filter=query_filter,
            limit=max(1, int(limit)),
        )
        children = [chunk for chunk in (self._point_to_retrieved_chunk(point) for point in points) if chunk is not None]
        children = [chunk for chunk in children if chunk.chunk_level == "child" and chunk.parent_id == parent_id]
        return sorted(children, key=lambda item: (-(item.score or 0.0), item.chunk_id))

    def load_sibling_chunks(
        self,
        parent_id: str,
        *,
        preferred_roles: Sequence[str] | None = None,
        limit: int = _DEFAULT_SIBLING_LIMIT,
        role_limits: Mapping[str, int] | None = None,
    ) -> list[RetrievedChunk]:
        query_filter = self._build_sibling_filter(parent_id)
        points = self._scroll_or_query(collection_name=self._collection_name, query_filter=query_filter, limit=max(1, int(limit) * 3))
        siblings: list[RetrievedChunk] = []
        seen_chunk_ids: set[str] = set()
        role_counts: dict[str, int] = defaultdict(int)
        role_caps = dict(_ROLE_SIBLING_CAPS)
        if role_limits:
            for role, cap in role_limits.items():
                try:
                    role_caps[str(role)] = max(1, int(cap))
                except Exception:
                    continue
        preferred_roles = [role for role in (preferred_roles or []) if role]
        preferred_rank = {role: index for index, role in enumerate(preferred_roles)}
        candidates = [chunk for chunk in (self._point_to_retrieved_chunk(point) for point in points) if chunk is not None]
        candidates.sort(
            key=lambda item: (
                0 if item.chunk_role in preferred_rank else 1,
                preferred_rank.get(item.chunk_role, len(preferred_rank)),
                0 if self._is_true(item.payload, "is_latest") else 1,
                0 if self._is_true(item.payload, "is_active") else 1,
                0 if str(get_payload_value(item.payload, "version") or "") == LOCAL_LIFE_VERSION else 1,
                item.chunk_id,
            )
        )
        for candidate in candidates:
            if candidate.chunk_id in seen_chunk_ids:
                continue
            if candidate.chunk_level and candidate.chunk_level != "child":
                continue
            role = candidate.chunk_role
            role_cap = role_caps.get(role, 1)
            if role_counts[role] >= role_cap:
                continue
            siblings.append(candidate)
            seen_chunk_ids.add(candidate.chunk_id)
            role_counts[role] += 1
            if len(siblings) >= int(limit):
                break
        return siblings

    def to_evidence_claims(self, pack: LocalLifeEvidencePack, *, limit: int = 8) -> list[EvidenceClaim]:
        claims: list[EvidenceClaim] = []
        seen_chunk_ids: set[str] = set()
        for parent in pack.parent_evidences:
            for chunk in [*parent.matched_chunks, *parent.sibling_chunks]:
                if chunk.chunk_id in seen_chunk_ids:
                    continue
                seen_chunk_ids.add(chunk.chunk_id)
                claims.append(
                    EvidenceClaim(
                        chunk_id=chunk.chunk_id,
                        shop_id=parent.shop_id,
                        claim=self._claim_text(chunk),
                        support_text=chunk.text,
                        source_type=chunk.chunk_role or chunk.source_type or "local_life",
                        confidence=self._chunk_confidence(chunk, parent.parent_score),
                        metadata={
                            **dict(chunk.payload),
                            "parent_id": parent.parent_id,
                            "parent_title": parent.parent_title,
                            "parent_context_chunk_id": parent.parent_context.chunk_id if parent.parent_context else None,
                            "parent_context_role": parent.parent_context.chunk_role if parent.parent_context else None,
                            "parent_score": parent.parent_score,
                            "chunk_role": chunk.chunk_role,
                            "retrieval_strategy": pack.retrieval_strategy,
                            "retrieval_kind": pack.retrieval_kind,
                            "collection_name": pack.collection_name,
                            "source_domain": pack.source_domain,
                            "route": pack.route,
                            "score_breakdown": dict(parent.score_breakdown),
                            "business_facts": dict(parent.business_facts),
                        },
                    )
                )
                if len(claims) >= max(0, int(limit)):
                    return claims
        return claims

    def _claim_text(self, chunk: RetrievedChunk) -> str:
        role = chunk.chunk_role or chunk.source_type
        title = chunk.title or chunk.chunk_id
        mapping = {
            "merchant_profile": "商家介绍证据",
            "merchant_review_summary": "评价摘要证据",
            "merchant_scene_fit": "适合场景证据",
            "merchant_pitfall_summary": "避坑信息证据",
            "package_description": "套餐优惠证据",
            "merchant_blog_note": "探店笔记证据",
            "local_guide": "本地攻略证据",
            "platform_rule": "平台规则证据",
        }
        return f"{mapping.get(role, '检索证据')}：{title}"

    def _chunk_confidence(self, chunk: RetrievedChunk, parent_score: float) -> float:
        score = chunk.score if chunk.score is not None else parent_score
        return max(0.0, min(float(score), 1.0))

    def _embed_query(self, query: str) -> list[float]:
        if self._embedding_adapter is None:
            return []
        if hasattr(self._embedding_adapter, "embed"):
            vector = self._embedding_adapter.embed(query)
        elif callable(self._embedding_adapter):
            vector = self._embedding_adapter(query)
        else:
            raise RuntimeError("Embedding adapter does not expose embed capability")
        return list(vector or [])

    def _recall_hits(
        self,
        *,
        vector: Sequence[float],
        query_filter: Any,
        filters: Mapping[str, Any],
        child_top_k: int,
        parent_top_k: int,
        chunk_level: str,
    ) -> tuple[list[RetrievedChunk], dict[str, list[RetrievedChunk]]]:
        grouped_response = self._query_points_groups(
            vector=vector,
            query_filter=query_filter,
            limit=max(1, int(parent_top_k)),
            group_size=3,
        )
        grouped_hits = self._groups_to_parent_hits(grouped_response)
        if grouped_hits:
            child_hits = [hit for hits in grouped_hits.values() for hit in hits if self._matches_filters(hit.payload, filters)]
            grouped_hits = self._group_hits_by_parent(child_hits)
            return child_hits, grouped_hits
        raw_points = self._query_points(vector=vector, query_filter=query_filter, limit=max(1, int(child_top_k)))
        child_hits = [chunk for chunk in (self._point_to_retrieved_chunk(point) for point in raw_points) if chunk is not None]
        child_hits = [chunk for chunk in child_hits if self._matches_filters(chunk.payload, filters)]
        return child_hits, self._group_hits_by_parent(child_hits)

    def _recall_child_hits(
        self,
        *,
        vector: Sequence[float],
        query_filter: Any,
        filters: Mapping[str, Any],
        child_top_k: int,
        parent_top_k: int,
    ) -> tuple[list[RetrievedChunk], dict[str, list[RetrievedChunk]]]:
        return self._recall_hits(
            vector=vector,
            query_filter=query_filter,
            filters=filters,
            child_top_k=child_top_k,
            parent_top_k=parent_top_k,
            chunk_level="child",
        )

    def _query_points_groups(self, *, vector: Sequence[float], query_filter: Any, limit: int, group_size: int) -> Any:
        search_fn = getattr(self._client, "query_points_groups", None)
        if not callable(search_fn):
            return None
        try:
            return search_fn(
                collection_name=self._collection_name,
                group_by="parent_id",
                query=list(vector),
                using=self._vector_name,
                query_filter=query_filter,
                limit=max(1, int(limit)),
                group_size=max(1, int(group_size)),
                with_payload=True,
            )
        except TypeError:
            try:
                return search_fn(
                    collection_name=self._collection_name,
                    group_by="parent_id",
                    query=list(vector),
                    using=self._vector_name,
                    query_filter=query_filter,
                    limit=max(1, int(limit)),
                    group_size=max(1, int(group_size)),
                    with_payload=True,
                    with_vectors=False,
                )
            except Exception:
                return None
        except Exception:
            self._logger.exception("local_life_qdrant_group_query_failed")
            return None

    def _groups_to_parent_hits(self, response: Any) -> dict[str, list[RetrievedChunk]]:
        groups = _normalize_groups_response(response)
        grouped: dict[str, list[RetrievedChunk]] = {}
        for group in groups:
            parent_id = _group_parent_id(group)
            if not parent_id:
                continue
            hits: list[RetrievedChunk] = []
            for item in _group_items(group):
                chunk = self._point_to_retrieved_chunk(item)
                if chunk is None:
                    continue
                hits.append(chunk)
            if hits:
                grouped[parent_id] = sorted(hits, key=lambda item: (-(item.score or 0.0), item.chunk_id))
        return grouped

    def _query_points(self, *, vector: Sequence[float], query_filter: Any, limit: int) -> list[Any]:
        search_fn = getattr(self._client, "query_points", None) or getattr(self._client, "search", None)
        if not callable(search_fn):
            return []
        try:
            response = search_fn(
                collection_name=self._collection_name,
                query=list(vector),
                using=self._vector_name,
                query_filter=query_filter,
                limit=max(1, int(limit)),
                with_payload=True,
                with_vectors=False,
            )
        except TypeError:
            response = search_fn(
                collection_name=self._collection_name,
                query=list(vector),
                using=self._vector_name,
                filter=query_filter,
                limit=max(1, int(limit)),
                with_payload=True,
                with_vectors=False,
            )
        return _normalize_points(response)

    def _scroll_or_query(self, *, collection_name: str, query_filter: Any, limit: int) -> list[Any]:
        scroll_fn = getattr(self._client, "scroll", None)
        if callable(scroll_fn):
            try:
                page = scroll_fn(
                    collection_name=collection_name,
                    scroll_filter=query_filter,
                    limit=max(1, int(limit)),
                    with_payload=True,
                    with_vectors=False,
                )
            except TypeError:
                page = scroll_fn(
                    collection_name=collection_name,
                    query_filter=query_filter,
                    limit=max(1, int(limit)),
                    with_payload=True,
                    with_vectors=False,
                )
            points, _ = _normalize_scroll_page(page)
            if points:
                return list(points)
        query_fn = getattr(self._client, "query_points", None) or getattr(self._client, "search", None)
        if not callable(query_fn):
            return []
        try:
            response = query_fn(
                collection_name=collection_name,
                query=None,
                using=self._vector_name,
                query_filter=query_filter,
                limit=max(1, int(limit)),
                with_payload=True,
                with_vectors=False,
            )
        except TypeError:
            response = query_fn(
                collection_name=collection_name,
                query=None,
                using=self._vector_name,
                filter=query_filter,
                limit=max(1, int(limit)),
                with_payload=True,
                with_vectors=False,
            )
        return _normalize_points(response)

    def _build_query_filter(
        self,
        *,
        city: str | None,
        area: str | None,
        category: str | None,
        business_area: str | None,
        shop_type_id: int | None,
        shop_id: int | None,
        facet: str | None,
        scene_tags: Sequence[str] | None,
        allowed_facets: Sequence[str] | None,
        forbidden_facets: Sequence[str] | None,
        candidate_shop_ids: Sequence[int],
        chunk_level: str | None = None,
        entity_types: Sequence[str] | None = None,
    ) -> Any:
        must: list[Any] = [
            FieldCondition(key="version", match=MatchValue(value=LOCAL_LIFE_VERSION)),
            FieldCondition(key="is_latest", match=MatchValue(value=True)),
            FieldCondition(key="is_active", match=MatchValue(value=True)),
        ]
        if chunk_level:
            must.append(FieldCondition(key="chunk_level", match=MatchValue(value=str(chunk_level))))
        if city:
            must.append(FieldCondition(key="city", match=MatchValue(value=city)))
        if area:
            must.append(FieldCondition(key="area", match=MatchValue(value=area)))
        if category:
            must.append(FieldCondition(key="subcategory", match=MatchValue(value=category)))
        if business_area:
            must.append(FieldCondition(key="business_area", match=MatchValue(value=business_area)))
        if shop_type_id is not None:
            must.append(FieldCondition(key="shop_type_id", match=MatchValue(value=int(shop_type_id))))
        if shop_id is not None:
            must.append(FieldCondition(key="shop_id", match=MatchValue(value=int(shop_id))))
        if facet:
            must.append(FieldCondition(key="facet", match=MatchValue(value=facet)))
        normalized_scene_tags = [str(item).strip() for item in (scene_tags or []) if str(item).strip()]
        if normalized_scene_tags:
            if len(normalized_scene_tags) == 1:
                must.append(FieldCondition(key="scene_tags", match=MatchValue(value=normalized_scene_tags[0])))
            else:
                must.append(FieldCondition(key="scene_tags", match=MatchAny(any=normalized_scene_tags)))
        normalized_allowed_facets = [str(item).strip() for item in (allowed_facets or []) if str(item).strip()]
        if normalized_allowed_facets:
            if len(normalized_allowed_facets) == 1:
                must.append(FieldCondition(key="facet", match=MatchValue(value=normalized_allowed_facets[0])))
            else:
                must.append(FieldCondition(key="facet", match=MatchAny(any=normalized_allowed_facets)))
        normalized_forbidden_facets = [str(item).strip() for item in (forbidden_facets or []) if str(item).strip()]
        if normalized_forbidden_facets:
            must_not = [FieldCondition(key="facet", match=MatchAny(any=normalized_forbidden_facets))]
        else:
            must_not = []
        normalized_entity_types = [str(item).strip() for item in (entity_types or []) if str(item).strip()]
        if normalized_entity_types:
            if len(normalized_entity_types) == 1:
                must.append(FieldCondition(key="entity_type", match=MatchValue(value=normalized_entity_types[0])))
            else:
                must.append(FieldCondition(key="entity_type", match=MatchAny(any=normalized_entity_types)))
        candidate_ids: list[int] = []
        for shop_id in candidate_shop_ids:
            try:
                candidate_ids.append(int(shop_id))
            except Exception:
                continue
        if candidate_shop_ids:
            if candidate_ids:
                must.append(FieldCondition(key="shop_id", match=MatchAny(any=candidate_ids)))
            else:
                must.append(FieldCondition(key="shop_id", match=MatchValue(value=-1)))
        return Filter(must=must, must_not=must_not or None)

    def _build_parent_filter(self, parent_id: str | None, *, entity_type: str | None = None, parent_ids: Sequence[str] | None = None) -> Any:
        must: list[Any] = [
            FieldCondition(key="version", match=MatchValue(value=LOCAL_LIFE_VERSION)),
            FieldCondition(key="is_latest", match=MatchValue(value=True)),
            FieldCondition(key="is_active", match=MatchValue(value=True)),
            FieldCondition(key="chunk_level", match=MatchValue(value="parent")),
        ]
        normalized_parent_ids = [str(item).strip() for item in (parent_ids or []) if str(item).strip()]
        if normalized_parent_ids:
            if len(normalized_parent_ids) == 1:
                must.append(FieldCondition(key="parent_id", match=MatchValue(value=normalized_parent_ids[0])))
            else:
                must.append(FieldCondition(key="parent_id", match=MatchAny(any=normalized_parent_ids)))
        elif parent_id:
            must.append(FieldCondition(key="parent_id", match=MatchValue(value=parent_id)))
        if entity_type:
            must.append(FieldCondition(key="entity_type", match=MatchValue(value=entity_type)))
        return Filter(must=must)

    def _build_child_filter(self, parent_id: str, *, entity_types: Sequence[str] | None = None) -> Any:
        must: list[Any] = [
            FieldCondition(key="parent_id", match=MatchValue(value=parent_id)),
            FieldCondition(key="version", match=MatchValue(value=LOCAL_LIFE_VERSION)),
            FieldCondition(key="is_latest", match=MatchValue(value=True)),
            FieldCondition(key="is_active", match=MatchValue(value=True)),
            FieldCondition(key="chunk_level", match=MatchValue(value="child")),
        ]
        normalized_entity_types = [str(item).strip() for item in (entity_types or []) if str(item).strip()]
        if normalized_entity_types:
            if len(normalized_entity_types) == 1:
                must.append(FieldCondition(key="entity_type", match=MatchValue(value=normalized_entity_types[0])))
            else:
                must.append(FieldCondition(key="entity_type", match=MatchAny(any=normalized_entity_types)))
        return Filter(must=must)

    def _build_sibling_filter(self, parent_id: str) -> Any:
        return self._build_child_filter(parent_id)

    def _group_hits_by_parent(self, hits: Sequence[RetrievedChunk]) -> dict[str, list[RetrievedChunk]]:
        grouped: dict[str, list[RetrievedChunk]] = defaultdict(list)
        for hit in hits:
            grouped[hit.parent_id].append(hit)
        return {
            parent_id: sorted(items, key=lambda item: (-(item.score or 0.0), item.chunk_id))
            for parent_id, items in grouped.items()
            if items
        }

    def _build_debug_info(
        self,
        *,
        query: str,
        role_weights: Mapping[str, float],
        matched_chunks: Sequence[RetrievedChunk],
        sibling_chunks: Sequence[RetrievedChunk],
        role_coverage: Sequence[str],
        filters: Mapping[str, Any],
        parent_meta: Mapping[str, Any],
        parent_context: RetrievedChunk | None = None,
        use_parent_recall: bool = False,
    ) -> dict[str, Any]:
        adjusted_scores = [
            self._adjusted_child_score(chunk, role_weights)
            for chunk in matched_chunks
        ]
        max_child_score = max(adjusted_scores) if adjusted_scores else 0.0
        avg_top_child_score = sum(adjusted_scores[:3]) / min(3, len(adjusted_scores)) if adjusted_scores else 0.0
        role_coverage_score = self._role_coverage_score(role_coverage)
        preferred_roles = [
            role
            for role, weight in role_weights.items()
            if weight >= 1.15 and role
        ]
        preferred_role_coverage_score = self._role_coverage_score(
            [role for role in role_coverage if role in preferred_roles]
        )
        parent_summary_match_score = self._parent_summary_match_score(
            query=query,
            parent_context=parent_context,
            parent_meta=parent_meta,
        )
        freshness_score = self._freshness_score(parent_meta)
        semantic_parent_score = (
            max_child_score * 0.32
            + avg_top_child_score * 0.2
            + role_coverage_score * 0.14
            + preferred_role_coverage_score * 0.12
            + parent_summary_match_score * 0.12
            + freshness_score * 0.1
        )
        business_filter_match_score = self._business_boost_score(parent_meta, filters)
        return {
            "query": query,
            "role_weights": dict(role_weights),
            "matched_roles": [chunk.chunk_role for chunk in matched_chunks],
            "sibling_roles": [chunk.chunk_role for chunk in sibling_chunks],
            "adjusted_child_scores": adjusted_scores,
            "max_child_score": max_child_score,
            "avg_top_child_score": avg_top_child_score,
            "role_coverage_score": role_coverage_score,
            "preferred_role_coverage_score": preferred_role_coverage_score,
            "parent_summary_match_score": parent_summary_match_score,
            "freshness_score": freshness_score,
            "semantic_parent_score": semantic_parent_score,
            "business_filter_match_score": business_filter_match_score,
            "business_boost_score": business_filter_match_score,
            "matched_child_count": len(matched_chunks),
            "sibling_child_count": len(sibling_chunks),
            "filters": dict(filters),
            "use_parent_recall": use_parent_recall,
            "parent_context": {
                "chunk_id": parent_context.chunk_id if parent_context is not None else None,
                "chunk_level": parent_context.chunk_level if parent_context is not None else None,
                "chunk_role": parent_context.chunk_role if parent_context is not None else None,
                "parent_id": parent_context.parent_id if parent_context is not None else None,
                "title": parent_context.title if parent_context is not None else None,
            },
            "score_breakdown": {
                "max_child_score": max_child_score,
                "avg_top_child_score": avg_top_child_score,
                "role_coverage_score": role_coverage_score,
                "preferred_role_coverage_score": preferred_role_coverage_score,
                "parent_summary_match_score": parent_summary_match_score,
                "freshness_score": freshness_score,
                "semantic_parent_score": semantic_parent_score,
                "business_filter_match_score": business_filter_match_score,
                "parent_score": min(
                    1.0,
                    max(
                        0.0,
                        semantic_parent_score + (business_filter_match_score * 0.06),
                    ),
                ),
            },
        }

    def _aggregate_parent_score(self, debug_info: Mapping[str, Any]) -> float:
        max_child_score = float(debug_info.get("max_child_score") or 0.0)
        avg_top_child_score = float(debug_info.get("avg_top_child_score") or 0.0)
        role_coverage_score = float(debug_info.get("role_coverage_score") or 0.0)
        preferred_role_coverage_score = float(debug_info.get("preferred_role_coverage_score") or 0.0)
        parent_summary_match_score = float(debug_info.get("parent_summary_match_score") or 0.0)
        freshness_score = float(debug_info.get("freshness_score") or 0.0)
        business_boost_score = float(debug_info.get("business_filter_match_score") or debug_info.get("business_boost_score") or 0.0)
        parent_score = (
            max_child_score * 0.3
            + avg_top_child_score * 0.18
            + role_coverage_score * 0.14
            + preferred_role_coverage_score * 0.12
            + parent_summary_match_score * 0.12
            + freshness_score * 0.08
            + business_boost_score * 0.06
        )
        return max(0.0, min(parent_score, 1.0))

    def _adjusted_child_score(self, chunk: RetrievedChunk, role_weights: Mapping[str, float]) -> float:
        base_score = float(chunk.score or 0.0)
        role_weight = float(role_weights.get(chunk.chunk_role, 1.0))
        return max(0.0, min(base_score * role_weight, 1.0))

    def _role_coverage(self, roles: Sequence[str]) -> list[str]:
        seen: list[str] = []
        for role in roles:
            if role and role not in seen:
                seen.append(role)
        seen.sort(key=lambda role: (_ROLE_COVERAGE_WEIGHTS.get(role, 0.2) * -1.0, role))
        return seen

    def _role_coverage_score(self, roles: Sequence[str]) -> float:
        score = 0.0
        seen: set[str] = set()
        for role in roles:
            if not role or role in seen:
                continue
            seen.add(role)
            score += _ROLE_COVERAGE_WEIGHTS.get(role, 0.2)
        return max(0.0, min(score, 1.0))

    def _business_boost_score(self, parent_meta: Mapping[str, Any], filters: Mapping[str, Any]) -> float:
        requested = 0
        matched = 0
        parent_city = _first_text(get_payload_value(parent_meta, "city"))
        parent_area = _first_text(get_payload_value(parent_meta, "area"))
        parent_category = _first_text(get_payload_value(parent_meta, "subcategory"), get_payload_value(parent_meta, "shop_type_name"))
        parent_shop_type_id = self._to_int(get_payload_value(parent_meta, "shop_type_id"))
        parent_shop_id = self._to_int(get_payload_value(parent_meta, "shop_id"))

        city = _first_text(filters.get("city"))
        if city:
            requested += 1
            if _normalize_text(parent_city) == _normalize_text(city):
                matched += 1
        area = _first_text(filters.get("area"))
        if area:
            requested += 1
            if _normalize_text(parent_area) == _normalize_text(area):
                matched += 1
        category = _first_text(filters.get("category"))
        if category:
            requested += 1
            if _normalize_text(parent_category) == _normalize_text(category):
                matched += 1
        shop_type_id = filters.get("shop_type_id")
        if shop_type_id is not None:
            requested += 1
            if parent_shop_type_id is not None and int(parent_shop_type_id) == int(shop_type_id):
                matched += 1
        candidate_shop_ids = filters.get("candidate_shop_ids") or []
        if candidate_shop_ids:
            requested += 1
            if parent_shop_id is not None and int(parent_shop_id) in {int(item) for item in candidate_shop_ids if item is not None}:
                matched += 1
        if requested <= 0:
            return 0.0
        return max(0.0, min(matched / requested, 1.0))

    def _parent_summary_match_score(
        self,
        *,
        query: str,
        parent_context: RetrievedChunk | None,
        parent_meta: Mapping[str, Any],
    ) -> float:
        haystack_parts = [
            _first_text(get_payload_value(parent_meta, "parent_title")),
            _first_text(get_payload_value(parent_meta, "summary")),
            _first_text(get_payload_value(parent_meta, "text")),
        ]
        if parent_context is not None:
            haystack_parts.extend([parent_context.title, parent_context.text])
        haystack = " ".join(part for part in haystack_parts if part).strip()
        return self._lexical_overlap_score(query, haystack)

    def _freshness_score(self, parent_meta: Mapping[str, Any]) -> float:
        is_latest = self._is_true(parent_meta, "is_latest")
        is_active = self._is_true(parent_meta, "is_active")
        if is_latest and is_active:
            return 1.0
        if is_latest or is_active:
            return 0.6
        return 0.0

    def _build_business_facts(
        self,
        parent_meta: Mapping[str, Any],
        filters: Mapping[str, Any],
        *,
        debug_info: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        debug_info = debug_info or {}
        candidate_shop_ids = [int(item) for item in filters.get("candidate_shop_ids") or [] if self._to_int(item) is not None]
        shop_id = self._to_int(get_payload_value(parent_meta, "shop_id"))
        business_facts = {
            "shop_id": shop_id,
            "shop_name": _first_text(get_payload_value(parent_meta, "shop_name"), get_payload_value(parent_meta, "parent_title")),
            "parent_id": _first_text(get_payload_value(parent_meta, "parent_id")) or str(get_payload_value(parent_meta, "entity_id") or shop_id or ""),
            "parent_chunk_id": _first_text(get_payload_value(parent_meta, "parent_chunk_id")),
            "parent_title": _first_text(get_payload_value(parent_meta, "parent_title")),
            "entity_type": _first_text(get_payload_value(parent_meta, "entity_type")) or "shop",
            "entity_id": _first_text(get_payload_value(parent_meta, "entity_id")) or str(shop_id or ""),
            "chunk_level": _first_text(get_payload_value(parent_meta, "chunk_level")),
            "chunk_role": _first_text(get_payload_value(parent_meta, "chunk_role")),
            "city": _first_text(get_payload_value(parent_meta, "city")),
            "area": _first_text(get_payload_value(parent_meta, "area")),
            "business_area": _first_text(get_payload_value(parent_meta, "business_area"), get_payload_value(parent_meta, "area")),
            "category": _first_text(get_payload_value(parent_meta, "subcategory"), get_payload_value(parent_meta, "shop_type_name")),
            "shop_type_id": self._to_int(get_payload_value(parent_meta, "shop_type_id")),
            "open_hours": _first_text(get_payload_value(parent_meta, "open_hours"), get_payload_value(parent_meta, "openHours")),
            "distance_km": get_payload_value(parent_meta, "distance_km"),
            "avg_price": get_payload_value(parent_meta, "avg_price"),
            "score": get_payload_value(parent_meta, "score"),
            "comments": get_payload_value(parent_meta, "comments"),
            "facet": _first_text(get_payload_value(parent_meta, "facet"), get_payload_value(parent_meta, "chunk_role"), get_payload_value(parent_meta, "chunk_type")),
            "scene_tags": (
                [str(get_payload_value(parent_meta, "scene_tags"))]
                if isinstance(get_payload_value(parent_meta, "scene_tags"), str)
                else list(get_payload_value(parent_meta, "scene_tags") or get_payload_value(parent_meta, "tags") or [])
            ),
            "parking": self._is_true(parent_meta, "parking"),
            "quiet_score": float(get_payload_value(parent_meta, "quiet_score") or 0.0),
            "family_friendly": self._is_true(parent_meta, "family_friendly"),
            "elder_friendly": self._is_true(parent_meta, "elder_friendly"),
            "tags": list(get_payload_value(parent_meta, "tags") or []),
            "version": _first_text(get_payload_value(parent_meta, "version")),
            "is_latest": self._is_true(parent_meta, "is_latest"),
            "is_active": self._is_true(parent_meta, "is_active"),
            "candidate_shop_ids": candidate_shop_ids,
            "business_filter_match_score": float(debug_info.get("business_filter_match_score") or debug_info.get("business_boost_score") or 0.0),
        }
        business_facts["matches_candidate_filter"] = bool(
            not candidate_shop_ids or (shop_id is not None and int(shop_id) in set(candidate_shop_ids))
        )
        return {key: value for key, value in business_facts.items() if value not in (None, "", [], {}, ())}

    def _derive_preferred_roles(
        self,
        matched_chunks: Sequence[RetrievedChunk],
        parent_meta: Mapping[str, Any],
        *,
        parent_context: RetrievedChunk | None = None,
    ) -> list[str]:
        roles = [chunk.chunk_role for chunk in matched_chunks if chunk.chunk_role]
        if parent_context is not None and parent_context.chunk_role:
            roles.append(parent_context.chunk_role)
        sibling_roles = get_payload_value(parent_meta, "sibling_roles")
        if isinstance(sibling_roles, Sequence) and not isinstance(sibling_roles, (str, bytes)):
            roles.extend(str(role) for role in sibling_roles if str(role).strip())
        preferred: list[str] = []
        for role in roles:
            if role not in preferred:
                preferred.append(role)
        return preferred

    def _point_to_retrieved_chunk(self, point: Any) -> RetrievedChunk | None:
        payload = _point_payload(point)
        if not payload:
            return None
        normalized_payload = _flatten_payload(payload)
        chunk = KnowledgeChunk.from_payload(
            normalized_payload,
            fallback_chunk_id=str(_point_id(point) or normalized_payload.get("chunk_id") or ""),
            fallback_document_id=str(
                normalized_payload.get("document_id")
                or normalized_payload.get("doc_id")
                or normalized_payload.get("source_id")
                or normalized_payload.get("chunk_id")
                or ""
            )
            or None,
        )
        if chunk is None:
            return None
        parent_id = chunk.parent_id or _first_text(get_payload_value(normalized_payload, "parent_id"))
        if not parent_id:
            parent_id = str(normalized_payload.get("entity_id") or normalized_payload.get("shop_id") or "")
        if not parent_id:
            return None
        return RetrievedChunk(
            point_id=str(_point_id(point) or chunk.chunk_id),
            chunk_id=chunk.chunk_id,
            parent_id=parent_id,
            parent_chunk_id=_first_text(get_payload_value(normalized_payload, "parent_chunk_id")),
            chunk_role=str(get_payload_value(normalized_payload, "chunk_role") or chunk.chunk_type or chunk.source_type or ""),
            source_type=str(get_payload_value(normalized_payload, "source_type") or chunk.source_type or ""),
            chunk_level=_first_text(get_payload_value(normalized_payload, "chunk_level")) or chunk.chunk_level,
            parent_title=_first_text(get_payload_value(normalized_payload, "parent_title")) or chunk.parent_title,
            entity_type=_first_text(get_payload_value(normalized_payload, "entity_type")) or chunk.entity_type,
            entity_id=_first_text(get_payload_value(normalized_payload, "entity_id")) or chunk.entity_id,
            title=chunk.title,
            text=chunk.text,
            score=_point_score(point),
            payload=dict(normalized_payload),
        )

    def _matches_filters(self, payload: Mapping[str, Any], filters: Mapping[str, Any]) -> bool:
        # Qdrant already filters most cases. This helper protects fallback and mock responses.
        city = _first_text(get_payload_value(payload, "city"))
        area = _first_text(get_payload_value(payload, "area"))
        category = _first_text(get_payload_value(payload, "subcategory"), get_payload_value(payload, "shop_type_name"))
        business_area = _first_text(get_payload_value(payload, "business_area"), get_payload_value(payload, "area"))
        shop_type_id = self._to_int(get_payload_value(payload, "shop_type_id"))
        shop_id = self._to_int(get_payload_value(payload, "shop_id"))
        version = _first_text(get_payload_value(payload, "version"))
        chunk_level = _first_text(get_payload_value(payload, "chunk_level"))
        entity_type = _first_text(get_payload_value(payload, "entity_type"))
        facet = _first_text(get_payload_value(payload, "facet"), get_payload_value(payload, "chunk_role"), get_payload_value(payload, "chunk_type"))
        scene_tag_values = get_payload_value(payload, "scene_tags") or get_payload_value(payload, "tags") or []
        if isinstance(scene_tag_values, str):
            scene_tag_values = [scene_tag_values]
        elif not isinstance(scene_tag_values, Sequence) or isinstance(scene_tag_values, (bytes, bytearray)):
            scene_tag_values = [scene_tag_values]
        scene_tags = {
            _normalize_text(str(tag))
            for tag in scene_tag_values
            if str(tag).strip()
        }
        if not chunk_level:
            parent_chunk_id = _first_text(get_payload_value(payload, "parent_chunk_id"))
            chunk_id = _first_text(get_payload_value(payload, "chunk_id"))
            if parent_chunk_id and chunk_id and _normalize_text(parent_chunk_id) == _normalize_text(chunk_id):
                chunk_level = "parent"
            elif _first_text(get_payload_value(payload, "parent_id")):
                chunk_level = "child"
        is_latest = self._is_true(payload, "is_latest")
        is_active = self._is_true(payload, "is_active")
        if version and version != LOCAL_LIFE_VERSION:
            return False
        if not is_latest or not is_active:
            return False
        requested_chunk_level = _first_text(filters.get("chunk_level"))
        if requested_chunk_level and _normalize_text(chunk_level) != _normalize_text(requested_chunk_level):
            return False
        requested_city = _first_text(filters.get("city"))
        if requested_city and _normalize_text(city) != _normalize_text(requested_city):
            return False
        requested_area = _first_text(filters.get("area"))
        if requested_area and _normalize_text(area) != _normalize_text(requested_area):
            return False
        requested_category = _first_text(filters.get("category"))
        if requested_category and _normalize_text(category) != _normalize_text(requested_category):
            return False
        requested_business_area = _first_text(filters.get("business_area"))
        if requested_business_area and _normalize_text(business_area) != _normalize_text(requested_business_area):
            return False
        requested_shop_type_id = filters.get("shop_type_id")
        if requested_shop_type_id is not None and shop_type_id is not None and int(shop_type_id) != int(requested_shop_type_id):
            return False
        requested_shop_id = filters.get("shop_id")
        if requested_shop_id is not None and shop_id is not None and int(shop_id) != int(requested_shop_id):
            return False
        requested_entity_types = [str(item).strip() for item in filters.get("entity_types") or [] if str(item).strip()]
        if requested_entity_types and _normalize_text(entity_type) not in {_normalize_text(item) for item in requested_entity_types}:
            return False
        requested_facet = _first_text(filters.get("facet"))
        if requested_facet and _normalize_text(facet) != _normalize_text(requested_facet):
            return False
        requested_allowed_facets_values = filters.get("allowed_facets") or []
        if isinstance(requested_allowed_facets_values, str):
            requested_allowed_facets_values = [requested_allowed_facets_values]
        requested_allowed_facets = [str(item).strip() for item in requested_allowed_facets_values if str(item).strip()]
        if requested_allowed_facets and _normalize_text(facet) not in {_normalize_text(item) for item in requested_allowed_facets}:
            return False
        requested_forbidden_facets_values = filters.get("forbidden_facets") or []
        if isinstance(requested_forbidden_facets_values, str):
            requested_forbidden_facets_values = [requested_forbidden_facets_values]
        requested_forbidden_facets = [str(item).strip() for item in requested_forbidden_facets_values if str(item).strip()]
        if requested_forbidden_facets and _normalize_text(facet) in {_normalize_text(item) for item in requested_forbidden_facets}:
            return False
        requested_scene_tags_values = filters.get("scene_tags") or []
        if isinstance(requested_scene_tags_values, str):
            requested_scene_tags_values = [requested_scene_tags_values]
        requested_scene_tags = [str(item).strip() for item in requested_scene_tags_values if str(item).strip()]
        if requested_scene_tags and not scene_tags.intersection({_normalize_text(item) for item in requested_scene_tags}):
            return False
        candidate_shop_ids = {int(item) for item in filters.get("candidate_shop_ids") or [] if item is not None}
        if candidate_shop_ids and (shop_id is None or int(shop_id) not in candidate_shop_ids):
            return False
        return True

    def _build_query_filter_from_payload(self, **kwargs: Any) -> Any:
        return self._build_query_filter(**kwargs)

    @staticmethod
    def _compact_query(query: str) -> str:
        return str(query or "").replace(" ", "").lower()

    def _allowed_entity_types_for_route(self, route: str, *, use_parent_recall: bool) -> tuple[str, ...]:
        route_value = str(route or "").strip().lower()
        if route_value == "guide_rule_rag":
            return _DEFAULT_GUIDE_RULE_ENTITY_TYPES
        if use_parent_recall and route_value.startswith("compare"):
            return _DEFAULT_CHILD_ENTITY_TYPES
        return _DEFAULT_CHILD_ENTITY_TYPES

    def _lexical_overlap_score(self, query: str, text: str) -> float:
        query_tokens = [token for token in re.findall(r"[\u4e00-\u9fff]+|[A-Za-z0-9_+#.:-]+", str(query or "").lower()) if token]
        text_value = str(text or "").lower()
        if not query_tokens or not text_value:
            return 0.0
        matched = 0
        for token in dict.fromkeys(query_tokens):
            if token and token in text_value:
                matched += 1
        return max(0.0, min(matched / max(1, len(dict.fromkeys(query_tokens))), 1.0))

    @staticmethod
    def _to_int(value: Any) -> int | None:
        if value in (None, "", []):
            return None
        try:
            return int(value)
        except Exception:
            return None

    @staticmethod
    def _is_true(payload: Mapping[str, Any], key: str) -> bool:
        value = get_payload_value(payload, key)
        return str(value).lower() in {"1", "true", "yes", "y"} or value is True


def get_payload_value(payload: Any, key: str, default: Any = None) -> Any:
    if isinstance(payload, Mapping):
        if key in payload and payload[key] not in (None, ""):
            return payload[key]
        metadata = payload.get("metadata")
        if isinstance(metadata, Mapping) and key in metadata and metadata[key] not in (None, ""):
            return metadata[key]
        if "." in key:
            current: Any = payload
            for part in key.split("."):
                if not isinstance(current, Mapping):
                    current = None
                    break
                current = current.get(part)
            if current not in (None, ""):
                return current
    return default


def _flatten_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    metadata = normalized.get("metadata")
    if isinstance(metadata, Mapping):
        for key, value in metadata.items():
            normalized.setdefault(key, value)
    return normalized


def _point_payload(point: Any) -> dict[str, Any]:
    if isinstance(point, Mapping):
        payload = point.get("payload")
        return dict(payload) if isinstance(payload, Mapping) else {}
    payload = getattr(point, "payload", None)
    if isinstance(payload, Mapping):
        return dict(payload)
    return {}


def _point_id(point: Any) -> str | None:
    if isinstance(point, Mapping):
        value = point.get("id")
    else:
        value = getattr(point, "id", None)
    if value is None:
        return None
    return str(value)


def _point_score(point: Any) -> float | None:
    if isinstance(point, Mapping):
        value = point.get("score")
    else:
        value = getattr(point, "score", None)
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _normalize_points(response: Any) -> list[Any]:
    if response is None:
        return []
    if isinstance(response, tuple) and len(response) == 2 and isinstance(response[0], list):
        return list(response[0])
    if isinstance(response, Mapping):
        for key in ("points", "result", "records", "items"):
            value = response.get(key)
            if value is not None:
                return list(value)
        return []
    points = getattr(response, "points", None)
    if points is not None:
        return list(points)
    result = getattr(response, "result", None)
    if result is not None:
        return list(result)
    if isinstance(response, Sequence) and not isinstance(response, (str, bytes)):
        return list(response)
    return []


def _normalize_groups_response(response: Any) -> list[Any]:
    if response is None:
        return []
    if isinstance(response, Mapping):
        groups = response.get("groups") or response.get("result") or []
        return list(groups)
    groups = getattr(response, "groups", None)
    if groups is not None:
        return list(groups)
    result = getattr(response, "result", None)
    if result is not None:
        return list(result)
    if isinstance(response, Sequence) and not isinstance(response, (str, bytes)):
        return list(response)
    return []


def _normalize_scroll_page(page: Any) -> tuple[Sequence[Any], Any]:
    if isinstance(page, tuple) and len(page) == 2:
        return page[0] or (), page[1]
    points = getattr(page, "points", None)
    next_offset = getattr(page, "next_page_offset", None)
    if points is not None:
        return points or (), next_offset
    if isinstance(page, Mapping):
        return page.get("points", ()) or (), page.get("next_page_offset")
    return (), None


def _group_parent_id(group: Any) -> str | None:
    value = getattr(group, "id", None)
    if value is None and isinstance(group, Mapping):
        value = group.get("id")
    if value is None:
        value = getattr(group, "group_id", None)
    if value is None and isinstance(group, Mapping):
        value = group.get("group_id")
    if value is None:
        return None
    return str(value)


def _group_items(group: Any) -> list[Any]:
    for name in ("hits", "points", "records", "result"):
        value = getattr(group, name, None)
        if value is not None:
            return list(value)
        if isinstance(group, Mapping) and group.get(name) is not None:
            return list(group.get(name) or [])
    return []


def _first_text(*values: Any) -> str | None:
    for value in values:
        if value in (None, "", [], {}):
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _normalize_text(value: Any) -> str:
    return "".join(str(value or "").split()).lower()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Debug local life parent-child retrieval from Qdrant.")
    parser.add_argument("--query", required=True)
    parser.add_argument("--city", default=None)
    parser.add_argument("--area", default=None)
    parser.add_argument("--category", default=None)
    parser.add_argument("--shop-type-id", type=int, default=None)
    parser.add_argument("--candidate-shop-id", action="append", dest="candidate_shop_ids", type=int, default=[])
    parser.add_argument("--child-top-k", type=int, default=_DEFAULT_CHILD_TOP_K)
    parser.add_argument("--top-k", "--parent-top-k", type=int, default=_DEFAULT_PARENT_TOP_K, dest="parent_top_k")
    parser.add_argument(
        "--sibling-limit",
        "--sibling-limit-per-parent",
        type=int,
        default=_DEFAULT_SIBLING_LIMIT,
        dest="sibling_limit",
    )
    parser.add_argument(
        "--enable-parent-recall",
        action="store_true",
        default=False,
        help="Enable parent-first recall for comparison/recommendation style queries.",
    )
    parser.add_argument("--collection-name", default=LOCAL_LIFE_PARENT_CHILD_COLLECTION)
    parser.add_argument("--vector-name", default=LOCAL_LIFE_VECTOR_NAME)
    return parser


def _format_pack(pack: LocalLifeEvidencePack) -> str:
    return format_evidence_pack(pack)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    settings = get_settings()
    qdrant_runtime = build_qdrant_runtime(settings.qdrant)
    openai_runtime = build_openai_runtime(settings.openai)
    from learning_agent_service.application.dependencies import OpenAIEmbeddingAdapter

    retriever = LocalLifeParentChildRetriever(
        qdrant_client=qdrant_runtime.client,
        embedding_adapter=OpenAIEmbeddingAdapter(runtime=openai_runtime, model=settings.openai.embedding_model),
        collection_name=args.collection_name,
        vector_name=args.vector_name,
    )
    pack = retriever.retrieve_local_life_evidence(
        args.query,
        city=args.city,
        area=args.area,
        category=args.category,
        shop_type_id=args.shop_type_id,
        candidate_shop_ids=args.candidate_shop_ids or None,
        child_top_k=args.child_top_k,
        parent_top_k=args.parent_top_k,
        sibling_limit_per_parent=args.sibling_limit,
        enable_parent_recall=args.enable_parent_recall,
    )
    print(_format_pack(pack))
    return 0


__all__ = [
    "LocalLifeParentChildRetriever",
    "LocalLifeEvidencePack",
    "LOCAL_LIFE_KNOWLEDGE_COLLECTION",
    "LOCAL_LIFE_PARENT_CHILD_COLLECTION",
    "ParentEvidence",
    "RetrievedChunk",
    "build_arg_parser",
    "get_payload_value",
    "infer_role_weights",
    "main",
    "rerank_parent_evidences",
]


def infer_role_weights(query: str, *, route: str | None = None) -> dict[str, float]:
    return _infer_role_weights(query, route=route)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
