from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, MutableMapping, Optional, Sequence

from .models import KnowledgeChunk

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class KnowledgeChunkBackfillPlan:
    source_payload: Mapping[str, Any]
    normalized_payload: Mapping[str, Any]
    missing_fields: tuple[str, ...]
    needs_backfill: bool


@dataclass(frozen=True)
class KnowledgeChunkBackfillResult:
    processed_count: int
    updated_count: int
    skipped_count: int
    plans: tuple[KnowledgeChunkBackfillPlan, ...]


def plan_knowledge_chunk_backfill(payload: Mapping[str, Any] | KnowledgeChunk) -> KnowledgeChunkBackfillPlan:
    if isinstance(payload, KnowledgeChunk):
        source_payload: Mapping[str, Any] = payload.to_payload()
    else:
        source_payload = dict(payload)

    normalized = _normalize_payload(source_payload)
    missing_fields = tuple(field for field in _required_fields() if field not in source_payload)
    needs_backfill = bool(missing_fields)
    return KnowledgeChunkBackfillPlan(
        source_payload=source_payload,
        normalized_payload=normalized,
        missing_fields=missing_fields,
        needs_backfill=needs_backfill,
    )


def execute_knowledge_chunk_backfill(
    *,
    client: Any,
    collection_name: str,
    chunks: Iterable[KnowledgeChunk | Mapping[str, Any]],
    batch_size: int = 128,
) -> KnowledgeChunkBackfillResult:
    plans = tuple(plan_knowledge_chunk_backfill(chunk) for chunk in chunks)
    if not plans:
        return KnowledgeChunkBackfillResult(processed_count=0, updated_count=0, skipped_count=0, plans=())

    updated = 0
    skipped = 0
    batch: list[KnowledgeChunkBackfillPlan] = []
    for plan in plans:
        if not plan.needs_backfill:
            skipped += 1
        else:
            updated += 1
        batch.append(plan)
        if len(batch) >= max(batch_size, 1):
            _write_backfill_batch(client, collection_name, batch)
            batch = []
    if batch:
        _write_backfill_batch(client, collection_name, batch)
    return KnowledgeChunkBackfillResult(
        processed_count=len(plans),
        updated_count=updated,
        skipped_count=skipped,
        plans=plans,
    )


def _normalize_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    normalized: MutableMapping[str, Any] = dict(payload)
    document_id = normalized.get("document_id") or normalized.get("doc_id") or normalized.get("source_id")
    chunk_id = normalized.get("chunk_id")
    parent_id = normalized.get("parent_id") or normalized.get("parent_chunk_id")
    text = normalized.get("text") or normalized.get("content") or ""
    if document_id and "doc_id" not in normalized:
        normalized["doc_id"] = document_id
    if chunk_id and "chunk_id" not in normalized:
        normalized["chunk_id"] = chunk_id
    if parent_id and "parent_id" not in normalized:
        normalized["parent_id"] = parent_id
    if parent_id and "parent_chunk_id" not in normalized:
        normalized["parent_chunk_id"] = parent_id
    if "summary" not in normalized and normalized.get("excerpt") is not None:
        normalized["summary"] = normalized.get("excerpt")
    if "hash" not in normalized and document_id and chunk_id:
        normalized["hash"] = hashlib.sha1(f"{document_id}:{chunk_id}:{text}".encode("utf-8")).hexdigest()
    return {key: value for key, value in normalized.items() if value is not None}


def _required_fields() -> tuple[str, ...]:
    return (
        "doc_id",
        "document_id",
        "chunk_id",
        "title",
        "text",
        "summary",
        "category",
        "subcategory",
        "chunk_type",
        "difficulty",
        "source_type",
        "version",
        "is_latest",
        "tags",
        "hash",
    )


def _write_backfill_batch(
    client: Any,
    collection_name: str,
    plans: Sequence[KnowledgeChunkBackfillPlan],
) -> None:
    points = [
        {
            "id": plan.normalized_payload.get("chunk_id"),
            "payload": dict(plan.normalized_payload),
        }
        for plan in plans
        if plan.normalized_payload.get("chunk_id")
    ]
    if not points:
        return
    upsert_fn = getattr(client, "upsert", None) or getattr(client, "upsert_points", None) or getattr(client, "upload_points", None)
    if not callable(upsert_fn):
        raise RuntimeError("Qdrant client does not expose an upsert-compatible API")
    try:
        upsert_fn(collection_name=collection_name, points=points)
    except TypeError:
        upsert_fn(collection_name=collection_name, points=points, wait=True)  # pragma: no cover - alternate client signature
    except Exception:  # pragma: no cover - defensive logging
        _LOGGER.exception("knowledge_chunk_backfill_batch_failed")
        raise
