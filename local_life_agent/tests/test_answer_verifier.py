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


def test_verify_answer_allows_required_open_status_success():
    evidence = {
        "facet_results": [
            {"facet": "open_status", "required": True, "status": "ok", "value": "open"},
        ],
        "evidence_items": [
            {
                "shop_name": "海底捞火锅(水晶城购物中心店)",
                "facet": "open_status",
                "value": "open",
            }
        ],
        "unknown_items": [],
        "forbidden_claims": [],
    }
    answer = "海底捞火锅(水晶城购物中心店)目前营业中。"

    result = verify_answer(answer, evidence, "single_shop_query")

    assert result["passed"] is True


def test_verify_answer_blocks_missing_required_open_status():
    evidence = {
        "facet_results": [
            {"facet": "open_status", "required": True, "status": "ok", "value": "open"},
        ],
        "evidence_items": [
            {
                "shop_name": "海底捞火锅(水晶城购物中心店)",
                "facet": "open_status",
                "value": "open",
            }
        ],
        "unknown_items": [],
        "forbidden_claims": [],
    }
    answer = "海底捞火锅(水晶城购物中心店)位置不错。"

    result = verify_answer(answer, evidence, "single_shop_query")

    assert result["passed"] is False
    assert any("open_status" in issue for issue in result["issues"])


def test_verify_answer_allows_unknown_distance_when_answer_is_uncertain():
    evidence = {
        "facet_results": [
            {
                "facet": "distance",
                "required": True,
                "status": "unknown",
                "value": None,
            }
        ],
        "evidence_items": [],
        "unknown_items": [
            {
                "shop_name": "海底捞火锅(水晶城购物中心店)",
                "facet": "distance",
                "value": None,
            }
        ],
        "forbidden_claims": [],
    }
    answer = "距离暂时无法确认。"

    result = verify_answer(answer, evidence, "single_shop_query")

    assert result["passed"] is True


def test_verify_answer_blocks_false_distance_claim_when_unknown():
    evidence = {
        "facet_results": [
            {
                "facet": "distance",
                "required": True,
                "status": "unknown",
                "value": None,
            }
        ],
        "evidence_items": [],
        "unknown_items": [
            {
                "shop_name": "海底捞火锅(水晶城购物中心店)",
                "facet": "distance",
                "value": None,
            }
        ],
        "forbidden_claims": [],
    }
    answer = "离我很近，几分钟就到。"

    result = verify_answer(answer, evidence, "single_shop_query")

    assert result["passed"] is False
    assert any("distance" in issue for issue in result["issues"])


def test_verify_answer_allows_coupon_empty_notice():
    evidence = {
        "facet_results": [
            {"facet": "coupon", "required": True, "status": "empty", "value": "empty"},
        ],
        "evidence_items": [
            {
                "shop_name": "海底捞火锅(水晶城购物中心店)",
                "facet": "coupon",
                "value": "empty",
            }
        ],
        "unknown_items": [],
        "forbidden_claims": [],
    }
    answer = "当前暂无可用券。"

    result = verify_answer(answer, evidence, "coupon_query")

    assert result["passed"] is True
