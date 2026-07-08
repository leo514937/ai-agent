"""response_subgraph — answer generation, verification, and fallback.

Generates the final answer via LLM verbalizer, verifies it against evidence,
rewrites if needed, and handles clarification / fallback responses.
"""

from __future__ import annotations

import logging
import inspect
from typing import Any

from .._compat import (
    _build_conversation_continuity,
    _log,
    _run_step,
    _run_steps,
    _session_store_state,
    _state_delta,
    _to_dict,
    _GRAPH_REWRITE_LIMIT,
    _OUTER_WRAPPER_EXCLUDE_FIELDS,
)
from .._routes import (
    _OUTER_ROUTE_CLARIFY,
    _OUTER_ROUTE_CLARIFY_READY,
    _OUTER_ROUTE_DIRECT,
    _OUTER_ROUTE_FALLBACK,
    _OUTER_ROUTE_FALLBACK_READY,
    _OUTER_ROUTE_PASS,
    _OUTER_ROUTE_REJECT,
)
from ...domain.enums import ResponseMode, normalize_response_mode
from ...domain.graph_state import GraphState
from ...domain.schemas import AnswerPlan
from ...domain.decision import decision_to_answer_plan
from ...answer.verifier import verify_answer
from ...answer.response_directive import ResponseDirective, build_early_response_directive, build_response_directive
from ...answer.response_contract import ResponseContractV1, ResponseContractV2
from ...answer.rewrite_instruction import RewriteInstruction
from ...domain.state import SessionState
from ...planning.budget.execution_budget import execution_budget_from_state
from ...planning.budget.budget_context import budget_context_from_state
from ...streaming.preview_policy import sanitize_preview_text
from ...observability.file_logger import get_python_service_logger, log_kv
from ...target.clarification import build_clarification_request

_LOGGER = get_python_service_logger()
_DIAGNOSTIC_FALLBACK_REASONS = {"LLM_ENUM_OUT_OF_RANGE", "LLM_JSON_PARSE_ERROR", "semantic_frame_validation_failed"}


def _recommendation_limit_from_state(state: GraphState) -> int:
    semantic_frame = _to_dict(state.get("semantic_frame"))
    ranking_snapshot = _to_dict(_to_dict(state.get("evidence_pack")).get("ranking_snapshot"))
    for raw_value in (
        semantic_frame.get("candidate_limit"),
        ranking_snapshot.get("candidate_limit"),
    ):
        try:
            value = int(raw_value)
        except Exception:
            continue
        if value > 0:
            return value
    return 5


def _compose_single_shop_response(evidence: dict[str, Any], draft_text: str) -> str:
    """Build a deterministic single-shop summary from EvidencePack."""
    evidence_dict = _to_dict(evidence)
    snapshot = evidence_dict.get("ranking_snapshot") or {}
    shop_name = str(snapshot.get("shop_name", "") or "").strip()
    if not shop_name:
        for item in evidence_dict.get("evidence_items") or []:
            if isinstance(item, dict) and str(item.get("shop_name", "") or "").strip():
                shop_name = str(item.get("shop_name", "") or "").strip()
                break
    if not shop_name:
        shop_name = "这家店"

    facet_results = evidence_dict.get("facet_results") or []
    coupon_text = ""
    open_text = ""
    distance_text = ""
    rating_text = ""
    price_text = ""
    uncertain_notes: list[str] = []

    for item in facet_results:
        item_dict = _to_dict(item)
        facet = str(item_dict.get("facet", "") or "")
        status = str(item_dict.get("status", item_dict.get("result_status", "")) or "").lower()
        value = item_dict.get("value")

        if facet == "coupon":
            if status == "ok":
                titles: list[str] = []
                if isinstance(value, list):
                    titles = [str(v).strip() for v in value if str(v).strip()]
                if titles:
                    coupon_text = f"有券：{'、'.join(titles[:3])}"
                else:
                    coupon_text = "有券"
            elif status == "empty":
                coupon_text = "当前暂无可用优惠券"
            else:
                uncertain_notes.append("优惠券情况暂时无法确认")
        elif facet == "open_status":
            open_value = value
            if isinstance(open_value, dict):
                open_value = open_value.get("open_status", open_value.get("status", ""))
            open_status = str(open_value or "").strip().lower()
            if status == "ok" and open_status in {"open", "opened"}:
                open_text = "目前营业中"
            elif status == "ok" and open_status in {"closed", "close"}:
                open_text = "当前未营业"
            else:
                uncertain_notes.append("营业状态暂时无法确认")
        elif facet == "distance":
            distance_value = value
            distance_km = None
            eta_minutes = None
            if isinstance(distance_value, dict):
                distance_km = distance_value.get("distance_km")
                eta_minutes = distance_value.get("eta_minutes")
            elif isinstance(distance_value, (int, float)):
                distance_km = distance_value
            if status == "ok" and distance_km is not None:
                distance_text = f"距离为 {distance_km} 公里"
                if eta_minutes is not None:
                    distance_text += f"，预计时间 {eta_minutes} 分钟"
            else:
                uncertain_notes.append("距离暂时无法确认")
        elif facet == "rating":
            if status == "ok" and value is not None:
                rating_text = f"评分为 {value}"
            else:
                uncertain_notes.append("评分暂时无法确认")
        elif facet in {"avg_price", "price"}:
            price_value = value
            if isinstance(price_value, dict):
                price_value = price_value.get("avg_price", price_value.get("price", price_value.get("value", "")))
            if status == "ok" and price_value is not None:
                price_text = f"人均约 {price_value} 元"
            else:
                uncertain_notes.append("人均价格暂时无法确认")

    parts: list[str] = []
    if open_text:
        parts.append(open_text)
    if coupon_text:
        parts.append(coupon_text)
    if distance_text:
        parts.append(distance_text)
    if rating_text:
        parts.append(rating_text)
    if price_text:
        parts.append(price_text)

    if parts:
        response = f"{shop_name}: {'; '.join(parts)}"
    else:
        response = draft_text.strip() or f"{shop_name}的信息我已经整理好了。"

    if uncertain_notes:
        response += "；" + "；".join(dict.fromkeys(uncertain_notes))

    return response


def _rewrite_strategy_from_instruction(
    answer_plan: AnswerPlan,
    rewrite_instruction: RewriteInstruction | dict[str, Any] | None,
    *,
    rewrite_count: int,
    rewrite_limit: int,
) -> str:
    if rewrite_count >= rewrite_limit:
        return "trusted_fallback"
    instruction = rewrite_instruction
    if isinstance(instruction, dict):
        try:
            instruction = RewriteInstruction.model_validate(instruction)
        except Exception:
            instruction = None
    if instruction is None:
        return "llm_rewrite"
    fallback_mode = str(getattr(instruction, "fallback_mode", "") or "").strip()
    if fallback_mode in {"fallback", "system_fallback"}:
        return "trusted_fallback"
    answer_type = str(getattr(answer_plan, "answer_type", "") or "").strip()
    violation_codes = {str(item).strip() for item in (getattr(instruction, "violation_codes", []) or []) if str(item).strip()}
    ranking_sensitive = bool(
        violation_codes
        & {
            "ranking_changed_by_llm",
            "unsupported_comparison_winner",
            "missing_comparison_targets",
            "missing_recommendation_targets",
        }
    )
    if answer_type in {"single_shop", "single_shop_query", "clarification", "general", "chat", "capability", "out_of_scope", "unsafe", "invalid", "forbidden", "error"}:
        return "deterministic_composer"
    if ranking_sensitive:
        return "deterministic_composer"
    if getattr(instruction, "unsupported_claims", None) or getattr(instruction, "contradicted_claims", None):
        return "deterministic_composer"
    if violation_codes & {"empty_evidence_or_draft", "template_fallback", "llm_disabled", "llm_client_unavailable", "llm_call_failed", "llm_verbalizer_error", "prompt_load_failed"}:
        return "trusted_fallback"
    return "llm_rewrite"


def _rewrite_route_from_instruction(
    answer_plan: AnswerPlan,
    rewrite_instruction: RewriteInstruction | dict[str, Any] | None,
    *,
    rewrite_count: int,
    rewrite_limit: int,
) -> str:
    """Compute the next rewrite route from the verifier instruction."""

    if rewrite_count >= rewrite_limit:
        return "trusted_fallback"
    return _rewrite_strategy_from_instruction(
        answer_plan,
        rewrite_instruction,
        rewrite_count=rewrite_count,
        rewrite_limit=rewrite_limit,
    )


def _to_response_directive(value: Any) -> ResponseDirective | None:
    if value is None:
        return None
    if isinstance(value, ResponseDirective):
        return value
    if isinstance(value, dict):
        try:
            return ResponseDirective.model_validate(value)
        except Exception:
            return None
    return None


def _as_list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, dict)]
    if isinstance(value, tuple):
        return [dict(item) for item in value if isinstance(item, dict)]
    if hasattr(value, "model_dump"):
        try:
            dumped = value.model_dump()
            if isinstance(dumped, dict):
                return [dumped]
        except Exception:
            return []
    if isinstance(value, dict):
        return [dict(value)]
    return []


def _build_response_trace_summary(state: GraphState, *, answer_source: str, fallback_reason: str, directive: ResponseDirective | None) -> dict[str, Any]:
    evidence = _to_dict(state.get("evidence_pack"))
    tool_results = _to_dict(state.get("tool_results") or state.get("tool_result_set"))
    tool_call_count = len(tool_results) if isinstance(tool_results, dict) else 0
    trace_spans = state.get("trace_spans") or []
    stage_names: list[str] = []
    for item in trace_spans:
        item_dict = _to_dict(item)
        name = str(item_dict.get("span_name") or item_dict.get("stage") or "").strip()
        if name and name not in stage_names:
            stage_names.append(name)
    return {
        "trace_id": str(state.get("trace_id", "") or ""),
        "session_id": str(state.get("session_id", "") or ""),
        "turn_id": str(state.get("turn_id", "") or ""),
        "workflow_name": str(state.get("workflow_name", "") or ""),
        "response_mode": str(state.get("response_mode", "") or ""),
        "task_type": str(state.get("task_type", "") or ""),
        "answer_source": str(answer_source or ""),
        "fallback_reason": str(fallback_reason or ""),
        "llm_called": bool(state.get("llm_called", False) or state.get("planning_llm_called", False) or state.get("llm_verbalizer_called", False)),
        "tool_called": bool(tool_call_count > 0),
        "tool_call_count": tool_call_count,
        "rewrite_count": int(state.get("rewrite_count", 0) or 0),
        "fallback_used": bool(state.get("fallback_used", False)),
        "answer_verify_passed": bool(state.get("answer_verify_passed", True)),
        "answer_verify_violations": list(state.get("answer_verify_violations") or []),
        "stage_names": stage_names,
        "has_evidence_pack": bool(evidence),
        "directive_kind": str(getattr(directive, "directive_kind", "") or ""),
    }


def _build_response_policy(answer_plan: AnswerPlan | None, state: GraphState) -> dict[str, Any]:
    return {
        "response_mode": str(state.get("response_mode", "") or ""),
        "workflow_name": str(state.get("workflow_name", "") or ""),
        "task_type": str(state.get("task_type", "") or ""),
        "answer_type": str(getattr(answer_plan, "answer_type", "") or ""),
        "fallback_template_type": str(getattr(answer_plan, "fallback_template_type", "") or ""),
        "verifier_result": str(state.get("verifier_result", "") or ""),
        "final_safety_status": str(state.get("final_safety_status", "") or ""),
    }


def _build_response_contract_v2(
    state: GraphState,
    directive: ResponseDirective | None,
    *,
    answer_text: str,
    preview_text: str,
    fallback_reason: str,
) -> ResponseContractV2:
    answer_plan = state.get("answer_plan")
    evidence_pack = _to_dict(state.get("evidence_pack"))
    claims = _as_list_of_dicts(state.get("answer_claim_results")) or _as_list_of_dicts(evidence_pack.get("claims"))
    citations = _as_list_of_dicts(evidence_pack.get("citations"))
    cards = _as_list_of_dicts(state.get("cards") or evidence_pack.get("cards"))
    clarification = _to_dict(state.get("clarification_request") or state.get("pending_clarification"))
    safety_notice = [
        str(item).strip()
        for item in (
            (getattr(answer_plan, "uncertainty_notes", []) if answer_plan is not None else [])
            or state.get("answer_verify_violations")
            or []
        )
        if str(item).strip()
    ]
    confidence_band = str(getattr(answer_plan, "confidence_band", "") or evidence_pack.get("confidence_band", "") or "")
    trace_summary = _build_response_trace_summary(
        state,
        answer_source=str(state.get("answer_source", "") or ""),
        fallback_reason=fallback_reason,
        directive=directive,
    )
    return ResponseContractV2.from_response_directive(
        directive,
        verifier_result=str(state.get("verifier_result", "") or ""),
        fallback_reason=fallback_reason,
        uncertainty_notices=safety_notice,
        metadata={
            "workflow_name": str(state.get("workflow_name", "") or ""),
            "answer_source": str(state.get("answer_source", "") or ""),
            "response_mode": str(state.get("response_mode", "") or ""),
            "trace_summary": trace_summary,
        },
        claims=claims,
        citations=citations,
        cards=cards,
        confidence_band=confidence_band,
        response_policy=_build_response_policy(answer_plan if isinstance(answer_plan, AnswerPlan) else None, state),
        clarification=clarification,
        safety_notice=safety_notice,
        trace_summary=trace_summary,
    ).model_copy(update={"answer_text": answer_text, "preview_text": preview_text, "final_response": answer_text})


def _response_text_from_state(state: GraphState) -> str:
    for key in ("final_response", "draft_response", "preview_text"):
        text = str(state.get(key, "") or "").strip()
        if text:
            return text
    directive = _to_response_directive(state.get("response_directive"))
    if directive is not None:
        for text in (directive.answer_text, directive.final_response, directive.preview_text):
            if str(text or "").strip():
                return str(text).strip()
    return ""


def _is_recommendation_refine_follow_up(state: GraphState) -> bool:
    last_recommendation_list = list(state.get("last_recommendation_list") or [])
    if not last_recommendation_list:
        return False
    semantic_frame = _to_dict(state.get("semantic_frame"))
    pending = _to_dict(state.get("pending_clarification"))
    if not semantic_frame:
        semantic_frame = _to_dict(pending.get("original_semantic_frame"))
    if not semantic_frame:
        return False
    if not bool(semantic_frame.get("constraint_update")):
        return False
    preference_signals = semantic_frame.get("preference_signals") or []
    signal_text = " ".join(
        [
            " ".join(
                str(part).strip()
                for part in (
                    item.get("preference_type", "") if isinstance(item, dict) else getattr(item, "preference_type", ""),
                    item.get("value", "") if isinstance(item, dict) else getattr(item, "value", ""),
                    item.get("text", "") if isinstance(item, dict) else getattr(item, "text", ""),
                )
                if str(part or "").strip()
            )
            for item in preference_signals
        ]
    )
    raw_text = str(
        state.get("raw_text", "")
        or state.get("normalized_text", "")
        or pending.get("original_text", "")
        or semantic_frame.get("raw_text", "")
        or semantic_frame.get("normalized_text", "")
        or ""
    )
    cues = ("便宜一点", "便宜点", "更便宜", "更便宜点", "便宜些", "比较便宜", "relative_price_preference", "lower_price", "cheaper")
    return any(token in raw_text for token in cues) or any(token in signal_text for token in cues)


def _build_recommendation_refine_text(state: GraphState) -> str:
    items = [item for item in (state.get("last_recommendation_list") or []) if isinstance(item, dict)]
    if not items:
        return "我会按更便宜的方向继续帮你看。"
    lines: list[str] = ["我按更便宜的方向继续看了上轮推荐，先给你这几家："]
    for idx, item in enumerate(items[:_recommendation_limit_from_state(state)], 1):
        shop_name = str(item.get("shop_name", "") or "").strip() or f"第{idx}家"
        extra_parts: list[str] = []
        open_status = str(item.get("open_status", "") or "").strip()
        if open_status:
            extra_parts.append("营业中" if open_status not in {"closed", "close", "0"} else "当前未营业")
        coupon_count = item.get("coupon_count")
        if coupon_count is not None:
            try:
                coupon_num = int(coupon_count)
            except Exception:
                coupon_num = 0
            extra_parts.append(f"有{coupon_num}张券" if coupon_num > 0 else "暂无券")
        score = item.get("score")
        if score is not None:
            extra_parts.append(f"综合分 {score}")
        suffix = f"（{'；'.join(extra_parts)}）" if extra_parts else ""
        lines.append(f"{idx}. {shop_name}{suffix}")
    lines.append("如果你想，我可以继续按券、营业状态或距离再筛一轮。")
    return "\n".join(lines)


def h_response_subgraph(state: GraphState) -> dict:
    """Outer wrapper: handle response mode → generate / clarify / fallback."""
    before = dict(state)
    response_mode_raw = state.get("response_mode", "")
    normalized_mode = normalize_response_mode(response_mode_raw)
    response_mode = str(getattr(normalized_mode, "value", "") or response_mode_raw or "")
    semantic_frame = _to_dict(state.get("semantic_frame"))
    prior_current_shop = _to_dict(state.get("current_shop"))
    task_type_value = str(state.get("task_type", "") or semantic_frame.get("task_type", "") or "")
    has_deictic_reference = bool(semantic_frame.get("deictic_references") or semantic_frame.get("reference_mentions"))
    log_kv(
        _LOGGER,
        logging.INFO,
        "[SUBGRAPH_ENTER]",
        tone="route",
        subgraph="response_subgraph",
        trace_id=state.get("trace_id", ""),
        response_mode=response_mode,
    )
    if (
        task_type_value == "comparison"
        and has_deictic_reference
        and not prior_current_shop.get("shop_id")
        and not prior_current_shop.get("shop_name")
    ):
        working = {
            **state,
            "workflow_name": "clarification_fallback",
            "response_mode": "clarify",
            "error_message": "请提供完整店名，或回复编号/店名。",
            "final_response": "请提供完整店名，或回复编号/店名。",
        }
        working = _run_step(working, _h_clarify_response)
        after = {**working, "response_route": _OUTER_ROUTE_CLARIFY_READY}
        log_kv(
            _LOGGER,
            logging.INFO,
            "[ROUTE_DECISION]",
            tone="route",
            subgraph="response_subgraph",
            route=_OUTER_ROUTE_CLARIFY_READY,
            response_mode="clarify",
            reason="comparison_deictic_missing_current_shop",
        )
        return _state_delta(before, after, always_include={"response_route"})
    if normalized_mode in {ResponseMode.DIRECT, ResponseMode.DIRECT_RESPONSE, ResponseMode.REJECT, ResponseMode.EXPLORATION_PLAN} or response_mode in {_OUTER_ROUTE_DIRECT, _OUTER_ROUTE_REJECT, "direct_response", "exploration_plan"}:
        working = dict(state)
        if not str(working.get("final_response", "") or "").strip():
            if _response_text_from_state(working):
                working = {**working, **_h_final_response(working)}
            else:
                working = {**working, **_h_final_response(working)}
        after = {**working, "response_route": _OUTER_ROUTE_PASS}
        log_kv(_LOGGER, logging.INFO, "[ROUTE_DECISION]", tone="route", subgraph="response_subgraph", route=_OUTER_ROUTE_PASS, response_mode=response_mode)
        return _state_delta(before, after, always_include={"response_route"})
    if normalized_mode == ResponseMode.CLARIFY or response_mode in {_OUTER_ROUTE_CLARIFY} or state.get("pending_clarification") is not None:
        if _is_recommendation_refine_follow_up(state):
            response = _build_recommendation_refine_text(state)
            working = {
                **state,
                "workflow_name": "discovery_decision",
                "response_mode": "answer",
                "draft_response": response,
                "final_response": response,
                "answer_source": "template_fallback",
                "template_degraded": False,
                "fallback_used": False,
                "template_fallback_used": True,
                "response_directive": build_response_directive(
                    answer_text=response,
                    answer_type="recommendation",
                    response_mode="answer",
                    reason="recommendation_refine_follow_up",
                    fallback_reason="recommendation_refine_follow_up",
                    trace_id=str(state.get("trace_id", "") or ""),
                    final_response=response,
                    preview_text=response,
                    answer_source="template_fallback",
                ),
            }
            working = _run_step(working, _h_final_response)
            after = {**working, "response_route": _OUTER_ROUTE_PASS}
            return _state_delta(before, after, always_include={"response_route"})
        if not str(state.get("final_response", "") or "").strip():
            if _response_text_from_state(state):
                working = _run_step(state, _h_final_response)
            else:
                working = _run_step(state, _h_clarify_response)
                if not str(working.get("final_response", "") or "").strip():
                    working = {**working, **_h_final_response(working)}
        else:
            working = dict(state)
        after = {**working, "response_route": _OUTER_ROUTE_CLARIFY_READY}
        log_kv(_LOGGER, logging.INFO, "[ROUTE_DECISION]", tone="route", subgraph="response_subgraph", route=_OUTER_ROUTE_CLARIFY_READY, response_mode=response_mode or _OUTER_ROUTE_CLARIFY)
        return _state_delta(before, after, always_include={"response_route"})
    if normalized_mode == ResponseMode.FALLBACK or response_mode in {_OUTER_ROUTE_FALLBACK}:
        if not str(state.get("final_response", "") or "").strip():
            if _response_text_from_state(state):
                working = _run_step(state, _h_final_response)
            else:
                working = _run_step(state, _h_fallback_answer)
                if not str(working.get("final_response", "") or "").strip():
                    working = {**working, **_h_final_response(working)}
        else:
            working = dict(state)
        after = {**working, "response_route": _OUTER_ROUTE_FALLBACK_READY}
        log_kv(_LOGGER, logging.WARNING, "[ROUTE_DECISION]", tone="warn", subgraph="response_subgraph", route=_OUTER_ROUTE_FALLBACK_READY, response_mode=response_mode)
        return _state_delta(before, after, always_include={"response_route"})
    if normalized_mode is None and response_mode:
        log_kv(_LOGGER, logging.WARNING, "[ROUTE_DECISION]", tone="warn", subgraph="response_subgraph", route=_OUTER_ROUTE_FALLBACK_READY, response_mode=response_mode, reason="invalid_response_mode")
        after = {**state, "response_route": _OUTER_ROUTE_FALLBACK_READY, "fallback_reason": str(state.get("fallback_reason", "") or "invalid_response_mode")}
        if not str(state.get("final_response", "") or "").strip():
            if _response_text_from_state(state):
                working = _run_step(state, _h_final_response)
            else:
                working = _run_step(state, _h_fallback_answer)
                if not str(working.get("final_response", "") or "").strip():
                    working = {**working, **_h_final_response(working)}
            after = {**working, "response_route": _OUTER_ROUTE_FALLBACK_READY}
        return _state_delta(before, after, always_include={"response_route"})

    working = _run_step(state, _h_answer_plan_build)
    budget = budget_context_from_state(state)
    execution_budget = execution_budget_from_state(state)
    rewrite_budget = budget.remaining("rewrite_budget")
    rewrite_limit = max(0, min(int(_GRAPH_REWRITE_LIMIT or 0), int(rewrite_budget), int(execution_budget.max_rewrite_rounds or 0)))
    working = {**working, "rewrite_limit": rewrite_limit}
    while True:
        working = _run_step(working, _h_answer_generate)
        working = _run_step(working, _h_answer_verify)
        verify_result = str(working.get("verify_result", "") or "")
        if verify_result == "pass":
            working = _run_step(working, _h_final_response)
            after = {**working, "response_route": _OUTER_ROUTE_PASS}
            log_kv(_LOGGER, logging.INFO, "[ROUTE_DECISION]", tone="route", subgraph="response_subgraph", route=_OUTER_ROUTE_PASS, verify_result=verify_result)
            return _state_delta(before, after, always_include={"response_route"})
        if not bool(working.get("rewrite_needed", True)) or not bool(working.get("verifier_recoverable", True)):
            working = _run_step(working, _h_fallback_answer)
            after = {**working, "response_route": _OUTER_ROUTE_FALLBACK_READY}
            log_kv(_LOGGER, logging.WARNING, "[ROUTE_DECISION]", tone="warn", subgraph="response_subgraph", route=_OUTER_ROUTE_FALLBACK_READY, verify_result=verify_result, rewrite_needed=working.get("rewrite_needed", False), verifier_recoverable=working.get("verifier_recoverable", False))
            return _state_delta(before, after, always_include={"response_route"})
        rewrite_count = int(working.get("rewrite_count", 0) or 0)
        if rewrite_count >= rewrite_limit:
            working = _run_step(working, _h_fallback_answer)
            after = {**working, "response_route": _OUTER_ROUTE_FALLBACK_READY}
            log_kv(_LOGGER, logging.WARNING, "[ROUTE_DECISION]", tone="warn", subgraph="response_subgraph", route=_OUTER_ROUTE_FALLBACK_READY, verify_result=verify_result, rewrite_count=rewrite_count)
            return _state_delta(before, after, always_include={"response_route"})
        working = _run_step(working, _h_rewrite)
        rewrite_route = str(working.get("rewrite_route", working.get("rewrite_mode", "")) or "")
        if rewrite_route == "trusted_fallback":
            working = _run_step(working, _h_fallback_answer)
            after = {**working, "response_route": _OUTER_ROUTE_FALLBACK_READY}
            log_kv(
                _LOGGER,
                logging.WARNING,
                "[ROUTE_DECISION]",
                tone="warn",
                subgraph="response_subgraph",
                route=_OUTER_ROUTE_FALLBACK_READY,
                verify_result=verify_result,
                rewrite_count=rewrite_count,
                rewrite_route=rewrite_route,
            )
            return _state_delta(before, after, always_include={"response_route"})


# ---------------------------------------------------------------------------
# Internal step handlers
# ---------------------------------------------------------------------------


def _h_answer_plan_build(state: GraphState) -> dict:
    p2_dp = state.get("p2_decision_plan")
    answer_plan_payload = decision_to_answer_plan(p2_dp, state.get("evidence_pack") or {}) if p2_dp is not None else {}
    answer_plan = AnswerPlan.model_validate(answer_plan_payload)
    return {
        "answer_plan": answer_plan,
        **_log(state, "answer_plan_build", answer_plan_source="decision_plan", has_decision_plan=p2_dp is not None),
    }


def _h_answer_generate(state: GraphState) -> dict:
    # lazy-import via graph_builder for test monkeypatch compat
    from ..graph_builder import generate_answer as _generate_answer
    answer_plan = state.get("answer_plan")
    if answer_plan is None:
        answer_plan = AnswerPlan.model_validate(
            decision_to_answer_plan(state.get("p2_decision_plan"), state.get("evidence_pack") or {})
        )
    metadata: dict[str, Any] = {}
    rc = state.get("rewrite_count", 0)
    violations = state.get("answer_verify_violations") or []

    cc = _build_conversation_continuity(state)

    txt = _generate_answer(
        answer_plan,
        state.get("evidence_pack") or {},
        metadata_out=metadata,
        rewrite_count=rc,
        previous_violations=violations,
        rewrite_instruction=state.get("rewrite_instruction"),
        rewrite_mode=str(state.get("rewrite_mode", "") or ""),
        in_graph=True,
        conversation_continuity=cc,
    )
    answer_type = str(getattr(answer_plan, "answer_type", "") or "")
    if answer_type in {"single_shop", "single_shop_query"}:
        generic_markers = (
            "我会优先参考当前结果来回答。",
            "当前信息还不够完整，我暂时无法确认当前结果的全部细节。",
            "这项信息我已经按当前查询结果整理好了。",
            "抱歉，暂时无法处理您的请求，请稍后再试。",
            "当前已知信息还不够完整，我暂时无法确认哪家更好。",
        )
        if not txt.strip() or any(marker in txt for marker in generic_markers):
            txt = _compose_single_shop_response(state.get("evidence_pack") or {}, txt)
    preview_text = sanitize_preview_text(txt, verified=False)
    fallback_reason = str(state.get("fallback_reason", "") or metadata.get("fallback_reason", "") or "")
    answer_fallback_reason = str(state.get("answer_fallback_reason", "") or metadata.get("answer_fallback_reason", "") or "")
    if (
        answer_type == "clarification"
        or str(state.get("response_mode", "") or "") == ResponseMode.CLARIFY.value
        or state.get("pending_clarification") is not None
    ):
        if fallback_reason in _DIAGNOSTIC_FALLBACK_REASONS:
            fallback_reason = ""
        if answer_fallback_reason in _DIAGNOSTIC_FALLBACK_REASONS:
            answer_fallback_reason = ""
    response_directive = build_response_directive(
        answer_text=txt,
        answer_type=answer_type,
        response_mode=str(state.get("response_mode", "") or ""),
        fallback_reason=answer_fallback_reason or fallback_reason,
        trace_id=str(state.get("trace_id", "") or ""),
        preview_text=preview_text,
        answer_source=metadata.get("answer_source", "llm_verbalizer"),
        fallback_template_type=str(getattr(answer_plan, "fallback_template_type", "") or ""),
        metadata=metadata,
    )
    return {
        "answer_plan": answer_plan,
        "draft_response": txt,
        "response_directive": response_directive,
        "preview_text": preview_text,
        "preview_policy_result": {
            "verified": False,
            "allowed": bool(preview_text.strip()),
            "reason": "" if preview_text.strip() else "blocked_unverified_claim",
        },
        "answer_source": metadata.get("answer_source", "llm_verbalizer"),
        "template_degraded": metadata.get("template_degraded", False),
        "fallback_used": metadata.get("fallback_used", False),
        "template_fallback_used": metadata.get("template_fallback_used", False),
        "answer_fallback_reason": answer_fallback_reason,
        "llm_verbalizer_error": metadata.get("llm_verbalizer_error"),
        "generated_llm_answer_before_fallback": metadata.get("generated_llm_answer_before_fallback", ""),
        "llm_structured_claims": metadata.get("llm_structured_claims", []),
        "llm_verbalizer_violation": metadata.get("violation"),
        "llm_verbalizer_called": metadata.get("llm_verbalizer_called", True),
        "llm_backend": metadata.get("llm_backend", ""),
        "answer_verifier_result": metadata.get("answer_verifier_result", "unknown"),
        "verifier_result": metadata.get("verifier_result", metadata.get("answer_verifier_result", "unknown")),
        "verifier_failure_code": metadata.get("verifier_failure_code", metadata.get("violation", "")),
        "verifier_unknown_fields": metadata.get("verifier_unknown_fields", []),
        "verifier_unsupported_claims": metadata.get("verifier_unsupported_claims", []),
        "verifier_false_fields": metadata.get("verifier_false_fields", []),
        "verifier_recoverable": metadata.get("verifier_recoverable", False),
        "answer_verify_passed": metadata.get("answer_verify_passed", True),
        "answer_verify_violations": metadata.get("answer_verify_violations") or [],
        "rewrite_needed": metadata.get("rewrite_needed", False),
        "rewrite_reason": metadata.get("rewrite_reason", ""),
        "fallback_reason": fallback_reason,
        "raw_text_fallback_source": metadata.get("raw_text_fallback_source", answer_fallback_reason or fallback_reason),
        "final_safety_status": metadata.get("final_safety_status", "safe"),
        **_log(state, "answer_generate", answer_source=metadata.get("answer_source", "template_fallback"),
              rewrite_count=rc, fallback_reason=fallback_reason,
              template_degraded=metadata.get("template_degraded", False),
              fallback_used=metadata.get("fallback_used", False)),
    }


def _verify_answer_with_context(
    answer: str,
    evidence: Any,
    task_type: str,
    *,
    answer_source: str,
    extracted_claims: list[dict[str, Any]],
) -> dict:
    try:
        signature = inspect.signature(verify_answer)
        supports_kwargs = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values())
        supports_l3 = "answer_source" in signature.parameters and "extracted_claims" in signature.parameters
    except (TypeError, ValueError):
        supports_kwargs = False
        supports_l3 = False
    if supports_kwargs or supports_l3:
        return verify_answer(
            answer,
            evidence,
            task_type,
            answer_source=answer_source,
            extracted_claims=extracted_claims,
        )
    return verify_answer(answer, evidence, task_type)


def _h_answer_verify(state: GraphState) -> dict:
    evidence = state.get("evidence_pack") or {}
    evidence_dict = _to_dict(evidence)
    answer_plan = state.get("answer_plan")
    task_type = getattr(state.get("execution_plan"), "task_type", "") or (
        state.get("execution_plan", {}).get("task_type", "") if isinstance(state.get("execution_plan"), dict) else ""
    )
    if not evidence or not str(state.get("draft_response", "") or "").strip():
        report = _verify_answer_with_context(
            str(state.get("draft_response", "") or ""),
            evidence,
            task_type,
            answer_source=str(state.get("answer_source", "") or ""),
            extracted_claims=_as_list_of_dicts(state.get("llm_structured_claims")),
        )
        recoverable = bool(report.get("recoverable", False))
        violation_codes = list(report.get("issues") or [])
        rewrite_instruction = RewriteInstruction.from_verifier_report(
            report,
            plan=answer_plan if isinstance(answer_plan, AnswerPlan) else None,
            fallback_mode="rewrite" if recoverable else "fallback",
            tone="neutral",
        )
        return {
            "verify_result": "rewrite_needed" if recoverable else "fallback",
            "error_code": "ANSWER_VERIFIER_FAILED",
            "error_message": report.get("suggested_fix", ""),
            "answer_verify_passed": False,
            "answer_verify_violations": violation_codes,
            "rewrite_needed": recoverable,
            "rewrite_reason": str(report.get("failure_code") or (violation_codes or ["empty_evidence_or_draft"])[0]),
            "rewrite_instruction": rewrite_instruction,
            "rewrite_mode": "trusted_fallback" if not recoverable else _rewrite_route_from_instruction(
                answer_plan if isinstance(answer_plan, AnswerPlan) else AnswerPlan(),
                rewrite_instruction,
                rewrite_count=int(state.get("rewrite_count", 0) or 0),
                rewrite_limit=int(state.get("rewrite_limit", 0) or 0) or 1,
            ),
            "verifier_result": "fail",
            "verifier_failure_code": str(report.get("failure_code") or (report.get("issues") or ["empty_evidence_or_draft"])[0]),
            "verifier_unknown_fields": report.get("verifier_unknown_fields", report.get("unknown_fields", [])),
            "verifier_unsupported_claims": report.get("verifier_unsupported_claims", report.get("unsupported_claims", [])),
            "verifier_false_fields": report.get("verifier_false_fields", report.get("false_fields", [])),
            "verifier_recoverable": recoverable,
            "answer_claim_results": report.get("claim_results", []),
            "answer_expected_claims": report.get("expected_claims", []),
            "answer_claim_extractor": report.get("claim_extractor", ""),
            **_log(state, "answer_verify", passed=False, failure_code=report.get("failure_code", "empty_evidence_or_draft")),
        }
    if str(state.get("answer_source", "") or "") in {"template_fallback", "llm_disabled"}:
        return {
            "verify_result": "pass",
            "error_code": "",
            "error_message": "",
            "answer_verify_passed": True,
            "answer_verify_violations": [],
            "rewrite_needed": False,
            "verifier_result": "pass",
            "verifier_failure_code": "",
            "verifier_unknown_fields": [],
            "verifier_unsupported_claims": [],
            "verifier_false_fields": [],
            "verifier_recoverable": True,
            **_log(state, "answer_verify", passed=True, skipped_reason="template_fallback"),
        }
    report = _verify_answer_with_context(
        state.get("draft_response", ""),
        evidence,
        task_type,
        answer_source=str(state.get("answer_source", "") or ""),
        extracted_claims=_as_list_of_dicts(state.get("llm_structured_claims")),
    )
    passed = report.get("passed", False)
    violations = report.get("issues", [])
    rewrite_instruction = RewriteInstruction.from_verifier_report(
        report,
        plan=answer_plan if isinstance(answer_plan, AnswerPlan) else None,
        fallback_mode="rewrite" if bool(report.get("recoverable", not passed)) else "fallback",
        tone="neutral",
    )
    rewrite_count = int(state.get("rewrite_count", 0) or 0)
    rewrite_limit = int(state.get("rewrite_limit", 0) or 0) or 1
    rewrite_mode = _rewrite_strategy_from_instruction(
        answer_plan if isinstance(answer_plan, AnswerPlan) else AnswerPlan(),
        rewrite_instruction,
        rewrite_count=rewrite_count,
        rewrite_limit=rewrite_limit,
    )

    snapshot = evidence_dict.get("ranking_snapshot") or {}
    ranked = snapshot.get("ranked") or snapshot.get("ranked_shops") or snapshot.get("shops") or []
    fr = evidence_dict.get("facet_results") or snapshot.get("facet_results") or []
    log_kv(
        _LOGGER,
        logging.INFO if passed else logging.WARNING,
        "[ANSWER_VERIFY]",
        tone="route" if passed else "warn",
        passed=passed,
        task_type=task_type,
        violations=violations,
        draft_preview=state.get("draft_response", "")[:200],
        evidence_items=len(evidence_dict.get("evidence_items") or []),
        ranked_preview=ranked[:5],
        facet_results_preview=fr[:10],
    )

    return {
        "verify_result": "pass" if passed else "rewrite_needed",
        "error_code": "" if passed else "ANSWER_VERIFIER_FAILED",
        "error_message": "" if passed else report.get("suggested_fix", ""),
        "answer_verify_passed": passed,
        "answer_verify_violations": violations,
        "rewrite_needed": not passed,
        "rewrite_reason": violations[0] if violations else "",
        "rewrite_instruction": rewrite_instruction,
        "rewrite_mode": rewrite_mode,
        "verifier_result": "pass" if passed else "fail",
        "verifier_failure_code": report.get("failure_code") or (violations[0] if violations else ""),
        "verifier_unknown_fields": report.get("verifier_unknown_fields", report.get("unknown_fields", [])),
        "verifier_unsupported_claims": report.get("verifier_unsupported_claims", report.get("unsupported_claims", [])),
        "verifier_false_fields": report.get("verifier_false_fields", report.get("false_fields", [])),
        "verifier_recoverable": bool(report.get("recoverable", not passed)),
        "answer_claim_results": report.get("claim_results", []),
        "answer_expected_claims": report.get("expected_claims", []),
        "answer_claim_extractor": report.get("claim_extractor", ""),
        **_log(state, "answer_verify", passed=passed, violations=violations,
              final_safety_status="safe" if passed else "violated"),
    }


def _h_rewrite(state: GraphState) -> dict:
    rc = state.get("rewrite_count", 0) + 1
    answer_plan = state.get("answer_plan")
    rewrite_limit = int(state.get("rewrite_limit", 0) or 0) or _GRAPH_REWRITE_LIMIT
    rewrite_instruction = state.get("rewrite_instruction")
    rewrite_mode = _rewrite_route_from_instruction(
        answer_plan if isinstance(answer_plan, AnswerPlan) else AnswerPlan(),
        rewrite_instruction,
        rewrite_count=rc,
        rewrite_limit=int(rewrite_limit or 0) or 1,
    )
    txt = str(state.get("draft_response", "") or "").strip()
    if not txt:
        directive = _to_response_directive(state.get("response_directive"))
        if directive is not None:
            txt = str(directive.answer_text or directive.preview_text or directive.final_response or "").strip()
    patch: dict[str, Any] = {
        "draft_response": txt,
        "rewrite_count": rc,
        "rewrite_mode": rewrite_mode,
        "rewrite_strategy": rewrite_mode,
        "rewrite_route": rewrite_mode,
    }
    if rewrite_instruction is not None:
        patch["rewrite_instruction"] = rewrite_instruction
    patch["rewrite_reason"] = str(state.get("rewrite_reason", "") or state.get("verifier_failure_code", "") or state.get("error_message", "") or "")
    patch.update(_log(state, "rewrite", rewrite_count=rc))
    return patch


def _h_final_response(state: GraphState) -> dict:
    txt = _response_text_from_state(state)
    directive = _to_response_directive(state.get("response_directive"))
    if directive is not None and not str(directive.final_response or "").strip():
        directive = directive.model_copy(update={"final_response": txt, "preview_text": directive.preview_text or txt})
    elif directive is None:
        directive = build_response_directive(
            answer_text=txt,
            answer_type=str(getattr(state.get("answer_plan"), "answer_type", "") or ""),
            response_mode=str(state.get("response_mode", "") or ""),
            fallback_reason=str(state.get("fallback_reason", "") or ""),
            trace_id=str(state.get("trace_id", "") or ""),
            final_response=txt,
            preview_text=txt,
            answer_source=str(state.get("answer_source", "") or ""),
            fallback_template_type=str(getattr(state.get("answer_plan"), "fallback_template_type", "") or ""),
        )
    fallback_reason = str(state.get("fallback_reason", "") or directive.fallback_reason or "")
    contract_v2 = _build_response_contract_v2(
        state,
        directive,
        answer_text=txt,
        preview_text=txt,
        fallback_reason=fallback_reason,
    )
    contract = contract_v2.to_v1(
        verifier_result=str(state.get("verifier_result", "") or ""),
        fallback_reason=fallback_reason,
        uncertainty_notices=[
            str(item).strip()
            for item in (
                getattr(state.get("answer_plan"), "uncertainty_notes", []) or []
            )
            if str(item).strip()
        ],
        metadata={
            "workflow_name": str(state.get("workflow_name", "") or ""),
            "answer_source": str(state.get("answer_source", "") or ""),
            "response_contract_v2": contract_v2.model_dump(),
        },
    )
    return {
        "final_response": txt,
        "preview_text": txt,
        "response_directive": directive,
        "response_contract_v1": contract,
        "response_contract_v2": contract_v2,
        "preview_policy_result": {
            "verified": True,
            "allowed": True,
            "reason": "verified",
        },
        **_log(state, "final_response_build", answer_source=state.get("answer_source", ""),
              final_safety_status=state.get("final_safety_status", "safe")),
    }


def _clarify_answer_source(state: GraphState) -> str:
    workflow_name = str(state.get("workflow_name", "") or "")
    if workflow_name == "clarification_fallback" or str(state.get("response_mode", "") or "") == "clarify":
        return "clarification_fallback_workflow"
    pending = state.get("pending_clarification")
    pending_source = ""
    if isinstance(pending, dict):
        pending_source = str(pending.get("source_node", "") or "")
    else:
        pending_source = str(getattr(pending, "source_node", "") or "")
    if pending_source == "deterministic_tool_workflow":
        return "clarification_fallback_workflow"
    return "clarify_message"


def _h_clarify_response(state: GraphState) -> dict:
    from ...target.clarification import build_pending_clarification, format_pending_prompt

    answer_source = _clarify_answer_source(state)
    pending_result = str(state.get("pending_check_result", "") or "")
    if pending_result in {"expired", "invalid", "out_of_range"} and str(state.get("final_response", "") or "").strip():
        error_envelope = {
            "error_code": f"pending_{pending_result}",
            "message": str(state.get("final_response", "") or ""),
            "severity": "warning",
            "recoverable": True,
            "source_stage": "response_subgraph",
            "trace_id": str(state.get("trace_id", "") or ""),
        }
        return {
            "draft_response": state.get("final_response", ""),
            "response_directive": build_early_response_directive(
                answer_text=str(state.get("final_response", "") or ""),
                answer_type="clarification",
                response_mode="clarify",
                reason=pending_result,
                fallback_reason="expired_pending_clarification",
                trace_id=str(state.get("trace_id", "") or ""),
                answer_source=answer_source,
                error_envelope=error_envelope,
            ),
            "answer_source": answer_source, "template_degraded": True,
            "fallback_used": True, "template_fallback_used": False,
            **_log(state, "clarify_response"),
        }
    pending = state.get("pending_clarification")
    if pending is None:
        candidate_targets: list[dict[str, Any]] = []

        def _append_candidate(source: Any) -> None:
            if not source:
                return
            if isinstance(source, dict):
                source = source.get("candidate_targets") or source.get("targets") or source.get("candidates") or []
            if not isinstance(source, list):
                return
            for item in source:
                item_dict = _to_dict(item)
                shop = _to_dict(item_dict.get("resolved_shop") or item_dict.get("shop") or item_dict)
                shop_id = str(shop.get("shop_id", "") or "").strip()
                shop_name = str(shop.get("shop_name", "") or "").strip()
                if not shop_id and not shop_name:
                    continue
                key = (shop_id, shop_name)
                if any((str(existing.get("shop_id", "") or "").strip(), str(existing.get("shop_name", "") or "").strip()) == key for existing in candidate_targets):
                    continue
                candidate_targets.append(
                    {
                        "shop_id": shop_id,
                        "shop_name": shop_name,
                        "address": str(shop.get("address", "") or item_dict.get("address", "") or "").strip(),
                    }
                )

        _append_candidate(state.get("comparison_target_resolution"))
        _append_candidate(state.get("resolve_shop_result"))
        _append_candidate(state.get("comparison_targets"))
        _append_candidate(_to_dict(state.get("semantic_frame")).get("comparison_targets"))
        _append_candidate(state.get("last_recommendation_list"))
        if candidate_targets:
            task_type_value = str(state.get("task_type", "") or _to_dict(state.get("semantic_frame")).get("task_type", "") or "")
            reason = "response_subgraph_clarify"
            source_node = "response_subgraph"
            if str(state.get("comparison_target_resolution") and _to_dict(state.get("comparison_target_resolution")).get("status", "") or "").upper() in {"NEED_CLARIFICATION", "PARTIAL", "AMBIGUOUS", "NOT_FOUND", "TOO_MANY"}:
                reason = str(_to_dict(state.get("comparison_target_resolution")).get("reason", "") or "comparison_targets_need_clarification")
                task_type_value = "comparison"
            elif str(getattr(state.get("resolve_shop_result"), "status", "") or _to_dict(state.get("resolve_shop_result")).get("status", "") or "").upper() in {"AMBIGUOUS", "LOW_CONFIDENCE"}:
                reason = str(getattr(state.get("resolve_shop_result"), "reason", "") or _to_dict(state.get("resolve_shop_result")).get("reason", "") or "shop_resolution_need_clarification")
            try:
                pending = build_pending_clarification(
                    original_text=str(state.get("raw_text", "") or state.get("normalized_text", "") or ""),
                    original_semantic_frame=_to_dict(state.get("semantic_frame")),
                    original_task_type=task_type_value or "single_shop_query",
                    candidate_targets=candidate_targets,
                    reason=reason,
                    source_node=source_node,
                )
            except Exception:
                pending = None
    if pending is not None:
        try:
            prompt = format_pending_prompt(pending)
        except Exception:
            prompt = "店名有点模糊，请提供完整店名。"
        clarification_request = None
        try:
            clarification_request = build_clarification_request(pending, question=prompt, source_stage="response_subgraph")
        except Exception:
            clarification_request = None
        if prompt.strip():
            return {
                "draft_response": prompt,
                "pending_clarification": pending,
                "response_directive": build_early_response_directive(
                    answer_text=prompt,
                    answer_type="clarification",
                    response_mode="clarify",
                    reason=str(getattr(pending, "reason", "") or ""),
                    fallback_reason="pending_clarification",
                    trace_id=str(state.get("trace_id", "") or ""),
                    answer_source=answer_source,
                    clarification_request=clarification_request,
                ),
                "answer_source": answer_source,
                "template_degraded": True, "fallback_used": True, "template_fallback_used": False,
                **_log(state, "clarify_response"),
            }
    rs = state.get("resolve_shop_result")
    if rs is not None and getattr(rs, "status", "") in ("AMBIGUOUS", "LOW_CONFIDENCE"):
        error_envelope = {
            "error_code": "ambiguous_shop",
            "message": "店名有点模糊，请提供完整店名。",
            "severity": "warning",
            "recoverable": True,
            "source_stage": "response_subgraph",
            "trace_id": str(state.get("trace_id", "") or ""),
        }
        return {
            "draft_response": "店名有点模糊，请提供完整店名。",
            "response_directive": build_early_response_directive(
                answer_text="店名有点模糊，请提供完整店名。",
                answer_type="clarification",
                response_mode="clarify",
                reason="ambiguous_shop",
                fallback_reason="ambiguous_shop",
                trace_id=str(state.get("trace_id", "") or ""),
                answer_source=answer_source,
                error_envelope=error_envelope,
            ),
            "answer_source": answer_source,
            "template_degraded": True,
            "fallback_used": True, "template_fallback_used": False,
            **_log(state, "clarify_response"),
        }
    clarification = (state.get("error_message", "") or "").strip()
    if clarification:
        error_envelope = {
            "error_code": str(state.get("error_code", "") or "clarification_needed"),
            "message": clarification,
            "severity": "warning",
            "recoverable": True,
            "source_stage": "response_subgraph",
            "trace_id": str(state.get("trace_id", "") or ""),
        }
        return {
            "draft_response": clarification,
            "response_directive": build_early_response_directive(
                answer_text=clarification,
                answer_type="clarification",
                response_mode="clarify",
                reason=str(state.get("error_code", "") or "error_message"),
                fallback_reason="error_message",
                trace_id=str(state.get("trace_id", "") or ""),
                answer_source=answer_source,
                error_envelope=error_envelope,
            ),
            "answer_source": answer_source,
            "template_degraded": True, "fallback_used": True, "template_fallback_used": False,
            **_log(state, "clarify_response"),
        }
    return {
        "draft_response": "请提供完整店名。",
        "response_directive": build_early_response_directive(
            answer_text="请提供完整店名。",
            answer_type="clarification",
            response_mode="clarify",
            reason="missing_shop_name",
            fallback_reason="missing_shop_name",
            trace_id=str(state.get("trace_id", "") or ""),
            answer_source=answer_source,
        ),
        "answer_source": answer_source,
        "template_degraded": True,
        "fallback_used": True, "template_fallback_used": False,
        **_log(state, "clarify_response"),
    }


def _h_fallback_answer(state: GraphState) -> dict:
    response = "抱歉，暂时无法处理您的请求，请稍后再试。"
    evidence_dict = _to_dict(state.get("evidence_pack") or {})
    snapshot = evidence_dict.get("ranking_snapshot") or {}
    status = str(snapshot.get("status", "") or "") if isinstance(snapshot, dict) else ""
    task_type = str(state.get("task_type", "") or getattr(state.get("execution_plan"), "task_type", "") or "")
    shop_name = str(snapshot.get("shop_name", "") or "").strip()
    if not shop_name:
        for item in evidence_dict.get("evidence_items") or []:
            if isinstance(item, dict) and str(item.get("shop_name", "") or "").strip():
                shop_name = str(item.get("shop_name", "") or "").strip()
                break
    facet_results = evidence_dict.get("facet_results") or snapshot.get("facet_results") or []
    coupon_titles: list[str] = []
    coupon_available = False
    for facet_item in facet_results:
        facet_dict = facet_item if isinstance(facet_item, dict) else _to_dict(facet_item)
        if str(facet_dict.get("facet", "") or "") != "coupon":
            continue
        if str(facet_dict.get("status", "") or "") == "ok":
            coupon_available = True
            values = facet_dict.get("value") or []
            if isinstance(values, list):
                for value in values[:3]:
                    value_text = str(value).strip()
                    if value_text:
                        coupon_titles.append(value_text)
            break
    if task_type in {"single_shop_query", "open_status_query"} and shop_name:
        for facet_item in facet_results:
            facet_dict = facet_item if isinstance(facet_item, dict) else _to_dict(facet_item)
            if str(facet_dict.get("facet", "") or "") != "open_status":
                continue
            if str(facet_dict.get("status", "") or "") != "ok":
                break
            raw_value = facet_dict.get("value")
            if isinstance(raw_value, dict):
                raw_value = raw_value.get("open_status", raw_value.get("status", ""))
            status_text = str(raw_value or "").strip().lower()
            if status_text in {"open", "opened", "营业中", "open_now", "openstatusopen"}:
                response = f"{shop_name}当前营业中。"
            elif status_text in {"closed", "close", "closed_now", "not_open", "关闭"}:
                response = f"{shop_name}当前未营业。"
            else:
                response = f"{shop_name}的营业状态暂时无法确认。"
            break
    if task_type in {"single_shop_query", "coupon_query"} and shop_name and coupon_available:
        if coupon_titles:
            response = f"{shop_name}有券，当前可用券包括：{'、'.join(coupon_titles)}。"
        else:
            response = f"{shop_name}有券。"
    if not status:
        tr = state.get("tool_result_set") or state.get("tool_results", {})
        for result in tr.values():
            value = result.result_status.value if hasattr(result, "result_status") else str(_to_dict(result).get("result_status", ""))
            status = value
            if value in ("failed", "circuit_open", "unknown", "unsupported"):
                break
    if status == "circuit_open":
        response = "相关服务暂时不可用，请稍后再试。"
    elif status == "failed":
        response = "查询失败，建议稍后再试。"
    elif status in {"unknown", "unsupported"}:
        response = "暂时无法确认相关信息，请稍后再试。"
    return {
        "draft_response": response,
        "response_directive": build_response_directive(
            answer_text=response,
            response_mode="fallback",
            fallback_reason="trusted_failure_message",
            trace_id=str(state.get("trace_id", "") or ""),
            answer_source="trusted_failure_message",
        ),
        "answer_source": "trusted_failure_message",
        "template_degraded": True, "fallback_used": True, "template_fallback_used": False,
        "final_safety_status": "fallback",
        **_log(state, "fallback_answer"),
    }
