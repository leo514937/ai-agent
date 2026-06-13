from typing import Any
from .stages_back_core import WorkflowNodeAdapterStagesBackCoreMixin
from .stages_back_emit import WorkflowNodeAdapterStagesBackEmitMixin


class WorkflowNodeAdapterStagesBackMixin(WorkflowNodeAdapterStagesBackCoreMixin, WorkflowNodeAdapterStagesBackEmitMixin):
    container: 'Any'
    _plan_executor: 'Any'
    plan_planner: 'Any'
    plan_validator: 'Any'
    step_executor: 'Any'
    progress_checker: 'Any'
    plan_reviewer: 'Any'
    replanner: 'Any'
    human_approval_stub: 'Any'
    business_client: 'Any'
    pass
