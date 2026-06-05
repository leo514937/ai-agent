from __future__ import annotations

import asyncio
import logging
import math
import re
import time
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

try:  # pragma: no cover - optional dependency path
    import httpx
except Exception:  # pragma: no cover - httpx may be unavailable in some runtime slices
    httpx = None  # type: ignore[assignment]

try:  # pragma: no cover - optional dependency path
    from rank_bm25 import BM25Okapi
except Exception:  # pragma: no cover - rank-bm25 may be unavailable in some runtime slices
    BM25Okapi = None  # type: ignore[assignment]

from ..models import (
    HybridRecallResult,
    KnowledgeChunk,
    RecallHit,
    RetrievalFilters,
    RetrievalPlan,
    RetrievalTrace,
    RetrievalTraceItem,
)
from ..protocols import DenseRetriever, MetadataRetriever, Reranker, SparseRetriever
from ..qdrant_filters import _RUNTIME_FILTER_KEYS, QdrantFilterBuilder
from ..rewrite import QueryRewriteService
from learning_agent_service.domain.utils import coerce_float as _coerce_float

_LOGGER = logging.getLogger(__name__)
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_+#.:-]+|[\u4e00-\u9fff]+")

def _collection_vectors(collection_info: Any) -> Any:
    config = getattr(collection_info, "config", None)
    params = getattr(config, "params", None) if config is not None else None
    if params is None:
        return None
    vectors = getattr(params, "vectors", None)
    if vectors is not None:
        return vectors
    return getattr(params, "sparse_vectors", None)

def _distance_value(distance: Any) -> str:
    val = distance.value if hasattr(distance, "value") else distance
    return str(val or "").strip().lower()

def _distance_matches(expected: Any, actual: Any) -> bool:
    return _distance_value(expected) == _distance_value(actual)

def validate_qdrant_collection_shape(
    client: Any,
    *,
    collection_name: str,
    vector_name: str,
    vector_size: int | None = None,
    distance: Any | None = None,
    action_hint: str = "run the dedicated seed or reindex command",
) -> None:
    get_collection = getattr(client, "get_collection", None)
    if not callable(get_collection):
        return
    try:
        collection_info = get_collection(collection_name)
    except Exception as exc:
        raise RuntimeError(
            "Qdrant collection missing:\n"
            f"collection={collection_name}\n"
            f"vector_name={vector_name}\n"
            f"action={action_hint}"
        ) from exc

    vectors = _collection_vectors(collection_info)
    if vectors is None:
        raise RuntimeError(
            "Qdrant collection shape mismatch:\n"
            f"collection={collection_name}\n"
            f"vector_name={vector_name}\n"
            f"expected_vector_size={vector_size if vector_size is not None else 'unknown'}\n"
            "actual_vector_size=unknown\n"
            f"expected_distance={_distance_value(distance) if distance is not None else 'unknown'}\n"
            "actual_distance=unknown\n"
            f"action={action_hint}"
        )
    if not isinstance(vectors, Mapping):
        raise RuntimeError(
            "Qdrant collection shape mismatch:\n"
            f"collection={collection_name}\n"
            f"vector_name={vector_name}\n"
            f"expected_vector_size={vector_size if vector_size is not None else 'unknown'}\n"
            "actual_vector_size=unknown\n"
            f"expected_distance={_distance_value(distance) if distance is not None else 'unknown'}\n"
            "actual_distance=unknown\n"
            f"action={action_hint}"
        )
    vector_params = vectors.get(vector_name)
    if vector_params is None:
        sparse_vectors = getattr(collection_info.config.params, "sparse_vectors", None) if getattr(collection_info, "config", None) is not None else None
        if isinstance(sparse_vectors, Mapping):
            vector_params = sparse_vectors.get(vector_name)
    if vector_params is None:
        raise RuntimeError(
            "Qdrant collection shape mismatch:\n"
            f"collection={collection_name}\n"
            f"vector_name={vector_name}\n"
            f"expected_vector_size={vector_size if vector_size is not None else 'unknown'}\n"
            "actual_vector_size=unknown\n"
            f"expected_distance={_distance_value(distance) if distance is not None else 'unknown'}\n"
            "actual_distance=unknown\n"
            f"action={action_hint}"
        )
    size = getattr(vector_params, "size", None)
    actual_distance = getattr(vector_params, "distance", None)
    if vector_size is not None and size is not None and int(size) != int(vector_size):
        raise RuntimeError(
            "Qdrant collection shape mismatch:\n"
            f"collection={collection_name}\n"
            f"vector_name={vector_name}\n"
            f"expected_vector_size={vector_size}\n"
            f"actual_vector_size={size}\n"
            f"expected_distance={_distance_value(distance) if distance is not None else 'unknown'}\n"
            f"actual_distance={_distance_value(actual_distance) if actual_distance is not None else 'unknown'}\n"
            f"action={action_hint}"
        )
    if distance is not None and actual_distance is not None and not _distance_matches(distance, actual_distance):
        raise RuntimeError(
            "Qdrant collection shape mismatch:\n"
            f"collection={collection_name}\n"
            f"vector_name={vector_name}\n"
            f"expected_vector_size={vector_size if vector_size is not None else 'unknown'}\n"
            f"actual_vector_size={size if size is not None else 'unknown'}\n"
            f"expected_distance={_distance_value(distance)}\n"
            f"actual_distance={_distance_value(actual_distance)}\n"
            f"action={action_hint}"
        )

def _with_hit_provenance(
    hit: RecallHit,
    *,
    retrieval_kind: str,
    collection_name: str = "",
    source_domain: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> RecallHit:
    return replace(
        hit,
        retrieval_kind=retrieval_kind,
        collection_name=collection_name,
        source_domain=source_domain,
        metadata={**dict(hit.metadata), **dict(metadata or {})},
    )

class RetrieverRoute(Protocol):
    route_name: str

    def retrieve(self, plan: RetrievalPlan) -> Sequence[RecallHit]:
        ...

@dataclass(frozen=True)
class HybridRerankConfig:
    top_k: int = 15

@dataclass(frozen=True)
class RRFConfig:
    k: int = 60
    route_weights: Mapping[str, float] = field(
        default_factory=lambda: {"dense": 1.0, "sparse": 1.0, "metadata": 0.6}
    )


_SOFT_METADATA_WEIGHTS = {
    "category": 0.22,
    "subcategory": 0.18,
    "difficulty": 0.10,
    "source_type": 0.14,
    "chunk_type": 0.10,
    "version": 0.08,
    "tags": 0.12,
    "entity_type": 0.08,
    "entity_id": 0.08,
    "shop_id": 0.10,
}

def _tokenize(text: str) -> tuple[str, ...]:
    if not text:
        return ()
    return tuple(token.lower() for token in _TOKEN_PATTERN.findall(text))

def _jaccard(left: Sequence[str], right: Sequence[str]) -> float:
    left_set = set(left)
    right_set = set(right)
    if not left_set or not right_set:
        return 0.0
    intersection = len(left_set & right_set)
    union = len(left_set | right_set)
    return intersection / float(union or 1)

def _term_overlap(left: Sequence[str], right: Sequence[str]) -> float:
    if not left or not right:
        return 0.0
    right_set = set(right)
    matched = sum(1 for token in left if token in right_set)
    return matched / float(max(len(left), 1))

def _dedupe_queries(queries: Sequence[str]) -> tuple[str, ...]:
    seen = set()
    ordered: list[str] = []
    for query in queries:
        normalized = (query or "").strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(normalized)
    return tuple(ordered)

def _serialize_final_filters(plan: RetrievalPlan) -> dict[str, Any]:
    extra = dict(plan.retrieval_filters.extra)
    for key in _RUNTIME_FILTER_KEYS:
        if key in plan.extra and key not in extra:
            extra[key] = plan.extra[key]
    return {
        "category": list(plan.retrieval_filters.category),
        "subcategory": list(plan.retrieval_filters.subcategory),
        "difficulty": list(plan.retrieval_filters.difficulty),
        "source_type": list(plan.retrieval_filters.source_type),
        "chunk_type": list(plan.retrieval_filters.chunk_type),
        "version": list(plan.retrieval_filters.version),
        "tags": list(plan.retrieval_filters.tags),
        "extra": extra,
    }

def _sanitize_trace_text(value: Any, *, limit: int = 256) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"

def _is_hard_metadata_key(key: str) -> bool:
    normalized = _normalize_value(key)
    return normalized in _HARD_METADATA_KEYS or normalized.startswith("tenant_") or normalized.startswith("permission_")

def _coerce_filter_values(value: Any) -> tuple[str, ...]:
    if not value:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Mapping):
        return tuple(str(item) for item in value.values() if item)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(str(item) for item in value if item)
    return (str(value),)

def _extract_soft_metadata_filters(plan: RetrievalPlan) -> dict[str, tuple[str, ...]]:
    if plan.metadata_filter_mode == "hard":
        return {}
    return {key: values for key, values in plan.retrieval_filters.soft_fields().items() if values}

def _extract_hard_metadata_filters(plan: RetrievalPlan) -> dict[str, tuple[str, ...]]:
    hard: dict[str, tuple[str, ...]] = {}
    for key, values in plan.retrieval_filters.hard_fields().items():
        if values:
            hard[key] = values
    for key, value in plan.retrieval_filters.extra.items():
        if _is_hard_metadata_key(str(key)):
            normalized = _coerce_filter_values(value)
            if normalized:
                hard[str(key)] = normalized
    if plan.metadata_filter_mode == "hard":
        for key, values in plan.retrieval_filters.soft_fields().items():
            if values:
                hard[key] = values
    return hard

def _metadata_value_for_key(chunk: KnowledgeChunk, key: str) -> Any:
    if key == "category":
        return chunk.category
    if key == "subcategory":
        return chunk.subcategory
    if key == "difficulty":
        return chunk.difficulty
    if key == "source_type":
        return chunk.source_type
    if key == "chunk_type":
        return chunk.chunk_type
    if key == "version":
        return chunk.version
    if key == "tags":
        return chunk.tags
    return chunk.metadata.get(key)

def _value_matches(actual: Any, expected: Sequence[str]) -> bool:
    actual_values = _coerce_filter_values(actual)
    expected_values = {value.lower() for value in expected if value}
    if not expected_values:
        return True
    if not actual_values:
        return False
    return any(value.lower() in expected_values for value in actual_values)

def _matches_hard_filters(chunk: KnowledgeChunk, filters: Mapping[str, tuple[str, ...]]) -> bool:
    for key, expected in filters.items():
        if not _value_matches(_metadata_value_for_key(chunk, key), expected):
            return False
    return True

def _hard_metadata_score(chunk: KnowledgeChunk, filters: Mapping[str, tuple[str, ...]]) -> float:
    if not filters:
        return 0.0
    matched = 0
    total = 0
    for key, expected in filters.items():
        total += 1
        if _value_matches(_metadata_value_for_key(chunk, key), expected):
            matched += 1
    return matched / float(total or 1)

def _soft_metadata_score(chunk: KnowledgeChunk, filters: Mapping[str, tuple[str, ...]]) -> float:
    if not filters:
        return 0.0
    total_weight = 0.0
    matched_weight = 0.0
    for key, expected in filters.items():
        weight = _SOFT_METADATA_WEIGHTS.get(key, 0.08)
        total_weight += weight
        if _value_matches(_metadata_value_for_key(chunk, key), expected):
            matched_weight += weight
    return matched_weight / float(total_weight or 1.0)

def _matches_filters(chunk: KnowledgeChunk, filters: RetrievalFilters) -> bool:
    checks = (
        (filters.category, chunk.category),
        (filters.subcategory, chunk.subcategory),
        (filters.difficulty, chunk.difficulty),
        (filters.source_type, chunk.source_type),
        (filters.chunk_type, chunk.chunk_type),
        (filters.version, chunk.version),
    )
    for expected, actual in checks:
        normalized_expected = {_normalize_value(value) for value in expected if value}
        normalized_actual = _normalize_value(actual)
        if normalized_expected and normalized_actual not in normalized_expected:
            return False
    if filters.tags and not {_normalize_value(tag) for tag in filters.tags}.issubset(
        {_normalize_value(tag) for tag in chunk.tags}
    ):
        return False
    for key, expected in filters.extra.items():
        actual = chunk.metadata.get(key)
        if isinstance(expected, (list, tuple, set)):
            normalized_expected = {_normalize_value(value) for value in expected if value}
            if _normalize_value(actual) not in normalized_expected:
                return False
        elif _normalize_value(actual) != _normalize_value(expected):
            return False
    return True

def _count_filter_constraints(filters: RetrievalFilters) -> int:
    total = 0
    for values in filters.as_dict().values():
        if values:
            total += 1
    total += len(filters.extra)
    return total

def _count_filter_matches(chunk: KnowledgeChunk, filters: RetrievalFilters) -> int:
    matches = 0
    checks = (
        (filters.category, chunk.category),
        (filters.subcategory, chunk.subcategory),
        (filters.difficulty, chunk.difficulty),
        (filters.source_type, chunk.source_type),
        (filters.chunk_type, chunk.chunk_type),
        (filters.version, chunk.version),
    )
    for expected, actual in checks:
        normalized_expected = {_normalize_value(value) for value in expected if value}
        if normalized_expected and _normalize_value(actual) in normalized_expected:
            matches += 1
    if filters.tags and {_normalize_value(tag) for tag in filters.tags}.issubset(
        {_normalize_value(tag) for tag in chunk.tags}
    ):
        matches += 1
    for key, expected in filters.extra.items():
        actual = chunk.metadata.get(key)
        if isinstance(expected, (list, tuple, set)):
            normalized_expected = {_normalize_value(value) for value in expected if value}
            if _normalize_value(actual) in normalized_expected:
                matches += 1
        elif _normalize_value(actual) == _normalize_value(expected):
            matches += 1
    return matches

def _normalize_value(value: object) -> str:
    return str(value or "").strip().lower()

def _normalize_points(response: Any) -> Sequence[Any]:
    if response is None:
        return ()
    if isinstance(response, tuple) and len(response) == 2:
        return response[0] or ()
    points = getattr(response, "points", None)
    if points is not None:
        return points or ()
    if isinstance(response, Mapping):
        return response.get("points", ()) or ()
    if isinstance(response, Sequence) and not isinstance(response, (str, bytes, bytearray)):
        return response
    return ()

def _point_to_chunk(point: Any) -> KnowledgeChunk | None:
    payload = getattr(point, "payload", None)
    if payload is None and isinstance(point, Mapping):
        payload = point.get("payload")
    if not isinstance(payload, Mapping):
        return None
    return KnowledgeChunk.from_payload(payload, fallback_chunk_id=str(getattr(point, "id", "") or ""))  # type: ignore[arg-type]

def _point_score(point: Any) -> float:
    score = getattr(point, "score", None)
    if score is None and isinstance(point, Mapping):
        score = point.get("score")
    try:
        return float(score or 0.0)
    except Exception:
        return 0.0

__all__ = [name for name in globals() if not name.startswith("__")]
