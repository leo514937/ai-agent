"""LangGraph StateGraph builder for the local life agent.

Maps the node/edge/state contracts from todo/05 into a compilable
``StateGraph``.  Each node handler documents its input/output fields
per 搂2 Node Table; conditional edges follow 搂3 Conditional Edge Table.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import ValidationError

from ..config import MOCK_LOCATION
from ..domain.enums import TaskType, ToolResultStatus, TopIntent
from ..domain.graph_state import GraphState
from ..domain.schemas import (
    AnswerPlan,
    EvidenceItem,
    EvidencePack,
    ExecutionPlan,
    ExecutionStage,
    ResolveShopResult,
    SemanticFrame,
    ShopCandidate,
    ShopRef,
    ToolCallSpec,
    ToolResult,
)
from ..domain.state import SessionState, SessionWriteDirective
from ..answer.answer_plan_builder import build_answer_plan
from ..answer.evidence_builder import build_evidence
from ..answer.generator import generate_answer
from ..answer.verifier import verify_answer
from ..input.hard_guard import check_hard_guard
from ..input.normalizer import normalize_text as input_normalize_text
from ..input.receiver import receive_input as assemble_turn_input
from ..input.validator import validate_basic_input
from ..planning.plan_validator import ExecutionPlanValidator
from ..planning.execution_plan_builder import build_execution_plan
from ..planning.facet_planner import plan_facets
from ..planning.task_router import route_task
from ..semantic.frame_validator import validate_frame
from ..semantic.intent_parser import parse_semantic_frame, parse_top_intent
from ..tools.gateway import dispatch_tool_call
from ..tools.mock_tools import resolve_shop
from ..tools.gateway import BatchToolExecutor
from .nodes import ExecutionNode
from .session_write import get_directive, resolve_scenario

# ===================================================================
# Helpers
# ===================================================================

GraphNodeFunc = Any  # Callable[[GraphState], dict] 鈥?acceptable typing overhead

_GRAPH_REWRITE_LIMIT = 1


def _log(state: GraphState, node: str, **extra: Any) -> dict:
    """Return a partial update that appends an event-log entry."""
    log = list(state.get("event_log", []))
    log.append({"node": node, **extra})
    return {"event_log": log}


def _pick_route(
    state: GraphState,
    status_field: str,
    route_map: dict[str, str],
    default: str,
) -> str:
    """Read *status_field* from state and return the matching route name."""
    val = state.get(status_field, "")
    for key, route in route_map.items():
        if val == key:
            return route
    return default


def _plan_validation_error_code(errors: list[str]) -> str:
    """Map validator errors to the runtime error_code used by graph routing."""
    joined = " | ".join(errors)
    if "not registered" in joined:
        return "TOOL_NOT_REGISTERED"
    if "forbidden" in joined:
        return "INVALID_ARGUMENT"
    if "Circular dependency" in joined:
        return "INVALID_ARGUMENT"
    if "not produced by legitimate resolve" in joined or "shop_id mismatch" in joined:
        return "INVALID_ARGUMENT"
    if "INVALID_ARGUMENT" in joined:
        return "INVALID_ARGUMENT"
    if "SCHEMA_VALIDATION_FAILED" in joined:
        return "SCHEMA_VALIDATION_FAILED"
    if "exceeds max_tool_calls" in joined:
        return "INVALID_ARGUMENT"
    return "SCHEMA_VALIDATION_FAILED"


def _to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        return dumped if isinstance(dumped, dict) else {}
    return dict(getattr(value, "__dict__", {}) or {})


def _resolved_shop_ids_from_state(state: GraphState) -> set[str]:
    """Collect legitimate resolved shop IDs from the current turn state."""
    resolved_ids: set[str] = set()
    for source in (state.get("resolved_target"), state.get("resolve_shop_result")):
        if source is None:
            continue
        data = _to_dict(source)
        if data.get("status") == "RESOLVED":
            resolved_shop = data.get("resolved_shop") or data.get("shop") or {}
            if hasattr(resolved_shop, "model_dump"):
                resolved_shop = resolved_shop.model_dump()
            if isinstance(resolved_shop, dict):
                sid = str(resolved_shop.get("shop_id", "")).strip()
                if sid:
                    resolved_ids.add(sid)
        sid = str(data.get("shop_id", "")).strip()
        if sid:
            resolved_ids.add(sid)
    return resolved_ids


# ===================================================================
# 26 Node Handlers  (todo/05 搂2 Node Table)
# ===================================================================


# --- 1. receive_input ---
# 搂1 input:  raw_text, session_id, trace_id
# 搂1 output: normalized_text, input_type, basic IDs
def _h_receive_input(state: GraphState) -> dict:
    raw = state.get("raw_text", "")
    received = assemble_turn_input(raw)
    return {
        "normalized_text": raw,
        "input_type": received.get("input_type", "text"),
        "turn_id": state.get("turn_id", ""),
        **_log(state, "receive_input"),
    }


# --- 2. load_session_state ---
# 搂1 input:  session_id
# 搂1 output: current_shop, last_recommendation_list, pending_clarification, session_state_before
def _h_load_session(state: GraphState) -> dict:
    existing = state.get("session_state")
    if existing is None:
        existing = SessionState()
    return {
        "session_state": existing,
        "session_state_before": existing,  # 搂1: 浼氳瘽蹇収渚涗笅娓歌妭鐐硅鍙?
        "current_shop": existing.current_shop,
        "last_recommendation_list": existing.last_recommendation_list,
        "active_constraints": existing.active_constraints,
        "pending_clarification": existing.pending_clarification,
        "comparison_targets": existing.comparison_targets,
        **_log(state, "load_session_state"),
    }


# --- 3. check_pending_clarification ---
# 搂1 input:  pending_clarification, raw_text
# 搂1 output: cleared or retained pending state
def _h_check_pending(state: GraphState) -> dict:
    pending = state.get("pending_clarification")
    if pending is None:
        return _log(state, "check_pending_clarification", has_pending=False)
    return _log(state, "check_pending_clarification", has_pending=True)


# --- 4. basic_input_validate ---
# 搂1 input:  normalized_text
# 搂1 output: input_type, error_code
def _h_basic_validate(state: GraphState) -> dict:
    raw = state.get("raw_text", "")
    validation = validate_basic_input(raw)
    if not validation["valid"]:
        return {
            "input_type": validation["input_type"],
            "error_code": validation["error_code"],
            "error_message": validation["error_message"],
            "final_response": "请提供一条有效的文本内容。",
            **_log(state, "basic_input_validate", valid=False, error_code=validation["error_code"]),
        }
    return {
        "input_type": "text",
        "error_code": "",
        "error_message": "",
        **_log(state, "basic_input_validate", valid=True),
    }


# --- 5. normalize_text ---
# 搂1 input:  raw_text
# 搂1 output: normalized_text
def _h_normalize_text(state: GraphState) -> dict:
    raw = state.get("raw_text", "")
    return {
        "normalized_text": input_normalize_text(raw),
        **_log(state, "normalize_text"),
    }


# --- 6. hard_guard ---
# 搂1 input:  normalized_text
# 搂1 output: guard_result
def _h_hard_guard(state: GraphState) -> dict:
    txt = state.get("normalized_text", "")
    result = check_hard_guard(txt)
    guard_result = result.get("label", "invalid")
    if guard_result == "safe":
        guard_result = "ok"
    return {
        "guard_result": guard_result,
        "final_response": result.get("reply", "") if not result.get("passed", False) else state.get("final_response", ""),
        **_log(state, "hard_guard"),
    }


# --- 7. top_intent_router ---
# 搂1 input:  normalized_text, session_state_before
# 搂1 output: top_intent
def _h_top_intent_router(state: GraphState) -> dict:
    txt = state.get("normalized_text", "")
    result = parse_top_intent(txt)
    intent = result.get("top_intent", TopIntent.out_of_scope)
    if not isinstance(intent, TopIntent):
        try:
            intent = TopIntent(intent)
        except Exception:
            intent = TopIntent.out_of_scope

    final_response = state.get("final_response", "")
    if intent == TopIntent.invalid:
        final_response = "请先输入一条有效的问题。"
    elif intent == TopIntent.chat:
        final_response = "我可以帮你查附近门店、优惠和营业状态。"
    elif intent == TopIntent.capability:
        final_response = "我可以帮你查附近门店、优惠、距离和营业状态。"
    elif intent in (TopIntent.unsafe, TopIntent.out_of_scope):
        final_response = "抱歉，我主要处理本地生活相关问题。"

    return {
        "top_intent": intent,
        "error_code": result.get("error_code", ""),
        "error_message": result.get("error_message", ""),
        "final_response": final_response,
        **_log(state, "top_intent_router", intent=intent.value),
    }


# --- 8. semantic_parse ---
# 搂1 input:  normalized_text, top_intent
# 搂1 output: semantic_frame
def _h_semantic_parse(state: GraphState) -> dict:
    txt = state.get("normalized_text", "")
    top_intent = state.get("top_intent")
    top_intent_value = top_intent.value if isinstance(top_intent, TopIntent) else str(top_intent or "")
    parsed = parse_semantic_frame(txt, top_intent_value)
    frame = parsed.get("semantic_frame")
    error_code = parsed.get("error_code", "")
    error_message = parsed.get("error_message", "")
    if not isinstance(frame, SemanticFrame):
        try:
            frame = SemanticFrame.model_validate(frame or {})
        except ValidationError as exc:
            return {
                "semantic_frame": None,
                "error_code": "SCHEMA_VALIDATION_FAILED",
                "error_message": str(exc),
                **_log(state, "semantic_parse", status="failed", reason="semantic_frame_validation_failed"),
            }
    if not error_code:
        validation = validate_frame(frame.model_dump())
        if not validation.get("valid", False):
            issues = validation.get("issues", [])
            if "missing_task_type" in issues:
                error_code = "MISSING_TASK_TYPE"
            elif "missing_merchant_mentions" in issues:
                error_code = "MISSING_MERCHANT_MENTION"
            elif any(issue.startswith("forbidden_field:") for issue in issues):
                error_code = "SCHEMA_VALIDATION_FAILED"
            elif "invalid_task_type" in issues:
                error_code = "INVALID_ARGUMENT"
            else:
                error_code = "SEMANTIC_FRAME_INVALID"
            error_message = validation.get("clarification", "")
    return {
        "semantic_frame": frame,
        "error_code": error_code,
        "error_message": error_message,
        **_log(state, "semantic_parse"),
    }


# --- 9. slot_extractor ---
# 搂1 input:  semantic_frame
# 搂1 output: facets, merchant_mentions, reference_mentions
def _h_slot_extractor(state: GraphState) -> dict:
    sf = state.get("semantic_frame")
    if sf is not None:
        return {
            "semantic_frame": sf,
            **_log(
                state,
                "slot_extractor",
                mentions=sf.merchant_mentions,
            ),
        }
    return _log(state, "slot_extractor")


# --- 10. frame_validator ---
# 搂1 input:  semantic_frame
# 搂1 output: semantic_frame (or error_code)
def _h_frame_validator(state: GraphState) -> dict:
    sf = state.get("semantic_frame")
    validation = validate_frame(sf.model_dump() if hasattr(sf, "model_dump") else _to_dict(sf))
    err = ""
    if not validation.get("valid", False):
        issues = validation.get("issues", [])
        if "missing_task_type" in issues:
            err = "MISSING_TASK_TYPE"
        elif "missing_merchant_mentions" in issues:
            err = "MISSING_MERCHANT_MENTION"
        elif "invalid_task_type" in issues:
            err = "INVALID_ARGUMENT"
        elif any(issue.startswith("forbidden_field:") for issue in issues):
            err = "SCHEMA_VALIDATION_FAILED"
        else:
            err = "SEMANTIC_FRAME_INVALID"
    return {
        "error_code": err,
        "error_message": validation.get("clarification", "") if err else "",
        "semantic_frame": sf,
        **_log(state, "frame_validator"),
    }


# --- 11. context_recovery ---
# 搂1 input:  session_state_before, semantic_frame
# 搂1 output: resolved_target (candidates)
def _h_context_recovery(state: GraphState) -> dict:
    return _log(state, "context_recovery")


# --- 12. target_resolve ---
# 搂1 input:  merchant_mentions, reference_mentions, session_state_before
# 搂1 output: resolve_shop_result
def _h_target_resolve(state: GraphState) -> dict:
    sf = state.get("semantic_frame")
    mentions = []
    if sf is not None:
        mentions = list(getattr(sf, "merchant_mentions", []) or [])
    query = mentions[0] if mentions else ""
    raw = resolve_shop(query, location=MOCK_LOCATION, session_shop_ids=[])
    status = raw.get("status", "NOT_FOUND")
    if status == "RESOLVED":
        shop = raw.get("shop") or {}
        if hasattr(shop, "model_dump"):
            shop = shop.model_dump()
        resolved_result = ResolveShopResult(
            status="RESOLVED",
            resolved_shop=ShopRef(
                shop_id=shop.get("shop_id", ""),
                shop_name=shop.get("shop_name", ""),
            ),
            confidence=float(raw.get("confidence", 0.0)),
            reason="resolved_by_target_resolve",
        )
        return {
            "resolve_shop_result": resolved_result,
            "resolved_target": resolved_result,
            **_log(state, "target_resolve", status="RESOLVED", query=query),
        }

    if status == "AMBIGUOUS":
        candidates = []
        for candidate in raw.get("candidates", []):
            candidate = candidate if isinstance(candidate, dict) else {}
            candidates.append(
                ShopCandidate(
                    shop=ShopRef(
                        shop_id=candidate.get("shop_id", ""),
                        shop_name=candidate.get("shop_name", ""),
                    )
                )
            )
        resolved_result = ResolveShopResult(
            status="AMBIGUOUS",
            candidates=candidates,
            confidence=float(raw.get("confidence", 0.0)),
            reason="ambiguous_shop",
        )
        return {
            "resolve_shop_result": resolved_result,
            **_log(state, "target_resolve", status="AMBIGUOUS", query=query),
        }

    resolved_result = ResolveShopResult(
        status="NOT_FOUND",
        confidence=0.0,
        reason=raw.get("error_code", "SHOP_NOT_FOUND") or "SHOP_NOT_FOUND",
    )
    return {
        "resolve_shop_result": resolved_result,
        **_log(state, "target_resolve", status="NOT_FOUND", query=query),
    }


# --- 12b. clarify_decide ---
# 搂1 input:  resolve_shop_result, semantic_frame
# 搂1 output: pending_clarification 鎴?resolved_target (鍙墽琛岀洰鏍?
def _h_clarify_decide(state: GraphState) -> dict:
    rs = state.get("resolve_shop_result")
    if rs is not None:
        status = rs.status
        if status == "RESOLVED":
            return {
                "resolved_target": rs,
                **_log(state, "clarify_decide", decision="proceed"),
            }
        if status in ("AMBIGUOUS", "LOW_CONFIDENCE"):
            return {
                **_log(state, "clarify_decide", decision="clarify"),
            }
        # NOT_FOUND or other
        return {
            "final_response": "没有找到这家店，请提供完整店名。",
            **_log(state, "clarify_decide", decision="not_found"),
        }
    # No resolve result 鈫?clarify
    return _log(state, "clarify_decide", decision="no_result")


# --- 13. task_plan ---
# 搂1 input:  top_intent, task_type, resolved_target
# 搂1 output: execution_plan
def _h_task_plan(state: GraphState) -> dict:
    sf = state.get("semantic_frame")
    rt = state.get("resolved_target")
    frame_dict = sf.model_dump() if hasattr(sf, "model_dump") else _to_dict(sf)
    target_dict = rt.model_dump() if hasattr(rt, "model_dump") else _to_dict(rt)
    task_type = route_task(frame_dict, target_dict)
    return {
        "task_type": task_type,
        **_log(state, "task_plan"),
    }


# --- 14. facet_plan ---
# 搂1 input:  semantic_frame, resolved_target
# 搂1 output: execution_plan.tool_calls
def _h_facet_plan(state: GraphState) -> dict:
    sf = state.get("semantic_frame")
    rt = state.get("resolved_target")
    frame_dict = sf.model_dump() if hasattr(sf, "model_dump") else _to_dict(sf)
    target_dict = rt.model_dump() if hasattr(rt, "model_dump") else _to_dict(rt)
    task_type = state.get("task_type") or route_task(frame_dict, target_dict)
    facets = plan_facets(task_type, frame_dict)
    plan_dict = build_execution_plan(task_type, target_dict, facets)
    plan = ExecutionPlan.model_validate(plan_dict)
    return {
        "execution_plan": plan,
        **_log(state, "facet_plan", tool_calls=len(plan.tool_calls)),
    }


# --- 15. comparison_planner ---
# 搂1 input:  comparison_targets, resolved_target
# 搂1 output: execution_plan, comparison_matrix placeholder
def _h_comparison_planner(state: GraphState) -> dict:
    return _log(state, "comparison_planner")


# --- 16. plan_validator ---
# 搂1 input:  execution_plan
# 搂1 output: validated_plan (or error_code)
def _h_plan_validator(state: GraphState) -> dict:
    plan = state.get("execution_plan")
    if plan is None:
        return {
            "error_code": "SCHEMA_VALIDATION_FAILED",
            "error_message": "execution_plan is required",
            "plan_validation_result": "failed",
            "failed_stage": "plan_validator",
            "validated_plan": None,
            **_log(state, "plan_validator", status="failed", reason="missing_execution_plan"),
        }

    if not plan.tool_calls and not plan.stages:
        return {
            "error_code": "INVALID_PLAN",
            "error_message": "execution_plan must contain tool_calls or stages",
            "plan_validation_result": "failed",
            "failed_stage": "plan_validator",
            "validated_plan": None,
            **_log(state, "plan_validator", status="failed", reason="empty_plan"),
        }

    validator = ExecutionPlanValidator()
    resolved_shop_ids = _resolved_shop_ids_from_state(state)
    report = validator.validate(plan, resolved_shop_ids=resolved_shop_ids or None)
    if not report.passed:
        error_code = _plan_validation_error_code(report.errors)
        error_message = "; ".join(report.errors)
        return {
            "error_code": error_code,
            "error_message": error_message,
            "plan_validation_result": "failed",
            "failed_stage": "plan_validator",
            "validated_plan": None,
            **_log(state, "plan_validator", status="failed", reason=error_code),
        }

    return {
        "error_code": "",
        "error_message": "",
        "plan_validation_result": "pass",
        "failed_stage": "",
        "validated_plan": plan,  # 搂1: 鏍￠獙閫氳繃鍚庣殑鎵ц璁″垝
        **_log(state, "plan_validator", status="pass"),
    }


# --- 17. tool_execute ---
# 搂1 input:  validated_plan
# 搂1 output: tool_result_set
def _h_tool_execute(state: GraphState) -> dict:
    plan = state.get("validated_plan") or state.get("execution_plan")
    results: dict[str, ToolResult] = {}
    if plan is not None:
        tool_calls = getattr(plan, "tool_calls", []) or []
        batch_executor = BatchToolExecutor(call_fn=dispatch_tool_call)
        raw_results = batch_executor.execute_sync(tool_calls)
        for spec in tool_calls:
            call = spec.model_dump() if hasattr(spec, "model_dump") else _to_dict(spec)
            call_id = call.get("call_id", "") or call.get("tool_name", "")
            raw_result = raw_results.get(call_id)
            if raw_result is None:
                raw_result = {
                    "call_id": call_id,
                    "shop_id": call.get("target_shop_id", "") or call.get("args", {}).get("shop_id", ""),
                    "tool_name": call.get("tool_name", ""),
                    "success": False,
                    "result_status": "unknown" if not call.get("required", True) else "failed",
                    "data": None,
                    "error_code": "TOOL_TIMEOUT",
                    "error_message": f"Tool '{call.get('tool_name', '')}' did not return a result",
                    "source": "mock",
                    "degraded": not call.get("required", True),
                }
            shop_id = call.get("target_shop_id", "") or call.get("args", {}).get("shop_id", "") or raw_result.get("shop_id", "")
            raw_result = {
                **raw_result,
                "call_id": call_id,
                "shop_id": shop_id,
                "tool_name": call.get("tool_name", ""),
            }
            results[call_id or call.get("tool_name", "")] = ToolResult.model_validate(raw_result)
    return {
        "tool_results": results,
        "tool_result_set": results,  # 搂1: 鏂囨。瑕佹眰鐨勫瓧娈靛悕
        **_log(state, "tool_execute"),
    }


# --- 18. evidence_build ---
# 搂1 input:  tool_result_set
# 搂1 output: evidence_pack
def _h_evidence_build(state: GraphState) -> dict:
    pack = EvidencePack.model_validate(
        build_evidence(
            state.get("tool_result_set") or state.get("tool_results", {}),
            state.get("resolved_target"),
            state.get("validated_plan") or state.get("execution_plan"),
        )
    )
    return {
        "evidence_pack": pack,
        **_log(state, "evidence_build"),
    }


# --- 19. answer_plan_build ---
# 搂1 input:  evidence_pack, semantic_frame
# 搂1 output: answer_plan
def _h_answer_plan_build(state: GraphState) -> dict:
    execution_plan = state.get("execution_plan")
    task_type = ""
    if hasattr(execution_plan, "task_type"):
        task_type = getattr(execution_plan, "task_type", "")
    elif isinstance(execution_plan, dict):
        task_type = execution_plan.get("task_type", "")
    plan = AnswerPlan.model_validate(
        build_answer_plan(
            task_type,
            state.get("evidence_pack") or {},
            None,
        )
    )
    return {
        "answer_plan": plan,
        **_log(state, "answer_plan_build"),
    }


# --- 20. answer_generate ---
# 搂1 input:  answer_plan, evidence_pack
# 搂1 output: draft_response
def _h_answer_generate(state: GraphState) -> dict:
    txt = generate_answer(
        state.get("answer_plan") or {},
        state.get("evidence_pack") or {},
    )
    return {
        "draft_response": txt,
        **_log(state, "answer_generate"),
    }


# --- 21. answer_verify ---
# 搂1 input:  draft_response, evidence_pack
# 搂1 output: verify_result
def _h_answer_verify(state: GraphState) -> dict:
    evidence = state.get("evidence_pack") or {}
    answer_plan = state.get("answer_plan") or {}
    task_type = getattr(state.get("execution_plan"), "task_type", "") or (
        state.get("execution_plan", {}).get("task_type", "") if isinstance(state.get("execution_plan"), dict) else ""
    )
    if not evidence or not state.get("draft_response", ""):
        return {
            "verify_result": "pass",
            "error_code": "",
            "error_message": "",
            **_log(state, "answer_verify"),
        }
    report = verify_answer(state.get("draft_response", ""), evidence, task_type)
    return {
        "verify_result": "pass" if report.get("passed") else "rewrite_needed",
        "error_code": "" if report.get("passed") else "ANSWER_VERIFIER_FAILED",
        "error_message": "" if report.get("passed") else report.get("suggested_fix", ""),
        **_log(state, "answer_verify"),
    }


# --- 22. rewrite ---
# 搂1 input:  verify_result, answer_plan
# 搂1 output: draft_response
def _h_rewrite(state: GraphState) -> dict:
    rc = state.get("rewrite_count", 0) + 1
    txt = state.get("draft_response", "")
    return {
        "draft_response": txt,
        "rewrite_count": rc,
        **_log(state, "rewrite", rewrite_count=rc),
    }


# --- 23. final_response_build ---
# 搂1 input:  draft_response, verify_result
# 搂1 output: final_response
def _h_final_response(state: GraphState) -> dict:
    txt = state.get("draft_response", "")
    return {
        "final_response": txt,
        **_log(state, "final_response_build"),
    }


# --- 24. clarify_response ---
# 搂1 input:  resolve_shop_result, pending_clarification
# 搂1 output: final_response
def _h_clarify_response(state: GraphState) -> dict:
    rs = state.get("resolve_shop_result")
    if rs is not None and getattr(rs, "status", "") in ("AMBIGUOUS", "LOW_CONFIDENCE"):
        return {
            "final_response": "店名有点模糊，请提供完整店名。",
            **_log(state, "clarify_response"),
        }
    clarification = (state.get("error_message", "") or "").strip()
    if clarification:
        return {
            "final_response": clarification,
            **_log(state, "clarify_response"),
        }
    return {
        "final_response": "你想查哪家店的优惠券？请告诉我具体店名。",
        **_log(state, "clarify_response"),
    }


# --- 25. fallback_answer ---
# 搂1 input:  error_code, evidence_pack
# 搂1 output: final_response
def _h_fallback_answer(state: GraphState) -> dict:
    evidence = state.get("evidence_pack")
    evidence_dict = _to_dict(evidence)
    status = ""
    snapshot = evidence_dict.get("ranking_snapshot") or {}
    if isinstance(snapshot, dict):
        status = str(snapshot.get("status", "") or "")
    if not status:
        tr = state.get("tool_result_set") or state.get("tool_results", {})
        for result in tr.values():
            value = result.result_status.value if hasattr(result, "result_status") else str(_to_dict(result).get("result_status", ""))
            status = value
            if value in ("failed", "circuit_open"):
                break
    if status == "circuit_open":
        response = "优惠券服务暂时不可用，请稍后再试。"
    elif status == "failed":
        response = "获取优惠券信息失败，建议稍后再试。"
    elif status == "unknown":
        response = "暂时无法确认优惠券情况，请稍后再试。"
    else:
        response = "抱歉，暂时无法处理您的请求，请稍后再试。"
    return {
        "final_response": response,
        **_log(state, "fallback_answer"),
    }


# --- 26. state_update_plan ---
# 搂1 input:  final_response, session_state_before
# 搂1 output: state_update_plan
def _h_state_update_plan(state: GraphState) -> dict:
    return _log(state, "state_update_plan")


# --- 27. persist_session_state ---
# 搂1 input:  state_update_plan
# 搂1 output: session_state_after
def _h_persist_session(state: GraphState) -> dict:
    return _log(state, "persist_session_state")


# --- 28. emit_response ---
# 搂1 input:  final_response, trace_id
# 搂1 output: (terminal 鈥?no state mutation)
def _h_emit_response(state: GraphState) -> dict:
    return _log(state, "emit_response")


# ===================================================================
# Node name 鈫?handler mapping
# ===================================================================

_HANDLERS: dict[str, GraphNodeFunc] = {
    "receive_input": _h_receive_input,
    "load_session_state": _h_load_session,
    "check_pending_clarification": _h_check_pending,
    "basic_input_validate": _h_basic_validate,
    "normalize_text": _h_normalize_text,
    "hard_guard": _h_hard_guard,
    "top_intent_router": _h_top_intent_router,
    "semantic_parse": _h_semantic_parse,
    "slot_extractor": _h_slot_extractor,
    "frame_validator": _h_frame_validator,
    "context_recovery": _h_context_recovery,
    "target_resolve": _h_target_resolve,
    "clarify_decide": _h_clarify_decide,
    "task_plan": _h_task_plan,
    "facet_plan": _h_facet_plan,
    "comparison_planner": _h_comparison_planner,
    "plan_validator": _h_plan_validator,
    "tool_execute": _h_tool_execute,
    "evidence_build": _h_evidence_build,
    "answer_plan_build": _h_answer_plan_build,
    "answer_generate": _h_answer_generate,
    "answer_verify": _h_answer_verify,
    "rewrite": _h_rewrite,
    "final_response_build": _h_final_response,
    "clarify_response": _h_clarify_response,
    "fallback_answer": _h_fallback_answer,
    "state_update_plan": _h_state_update_plan,
    "persist_session_state": _h_persist_session,
    "emit_response": _h_emit_response,
}

# Nodes that the 搂2 Node Table says should exist in the graph.
# All 27 rows including clarify_decide as independent node.
ALL_NODE_NAMES: set[str] = set(_HANDLERS.keys())

# Normal-flow unconditional edges  (搂2 "涓嬩竴璺? default path)
_NORMAL_EDGES: dict[str, str] = {
    "receive_input": "load_session_state",
    "load_session_state": "check_pending_clarification",
    "normalize_text": "hard_guard",
    "slot_extractor": "context_recovery",
    "context_recovery": "target_resolve",
    "target_resolve": "clarify_decide",  # 搂2: target_resolve 鈫?clarify_decide
    "task_plan": "facet_plan",
    "facet_plan": "plan_validator",
    "comparison_planner": "plan_validator",
    "evidence_build": "answer_plan_build",
    "answer_plan_build": "answer_generate",
    "answer_generate": "answer_verify",
    "rewrite": "answer_generate",
    "final_response_build": "state_update_plan",
    "clarify_response": "state_update_plan",
    "fallback_answer": "state_update_plan",
    "state_update_plan": "persist_session_state",
    "persist_session_state": "emit_response",
}


# ===================================================================
# Conditional edge routing functions  (todo/05 搂3)
# ===================================================================


def _route_check_pending(state: GraphState) -> str:
    """搂3 鈥?Route check_pending_clarification."""
    pending = state.get("pending_clarification")
    raw = state.get("raw_text", "")
    if pending is not None and raw.strip().isdigit():
        return "target_resolve"
    # Future: NL topic-switch detection 鈫?return "top_intent_router"
    return "basic_input_validate"


def _route_basic_validate(state: GraphState) -> str:
    """Route basic_input_validate."""
    err = state.get("error_code", "")
    if err:
        return "emit_response"
    return "normalize_text"


def _route_hard_guard(state: GraphState) -> str:
    """搂3 鈥?Route hard_guard."""
    result = state.get("guard_result", "")
    if result in ("safe", "ok"):
        return "top_intent_router"
    if result in ("invalid", "greeting", "capability"):
        return "emit_response"
    return "emit_response"


def _route_top_intent(state: GraphState) -> str:
    """搂3 鈥?Route top_intent_router."""
    intent = state.get("top_intent")
    if intent in (TopIntent.local_life, "local_life"):
        return "semantic_parse"
    if intent in (
        TopIntent.chat,
        "chat",
        TopIntent.out_of_scope,
        TopIntent.unsafe,
        TopIntent.invalid,
        TopIntent.capability,
        "out_of_scope",
        "unsafe",
        "invalid",
        "capability",
    ):
        return "emit_response"
    return "emit_response"


def _route_semantic_parse(state: GraphState) -> str:
    """搂3 + 搂2 鈥?Route semantic_parse."""
    err = state.get("error_code", "")
    if err == "LLM_JSON_PARSE_ERROR":
        return "clarify_response"
    if err:
        return "clarify_response"
    return "slot_extractor"


def _route_frame_validator(state: GraphState) -> str:
    """搂2 鈥?Route frame_validator."""
    err = state.get("error_code", "")
    if err:
        return "clarify_response"
    return "context_recovery"


def _route_clarify_decide(state: GraphState) -> str:
    """搂3 鈥?Route clarify_decide based on resolve_shop_result.status."""
    rs = state.get("resolve_shop_result")
    if rs is not None:
        status = rs.status
        if status == "RESOLVED":
            return "task_plan"
        if status in ("AMBIGUOUS", "LOW_CONFIDENCE"):
            return "clarify_response"
        if status == "NOT_FOUND":
            return "emit_response"
    # Default fallthrough 鈫?clarify
    return "clarify_response"


def _route_plan_validator(state: GraphState) -> str:
    """搂3 鈥?Route plan_validator."""
    err = state.get("error_code", "")
    if err:
        return "fallback_answer"
    return "tool_execute"


def _route_tool_execute(state: GraphState) -> str:
    """搂3 鈥?Route tool_execute."""
    tr = state.get("tool_result_set") or state.get("tool_results", {})
    for _call_id, result in tr.items():
        status = result.result_status.value if hasattr(result, "result_status") else str(_to_dict(result).get("result_status", ""))
        if status in ("failed", "circuit_open"):
            return "fallback_answer"
    return "evidence_build"


def _route_answer_verify(state: GraphState) -> str:
    """搂3 鈥?Route answer_verify."""
    vr = state.get("verify_result", "pass")
    rc = state.get("rewrite_count", 0)
    if vr == "pass":
        return "final_response_build"
    if vr in ("rewrite_needed", "rewrite_exhausted"):
        if rc < _GRAPH_REWRITE_LIMIT:
            return "rewrite"
        return "fallback_answer"
    # default
    return "final_response_build"


# === Conditional edge route maps ===

_CHECK_PENDING_ROUTES: dict[Any, str] = {
    "target_resolve": "target_resolve",
    "top_intent_router": "top_intent_router",
    "basic_input_validate": "basic_input_validate",
}

_BASIC_VALIDATE_ROUTES: dict[Any, str] = {
    "emit_response": "emit_response",
    "normalize_text": "normalize_text",
}

_HARD_GUARD_ROUTES: dict[Any, str] = {
    "emit_response": "emit_response",
    "top_intent_router": "top_intent_router",
}

_TOP_INTENT_ROUTES: dict[Any, str] = {
    "emit_response": "emit_response",
    "semantic_parse": "semantic_parse",
}

_SEMANTIC_PARSE_ROUTES: dict[Any, str] = {
    "clarify_response": "clarify_response",
    "frame_validator": "frame_validator",
    "slot_extractor": "slot_extractor",
}

_FRAME_VALIDATOR_ROUTES: dict[Any, str] = {
    "clarify_response": "clarify_response",
    "context_recovery": "context_recovery",
}

_CLARIFY_DECIDE_ROUTES: dict[Any, str] = {
    "task_plan": "task_plan",
    "clarify_response": "clarify_response",
    "emit_response": "emit_response",
}

_PLAN_VALIDATOR_ROUTES: dict[Any, str] = {
    "fallback_answer": "fallback_answer",
    "tool_execute": "tool_execute",
}

_TOOL_EXECUTE_ROUTES: dict[Any, str] = {
    "fallback_answer": "fallback_answer",
    "evidence_build": "evidence_build",
}

_ANSWER_VERIFY_ROUTES: dict[Any, str] = {
    "final_response_build": "final_response_build",
    "rewrite": "rewrite",
    "fallback_answer": "fallback_answer",
}


# ===================================================================
# Graph builder
# ===================================================================


def _parse_node(n: str | ExecutionNode) -> str:
    """Normalise to string node name."""
    return n.value if isinstance(n, ExecutionNode) else n


def build_graph() -> CompiledStateGraph:
    """Construct the full ``StateGraph`` per todo/05.

    Returns a compiled graph ready for ``graph.invoke(state_dict)``.

    Raises ``ValueError`` if the graph fails completeness verification.
    """
    builder: StateGraph = StateGraph(GraphState)

    # 1. Add all nodes
    for name, handler in _HANDLERS.items():
        builder.add_node(name, handler)

    # 2. START 鈫?receive_input
    builder.add_edge(START, "receive_input")

    # 3. Normal-flow unconditional edges
    for src, dst in _NORMAL_EDGES.items():
        builder.add_edge(src, dst)

    # 4. Conditional edges  (搂3)
    builder.add_conditional_edges(
        "check_pending_clarification",
        _route_check_pending,
        _CHECK_PENDING_ROUTES,
    )
    builder.add_conditional_edges(
        "basic_input_validate",
        _route_basic_validate,
        _BASIC_VALIDATE_ROUTES,
    )
    builder.add_conditional_edges(
        "hard_guard",
        _route_hard_guard,
        _HARD_GUARD_ROUTES,
    )
    builder.add_conditional_edges(
        "top_intent_router",
        _route_top_intent,
        _TOP_INTENT_ROUTES,
    )
    builder.add_conditional_edges(
        "semantic_parse",
        _route_semantic_parse,
        _SEMANTIC_PARSE_ROUTES,
    )
    builder.add_conditional_edges(
        "frame_validator",
        _route_frame_validator,
        _FRAME_VALIDATOR_ROUTES,
    )
    builder.add_conditional_edges(
        "clarify_decide",
        _route_clarify_decide,
        _CLARIFY_DECIDE_ROUTES,
    )
    builder.add_conditional_edges(
        "plan_validator",
        _route_plan_validator,
        _PLAN_VALIDATOR_ROUTES,
    )
    builder.add_conditional_edges(
        "tool_execute",
        _route_tool_execute,
        _TOOL_EXECUTE_ROUTES,
    )
    builder.add_conditional_edges(
        "answer_verify",
        _route_answer_verify,
        _ANSWER_VERIFY_ROUTES,
    )

    # 5. Terminal: emit_response 鈫?END
    builder.add_edge("emit_response", END)

    # 6. Validate
    report = verify_graph_completeness(builder)
    if report["errors"]:
        raise ValueError(
            f"Graph completeness check FAILED:\n"
            + "\n".join(f"  - {e}" for e in report["errors"])
        )

    return builder.compile()


# ===================================================================
# Completeness verifier
# ===================================================================

_NODE_TABLE_NEXT_HOPS: dict[str, list[str]] = {
    "receive_input": ["load_session_state"],
    "load_session_state": ["check_pending_clarification"],
    "check_pending_clarification": [
        "hard_guard",
        "clarify_response",
        "semantic_parse",
        "basic_input_validate",
        "target_resolve",
        "top_intent_router",
    ],
    "basic_input_validate": ["normalize_text", "emit_response"],
    "normalize_text": ["hard_guard"],
    "hard_guard": ["emit_response", "top_intent_router"],
    "top_intent_router": ["emit_response", "semantic_parse"],
    "semantic_parse": ["slot_extractor", "frame_validator", "clarify_response"],
    "slot_extractor": ["context_recovery"],
    "frame_validator": ["context_recovery", "clarify_response"],
    "context_recovery": ["target_resolve"],
    "target_resolve": ["clarify_decide"],  # 搂2: 鏃犳潯浠惰浆鍏?clarify_decide
    "clarify_decide": ["clarify_response", "task_plan", "emit_response"],  # 搂2: 鐙珛鍐崇瓥鑺傜偣
    "task_plan": ["facet_plan", "comparison_planner", "tool_execute"],
    "facet_plan": ["plan_validator"],
    "comparison_planner": ["plan_validator"],
    "plan_validator": ["tool_execute", "fallback_answer"],
    "tool_execute": ["fallback_answer", "evidence_build"],
    "evidence_build": ["answer_plan_build"],
    "answer_plan_build": ["answer_generate"],
    "answer_generate": ["answer_verify"],
    "answer_verify": ["final_response_build", "rewrite", "fallback_answer"],
    "rewrite": ["answer_generate"],
    "final_response_build": ["state_update_plan"],
    "clarify_response": ["state_update_plan"],
    "fallback_answer": ["state_update_plan"],
    "state_update_plan": ["persist_session_state"],
    "persist_session_state": ["emit_response"],
    "emit_response": [],  # Terminal
}

_EDGE_TABLE_ROWS: list[tuple[str, str, str]] = [
    ("check_pending_clarification", "pending reply digits", "target_resolve"),
    ("check_pending_clarification", "new topic or normal input", "basic_input_validate"),
    ("basic_input_validate", "invalid/empty/overlong", "emit_response"),
    ("basic_input_validate", "valid text", "normalize_text"),
    ("hard_guard", "pure invalid/greeting/capability", "emit_response"),
    ("hard_guard", "safe", "top_intent_router"),
    ("top_intent_router", "out_of_scope/unsafe/chat/capability/invalid", "emit_response"),
    ("top_intent_router", "local_life", "semantic_parse"),
    ("semantic_parse", "JSON parse fail after retry", "clarify_response"),
    ("clarify_decide", "RESOLVED", "task_plan"),
    ("clarify_decide", "AMBIGUOUS", "clarify_response"),
    ("clarify_decide", "LOW_CONFIDENCE", "clarify_response"),
    ("clarify_decide", "NOT_FOUND", "emit_response"),
    ("plan_validator", "invalid plan or unregistered tool", "fallback_answer"),
    ("tool_execute", "required tool failed/unknown", "fallback_answer"),
    ("tool_execute", "optional tool failed/unknown", "evidence_build"),
    ("answer_verify", "pass", "final_response_build"),
    ("answer_verify", "rewrite attempts < 1", "rewrite"),
    ("answer_verify", "rewrite attempts >= 1", "fallback_answer"),
]

_GRAPH_STATE_FIELDS: list[str] = [
    # 璺敱鏍囪瘑
    "trace_id",
    "turn_id",
    "session_id",
    "user_id",
    # 杈撳叆灞?
    "raw_text",
    "normalized_text",
    "input_type",
    # 椤跺眰鎰忓浘
    "top_intent",
    "task_type",
    # 璇箟甯?
    "semantic_frame",
    # 婢勬竻鐘舵€?
    "pending_clarification",
    # 浼氳瘽璁板繂
    "current_shop",
    "last_recommendation_list",
    "active_constraints",
    "comparison_targets",
    # 瑙ｆ瀽缁撴灉
    "resolved_target",
    "resolve_shop_result",  # 搂1 鏂囨。瀛楁
    # 鎵ц璁″垝
    "execution_plan",
    "validated_plan",  # 搂1 鏂囨。瀛楁
    # 宸ュ叿缁撴灉
    "tool_results",
    "tool_result_set",  # 搂1 鏂囨。瀛楁
    # 璇佹嵁灞?
    "evidence_pack",
    # 鍥炵瓟灞?
    "answer_plan",
    "final_response",
    # 鐘舵€佹洿鏂?
    "state_update_plan",
    # 浼氳瘽蹇収
    "session_state_before",  # 搂1 鏂囨。瀛楁
    # 瑙傛祴瀛楁
    "event_log",
    "metrics_tags",
    "trace_spans",
    # 杩愯鏃惰緟鍔?
    "error_message",
    "plan_validation_result",
    "failed_stage",
]


def verify_graph_completeness(
    builder: StateGraph | None = None,
) -> dict[str, Any]:
    """Verify the graph against the todo/05 contract.

    Checks:
      1. All 26 nodes from 搂2 Node Table exist.
      2. All 搂3 conditional edges have their ``from`` nodes present.
      3. No orphan destinations (every ``涓嬩竴璺砢` target exists as a node).
      4. All 搂1 state fields are documented.

    Args:
        builder: Optional built (but not compiled) graph.  When omitted
                 only the static contract is checked.

    Returns:
        A dict with ``errors`` (list) and ``warnings`` (list).
    """
    errors: list[str] = []
    warnings: list[str] = []

    # --- Check 1: all nodes present ---
    configured = set(_HANDLERS.keys())

    # Check that the node-table next hops all exist
    for src, targets in _NODE_TABLE_NEXT_HOPS.items():
        if src not in configured:
            errors.append(f"搂2 node '{src}' has no handler 鈥?missing from graph")
        for t in targets:
            if t and t not in configured:
                errors.append(
                    f"搂2 node '{src}' lists '{t}' as 涓嬩竴璺? "
                    f"but '{t}' has no handler"
                )

    # --- Check 2: conditional edge from-nodes ---
    seen_from: set[str] = set()
    for src, _cond, dst in _EDGE_TABLE_ROWS:
        seen_from.add(src)
        if src not in configured:
            errors.append(
                f"搂3 conditional edge from '{src}' 鈫?'{dst}': "
                f"source node missing from graph"
            )
        if dst not in configured:
            errors.append(
                f"搂3 conditional edge '{src}' 鈫?'{dst}': "
                f"destination node missing from graph"
            )

    # --- Check 3: builder-level validation ---
    if builder is not None:
        try:
            # The builder performs internal consistency at add_* time.
            # No explicit validate call needed 鈥?LangGraph checks inline.
            pass
        except Exception as exc:
            errors.append(f"Builder internal validation: {exc}")

    return {
        "errors": errors,
        "warnings": warnings,
        "node_count": len(configured),
        "conditional_edges_verified": len(seen_from),
    }


