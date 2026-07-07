from __future__ import annotations

from local_life_agent.answer.response_contract import ResponseContractV1, ResponseContractV2
from local_life_agent.answer.response_directive import build_response_directive
from local_life_agent.engine.subgraphs.response_subgraph import _h_final_response


def test_response_contract_v2_derives_v1_fields():
    directive = build_response_directive(
        answer_text="海底捞当前营业中。",
        answer_type="single_shop",
        response_mode="answer",
        trace_id="trace_v2_1",
        preview_text="海底捞当前营业中。",
        answer_source="deterministic_composer",
    )

    contract_v2 = ResponseContractV2.from_response_directive(
        directive,
        verifier_result="pass",
        fallback_reason="",
        uncertainty_notices=["距离暂时无法确认"],
        metadata={"workflow_name": "single_shop_fact_workflow"},
        claims=[{"text": "海底捞当前营业中"}],
        citations=[{"source": "tool"}],
        cards=[{"shop_id": "shop_1"}],
        confidence_band="high",
        response_policy={"response_mode": "answer"},
        clarification={"needed": False},
        safety_notice=["距离暂时无法确认"],
        trace_summary={"stage_names": ["intake_span", "response_span"]},
    )

    contract_v1 = ResponseContractV1.from_response_contract_v2(
        contract_v2,
        verifier_result="pass",
        fallback_reason="",
        uncertainty_notices=["距离暂时无法确认"],
        metadata={"workflow_name": "single_shop_fact_workflow"},
    )

    assert contract_v2.final_response == "海底捞当前营业中。"
    assert contract_v2.claims == [{"text": "海底捞当前营业中"}]
    assert contract_v2.trace_summary["stage_names"] == ["intake_span", "response_span"]
    assert contract_v1.answer_text == "海底捞当前营业中。"
    assert contract_v1.preview_text == "海底捞当前营业中。"
    assert contract_v1.answer_source == "deterministic_composer"


def test_final_response_build_emits_v2_and_v1():
    patch = _h_final_response(
        {
            "trace_id": "trace_v2_2",
            "session_id": "session_v2_2",
            "turn_id": "turn_v2_2",
            "workflow_name": "single_shop_fact_workflow",
            "response_mode": "answer",
            "task_type": "single_shop_query",
            "answer_plan": {"answer_type": "single_shop", "fallback_template_type": "deterministic_single_shop", "uncertainty_notes": []},
            "response_directive": {
                "answer_text": "海底捞当前营业中。",
                "preview_text": "海底捞当前营业中。",
                "final_response": "海底捞当前营业中。",
                "answer_source": "deterministic_composer",
            },
            "answer_source": "deterministic_composer",
            "final_response": "海底捞当前营业中。",
            "preview_text": "海底捞当前营业中。",
            "evidence_pack": {"claims": [{"text": "海底捞当前营业中"}]},
            "tool_results": {"call_1": {"tool_name": "get_shop_detail", "result_status": "ok"}},
            "answer_verify_passed": True,
            "verifier_result": "pass",
            "final_safety_status": "safe",
            "rewrite_count": 0,
            "fallback_reason": "",
        }
    )

    contract_v2 = patch["response_contract_v2"]
    contract_v1 = patch["response_contract_v1"]
    assert contract_v2.answer_text == "海底捞当前营业中。"
    assert contract_v2.trace_summary["answer_source"] == "deterministic_composer"
    assert contract_v1.answer_text == "海底捞当前营业中。"
    assert patch["final_response"] == "海底捞当前营业中。"
    assert patch["preview_text"] == "海底捞当前营业中。"


def test_final_response_v2_prefers_verifier_claim_results():
    patch = _h_final_response(
        {
            "trace_id": "trace_v2_claims",
            "session_id": "session_v2_claims",
            "turn_id": "turn_v2_claims",
            "workflow_name": "single_shop_fact_workflow",
            "response_mode": "answer",
            "task_type": "single_shop_query",
            "answer_plan": {"answer_type": "single_shop", "fallback_template_type": "deterministic_single_shop", "uncertainty_notes": []},
            "response_directive": {
                "answer_text": "海底捞当前营业中。",
                "preview_text": "海底捞当前营业中。",
                "final_response": "海底捞当前营业中。",
                "answer_source": "deterministic_composer",
            },
            "answer_source": "deterministic_composer",
            "final_response": "海底捞当前营业中。",
            "preview_text": "海底捞当前营业中。",
            "evidence_pack": {"claims": [{"claim_id": "raw_evidence_claim", "text": "raw"}]},
            "answer_claim_results": [
                {
                    "claim_id": "open_status_s1",
                    "claim_type": "fact",
                    "facet": "open_status",
                    "status": "supported",
                    "span_text": "营业中",
                    "span_start": 5,
                    "span_end": 8,
                }
            ],
            "tool_results": {"call_1": {"tool_name": "get_shop_detail", "result_status": "ok"}},
            "answer_verify_passed": True,
            "verifier_result": "pass",
            "final_safety_status": "safe",
            "rewrite_count": 0,
            "fallback_reason": "",
        }
    )

    contract_v2 = patch["response_contract_v2"]
    assert contract_v2.claims[0]["claim_id"] == "open_status_s1"
    assert contract_v2.claims[0]["span_text"] == "营业中"
