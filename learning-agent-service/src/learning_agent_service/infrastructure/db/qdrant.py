"""Bootstrap-friendly Qdrant client factory and collection descriptors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from learning_agent_service.config.settings import QdrantSettings

from .errors import InfrastructureConfigurationError, require_dependency

try:
    from qdrant_client import QdrantClient
except ImportError:  # pragma: no cover - depends on optional runtime installation.
    QdrantClient = None


@dataclass(frozen=True)
class QdrantRuntime:
    """Holds the Qdrant client and canonical collection names."""

    client: Any
    knowledge_collection: str
    local_life_hybrid_collection: str
    local_life_parent_child_collection: str
    memory_collection: str
    user_memory_collection: str
    knowledge_vector_name: str
    knowledge_sparse_vector_name: str
    knowledge_vector_size: int | None
    knowledge_distance: str
    memory_vector_name: str
    memory_vector_size: int | None
    memory_distance: str

    def collection_map(self) -> dict[str, str]:
        return {
            "knowledge": self.knowledge_collection,
            "memory": self.memory_collection,
            "user_memory": self.user_memory_collection,
            "local_life_hybrid": self.local_life_hybrid_collection,
            "local_life_parent_child": self.local_life_parent_child_collection,
        }


def build_qdrant_runtime(settings: QdrantSettings) -> QdrantRuntime:
    """Create a Qdrant runtime with the service-owned collection names."""

    if QdrantClient is None:
        require_dependency("qdrant-client", "knowledge and semantic memory retrieval")
    client = QdrantClient(
        url=settings.url,
        api_key=settings.api_key,
        timeout=settings.timeout_seconds,
        prefer_grpc=settings.prefer_grpc,
    )
    probe = getattr(client, "collection_exists", None)
    if callable(probe):
        try:
            probe(settings.user_memory_collection)
        except Exception as exc:
            raise InfrastructureConfigurationError(
                "Qdrant runtime is unavailable at %s" % settings.url
            ) from exc
    else:
        probe = getattr(client, "get_collections", None)
        if callable(probe):
            try:
                probe()
            except Exception as exc:
                raise InfrastructureConfigurationError(
                    "Qdrant runtime is unavailable at %s" % settings.url
                ) from exc
    return QdrantRuntime(
        client=client,
        knowledge_collection=settings.knowledge_collection,
        local_life_hybrid_collection=settings.local_life_hybrid_collection,
        local_life_parent_child_collection=settings.local_life_parent_child_collection,
        memory_collection=settings.memory_collection,
        user_memory_collection=settings.user_memory_collection,
        knowledge_vector_name=settings.knowledge_vector_name,
        knowledge_sparse_vector_name=settings.knowledge_sparse_vector_name,
        knowledge_vector_size=settings.knowledge_vector_size,
        knowledge_distance=settings.knowledge_distance,
        memory_vector_name=settings.memory_vector_name,
        memory_vector_size=settings.memory_vector_size,
        memory_distance=settings.memory_distance,
    )
