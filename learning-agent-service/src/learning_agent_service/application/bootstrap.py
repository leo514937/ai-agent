from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from learning_agent_service.config import configure_logging, get_settings

from .dependencies import AppDependencies, ApplicationRuntime, build_dependencies
from .service import WorkflowLearningAgentService, create_learning_agent_service


@dataclass
class BootstrapResult:
    container: ApplicationRuntime
    dependencies: AppDependencies
    learning_service: WorkflowLearningAgentService
    logging_backend: Dict[str, Any]
    infrastructure_status: Dict[str, Any]


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
