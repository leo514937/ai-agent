from typing import Iterable

from learning_agent_service.domain.utils import as_mapping as _as_mapping

from .helpers import *  # noqa: F403
from .helpers import _mark_stage
from .stream_context import StreamRunContext


class LocalLifeStreamLoadMixin:
    def _build_stream_run_context(
        self,
        *,
        command: ChatTurnCommand,
        persistent_context: PersistentSessionContext | None = None,
    ) -> StreamRunContext:
        persistent = persistent_context or PersistentSessionContext()
        client_context = _as_mapping(command.client_context)
        session_context = persistent.model_dump(mode="json")
        session_current_shop_before = persistent.current_shop
        session_current_shop_id_before = persistent.selected_shop_id
        last_candidates_before = list(persistent.last_candidates or [])
        low_information_input = is_low_information_query(command.message)
        clean_session_context = dict(session_context)
        for key in ("current_scene", "scene", "local_life_preferences", "local_life_avoid", "current_constraints"):
            if key in clean_session_context:
                del clean_session_context[key]
        nearby_recommendation_like = any(
            token in command.message
            for token in ("??", "??", "??", "??", "???", "????", "????", "??", "??")
        )
        has_pronoun = any(p in command.message for p in ("??", "??", "??", "?", "?", "?", "????", "????", "???", "????", "???"))
        if nearby_recommendation_like and not has_pronoun:
            for key in ("current_shop", "selected_shop_name", "selected_shop_id", "current_shop_id", "current_topic", "last_candidates"):
                clean_session_context.pop(key, None)
        understanding_hint = self._build_understanding_hint(
            raw_query=command.message,
            client_context=client_context,
            session_context=clean_session_context,
        )
        understanding = normalize_query(
            command.message,
            client_context=client_context,
            session_context=clean_session_context,
            model_hint=understanding_hint,
        )
        slots, clarification, intent = extract_slots(
            understanding,
            command.message,
            client_context=client_context,
            session_context=clean_session_context,
            model_hint=understanding_hint,
        )
        user_need = UserNeedParser.parse(
            command.message,
            slots=slots,
            intent=intent,
            client_context=client_context,
            session_context=clean_session_context,
        )
        arbitration_result = ContextArbitration().arbitrate(
            raw_query=command.message,
            slots=slots,
            user_need=user_need,
            session_context=clean_session_context,
            client_context=client_context,
        )
        user_need = arbitration_result["user_need"]
        try:
            intent = LocalLifeIntentType(str(getattr(user_need, "intent", intent)))
        except Exception:
            pass
        input_context = build_input_context(
            raw_query=command.message,
            latest_turn_message=command.message,
            session_id=command.session_id,
            user_id=command.user_id,
            client_context=client_context,
            request_ts=datetime.now(UTC),
        )
        perception_context = build_perception_context(
            raw_query=command.message,
            normalized_query=getattr(understanding, "normalized_query", command.message),
            slots=slots,
            client_context=client_context,
            session_context=clean_session_context,
            confidence=getattr(understanding, "confidence", 0.5) or 0.5,
        )
        memory_arbitration = build_memory_arbitration_result(
            merged_context={
                "user_need": user_need.model_dump(mode="json"),
                "pending_user_need": arbitration_result.get("pending_user_need") or {},
                "source": arbitration_result.get("source"),
                "reason": arbitration_result.get("reason"),
                "clarification_action": arbitration_result.get("clarification_action"),
                "restored_pending_need": arbitration_result.get("restored_pending_need"),
                "latest_turn_message": command.message,
                "priority_source": "latest_turn_message",
            },
            winning_sources={
                "priority_source": "latest_turn_message",
                "temporal_scope": perception_context.temporal_scope,
                "source": arbitration_result.get("source"),
            },
            suppressed_memories=[],
            promotion_candidates=(
                [{"raw_query": command.message, "temporal_scope": perception_context.temporal_scope}]
                if perception_context.temporal_scope == "long_term"
                else []
            ),
            conflict_reason=arbitration_result.get("reason"),
        )
        if arbitration_result.get("restored_pending_need"):
            yield _event(
                EventType.HEARTBEAT,
                trace_id=command.trace_id,
                session_id=command.session_id,
                turn_id=command.turn_id,
                workflow_version=self.settings.workflow_version,
                payload={
                    "stage": "consume_pending_clarification",
                    "status": "done",
                    "elapsed_ms": 1.0,
                    "current_stage": "consume_pending_clarification",
                    "stage_status": "done",
                    "details": {},
                },
            )
        state = LocalLifeTurnState(
            trace_id=command.trace_id,
            session_id=command.session_id,
            turn_id=command.turn_id,
            user_id=command.user_id,
            page=command.page,
            raw_query=command.message,
            input_context=input_context.to_dict(),
            client_context=client_context,
            persistent_context=session_context,
            perception_context=perception_context.to_dict(),
            memory_arbitration=memory_arbitration.to_dict(),
            understanding=understanding,
            slots=slots,
            clarification=clarification,
            intent=intent,
            user_need=user_need,
        )
        state.node_writes.append(
            {
                "node": "load_context",
                "writes": [
                    "input_context",
                    "perception_context",
                    "memory_arbitration",
                    "user_need",
                    "slots",
                    "clarification",
                    "intent",
                ],
            }
        )
        state.metrics.update(
            {
                "input_context": input_context.to_dict(),
                "perception_context": perception_context.to_dict(),
                "memory_arbitration": memory_arbitration.to_dict(),
                "priority_source": "latest_turn_message",
                "latest_turn_message": command.message,
            }
        )
        _mark_stage(
            state,
            "load_context",
            "completed",
            detail={},
        )
        ctx = StreamRunContext(
            command=command,
            persistent=persistent,
            client_context=client_context,
            session_context=session_context,
            clean_session_context=clean_session_context,
            session_current_shop_before=session_current_shop_before,
            session_current_shop_id_before=session_current_shop_id_before,
            last_candidates_before=last_candidates_before,
            low_information_input=low_information_input,
            understanding_hint=understanding_hint,
            understanding=understanding,
            slots=slots,
            clarification=clarification,
            intent=intent,
            user_need=user_need,
            arbitration_result=arbitration_result,
            input_context=input_context,
            perception_context=perception_context,
            memory_arbitration=memory_arbitration,
            state=state,
        )
        return ctx
    def _stage_load_and_understand(self, ctx: StreamRunContext) -> Iterable[SseEnvelope]:
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
        input_context = ctx.input_context
        perception_context = ctx.perception_context
        memory_arbitration = ctx.memory_arbitration
        state = ctx.state
        # Emit load_context events for timeline compatibility (E2E regression compatibility)
        yield _event(
            EventType.LOAD_CONTEXT_STARTED,
            trace_id=command.trace_id,
            session_id=command.session_id,
            turn_id=command.turn_id,
            workflow_version=self.settings.workflow_version,
            payload={
                "stage": "load_context",
                "status": "started",
                "elapsed_ms": 0.0,
                "current_stage": "load_context",
                "stage_status": "started",
                "details": {},
            },
        )
        yield _event(
            EventType.LOAD_CONTEXT_DONE,
            trace_id=command.trace_id,
            session_id=command.session_id,
            turn_id=command.turn_id,
            workflow_version=self.settings.workflow_version,
            payload={
                "stage": "load_context",
                "status": "done",
                "elapsed_ms": 1.0,
                "current_stage": "load_context",
                "stage_status": "done",
                "details": {},
            },
        )

        persistent = ctx.persistent
        client_context = _as_mapping(command.client_context)
        session_context = persistent.model_dump(mode="json")
        session_current_shop_before = persistent.current_shop
        session_current_shop_id_before = persistent.selected_shop_id
        last_candidates_before = list(persistent.last_candidates or [])
        low_information_input = is_low_information_query(command.message)
        # Day2 P1: Multi-turn only inherits entity, not facets/constraints
        # We strip out facet-related session context to prevent inheritance pollution
        clean_session_context = dict(session_context)
        for key in ("current_scene", "scene", "local_life_preferences", "local_life_avoid", "current_constraints"):
            if key in clean_session_context:
                del clean_session_context[key]
        nearby_recommendation_like = any(
            token in command.message
            for token in ("附近", "周边", "推荐", "几家", "多推荐", "适合约会", "家庭聚餐", "安静", "不吵")
        )
        has_pronoun = any(p in command.message for p in ("这家", "这店", "这间", "它", "他", "她", "刚才那家", "刚才那个", "这商家", "这个商家", "这几家"))
        if nearby_recommendation_like and not has_pronoun:
            for key in ("current_shop", "selected_shop_name", "selected_shop_id", "current_shop_id", "current_topic", "last_candidates"):
                clean_session_context.pop(key, None)

        understanding_hint = self._build_understanding_hint(
            raw_query=command.message,
            client_context=client_context,
            session_context=clean_session_context,
        )

        understanding = normalize_query(
            command.message,
            client_context=client_context,
            session_context=clean_session_context,
            model_hint=understanding_hint,
        )
        slots, clarification, intent = extract_slots(
            understanding,
            command.message,
            client_context=client_context,
            session_context=clean_session_context,
            model_hint=understanding_hint,
        )
        user_need = UserNeedParser.parse(
            command.message,
            slots=slots,
            intent=intent,
            client_context=client_context,
            session_context=clean_session_context,
        )
        arbitration_result = ContextArbitration().arbitrate(
            raw_query=command.message,
            slots=slots,
            user_need=user_need,
            session_context=clean_session_context,
            client_context=client_context,
        )
        user_need = arbitration_result["user_need"]
        try:
            intent = LocalLifeIntentType(str(getattr(user_need, "intent", intent)))
        except Exception:
            pass
        input_context = build_input_context(
            raw_query=command.message,
            latest_turn_message=command.message,
            session_id=command.session_id,
            user_id=command.user_id,
            client_context=client_context,
            request_ts=datetime.now(UTC),
        )
        perception_context = build_perception_context(
            raw_query=command.message,
            normalized_query=getattr(understanding, "normalized_query", command.message),
            slots=slots,
            client_context=client_context,
            session_context=clean_session_context,
            confidence=getattr(understanding, "confidence", 0.5) or 0.5,
        )
        memory_arbitration = build_memory_arbitration_result(
            merged_context={
                "user_need": user_need.model_dump(mode="json"),
                "pending_user_need": arbitration_result.get("pending_user_need") or {},
                "source": arbitration_result.get("source"),
                "reason": arbitration_result.get("reason"),
                "clarification_action": arbitration_result.get("clarification_action"),
                "restored_pending_need": arbitration_result.get("restored_pending_need"),
                "latest_turn_message": command.message,
                "priority_source": "latest_turn_message",
            },
            winning_sources={
                "priority_source": "latest_turn_message",
                "temporal_scope": perception_context.temporal_scope,
                "source": arbitration_result.get("source"),
            },
            suppressed_memories=[],
            promotion_candidates=(
                [{"raw_query": command.message, "temporal_scope": perception_context.temporal_scope}]
                if perception_context.temporal_scope == "long_term"
                else []
            ),
            conflict_reason=arbitration_result.get("reason"),
        )
        if arbitration_result.get("restored_pending_need"):
            yield _event(
                EventType.HEARTBEAT,
                trace_id=command.trace_id,
                session_id=command.session_id,
                turn_id=command.turn_id,
                workflow_version=self.settings.workflow_version,
                payload={
                    "stage": "consume_pending_clarification",
                    "status": "done",
                    "elapsed_ms": 1.0,
                    "current_stage": "consume_pending_clarification",
                    "stage_status": "done",
                    "details": {},
                },
            )
        state = LocalLifeTurnState(
            trace_id=command.trace_id,
            session_id=command.session_id,
            turn_id=command.turn_id,
            user_id=command.user_id,
            page=command.page,
            raw_query=command.message,
            input_context=input_context.to_dict(),
            client_context=client_context,
            persistent_context=session_context,
            perception_context=perception_context.to_dict(),
            memory_arbitration=memory_arbitration.to_dict(),
            understanding=understanding,
            slots=slots,
            clarification=clarification,
            intent=intent,
            user_need=user_need,
        )
        state.node_writes.append(
            {
                "node": "load_context",
                "writes": [
                    "input_context",
                    "perception_context",
                    "memory_arbitration",
                    "user_need",
                    "slots",
                    "clarification",
                    "intent",
                ],
            }
        )
        state.metrics.update(
            {
                "input_context": input_context.to_dict(),
                "perception_context": perception_context.to_dict(),
                "memory_arbitration": memory_arbitration.to_dict(),
                "priority_source": "latest_turn_message",
                "latest_turn_message": command.message,
            }
        )
        _mark_stage(
            state,
            "load_context",
            "completed",
            detail={},
        )

        if low_information_input:
            from ..answer_contract import AnswerContract

            clarification = ClarificationDecision(
                need_clarification=True,
                question="你想问哪家店？请直接说店名，或者发我候选店序号。",
                ambiguity_type="low_information",
            )
            state.clarification = clarification
            state.route_decision = "clarify"
            state.route_reason = "low_information_query"
            state.metrics.update(
                {
                    "trace_id": command.trace_id,
                    "latest_turn_message": command.message,
                    "raw_query": command.message,
                    "normalized_query": getattr(understanding, "normalized_query", command.message),
                    "current_intent": str(getattr(intent, "value", intent)),
                    "low_information_input": True,
                    "should_clarify": True,
                    "latest_message_priority": "low_information_gate",
                    "session_current_shop_before": session_current_shop_before,
                    "session_current_shop_after": session_current_shop_before,
                    "session_current_shop_id_before": session_current_shop_id_before,
                    "session_current_shop_id_after": session_current_shop_id_before,
                    "last_candidates_before": last_candidates_before,
                    "last_candidates_after": last_candidates_before,
                    "target_shop": {
                        "source": "session",
                        "resolution_source": "missing",
                        "shop_id": None,
                        "shop_name": None,
                        "confidence": 0.0,
                        "is_explicit_in_current_turn": False,
                        "is_pronoun_inherited": False,
                        "is_candidate_reference": False,
                        "should_clarify": True,
                        "reason": "low_information_query",
                        "candidate_shop_ids": [],
                    },
                    "target_shop.source": "session",
                    "target_shop.shop_id": None,
                    "target_shop.shop_name": None,
                    "single_shop_mode": False,
                    "target_shop_resolution": {
                        "source": "missing",
                        "resolution_source": "missing",
                        "shop_id": None,
                        "shop_name": None,
                        "confidence": 0.0,
                        "is_explicit_in_current_turn": False,
                        "is_pronoun_inherited": False,
                        "is_candidate_reference": False,
                        "should_clarify": True,
                        "reason": "low_information_query",
                        "candidate_shop_ids": [],
                    },
                }
            )
            _mark_stage(
                state,
                "clarify",
                "completed",
                route_decision=state.route_decision,
                route_reason=state.route_reason,
                detail={"low_information_input": True},
            )
            answer_contract = AnswerContract.build_contract(user_need, None)
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
                model_hint={
                    "answer_text": clarification.question,
                    "suggested_replies": [
                        {"label": "发店名", "prompt": "海底捞水晶城店"},
                        {"label": "发序号", "prompt": "第一家"},
                    ],
                },
                source_mode="clarification_only",
                degraded_reason=None,
                knowledge_freshness={},
                graph_trace=state.metrics,
            )
            bundle = sanitize_local_life_output(bundle, shop_lookup={})
            bundle = bundle.model_copy(
                update={
                    "metrics": {
                        **dict(bundle.metrics),
                        **dict(state.metrics),
                        "user_need": user_need.model_dump(mode="json"),
                        "route_review": None,
                        "execution_requirements": None,
                    },
                    "context": {
                        **dict(bundle.context),
                        "metrics": {
                            **dict(bundle.metrics),
                            **dict(state.metrics),
                            "user_need": user_need.model_dump(mode="json"),
                        },
                        "user_need": user_need.model_dump(mode="json"),
                        "route_review": None,
                        "execution_requirements": None,
                        "reviewed_route": None,
                        "clarification": clarification.model_dump(mode="json"),
                        "tool_results": list(state.tool_results),
                        "pending_user_need": user_need.model_dump(mode="json"),
                        "target_shop_resolution": dict(state.metrics.get("target_shop_resolution") or {}),
                    },
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
                    "context": {
                        **dict(bundle.context),
                        "route_decision": state.route_decision,
                        "route_reason": state.route_reason,
                        "current_stage": state.current_stage,
                        "stage_status": state.stage_status,
                        "stage_timeline": list(state.stage_timeline),
                        "pending_user_need": user_need.model_dump(mode="json"),
                        "target_shop_resolution": dict(state.metrics.get("target_shop_resolution") or {}),
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
        ctx.persistent = persistent
        ctx.client_context = client_context
        ctx.session_context = session_context
        ctx.clean_session_context = clean_session_context
        ctx.session_current_shop_before = session_current_shop_before
        ctx.session_current_shop_id_before = session_current_shop_id_before
        ctx.last_candidates_before = last_candidates_before
        ctx.low_information_input = low_information_input
        ctx.understanding = understanding
        ctx.slots = slots
        ctx.clarification = clarification
        ctx.intent = intent
        ctx.user_need = user_need
        ctx.arbitration_result = arbitration_result
        ctx.input_context = input_context
        ctx.perception_context = perception_context
        ctx.memory_arbitration = memory_arbitration
        ctx.state = state
        return None

