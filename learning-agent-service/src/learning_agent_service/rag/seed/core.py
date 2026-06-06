from __future__ import annotations

import argparse
import logging
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from learning_agent_service.adapters.java_business import JavaBusinessClient
from learning_agent_service.application.dependencies import OpenAIEmbeddingAdapter
from learning_agent_service.config.settings import Settings, get_settings
from learning_agent_service.infrastructure.db.openai_client import build_openai_runtime
from learning_agent_service.infrastructure.db.qdrant import build_qdrant_runtime
from learning_agent_service.local_life.schemas import (
    ShopRecord,
)

from ..models import KnowledgeChunk

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


from .context_builder import *# noqa: F401,F403,F405
from .entity_resolver import *# noqa: F401,F403,F405

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

__all__ = [name for name in globals() if not name.startswith("__")]
