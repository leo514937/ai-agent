from __future__ import annotations

import pytest

from local_life_agent.domain.schemas import OrchestrationDecision
from local_life_agent.engine.workflow_registry import WORKFLOW_REGISTRY, WORKFLOW_STATUS_NOT_IMPLEMENTED
from local_life_agent.engine.workflow_runner import h_workflow_runner


def _single_shop_state(task_type: str, primary_task: str = "", current_shop: dict | None = None) -> dict:
    return {
        "trace_id": "trace_det_tool",
        "session_id": "session_det_tool",
        "turn_id": "turn_1",
        "task_type": task_type,
        "goal_type": task_type,
        "workflow_name": "deterministic_tool",
        "orchestration_pattern": "deterministic_tool",
        "orchestration_decision": OrchestrationDecision(
            orchestration_pattern="deterministic_tool",
            workflow_name="deterministic_tool",
            workflow_reason=f"route for {task_type}",
            task_complexity="low",
            requires_tool=True,
            requires_clarification=False,
            response_mode="tool_answer",
            confidence=0.9,
            missing_fields=[],
            next_action="run_workflow",
        ),
        "semantic_frame": {"task_type": task_type, "primary_task": primary_task, "confidence": 0.9},
        "current_shop": current_shop,
        "last_answer_order": [],
        "last_recommendation_list": [],
        "comparison_targets": [],
        "event_log": [],
    }


def test_registry_entry_for_deterministic_tool_is_real_callable():
    registration = WORKFLOW_REGISTRY.lookup("deterministic_tool")
    assert registration.status != WORKFLOW_STATUS_NOT_IMPLEMENTED
    assert registration.entry_node is not None


def test_shop_status_uses_open_status_tool():
    from local_life_agent.engine.workflows.deterministic_tool_workflow import run_deterministic_tool_workflow

    calls: list[tuple[str, dict]] = []

    def fake_dispatch(tool_name: str, args: dict) -> dict:
        calls.append((tool_name, dict(args)))
        return {
            "success": True,
            "result_status": "ok",
            "data": {"is_open": True},
            "error_code": "",
            "error_message": "",
        }

    state = _single_shop_state("shop_status", "shop_status", {"shop_id": "900001", "shop_name": "测试店"})
    result = run_deterministic_tool_workflow(state, dispatch_tool_call=fake_dispatch)

    assert calls[0][0] == "check_open_status"
    assert result["workflow_name"] == "deterministic_tool"
    assert result["workflow_run_status"] in {"dispatched", "success", "completed"}
    assert result["final_response"]


def test_missing_target_falls_back_without_tool_call():
    from local_life_agent.engine.workflows.deterministic_tool_workflow import run_deterministic_tool_workflow

    calls: list[str] = []

    def fake_dispatch(tool_name: str, args: dict) -> dict:
        calls.append(tool_name)
        return {"success": True, "result_status": "ok", "data": {}}

    state = _single_shop_state("shop_distance", "distance_query", None)
    result = run_deterministic_tool_workflow(state, dispatch_tool_call=fake_dispatch)

    assert calls == []
    assert result["workflow_run_status"] in {"fallback", "clarify"}
    assert result["next_action"] in {"clarify", "fallback"}


def test_multi_target_does_not_pick_first_target():
    from local_life_agent.engine.workflows.deterministic_tool_workflow import run_deterministic_tool_workflow

    calls: list[str] = []

    def fake_dispatch(tool_name: str, args: dict) -> dict:
        calls.append(tool_name)
        return {"success": True, "result_status": "ok", "data": {}}

    state = _single_shop_state("shop_coupon", "coupon_query", None)
    state["reference_resolution"] = {"resolved_targets": [{"shop_id": "900001"}, {"shop_id": "900002"}]}
    result = run_deterministic_tool_workflow(state, dispatch_tool_call=fake_dispatch)

    assert calls == []
    assert result["workflow_run_status"] in {"fallback", "clarify"}


def test_second_shop_without_history_falls_back():
    from local_life_agent.engine.workflows.deterministic_tool_workflow import run_deterministic_tool_workflow

    calls: list[str] = []

    def fake_dispatch(tool_name: str, args: dict) -> dict:
        calls.append(tool_name)
        return {"success": True, "result_status": "ok", "data": {}}

    state = _single_shop_state("shop_distance", "distance_query", None)
    state["semantic_frame"]["deictic_references"] = ["第二家"]
    result = run_deterministic_tool_workflow(state, dispatch_tool_call=fake_dispatch)

    assert calls == []
    assert result["workflow_run_status"] in {"fallback", "clarify"}


def test_runner_dispatches_deterministic_tool():
    state = _single_shop_state("shop_price", "price_query", {"shop_id": "900001", "shop_name": "测试店"})
    state["workflow_name"] = "direct_response"
    state["orchestration_pattern"] = "direct_response"
    result = h_workflow_runner(state)
    assert result["workflow_name"] == "deterministic_tool"
    assert result["response_mode"] == "direct"
