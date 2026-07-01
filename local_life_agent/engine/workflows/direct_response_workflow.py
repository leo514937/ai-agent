"""Independent workflow for lightweight direct responses.

Phase 7 uses this workflow for chat / capability / boundary-style replies
that do not need tool calls or merchant-fact evidence.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ...domain.graph_state import GraphState
from ...domain.schemas import AnswerPlan, OrchestrationDecision
from ...engine._compat import _log, _to_dict
from ...observability.file_logger import get_python_service_logger, log_kv

_LOGGER = get_python_service_logger()

_DIRECT_RESPONSE_POLICY: dict[str, dict[str, Any]] = {
    "chat": {
        "answer_type": "general",
        "response_text": "你好，我可以帮你查商家营业状态、距离、优惠券、评价摘要和人均价格。",
        "tone": "friendly",
        "section_type": "greeting",
    },
    "capability": {
        "answer_type": "general",
        "response_text": "我可以帮你处理本地生活查询，比如营业状态、距离、优惠券、评价摘要和人均价格；暂不支持 RAG、交易、下单、支付、退款和预约。",
        "tone": "informative",
        "section_type": "capability",
    },
    "unsafe": {
        "answer_type": "error",
        "response_text": "出于安全考虑，我不能继续处理这个请求。",
        "tone": "firm",
        "section_type": "safety",
    },
    "out_of_scope": {
        "answer_type": "error",
        "response_text": "这个请求超出我当前可支持的本地生活能力，我可以继续帮你处理商家查询类问题。",
        "tone": "informative",
        "section_type": "boundary",
    },
    "invalid": {
        "answer_type": "clarification",
        "response_text": "我没太理解你的意思，可以换个更具体的说法吗？",
        "tone": "helpful",
        "section_type": "clarification",
    },
    "forbidden": {
        "answer_type": "error",
        "response_text": "这个请求包含当前不支持或受限的能力，我不能继续处理。",
        "tone": "firm",
        "section_type": "boundary",
    },
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _classify_direct_response(state: GraphState, decision: OrchestrationDecision) -> str:
    top_intent = str(state.get("top_intent", "") or "").strip()
    task_type = str(state.get("task_type", "") or "").strip()
    workflow_reason = str(decision.workflow_reason or state.get("workflow_reason", "") or "").lower()
    raw_text = str(state.get("raw_text", "") or state.get("normalized_text", "") or "").lower()
    semantic_frame = _to_dict(state.get("semantic_frame"))
    primary_task = str(semantic_frame.get("primary_task", "") or "").lower()

    if any(token in workflow_reason for token in ("forbidden", "unsupported/forbidden")):
        return "forbidden"
    if any(token in raw_text for token in ("退款", "交易", "下单", "支付", "预约", "订单", "rag")):
        return "forbidden"
    if top_intent in _DIRECT_RESPONSE_POLICY:
        return top_intent
    if task_type in _DIRECT_RESPONSE_POLICY:
        return task_type
    if primary_task in _DIRECT_RESPONSE_POLICY:
        return primary_task
    if any(token in raw_text for token in ("能做什么", "支持什么", "支持哪些", "可以做什么")):
        return "capability"
    if any(token in raw_text for token in ("你好", "嗨", "您好", "哈喽")):
        return "chat"
    return "out_of_scope"


def _build_answer_plan(policy_key: str) -> AnswerPlan:
    policy = _DIRECT_RESPONSE_POLICY.get(policy_key, _DIRECT_RESPONSE_POLICY["out_of_scope"])
    return AnswerPlan.model_validate(
        {
            "answer_type": str(policy.get("answer_type", "general") or "general"),
            "target_shop_ids": [],
            "response_sections": [
                {
                    "section_id": f"direct_{policy_key}",
                    "section_type": str(policy.get("section_type", "general") or "general"),
                    "status": "ok",
                    "required": False,
                },
            ],
            "allowed_claims": [],
            "required_claims": [],
            "must_mention_unknowns": [],
            "forbidden_claims": [],
            "ranking_snapshot_id": "",
            "comparison_matrix_id": "",
            "tone": str(policy.get("tone", "neutral") or "neutral"),
            "fallback_template_type": "direct_response",
        }
    )


def run_direct_response_workflow(
    state: GraphState,
    decision: OrchestrationDecision | None = None,
) -> dict[str, Any]:
    """Run the Phase 7 direct response workflow."""

    decision = decision or _to_dict(state.get("orchestration_decision"))
    if not isinstance(decision, OrchestrationDecision):
        decision = OrchestrationDecision.model_validate(
            _to_dict(decision)
            or {
                "orchestration_pattern": "direct_response",
                "workflow_name": "direct_response",
                "workflow_reason": "direct response workflow",
                "task_complexity": "low",
                "requires_tool": False,
                "requires_clarification": False,
                "response_mode": "direct_response",
                "confidence": 0.0,
                "missing_fields": [],
                "next_action": "run_workflow",
            }
        )

    policy_key = _classify_direct_response(state, decision)
    policy = _DIRECT_RESPONSE_POLICY.get(policy_key, _DIRECT_RESPONSE_POLICY["out_of_scope"])
    answer_plan = _build_answer_plan(policy_key)
    final_response = str(policy["response_text"])
    timestamp = _utc_now_iso()

    patch: dict[str, Any] = {
        "workflow_name": "direct_response",
        "orchestration_pattern": "direct_response",
        "workflow_reason": str(decision.workflow_reason or f"direct response for {policy_key}"),
        "workflow_run_status": "completed",
        "workflow_runner_error": "",
        "workflow_runner_reason": str(decision.workflow_reason or f"direct response for {policy_key}"),
        "workflow_started_at": timestamp,
        "workflow_finished_at": timestamp,
        "workflow_callable": "run_direct_response_workflow",
        "workflow_registered": True,
        "response_mode": "direct_response",
        "next_action": "run_workflow",
        "answer_plan": answer_plan,
        "final_response": final_response,
        "draft_response": final_response,
        "answer_source": "direct_response_workflow",
        "verifier_result": "pass",
        "answer_verify_passed": True,
        "answer_verify_violations": [],
        "fallback_reason": "",
        "answer_fallback_reason": "",
        "final_safety_status": "safe",
        "llm_verbalizer_called": False,
        "llm_called": False,
        "llm_backend": "deterministic",
        "state_keys_changed": [
            "workflow_name",
            "orchestration_pattern",
            "workflow_run_status",
            "workflow_runner_error",
            "workflow_runner_reason",
            "workflow_started_at",
            "workflow_finished_at",
            "workflow_callable",
            "workflow_registered",
            "response_mode",
            "next_action",
            "answer_plan",
            "final_response",
            "draft_response",
            "answer_source",
            "verifier_result",
            "answer_verify_passed",
            "answer_verify_violations",
            "final_safety_status",
        ],
    }
    patch.update(_log(state, "direct_response_workflow", workflow_name="direct_response", policy_key=policy_key, status="completed"))
    log_kv(
        _LOGGER,
        20,
        "[WORKFLOW_RUNNER]",
        tone="route",
        node_name="direct_response_workflow",
        workflow_name="direct_response",
        policy_key=policy_key,
        status="completed",
    )
    return patch
