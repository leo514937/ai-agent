from __future__ import annotations

from local_life_agent.domain.decision import DecisionPlan as CanonicalDecisionPlan
from local_life_agent.domain.evidence import EvidenceReviewResult
from local_life_agent.domain.facets import TargetResolutionResult
from local_life_agent.domain.graph_state_model import validate_graph_state
from local_life_agent.domain.schemas import AnswerPlan, EvidencePack, ExecutionPlan, OrchestrationDecision, ToolCallSpec, ToolResult
from local_life_agent.domain.state import SessionState, SessionWriteDirective, StateUpdatePlan
from local_life_agent.observability.metrics import TurnMetrics
from local_life_agent.observability.trace import TurnTrace, validate_turn_trace
from local_life_agent.planning.budget.budget_context import BudgetContext


def _tool_result() -> ToolResult:
    return ToolResult.model_validate(
        {
            "call_id": "call_1",
            "shop_id": "shop_1",
            "tool_name": "get_shop_detail",
            "success": True,
            "result_status": "ok",
            "data": {"shop_id": "shop_1"},
        }
    )


def test_graph_state_model_accepts_dict_and_base_models():
    orchestration = OrchestrationDecision(
        orchestration_pattern="deterministic_tool",
        workflow_name="deterministic_tool",
        workflow_reason="ok",
        task_complexity="low",
        requires_tool=True,
        requires_clarification=False,
        response_mode="tool_answer",
        confidence=0.9,
        missing_fields=[],
        next_action="run_workflow",
    )
    execution_plan = ExecutionPlan.model_validate(
        {
            "plan_id": "plan_1",
            "task_type": "single_shop_query",
            "tool_calls": [
                ToolCallSpec(call_id="call_1", tool_name="get_shop_detail", args={"shop_id": "shop_1"}, target_shop_id="shop_1")
            ],
            "target_shop_ids": ["shop_1"],
            "blocked_tool_calls": None,
        }
    )
    evidence_pack = EvidencePack.model_validate(
        {
            "owner": "execution_review_subgraph",
            "answerable_facets": ["detail"],
            "unknown_facets": None,
            "failed_facets": None,
            "target_shop_ids": ["shop_1"],
            "evidence_items": [],
        }
    )
    decision_plan = CanonicalDecisionPlan.model_validate(
        {
            "decision_type": "single_shop_query",
            "goal_id": "goal_1",
            "candidates": ["shop_1"],
            "answerable_facets": ["detail"],
            "unknown_facets": [],
            "failed_facets": [],
            "claims": [],
        }
    )
    answer_plan = AnswerPlan.model_validate(
        {
            "answer_type": "single_shop_query",
            "facets": [],
            "answerable_facets": ["detail"],
            "unknown_facets": [],
            "failed_facets": [],
            "required_disclaimers": [],
            "target_shop_ids": ["shop_1"],
            "response_sections": [],
            "allowed_claims": [],
            "required_claims": [],
            "must_mention_unknowns": [],
            "forbidden_claims": [],
        }
    )
    directive = SessionWriteDirective(
        set_fields={"current_shop": {"shop_id": "shop_1"}},
        clear_fields=["pending_clarification"],
        source="state_update_planner",
        evidence_ref="ev_1",
        ttl=120,
        location_context={"city": "beijing"},
        reason="resolved",
    )

    state = {
        "workflow_name": "deterministic_tool",
        "orchestration_decision": orchestration,
        "execution_plan": execution_plan,
        "validated_plan": execution_plan.model_dump(),
        "evidence_pack": evidence_pack,
        "decision_plan": decision_plan,
        "answer_plan": answer_plan,
        "state_update_plan": directive,
        "session_state": SessionState(current_shop={"shop_id": "shop_1"}),
        "session_state_before": SessionState(),
        "session_state_after": SessionState(current_shop={"shop_id": "shop_1"}),
        "budget_context": BudgetContext(tool_round_budget=1).model_dump(),
        "tool_results": {"call_1": _tool_result()},
        "tool_result_set": {"call_1": _tool_result()},
        "resolved_target": {"status": "RESOLVED", "resolved_shop": {"shop_id": "shop_1", "shop_name": "店1"}},
        "resolve_shop_result": {"status": "RESOLVED", "resolved_shop": {"shop_id": "shop_1", "shop_name": "店1"}},
    }

    result = validate_graph_state(state)

    assert result.is_valid is True
    assert result.model.workflow_name == "deterministic_tool"
    assert result.model.response_mode == "tool_answer"
    assert result.model.execution_plan is not None
    assert result.model.evidence_pack is not None
    assert result.model.decision_plan is not None
    assert result.model.state_update_plan is not None
    assert result.model.tool_results["call_1"].tool_name == "get_shop_detail"
    assert result.model.resolve_shop_result is not None
    assert result.issues == []


def test_graph_state_validation_flags_alias_conflicts_and_multi_value_names():
    state = {
        "workflow_name": ["deterministic_tool", "response_subgraph"],
        "tool_results": {"call_1": _tool_result()},
        "tool_result_set": {},
        "resolved_target": {"status": "RESOLVED", "resolved_shop": {"shop_id": "shop_1"}},
        "resolve_shop_result": {"status": "NOT_FOUND"},
    }

    result = validate_graph_state(state)

    assert result.is_valid is True
    assert result.model.workflow_name == "deterministic_tool"
    assert any(issue.issue_code == "multi_value_workflow_name" for issue in result.issues)
    assert any(issue.issue_code == "alias_conflict" and issue.field_name == "tool_result_set" for issue in result.issues)
    assert any(issue.issue_code == "alias_conflict" and issue.field_name == "resolve_shop_result" for issue in result.issues)


def test_key_models_remain_dict_and_base_model_compatible():
    plan = ExecutionPlan.model_validate(
        {
            "plan_id": "plan_1",
            "task_type": "single_shop_query",
            "tool_calls": None,
            "target_shop_ids": None,
        }
    )
    evidence = EvidencePack.model_validate(
        {
            "owner": "execution_review_subgraph",
            "answerable_facets": None,
            "unknown_facets": None,
            "failed_facets": None,
            "evidence_items": None,
            "tool_results": None,
        }
    )
    decision = CanonicalDecisionPlan.model_validate(
        {
            "decision_type": "single_shop_query",
            "goal_id": "goal_1",
            "candidates": None,
            "answerable_facets": None,
            "unknown_facets": None,
            "failed_facets": None,
            "claims": None,
        }
    )
    review = EvidenceReviewResult.model_validate(
        {
            "retryable_facets": None,
            "missing_facets": None,
            "unknown_facets": None,
            "failed_facets": None,
            "answerable_facets": None,
            "required_ok": None,
            "required_empty": None,
            "required_unknown": None,
            "required_failed": None,
            "optional_ok": None,
            "optional_empty": None,
            "optional_unknown": None,
            "optional_failed": None,
            "missing_evidence": None,
            "unsafe_answer_risks": None,
            "budget_exhausted_reasons": None,
            "stale_facets": None,
            "expired_facets": None,
            "disclaimer_facets": None,
        }
    )
    turn_trace_model = validate_turn_trace(TurnTrace(trace_id="trace_1"))
    metrics = TurnMetrics.model_validate({"workflow_name": "deterministic_tool", "route_task": "single_shop_query"})
    state_update = StateUpdatePlan.model_validate(
        {
            "set_fields": {"current_shop": {"shop_id": "shop_1"}},
            "clear_fields": None,
            "source": "state_update_planner",
            "evidence_ref": "ev_1",
            "ttl": -5,
            "location_context": None,
        }
    )
    target_resolution = TargetResolutionResult.model_validate(
        {
            "resolved": True,
            "target_shop": {"shop_id": "shop_1", "shop_name": "店1"},
            "comparison_targets": None,
        }
    )

    assert plan.tool_calls == []
    assert plan.target_shop_ids == []
    assert evidence.answerable_facets == []
    assert evidence.unknown_facets == []
    assert decision.candidates == []
    assert review.retryable_facets == []
    assert turn_trace_model.trace_id == "trace_1"
    assert metrics.workflow_name == "deterministic_tool"
    assert state_update.clear_fields == []
    assert state_update.ttl == 0
    assert target_resolution.comparison_targets == []


def test_state_update_directive_clone_keeps_subclass_behavior():
    directive = SessionWriteDirective(set_fields={"current_shop": {"shop_id": "shop_1"}}, clear_fields=["pending_clarification"])
    clone = directive.clone()

    assert isinstance(clone, SessionWriteDirective)
    assert clone.set_fields == directive.set_fields
    clone.set_fields["current_shop"] = {"shop_id": "shop_2"}
    assert directive.set_fields["current_shop"]["shop_id"] == "shop_1"
