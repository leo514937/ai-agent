from __future__ import annotations

import copy

import pytest

from local_life_agent.app import ChatRequest, _stream_chat_events
from local_life_agent.domain.schemas import ExecutionPlan, OrchestrationDecision
from local_life_agent.engine.workflow_registry import WORKFLOW_REGISTRY
from local_life_agent.engine.workflow_runner import h_workflow_runner
import local_life_agent.engine.workflow_runner as workflow_runner_module
from local_life_agent.engine.workflows.deterministic_tool_workflow import run_deterministic_tool_workflow
from local_life_agent.engine.workflows.exploration_planning_workflow import run_exploration_planning_workflow
import local_life_agent.engine.workflows.exploration_planning_workflow as exploration_workflow_module
import local_life_agent.tests.test_exploration_planning_workflow as exploration_tests
from local_life_agent.planning.evidence.evidence_builder import build_evidence
from local_life_agent.planning.evidence.evidence_cache import EvidenceCache
from local_life_agent.planning.evidence.facet_budget import FacetBudgetPlan, plan_facet_budget
from local_life_agent.planning.evidence.tool_batch_executor import ToolBatchExecutor
from local_life_agent.session.store import get_session_store
from local_life_agent.streaming.events import StreamEventEnvelope, make_final, make_status
from local_life_agent.streaming.preview_policy import can_emit_preview, contains_unverified_claim, sanitize_preview_text


def _fake_dispatch(tool_name: str, kwargs: dict[str, object]) -> dict[str, object]:
    call_id = str(kwargs.get("call_id", "") or "")
    shop_id = str(kwargs.get("shop_id", "") or "")
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
    if tool_name == "get_coupon_list":
        return {
            "call_id": call_id,
            "shop_id": shop_id,
            "tool_name": tool_name,
            "success": True,
            "result_status": "ok",
            "data": [{"shop_id": shop_id, "title": "满100减20"}],
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
            "data": {"shop_id": shop_id, "distance_km": 1.2, "eta_minutes": 12},
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
            "data": {"items": [{"shop_id": shop_id, "summary": "口碑不错"}]},
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


def test_status_event_does_not_mutate_workflow_state():
    state = {"workflow_name": "demo", "turn_id": "turn-1", "session_id": "session-1"}
    snapshot = copy.deepcopy(state)

    event = make_status("trace-1", "session-1", "turn-1", "running", stage="streaming")

    assert state == snapshot
    assert event.event_type.value == "status"
    assert event.payload["status"] == "running"
    assert event.payload["stage"] == "streaming"


def test_preview_policy_blocks_unverified_claims():
    text = "这家店有券，而且目前营业中。"
    assert contains_unverified_claim(text) is True
    assert can_emit_preview(text, verified=False) is False
    assert sanitize_preview_text(text, verified=False) == ""
    assert can_emit_preview(text, verified=True) is True
    assert sanitize_preview_text(text, verified=True) == text


def test_final_event_requires_verified_answer():
    with pytest.raises(Exception):
        StreamEventEnvelope.model_validate(
            {
                "event_type": "final",
                "trace_id": "trace-1",
                "session_id": "session-1",
                "turn_id": "turn-1",
                "payload": {"answer_text": "最终答案", "verified": False},
            }
        )

    event = make_final("trace-1", "session-1", "turn-1", "最终答案")
    assert event.payload["verified"] is True


def test_batch_executor_reduces_tool_calls_to_single_evidence_pack():
    executor = ToolBatchExecutor(call_fn=_fake_dispatch)
    tool_calls = [
        {
            "call_id": "call_1",
            "tool_name": "check_open_status",
            "args": {"shop_id": "shop-1"},
            "required": True,
            "facet": "open_status",
        },
        {
            "call_id": "call_2",
            "tool_name": "get_coupon_list",
            "args": {"shop_id": "shop-1"},
            "required": True,
            "facet": "coupon",
        },
    ]

    results = executor.execute(tool_calls)
    evidence, cache_meta = executor.build_evidence_pack(
        tool_results=results,
        resolved_target={"status": "RESOLVED", "resolved_shop": {"shop_id": "shop-1", "shop_name": "测试店"}},
        execution_plan=ExecutionPlan.model_validate(
            {
                "plan_id": "plan-1",
                "task_type": "single_shop_query",
                "tool_calls": tool_calls,
                "target_shop_ids": ["shop-1"],
            }
        ),
        cache_scope={"workflow": "p10", "session_id": "session-1", "turn_id": "turn-1"},
    )

    assert set(results) == {"call_1", "call_2"}
    assert evidence.tool_results
    assert evidence.evidence_cache_key
    assert cache_meta["cache_hit"] is False


def test_cache_reuse_is_scoped_and_traceable():
    cache = EvidenceCache()
    payload = {
        "tool_results": {
            "call_1": {
                "call_id": "call_1",
                "shop_id": "shop-1",
                "tool_name": "check_open_status",
                "success": True,
                "result_status": "ok",
                "data": {"shop_id": "shop-1", "open_status": "open"},
                "backend_source": "test",
            }
        },
        "resolved_target": {"status": "RESOLVED", "resolved_shop": {"shop_id": "shop-1", "shop_name": "测试店"}},
        "execution_plan": {
            "plan_id": "plan-1",
            "task_type": "single_shop_query",
            "tool_calls": [{"call_id": "call_1", "tool_name": "check_open_status", "facet": "open_status"}],
        },
        "recommendation_candidates": [],
        "comparison_targets": [],
    }
    first, first_meta = cache.get_or_build({"workflow": "p10", "trace_id": "trace-a"}, payload, lambda: {"answerable_facets": ["open_status"]})
    second, second_meta = cache.get_or_build({"workflow": "p10", "trace_id": "trace-a"}, payload, lambda: {"answerable_facets": ["open_status", "coupon"]})
    other_scope, other_meta = cache.get_or_build({"workflow": "p10", "trace_id": "trace-b"}, payload, lambda: {"answerable_facets": ["open_status"]})

    assert first_meta["cache_hit"] is False
    assert second_meta["cache_hit"] is True
    assert other_meta["cache_hit"] is False
    assert first["evidence_cache_key"] == second["evidence_cache_key"]
    assert first_meta["cache_key"] != other_meta["cache_key"]


def test_top_k_budget_limits_are_reflected_in_plans_and_evidence():
    plan = plan_facet_budget(
        candidates=[
            {"facet": "coupon", "source": "llm", "confidence": 1.0, "priority_group": "user_explicit"},
            {"facet": "open_status", "source": "llm", "confidence": 0.9, "priority_group": "user_explicit"},
            {"facet": "distance", "source": "llm", "confidence": 0.8, "priority_group": "experience"},
        ],
        validation_result=type("R", (), {"accepted_facets": ["coupon", "open_status", "distance"], "unsupported_facets": [], "rejected_facets": [], "rejection_reasons": {}})(),
        max_facets=2,
        max_tool_calls=2,
        total_cost_budget=2,
    )

    assert isinstance(plan, FacetBudgetPlan)
    assert plan.enrichment_top_k <= 2
    assert len(plan.selected_facets) <= 2


def test_deterministic_single_shop_multi_facet_batches_calls(monkeypatch):
    calls: list[str] = []

    def dispatch(tool_name: str, kwargs: dict[str, object]) -> dict[str, object]:
        calls.append(tool_name)
        return _fake_dispatch(tool_name, kwargs)

    state = {
        "trace_id": "trace-det-p10",
        "session_id": "session-det-p10",
        "turn_id": "turn-det-p10",
        "task_type": "shop_status",
        "goal_type": "shop_status",
        "workflow_name": "deterministic_tool",
        "orchestration_pattern": "deterministic_tool",
        "orchestration_decision": {
            "orchestration_pattern": "deterministic_tool",
            "workflow_name": "deterministic_tool",
            "workflow_reason": "p10 test",
            "task_complexity": "low",
            "requires_tool": True,
            "requires_clarification": False,
            "response_mode": "tool_answer",
            "confidence": 0.9,
            "missing_fields": [],
            "next_action": "run_workflow",
        },
        "semantic_frame": {
            "task_type": "shop_status",
            "primary_task": "shop_status",
            "facets": [
                {"name": "open_status"},
                {"name": "coupon"},
                {"name": "distance"},
            ],
        },
        "current_shop": {"shop_id": "shop-1", "shop_name": "测试店"},
        "user_context": {"lat": 39.9, "lng": 116.4},
        "event_log": [],
    }

    result = run_deterministic_tool_workflow(state, dispatch_tool_call=dispatch)

    assert "check_open_status" in calls
    assert "get_coupon_list" in calls
    assert "get_distance_eta" in calls
    assert result["tool_results"]
    assert result["stream_status"] == "completed"


def test_exploration_status_preview_stays_within_single_workflow_boundary(monkeypatch):
    calls = exploration_tests._install_success_dispatch(monkeypatch)
    monkeypatch.setattr(workflow_runner_module, "WORKFLOW_REGISTRY", WORKFLOW_REGISTRY)
    result = h_workflow_runner(
        {
            **exploration_tests._state("coffee_then_dinner", "先喝咖啡然后吃晚饭"),
            "workflow_name": "exploration_planning",
            "orchestration_pattern": "exploration_planning",
            "workflow_reason": "p10 exploration",
            "orchestration_decision": exploration_tests._decision("coffee_then_dinner"),
        }
    )

    assert result["workflow_run_status"] == "completed"
    assert result["workflow_callable"] == "run_exploration_planning_workflow"
    assert result["response_mode"] == "exploration_plan"
    assert result["stream_status"] == "completed"
    assert result["preview_text"]
    assert calls


def test_streaming_http_wrapper_emits_verified_final_and_preview(monkeypatch):
    def fake_run_agent_graph(message: str, session_id: str = "", trace_id: str = "", turn_id: str = ""):
        return type(
            "R",
            (),
            {
                "trace_id": trace_id or "trace-stream",
                "session_id": session_id or "session-stream",
                "answer_text": "最终答案",
                "cards": [],
                "debug": None,
            },
        )()

    monkeypatch.setattr("local_life_agent.app.run_agent_graph", fake_run_agent_graph)
    request = ChatRequest(session_id="session-stream", trace_id="trace-stream", turn_id="turn-stream", page="assistant", message="推荐附近火锅", response_mode="stream")
    stream = _stream_chat_events(request)
    body = "".join(list(stream))

    assert "event: trace_started" in body
    assert "event: final" in body
    assert '"verified": true' in body
