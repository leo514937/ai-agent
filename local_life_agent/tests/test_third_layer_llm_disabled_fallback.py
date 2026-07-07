from __future__ import annotations

from typing import Any

import pytest

from .. import config
from ..answer.generator import generate_answer


def test_llm_disabled_uses_deterministic_text(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("local_life_agent.config.ENABLE_LLM_VERBALIZER", False)
    answer = generate_answer(
        {"answer_type": "single_shop"},
        {"ranking_snapshot": {"shop_name": "川味轩(知春路店)"}},
        llm_client=lambda *args, **kwargs: {"ok": True, "content": {"natural_response": "should not use"}},
    )
    assert "无法生成自然语言回答" not in answer
    assert "川味轩" in answer or "信息" in answer


def test_llm_error_falls_back_to_deterministic_text(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("local_life_agent.config.ENABLE_LLM_VERBALIZER", True)

    def bad_client(*args, **kwargs):
        raise RuntimeError("boom")

    metadata: dict[str, Any] = {}
    answer = generate_answer(
        {"answer_type": "single_shop"},
        {"evidence_items": [{"shop_name": "川味轩(知春路店)", "facet": "open_status", "value": "open"}]},
        llm_client=bad_client,
        metadata_out=metadata,
    )
    assert "营业" in answer
    assert metadata["answer_source"] == "deterministic_single_shop"


def test_llm_empty_output_falls_back_to_deterministic_text(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("local_life_agent.config.ENABLE_LLM_VERBALIZER", True)

    def empty_client(*args, **kwargs):
        return {"ok": True, "content": {"natural_response": ""}, "confidence": 1.0}

    answer = generate_answer(
        {"answer_type": "single_shop"},
        {"evidence_items": [{"shop_name": "川味轩(知春路店)", "facet": "open_status", "value": "open"}]},
        llm_client=empty_client,
    )
    assert "营业" in answer


@pytest.mark.parametrize(
    "answer_plan,evidence,expected",
    [
        (
            {"answer_type": "recommendation"},
            {
                "ranking_snapshot": {
                    "ranked": [
                        {"shop_name": "川味轩(知春路店)", "reason": "评分更高"},
                        {"shop_name": "海底捞(牡丹园店)", "reason": "距离更近"},
                    ]
                }
            },
            ["川味轩(知春路店)", "海底捞(牡丹园店)"],
        ),
        (
            {"answer_type": "comparison"},
            {
                "comparison_matrix": {
                    "rows": [
                        {"shop_name": "川味轩(知春路店)", "rating": 4.9},
                        {"shop_name": "海底捞(牡丹园店)", "rating": 4.7},
                    ],
                    "dimension_winners": {"rating": [{"shop_name": "川味轩(知春路店)"}]},
                }
            },
            ["川味轩(知春路店)", "海底捞(牡丹园店)"],
        ),
        (
            {"answer_type": "exploration_plan"},
            {
                "exploration_stages": [
                    {"stage_type": "eat", "candidate_query": "先找正餐", "status": "ok"},
                    {"stage_type": "coffee", "candidate_query": "再找咖啡", "status": "partial"},
                ],
                "stage_queries": ["先找正餐", "再找咖啡"],
                "stage_statuses": ["ok", "partial"],
            },
            ["先找正餐", "再找咖啡"],
        ),
    ],
)
def test_llm_disabled_uses_deterministic_composer_for_non_single_shop(monkeypatch: pytest.MonkeyPatch, answer_plan, evidence, expected):
    monkeypatch.setattr("local_life_agent.config.ENABLE_LLM_VERBALIZER", False)
    answer = generate_answer(answer_plan, evidence, llm_client=lambda *args, **kwargs: {"ok": True, "content": {"natural_response": "should not use"}})
    if answer_plan["answer_type"] == "comparison":
        assert "对比" in answer
        assert "不完整" in answer or "当前" in answer
    elif answer_plan["answer_type"] == "recommendation":
        assert "推荐" in answer
    else:
        for item in expected:
            assert item in answer
