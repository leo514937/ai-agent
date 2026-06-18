from typing import Any
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

from learning_agent_service.application.evidence_gate import EvidenceGateRequest
from .helpers import routing_trace_payload, _update_phase0_trace
from .helpers import _build_facet_routing_decision
from .helpers import apply_fast_decision_to_routing
from learning_agent_service.application.routing_utils import build_rewrite_decision
from .helpers import _apply_route_review
from .helpers import ensure_task_plan
from .helpers import ensure_retrieval_plan
from .helpers import ensure_tool_plan
from learning_agent_service.application.routing_primitives import _mark_routing_blocked, _pending_clarification_matches_query
from learning_agent_service.domain.contracts import ChatTurnCommand, FastDecision, ReferenceResolutionRequest, TurnUnderstandingRequest
from learning_agent_service.domain.enums import TurnDecision
from learning_agent_service.local_life.entity_resolver import _explicit_entity_from_query
from learning_agent_service.local_life.query_rewriter import normalize_query as normalize_local_life_query

from .helpers import Any, GraphState, IntentType, Mapping, _append_stage_metric, _apply_phase1_routing_extra, _build_cached_evidence_gate, _build_raw_retrieval_plan, _cached_evidence_gate, _CLASSIFY_TIMEOUT_SECONDS, _coerce_reference_resolution, _coerce_retrieval_plan, _copy_state, _log_routing_decision, _mark_degrade, _response_kind_for_turn, _restore_pending_clarification_from_result, _routing_decision_for_turn, _store_routing_decision


class WorkflowNodeAdapterStagesFrontAMixin:
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
        def load_context(self, state: GraphState) -> GraphState:
            # 1. 拷贝状态并提取上下文，判断是否有处于等待澄清（pending clarification）的状态
            state = _copy_state(state)
            turn = state["turn"]
            persistent = state["persistent"]
            had_pending_clarification = getattr(persistent, "pending_clarification", None) is not None
            persistent, turn = _restore_pending_clarification_from_result(
                runtime=state["runtime"],
                turn=turn,
                persistent=persistent,
            )
            state["persistent"] = persistent
            state["turn"] = turn

            # 2. 从客户端上下文（如小程序传来的页面参数）中提取当前的店铺信息，并更新到长期记忆（persistent）
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

            # 3. 尝试从用户 query 中直接提取显式的实体（如直接提到某个店名），如果提取到了也更新到上下文中
            explicit_query_shop = _explicit_entity_from_query(turn.raw_query)
            if explicit_query_shop:
                turn_extra = dict(turn.extra)
                if not str(turn_extra.get("current_shop") or "").strip():
                    turn_extra["current_shop"] = explicit_query_shop
                if not str(turn_extra.get("selected_shop_name") or "").strip():
                    turn_extra["selected_shop_name"] = explicit_query_shop
                if not str(turn_extra.get("explicit_query_shop") or "").strip():
                    turn_extra["explicit_query_shop"] = explicit_query_shop
                if not str(getattr(persistent, "current_shop", "") or "").strip():
                    persistent = persistent.model_copy(update={"current_shop": explicit_query_shop})
                    state["persistent"] = persistent
                if not str(getattr(persistent, "selected_shop_name", "") or "").strip():
                    persistent = persistent.model_copy(update={"selected_shop_name": explicit_query_shop})
                    state["persistent"] = persistent
                turn = turn.model_copy(update={"extra": turn_extra})
                state["turn"] = turn

            # 4. 根据当前 Query 和历史上下文，构建一个初始的路由决策（Routing Decision）
            routing = _build_facet_routing_decision(
                turn.raw_query,
                persistent,
                client_context=state["runtime"].client_context,
            )
            routing = _apply_route_review(
                routing,
                raw_query=turn.raw_query,
                persistent=persistent,
                client_context=state["runtime"].client_context,
            )
            turn = _store_routing_decision(turn, routing)

            # 4.5 RoutingPolicyValidator: 初始路由校验（规则层 final gate）
            try:
                from learning_agent_service.application.routing_policy_validator import RoutingPolicyValidator
                validated = RoutingPolicyValidator().validate(
                    routing,
                    resolved_shop=getattr(getattr(state.get("runtime"), "extra", {}), "resolved_shop", None),
                )
                if validated is not routing:
                    routing = validated
                    turn = _store_routing_decision(turn, routing)
            except Exception:
                pass  # Validator failure should not crash the pipeline

            # 5. 如果之前有等待用户回答的澄清问题（pending clarification），检查当前 Query 是否匹配了澄清选项
            pending_match = getattr(persistent, "pending_clarification", None) is not None
            if pending_match:
                if had_pending_clarification:
                    state = self.consume_pending_clarification(state)
                    turn = state["turn"]
                    persistent = state["persistent"]
                    routing = _routing_decision_for_turn(turn)
                else:
                    pending_restore = dict(dict(turn.extra).get("pending_clarification_restore") or {})
                    original_query = str(
                        pending_restore.get("original_query")
                        or getattr(persistent, "clarification_result", {}).get("original_query")
                        or ""
                    ).strip()
                    original_route = str(
                        pending_restore.get("original_route")
                        or getattr(persistent, "clarification_result", {}).get("original_route")
                        or "rag_retrieval"
                    ).strip() or "rag_retrieval"
                    routing = _build_facet_routing_decision(
                        original_query or turn.raw_query,
                        persistent,
                        client_context=state["runtime"].client_context,
                    )
                    routing = _apply_route_review(
                        routing,
                        raw_query=original_query or turn.raw_query,
                        persistent=persistent,
                        client_context=state["runtime"].client_context,
                    )
                    routing = routing.model_copy(
                        update={
                            "required_action": original_route,
                            "should_retrieve": True,
                            "blocked": False,
                            "blocked_reason": None,
                        }
                    )
                    turn_extra = dict(turn.extra)
                    turn_extra["routing_decision"] = routing.model_dump(mode="json")
                    turn_extra["routing_trace"] = routing_trace_payload(routing)
                    turn_extra["pending_clarification_restore"] = {
                        "original_query": original_query,
                        "original_intent": str(
                            pending_restore.get("original_intent")
                            or getattr(persistent, "clarification_result", {}).get("original_intent")
                            or "local_life_recommend"
                        ).strip() or "local_life_recommend",
                        "original_route": original_route,
                    }
                    turn = turn.model_copy(update={"routing_decision": routing, "extra": turn_extra})
                    state["turn"] = turn

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
                    harness_mode=str((state.get("runtime_context", {}) or {}).get("harness_mode") or (state["runtime"].extra or {}).get("harness_mode") or "off"),
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

            # 7. 调用 RAG 门禁（Rag Gate）进行预检（Precheck），判断当前查询是否适合触发 RAG 检索
            gate = getattr(self.container, "rag_route_gate", None)
            if gate is not None and hasattr(gate, "precheck"):
                request = EvidenceGateRequest(
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
                if pending_match:
                    cached_vote["reason"] = "pending_clarification"
                    cached_vote["response_kind"] = "pending_clarification"
                    cached_vote["final_vote"] = "allow"
                turn_extra = dict(turn.extra)
                turn_extra["evidence_gate"] = {
                    **dict(turn_extra.get("evidence_gate", {})),
                    "precheck_vote": vote.vote,
                    "precheck_reason": "pending_clarification" if pending_match else vote.reason,
                    "precheck_response_kind": "pending_clarification" if pending_match else vote.response_kind,
                }
                turn_extra["rag_gate"] = turn_extra["evidence_gate"]
                turn_extra["cached_evidence_gate_vote"] = cached_vote
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
                harness_mode=str((state.get("runtime_context", {}) or {}).get("harness_mode") or (state["runtime"].extra or {}).get("harness_mode") or "off"),
                initial_routing_decision=routing.model_dump(mode="json"),
                initial_route_reason=routing.route_reason,
                initial_route_candidate=routing.route_candidate,
                initial_required_action=routing.required_action,
                retrieval_plan_status="not_attempted",
                retrieval_plan_failure_reason=None,
                tool_plan_status="not_attempted",
                tool_plan_failure_reason=None,
            )

            # 8. 如果路由策略允许使用历史记忆（Should Use Memory），则调用记忆编排器进行相关的记忆检索和注入
            memory_retrieval_summary = {
                "attempted": False,
                "status": "skipped",
                "reason": "routing_disallowed",
                "retrieved_count": 0,
                "injected_count": 0,
            }
            if routing.should_use_memory:
                memory_orchestrator = getattr(self.container, "memory_orchestrator", None)
                if (
                    memory_orchestrator is not None
                    and hasattr(memory_orchestrator, "retrieve_for_state")
                    and hasattr(memory_orchestrator, "build_injection_plan")
                    and hasattr(memory_orchestrator, "attach_to_state")
                ):
                    try:
                        memory_retrieval_summary["attempted"] = True
                        pack = memory_orchestrator.retrieve_for_state(state)
                        injection = memory_orchestrator.build_injection_plan(pack)
                        state = memory_orchestrator.attach_to_state(state, pack, injection)
                        memory_retrieval_summary.update(
                            {
                                "status": "retrieved",
                                "reason": getattr(pack, "retrieval_reason", None) or "retrieved",
                                "retrieved_count": len(list(getattr(pack, "source_memory_ids", []) or [])),
                                "injected_count": len(
                                    list(getattr(injection, "prompt_memories", []) or [])
                                    + list(getattr(injection, "state_memories", []) or [])
                                    + list(getattr(injection, "tool_memories", []) or [])
                                    + list(getattr(injection, "semantic_memories", []) or [])
                                    + list(getattr(injection, "episodic_memories", []) or [])
                                    + list(getattr(injection, "procedural_memories", []) or [])
                                    + list(getattr(injection, "rag_memories", []) or [])
                                ),
                            }
                        )
                    except Exception as exc:  # pragma: no cover - defensive fallback
                        memory_retrieval_summary.update(
                            {
                                "attempted": True,
                                "status": "failed",
                                "reason": str(exc) or "memory_retrieval_failed",
                            }
                        )
                else:
                    memory_retrieval_summary.update(
                        {
                            "attempted": True,
                            "status": "unavailable",
                            "reason": "memory_orchestrator_unavailable",
                        }
                    )
            runtime = state["runtime"]
            metrics = dict(runtime.metrics)
            metrics.update(
                {
                    "memory_retrieval_attempted": bool(memory_retrieval_summary["attempted"]),
                    "memory_retrieval_status": memory_retrieval_summary["status"],
                    "memory_retrieval_reason": memory_retrieval_summary["reason"],
                    "memory_retrieval_skipped": not routing.should_use_memory,
                    "memory_retrieved_count": memory_retrieval_summary["retrieved_count"],
                    "memory_injected_count": memory_retrieval_summary["injected_count"],
                }
            )
            state["runtime"] = runtime.model_copy(update={"metrics": metrics})
            turn_extra = dict(state["turn"].extra)
            turn_extra["memory_retrieval"] = memory_retrieval_summary
            state["turn"] = state["turn"].model_copy(update={"extra": turn_extra})
            _log_routing_decision(state, stage="load_context")
            return state

        def consume_pending_clarification(self, state: GraphState) -> GraphState:
            # 消费并解析用户的澄清回答（例如用户刚才选择了具体的城市或店铺）
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
                    location_result = normalize_local_life_query(  # noqa: F821
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
                if not city:
                    options = list(getattr(pending, "options", []) or [])
                    for option in options:
                        option_value = str(getattr(option, "value", "") or getattr(option, "label", "") or getattr(option, "description", "") or "").strip()
                        if option_value:
                            city = option_value
                            location_value = {"city": city}
                            restored_persistent["current_city"] = city
                            restored_persistent["current_location"] = location_value
                            break

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
            routing = _build_facet_routing_decision(
                original_query,
                routing_context,
                client_context=runtime.client_context,
            )
            routing = _apply_route_review(
                routing,
                raw_query=original_query,
                persistent=routing_context,
                client_context=runtime.client_context,
            )
            if original_route:
                routing = routing.model_copy(
                    update={
                        "required_action": original_route,
                        "blocked": False,
                        "blocked_reason": None,
                    }
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
            return state
            state = _update_phase0_trace(
                state,
                conversation_recap=True,
                direct_response_kind="conversation_recap",
                current_shop=state["persistent"].current_shop or state["persistent"].selected_shop_name,
            )
            _log_routing_decision(state, stage="conversation_recap_direct_response")
            return state

        def parse_intent_slots(self, state: GraphState) -> GraphState:
            # 这里是模型分类节点，调用 model_gateway.classify_turn 做意图与槽位解析，不是纯规则分支。
            model_gateway = getattr(self.container, "model_gateway", None)
            if model_gateway is None or not hasattr(model_gateway, "classify_turn"):
                return state

            turn = state["turn"]
            persistent = state["persistent"]
            routing = _routing_decision_for_turn(turn)
            allow_plan_execute = str(getattr(turn, "execution_mode", "") or "").strip().lower() == "plan_execute"
            pending_match = getattr(persistent, "pending_clarification", None) is not None
            if pending_match:
                pending_restore = dict(dict(turn.extra).get("pending_clarification_restore") or {})
                original_query = str(
                    pending_restore.get("original_query")
                    or getattr(persistent, "clarification_result", {}).get("original_query")
                    or ""
                ).strip()
                original_route = str(
                    pending_restore.get("original_route")
                    or getattr(persistent, "clarification_result", {}).get("original_route")
                    or "rag_retrieval"
                ).strip() or "rag_retrieval"
                restored_persistent: dict[str, Any] = {}
                if original_query:
                    if str(getattr(persistent, "current_topic", "") or "").strip() != original_query:
                        restored_persistent["current_topic"] = original_query
                    if str(getattr(persistent, "last_retrieval_topic", "") or "").strip() != original_query:
                        restored_persistent["last_retrieval_topic"] = original_query

                ambiguity_type = str(getattr(persistent.pending_clarification, "ambiguity_type", "") or "").strip().lower()
                if ambiguity_type in {"location", "city", "area", "district", "region"}:
                    try:
                        location_result = normalize_local_life_query(  # noqa: F821
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
                routing = _build_facet_routing_decision(
                    original_query or turn.raw_query,
                    state["persistent"],
                    client_context=state["runtime"].client_context,
                )
                routing = _apply_route_review(
                    routing,
                    raw_query=original_query or turn.raw_query,
                    persistent=state["persistent"],
                    client_context=state["runtime"].client_context,
                )
                routing = routing.model_copy(
                    update={
                        "required_action": original_route,
                        "blocked": False,
                        "blocked_reason": None,
                    }
                )
                turn_extra = dict(turn.extra)
                turn_extra["routing_decision"] = routing.model_dump(mode="json")
                turn_extra["routing_trace"] = routing_trace_payload(routing)
                state["turn"] = turn.model_copy(update={"routing_decision": routing, "extra": turn_extra})
                return state
            if routing is not None and not allow_plan_execute and (routing.blocked or routing.required_action in {"clarify", "reject", "direct_answer", "memory_update", "no_op"}):
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
                # 这里是真正的模型/LLM 分类请求；如果超时或异常，再回退到规则/启发式兜底。
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

            # 将 FastDecision 规范化，补充默认值，并将一些快捷决策转化为具体的行为标识
            decision_result = result
            if not isinstance(result, FastDecision):
                decision_result = FastDecision(
                    intent=getattr(result, "intent", IntentType.EXPLAIN),
                    # needs_rag 表示该意图是否需要进行知识库或店铺检索
                    needs_rag=bool(
                        getattr(result, "required_action", None) in {"rag_retrieval", "rag_plus_tool"}
                        or getattr(result, "retrieval_plan", None) is not None
                    ),
                    # needs_tool 表示该意图是否需要调用工具API（如查询价格等）
                    needs_tool=bool(getattr(result, "required_action", None) in {"tool_call", "rag_plus_tool"}),
                    # needs_clarify 表示用户的意图不清晰，必须向用户进行追问或澄清
                    needs_clarify=bool(getattr(result, "required_action", None) == "clarify"),
                    # needs_query_rewrite 表示原始 query 需要被重写才能更好地给检索引擎用
                    needs_query_rewrite=bool(getattr(result, "needs_query_rewrite", False)),
                    # 意图识别模型的置信度（0.0 到 1.0）
                    confidence=float(getattr(result, "intent_confidence", getattr(result, "confidence", 0.0)) or 0.0),
                    # 识别出的核心槽位信息（例如：地点、菜系、商圈）
                    key_slots=dict(getattr(result, "slots", {}) or {}),
                    extra=dict(getattr(result, "extra", {}) or {}),
                )

            # 合并意图分类器返回的额外上下文（semantic_context）
            turn_extra = {**dict(turn.extra), **dict(getattr(result, "extra", {}) or {})}
            turn_extra["needs_query_rewrite"] = bool(getattr(decision_result, "needs_query_rewrite", False))
            semantic_context = turn_extra.get("semantic_context")

            # 解析语义上下文，如果是继承或对比场景，需要把实体信息塞入持久化长期记忆中（persistent updates）
            if isinstance(semantic_context, Mapping):
                persistent_updates: dict[str, Any] = {}
                anchor = semantic_context.get("anchor_shop")
                if isinstance(anchor, Mapping):
                    anchor_payload = {k: v for k, v in dict(anchor).items() if v not in (None, "", [], {}, ())}
                    if anchor_payload:
                        persistent_updates["current_shop_anchor"] = anchor_payload
                        anchor_name = str(anchor_payload.get("name") or anchor_payload.get("shop_name") or "").strip()
                        anchor_id = anchor_payload.get("shop_id") or anchor_payload.get("id")
                        if anchor_name and not getattr(state["persistent"], "current_shop", None):
                            persistent_updates.setdefault("current_shop", anchor_name)
                        if anchor_id not in (None, "") and not getattr(state["persistent"], "selected_shop_id", None):
                            persistent_updates.setdefault("selected_shop_id", anchor_id)
                inherited_constraints = semantic_context.get("inherited_constraints")
                if isinstance(inherited_constraints, Mapping) and inherited_constraints:
                    merged_constraints = dict(getattr(state["persistent"], "current_constraints", {}) or {})
                    merged_constraints.update({k: v for k, v in dict(inherited_constraints).items() if v not in (None, "", [], {}, ())})
                    persistent_updates["current_constraints"] = merged_constraints
                    if merged_constraints.get("scene") and not getattr(state["persistent"], "current_scene", None):
                        persistent_updates["current_scene"] = str(merged_constraints.get("scene"))
                comparison_targets = semantic_context.get("comparison_targets")
                if isinstance(comparison_targets, list):
                    target_names = [
                        str(item.get("name") or item.get("shop_name") or item.get("target") or "").strip()
                        for item in comparison_targets
                        if isinstance(item, Mapping)
                    ]
                    target_names = [name for name in target_names if name]
                    if target_names:
                        persistent_updates["dialog_comparison_targets"] = list(dict.fromkeys(target_names))
                follow_up_kind = str(semantic_context.get("follow_up_kind") or "").strip()
                promoted_intent = str(semantic_context.get("promoted_intent") or "").strip()
                if follow_up_kind:
                    if follow_up_kind == "comparison_completion":
                        persistent_updates["dialog_state"] = "comparing"
                        persistent_updates["dialog_task"] = "comparison"
                        persistent_updates["dialog_intent"] = promoted_intent or "compare"
                    elif follow_up_kind in {"intent_ellipsis", "constraint_inheritance"}:
                        persistent_updates["dialog_state"] = "follow_up"
                        persistent_updates["dialog_task"] = "recommendation"
                        persistent_updates["dialog_intent"] = promoted_intent or "recommend"
                    elif follow_up_kind == "entity_reference":
                        persistent_updates["dialog_state"] = "follow_up"
                        persistent_updates["dialog_task"] = "detail"
                        persistent_updates["dialog_intent"] = promoted_intent or "detail"
                if persistent_updates:
                    state["persistent"] = state["persistent"].model_copy(update=persistent_updates)

            # 尝试从分类器中提取“指代消解（Reference Resolution）”的结果并强制类型化
            reference_resolution = _coerce_reference_resolution(
                getattr(result, "reference_resolution", None)
                or turn_extra.get("reference_resolution")
                or turn_extra.get("cached_reference_resolution")
            )

            # 尝试提取已经生成的检索计划（Retrieval Plan）
            retrieval_plan = _coerce_retrieval_plan(
                getattr(result, "retrieval_plan", None)
                or turn_extra.get("retrieval_plan")
                or turn_extra.get("cached_retrieval_plan")
            )

            # 如果需要走RAG但没有检索计划，则构造一个基础的原始检索计划
            if retrieval_plan is None and decision_result.needs_rag:
                retrieval_plan = _build_raw_retrieval_plan(turn)

            if reference_resolution is not None:
                turn_extra["cached_reference_resolution"] = reference_resolution.model_dump(mode="json")
            if retrieval_plan is not None:
                turn_extra["cached_retrieval_plan"] = retrieval_plan.model_dump(mode="json")

            # 基于上述所有信息，更新最终的路由决策（Routing Decision）
            routing = routing or _build_facet_routing_decision(turn.raw_query, state["persistent"], client_context=runtime.client_context)
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
            # RoutingPolicyValidator: 最终路由校验（规则层 final gate）
            try:
                from learning_agent_service.application.routing_policy_validator import RoutingPolicyValidator
                validated = RoutingPolicyValidator().validate(
                    routing,
                    resolved_shop=getattr(getattr(state.get("runtime"), "extra", {}), "resolved_shop", None),
                )
                if validated is not routing:
                    routing = validated
            except Exception:
                pass  # Validator failure should not crash the pipeline
            rewrite_decision = None
            if retrieval_plan is not None:
                # 如果有检索计划，则一并生成 Query Rewrite 的结果和决策。
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

            # 生成或者复用 Rag Gate 允许进入后续检索/工具链的门禁状态
            existing_gate = turn_extra.get("evidence_gate")
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
                computed_gate = _build_cached_evidence_gate(
                    required_action,
                    decision_result.intent,
                    decision_result.confidence,
                    turn_extra,
                    slots=dict(getattr(decision_result, "key_slots", {}) or {}),
                )
                existing_gate = {**existing_gate, **computed_gate}
            turn_extra = _apply_phase1_routing_extra(turn_extra, routing)
            turn_extra["evidence_gate"] = existing_gate
            turn_extra["rag_gate"] = existing_gate
            turn_extra["cached_evidence_gate_vote"] = dict(existing_gate)
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

            # 如果识别出路由被拦截，且动作为澄清（Clarify），则在此处构造澄清相关的对话状态并写入
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
            task_plan = getattr(state["turn"], "task_plan", None)
            if (
                getattr(state["turn"], "execution_mode", "") == "plan_execute"
                and task_plan is not None
                and getattr(task_plan, "enabled", False)
                and hasattr(self, "plan_planner")
            ):
                state = self.plan_planner(state)
                state = self.plan_validator(state)
                for _ in range(2):
                    state = self.step_executor(state)
                    state = self.progress_checker(state)
                    state = self.plan_reviewer(state)
                    if getattr(state["turn"], "need_human_approval", False):
                        if hasattr(self, "human_approval_stub"):
                            state = self.human_approval_stub(state)
                        break
                    if not getattr(state["turn"], "need_replan", False):
                        break
                    state = self.replanner(state)
                    state = self.plan_validator(state)
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
            # 这里走的是实体消歧能力，通常会调用检索/消歧服务，不是纯规则字符串匹配。
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
            # 这里是规则节点，基于置信度、信息残缺和路由状态做歧义判断与澄清信号补写。
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

        def evidence_gate(self, state: GraphState) -> GraphState:
            # RAG 门禁：enable_rag=false 时直接短路，不进入任何检索相关执行。
            settings = getattr(self.container, "settings", None)
            if settings is not None and not bool(getattr(settings, "enable_rag", True)):
                return state

            gate = getattr(self.container, "rag_route_gate", None)
            if gate is None or not hasattr(gate, "precheck"):
                return state

            turn = state["turn"]
            persistent = state["persistent"]
            routing = _routing_decision_for_turn(turn)
            turn_extra = dict(turn.extra)
            pending_match = getattr(persistent, "pending_clarification", None) is not None

            if routing is not None and not routing.should_retrieve:
                response_kind = _response_kind_for_turn(turn) or "low_info"
                gate_payload = {
                    "allowed": False,
                    "reason": routing.route_reason or routing.required_action,
                    "confidence": routing.input_quality.score,
                    "response_kind": response_kind,
                    "precheck_skip_memory": True,
                    "final_vote": "deny",
                    "rule_vote": None,
                    "llm_vote": None,
                    "metadata": {"source": "routing_decision"},
                }
                if response_kind in {"low_info", "empty"}:
                    gate_payload["clarification_response_kind"] = response_kind
                    gate_payload["clarification_signal"] = {
                        "kind": response_kind,
                        "reason": routing.route_reason or routing.required_action,
                    }
                turn_extra["evidence_gate"] = gate_payload
                turn_extra["rag_gate"] = gate_payload
                if response_kind in {"low_info", "empty"}:
                    turn_extra["clarification_response_kind"] = response_kind
                    turn_extra["clarification_signal"] = {
                        "kind": response_kind,
                        "reason": routing.route_reason or routing.required_action,
                    }
                    turn = turn.model_copy(update={"decision": TurnDecision.DIRECT_ANSWER})
                turn_extra["route_reason"] = routing.route_reason or turn_extra.get("route_reason")
                if routing.blocked:
                    turn_extra["routing_decision"] = routing.model_dump(mode="json")
                    turn_extra["routing_trace"] = routing_trace_payload(routing)
                state["turn"] = turn.model_copy(update={"extra": turn_extra})
                return state

            cached_gate = _cached_evidence_gate(turn)
            if cached_gate is not None:
                turn_extra["evidence_gate"] = dict(cached_gate)
                turn_extra["rag_gate"] = dict(cached_gate)
                turn_extra["route_reason"] = cached_gate.get("reason", turn_extra.get("route_reason"))
                if not bool(cached_gate.get("allowed", True)):
                    turn_extra["clarification_response_kind"] = cached_gate.get("response_kind")
                    turn_extra["clarification_signal"] = {
                        "kind": cached_gate.get("response_kind"),
                        "reason": cached_gate.get("reason"),
                    }
                    turn_extra["rag_gate"]["clarification_response_kind"] = cached_gate.get("response_kind")
                    turn_extra["rag_gate"]["clarification_signal"] = {
                        "kind": cached_gate.get("response_kind"),
                        "reason": cached_gate.get("reason"),
                    }
                    if routing is not None:
                        blocked_routing = _mark_routing_blocked(
                            routing,
                            reason=str(cached_gate.get("reason") or cached_gate.get("response_kind") or "evidence_gate_blocked"),
                            required_action="clarify" if cached_gate.get("response_kind") != "empty" else "reject",
                            route_candidate=routing.route_candidate,
                        )
                        turn_extra["routing_decision"] = blocked_routing.model_dump(mode="json")
                        turn_extra["routing_trace"] = routing_trace_payload(blocked_routing)
                        state["turn"] = turn.model_copy(update={"routing_decision": blocked_routing, "extra": turn_extra})
                        return state
                state["turn"] = turn.model_copy(update={"extra": turn_extra})
                return state

            request = EvidenceGateRequest(
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
            if pending_match:
                cached_vote["reason"] = "pending_clarification"
                cached_vote["response_kind"] = "pending_clarification"
                cached_vote["final_vote"] = "allow"

            turn_extra["evidence_gate"] = cached_vote
            turn_extra["rag_gate"] = cached_vote
            turn_extra["cached_evidence_gate_vote"] = dict(cached_vote)
            turn_extra["cached_rag_gate_vote"] = dict(cached_vote)
            if not bool(cached_vote.get("allowed", True)):
                turn_extra["clarification_response_kind"] = cached_vote.get("response_kind")
                turn_extra["clarification_signal"] = {
                    "kind": cached_vote.get("response_kind"),
                    "reason": cached_vote.get("reason"),
                }
            turn = turn.model_copy(update={"extra": turn_extra})
            state["turn"] = turn
            return state

        def rag_gate(self, state: GraphState) -> GraphState:
            return self.evidence_gate(state)
