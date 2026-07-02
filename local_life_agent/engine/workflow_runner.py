"""Phase 5 workflow runner.

The runner is deliberately thin:
- it reads the workflow name from orchestration output
- it validates against the whitelist registry
- it dispatches to the registry adapter
- it never performs business reasoning or tool execution itself
"""

from __future__ import annotations

import logging
from time import perf_counter
from typing import Any

from ..domain.graph_state import GraphState
from ..domain.schemas import OrchestrationDecision
from ..observability.file_logger import get_python_service_logger, log_kv
from ._compat import _log, _state_delta, _to_dict
from .workflow_registry import WORKFLOW_REGISTRY, WorkflowRegistryError

_LOGGER = get_python_service_logger()


def _coerce_single_workflow_name(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return ""
    return str(value or "").strip()


def _coerce_decision(state: GraphState) -> OrchestrationDecision | None:
    raw = state.get("orchestration_decision")
    if raw is None:
        return None
    if isinstance(raw, OrchestrationDecision):
        return raw
    try:
        return OrchestrationDecision.model_validate(_to_dict(raw))
    except Exception:
        return None


def _fallback_patch(
    state: GraphState,
    decision: OrchestrationDecision | None,
    *,
    status: str,
    error_code: str,
    error_message: str,
    workflow_reason: str,
    workflow_registered: bool,
) -> dict[str, Any]:
    workflow_name = _coerce_single_workflow_name(decision.workflow_name if decision is not None else state.get("workflow_name", ""))
    orchestration_pattern = str((decision.orchestration_pattern if decision is not None else state.get("orchestration_pattern", "")) or "").strip()
    timestamp = ""
    try:
        from datetime import datetime, timezone

        timestamp = datetime.now(timezone.utc).isoformat()
    except Exception:
        timestamp = ""
    return {
        "workflow_name": workflow_name,
        "orchestration_pattern": orchestration_pattern,
        "workflow_run_status": status,
        "workflow_runner_error": error_code,
        "workflow_runner_reason": workflow_reason,
        "workflow_started_at": timestamp,
        "workflow_finished_at": timestamp,
        "workflow_callable": "",
        "workflow_registered": workflow_registered,
        "response_mode": "fallback",
        "next_action": "fallback",
        "orchestration_error_code": error_code,
        "orchestration_error_message": error_message,
    }


def h_workflow_runner(state: GraphState) -> dict[str, Any]:
    """Outer wrapper: registry lookup + adapter dispatch + safe fallback."""

    before = dict(state)
    started = perf_counter()
    decision = _coerce_decision(state)
    workflow_name = _coerce_single_workflow_name(decision.workflow_name if decision is not None else state.get("workflow_name", ""))
    orchestration_pattern = str((decision.orchestration_pattern if decision is not None else state.get("orchestration_pattern", "")) or "")
    workflow_reason = str((decision.workflow_reason if decision is not None else state.get("workflow_reason", "")) or "")
    route_state = dict(state)
    if decision is not None:
        route_state["orchestration_decision"] = decision
    log_kv(
        _LOGGER,
        logging.INFO,
        "[SUBGRAPH_ENTER]",
        tone="route",
        subgraph="workflow_runner",
        trace_id=state.get("trace_id", ""),
        session_id=state.get("session_id", ""),
        turn_id=state.get("turn_id", ""),
        workflow_name=workflow_name,
        orchestration_pattern=orchestration_pattern,
        workflow_reason=workflow_reason,
    )

    if decision is None:
        patch = _fallback_patch(
            state,
            decision,
            status="fallback",
            error_code="WORKFLOW_DECISION_MISSING",
            error_message="orchestration_decision is missing or invalid",
            workflow_reason="workflow decision missing",
            workflow_registered=False,
        )
        elapsed_ms = int((perf_counter() - started) * 1000.0)
        patch["latency_ms"] = elapsed_ms
        after = {**state, **patch, **_log(state, "workflow_runner", workflow_name=workflow_name, orchestration_pattern=orchestration_pattern, workflow_reason=workflow_reason, status="fallback", error_code=patch["workflow_runner_error"], error_message=patch["orchestration_error_message"], workflow_registered=False, latency_ms=elapsed_ms)}
        log_kv(
            _LOGGER,
            logging.WARNING,
            "[WORKFLOW_RUNNER]",
            tone="warn",
            node_name="workflow_runner",
            workflow_name=workflow_name,
            orchestration_pattern=orchestration_pattern,
            workflow_reason=workflow_reason,
            input_summary={"workflow_name": workflow_name},
            output_summary={"workflow_run_status": patch["workflow_run_status"]},
            state_keys_changed=["workflow_run_status", "workflow_runner_error", "workflow_runner_reason"],
            latency_ms=elapsed_ms,
            status="fallback",
            next_action=patch["next_action"],
            error_code=patch["workflow_runner_error"],
            error_message=patch["orchestration_error_message"],
            workflow_registered=False,
        )
        return _state_delta(before, after, always_include={"workflow_run_status", "workflow_runner_error", "workflow_runner_reason", "workflow_started_at", "workflow_finished_at", "workflow_callable", "workflow_registered", "response_mode", "next_action", "orchestration_error_code", "orchestration_error_message"})

    try:
        registration = WORKFLOW_REGISTRY.lookup(workflow_name)
    except WorkflowRegistryError as exc:
        error_text = str(exc)
        error_code = "WORKFLOW_NAME_MISSING" if "WORKFLOW_NAME_MISSING" in error_text else "WORKFLOW_NOT_REGISTERED"
        patch = _fallback_patch(
            state,
            decision,
            status="fallback",
            error_code=error_code,
            error_message=error_text,
            workflow_reason="workflow_name missing or not registered",
            workflow_registered=False,
        )
        elapsed_ms = int((perf_counter() - started) * 1000.0)
        patch["latency_ms"] = elapsed_ms
        after = {**route_state, **patch, **_log(state, "workflow_runner", workflow_name=workflow_name, orchestration_pattern=orchestration_pattern, workflow_reason=workflow_reason, status="fallback", error_code=error_code, error_message=error_text, workflow_registered=False, latency_ms=elapsed_ms)}
        log_kv(
            _LOGGER,
            logging.WARNING,
            "[WORKFLOW_RUNNER]",
            tone="warn",
            node_name="workflow_runner",
            workflow_name=workflow_name,
            orchestration_pattern=orchestration_pattern,
            workflow_reason=workflow_reason,
            input_summary={"workflow_name": workflow_name},
            output_summary={"workflow_run_status": patch["workflow_run_status"]},
            state_keys_changed=["workflow_run_status", "workflow_runner_error", "workflow_runner_reason"],
            latency_ms=elapsed_ms,
            status="fallback",
            next_action=patch["next_action"],
            error_code=error_code,
            error_message=error_text,
            workflow_registered=False,
        )
        return _state_delta(before, after, always_include={"workflow_run_status", "workflow_runner_error", "workflow_runner_reason", "workflow_started_at", "workflow_finished_at", "workflow_callable", "workflow_registered", "response_mode", "next_action", "orchestration_error_code", "orchestration_error_message"})

    try:
        patch = registration.handler(route_state, decision)
        if not isinstance(patch, dict):
            patch = _to_dict(patch)
        patch.setdefault("workflow_registered", registration.status == "registered")
        patch.setdefault("workflow_callable", registration.callable_name)
        patch.setdefault("workflow_runner_error", "")
        patch.setdefault("workflow_runner_reason", decision.workflow_reason)
        patch.setdefault("workflow_run_status", "dispatched" if registration.is_real else registration.status)
        patch.setdefault("workflow_name", workflow_name)
        patch.setdefault("orchestration_pattern", orchestration_pattern)
        if registration.is_real:
            patch.setdefault("response_mode", decision.response_mode)
            patch.setdefault("next_action", decision.next_action)
        else:
            patch.setdefault("response_mode", "fallback")
            patch.setdefault("next_action", "fallback")
        elapsed_ms = int((perf_counter() - started) * 1000.0)
        patch["latency_ms"] = elapsed_ms
        after = {**route_state, **patch, **_log(state, "workflow_runner", workflow_name=workflow_name, orchestration_pattern=orchestration_pattern, workflow_reason=workflow_reason, status=patch.get("workflow_run_status", ""), error_code=patch.get("workflow_runner_error", ""), error_message=patch.get("orchestration_error_message", ""), workflow_registered=bool(patch.get("workflow_registered", False)), workflow_callable=patch.get("workflow_callable", ""), latency_ms=elapsed_ms)}
        log_kv(
            _LOGGER,
            logging.INFO if registration.is_real else logging.WARNING,
            "[WORKFLOW_RUNNER]",
            tone="route" if registration.is_real else "warn",
            node_name="workflow_runner",
            workflow_name=workflow_name,
            orchestration_pattern=orchestration_pattern,
            workflow_reason=workflow_reason,
            input_summary={"workflow_name": workflow_name},
            output_summary={
                "workflow_run_status": patch.get("workflow_run_status", ""),
                "workflow_callable": patch.get("workflow_callable", ""),
            },
            state_keys_changed=["workflow_run_status", "workflow_runner_error", "workflow_runner_reason", "workflow_started_at", "workflow_finished_at"],
            latency_ms=elapsed_ms,
            status=patch.get("workflow_run_status", ""),
            next_action=patch.get("next_action", ""),
            error_code=patch.get("workflow_runner_error", ""),
            error_message=patch.get("orchestration_error_message", ""),
            workflow_registered=bool(patch.get("workflow_registered", False)),
            workflow_callable=patch.get("workflow_callable", ""),
        )
        return _state_delta(
            before,
            after,
            always_include={
                "workflow_run_status",
                "workflow_runner_error",
                "workflow_runner_reason",
                "workflow_started_at",
                "workflow_finished_at",
                "workflow_callable",
                "workflow_registered",
                "response_mode",
                "next_action",
                "orchestration_error_code",
                "orchestration_error_message",
            },
        )
    except Exception as exc:
        patch = _fallback_patch(
            state,
            decision,
            status="failed",
            error_code="WORKFLOW_RUN_FAILED",
            error_message=str(exc),
            workflow_reason=f"workflow runner failed: {exc}",
            workflow_registered=True,
        )
        elapsed_ms = int((perf_counter() - started) * 1000.0)
        patch["latency_ms"] = elapsed_ms
        after = {**route_state, **patch, **_log(state, "workflow_runner", workflow_name=workflow_name, orchestration_pattern=orchestration_pattern, workflow_reason=workflow_reason, status="failed", error_code="WORKFLOW_RUN_FAILED", error_message=str(exc), workflow_registered=True, latency_ms=elapsed_ms)}
        log_kv(
            _LOGGER,
            logging.ERROR,
            "[WORKFLOW_RUNNER]",
            tone="error",
            node_name="workflow_runner",
            workflow_name=workflow_name,
            orchestration_pattern=orchestration_pattern,
            workflow_reason=workflow_reason,
            input_summary={"workflow_name": workflow_name},
            output_summary={"workflow_run_status": patch["workflow_run_status"]},
            state_keys_changed=["workflow_run_status", "workflow_runner_error", "workflow_runner_reason"],
            latency_ms=elapsed_ms,
            status="failed",
            next_action=patch["next_action"],
            error_code=patch["workflow_runner_error"],
            error_message=patch["orchestration_error_message"],
            workflow_registered=True,
        )
        return _state_delta(before, after, always_include={"workflow_run_status", "workflow_runner_error", "workflow_runner_reason", "workflow_started_at", "workflow_finished_at", "workflow_callable", "workflow_registered", "response_mode", "next_action", "orchestration_error_code", "orchestration_error_message"})
