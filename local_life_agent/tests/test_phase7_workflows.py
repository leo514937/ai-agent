from __future__ import annotations

import pytest

from local_life_agent.domain.schemas import OrchestrationDecision
from local_life_agent.engine.subgraphs.response_subgraph import h_response_subgraph
from local_life_agent.engine.workflow_runner import h_workflow_runner
from local_life_agent.engine.workflows.clarification_fallback_workflow import run_clarification_fallback_workflow
from local_life_agent.engine.workflows.direct_response_workflow import run_direct_response_workflow
from local_life_agent.target.clarification import build_pending_clarification


def _base_state(workflow_name: str, *, top_intent: str, task_type: str, raw_text: str) -> dict:
    return {
        "trace_id": f"trace_{workflow_name}",
        "session_id": "session_phase7",
        "turn_id": "turn_1",
        "top_intent": top_intent,
        "task_type": task_type,
        "workflow_name": workflow_name,
        "orchestration_pattern": workflow_name,
        "orchestration_decision": OrchestrationDecision(
            orchestration_pattern=workflow_name,
            workflow_name=workflow_name,
            workflow_reason=f"route for {task_type}",
            task_complexity="low" if workflow_name == "direct_response" else "medium",
            requires_tool=False,
            requires_clarification=workflow_name == "clarification_fallback",
            response_mode="direct_response" if workflow_name == "direct_response" else "clarify",
            confidence=0.9,
            missing_fields=[],
            next_action="run_workflow" if workflow_name == "direct_response" else "clarify",
        ),
        "semantic_frame": {"task_type": task_type, "primary_task": task_type, "confidence": 0.9},
        "raw_text": raw_text,
        "normalized_text": raw_text,
        "event_log": [],
    }


@pytest.mark.parametrize(
    ("top_intent", "task_type", "raw_text", "expected_fragment"),
    [
        ("chat", "chat", "你好", "你好"),
        ("capability", "capability", "你能做什么", "我可以帮你"),
        ("local_life", "recommendation", "我想退款，顺便推荐一下附近餐厅", "不支持"),
    ],
)
def test_direct_response_workflow_stays_template_only(top_intent: str, task_type: str, raw_text: str, expected_fragment: str):
    state = _base_state("direct_response", top_intent=top_intent, task_type=task_type, raw_text=raw_text)

    result = run_direct_response_workflow(state)

    assert result["workflow_name"] == "direct_response"
    assert result["workflow_run_status"] == "completed"
    assert result["response_mode"] == "direct_response"
    assert expected_fragment in result["draft_response"]
    assert result["response_directive"].answer_text == result["draft_response"]
    assert result["verifier_result"] == "pass"
    assert result["answer_verify_passed"] is True
    assert "tool_results" not in result
    assert "evidence_pack" not in result
    assert "last_recommendation_list" not in result
    assert "comparison_targets" not in result

    routed = h_response_subgraph(result)
    assert routed["response_route"] == "pass"
    assert expected_fragment in routed["final_response"]


@pytest.mark.parametrize(
    ("task_type", "expected_mode", "expected_fragment"),
    [
        ("ambiguous", "clarify", "请回复编号或店名"),
        ("missing_required_slot", "clarify", "完整店名"),
        ("tool_failure", "fallback", "暂时"),
        ("no_result", "fallback", "没有查到"),
    ],
)
def test_clarification_fallback_workflow_handles_clarify_and_fallback(task_type: str, expected_mode: str, expected_fragment: str):
    state = _base_state(
        "clarification_fallback",
        top_intent="local_life",
        task_type=task_type,
        raw_text="请帮我看看",
    )
    if task_type == "ambiguous":
        state["pending_clarification"] = build_pending_clarification(
            original_text="请帮我看看这家店",
            original_semantic_frame=state["semantic_frame"],
            original_task_type=task_type,
            candidate_targets=[
                {"shop_id": "101", "shop_name": "甲店", "address": "A路"},
                {"shop_id": "102", "shop_name": "乙店", "address": "B路"},
            ],
            reason="ambiguous",
            source_node="test",
        ).model_dump()

    result = run_clarification_fallback_workflow(state)

    assert result["workflow_name"] == "clarification_fallback"
    assert result["response_mode"] == expected_mode
    assert result["draft_response"]
    assert expected_fragment in result["draft_response"]
    assert result["response_directive"].answer_text == result["draft_response"]
    assert result["verifier_result"] == "pass"
    assert result["answer_verify_passed"] is True
    assert "tool_results" not in result
    assert "evidence_pack" not in result
    if expected_mode == "clarify":
        assert "pending_clarification" in result
    else:
        assert "pending_clarification" not in result

    routed = h_response_subgraph(result)
    assert routed["response_route"] in {"clarify_ready", "fallback_ready"}
    assert expected_fragment in routed["final_response"]


@pytest.mark.parametrize(
    ("state_kwargs", "expected_workflow", "expected_mode"),
    [
        (
            {"top_intent": "chat", "task_type": "chat", "raw_text": "你好"},
            "direct_response",
            "direct_response",
        ),
        (
            {"top_intent": "local_life", "task_type": "ambiguous", "raw_text": "这家店怎么样"},
            "clarification_fallback",
            "clarify",
        ),
    ],
)
def test_workflow_runner_dispatches_phase7_workflows(state_kwargs: dict[str, str], expected_workflow: str, expected_mode: str):
    state = _base_state(expected_workflow, **state_kwargs)

    result = h_workflow_runner(state)

    assert result["workflow_registered"] is True
    assert result["workflow_callable"] in {
        "run_direct_response_workflow",
        "run_clarification_fallback_workflow",
    }
    assert result["response_mode"] == expected_mode
    assert result["workflow_run_status"] in {"completed", "clarify", "fallback"}


def test_response_subgraph_treats_direct_response_as_pass_through():
    result = h_response_subgraph(
        {
            "trace_id": "trace_direct",
            "response_mode": "direct_response",
            "draft_response": "你好，我可以帮你查商家营业状态。",
            "response_directive": {
                "answer_text": "你好，我可以帮你查商家营业状态。",
                "answer_type": "general",
                "response_mode": "direct_response",
                "answer_source": "direct_response_workflow",
            },
            "event_log": [],
        }
    )

    assert result["response_route"] == "pass"
    assert "answer_plan" not in result
    assert result["final_response"] == "你好，我可以帮你查商家营业状态。"
    assert "verify_result" not in result
