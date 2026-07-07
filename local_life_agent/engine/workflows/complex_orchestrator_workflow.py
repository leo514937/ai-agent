from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Iterable

from ...answer.answer_plan_builder import build_answer_plan
from ...answer.response_contract import ResponseContractV2
from ...answer.response_directive import build_response_directive
from ...domain.schemas import AnswerPlan, OrchestrationDecision
from ...observability.file_logger import log_kv
from ...planning.orchestrator import DecisionReducer, EvidenceReducer, SubTaskDAG, WorkerResult
from .._compat import _to_dict

_LOGGER = __import__("logging").getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _default_subtask_specs(state: dict[str, Any], decision: OrchestrationDecision) -> list[dict[str, Any]]:
    semantic_frame = _to_dict(state.get("semantic_frame"))
    raw_specs = (
        state.get("complex_subtasks")
        or semantic_frame.get("complex_subtasks")
        or semantic_frame.get("subtasks")
        or state.get("subtask_specs")
        or []
    )
    if isinstance(raw_specs, dict):
        raw_specs = list(raw_specs.values())
    if isinstance(raw_specs, tuple):
        raw_specs = list(raw_specs)
    if not isinstance(raw_specs, list):
        raw_specs = []
    if raw_specs:
        return [spec for spec in raw_specs if isinstance(spec, dict)]
    return [
        {
            "task_id": "root",
            "workflow_name": "exploration_planning",
            "depends_on": [],
            "payload": {
                "workflow_hint": "exploration_planning",
                "task_complexity": "high",
            },
            "description": decision.workflow_reason or "default complex orchestration root",
        }
    ]


def _build_child_decision(workflow_name: str, parent: OrchestrationDecision, payload: dict[str, Any]) -> OrchestrationDecision:
    workflow_name = _normalize_text(workflow_name)
    orchestration_pattern = workflow_name
    response_mode = _normalize_text(payload.get("response_mode"))
    if not response_mode:
        if workflow_name in {"recommendation_decision_workflow"}:
            response_mode = "recommendation"
        elif workflow_name in {"comparison_decision_workflow"}:
            response_mode = "comparison"
        elif workflow_name in {"exploration_planning"}:
            response_mode = "exploration_plan"
        elif workflow_name in {"clarification_fallback"}:
            response_mode = "clarify"
        else:
            response_mode = "exploration_plan"
    task_complexity = _normalize_text(payload.get("task_complexity")) or ("super_complex" if workflow_name == "complex_orchestrator_workflow" else "medium")
    requires_tool = bool(payload.get("requires_tool", workflow_name not in {"direct_response", "clarification_fallback"}))
    requires_clarification = bool(payload.get("requires_clarification", False))
    next_action = _normalize_text(payload.get("next_action")) or ("clarify" if requires_clarification else "run_workflow")
    return OrchestrationDecision(
        orchestration_pattern=orchestration_pattern,
        workflow_name=workflow_name,
        workflow_entry_name=_normalize_text(payload.get("workflow_entry_name")),
        workflow_reason=_normalize_text(payload.get("workflow_reason") or parent.workflow_reason or f"subtask {workflow_name}"),
        task_complexity=task_complexity,
        requires_tool=requires_tool,
        requires_clarification=requires_clarification,
        response_mode=response_mode,
        confidence=float(payload.get("confidence", parent.confidence or 0.5) or 0.5),
        missing_fields=list(payload.get("missing_fields") or []),
        next_action=next_action,
    )


def _compose_response_text(answer_type: str, evidence_summary: dict[str, Any], decision_summary: dict[str, Any], dag: SubTaskDAG) -> str:
    task_count = len(dag.nodes)
    winner_shop_id = _normalize_text(decision_summary.get("winner_shop_id"))
    if winner_shop_id:
        return f"已完成 {task_count} 个子任务的汇总，综合结果优先关注 {winner_shop_id}。"
    if answer_type == "comparison" and decision_summary.get("conflict_summary", {}).get("has_conflict"):
        return f"已完成 {task_count} 个子任务，但证据存在冲突，暂时无法给出唯一赢家。"
    if answer_type == "exploration_plan":
        return f"已完成 {task_count} 个探索子任务，建议按阶段顺序继续执行。"
    if evidence_summary.get("uncertainty_notices"):
        return f"已完成 {task_count} 个子任务，但仍有部分证据不确定。"
    return f"已完成 {task_count} 个复杂任务子任务，结果已汇总。"


def _build_response_plan(answer_type: str, evidence_summary: dict[str, Any], decision_summary: dict[str, Any]) -> AnswerPlan:
    plan_input = {
        "task_type": answer_type,
        "comparison_matrix": evidence_summary.get("comparison_matrix") or {},
        "ranking_snapshot": {
            "shop_id": _normalize_text(decision_summary.get("winner_shop_id")),
            "shop_name": _normalize_text(decision_summary.get("winner_shop_name")),
            "status": "ok" if _normalize_text(decision_summary.get("winner_shop_id")) else "unknown",
            "comparison_matrix": evidence_summary.get("comparison_matrix") or {},
        },
        "facet_results": [],
        "answerable_facets": evidence_summary.get("answerable_facets") or [],
        "unknown_facets": evidence_summary.get("unknown_facets") or [],
        "failed_facets": evidence_summary.get("failed_facets") or [],
        "required_disclaimers": evidence_summary.get("uncertainty_notices") or [],
        "semantic_frame": {},
    }
    return AnswerPlan.model_validate(build_answer_plan(answer_type, plan_input))


def _execute_worker(state: dict[str, Any], spec: dict[str, Any], parent_decision: OrchestrationDecision) -> WorkerResult:
    workflow_name = _normalize_text(spec.get("workflow_name"))
    payload = deepcopy(dict(spec.get("payload") or {}))
    child_state = deepcopy(state)
    child_state.update(payload)
    child_state["workflow_name"] = workflow_name
    child_state["workflow_reason"] = _normalize_text(spec.get("description") or parent_decision.workflow_reason or workflow_name)
    child_state["task_complexity"] = _normalize_text(payload.get("task_complexity") or parent_decision.task_complexity or "medium")
    child_state["response_mode"] = _normalize_text(payload.get("response_mode") or parent_decision.response_mode or "exploration_plan")
    child_state["next_action"] = _normalize_text(payload.get("next_action") or parent_decision.next_action or "run_workflow")
    child_state["workflow_entry_name"] = _normalize_text(payload.get("workflow_entry_name"))
    try:
        from ...engine.workflow_registry import WORKFLOW_REGISTRY

        registration = WORKFLOW_REGISTRY.lookup(workflow_name)
    except Exception as exc:
        fallback_patch = {
            "workflow_name": workflow_name,
            "workflow_run_status": "fallback",
            "workflow_runner_error": "WORKFLOW_NOT_REGISTERED",
            "workflow_runner_reason": str(exc),
            "workflow_callable": "complex_orchestrator_workflow",
            "workflow_registered": False,
        }
        return WorkerResult.from_patch(
            task_id=_normalize_text(spec.get("task_id")) or workflow_name,
            workflow_name=workflow_name,
            patch=fallback_patch,
            provenance={"workflow_reason": child_state["workflow_reason"], "depends_on": list(spec.get("depends_on") or [])},
            trace_summary={"status": "fallback", "reason": str(exc)},
        )

    child_decision = _build_child_decision(workflow_name, parent_decision, payload)
    patch = registration.handler(child_state, child_decision)
    if not isinstance(patch, dict):
        patch = _to_dict(patch)
    patch.setdefault("workflow_name", workflow_name)
    patch.setdefault("workflow_run_status", "completed")
    patch.setdefault("workflow_callable", getattr(registration, "callable_name", workflow_name))
    patch.setdefault("workflow_registered", True)
    patch.setdefault("response_mode", child_decision.response_mode)
    patch.setdefault("next_action", child_decision.next_action)
    return WorkerResult.from_patch(
        task_id=_normalize_text(spec.get("task_id")) or workflow_name,
        workflow_name=workflow_name,
        patch=patch,
        provenance={
            "workflow_reason": child_state["workflow_reason"],
            "depends_on": list(spec.get("depends_on") or []),
            "registration_status": registration.status,
        },
        trace_summary={
            "status": patch.get("workflow_run_status", ""),
            "workflow_callable": patch.get("workflow_callable", ""),
        },
    )


def run_complex_orchestrator_workflow(
    state: dict[str, Any],
    decision: OrchestrationDecision | None = None,
) -> dict[str, Any]:
    """Run the Phase 9 complex orchestrator workflow."""

    decision = decision or _to_dict(state.get("orchestration_decision"))
    if not isinstance(decision, OrchestrationDecision):
        decision = OrchestrationDecision.model_validate(
            _to_dict(decision)
            or {
                "orchestration_pattern": "complex_orchestrator_workflow",
                "workflow_name": "complex_orchestrator_workflow",
                "workflow_reason": "complex orchestrator workflow",
                "task_complexity": "super_complex",
                "requires_tool": True,
                "requires_clarification": False,
                "response_mode": "exploration_plan",
                "confidence": 0.0,
                "missing_fields": [],
                "next_action": "run_workflow",
            }
        )

    semantic_frame = _to_dict(state.get("semantic_frame"))
    task_type = _normalize_text(state.get("task_type") or semantic_frame.get("task_type") or "super_complex")
    subtask_specs = _default_subtask_specs(state, decision)
    dag = SubTaskDAG.from_specs(subtask_specs)
    worker_results = [_execute_worker(dict(state), spec.to_dict(), decision) for spec in dag.topological_sort()]
    evidence_summary = EvidenceReducer.reduce(worker_results)
    decision_summary = DecisionReducer.reduce(worker_results)
    response_answer_type = _normalize_text(decision_summary.get("answer_type") or task_type or "general")
    answer_plan = _build_response_plan(response_answer_type, evidence_summary, decision_summary)
    response_text = _compose_response_text(response_answer_type, evidence_summary, decision_summary, dag)
    response_directive = build_response_directive(
        answer_text=response_text,
        answer_type=response_answer_type,
        response_mode="exploration_plan",
        fallback_reason="",
        trace_id=str(state.get("trace_id", "") or ""),
        preview_text=response_text,
        answer_source="complex_orchestrator_workflow",
        fallback_template_type="complex_orchestrator_workflow",
        metadata={
            "worker_results": [result.to_dict() for result in worker_results],
            "sub_task_dag": dag.to_dict(),
            "decision_summary": decision_summary,
            "evidence_summary": evidence_summary,
        },
    )
    contract_v2 = ResponseContractV2.from_response_directive(
        response_directive,
        verifier_result="pass",
        fallback_reason="",
        uncertainty_notices=list(evidence_summary.get("uncertainty_notices") or []),
        metadata={
            "workflow_name": "complex_orchestrator_workflow",
            "answer_source": "complex_orchestrator_workflow",
            "worker_results": [result.to_dict() for result in worker_results],
            "sub_task_dag": dag.to_dict(),
            "decision_summary": decision_summary,
            "evidence_summary": evidence_summary,
        },
        claims=list(decision_summary.get("claim_bindings") or []),
        citations=list(evidence_summary.get("citations") or []),
        cards=list(evidence_summary.get("cards") or []),
        confidence_band="high" if not evidence_summary.get("conflict_summary", {}).get("has_conflict") else "medium",
        response_policy={
            "workflow_name": "complex_orchestrator_workflow",
            "task_complexity": "super_complex",
            "subtask_count": len(worker_results),
        },
        clarification={},
        safety_notice=list(evidence_summary.get("uncertainty_notices") or []),
        trace_summary={
            "workflow_name": "complex_orchestrator_workflow",
            "subtask_count": len(worker_results),
            "dag": dag.to_dict(),
            "conflict_summary": evidence_summary.get("conflict_summary") or {},
        },
    )

    timestamp = _utc_now_iso()
    patch: dict[str, Any] = {
        "workflow_name": "complex_orchestrator_workflow",
        "orchestration_pattern": "complex_orchestrator_workflow",
        "workflow_reason": str(decision.workflow_reason or "complex orchestrator workflow"),
        "workflow_run_status": "completed",
        "workflow_runner_error": "",
        "workflow_runner_reason": str(decision.workflow_reason or "complex orchestrator workflow"),
        "workflow_candidate_reason": str(decision.workflow_reason or "complex orchestrator workflow"),
        "workflow_started_at": timestamp,
        "workflow_finished_at": timestamp,
        "workflow_callable": "run_complex_orchestrator_workflow",
        "workflow_registered": True,
        "response_mode": "exploration_plan",
        "next_action": "run_workflow",
        "task_complexity": "super_complex",
        "answer_plan": answer_plan,
        "draft_response": response_text,
        "preview_text": response_text,
        "response_directive": response_directive,
        "response_contract_v2": contract_v2,
        "response_contract_v1": contract_v2.to_v1(
            verifier_result="pass",
            fallback_reason="",
            uncertainty_notices=list(evidence_summary.get("uncertainty_notices") or []),
            metadata={
                "workflow_name": "complex_orchestrator_workflow",
                "answer_source": "complex_orchestrator_workflow",
                "response_contract_v2": contract_v2.model_dump(),
            },
        ),
        "answer_source": "complex_orchestrator_workflow",
        "verifier_result": "pass",
        "answer_verify_passed": True,
        "answer_verify_violations": [],
        "fallback_reason": "",
        "answer_fallback_reason": "",
        "final_safety_status": "safe",
        "llm_verbalizer_called": False,
        "llm_called": False,
        "llm_backend": "deterministic",
        "worker_results": [result.to_dict() for result in worker_results],
        "sub_task_dag": dag.to_dict(),
        "evidence_pack": evidence_summary,
        "decision_plan": decision_summary,
        "decision_summary": decision_summary,
        "evidence_summary": evidence_summary,
        "trace_summary": {
            "workflow_name": "complex_orchestrator_workflow",
            "subtask_count": len(worker_results),
            "dag": dag.to_dict(),
            "conflict_summary": evidence_summary.get("conflict_summary") or {},
        },
        "state_keys_changed": [
            "workflow_name",
            "orchestration_pattern",
            "workflow_run_status",
            "workflow_runner_error",
            "workflow_runner_reason",
            "workflow_started_at",
            "workflow_finished_at",
            "workflow_callable",
            "workflow_registered",
            "response_mode",
            "next_action",
            "task_complexity",
            "answer_plan",
            "draft_response",
            "preview_text",
            "response_directive",
            "response_contract_v2",
            "response_contract_v1",
            "answer_source",
            "verifier_result",
            "answer_verify_passed",
            "answer_verify_violations",
            "fallback_reason",
            "answer_fallback_reason",
            "final_safety_status",
        ],
    }
    patch.update(
        {
            "answer_verify_passed": True,
            "workflow_candidate_reason": str(decision.workflow_reason or "complex orchestrator workflow"),
        }
    )
    log_kv(
        _LOGGER,
        20,
        "[WORKFLOW_RUNNER]",
        tone="route",
        node_name="complex_orchestrator_workflow",
        workflow_name="complex_orchestrator_workflow",
        status="completed",
        subtask_count=len(worker_results),
    )
    return patch
