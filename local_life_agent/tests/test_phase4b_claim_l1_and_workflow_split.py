from __future__ import annotations

from ..answer.composers import compose_deterministic_response
from ..answer.verifier import verify_answer
from ..domain.schemas import DecisionPlan, OrchestrationDecision
from ..engine.subgraphs.response_subgraph import _h_answer_verify
from ..engine.workflow_registry import WORKFLOW_REGISTRY, WorkflowRegistration, WorkflowRegistry
from ..engine.workflow_runner import h_workflow_runner
import local_life_agent.engine.workflow_runner as workflow_runner_module
from ..planning.orchestration_router import build_orchestration_decision


def test_claim_l1_verifier_exposes_structured_claims():
    evidence = {
        "ranking_snapshot": {
            "status": "ok",
            "ranked": [
                {"shop_id": "s1", "shop_name": "川味轩(知春路店)", "total_score": 98},
                {"shop_id": "s2", "shop_name": "海底捞(牡丹园店)", "total_score": 88},
            ],
        },
        "comparison_matrix": {
            "status": "ok",
            "rows": [
                {"shop_id": "s1", "shop_name": "川味轩(知春路店)"},
                {"shop_id": "s2", "shop_name": "海底捞(牡丹园店)"},
            ],
            "overall_ranked": [
                {"shop_id": "s1", "shop_name": "川味轩(知春路店)", "total_score": 98},
                {"shop_id": "s2", "shop_name": "海底捞(牡丹园店)", "total_score": 88},
            ],
            "dimension_winners": {
                "rating": [{"shop_id": "s1", "shop_name": "川味轩(知春路店)"}],
            },
        },
        "unknown_items": [{"shop_name": "海底捞(牡丹园店)", "facet": "coupon"}],
        "forbidden_claims": [],
    }

    result = verify_answer("推荐川味轩(知春路店)更合适。", evidence, "recommendation")

    assert result["claim_extractor"] == "l1_structured"
    assert result["expected_claims"]
    assert any(claim["claim_type"] == "recommendation_rank" for claim in result["expected_claims"])
    assert not any(claim["claim_type"] == "comparison_winner" for claim in result["expected_claims"])
    assert any(claim["claim_type"] == "unknown_notice" for claim in result["expected_claims"])


def test_claim_l1_verifier_marks_reordered_comparison_winner():
    evidence = {
        "comparison_matrix": {
            "status": "ok",
            "rows": [
                {"shop_id": "s1", "shop_name": "川味轩(知春路店)"},
                {"shop_id": "s2", "shop_name": "海底捞(牡丹园店)"},
            ],
            "overall_ranked": [
                {"shop_id": "s1", "shop_name": "川味轩(知春路店)", "total_score": 98},
                {"shop_id": "s2", "shop_name": "海底捞(牡丹园店)", "total_score": 88},
            ],
            "dimension_winners": {
                "rating": [{"shop_id": "s1", "shop_name": "川味轩(知春路店)"}],
            },
        },
        "ranking_snapshot": {
            "status": "ok",
            "ranked": [
                {"shop_id": "s1", "shop_name": "川味轩(知春路店)", "total_score": 98},
                {"shop_id": "s2", "shop_name": "海底捞(牡丹园店)", "total_score": 88},
            ],
        },
        "forbidden_claims": [],
    }

    result = verify_answer("对比川味轩(知春路店)和海底捞(牡丹园店)：海底捞(牡丹园店)更适合。", evidence, "comparison")

    assert result["passed"] is False
    assert any(issue in {"unsupported_comparison_winner", "ranking_changed_by_llm"} for issue in result["issues"])
    comparison_claims = [claim for claim in result["claim_results"] if claim["claim_type"] == "comparison_winner"]
    assert comparison_claims
    assert any(claim["status"] != "supported" for claim in comparison_claims)


def test_claim_l2_backfills_composer_text_spans():
    plan = DecisionPlan(
        answer_type="recommendation",
        selected_targets=[
            {"shop_id": "s1", "shop_name": "川味轩(知春路店)", "total_score": 98},
            {"shop_id": "s2", "shop_name": "海底捞(牡丹园店)", "total_score": 88},
        ],
        overall_ranking=[
            {"shop_id": "s1", "shop_name": "川味轩(知春路店)", "total_score": 98},
            {"shop_id": "s2", "shop_name": "海底捞(牡丹园店)", "total_score": 88},
        ],
    )
    directive = compose_deterministic_response(plan)
    evidence = {
        "ranking_snapshot": {
            "status": "ok",
            "ranked": [
                {"shop_id": "s1", "shop_name": "川味轩(知春路店)", "total_score": 98},
                {"shop_id": "s2", "shop_name": "海底捞(牡丹园店)", "total_score": 88},
            ],
        },
        "forbidden_claims": [],
    }

    result = verify_answer(directive.answer_text, evidence, "recommendation", answer_source="deterministic_composer")

    first_rank = next(claim for claim in result["claim_results"] if claim["claim_id"] == "recommendation_rank_1")
    assert first_rank["status"] == "supported"
    assert first_rank["span_text"] == "川味轩(知春路店)"
    assert first_rank["span_start"] >= 0
    assert first_rank["span_end"] > first_rank["span_start"]
    assert first_rank["span_confidence"] == "high"
    assert first_rank["claim_span_level"] == "l2_text_span"


def test_claim_l2_uncertain_span_is_low_confidence():
    evidence = {
        "ranking_snapshot": {
            "status": "ok",
            "ranked": [
                {"shop_id": "s1", "shop_name": "川味轩(知春路店)", "total_score": 98},
            ],
        },
        "forbidden_claims": [],
    }

    result = verify_answer("第一家更合适。", evidence, "recommendation", answer_source="deterministic_composer")

    first_rank = next(claim for claim in result["claim_results"] if claim["claim_id"] == "recommendation_rank_1")
    assert first_rank["span_confidence"] == "low"
    assert first_rank["span_start"] == -1


def test_claim_l3_llm_structured_claims_do_not_override_evidence():
    evidence = {
        "comparison_matrix": {
            "status": "ok",
            "rows": [
                {"shop_id": "s1", "shop_name": "川味轩(知春路店)"},
                {"shop_id": "s2", "shop_name": "海底捞(牡丹园店)"},
            ],
            "overall_ranked": [
                {"shop_id": "s1", "shop_name": "川味轩(知春路店)", "total_score": 98},
                {"shop_id": "s2", "shop_name": "海底捞(牡丹园店)", "total_score": 88},
            ],
            "statistical_winner": {"shop_id": "s1", "shop_name": "川味轩(知春路店)", "reason": "综合分更高"},
        },
        "forbidden_claims": [],
    }
    extracted_claims = [
        {
            "claim_type": "comparison_winner",
            "text": "海底捞(牡丹园店)整体胜出",
            "shop_id": "s2",
            "shop_name": "海底捞(牡丹园店)",
        }
    ]

    result = verify_answer(
        "综合来看，海底捞(牡丹园店)整体胜出。",
        evidence,
        "comparison",
        answer_source="llm_verbalizer",
        extracted_claims=extracted_claims,
    )

    assert result["passed"] is False
    assert result["claim_extractor"] == "l3_structured_llm"
    assert "unsupported_structured_claim" in result["issues"]
    assert any("海底捞(牡丹园店)整体胜出" in claim for claim in result["unsupported_claims"])


def test_unsupported_l3_claim_enters_rewrite_instruction():
    evidence = {
        "comparison_matrix": {
            "status": "ok",
            "rows": [
                {"shop_id": "s1", "shop_name": "川味轩(知春路店)"},
                {"shop_id": "s2", "shop_name": "海底捞(牡丹园店)"},
            ],
            "overall_ranked": [
                {"shop_id": "s1", "shop_name": "川味轩(知春路店)", "total_score": 98},
                {"shop_id": "s2", "shop_name": "海底捞(牡丹园店)", "total_score": 88},
            ],
            "statistical_winner": {"shop_id": "s1", "shop_name": "川味轩(知春路店)"},
        },
        "forbidden_claims": [],
    }
    patch = _h_answer_verify(
        {
            "draft_response": "综合来看，海底捞(牡丹园店)整体胜出。",
            "evidence_pack": evidence,
            "execution_plan": {"task_type": "comparison"},
            "answer_source": "llm_verbalizer",
            "llm_structured_claims": [
                {
                    "claim_type": "comparison_winner",
                    "text": "海底捞(牡丹园店)整体胜出",
                    "shop_id": "s2",
                    "shop_name": "海底捞(牡丹园店)",
                }
            ],
            "rewrite_count": 0,
            "rewrite_limit": 1,
        }
    )

    assert patch["verify_result"] == "rewrite_needed"
    assert "unsupported_structured_claim" in patch["answer_verify_violations"]
    assert "海底捞(牡丹园店)整体胜出" in patch["rewrite_instruction"].unsupported_claims


def test_recommendation_and_comparison_workflow_names_are_split():
    recommendation = build_orchestration_decision(
        {
            "raw_text": "附近推荐火锅",
            "semantic_frame": {
                "task_type": "recommendation",
                "comparison_intent": False,
                "category": "火锅",
                "ranking_signals": ["口碑", "距离"],
            },
        }
    )
    comparison = build_orchestration_decision(
        {
            "raw_text": "帮我比较川味轩和海底捞",
            "semantic_frame": {
                "task_type": "comparison",
                "comparison_intent": True,
                "comparison_targets": ["川味轩", "海底捞"],
                "merchant_mentions": ["川味轩", "海底捞"],
            },
        }
    )

    assert recommendation.workflow_name == "discovery_decision"
    assert comparison.workflow_name == "discovery_decision"
    assert recommendation.response_mode == "recommendation"
    assert comparison.response_mode == "comparison"
    assert WORKFLOW_REGISTRY.lookup("recommendation_decision_workflow").workflow_name == "recommendation_decision_workflow"
    assert WORKFLOW_REGISTRY.lookup("comparison_decision_workflow").workflow_name == "comparison_decision_workflow"
    assert WORKFLOW_REGISTRY.lookup("discovery_decision").entry_node == "planning_subgraph"
    assert WORKFLOW_REGISTRY.lookup("recommendation_decision_workflow").entry_node == "planning_subgraph"
    assert WORKFLOW_REGISTRY.lookup("comparison_decision_workflow").entry_node == "planning_subgraph"


def test_workflow_runner_uses_split_entry_names(monkeypatch):
    calls: list[str] = []

    def recommendation_handler(state, decision):
        calls.append(decision.workflow_name)
        return {
            "workflow_name": "recommendation_decision_workflow",
            "workflow_run_status": "dispatched",
            "workflow_runner_reason": "recommendation dispatch",
            "workflow_started_at": "2026-07-01T00:00:00Z",
            "workflow_finished_at": "2026-07-01T00:00:00Z",
            "workflow_callable": "recommendation_handler",
            "workflow_registered": True,
        }

    registry = WorkflowRegistry()
    registry.register(
        WorkflowRegistration(
            workflow_name="recommendation_decision_workflow",
            handler=recommendation_handler,
            status="registered",
            entry_node="planning_subgraph",
        )
    )
    monkeypatch.setattr(workflow_runner_module, "WORKFLOW_REGISTRY", registry)

    result = h_workflow_runner(
        {
            "trace_id": "trace_split",
            "task_type": "recommendation",
            "workflow_name": "discovery_decision",
            "workflow_entry_name": "recommendation_decision_workflow",
            "orchestration_pattern": "discovery_decision",
            "response_mode": "recommendation",
            "orchestration_decision": OrchestrationDecision(
                orchestration_pattern="discovery_decision",
                workflow_name="discovery_decision",
                workflow_entry_name="recommendation_decision_workflow",
                workflow_reason="recommendation route",
                task_complexity="medium",
                requires_tool=True,
                requires_clarification=False,
                response_mode="recommendation",
                confidence=0.91,
                missing_fields=[],
                next_action="run_workflow",
            ),
            "event_log": [],
        }
    )

    assert calls == ["discovery_decision"]
    assert result["workflow_name"] == "recommendation_decision_workflow"
    assert result["workflow_entry_name"] == "recommendation_decision_workflow"
    assert result["workflow_callable"] == "recommendation_handler"
