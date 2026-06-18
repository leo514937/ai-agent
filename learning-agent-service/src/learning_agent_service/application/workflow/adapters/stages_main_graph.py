from __future__ import annotations

import logging
from dataclasses import asdict
from collections.abc import Mapping
from typing import Any

from .helpers import (
    _build_answer_contract,
    _build_entity_join_result,
    _build_source_contract,
)
from .helpers import route_execution_mode
from .helpers import check_hard_guard
from .helpers import check_query_safety
from ...routing_registry import resolve_top_level_route
from learning_agent_service.domain.utils import as_mapping as _as_mapping
from learning_agent_service.local_life.business_metrics import (
    QueryMetrics,
    business_metrics_collector,
)
from learning_agent_service.local_life.context_recovery import recover_follow_up_context
from learning_agent_service.local_life.final_answer_safety import apply_final_answer_safety
from learning_agent_service.local_life.response_builder.bundle import build_response_bundle
from learning_agent_service.local_life.realtime_conflict_resolver import (
    REALTIME_FACETS,
    resolve_realtime_conflict,
)
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
    return (
        str(getattr(routing, "required_action", "") or "").strip().lower()
        if routing is not None
        else ""
    )


def _route_branch(state: GraphState) -> str:
    try:
        from learning_agent_service.application.workflow.subgraphs import (
            route_decider as _route_decider,
        )

        return str(_route_decider(state) or "").strip().lower()
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
    # 这里只做“要不要把追问和上一轮语义合并”的轻量判断，主要覆盖“有券吗”“离我多远”这类追问。
    compact = _turn_compact_query(state)
    if not compact:
        return False
    merge_tokens = ("对比", "比较", "和", "以及", "还是", "一起", "附近", "推荐")
    return any(token in compact for token in merge_tokens) and any(
        token in compact for token in ("店", "券", "营业", "路线", "优惠", "推荐")
    )


def _preset_response(
    state: GraphState,
    *,
    response_node: str,
    answer_text: str,
    route_candidate: str | None = None,
    route_reason: str | None = None,
) -> GraphState:
    # 顶层直答、拒答和能力介绍等分支会走这里，统一封装路由元信息和答复文本。
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

    target_shop_id = turn_extra.get("selected_shop_id") or getattr(
        persistent, "selected_shop_id", None
    )
    answer_shop_ids = list(turn_extra.get("answer_shop_ids") or [])
    forbidden_facets = list(getattr(answer_contract, "forbidden_facets", []) or [])
    realtime_facets = list(getattr(answer_contract, "realtime_facets", []) or [])
    evidence_claims = list(turn_extra.get("evidence_claims") or [])
    tool_results = list(turn_extra.get("tool_results") or [])

    degraded = bool(turn_extra.get("degraded") or getattr(state["runtime"], "degrade_to", ""))
    degraded_reason = str(
        getattr(state["runtime"], "degrade_to", "") or turn_extra.get("degraded_reason", "") or ""
    )
    fallback = bool(turn_extra.get("fallback"))
    clarification_asked = bool(turn_extra.get("clarification_asked"))
    clarification_needed = bool(turn_extra.get("clarification_needed"))
    answer_text = str(getattr(turn, "final_answer", "") or "")
    retry_quality = dict(turn_extra.get("retry_quality") or {})
    review_report = turn_extra.get("review_report")
    response_bundle = _as_mapping(bundle)
    bundle_metrics = _as_mapping(response_bundle.get("metrics")) if response_bundle else {}
    safety_result = _as_mapping(turn_extra.get("final_answer_safety"))
    answer_quality = _as_mapping(bundle_metrics.get("answer_quality"))

    metrics = QueryMetrics(
        query=raw_query,
        intent=intent,
        route=route,
        answer_style=answer_style,
        single_shop_mode=answer_style == "single_shop_review",
        recommendation_mode=answer_style == "multi_shop_recommendation",
        tool_called=bool(tool_results),
        tools_called=[
            str(item.get("tool_name", "")) for item in tool_results if isinstance(item, dict)
        ],
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
        llm_primary_output=bool(bundle_metrics.get("llm_primary_output")),
        quality_gate_rewrite=bool(
            bundle_metrics.get("quality_gate_rewrite")
            or answer_quality.get("expanded_by_quality_gate")
        ),
        contract_block_fallback=bool(safety_result.get("blocked")),
        template_fallback_used=bool(bundle_metrics.get("template_fallback_used")),
    )
    business_metrics_collector.record_query(metrics)


def _resolve_facet_conflicts(state: GraphState) -> None:
    turn_extra = _turn_extra(state)
    answer_contract = turn_extra.get("answer_contract") or getattr(
        state["turn"], "answer_contract", None
    )
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
        evidence_result = None
        for claim in evidence_claims:
            claim_facet = str(
                getattr(claim, "facet", "")
                or (claim.get("facet", "") if isinstance(claim, dict) else "")
            )
            if claim_facet == facet:
                evidence_result = claim
                break
        if tool_result or evidence_result:
            resolution = resolve_realtime_conflict(facet, tool_result, evidence_result)
            if resolution:
                turn_extra[f"conflict_resolution_{facet}"] = {
                    "chosen_source": resolution.chosen_source,
                    "resolution_reason": resolution.resolution_reason,
                }


class WorkflowNodeAdapterMainGraphMixin:
    def resolve_target_shop(self, state: GraphState) -> GraphState:
        # 把路由结果转成可观测的目标门店信息，供后续节点、指标和测试断言使用。
        from learning_agent_service.application.workflow.subgraphs import route_gate as _route_gate

        command = _route_gate(state)
        updated = getattr(command, "update", None)
        if isinstance(updated, dict):
            state = _update_turn_extra(state, **updated)
        turn = state["turn"]
        turn_extra = _turn_extra(state)
        routing = _routing_decision(state)
        selected_shop_id = turn_extra.get("selected_shop_id") or turn_extra.get("target_shop_id")
        selected_shop_name = (
            str(
                turn_extra.get("selected_shop_name")
                or turn_extra.get("target_shop_name")
                or turn_extra.get("current_shop")
                or ""
            ).strip()
            or None
        )
        explicit_query_shop = str(turn_extra.get("explicit_query_shop") or "").strip() or None
        current_shop = (
            str(
                turn_extra.get("current_shop") or selected_shop_name or explicit_query_shop or ""
            ).strip()
            or None
        )
        # 把门店锚点同步到 slots 和 persistent，避免工具规划器只看旧上下文。
        slots = dict(getattr(turn, "slots", {}) or {})
        if selected_shop_id is not None:
            slots["shop_id"] = selected_shop_id
            slots["selected_shop_id"] = selected_shop_id
        if current_shop:
            slots["shop_name"] = current_shop
            slots["selected_shop_name"] = current_shop
            slots["current_shop"] = current_shop
            slots.setdefault("shop_query", current_shop)
        elif explicit_query_shop:
            slots["shop_name"] = explicit_query_shop
            slots["selected_shop_name"] = explicit_query_shop
            slots["current_shop"] = explicit_query_shop
            slots.setdefault("shop_query", explicit_query_shop)
        if slots != dict(getattr(turn, "slots", {}) or {}):
            state["turn"] = turn.model_copy(update={"slots": slots})
            turn = state["turn"]
        if routing is not None:
            routing_extra = dict(getattr(routing, "extra", {}) or {})
            if selected_shop_id is not None:
                routing_extra["selected_shop_id"] = selected_shop_id
                routing_extra["target_shop_id"] = selected_shop_id
            if current_shop:
                routing_extra["selected_shop_name"] = current_shop
                routing_extra["current_shop"] = current_shop
                routing_extra["target_shop_name"] = current_shop
            elif explicit_query_shop:
                routing_extra["selected_shop_name"] = explicit_query_shop
                routing_extra["current_shop"] = explicit_query_shop
                routing_extra["target_shop_name"] = explicit_query_shop
            if explicit_query_shop:
                routing_extra["explicit_query_shop"] = explicit_query_shop
            state["turn"] = turn.model_copy(
                update={"routing_decision": routing.model_copy(update={"extra": routing_extra})}
            )
            turn = state["turn"]
        persistent = state.get("persistent")
        if persistent is not None:
            persistent_updates: dict[str, Any] = {}
            if current_shop:
                persistent_updates["current_shop"] = current_shop
                persistent_updates["selected_shop_name"] = current_shop
                if not getattr(persistent, "current_topic", None):
                    persistent_updates["current_topic"] = current_shop
            if selected_shop_id is not None:
                persistent_updates["selected_shop_id"] = selected_shop_id
            if persistent_updates:
                state["persistent"] = persistent.model_copy(update=persistent_updates)
        detail = {
            "branch": _route_branch(state) or None,
            "execution_mode": _route_execution_mode(state),
            "target_shop_id": selected_shop_id,
            "selected_shop_id": selected_shop_id,
            "current_shop": current_shop,
            "selected_shop_name": current_shop,
            "candidate_shop_ids": list(turn_extra.get("candidate_shop_ids") or []),
            "should_clarify": turn_extra.get("should_clarify", False),
            "target_shop.resolution_source": turn_extra.get("target_shop_resolution_source"),
            "target_shop.source": turn_extra.get("target_shop_source"),
        }
        state = _update_turn_extra(
            state,
            current_shop=current_shop,
            selected_shop_id=selected_shop_id,
            selected_shop_name=current_shop,
            explicit_query_shop=explicit_query_shop,
            target_shop_id=selected_shop_id,
            resolve_target_shop=detail,
        )
        state = _update_runtime_metrics(state, resolve_target_shop=detail)
        # 这里也把关键顶层字段同步到 metrics，方便测试和下游逻辑直接读取。
        runtime = state.get("runtime")
        if runtime:
            metrics = dict(getattr(runtime, "metrics", {}) or {})
            metrics["should_clarify"] = turn_extra.get("should_clarify", False)
            if selected_shop_id is not None:
                metrics["selected_shop_id"] = selected_shop_id
                metrics["target_shop_id"] = selected_shop_id
            if current_shop:
                metrics["current_shop"] = current_shop
                metrics["selected_shop_name"] = current_shop
            if turn_extra.get("target_shop_resolution_source"):
                metrics["target_shop.resolution_source"] = turn_extra.get(
                    "target_shop_resolution_source"
                )
            if turn_extra.get("target_shop_source"):
                metrics["target_shop.source"] = turn_extra.get("target_shop_source")
            state["runtime"] = runtime.model_copy(update={"metrics": metrics})
        return state

    def resolve_comparison_targets(self, state: GraphState) -> GraphState:
        # 对比场景要显式记录比较对象，避免后面把“和谁比”丢掉。
        turn_extra = _turn_extra(state)
        semantic_context = _as_mapping(turn_extra.get("semantic_context"))
        routing_contract = getattr(state["turn"], "routing_contract", None)
        detail = {
            "branch": _route_branch(state) or None,
            "execution_mode": _route_execution_mode(state),
            "comparison_shop_ids": list(getattr(routing_contract, "comparison_shop_ids", []) or [])
            if routing_contract is not None
            else [],
            "comparison_targets": list(
                turn_extra.get("comparison_targets")
                or semantic_context.get("comparison_targets")
                or []
            ),
        }
        state = _update_turn_extra(state, resolve_comparison_targets=detail)
        return _update_runtime_metrics(state, resolve_comparison_targets=detail)

    def prepare_recommendation_context(self, state: GraphState) -> GraphState:
        # 推荐分支会依赖追问语义和推荐意图，这里先固化会话恢复结果。
        turn_extra = _turn_extra(state)
        semantic_context = _as_mapping(turn_extra.get("semantic_context"))
        detail = {
            "branch": _route_branch(state) or None,
            "execution_mode": _route_execution_mode(state),
            "follow_up_kind": semantic_context.get("follow_up_kind"),
            "promoted_intent": semantic_context.get("promoted_intent"),
            "selected_sources": list(turn_extra.get("selected_sources") or []),
        }
        state = _update_turn_extra(state, prepare_recommendation_context=detail)
        return _update_runtime_metrics(state, prepare_recommendation_context=detail)

    def clarification_or_reject(self, state: GraphState) -> GraphState:
        # 当前轮如果信息不足或需拒答，这里只记录分支，后面统一收口。
        return _update_turn_extra(
            state,
            clarification_or_reject={
                "branch": _route_branch(state) or None,
                "execution_mode": _route_execution_mode(state),
            },
        )

    def build_answer_contract(self, state: GraphState) -> GraphState:
        # AnswerContract 决定本轮要回答什么、保留哪些 facet、允许哪些证据来源。
        turn = state["turn"]
        routing = _routing_decision(state)
        entity_join_result = _build_entity_join_result(turn)
        evidence_quality = getattr(turn, "evidence_quality", None)
        answer_contract = _build_answer_contract(
            turn, routing, evidence_quality, entity_join_result
        )
        turn_extra = _turn_extra(state)
        required_facets = [
            dict(facet)
            for facet in list(getattr(answer_contract, "required_facets", []) or [])
            if isinstance(facet, dict)
        ]
        realtime_facets = [
            str(item).strip()
            for item in list(getattr(answer_contract, "realtime_facets", []) or [])
            if str(item).strip()
        ]
        tool_requirements = dict(getattr(answer_contract, "tool_requirements", {}) or {})
        if routing is not None:
            routing_extra = dict(getattr(routing, "extra", {}) or {})
            if required_facets:
                routing_extra["required_facets"] = required_facets
            if realtime_facets:
                routing_extra["realtime_facets"] = list(realtime_facets)
            if tool_requirements.get("tool_candidates"):
                routing_extra["tool_candidates"] = list(
                    tool_requirements.get("tool_candidates") or []
                )
            routing_extra["answer_style"] = getattr(answer_contract, "answer_style", None)
            state["turn"] = turn.model_copy(
                update={"routing_decision": routing.model_copy(update={"extra": routing_extra})}
            )
            turn = state["turn"]
        turn_extra["answer_contract"] = answer_contract.model_dump(mode="json")
        turn_extra["build_answer_contract"] = {
            "answer_style": getattr(answer_contract, "answer_style", None),
            "scope_kind": getattr(answer_contract, "scope_kind", None),
            "required_facets": [
                str(facet.get("name") or "").strip()
                for facet in required_facets
                if str(facet.get("name") or "").strip()
            ],
            "realtime_facets": list(realtime_facets),
            "tool_candidates": list(tool_requirements.get("tool_candidates") or []),
        }
        state["turn"] = turn.model_copy(
            update={"answer_contract": answer_contract, "extra": turn_extra}
        )
        state = _update_runtime_metrics(
            state, build_answer_contract=turn_extra["build_answer_contract"]
        )
        return state

    def target_requirement_router(self, state: GraphState) -> GraphState:
        # 根据 answer_style 和 routing_contract 选择下一跳：单店、对比、推荐还是澄清。
        turn = state["turn"]
        turn_extra = _turn_extra(state)
        routing_contract = getattr(turn, "routing_contract", None)
        answer_contract = _as_mapping(
            turn_extra.get("answer_contract") or getattr(turn, "answer_contract", None)
        )
        semantic_context = _as_mapping(turn_extra.get("semantic_context"))
        answer_style = str(answer_contract.get("answer_style") or "").strip().lower()
        follow_up_kind = str(semantic_context.get("follow_up_kind") or "").strip().lower()
        comparison_shop_ids = (
            list(getattr(routing_contract, "comparison_shop_ids", []) or [])
            if routing_contract is not None
            else []
        )
        candidate_shop_ids = (
            list(getattr(routing_contract, "candidate_shop_ids", []) or [])
            if routing_contract is not None
            else []
        )
        target_shop_id = (
            getattr(routing_contract, "target_shop_id", None)
            if routing_contract is not None
            else None
        )
        single_shop_mode = (
            bool(getattr(routing_contract, "single_shop_mode", False))
            if routing_contract is not None
            else False
        )
        recommendation_mode = (
            bool(getattr(routing_contract, "recommendation_mode", False))
            if routing_contract is not None
            else False
        )
        need_clarify = (
            bool(getattr(routing_contract, "need_clarify", False))
            if routing_contract is not None
            else False
        )

        # 如果 routing_contract 里没有候选店，就检测“第一家/第二家/刚才那家”这类位置代词，
        # 再从 persistent.last_candidates 里把候选店补回来。
        if not candidate_shop_ids and not target_shop_id and not single_shop_mode:
            _POSITIONAL_PRONOUNS = (
                "第一家",
                "第二家",
                "第三家",
                "刚才那家",
                "上面那家",
                "刚推荐的",
            )
            raw_query_text = str(getattr(turn, "raw_query", "") or "")
            if any(pronoun in raw_query_text for pronoun in _POSITIONAL_PRONOUNS):
                persistent = state.get("persistent")
                if persistent is not None:
                    last_candidates = getattr(persistent, "last_candidates", []) or []
                    for cand in last_candidates:
                        if isinstance(cand, dict):
                            cid = cand.get("shop_id") or cand.get("id")
                            if cid is not None:
                                try:
                                    candidate_shop_ids.append(int(cid))
                                except (ValueError, TypeError):
                                    pass

        route = "clarification_node"
        if (
            need_clarify
            or answer_style == "clarification"
            or follow_up_kind == "none"
            and not any(
                (
                    single_shop_mode,
                    recommendation_mode,
                    comparison_shop_ids,
                    target_shop_id,
                    candidate_shop_ids,
                )
            )
        ):
            route = "clarification_node"
        elif (
            comparison_shop_ids
            or answer_style == "comparison"
            or follow_up_kind == "comparison_completion"
        ):
            route = "resolve_comparison_targets"
        elif (
            recommendation_mode
            or answer_style == "multi_shop_recommendation"
            or follow_up_kind in {"intent_ellipsis", "constraint_inheritance"}
        ):
            route = "prepare_recommendation_context"
        elif single_shop_mode or target_shop_id is not None or candidate_shop_ids:
            route = "resolve_target_shop"

        detail = {
            "route": route,
            "target_shop_id": target_shop_id,
            "candidate_shop_ids": candidate_shop_ids,
            "comparison_shop_ids": comparison_shop_ids,
            "single_shop_mode": single_shop_mode,
            "recommendation_mode": recommendation_mode,
            "need_clarify": need_clarify,
            "answer_style": answer_style or None,
            "follow_up_kind": follow_up_kind or None,
        }
        state = _update_turn_extra(state, target_requirement_router=detail)
        return _update_runtime_metrics(state, target_requirement_router=detail)

    def build_source_contract(self, state: GraphState) -> GraphState:
        # SourceContract 把当前店、显式店名和候选店统一成后续检索/工具调用的输入。
        turn = state["turn"]
        routing = _routing_decision(state)
        turn_extra = _turn_extra(state)
        answer_contract = getattr(turn, "answer_contract", None)
        if answer_contract is None:
            entity_join_result = _build_entity_join_result(turn)
            answer_contract = _build_answer_contract(
                turn, routing, getattr(turn, "evidence_quality", None), entity_join_result
            )
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
        state["turn"] = turn.model_copy(
            update={"source_contract": source_contract, "extra": turn_extra}
        )
        state = _update_runtime_metrics(
            state, build_source_contract=turn_extra["build_source_contract"]
        )
        return state

    def complexity_router(self, state: GraphState) -> GraphState:
        # 用 routing decision 的 execution_mode 统一复杂度分流。
        routing = _routing_decision(state)
        complexity = route_execution_mode(routing)
        return _update_turn_extra(state, complexity_router=complexity.to_dict())

    def hard_guard(self, state: GraphState) -> GraphState:
        # 最早的硬门禁，遇到高风险或违规输入时直接改写路由。
        turn = state["turn"]
        persistent = state.get("persistent")
        client_context = dict(getattr(state.get("runtime"), "client_context", {}) or {})
        result = check_hard_guard(
            str(getattr(turn, "raw_query", "") or ""), persistent, client_context
        )
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
        # 记录请求是否通过合法性检查，供后续拒答链路使用。
        routing = _routing_decision(state)
        return _update_turn_extra(
            state,
            request_legality={
                "checked": True,
                "blocked": bool(getattr(routing, "blocked", False))
                if routing is not None
                else False,
                "required_action": _routing_action(state) or None,
                "route_reason": str(getattr(routing, "route_reason", "") or "").strip()
                if routing is not None
                else None,
            },
        )

    def query_safety(self, state: GraphState) -> GraphState:
        # 对原始 query 做安全检查，避免在进入检索前就污染下游。
        routing = _routing_decision(state)
        return _update_turn_extra(
            state,
            query_safety={
                "checked": True,
                "blocked": bool(getattr(routing, "blocked", False))
                if routing is not None
                else False,
                "required_action": _routing_action(state) or None,
            },
        )

    def query_merge_for_local_life(self, state: GraphState) -> GraphState:
        # 这里把当前 query 和上一轮门店/比较对象/追问语义合并，专门服务“有券吗”“离我多远”这类本地生活追问。
        persistent = state.get("persistent")
        runtime = state.get("runtime")
        turn = state["turn"]
        session_context = (
            persistent.model_dump()
            if persistent is not None and hasattr(persistent, "model_dump")
            else dict(getattr(persistent, "__dict__", {}) or {})
        )
        recovery = recover_follow_up_context(
            str(getattr(turn, "raw_query", "") or ""),
            client_context=dict(getattr(runtime, "client_context", {}) or {}),
            session_context=session_context,
        )
        semantic_context = recovery.to_dict()
        turn_extra = _turn_extra(state)
        turn_extra["local_life_context_recovery"] = semantic_context
        turn_extra["semantic_context"] = semantic_context
        if recovery.comparison_targets:
            turn_extra["comparison_targets"] = list(
                semantic_context.get("comparison_targets") or []
            )
        if recovery.anchor_shop is not None:
            turn_extra["anchor_shop"] = (
                recovery.anchor_shop.to_dict()
                if hasattr(recovery.anchor_shop, "to_dict")
                else {
                    "name": recovery.anchor_shop.name,
                    "shop_id": recovery.anchor_shop.shop_id,
                    "source": recovery.anchor_shop.source,
                    "confidence": recovery.anchor_shop.confidence,
                }
            )
        state["turn"] = turn.model_copy(update={"extra": turn_extra})
        return _update_turn_extra(
            state,
            query_merge_for_local_life={
                "checked": True,
                "needs_merge": _requires_query_merge(state),
                "follow_up_kind": recovery.follow_up_kind,
                "promoted_intent": recovery.promoted_intent,
            },
        )

    def merged_query_safety(self, state: GraphState) -> GraphState:
        # 语义合并后再做一轮安全检查，防止追问拼接后绕过门禁。
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
                reason=str(
                    getattr(routing, "blocked_reason", "")
                    or getattr(routing, "route_reason", "")
                    or result.reason
                ),
            )
        return _update_turn_extra(
            state,
            merged_query_safety={
                "checked": True,
                "query": _turn_raw_query(state),
                "blocked": bool(result.blocked),
                "allowed": bool(result.allowed),
                "required_action": str(getattr(result, "required_action", "") or "").strip()
                or None,
                "reason": str(getattr(result, "reason", "") or "").strip() or None,
            },
        )

    def top_level_intent_router(self, state: GraphState) -> GraphState:
        # 顶层意图最终分流口：安全拒答、澄清、直答、工作流都在这里收口。
        routing = _routing_decision(state)
        route = "clarification_node"
        if routing is not None and (
            bool(getattr(routing, "blocked", False))
            or str(getattr(routing, "required_action", "") or "").strip().lower() == "reject"
        ):
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
            intent_name = (
                str(getattr(getattr(routing, "intent", None), "name", "") or "").strip().lower()
            )
            if routing_action == "direct_answer" and (
                route_candidate == "out_of_scope" or intent_name == "out_of_scope"
            ):
                payload = {
                    "route": "out_of_scope_response",
                    "query": _turn_raw_query(state),
                    "intent": "out_of_scope",
                    "confidence": float(getattr(routing, "confidence", 0.0) or 0.0),
                    "reason": str(getattr(routing, "route_reason", "") or "").strip()
                    or "top_level_out_of_scope",
                    "source": "routing_decision",
                    "matched_signals": [],
                    "requires_current_shop": False,
                    "requires_candidate_context": False,
                }
                return _update_turn_extra(state, top_level_intent_router=payload)

        turn_extra = _turn_extra(state)
        resolved_top_level_route = (
            str(turn_extra.get("resolved_top_level_route") or "").strip().lower() or None
        )
        resolved_route_candidate = (
            str(
                turn_extra.get("resolved_route_candidate")
                or turn_extra.get("route_candidate")
                or ""
            )
            .strip()
            .lower()
            or None
        )
        existing_intent_info = turn_extra.get("top_level_intent")
        if existing_intent_info and isinstance(existing_intent_info, dict):
            intent = existing_intent_info.get("intent")
            requires_current_shop = existing_intent_info.get("requires_current_shop", False)
            requires_candidate_context = existing_intent_info.get(
                "requires_candidate_context", False
            )
            source = existing_intent_info.get("source", "existing")
            confidence = existing_intent_info.get("confidence", 0.0)
            reason = existing_intent_info.get("reason", "")
            matched_signals = existing_intent_info.get("matched_signals", [])
        else:
            routing_intent_name = (
                str(getattr(getattr(routing, "intent", None), "name", "") or "").strip().lower()
                if routing is not None
                else ""
            )
            if routing_intent_name and routing_intent_name not in ("", "unknown"):
                intent = routing_intent_name
                confidence = float(getattr(routing, "confidence", 0.8) or 0.8)
                reason = (
                    str(getattr(routing, "route_reason", "") or "").strip()
                    or "from_routing_decision"
                )
                source = "routing_decision"
            else:
                intent = "local_life"
                confidence = 0.8
                reason = "default_local_life"
                source = "default"
            requires_current_shop = False
            requires_candidate_context = False
            matched_signals = []

        registry_match = resolve_top_level_route(
            intent,
            route_candidate=resolved_top_level_route or resolved_route_candidate,
            route_candidates=turn_extra.get("route_candidates"),
        )
        route = str(registry_match.get("entry_node") or "").strip() or "clarification_node"
        if (
            str(getattr(state["turn"], "decision", "") or "").strip().lower() == "direct_answer"
            and existing_intent_info is None
        ):
            route = "final_answer"
        if (
            route == "clarification_node"
            and str(getattr(state["turn"], "decision", "") or "").strip().lower() == "direct_answer"
        ):
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
            f"{reason}|registry={registry_match.get('route_id')}",
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
                "route_registry_match": registry_match,
                "resolved_route_candidate": resolved_route_candidate,
                "resolved_top_level_route": resolved_top_level_route,
            },
        )

    def identity_answer(self, state: GraphState) -> GraphState:
        # 身份类问答，直接返回系统自我介绍。
        return _preset_response(
            state,
            response_node="identity_answer",
            answer_text="我是本地生活助手，可以帮你查店铺信息、优惠券、营业状态和推荐。",
            route_candidate="profile",
            route_reason="top_level_identity",
        )

    def capability_answer(self, state: GraphState) -> GraphState:
        # 能力介绍类问答，直接说明可处理的本地生活范围。
        return _preset_response(
            state,
            response_node="capability_answer",
            answer_text="我可以帮你查店铺详情、优惠券、营业时间、距离和推荐。",
            route_candidate="low_info",
            route_reason="top_level_capability",
        )

    def direct_chat_answer(self, state: GraphState) -> GraphState:
        # 闲聊或低信息输入时的轻量直答。
        return _preset_response(
            state,
            response_node="direct_chat_answer",
            answer_text="可以，我在。你也可以继续问我本地生活相关问题。",
            route_candidate="greeting",
            route_reason="top_level_direct_chat",
        )

    def out_of_scope_response(self, state: GraphState) -> GraphState:
        # 非本地生活问题，直接提示超出范围。
        return _preset_response(
            state,
            response_node="out_of_scope_response",
            answer_text="这个问题超出了本地生活查询范围，我先帮你处理店铺相关的问题。",
            route_candidate="empty",
            route_reason="top_level_out_of_scope",
        )

    def illegal_request_response(self, state: GraphState) -> GraphState:
        # 请求信息不足时，优先引导用户补充门店或城市。
        return _preset_response(
            state,
            response_node="illegal_request_response",
            answer_text="你可以补充一点信息吗？比如店名、城市，或者你想查的内容。",
            route_candidate="low_info",
            route_reason="request_legality_failed",
        )

    def safety_reject_response(self, state: GraphState) -> GraphState:
        # 命中安全限制时的统一拒答文案。
        return _preset_response(
            state,
            response_node="safety_reject_response",
            answer_text="抱歉，这个问题涉及安全限制，我不能继续处理。",
            route_candidate="low_info",
            route_reason="query_safety_rejected",
        )

    def direct_executor(self, state: GraphState) -> GraphState:
        # 直答分支的执行节点，主要记录路由轨迹。
        return _update_turn_extra(
            state,
            direct_executor={
                "branch": _route_branch(state) or None,
                "execution_mode": _route_execution_mode(state),
            },
        )

    def workflow_executor(self, state: GraphState) -> GraphState:
        # 需要检索、工具、规划的工作流分支入口。
        return _update_turn_extra(
            state,
            workflow_executor={
                "branch": _route_branch(state) or None,
                "execution_mode": _route_execution_mode(state),
            },
        )

    def clarification_node(self, state: GraphState) -> GraphState:
        # 信息不足时先进入澄清节点，不直接硬答。
        return _update_turn_extra(
            state,
            clarification_node={
                "branch": _route_branch(state) or None,
                "execution_mode": _route_execution_mode(state),
            },
        )

    def rule_review(self, state: GraphState) -> GraphState:
        # 规则复核节点，给重试/修复链路提供上下文。
        turn_extra = _turn_extra(state)
        turn_extra["rule_review"] = {
            "reviewed": True,
            "required_action": _routing_action(state) or None,
            "route_branch": _route_branch(state) or None,
        }
        state["turn"] = state["turn"].model_copy(update={"extra": turn_extra})
        return state

    def select_required_sources(self, state: GraphState) -> GraphState:
        # 根据 contract 选择要走的证据源组合：工具或推荐。
        turn_extra = _turn_extra(state)
        routing_contract = getattr(state["turn"], "routing_contract", None)
        answer_contract = _as_mapping(
            turn_extra.get("answer_contract") or getattr(state["turn"], "answer_contract", None)
        )
        required_facets = list(answer_contract.get("required_facets") or [])
        allowed_facets = list(answer_contract.get("allowed_facets") or [])
        tool_requirements = dict(answer_contract.get("tool_requirements") or {})
        evidence_requirements = dict(answer_contract.get("evidence_requirements") or {})

        selected_sources: list[str] = []
        answer_style = str(answer_contract.get("answer_style") or "").strip().lower()
        if (
            bool(getattr(routing_contract, "recommendation_mode", False))
            or answer_style == "multi_shop_recommendation"
        ):
            selected_sources.append("recommendation")
        if bool(getattr(routing_contract, "tool_allowed", True)):
            tool_candidates = list(tool_requirements.get("tool_candidates") or [])
            dynamic_facets = list(evidence_requirements.get("dynamic_facets") or [])
            realtime_tool_facets = {
                str(facet.get("name") or "").strip()
                for facet in required_facets
                if isinstance(facet, dict) and str(facet.get("name") or "").strip()
            }
            has_realtime_tool_facet = bool(
                realtime_tool_facets.intersection({"coupon", "open_status", "distance_eta"})
            )
            if (
                tool_candidates
                or dynamic_facets
                or answer_style in {"coupon_only", "open_status_only", "distance_only"}
                or (answer_style == "facet_multi" and has_realtime_tool_facet)
            ):
                selected_sources.append("tool")
        if not selected_sources:
            if bool(getattr(routing_contract, "tool_allowed", True)):
                selected_sources.append("tool")
            else:
                selected_sources.append("recommendation")

        selected_sources = list(dict.fromkeys(selected_sources))
        turn_extra["selected_sources"] = list(selected_sources)
        turn_extra["source_dispatch"] = {
            "selected_sources": list(selected_sources),
            "remaining_sources": list(selected_sources),
            "current_source": None,
            "execution_mode": str(getattr(state["turn"], "execution_mode", "") or "")
            .strip()
            .lower()
            or None,
        }
        turn_extra["select_required_sources"] = {
            "selected_sources": list(selected_sources),
            "execution_mode": str(getattr(state["turn"], "execution_mode", "") or "")
            .strip()
            .lower()
            or None,
            "branch": _route_branch(state) or None,
        }
        state["turn"] = state["turn"].model_copy(update={"extra": turn_extra})
        return state

    def source_dispatch(self, state: GraphState) -> GraphState:
        # 按选中的源逐个分发，支持多源串行取证。
        turn = state["turn"]
        turn_extra = _turn_extra(state)
        dispatch = dict(turn_extra.get("source_dispatch") or {})
        selected_sources = list(
            dispatch.get("selected_sources") or turn_extra.get("selected_sources") or []
        )
        remaining_sources = list(dispatch.get("remaining_sources") or selected_sources)
        current_source = remaining_sources.pop(0) if remaining_sources else None
        dispatch["selected_sources"] = list(selected_sources)
        dispatch["remaining_sources"] = list(remaining_sources)
        dispatch["current_source"] = current_source
        dispatch["execution_mode"] = str(
            getattr(turn, "execution_mode", "") or ""
        ).strip().lower() or dispatch.get("execution_mode")
        turn_extra["source_dispatch"] = dispatch
        state["turn"] = turn.model_copy(update={"extra": turn_extra})
        return state

    def final_answer(self, state: GraphState) -> GraphState:
        # 如果 compose_answer 没先产出结果，这里负责兜底；plan_execute 还会把任务总结改写成最终回复。
        turn = state["turn"]
        compose_was_called = False
        if not str(getattr(turn, "final_answer", "") or "").strip():
            state = self.compose_answer(state)
            turn = state["turn"]
            compose_was_called = True
        # 兜底补写 persistent.last_candidates：即使 compose_answer 被跳过，
        # 也尽量从 turn.extra["ranked_candidates"] 里恢复上一轮可复用的候选店。
        if not compose_was_called:
            turn_extra_snapshot = dict(getattr(turn, "extra", {}) or {})
            ranked_candidates = list(turn_extra_snapshot.get("ranked_candidates") or [])
            persistent = state.get("persistent")
            _LOGGER.warning(
                "DEBUG final_answer fallback: compose_skipped=%s ranked_candidates_count=%d persistent_last_cands=%s",
                not compose_was_called,
                len(ranked_candidates),
                list(getattr(persistent, "last_candidates", None) or [])
                if persistent is not None
                else "no_persistent",
            )
            if ranked_candidates:
                if persistent is not None and not getattr(persistent, "last_candidates", None):
                    state["persistent"] = persistent.model_copy(
                        update={
                            "last_candidates": [
                                {
                                    "shop_id": c.get("shop_id"),
                                    "name": c.get("name"),
                                    "shop_name": c.get("shop_name"),
                                }
                                for c in ranked_candidates
                                if c.get("shop_id") is not None
                            ]
                        }
                    )
                    _LOGGER.warning(
                        "DEBUG final_answer: WROTE persistent.last_candidates count=%d",
                        len(state["persistent"].last_candidates),
                    )
                elif persistent is not None:
                    _LOGGER.warning(
                        "DEBUG final_answer: SKIPPED write, persistent.last_candidates already has %d items",
                        len(list(getattr(persistent, "last_candidates", None) or [])),
                    )
        if str(getattr(turn, "execution_mode", "") or "").strip().lower() == "plan_execute":
            summary = getattr(turn, "final_task_summary", None)
            if summary is not None:
                summary_text = str(getattr(summary, "final_decision", "") or "").strip()
                summary_status = str(getattr(summary, "status", "") or "").strip()
                planned_answer = f"Plan execution {summary_status}: {summary_text}".strip()
                if summary_text:
                    turn_extra = _turn_extra(state)
                    turn_extra["plan_execution_answer"] = planned_answer
                    turn = turn.model_copy(
                        update={"final_answer": planned_answer, "extra": turn_extra}
                    )
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
        # 合并多源证据并完成候选排序。
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
        # 回答前再审一遍 contract，决定是否需要重试或修复。
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
        # 把审查结果转成重试语义，驱动后续修复或重跑。
        turn = state["turn"]
        turn_extra = _turn_extra(state)
        review_report = turn_extra.get("review_report")
        if review_report:
            from learning_agent_service.domain.contracts import RewriteDecision

            retry_count = int(getattr(review_report, "retry_count", 0)) + 1
            setattr(review_report, "retry_count", retry_count)
            decision = str(getattr(review_report, "decision", "") or "").strip()
            failure_category = str(
                getattr(review_report, "extra", {}).get("failure_category") or ""
            ).strip()
            retry_reason = (
                str(getattr(review_report, "reason", "") or "").strip()
                or failure_category
                or "retry_requested"
            )
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
                    preserved_constraints=[
                        str(item)
                        for item in [
                            tool_name,
                            failure_category,
                            getattr(review_report, "retry_target", ""),
                        ]
                        if str(item).strip()
                    ],
                    confidence=0.55,
                    should_retrieve=True,
                    reason="retry_tool_failure",
                )
            else:
                repair_hint = getattr(review_report, "repair_hint", "")
                rewrite = RewriteDecision(
                    original_query=str(getattr(turn, "raw_query", "")),
                    rewritten_query=str(getattr(turn, "raw_query", "")) + f" {repair_hint}",
                    preserved_constraints=[
                        str(item)
                        for item in getattr(review_report, "failed_facets", [])
                        if str(item).strip()
                    ],
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
                turn = turn.model_copy(
                    update={
                        "routing_decision": routing.model_copy(update={"rewrite_decision": rewrite})
                    }
                )
            if "rag_result" in turn_extra:
                del turn_extra["rag_result"]
            turn_extra["review_report"] = review_report
        state["turn"] = turn.model_copy(update={"extra": turn_extra})
        return state

    def final_answer_safety(self, state: GraphState) -> GraphState:
        # 最终回答输出前的最后一道安全校验。
        turn = state["turn"]
        turn_extra = _turn_extra(state)
        plan_execution_answer = str(turn_extra.get("plan_execution_answer") or "").strip()
        raw_answer = str(
            plan_execution_answer
            or getattr(turn, "final_answer", "")
            or turn_extra.get("preset_response_text")
            or ""
        ).strip()
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
            answer_contract=turn_extra.get("answer_contract")
            or getattr(turn, "answer_contract", None),
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
        turn_extra["final_answer_safety"] = (
            safety_result.to_dict() if hasattr(safety_result, "to_dict") else asdict(safety_result)
        )
        state["turn"] = turn.model_copy(update={"extra": turn_extra})
        runtime = state["runtime"]
        runtime_metrics = dict(getattr(runtime, "metrics", {}) or {})
        runtime_metrics["final_answer_safety"] = turn_extra["final_answer_safety"]
        state["runtime"] = runtime.model_copy(update={"metrics": runtime_metrics})
        return state

    def final_safety_fallback(self, state: GraphState) -> GraphState:
        # 安全校验拦截后，保留一个可控的兜底输出。
        turn = state["turn"]
        turn_extra = _turn_extra(state)
        safety_result = dict(turn_extra.get("final_answer_safety") or {})
        plan_execution_answer = str(turn_extra.get("plan_execution_answer") or "").strip()
        if (
            safety_result.get("blocked")
            and not str(getattr(turn, "final_answer", "") or "").strip()
        ):
            fallback_text = str(
                safety_result.get("answer_text") or "抱歉，这条回复暂时无法安全输出。"
            ).strip()
            turn = turn.model_copy(update={"final_answer": plan_execution_answer or fallback_text})
        turn_extra["final_safety_fallback"] = {
            "applied": bool(safety_result.get("blocked")),
            "blocked": bool(safety_result.get("blocked")),
        }
        state["turn"] = turn.model_copy(update={"extra": turn_extra})
        return state

    def repair_answer(self, state: GraphState) -> GraphState:
        # 根据安全/审查结果修补最终回答文本。
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
        # 对仍然不完整的结果追加限制说明，避免过度承诺。
        turn = state["turn"]
        turn_extra = _turn_extra(state)
        safety_result = dict(turn_extra.get("final_answer_safety") or {})
        plan_execution_answer = str(turn_extra.get("plan_execution_answer") or "").strip()
        issues = list(safety_result.get("issues") or [])
        current_answer = str(
            plan_execution_answer or getattr(turn, "final_answer", "") or ""
        ).strip()
        if issues and current_answer and not current_answer.endswith("。"):
            turn = turn.model_copy(
                update={"final_answer": f"{current_answer}（以上为当前可确认信息）"}
            )
        turn_extra["final_with_limitations"] = {
            "issues": issues,
            "issue_count": len(issues),
        }
        state["turn"] = turn.model_copy(update={"extra": turn_extra})
        return state

    def response_builder(self, state: GraphState) -> GraphState:
        # 把最终答案和会话状态写回响应结构。
        turn = state["turn"]
        turn_extra = _turn_extra(state)
        from learning_agent_service.local_life.dialog_state_machine import (
            DialogContext,
            DialogState,
            dialog_state_machine,
        )

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
                        str(
                            item.get("name") or item.get("shop_name") or item.get("target") or ""
                        ).strip()
                        for item in comparison_targets
                        if isinstance(item, Mapping)
                    ]
                    target_names = [name for name in target_names if name]
                    if target_names and not getattr(persistent, "dialog_comparison_targets", None):
                        persistent.dialog_comparison_targets = list(dict.fromkeys(target_names))
            dialog_ctx = DialogContext(
                current_state=DialogState(
                    str(getattr(persistent, "dialog_state", "") or DialogState.IDLE.value)
                ),
                transition_count=int(getattr(persistent, "dialog_transition_count", 0) or 0),
                current_task=getattr(persistent, "dialog_task", None),
                active_intent=getattr(persistent, "dialog_intent", None),
                comparison_targets=list(getattr(persistent, "dialog_comparison_targets", []) or []),
                pending_slots=list(getattr(persistent, "dialog_pending_slots", []) or []),
            )
            has_clarification = bool(turn_extra.get("clarification_needed"))
            has_results = bool(turn_extra.get("evidence_claims"))
            answer_contract = turn_extra.get("answer_contract") or getattr(
                turn, "answer_contract", None
            )
            is_comparison = str(getattr(answer_contract, "answer_style", "") or "") == "comparison"
            has_error = bool(
                turn_extra.get("error") or getattr(state.get("runtime"), "error", None)
            )
            is_degraded = bool(
                turn_extra.get("degraded") or getattr(state.get("runtime"), "degrade_to", None)
            )
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

            turn_extra["answer_text"] = str(
                getattr(turn, "final_answer", "") or turn_extra.get("answer_text") or ""
            ).strip()

            # 先把 ranked_candidates 写进 bundle，后续响应组装和 Bug1 修复逻辑都要用到。
            # 这一步必须放在 build_response_bundle 之前。
            if turn_extra.get("ranked_candidates"):
                from learning_agent_service.local_life.schemas import RankedCandidate

                ranked_candidates = [
                    RankedCandidate(
                        shop_id=c.get("shop_id"),
                        name=c.get("name"),
                        matched_requirements=[],
                        structured_features={},
                        evidence_features={},
                        risk_flags=[],
                        explainable_reasons=[],
                        vouchers=c.get("vouchers", []),
                        blog_snippets=[],
                        score_breakdown={},
                        rank_score=0.0,
                    )
                    for c in turn_extra["ranked_candidates"]
                ]
            else:
                ranked_candidates = []

            bundle = build_response_bundle(
                raw_query=str(getattr(turn, "raw_query", "") or ""),
                slots=LocalLifeSlots(**(getattr(turn, "slots", None) or {})),
                answer_contract=turn_extra.get("answer_contract")
                or getattr(turn, "answer_contract", None),
                ranked_candidates=ranked_candidates,
                evidence_claims=list(turn_extra.get("evidence_claims") or []),
                answer_plan=turn_extra.get("task_plan") or getattr(turn, "task_plan", None),
                verification_result=turn_extra.get("answer_verifier_result"),
                evidence_pack=getattr(turn, "evidence_pack", None),
                page=str(
                    (state.get("runtime_context", {}) or {}).get("page")
                    or (state["runtime"].client_context or {}).get("page")
                    or ""
                ),
                current_topic=str(getattr(state["persistent"], "current_topic", "") or ""),
                selected_shop_id=turn_extra.get("selected_shop_id"),
                current_shop=str(
                    turn_extra.get("current_shop")
                    or getattr(state["persistent"], "current_shop", "")
                    or ""
                ),
                client_context=dict(getattr(state["runtime"], "client_context", {}) or {}),
                approval_required=bool(getattr(turn, "need_human_approval", False)),
                approval_request=turn_extra.get("approval_request"),
                transaction_draft=turn_extra.get("transaction_draft"),
                safety_result=turn_extra.get("final_answer_safety"),
                route_decision=_routing_action(state) or None,
                route_reason=str(getattr(_routing_decision(state), "route_reason", "") or ""),
                current_stage=getattr(turn, "current_stage", None),
                stage_status=getattr(turn, "stage_status", None),
                stage_timeline=list(
                    (state["runtime"].metrics or {}).get("stage_timeline", []) or []
                ),
                model_hint=turn_extra,
                source_mode=str(turn_extra.get("source_mode") or ""),
                degraded_reason=str(getattr(state["runtime"], "degrade_to", "") or ""),
                knowledge_freshness=turn_extra.get("knowledge_freshness"),
                user_need=turn_extra.get("user_need"),
                facet_result_bundle=turn_extra.get("facet_result_bundle"),
                graph_trace=turn_extra.get("phase5_trace") or turn_extra.get("phase4_trace"),
            )

            turn_extra["response_bundle"] = (
                bundle.model_dump(mode="json") if hasattr(bundle, "model_dump") else dict(bundle)
            )
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
