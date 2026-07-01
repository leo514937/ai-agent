from __future__ import annotations

import pytest

from local_life_agent.domain.schemas import OrchestrationDecision
from local_life_agent.engine._routes import _route_workflow_runner
from local_life_agent.engine.workflow_registry import WORKFLOW_REGISTRY
from local_life_agent.engine.workflow_runner import h_workflow_runner
import local_life_agent.engine.workflow_runner as workflow_runner_module
import local_life_agent.engine.workflows.exploration_planning_workflow as exploration_workflow_module
from local_life_agent.planning.orchestration_router import route_orchestration


ALLOWED_TOOLS = {
    "search_shops",
    "get_shop_detail",
    "check_open_status",
    "get_distance_eta",
    "get_shop_review_summary",
    "get_coupon_list",
    "get_deal_list",
}


def _decision(task_type: str, *, raw_text: str = "", workflow_reason: str = "") -> OrchestrationDecision:
    return OrchestrationDecision(
        orchestration_pattern="exploration_planning",
        workflow_name="exploration_planning",
        workflow_reason=workflow_reason or f"{task_type} exploration",
        task_complexity="high",
        requires_tool=True,
        requires_clarification=False,
        response_mode="exploration_plan",
        confidence=0.7,
        missing_fields=[],
        next_action="run_workflow",
    )


def _state(task_type: str, raw_text: str, *, lat: float = 39.9, lng: float = 116.4) -> dict[str, object]:
    return {
        "trace_id": "trace_phase8",
        "session_id": "session_phase8",
        "turn_id": "turn_phase8",
        "task_type": task_type,
        "raw_text": raw_text,
        "normalized_text": raw_text,
        "semantic_frame": {
            "task_type": task_type,
            "primary_task": task_type,
            "hard_constraints": {},
            "soft_preferences": {},
            "ranking_signals": {},
            "need_context": False,
            "facets": [],
        },
        "user_context": {"lat": lat, "lng": lng},
        "event_log": [],
    }


def _install_success_dispatch(monkeypatch):
    calls: list[str] = []

    def dispatch(tool_name: str, kwargs: dict[str, object]) -> dict[str, object]:
        calls.append(tool_name)
        assert tool_name in ALLOWED_TOOLS
        call_id = str(kwargs.get("call_id", "") or "")
        shop_id = str(kwargs.get("shop_id", "") or "")
        if tool_name == "search_shops":
            query = str(kwargs.get("query", "") or "店")
            return {
                "call_id": call_id,
                "shop_id": "",
                "tool_name": tool_name,
                "success": True,
                "result_status": "ok",
                "data": [
                    {
                        "shop_id": f"{query}_1",
                        "shop_name": f"{query} A",
                        "address": "测试路 1 号",
                        "open_status": "open",
                        "distance_km": 1.2,
                        "eta_minutes": 10,
                    }
                ],
                "error_code": "",
                "error_message": "",
                "source": "test",
                "backend_source": "test",
                "degraded": False,
            }
        if tool_name == "get_shop_detail":
            return {
                "call_id": call_id,
                "shop_id": shop_id,
                "tool_name": tool_name,
                "success": True,
                "result_status": "ok",
                "data": {"shop_id": shop_id, "shop_name": "测试店", "avg_price": 58},
                "error_code": "",
                "error_message": "",
                "source": "test",
                "backend_source": "test",
                "degraded": False,
            }
        if tool_name == "check_open_status":
            return {
                "call_id": call_id,
                "shop_id": shop_id,
                "tool_name": tool_name,
                "success": True,
                "result_status": "ok",
                "data": {"shop_id": shop_id, "open_status": "open"},
                "error_code": "",
                "error_message": "",
                "source": "test",
                "backend_source": "test",
                "degraded": False,
            }
        if tool_name == "get_distance_eta":
            return {
                "call_id": call_id,
                "shop_id": shop_id,
                "tool_name": tool_name,
                "success": True,
                "result_status": "ok",
                "data": {"shop_id": shop_id, "distance_km": 1.3, "eta_minutes": 12},
                "error_code": "",
                "error_message": "",
                "source": "test",
                "backend_source": "test",
                "degraded": False,
            }
        if tool_name == "get_shop_review_summary":
            return {
                "call_id": call_id,
                "shop_id": shop_id,
                "tool_name": tool_name,
                "success": True,
                "result_status": "ok",
                "data": {"items": [{"shop_id": shop_id, "summary": "评价不错"}]},
                "error_code": "",
                "error_message": "",
                "source": "test",
                "backend_source": "test",
                "degraded": False,
            }
        if tool_name == "get_coupon_list":
            return {
                "call_id": call_id,
                "shop_id": shop_id,
                "tool_name": tool_name,
                "success": True,
                "result_status": "empty",
                "data": [],
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
            "data": {"shop_id": shop_id},
            "error_code": "",
            "error_message": "",
            "source": "test",
            "backend_source": "test",
            "degraded": False,
        }

    monkeypatch.setattr(exploration_workflow_module, "dispatch_tool_call", dispatch)
    return calls


def _install_failure_dispatch(monkeypatch, *, fail_tool: str):
    calls: list[str] = []

    def dispatch(tool_name: str, kwargs: dict[str, object]) -> dict[str, object]:
        calls.append(tool_name)
        assert tool_name in ALLOWED_TOOLS
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
        if tool_name == fail_tool:
            return {
                "call_id": call_id,
                "shop_id": shop_id,
                "tool_name": tool_name,
                "success": False,
                "result_status": "failed",
                "data": None,
                "error_code": "TOOL_FAILED",
                "error_message": "simulated failure",
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
            "data": {"shop_id": shop_id, "shop_name": "测试店"},
            "error_code": "",
            "error_message": "",
            "source": "test",
            "backend_source": "test",
            "degraded": False,
        }

    monkeypatch.setattr(exploration_workflow_module, "dispatch_tool_call", dispatch)
    return calls


def test_registry_entry_is_real_callable():
    registration = WORKFLOW_REGISTRY.lookup("exploration_planning")
    assert registration.is_real is True
    assert registration.entry_node == "response_subgraph"
    assert registration.callable_name == "run_exploration_planning_workflow"


def test_workflow_runner_can_schedule_exploration(monkeypatch):
    _install_success_dispatch(monkeypatch)
    monkeypatch.setattr(workflow_runner_module, "WORKFLOW_REGISTRY", WORKFLOW_REGISTRY)

    result = h_workflow_runner(
        {
            **_state("coffee_then_dinner", "先喝咖啡然后吃晚饭"),
            "workflow_name": "exploration_planning",
            "orchestration_pattern": "exploration_planning",
            "workflow_reason": "phase 8 exploration",
            "orchestration_decision": _decision("coffee_then_dinner"),
        }
    )

    assert result["workflow_run_status"] == "completed"
    assert result["response_mode"] == "exploration_plan"
    assert result["workflow_callable"] == "run_exploration_planning_workflow"
    assert result["workflow_registered"] is True


@pytest.mark.parametrize(
    ("task_type", "raw_text", "max_subgoals"),
    [
        ("coffee_then_dinner", "先喝咖啡然后吃晚饭", 2),
        ("date_plan", "约会安排", 3),
        ("family_activity_plan", "周末亲子活动安排", 3),
    ],
)
def test_exploration_subgoal_limits(monkeypatch, task_type, raw_text, max_subgoals):
    calls = _install_success_dispatch(monkeypatch)

    result = exploration_workflow_module.run_exploration_planning_workflow(
        _state(task_type, raw_text),
        _decision(task_type),
    )

    plan = result["exploration_plan"]
    assert len(plan.subgoals) <= max_subgoals
    assert plan.tool_rounds_used <= 2
    assert result["response_mode"] == "exploration_plan"
    assert result["workflow_name"] == "exploration_planning"
    assert set(calls).issubset(ALLOWED_TOOLS)
    assert "search_pois" not in calls
    assert "search_business_areas" not in calls
    assert "estimate_travel_time" not in calls
    assert "calculate_distance" not in calls


def test_exceeding_three_subgoals_falls_back(monkeypatch):
    _install_success_dispatch(monkeypatch)

    result = exploration_workflow_module.run_exploration_planning_workflow(
        _state("custom_trip", "先喝咖啡，然后吃饭，再看电影，之后去散步"),
        _decision("custom_trip", workflow_reason="too many subgoals"),
    )

    assert result["workflow_name"] == "clarification_fallback"
    assert result["response_mode"] in {"clarify", "fallback"}


def test_missing_location_falls_back(monkeypatch):
    _install_success_dispatch(monkeypatch)

    result = exploration_workflow_module.run_exploration_planning_workflow(
        _state("date_plan", "约会安排", lat=0.0, lng=0.0) | {"user_context": {}},
        _decision("date_plan"),
    )

    assert result["workflow_name"] == "clarification_fallback"
    assert result["response_mode"] == "clarify"


def test_tool_failure_does_not_hallucinate(monkeypatch):
    calls = _install_failure_dispatch(monkeypatch, fail_tool="get_shop_detail")

    result = exploration_workflow_module.run_exploration_planning_workflow(
        _state("coffee_then_dinner", "先喝咖啡然后吃晚饭"),
        _decision("coffee_then_dinner"),
    )

    assert result["workflow_name"] == "clarification_fallback"
    assert result["response_mode"] in {"clarify", "fallback"}
    assert "get_shop_detail" in calls


def test_no_forbidden_future_tools_and_no_state_pollution(monkeypatch):
    calls = _install_success_dispatch(monkeypatch)

    result = exploration_workflow_module.run_exploration_planning_workflow(
        _state("family_activity_plan", "亲子活动安排"),
        _decision("family_activity_plan"),
    )

    assert set(calls).issubset(ALLOWED_TOOLS)
    assert "last_recommendation_list" not in result
    assert "comparison_targets" not in result
    assert "current_shop" not in result
    assert "search_pois" not in calls
    assert "search_business_areas" not in calls
    assert "estimate_travel_time" not in calls
    assert "calculate_distance" not in calls
    assert "rag" not in "".join(calls).lower()


def test_existing_workflows_still_route_correctly():
    recommendation = route_orchestration(
        {
            "top_intent": "local_life",
            "task_type": "recommendation",
            "semantic_frame": {"confidence": 0.82},
            "comparison_targets": [],
            "last_recommendation_list": [],
            "current_shop": None,
            "pending_clarification": None,
            "raw_text": "附近推荐火锅",
        }
    )
    deterministic = route_orchestration(
        {
            "top_intent": "local_life",
            "task_type": "single_shop_query",
            "semantic_frame": {"confidence": 0.84, "primary_task": "shop_coupon"},
            "current_shop": {"shop_id": "shop_1", "shop_name": "测试店"},
            "pending_clarification": None,
            "raw_text": "这家店有券吗",
        }
    )
    direct = route_orchestration(
        {
            "top_intent": "chat",
            "task_type": "chat",
            "semantic_frame": {"confidence": 0.9},
            "raw_text": "你好",
        }
    )
    fallback = route_orchestration(
        {
            "top_intent": "local_life",
            "task_type": "single_shop_query",
            "semantic_frame": {"confidence": 0.64},
            "raw_text": "这家店",
        }
    )

    assert recommendation["workflow_name"] == "discovery_decision"
    assert deterministic["workflow_name"] == "deterministic_tool"
    assert direct["workflow_name"] == "direct_response"
    assert fallback["workflow_name"] == "clarification_fallback"


def test_workflow_runner_routes_exploration_to_response_subgraph():
    assert _route_workflow_runner({"workflow_name": "exploration_planning", "workflow_run_status": "dispatched"}) == "response_subgraph"
