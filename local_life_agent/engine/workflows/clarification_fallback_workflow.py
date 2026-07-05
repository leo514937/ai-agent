"""Independent workflow for clarification and trusted fallback replies.

Phase 7 uses this workflow when the request is ambiguous, underspecified,
low-confidence, or otherwise cannot safely proceed to tool execution.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ...domain.graph_state import GraphState
from ...domain.schemas import AnswerPlan, OrchestrationDecision
from ...engine._compat import _log, _to_dict
from ...observability.file_logger import get_python_service_logger, log_kv
from ...target.clarification import build_pending_clarification, format_pending_prompt

_LOGGER = get_python_service_logger()

_CLARIFICATION_POLICY: dict[str, dict[str, Any]] = {
    "ambiguous": {
        "response_mode": "clarify",
        "next_action": "clarify",
        "answer_type": "clarification",
        "response_text": "我找到了多个可能的对象，请你补充更明确的店名或编号。",
        "section_type": "clarification",
    },
    "reference_failed": {
        "response_mode": "clarify",
        "next_action": "clarify",
        "answer_type": "clarification",
        "response_text": "我暂时没法确认你指的是哪一家店，请提供完整店名。",
        "section_type": "clarification",
    },
    "missing_required_slot": {
        "response_mode": "clarify",
        "next_action": "clarify",
        "answer_type": "clarification",
        "response_text": "还缺少一些关键信息，请补充后我再继续帮你处理。",
        "section_type": "clarification",
    },
    "low_confidence": {
        "response_mode": "clarify",
        "next_action": "clarify",
        "answer_type": "clarification",
        "response_text": "我现在把握不够高，可以再补充一点信息吗？",
        "section_type": "clarification",
    },
    "no_result": {
        "response_mode": "fallback",
        "next_action": "fallback",
        "answer_type": "error",
        "response_text": "暂时没有查到结果，你可以换个说法或补充更多信息再试。",
        "section_type": "fallback",
    },
    "tool_failure": {
        "response_mode": "fallback",
        "next_action": "fallback",
        "answer_type": "error",
        "response_text": "相关服务暂时不可用，请稍后再试。",
        "section_type": "fallback",
    },
    "unsupported": {
        "response_mode": "fallback",
        "next_action": "fallback",
        "answer_type": "error",
        "response_text": "这个能力暂时不支持，我可以继续帮你处理本地生活查询类问题。",
        "section_type": "boundary",
    },
    "forbidden": {
        "response_mode": "fallback",
        "next_action": "fallback",
        "answer_type": "error",
        "response_text": "这个请求包含当前不支持或受限的能力，我不能继续处理。",
        "section_type": "boundary",
    },
}

_CLARIFYING_TASKS = {"ambiguous", "reference_failed", "missing_required_slot", "low_confidence"}
_FALLBACK_TASKS = {"no_result", "tool_failure", "unsupported", "forbidden"}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _classify_fallback(state: GraphState, decision: OrchestrationDecision) -> str:
    task_type = str(state.get("task_type", "") or "").strip()
    workflow_reason = str(decision.workflow_reason or state.get("workflow_reason", "") or "").lower()
    raw_text = str(state.get("raw_text", "") or state.get("normalized_text", "") or "").lower()
    if task_type in _CLARIFICATION_POLICY:
        return task_type
    if "forbidden" in workflow_reason or any(token in raw_text for token in ("退款", "交易", "下单", "支付", "预约", "订单")):
        return "forbidden"
    if "unsupported" in workflow_reason:
        return "unsupported"
    if "tool_failure" in workflow_reason or "tool failure" in workflow_reason:
        return "tool_failure"
    if "no_result" in workflow_reason or "no result" in workflow_reason:
        return "no_result"
    if "low_confidence" in workflow_reason:
        return "low_confidence"
    if "missing" in workflow_reason:
        return "missing_required_slot"
    if "reference" in workflow_reason or "ambiguous" in workflow_reason:
        return "reference_failed"
    if any(token in raw_text for token in ("模糊", "哪个", "哪家", "哪一个", "哪一家")):
        return "ambiguous"
    return "missing_required_slot"


def _collect_candidate_targets(state: GraphState) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for source in (state.get("pending_clarification"), state.get("comparison_targets"), _to_dict(state.get("semantic_frame")).get("comparison_targets")):
        if not source:
            continue
        if isinstance(source, dict):
            source = source.get("candidate_targets") or source.get("targets") or []
        if not isinstance(source, list):
            continue
        for item in source:
            item_dict = _to_dict(item)
            shop_id = str(item_dict.get("shop_id", "") or item_dict.get("resolved_shop", {}).get("shop_id", "") or "").strip()
            shop_name = str(item_dict.get("shop_name", "") or item_dict.get("resolved_shop", {}).get("shop_name", "") or "").strip()
            if shop_id or shop_name:
                candidates.append(
                    {
                        "shop_id": shop_id,
                        "shop_name": shop_name,
                        "address": str(item_dict.get("address", "") or "").strip(),
                    }
                )
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in candidates:
        key = (str(item.get("shop_id", "")).strip(), str(item.get("shop_name", "")).strip())
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _build_answer_plan(policy_key: str, response_mode: str) -> AnswerPlan:
    policy = _CLARIFICATION_POLICY.get(policy_key, _CLARIFICATION_POLICY["missing_required_slot"])
    return AnswerPlan.model_validate(
        {
            "answer_type": str(policy.get("answer_type", "clarification") or "clarification"),
            "target_shop_ids": [],
            "response_sections": [
                {
                    "section_id": f"clarification_{policy_key}",
                    "section_type": str(policy.get("section_type", "clarification") or "clarification"),
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
            "tone": "neutral",
            "fallback_template_type": response_mode,
        }
    )


def run_clarification_fallback_workflow(
    state: GraphState,
    decision: OrchestrationDecision | None = None,
) -> dict[str, Any]:
    """Run the Phase 7 clarification / fallback workflow."""

    decision = decision or _to_dict(state.get("orchestration_decision"))
    if not isinstance(decision, OrchestrationDecision):
        decision = OrchestrationDecision.model_validate(
            _to_dict(decision)
            or {
                "orchestration_pattern": "clarification_fallback",
                "workflow_name": "clarification_fallback",
                "workflow_reason": "clarification fallback workflow",
                "task_complexity": "medium",
                "requires_tool": False,
                "requires_clarification": True,
                "response_mode": "clarify",
                "confidence": 0.0,
                "missing_fields": [],
                "next_action": "clarify",
            }
        )

    policy_key = _classify_fallback(state, decision)
    policy = _CLARIFICATION_POLICY.get(policy_key, _CLARIFICATION_POLICY["missing_required_slot"])
    response_mode = str(policy.get("response_mode", "clarify") or "clarify")
    answer_plan = _build_answer_plan(policy_key, response_mode)
    timestamp = _utc_now_iso()
    semantic_frame = _to_dict(state.get("semantic_frame"))
    final_response = str(policy.get("response_text", "") or "").strip()
    pending_clarification = _to_dict(state.get("pending_clarification"))

    if response_mode == "clarify":
        if not pending_clarification:
            pending = build_pending_clarification(
                original_text=str(state.get("raw_text", "") or state.get("normalized_text", "") or ""),
                original_semantic_frame=semantic_frame,
                original_task_type=str(state.get("task_type", "") or semantic_frame.get("task_type", "") or ""),
                candidate_targets=_collect_candidate_targets(state),
                reason=policy_key,
                source_node="clarification_fallback_workflow",
            )
            pending_clarification = pending.model_dump()
        final_response = format_pending_prompt(pending_clarification)
    elif not final_response:
        final_response = str(policy.get("response_text", "") or "抱歉，暂时无法处理您的请求，请稍后再试。")

    patch: dict[str, Any] = {
        "workflow_name": "clarification_fallback",
        "orchestration_pattern": "clarification_fallback",
        "workflow_reason": str(decision.workflow_reason or f"clarification fallback for {policy_key}"),
        "workflow_run_status": "clarify" if response_mode == "clarify" else "fallback",
        "workflow_runner_error": "",
        "workflow_runner_reason": str(decision.workflow_reason or f"clarification fallback for {policy_key}"),
        "workflow_candidate_reason": str(decision.workflow_reason or f"clarification fallback for {policy_key}"),
        "workflow_started_at": timestamp,
        "workflow_finished_at": timestamp,
        "workflow_callable": "run_clarification_fallback_workflow",
        "workflow_registered": True,
        "response_mode": response_mode,
        "next_action": str(policy.get("next_action", "clarify") or "clarify"),
        "answer_plan": answer_plan,
        "final_response": final_response,
        "draft_response": final_response,
        "answer_source": "clarification_fallback_workflow",
        "verifier_result": "pass",
        "answer_verify_passed": True,
        "answer_verify_violations": [],
        "fallback_reason": policy_key,
        "answer_fallback_reason": policy_key,
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
            "fallback_reason",
            "answer_fallback_reason",
            "final_safety_status",
        ],
    }
    if response_mode == "clarify":
        patch["pending_clarification"] = pending_clarification
        patch["state_keys_changed"].append("pending_clarification")
    patch.update(_log(state, "clarification_fallback_workflow", workflow_name="clarification_fallback", policy_key=policy_key, status=patch["workflow_run_status"]))
    log_kv(
        _LOGGER,
        20 if response_mode == "clarify" else 30,
        "[WORKFLOW_RUNNER]",
        tone="route" if response_mode == "clarify" else "warn",
        node_name="clarification_fallback_workflow",
        workflow_name="clarification_fallback",
        policy_key=policy_key,
        status=patch["workflow_run_status"],
    )
    return patch
