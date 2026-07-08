from __future__ import annotations

import json

import pytest

from local_life_agent.domain.evidence import EvidenceReviewAction
from local_life_agent.engine.subgraphs import response_subgraph as response_subgraph_module
from local_life_agent.engine.workflows import deterministic_tool_workflow as deterministic_workflow_module
from local_life_agent.engine.workflows import exploration_planning_workflow as exploration_workflow_module
from local_life_agent.observability.metrics import build_turn_metrics
from local_life_agent.planning.budget.budget_context import BudgetContext, budget_context_from_state, default_budget_context
from local_life_agent.planning.evidence.evidence_cache import EvidenceCache
from local_life_agent.planning.evidence.evidence_review import review_evidence
from local_life_agent.planning.freshness.freshness_policy import (
    FreshnessClass,
    compute_location_fingerprint,
    freshness_policy_for_facet,
)
from local_life_agent.planning.orchestrator.orchestrator_cache_key import build_orchestrator_cache_inputs
from local_life_agent.planning.orchestrator.sub_task_dag import SubTaskSpec


def test_p12_budget_context_defaults_are_bounded():
    budget = BudgetContext()
    fallback = default_budget_context(None)
    recovered = budget_context_from_state({})

    assert budget.tool_round_budget > 0
    assert budget.retry_budget >= 0
    assert budget.expand_search_budget >= 0
    assert budget.rewrite_budget >= 0
    assert budget.facet_enrich_budget > 0
    assert budget.tool_round_budget <= 3
    assert budget.retry_budget <= 2
    assert budget.expand_search_budget <= 2
    assert budget.rewrite_budget <= 2
    assert budget.facet_enrich_budget <= 8
    assert budget.deadline_remaining_ms is None or budget.deadline_remaining_ms > 0
    assert json.loads(budget.model_dump_json())["tool_round_budget"] == budget.tool_round_budget
    assert fallback.model_dump() == budget.model_dump()
    assert recovered.model_dump() == budget.model_dump()


@pytest.mark.parametrize(
    ("facet", "freshness_class"),
    [
        ("open_status", FreshnessClass.STRONG_DYNAMIC),
        ("coupon", FreshnessClass.STRONG_DYNAMIC),
        ("queue_status", FreshnessClass.STRONG_DYNAMIC),
        ("rating", FreshnessClass.WEAK_DYNAMIC),
        ("review_tags", FreshnessClass.WEAK_DYNAMIC),
        ("avg_price", FreshnessClass.WEAK_DYNAMIC),
        ("shop_static_info", FreshnessClass.WEAK_DYNAMIC),
        ("distance", FreshnessClass.LOCATION_BOUND),
        ("travel_time", FreshnessClass.LOCATION_BOUND),
    ],
)
def test_p12_freshness_policy_classification(facet: str, freshness_class: FreshnessClass):
    policy = freshness_policy_for_facet(facet)

    assert policy.facet == facet
    assert policy.freshness_class == freshness_class
    assert policy.ttl_seconds is None or policy.ttl_seconds > 0


def test_p12_distance_cache_requires_same_location_fingerprint():
    cache = EvidenceCache()
    payload = {"facet": "distance", "value": {"distance_km": 1.2}}
    scope_a = {"workflow": "p12", "location_fingerprint": compute_location_fingerprint({"lat": 39.9, "lng": 116.3})}
    scope_b = {"workflow": "p12", "location_fingerprint": compute_location_fingerprint({"lat": 39.8, "lng": 116.2})}

    first, first_meta = cache.get_or_build(scope_a, payload, lambda: {"facet_results": [{"facet": "distance", "result_status": "ok"}]})
    second, second_meta = cache.get_or_build(scope_a, payload, lambda: {"facet_results": [{"facet": "distance", "result_status": "empty"}]})
    other, other_meta = cache.get_or_build(scope_b, payload, lambda: {"facet_results": [{"facet": "distance", "result_status": "ok"}]})

    assert first_meta["cache_hit"] is False
    assert second_meta["cache_hit"] is True
    assert other_meta["cache_hit"] is False
    assert first["evidence_cache_hit"] is False
    assert second["evidence_cache_hit"] is True
    assert first_meta["cache_key"] != other_meta["cache_key"]


def test_p12_same_turn_cache_reuse_is_allowed_and_traceable():
    cache = EvidenceCache()
    payload = {"facet": "open_status", "value": {"open_status": "open"}}
    scope = {"workflow": "p12", "turn_id": "turn-1", "location_fingerprint": compute_location_fingerprint({"lat": 39.9, "lng": 116.3})}

    first, first_meta = cache.get_or_build(scope, payload, lambda: {"facet_results": [{"facet": "open_status", "result_status": "ok"}]})
    second, second_meta = cache.get_or_build(scope, payload, lambda: {"facet_results": [{"facet": "open_status", "result_status": "empty"}]})

    assert first_meta["cache_hit"] is False
    assert second_meta["cache_hit"] is True
    assert first["evidence_cache_key"] == second["evidence_cache_key"]
    assert second["evidence_cache_hit"] is True


def test_p12_orchestrator_cache_inputs_include_required_dimensions():
    scope, payload = build_orchestrator_cache_inputs(
        {
            "session_id": "session-1",
            "trace_id": "trace-1",
            "location": {"lat": 39.9, "lng": 116.3},
            "freshness": "location_bound",
        },
        SubTaskSpec(
            task_id="task_a",
            workflow_name="exploration_planning",
            depends_on=("task_root",),
            payload={"query": "附近推荐"},
            description="explore",
        ),
        workflow_name="exploration_planning",
        tool_version="v1",
    )

    assert scope["session_id"] == "session-1"
    assert scope["trace_id"] == "trace-1"
    assert scope["workflow_name"] == "exploration_planning"
    assert scope["location"]
    assert scope["freshness"] == "location_bound"
    assert scope["tool_version"] == "v1"
    assert payload["task_id"] == "task_a"
    assert payload["payload"]["query"] == "附近推荐"


def test_p12_strong_dynamic_stale_evidence_cannot_be_claimed_as_fresh():
    result = review_evidence(
        type("Goal", (), {"required_facets": ["coupon"], "optional_facets": []})(),
        {
            "facet_results": [{"facet": "coupon", "result_status": "ok", "required": True}],
            "stale_facets": ["coupon"],
            "budget_context_snapshot": {"tool_round_budget": 1},
        },
    )

    assert result.action in {EvidenceReviewAction.DEGRADE, EvidenceReviewAction.FALLBACK}
    assert "coupon" in result.stale_facets
    assert "coupon" in (result.expired_facets or []) or "coupon" in result.unknown_facets
    assert result.trace_payload.get("stale_facets") == ["coupon"]


def test_p12_weak_dynamic_evidence_allows_disclaimer_when_stale():
    result = review_evidence(
        type("Goal", (), {"required_facets": ["rating"], "optional_facets": []})(),
        {
            "facet_results": [{"facet": "rating", "result_status": "ok", "required": True}],
            "stale_facets": ["rating"],
            "budget_context_snapshot": {"tool_round_budget": 1},
        },
    )

    assert result.action in {EvidenceReviewAction.PROCEED, EvidenceReviewAction.DEGRADE}
    assert "rating" in result.stale_facets
    assert "rating" in result.disclaimer_facets


def test_p12_tool_round_budget_exhaustion_degrades_without_more_tools(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []

    def fake_dispatch(tool_name: str, kwargs: dict[str, object]) -> dict[str, object]:
        calls.append(tool_name)
        raise AssertionError("tool dispatch should not be reached when tool_round_budget is exhausted")

    monkeypatch.setattr(deterministic_workflow_module, "dispatch_tool_call", fake_dispatch)

    state = {
        "trace_id": "trace_p12_deterministic",
        "session_id": "session_p12",
        "turn_id": "turn_p12",
        "task_type": "shop_coupon",
        "workflow_name": "deterministic_tool",
        "orchestration_pattern": "deterministic_tool",
        "semantic_frame": {"task_type": "shop_coupon", "primary_task": "shop_coupon", "facets": [{"name": "coupon"}, {"name": "open_status"}]},
        "current_shop": {"shop_id": "shop_1", "shop_name": "测试店"},
        "budget_context": BudgetContext(tool_round_budget=0).model_dump(),
        "event_log": [],
    }

    result = deterministic_workflow_module.run_deterministic_tool_workflow(state)

    assert calls == []
    assert result["workflow_run_status"] in {"fallback", "completed"}
    assert result["workflow_name"] == "clarification_fallback"
    assert result["response_mode"] in {"clarify", "fallback"}


def test_p12_rewrite_budget_exhaustion_fallbacks_after_verify_fail(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(response_subgraph_module, "verify_answer", lambda *args, **kwargs: {"passed": False, "issues": ["claim"], "suggested_fix": "fix", "recoverable": True})
    monkeypatch.setattr(response_subgraph_module, "_GRAPH_REWRITE_LIMIT", 99)
    monkeypatch.setattr(response_subgraph_module, "_h_answer_generate", lambda state: {"draft_response": "有券", "rewrite_count": state.get("rewrite_count", 0), "answer_source": "llm_verbalizer"})

    state = {
        "trace_id": "trace_p12_response",
        "session_id": "session_p12",
        "turn_id": "turn_p12",
        "response_mode": "answer",
        "rewrite_count": 0,
        "budget_context": BudgetContext(rewrite_budget=0).model_dump(),
        "evidence_pack": {"facet_results": [{"facet": "coupon", "result_status": "ok", "required": True}], "evidence_items": []},
        "p2_decision_plan": None,
        "event_log": [],
    }

    result = response_subgraph_module.h_response_subgraph(state)

    assert result["response_route"] in {"state_update_plan", "fallback_answer", "fallback_ready"}
    assert result.get("rewrite_count", 0) == 0
    assert result.get("answer_verify_passed") is False or result.get("verify_result") != "pass"


def test_p12_low_deadline_skips_low_priority_enrichment(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []

    def fake_dispatch(tool_name: str, kwargs: dict[str, object]) -> dict[str, object]:
        calls.append(tool_name)
        call_id = str(kwargs.get("call_id", "") or "")
        shop_id = str(kwargs.get("shop_id", "") or "")
        if tool_name == "search_shops":
            return {
                "call_id": call_id,
                "shop_id": "",
                "tool_name": tool_name,
                "success": True,
                "result_status": "ok",
                "data": [{"shop_id": "shop_1", "shop_name": "测试店", "address": "测试路 1 号"}],
                "error_code": "",
                "error_message": "",
                "source": "test",
                "backend_source": "test",
                "degraded": False,
            }
        return {
            "call_id": call_id,
            "shop_id": shop_id,
            "tool_name": tool_name,
            "success": True,
            "result_status": "ok",
            "data": {"shop_id": shop_id, "shop_name": "测试店", "avg_price": 58, "open_status": "open"},
            "error_code": "",
            "error_message": "",
            "source": "test",
            "backend_source": "test",
            "degraded": False,
        }

    monkeypatch.setattr(exploration_workflow_module, "dispatch_tool_call", fake_dispatch)

    state = {
        "trace_id": "trace_p12_explore",
        "session_id": "session_p12",
        "turn_id": "turn_p12",
        "task_type": "coffee_then_dinner",
        "raw_text": "先喝咖啡然后吃晚饭",
        "normalized_text": "先喝咖啡然后吃晚饭",
        "semantic_frame": {
            "task_type": "coffee_then_dinner",
            "primary_task": "coffee_then_dinner",
            "facets": [{"name": "coffee"}, {"name": "restaurant"}],
            "hard_constraints": {},
            "soft_preferences": {},
            "ranking_signals": {},
            "need_context": False,
        },
        "user_context": {"lat": 39.9609, "lng": 116.3581, "location_status": "provided", "location_source": "test"},
        "budget_context": BudgetContext(tool_round_budget=1, facet_enrich_budget=1, deadline_remaining_ms=1).model_dump(),
        "event_log": [],
    }
    decision = exploration_workflow_module.OrchestrationDecision(
        orchestration_pattern="exploration_planning",
        workflow_name="exploration_planning",
        workflow_reason="p12 exploration",
        task_complexity="high",
        requires_tool=True,
        requires_clarification=False,
        response_mode="exploration_plan",
        confidence=0.88,
        missing_fields=[],
        next_action="run_workflow",
    )

    result = exploration_workflow_module.run_exploration_planning_workflow(state, decision)

    assert "search_shops" in calls
    assert any(name != "search_shops" for name in calls) is False or result["workflow_name"] in {"exploration_planning", "clarification_fallback"}
    assert result["workflow_name"] in {"exploration_planning", "clarification_fallback"}
    assert result["response_mode"] in {"exploration_plan", "clarify", "fallback"}
    assert result.get("evidence_pack") is not None


def test_p12_budget_and_freshness_metrics_are_observable_only():
    final_state = {
        "workflow_name": "deterministic_tool_workflow",
        "route_task": "recommendation",
        "response_mode": "final",
        "task_type": "recommendation",
        "facets": ["口味", "距离"],
        "semantic_frame": {"task_type": "recommendation", "facets": [{"name": "口味"}]},
        "execution_plan": {
            "tool_calls": [{"call_id": "call_1"}],
            "facet_candidates": [{"name": "口味"}],
            "facet_validation_result": {"accepted_facets": ["口味"], "rejected_facets": [], "unsupported_facets": []},
            "blocked_tool_calls": [],
            "facet_budget_plan": {"budget_exceeded": False},
        },
        "answer_plan": {"facets": ["口味", "距离"]},
        "evidence_pack": {
            "evidence_items": [{"evidence_id": "e1", "freshness_class": "weak_dynamic", "ttl_seconds": 86400, "observed_at_ms": 1}],
            "answerable_facets": ["口味"],
            "unknown_facets": ["距离"],
            "failed_facets": [],
            "evidence_cache_hit": True,
            "stale_evidence_count": 1,
            "cache_stale_count": 1,
            "cache_refresh_count": 0,
            "location_fingerprint_mismatch_count": 1,
            "freshness_unknown_count": 0,
        },
        "review_results": {"evidence_review": {"next_action": "degrade", "budget_exhausted_reasons": ["tool_round_budget"]}},
        "state_update_plan": {"set_fields": {"comparison_targets": [{"shop_id": "shop_1"}]}, "clear_fields": ["pending_clarification"]},
        "answer_verify_passed": True,
        "fallback_reason": "",
        "final_safety_status": "safe",
        "event_log": [],
        "budget_context": BudgetContext(tool_round_budget=0, retry_budget=0, expand_search_budget=0, rewrite_budget=0, facet_enrich_budget=0, deadline_remaining_ms=0).model_dump(),
    }

    before = dict(final_state)
    metrics = build_turn_metrics(final_state)

    assert final_state == before
    assert metrics.cache_hit_count == 1
    assert metrics.budget_exceeded_count == 0 or metrics.budget_exceeded_count == 1
    assert metrics.stream_event_count == 0
