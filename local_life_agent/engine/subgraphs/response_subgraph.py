"""response_subgraph — answer generation, verification, and fallback.

Generates the final answer via LLM verbalizer, verifies it against evidence,
rewrites if needed, and handles clarification / fallback responses.
"""

from __future__ import annotations

import logging
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
from ...domain.graph_state import GraphState
from ...domain.schemas import AnswerPlan
from ...domain.decision import decision_to_answer_plan
from ...answer.verifier import verify_answer
from ...domain.state import SessionState
from ...planning.budget.budget_context import budget_context_from_state
from ...streaming.preview_policy import sanitize_preview_text
from ...observability.file_logger import get_python_service_logger, log_kv

_LOGGER = get_python_service_logger()


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

    parts: list[str] = []
    if open_text:
        parts.append(open_text)
    if coupon_text:
        parts.append(coupon_text)
    if distance_text:
        parts.append(distance_text)

    if parts:
        response = f"{shop_name}: {'; '.join(parts)}"
    else:
        response = draft_text.strip() or f"{shop_name}的信息我已经整理好了。"

    if uncertain_notes:
        response += "；" + "；".join(dict.fromkeys(uncertain_notes))

    return response


def h_response_subgraph(state: GraphState) -> dict:
    """Outer wrapper: handle response mode → generate / clarify / fallback."""
    before = dict(state)
    response_mode = str(state.get("response_mode", "") or "")
    log_kv(_LOGGER, logging.INFO, "[SUBGRAPH_ENTER]", tone="route", subgraph="response_subgraph", trace_id=state.get("trace_id", ""), response_mode=response_mode)
    if response_mode in {_OUTER_ROUTE_DIRECT, _OUTER_ROUTE_REJECT, "direct_response", "exploration_plan"}:
        after = {**state, "response_route": _OUTER_ROUTE_PASS}
        log_kv(_LOGGER, logging.INFO, "[ROUTE_DECISION]", tone="route", subgraph="response_subgraph", route=_OUTER_ROUTE_PASS, response_mode=response_mode)
        return _state_delta(before, after, always_include={"response_route"})
    if response_mode in {_OUTER_ROUTE_CLARIFY} or state.get("pending_clarification") is not None:
        if not str(state.get("final_response", "") or "").strip():
            working = _run_step(state, _h_clarify_response)
        else:
            working = dict(state)
        after = {**working, "response_route": _OUTER_ROUTE_CLARIFY_READY}
        log_kv(_LOGGER, logging.INFO, "[ROUTE_DECISION]", tone="route", subgraph="response_subgraph", route=_OUTER_ROUTE_CLARIFY_READY, response_mode=response_mode or _OUTER_ROUTE_CLARIFY)
        return _state_delta(before, after, always_include={"response_route"})
    if response_mode in {_OUTER_ROUTE_FALLBACK}:
        if not str(state.get("final_response", "") or "").strip():
            working = _run_step(state, _h_fallback_answer)
        else:
            working = dict(state)
        after = {**working, "response_route": _OUTER_ROUTE_FALLBACK_READY}
        log_kv(_LOGGER, logging.WARNING, "[ROUTE_DECISION]", tone="warn", subgraph="response_subgraph", route=_OUTER_ROUTE_FALLBACK_READY, response_mode=response_mode)
        return _state_delta(before, after, always_include={"response_route"})

    working = _run_step(state, _h_answer_plan_build)
    budget = budget_context_from_state(state)
    rewrite_budget = budget.remaining("rewrite_budget")
    rewrite_limit = max(0, min(int(_GRAPH_REWRITE_LIMIT or 0), int(rewrite_budget)))
    while True:
        working = _run_step(working, _h_answer_generate)
        working = _run_step(working, _h_answer_verify)
        verify_result = str(working.get("verify_result", "") or "")
        if verify_result == "pass":
            working = _run_step(working, _h_final_response)
            after = {**working, "response_route": _OUTER_ROUTE_PASS}
            log_kv(_LOGGER, logging.INFO, "[ROUTE_DECISION]", tone="route", subgraph="response_subgraph", route=_OUTER_ROUTE_PASS, verify_result=verify_result)
            return _state_delta(before, after, always_include={"response_route"})
        rewrite_count = int(working.get("rewrite_count", 0) or 0)
        if rewrite_count >= rewrite_limit:
            working = _run_step(working, _h_fallback_answer)
            after = {**working, "response_route": _OUTER_ROUTE_FALLBACK_READY}
            log_kv(_LOGGER, logging.WARNING, "[ROUTE_DECISION]", tone="warn", subgraph="response_subgraph", route=_OUTER_ROUTE_FALLBACK_READY, verify_result=verify_result, rewrite_count=rewrite_count)
            return _state_delta(before, after, always_include={"response_route"})
        working = _run_step(working, _h_rewrite)


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
    return {
        "answer_plan": answer_plan,
        "draft_response": txt,
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
        "answer_fallback_reason": metadata.get("answer_fallback_reason", ""),
        "llm_verbalizer_error": metadata.get("llm_verbalizer_error"),
        "generated_llm_answer_before_fallback": metadata.get("generated_llm_answer_before_fallback", ""),
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
        "fallback_reason": metadata.get("fallback_reason", ""),
        "raw_text_fallback_source": metadata.get("raw_text_fallback_source", metadata.get("answer_fallback_reason", "")),
        "final_safety_status": metadata.get("final_safety_status", "safe"),
        **_log(state, "answer_generate", answer_source=metadata.get("answer_source", "template_fallback"),
              rewrite_count=rc, fallback_reason=metadata.get("fallback_reason", ""),
              template_degraded=metadata.get("template_degraded", False),
              fallback_used=metadata.get("fallback_used", False)),
    }


def _h_answer_verify(state: GraphState) -> dict:
    evidence = state.get("evidence_pack") or {}
    evidence_dict = _to_dict(evidence)
    task_type = getattr(state.get("execution_plan"), "task_type", "") or (
        state.get("execution_plan", {}).get("task_type", "") if isinstance(state.get("execution_plan"), dict) else ""
    )
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
    if not evidence or not state.get("draft_response", ""):
        return {
            "verify_result": "pass", "error_code": "", "error_message": "",
            "answer_verify_passed": True, "answer_verify_violations": [],
            "rewrite_needed": False, "verifier_result": "pass", "verifier_failure_code": "",
            "verifier_unknown_fields": [], "verifier_unsupported_claims": [],
            "verifier_false_fields": [], "verifier_recoverable": True,
            **_log(state, "answer_verify"),
        }
    report = verify_answer(state.get("draft_response", ""), evidence, task_type)
    passed = report.get("passed", False)
    violations = report.get("issues", [])

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
        "verifier_result": "pass" if passed else "fail",
        "verifier_failure_code": report.get("failure_code") or (violations[0] if violations else ""),
        "verifier_unknown_fields": report.get("verifier_unknown_fields", report.get("unknown_fields", [])),
        "verifier_unsupported_claims": report.get("verifier_unsupported_claims", report.get("unsupported_claims", [])),
        "verifier_false_fields": report.get("verifier_false_fields", report.get("false_fields", [])),
        "verifier_recoverable": bool(report.get("recoverable", not passed)),
        **_log(state, "answer_verify", passed=passed, violations=violations,
              final_safety_status="safe" if passed else "violated"),
    }


def _h_rewrite(state: GraphState) -> dict:
    rc = state.get("rewrite_count", 0) + 1
    txt = state.get("draft_response", "")
    return {"draft_response": txt, "rewrite_count": rc, **_log(state, "rewrite", rewrite_count=rc)}


def _h_final_response(state: GraphState) -> dict:
    txt = state.get("draft_response", "")
    return {
        "final_response": txt,
        "preview_text": txt,
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
    if workflow_name == "clarification_fallback":
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
    from ...target.clarification import format_pending_prompt

    answer_source = _clarify_answer_source(state)
    pending_result = str(state.get("pending_check_result", "") or "")
    if pending_result in {"expired", "invalid", "out_of_range"} and str(state.get("final_response", "") or "").strip():
        return {
            "final_response": state.get("final_response", ""),
            "answer_source": answer_source, "template_degraded": True,
            "fallback_used": True, "template_fallback_used": False,
            **_log(state, "clarify_response"),
        }
    pending = state.get("pending_clarification")
    if pending is not None:
        try:
            prompt = format_pending_prompt(pending)
        except Exception:
            prompt = "店名有点模糊，请提供完整店名。"
        if prompt.strip():
            return {
                "final_response": prompt, "answer_source": answer_source,
                "template_degraded": True, "fallback_used": True, "template_fallback_used": False,
                **_log(state, "clarify_response"),
            }
    rs = state.get("resolve_shop_result")
    if rs is not None and getattr(rs, "status", "") in ("AMBIGUOUS", "LOW_CONFIDENCE"):
        return {
            "final_response": "店名有点模糊，请提供完整店名。",
            "answer_source": answer_source, "template_degraded": True,
            "fallback_used": True, "template_fallback_used": False,
            **_log(state, "clarify_response"),
        }
    clarification = (state.get("error_message", "") or "").strip()
    if clarification:
        return {
            "final_response": clarification, "answer_source": answer_source,
            "template_degraded": True, "fallback_used": True, "template_fallback_used": False,
            **_log(state, "clarify_response"),
        }
    return {
        "final_response": "请提供完整店名。",
        "answer_source": answer_source, "template_degraded": True,
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
        "final_response": response, "answer_source": "trusted_failure_message",
        "template_degraded": True, "fallback_used": True, "template_fallback_used": False,
        "final_safety_status": "fallback",
        **_log(state, "fallback_answer"),
    }
