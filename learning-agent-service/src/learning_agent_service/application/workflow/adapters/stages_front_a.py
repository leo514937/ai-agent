from .helpers import *


class WorkflowNodeAdapterStagesFrontAMixin:
        def load_context(self, state: GraphState) -> GraphState:
            state = _copy_state(state)
            turn = state["turn"]
            persistent = state["persistent"]
            persistent, turn = _restore_pending_clarification_from_result(
                runtime=state["runtime"],
                turn=turn,
                persistent=persistent,
            )
            state["persistent"] = persistent
            state["turn"] = turn
            client_context = dict(state["runtime"].client_context)
            shop_anchor = str(
                client_context.get("shopName")
                or client_context.get("shop_name")
                or client_context.get("selected_shop_name")
                or client_context.get("current_shop")
                or ""
            ).strip()
            if shop_anchor:
                persistent_updates: dict[str, Any] = {}
                if not str(getattr(persistent, "current_shop", "") or "").strip():
                    persistent_updates["current_shop"] = shop_anchor
                if not str(getattr(persistent, "selected_shop_name", "") or "").strip():
                    persistent_updates["selected_shop_name"] = shop_anchor
                shop_id = str(
                    client_context.get("shopId")
                    or client_context.get("shop_id")
                    or client_context.get("selected_shop_id")
                    or ""
                ).strip()
                if shop_id and not str(getattr(persistent, "selected_shop_id", "") or "").strip():
                    persistent_updates["selected_shop_id"] = shop_id
                if persistent_updates:
                    persistent = persistent.model_copy(update=persistent_updates)
                    state["persistent"] = persistent
            routing = build_initial_routing_decision(
                turn.raw_query,
                persistent,
                client_context=state["runtime"].client_context,
            )
            routing = legacy_to_routing_decision(turn, persistent, routing)
            routing = _apply_route_review(
                routing,
                raw_query=turn.raw_query,
                persistent=persistent,
                client_context=state["runtime"].client_context,
            )
            turn = _store_routing_decision(turn, routing)
            if routing.required_action in {"clarify", "reject", "direct_answer", "memory_update", "no_op"}:
                if routing.required_action == "clarify":
                    clarification_result, pending_clarification = self._build_pending_clarification_state(
                        runtime=state["runtime"],
                        turn=turn,
                        routing=routing,
                        question=str(routing.clarification_question or ""),
                    )
                    persistent = persistent.model_copy(
                        update={
                            "clarification_result": clarification_result,
                            "pending_clarification": pending_clarification,
                        }
                    )
                    state["persistent"] = persistent
                    turn_extra = dict(turn.extra)
                    turn_extra["clarification_result"] = clarification_result
                    turn_extra["pending_clarification"] = pending_clarification.model_dump(mode="json")
                    turn = turn.model_copy(update={"extra": turn_extra})
                state["turn"] = turn
                runtime = state["runtime"]
                metrics = dict(runtime.metrics)
                metrics["memory_retrieval_skipped"] = True
                metrics["routing_decision"] = routing.model_dump(mode="json")
                metrics["routing_required_action"] = routing.required_action
                metrics["routing_reason"] = routing.route_reason
                state["runtime"] = runtime.model_copy(update={"metrics": metrics})
                state = _update_phase0_trace(
                    state,
                    harness_mode=str((state["runtime"].extra or {}).get("harness_mode") or "off"),
                    initial_routing_decision=routing.model_dump(mode="json"),
                    initial_route_reason=routing.route_reason,
                    initial_route_candidate=routing.route_candidate,
                    initial_required_action=routing.required_action,
                    retrieval_plan_status="not_attempted",
                    retrieval_plan_failure_reason=None,
                    tool_plan_status="not_attempted",
                    tool_plan_failure_reason=None,
                )
                _log_routing_decision(state, stage="load_context_terminal")
                return state
    
            gate = getattr(self.container, "rag_route_gate", None)
            if gate is not None and hasattr(gate, "precheck"):
                request = RagGateRequest(
                    raw_query=turn.raw_query,
                    intent=turn.intent,
                    intent_confidence=turn.intent_confidence,
                    requested_output_style=turn.requested_output_style,
                    current_topic=persistent.current_topic,
                    recent_entities=persistent.recent_entities,
                    history_summary=persistent.history_summary,
                    pending_clarification=persistent.pending_clarification,
                    reference_confidence=getattr(turn.reference_resolution, "confidence", None) if turn.reference_resolution else None,
                    reference_resolved=getattr(turn.reference_resolution, "resolved", None) if turn.reference_resolution else None,
                    client_context=dict(state["runtime"].client_context),
                )
                vote = gate.precheck(request)
                cached_vote = {
                    "allowed": vote.vote == "allow",
                    "reason": vote.reason,
                    "confidence": vote.confidence,
                    "response_kind": vote.response_kind,
                    "precheck_skip_memory": False,
                    "final_vote": vote.vote,
                    "rule_vote": None,
                    "llm_vote": None,
                    "metadata": {
                        "source": "precheck",
                        "decision": vote.vote,
                        "reason": vote.reason,
                    },
                }
                turn_extra = dict(turn.extra)
                turn_extra["rag_gate"] = {
                    **dict(turn_extra.get("rag_gate", {})),
                    "precheck_vote": vote.vote,
                    "precheck_reason": vote.reason,
                    "precheck_response_kind": vote.response_kind,
                }
                turn_extra["cached_rag_gate_vote"] = cached_vote
                turn = turn.model_copy(update={"extra": turn_extra})
    
            runtime = state["runtime"]
            metrics = dict(runtime.metrics)
            metrics["routing_decision"] = routing.model_dump(mode="json")
            metrics["routing_required_action"] = routing.required_action
            metrics["routing_reason"] = routing.route_reason
            metrics["memory_retrieval_skipped"] = not routing.should_use_memory
            state["turn"] = turn
            state["runtime"] = runtime.model_copy(update={"metrics": metrics})
            state = _update_phase0_trace(
                state,
                harness_mode=str((state["runtime"].extra or {}).get("harness_mode") or "off"),
                initial_routing_decision=routing.model_dump(mode="json"),
                initial_route_reason=routing.route_reason,
                initial_route_candidate=routing.route_candidate,
                initial_required_action=routing.required_action,
                retrieval_plan_status="not_attempted",
                retrieval_plan_failure_reason=None,
                tool_plan_status="not_attempted",
                tool_plan_failure_reason=None,
            )
            _log_routing_decision(state, stage="load_context")
            return state
    
        def consume_pending_clarification(self, state: GraphState) -> GraphState:
            turn = state["turn"]
            persistent = state["persistent"]
            runtime = state["runtime"]
            pending = getattr(persistent, "pending_clarification", None)
            if pending is None or not _pending_clarification_matches_query(turn.raw_query, persistent):
                return state
    
            clarification_result = dict(getattr(persistent, "clarification_result", {}) or {})
            turn_extra = dict(turn.extra)
            pending_restore = dict(turn_extra.get("pending_clarification_restore") or {})
            original_query = str(
                pending_restore.get("original_query")
                or clarification_result.get("original_query")
                or getattr(pending, "question", "")
                or ""
            ).strip()
            if not original_query:
                return state
    
            original_intent = str(
                pending_restore.get("original_intent")
                or clarification_result.get("original_intent")
                or "local_life_recommend"
            ).strip() or "local_life_recommend"
            original_route = str(
                pending_restore.get("original_route")
                or clarification_result.get("original_route")
                or "rag_retrieval"
            ).strip() or "rag_retrieval"
    
            follow_up_query = str(turn.raw_query or "").strip()
            ambiguity_type = str(
                getattr(pending, "ambiguity_type", "")
                or clarification_result.get("ambiguity_type")
                or ""
            ).strip().lower()
    
            restored_persistent: dict[str, Any] = {}
            if str(getattr(persistent, "current_topic", "") or "").strip() != original_query:
                restored_persistent["current_topic"] = original_query
            if str(getattr(persistent, "last_retrieval_topic", "") or "").strip() != original_query:
                restored_persistent["last_retrieval_topic"] = original_query
    
            city = ""
            location_value: dict[str, Any] | None = None
            if ambiguity_type in {"location", "city", "area", "district", "region"}:
                try:
                    location_result = normalize_local_life_query(
                        follow_up_query,
                        client_context=dict(runtime.client_context),
                        session_context={
                            "current_city": getattr(persistent, "current_city", None),
                            "current_location": dict(getattr(persistent, "current_location", {}) or {}),
                            "city": getattr(persistent, "current_city", None),
                            "location": dict(getattr(persistent, "current_location", {}) or {}),
                        },
                    )
                    location_norm = getattr(location_result, "location_norm", None)
                    city = str(getattr(location_norm, "city", "") or "").strip()
                    if city:
                        location_value = (
                            location_norm.model_dump(mode="json")
                            if hasattr(location_norm, "model_dump")
                            else {"city": city}
                        )
                        restored_persistent["current_city"] = city
                        restored_persistent["current_location"] = location_value
                except Exception:
                    city = ""
                    location_value = None
    
            if clarification_result:
                clarification_result = dict(clarification_result)
                clarification_result["consumed"] = True
                clarification_result["follow_up_query"] = follow_up_query
                if city:
                    clarification_result["resolved_city"] = city
            restored_persistent["pending_clarification"] = None
            if clarification_result:
                restored_persistent["clarification_result"] = clarification_result
            state["persistent"] = persistent.model_copy(update=restored_persistent)
    
            turn_slots = dict(turn.slots)
            if city:
                turn_slots["city"] = city
            if location_value is not None:
                turn_slots["location"] = location_value
    
            turn_extra.update(
                {
                    "clarification_result": clarification_result,
                    "clarification_response": follow_up_query,
                    "pending_clarification_consumed": True,
                    "restored_query": original_query,
                    "restored_intent": original_intent,
                    "restored_route": original_route,
                    "pending_clarification_restore": {
                        "original_query": original_query,
                        "original_intent": original_intent,
                        "original_route": original_route,
                    },
                }
            )
            if city:
                turn_extra["restored_city"] = city
            if location_value is not None:
                turn_extra["restored_location"] = location_value
            turn_extra.pop("pending_clarification", None)
            short_term_window = list(turn.short_term_window)
            if short_term_window:
                short_term_window[0] = {
                    **dict(short_term_window[0]),
                    "content": original_query,
                }
            sensory_memory = dict(turn.sensory_memory)
            sensory_memory["raw_message"] = original_query
            sensory_memory["clarification_response"] = follow_up_query
            state["turn"] = turn.model_copy(
                update={
                    "raw_query": original_query,
                    "slots": turn_slots,
                    "short_term_window": short_term_window,
                    "sensory_memory": sensory_memory,
                    "clarification_card": None,
                    "extra": turn_extra,
                }
            )
    
            routing_context = state["persistent"].model_copy(update={"pending_clarification": None})
            routing = build_initial_routing_decision(
                original_query,
                routing_context,
                client_context=runtime.client_context,
            )
            routing = legacy_to_routing_decision(state["turn"], routing_context, routing)
            routing = _apply_route_review(
                routing,
                raw_query=original_query,
                persistent=routing_context,
                client_context=runtime.client_context,
            )
            turn_extra = dict(state["turn"].extra)
            turn_extra["routing_decision"] = routing.model_dump(mode="json")
            turn_extra["routing_trace"] = routing_trace_payload(routing)
            state["turn"] = state["turn"].model_copy(update={"routing_decision": routing, "extra": turn_extra})
            state = _update_phase0_trace(
                state,
                pending_clarification_consumed=True,
                pending_clarification_follow_up=follow_up_query,
                restored_query=original_query,
                restored_intent=original_intent,
                restored_route=original_route,
                restored_city=city or None,
            )
            _log_routing_decision(state, stage="consume_pending_clarification")
            return state
    
        def conversation_recap_direct_response(self, state: GraphState) -> GraphState:
            turn = state["turn"]
            routing = _routing_decision_for_turn(turn)
            if routing is None or str(routing.route_candidate).strip().lower() != "conversation_recap":
                return state
            turn_extra = dict(turn.extra)
            turn_extra["conversation_recap"] = True
            turn_extra["direct_response_kind"] = "conversation_recap"
            state["turn"] = turn.model_copy(update={"extra": turn_extra})
            state = _update_phase0_trace(
                state,
                conversation_recap=True,
                direct_response_kind="conversation_recap",
                current_shop=state["persistent"].current_shop or state["persistent"].selected_shop_name,
            )
            _log_routing_decision(state, stage="conversation_recap_direct_response")
            return state
    
        def parse_intent_slots(self, state: GraphState) -> GraphState:
            model_gateway = getattr(self.container, "model_gateway", None)
            if model_gateway is None or not hasattr(model_gateway, "classify_turn"):
                return state
    
            turn = state["turn"]
            persistent = state["persistent"]
            routing = _routing_decision_for_turn(turn)
            if routing is not None and (routing.blocked or routing.required_action in {"clarify", "reject", "direct_answer", "memory_update", "no_op"}):
                return state
            if getattr(persistent, "pending_clarification", None) is not None and _pending_clarification_matches_query(turn.raw_query, persistent):
                pending_restore = dict(dict(turn.extra).get("pending_clarification_restore") or {})
                original_query = str(
                    pending_restore.get("original_query")
                    or getattr(persistent, "clarification_result", {}).get("original_query")
                    or ""
                ).strip()
                restored_persistent: dict[str, Any] = {}
                if original_query:
                    if str(getattr(persistent, "current_topic", "") or "").strip() != original_query:
                        restored_persistent["current_topic"] = original_query
                    if str(getattr(persistent, "last_retrieval_topic", "") or "").strip() != original_query:
                        restored_persistent["last_retrieval_topic"] = original_query
    
                ambiguity_type = str(getattr(persistent.pending_clarification, "ambiguity_type", "") or "").strip().lower()
                if ambiguity_type in {"location", "city", "area", "district", "region"}:
                    try:
                        location_result = normalize_local_life_query(
                            turn.raw_query,
                            client_context=dict(state["runtime"].client_context),
                            session_context={
                                "current_city": getattr(persistent, "current_city", None),
                                "current_location": dict(getattr(persistent, "current_location", {}) or {}),
                                "city": getattr(persistent, "current_city", None),
                                "location": dict(getattr(persistent, "current_location", {}) or {}),
                            },
                        )
                        location_norm = getattr(location_result, "location_norm", None)
                        city = str(getattr(location_norm, "city", "") or "").strip()
                        if city:
                            restored_persistent["current_city"] = city
                            restored_persistent["current_location"] = (
                                location_norm.model_dump(mode="json")
                                if hasattr(location_norm, "model_dump")
                                else {"city": city}
                            )
                            turn_slots = dict(turn.slots)
                            turn_slots.setdefault("city", city)
                            if hasattr(location_norm, "model_dump"):
                                turn_slots.setdefault("location", location_norm.model_dump(mode="json"))
                            state["turn"] = turn.model_copy(update={"slots": turn_slots})
                    except Exception:
                        pass
                if restored_persistent:
                    state["persistent"] = persistent.model_copy(update=restored_persistent)
                return state
            runtime = state["runtime"]
            command = ChatTurnCommand(
                trace_id=runtime.trace_id,
                session_id=runtime.session_id,
                turn_id=runtime.turn_id,
                user_id=runtime.user_id,
                message=turn.raw_query,
                page=runtime.page,
                response_mode=runtime.response_mode,
                topic_hint=runtime.topic_hint,
                history_summary=runtime.history_summary,
                client_context=runtime.client_context,
            )
            request = TurnUnderstandingRequest(command=command, persistent=state["persistent"])
            started_at = time.perf_counter()
            fast_result: FastDecision | None = None
            degrade_to: str | None = None
            with ThreadPoolExecutor(max_workers=1, thread_name_prefix="intent-analysis") as executor:
                future = executor.submit(model_gateway.classify_turn, request)
                try:
                    fast_result = future.result(timeout=_CLASSIFY_TIMEOUT_SECONDS)
                except FuturesTimeoutError:
                    gate = getattr(model_gateway, "intent_gate", None)
                    fallback = gate.fallback_decide(request) if gate is not None and hasattr(gate, "fallback_decide") else None
                    if fallback is None:
                        from ...rag.heuristics import HeuristicIntentGate
    
                        fallback = HeuristicIntentGate().fallback_decide(request)
                    fast_result = fallback
                    degrade_to = "classify_timeout_fallback"
                except Exception:
                    gate = getattr(model_gateway, "intent_gate", None)
                    fallback = gate.fallback_decide(request) if gate is not None and hasattr(gate, "fallback_decide") else None
                    if fallback is None:
                        from ...rag.heuristics import HeuristicIntentGate
    
                        fallback = HeuristicIntentGate().fallback_decide(request)
                    fast_result = fallback
                    degrade_to = "classify_error_fallback"
            result = fast_result or FastDecision(intent=IntentType.EXPLAIN, needs_rag=False, needs_tool=False, confidence=0.0)
            if degrade_to is None:
                gateway_degrade = str(getattr(model_gateway, "last_degrade_to", "") or "").strip()
                degrade_to = gateway_degrade or None
            elapsed_ms = (time.perf_counter() - started_at) * 1000.0
            _append_stage_metric(state, "intent_analysis", elapsed_ms)
            if degrade_to:
                _mark_degrade(state, degrade_to)
    
            decision_result = result
            if not isinstance(result, FastDecision):
                decision_result = FastDecision(
                    intent=getattr(result, "intent", IntentType.EXPLAIN),
                    needs_rag=bool(
                        getattr(result, "required_action", None) in {"rag_retrieval", "rag_plus_tool"}
                        or getattr(result, "retrieval_plan", None) is not None
                    ),
                    needs_tool=bool(getattr(result, "required_action", None) in {"tool_call", "rag_plus_tool"}),
                    needs_clarify=bool(getattr(result, "required_action", None) == "clarify"),
                    needs_query_rewrite=bool(getattr(result, "needs_query_rewrite", False)),
                    confidence=float(getattr(result, "intent_confidence", getattr(result, "confidence", 0.0)) or 0.0),
                    key_slots=dict(getattr(result, "slots", {}) or {}),
                    extra=dict(getattr(result, "extra", {}) or {}),
                )
    
            turn_extra = {**dict(turn.extra), **dict(getattr(result, "extra", {}) or {})}
            turn_extra["needs_query_rewrite"] = bool(getattr(decision_result, "needs_query_rewrite", False))
            reference_resolution = _coerce_reference_resolution(
                getattr(result, "reference_resolution", None)
                or turn_extra.get("reference_resolution")
                or turn_extra.get("cached_reference_resolution")
            )
            retrieval_plan = _coerce_retrieval_plan(
                getattr(result, "retrieval_plan", None)
                or turn_extra.get("retrieval_plan")
                or turn_extra.get("cached_retrieval_plan")
            )
            if retrieval_plan is None and decision_result.needs_rag:
                retrieval_plan = _build_raw_retrieval_plan(turn)
            if reference_resolution is not None:
                turn_extra["cached_reference_resolution"] = reference_resolution.model_dump(mode="json")
            if retrieval_plan is not None:
                turn_extra["cached_retrieval_plan"] = retrieval_plan.model_dump(mode="json")
            routing = routing or build_initial_routing_decision(turn.raw_query, state["persistent"], client_context=runtime.client_context)
            routing = apply_fast_decision_to_routing(
                routing,
                decision_result,
                reference_resolved=getattr(reference_resolution, "resolved", False) if reference_resolution is not None else False,
                reference_confidence=getattr(reference_resolution, "confidence", None) if reference_resolution is not None else None,
                resolved_references=[getattr(reference_resolution, "resolved_entity", None)] if reference_resolution is not None else None,
            )
            routing = _apply_route_review(
                routing,
                raw_query=turn.raw_query,
                persistent=state["persistent"],
                client_context=runtime.client_context,
            )
            rewrite_decision = None
            if retrieval_plan is not None:
                rewrite_confidence = float(retrieval_plan.extra.get("filter_confidence", decision_result.confidence) or decision_result.confidence)
                rewrite_decision = build_rewrite_decision(
                    turn.raw_query,
                    retrieval_plan.semantic_query or turn.raw_query,
                    confidence=rewrite_confidence,
                    reason=str(retrieval_plan.extra.get("rewrite_reason") or retrieval_plan.extra.get("rewrite_source") or "rewrite_plan"),
                    preserved_constraints=[str(item) for item in dict(turn.slots).keys()],
                    extra=retrieval_plan.extra,
                )
                routing = routing.model_copy(update={"rewrite_decision": rewrite_decision})
            existing_gate = turn_extra.get("rag_gate")
            if isinstance(existing_gate, Mapping):
                existing_gate = dict(existing_gate)
            else:
                existing_gate = {}
            if "allowed" not in existing_gate:
                required_action = (
                    "clarify"
                    if decision_result.needs_clarify
                    else "rag_plus_tool"
                    if decision_result.needs_tool and decision_result.needs_rag
                    else "tool_call"
                    if decision_result.needs_tool
                    else "rag_retrieval"
                    if decision_result.needs_rag
                    else "direct_answer"
                )
                computed_gate = _build_cached_rag_gate(
                    required_action,
                    decision_result.intent,
                    decision_result.confidence,
                    turn_extra,
                    slots=dict(getattr(decision_result, "key_slots", {}) or {}),
                )
                existing_gate = {**existing_gate, **computed_gate}
            turn_extra = _apply_phase1_routing_extra(turn_extra, routing)
            turn_extra["rag_gate"] = existing_gate
            turn_extra["cached_rag_gate_vote"] = dict(existing_gate)
            turn_extra["routing_decision"] = routing.model_dump(mode="json")
            turn_extra["routing_trace"] = routing_trace_payload(routing)
            state["turn"] = turn.model_copy(
                update={
                    "intent": decision_result.intent,
                    "intent_confidence": decision_result.confidence,
                    "requested_output_style": turn.requested_output_style,
                    "reference_resolution": reference_resolution,
                    "retrieval_plan": retrieval_plan,
                    "slots": dict(getattr(decision_result, "key_slots", {}) or {}),
                    "routing_decision": routing,
                    "rewrite_decision": rewrite_decision,
                    "extra": turn_extra,
                }
            )
            if routing.blocked and str(routing.required_action).strip().lower() == "clarify":
                clarification_result, pending_clarification = self._build_pending_clarification_state(
                    runtime=runtime,
                    turn=state["turn"],
                    routing=routing,
                    question=str(routing.clarification_question or ""),
                )
                state["persistent"] = state["persistent"].model_copy(
                    update={
                        "clarification_result": clarification_result,
                        "pending_clarification": pending_clarification,
                    }
                )
                turn_extra = dict(state["turn"].extra)
                turn_extra["clarification_result"] = clarification_result
                turn_extra["pending_clarification"] = pending_clarification.model_dump(mode="json")
                state["turn"] = state["turn"].model_copy(update={"extra": turn_extra})
            if routing.required_action in {"rag_retrieval", "rag_plus_tool"}:
                state = ensure_retrieval_plan(state)
            if routing.required_action in {"tool_call", "rag_plus_tool"}:
                state = ensure_tool_plan(state)
            state = ensure_task_plan(state)
            state = _update_phase0_trace(
                state,
                parsed_intent=decision_result.intent.value if hasattr(decision_result.intent, "value") else str(decision_result.intent),
                parsed_intent_confidence=decision_result.confidence,
                needs_rag=bool(decision_result.needs_rag),
                needs_tool=bool(decision_result.needs_tool),
                needs_clarify=bool(decision_result.needs_clarify),
            )
            _log_routing_decision(state, stage="intent_analysis")
            return state
    
        def resolve_reference(self, state: GraphState) -> GraphState:
            rag_orchestrator = getattr(self.container, "rag_orchestrator", None)
            if rag_orchestrator is None or not hasattr(rag_orchestrator, "resolve_reference"):
                return state
    
            turn = state["turn"]
            routing = _routing_decision_for_turn(turn)
            if routing is not None and routing.blocked:
                return state
            cached_resolution = turn.reference_resolution or _coerce_reference_resolution(
                dict(turn.extra).get("cached_reference_resolution") or dict(turn.extra).get("reference_resolution")
            )
            if cached_resolution is not None:
                updated_turn = turn
                if turn.reference_resolution is None:
                    updated_turn = turn.model_copy(update={"reference_resolution": cached_resolution})
                if getattr(cached_resolution, "resolved", False) and getattr(cached_resolution, "resolved_entity", None):
                    persistent = state["persistent"]
                    state["persistent"] = persistent.model_copy(update={"current_topic": cached_resolution.resolved_entity})
                    if routing is not None:
                        updated_routing = routing.model_copy(
                            update={
                                "resolved_references": list(dict.fromkeys(list(routing.resolved_references) + [cached_resolution.resolved_entity])),
                                "route_reason": routing.route_reason or "reference_resolved_from_cache",
                            }
                        )
                        updated_turn = _store_routing_decision(updated_turn, updated_routing)
                state["turn"] = updated_turn
                return state
    
            persistent = state["persistent"]
            runtime = state["runtime"]
            request = ReferenceResolutionRequest(
                raw_query=turn.raw_query,
                current_topic=persistent.current_topic,
                recent_entities=list(persistent.recent_entities),
                clarification_result=dict(persistent.clarification_result),
                pending_clarification=persistent.pending_clarification,
                history_summary=persistent.history_summary,
                topic_hint=runtime.topic_hint,
            )
            result = rag_orchestrator.resolve_reference(request)
            updated_turn = turn.model_copy(update={"reference_resolution": result})
            if getattr(result, "resolved", False) and getattr(result, "resolved_entity", None):
                state["persistent"] = persistent.model_copy(update={"current_topic": result.resolved_entity})
                if routing is not None:
                    updated_routing = routing.model_copy(
                        update={
                            "resolved_references": list(dict.fromkeys(list(routing.resolved_references) + [result.resolved_entity])),
                        }
                    )
                    updated_turn = _store_routing_decision(updated_turn, updated_routing)
            state["turn"] = updated_turn
            return state
    
        def ambiguity_check(self, state: GraphState) -> GraphState:
            turn = state["turn"]
            routing = _routing_decision_for_turn(turn)
            if routing is not None and routing.blocked:
                return state
            if routing is not None and str(routing.route_candidate or "").strip().lower() in {"conversation_recap", "continue_previous_topic"}:
                return state
            if turn.intent_confidence >= 0.5 and (routing is None or routing.input_quality.kind not in {"ambiguous_reference", "incomplete_recommendation", "low_information"}):
                return state
    
            turn_extra = dict(turn.extra)
            turn_extra["clarification_signal"] = {
                "kind": "low_confidence",
                "intent_confidence": turn.intent_confidence,
            }
            if routing is not None:
                routing = routing.model_copy(
                    update={
                        "safeguards_triggered": list(dict.fromkeys(list(routing.safeguards_triggered) + ["ambiguity_check"])),
                    }
                )
                turn = _store_routing_decision(turn, routing)
                turn_extra = dict(turn.extra)
                turn_extra["clarification_signal"] = {
                    "kind": "low_confidence",
                    "intent_confidence": turn.intent_confidence,
                }
            state["turn"] = turn.model_copy(update={"extra": turn_extra})
            return state
    
        def rag_gate(self, state: GraphState) -> GraphState:
            gate = getattr(self.container, "rag_route_gate", None)
            if gate is None or not hasattr(gate, "decide"):
                return state
    
            turn = state["turn"]
            persistent = state["persistent"]
            routing = _routing_decision_for_turn(turn)
            if routing is not None and not routing.should_retrieve:
                turn_extra = dict(turn.extra)
                turn_extra["rag_gate"] = {
                    "allowed": False,
                    "reason": routing.route_reason or routing.required_action,
                    "confidence": routing.input_quality.score,
                    "response_kind": _response_kind_for_turn(turn) or "low_info",
                    "precheck_skip_memory": True,
                    "final_vote": "deny",
                    "rule_vote": None,
                    "llm_vote": None,
                    "metadata": {"source": "routing_decision"},
                }
                turn_extra["route_reason"] = routing.route_reason or turn_extra.get("route_reason")
                if routing.blocked:
                    turn_extra["routing_decision"] = routing.model_dump(mode="json")
                    turn_extra["routing_trace"] = routing_trace_payload(routing)
                state["turn"] = turn.model_copy(update={"extra": turn_extra})
                return state
            cached_gate = _cached_rag_gate(turn)
            if cached_gate is not None:
                turn_extra = dict(turn.extra)
                turn_extra["rag_gate"] = cached_gate
                turn_extra["route_reason"] = cached_gate.get("reason", turn_extra.get("route_reason"))
                if not bool(cached_gate.get("allowed", True)) and cached_gate.get("response_kind") in {"low_info", "empty"}:
                    blocked_routing = routing
                    if blocked_routing is None:
                        blocked_routing = build_initial_routing_decision(turn.raw_query, persistent, client_context=state["runtime"].client_context)
                    blocked_action = "reject" if cached_gate.get("response_kind") == "empty" else "clarify"
                    blocked_routing = _mark_routing_blocked(
                        blocked_routing,
                        reason=str(cached_gate.get("reason") or cached_gate.get("response_kind") or "rag_gate_blocked"),
                        required_action=blocked_action,
                        route_candidate=blocked_routing.route_candidate,
                    )
                    turn_extra["clarification_response_kind"] = cached_gate.get("response_kind")
                    turn_extra["clarification_signal"] = {
                        "kind": cached_gate.get("response_kind"),
                        "reason": cached_gate.get("reason"),
                    }
                    if blocked_action == "clarify":
                        clarification_result, pending_clarification = self._build_pending_clarification_state(
                            runtime=state["runtime"],
                            turn=turn,
                            routing=blocked_routing,
                            question=str(blocked_routing.clarification_question or ""),
                        )
                        persistent = persistent.model_copy(
                            update={
                                "clarification_result": clarification_result,
                                "pending_clarification": pending_clarification,
                            }
                        )
                        state["persistent"] = persistent
                        turn_extra["clarification_result"] = clarification_result
                        turn_extra["pending_clarification"] = pending_clarification.model_dump(mode="json")
                    runtime = state["runtime"]
                    metrics = dict(runtime.metrics)
                    state["runtime"] = runtime.model_copy(update={"metrics": metrics})
                    turn_extra["routing_decision"] = blocked_routing.model_dump(mode="json")
                    turn_extra["routing_trace"] = routing_trace_payload(blocked_routing)
                    state["turn"] = turn.model_copy(update={"routing_decision": blocked_routing, "extra": turn_extra})
                    return state
                if not bool(cached_gate.get("allowed", True)):
                    blocked_routing = routing
                    if blocked_routing is None:
                        blocked_routing = build_initial_routing_decision(turn.raw_query, persistent, client_context=state["runtime"].client_context)
                    blocked_action = "reject" if cached_gate.get("response_kind") == "empty" else "clarify"
                    blocked_routing = _mark_routing_blocked(
                        blocked_routing,
                        reason=str(cached_gate.get("reason") or cached_gate.get("response_kind") or "rag_gate_blocked"),
                        required_action=blocked_action,
                        route_candidate=blocked_routing.route_candidate,
                    )
                    turn_extra["routing_decision"] = blocked_routing.model_dump(mode="json")
                    turn_extra["routing_trace"] = routing_trace_payload(blocked_routing)
                    state["turn"] = turn.model_copy(update={"routing_decision": blocked_routing, "extra": turn_extra})
                    return state
                state["turn"] = turn.model_copy(update={"extra": turn_extra})
                return state
    
            request = __import__("learning_agent_service.application.rag_gate", fromlist=["RagGateRequest"]).RagGateRequest(
                raw_query=turn.raw_query,
                intent=turn.intent,
                intent_confidence=turn.intent_confidence,
                requested_output_style=turn.requested_output_style,
                current_topic=persistent.current_topic,
                recent_entities=persistent.recent_entities,
                history_summary=persistent.history_summary,
                pending_clarification=persistent.pending_clarification,
                reference_confidence=getattr(turn.reference_resolution, "confidence", None) if turn.reference_resolution else None,
                reference_resolved=getattr(turn.reference_resolution, "resolved", None) if turn.reference_resolution else None,
                client_context=dict(state["runtime"].client_context),
            )
            decision = gate.decide(request)
            turn_extra = dict(turn.extra)
            turn_extra["rag_gate"] = decision.as_dict()
            turn_extra["route_reason"] = decision.reason
            if not decision.allowed:
                blocked_routing = routing
                if blocked_routing is None:
                    blocked_routing = build_initial_routing_decision(turn.raw_query, persistent, client_context=state["runtime"].client_context)
                blocked_action = "reject" if decision.response_kind in {"empty"} else "clarify"
                blocked_routing = _mark_routing_blocked(
                    blocked_routing,
                    reason=str(decision.reason or decision.response_kind or "rag_gate_blocked"),
                    required_action=blocked_action,
                    route_candidate=blocked_routing.route_candidate,
                )
                if decision.response_kind in {"low_info", "empty"}:
                    turn_extra["rag_gate"]["clarification_response_kind"] = decision.response_kind
                runtime = state["runtime"]
                metrics = dict(runtime.metrics)
                state["runtime"] = runtime.model_copy(update={"metrics": metrics})
                turn_extra["clarification_signal"] = {
                    "kind": decision.response_kind,
                    "reason": decision.reason,
                }
                if blocked_action == "clarify":
                    clarification_result, pending_clarification = self._build_pending_clarification_state(
                        runtime=state["runtime"],
                        turn=turn,
                        routing=blocked_routing,
                        question=str(blocked_routing.clarification_question or ""),
                    )
                    persistent = persistent.model_copy(
                        update={
                            "clarification_result": clarification_result,
                            "pending_clarification": pending_clarification,
                        }
                    )
                    state["persistent"] = persistent
                    turn_extra["clarification_result"] = clarification_result
                    turn_extra["pending_clarification"] = pending_clarification.model_dump(mode="json")
                turn_extra["routing_decision"] = blocked_routing.model_dump(mode="json")
                turn_extra["routing_trace"] = routing_trace_payload(blocked_routing)
                state["turn"] = turn.model_copy(update={"routing_decision": blocked_routing, "extra": turn_extra})
                return state
            state["turn"] = turn.model_copy(update={"extra": turn_extra})
