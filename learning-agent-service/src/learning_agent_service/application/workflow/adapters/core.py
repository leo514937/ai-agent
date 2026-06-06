from dataclasses import dataclass

from .helpers import Any, GraphState, Mapping
from ..plan_execute import ReactStepExecutor
from ..state import append_runtime_event as _append_state_runtime_event
from .stages import WorkflowNodeAdapterStagesMixin


@dataclass
class WorkflowNodeAdapter(WorkflowNodeAdapterStagesMixin):
    container: Any

    def __post_init__(self) -> None:
        self._plan_executor = ReactStepExecutor(
            container=self.container,
            append_event=self._append_event,
        )

    def _append_event(self, state: GraphState, event_type: str, payload: Mapping[str, Any]) -> GraphState:
        return _append_state_runtime_event(state, event_type, dict(payload))

