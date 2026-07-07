from __future__ import annotations

from local_life_agent.domain.state import SessionState
from local_life_agent.engine.subgraphs.orchestration_router_shadow import h_orchestration_router_shadow
from local_life_agent.planning import orchestration_router as orr
from local_life_agent.planning.orchestration_router import build_orchestration_decision, build_orchestration_shadow_patch
from local_life_agent.planning.plans.state_update_planner import plan_state_update


def test_orchestration_router_prefers_discovery_decision_for_recommendation():
    decision = build_orchestration_decision(
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

    assert decision.orchestration_pattern == "discovery_decision"
    assert decision.workflow_name == "discovery_decision"
    assert decision.requires_tool is True
    assert decision.requires_clarification is False
    assert decision.response_mode == "recommendation"
    assert decision.next_action == "run_workflow"


def test_orchestration_router_prefers_deterministic_tool_for_single_shop_query():
    decision = build_orchestration_decision(
        {
            "top_intent": "local_life",
            "task_type": "single_shop_query",
            "semantic_frame": {"confidence": 0.84, "primary_task": "shop_coupon"},
            "current_shop": {"shop_id": "shop_1", "shop_name": "测试店"},
            "pending_clarification": None,
            "raw_text": "这家店有券吗",
        }
    )

    assert decision.orchestration_pattern == "deterministic_tool"
    assert decision.workflow_name == "deterministic_tool"
    assert decision.requires_tool is True
    assert decision.requires_clarification is False
    assert decision.response_mode == "tool_answer"


def test_orchestration_router_prefers_exploration_planning_for_trip_plan():
    decision = build_orchestration_decision(
        {
            "top_intent": "local_life",
            "task_type": "local_trip_plan",
            "semantic_frame": {"confidence": 0.61},
            "pending_clarification": None,
            "raw_text": "周末来一趟本地两日游",
        }
    )

    assert decision.orchestration_pattern == "exploration_planning"
    assert decision.workflow_name == "exploration_planning"
    assert decision.requires_tool is True
    assert decision.response_mode == "exploration_plan"


def test_orchestration_router_prefers_complex_orchestrator_for_super_complex_tasks():
    decision = build_orchestration_decision(
        {
            "top_intent": "local_life",
            "task_type": "super_complex",
            "semantic_frame": {"confidence": 0.55, "task_complexity": "super_complex", "workflow_hint": "complex_orchestrator_workflow"},
            "pending_clarification": None,
            "raw_text": "请帮我做一个跨多个阶段的复杂本地生活规划",
        }
    )

    assert decision.orchestration_pattern == "complex_orchestrator_workflow"
    assert decision.workflow_name == "complex_orchestrator_workflow"
    assert decision.task_complexity == "super_complex"
    assert decision.requires_tool is True
    assert decision.response_mode == "exploration_plan"


def test_orchestration_router_falls_back_when_single_shop_anchor_missing():
    state = {
        "top_intent": "local_life",
        "task_type": "single_shop_query",
        "semantic_frame": {"confidence": 0.64},
        "current_shop": None,
        "pending_clarification": None,
        "raw_text": "这家店营业时间怎么样",
    }

    assert orr.normalize_route_task(state) == "missing_required_slot"
    assert "current_shop" in orr._build_missing_fields(state, "missing_required_slot")
    assert "pending_clarification" in orr._build_missing_fields(state, "missing_required_slot")


def test_orchestration_router_forbidden_scope_uses_direct_response():
    decision = build_orchestration_decision(
        {
            "top_intent": "local_life",
            "task_type": "recommendation",
            "semantic_frame": {"confidence": 0.8},
            "raw_text": "我想退款，顺便推荐一下附近餐厅",
        }
    )

    assert decision.orchestration_pattern == "direct_response"
    assert decision.workflow_name == "direct_response"
    assert decision.requires_tool is False
    assert decision.requires_clarification is False
    assert decision.response_mode == "direct_response"


def test_orchestration_shadow_patch_uses_serializable_model():
    patch = build_orchestration_shadow_patch(
        {
            "top_intent": "local_life",
            "task_type": "comparison",
            "semantic_frame": {
                "confidence": 0.91,
                "comparison_intent": True,
                "comparison_structure": "multi_target",
            },
            "comparison_targets": [{"shop_id": "shop_1"}, {"shop_id": "shop_2"}],
            "raw_text": "比较这两家店",
        }
    )

    assert "orchestration_decision" in patch
    assert patch["orchestration_decision"].model_dump()["workflow_name"] == "discovery_decision"
    assert patch["router_policy_decision"]["workflow_name"] == "discovery_decision"
    assert patch["workflow_candidate_reason"]
    assert isinstance(patch["rule_pattern_signals"], list)


def test_orchestration_shadow_node_is_independent_from_planning():
    result = h_orchestration_router_shadow(
        {
            "trace_id": "trace_shadow",
            "top_intent": "local_life",
            "task_type": "recommendation",
            "semantic_frame": {"task_type": "recommendation", "confidence": 0.86},
            "raw_text": "附近推荐火锅",
            "session_state": SessionState(),
            "event_log": [],
        }
    )

    decision = result.get("orchestration_decision")
    assert decision is not None
    assert decision.workflow_name == "discovery_decision"
    assert result["response_mode"] == "recommendation"
    assert "planning_route" not in result
    assert result["orchestration_pattern"] == "discovery_decision"


def test_orchestration_router_safe_fallback_on_exception(monkeypatch):
    def _boom(_state):
        raise RuntimeError("boom")

    monkeypatch.setattr(orr, "build_orchestration_decision", _boom)

    patch = orr.route_orchestration(
        {
            "top_intent": "local_life",
            "task_type": "recommendation",
            "semantic_frame": {"confidence": 0.82},
            "raw_text": "附近推荐火锅",
        }
    )

    assert patch["orchestration_error_code"] == "ORCHESTRATION_ROUTER_EXCEPTION"
    assert patch["workflow_name"] == "clarification_fallback"
    assert patch["requires_clarification"] is True
    assert patch["response_mode"] == "clarify"
    assert "boom" in patch["orchestration_error_message"]


def test_session_state_and_state_update_ignore_orchestration_shadow_fields():
    session_state = SessionState(
        orchestration_decision={"workflow_name": "discovery_decision", "response_mode": "recommendation"}
    )
    assert not hasattr(session_state, "orchestration_decision")

    update = plan_state_update(
        {
            "task_type": "recommendation",
            "resolved_target": None,
            "current_shop": None,
            "orchestration_decision": {"workflow_name": "discovery_decision"},
        },
        task_type="recommendation",
        resolve_shop_status="RESOLVED",
    )

    assert "orchestration_decision" not in update["set_fields"]
    assert "orchestration_decision" not in update["clear_fields"]
