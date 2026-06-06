from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from learning_agent_service.config import configure_logging, get_settings

from .dependencies import AppDependencies, ApplicationRuntime, _load_qdrant_knowledge_chunks, build_dependencies
from .service import WorkflowLearningAgentService, create_learning_agent_service


@dataclass
class BootstrapResult:
    container: ApplicationRuntime
    dependencies: AppDependencies
    learning_service: WorkflowLearningAgentService
    logging_backend: dict[str, Any]
    infrastructure_status: dict[str, Any]


async def _warmup_qdrant_knowledge_chunks(app: Any) -> dict[str, Any]:
    container = getattr(app.state, "container", None)
    infrastructure = getattr(container, "infrastructure_clients", None)
    qdrant = getattr(infrastructure, "qdrant", None) if infrastructure is not None else None
    rag_orchestrator = getattr(container, "rag_orchestrator", None) if container is not None else None
    warmup_state: dict[str, Any] = {
        "status": "skipped",
        "source": "qdrant",
        "chunk_count": 0,
    }
    if qdrant is None or rag_orchestrator is None or not hasattr(rag_orchestrator, "replace_knowledge_chunks"):
        app.state.infrastructure_status["rag_knowledge_warmup"] = warmup_state
        return warmup_state

    warmup_state["status"] = "running"
    app.state.infrastructure_status["rag_knowledge_warmup"] = dict(warmup_state)
    try:
        chunks = await asyncio.to_thread(_load_qdrant_knowledge_chunks, qdrant)
        chunk_count = int(rag_orchestrator.replace_knowledge_chunks(chunks))
        warmup_state.update(
            {
                "status": "completed",
                "chunk_count": chunk_count,
                "replaced": chunk_count > 0,
            }
        )
    except Exception as exc:  # pragma: no cover - defensive warmup fallback
        warmup_state.update(
            {
                "status": "failed",
                "error": type(exc).__name__,
            }
        )
    app.state.infrastructure_status["rag_knowledge_warmup"] = warmup_state
    return warmup_state


def _register_qdrant_knowledge_warmup(app: Any) -> None:
    @app.on_event("startup")
    async def _startup_qdrant_knowledge_warmup() -> None:
        container = getattr(app.state, "container", None)
        infrastructure = getattr(container, "infrastructure_clients", None)
        qdrant = getattr(infrastructure, "qdrant", None) if infrastructure is not None else None
        if qdrant is None:
            app.state.infrastructure_status["rag_knowledge_warmup"] = {
                "status": "skipped",
                "source": "qdrant",
                "chunk_count": 0,
            }
            return

        app.state.infrastructure_status["rag_knowledge_warmup"] = {
            "status": "scheduled",
            "source": "qdrant",
            "chunk_count": 0,
        }
        task = asyncio.create_task(_warmup_qdrant_knowledge_chunks(app))
        app.state.qdrant_knowledge_warmup_task = task

    @app.on_event("shutdown")
    async def _shutdown_qdrant_knowledge_warmup() -> None:
        task = getattr(app.state, "qdrant_knowledge_warmup_task", None)
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def bootstrap_application(app: Any | None = None) -> BootstrapResult:
    settings = get_settings()
    configure_logging(settings.observability)
    dependencies = build_dependencies(settings=settings)
    learning_service = create_learning_agent_service(dependencies.container)
    infrastructure_status = {
        "runtime_profile": dependencies.container.runtime_profile.as_dict(),
        "dependency_status": dependencies.container.runtime_dependency_status.as_dict(),
    }
    if app is not None:
        app.state.container = dependencies.container
        app.state.settings = settings
        app.state.dependencies = dependencies
        app.state.learning_service = learning_service
        app.state.infrastructure_status = infrastructure_status
        app.state.bootstrap_errors = list(dependencies.container.runtime_dependency_status.bootstrap_errors)
    return BootstrapResult(
        container=dependencies.container,
        dependencies=dependencies,
        learning_service=learning_service,
        logging_backend={
            "backend": "stdlib",
            "log_level": settings.observability.log_level,
            "json_logs": settings.observability.json_logs,
        },
        infrastructure_status=infrastructure_status,
    )
