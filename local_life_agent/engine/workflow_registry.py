"""Whitelist workflow registry for Phase 5 dispatch.

The registry intentionally keeps the surface area small:
- only legal workflow names are accepted
- only explicitly registered entries can be dispatched
- not implemented workflows remain explicit
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from ..domain.graph_state import GraphState
from ..domain.schemas import OrchestrationDecision
from .workflows.clarification_fallback_workflow import run_clarification_fallback_workflow
from .workflows.deterministic_tool_workflow import run_deterministic_tool_workflow
from .workflows.direct_response_workflow import run_direct_response_workflow
from .workflows.exploration_planning_workflow import run_exploration_planning_workflow

WorkflowHandler = Callable[[GraphState, OrchestrationDecision], dict[str, Any]]

LEGAL_WORKFLOW_NAMES: tuple[str, ...] = (
    "direct_response",
    "deterministic_tool",
    "discovery_decision",
    "exploration_planning",
    "clarification_fallback",
)

WORKFLOW_STATUS_REGISTERED = "registered"
WORKFLOW_STATUS_NOT_IMPLEMENTED = "not_implemented"


@dataclass(frozen=True)
class WorkflowRegistration:
    """Single whitelist entry stored in the registry."""

    workflow_name: str
    handler: WorkflowHandler
    status: str
    entry_node: str | None = None
    description: str = ""

    @property
    def callable_name(self) -> str:
        return getattr(self.handler, "__name__", self.workflow_name)

    @property
    def is_real(self) -> bool:
        return self.status == WORKFLOW_STATUS_REGISTERED and self.entry_node is not None


class WorkflowRegistryError(KeyError):
    """Raised when a workflow name is missing or not allowed."""


class WorkflowRegistry:
    """Explicit workflow registry with whitelist lookup."""

    def __init__(self, registrations: Mapping[str, WorkflowRegistration] | None = None):
        self._registrations: dict[str, WorkflowRegistration] = {}
        if registrations:
            for registration in registrations.values():
                self.register(registration)

    @staticmethod
    def _normalize_name(workflow_name: str | None) -> str:
        return str(workflow_name or "").strip()

    @staticmethod
    def _ensure_legal_name(workflow_name: str) -> None:
        if workflow_name not in LEGAL_WORKFLOW_NAMES:
            raise WorkflowRegistryError(f"WORKFLOW_NOT_REGISTERED: {workflow_name or '<empty>'}")

    def register(self, registration: WorkflowRegistration) -> None:
        workflow_name = self._normalize_name(registration.workflow_name)
        self._ensure_legal_name(workflow_name)
        if workflow_name in self._registrations:
            raise WorkflowRegistryError(f"duplicate workflow registration: {workflow_name}")
        self._registrations[workflow_name] = registration

    def lookup(self, workflow_name: str | None) -> WorkflowRegistration:
        normalized = self._normalize_name(workflow_name)
        if not normalized:
            raise WorkflowRegistryError("WORKFLOW_NAME_MISSING")
        self._ensure_legal_name(normalized)
        registration = self._registrations.get(normalized)
        if registration is None:
            raise WorkflowRegistryError(f"WORKFLOW_NOT_REGISTERED: {normalized}")
        return registration

    def names(self) -> tuple[str, ...]:
        return tuple(self._registrations.keys())

    def is_registered(self, workflow_name: str | None) -> bool:
        try:
            self.lookup(workflow_name)
        except WorkflowRegistryError:
            return False
        return True


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_dispatch_patch(
    state: GraphState,
    decision: OrchestrationDecision,
    *,
    workflow_run_status: str,
    workflow_runner_error: str = "",
    workflow_runner_reason: str = "",
    workflow_callable: str = "",
    workflow_registered: bool = False,
    response_mode: str = "",
    next_action: str = "",
) -> dict[str, Any]:
    timestamp = _utc_now_iso()
    patch: dict[str, Any] = {
        "workflow_run_status": workflow_run_status,
        "workflow_runner_error": workflow_runner_error,
        "workflow_runner_reason": workflow_runner_reason or decision.workflow_reason,
        "workflow_started_at": timestamp,
        "workflow_finished_at": timestamp,
        "workflow_callable": workflow_callable,
        "workflow_registered": workflow_registered,
    }
    if response_mode:
        patch["response_mode"] = response_mode
    if next_action:
        patch["next_action"] = next_action
    return patch


def _dispatch_discovery_decision(state: GraphState, decision: OrchestrationDecision) -> dict[str, Any]:
    return _build_dispatch_patch(
        state,
        decision,
        workflow_run_status="dispatched",
        workflow_runner_reason=decision.workflow_reason or "dispatch discovery_decision to planning_subgraph",
        workflow_callable="planning_subgraph",
        workflow_registered=True,
        response_mode=decision.response_mode,
        next_action=decision.next_action,
    )


def build_default_workflow_registry() -> WorkflowRegistry:
    """Build the Phase 5 whitelist registry."""

    registry = WorkflowRegistry()
    registry.register(
        WorkflowRegistration(
            workflow_name="discovery_decision",
            handler=_dispatch_discovery_decision,
            status=WORKFLOW_STATUS_REGISTERED,
            entry_node="planning_subgraph",
            description="Current main-chain discovery / decision flow.",
        )
    )
    registry.register(
        WorkflowRegistration(
            workflow_name="direct_response",
            handler=run_direct_response_workflow,
            status=WORKFLOW_STATUS_REGISTERED,
            entry_node="response_subgraph",
            description="Phase 7 direct-response workflow for lightweight replies.",
        )
    )
    registry.register(
        WorkflowRegistration(
            workflow_name="deterministic_tool",
            handler=run_deterministic_tool_workflow,
            status=WORKFLOW_STATUS_REGISTERED,
            entry_node="response_subgraph",
            description="Phase 6 deterministic single-shop tool workflow.",
        )
    )
    registry.register(
        WorkflowRegistration(
            workflow_name="clarification_fallback",
            handler=run_clarification_fallback_workflow,
            status=WORKFLOW_STATUS_REGISTERED,
            entry_node="response_subgraph",
            description="Phase 7 clarification / trusted fallback workflow.",
        )
    )
    registry.register(
        WorkflowRegistration(
            workflow_name="exploration_planning",
            handler=run_exploration_planning_workflow,
            status=WORKFLOW_STATUS_REGISTERED,
            entry_node="response_subgraph",
            description="Phase 8 exploration planning workflow.",
        )
    )
    return registry


WORKFLOW_REGISTRY = build_default_workflow_registry()
