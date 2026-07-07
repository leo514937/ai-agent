from __future__ import annotations

from typing import Any

from local_life_agent.answer.response_contract import ResponseContractV1
from local_life_agent.answer.response_directive import build_response_directive
from local_life_agent.domain.schemas import ExecutionPlan
from local_life_agent.planning.evidence.stage_tool_executor import StageToolExecutor
from local_life_agent.planning.policies.ranking_policy import ExpandSearchPolicy, rank_candidates


def test_response_contract_v1_is_serializable():
    directive = build_response_directive(
        answer_text="海底捞当前营业中。",
        answer_type="single_shop",
        response_mode="answer",
        trace_id="trace_1",
        fallback_reason="",
        preview_text="海底捞当前营业中。",
        answer_source="deterministic_composer",
    )

    contract = ResponseContractV1.from_response_directive(
        directive,
        verifier_result="pass",
        fallback_reason="",
        uncertainty_notices=["距离暂时无法确认"],
        metadata={"workflow_name": "single_shop_fact_workflow"},
    )

    dumped = contract.model_dump()
    assert dumped["answer_text"] == "海底捞当前营业中。"
    assert dumped["response_mode"] == "answer"
    assert dumped["trace_id"] == "trace_1"
    assert dumped["uncertainty_notices"] == ["距离暂时无法确认"]


def test_expand_search_policy_preserves_constraints():
    policy = ExpandSearchPolicy(extra_candidate_limit=8)
    frame = {
        "hard_constraints": {"category": "火锅", "location": "知春路"},
        "filters": {"open_now": True},
        "ranking_signals": {"sort_by": ["total_score"]},
        "candidate_limit": 2,
    }

    expanded = policy.expand(frame)

    assert expanded["hard_constraints"] == {"category": "火锅", "location": "知春路"}
    assert expanded["filters"] == {"open_now": True}
    assert expanded["candidate_limit"] == 8


def test_rank_candidates_filters_closed_and_failed_candidates():
    candidates = [
        {"shop_id": "1", "shop_name": "A店", "category": "火锅", "rating": 4.9, "distance_km": 1.0, "open_status": "open"},
        {"shop_id": "2", "shop_name": "B店", "category": "火锅", "rating": 4.8, "distance_km": 0.5, "open_status": "closed"},
        {"shop_id": "3", "shop_name": "C店", "category": "火锅", "rating": 4.7, "distance_km": 1.5, "detail_failed": True},
    ]

    ranked = rank_candidates(candidates, {"hard_constraints": {"category": "火锅"}})

    assert [item["shop_id"] for item in ranked] == ["1"]
    assert ranked[0]["failed_constraints"] == []


def test_stage_tool_executor_dedupes_same_stage_calls():
    calls: list[tuple[str, dict[str, Any]]] = []

    def dispatch(tool_name: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        calls.append((tool_name, dict(kwargs)))
        return {
            "call_id": kwargs.get("call_id", ""),
            "shop_id": kwargs.get("shop_id", ""),
            "tool_name": tool_name,
            "success": True,
            "result_status": "ok",
            "data": {"shop_id": kwargs.get("shop_id", ""), "shop_name": "A店"},
            "error_code": "",
            "error_message": "",
            "source": "mock",
            "tool_backend": "mock",
            "backend_source": "mock",
            "degraded": False,
        }

    plan = ExecutionPlan.model_validate(
        {
            "plan_id": "plan_1",
            "task_type": "single_shop_query",
            "tool_calls": [
                {"call_id": "call_1", "tool_name": "get_shop_detail", "args": {"shop_id": "1"}, "facet": "detail"},
                {"call_id": "call_2", "tool_name": "get_shop_detail", "args": {"shop_id": "1"}, "facet": "detail"},
            ],
            "stages": [
                {"stage_id": "stage_1", "tool_names": ["get_shop_detail"], "depends_on": []},
            ],
        }
    )

    executor = StageToolExecutor(call_fn=dispatch)
    result = executor.execute(plan)

    assert len(calls) == 1
    assert "call_1" in result.results
    assert "call_2" in result.results
    assert result.results["call_2"]["tool_result_cache_hit"] is True
