from .services import (
    EvidenceSubgraphServices,
    ToolSubgraphServices,
    UnderstandTurnServices,
    WorkflowServices,
)

__all__ = [
    "create_workflow_runner",
    "EvidenceSubgraphServices",
    "BaseWorkflowRunner",
    "ToolSubgraphServices",
    "UnderstandTurnServices",
    "WorkflowRunner",
    "WorkflowServices",
]


def __getattr__(name: str):
    if name == "create_workflow_runner":
        from .builder import create_workflow_runner as value

        return value
    if name in {"BaseWorkflowRunner", "WorkflowRunner"}:
        from .runner import BaseWorkflowRunner as base_workflow_runner
        from .runner import WorkflowRunner as workflow_runner

        return {
            "BaseWorkflowRunner": base_workflow_runner,
            "WorkflowRunner": workflow_runner,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
