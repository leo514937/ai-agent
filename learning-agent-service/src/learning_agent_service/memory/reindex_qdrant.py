from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from learning_agent_service.application.dependencies import OpenAIEmbeddingAdapter, _resolve_memory_vector_size
from learning_agent_service.config import Settings, get_settings
from learning_agent_service.domain.memory import MemoryRecord
from learning_agent_service.infrastructure.db.factories import InfrastructureClients, build_infrastructure_clients
from learning_agent_service.infrastructure.memory import LongTermMemoryRepository, QdrantLongTermMemoryIndex


@dataclass(frozen=True)
class ReindexResult:
    scanned_memory_count: int
    indexed_memory_count: int
    skipped_memory_count: int
    failed_memory_count: int
    collection_name: str
    vector_size: int
    vector_name: str
    duration_seconds: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "scanned_memory_count": self.scanned_memory_count,
            "indexed_memory_count": self.indexed_memory_count,
            "skipped_memory_count": self.skipped_memory_count,
            "failed_memory_count": self.failed_memory_count,
            "collection_name": self.collection_name,
            "vector_size": self.vector_size,
            "vector_name": self.vector_name,
            "duration_seconds": round(self.duration_seconds, 3),
        }


def _distance_value(value: Any) -> str:
    if hasattr(value, "value"):
        return str(value.value).lower()
    return str(value or "").lower()


def _collection_vector_params(client: Any, collection_name: str, vector_name: str) -> tuple[Optional[int], Optional[str]]:
    get_collection = getattr(client, "get_collection", None)
    if not callable(get_collection):
        return None, None
    try:
        info = get_collection(collection_name)
    except Exception:
        return None, None
    config = getattr(info, "config", None)
    params = getattr(config, "params", None) if config is not None else None
    vectors = getattr(params, "vectors", None) if params is not None else None
    if vectors is None:
        return None, None
    if isinstance(vectors, Mapping):
        vector_params = vectors.get(vector_name)
    else:
        vector_params = vectors
    if vector_params is None:
        return None, None
    size = getattr(vector_params, "size", None)
    distance = getattr(vector_params, "distance", None)
    return int(size) if size is not None else None, _distance_value(distance) if distance is not None else None


def _collection_exists(client: Any, collection_name: str) -> bool:
    collection_exists = getattr(client, "collection_exists", None)
    if callable(collection_exists):
        try:
            return bool(collection_exists(collection_name))
        except Exception:
            return False
    get_collection = getattr(client, "get_collection", None)
    if callable(get_collection):
        try:
            get_collection(collection_name)
            return True
        except Exception:
            return False
    return False


def _delete_collection(client: Any, collection_name: str) -> None:
    delete_collection = getattr(client, "delete_collection", None)
    if not callable(delete_collection):
        raise RuntimeError(f"Qdrant client does not support delete_collection for {collection_name}")
    try:
        delete_collection(collection_name=collection_name)
    except TypeError:
        delete_collection(collection_name)


def _build_embedding_adapter(infra: InfrastructureClients, settings: Settings) -> OpenAIEmbeddingAdapter:
    if infra.openai is None:
        raise RuntimeError("OpenAI runtime is required to rebuild the memory collection")
    provider = str(getattr(settings.embedding, "memory_provider", "") or "").strip().lower()
    if provider not in {"openai"}:
        raise RuntimeError(f"Unsupported memory embedding provider: {provider or 'unknown'}")
    return OpenAIEmbeddingAdapter(runtime=infra.openai, model=settings.embedding.memory_model)


def reindex_memory_collection(
    settings: Settings,
    *,
    infra: InfrastructureClients | None = None,
    collection_name: Optional[str] = None,
    vector_size: Optional[int] = None,
    vector_name: Optional[str] = None,
    distance: Optional[str] = None,
    drop_existing: bool = False,
    expected_old_vector_size: Optional[int] = None,
    confirm_nonstandard_existing_collection: bool = False,
    batch_size: int = 64,
) -> ReindexResult:
    started = time.perf_counter()
    infra = infra or build_infrastructure_clients(settings, allow_partial=False)
    if infra.postgres is None or infra.qdrant is None or infra.openai is None:
        raise RuntimeError("postgres, qdrant and openai runtimes are required for memory reindexing")

    target_collection = collection_name or settings.qdrant.memory_collection
    target_vector_name = vector_name or settings.qdrant.memory_vector_name
    target_vector_size = vector_size if vector_size is not None else settings.qdrant.memory_vector_size
    target_distance = distance or settings.qdrant.memory_distance
    embedding_adapter = _build_embedding_adapter(infra, settings)
    if target_vector_size is None:
        target_vector_size = _resolve_memory_vector_size(settings)

    repository = LongTermMemoryRepository(infra.postgres.session_factory)
    index = QdrantLongTermMemoryIndex(
        client=infra.qdrant.client,
        collection_name=target_collection,
        vector_size=target_vector_size,
        vector_name=target_vector_name,
        distance=target_distance,
        embedding_adapter=embedding_adapter,
    )

    collection_exists = _collection_exists(infra.qdrant.client, target_collection)
    existing_size, _existing_distance = (None, None)
    if collection_exists:
        existing_size, _existing_distance = _collection_vector_params(
            infra.qdrant.client,
            target_collection,
            target_vector_name,
        )
    if collection_exists and drop_existing:
        if existing_size is None:
            if not confirm_nonstandard_existing_collection:
                raise RuntimeError(
                    f"Refusing to delete {target_collection}: unable to verify existing vector size; "
                    "pass --confirm-nonstandard-existing-collection to force deletion"
                )
        elif int(existing_size) != 64 and not confirm_nonstandard_existing_collection:
            raise RuntimeError(
                f"Refusing to delete {target_collection}: existing vector size {existing_size} is not the legacy 64; "
                "pass --confirm-nonstandard-existing-collection to force deletion"
            )
        if expected_old_vector_size is not None and existing_size is not None and int(existing_size) != int(expected_old_vector_size):
            raise RuntimeError(
                f"Refusing to delete {target_collection}: expected old vector size {expected_old_vector_size}, "
                f"but found {existing_size}"
            )
        _delete_collection(infra.qdrant.client, target_collection)
    elif collection_exists and (existing_size is None or int(existing_size) != int(target_vector_size)):
        raise RuntimeError(
            "Memory Qdrant collection shape mismatch:\n"
            f"collection={target_collection}\n"
            f"vector_name={target_vector_name}\n"
            f"expected_vector_size={target_vector_size}\n"
            f"actual_vector_size={existing_size}\n"
            f"action=run memory reindex command with --drop-existing --expected-old-vector-size 64"
        )

    index.ensure_collection()

    scanned = 0
    indexed = 0
    skipped = 0
    failed = 0
    failures: list[str] = []

    records = repository.iter_reindexable_records()
    step = max(int(batch_size or 1), 1)
    for offset in range(0, len(records), step):
        for record in records[offset : offset + step]:
            scanned += 1
            try:
                decision = index.vectorization_gate.should_vectorize(record)
                if not decision.allowed:
                    skipped += 1
                    continue
                index.upsert(record)
                if getattr(index, "last_error", None):
                    raise RuntimeError(str(index.last_error))
                indexed += 1
            except Exception as exc:
                failed += 1
                failures.append(f"{record.memory_id}: {exc}")

    duration_seconds = time.perf_counter() - started
    result = ReindexResult(
        scanned_memory_count=scanned,
        indexed_memory_count=indexed,
        skipped_memory_count=skipped,
        failed_memory_count=failed,
        collection_name=target_collection,
        vector_size=int(target_vector_size),
        vector_name=target_vector_name,
        duration_seconds=duration_seconds,
    )
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    if failures:
        raise RuntimeError(f"memory reindex failed: {failures[0]}")
    return result


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rebuild and reindex the memory Qdrant collection from PostgreSQL.")
    parser.add_argument("--drop-existing", "--force", dest="drop_existing", action="store_true", help="Delete the existing memory collection before rebuilding.")
    parser.add_argument("--expected-old-vector-size", type=int, default=None, help="Refuse deletion unless the existing collection matches this vector size.")
    parser.add_argument(
        "--confirm-nonstandard-existing-collection",
        action="store_true",
        help="Allow deletion when the existing collection is not the legacy 64-dimensional memory index.",
    )
    parser.add_argument("--collection-name", default=None, help="Override the target memory collection name.")
    parser.add_argument("--vector-size", type=int, default=None, help="Override the target vector size.")
    parser.add_argument("--vector-name", default=None, help="Override the named vector key.")
    parser.add_argument("--distance", default=None, help="Override the Qdrant distance metric.")
    parser.add_argument("--batch-size", type=int, default=64, help="Batch size for progress accounting.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    settings = get_settings()
    try:
        reindex_memory_collection(
            settings,
            collection_name=args.collection_name,
            vector_size=args.vector_size,
            vector_name=args.vector_name,
            distance=args.distance,
            drop_existing=args.drop_existing,
            expected_old_vector_size=args.expected_old_vector_size,
            confirm_nonstandard_existing_collection=args.confirm_nonstandard_existing_collection,
            batch_size=args.batch_size,
        )
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main(sys.argv[1:]))
