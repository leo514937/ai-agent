from .helpers import *
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
        runtime = state["runtime"]
        events = list(runtime.emitted_events)
        events.append(
            SseEnvelope(
                event_type=event_type,
                trace_id=runtime.trace_id,
                session_id=runtime.session_id,
                turn_id=runtime.turn_id,
                timestamp=_utc_now(),
                workflow_version=runtime.workflow_version,
                payload=dict(payload),
            )
        )
        state["runtime"] = runtime.model_copy(update={"emitted_events": events})
        return state

