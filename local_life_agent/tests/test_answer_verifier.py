"""Focused contract tests for `answer/verifier.py`.

These tests cover the minimum verifier behavior required by todo/07 and
todo/08:
  - aligned answers pass
  - reordered rankings are rejected with `ranking_changed_by_llm`
  - forbidden claims are rejected
"""

from __future__ import annotations

import pytest

from ..answer.verifier import verify_answer
from .fakes.verifier import fake_verifier_verify


@pytest.fixture(autouse=True)
def _fake_verifier(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("local_life_agent.answer.b2_mini_verifier.B2MiniVerifier.verify", fake_verifier_verify)


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
        "comparison_matrix": {
            "rows": [
                {"shop_id": "shop_sc_05", "shop_name": "川味轩(知春路店)"},
                {"shop_id": "shop_sc_04", "shop_name": "张记家常菜(北邮店)"},
            ],
            "overall_ranked": [
                {"shop_id": "shop_sc_05", "shop_name": "川味轩(知春路店)"},
                {"shop_id": "shop_sc_04", "shop_name": "张记家常菜(北邮店)"},
            ],
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


def test_verify_answer_blocks_shop_hallucination():
    evidence = {
        "ranking_snapshot": {
            "status": "ok",
            "shop_name": "川味轩(知春路店)",
        },
        "evidence_items": [{"shop_name": "川味轩(知春路店)"}],
        "forbidden_claims": [],
    }
    # Mentions "海底捞(牡丹园店)" which is known but not allowed in this turn
    answer = "为您推荐川味轩(知春路店)，您也可以去海底捞(牡丹园店)看看。"
    result = verify_answer(answer, evidence, "single_shop_query")
    assert result["passed"] is False
    assert "hallucinated_shop_name" in result["issues"]
    assert "shop_mismatch" in result["issues"]


def test_verify_answer_blocks_unknown_coupon_negative_claim():
    evidence = {
        "facet_results": [{"facet": "coupon", "status": "unknown", "required": True}],
        "evidence_items": [],
        "unknown_items": [{"shop_name": "川味轩(知春路店)", "facet": "coupon"}],
        "forbidden_claims": [],
    }
    answer = "川味轩(知春路店)没有优惠券。"
    result = verify_answer(answer, evidence, "coupon_query")
    assert result["passed"] is False
    assert "unknown_as_false" in result["issues"]
    assert "unsupported_coupon" in result["issues"]


def test_verify_answer_blocks_unknown_open_status_claim():
    evidence = {
        "facet_results": [{"facet": "open_status", "status": "unknown", "required": True}],
        "evidence_items": [],
        "unknown_items": [{"shop_name": "川味轩(知春路店)", "facet": "open_status"}],
        "forbidden_claims": [],
    }
    answer = "川味轩(知春路店)现在不营业了。"
    result = verify_answer(answer, evidence, "open_status_query")
    assert result["passed"] is False
    assert "unknown_as_false" in result["issues"]
    assert "unsupported_open_status" in result["issues"]


def test_verify_answer_blocks_unsupported_distance():
    evidence = {
        "evidence_items": [
            {
                "shop_name": "川味轩(知春路店)",
                "facet": "distance",
                "value": {"distance_km": 1.5},
            }
        ],
        "forbidden_claims": [],
    }
    # Claims distance is 2.5km (binding error)
    answer = "川味轩(知春路店)离你大约2.5公里。"
    result = verify_answer(answer, evidence, "distance_query")
    assert result["passed"] is False
    assert "unsupported_distance" in result["issues"]


def test_verify_answer_blocks_unsupported_price():
    evidence = {
        "evidence_items": [
            {
                "shop_name": "川味轩(知春路店)",
                "facet": "avg_price",
                "value": 80,
            }
        ],
        "forbidden_claims": [],
    }
    # Claims average price is 120
    answer = "川味轩(知春路店)人均消费120元。"
    result = verify_answer(answer, evidence, "detail_query")
    assert result["passed"] is False
    assert "unsupported_price" in result["issues"]


def test_verify_answer_blocks_unsupported_rating():
    evidence = {
        "evidence_items": [
            {
                "shop_name": "川味轩(知春路店)",
                "facet": "rating",
                "value": 4.8,
            }
        ],
        "forbidden_claims": [],
    }
    # Claims rating is 4.2
    answer = "川味轩(知春路店)的评分为4.2分。"
    result = verify_answer(answer, evidence, "detail_query")
    assert result["passed"] is False
    assert "unsupported_rating" in result["issues"]


def test_verify_answer_blocks_omitted_targets_violation():
    evidence = {
        "ranking_snapshot": {
            "status": "ok",
            "shop_name": "川味轩(知春路店)",
        },
        "evidence_items": [{"shop_name": "川味轩(知春路店)"}],
        "unknown_items": [{"shop_name": "蜀香居(学院路店)"}],
        "forbidden_claims": [],
    }
    # Claims compared all, but 蜀香居 is omitted/unknown
    answer = "我已经对比了所有店，川味轩(知春路店)是营业的。"
    result = verify_answer(answer, evidence, "recommendation")
    assert result["passed"] is False
    assert "omitted_targets_violation" in result["issues"]
    assert "all_targets_claim_violation" in result["issues"]


def test_verify_answer_blocks_unsupported_comparison_winner():
    evidence = {
        "comparison_matrix": {
            "rows": [
                {"shop_name": "川味轩(知春路店)", "shop_id": "shop_sc_05", "distance_km": 1.2},
                {"shop_name": "海底捞(牡丹园店)", "shop_id": "shop_007", "distance_km": 2.5},
            ],
            "dimension_winners": {
                "distance": [{"shop_id": "shop_sc_05", "shop_name": "川味轩(知春路店)"}]
            }
        },
        "forbidden_claims": [],
    }
    # Claims B is closer
    answer = "对比川味轩(知春路店)和海底捞(牡丹园店)：海底捞(牡丹园店)距离更近。"
    result = verify_answer(answer, evidence, "comparison")
    assert result["passed"] is False
    assert any(issue in {"unsupported_comparison_winner", "unprovided_dimension_winner"} for issue in result["issues"])


def test_verify_answer_blocks_tool_failure_as_fact():
    evidence = {
        "facet_results": [{"facet": "coupon", "status": "failed", "required": True}],
        "evidence_items": [],
        "unknown_items": [{"shop_name": "川味轩(知春路店)", "facet": "coupon"}],
        "forbidden_claims": [],
    }
    answer = "川味轩(知春路店)没有优惠券。"
    result = verify_answer(answer, evidence, "coupon_query")
    assert result["passed"] is False
    assert "tool_failure_as_fact" in result["issues"]


def test_verify_answer_ignores_snapshot_as_facet_fallback():
    evidence = {
        "ranking_snapshot": {
            "status": "ok",
            "ranked": [
                {
                    "shop_name": "川味轩(知春路店)",
                    "coupon_status": "unknown",
                    "open_status": "unknown",
                }
            ],
        },
        "forbidden_claims": [],
    }
    answer = "优惠券情况暂时无法确认。"

    result = verify_answer(answer, evidence, "coupon_query")

    assert result["passed"] is True
    assert "unknown_as_false" not in result["issues"]

