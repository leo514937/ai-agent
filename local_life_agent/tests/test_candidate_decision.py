from __future__ import annotations

from typing import Any
import pytest
import json

from local_life_agent import config
from local_life_agent.domain.schemas import DecisionPlan
from local_life_agent.answer.candidate_decision import (
    CandidateItem,
    CandidateEvidence,
    CandidateEvaluation,
    CandidateDecisionPlan,
    CandidateEvidenceCollector,
    CandidateEvaluator,
    build_candidate_decision_plan,
    map_candidate_decision_plan_to_decision_plan,
)
from local_life_agent.answer.generator import generate_answer, _build_decision_plan


def _mock_llm_client(content: str | dict, ok: bool = True) -> Any:
    def _call(*args, **kwargs) -> dict:
        if not ok:
            return {
                "ok": False,
                "content": None,
                "confidence": 0.0,
                "error_code": "LLM_ERROR",
                "error_message": "LLM failed",
            }
        
        payload = {"natural_response": content} if isinstance(content, str) else content
        return {
            "ok": True,
            "content": payload,
            "confidence": 0.95,
            "raw": "{}",
            "error_code": "",
            "error_message": "",
        }
    return _call


def test_candidate_evidence_collector():
    collector = CandidateEvidenceCollector()
    tool_results = {
        "call_detail": {
            "tool_name": "get_shop_detail",
            "result_status": "ok",
            "shop_id": "shop_01",
            "data": {
                "shop_id": "shop_01",
                "shop_name": "川味轩",
                "rating": 4.5,
            }
        },
        "call_open": {
            "tool_name": "check_open_status",
            "result_status": "ok",
            "shop_id": "shop_01",
            "data": {
                "shop_id": "shop_01",
                "open_status": "open"
            }
        },
        "call_coupon": {
            "tool_name": "get_coupon_list",
            "result_status": "empty",
            "shop_id": "shop_01",
            "data": []
        },
        "call_distance": {
            "tool_name": "get_distance_eta",
            "result_status": "failed",
            "shop_id": "shop_01",
            "error_code": "ROUTE_FAILED"
        }
    }
    
    evidences = collector.collect(["shop_01"], tool_results)
    assert len(evidences) == 1
    ev = evidences[0]
    assert ev.shop_id == "shop_01"
    assert ev.detail["data"]["shop_name"] == "川味轩"
    assert ev.open_status["data"]["open_status"] == "open"
    assert ev.coupon["result_status"] == "empty"
    assert ev.distance["result_status"] == "failed"


def test_candidate_evaluator_recommendation():
    evaluator = CandidateEvaluator()
    
    # Detail ok, open status unknown, coupon unknown, distance ok
    evidence_1 = CandidateEvidence(
        shop_id="shop_01",
        detail={
            "tool_name": "get_shop_detail",
            "result_status": "ok",
            "shop_id": "shop_01",
            "data": {
                "shop_name": "川味轩",
                "category": "川菜",
                "tags": ["火锅"],
                "rating": 4.8,
            }
        },
        distance={
            "tool_name": "get_distance_eta",
            "result_status": "ok",
            "shop_id": "shop_01",
            "data": {
                "distance_km": 1.5,
                "eta_minutes": 15,
            }
        }
    )
    
    preferences = {
        "query_terms": ["川菜"],
        "scene_terms": ["聚餐"],
    }
    
    evaluations = evaluator.evaluate([evidence_1], "recommendation", preferences)
    assert len(evaluations) == 1
    eval_item = evaluations[0]
    assert eval_item.shop_id == "shop_01"
    assert eval_item.rank == 1
    assert "川味轩营业状态暂无法确认" in eval_item.uncertainty_notes
    assert "川味轩优惠暂无法确认" in eval_item.uncertainty_notes


def test_candidate_evaluator_comparison():
    evaluator = CandidateEvaluator()
    
    # shop_01: rating 4.8, distance 1.5, open, has coupons
    ev_1 = CandidateEvidence(
        shop_id="shop_01",
        detail={
            "tool_name": "get_shop_detail",
            "result_status": "ok",
            "data": {
                "shop_name": "川味轩",
                "rating": 4.8,
            }
        },
        open_status={
            "tool_name": "check_open_status",
            "result_status": "ok",
            "data": {
                "open_status": "open"
            }
        },
        coupon={
            "tool_name": "get_coupon_list",
            "result_status": "ok",
            "data": [{"title": "100减10"}]
        },
        distance={
            "tool_name": "get_distance_eta",
            "result_status": "ok",
            "data": {
                "distance_km": 1.5,
            }
        }
    )
    
    # shop_02: rating 4.0, distance 0.5, open, no coupons
    ev_2 = CandidateEvidence(
        shop_id="shop_02",
        detail={
            "tool_name": "get_shop_detail",
            "result_status": "ok",
            "data": {
                "shop_name": "海底捞",
                "rating": 4.0,
            }
        },
        open_status={
            "tool_name": "check_open_status",
            "result_status": "ok",
            "data": {
                "open_status": "open"
            }
        },
        coupon={
            "tool_name": "get_coupon_list",
            "result_status": "empty",
            "data": []
        },
        distance={
            "tool_name": "get_distance_eta",
            "result_status": "ok",
            "data": {
                "distance_km": 0.5,
            }
        }
    )
    
    evaluations = evaluator.evaluate([ev_1, ev_2], "comparison", {})
    assert len(evaluations) == 2
    
    # Sort by rank
    evaluations.sort(key=lambda x: x.rank)
    assert evaluations[0].shop_id == "shop_01"  # rating 4.8, overall score higher
    assert evaluations[1].shop_id == "shop_02"
    
    dim_winners = evaluations[0].dimension_winners
    assert "rating" in dim_winners
    assert dim_winners["rating"][0]["shop_id"] == "shop_01"
    assert "distance" in dim_winners
    assert dim_winners["distance"][0]["shop_id"] == "shop_02"
    assert "coupon" in dim_winners
    assert dim_winners["coupon"][0]["shop_id"] == "shop_01"
    # both open: so open_status has both or is open winner
    assert "open_status" in dim_winners
    assert len(dim_winners["open_status"]) == 2


def test_build_and_map_decision_plan():
    evaluator = CandidateEvaluator()
    ev_1 = CandidateEvidence(
        shop_id="shop_01",
        detail={
            "tool_name": "get_shop_detail",
            "result_status": "ok",
            "data": {
                "shop_name": "川味轩",
                "category": "川菜",
                "tags": ["川菜", "火锅"],
                "rating": 4.8,
            }
        },
        open_status={
            "tool_name": "check_open_status",
            "result_status": "ok",
            "data": {
                "open_status": "open"
            }
        },
        coupon={
            "tool_name": "get_coupon_list",
            "result_status": "ok",
            "data": [{"title": "100减10"}]
        },
        distance={
            "tool_name": "get_distance_eta",
            "result_status": "ok",
            "data": {
                "distance_km": 1.5,
                "eta_minutes": 15
            }
        }
    )
    
    evaluations = evaluator.evaluate([ev_1], "recommendation", {
        "query_terms": ["川菜"],
        "scene_terms": []
    })
    
    c_plan = build_candidate_decision_plan(
        decision_type="recommendation",
        user_goal="想吃川菜",
        location="北京邮电大学",
        evidences=[ev_1],
        evaluations=evaluations,
        forbidden_claims=["便宜"],
        must_mention_unknowns=["海底捞"],
    )
    
    assert c_plan.decision_type == "recommendation"
    assert c_plan.candidates[0].shop_name == "川味轩"
    assert "海底捞" in c_plan.must_mention_unknowns
    
    d_plan = map_candidate_decision_plan_to_decision_plan(c_plan)
    assert d_plan.answer_type == "recommendation"
    assert d_plan.selected_targets[0]["shop_id"] == "shop_01"
    assert d_plan.omitted_targets[0]["shop_name"] == "海底捞"
    assert d_plan.main_recommendation["shop_name"] == "川味轩"
    assert d_plan.forbidden_claims == ["便宜"]


def test_generator_unified_pipeline_recommendation(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "ENABLE_LLM_VERBALIZER", True)
    
    answer_plan = {
        "answer_type": "recommendation",
        "forbidden_claims": [],
        "must_mention_unknowns": [],
    }
    
    evidence = {
        "target_shop_ids": ["shop_01"],
        "tool_results": {
            "call_detail": {
                "tool_name": "get_shop_detail",
                "result_status": "ok",
                "shop_id": "shop_01",
                "data": {
                    "shop_id": "shop_01",
                    "shop_name": "川味轩",
                    "rating": 4.8,
                },
            }
        }
    }
    
    # Mock LLM verbalizer output
    client = _mock_llm_client("这是LLM润色后的推荐回复：推荐川味轩，评分4.8，营业中。")
    res = generate_answer(answer_plan, evidence, llm_client=client)
    assert "推荐川味轩" in res


def test_build_decision_plan_does_not_promote_snapshot_to_winner():
    answer_plan = {
        "answer_type": "recommendation",
    }
    evidence = {
        "ranking_snapshot": {
            "status": "ok",
            "ranked": [
                {
                    "shop_id": "shop_01",
                    "shop_name": "川味轩",
                    "rating": 4.8,
                    "distance_km": 1.2,
                    "open_status": "open",
                    "coupon_count": 1,
                }
            ]
        }
    }

    plan = _build_decision_plan(answer_plan, evidence)

    assert plan.selected_targets == []
    assert plan.main_recommendation is None
    assert plan.overall_ranking == []


def test_generator_unified_pipeline_comparison(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "ENABLE_LLM_VERBALIZER", True)
    
    answer_plan = {
        "answer_type": "comparison",
        "forbidden_claims": [],
        "must_mention_unknowns": [],
    }
    
    evidence = {
        "comparison_matrix": {
            "status": "ok",
            "rows": [
                {
                    "shop_id": "shop_01",
                    "shop_name": "川味轩",
                    "rating": 4.8,
                    "distance_km": 1.2,
                    "open_status": "open",
                    "coupon_status": "has_coupon",
                    "coupon_titles": ["优惠"],
                },
                {
                    "shop_id": "shop_02",
                    "shop_name": "海底捞",
                    "rating": 4.2,
                    "distance_km": 0.5,
                    "open_status": "open",
                    "coupon_status": "empty",
                    "coupon_titles": [],
                }
            ],
            "overall_ranked": [
                {"shop_id": "shop_01", "shop_name": "川味轩", "overall_score": 0.8},
                {"shop_id": "shop_02", "shop_name": "海底捞", "overall_score": 0.6},
            ],
            "dimension_winners": {
                "rating": [{"shop_id": "shop_01", "shop_name": "川味轩"}],
                "distance": [{"shop_id": "shop_02", "shop_name": "海底捞"}],
            }
        }
    }
    
    client = _mock_llm_client("对比川味轩和海底捞：川味轩评分更高，海底捞更近。")
    metadata_out = {}
    res = generate_answer(answer_plan, evidence, llm_client=client, metadata_out=metadata_out)
    
    assert "对比" in res
    assert metadata_out["decision_type"] == "comparison"
    assert metadata_out["candidate_count"] == 2
