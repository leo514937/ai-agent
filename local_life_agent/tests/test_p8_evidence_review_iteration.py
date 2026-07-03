from __future__ import annotations

from local_life_agent.domain.candidate import GoalType, LocalLifeGoalDraft
from local_life_agent.domain.schemas import OrchestrationDecision
from local_life_agent.engine.workflows import exploration_planning_workflow as exploration_workflow_module
from local_life_agent.planning.evidence_review import review_evidence
from local_life_agent.tests.fakes import mock_tools
from local_life_agent.tests.helpers.fake_backends import FakeLocalLifeBackend, install_fake_runtime


def _goal(*, required_facets: list[str] | None = None, optional_facets: list[str] | None = None) -> LocalLifeGoalDraft:
    return LocalLifeGoalDraft(
        goal_type=GoalType.SINGLE_SHOP_QUERY,
        required_facets=required_facets or [],
        optional_facets=optional_facets or [],
    )


def _shop_by_name(name: str) -> dict:
    for shop in mock_tools._all_shops():
        if str(shop.get("shop_name", "") or "") == name:
            return dict(shop)
    raise AssertionError(name)


def _install_exploration_runtime(monkeypatch, backend: FakeLocalLifeBackend) -> None:
    install_fake_runtime(monkeypatch, backend)
    monkeypatch.setattr(exploration_workflow_module, "dispatch_tool_call", backend.dispatch_tool_call)
    monkeypatch.setattr(exploration_workflow_module, "verify_answer_plan", lambda answer, evidence, task_type: {"passed": True, "issues": [], "suggested_fix": "", "task_type": task_type})


def test_p8_evidence_review_proceeds_when_required_facets_answerable():
    result = review_evidence(
        _goal(required_facets=["coupon"]),
        {
            "facet_results": [
                {"facet": "coupon", "result_status": "ok", "required": True},
            ],
        },
    )

    assert result.action == "proceed"
    assert result.next_action == "FINISH"
    assert result.answerable_facets == ["coupon"]


def test_p8_retry_for_retryable_tool_failure_with_budget():
    result = review_evidence(
        _goal(required_facets=["coupon"]),
        {
            "facet_results": [
                {"facet": "coupon", "result_status": "timeout", "required": True, "tool_name": "get_coupon_list"},
            ],
            "retry_budget_remaining": 1,
        },
    )

    assert result.action == "retry"
    assert result.retry_budget_remaining == 1
    assert result.tool_failures
    assert result.tool_failures[0].retryable is True


def test_p8_clarifies_for_missing_target_instead_of_retrying():
    result = review_evidence(
        _goal(required_facets=["coupon"]),
        {
            "facet_results": [],
            "missing_input": ["current_shop"],
            "clarification_needed": True,
        },
    )

    assert result.action == "clarify"
    assert result.clarification_reason


def test_p8_replans_missing_facets_when_budget_available():
    result = review_evidence(
        _goal(required_facets=["coupon", "open_status"]),
        {
            "facet_results": [
                {"facet": "coupon", "result_status": "ok", "required": True},
                {"facet": "open_status", "result_status": "unknown", "required": True},
            ],
            "replan_budget_remaining": 1,
        },
    )

    assert result.action == "replan_missing_facets"
    assert "open_status" in result.missing_facets
    assert result.next_action == "REPLAN_EVIDENCE"


def test_p8_expand_search_for_empty_results_with_budget():
    result = review_evidence(
        _goal(required_facets=["coupon"]),
        {
            "facet_results": [
                {"facet": "coupon", "result_status": "empty", "required": True},
            ],
            "expand_search_budget_remaining": 1,
        },
    )

    assert result.action == "expand_search"
    assert result.next_step == "expand_search"
    assert result.next_action == "FINISH"


def test_p8_retry_budget_exhaustion_degrades_or_fallbacks():
    result = review_evidence(
        _goal(required_facets=["coupon"]),
        {
            "facet_results": [
                {"facet": "coupon", "result_status": "timeout", "required": True, "tool_name": "get_coupon_list"},
            ],
            "retry_budget_remaining": 0,
        },
    )

    assert result.action == "fallback"
    assert result.next_action == "FALLBACK"
    assert result.fallback_reason


def test_p8_degrades_with_partial_answerable_facets():
    result = review_evidence(
        _goal(required_facets=["coupon"], optional_facets=["distance"]),
        {
            "facet_results": [
                {"facet": "coupon", "result_status": "ok", "required": True},
                {"facet": "distance", "result_status": "unknown", "required": False},
            ],
            "replan_budget_remaining": 0,
        },
    )

    assert result.action == "degrade"
    assert result.can_degrade is True
    assert "distance" in result.unknown_facets


def test_p8_fallback_when_no_answerable_facets_and_budget_exhausted():
    result = review_evidence(
        _goal(required_facets=["coupon"]),
        {
            "facet_results": [
                {"facet": "coupon", "result_status": "timeout", "required": True, "tool_name": "get_coupon_list"},
            ],
            "retry_budget_remaining": 0,
            "replan_budget_remaining": 0,
            "expand_search_budget_remaining": 0,
        },
    )

    assert result.action == "fallback"
    assert result.next_action == "FALLBACK"
    assert result.failed_facets == ["coupon"]


def test_p8_exploration_partial_success_degrades_route_plan(monkeypatch):
    backend = FakeLocalLifeBackend(scenario_name="p8_exploration")
    _install_exploration_runtime(monkeypatch, backend)

    def _search_shops(query: str, location: dict | None = None, limit: int | None = None) -> dict:
        compact = str(query or "").strip()
        if "咖啡" in compact:
            return {"success": True, "result_status": "empty", "data": [], "total": 0}
        if "餐厅" in compact or "饭" in compact:
            item = _shop_by_name("川味轩(知春路店)")
            return {"success": True, "result_status": "ok", "data": [item], "total": 1}
        return {"success": True, "result_status": "empty", "data": [], "total": 0}

    monkeypatch.setattr(backend, "search_shops", _search_shops)

    state = {
        "trace_id": "t_p8",
        "session_id": "s_p8",
        "turn_id": "turn_p8",
        "task_type": "coffee_then_dinner",
        "raw_text": "先喝咖啡然后吃晚饭",
        "normalized_text": "先喝咖啡然后吃晚饭",
        "semantic_frame": {
            "task_type": "coffee_then_dinner",
            "primary_task": "coffee_then_dinner",
            "facets": [
                {"name": "咖啡", "group": "category", "required": True},
                {"name": "餐厅", "group": "category", "required": True},
            ],
            "hard_constraints": {},
            "soft_preferences": {},
            "ranking_signals": {},
            "need_context": False,
        },
        "user_context": {"lat": 39.9609, "lng": 116.3581, "location_status": "provided", "location_source": "test"},
        "event_log": [],
    }
    decision = OrchestrationDecision(
        orchestration_pattern="exploration_planning",
        workflow_name="exploration_planning",
        workflow_reason="p8 exploration",
        task_complexity="high",
        requires_tool=True,
        requires_clarification=False,
        response_mode="exploration_plan",
        confidence=0.88,
        missing_fields=[],
        next_action="run_workflow",
    )

    result = exploration_workflow_module.run_exploration_planning_workflow(state, decision)

    assert result["workflow_name"] == "exploration_planning"
    assert "咖啡" in result["final_response"] or "部分信息暂无法确认" in result["final_response"]
    assert "state_update_plan_preview" in result
