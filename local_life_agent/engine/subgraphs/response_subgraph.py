"""response_subgraph — answer generation, verification, and fallback.

Generates the final answer via LLM verbalizer, verifies it against evidence,
rewrites if needed, and handles clarification / fallback responses.
"""

from __future__ import annotations

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


def h_response_subgraph(state: GraphState) -> dict:
    """Outer wrapper: handle response mode → generate / clarify / fallback."""
    before = dict(state)
    response_mode = str(state.get("response_mode", "") or "")
    if response_mode in {_OUTER_ROUTE_DIRECT, _OUTER_ROUTE_REJECT}:
        after = {**state, "response_route": _OUTER_ROUTE_PASS}
        return _state_delta(before, after, always_include={"response_route"})
    if response_mode in {_OUTER_ROUTE_CLARIFY} or state.get("pending_clarification") is not None:
        if not str(state.get("final_response", "") or "").strip():
            working = _run_step(state, _h_clarify_response)
        else:
            working = dict(state)
        after = {**working, "response_route": _OUTER_ROUTE_CLARIFY_READY}
        return _state_delta(before, after, always_include={"response_route"})
    if response_mode in {_OUTER_ROUTE_FALLBACK}:
        if not str(state.get("final_response", "") or "").strip():
            working = _run_step(state, _h_fallback_answer)
        else:
            working = dict(state)
        after = {**working, "response_route": _OUTER_ROUTE_FALLBACK_READY}
        return _state_delta(before, after, always_include={"response_route"})

    working = _run_step(state, _h_answer_plan_build)
    rewrite_limit = max(0, int(_GRAPH_REWRITE_LIMIT or 0))
    while True:
        working = _run_step(working, _h_answer_generate)
        working = _run_step(working, _h_answer_verify)
        verify_result = str(working.get("verify_result", "") or "")
        if verify_result == "pass":
            working = _run_step(working, _h_final_response)
            after = {**working, "response_route": _OUTER_ROUTE_PASS}
            return _state_delta(before, after, always_include={"response_route"})
        rewrite_count = int(working.get("rewrite_count", 0) or 0)
        if rewrite_count >= rewrite_limit:
            working = _run_step(working, _h_fallback_answer)
            after = {**working, "response_route": _OUTER_ROUTE_FALLBACK_READY}
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
    return {
        "answer_plan": answer_plan,
        "draft_response": txt,
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

    if not passed:
        print(f"[DEBUG answer_verify FAIL] task_type={task_type} violations={violations}")
        print(f"[DEBUG answer_verify FAIL] draft_prefix={state.get('draft_response', '')[:200]}")
        print(f"[DEBUG answer_verify FAIL] evidence_items={len(evidence_dict.get('evidence_items') or [])}")
        snapshot = evidence_dict.get("ranking_snapshot") or {}
        ranked = snapshot.get("ranked") or snapshot.get("ranked_shops") or snapshot.get("shops") or []
        print(f"[DEBUG answer_verify FAIL] ranked_count={len(ranked)}")
        for i, r in enumerate(ranked[:5]):
            if isinstance(r, dict):
                print(f"  ranked[{i}] shop_name={r.get('shop_name')} shop_id={r.get('shop_id')}")
            else:
                print(f"  ranked[{i}]={r}")
        fr = evidence_dict.get("facet_results") or snapshot.get("facet_results") or []
        print(f"[DEBUG answer_verify FAIL] facet_results_count={len(fr)}")
        for f in fr[:10]:
            print(f"  facet={f.get('facet')} status={f.get('result_status')} shop_id={f.get('shop_id')}")
    else:
        print(f"[DEBUG answer_verify PASS] task_type={task_type}")

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
        **_log(state, "final_response_build", answer_source=state.get("answer_source", ""),
              final_safety_status=state.get("final_safety_status", "safe")),
    }


def _h_clarify_response(state: GraphState) -> dict:
    from ...target.clarification import format_pending_prompt

    pending_result = str(state.get("pending_check_result", "") or "")
    if pending_result in {"expired", "invalid", "out_of_range"} and str(state.get("final_response", "") or "").strip():
        return {
            "final_response": state.get("final_response", ""),
            "answer_source": "clarify_message", "template_degraded": True,
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
                "final_response": prompt, "answer_source": "clarify_message",
                "template_degraded": True, "fallback_used": True, "template_fallback_used": False,
                **_log(state, "clarify_response"),
            }
    rs = state.get("resolve_shop_result")
    if rs is not None and getattr(rs, "status", "") in ("AMBIGUOUS", "LOW_CONFIDENCE"):
        return {
            "final_response": "店名有点模糊，请提供完整店名。",
            "answer_source": "clarify_message", "template_degraded": True,
            "fallback_used": True, "template_fallback_used": False,
            **_log(state, "clarify_response"),
        }
    clarification = (state.get("error_message", "") or "").strip()
    if clarification:
        return {
            "final_response": clarification, "answer_source": "clarify_message",
            "template_degraded": True, "fallback_used": True, "template_fallback_used": False,
            **_log(state, "clarify_response"),
        }
    return {
        "final_response": "请提供完整店名。",
        "answer_source": "clarify_message", "template_degraded": True,
        "fallback_used": True, "template_fallback_used": False,
        **_log(state, "clarify_response"),
    }


def _h_fallback_answer(state: GraphState) -> dict:
    response = "抱歉，暂时无法处理您的请求，请稍后再试。"
    evidence_dict = _to_dict(state.get("evidence_pack") or {})
    snapshot = evidence_dict.get("ranking_snapshot") or {}
    status = str(snapshot.get("status", "") or "") if isinstance(snapshot, dict) else ""
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
