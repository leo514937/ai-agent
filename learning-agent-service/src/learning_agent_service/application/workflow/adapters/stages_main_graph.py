from __future__ import annotations

import logging
from dataclasses import asdict
from collections.abc import Mapping
from typing import Any

from learning_agent_service.application.router.base import should_run_tool
from learning_agent_service.application.router.phase7_compose import (
    _build_answer_contract,
    _build_entity_join_result,
    _build_source_contract,
)
from learning_agent_service.application.router.stages import route_execution_mode
from learning_agent_service.application.router.stages.hard_guard import check_hard_guard
from learning_agent_service.application.router.stages.query_safety import check_query_safety
from learning_agent_service.application.workflow.subgraphs import route_decider, route_gate
from learning_agent_service.local_life.business_metrics import QueryMetrics, business_metrics_collector
from learning_agent_service.local_life.final_answer_safety import apply_final_answer_safety
from learning_agent_service.local_life.response_builder.bundle import build_response_bundle
from learning_agent_service.local_life.realtime_conflict_resolver import REALTIME_FACETS, resolve_realtime_conflict
from learning_agent_service.local_life.retry_quality_evaluator import evaluate_retry_quality

from .helpers import GraphState, Mapping, _routing_decision_for_turn

_LOGGER = logging.getLogger(__name__)


def _turn_raw_query(state: GraphState) -> str:
    return str(getattr(state["turn"], "raw_query", "") or "")


def _turn_compact_query(state: GraphState) -> str:
    return _turn_raw_query(state).replace(" ", "")


def _turn_extra(state: GraphState) -> dict[str, Any]:
    return dict(getattr(state["turn"], "extra", {}) or {})


def _routing_decision(state: GraphState):
    return _routing_decision_for_turn(state["turn"])


def _routing_action(state: GraphState) -> str:
    routing = _routing_decision(state)
    return str(getattr(routing, "required_action", "") or "").strip().lower() if routing is not None else ""


def _route_branch(state: GraphState) -> str:
    try:
        return str(route_decider(state) or "").strip().lower()
    except Exception:
        return ""


def _route_execution_mode(state: GraphState) -> str:
    routing = _routing_decision(state)
    if routing is None:
        return "simple"
    try:
        return str(route_execution_mode(routing).execution_mode or "").strip().lower() or "simple"
    except Exception:
        return "simple"


def _update_turn_extra(state: GraphState, **updates: Any) -> GraphState:
    turn = state["turn"]
    turn_extra = _turn_extra(state)
    turn_extra.update(updates)
    state["turn"] = turn.model_copy(update={"extra": turn_extra})
    return state


def _update_runtime_metrics(state: GraphState, **updates: Any) -> GraphState:
    runtime = state["runtime"]
    runtime_metrics = dict(getattr(runtime, "metrics", {}) or {})
    runtime_metrics.update(updates)
    state["runtime"] = runtime.model_copy(update={"metrics": runtime_metrics})
    return state


def _rewrite_routing_decision(
    state: GraphState,
    *,
    required_action: str | None = None,
    route_candidate: str | None = None,
    route_reason: str | None = None,
) -> GraphState:
    turn = state["turn"]
    routing = _routing_decision(state)
    if routing is None:
        return state
    updates: dict[str, Any] = {"blocked": False, "blocked_reason": None}
    if required_action is not None:
        updates["required_action"] = required_action
    if route_candidate is not None:
        updates["route_candidate"] = route_candidate
    if route_reason is not None:
        updates["route_reason"] = route_reason
    state["turn"] = turn.model_copy(update={"routing_decision": routing.model_copy(update=updates)})
    return state


def _requires_query_merge(state: GraphState) -> bool:
    compact = _turn_compact_query(state)
    if not compact:
        return False
    merge_tokens = ("对比", "比较", "和", "以及", "还是", "一起", "附近", "推荐")
    return any(token in compact for token in merge_tokens) and any(token in compact for token in ("店", "券", "营业", "路线", "优惠", "推荐"))


def _preset_response(
    state: GraphState,
    *,
    response_node: str,
    answer_text: str,
    route_candidate: str | None = None,
    route_reason: str | None = None,
) -> GraphState:
    state = _rewrite_routing_decision(
        state,
        required_action="direct_answer",
        route_candidate=route_candidate,
        route_reason=route_reason,
    )
    turn = state["turn"]
    turn_extra = _turn_extra(state)
    turn_extra.update(
        {
            "response_node": response_node,
            "response_path": response_node,
            "preset_response_text": answer_text,
            "response_kind": route_candidate,
        }
    )
    state["turn"] = turn.model_copy(update={"final_answer": answer_text, "extra": turn_extra})
    runtime = state["runtime"]
    runtime_metrics = dict(getattr(runtime, "metrics", {}) or {})
    runtime_metrics["response_node"] = response_node
    runtime_metrics["response_path"] = response_node
    state["runtime"] = runtime.model_copy(update={"metrics": runtime_metrics})
    return state


def _apply_retry_quality_evaluation(
    turn: Any,
    turn_extra: dict[str, Any],
    *,
    answer_text: str,
    evidence_claims: list[Any],
    tool_results: list[Any],
) -> tuple[Any, dict[str, Any]]:
    retry_snapshot = dict(turn_extra.get("retry_snapshot") or {})
    if not retry_snapshot:
        return turn, turn_extra

    pre_retry_answer = str(retry_snapshot.get("answer_text") or "").strip()
    pre_retry_evidence_count = int(retry_snapshot.get("evidence_count") or 0)
    quality = evaluate_retry_quality(
        pre_retry_answer=pre_retry_answer,
        post_retry_answer=str(answer_text or "").strip(),
        pre_retry_evidence_count=pre_retry_evidence_count,
        post_retry_evidence_count=len(evidence_claims),
        has_tool_result=bool(tool_results),
    )

    reverted_to_pre_retry = False
    if not quality.should_keep_retry and pre_retry_answer:
        turn = turn.model_copy(update={"final_answer": pre_retry_answer})
        answer_text = pre_retry_answer
        reverted_to_pre_retry = True

    retry_quality = {
        "pre_retry_score": quality.pre_retry_score,
        "post_retry_score": quality.post_retry_score,
        "improvement": quality.improvement,
        "should_keep_retry": quality.should_keep_retry,
        "reason": quality.reason,
        "reverted_to_pre_retry": reverted_to_pre_retry,
    }
    turn_extra["retry_quality"] = retry_quality

    review_report = turn_extra.get("review_report")
    if review_report is not None:
        extra = dict(getattr(review_report, "extra", {}) or {})
        extra["retry_quality"] = retry_quality
        setattr(review_report, "extra", extra)
        turn_extra["review_report"] = review_report

    return turn, turn_extra


def _collect_query_metrics(state: GraphState, bundle: Any = None) -> None:
    turn = state["turn"]
    turn_extra = _turn_extra(state)
    persistent = state.get("persistent")

    raw_query = str(getattr(turn, "raw_query", "") or "")
    answer_contract = turn_extra.get("answer_contract") or getattr(turn, "answer_contract", None)
    intent = str(getattr(answer_contract, "intent", "") or turn_extra.get("intent", "") or "")
    route = str(_routing_action(state) or "")
    answer_style = str(getattr(answer_contract, "answer_style", "") or "")

    target_shop_id = turn_extra.get("selected_shop_id") or getattr(persistent, "selected_shop_id", None)
    answer_shop_ids = list(turn_extra.get("answer_shop_ids") or [])
    forbidden_facets = list(getattr(answer_contract, "forbidden_facets", []) or [])
    realtime_facets = list(getattr(answer_contract, "realtime_facets", []) or [])
    evidence_claims = list(turn_extra.get("evidence_claims") or [])
    tool_results = list(turn_extra.get("tool_results") or [])

    degraded = bool(turn_extra.get("degraded") or getattr(state["runtime"], "degrade_to", ""))
    degraded_reason = str(getattr(state["runtime"], "degrade_to", "") or turn_extra.get("degraded_reason", "") or "")
    fallback = bool(turn_extra.get("fallback"))
    clarification_asked = bool(turn_extra.get("clarification_asked"))
    clarification_needed = bool(turn_extra.get("clarification_needed"))
    answer_text = str(getattr(turn, "final_answer", "") or "")
    retry_quality = dict(turn_extra.get("retry_quality") or {})
    review_report = turn_extra.get("review_report")

    metrics = QueryMetrics(
        query=raw_query,
        intent=intent,
        route=route,
        answer_style=answer_style,
        single_shop_mode=answer_style == "single_shop_review",
        recommendation_mode=answer_style == "multi_shop_recommendation",
        tool_called=bool(tool_results),
        tools_called=[str(item.get("tool_name", "")) for item in tool_results if isinstance(item, dict)],
        evidence_count=len(evidence_claims),
        target_shop_id=target_shop_id,
        answer_shop_ids=answer_shop_ids,
        forbidden_facets=forbidden_facets,
        realtime_facets=realtime_facets,
        degraded=degraded,
        degraded_reason=degraded_reason or None,
        fallback=fallback,
        clarification_asked=clarification_asked,
        clarification_needed=clarification_needed,
        answer_text=answer_text,
        retry_count=int(getattr(review_report, "retry_count", 0) or 0),
        retry_improved=(
            True
            if retry_quality and float(retry_quality.get("improvement", 0.0) or 0.0) > 0
            else False
            if retry_quality
            else None
        ),
    )
    business_metrics_collector.record_query(metrics)


def _resolve_facet_conflicts(state: GraphState) -> None:
    turn_extra = _turn_extra(state)
    answer_contract = turn_extra.get("answer_contract") or getattr(state["turn"], "answer_contract", None)
    if answer_contract is None:
        return

    realtime_facets = list(getattr(answer_contract, "realtime_facets", []) or [])
    if not realtime_facets:
        return

    tool_results = list(turn_extra.get("tool_results") or [])
    tool_result_map: dict[str, Any] = {}
    for tool_result in tool_results:
        if isinstance(tool_result, dict):
            facet = tool_result.get("facet") or tool_result.get("tool_name", "")
            tool_result_map[str(facet)] = tool_result

    evidence_claims = list(turn_extra.get("evidence_claims") or [])
    for facet in realtime_facets:
        if facet not in REALTIME_FACETS:
            continue
        tool_result = tool_result_map.get(facet)
        rag_result = None
        for claim in evidence_claims:
            claim_facet = str(getattr(claim, "facet", "") or (claim.get("facet", "") if isinstance(claim, dict) else ""))
            if claim_facet == facet:
                rag_result = claim
                break
        if tool_result or rag_result:
            resolution = resolve_realtime_conflict(facet=facet, tool_result=tool_result, rag_result=rag_result)
            if resolution:
                turn_extra[f"conflict_resolution_{facet}"] = {
                    "chosen_source": resolution.chosen_source,
                    "resolution_reason": resolution.resolution_reason,
                }


class WorkflowNodeAdapterMainGraphMixin:
    def resolve_target_shop(self, state: GraphState) -> GraphState:
        command = route_gate(state)
        updated = getattr(command, "update", None)
        if isinstance(updated, dict):
            state = updated
        turn_extra = _turn_extra(state)
        detail = {
            "branch": _route_branch(state) or None,
            "execution_mode": _route_execution_mode(state),
            "target_shop_id": turn_extra.get("target_shop_id"),
            "candidate_shop_ids": list(turn_extra.get("candidate_shop_ids") or []),
        }
        state = _update_turn_extra(state, resolve_target_shop=detail)
        state = _update_runtime_metrics(state, resolve_target_shop=detail)
        return state

    def clarification_or_reject(self, state: GraphState) -> GraphState:
        return _update_turn_extra(
            state,
            clarification_or_reject={
                "branch": _route_branch(state) or None,
                "execution_mode": _route_execution_mode(state),
            },
        )

    def build_answer_contract(self, state: GraphState) -> GraphState:
        turn = state["turn"]
        routing = _routing_decision(state)
        entity_join_result = _build_entity_join_result(turn)
        evidence_quality = getattr(turn, "evidence_quality", None)
        answer_contract = _build_answer_contract(turn, routing, evidence_quality, entity_join_result)
        turn_extra = _turn_extra(state)
        turn_extra["answer_contract"] = answer_contract.model_dump(mode="json")
        turn_extra["build_answer_contract"] = {
            "answer_style": getattr(answer_contract, "answer_style", None),
            "scope_kind": getattr(answer_contract, "scope_kind", None),
            "required_facets": [
                str(facet.get("name") or "").strip()
                for facet in answer_contract.required_facets
                if str(facet.get("name") or "").strip()
            ],
        }
        state["turn"] = turn.model_copy(update={"answer_contract": answer_contract, "extra": turn_extra})
        state = _update_runtime_metrics(state, build_answer_contract=turn_extra["build_answer_contract"])
        return state

    def build_source_contract(self, state: GraphState) -> GraphState:
        turn = state["turn"]
        routing = _routing_decision(state)
        turn_extra = _turn_extra(state)
        answer_contract = getattr(turn, "answer_contract", None)
        if answer_contract is None:
            entity_join_result = _build_entity_join_result(turn)
            answer_contract = _build_answer_contract(turn, routing, getattr(turn, "evidence_quality", None), entity_join_result)
        selected_shop_id = turn_extra.get("selected_shop_id") or turn_extra.get("target_shop_id")
        try:
            selected_shop_id = int(selected_shop_id) if selected_shop_id not in (None, "") else None
        except (TypeError, ValueError):
            selected_shop_id = None
        current_shop = str(turn_extra.get("current_shop") or "").strip() or None
        explicit_query_shop = str(turn_extra.get("explicit_query_shop") or "").strip() or None
        source_contract = _build_source_contract(
            turn,
            routing,
            answer_contract,
            selected_shop_id=selected_shop_id,
            current_shop=current_shop,
            explicit_query_shop=explicit_query_shop,
        )
        turn_extra["source_contract"] = source_contract.model_dump(mode="json")
        turn_extra["build_source_contract"] = {
            "scope_kind": getattr(source_contract, "scope_kind", None),
            "target_shop_id": getattr(source_contract, "target_shop_id", None),
            "candidate_shop_ids": list(getattr(source_contract, "candidate_shop_ids", []) or []),
        }
        state["turn"] = turn.model_copy(update={"source_contract": source_contract, "extra": turn_extra})
        state = _update_runtime_metrics(state, build_source_contract=turn_extra["build_source_contract"])
        return state

    def complexity_router(self, state: GraphState) -> GraphState:
        routing = _routing_decision(state)
        complexity = route_execution_mode(routing)
        return _update_turn_extra(state, complexity_router=complexity.to_dict())

    def hard_guard(self, state: GraphState) -> GraphState:
        turn = state["turn"]
        persistent = state.get("persistent")
        client_context = dict(getattr(state.get("runtime"), "client_context", {}) or {})
        result = check_hard_guard(str(getattr(turn, "raw_query", "") or ""), persistent, client_context)
        if result.blocked and result.required_action:
            state = _rewrite_routing_decision(
                state,
                required_action=result.required_action,
                route_candidate=result.route_candidate,
                route_reason=result.reason,
            )
        return _update_turn_extra(
            state,
            hard_guard={
                "blocked": bool(result.blocked),
                "reason": result.reason,
                "required_action": result.required_action,
                "route_candidate": result.route_candidate,
            },
        )

    def request_legality(self, state: GraphState) -> GraphState:
        routing = _routing_decision(state)
        return _update_turn_extra(
            state,
            request_legality={
                "checked": True,
                "blocked": bool(getattr(routing, "blocked", False)) if routing is not None else False,
                "required_action": _routing_action(state) or None,
                "route_reason": str(getattr(routing, "route_reason", "") or "").strip() if routing is not None else None,
            },
        )

    def query_safety(self, state: GraphState) -> GraphState:
        routing = _routing_decision(state)
        return _update_turn_extra(
            state,
            query_safety={
                "checked": True,
                "blocked": bool(getattr(routing, "blocked", False)) if routing is not None else False,
                "required_action": _routing_action(state) or None,
            },
        )

    def query_merge_for_local_life(self, state: GraphState) -> GraphState:
        return _update_turn_extra(
            state,
            query_merge_for_local_life={
                "checked": True,
                "needs_merge": _requires_query_merge(state),
            },
        )

    def merged_query_safety(self, state: GraphState) -> GraphState:
        routing = _routing_decision(state)
        client_context = dict(getattr(state.get("runtime"), "client_context", {}) or {})
        result = check_query_safety(_turn_raw_query(state), client_context=client_context)
        if routing is not None and bool(getattr(routing, "blocked", False)):
            from dataclasses import replace

            result = replace(
                result,
                blocked=True,
                allowed=False,
                required_action="reject",
                reason=str(getattr(routing, "blocked_reason", "") or getattr(routing, "route_reason", "") or result.reason),
            )
        return _update_turn_extra(
            state,
            merged_query_safety={
                "checked": True,
                "query": _turn_raw_query(state),
                "blocked": bool(result.blocked),
                "allowed": bool(result.allowed),
                "required_action": str(getattr(result, "required_action", "") or "").strip() or None,
                "reason": str(getattr(result, "reason", "") or "").strip() or None,
            },
        )

    def top_level_intent_router(self, state: GraphState) -> GraphState:
        routing = _routing_decision(state)
        route = "clarification_node"
        if routing is not None and (bool(getattr(routing, "blocked", False)) or str(getattr(routing, "required_action", "") or "").strip().lower() == "reject"):
            route = "safety_reject_response"
            payload = {
                "route": route,
                "query": _turn_raw_query(state),
                "blocked": True,
            }
            return _update_turn_extra(state, top_level_intent_router=payload)
        if routing is not None:
            routing_action = str(getattr(routing, "required_action", "") or "").strip().lower()
            route_candidate = str(getattr(routing, "route_candidate", "") or "").strip().lower()
            intent_name = str(getattr(getattr(routing, "intent", None), "name", "") or "").strip().lower()
            if routing_action == "direct_answer" and (route_candidate == "out_of_scope" or intent_name == "out_of_scope"):
                payload = {
                    "route": "out_of_scope_response",
                    "query": _turn_raw_query(state),
                    "intent": "out_of_scope",
                    "confidence": float(getattr(routing, "confidence", 0.0) or 0.0),
                    "reason": str(getattr(routing, "route_reason", "") or "").strip() or "top_level_out_of_scope",
                    "source": "routing_decision",
                    "matched_signals": [],
                    "requires_current_shop": False,
                    "requires_candidate_context": False,
                }
                return _update_turn_extra(state, top_level_intent_router=payload)

        turn_extra = _turn_extra(state)
        existing_intent_info = turn_extra.get("top_level_intent")
        if existing_intent_info and isinstance(existing_intent_info, dict):
            intent = existing_intent_info.get("intent")
            requires_current_shop = existing_intent_info.get("requires_current_shop", False)
            requires_candidate_context = existing_intent_info.get("requires_candidate_context", False)
            source = existing_intent_info.get("source", "existing")
            confidence = existing_intent_info.get("confidence", 0.0)
            reason = existing_intent_info.get("reason", "")
            matched_signals = existing_intent_info.get("matched_signals", [])
        else:
            intent = "local_life"
            requires_current_shop = False
            requires_candidate_context = False
            source = "default"
            confidence = 0.8
            reason = "default_local_life"
            matched_signals = []

        if intent in {"identity", "capability", "help"}:
            route = "identity_answer" if intent == "identity" else "capability_answer"
        elif intent in {"direct_chat"}:
            route = "direct_chat_answer"
        elif intent in {"unsafe", "math_or_code", "document_or_knowledge", "planning", "out_of_scope"}:
            route = "out_of_scope_response"
        elif intent in {"local_life", "recommendation", "comparison"}:
            if requires_candidate_context:
                persistent = state.get("persistent")
                last_candidates = list(getattr(persistent, "last_candidates", None) or [])
                route = "clarification_node" if not last_candidates else "resolve_target_shop"
            elif requires_current_shop:
                has_current_shop = bool(
                    turn_extra.get("current_shop")
                    or turn_extra.get("selected_shop_id")
                    or turn_extra.get("explicit_query_shop")
                    or turn_extra.get("target_shop_name")
                )
                route = "clarification_node" if not has_current_shop else "resolve_target_shop"
            else:
                route = "resolve_target_shop"
        elif str(getattr(state["turn"], "decision", "") or "").strip().lower() == "direct_answer" and existing_intent_info is None:
            route = "final_answer"
        if route == "clarification_node" and str(getattr(state["turn"], "decision", "") or "").strip().lower() == "direct_answer":
            route = "final_answer"

        raw_query = _turn_raw_query(state)
        normalized_query = raw_query.replace(" ", "")
        _LOGGER.info(
            "top_level_intent_route raw_query=%s normalized_query=%s intent=%s route=%s confidence=%.2f source=%s matched_signals=%s reason=%s",
            raw_query,
            normalized_query,
            intent,
            route,
            confidence,
            source,
            matched_signals,
            reason,
        )
        return _update_turn_extra(
            state,
            top_level_intent_router={
                "route": route,
                "query": raw_query,
                "intent": intent,
                "confidence": confidence,
                "reason": reason,
                "source": source,
                "matched_signals": list(matched_signals or []),
                "requires_current_shop": bool(requires_current_shop),
                "requires_candidate_context": bool(requires_candidate_context),
            },
        )

    def identity_answer(self, state: GraphState) -> GraphState:
        return _preset_response(
            state,
            response_node="identity_answer",
            answer_text="我是本地生活助手，可以帮你查店铺信息、优惠券、营业状态和推荐。",
            route_candidate="profile",
            route_reason="top_level_identity",
        )

    def capability_answer(self, state: GraphState) -> GraphState:
        return _preset_response(
            state,
            response_node="capability_answer",
            answer_text="我可以帮你查店铺详情、优惠券、营业时间、距离和推荐。",
            route_candidate="low_info",
            route_reason="top_level_capability",
        )

    def direct_chat_answer(self, state: GraphState) -> GraphState:
        return _preset_response(
            state,
            response_node="direct_chat_answer",
            answer_text="可以，我在。你也可以继续问我本地生活相关问题。",
            route_candidate="greeting",
            route_reason="top_level_direct_chat",
        )

    def out_of_scope_response(self, state: GraphState) -> GraphState:
        return _preset_response(
            state,
            response_node="out_of_scope_response",
            answer_text="这个问题超出了本地生活查询范围，我先帮你处理店铺相关的问题。",
            route_candidate="empty",
            route_reason="top_level_out_of_scope",
        )

    def illegal_request_response(self, state: GraphState) -> GraphState:
        return _preset_response(
            state,
            response_node="illegal_request_response",
            answer_text="你可以补充一点信息吗？比如店名、城市，或者你想查的内容。",
            route_candidate="low_info",
            route_reason="request_legality_failed",
        )

    def safety_reject_response(self, state: GraphState) -> GraphState:
        return _preset_response(
            state,
            response_node="safety_reject_response",
            answer_text="抱歉，这个问题涉及安全限制，我不能继续处理。",
            route_candidate="low_info",
            route_reason="query_safety_rejected",
        )

    def direct_executor(self, state: GraphState) -> GraphState:
        return _update_turn_extra(
            state,
            direct_executor={
                "branch": _route_branch(state) or None,
                "execution_mode": _route_execution_mode(state),
            },
        )

    def workflow_executor(self, state: GraphState) -> GraphState:
        return _update_turn_extra(
            state,
            workflow_executor={
                "branch": _route_branch(state) or None,
                "execution_mode": _route_execution_mode(state),
            },
        )

    def clarification_node(self, state: GraphState) -> GraphState:
        return _update_turn_extra(
            state,
            clarification_node={
                "branch": _route_branch(state) or None,
                "execution_mode": _route_execution_mode(state),
            },
        )

    def rule_review(self, state: GraphState) -> GraphState:
        turn_extra = _turn_extra(state)
        turn_extra["rule_review"] = {
            "reviewed": True,
            "required_action": _routing_action(state) or None,
            "route_branch": _route_branch(state) or None,
        }
        state["turn"] = state["turn"].model_copy(update={"extra": turn_extra})
        return state

    def select_required_sources(self, state: GraphState) -> GraphState:
        turn_extra = _turn_extra(state)
        branch = _route_branch(state)
        route = "recommendation_executor" if branch == "recommendation" else "tool_executor" if branch == "tool" else "rag_executor"
        turn_extra["select_required_sources"] = {
            "selected_route": route,
            "execution_mode": str(getattr(state["turn"], "execution_mode", "") or "").strip().lower() or None,
            "branch": branch or None,
        }
        state["turn"] = state["turn"].model_copy(update={"extra": turn_extra})
        return state

    def final_answer(self, state: GraphState) -> GraphState:
        turn = state["turn"]
        if not str(getattr(turn, "final_answer", "") or "").strip():
            state = self.compose_answer(state)
            turn = state["turn"]
        if str(getattr(turn, "execution_mode", "") or "").strip().lower() == "plan_execute":
            summary = getattr(turn, "final_task_summary", None)
            if summary is not None:
                summary_text = str(getattr(summary, "final_decision", "") or "").strip()
                summary_status = str(getattr(summary, "status", "") or "").strip()
                planned_answer = f"Plan execution {summary_status}: {summary_text}".strip()
                if summary_text:
                    turn_extra = _turn_extra(state)
                    turn_extra["plan_execution_answer"] = planned_answer
                    turn = turn.model_copy(update={"final_answer": planned_answer, "extra": turn_extra})
                    state["turn"] = turn
        turn_extra = _turn_extra(state)
        turn_extra["final_answer_ready"] = True
        state["turn"] = turn.model_copy(update={"extra": turn_extra})
        runtime = state["runtime"]
        runtime_metrics = dict(getattr(runtime, "metrics", {}) or {})
        runtime_metrics["final_answer"] = True
        state["runtime"] = runtime.model_copy(update={"metrics": runtime_metrics})
        return state

    def merge_or_rank(self, state: GraphState) -> GraphState:
        turn = state["turn"]
        turn_extra = _turn_extra(state)
        try:
            _resolve_facet_conflicts(state)
        except Exception:
            pass
        ranked_candidates = list(turn_extra.get("ranked_candidates") or [])
        evidence_claims = list(turn_extra.get("evidence_claims") or [])
        turn_extra["merge_or_rank"] = {
            "ranked_candidate_count": len(ranked_candidates),
            "evidence_claim_count": len(evidence_claims),
            "route_branch": _route_branch(state) or None,
        }
        state["turn"] = turn.model_copy(update={"extra": turn_extra})
        return state

    def contract_review(self, state: GraphState) -> GraphState:
        turn = state["turn"]
        turn_extra = _turn_extra(state)
        turn_extra["contract_review"] = {
            "reviewed": True,
            "branch": _route_branch(state) or None,
            "route_candidate": getattr(_routing_decision(state), "route_candidate", None),
        }
        state["turn"] = turn.model_copy(update={"extra": turn_extra})
        return state

    def prepare_retry(self, state: GraphState) -> GraphState:
        turn = state["turn"]
        turn_extra = _turn_extra(state)
        review_report = turn_extra.get("review_report")
        if review_report:
            from learning_agent_service.domain.contracts import RewriteDecision

            retry_count = int(getattr(review_report, "retry_count", 0)) + 1
            setattr(review_report, "retry_count", retry_count)
            decision = str(getattr(review_report, "decision", "") or "").strip()
            failure_category = str(getattr(review_report, "extra", {}).get("failure_category") or "").strip()
            retry_reason = str(getattr(review_report, "reason", "") or "").strip() or failure_category or "retry_requested"
            if decision == "retry_tool":
                tool_result = getattr(turn, "tool_result", None)
                raw_tool_result = getattr(turn, "raw_tool_result", None)
                active_tool_result = tool_result or raw_tool_result
                if isinstance(active_tool_result, Mapping):
                    tool_name = str(active_tool_result.get("tool_name", "") or "").strip()
                else:
                    tool_name = str(getattr(active_tool_result, "tool_name", "") or "").strip()
                rewrite = RewriteDecision(
                    original_query=str(getattr(turn, "raw_query", "")),
                    rewritten_query=str(getattr(turn, "raw_query", "")),
                    preserved_constraints=[str(item) for item in [tool_name, failure_category, getattr(review_report, "retry_target", "")] if str(item).strip()],
                    confidence=0.55,
                    should_retrieve=True,
                    reason="retry_tool_failure",
                )
            else:
                repair_hint = getattr(review_report, "repair_hint", "")
                rewrite = RewriteDecision(
                    original_query=str(getattr(turn, "raw_query", "")),
                    rewritten_query=str(getattr(turn, "raw_query", "")) + f" {repair_hint}",
                    preserved_constraints=[str(item) for item in getattr(review_report, "failed_facets", []) if str(item).strip()],
                    confidence=0.6,
                    should_retrieve=True,
                    reason="retry_repair_answer",
                )
            if "retry_snapshot" not in turn_extra:
                turn_extra["retry_snapshot"] = {
                    "answer_text": str(
                        getattr(turn, "final_answer", "")
                        or turn_extra.get("plan_execution_answer")
                        or turn_extra.get("preset_response_text")
                        or ""
                    ).strip(),
                    "evidence_count": len(list(turn_extra.get("evidence_claims") or [])),
                    "tool_result_count": len(list(turn_extra.get("tool_results") or [])),
                    "retry_count": retry_count,
                    "retry_origin": "tool" if decision == "retry_tool" else "answer",
                    "tool_name": tool_name if decision == "retry_tool" else None,
                    "retry_reason": retry_reason,
                    "failure_category": failure_category or None,
                }
            turn_extra["rewrite_decision"] = rewrite
            routing = getattr(turn, "routing_decision", None)
            if routing is not None:
                turn = turn.model_copy(update={"routing_decision": routing.model_copy(update={"rewrite_decision": rewrite})})
            if "rag_result" in turn_extra:
                del turn_extra["rag_result"]
            turn_extra["review_report"] = review_report
        state["turn"] = turn.model_copy(update={"extra": turn_extra})
        return state

    def final_answer_safety(self, state: GraphState) -> GraphState:
        turn = state["turn"]
        turn_extra = _turn_extra(state)
        plan_execution_answer = str(turn_extra.get("plan_execution_answer") or "").strip()
        raw_answer = str(plan_execution_answer or getattr(turn, "final_answer", "") or turn_extra.get("preset_response_text") or "").strip()
        ranked_candidates = list(turn_extra.get("ranked_candidates") or [])
        evidence_claims = list(turn_extra.get("evidence_claims") or [])
        shop_lookup: dict[int, str] = {}
        for candidate in ranked_candidates:
            if not isinstance(candidate, Mapping):
                continue
            shop_id = candidate.get("shop_id")
            shop_name = candidate.get("name") or candidate.get("shop_name")
            if shop_id not in (None, "") and shop_name:
                try:
                    shop_lookup[int(shop_id)] = str(shop_name)
                except Exception:
                    pass
        safety_result = apply_final_answer_safety(
            answer_text=raw_answer,
            answer_contract=turn_extra.get("answer_contract") or getattr(turn, "answer_contract", None),
            ranked_candidates=ranked_candidates,
            evidence_claims=evidence_claims,
            evidence_pack=getattr(turn, "evidence_pack", None),
            facet_result_bundle=turn_extra.get("facet_result_bundle"),
            user_need=turn_extra.get("user_need"),
            route_gate=turn_extra.get("route_gate"),
            source_contract=turn_extra.get("source_contract"),
            review_report=turn_extra.get("review_report"),
            tool_results=list(turn_extra.get("tool_results") or []),
            shop_lookup=shop_lookup or None,
        )
        if getattr(safety_result, "answer_text", None):
            final_text = str(safety_result.answer_text or "").strip()
            if plan_execution_answer:
                final_text = plan_execution_answer
            turn = turn.model_copy(update={"final_answer": final_text})
        turn, turn_extra = _apply_retry_quality_evaluation(
            turn,
            turn_extra,
            answer_text=str(getattr(turn, "final_answer", "") or raw_answer),
            evidence_claims=evidence_claims,
            tool_results=list(turn_extra.get("tool_results") or []),
        )
        turn_extra["final_answer_safety"] = safety_result.to_dict() if hasattr(safety_result, "to_dict") else asdict(safety_result)
        state["turn"] = turn.model_copy(update={"extra": turn_extra})
        runtime = state["runtime"]
        runtime_metrics = dict(getattr(runtime, "metrics", {}) or {})
        runtime_metrics["final_answer_safety"] = turn_extra["final_answer_safety"]
        state["runtime"] = runtime.model_copy(update={"metrics": runtime_metrics})
        return state

    def final_safety_fallback(self, state: GraphState) -> GraphState:
        turn = state["turn"]
        turn_extra = _turn_extra(state)
        safety_result = dict(turn_extra.get("final_answer_safety") or {})
        plan_execution_answer = str(turn_extra.get("plan_execution_answer") or "").strip()
        if safety_result.get("blocked") and not str(getattr(turn, "final_answer", "") or "").strip():
            fallback_text = str(safety_result.get("answer_text") or "抱歉，这条回复暂时无法安全输出。").strip()
            turn = turn.model_copy(update={"final_answer": plan_execution_answer or fallback_text})
        turn_extra["final_safety_fallback"] = {
            "applied": bool(safety_result.get("blocked")),
            "blocked": bool(safety_result.get("blocked")),
        }
        state["turn"] = turn.model_copy(update={"extra": turn_extra})
        return state

    def repair_answer(self, state: GraphState) -> GraphState:
        turn = state["turn"]
        turn_extra = _turn_extra(state)
        safety_result = dict(turn_extra.get("final_answer_safety") or {})
        plan_execution_answer = str(turn_extra.get("plan_execution_answer") or "").strip()
        repaired_text = str(
            plan_execution_answer
            or safety_result.get("answer_text")
            or turn_extra.get("preset_response_text")
            or getattr(turn, "final_answer", "")
            or ""
        ).strip()
        if repaired_text:
            turn = turn.model_copy(update={"final_answer": repaired_text})
        turn_extra["repair_answer"] = {
            "repaired": bool(safety_result.get("repaired_text")),
            "severity": safety_result.get("severity"),
        }
        state["turn"] = turn.model_copy(update={"extra": turn_extra})
        return state

    def final_with_limitations(self, state: GraphState) -> GraphState:
        turn = state["turn"]
        turn_extra = _turn_extra(state)
        safety_result = dict(turn_extra.get("final_answer_safety") or {})
        plan_execution_answer = str(turn_extra.get("plan_execution_answer") or "").strip()
        issues = list(safety_result.get("issues") or [])
        current_answer = str(plan_execution_answer or getattr(turn, "final_answer", "") or "").strip()
        if issues and current_answer and not current_answer.endswith("。"):
            turn = turn.model_copy(update={"final_answer": f"{current_answer}（以上为当前可确认信息）"})
        turn_extra["final_with_limitations"] = {
            "issues": issues,
            "issue_count": len(issues),
        }
        state["turn"] = turn.model_copy(update={"extra": turn_extra})
        return state

    def response_builder(self, state: GraphState) -> GraphState:
        turn = state["turn"]
        turn_extra = _turn_extra(state)
        from learning_agent_service.local_life.dialog_state_machine import DialogContext, DialogState, dialog_state_machine

        persistent = state.get("persistent")
        if persistent:
            semantic_context = turn_extra.get("semantic_context")
            if isinstance(semantic_context, Mapping):
                follow_up_kind = str(semantic_context.get("follow_up_kind") or "").strip()
                if follow_up_kind == "comparison_completion":
                    persistent.dialog_state = persistent.dialog_state or "comparing"
                    persistent.dialog_task = "comparison"
                elif follow_up_kind in {"intent_ellipsis", "constraint_inheritance"}:
                    persistent.dialog_state = persistent.dialog_state or "follow_up"
                    persistent.dialog_task = "recommendation"
                elif follow_up_kind == "entity_reference":
                    persistent.dialog_state = persistent.dialog_state or "follow_up"
                    persistent.dialog_task = "detail"
                comparison_targets = semantic_context.get("comparison_targets")
                if isinstance(comparison_targets, list):
                    target_names = [
                        str(item.get("name") or item.get("shop_name") or item.get("target") or "").strip()
                        for item in comparison_targets
                        if isinstance(item, Mapping)
                    ]
                    target_names = [name for name in target_names if name]
                    if target_names and not getattr(persistent, "dialog_comparison_targets", None):
                        persistent.dialog_comparison_targets = list(dict.fromkeys(target_names))
            dialog_ctx = DialogContext(
                current_state=DialogState(str(getattr(persistent, "dialog_state", "") or DialogState.IDLE.value)),
                transition_count=int(getattr(persistent, "dialog_transition_count", 0) or 0),
                current_task=getattr(persistent, "dialog_task", None),
                active_intent=getattr(persistent, "dialog_intent", None),
                comparison_targets=list(getattr(persistent, "dialog_comparison_targets", []) or []),
                pending_slots=list(getattr(persistent, "dialog_pending_slots", []) or []),
            )
            has_clarification = bool(turn_extra.get("clarification_needed"))
            has_results = bool(turn_extra.get("evidence_claims"))
            answer_contract = turn_extra.get("answer_contract") or getattr(turn, "answer_contract", None)
            is_comparison = str(getattr(answer_contract, "answer_style", "") or "") == "comparison"
            has_error = bool(turn_extra.get("error") or getattr(state.get("runtime"), "error", None))
            is_degraded = bool(turn_extra.get("degraded") or getattr(state.get("runtime"), "degrade_to", None))
            trigger = dialog_state_machine.determine_trigger(
                dialog_ctx,
                has_clarification=has_clarification,
                has_results=has_results,
                is_comparison=is_comparison,
                has_error=has_error,
                is_degraded=is_degraded,
            )
            if trigger:
                new_ctx = dialog_state_machine.transition(dialog_ctx, trigger)
                persistent.dialog_state = new_ctx.current_state.value
                persistent.dialog_transition_count = new_ctx.transition_count
                persistent.dialog_task = new_ctx.current_task
                persistent.dialog_intent = new_ctx.active_intent
                persistent.dialog_comparison_targets = new_ctx.comparison_targets
                persistent.dialog_pending_slots = new_ctx.pending_slots

        bundle = None
        try:
            from learning_agent_service.local_life.schemas import LocalLifeSlots
            turn_extra["answer_text"] = str(getattr(turn, "final_answer", "") or turn_extra.get("answer_text") or "").strip()

            bundle = build_response_bundle(
                raw_query=str(getattr(turn, "raw_query", "") or ""),
                slots=LocalLifeSlots(**(getattr(turn, "slots", None) or {})),
                answer_contract=turn_extra.get("answer_contract") or getattr(turn, "answer_contract", None),
                ranked_candidates=list(turn_extra.get("ranked_candidates") or []),
                evidence_claims=list(turn_extra.get("evidence_claims") or []),
                answer_plan=turn_extra.get("task_plan") or getattr(turn, "task_plan", None),
                verification_result=turn_extra.get("answer_verifier_result"),
                evidence_pack=getattr(turn, "evidence_pack", None),
                page=str((state.get("runtime_context", {}) or {}).get("page") or (state["runtime"].client_context or {}).get("page") or ""),
                current_topic=str(getattr(state["persistent"], "current_topic", "") or ""),
                selected_shop_id=turn_extra.get("selected_shop_id"),
                current_shop=str(turn_extra.get("current_shop") or getattr(state["persistent"], "current_shop", "") or ""),
                client_context=dict(getattr(state["runtime"], "client_context", {}) or {}),
                approval_required=bool(getattr(turn, "need_human_approval", False)),
                approval_request=turn_extra.get("approval_request"),
                transaction_draft=turn_extra.get("transaction_draft"),
                safety_result=turn_extra.get("final_answer_safety"),
                route_decision=_routing_action(state) or None,
                route_reason=str(getattr(_routing_decision(state), "route_reason", "") or ""),
                current_stage=getattr(turn, "current_stage", None),
                stage_status=getattr(turn, "stage_status", None),
                stage_timeline=list((state["runtime"].metrics or {}).get("stage_timeline", []) or []),
                model_hint=turn_extra,
                source_mode=str(turn_extra.get("source_mode") or ""),
                degraded_reason=str(getattr(state["runtime"], "degrade_to", "") or ""),
                knowledge_freshness=turn_extra.get("knowledge_freshness"),
                user_need=turn_extra.get("user_need"),
                facet_result_bundle=turn_extra.get("facet_result_bundle"),
                graph_trace=turn_extra.get("phase5_trace") or turn_extra.get("phase4_trace"),
            )
            turn_extra["response_bundle"] = bundle.model_dump(mode="json") if hasattr(bundle, "model_dump") else dict(bundle)
        except Exception:
            pass

        try:
            _collect_query_metrics(state, bundle)
        except Exception:
            pass

        state["turn"] = turn.model_copy(update={"extra": turn_extra})
        runtime = state["runtime"]
        runtime_metrics = dict(getattr(runtime, "metrics", {}) or {})
        runtime_metrics["response_builder"] = True
        state["runtime"] = runtime.model_copy(update={"metrics": runtime_metrics})
        return state
