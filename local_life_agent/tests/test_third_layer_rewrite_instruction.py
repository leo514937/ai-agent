from __future__ import annotations

from ..answer.rewrite_instruction import RewriteInstruction
from ..domain.schemas import AnswerPlan
from ..engine.subgraphs.response_subgraph import _h_rewrite


def test_rewrite_instruction_serializes():
    instruction = RewriteInstruction.from_violation_codes(
        ["empty_evidence_or_draft", "unsupported_price"],
        fallback_mode="rewrite",
        tone="neutral",
        max_length=120,
    )
    payload = instruction.model_dump()
    assert "empty_evidence_or_draft" in payload["violation_codes"]
    assert payload["fallback_mode"] == "rewrite"
    assert payload["max_length"] == 120


def test_rewrite_instruction_from_verifier_report_keeps_claim_and_ranking_signals():
    report = {
        "violation": "ranking_changed_by_llm",
        "failure_code": "ranking_changed_by_llm",
        "violations": ["ranking_changed_by_llm"],
        "unsupported_claims": ["川味轩更好"],
        "false_fields": ["winner_shop_id"],
        "unknown_fields": ["distance"],
        "suggested_fix": "请严格按 evidence 中的排序输出。",
    }
    plan = AnswerPlan(
        answer_type="comparison",
        overall_ranking=[{"shop_name": "川味轩(知春路店)"}],
        forbidden_claims=["全场打一折"],
        required_claims=[{"verbalization_hint": "川味轩(知春路店)"}],
    )

    instruction = RewriteInstruction.from_verifier_report(report, plan=plan, fallback_mode="rewrite")

    assert "ranking_changed_by_llm" in instruction.violation_codes
    assert "川味轩更好" in instruction.unsupported_claims
    assert "winner_shop_id" in instruction.contradicted_claims
    assert any("不要重排" in item for item in instruction.required_additions)
    assert "川味轩(知春路店)" in instruction.claims_to_keep


def test_h_rewrite_consumes_instruction_and_sets_strategy():
    instruction = RewriteInstruction.from_violation_codes(["ranking_changed_by_llm"], fallback_mode="rewrite")
    patch = _h_rewrite(
        {
            "answer_plan": AnswerPlan(answer_type="comparison"),
            "rewrite_instruction": instruction,
            "rewrite_count": 1,
            "rewrite_limit": 3,
            "draft_response": "草稿",
        }
    )

    assert patch["rewrite_count"] == 2
    assert patch["rewrite_mode"] == "deterministic_composer"
    assert patch["rewrite_strategy"] == "deterministic_composer"
    assert patch["rewrite_route"] == "deterministic_composer"


def test_h_rewrite_hits_trusted_fallback_at_limit():
    instruction = RewriteInstruction.from_violation_codes(["unsupported_price"], fallback_mode="rewrite")
    patch = _h_rewrite(
        {
            "answer_plan": AnswerPlan(answer_type="single_shop_query"),
            "rewrite_instruction": instruction,
            "rewrite_count": 2,
            "rewrite_limit": 2,
            "draft_response": "草稿",
        }
    )

    assert patch["rewrite_mode"] == "trusted_fallback"
    assert patch["rewrite_route"] == "trusted_fallback"
