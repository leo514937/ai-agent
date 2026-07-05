from __future__ import annotations

from local_life_agent.answer.answer_plan_builder import build_answer_plan
from local_life_agent.domain.decision import decision_to_answer_plan
from local_life_agent.domain.schemas import AnswerPlan, EvidencePack
from local_life_agent.planning.decision.decision_planner import plan_decision
from local_life_agent.planning.evidence.evidence_builder import build_evidence


def _build_single_shop_evidence() -> dict:
    execution_plan = {
        "task_type": "single_shop_query",
        "plan_id": "plan_1",
        "facets": [
            {"name": "coupon", "group": "deal", "required": True},
            {"name": "open_status", "group": "status", "required": True},
            {"name": "distance", "group": "location", "required": True},
        ],
        "tool_calls": [
            {"call_id": "call_coupon", "facet": "coupon", "required": True, "target_shop_id": "shop_1"},
            {"call_id": "call_open", "facet": "open_status", "required": True, "target_shop_id": "shop_1"},
            {"call_id": "call_distance", "facet": "distance", "required": True, "target_shop_id": "shop_1"},
        ],
    }
    tool_results = {
        "call_coupon": {
            "call_id": "call_coupon",
            "tool_name": "get_coupon_list",
            "shop_id": "shop_1",
            "result_status": "ok",
            "data": [{"title": "双人餐 88 元"}],
        },
        "call_open": {
            "call_id": "call_open",
            "tool_name": "check_open_status",
            "shop_id": "shop_1",
            "result_status": "unknown",
            "data": {},
        },
        "call_distance": {
            "call_id": "call_distance",
            "tool_name": "get_distance_eta",
            "shop_id": "shop_1",
            "result_status": "failed",
            "error_code": "TIMEOUT",
            "error_message": "timeout",
            "data": {},
        },
    }
    return build_evidence(
        tool_results=tool_results,
        resolved_target={
            "status": "RESOLVED",
            "resolved_shop": {"shop_id": "shop_1", "shop_name": "测试店"},
        },
        execution_plan=execution_plan,
        recommendation_candidates=[],
        comparison_targets=[],
    )


def test_evidence_pack_exposes_answerable_unknown_failed_facets():
    evidence = EvidencePack.model_validate(_build_single_shop_evidence())

    assert evidence.answerable_facets == ["coupon"]
    assert evidence.unknown_facets == ["open_status"]
    assert evidence.failed_facets == ["distance"]
    assert "coupon" in evidence.requested_facets
    assert evidence.facet_results
    assert evidence.facet_statuses["coupon"] == "grounded"
    assert evidence.facet_statuses["open_status"] == "unknown"
    assert evidence.facet_statuses["distance"] == "failed"
    assert evidence.grounded_facts["coupon_count"] == 1
    assert evidence.grounded_facts["open_status"] == "unknown" or evidence.grounded_facts["open_status"] == "open"


def test_decision_to_answer_plan_preserves_facet_triage_and_disclaimers():
    evidence = _build_single_shop_evidence()
    decision = plan_decision(
        goal_plan={"goal_type": "single_shop_query", "goal_summary": "这家有券吗"},
        evidence_pack=evidence,
    )

    assert decision.answerable_facets == ["coupon"]
    assert decision.unknown_facets == ["open_status"]
    assert decision.failed_facets == ["distance"]

    answer_plan_dict = decision_to_answer_plan(decision, evidence)
    answer_plan = AnswerPlan.model_validate(answer_plan_dict)

    assert answer_plan.answerable_facets == ["coupon"]
    assert answer_plan.unknown_facets == ["open_status"]
    assert answer_plan.failed_facets == ["distance"]
    assert answer_plan.required_disclaimers
    assert "open_status" in answer_plan.required_disclaimers[0]
    assert "distance" in answer_plan.required_disclaimers[1]
    assert answer_plan.facet_statuses["coupon"] == "grounded"
    assert answer_plan.facet_statuses["open_status"] == "unknown"
    assert answer_plan.facet_statuses["distance"] == "failed"


def test_build_answer_plan_includes_required_disclaimers_for_partial_evidence():
    evidence = _build_single_shop_evidence()
    answer_plan = build_answer_plan("single_shop_query", evidence)

    assert answer_plan["answerable_facets"] == ["coupon"]
    assert answer_plan["unknown_facets"] == ["open_status"]
    assert answer_plan["failed_facets"] == ["distance"]
    assert answer_plan["required_disclaimers"]
    assert "open_status" in answer_plan["required_disclaimers"][0]
    assert "distance" in answer_plan["required_disclaimers"][1]


def test_build_answer_plan_preserves_semantic_sidecar_fields():
    evidence = build_evidence(
        tool_results={
            "call_coupon": {
                "call_id": "call_coupon",
                "tool_name": "get_coupon_list",
                "shop_id": "shop_1",
                "result_status": "ok",
                "data": [{"title": "双人餐 88 元"}],
            }
        },
        resolved_target={
            "status": "RESOLVED",
            "resolved_shop": {"shop_id": "shop_1", "shop_name": "测试店"},
        },
        execution_plan={
            "task_type": "single_shop_query",
            "plan_id": "plan_semantic",
            "facets": [{"name": "coupon", "group": "deal", "required": True}],
            "tool_calls": [{"call_id": "call_coupon", "facet": "coupon", "required": True, "target_shop_id": "shop_1"}],
        },
        recommendation_candidates=[],
        comparison_targets=[],
        semantic_frame={"scene": "date", "grounding_status": "grounded"},
        semantic_parse_source="real_llm",
        grounding_status="grounded",
        missing_slot_type="",
        exploration_stages=[{"stage_type": "eat", "candidate_query": "先吃饭"}],
        stage_queries=["先吃饭"],
        stage_evidence_requirements=[["coupon"]],
        stage_statuses=["ok"],
        scene="date",
        time="evening",
        location={"location_name": "五道口附近"},
    )

    answer_plan = build_answer_plan("single_shop_query", evidence)

    assert answer_plan["semantic_parse_source"] == "real_llm"
    assert answer_plan["grounding_status"] == "grounded"
    assert answer_plan["stage_statuses"] == ["ok"]
    assert answer_plan["scene"] == "date"
    assert answer_plan["location"]["location_name"] == "五道口附近"
    assert answer_plan["facet_statuses"]["coupon"] == "grounded"
    assert answer_plan["grounded_facts"]["coupon_count"] == 1
