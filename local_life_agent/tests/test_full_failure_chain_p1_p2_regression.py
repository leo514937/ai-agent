from __future__ import annotations

from typing import Any

import pytest

from ..answer.verifier import verify_answer
from ..domain.candidate import GoalType, LocalLifeGoalDraft
from ..planning.evidence.evidence_review import review_evidence_with_llm
from ..planning.review_policy import NextAction
from ..semantic.intent_parser import parse_semantic_frame
from ..domain.enums import TaskType


def test_semantic_parser_retries_with_shorter_prompt_and_exposes_metadata():
    prompts: list[str] = []

    def backend(prompt, **kwargs):
        prompts.append(prompt)
        if len(prompts) == 1:
            return {
                "ok": False,
                "error_code": "LLM_ENUM_OUT_OF_RANGE",
                "error_message": "schema invalid",
                "raw": "{}",
                "llm_backend": "fake_llm",
            }
        return {
            "ok": True,
            "content": {
                "top_intent": "local_life",
                "task_type": "recommendation",
                "primary_task": "recommendation",
                "facets": [{"name": "coupon", "required": True}],
                "merchant_mentions": ["海底捞"],
                "brand_mentions": [],
                "branch_mentions": [],
                "hard_constraints": {},
                "soft_preferences": {},
                "ranking_signals": {},
                "follow_up": None,
                "confidence": 0.91,
                "need_context": False,
            },
            "raw": '{"top_intent":"local_life"}',
            "llm_backend": "fake_llm",
            "error_code": "",
            "error_message": "",
        }

    result = parse_semantic_frame(
        "推荐北京邮电大学附近的火锅或烧烤，要性价比高的",
        "local_life",
        llm_call=backend,
    )

    assert len(prompts) == 2
    assert prompts[1] != prompts[0]
    assert len(prompts[1]) < len(prompts[0])
    assert "只输出 JSON" in prompts[1]
    assert result["semantic_frame"] is not None
    assert result["semantic_frame"].task_type == TaskType.recommendation
    assert result["semantic_parse_mode"] == "repair_prompt"
    assert result["semantic_parse_retry_count"] == 1
    assert result["semantic_parse_attempts"] == 2
    assert result["schema_validation_result"]["parse_status"] == "repaired"


def test_evidence_review_with_llm_uses_compact_summary_and_no_internal_retry(monkeypatch: pytest.MonkeyPatch):
    goal = LocalLifeGoalDraft(goal_type=GoalType.SINGLE_SHOP_QUERY, required_facets=["coupon"])
    evidence_pack = {
        "facet_results": [
            {"facet": "coupon", "result_status": "unknown", "required": True, "shop_id": "shop_1", "shop_name": "示例店"}
        ],
        "tool_round_budget_remaining": 1,
        "replan_budget_remaining": 1,
        "retry_budget_remaining": 1,
        "grounding_status": "grounded",
    }
    captured: dict[str, Any] = {}

    def fake_invoke_structured_llm(**kwargs):
        captured.update(kwargs)
        return {
            "ok": True,
            "payload": {
                "stage": "evidence_review",
                "action": "replan_missing_facets",
                "next_action": NextAction.REPLAN_EVIDENCE,
                "can_degrade": False,
                "status": "partial_insufficient",
                "reason": "missing_facets: ['coupon']",
                "retryable_facets": ["coupon"],
                "missing_facets": ["coupon"],
                "unknown_facets": ["coupon"],
                "failed_facets": [],
                "answerable_facets": [],
                "required_ok": [],
                "required_empty": [],
                "required_unknown": ["coupon"],
                "required_failed": [],
                "optional_ok": [],
                "optional_empty": [],
                "optional_unknown": [],
                "optional_failed": [],
                "unknown_as_false_detected": False,
                "failed_as_empty_detected": False,
                "evidence_incomplete": True,
                "trace_payload": {},
                "review_source": "llm_evidence_review",
                "review_confidence": 0.82,
                "missing_evidence": ["coupon"],
                "unsafe_answer_risks": [],
                "recommended_next_action": "REPLAN_EVIDENCE",
                "tool_failures": [],
                "review_mode": "llm",
                "review_precheck_status": "partial_insufficient",
                "review_precheck_reason": "missing_facets: ['coupon']",
                "review_retry_count": 0,
                "candidate_count": 1,
                "evidence_count": 1,
            },
            "error_code": "",
            "error_message": "",
            "llm_backend": "fake_llm",
            "raw": "{}",
        }

    monkeypatch.setattr("local_life_agent.planning.evidence.evidence_review.invoke_structured_llm", fake_invoke_structured_llm)
    review, meta = review_evidence_with_llm(goal, evidence_pack, llm_call=None)

    assert review is not None
    assert review.review_mode == "llm"
    assert meta["review_mode"] == "llm"
    assert meta["candidate_count"] == 0
    assert meta["evidence_count"] == 1
    assert captured["max_retries"] == 0
    summary = captured["replacements"]["{{EVIDENCE_PACK}}"]
    assert summary["precheck"]["status"] == "partial_insufficient"
    assert summary["precheck"]["next_action"] == NextAction.REPLAN_EVIDENCE
    assert summary["evidence"]["candidate_count"] == 0
    assert summary["evidence"]["evidence_count"] == 1


def test_verify_answer_prefers_deterministic_path_for_simple_evidence(monkeypatch: pytest.MonkeyPatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("LLM verifier should not be called for simple evidence")

    monkeypatch.setattr("local_life_agent.answer.b2_mini_verifier.B2MiniVerifier.verify", boom)

    evidence = {
        "facet_results": [
            {"facet": "coupon", "required": True, "status": "empty", "value": "empty"},
        ],
        "evidence_items": [
            {
                "shop_name": "牡丹园小火锅",
                "facet": "coupon",
                "value": "empty",
            }
        ],
        "unknown_items": [],
        "forbidden_claims": [],
    }

    result = verify_answer("当前暂无可用券。", evidence, "coupon_query")

    assert result["passed"] is True
    assert result["issues"] == []
    assert result["verification_mode"] == "deterministic"
