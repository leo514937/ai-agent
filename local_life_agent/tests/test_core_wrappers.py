"""Focused tests for the thin core wrappers added in batch A."""

from __future__ import annotations

from typing import Any

from ..core import (
    CandidateCore,
    DecisionCore,
    EvidenceCore,
    ExecutionCore,
    PlanningCore,
    ResponseCore,
    StateCore,
)
from ..core.state_core import build_missing_user_context, is_location_provided
from ..domain.candidate import CandidateSource, CandidateSpec, CandidateStatus, LocalLifeGoalDraft, ResolvedCandidate, CandidateSet, GoalType
from ..domain.decision import DecisionPlan, DecisionType
from ..domain.state import SessionState
from ..domain.schemas import UserContext
from ..planning.decision.candidate_decision import CandidateEvidence, CandidateEvaluation


def test_state_core_builds_missing_location_and_state_patch():
    core = StateCore()
    ctx = core.build_session_state(current_shop={"shop_id": "shop_1"})
    patch = core.build_state_patch(set_fields={"current_shop": None}, clear_fields=["pending_clarification"])

    assert core.build_session_state().current_shop is None
    assert core.clone_session_state(ctx).current_shop == {"shop_id": "shop_1"}
    assert core.build_state_patch(set_fields={"foo": "bar"}).set_fields["foo"] == "bar"
    assert patch.clear_fields == ["pending_clarification"]


def test_state_core_missing_user_context_is_not_provided():
    core = StateCore()
    missing = build_missing_user_context()

    assert is_location_provided(missing) is False
    assert missing.location_status == "missing"
    assert missing.location_source == "receiver"
    assert missing.location_missing_reason == "user_location_not_provided"


def test_state_core_explicit_test_mock_location_is_provided():
    ctx = UserContext(
        location_name="测试位置",
        lat=39.96,
        lng=116.35,
        location_status="test_mock",
        location_source="test_mock",
    )

    assert is_location_provided(ctx) is True


def test_candidate_core_ordinal_without_history_returns_not_found():
    core = CandidateCore()
    goal = LocalLifeGoalDraft(goal_type=GoalType.COMPARISON, candidate_source=CandidateSource.CONTEXT, candidate_limit=2)
    spec = CandidateSpec(source=CandidateSource.CONTEXT, context_ref="第二家")

    result = core.resolve_context(goal, spec, state={})

    assert result.status == CandidateStatus.NOT_FOUND
    assert result.candidates == []


def test_candidate_core_builds_comparison_turn_artifact(monkeypatch):
    core = CandidateCore()

    monkeypatch.setattr(
        "local_life_agent.target.reference_resolver.resolve_comparison_targets",
        lambda *args, **kwargs: {
            "status": "NEED_CLARIFICATION",
            "targets": [{"shop_id": "shop_1", "shop_name": "A"}],
            "reason": "comparison_requires_at_least_two_shops",
        },
    )

    class _Pending:
        def model_dump(self):
            return {
                "original_task_type": "comparison",
                "candidate_targets": [{"shop_id": "shop_1", "shop_name": "A"}],
                "source_node": "candidate_core",
            }

    monkeypatch.setattr(
        "local_life_agent.target.clarification.build_pending_clarification",
        lambda **kwargs: _Pending(),
    )

    artifact = core.build_comparison_turn_artifact(
        text="第一家和这家比一下",
        session_state=SessionState(last_recommendation_list=[{"shop_id": "shop_1", "shop_name": "A"}]),
        semantic_frame={"task_type": "comparison"},
    )

    assert artifact.comparison_targets == [{"shop_id": "shop_1", "shop_name": "A"}]
    assert artifact.pending_clarification["source_node"] == "candidate_core"
    assert artifact.source == "comparison_context"


def test_planning_core_deterministic_goal_plan():
    core = PlanningCore()
    plan = core.plan_goal({"task_type": "comparison", "merchant_mentions": ["A", "B"]}, {}, "A和B哪个好")

    assert str(plan.goal_type) == "comparison"
    assert plan.candidate_limit == 2


def test_evidence_core_builds_pack_without_winner():
    core = EvidenceCore()
    pack = core.build(
        {"call_1": {"tool_name": "get_shop_detail", "result_status": "ok", "shop_id": "shop_1", "data": {"shop_name": "A"}}},
        {"shop_id": "shop_1", "shop_name": "A"},
        {"task_type": "recommendation", "tool_calls": []},
        recommendation_candidates=[{"shop_id": "shop_1", "shop_name": "A"}],
    )

    assert "final_winner" not in pack
    assert "best_shop" not in pack
    assert pack["ranking_snapshot"]["status"] == "ok"


def test_decision_core_recommendation_and_comparison_paths():
    core = DecisionCore()
    evidences = [
        CandidateEvidence(
            shop_id="shop_1",
            detail={"result_status": "ok", "data": {"shop_name": "A", "rating": 4.8}},
            open_status={"result_status": "ok", "data": {"open_status": "open"}},
            coupon={"result_status": "empty", "data": []},
            distance={"result_status": "ok", "data": {"distance_km": 0.8}},
        )
    ]
    evaluations = [
        CandidateEvaluation(
            shop_id="shop_1",
            dimension_scores={"rating": 4.8},
            score=10.0,
            rank=1,
        )
    ]

    plan = core.build_candidate_decision_plan(
        "recommendation",
        "去吃饭",
        "",
        evidences,
        evaluations,
        [],
    )
    mapped = core.map_candidate_decision_plan(plan)
    assert plan.final_recommendation == "A"
    assert mapped.main_recommendation["shop_id"] == "shop_1"
    assert mapped.selected_targets[0]["shop_id"] == "shop_1"

    comparison_plan = core.build_candidate_decision_plan(
        "comparison",
        "A和B哪个好",
        "",
        evidences,
        evaluations,
        [],
    )
    assert comparison_plan.final_recommendation is None


def test_execution_core_dispatch_and_batch(monkeypatch):
    core = ExecutionCore(call_fn=lambda tool_name, kwargs: {
        "call_id": kwargs.get("call_id", ""),
        "tool_name": tool_name,
        "shop_id": kwargs.get("shop_id", ""),
        "success": True,
        "result_status": "ok",
        "data": {"echo": True},
    })
    batch = core.execute_batch([
        {"call_id": "call_1", "tool_name": "echo_tool", "args": {"call_id": "call_1", "shop_id": "shop_1"}},
    ])
    assert "call_1" in batch
    assert batch["call_1"]["result_status"] == "ok"

    bad = core.dispatch("not_a_real_tool", {})
    assert bad.get("tool_name") == "not_a_real_tool"
    assert bad.get("success") is True


def test_response_core_generate_and_verify(monkeypatch):
    monkeypatch.setattr("local_life_agent.core.response_core.generate_answer", lambda *args, **kwargs: "ok")
    monkeypatch.setattr(
        "local_life_agent.core.response_core.verify_answer",
        lambda *args, **kwargs: {"passed": False, "violations": ["forced"], "failure_code": "forced"},
    )

    core = ResponseCore()
    plan = {"answer_type": "recommendation"}
    evidence = {"ranking_snapshot": {"ranked": [{"shop_id": "shop_1", "shop_name": "A"}]}, "forbidden_claims": []}

    assert core.generate(plan, evidence) == "ok"
    assert core.verify("A可以，下单请点击", evidence, "recommendation")["passed"] is False


def test_response_core_builds_displayed_items():
    core = ResponseCore()
    plan = DecisionPlan(
        decision_type=DecisionType.RECOMMENDATION,
        candidates=["shop_2", "shop_1"],
        winner_shop_id="shop_2",
        decision_context={"tone": "neutral"},
    )

    answer_plan = core.build_answer_plan(plan, {"ranking_snapshot": {}})

    assert answer_plan["target_shop_ids"] == ["shop_2"]
    assert answer_plan["response_sections"][0]["target_shop_ids"] == ["shop_2"]
