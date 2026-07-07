from __future__ import annotations

from local_life_agent.answer.response_contract import ResponseContractV1
from local_life_agent.answer.response_directive import EarlyResponseDirective, build_early_response_directive
from local_life_agent.domain.schemas import ErrorEnvelope, SemanticFrame
from local_life_agent.domain.enums import TaskType
from local_life_agent.engine.subgraphs.intake_guard_router import _h_hard_guard
from local_life_agent.engine.subgraphs.response_subgraph import _h_clarify_response
from local_life_agent.engine.subgraphs.understanding_subgraph import _h_slot_extractor
from local_life_agent.target.clarification import build_clarification_request, build_pending_clarification


def test_error_envelope_and_early_response_directive_roundtrip():
    clarification_request = build_clarification_request(
        build_pending_clarification(
            original_text="这两家哪个更适合聚餐",
            original_semantic_frame={"task_type": "comparison", "confidence": 0.9},
            original_task_type="comparison",
            candidate_targets=[],
            reason="comparison_targets_need_clarification",
            source_node="test",
        ),
        question="请说明要比较哪几家店。",
        source_stage="response_subgraph",
    )
    error_envelope = ErrorEnvelope(
        error_code="missing_comparison_targets",
        message="请说明要比较哪几家店。",
        severity="warning",
        recoverable=True,
        source_stage="merge_clarification",
        trace_id="trace_1",
    )
    directive = build_early_response_directive(
        answer_text="请说明要比较哪几家店。",
        answer_type="clarification",
        response_mode="clarify",
        reason="comparison_targets_need_clarification",
        fallback_reason="pending_clarification",
        trace_id="trace_1",
        clarification_request=clarification_request,
        error_envelope=error_envelope,
        answer_source="clarification_fallback_workflow",
    )

    assert isinstance(directive, EarlyResponseDirective)
    assert directive.directive_kind == "early_response"
    assert directive.final_response == ""
    assert directive.preview_text == "请说明要比较哪几家店。"
    assert directive.clarification_request is not None
    assert directive.error_envelope is not None

    contract = ResponseContractV1.from_response_directive(directive)
    assert contract.answer_text == "请说明要比较哪几家店。"
    assert contract.preview_text == "请说明要比较哪几家店。"
    assert contract.metadata["error_envelope"]["error_code"] == "missing_comparison_targets"
    assert contract.metadata["clarification_request"]["clarification_type"] == "missing_comparison_targets"


def test_hard_guard_rejection_emits_structured_early_response():
    result = _h_hard_guard({"normalized_text": "你好", "trace_id": "trace_guard", "task_type": "chat"})

    assert result["guard_result"] == "greeting"
    assert result["error_envelope"] is not None
    assert result["error_envelope"].source_stage == "hard_guard"
    assert result["response_directive"] is not None
    assert isinstance(result["response_directive"], EarlyResponseDirective)
    assert result["response_directive"].response_mode == "reject"
    assert result["response_directive"].final_response == ""
    assert result["response_directive"].preview_text


def test_pending_clarification_converts_to_unified_request():
    pending = build_pending_clarification(
        original_text="这两家哪个更适合聚餐",
        original_semantic_frame={"task_type": "comparison", "confidence": 0.9},
        original_task_type="comparison",
        candidate_targets=[
            {"shop_id": "s1", "shop_name": "海底捞"},
            {"shop_id": "s2", "shop_name": "巴奴"},
        ],
        reason="comparison_targets_need_clarification",
        source_node="test",
    )
    request = build_clarification_request(pending, source_stage="merge_clarification")

    assert request.clarification_type == "missing_comparison_targets"
    assert request.question == "请说明要比较哪几家店。"
    assert request.missing_slots == ["missing_comparison_targets"]
    assert [item["shop_name"] for item in request.candidate_options] == ["巴奴", "海底捞"] or [item["shop_name"] for item in request.candidate_options] == ["海底捞", "巴奴"]
    assert request.resume_context["original_task_type"] == "comparison"
    assert request.source_stage == "merge_clarification"


def test_slot_extractor_keeps_existing_slot_assignments():
    frame = SemanticFrame(
        task_type=TaskType.recommendation,
        primary_task="recommendation",
        merchant_mentions=["原有店"],
        deictic_references=["这家"],
        ordinal_references=["第一家"],
        confidence=0.9,
    )
    result = _h_slot_extractor(
        {
            "raw_text": "这家推荐咖啡",
            "semantic_frame": frame,
        }
    )
    updated = result["semantic_frame"]

    assert updated.task_type == TaskType.recommendation
    assert updated.merchant_mentions == ["原有店"]
    assert updated.deictic_references == ["这家"]
    assert updated.ordinal_references == ["第一家"]


def test_clarify_response_uses_unified_request():
    pending = build_pending_clarification(
        original_text="这两家哪个更适合聚餐",
        original_semantic_frame={"task_type": "comparison", "confidence": 0.9},
        original_task_type="comparison",
        candidate_targets=[
            {"shop_id": "s1", "shop_name": "海底捞"},
            {"shop_id": "s2", "shop_name": "巴奴"},
        ],
        reason="comparison_targets_need_clarification",
        source_node="test",
    )
    result = _h_clarify_response(
        {
            "trace_id": "trace_clarify",
            "pending_clarification": pending,
            "pending_check_result": "invalid",
        }
    )

    directive = result["response_directive"]
    assert isinstance(directive, EarlyResponseDirective)
    assert directive.clarification_request is not None
    assert directive.clarification_request.clarification_type == "missing_comparison_targets"
    assert directive.final_response == ""
