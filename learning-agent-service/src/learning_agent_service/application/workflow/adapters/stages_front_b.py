from typing import Any
import time
from concurrent.futures import ThreadPoolExecutor, wait

from learning_agent_service.application.router.base import routing_trace_payload, _update_phase0_trace, _update_phase1_trace, _update_phase2_trace
from learning_agent_service.local_life.hybrid_router import build_routing_decision_from_hybrid_router as build_initial_routing_decision
from learning_agent_service.application.router.phase1_intent import build_rewrite_decision
from learning_agent_service.application.router.phase2_slots import build_evidence_quality
from learning_agent_service.application.router.phase5_retrieval import can_enter_retrieval
from learning_agent_service.application.router.phase6_tool import ensure_tool_plan
from learning_agent_service.domain.contracts import CitationBuildRequest, EvidenceEvaluationRequest, HybridRetrieveRequest, QueryRewriteRequest, ReviewReport, ToolExecutionCommand, ToolNormalizationRequest, ToolPlanningRequest

from .helpers import Any, ClarificationCard, GraphState, Mapping, _append_stage_metric, _apply_phase1_routing_extra, _build_phase2_trace, _build_raw_retrieval_plan, _coerce_retrieval_plan, _emit_stage_state, _mark_degrade, _QUERY_REWRITE_TIMEOUT_SECONDS, _routing_decision_for_turn


class WorkflowNodeAdapterStagesFrontBMixin:
        container: 'Any'
        _plan_executor: 'Any'
        plan_planner: 'Any'
        plan_validator: 'Any'
        step_executor: 'Any'
        progress_checker: 'Any'
        plan_reviewer: 'Any'
        replanner: 'Any'
        human_approval_stub: 'Any'
        business_client: 'Any'
        def _build_pending_clarification_state(self, *, runtime, turn, routing, question: str) -> tuple[dict[str, Any], ClarificationCard]:
            missing_slots = list(getattr(routing, "missing_slots", None) or [])
            question_text = str(question or "").strip() or str(getattr(routing, "clarification_question", "") or "").strip() or "你可以补充一点上下文吗？"
            ambiguity_type = "location" if any(slot in {"city", "location", "area", "district", "region"} for slot in missing_slots) or any(
                token in question_text for token in ("城市", "位置", "附近")
            ) else "general"
            clarification_result = {
                "original_query": str(turn.raw_query or "").strip(),
                "original_intent": "local_life_recommend",
                "original_route": "rag_retrieval",
                "question": question_text,
                "ambiguity_type": ambiguity_type,
            }
            pending_clarification = ClarificationCard(
                card_id=f"{runtime.session_id}:{runtime.turn_id}:clarification",
                question=question_text,
                options=[],
                ambiguity_type=ambiguity_type,
                source_turn_id=runtime.turn_id,
                expires_at=None,
            )
            return clarification_result, pending_clarification
    
        def rewrite_query(self, state: GraphState) -> GraphState:
            rag_orchestrator = getattr(self.container, "rag_orchestrator", None)
            if rag_orchestrator is None or not hasattr(rag_orchestrator, "rewrite_query"):
                return state
    
            turn = state["turn"]
            routing = _routing_decision_for_turn(turn)
            eligibility = can_enter_retrieval(state)
            if not eligibility.allowed and routing is not None:
                if routing is not None:
                    turn_extra = dict(turn.extra)
                    turn_extra["retrieval_skipped_reason"] = eligibility.reason
                    turn_extra["routing_decision"] = routing.model_dump(mode="json")
                    turn_extra["routing_trace"] = routing_trace_payload(routing)
                    state["turn"] = turn.model_copy(update={"extra": turn_extra})
                return state
            started_at = time.perf_counter()
            _emit_stage_state(state, "query_rewrite", "started", elapsed_ms=0.0)
            raw_query = str(turn.raw_query or "").strip()
            persistent = state["persistent"]
            pending_restore = dict(dict(turn.extra).get("pending_clarification_restore") or {})
            clarification_result = getattr(persistent, "clarification_result", None)
            restored_topic = str(getattr(persistent, "current_topic", "") or "").strip()
            if not restored_topic:
                restored_topic = str(pending_restore.get("original_query") or "").strip()
            if not restored_topic and clarification_result is not None:
                getter = getattr(clarification_result, "get", None)
                if callable(getter):
                    restored_topic = str(getter("original_query") or "").strip()
                else:
                    restored_topic = str(getattr(clarification_result, "original_query", "") or "").strip()
            cached_plan = turn.retrieval_plan or _coerce_retrieval_plan(
                dict(turn.extra).get("cached_retrieval_plan") or dict(turn.extra).get("retrieval_plan")
            )
            if cached_plan is not None:
                rewrite_decision = build_rewrite_decision(
                    raw_query,
                    cached_plan.semantic_query or raw_query,
                    confidence=float(cached_plan.extra.get("filter_confidence", 1.0) or 1.0),
                    reason=str(cached_plan.extra.get("rewrite_reason") or cached_plan.extra.get("rewrite_source") or "cached_plan"),
                    preserved_constraints=[str(item) for item in dict(turn.slots).keys()],
                    extra=cached_plan.extra,
                )
                if routing is None:
                    routing = build_initial_routing_decision(turn.raw_query, state["persistent"], client_context=state["runtime"].client_context)
                routing = routing.model_copy(update={"rewrite_decision": rewrite_decision})
                elapsed_ms = (time.perf_counter() - started_at) * 1000.0
                _append_stage_metric(state, "query_rewrite", elapsed_ms)
                _emit_stage_state(
                    state,
                    "query_rewrite",
                    "done",
                    elapsed_ms=elapsed_ms,
                    details={"rewrite_source": "cached_plan"},
                )
                turn_extra = dict(turn.extra)
                turn_extra["routing_decision"] = routing.model_dump(mode="json")
                turn_extra["routing_trace"] = routing_trace_payload(routing)
                state["turn"] = turn.model_copy(
                    update={
                        "retrieval_plan": cached_plan,
                        "rewrite_decision": rewrite_decision,
                        "routing_decision": routing,
                        "extra": turn_extra,
                    }
                )
                return state
    
            lowered = raw_query.lower()
            has_reference = any(token in lowered for token in ("this", "that", "it", "previous")) or any(
                token in raw_query for token in ("这", "那", "它", "前面", "刚才", "上一个")
            )
            low_confidence = float(turn.intent_confidence or 0.0) < 0.65
            needs_query_rewrite = bool(turn.extra.get("needs_query_rewrite") or turn.slots.get("needs_query_rewrite"))
            context_dependent = bool(turn.reference_resolution and turn.reference_resolution.resolved)
            short_or_ellipsis = len(raw_query) <= 8
            should_rewrite = bool(needs_query_rewrite or has_reference or low_confidence or context_dependent or short_or_ellipsis)
    
            persistent = state["persistent"]
            runtime = state["runtime"]
            if not should_rewrite:
                plan = _build_raw_retrieval_plan(turn)
                rewrite_decision = build_rewrite_decision(
                    raw_query,
                    plan.semantic_query or raw_query,
                    confidence=1.0,
                    reason="rewrite_skipped_use_raw_query",
                    preserved_constraints=[str(item) for item in dict(turn.slots).keys()],
                    extra=plan.extra,
                )
                if routing is None:
                    routing = build_initial_routing_decision(turn.raw_query, state["persistent"], client_context=state["runtime"].client_context)
                routing = routing.model_copy(update={"rewrite_decision": rewrite_decision})
                elapsed_ms = (time.perf_counter() - started_at) * 1000.0
                _append_stage_metric(state, "query_rewrite", elapsed_ms)
                _emit_stage_state(
                    state,
                    "query_rewrite",
                    "done",
                    elapsed_ms=elapsed_ms,
                    details={"rewrite_source": "raw_query_skip"},
                )
                turn_extra = dict(turn.extra)
                turn_extra["routing_decision"] = routing.model_dump(mode="json")
                turn_extra["routing_trace"] = routing_trace_payload(routing)
                state["turn"] = turn.model_copy(
                    update={
                        "retrieval_plan": plan,
                        "rewrite_decision": rewrite_decision,
                        "routing_decision": routing,
                        "extra": turn_extra,
                    }
                )
                return state
    
            request = QueryRewriteRequest(
                raw_query=raw_query,
                intent=turn.intent,
                requested_output_style=turn.requested_output_style,
                reference_resolution=turn.reference_resolution,
                current_topic=restored_topic or persistent.current_topic,
                topic_hint=restored_topic or runtime.topic_hint,
                intent_confidence=turn.intent_confidence,
                user_preferences=dict(persistent.user_preferences),
                base_filters=dict(turn.slots),
            )
            degrade_to: str | None = None
            warmup_cache_hit = False
            warmup_fn = getattr(rag_orchestrator, "warmup_raw_query_embedding", None)
            with ThreadPoolExecutor(max_workers=2, thread_name_prefix="query-rewrite") as executor:
                rewrite_future = executor.submit(rag_orchestrator.rewrite_query, request)
                warmup_future = executor.submit(warmup_fn, raw_query) if callable(warmup_fn) else None
                timeout_ms = _QUERY_REWRITE_TIMEOUT_SECONDS * 1000.0
                while True:
                    elapsed_ms = (time.perf_counter() - started_at) * 1000.0
                    if rewrite_future.done():
                        if elapsed_ms >= timeout_ms:
                            degrade_to = "query_rewrite_timeout_raw_query"
                        break
                    if elapsed_ms >= timeout_ms:
                        rewrite_future.cancel()
                        degrade_to = "query_rewrite_timeout_raw_query"
                        break
                    wait([rewrite_future], timeout=0.8)
                    if rewrite_future.done():
                        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
                        if elapsed_ms >= timeout_ms:
                            degrade_to = "query_rewrite_timeout_raw_query"
                        break
                    _emit_stage_state(state, "query_rewrite", "heartbeat", elapsed_ms=elapsed_ms)
                if degrade_to is None:
                    try:
                        plan = rewrite_future.result()
                    except Exception:
                        plan = _build_raw_retrieval_plan(turn)
                        degrade_to = "query_rewrite_error_raw_query"
                else:
                    plan = _build_raw_retrieval_plan(turn)
                if warmup_future is not None:
                    try:
                        warmup_payload = warmup_future.result(timeout=0.05) if warmup_future.done() else None
                    except Exception:
                        warmup_payload = None
                    if isinstance(warmup_payload, Mapping):
                        warmup_cache_hit = bool(warmup_payload.get("cache_hit", False))
    
            elapsed_ms = (time.perf_counter() - started_at) * 1000.0
            _append_stage_metric(state, "query_rewrite", elapsed_ms)
            if warmup_cache_hit:
                runtime = state["runtime"]
                metrics = dict(runtime.metrics)
                metrics["embedding_cache_hit"] = True
                state["runtime"] = runtime.model_copy(update={"metrics": metrics})
            _mark_degrade(state, degrade_to)
            rewrite_decision = build_rewrite_decision(
                turn.raw_query,
                plan.semantic_query or turn.raw_query,
                confidence=float(plan.extra.get("filter_confidence", turn.intent_confidence or 0.0) or 0.0),
                reason=str(plan.extra.get("rewrite_reason") or plan.extra.get("rewrite_source") or "llm_or_rule"),
                preserved_constraints=[str(item) for item in dict(turn.slots).keys()],
                extra=plan.extra,
            )
            if routing is None:
                routing = build_initial_routing_decision(turn.raw_query, state["persistent"], client_context=state["runtime"].client_context)
            routing = routing.model_copy(update={"rewrite_decision": rewrite_decision})
            _emit_stage_state(
                state,
                "query_rewrite",
                "done",
                elapsed_ms=elapsed_ms,
                degrade_to=degrade_to,
                details={"rewrite_source": "llm_or_rule", "embedding_cache_hit": warmup_cache_hit},
            )
            turn_extra = dict(turn.extra)
            turn_extra["routing_decision"] = routing.model_dump(mode="json")
            turn_extra["routing_trace"] = routing_trace_payload(routing)
            state["turn"] = turn.model_copy(
                update={
                    "retrieval_plan": plan,
                    "rewrite_decision": rewrite_decision,
                    "routing_decision": routing,
                    "extra": turn_extra,
                }
            )
            return state
    
        def hybrid_retrieve(self, state: GraphState) -> GraphState:
            rag_orchestrator = getattr(self.container, "rag_orchestrator", None)
            turn = state["turn"]
            routing = _routing_decision_for_turn(turn)
            eligibility = can_enter_retrieval(state)
            if (
                rag_orchestrator is None
                or not hasattr(rag_orchestrator, "hybrid_retrieve")
                or not eligibility.allowed
            ):
                if routing is not None:
                    turn_extra = dict(turn.extra)
                    turn_extra["retrieval_skipped_reason"] = eligibility.reason
                    turn_extra["routing_decision"] = routing.model_dump(mode="json")
                    turn_extra["routing_trace"] = routing_trace_payload(routing)
                    state["turn"] = turn.model_copy(update={"extra": turn_extra})
                return state
            retrieval_started_at = time.perf_counter()
            _emit_stage_state(state, "embedding", "started", elapsed_ms=0.0)
            result = rag_orchestrator.hybrid_retrieve(HybridRetrieveRequest(plan=turn.retrieval_plan))
            total_elapsed_ms = (time.perf_counter() - retrieval_started_at) * 1000.0
            metrics = dict(getattr(result, "metrics", {}) or {})
            dense_ms = float(metrics.get("dense_latency_ms", 0.0) or 0.0)
            sparse_ms = float(metrics.get("sparse_latency_ms", 0.0) or 0.0)
            metadata_ms = float(metrics.get("metadata_latency_ms", 0.0) or 0.0)
            embedding_ms = float(metrics.get("embedding_latency_ms", dense_ms) or dense_ms)
            qdrant_ms = float(metrics.get("qdrant_search_latency_ms", dense_ms + sparse_ms + metadata_ms) or (dense_ms + sparse_ms + metadata_ms))
            rerank_ms = float(metrics.get("rerank_latency_ms", 0.0) or 0.0)
            rrf_ms = float(metrics.get("rrf_latency_ms", 0.0) or 0.0)
            degrade_to = str(metrics.get("fallback_reason") or "") or None
            runtime = state["runtime"]
            runtime_metrics = dict(runtime.metrics)
            runtime_metrics.update(
                {
                    "embedding_cache_hit": bool(metrics.get("embedding_cache_hit", False)),
                    "dense_latency_ms": dense_ms,
                    "sparse_latency_ms": sparse_ms,
                    "metadata_latency_ms": metadata_ms,
                    "qdrant_search_latency_ms": qdrant_ms,
                    "rrf_latency_ms": rrf_ms,
                    "rerank_latency_ms": rerank_ms,
                }
            )
            state["runtime"] = runtime.model_copy(update={"metrics": runtime_metrics})
            _append_stage_metric(state, "embedding", embedding_ms)
            _append_stage_metric(state, "dense_retrieve", dense_ms)
            _append_stage_metric(state, "sparse_retrieve", sparse_ms)
            _append_stage_metric(state, "metadata_retrieve", metadata_ms)
            _append_stage_metric(state, "rrf_fusion", rrf_ms)
            _append_stage_metric(state, "rerank", rerank_ms)
            _mark_degrade(state, degrade_to)
            _emit_stage_state(state, "embedding", "done", elapsed_ms=embedding_ms)
            _emit_stage_state(state, "qdrant_search", "started", elapsed_ms=0.0)
            _emit_stage_state(
                state,
                "qdrant_search",
                "done",
                elapsed_ms=qdrant_ms,
                degrade_to=degrade_to,
                details={
                    "dense_ms": dense_ms,
                    "sparse_ms": sparse_ms,
                    "metadata_ms": metadata_ms,
                },
            )
            _emit_stage_state(state, "rerank", "started", elapsed_ms=0.0)
            _emit_stage_state(state, "rerank", "done", elapsed_ms=rerank_ms, degrade_to=degrade_to)
            _append_stage_metric(state, "retrieval", total_elapsed_ms)
            turn_extra = dict(turn.extra)
            turn_extra["retrieval_metrics"] = metrics
            if routing is not None:
                turn_extra["routing_decision"] = routing.model_dump(mode="json")
                turn_extra["routing_trace"] = routing_trace_payload(routing)
            state["turn"] = turn.model_copy(update={"hybrid_recall": result, "extra": turn_extra})
            return state
    
        def evaluate_evidence(self, state: GraphState) -> GraphState:
            rag_orchestrator = getattr(self.container, "rag_orchestrator", None)
            turn = state["turn"]
            eligibility = can_enter_retrieval(state)
            if rag_orchestrator is None or not hasattr(rag_orchestrator, "evaluate_evidence") or not eligibility.allowed:
                return state
    
            result = rag_orchestrator.evaluate_evidence(
                EvidenceEvaluationRequest(
                    plan=turn.retrieval_plan,
                    hybrid_recall=turn.hybrid_recall,
                    intent=turn.intent,
                    requested_output_style=turn.requested_output_style,
                )
            )
            routing = _routing_decision_for_turn(turn)
            tool_result_payload = None
            if turn.raw_tool_result is not None:
                tool_result_payload = getattr(turn.raw_tool_result, "output_payload", None)
            elif turn.tool_result is not None:
                tool_result_payload = getattr(turn.tool_result, "normalized_output", None)
            context = {
                "raw_query": turn.raw_query,
                "query_text": turn.raw_query,
                "client_context": dict(state["runtime"].client_context),
                "shop_id": state["persistent"].selected_shop_id,
                "shop_name": state["persistent"].current_shop or state["persistent"].selected_shop_name,
                "current_shop": state["persistent"].current_shop,
                "selected_shop_id": state["persistent"].selected_shop_id,
                "selected_shop_name": state["persistent"].selected_shop_name,
                "city": state["persistent"].current_city,
                "current_city": state["persistent"].current_city,
                "area": state["persistent"].current_location.get("area") if isinstance(state["persistent"].current_location, Mapping) else None,
                "current_area": state["persistent"].current_location.get("area") if isinstance(state["persistent"].current_location, Mapping) else None,
                "category": turn.slots.get("category") if isinstance(turn.slots, Mapping) else None,
                "current_category": turn.slots.get("category") if isinstance(turn.slots, Mapping) else None,
                "tool_result_present": bool(turn.tool_result is not None),
                "has_tool_result": bool(turn.tool_result is not None),
                "tool_result_payload": dict(tool_result_payload or {}) if isinstance(tool_result_payload, Mapping) else tool_result_payload,
                "missing_slots": list(routing.missing_slots) if routing is not None else [],
                "clarification_slot": routing.missing_slots[0] if routing is not None and routing.missing_slots else None,
                "required_facets": list((routing.extra or {}).get("required_facets") or []) if routing is not None else [],
                "optional_facets": list((routing.extra or {}).get("optional_facets") or []) if routing is not None else [],
                "required_facets_source_constraints": dict((routing.extra or {}).get("required_facets_source_constraints") or {})
                if routing is not None and isinstance((routing.extra or {}).get("required_facets_source_constraints"), Mapping)
                else (routing.extra or {}).get("required_facets_source_constraints")
                if routing is not None
                else {},
                "user_need": (routing.extra or {}).get("user_need") if routing is not None else None,
                "tool_candidates": list(routing.tool_candidates) if routing is not None else [],
                "routing_action": str(routing.required_action).strip().lower() if routing is not None else None,
                "retrieval_plan_missing": bool(turn.retrieval_plan is None),
                "tool_plan_missing": bool(turn.tool_plan is None or not getattr(turn.tool_plan, "tool_name", None)),
                "tool_slot_missing": bool(routing is not None and routing.missing_slots),
                "tool_not_allowed": bool(routing is not None and not routing.should_call_tool),
                "retrieval_not_allowed": bool(routing is not None and not routing.should_retrieve),
                "rag_gate_blocked": bool(not eligibility.allowed),
                "evidence_after_gate_count": len(result.items or []),
            }
            evidence_quality = build_evidence_quality(
                result,
                intent_name=(routing.intent.name if routing is not None else None),
                context=context,
            )
            if not evidence_quality.is_valid:
                degraded_status = "WEAK" if getattr(result, "items", None) else "EMPTY"
                result = result.model_copy(
                    update={
                        "evidence_status": degraded_status,
                        "extra": {
                            **dict(getattr(result, "extra", {}) or {}),
                            "evidence_quality_gate": evidence_quality.model_dump(mode="json"),
                        },
                    }
                )
            turn_extra = dict(turn.extra)
            turn_extra = _apply_phase1_routing_extra(turn_extra, routing)
            turn_extra["evidence_quality"] = evidence_quality.model_dump(mode="json")
            turn_extra["entity_consistency_minimal"] = evidence_quality.details.get("entity_consistency_minimal") if isinstance(evidence_quality.details, Mapping) else None
            if routing is not None:
                routing = routing.model_copy(update={"evidence_quality": evidence_quality})
                turn_extra["routing_decision"] = routing.model_dump(mode="json")
                turn_extra["routing_trace"] = routing_trace_payload(routing)
            state["turn"] = turn.model_copy(
                update={
                    "evidence_pack": result,
                    "evidence_quality": evidence_quality,
                    "routing_decision": routing,
                    "extra": turn_extra,
                }
            )
            state = _update_phase0_trace(
                state,
                evidence_quality=evidence_quality.model_dump(mode="json"),
            )
            state = _update_phase1_trace(
                state,
                evidence_quality=evidence_quality.model_dump(mode="json"),
                entity_consistency_minimal=evidence_quality.details.get("entity_consistency_minimal") if isinstance(evidence_quality.details, Mapping) else None,
                route_review_decision=turn_extra.get("route_review_decision"),
            )
            state = _update_phase2_trace(
                state,
                **_build_phase2_trace(
                    state["turn"],
                    routing,
                    evidence_quality,
                    rag_gate_blocked=bool(not eligibility.allowed),
                    evidence_after_gate_count=len(result.items or []),
                ),
            )
            return state
    
        def citation_builder(self, state: GraphState) -> GraphState:
            rag_orchestrator = getattr(self.container, "rag_orchestrator", None)
            turn = state["turn"]
            eligibility = can_enter_retrieval(state)
            if rag_orchestrator is None or not hasattr(rag_orchestrator, "build_citations") or turn.evidence_pack is None or not eligibility.allowed:
                return state
    
            citations = list(rag_orchestrator.build_citations(CitationBuildRequest(evidence_pack=turn.evidence_pack)))
            state["turn"] = turn.model_copy(update={"citations": citations})
            return state
    
        def tool_planner(self, state: GraphState) -> GraphState:
            planner = getattr(self.container, "tool_planner", None)
            if planner is None or not hasattr(planner, "plan"):
                return state
    
            turn = state["turn"]
            routing = _routing_decision_for_turn(turn)
            if routing is not None and not routing.should_call_tool:
                return state
            state = ensure_tool_plan(state)
            turn = state["turn"]
            routing = _routing_decision_for_turn(turn)
            selection = turn.tool_plan
            if selection is not None and getattr(selection, "should_execute", False) and getattr(selection, "tool_name", None):
                selection_extra = dict(getattr(selection, "extra", {}) or {})
                turn_extra = dict(turn.extra)
                turn_extra["tool_planner"] = {
                    "decision": routing.required_action if routing is not None else "no_op",
                    "intent": turn.intent.value if turn.intent else None,
                    "resolved_intent": selection_extra.get("resolved_intent"),
                    "tool_name": selection.tool_name if selection else None,
                    "should_execute": bool(getattr(selection, "should_execute", False)),
                    "approval_required": bool(getattr(selection, "approval_required", False)),
                    "approval_status": getattr(selection, "approval_status", None) if selection is not None else None,
                    "reason": getattr(selection, "reason", None) if selection is not None else None,
                    "planning_state": selection_extra.get("planning_state"),
                    "selection_source": selection_extra.get("selection_source"),
                    "tool_call_id": selection_extra.get("tool_call_id"),
                }
                if routing is not None:
                    turn_extra["routing_decision"] = routing.model_dump(mode="json")
                    turn_extra["routing_trace"] = routing_trace_payload(routing)
                state["turn"] = turn.model_copy(update={"tool_plan": selection, "extra": turn_extra})
                return state
            selection = planner.plan(
                ToolPlanningRequest(
                    raw_query=turn.raw_query,
                    decision=(routing.required_action if routing is not None else "no_op"),
                    routing_decision=routing,
                    intent=turn.intent,
                    slots=dict(turn.slots),
                    current_topic=state["persistent"].current_topic,
                )
            )
            selection_extra = dict(getattr(selection, "extra", {}) or {})
            turn_extra = dict(turn.extra)
            turn_extra["tool_planner"] = {
                "decision": routing.required_action if routing is not None else "no_op",
                "intent": turn.intent.value if turn.intent else None,
                "resolved_intent": selection_extra.get("resolved_intent"),
                "tool_name": selection.tool_name if selection else None,
                "should_execute": bool(getattr(selection, "should_execute", False)),
                "approval_required": bool(getattr(selection, "approval_required", False)),
                "approval_status": getattr(selection, "approval_status", None) if selection is not None else None,
                "reason": getattr(selection, "reason", None) if selection is not None else None,
                "planning_state": selection_extra.get("planning_state"),
                "selection_source": selection_extra.get("selection_source"),
                "tool_call_id": selection_extra.get("tool_call_id"),
            }
            if routing is not None:
                turn_extra["routing_decision"] = routing.model_dump(mode="json")
                turn_extra["routing_trace"] = routing_trace_payload(routing)
            state["turn"] = turn.model_copy(update={"tool_plan": selection, "extra": turn_extra})
            return state
    
        def tool_executor(self, state: GraphState) -> GraphState:
            executor = getattr(self.container, "tool_executor", None)
            turn = state["turn"]
            if executor is None or not hasattr(executor, "execute") or turn.tool_plan is None:
                return state
            result = executor.execute(ToolExecutionCommand(selection=turn.tool_plan))
            turn_extra = dict(turn.extra)
            turn_extra["tool_executor"] = {
                "tool_name": result.tool_name,
                "status": str(getattr(getattr(result, "status", None), "value", getattr(result, "status", ""))),
                "approval_required": bool(getattr(result, "approval_required", False)),
                "approval_status": getattr(result, "approval_status", None),
                "degraded": bool(getattr(result, "degraded", False)),
                "error_code": getattr(result, "error_code", None),
                "degrade_to": getattr(result, "degrade_to", None),
                "duration_ms": getattr(result, "duration_ms", 0),
            }
            state["turn"] = turn.model_copy(update={"raw_tool_result": result, "extra": turn_extra})
            return state
    
        def tool_result_normalizer(self, state: GraphState) -> GraphState:
            normalizer = getattr(self.container, "tool_result_normalizer", None)
            turn = state["turn"]
            if normalizer is None or not hasattr(normalizer, "normalize") or turn.raw_tool_result is None:
                return state
            result = normalizer.normalize(ToolNormalizationRequest(result=turn.raw_tool_result))
            turn_extra = dict(turn.extra)
            turn_extra["tool_result_normalizer"] = {
                "tool_name": result.tool_name,
                "status": str(getattr(getattr(result, "status", None), "value", getattr(result, "status", ""))),
                "approval_required": bool(getattr(result, "approval_required", False)),
                "approval_status": getattr(result, "approval_status", None),
                "degraded": bool(getattr(result, "degraded", False)),
                "retryable": bool(getattr(result, "retryable", False)),
                "degrade_to": getattr(result, "degrade_to", None),
                "failure_category": getattr(result, "extra", {}).get("failure_category"),
                "retry_reason": getattr(result, "extra", {}).get("retry_reason"),
            }
            if bool(getattr(result, "retryable", False)) and turn_extra.get("review_report") is None:
                turn_extra["review_report"] = ReviewReport(
                    decision="retry_tool",
                    reason=str(getattr(result, "extra", {}).get("retry_reason") or getattr(result, "extra", {}).get("failure_category") or "retryable_tool_failure"),
                    retry_target=str(result.tool_name or ""),
                    retry_count=0,
                    max_retry_count=1,
                    extra={
                        "retry_origin": "tool",
                        "failure_category": getattr(result, "extra", {}).get("failure_category"),
                        "retryable": True,
                    },
                )
            state["turn"] = turn.model_copy(update={"tool_result": result, "extra": turn_extra})
            return state
