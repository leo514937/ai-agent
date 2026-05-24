from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from learning_agent_service.adapters.java_business import JavaBusinessClient
from learning_agent_service.application.dependencies import OpenAIEmbeddingAdapter
from learning_agent_service.config.settings import Settings, get_settings
from learning_agent_service.infrastructure.db.openai_client import build_openai_runtime
from learning_agent_service.infrastructure.db.qdrant import build_qdrant_runtime
from learning_agent_service.rag.retrieval import validate_qdrant_collection_shape
from learning_agent_service.rag.seed_parent_child import (
    _format_seed_summary_lines,
    seed_local_life_hybrid_knowledge_from_settings,
    seed_local_life_parent_child_knowledge_from_settings,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class _BootstrapTarget:
    collection_name: str
    seed_fn: Callable[..., Any]


def _collection_exists(qdrant_client: Any, collection_name: str) -> bool:
    collection_exists = getattr(qdrant_client, "collection_exists", None)
    if callable(collection_exists):
        try:
            return bool(collection_exists(collection_name))
        except Exception:
            return False

    get_collection = getattr(qdrant_client, "get_collection", None)
    if callable(get_collection):
        try:
            get_collection(collection_name)
            return True
        except Exception:
            return False

    return False


def _collection_point_count(qdrant_client: Any, collection_name: str) -> int | None:
    count = getattr(qdrant_client, "count", None)
    if not callable(count):
        return None
    try:
        try:
            response = count(collection_name=collection_name, exact=True)
        except TypeError:
            response = count(collection_name=collection_name)
    except Exception:
        return None

    value = getattr(response, "count", None)
    if value is None and isinstance(response, dict):
        value = response.get("count")
    try:
        return int(value) if value is not None else None
    except Exception:
        return None


def ensure_local_life_collections(settings: Settings | None = None) -> tuple[str, ...]:
    settings = settings or get_settings()
    business_client = JavaBusinessClient(settings=settings)
    openai_runtime = build_openai_runtime(settings.openai)
    qdrant_runtime = build_qdrant_runtime(settings.qdrant)
    embedding_adapter = OpenAIEmbeddingAdapter(runtime=openai_runtime, model=settings.openai.embedding_model)
    ensured: list[str] = []
    targets = (
        _BootstrapTarget(
            collection_name=settings.qdrant.local_life_hybrid_collection,
            seed_fn=seed_local_life_hybrid_knowledge_from_settings,
        ),
        _BootstrapTarget(
            collection_name=settings.qdrant.local_life_parent_child_collection,
            seed_fn=seed_local_life_parent_child_knowledge_from_settings,
        ),
    )
    try:
        for target in targets:
            exists = _collection_exists(qdrant_runtime.client, target.collection_name)
            point_count = _collection_point_count(qdrant_runtime.client, target.collection_name)
            if exists:
                if point_count == 0:
                    _LOGGER.info("local_life_bootstrap_collection_empty collection=%s", target.collection_name)
                else:
                    validate_qdrant_collection_shape(
                        qdrant_runtime.client,
                        collection_name=target.collection_name,
                        vector_name=settings.qdrant.knowledge_vector_name,
                        vector_size=settings.qdrant.knowledge_vector_size,
                        distance=settings.qdrant.knowledge_distance,
                        action_hint="run the dedicated local-life seed or reindex command",
                    )
                    _LOGGER.info("local_life_bootstrap_collection_ready collection=%s", target.collection_name)
                    continue

            _LOGGER.info("local_life_bootstrap_collection_missing collection=%s", target.collection_name)
            result = target.seed_fn(
                settings=settings,
                business_client=business_client,
                qdrant_client=qdrant_runtime.client,
                embedding_adapter=embedding_adapter,
            )
            for line in _format_seed_summary_lines(result):
                _LOGGER.info("%s", line)
            ensured.append(target.collection_name)
        return tuple(ensured)
    finally:
        business_client.close()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ensure local-life Qdrant collections exist before service boot.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    parser.parse_args(list(argv) if argv is not None else None)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    ensured = ensure_local_life_collections()
    if ensured:
        _LOGGER.info("local_life_bootstrap_seeded=%s", ", ".join(ensured))
    else:
        _LOGGER.info("local_life_bootstrap_no_seed_needed")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
