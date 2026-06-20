"""Focused contract tests for `answer/verifier.py`.

These tests cover the minimum verifier behavior required by todo/07 and
todo/08:
  - aligned answers pass
  - reordered rankings are rejected with `ranking_changed_by_llm`
  - forbidden claims are rejected
"""

from __future__ import annotations

from ..answer.verifier import verify_answer


def test_verify_answer_passes_for_aligned_ranking():
    evidence = {
        "ranking_snapshot": {
            "ranked": [
                {"shop_id": "shop_sc_05", "shop_name": "川味轩(知春路店)"},
                {"shop_id": "shop_sc_04", "shop_name": "张记家常菜(北邮店)"},
            ]
        },
        "forbidden_claims": [],
    }
    answer = "推荐顺序是川味轩(知春路店)在前，张记家常菜(北邮店)在后。"

    result = verify_answer(answer, evidence, "recommendation")

    assert result["passed"] is True
    assert result["issues"] == []


def test_verify_answer_blocks_reordered_ranking():
    evidence = {
        "ranking_snapshot": {
            "ranked": [
                {"shop_id": "shop_sc_05", "shop_name": "川味轩(知春路店)"},
                {"shop_id": "shop_sc_04", "shop_name": "张记家常菜(北邮店)"},
            ]
        },
        "forbidden_claims": [],
    }
    answer = "推荐顺序是张记家常菜(北邮店)在前，川味轩(知春路店)在后。"

    result = verify_answer(answer, evidence, "recommendation")

    assert result["passed"] is False
    assert "ranking_changed_by_llm" in result["issues"]
    assert result["suggested_fix"]


def test_verify_answer_blocks_forbidden_claim():
    evidence = {
        "ranking_snapshot": {
            "ranked": [
                {"shop_id": "shop_sc_05", "shop_name": "川味轩(知春路店)"},
            ]
        },
        "forbidden_claims": ["评分最高"],
    }
    answer = "这家评分最高，推荐川味轩(知春路店)。"

    result = verify_answer(answer, evidence, "recommendation")

    assert result["passed"] is False
    assert any("评分最高" in issue for issue in result["issues"])
