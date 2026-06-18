from __future__ import annotations

from types import SimpleNamespace

import _bootstrap  # noqa: F401

from learning_agent_service.domain import AnswerComposeRequest
from learning_agent_service.local_life.answer_contract import AnswerContract as LocalLifeAnswerContract
from learning_agent_service.local_life.answer_linter import lint_answer
from learning_agent_service.tools.composer import (
    _sanitize_request_for_strict_natural,
    _strict_natural_answer_is_valid,
)


def _make_request(**overrides):
    payload = {
        "raw_query": "海底捞怎么样",
        "requested_output_style": None,
        "rag_result": None,
        "tool_result": None,
        "plan_summary": None,
        "memory_injection_plan": None,
        "entity_join_result": None,
        "answer_contract": None,
        "answer_depth_policy": None,
        "ranked_candidates": [],
        "facet_result_bundle": None,
        "answer_context": {},
        "routing_decision": None,
        "evidence_quality": None,
        "final_response_mode": "grounded_strict",
        "missing_slots": [],
        "clarification_slot": None,
        "allow_direct_response": False,
        "direct_response_kind": None,
        "history_summary": None,
        "stream_event_sink": None,
        "stream_event_meta": {},
    }
    payload.update(overrides)
    return AnswerComposeRequest(**payload)


def test_strict_natural_sanitizer_drops_history_and_free_form_context() -> None:
    request = _make_request(
        history_summary="上次说过这家店很火，别用这个当事实。",
        answer_context={
            "history_summary": "上次说过这家店很火，别用这个当事实。",
            "historySummary": "legacy summary",
            "client_context": {"shopName": "伪造店名"},
            "clientContext": {"shopName": "伪造店名"},
            "fallback_catalog": {"shop_name": "伪造店名"},
            "confirmed_slots": ["shop_id: 1001"],
            "current_shop": "海底捞",
            "scene": "约会",
        },
        ranked_candidates=[
            {"shop_id": 1001, "name": "海底捞", "source": "rag", "structured_features": {"score": "4.5"}},
            {"shop_id": 2002, "name": "兜底店", "source": "catalog", "structured_features": {"score": "5.0"}},
        ],
    )

    sanitized = _sanitize_request_for_strict_natural(request, "海底捞：评分 4.5，人均约 100 元。")

    assert sanitized.history_summary is None
    assert sanitized.answer_context["answer_branch"] == "strict_natural"
    assert sanitized.answer_context["fact_draft"] == "海底捞：评分 4.5，人均约 100 元。"
    assert sanitized.answer_context["confirmed_slots"] == ["shop_id: 1001"]
    assert "history_summary" not in sanitized.answer_context
    assert "historySummary" not in sanitized.answer_context
    assert "client_context" not in sanitized.answer_context
    assert "clientContext" not in sanitized.answer_context
    assert "fallback_catalog" not in sanitized.answer_context
    assert len(sanitized.ranked_candidates) == 1
    assert sanitized.ranked_candidates[0]["name"] == "海底捞"


def test_strict_natural_validator_rejects_unsupported_numeric_claim() -> None:
    local_contract = LocalLifeAnswerContract(
        allowed_facets=["environment", "taste", "service", "price", "shop_detail", "recommendation_reason"],
        forbidden_facets=[],
        answer_style="single_shop_review",
        allow_extra_context=True,
        evidence_policy="balanced",
    )
    ranked_candidates = [
        {"shop_id": 1001, "name": "海底捞", "structured_features": {"score": "4.5", "avg_price": "100", "distance_km": "1.0"}},
    ]
    evidence_claims = [
        {"shop_id": 1001, "claim": "环境安静，适合约会。", "metadata": {"shop_name": "海底捞"}},
    ]
    user_need = SimpleNamespace(raw_query="海底捞怎么样")
    draft_answer = "海底捞：评分 4.5，人均约 100 元，距离你约 1.0 公里。"

    assert _strict_natural_answer_is_valid(
        candidate_answer="海底捞：评分 4.8，人均约 100 元，距离你约 1.0 公里。",
        draft_answer=draft_answer,
        required_terms=["海底捞"],
        local_contract=local_contract,
        topic_name="海底捞",
        ranked_candidates=ranked_candidates,
        evidence_claims=evidence_claims,
        facet_bundle=None,
        user_need=user_need,
        answer_context={"answer_branch": "strict_natural", "fact_draft": draft_answer, "confirmed_slots": []},
    ) is False


def test_strict_natural_linter_blocks_untrusted_shop_mentions() -> None:
    local_contract = LocalLifeAnswerContract(
        allowed_facets=["environment", "taste", "service", "price", "shop_detail", "recommendation_reason"],
        forbidden_facets=[],
        answer_style="comparison",
        allow_recommendation=True,
        allow_extra_context=True,
        evidence_policy="balanced",
    )
    result = lint_answer(
        answer_text="别家店：环境不错，评分 4.5。",
        answer_contract=local_contract,
        topic_name="海底捞",
        ranked_candidates=[{"shop_id": 1001, "name": "海底捞", "structured_features": {"score": "4.5"}}],
        evidence_claims=[{"shop_id": 1001, "claim": "环境安静。"}],
        answer_context={"answer_branch": "strict_natural", "fact_draft": "海底捞：环境安静。"},
    )

    assert result.severity == "block"
    assert "unsupported_shop_name" in result.issues
