from .stages_front import WorkflowNodeAdapterStagesFrontMixin
from .stages_back import WorkflowNodeAdapterStagesBackMixin
from .stages_main_graph import WorkflowNodeAdapterMainGraphMixin


class WorkflowNodeAdapterStagesMixin(
    WorkflowNodeAdapterStagesFrontMixin,
    WorkflowNodeAdapterStagesBackMixin,
    WorkflowNodeAdapterMainGraphMixin,
):
    pass
