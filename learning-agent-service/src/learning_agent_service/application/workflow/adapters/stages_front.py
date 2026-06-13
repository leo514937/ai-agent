from typing import Any
from .stages_front_a import WorkflowNodeAdapterStagesFrontAMixin
from .stages_front_b import WorkflowNodeAdapterStagesFrontBMixin


class WorkflowNodeAdapterStagesFrontMixin(WorkflowNodeAdapterStagesFrontAMixin, WorkflowNodeAdapterStagesFrontBMixin):
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
