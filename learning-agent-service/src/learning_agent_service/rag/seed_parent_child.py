from __future__ import annotations

import argparse
import logging
import time
import uuid
from dataclasses import dataclass, field
import hashlib
import re
from typing import Any, Iterable, Mapping, Optional, Sequence

from learning_agent_service.application.dependencies import OpenAIEmbeddingAdapter
from learning_agent_service.adapters.java_business import JavaBusinessClient
from learning_agent_service.config.settings import Settings, get_settings
from learning_agent_service.infrastructure.db.openai_client import build_openai_runtime
from learning_agent_service.infrastructure.db.qdrant import build_qdrant_runtime
from learning_agent_service.local_life.schemas import BlogRecord, ShopRecord, ShopTypeRecord, VoucherRecord

from .models import KnowledgeChunk

try:  # pragma: no cover - optional runtime dependency
    from qdrant_client import QdrantClient
    from qdrant_client.http.models import (
        Distance,
        FieldCondition,
        Filter,
        HasIdCondition,
        MatchAny,
        MatchValue,
        PayloadSchemaType,
        PointStruct,
        VectorParams,
    )
except Exception:  # pragma: no cover - import-tolerant fallback for test environments
    QdrantClient = None
    PointStruct = None

    @dataclass(frozen=True)
    class VectorParams:  # type: ignore[no-redef]
        size: int
        distance: Any

    class Distance:  # type: ignore[no-redef]
        COSINE = "Cosine"

    class PayloadSchemaType:  # type: ignore[no-redef]
        KEYWORD = "keyword"
        INTEGER = "integer"
        BOOL = "bool"

    class FieldCondition:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class MatchValue:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class MatchAny:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class HasIdCondition:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class Filter:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs


LOCAL_LIFE_KNOWLEDGE_COLLECTION = "local_life_hybrid_chunks"
LOCAL_LIFE_HYBRID_COLLECTION = "local_life_hybrid_chunks"
LOCAL_LIFE_PARENT_CHILD_COLLECTION = "local_life_parent_child_chunks"
LOCAL_LIFE_VECTOR_NAME = "embedding"
LOCAL_LIFE_VECTOR_SIZE = 4096
LOCAL_LIFE_VERSION = "local-life-v1"
LOCAL_LIFE_LONG_TEXT_MAX_CHARS = 760
LOCAL_LIFE_LONG_TEXT_OVERLAP_CHARS = 72
LOCAL_LIFE_LONG_TEXT_MIN_SPLIT_CHARS = 850
_LOGGER = logging.getLogger(__name__)

LOCAL_LIFE_SOURCE_TYPES = (
    "merchant_profile",
    "merchant_review",
    "package_description",
    "platform_rule",
    "local_guide",
)

_LOCAL_LIFE_CHUNK_ROLE_LABELS = {
    "merchant_parent_summary": "商家整体摘要",
    "shop_type_parent_summary": "商家类型整体摘要",
    "platform_rule_parent_summary": "平台规则整体摘要",
    "merchant_profile": "商家介绍",
    "merchant_review_summary": "评价摘要",
    "merchant_scene_fit": "适合场景",
    "merchant_pitfall_summary": "避坑提示",
    "package_description": "套餐说明",
    "merchant_blog_note": "探店笔记",
    "local_guide": "本地攻略",
    "platform_rule": "平台规则",
}

_LOCAL_LIFE_SOURCE_TYPE_LABELS = {
    "merchant_profile": "商家介绍",
    "merchant_review": "商家评价",
    "package_description": "套餐说明",
    "platform_rule": "平台规则",
    "local_guide": "本地攻略",
}

_CITY_HINTS = (
    "北京",
    "上海",
    "广州",
    "深圳",
    "杭州",
    "成都",
    "重庆",
    "南京",
    "苏州",
    "武汉",
    "西安",
    "天津",
    "长沙",
    "厦门",
    "青岛",
    "宁波",
    "郑州",
)

_PLATFORM_RULE_ROWS = (
    {
        "rule_id": "profile_priority",
        "title": "商家介绍优先看什么",
        "text": "先看商家名称、类型、商圈、地址、人均、评分、营业时间，再补看评价摘要和探店笔记。",
        "subcategory": "profile_priority",
        "chunk_type": "qa",
    },
    {
        "rule_id": "review_priority",
        "title": "商家评价怎么读",
        "text": "优先抓取反复出现的高频口碑关键词，比如安静、排队少、适合家庭、停车方便、口味清淡。",
        "subcategory": "review_priority",
        "chunk_type": "qa",
    },
    {
        "rule_id": "voucher_priority",
        "title": "套餐和券怎么看",
        "text": "先看规则、生效时间、失效时间、库存、支付金额和抵扣金额，再判断是否值得下单。",
        "subcategory": "voucher_priority",
        "chunk_type": "qa",
    },
    {
        "rule_id": "guide_priority",
        "title": "本地攻略怎么用",
        "text": "本地攻略优先回答适合什么场景、适合什么人群、哪些商圈更合适，以及怎么在同类商家中做选择。",
        "subcategory": "guide_priority",
        "chunk_type": "qa",
    },
)


@dataclass(frozen=True)
class LocalLifeKnowledgeSeedResult:
    collection_name: str
    vector_name: str
    vector_size: int
    chunk_count: int
    point_count: int
    chunk_ids: tuple[str, ...] = ()
    source_type_counts: Mapping[str, int] = field(default_factory=dict)
    chunk_role_counts: Mapping[str, int] = field(default_factory=dict)
    upsert_batches: tuple[tuple[str, ...], ...] = ()
    payload_index_fields: tuple[str, ...] = ()
    deleted_point_count: int = 0
    duration_seconds: float = 0.0


class LocalLifeQdrantCollectionShapeError(ValueError):
    """Raised when the target Qdrant collection does not match the expected schema."""


_LOCAL_LIFE_PAYLOAD_INDEXES: tuple[tuple[str, Any], ...] = (
    ("chunk_level", PayloadSchemaType.KEYWORD),
    ("category", PayloadSchemaType.KEYWORD),
    ("source_type", PayloadSchemaType.KEYWORD),
    ("chunk_type", PayloadSchemaType.KEYWORD),
    ("document_id", PayloadSchemaType.KEYWORD),
    ("chunk_id", PayloadSchemaType.KEYWORD),
    ("parent_id", PayloadSchemaType.KEYWORD),
    ("parent_title", PayloadSchemaType.KEYWORD),
    ("parent_chunk_id", PayloadSchemaType.KEYWORD),
    ("child_chunk_ids", PayloadSchemaType.KEYWORD),
    ("child_roles", PayloadSchemaType.KEYWORD),
    ("entity_type", PayloadSchemaType.KEYWORD),
    ("entity_id", PayloadSchemaType.KEYWORD),
    ("chunk_role", PayloadSchemaType.KEYWORD),
    ("is_latest", PayloadSchemaType.BOOL),
    ("is_active", PayloadSchemaType.BOOL),
    ("version", PayloadSchemaType.KEYWORD),
    ("metadata.parent_id", PayloadSchemaType.KEYWORD),
    ("metadata.chunk_level", PayloadSchemaType.KEYWORD),
    ("metadata.parent_title", PayloadSchemaType.KEYWORD),
    ("metadata.parent_chunk_id", PayloadSchemaType.KEYWORD),
    ("metadata.child_chunk_ids", PayloadSchemaType.KEYWORD),
    ("metadata.child_roles", PayloadSchemaType.KEYWORD),
    ("metadata.entity_type", PayloadSchemaType.KEYWORD),
    ("metadata.entity_id", PayloadSchemaType.KEYWORD),
    ("metadata.chunk_role", PayloadSchemaType.KEYWORD),
    ("metadata.source_type", PayloadSchemaType.KEYWORD),
    ("metadata.version", PayloadSchemaType.KEYWORD),
    ("metadata.is_latest", PayloadSchemaType.BOOL),
    ("metadata.is_active", PayloadSchemaType.BOOL),
    ("shop_id", PayloadSchemaType.INTEGER),
    ("shop_type_id", PayloadSchemaType.INTEGER),
    ("voucher_id", PayloadSchemaType.INTEGER),
    ("blog_id", PayloadSchemaType.INTEGER),
    ("rule_id", PayloadSchemaType.KEYWORD),
    ("shop_name", PayloadSchemaType.KEYWORD),
    ("city", PayloadSchemaType.KEYWORD),
    ("area", PayloadSchemaType.KEYWORD),
    ("is_active", PayloadSchemaType.BOOL),
    ("version", PayloadSchemaType.KEYWORD),
    ("metadata.shop_id", PayloadSchemaType.INTEGER),
    ("metadata.shop_type_id", PayloadSchemaType.INTEGER),
    ("metadata.shop_name", PayloadSchemaType.KEYWORD),
    ("metadata.city", PayloadSchemaType.KEYWORD),
    ("metadata.area", PayloadSchemaType.KEYWORD),
)


def build_local_life_knowledge_chunks(
    business_client: JavaBusinessClient,
    *,
    shop_limit_per_type: int = 5,
    voucher_limit: int = 3,
    blog_limit: int = 3,
    shop_ids: Sequence[int] | None = None,
    voucher_ids: Sequence[int] | None = None,
    shop_type_ids: Sequence[int] | None = None,
) -> tuple[KnowledgeChunk, ...]:
    chunks: list[KnowledgeChunk] = []
    shop_type_rows = list(_safe_list(business_client.list_shop_types()))
    seen_shop_ids: set[int] = set()
    wanted_shop_ids = {int(value) for value in shop_ids or ()}
    wanted_voucher_ids = {int(value) for value in voucher_ids or ()}
    wanted_shop_type_ids = {int(value) for value in shop_type_ids or ()}

    for shop_type in shop_type_rows:
        if shop_type is None:
            continue
        if wanted_shop_type_ids and int(shop_type.id) not in wanted_shop_type_ids:
            continue
        candidates = list(
            _safe_list(
                business_client.search_shops_by_type(
                    type_id=int(shop_type.id),
                    current=1,
                    x=None,
                    y=None,
                )
            )
        )[: max(1, int(shop_limit_per_type))]

        typed_shops: list[ShopRecord] = []
        for candidate in candidates:
            shop = _resolve_shop_detail(business_client, candidate)
            if shop is None or shop.id in seen_shop_ids:
                continue
            if wanted_shop_ids and int(shop.id) not in wanted_shop_ids:
                continue
            seen_shop_ids.add(shop.id)
            typed_shops.append(shop)
            chunks.extend(
                _build_shop_chunks(
                    shop=shop,
                    shop_type=shop_type,
                    business_client=business_client,
                    voucher_limit=voucher_limit,
                    blog_limit=blog_limit,
                    voucher_ids=wanted_voucher_ids,
                )
            )

        if typed_shops:
            chunks.extend(_build_local_guide_chunks(shop_type=shop_type, shops=typed_shops))

    chunks.extend(_build_platform_rule_chunks())
    return _dedupe_chunks(chunks)


def seed_local_life_knowledge(
    *,
    business_client: JavaBusinessClient,
    qdrant_client: Any,
    embedding_adapter: Any,
    collection_name: str = LOCAL_LIFE_HYBRID_COLLECTION,
    vector_name: str = LOCAL_LIFE_VECTOR_NAME,
    vector_size: int = LOCAL_LIFE_VECTOR_SIZE,
    shop_limit_per_type: int = 5,
    voucher_limit: int = 3,
    blog_limit: int = 3,
    batch_size: int = 64,
    cleanup_stale_points: bool = True,
    shop_ids: Sequence[int] | None = None,
    voucher_ids: Sequence[int] | None = None,
    shop_type_ids: Sequence[int] | None = None,
) -> LocalLifeKnowledgeSeedResult:
    started_at = time.perf_counter()
    _LOGGER.info(
        "local_life_seed_started collection=%s vector=%s size=%s cleanup_stale_points=%s",
        collection_name,
        vector_name,
        vector_size,
        cleanup_stale_points,
    )
    chunks = build_local_life_knowledge_chunks(
        business_client,
        shop_limit_per_type=shop_limit_per_type,
        voucher_limit=voucher_limit,
        blog_limit=blog_limit,
        shop_ids=shop_ids,
        voucher_ids=voucher_ids,
        shop_type_ids=shop_type_ids,
    )
    ensure_local_life_collection(
        qdrant_client,
        collection_name=collection_name,
        vector_name=vector_name,
        vector_size=vector_size,
    )
    payload_index_fields = ensure_local_life_payload_indexes(qdrant_client, collection_name=collection_name)

    point_batches: list[tuple[str, ...]] = []
    current_batch: list[Any] = []
    current_ids: list[str] = []
    for chunk in chunks:
        point = _chunk_to_point(
            chunk,
            embedding_adapter=embedding_adapter,
            vector_name=vector_name,
            vector_size=vector_size,
        )
        current_batch.append(point)
        current_ids.append(str(point.id))
        if len(current_batch) >= max(1, int(batch_size)):
            _upsert_points(qdrant_client, collection_name, current_batch)
            point_batches.append(tuple(current_ids))
            current_batch = []
            current_ids = []

    if current_batch:
        _upsert_points(qdrant_client, collection_name, current_batch)
        point_batches.append(tuple(current_ids))

    deleted_point_count = 0
    if cleanup_stale_points:
        scoped_parent_ids = tuple(
            sorted(
                {
                    str(chunk.parent_id)
                    for chunk in chunks
                    if chunk.parent_id
                }
            )
        )
        deleted_point_count = _cleanup_stale_points(
            qdrant_client,
            collection_name=collection_name,
            current_chunk_ids=tuple(chunk.chunk_id for chunk in chunks),
            scoped_parent_ids=scoped_parent_ids,
            scoped_update=bool(shop_ids or voucher_ids or shop_type_ids),
        )

    source_type_counts: dict[str, int] = {}
    chunk_role_counts: dict[str, int] = {}
    for chunk in chunks:
        source_type = str(chunk.source_type or "")
        source_type_counts[source_type] = source_type_counts.get(source_type, 0) + 1
        chunk_role = str(chunk.metadata.get("chunk_role") or chunk.chunk_type or chunk.source_type or "")
        if chunk_role:
            chunk_role_counts[chunk_role] = chunk_role_counts.get(chunk_role, 0) + 1

    duration_seconds = time.perf_counter() - started_at
    _LOGGER.info(
        "local_life_seed_completed collection=%s vector=%s chunks=%s points=%s batches=%s deleted=%s payload_indexes=%s duration_ms=%.1f source_types=%s chunk_roles=%s",
        collection_name,
        vector_name,
        len(chunks),
        len(chunks),
        len(point_batches),
        deleted_point_count,
        len(payload_index_fields),
        duration_seconds * 1000.0,
        dict(source_type_counts),
        dict(chunk_role_counts),
    )

    return LocalLifeKnowledgeSeedResult(
        collection_name=collection_name,
        vector_name=vector_name,
        vector_size=vector_size,
        chunk_count=len(chunks),
        point_count=len(chunks),
        chunk_ids=tuple(chunk.chunk_id for chunk in chunks),
        source_type_counts=source_type_counts,
        chunk_role_counts=chunk_role_counts,
        upsert_batches=tuple(point_batches),
        payload_index_fields=tuple(payload_index_fields),
        deleted_point_count=deleted_point_count,
        duration_seconds=duration_seconds,
    )


def seed_local_life_knowledge_from_settings(
    *,
    settings: Settings | None = None,
    business_client: JavaBusinessClient,
    qdrant_client: Any,
    embedding_adapter: Any,
    shop_limit_per_type: int = 5,
    voucher_limit: int = 3,
    blog_limit: int = 3,
    batch_size: int = 64,
    cleanup_stale_points: bool = True,
    shop_ids: Sequence[int] | None = None,
    voucher_ids: Sequence[int] | None = None,
    shop_type_ids: Sequence[int] | None = None,
) -> LocalLifeKnowledgeSeedResult:
    settings = settings or get_settings()
    return seed_local_life_knowledge(
        business_client=business_client,
        qdrant_client=qdrant_client,
        embedding_adapter=embedding_adapter,
        collection_name=settings.qdrant.local_life_hybrid_collection,
        vector_name=settings.qdrant.knowledge_vector_name,
        vector_size=settings.qdrant.knowledge_vector_size,
        shop_limit_per_type=shop_limit_per_type,
        voucher_limit=voucher_limit,
        blog_limit=blog_limit,
        batch_size=batch_size,
        cleanup_stale_points=cleanup_stale_points,
        shop_ids=shop_ids,
        voucher_ids=voucher_ids,
        shop_type_ids=shop_type_ids,
    )


def seed_local_life_hybrid_knowledge_from_settings(
    *,
    settings: Settings | None = None,
    business_client: JavaBusinessClient,
    qdrant_client: Any,
    embedding_adapter: Any,
    shop_limit_per_type: int = 5,
    voucher_limit: int = 3,
    blog_limit: int = 3,
    batch_size: int = 64,
    cleanup_stale_points: bool = True,
    shop_ids: Sequence[int] | None = None,
    voucher_ids: Sequence[int] | None = None,
    shop_type_ids: Sequence[int] | None = None,
) -> LocalLifeKnowledgeSeedResult:
    settings = settings or get_settings()
    return seed_local_life_knowledge(
        business_client=business_client,
        qdrant_client=qdrant_client,
        embedding_adapter=embedding_adapter,
        collection_name=settings.qdrant.local_life_hybrid_collection,
        vector_name=settings.qdrant.knowledge_vector_name,
        vector_size=settings.qdrant.knowledge_vector_size,
        shop_limit_per_type=shop_limit_per_type,
        voucher_limit=voucher_limit,
        blog_limit=blog_limit,
        batch_size=batch_size,
        cleanup_stale_points=cleanup_stale_points,
        shop_ids=shop_ids,
        voucher_ids=voucher_ids,
        shop_type_ids=shop_type_ids,
    )


def seed_local_life_parent_child_knowledge_from_settings(
    *,
    settings: Settings | None = None,
    business_client: JavaBusinessClient,
    qdrant_client: Any,
    embedding_adapter: Any,
    shop_limit_per_type: int = 5,
    voucher_limit: int = 3,
    blog_limit: int = 3,
    batch_size: int = 64,
    cleanup_stale_points: bool = True,
    shop_ids: Sequence[int] | None = None,
    voucher_ids: Sequence[int] | None = None,
    shop_type_ids: Sequence[int] | None = None,
) -> LocalLifeKnowledgeSeedResult:
    settings = settings or get_settings()
    return seed_local_life_knowledge(
        business_client=business_client,
        qdrant_client=qdrant_client,
        embedding_adapter=embedding_adapter,
        collection_name=settings.qdrant.local_life_parent_child_collection,
        vector_name=settings.qdrant.knowledge_vector_name,
        vector_size=settings.qdrant.knowledge_vector_size,
        shop_limit_per_type=shop_limit_per_type,
        voucher_limit=voucher_limit,
        blog_limit=blog_limit,
        batch_size=batch_size,
        cleanup_stale_points=cleanup_stale_points,
        shop_ids=shop_ids,
        voucher_ids=voucher_ids,
        shop_type_ids=shop_type_ids,
    )


def ensure_local_life_collection(
    qdrant_client: Any,
    *,
    collection_name: str = LOCAL_LIFE_KNOWLEDGE_COLLECTION,
    vector_name: str = LOCAL_LIFE_VECTOR_NAME,
    vector_size: int = LOCAL_LIFE_VECTOR_SIZE,
) -> None:
    collection_exists = getattr(qdrant_client, "collection_exists", None)
    if callable(collection_exists):
        try:
            exists = bool(collection_exists(collection_name))
        except Exception:
            exists = False
        if exists:
            _validate_collection_vector_shape(
                qdrant_client,
                collection_name=collection_name,
                vector_name=vector_name,
                vector_size=vector_size,
            )
            return

    get_collection = getattr(qdrant_client, "get_collection", None)
    if callable(get_collection):
        try:
            _validate_collection_vector_shape(
                qdrant_client,
                collection_name=collection_name,
                vector_name=vector_name,
                vector_size=vector_size,
            )
            return
        except LocalLifeQdrantCollectionShapeError:
            raise
        except Exception:
            pass

    create_collection = getattr(qdrant_client, "create_collection", None)
    if not callable(create_collection):
        raise RuntimeError("Qdrant client does not expose create_collection")
    vectors_config = {vector_name: VectorParams(size=vector_size, distance=Distance.COSINE)}
    try:
        create_collection(collection_name=collection_name, vectors_config=vectors_config)
    except TypeError:
        create_collection(collection_name=collection_name, vectors_config=vectors_config, wait=True)


def _build_shop_chunks(
    *,
    shop: ShopRecord,
    shop_type: ShopTypeRecord,
    business_client: JavaBusinessClient,
    voucher_limit: int,
    blog_limit: int,
    voucher_ids: set[int] | None = None,
) -> list[KnowledgeChunk]:
    try:
        vouchers = list(_safe_list(business_client.get_coupon_list(shop.id)))[: max(0, int(voucher_limit))]
    except Exception:
        vouchers = []
    if voucher_ids:
        vouchers = [voucher for voucher in vouchers if voucher is not None and int(voucher.id) in voucher_ids]
    try:
        blogs = list(_safe_list(business_client.get_shop_blogs(shop.id, limit=blog_limit)))[: max(0, int(blog_limit))]
    except Exception:
        blogs = []
    child_chunks = _build_shop_child_chunks(
        shop=shop,
        shop_type=shop_type,
        vouchers=vouchers,
        blogs=blogs,
    )
    parent_chunk = _build_shop_parent_chunk(
        shop=shop,
        shop_type=shop_type,
        child_chunks=child_chunks,
        vouchers=vouchers,
        blogs=blogs,
    )
    return [parent_chunk, *child_chunks]


def _build_shop_child_chunks(
    *,
    shop: ShopRecord,
    shop_type: ShopTypeRecord,
    vouchers: Sequence[VoucherRecord],
    blogs: Sequence[BlogRecord],
) -> list[KnowledgeChunk]:
    chunks: list[KnowledgeChunk] = []
    chunks.append(_build_merchant_profile_chunk(shop, shop_type, vouchers=vouchers, blogs=blogs))
    chunks.extend(_build_merchant_review_chunks(shop, shop_type, blogs=blogs, vouchers=vouchers))
    chunks.extend(
        _build_package_description_chunks(
            shop=shop,
            shop_type=shop_type,
            vouchers=vouchers,
        )
    )
    chunks.extend(_build_blog_note_chunks(shop=shop, shop_type=shop_type, blogs=blogs))
    return chunks


def _build_shop_parent_chunk(
    *,
    shop: ShopRecord,
    shop_type: ShopTypeRecord,
    child_chunks: Sequence[KnowledgeChunk],
    vouchers: Sequence[VoucherRecord],
    blogs: Sequence[BlogRecord],
) -> KnowledgeChunk:
    city = _infer_city(shop.address)
    parent_chunk_id = f"local-life:shop:{shop.id}:parent-summary"
    child_chunk_ids = tuple(chunk.chunk_id for chunk in child_chunks)
    child_roles = tuple(
        chunk.chunk_role
        for chunk in child_chunks
        if chunk.chunk_role
    )
    summary_text = _compose_shop_parent_summary_text(
        shop=shop,
        shop_type=shop_type,
        city=city,
        child_chunks=child_chunks,
        vouchers=vouchers,
        blogs=blogs,
    )
    return _make_chunk(
        source_type="merchant_profile",
        document_id=parent_chunk_id,
        chunk_id=parent_chunk_id,
        chunk_index=1,
        title=f"{shop.name} 商家整体摘要",
        text=summary_text,
        summary=_truncate_text(summary_text, max_chars=160),
        category="local_life",
        chunk_type="concept",
        subcategory=shop_type.name,
        chunk_level="parent",
        parent_id=f"shop:{shop.id}",
        parent_title=shop.name,
        parent_chunk_id=parent_chunk_id,
        child_chunk_ids=child_chunk_ids,
        child_roles=child_roles,
        chunk_role="merchant_parent_summary",
        entity_type="shop",
        entity_id=f"shop:{shop.id}",
        sibling_source_types=(
            "merchant_profile",
            "merchant_review",
            "package_description",
            "local_guide",
        ),
        sibling_roles=(
            "merchant_profile",
            "merchant_review_summary",
            "merchant_scene_fit",
            "merchant_pitfall_summary",
            "merchant_blog_note",
            "package_description",
        ),
        metadata={
            "shop_id": shop.id,
            "shop_type_id": shop_type.id,
            "shop_name": shop.name,
            "area": shop.area,
            "city": city,
            "is_active": True,
            "version": LOCAL_LIFE_VERSION,
            "chunk_level": "parent",
            "chunk_role": "merchant_parent_summary",
            "parent_id": f"shop:{shop.id}",
            "parent_title": shop.name,
            "parent_chunk_id": parent_chunk_id,
            "child_chunk_ids": list(child_chunk_ids),
            "child_roles": list(child_roles),
            "entity_type": "shop",
            "entity_id": f"shop:{shop.id}",
            "parent_summary_kind": "merchant_parent_summary",
            "voucher_count": len(vouchers),
            "blog_count": len(blogs),
        },
        tags=_chunk_tags(shop, shop_type, city, source_type="merchant_profile", extra=("parent_summary", "merchant_parent_summary")),
    )


def split_long_text_by_semantic_units(
    text: str,
    *,
    max_chars: int = LOCAL_LIFE_LONG_TEXT_MAX_CHARS,
    overlap_chars: int = LOCAL_LIFE_LONG_TEXT_OVERLAP_CHARS,
) -> list[str]:
    normalized = _normalize_text_block(text)
    if not normalized:
        return []
    if len(normalized) < LOCAL_LIFE_LONG_TEXT_MIN_SPLIT_CHARS:
        return [normalized]

    units = _split_semantic_units(normalized)
    if not units:
        return [normalized]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for unit in units:
        for piece in _split_overlong_unit(unit, max_chars=max_chars):
            piece_len = len(piece)
            if current and current_len + piece_len > max_chars:
                chunk_text = "".join(current).strip()
                if chunk_text:
                    chunks.append(chunk_text)
                overlap = _semantic_overlap_text(chunk_text, overlap_chars)
                current = [overlap] if overlap else []
                current_len = len(overlap)
            current.append(piece)
            current_len += piece_len
    if current:
        chunk_text = "".join(current).strip()
        if chunk_text:
            chunks.append(chunk_text)
    return [chunk for chunk in chunks if chunk]


def _normalize_text_block(text: str) -> str:
    return " ".join(part.strip() for part in str(text or "").splitlines() if part.strip()).strip()


def _split_semantic_units(text: str) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n+", str(text or "")) if part.strip()]
    if not paragraphs:
        return []
    units: list[str] = []
    for paragraph in paragraphs:
        sentence_units = re.split(r"(?<=[。！？!?；;])", paragraph)
        for sentence in sentence_units:
            sentence = sentence.strip()
            if sentence:
                units.append(sentence)
    return units


def _split_overlong_unit(unit: str, *, max_chars: int) -> list[str]:
    text = str(unit or "").strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    sub_units = [part.strip() for part in re.split(r"(?<=[，,、：:])", text) if part.strip()]
    if len(sub_units) > 1:
        merged: list[str] = []
        current = ""
        for part in sub_units:
            if not current:
                current = part
                continue
            if len(current) + len(part) <= max_chars:
                current += part
            else:
                merged.append(current)
                current = part
        if current:
            merged.append(current)
        return merged
    return [text[i : i + max_chars] for i in range(0, len(text), max_chars)]


def _semantic_overlap_text(text: str, overlap_chars: int) -> str:
    if overlap_chars <= 0:
        return ""
    units = _split_semantic_units(text)
    if not units:
        return ""
    overlap: list[str] = []
    total = 0
    for unit in reversed(units):
        if overlap and total + len(unit) > overlap_chars:
            break
        overlap.append(unit)
        total += len(unit)
        if total >= overlap_chars:
            break
    return "".join(reversed(overlap)).strip()


def _join_natural(items: Sequence[str]) -> str:
    values = [str(item).strip() for item in items if str(item).strip()]
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return "和".join(values)
    return "、".join(values[:-1]) + "和" + values[-1]


def _truncate_text(text: str, *, max_chars: int) -> str:
    normalized = _normalize_text_block(text)
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max(0, max_chars - 1)].rstrip() + "…"


def _chunk_role_label(chunk_role: Optional[str]) -> str:
    role = str(chunk_role or "").strip()
    return _LOCAL_LIFE_CHUNK_ROLE_LABELS.get(role, role)


def _source_type_label(source_type: Optional[str]) -> str:
    source = str(source_type or "").strip()
    return _LOCAL_LIFE_SOURCE_TYPE_LABELS.get(source, source)


def _search_keywords(*values: Any) -> tuple[str, ...]:
    tokens: list[str] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            candidates = [value]
        elif isinstance(value, Iterable):
            candidates = [str(item) for item in value if item not in (None, "")]
        else:
            candidates = [str(value)]
        for candidate in candidates:
            candidate = str(candidate).strip()
            if candidate and candidate not in tokens:
                tokens.append(candidate)
    return tuple(tokens)


def _compose_shop_parent_summary_text(
    *,
    shop: ShopRecord,
    shop_type: ShopTypeRecord,
    city: str | None,
    child_chunks: Sequence[KnowledgeChunk],
    vouchers: Sequence[VoucherRecord],
    blogs: Sequence[BlogRecord],
) -> str:
    matched_texts = {
        chunk.chunk_role: _truncate_text(chunk.text, max_chars=70)
        for chunk in child_chunks
        if chunk.chunk_role in {
            "merchant_profile",
            "merchant_review_summary",
            "merchant_scene_fit",
            "merchant_pitfall_summary",
            "package_description",
            "merchant_blog_note",
        }
        and chunk.text
    }
    lines = [
        f"{shop.name} 位于{city or '未知城市'}{shop.area or '未知商圈'}，是一家{shop_type.name}商家。",
    ]
    profile_bits = [
        f"人均约{_format_price(shop.avg_price)}元" if shop.avg_price is not None else "",
        f"评分{_format_score(shop.score)}" if shop.score is not None else "",
        f"评论数{_format_int(shop.comments)}" if shop.comments is not None else "",
    ]
    profile_text = "，".join(bit for bit in profile_bits if bit)
    if profile_text:
        lines.append(f"基础信息显示{profile_text}。")
    if shop.open_hours:
        lines.append(f"营业时间为{shop.open_hours}。")
    if shop.parking:
        lines.append("支持停车。")
    if shop.family_friendly:
        lines.append("适合家庭聚餐。")
    if shop.elder_friendly:
        lines.append("对长辈相对友好。")
    if matched_texts.get("merchant_review_summary"):
        lines.append(f"评价摘要提示：{matched_texts['merchant_review_summary']}")
    if matched_texts.get("merchant_scene_fit"):
        lines.append(f"适合场景提示：{matched_texts['merchant_scene_fit']}")
    if matched_texts.get("merchant_pitfall_summary"):
        lines.append(f"主要注意点：{matched_texts['merchant_pitfall_summary']}")
    if vouchers:
        lines.append(f"当前有{len(vouchers)}张套餐或优惠券可参考，优先核对规则和有效期。")
    if blogs:
        lines.append(f"还有{len(blogs)}篇探店笔记可补充判断。")
    if matched_texts.get("merchant_blog_note"):
        lines.append(f"探店笔记提示：{matched_texts['merchant_blog_note']}")
    summary = _normalize_text_block(" ".join(lines))
    return _truncate_text(summary, max_chars=480)


def _compose_shop_type_parent_summary_text(
    *,
    shop_type: ShopTypeRecord,
    shops: Sequence[ShopRecord],
    child_chunks: Sequence[KnowledgeChunk],
) -> str:
    areas = _join_natural([shop.area for shop in shops if shop.area])
    shop_names = _join_natural([shop.name for shop in shops[:3] if shop.name])
    scene_chunks = [
        _truncate_text(chunk.text, max_chars=60)
        for chunk in child_chunks
        if chunk.chunk_role == "local_guide" and chunk.text
    ]
    lines = [f"{shop_type.name} 本地攻略用于筛选同类商家，优先看商圈、人均、评分和营业时间。"]
    if areas:
        lines.append(f"常见商圈包括{areas}。")
    if shop_names:
        lines.append(f"代表商家有{shop_names}。")
    if scene_chunks:
        lines.append(f"攻略补充提示：{scene_chunks[0]}")
    return _truncate_text(_normalize_text_block(" ".join(lines)), max_chars=380)


def _compose_platform_rule_parent_summary_text(
    *,
    title: str,
    text: str,
    child_chunks: Sequence[KnowledgeChunk],
) -> str:
    snippets = [
        _truncate_text(chunk.text, max_chars=80)
        for chunk in child_chunks
        if chunk.chunk_role == "platform_rule" and chunk.text
    ]
    lines = [f"{title} 主要说明平台规则的适用边界、限制条件和核对顺序。"]
    if text:
        lines.append(_truncate_text(text, max_chars=180))
    if snippets:
        lines.append(f"拆分后的规则补充：{snippets[0]}")
    return _truncate_text(_normalize_text_block(" ".join(lines)), max_chars=320)


def _build_merchant_profile_chunk(
    shop: ShopRecord,
    shop_type: ShopTypeRecord,
    *,
    vouchers: Sequence[VoucherRecord],
    blogs: Sequence[BlogRecord],
) -> KnowledgeChunk:
    city = _infer_city(shop.address)
    lines = [
        f"{shop.name} 是一家{shop_type.name}商家，位于{shop.area or '未知商圈'}。",
        f"地址：{shop.address or '未知'}。",
        f"人均约{_format_price(shop.avg_price)}元，评分{_format_score(shop.score)}，评论数{_format_int(shop.comments)}。",
    ]
    if shop.open_hours:
        lines.append(f"营业时间：{shop.open_hours}。")
    if shop.parking:
        lines.append("支持停车。")
    if shop.family_friendly:
        lines.append("适合家庭聚餐。")
    if shop.elder_friendly:
        lines.append("对长辈友好。")
    if shop.review_summary:
        lines.append(f"评价摘要：{shop.review_summary}")
    if shop.evidence_texts:
        lines.append("典型评价：" + "；".join(shop.evidence_texts[:3]))
    if vouchers:
        lines.append(f"当前可参考的优惠券有{len(vouchers)}张。")
    if blogs:
        lines.append(f"相关探店笔记有{len(blogs)}篇。")
    text = " ".join(lines)
    return _make_chunk(
        source_type="merchant_profile",
        document_id=f"local-life:shop:{shop.id}:merchant-profile",
        chunk_index=1,
        title=f"{shop.name} 商家介绍",
        text=text,
        category="local_life",
        chunk_type="concept",
        subcategory=shop_type.name,
        chunk_level="child",
        parent_id=f"shop:{shop.id}",
        parent_title=shop.name,
        parent_chunk_id=f"local-life:shop:{shop.id}:parent-summary",
        chunk_role="merchant_profile",
        entity_type="shop",
        entity_id=f"shop:{shop.id}",
        sibling_source_types=(
            "merchant_profile",
            "merchant_review",
            "package_description",
            "local_guide",
        ),
        sibling_roles=(
            "merchant_profile",
            "merchant_review_summary",
            "merchant_scene_fit",
            "merchant_pitfall_summary",
            "merchant_blog_note",
            "package_description",
        ),
        metadata={
            "shop_id": shop.id,
            "shop_type_id": shop_type.id,
            "shop_name": shop.name,
            "area": shop.area,
            "city": city,
            "is_active": True,
            "version": LOCAL_LIFE_VERSION,
            "voucher_count": len(vouchers),
            "blog_count": len(blogs),
        },
        tags=_chunk_tags(shop, shop_type, city, source_type="merchant_profile"),
    )


def _build_merchant_review_chunks(
    shop: ShopRecord,
    shop_type: ShopTypeRecord,
    *,
    blogs: Sequence[BlogRecord],
    vouchers: Sequence[VoucherRecord],
 ) -> list[KnowledgeChunk]:
    city = _infer_city(shop.address)
    signals = _extract_review_signals(shop, blogs=blogs, vouchers=vouchers)
    chunks: list[KnowledgeChunk] = []
    summary_text = _compose_review_summary_text(
        shop=shop,
        positive_points=signals["positive_points"],
        negative_points=signals["negative_points"],
        keywords=signals["keywords"],
        suitable_scenes=signals["suitable_scenes"],
        unsuitable_scenes=signals["unsuitable_scenes"],
    )
    if summary_text:
        chunks.append(
            _make_chunk(
                source_type="merchant_review",
                document_id=f"local-life:shop:{shop.id}:merchant-review-summary",
                chunk_index=1,
                title=f"{shop.name} 评价摘要",
                text=summary_text,
                category="local_life",
                chunk_type="concept",
                subcategory=shop_type.name,
                chunk_level="child",
                parent_id=f"shop:{shop.id}",
                parent_title=shop.name,
                parent_chunk_id=f"local-life:shop:{shop.id}:parent-summary",
                chunk_role="merchant_review_summary",
                entity_type="shop",
                entity_id=f"shop:{shop.id}",
                sibling_source_types=(
                    "merchant_profile",
                    "merchant_review",
                    "package_description",
                    "local_guide",
                ),
                sibling_roles=(
                    "merchant_profile",
                    "merchant_review_summary",
                    "merchant_scene_fit",
                    "merchant_pitfall_summary",
                    "merchant_blog_note",
                    "package_description",
                ),
                metadata={
                    "shop_id": shop.id,
                    "shop_type_id": shop_type.id,
                    "shop_name": shop.name,
                    "area": shop.area,
                    "city": city,
                    "is_active": True,
                    "version": LOCAL_LIFE_VERSION,
                    "summary_kind": "merchant_review_summary",
                },
                tags=_chunk_tags(shop, shop_type, city, source_type="merchant_review"),
            )
        )
    scene_fit_text = _compose_scene_fit_text(shop=shop, shop_type=shop_type, signals=signals)
    if scene_fit_text:
        chunks.append(
            _make_chunk(
                source_type="merchant_review",
                document_id=f"local-life:shop:{shop.id}:merchant-scene-fit",
                chunk_index=1,
                title=f"{shop.name} 适合场景",
                text=scene_fit_text,
                category="local_life",
                chunk_type="roadmap",
                subcategory=shop_type.name,
                chunk_level="child",
                parent_id=f"shop:{shop.id}",
                parent_title=shop.name,
                parent_chunk_id=f"local-life:shop:{shop.id}:parent-summary",
                chunk_role="merchant_scene_fit",
                entity_type="shop",
                entity_id=f"shop:{shop.id}",
                sibling_source_types=(
                    "merchant_profile",
                    "merchant_review",
                    "package_description",
                    "local_guide",
                ),
                sibling_roles=(
                    "merchant_profile",
                    "merchant_review_summary",
                    "merchant_scene_fit",
                    "merchant_pitfall_summary",
                    "merchant_blog_note",
                    "package_description",
                ),
                metadata={
                    "shop_id": shop.id,
                    "shop_type_id": shop_type.id,
                    "shop_name": shop.name,
                    "area": shop.area,
                    "city": city,
                    "is_active": True,
                    "version": LOCAL_LIFE_VERSION,
                    "scene_kind": "merchant_scene_fit",
                },
                tags=_chunk_tags(shop, shop_type, city, source_type="merchant_review", extra=("scene_fit",)),
            )
        )
    pitfall_text = _compose_pitfall_summary_text(shop=shop, shop_type=shop_type, signals=signals)
    if pitfall_text:
        chunks.append(
            _make_chunk(
                source_type="merchant_review",
                document_id=f"local-life:shop:{shop.id}:merchant-pitfall-summary",
                chunk_index=1,
                title=f"{shop.name} 避坑信息",
                text=pitfall_text,
                category="local_life",
                chunk_type="pitfall",
                subcategory=shop_type.name,
                chunk_level="child",
                parent_id=f"shop:{shop.id}",
                parent_title=shop.name,
                parent_chunk_id=f"local-life:shop:{shop.id}:parent-summary",
                chunk_role="merchant_pitfall_summary",
                entity_type="shop",
                entity_id=f"shop:{shop.id}",
                sibling_source_types=(
                    "merchant_profile",
                    "merchant_review",
                    "package_description",
                    "local_guide",
                ),
                sibling_roles=(
                    "merchant_profile",
                    "merchant_review_summary",
                    "merchant_scene_fit",
                    "merchant_pitfall_summary",
                    "merchant_blog_note",
                    "package_description",
                ),
                metadata={
                    "shop_id": shop.id,
                    "shop_type_id": shop_type.id,
                    "shop_name": shop.name,
                    "area": shop.area,
                    "city": city,
                    "is_active": True,
                    "version": LOCAL_LIFE_VERSION,
                    "pitfall_kind": "merchant_pitfall_summary",
                },
                tags=_chunk_tags(shop, shop_type, city, source_type="merchant_review", extra=("pitfall",)),
            )
        )
    return chunks


def _build_package_description_chunks(
    *,
    shop: ShopRecord,
    shop_type: ShopTypeRecord,
    vouchers: Sequence[VoucherRecord],
) -> list[KnowledgeChunk]:
    chunks: list[KnowledgeChunk] = []
    for voucher in vouchers:
        if voucher is None:
            continue
        chunks.append(_build_package_description_chunk(shop, shop_type, voucher))
    return chunks


def _build_package_description_chunk(
    shop: ShopRecord,
    shop_type: ShopTypeRecord,
    voucher: VoucherRecord,
) -> KnowledgeChunk:
    city = _infer_city(shop.address)
    lines = [
        f"{shop.name} 的套餐/优惠券《{voucher.title}》主要适合关注价格和规则的用户。",
        f"支付金额{_format_price(voucher.pay_value)}元，抵扣金额{_format_price(voucher.actual_value)}元。",
    ]
    if voucher.sub_title:
        lines.append(f"副标题是“{voucher.sub_title}”。")
    if voucher.rules:
        lines.append(f"使用规则是：{voucher.rules}。")
    if voucher.stock is not None:
        lines.append(f"库存大约还有{voucher.stock}张。")
    if voucher.begin_time:
        lines.append(f"生效时间：{voucher.begin_time}。")
    if voucher.end_time:
        lines.append(f"失效时间：{voucher.end_time}。")
    text = " ".join(lines)
    return _make_chunk(
        source_type="package_description",
        document_id=f"local-life:package-description:voucher:{voucher.id}",
        chunk_index=1,
        title=f"{shop.name} 套餐说明 - {voucher.title}",
        text=text,
        category="local_life",
        chunk_type="qa",
        subcategory=shop_type.name,
        chunk_level="child",
        parent_id=f"shop:{shop.id}",
        parent_title=shop.name,
        parent_chunk_id=f"local-life:shop:{shop.id}:parent-summary",
        chunk_role="package_description",
        entity_type="voucher",
        entity_id=f"voucher:{voucher.id}",
        metadata={
            "shop_id": shop.id,
            "shop_type_id": shop_type.id,
            "voucher_id": voucher.id,
            "shop_name": shop.name,
            "area": shop.area,
            "city": city,
            "is_active": True,
            "version": LOCAL_LIFE_VERSION,
            "chunk_role": "package_description",
            "parent_id": f"shop:{shop.id}",
            "parent_title": shop.name,
            "entity_type": "voucher",
            "entity_id": f"voucher:{voucher.id}",
        },
        tags=_chunk_tags(shop, shop_type, city, source_type="package_description", extra=(voucher.title,)),
    )


def _build_blog_note_chunks(
    *,
    shop: ShopRecord,
    shop_type: ShopTypeRecord,
    blogs: Sequence[BlogRecord],
) -> list[KnowledgeChunk]:
    chunks: list[KnowledgeChunk] = []
    city = _infer_city(shop.address)
    for blog in blogs:
        if blog is None:
            continue
        parts: list[str] = []
        if blog.title:
            parts.append(str(blog.title).strip())
        if blog.content:
            parts.append(str(blog.content).strip())
        raw_text = _normalize_text_block(" ".join(part for part in parts if part))
        if not raw_text:
            continue
        segments = split_long_text_by_semantic_units(raw_text)
        if not segments:
            continue
        for index, segment in enumerate(segments, start=1):
            suffix = f"第{index}/{len(segments)}部分" if len(segments) > 1 else "笔记"
            text = f"{shop.name} 的探店笔记《{blog.title or '未命名'}》{suffix}：{segment}"
            chunks.append(
                _make_chunk(
                    source_type="merchant_review",
                    document_id=f"local-life:merchant-blog:shop:{shop.id}:blog:{blog.id}",
                    chunk_index=index,
                    title=f"{shop.name} 探店笔记 - {blog.title or blog.id}",
                    text=text,
                    category="local_life",
                    chunk_type="qa",
                    subcategory=shop_type.name,
                    chunk_level="child",
                    parent_id=f"shop:{shop.id}",
                    parent_title=shop.name,
                    parent_chunk_id=f"local-life:shop:{shop.id}:parent-summary",
                    chunk_role="merchant_blog_note",
                    entity_type="blog",
                    entity_id=f"blog:{blog.id}",
                    sibling_source_types=(
                        "merchant_profile",
                        "merchant_review",
                        "package_description",
                        "local_guide",
                    ),
                    sibling_roles=(
                        "merchant_profile",
                        "merchant_review_summary",
                        "merchant_scene_fit",
                        "merchant_pitfall_summary",
                        "merchant_blog_note",
                        "package_description",
                    ),
                    metadata={
                        "shop_id": shop.id,
                        "shop_type_id": shop_type.id,
                        "shop_name": shop.name,
                        "blog_id": blog.id,
                        "blog_title": blog.title,
                        "area": shop.area,
                        "city": city,
                        "is_active": True,
                        "version": LOCAL_LIFE_VERSION,
                        "chunk_role": "merchant_blog_note",
                        "parent_id": f"shop:{shop.id}",
                        "parent_title": shop.name,
                        "entity_type": "blog",
                        "entity_id": f"blog:{blog.id}",
                    },
                    tags=_chunk_tags(shop, shop_type, city, source_type="merchant_review", extra=(blog.title or "", "merchant_blog_note")),
                )
            )
    return chunks


def _build_local_guide_chunks(*, shop_type: ShopTypeRecord, shops: Sequence[ShopRecord]) -> list[KnowledgeChunk]:
    if not shops:
        return []
    city = _infer_city(shops[0].address) if shops else None
    areas = list(dict.fromkeys(shop.area for shop in shops if shop.area))
    scene_hints = _guide_scene_hints(shops)
    shop_names = [shop.name for shop in shops[:5] if shop.name]
    lead_lines = [
        f"{shop_type.name} 本地攻略：",
        "如果你在筛选同类型商家，可以先看商圈、人均、评分和营业时间。",
    ]
    if areas:
        lead_lines.append("常见商圈：" + "、".join(areas[:5]) + "。")
    if scene_hints:
        lead_lines.append("适用场景：" + "、".join(scene_hints) + "。")
    if shop_names:
        lead_lines.append("代表商家：" + "、".join(shop_names) + "。")
    text = " ".join(lead_lines)
    guide_key = _stable_key("local-guide", shop_type.id, shop_type.name, tuple(areas), tuple(shop_names))
    child_chunks: list[KnowledgeChunk] = []
    for index, segment in enumerate(split_long_text_by_semantic_units(text), start=1):
        child_chunks.append(
            _make_chunk(
                source_type="local_guide",
                document_id=f"local-life:local-guide:type:{shop_type.id}",
                chunk_index=index,
                title=f"{shop_type.name} 本地生活攻略",
                text=segment,
                category="local_life",
                chunk_type="roadmap",
                subcategory=shop_type.name,
                chunk_level="child",
                parent_id=f"shop_type:{shop_type.id}",
                parent_title=shop_type.name,
                parent_chunk_id=f"local-life:shop-type:{shop_type.id}:parent-summary",
                chunk_role="local_guide",
                entity_type="shop_type_guide",
                entity_id=f"shop_type:{shop_type.id}",
                sibling_roles=("local_guide",),
                metadata={
                    "shop_type_id": shop_type.id,
                    "shop_type_name": shop_type.name,
                    "area_list": areas,
                    "shop_names": shop_names,
                    "city": city,
                    "is_active": True,
                    "version": LOCAL_LIFE_VERSION,
                    "guide_key": guide_key,
                    "chunk_role": "local_guide",
                    "parent_id": f"shop_type:{shop_type.id}",
                    "parent_title": shop_type.name,
                    "entity_type": "shop_type_guide",
                    "entity_id": f"shop_type:{shop_type.id}",
                },
                tags=(
                    shop_type.name,
                    "local_guide",
                    *(tuple(areas[:3]) if areas else ()),
                    *(tuple(scene_hints[:3]) if scene_hints else ()),
                ),
            )
        )
    parent_chunk = _build_shop_type_parent_chunk(shop_type=shop_type, shops=shops, child_chunks=child_chunks)
    return [parent_chunk, *child_chunks]


def _build_shop_type_parent_chunk(
    *,
    shop_type: ShopTypeRecord,
    shops: Sequence[ShopRecord],
    child_chunks: Sequence[KnowledgeChunk],
) -> KnowledgeChunk:
    city = _infer_city(shops[0].address) if shops else None
    areas = list(dict.fromkeys(shop.area for shop in shops if shop.area))
    parent_chunk_id = f"local-life:shop-type:{shop_type.id}:parent-summary"
    child_chunk_ids = tuple(chunk.chunk_id for chunk in child_chunks)
    child_roles = tuple(chunk.chunk_role for chunk in child_chunks if chunk.chunk_role)
    summary_text = _compose_shop_type_parent_summary_text(
        shop_type=shop_type,
        shops=shops,
        child_chunks=child_chunks,
    )
    return _make_chunk(
        source_type="local_guide",
        document_id=parent_chunk_id,
        chunk_id=parent_chunk_id,
        chunk_index=1,
        title=f"{shop_type.name} 商家类型整体摘要",
        text=summary_text,
        summary=_truncate_text(summary_text, max_chars=140),
        category="local_life",
        chunk_type="roadmap",
        subcategory=shop_type.name,
        chunk_level="parent",
        parent_id=f"shop_type:{shop_type.id}",
        parent_title=shop_type.name,
        parent_chunk_id=parent_chunk_id,
        child_chunk_ids=child_chunk_ids,
        child_roles=child_roles,
        chunk_role="shop_type_parent_summary",
        entity_type="shop_type",
        entity_id=f"shop_type:{shop_type.id}",
        sibling_roles=("local_guide",),
        metadata={
            "shop_type_id": shop_type.id,
            "shop_type_name": shop_type.name,
            "area_list": areas,
            "shop_names": [shop.name for shop in shops[:5] if shop.name],
            "city": city,
            "is_active": True,
            "version": LOCAL_LIFE_VERSION,
            "chunk_level": "parent",
            "chunk_role": "shop_type_parent_summary",
            "parent_id": f"shop_type:{shop_type.id}",
            "parent_title": shop_type.name,
            "parent_chunk_id": parent_chunk_id,
            "child_chunk_ids": list(child_chunk_ids),
            "child_roles": list(child_roles),
            "entity_type": "shop_type",
            "entity_id": f"shop_type:{shop_type.id}",
        },
        tags=(
            shop_type.name,
            "shop_type_parent_summary",
            *(tuple(areas[:3]) if areas else ()),
        ),
    )


def _build_platform_rule_chunks() -> tuple[KnowledgeChunk, ...]:
    chunks: list[KnowledgeChunk] = []
    for index, row in enumerate(_PLATFORM_RULE_ROWS, start=1):
        segments = split_long_text_by_semantic_units(row["text"])
        child_chunks: list[KnowledgeChunk] = []
        for part_index, text in enumerate(segments, start=1):
            suffix = f"第{part_index}" if len(segments) > 1 else ""
            child_chunks.append(
                _make_chunk(
                    source_type="platform_rule",
                    document_id=f"local-life:platform-rule:{row['rule_id']}",
                    chunk_index=part_index,
                    title=row["title"],
                    text=text if not suffix else f"{row['title']}{suffix}：{text}",
                    category="local_life",
                    chunk_type=row["chunk_type"],
                    subcategory=row["subcategory"],
                    chunk_level="child",
                    parent_id=f"platform_rule:{row['rule_id']}",
                    parent_title=row["title"],
                    parent_chunk_id=f"local-life:platform-rule:{row['rule_id']}:parent-summary",
                    chunk_role="platform_rule",
                    entity_type="platform_rule",
                    entity_id=f"platform_rule:{row['rule_id']}",
                    sibling_roles=("platform_rule",),
                    metadata={
                        "rule_id": row["rule_id"],
                        "is_active": True,
                        "version": LOCAL_LIFE_VERSION,
                        "rule_order": index,
                        "chunk_role": "platform_rule",
                        "parent_id": f"platform_rule:{row['rule_id']}",
                        "parent_title": row["title"],
                        "entity_type": "platform_rule",
                        "entity_id": f"platform_rule:{row['rule_id']}",
                    },
                    tags=("platform_rule", row["rule_id"]),
                )
            )
        parent_chunk = _build_platform_rule_parent_chunk(row=row, child_chunks=child_chunks, rule_order=index)
        chunks.extend([parent_chunk, *child_chunks])
    return tuple(chunks)


def _build_platform_rule_parent_chunk(
    *,
    row: Mapping[str, Any],
    child_chunks: Sequence[KnowledgeChunk],
    rule_order: int,
) -> KnowledgeChunk:
    parent_chunk_id = f"local-life:platform-rule:{row['rule_id']}:parent-summary"
    child_chunk_ids = tuple(chunk.chunk_id for chunk in child_chunks)
    child_roles = tuple(chunk.chunk_role for chunk in child_chunks if chunk.chunk_role)
    summary_text = _compose_platform_rule_parent_summary_text(
        title=str(row["title"]),
        text=str(row["text"]),
        child_chunks=child_chunks,
    )
    return _make_chunk(
        source_type="platform_rule",
        document_id=parent_chunk_id,
        chunk_id=parent_chunk_id,
        chunk_index=1,
        title=f"{row['title']} 整体摘要",
        text=summary_text,
        summary=_truncate_text(summary_text, max_chars=120),
        category="local_life",
        chunk_type=row["chunk_type"],
        subcategory=row["subcategory"],
        chunk_level="parent",
        parent_id=f"platform_rule:{row['rule_id']}",
        parent_title=row["title"],
        parent_chunk_id=parent_chunk_id,
        child_chunk_ids=child_chunk_ids,
        child_roles=child_roles,
        chunk_role="platform_rule_parent_summary",
        entity_type="platform_rule",
        entity_id=f"platform_rule:{row['rule_id']}",
        sibling_roles=("platform_rule",),
        metadata={
            "rule_id": row["rule_id"],
            "is_active": True,
            "version": LOCAL_LIFE_VERSION,
            "rule_order": rule_order,
            "chunk_level": "parent",
            "chunk_role": "platform_rule_parent_summary",
            "parent_id": f"platform_rule:{row['rule_id']}",
            "parent_title": row["title"],
            "parent_chunk_id": parent_chunk_id,
            "child_chunk_ids": list(child_chunk_ids),
            "child_roles": list(child_roles),
            "entity_type": "platform_rule",
            "entity_id": f"platform_rule:{row['rule_id']}",
        },
        tags=("platform_rule", f"{row['rule_id']}", "platform_rule_parent_summary"),
    )


def _compose_review_summary_text(
    *,
    shop: ShopRecord,
    positive_points: Sequence[str],
    negative_points: Sequence[str],
    keywords: Sequence[str],
    suitable_scenes: Sequence[str],
    unsuitable_scenes: Sequence[str],
) -> str:
    lines = []
    if positive_points:
        lines.append("好评点：" + "；".join(positive_points[:3]) + "。")
    if negative_points:
        lines.append("差评点：" + "；".join(negative_points[:3]) + "。")
    if keywords:
        lines.append("高频关键词：" + "、".join(keywords[:6]) + "。")
    if suitable_scenes:
        lines.append("适合场景：" + "、".join(suitable_scenes[:6]) + "。")
    if unsuitable_scenes:
        lines.append("不适合场景：" + "、".join(unsuitable_scenes[:6]) + "。")
    if not lines:
        return ""
    return f"{shop.name} 的口碑摘要：" + " ".join(lines)


def _compose_scene_fit_text(
    *,
    shop: ShopRecord,
    shop_type: ShopTypeRecord,
    signals: Mapping[str, Sequence[str]],
) -> str:
    scene_items = list(signals.get("suitable_scenes") or [])
    if not scene_items:
        return ""
    return (
        f"{shop.name} 属于{shop_type.name}，更适合{_join_natural(scene_items)}。"
        " 从现有评价和店铺特征看，这类场景下更容易获得稳定体验。"
    )


def _compose_pitfall_summary_text(
    *,
    shop: ShopRecord,
    shop_type: ShopTypeRecord,
    signals: Mapping[str, Sequence[str]],
) -> str:
    pitfall_items = list(signals.get("pitfall_items") or [])
    if not pitfall_items:
        return ""
    return (
        f"{shop.name}（{shop_type.name}）的避坑信息主要是：{_join_natural(pitfall_items[:5])}。"
        " 如果在高峰期或节假日去，建议提前规划。"
    )


def _extract_review_signals(
    shop: ShopRecord,
    *,
    blogs: Sequence[BlogRecord],
    vouchers: Sequence[VoucherRecord],
) -> dict[str, list[str]]:
    text_fragments: list[str] = []
    if shop.review_summary:
        text_fragments.append(str(shop.review_summary))
    text_fragments.extend(str(text) for text in shop.evidence_texts[:5] if text)
    for blog in blogs[:3]:
        if blog.title:
            text_fragments.append(str(blog.title))
        if blog.content:
            text_fragments.append(str(blog.content[:400]))
    if vouchers:
        text_fragments.append("有优惠券可参考")
    combined = " ".join(text_fragments)
    positive_points: list[str] = []
    negative_points: list[str] = []
    keywords: list[str] = []
    suitable_scenes: list[str] = []
    unsuitable_scenes: list[str] = []
    pitfall_items: list[str] = []

    if any(keyword in combined for keyword in ("安静", "安静", "静")):
        positive_points.append("环境相对安静")
        keywords.append("安静")
        suitable_scenes.extend([item for item in ("约会", "家庭聚餐", "带长辈") if item not in suitable_scenes])
    if any(keyword in combined for keyword in ("家庭", "爸妈", "长辈", "老人")):
        positive_points.append("适合家庭一起吃饭")
        keywords.append("家庭")
        suitable_scenes.extend([item for item in ("家庭聚餐", "带长辈") if item not in suitable_scenes])
    if any(keyword in combined for keyword in ("停车",)):
        positive_points.append("停车条件在部分时段还能接受")
        keywords.append("停车")
        if "停车方便" not in suitable_scenes:
            suitable_scenes.append("停车方便")
    if any(keyword in combined for keyword in ("排队", "等位")):
        negative_points.append("高峰期可能要排队")
        pitfall_items.append("排队久")
        unsuitable_scenes.append("工作日午晚高峰")
    if any(keyword in combined for keyword in ("吵", "嘈杂")):
        negative_points.append("环境可能偏吵")
        pitfall_items.append("太吵")
    if any(keyword in combined for keyword in ("贵", "价格高", "偏高")):
        negative_points.append("价格可能偏高")
        pitfall_items.append("价格偏高")
    if any(keyword in combined for keyword in ("慢", "上菜慢", "服务慢")):
        negative_points.append("服务节奏可能偏慢")
        pitfall_items.append("服务慢")
    if any(keyword in combined for keyword in ("预约",)):
        negative_points.append("部分场景建议提前预约")
        pitfall_items.append("需要预约")
    if any(keyword in combined for keyword in ("节假日", "假日")):
        pitfall_items.append("节假日不可用")
    if any(keyword in combined for keyword in ("不方便", "难停", "停车难")):
        pitfall_items.append("停车不方便")

    if not positive_points:
        positive_points.append("口碑整体偏稳")
    if not negative_points:
        negative_points.append("暂无明显负面反馈")
    if not keywords:
        keywords.extend([shop.name, shop.area or shop_type.name])
    if not suitable_scenes:
        suitable_scenes.extend([item for item in ("朋友聚餐", "日常吃饭") if item not in suitable_scenes])
    if not unsuitable_scenes:
        unsuitable_scenes.extend([item for item in ("高峰期",) if item not in unsuitable_scenes])
    if not pitfall_items:
        pitfall_items.append("暂无明显硬伤，但建议结合时间段和预算判断")

    return {
        "positive_points": list(dict.fromkeys(positive_points)),
        "negative_points": list(dict.fromkeys(negative_points)),
        "keywords": list(dict.fromkeys(keywords)),
        "suitable_scenes": list(dict.fromkeys(suitable_scenes)),
        "unsuitable_scenes": list(dict.fromkeys(unsuitable_scenes)),
        "pitfall_items": list(dict.fromkeys(pitfall_items)),
    }


def _make_chunk(
    *,
    source_type: str,
    document_id: str,
    chunk_index: int,
    chunk_id: Optional[str] = None,
    title: str,
    text: str,
    category: str,
    chunk_type: str,
    subcategory: Optional[str] = None,
    summary: Optional[str] = None,
    chunk_level: str = "child",
    parent_id: Optional[str] = None,
    parent_title: Optional[str] = None,
    parent_chunk_id: Optional[str] = None,
    child_chunk_ids: Sequence[str] = (),
    child_roles: Sequence[str] = (),
    chunk_role: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    sibling_source_types: Sequence[str] = (),
    sibling_roles: Sequence[str] = (),
    metadata: Optional[Mapping[str, Any]] = None,
    tags: Sequence[str] = (),
) -> KnowledgeChunk:
    chunk_id = chunk_id or f"{document_id}:chunk-{int(chunk_index):03d}"
    payload_metadata = dict(metadata or {})
    payload_metadata.setdefault("chunk_level", chunk_level)
    if parent_id is not None:
        payload_metadata.setdefault("parent_id", parent_id)
    if parent_title is not None:
        payload_metadata.setdefault("parent_title", parent_title)
    if parent_chunk_id is not None:
        payload_metadata.setdefault("parent_chunk_id", parent_chunk_id)
    if child_chunk_ids:
        payload_metadata.setdefault("child_chunk_ids", list(dict.fromkeys(str(item) for item in child_chunk_ids if item)))
    if child_roles:
        payload_metadata.setdefault("child_roles", list(dict.fromkeys(str(item) for item in child_roles if item)))
    if chunk_role is not None:
        payload_metadata.setdefault("chunk_role", chunk_role)
    if entity_type is not None:
        payload_metadata.setdefault("entity_type", entity_type)
    if entity_id is not None:
        payload_metadata.setdefault("entity_id", entity_id)
    chunk_role_label = _chunk_role_label(chunk_role)
    source_type_label = _source_type_label(source_type)
    if chunk_role_label:
        payload_metadata.setdefault("chunk_role_label", chunk_role_label)
    if source_type_label:
        payload_metadata.setdefault("source_type_label", source_type_label)
    if sibling_source_types:
        payload_metadata.setdefault("sibling_source_types", list(dict.fromkeys(str(item) for item in sibling_source_types if item)))
    if sibling_roles:
        payload_metadata.setdefault("sibling_roles", list(dict.fromkeys(str(item) for item in sibling_roles if item)))
    payload_metadata.setdefault(
        "search_keywords",
        list(
            _search_keywords(
                title,
                parent_title,
                payload_metadata.get("shop_name"),
                payload_metadata.get("city"),
                payload_metadata.get("area"),
                payload_metadata.get("subcategory"),
                payload_metadata.get("chunk_role_label"),
                payload_metadata.get("source_type_label"),
                tags,
            )
        ),
    )
    return KnowledgeChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        text=text,
        title=title,
        summary=summary if summary is not None else _summarize_text(text),
        category=category,
        subcategory=subcategory,
        source_type=source_type,
        chunk_type=chunk_type,
        chunk_level=chunk_level,
        version=LOCAL_LIFE_VERSION,
        parent_id=parent_id,
        parent_title=parent_title,
        parent_chunk_id=parent_chunk_id,
        child_chunk_ids=tuple(str(item) for item in child_chunk_ids if item),
        child_roles=tuple(str(item) for item in child_roles if item),
        chunk_role=chunk_role,
        entity_type=entity_type,
        entity_id=entity_id,
        is_latest=True,
        is_active=bool(payload_metadata.get("is_active", True)),
        hash=hashlib.sha1(f"{document_id}:{chunk_id}:{text}".encode("utf-8")).hexdigest(),
        tags=tuple(dict.fromkeys(str(tag) for tag in tags if tag)),
        metadata=payload_metadata,
    )


def _chunk_to_point(
    chunk: KnowledgeChunk,
    *,
    embedding_adapter: Any,
    vector_name: str,
    vector_size: int,
) -> Any:
    dense_text = chunk.searchable_dense_text() or chunk.searchable_text()
    vector = embedding_adapter.embed(dense_text)
    if len(vector) != int(vector_size):
        raise RuntimeError(
            f"Embedding dimension mismatch for {chunk.chunk_id}: expected {vector_size}, got {len(vector)}"
        )
    payload = chunk.to_payload()
    payload.setdefault("dense_text", dense_text)
    payload.setdefault("sparse_text", chunk.searchable_sparse_text())
    point_id = uuid.uuid5(uuid.NAMESPACE_URL, f"local-life:{chunk.chunk_id}")
    named_vector = {vector_name: vector}
    if PointStruct is not None:
        return PointStruct(id=point_id, vector=named_vector, payload=payload)
    return {"id": point_id, "vector": named_vector, "payload": payload}


def _upsert_points(qdrant_client: Any, collection_name: str, points: Sequence[Any]) -> None:
    upsert = getattr(qdrant_client, "upsert", None)
    if not callable(upsert):
        raise RuntimeError("Qdrant client does not expose upsert")
    try:
        upsert(collection_name=collection_name, points=list(points), wait=True)
    except TypeError:
        upsert(collection_name=collection_name, points=list(points))


def ensure_local_life_payload_indexes(qdrant_client: Any, *, collection_name: str) -> tuple[str, ...]:
    create_payload_index = getattr(qdrant_client, "create_payload_index", None)
    if not callable(create_payload_index):
        return ()
    created_fields: list[str] = []
    for field_name, field_schema in _LOCAL_LIFE_PAYLOAD_INDEXES:
        if _create_payload_index(create_payload_index, collection_name, field_name, field_schema):
            created_fields.append(field_name)
        else:
            created_fields.append(field_name)
    return tuple(created_fields)


def _create_payload_index(create_payload_index: Any, collection_name: str, field_name: str, field_schema: Any) -> bool:
    try:
        create_payload_index(
            collection_name=collection_name,
            field_name=field_name,
            field_schema=field_schema,
            wait=True,
        )
        return True
    except TypeError as schema_error:
        try:
            create_payload_index(
                collection_name=collection_name,
                field_name=field_name,
                field_type=field_schema,
                wait=True,
            )
            return True
        except Exception as field_type_error:
            if _is_payload_index_already_exists_error(field_type_error):
                _LOGGER.info(
                    "local_life_seed_payload_index_exists collection=%s field=%s",
                    collection_name,
                    field_name,
                )
                return False
            raise field_type_error from schema_error
    except Exception as exc:
        if _is_payload_index_already_exists_error(exc):
            _LOGGER.info(
                "local_life_seed_payload_index_exists collection=%s field=%s",
                collection_name,
                field_name,
            )
            return False
        raise


def _is_payload_index_already_exists_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(
        token in text
        for token in (
            "already exists",
            "already exist",
            "already created",
            "index already",
            "duplicate",
            "conflict",
        )
    )


def _cleanup_stale_points(
    qdrant_client: Any,
    *,
    collection_name: str,
    current_chunk_ids: Sequence[str],
    scoped_parent_ids: Sequence[str] = (),
    scoped_update: bool = False,
) -> int:
    delete = getattr(qdrant_client, "delete", None)
    if not callable(delete):
        return 0
    must_not = []
    if current_chunk_ids:
        must_not.append(
            HasIdCondition(has_id=[uuid.uuid5(uuid.NAMESPACE_URL, f"local-life:{chunk_id}") for chunk_id in current_chunk_ids])
        )
    must = [
        FieldCondition(key="category", match=MatchValue(value="local_life")),
    ]
    parent_ids = [str(parent_id) for parent_id in scoped_parent_ids if str(parent_id).strip()]
    if scoped_update:
        if not parent_ids:
            _LOGGER.info("local_life_seed_skip_stale_cleanup_due_to_empty_scope collection=%s", collection_name)
            return 0
        must.append(FieldCondition(key="parent_id", match=MatchAny(any=parent_ids)))
    filter_selector = Filter(
        must=must,
        must_not=must_not or None,
    )
    response = delete(collection_name=collection_name, points_selector=filter_selector, wait=True)
    deleted = _extract_deleted_count(response)
    return deleted


def _extract_deleted_count(response: Any) -> int:
    if response is None:
        return 0
    for name in ("deleted_count", "deleted", "points_deleted"):
        value = _extract_value(response, name)
        if value is not None:
            try:
                return int(value)
            except Exception:
                continue
    return 0


def _validate_collection_vector_shape(
    qdrant_client: Any,
    *,
    collection_name: str,
    vector_name: str,
    vector_size: int,
) -> None:
    get_collection = getattr(qdrant_client, "get_collection", None)
    if not callable(get_collection):
        return
    info = get_collection(collection_name)
    vectors = _extract_vectors_config(info)
    candidate = None
    if isinstance(vectors, Mapping):
        candidate = vectors.get(vector_name)
        if candidate is None and len(vectors) == 1:
            candidate = next(iter(vectors.values()))
    else:
        candidate = vectors
    if candidate is None:
        raise LocalLifeQdrantCollectionShapeError(
            f"Qdrant collection {collection_name} does not expose vector config"
        )
    current_size = _extract_value(candidate, "size")
    current_distance = _extract_value(candidate, "distance")
    if current_size is not None and int(current_size) != int(vector_size):
        raise LocalLifeQdrantCollectionShapeError(
            f"Qdrant collection {collection_name} vector size mismatch: expected {vector_size}, got {current_size}"
        )
    if current_distance is not None and str(current_distance).lower() != "cosine":
        raise LocalLifeQdrantCollectionShapeError(
            f"Qdrant collection {collection_name} distance mismatch: expected cosine, got {current_distance}"
        )


def _extract_vectors_config(info: Any) -> Any:
    if isinstance(info, Mapping):
        config = info.get("config", info)
        if isinstance(config, Mapping):
            params = config.get("params", config)
            if isinstance(params, Mapping):
                return params.get("vectors") or params.get("vectors_config")
            return _extract_value(params, "vectors") or _extract_value(params, "vectors_config")
        params = _extract_value(config, "params")
        if params is not None:
            return _extract_value(params, "vectors") or _extract_value(params, "vectors_config")
        return _extract_value(config, "vectors") or _extract_value(config, "vectors_config")
    config = _extract_value(info, "config")
    if config is not None:
        params = _extract_value(config, "params")
        if params is not None:
            vectors = _extract_value(params, "vectors")
            if vectors is not None:
                return vectors
            return _extract_value(params, "vectors_config")
    params = _extract_value(info, "params")
    if params is not None:
        vectors = _extract_value(params, "vectors")
        if vectors is not None:
            return vectors
        return _extract_value(params, "vectors_config")
    return _extract_value(info, "vectors") or _extract_value(info, "vectors_config")


def _extract_value(obj: Any, name: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, Mapping):
        return obj.get(name)
    return getattr(obj, name, None)


def _resolve_shop_detail(business_client: JavaBusinessClient, shop: ShopRecord) -> Optional[ShopRecord]:
    if shop is None:
        return None
    try:
        detail = business_client.get_shop_detail(shop.id)
    except Exception:
        detail = None
    if detail is None:
        return shop
    merged = shop.model_copy()
    for field_name, value in detail.model_dump(mode="python").items():
        if value not in (None, "", [], {}):
            setattr(merged, field_name, value)
    return merged


def _safe_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return list(value)


def _dedupe_chunks(chunks: Iterable[KnowledgeChunk]) -> tuple[KnowledgeChunk, ...]:
    seen: dict[str, KnowledgeChunk] = {}
    for chunk in chunks:
        seen[chunk.chunk_id] = chunk
    return tuple(sorted(seen.values(), key=lambda item: (item.source_type or "", item.document_id, item.chunk_id)))


def _summarize_text(text: str, limit: int = 220) -> str:
    collapsed = " ".join(part.strip() for part in text.splitlines() if part.strip())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 3].rstrip() + "..."


def _infer_city(address: Optional[str]) -> Optional[str]:
    text = str(address or "")
    for city in _CITY_HINTS:
        if city in text:
            return city
    match = re.match(r"^([\u4e00-\u9fff]{2,3})", text.strip())
    if match:
        return match.group(1)
    return None


def _derive_review_trend(
    shop: ShopRecord,
    blogs: Sequence[BlogRecord],
    vouchers: Sequence[VoucherRecord],
) -> str:
    fragments = []
    if shop.review_summary:
        fragments.append(shop.review_summary)
    for blog in blogs[:3]:
        if blog.title:
            fragments.append(blog.title)
        if blog.content:
            fragments.append(blog.content)
    if vouchers:
        fragments.append("有优惠券可参考")
    text = " ".join(fragments)
    if any(keyword in text for keyword in ("安静", "安静", "静")):
        return "评论多次提到环境安静"
    if any(keyword in text for keyword in ("家庭", "爸妈", "长辈", "老人")):
        return "适合家庭聚餐"
    if any(keyword in text for keyword in ("排队", "热闹")):
        return "人气较高，可能需要排队"
    return "口碑信息偏正向，可结合具体需求再判断"


def _guide_scene_hints(shops: Sequence[ShopRecord]) -> list[str]:
    hints: list[str] = []
    for shop in shops:
        if shop.family_friendly and "家庭聚餐" not in hints:
            hints.append("家庭聚餐")
        if shop.elder_friendly and "带长辈" not in hints:
            hints.append("带长辈")
        if shop.parking and "停车方便" not in hints:
            hints.append("停车方便")
        if shop.quiet_score >= 0.8 and "环境安静" not in hints:
            hints.append("环境安静")
    return hints


def _chunk_tags(
    shop: ShopRecord,
    shop_type: ShopTypeRecord,
    city: Optional[str],
    *,
    source_type: str,
    extra: Sequence[str] = (),
) -> tuple[str, ...]:
    tags = [
        source_type,
        shop_type.name,
        shop.area or "",
        city or "",
        shop.name or "",
    ]
    tags.extend(extra)
    return tuple(dict.fromkeys(tag for tag in tags if tag))


def _format_price(value: Optional[float]) -> str:
    if value is None:
        return "未知"
    if float(value).is_integer():
        return str(int(value))
    return f"{float(value):.2f}".rstrip("0").rstrip(".")


def _format_score(value: Optional[float]) -> str:
    if value is None:
        return "0.0"
    score = float(value)
    if score > 5.0:
        score = score / 10.0
    return f"{score:.1f}"


def _format_int(value: Optional[int]) -> str:
    return "0" if value is None else str(int(value))


def _stable_key(*parts: Any) -> str:
    raw = "|".join(str(part) for part in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed local life knowledge chunks into Qdrant.")
    parser.add_argument("--collection-name", default=LOCAL_LIFE_PARENT_CHILD_COLLECTION)
    parser.add_argument("--vector-name", default=LOCAL_LIFE_VECTOR_NAME)
    parser.add_argument("--vector-size", type=int, default=LOCAL_LIFE_VECTOR_SIZE)
    parser.add_argument("--shop-limit-per-type", type=int, default=5)
    parser.add_argument("--voucher-limit", type=int, default=3)
    parser.add_argument("--blog-limit", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--shop-id", action="append", dest="shop_ids", type=int, default=[])
    parser.add_argument("--voucher-id", action="append", dest="voucher_ids", type=int, default=[])
    parser.add_argument("--shop-type-id", action="append", dest="shop_type_ids", type=int, default=[])
    parser.add_argument(
        "--no-cleanup-stale-points",
        action="store_false",
        dest="cleanup_stale_points",
        help="Disable stale point cleanup after seeding.",
    )
    parser.set_defaults(cleanup_stale_points=True)
    return parser


def _format_seed_summary_lines(result: LocalLifeKnowledgeSeedResult) -> tuple[str, ...]:
    role_pairs = sorted(result.chunk_role_counts.items(), key=lambda item: (-int(item[1]), item[0]))
    role_summary = ", ".join(f"{role}:{count}" for role, count in role_pairs) if role_pairs else "无"
    source_pairs = sorted(result.source_type_counts.items(), key=lambda item: (-int(item[1]), item[0]))
    source_summary = ", ".join(f"{source_type}:{count}" for source_type, count in source_pairs) if source_pairs else "无"
    return (
        f"本地生活 Qdrant 灌库完成：collection={result.collection_name} vector={result.vector_name} size={result.vector_size}",
        f"chunks={result.chunk_count} points={result.point_count} batches={len(result.upsert_batches)} deleted={result.deleted_point_count} duration={result.duration_seconds:.2f}s",
        f"source_type_counts: {source_summary}",
        f"chunk_role_counts: {role_summary}",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    settings = get_settings()
    business_client = JavaBusinessClient(settings=settings)
    openai_runtime = build_openai_runtime(settings.openai)
    qdrant_runtime = build_qdrant_runtime(settings.qdrant)
    embedding_adapter = OpenAIEmbeddingAdapter(runtime=openai_runtime, model=settings.openai.embedding_model)
    try:
        result = seed_local_life_knowledge(
            business_client=business_client,
            qdrant_client=qdrant_runtime.client,
            embedding_adapter=embedding_adapter,
            collection_name=args.collection_name,
            vector_name=args.vector_name,
            vector_size=args.vector_size,
            shop_limit_per_type=args.shop_limit_per_type,
            voucher_limit=args.voucher_limit,
            blog_limit=args.blog_limit,
            batch_size=args.batch_size,
            cleanup_stale_points=args.cleanup_stale_points,
            shop_ids=args.shop_ids or None,
            voucher_ids=args.voucher_ids or None,
            shop_type_ids=args.shop_type_ids or None,
        )
        for line in _format_seed_summary_lines(result):
            print(line)
    finally:
        business_client.close()
    return 0


__all__ = [
    "LOCAL_LIFE_KNOWLEDGE_COLLECTION",
    "LOCAL_LIFE_HYBRID_COLLECTION",
    "LOCAL_LIFE_PARENT_CHILD_COLLECTION",
    "LOCAL_LIFE_SOURCE_TYPES",
    "LOCAL_LIFE_VECTOR_NAME",
    "LOCAL_LIFE_VECTOR_SIZE",
    "LOCAL_LIFE_VERSION",
    "LocalLifeKnowledgeSeedResult",
    "LocalLifeQdrantCollectionShapeError",
    "build_arg_parser",
    "build_local_life_knowledge_chunks",
    "ensure_local_life_collection",
    "ensure_local_life_payload_indexes",
    "_format_seed_summary_lines",
    "main",
    "seed_local_life_knowledge",
    "seed_local_life_knowledge_from_settings",
    "seed_local_life_hybrid_knowledge_from_settings",
    "seed_local_life_parent_child_knowledge_from_settings",
]


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
