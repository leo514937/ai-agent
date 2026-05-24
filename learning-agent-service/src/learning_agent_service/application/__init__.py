from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - import-time typing only
    from .bootstrap import BootstrapResult, bootstrap_application
    from .dependencies import ApplicationRuntime
    from .service import WorkflowLearningAgentService, create_learning_agent_service

__all__ = [
    "ApplicationRuntime",
    "BootstrapResult",
    "WorkflowLearningAgentService",
    "bootstrap_application",
    "create_learning_agent_service",
]


def __getattr__(name: str) -> Any:
    if name == "ApplicationRuntime":
        from .dependencies import ApplicationRuntime as value

        return value
    if name == "BootstrapResult":
        from .bootstrap import BootstrapResult as value

        return value
    if name == "WorkflowLearningAgentService":
        from .service import WorkflowLearningAgentService as value

        return value
    if name == "bootstrap_application":
        from .bootstrap import bootstrap_application as value

        return value
    if name == "create_learning_agent_service":
        from .service import create_learning_agent_service as value

        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
