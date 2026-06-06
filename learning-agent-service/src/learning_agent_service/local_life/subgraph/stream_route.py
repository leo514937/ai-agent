from typing import Any, Iterable

from .helpers import *  # noqa: F403
from ..entity_resolver import EntityResolver
from ..route_review import RouteReview
from .stream_context import StreamRunContext


class LocalLifeStreamRouteMixin:
    def _stage_route_and_clarify(self, ctx: StreamRunContext) -> Iterable[SseEnvelope]:
        command = ctx.command
        persistent = ctx.persistent
        client_context = ctx.client_context
        session_context = ctx.session_context
        clean_session_context = ctx.clean_session_context
        session_current_shop_before = ctx.session_current_shop_before
        session_current_shop_id_before = ctx.session_current_shop_id_before
        last_candidates_before = ctx.last_candidates_before
        low_information_input = ctx.low_information_input
        understanding = ctx.understanding
        slots = ctx.slots
        clarification = ctx.clarification
        intent = ctx.intent
        user_need = ctx.user_need
        arbitration_result = ctx.arbitration_result
        state = ctx.state
        query_route = None
        review_result = None
        execution_requirements = None
        execution_contract = None
        target_shop = None
        answer_contract = None
        resolved_shop_ids: list[int] = []
        selected_shop: Any | None = None
        structured_candidates: list[Any] = []
        ranked_candidates: list[Any] = []
        evidence_claims: list[Any] = []
        source_summary: dict[str, Any] = {}
        qdrant_pack = None
        facet_bundle = FacetResultBundle()
        coupon_result_obj = None
        tool_plan = None
        tool_name = None
        tool_output = {}
        extra_tool_outputs = []
        first_shop_name = None
        tool_input_summary = {}
        top_shop = None
        response_hint = None
        verification_result = None
        selected_shop: Any | None = None
        query_route = self.local_life_query_router.route(
            command.message,
            slots=slots,
            intent=intent,
            client_context=client_context,
            session_context=session_context,
        )
        review_result = RouteReview.review(
            user_need=user_need,
            initial_route=query_route,
            clarification=clarification,
            client_context=client_context,
            session_context=clean_session_context,
        )
        state.route_review = review_result
        print(f"[DEBUG Subgraph Review Result] review_result={review_result.model_dump(mode='json')}")
        query_route = review_result.reviewed_route
        execution_requirements = review_result.execution_requirements
        clarification = review_result.reviewed_clarification or review_result.clarification or clarification
        state.clarification = clarification
        print(f"[DEBUG Subgraph Clarification] clarification={clarification}, need_clarification={getattr(clarification, 'need_clarification', None)}")
        execution_contract = EntityResolver().resolve(
            raw_query=command.message,
            slots=slots,
            user_need=user_need,
            session_context=clean_session_context,
            query_route=query_route,
            client_context=client_context,
        )

        target_shop = getattr(execution_contract, "target_shop", None)
        is_recommendation = user_need.intent in ("local_life_recommend", "restaurant_recommendation")
        if is_recommendation:
            from ..target_shop_policy import TargetShop

            target_shop = TargetShop(
                shop_id=None,
                shop_name=None,
                raw_mention=None,
                source="rag_fallback",
                resolution_source="rag_fallback",
                confidence=0.0,
                is_explicit_in_current_turn=False,
                reason="recommendation_mode_weak_anchor",
                candidate_shop_ids=[],
            )

        single_shop_mode = False
        if target_shop and (target_shop.shop_id is not None or target_shop.shop_name is not None):
            single_shop_mode = True

        from ..answer_contract import AnswerContract
        answer_contract = AnswerContract.build_contract(user_need, target_shop)

        resolved_shop_ids = list(execution_contract.candidate_shop_ids)
        if not resolved_shop_ids and not execution_contract.forbid_global_fallback:
            resolved_shop_ids = _resolve_review_shop_ids(
                user_need=user_need,
                slots=slots,
                session_context=session_context,
                query_route=query_route,
            )

        # JSON logs required by P0 regression
        import json
        import logging
        _LOGGER_JSON = logging.getLogger("learning_agent_service.local_life.json_log")

        # 1. Pronoun/Context binding log
        if any(p in command.message for p in ("这家", "它", "这店", "刚才那家")) or len(user_need.context_refs) > 0:
            log_data_pronoun = {
                "raw_query": command.message,
                "context_refs": [ref.model_dump() for ref in user_need.context_refs],
                "candidate_shop_ids": resolved_shop_ids
            }
            log_str = json.dumps(log_data_pronoun, ensure_ascii=False)
            print(log_str)
            _LOGGER_JSON.info(log_str)

        # 2. Multi-facet query log
        if any(k in command.message for k in ("适合约会", "营业", "火锅", "有券", "带娃", "餐厅")):
            log_data_facets = {
                "raw_query": command.message,
                "required_facets": [facet.model_dump() for facet in user_need.required_facets],
                "execution_requirements": {
                    "execute_rag": execution_requirements.execute_rag,
                    "execute_tools": execution_requirements.execute_tools
                }
            }
            log_str = json.dumps(log_data_facets, ensure_ascii=False)
            print(log_str)
            _LOGGER_JSON.info(log_str)

        state.metrics.update(
            {
                "trace_id": command.trace_id,
                "latest_turn_message": command.message,
                "raw_query": command.message,
                "normalized_query": getattr(understanding, "normalized_query", command.message),
                "current_intent": str(getattr(intent, "value", intent)),
                "should_clarify": bool(clarification.need_clarification),
                "low_information_input": low_information_input,
                "latest_message_priority": (
                    "low_information_gate"
                    if low_information_input
                    else (target_shop.resolution_source if target_shop and getattr(target_shop, "resolution_source", None) else getattr(target_shop, "source", None))
                ),
                "session_current_shop_before": session_current_shop_before,
                "session_current_shop_id_before": session_current_shop_id_before,
                "last_candidates_before": last_candidates_before,
                "local_life_route": query_route.route,
                "local_life_route_reason": query_route.route_reason,
                "local_life_retrieval_strategy": query_route.retrieval_strategy,
                "route_review_intercepted": review_result.intercepted,
                "route_review_reason": review_result.review_reason,
                "local_life_user_need": user_need.model_dump(mode="json"),
                "local_life_context_arbitration": arbitration_result,
                "local_life_route_review": review_result.model_dump(mode="json"),
                "local_life_execution_requirements": execution_requirements.model_dump(mode="json"),
                "local_life_execution_contract": execution_contract.model_dump(mode="json"),
                "target_shop": target_shop.model_dump(mode="json") if target_shop else None,
                "target_shop.source": target_shop.source if target_shop else None,
                "target_shop.shop_id": target_shop.shop_id if target_shop else None,
                "target_shop.shop_name": target_shop.shop_name if target_shop else None,
                "target_shop.resolution_source": target_shop.resolution_source if target_shop else None,
                "target_shop.confidence": target_shop.confidence if target_shop else None,
                "target_shop.should_clarify": target_shop.should_clarify if target_shop else None,
                "target_shop.reason": target_shop.reason if target_shop else None,
                "target_shop_resolution": target_shop.model_dump(mode="json") if target_shop else {
                    "source": "session",
                    "resolution_source": "missing" if low_information_input else "ambiguous",
                    "shop_id": None,
                    "shop_name": None,
                    "confidence": 0.0,
                    "is_explicit_in_current_turn": False,
                    "is_pronoun_inherited": False,
                    "is_candidate_reference": False,
                    "should_clarify": bool(clarification.need_clarification),
                    "reason": "low_information_query" if low_information_input else None,
                    "candidate_shop_ids": [],
                },
                "single_shop_mode": single_shop_mode,
                "answer_contract": answer_contract.model_dump(mode="json"),
            }
        )
        _mark_stage(
            state,
            "understand",
            "completed",
            route_decision=_route_decision_from_intent(intent),
            route_reason=f"intent:{intent.value}",
            detail={
                "normalized_query": understanding.normalized_query,
                "semantic_query": understanding.semantic_query,
                "keyword_query": understanding.keyword_query,
                "confidence": understanding.confidence,
                "local_life_route": query_route.route,
                "local_life_retrieval_strategy": query_route.retrieval_strategy,
            },
        )

        if clarification.need_clarification:
            state.route_decision = "clarify"
            state.route_reason = clarification.question or "need_clarification"
            _mark_stage(
                state,
                "clarify",
                "completed",
                route_decision=state.route_decision,
                route_reason=state.route_reason,
                detail={
                    "ambiguity_type": clarification.ambiguity_type,
                    "mode": "clarification_card",
                },
            )

            clarification_event = _event(
                EventType.CLARIFICATION_CARD,
                trace_id=command.trace_id,
                session_id=command.session_id,
                turn_id=command.turn_id,
                workflow_version=self.settings.workflow_version,
                payload=_clarification_payload(clarification),
            )

            yield clarification_event

            clarification_hint = {
                "answer_text": clarification.question or "你能再补充一点信息吗？",
                "suggested_replies": [
                    {
                        "label": option.label,
                        "prompt": option.prompt,
                    }
                    for option in clarification.options
                ],
            }
            pending_user_need = user_need.model_dump(mode="json")
            state.current_stage = "final"
            state.stage_status = "completed"
            bundle = build_response_bundle(
                raw_query=command.message,
                slots=slots,
                answer_contract=answer_contract,
                ranked_candidates=[],
                evidence_claims=[],
                page=command.page,
                current_topic=slots.category or slots.scene or "本地生活推荐",
                current_shop=persistent.current_shop or persistent.selected_shop_name,
                selected_shop_id=persistent.selected_shop_id,
                source="local-life-agent",
                fallback=True,
                mode="clarify",
                client_context=client_context,
                approval_required=False,
                approval_request={},
                transaction_draft={},
                safety_result={},
                route_decision=state.route_decision,
                route_reason=state.route_reason,
                current_stage=state.current_stage,
                stage_status=state.stage_status,
                stage_timeline=list(state.stage_timeline),
                model_hint=clarification_hint,
                source_mode="clarification_only",
                degraded_reason=None,
                knowledge_freshness={},
                graph_trace=state.metrics,
            )
            bundle = sanitize_local_life_output(
                bundle,
                shop_lookup={},
            )
            bundle = bundle.model_copy(
                update={
                    "context": {
                        **dict(bundle.context),
                        "pending_user_need": pending_user_need,
                    }
                }
            )
            state.answer_text = bundle.answer_text
            state.stage_timeline = list(bundle.stage_timeline or state.stage_timeline)
            _mark_stage(
                state,
                "final",
                "completed",
                route_decision=state.route_decision,
                route_reason=state.route_reason,
                detail={"selected_shop_id": None, "approval_required": False},
            )
            bundle = bundle.model_copy(
                update={
                    "route_decision": state.route_decision,
                    "route_reason": state.route_reason,
                    "current_stage": state.current_stage,
                    "stage_status": state.stage_status,
                    "stage_timeline": list(state.stage_timeline),
                    "metrics": {
                        **dict(bundle.metrics),
                        "user_need": user_need.model_dump(mode="json"),
                        "route_review": review_result.model_dump(mode="json"),
                        "execution_requirements": execution_requirements.model_dump(mode="json"),
                    },
                    "context": {
                        **dict(bundle.context),
                        "metrics": {
                            **dict(bundle.metrics),
                            "user_need": user_need.model_dump(mode="json"),
                            "route_review": review_result.model_dump(mode="json"),
                            "execution_requirements": execution_requirements.model_dump(mode="json"),
                        },
                        "user_need": user_need.model_dump(mode="json"),
                        "route_review": review_result.model_dump(mode="json"),
                        "execution_requirements": execution_requirements.model_dump(mode="json"),
                        "reviewed_route": query_route.as_dict(),
                        "clarification": clarification.model_dump(mode="json"),
                        "tool_results": list(state.tool_results),
                        "route_decision": state.route_decision,
                        "route_reason": state.route_reason,
                        "current_stage": state.current_stage,
                        "stage_status": state.stage_status,
                        "stage_timeline": list(state.stage_timeline),
                    },
                }
            )
            self._persist_context(
                persistent,
                state,
                command,
                slots=slots,
                ranked_candidates=[],
                bundle=bundle,
            )
            yield _event(
                EventType.FINAL,
                trace_id=command.trace_id,
                session_id=command.session_id,
                turn_id=command.turn_id,
                workflow_version=self.settings.workflow_version,
                payload=bundle.model_dump(mode="json"),
            )
            return
        ctx.query_route = query_route
        ctx.review_result = review_result
        ctx.execution_requirements = execution_requirements
        ctx.execution_contract = execution_contract
        ctx.target_shop = target_shop
        ctx.answer_contract = answer_contract
        ctx.resolved_shop_ids = list(resolved_shop_ids)
        ctx.selected_shop = selected_shop
        ctx.structured_candidates = list(structured_candidates)
        ctx.ranked_candidates = list(ranked_candidates)
        ctx.evidence_claims = list(evidence_claims)
        ctx.source_summary = dict(source_summary)
        ctx.qdrant_pack = qdrant_pack
        ctx.facet_bundle = facet_bundle
        ctx.coupon_result_obj = coupon_result_obj
        ctx.tool_plan = tool_plan
        ctx.tool_name = tool_name
        ctx.tool_output = dict(tool_output)
        ctx.extra_tool_outputs = list(extra_tool_outputs)
        ctx.first_shop_name = first_shop_name
        ctx.tool_input_summary = dict(tool_input_summary)
        ctx.top_shop = top_shop
        ctx.response_hint = response_hint
        ctx.verification_result = verification_result
        return None

