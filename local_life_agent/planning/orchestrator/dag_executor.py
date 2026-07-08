from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Callable

from ...streaming.runtime import get_stream_handler
from .orchestrator_budget import OrchestratorBudget
from .orchestrator_cache_key import build_orchestrator_cache_inputs
from .orchestrator_execution_report import OrchestratorExecutionReport
from .sub_task_dag import SubTaskDAG, SubTaskSpec
from .worker_result import WorkerResult


@dataclass
class OrchestratorExecutionBundle:
    worker_results: list[WorkerResult] = field(default_factory=list)
    execution_reports: list[OrchestratorExecutionReport] = field(default_factory=list)
    partial_events: list[dict[str, Any]] = field(default_factory=list)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _emit_partial_event(
    bundle: OrchestratorExecutionBundle,
    *,
    trace_id: str,
    session_id: str,
    turn_id: str,
    event_type: str,
    message: str,
    workflow_name: str,
    task_id: str,
    level_index: int,
    status: str,
    extra: dict[str, Any] | None = None,
) -> None:
    payload = {
        "event_type": event_type,
        "trace_id": trace_id,
        "session_id": session_id,
        "turn_id": turn_id,
        "workflow_name": workflow_name,
        "task_id": task_id,
        "level_index": level_index,
        "status": status,
        "message": message,
        "timestamp": _utc_now_iso(),
    }
    if extra:
        payload["metadata"] = dict(extra)
    bundle.partial_events.append(payload)
    handler = get_stream_handler()
    if handler is not None and message:
        handler(message)


def _build_failure_patch(
    *,
    workflow_name: str,
    status: str,
    error_code: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "workflow_name": workflow_name,
        "workflow_run_status": status,
        "workflow_runner_error": error_code,
        "workflow_runner_reason": reason,
        "workflow_callable": workflow_name,
        "workflow_registered": False,
        "error_code": error_code,
    }


def _execute_worker_snapshot(
    state_snapshot: dict[str, Any],
    spec: SubTaskSpec,
    parent_decision: Any,
    *,
    registry_lookup: Callable[[str], Any],
) -> WorkerResult:
    workflow_name = _normalize_text(spec.workflow_name)
    payload = deepcopy(dict(spec.payload or {}))
    child_state = deepcopy(state_snapshot)
    child_state.update(payload)
    child_state["workflow_name"] = workflow_name
    child_state["workflow_reason"] = _normalize_text(spec.description or child_state.get("workflow_reason") or workflow_name)
    child_state["task_id"] = _normalize_text(spec.task_id)
    child_state["depends_on"] = list(spec.depends_on)
    child_state["task_complexity"] = _normalize_text(payload.get("task_complexity") or child_state.get("task_complexity") or "medium")
    child_state["response_mode"] = _normalize_text(payload.get("response_mode") or child_state.get("response_mode") or "exploration_plan")
    child_state["next_action"] = _normalize_text(payload.get("next_action") or child_state.get("next_action") or "run_workflow")
    child_state["workflow_entry_name"] = _normalize_text(payload.get("workflow_entry_name"))

    try:
        registration = registry_lookup(workflow_name)
    except Exception as exc:
        patch = _build_failure_patch(
            workflow_name=workflow_name,
            status="failed",
            error_code="WORKFLOW_NOT_REGISTERED",
            reason=str(exc),
        )
        patch["workflow_registered"] = False
        return WorkerResult.from_patch(
            task_id=_normalize_text(spec.task_id) or workflow_name,
            workflow_name=workflow_name,
            patch=patch,
            provenance={"workflow_reason": child_state["workflow_reason"], "depends_on": list(spec.depends_on)},
            trace_summary={"status": "failed", "reason": str(exc)},
        )

    try:
        from ...domain.schemas import OrchestrationDecision

        if hasattr(parent_decision, "model_dump"):
            parent_payload = parent_decision.model_dump()
        elif isinstance(parent_decision, dict):
            parent_payload = dict(parent_decision)
        else:
            parent_payload = {}
        child_decision = OrchestrationDecision.model_validate(
            {
                **parent_payload,
                "workflow_name": workflow_name,
                "workflow_reason": child_state["workflow_reason"],
                "task_complexity": child_state["task_complexity"],
                "response_mode": child_state["response_mode"],
                "next_action": child_state["next_action"],
            }
        )
    except Exception:
        child_decision = parent_decision

    try:
        patch = registration.handler(child_state, child_decision)
        if not isinstance(patch, dict):
            model_dump = getattr(patch, "model_dump", None)
            if callable(model_dump):
                patch = model_dump()
            else:
                patch = dict(getattr(patch, "__dict__", {}) or {})
    except Exception as exc:
        patch = _build_failure_patch(
            workflow_name=workflow_name,
            status="failed",
            error_code=exc.__class__.__name__.upper(),
            reason=str(exc),
        )

    patch.setdefault("workflow_name", workflow_name)
    patch.setdefault("workflow_run_status", "completed")
    patch.setdefault("workflow_callable", getattr(registration, "callable_name", workflow_name))
    patch.setdefault("workflow_registered", True)
    patch.setdefault("response_mode", child_state["response_mode"])
    patch.setdefault("next_action", child_state["next_action"])
    patch.setdefault("task_id", _normalize_text(spec.task_id))
    return WorkerResult.from_patch(
        task_id=_normalize_text(spec.task_id) or workflow_name,
        workflow_name=workflow_name,
        patch=patch,
        provenance={
            "workflow_reason": child_state["workflow_reason"],
            "depends_on": list(spec.depends_on),
            "registration_status": getattr(registration, "status", ""),
        },
        trace_summary={
            "status": patch.get("workflow_run_status", ""),
            "workflow_callable": patch.get("workflow_callable", ""),
        },
    )


def execute_subtask_dag(
    state: dict[str, Any],
    decision: Any,
    dag: SubTaskDAG,
    *,
    registry_lookup: Callable[[str], Any],
    cache: Any | None = None,
    budget: OrchestratorBudget | None = None,
) -> OrchestratorExecutionBundle:
    from ...planning.evidence.evidence_cache import get_default_evidence_cache

    budget = budget or OrchestratorBudget.from_state(state)
    cache_store = cache or get_default_evidence_cache()
    bundle = OrchestratorExecutionBundle()
    trace_id = _normalize_text(state.get("trace_id")) or "trace-anon"
    session_id = _normalize_text(state.get("session_id")) or "session-anon"
    turn_id = _normalize_text(state.get("turn_id")) or "turn-anon"
    completed_status: dict[str, str] = {}
    failure_count = 0
    executed_count = 0
    current_level_count = 0
    timeout_seconds = max(int(budget.subtask_timeout_ms or 0), 1) / 1000.0

    for level_index, level in enumerate(dag.topological_levels()):
        if executed_count >= budget.max_subtask_count:
            for spec in level:
                result = WorkerResult.from_patch(
                    task_id=spec.task_id,
                    workflow_name=spec.workflow_name,
                    patch={
                        "workflow_name": spec.workflow_name,
                        "workflow_run_status": "skipped_budget_exhausted",
                        "workflow_runner_error": "BUDGET_EXHAUSTED",
                        "workflow_runner_reason": "orchestrator subtask budget exhausted",
                        "workflow_callable": spec.workflow_name,
                        "workflow_registered": False,
                        "skipped": True,
                        "error_code": "BUDGET_EXHAUSTED",
                    },
                    provenance={"depends_on": list(spec.depends_on)},
                    trace_summary={"status": "skipped_budget_exhausted"},
                )
                report = OrchestratorExecutionReport.from_worker_result(
                    result,
                    duration_ms=0,
                    skipped=True,
                    error_code="BUDGET_EXHAUSTED",
                )
                bundle.worker_results.append(result)
                bundle.execution_reports.append(report)
                _emit_partial_event(
                    bundle,
                    trace_id=trace_id,
                    session_id=session_id,
                    turn_id=turn_id,
                    event_type="status",
                    message=f"orchestrator skipped {spec.task_id} because budget was exhausted",
                    workflow_name=spec.workflow_name,
                    task_id=spec.task_id,
                    level_index=level_index,
                    status=result.status,
                    extra=report.to_dict(),
                )
            break

        runnable: list[SubTaskSpec] = []
        blocked_specs: list[tuple[SubTaskSpec, list[str]]] = []
        for spec in level:
            blocked_by = [dep for dep in spec.depends_on if completed_status.get(dep) not in {"completed"}]
            if blocked_by:
                blocked_specs.append((spec, blocked_by))
            else:
                runnable.append(spec)

        for spec, blocked_by in blocked_specs:
            patch = {
                "workflow_name": spec.workflow_name,
                "workflow_run_status": "skipped_dependency_failed",
                "workflow_runner_error": "DEPENDENCY_FAILED",
                "workflow_runner_reason": f"blocked by dependencies: {','.join(blocked_by)}",
                "workflow_callable": spec.workflow_name,
                "workflow_registered": False,
                "skipped": True,
                "blocked_by": blocked_by,
                "error_code": "DEPENDENCY_FAILED",
            }
            result = WorkerResult.from_patch(
                task_id=spec.task_id,
                workflow_name=spec.workflow_name,
                patch=patch,
                provenance={"depends_on": list(spec.depends_on)},
                trace_summary={"status": "skipped_dependency_failed"},
            )
            report = OrchestratorExecutionReport.from_worker_result(
                result,
                duration_ms=0,
                skipped=True,
                blocked_by=blocked_by,
                error_code="DEPENDENCY_FAILED",
            )
            bundle.worker_results.append(result)
            bundle.execution_reports.append(report)
            completed_status[spec.task_id] = result.status
            _emit_partial_event(
                bundle,
                trace_id=trace_id,
                session_id=session_id,
                turn_id=turn_id,
                event_type="status",
                message=f"orchestrator skipped {spec.task_id} because dependency failed",
                workflow_name=spec.workflow_name,
                task_id=spec.task_id,
                level_index=level_index,
                status=result.status,
                extra=report.to_dict(),
            )

        if not runnable:
            continue

        level_results: dict[str, WorkerResult] = {}
        level_reports: dict[str, OrchestratorExecutionReport] = {}
        with ThreadPoolExecutor(max_workers=max(1, min(len(runnable), budget.max_parallelism))) as executor:
            futures: dict[str, Future[WorkerResult]] = {}
            cache_inputs: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
            for spec in runnable:
                if executed_count >= budget.max_subtask_count:
                    patch = {
                        "workflow_name": spec.workflow_name,
                        "workflow_run_status": "skipped_budget_exhausted",
                        "workflow_runner_error": "BUDGET_EXHAUSTED",
                        "workflow_runner_reason": "orchestrator subtask budget exhausted",
                        "workflow_callable": spec.workflow_name,
                        "workflow_registered": False,
                        "skipped": True,
                        "error_code": "BUDGET_EXHAUSTED",
                    }
                    result = WorkerResult.from_patch(
                        task_id=spec.task_id,
                        workflow_name=spec.workflow_name,
                        patch=patch,
                        provenance={"depends_on": list(spec.depends_on)},
                        trace_summary={"status": "skipped_budget_exhausted"},
                    )
                    report = OrchestratorExecutionReport.from_worker_result(
                        result,
                        duration_ms=0,
                        skipped=True,
                        error_code="BUDGET_EXHAUSTED",
                    )
                    level_results[spec.task_id] = result
                    level_reports[spec.task_id] = report
                    _emit_partial_event(
                        bundle,
                        trace_id=trace_id,
                        session_id=session_id,
                        turn_id=turn_id,
                        event_type="status",
                        message=f"orchestrator skipped {spec.task_id} because budget was exhausted",
                        workflow_name=spec.workflow_name,
                        task_id=spec.task_id,
                        level_index=level_index,
                        status=result.status,
                        extra=report.to_dict(),
                    )
                    continue
                executed_count += 1
                tool_version = _normalize_text(
                    state.get("tool_version")
                    or state.get("workflow_version")
                    or spec.workflow_name
                )
                scope, payload = build_orchestrator_cache_inputs(
                    state,
                    spec,
                    workflow_name=spec.workflow_name,
                    tool_version=tool_version,
                )
                cache_inputs[spec.task_id] = (scope, payload)
                record = cache_store.get(scope, payload)
                if record is not None:
                    cached_result = dict(record.payload)
                    cached_result["cache_hit"] = True
                    result = WorkerResult.from_dict(cached_result)
                    result.cache_hit = True
                    result.deadline_ms = int(budget.subtask_timeout_ms or 0)
                    level_results[spec.task_id] = result
                    level_reports[spec.task_id] = OrchestratorExecutionReport.from_worker_result(
                        result,
                        duration_ms=result.duration_ms,
                        cache_hit=True,
                    )
                    _emit_partial_event(
                        bundle,
                        trace_id=trace_id,
                        session_id=session_id,
                        turn_id=turn_id,
                        event_type="evidence_update",
                        message=f"orchestrator cache hit for {spec.task_id}",
                        workflow_name=spec.workflow_name,
                        task_id=spec.task_id,
                        level_index=level_index,
                        status=result.status,
                        extra={"cache_key": record.cache_key, "cache_hit": True},
                    )
                    continue

                futures[spec.task_id] = executor.submit(
                    _execute_worker_snapshot,
                    deepcopy(state),
                    spec,
                    decision,
                    registry_lookup=registry_lookup,
                )

            for spec in runnable:
                if spec.task_id in level_results:
                    continue
                future = futures.get(spec.task_id)
                if future is None:
                    continue
                started = perf_counter()
                started_at = _utc_now_iso()
                try:
                    result = future.result(timeout=timeout_seconds)
                except TimeoutError:
                    result = WorkerResult.from_patch(
                        task_id=spec.task_id,
                        workflow_name=spec.workflow_name,
                        patch={
                            "workflow_name": spec.workflow_name,
                            "workflow_run_status": "timed_out",
                            "workflow_runner_error": "WORKER_TIMEOUT",
                            "workflow_runner_reason": "worker timed out",
                            "workflow_callable": spec.workflow_name,
                            "workflow_registered": True,
                            "timed_out": True,
                            "error_code": "WORKER_TIMEOUT",
                        },
                        provenance={"depends_on": list(spec.depends_on)},
                        trace_summary={"status": "timed_out"},
                    )
                except Exception as exc:
                    result = WorkerResult.from_patch(
                        task_id=spec.task_id,
                        workflow_name=spec.workflow_name,
                        patch={
                            "workflow_name": spec.workflow_name,
                            "workflow_run_status": "failed",
                            "workflow_runner_error": exc.__class__.__name__.upper(),
                            "workflow_runner_reason": str(exc),
                            "workflow_callable": spec.workflow_name,
                            "workflow_registered": True,
                            "error_code": exc.__class__.__name__.upper(),
                        },
                        provenance={"depends_on": list(spec.depends_on)},
                        trace_summary={"status": "failed", "reason": str(exc)},
                    )
                duration_ms = max(int((perf_counter() - started) * 1000), 0)
                result.duration_ms = duration_ms
                result.deadline_ms = int(budget.subtask_timeout_ms or 0)
                result.trace_summary.setdefault("started_at", started_at)
                result.trace_summary.setdefault("finished_at", _utc_now_iso())
                scope_payload = cache_inputs.get(spec.task_id)
                if scope_payload is not None:
                    cache_store.set(scope_payload[0], scope_payload[1], result.to_dict())
                if not result.status:
                    result.status = "completed"
                level_results[spec.task_id] = result
                level_reports[spec.task_id] = OrchestratorExecutionReport.from_worker_result(
                    result,
                    duration_ms=duration_ms,
                    timed_out=result.timed_out,
                    skipped=result.skipped,
                    blocked_by=result.blocked_by,
                    cache_hit=result.cache_hit,
                    error_code=result.error_code,
                    started_at=started_at,
                    finished_at=result.trace_summary.get("finished_at", ""),
                )

        for spec in level:
            result = level_results.get(spec.task_id)
            if result is None:
                continue
            bundle.worker_results.append(result)
            bundle.execution_reports.append(level_reports[spec.task_id])
            completed_status[spec.task_id] = result.status
            if result.status not in {"completed", "cached"}:
                failure_count += 1
            _emit_partial_event(
                bundle,
                trace_id=trace_id,
                session_id=session_id,
                turn_id=turn_id,
                event_type="status",
                message=f"orchestrator finished {spec.task_id} with status {result.status}",
                workflow_name=spec.workflow_name,
                task_id=spec.task_id,
                level_index=level_index,
                status=result.status,
                extra=level_reports[spec.task_id].to_dict(),
            )

        current_level_count += len(level)
        if failure_count > budget.max_failed_subtasks:
            break

    return bundle
