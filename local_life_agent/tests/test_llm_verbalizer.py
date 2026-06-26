from __future__ import annotations

from typing import Any
import pytest

from ..config import ENABLE_LLM_VERBALIZER
from ..domain.schemas import DecisionPlan
from ..answer.generator import generate_answer, _build_decision_plan
from ..answer.llm_verbalizer import verbalize_decision_plan, VerbalizerResponse


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
        
        # If validator is passed, validate
        val = kwargs.get("response_validator")
        payload = {"natural_response": content} if isinstance(content, str) else content
        if val:
            try:
                payload = val(payload)
            except Exception as e:
                return {
                    "ok": False,
                    "content": None,
                    "confidence": 0.0,
                    "error_code": "VALIDATION_ERROR",
                    "error_message": str(e),
                }
        return {
            "ok": True,
            "content": payload,
            "confidence": 0.95,
            "raw": "{}",
            "error_code": "",
            "error_message": "",
        }
    return _call


def test_verbalizer_disabled_by_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("local_life_agent.config.ENABLE_LLM_VERBALIZER", False)
    
    answer_plan = {"answer_type": "single_shop"}
    evidence = {
        "ranking_snapshot": {
            "status": "ok",
            "shop_name": "川味轩(知春路店)",
        }
    }
    
    # Even if we pass client, it should be ignored because ENABLE_LLM_VERBALIZER is False
    client = _mock_llm_client("自然语言回复")
    res = generate_answer(answer_plan, evidence, llm_client=client)
    assert res == "【LLM 服务未启用】无法生成自然语言回答。"


def test_verbalizer_success_natural(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("local_life_agent.config.ENABLE_LLM_VERBALIZER", True)
    
    answer_plan = {"answer_type": "single_shop"}
    evidence = {
        "ranking_snapshot": {
            "status": "ok",
            "shop_name": "川味轩(知春路店)",
        }
    }
    
    client = _mock_llm_client("川味轩(知春路店)的详细情况已帮您查明，这家店确实很赞。")
    res = generate_answer(answer_plan, evidence, llm_client=client)
    # No template fallback — LLM output is returned even when verifier flags issues,
    # with an appended trustworthiness warning note
    assert "川味轩(知春路店)的详细情况已帮您查明" in res


def test_verbalizer_failure_fallback(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("local_life_agent.config.ENABLE_LLM_VERBALIZER", True)
    
    answer_plan = {"answer_type": "single_shop"}
    evidence = {
        "ranking_snapshot": {
            "status": "ok",
            "shop_name": "川味轩(知春路店)",
        }
    }
    
    # LLM returns error — no template fallback, returns LLM error message
    client = _mock_llm_client("ERROR", ok=False)
    res = generate_answer(answer_plan, evidence, llm_client=client)
    assert "【LLM 出错】" in res
    assert "LLM 调用失败" in res


def test_verbalizer_exception_fallback(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("local_life_agent.config.ENABLE_LLM_VERBALIZER", True)
    
    answer_plan = {"answer_type": "single_shop"}
    evidence = {
        "ranking_snapshot": {
            "status": "ok",
            "shop_name": "川味轩(知春路店)",
        }
    }
    
    def bad_client(*args, **kwargs):
        raise RuntimeError("LLM crashed")
        
    res = generate_answer(answer_plan, evidence, llm_client=bad_client)
    assert "【LLM 出错】" in res
    assert "LLM crashed" in res


def test_verbalizer_unauthorized_shop_fallback(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("local_life_agent.config.ENABLE_LLM_VERBALIZER", True)
    
    answer_plan = {"answer_type": "single_shop"}
    evidence = {
        "ranking_snapshot": {
            "status": "ok",
            "shop_name": "川味轩(知春路店)",
        }
    }
    
    # LLM mentions "海底捞(牡丹园店)" which is a known shop but NOT in allowed targets
    client = _mock_llm_client("川味轩(知春路店)挺好，但海底捞(牡丹园店)更适合您。")
    res = generate_answer(answer_plan, evidence, llm_client=client)
    # No template fallback — LLM output is returned with verification warning note
    assert "川味轩(知春路店)挺好" in res
    assert "注意" in res


def test_verbalizer_forbidden_claim_fallback(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("local_life_agent.config.ENABLE_LLM_VERBALIZER", True)
    
    answer_plan = {
        "answer_type": "single_shop",
        "forbidden_claims": ["全场打一折"]
    }
    evidence = {
        "ranking_snapshot": {
            "status": "ok",
            "shop_name": "川味轩(知春路店)",
        }
    }
    
    # LLM mentions the forbidden claim
    client = _mock_llm_client("川味轩(知春路店)全场打一折哦！")
    res = generate_answer(answer_plan, evidence, llm_client=client)
    # No template fallback — LLM output is returned with verification warning note
    assert "川味轩(知春路店)全场打一折哦" in res
    assert "注意" in res


def test_verbalizer_omitted_targets_all_fallback(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("local_life_agent.config.ENABLE_LLM_VERBALIZER", True)
    
    answer_plan = {
        "answer_type": "comparison",
        "must_mention_unknowns": ["蜀香居(学院路店)"]
    }
    evidence = {
        "comparison_matrix": {
            "rows": [
                {"shop_name": "川味轩(知春路店)", "rating": 4.8, "shop_id": "shop_sc_05"},
                {"shop_name": "海底捞(牡丹园店)", "rating": 4.6, "shop_id": "shop_007"}
            ]
        }
    }
    
    # LLM claims it compared all shops, but蜀香居 was omitted
    client = _mock_llm_client("我已经对比了所有店，川味轩在评分上领先。")
    res = generate_answer(answer_plan, evidence, llm_client=client)
    # No template fallback — LLM output is returned with verification warning note
    assert "我已经对比了所有店" in res
    assert "注意" in res


def test_verbalizer_uncertainty_notes_fallback(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("local_life_agent.config.ENABLE_LLM_VERBALIZER", True)
    
    answer_plan = {
        "answer_type": "comparison"
    }
    evidence = {
        "comparison_matrix": {
            "rows": [
                {"shop_name": "川味轩(知春路店)", "rating": 4.8, "shop_id": "shop_sc_05", "coupon_status": "has_coupon"},
                {"shop_name": "海底捞(牡丹园店)", "rating": 4.6, "shop_id": "shop_007", "coupon_status": "unknown"}
            ],
            "uncertainty_notes": ["海底捞(牡丹园店)优惠暂时无法确认"]
        }
    }
    
    # LLM asserts negative certainty for uncertainty notes topic
    client = _mock_llm_client("川味轩有券，而海底捞没有券。")
    res = generate_answer(answer_plan, evidence, llm_client=client)
    # No template fallback — LLM output is returned with verification warning note
    assert "川味轩有券" in res
    assert "注意" in res


def test_recommendation_count_dynamic(monkeypatch: pytest.MonkeyPatch):
    # Template path removed — when LLM is disabled, returns error message
    monkeypatch.setattr("local_life_agent.config.ENABLE_LLM_VERBALIZER", False)

    answer_plan = {"answer_type": "recommendation"}
    
    evidence_2 = {
        "ranking_snapshot": {
            "ranked": [
                {"shop_name": "A", "shop_id": "s1"},
                {"shop_name": "B", "shop_id": "s2"}
            ]
        }
    }
    res_2 = generate_answer(answer_plan, evidence_2)
    assert res_2 == "【LLM 服务未启用】无法生成自然语言回答。"
    
    evidence_3 = {
        "ranking_snapshot": {
            "ranked": [
                {"shop_name": "A", "shop_id": "s1"},
                {"shop_name": "B", "shop_id": "s2"},
                {"shop_name": "C", "shop_id": "s3"}
            ]
        }
    }
    res_3 = generate_answer(answer_plan, evidence_3)
    assert res_3 == "【LLM 服务未启用】无法生成自然语言回答。"


def test_verbalizer_unknown_as_false_violation(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("local_life_agent.config.ENABLE_LLM_VERBALIZER", True)
    
    answer_plan = {"answer_type": "single_shop"}
    evidence = {
        "facet_results": [
            {"facet": "coupon", "required": True, "status": "unknown"}
        ],
        "ranking_snapshot": {
            "status": "ok",
            "shop_name": "川味轩(知春路店)",
            "shop_id": "shop_sc_05",
            "facet_statuses": {"coupon": "unknown"}
        }
    }
    
    # LLM says "没有券" which violates the unknown status check
    client = _mock_llm_client("川味轩(知春路店)没有券。")
    metadata_out = {}
    res = generate_answer(answer_plan, evidence, llm_client=client, metadata_out=metadata_out)
    
    # No template fallback — LLM output is returned with verification warning note
    # Violation must still be tracked in metadata
    assert "川味轩(知春路店)没有券" in res
    assert "注意" in res
    assert metadata_out.get("violation") is not None
    assert metadata_out.get("answer_verify_passed") is False
