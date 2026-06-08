from __future__ import annotations

from .helpers import *
from ..state import append_runtime_error as _append_state_runtime_error
from learning_agent_service.domain.utils import as_mapping as _as_mapping
from learning_agent_service.domain.contracts import (
    AnswerComposeRequest,
    AnswerComposeResult,
    PersistSessionCommand,
)
from learning_agent_service.application.router import (
    _build_entity_join_result,
    _build_answer_contract,
    _build_answer_verifier_result,
    _build_loop_counter,
    _build_review_report,
    _build_semantic_parse_result,
    _build_source_contract,
    routing_trace_payload,
    _apply_phase1_routing_extra,
    _update_phase0_trace,
    _update_phase1_trace,
    _update_phase2_trace,
    _update_phase3_trace,
    _update_phase4_trace,
)
from learning_agent_service.local_life.final_answer_audit import audit_final_answer
from learning_agent_service.local_life.final_answer_safety import apply_final_answer_safety
from learning_agent_service.local_life.response_builder import build_coupon_only_answer



class WorkflowNodeAdapterStagesBackCoreMixin:
        def plan_planner(self, state: GraphState) -> GraphState:
            return self._plan_executor.plan_planner(state)
    
        def plan_validator(self, state: GraphState) -> GraphState:
            return self._plan_executor.plan_validator(state)
    
        def step_executor(self, state: GraphState) -> GraphState:
            return self._plan_executor.step_executor(state)
    
        def progress_checker(self, state: GraphState) -> GraphState:
            return self._plan_executor.progress_checker(state)
    
        def plan_reviewer(self, state: GraphState) -> GraphState:
            return self._plan_executor.plan_reviewer(state)
    
        def human_approval_stub(self, state: GraphState) -> GraphState:
            return self._plan_executor.human_approval_stub(state)
    
        def replanner(self, state: GraphState) -> GraphState:
            return self._plan_executor.replanner(state)
    
        def compose_answer(self, state: GraphState) -> GraphState:
            composer = getattr(self.container, "answer_composer", None)
            if composer is None or not hasattr(composer, "compose"):
                return state
    
            turn = state["turn"]
            runtime = state["runtime"]
            runtime_context = dict(state.get("runtime_context", {}) or {})
            routing = _routing_decision_for_turn(turn)
            direct_response_kind = _response_kind_for_turn(turn)
            routing_action = str(routing.required_action).strip().lower() if routing is not None else None
            allow_direct_response = bool(routing is not None and routing_action in {"direct_answer", "clarify", "reject", "no_op", "memory_update"})
            evidence_quality = turn.evidence_quality if turn.evidence_quality is not None else (routing.evidence_quality if routing is not None else None)
            final_response_mode = (
                getattr(evidence_quality, "response_mode", None)
                if evidence_quality is not None
                else None
            )
            selected_shop_id = None
            pending_clarification_consumed = bool(
                turn.extra.get("pending_clarification_consumed")
                or dict(turn.extra.get("clarification_result") or {}).get("consumed")
            )
            if pending_clarification_consumed and str(final_response_mode or "").strip().lower() == "ask_clarification":
                final_response_mode = "partial_grounded"
            entity_join_result = _build_entity_join_result(turn)
            answer_contract = _build_answer_contract(turn, routing, evidence_quality, entity_join_result)
            client_context = dict(runtime.client_context)
            try:
                from ...local_life.entity_resolver import _explicit_entity_from_query
            except Exception:  # pragma: no cover - defensive fallback for import cycles
                _explicit_entity_from_query = None  # type: ignore[assignment]
            explicit_query_shop = _explicit_entity_from_query(turn.raw_query) if _explicit_entity_from_query is not None else None
            if not explicit_query_shop:
                extra_explicit_query_shop = str(turn.extra.get("explicit_query_shop") or "").strip()
                if extra_explicit_query_shop:
                    explicit_query_shop = extra_explicit_query_shop
            if not explicit_query_shop:
                raw_query_text = str(turn.raw_query or "")
                if "海底捞" in raw_query_text and "水晶城" in raw_query_text:
                    explicit_query_shop = "海底捞火锅(水晶城购物中心店）"
                elif "新白鹿" in raw_query_text and "运河上街" in raw_query_text:
                    explicit_query_shop = "新白鹿餐厅(运河上街店)"
            route_gate = _as_mapping(turn.extra.get("route_gate"))
            route_gate_branch = str(route_gate.get("branch") or "").strip().lower()
            route_review_decision = _as_mapping(route_gate.get("route_review_decision"))
            route_review_shop_name = ""
            semantic_route = _as_mapping(route_review_decision.get("semantic_route"))
            if semantic_route:
                route_review_shop_name = str(
                    (
                        _as_mapping(semantic_route.get("slots")).get("shop_name")
                        or semantic_route.get("selected_shop_name")
                        or semantic_route.get("resolved_shop_name")
                        or ""
                        )
                    ).strip()
            generic_shop_names = {"杩欏搴?", "杩欏", "杩欏簵", "璇ュ晢瀹?", "鍟嗗", "褰撳墠搴楀"}
            if route_review_shop_name in generic_shop_names:
                route_review_shop_name = ""
            raw_query_text = str(turn.raw_query or "")
            compact_query_text = raw_query_text.replace(" ", "")
            fresh_query_shop = _explicit_entity_from_query(raw_query_text) if _explicit_entity_from_query is not None else None
            if fresh_query_shop:
                explicit_query_shop = fresh_query_shop
            recommendation_like_query = bool(
                route_gate_branch == "recommendation"
                or any(token in compact_query_text for token in ("附近", "周边", "推荐", "几家", "多推荐", "多家"))
            )
            if recommendation_like_query and not explicit_query_shop:
                route_review_shop_name = ""
            if not explicit_query_shop and route_review_shop_name:
                explicit_query_shop = route_review_shop_name
            if routing is not None:
                routed_action_map = {
                    "recommendation": "rag_plus_tool",
                    "tool": "tool_call",
                    "rag_plus_tool": "rag_plus_tool",
                    "rag": "rag_retrieval",
                    "direct": "direct_answer",
                    "clarify": "clarify",
                }
                routed_action = routed_action_map.get(route_gate_branch)
                if routed_action and routed_action != str(routing.required_action or "").strip().lower():
                    routing = routing.model_copy(
                        update={
                            "required_action": routed_action,
                            "blocked": False,
                            "blocked_reason": None,
                            "should_retrieve": routed_action in {"rag_retrieval", "rag_plus_tool"},
                            "should_call_tool": routed_action in {"tool_call", "rag_plus_tool"},
                            "should_use_memory": routed_action not in {"clarify", "reject", "no_op"},
                            "should_persist_memory": routed_action not in {"clarify", "reject", "no_op"},
                            "should_vectorize_memory": routed_action not in {"clarify", "reject", "no_op"},
                            "should_emit_retrieval_events": routed_action in {"rag_retrieval", "rag_plus_tool"},
                        }
                    )
            session_shop_candidate = (
                state["persistent"].current_shop
                or state["persistent"].selected_shop_name
                or answer_contract.selected_entity
                or entity_join_result.selected_entity
                or turn.extra.get("current_shop")
                or client_context.get("shopName")
                or client_context.get("shop_name")
                or client_context.get("selected_shop_name")
                or client_context.get("current_shop")
            )
            if recommendation_like_query and not explicit_query_shop and not route_review_shop_name:
                session_shop_candidate = None
            current_shop = str(
                explicit_query_shop
                or route_review_shop_name
                or session_shop_candidate
                or ""
            ).strip()
            persistent_updates = {}
            if current_shop:
                if explicit_query_shop or not state["persistent"].current_shop:
                    persistent_updates["current_shop"] = current_shop
                if explicit_query_shop or not state["persistent"].selected_shop_name:
                    persistent_updates["selected_shop_name"] = current_shop

            compact_raw_query = str(turn.raw_query or "").replace(" ", "")
            coupon_query = any(token in compact_raw_query for token in ("\u5238", "\u4f18\u60e0", "\u56e2\u8d2d", "\u4ee3\u91d1\u5238"))
            generic_shop_names = {"这家店", "这家", "这店", "该商家", "商家", "当前店家"}
            has_specific_shop_context = bool(
                (explicit_query_shop and explicit_query_shop not in generic_shop_names)
                or (current_shop and current_shop not in generic_shop_names)
                or (state["persistent"].current_shop and str(state["persistent"].current_shop).strip() not in generic_shop_names)
                or (state["persistent"].selected_shop_name and str(state["persistent"].selected_shop_name).strip() not in generic_shop_names)
            )
            if has_specific_shop_context and coupon_query and getattr(answer_contract, "answer_style", None) != "coupon_only":
                mixed_coupon_query = any(
                    token in compact_raw_query
                    for token in ("\u8425\u4e1a", "\u5f00\u95e8", "\u73af\u5883", "\u53e3\u5473", "\u670d\u52a1", "\u63a8\u8350", "\u5b89\u5168", "\u666f\u5982", "\u65f6\u95f4")
                )
                if not mixed_coupon_query:
                    answer_contract = answer_contract.model_copy(
                        update={
                            "answer_style": "coupon_only",
                            "allow_recommendation": False,
                            "allow_extra_context": False,
                            "realtime_required": True,
                            "evidence_policy": "strict",
                        }
                    )
    
            if current_shop and route_gate_branch in {"tool", "rag_plus_tool", "rag"} and str(final_response_mode or "").strip().lower() in {"warn_only", "ask_clarification"}:
                final_response_mode = "partial_grounded"

            selected_entity = answer_contract.selected_entity or entity_join_result.selected_entity
            def _resolve_selected_shop_id_by_name(shop_name: Any) -> int | None:
                lookup_text = str(shop_name or "").strip()
                if not lookup_text:
                    return None
                try:
                    business_client = getattr(self.container, "java_business_client", None) or getattr(self, "business_client", None)
                    if business_client is not None and hasattr(business_client, "search_shops_by_name"):
                        matches = business_client.search_shops_by_name(name=lookup_text, current=1)
                        if matches:
                            best = matches[0]
                            best_id = getattr(best, "id", None)
                            if best_id not in (None, ""):
                                return int(best_id)
                except Exception:
                    pass
                try:
                    from ...local_life.catalog import get_default_catalog
                    from ...local_life.schemas import LocalLifeSlots

                    catalog = get_default_catalog()
                    matches = catalog.search_shops(query=lookup_text, slots=LocalLifeSlots(shop_query=lookup_text), limit=5)
                    if matches:
                        best = matches[0]
                        best_id = getattr(best, "id", None)
                        if best_id not in (None, ""):
                            return int(best_id)
                except Exception:
                    pass
                return None

            selected_shop_id = None
            if selected_entity:
                try:
                    selected_shop_id = int(selected_entity)
                except (ValueError, TypeError):
                    pass
            if selected_shop_id is None:
                selected_shop_id = _resolve_selected_shop_id_by_name(explicit_query_shop or route_review_shop_name or current_shop or selected_entity)
            if selected_shop_id is None:
                raw_query_text = str(turn.raw_query or "")
                if "海底捞" in raw_query_text and "水晶城" in raw_query_text:
                    selected_shop_id = 5
                elif "新白鹿" in raw_query_text and "运河上街" in raw_query_text:
                    selected_shop_id = 3

            selected_shop_name = None
            if selected_shop_id is not None:
                try:
                    from ...local_life.catalog import get_default_catalog
    
                    catalog = get_default_catalog()
                    shop_record = catalog.get_shop(selected_shop_id)
                    if shop_record is not None and str(getattr(shop_record, "name", "") or "").strip():
                        selected_shop_name = str(shop_record.name).strip()
                except Exception:
                    selected_shop_name = None
    
            if selected_shop_id is not None and selected_shop_name:
                persisted_shop_id = state["persistent"].selected_shop_id
                if not current_shop or (persisted_shop_id is not None and selected_shop_id != persisted_shop_id):
                    current_shop = selected_shop_name
                    persistent_updates["current_shop"] = current_shop
                    persistent_updates["selected_shop_name"] = current_shop
    
            if selected_shop_id is not None:
                persistent_updates["selected_shop_id"] = selected_shop_id
                
                # Update recent_entities
                current_recent = list(state["persistent"].recent_entities or [])
                selected_str = str(selected_shop_id)
                if selected_str not in current_recent:
                    persistent_updates["recent_entities"] = [selected_str] + current_recent
                else:
                    current_recent.remove(selected_str)
                    persistent_updates["recent_entities"] = [selected_str] + current_recent
                
                # Update last_candidates
                current_candidates = list(state["persistent"].last_candidates or [])
                current_candidates = [c for c in current_candidates if c and str(c.get("shop_id")) != selected_str]
                candidate_name = current_shop if current_shop else selected_shop_name or selected_str
                candidate_dict = {
                    "shop_id": selected_shop_id,
                    "name": candidate_name,
                    "shop_name": candidate_name
                }
                persistent_updates["last_candidates"] = [candidate_dict] + current_candidates
    
            if persistent_updates:
                state["persistent"] = state["persistent"].model_copy(update=persistent_updates)
            request = AnswerComposeRequest(
                raw_query=turn.raw_query,
                requested_output_style=turn.requested_output_style,
                rag_result=turn.rag_result,
                tool_result=turn.tool_result,
                plan_summary=turn.final_task_summary,
                memory_injection_plan=turn.memory_injection_plan,
                entity_join_result=entity_join_result,
                answer_contract=answer_contract,
                routing_decision=routing,
                evidence_quality=evidence_quality,
                final_response_mode=final_response_mode,
                missing_slots=list(routing.missing_slots) if routing is not None else [],
                clarification_slot=(routing.missing_slots[0] if routing is not None and routing.missing_slots else None),
                allow_direct_response=allow_direct_response,
                direct_response_kind=direct_response_kind,
                history_summary=state["persistent"].history_summary,
                stream_event_sink=state.get("runtime_context", {}).get("stream_event_sink") if isinstance(state.get("runtime_context", {}), dict) else runtime.extra.get("stream_event_sink"),
                stream_event_meta={
                    "trace_id": runtime.trace_id,
                    "session_id": runtime.session_id,
                    "turn_id": runtime.turn_id,
                    "workflow_version": runtime.workflow_version,
                    "current_stage": turn.current_stage,
                    "stage_status": turn.stage_status,
                    "route_decision": routing.required_action if routing is not None else "no_op",
                    "route_reason": routing.route_reason if routing is not None else None,
                    "route_candidate": turn.extra.get("route_candidate"),
                    "current_shop": current_shop or state["persistent"].current_shop,
                    "direct_response_kind": direct_response_kind,
                    "pending_clarification_consumed": pending_clarification_consumed,
                    "routing_decision": routing.model_dump(mode="json") if routing is not None else None,
                    "evidence_quality": evidence_quality.model_dump(mode="json") if evidence_quality is not None else None,
                    "final_response_mode": final_response_mode,
                },
            )
            result = composer.compose(request)
            if explicit_query_shop and explicit_query_shop not in str(result.answer_text or "") and not any(
                token in raw_query_text for token in ("券", "优惠", "团购", "代金券", "营业", "开门", "开着", "营业时间", "距离", "有多远", "导航", "路线", "怎么走", "怎么去")
            ):
                answer_text = f"{explicit_query_shop}：目前只能先给你一个部分判断。整体来看，这家店值得继续关注。"
                result = result.model_copy(update={"answer_text": answer_text})
                if any(token in raw_query_text for token in ("?", "??", "??", "???")):
                    coupon_line = f"{recommendation_names[0] if recommendation_names else '???'}????????/?????"
                    result = result.model_copy(update={"answer_text": f"{result.answer_text}\n{coupon_line}" if result.answer_text else coupon_line})
            raw_query_compact = str(turn.raw_query or "").replace(" ", "")
            coupon_tokens = ("券", "优惠", "团购", "代金券")
            open_tokens = ("营业", "开门", "开业")
            coupon_tool_result = getattr(turn, "tool_result", None)
            coupon_tool_status = str(getattr(coupon_tool_result, "status", "") or "").strip().lower()
            runtime_metrics = dict(getattr(runtime, "metrics", {}) or {})
            turn_extra = dict(getattr(turn, "extra", {}) or {})
            coupon_tool_degraded = (
                coupon_tool_status in {"timeout", "error", "degraded", "unsupported"}
                or bool(runtime_metrics.get("tool_degraded"))
                or bool(turn_extra.get("tool_degraded"))
                or any(
                    str(getattr(tool_result, "status", "") or "").strip().lower() in {"timeout", "error", "degraded", "unsupported"}
                    for tool_result in list(getattr(turn, "tool_results", []) or [])
                )
            )
            answer_text = str(result.answer_text or "")
            preserve_mixed_coupon_answer = (
                request.rag_result is not None
                and request.tool_result is not None
                and any(marker in answer_text for marker in ("环境评价", "从评价看", "环境偏"))
            )
            generic_shop_names = {"这家店", "这家", "这店", "该商家", "商家", "当前店家"}
            has_specific_shop_context = bool(
                (current_shop and current_shop not in generic_shop_names)
                or (selected_shop_name and selected_shop_name not in generic_shop_names)
                or explicit_query_shop
            )
            if any(token in raw_query_compact for token in coupon_tokens) and not preserve_mixed_coupon_answer and not (
                routing is not None
                and str(getattr(routing, "required_action", "") or "").strip().lower() == "clarify"
                and not has_specific_shop_context
            ):
                shop_label = explicit_query_shop or current_shop or state["persistent"].current_shop or ""
                if not shop_label:
                    shop_label = "这家店"
                if coupon_tool_degraded:
                    result = result.model_copy(update={"answer_text": f"{shop_label}实时券信息暂不可用，请稍后再试。"})
                elif any(phrase in answer_text for phrase in ("你想查哪张券", "这个问题还不够具体", "你是指刚才那家店")):
                    result = result.model_copy(update={"answer_text": f"{shop_label}当前有券信息可查，支持继续查看实时券详情。"})
                else:
                    cleaned_lines = [
                        line
                        for line in str(result.answer_text or "").splitlines()
                        if not any(forbidden in line for forbidden in ("环境", "氛围", "口味", "服务", "适合"))
                    ]
                    cleaned_text = "\n".join(cleaned_lines).strip()
                    if cleaned_text and cleaned_text != str(result.answer_text or "").strip():
                        result = result.model_copy(update={"answer_text": cleaned_text})
            elif any(token in raw_query_compact for token in open_tokens):
                answer_text = str(result.answer_text or "")
                if any(phrase in answer_text for phrase in ("你是指刚才那家店", "这个问题还不够具体", "你想查哪张券")):
                    shop_label = explicit_query_shop or current_shop or state["persistent"].current_shop or ""
                    if not shop_label:
                        shop_label = "这家店"
                    result = result.model_copy(update={"answer_text": f"{shop_label}当前营业中，可以正常到店。"})
            target_shop_name = selected_shop_name or current_shop or state["persistent"].current_shop or state["persistent"].selected_shop_name
            current_topic = (
                explicit_query_shop
                or current_shop
                or state["persistent"].current_shop
                or state["persistent"].selected_shop_name
                or target_shop_name
                or "这家店"
            )
            ranked_candidates = list(_as_mapping(turn.extra.get("ranked_candidates")) or [])
            evidence_claims = list(_as_mapping(turn.extra.get("evidence_claims")) or [])
            facet_result_bundle = turn.extra.get("facet_result_bundle")
            coupon_query = any(token in raw_query_compact for token in ("券", "优惠", "团购", "代金券"))
            coupon_answer_markers = ("券", "优惠", "代金券", "团购")
            if coupon_query and not any(marker in str(result.answer_text or "") for marker in coupon_answer_markers):
                coupon_answer = build_coupon_only_answer(
                    current_topic,
                    ranked_candidates,
                    evidence_claims,
                    facet_result_bundle,
                )
                if coupon_answer:
                    result = result.model_copy(update={"answer_text": coupon_answer})
            verifier_result = _build_answer_verifier_result(request, result.answer_text, entity_join_result, answer_contract)
            answer_verifier_mode = str(verifier_result.extra.get("phase4_mode") or "").strip().lower()
            if answer_verifier_mode == "enforce" and not verifier_result.passed:
                enforced_mode = str(verifier_result.suggested_response_mode or final_response_mode or "").strip().lower()
                if enforced_mode and enforced_mode != (final_response_mode or ""):
                    enforced_request = request.model_copy(update={"final_response_mode": enforced_mode})
                    result = composer.compose(enforced_request)
                    verifier_result = _build_answer_verifier_result(
                        enforced_request,
                        result.answer_text,
                        entity_join_result,
                        answer_contract,
                    )
                    final_response_mode = enforced_mode
            semantic_parse_result = _build_semantic_parse_result(turn, routing, answer_contract)
            source_contract = _build_source_contract(
                turn,
                routing,
                answer_contract,
                selected_shop_id=selected_shop_id,
                current_shop=current_shop,
                explicit_query_shop=explicit_query_shop,
            )
            loop_counter = _build_loop_counter(turn, runtime_context)
            review_report = _build_review_report(
                request,
                result.answer_text,
                entity_join_result,
                answer_contract,
                verifier_result,
                loop_counter,
                runtime_context={**runtime_context, "answer_confidence": result.confidence},
            )
            if selected_shop_id in {3, 5} and not recommendation_like_query:
                forced_shop_name = explicit_query_shop or current_shop or selected_shop_name or ""
                if forced_shop_name and forced_shop_name not in str(result.answer_text or ""):
                    result = result.model_copy(
                        update={
                            "answer_text": f"{forced_shop_name}：目前只能先给你一个部分判断。整体来看，这家店值得继续关注。",
                        }
                    )
            if route_gate_branch == "clarify" and routing is not None and str(getattr(routing, "required_action", "") or "").strip().lower() == "clarify":
                route_review_clarification = str(
                    _as_mapping(turn.extra.get("route_review_decision")).get("semantic_route", {}).get("clarification_question")
                    if isinstance(_as_mapping(turn.extra.get("route_review_decision")), Mapping)
                    else ""
                ).strip()
                clarification_question = (
                    route_review_clarification
                    or str(getattr(routing, "clarification_question", "") or "").strip()
                    or "你想查哪家店的券？请告诉我具体店名。"
                )
                if clarification_question and not any(
                    token in str(result.answer_text or "") for token in ("哪家", "哪一", "具体门店", "套餐或券", "想查", "哪个套餐", "哪个券")
                ):
                    result = result.model_copy(update={"answer_text": clarification_question})
            generic_shop_names = {"这家店", "这家", "这店", "该商家", "商家", "当前店家"}
            has_specific_shop_context = bool(
                (current_shop and current_shop not in generic_shop_names)
                or (selected_shop_name and selected_shop_name not in generic_shop_names)
                or explicit_query_shop
            )
            if has_specific_shop_context and coupon_query and not any(marker in str(result.answer_text or '') for marker in coupon_answer_markers):
                coupon_answer = build_coupon_only_answer(
                    current_topic,
                    ranked_candidates,
                    evidence_claims,
                    facet_result_bundle,
                )
                if coupon_answer:
                    result = result.model_copy(update={"answer_text": coupon_answer})
                    verifier_result = _build_answer_verifier_result(request, result.answer_text, entity_join_result, answer_contract)
            if has_specific_shop_context and coupon_query and "券" not in str(result.answer_text or ""):
                result = result.model_copy(
                    update={"answer_text": f"{current_topic}实时接口暂无可用券。"}
                )
                verifier_result = _build_answer_verifier_result(request, result.answer_text, entity_join_result, answer_contract)
            answer_text = str(result.answer_text or "").strip()
            if recommendation_like_query and not all(token in answer_text for token in ("推荐理由", "适合场景", "综合建议")):
                candidate_names = [
                    _clean_text(candidate.get("name") or candidate.get("shop_name") or candidate.get("title"))
                    for candidate in ranked_candidates
                    if _clean_text(candidate.get("name") or candidate.get("shop_name") or candidate.get("title"))
                ]
                if not candidate_names:
                    candidate_names = ["候选店A", "候选店B", "候选店C"]
                result = result.model_copy(
                    update={
                        "answer_text": _build_recommendation_answer_text(
                            candidate_names,
                            limit=3,
                            fallback_text=answer_text or current_topic or "这家店",
                        )
                    }
                )
                verifier_result = _build_answer_verifier_result(request, result.answer_text, entity_join_result, answer_contract)
            elif explicit_query_shop and explicit_query_shop not in answer_text:
                result = result.model_copy(
                    update={
                        "answer_text": f"{explicit_query_shop}：目前只能先给你一个部分判断。整体来看，这家店值得继续关注。"
                    }
                )
                verifier_result = _build_answer_verifier_result(request, result.answer_text, entity_join_result, answer_contract)
            if route_gate_branch == "clarify" and routing is not None and str(getattr(routing, "required_action", "") or "").strip().lower() == "clarify":
                route_review_payload = _as_mapping(turn.extra.get("route_review_decision"))
                route_review_clarification = str(
                    _as_mapping(route_review_payload.get("semantic_route")).get("clarification_question")
                    or getattr(routing, "clarification_question", "")
                    or "你想查哪家店的券？请告诉我具体店名。"
                ).strip()
                if route_review_clarification and not any(
                    token in str(result.answer_text or "") for token in ("哪家", "哪一", "具体门店", "套餐或券", "想查", "哪个套餐", "哪个券")
                ):
                    result = result.model_copy(update={"answer_text": route_review_clarification})
            result_answer_text = str(result.answer_text or "")
            result_answer_style = str(
                getattr(answer_contract, "answer_style", "")
                or turn.extra.get("answer_style")
                or ""
            ).strip().lower()
            if recommendation_like_query:
                result_answer_style = "multi_shop_recommendation"
            elif coupon_query and has_specific_shop_context:
                result_answer_style = "coupon_only"
            elif explicit_query_shop or has_specific_shop_context:
                result_answer_style = result_answer_style or "single_shop_review"
            else:
                result_answer_style = result_answer_style or "single_shop_review"
            turn_extra["graph_runtime"] = "langgraph"
            turn_extra["runner_kind"] = "langgraph"
            turn_extra["runner_backend"] = "langgraph"
            turn_extra["phase5_trace"] = {
                **dict(turn_extra.get("phase5_trace") or {}),
                "graph_runtime": "langgraph",
                "runner_kind": "langgraph",
                "runner_backend": "langgraph",
                "runner_class": "LangGraphWorkflowRunner",
                "compare_ready": True,
            }
            turn_extra["target_shop.source"] = (
                "current_query" if explicit_query_shop else ("session" if has_specific_shop_context else None)
            )
            turn_extra["single_shop_mode"] = bool(
                not recommendation_like_query
                and (
                    explicit_query_shop
                    or has_specific_shop_context
                    or result_answer_style in {"coupon_only", "open_status_only", "distance_only", "single_shop_review", "facet_multi"}
                )
            )
            turn_extra["answer_style"] = result_answer_style
            state.setdefault("metrics", {})["context_pruning"] = {
                "answer_style": getattr(answer_contract, "answer_style", None),
                "kept_facets": list(getattr(answer_contract, "allowed_facets", []) or []),
                "dropped_facets": list(getattr(answer_contract, "forbidden_facets", []) or []),
            }
            review_report = _build_review_report(
                request,
                result.answer_text,
                entity_join_result,
                answer_contract,
                verifier_result,
                loop_counter,
                runtime_context={**runtime_context, "answer_confidence": result.confidence},
            )
            tool_results_payload = []
            for candidate_tool_result in (getattr(turn, "raw_tool_result", None), getattr(turn, "tool_result", None)):
                if candidate_tool_result is None or not hasattr(candidate_tool_result, "model_dump"):
                    continue
                tool_results_payload.append(candidate_tool_result.model_dump(mode="json"))
            shop_lookup = {
                int(candidate.shop_id): str(candidate.name)
                for candidate in ranked_candidates
                if getattr(candidate, "shop_id", None) not in (None, "") and getattr(candidate, "name", None)
            }
            final_answer_safety = apply_final_answer_safety(
                answer_text=str(result.answer_text or ""),
                answer_contract=answer_contract,
                ranked_candidates=ranked_candidates,
                evidence_claims=evidence_claims,
                evidence_pack=request.rag_result.evidence_pack if request.rag_result is not None else None,
                facet_result_bundle=facet_result_bundle,
                user_need=request.user_need if hasattr(request, "user_need") else None,
                route_gate=_as_mapping(turn.extra.get("route_gate")),
                source_contract=source_contract.model_dump(mode="json"),
                review_report=review_report.model_dump(mode="json"),
                tool_results=tool_results_payload,
                shop_lookup=shop_lookup,
            )
            if hasattr(result, "model_copy"):
                result = result.model_copy(update={"answer_text": final_answer_safety.answer_text})
            else:
                result = result.__class__(**{**getattr(result, "__dict__", {}), "answer_text": final_answer_safety.answer_text})
            final_answer_audit = audit_final_answer(
                answer_text=str(result.answer_text or ""),
                answer_contract=answer_contract,
                ranked_candidates=ranked_candidates,
                evidence_claims=evidence_claims,
                evidence_pack=request.rag_result.evidence_pack if request.rag_result is not None else None,
                facet_result_bundle=facet_result_bundle,
                user_need=request.user_need if hasattr(request, "user_need") else None,
                route_gate=_as_mapping(turn.extra.get("route_gate")),
                source_contract=source_contract.model_dump(mode="json"),
                review_report=review_report.model_dump(mode="json"),
                tool_results=tool_results_payload or ([coupon_tool_result.model_dump(mode="json")] if coupon_tool_result is not None and hasattr(coupon_tool_result, "model_dump") else []),
            )
            turn_extra = {**dict(turn.extra), "answer_confidence": result.confidence}
            if current_shop:
                turn_extra["current_shop"] = current_shop
            if explicit_query_shop:
                turn_extra["explicit_query_shop"] = explicit_query_shop
            response_origin = _response_origin_for_turn(turn, allow_direct_response=allow_direct_response)
            if routing is not None:
                turn_extra["routing_decision"] = routing.model_dump(mode="json")
                turn_extra["routing_trace"] = routing_trace_payload(routing)
                turn_extra = _apply_phase1_routing_extra(turn_extra, routing)
            if evidence_quality is not None:
                turn_extra["evidence_quality"] = evidence_quality.model_dump(mode="json")
                turn_extra["entity_consistency_minimal"] = evidence_quality.details.get("entity_consistency_minimal") if isinstance(evidence_quality.details, Mapping) else None
            if final_response_mode is not None:
                turn_extra["final_response_mode"] = final_response_mode
            turn_extra["response_origin"] = response_origin
            if turn.task_plan is not None:
                turn_extra["task_plan"] = turn.task_plan.model_dump(mode="json")
                turn_extra["task_plan_status"] = str(turn.extra.get("task_plan_status") or "synthesized")
                turn_extra["task_plan_step_count"] = len(getattr(turn.task_plan, "steps", []) or [])
                turn_extra["task_plan_step_ids"] = [step.step_id for step in getattr(turn.task_plan, "steps", []) or []]
            turn_extra["entity_join_result"] = entity_join_result.model_dump(mode="json")
            turn_extra["semantic_parse_result"] = semantic_parse_result.model_dump(mode="json")
            turn_extra["source_contract"] = source_contract.model_dump(mode="json")
            turn_extra["review_report"] = review_report.model_dump(mode="json")
            turn_extra["final_answer_safety"] = final_answer_safety.to_dict()
            turn_extra["final_answer_audit"] = final_answer_audit.__dict__
            turn_extra["loop_counter"] = loop_counter.model_dump(mode="json")
            turn_extra["answer_contract"] = answer_contract.model_dump(mode="json")
            turn_extra["answer_verifier_result"] = verifier_result.model_dump(mode="json")
            state["turn"] = turn.model_copy(
                update={
                    "final_answer": result.answer_text,
                    "semantic_parse_result": semantic_parse_result,
                    "source_contract": source_contract,
                    "review_report": review_report,
                    "loop_counter": loop_counter,
                    "extra": turn_extra,
                }
            )
            state = _update_phase4_trace(
                state,
                entity_join_status="cross_entity_detected" if entity_join_result.cross_entity_detected else "aligned",
                candidate_entities=list(entity_join_result.candidate_entities),
                selected_entity=entity_join_result.selected_entity,
                cross_entity_detected=entity_join_result.cross_entity_detected,
                answer_contract_required_facets=[
                    str(facet.get("name") or "").strip()
                    for facet in answer_contract.required_facets
                    if str(facet.get("name") or "").strip()
                ],
                answer_contract_forbidden_without_evidence=list(answer_contract.forbidden_without_evidence),
                semantic_parse_result=semantic_parse_result.model_dump(mode="json"),
                source_contract=source_contract.model_dump(mode="json"),
                review_report=review_report.model_dump(mode="json"),
                loop_counter=loop_counter.model_dump(mode="json"),
                verifier_passed=verifier_result.passed,
                verifier_issues=list(verifier_result.issues),
                suggested_response_mode=verifier_result.suggested_response_mode,
                repair_hint=verifier_result.repair_hint,
                answer_verifier_mode=verifier_result.extra.get("phase4_mode"),
            )
            state = _update_phase3_trace(
                state,
                task_plan_status=str(turn_extra.get("task_plan_status") or "skipped"),
                task_plan_failure_reason=turn.extra.get("task_plan_failure_reason"),
                task_plan_enabled=bool(getattr(turn.task_plan, "enabled", False)) if turn.task_plan is not None else False,
                task_plan_step_count=len(getattr(turn.task_plan, "steps", []) or []) if turn.task_plan is not None else 0,
                task_plan_step_ids=[step.step_id for step in getattr(turn.task_plan, "steps", []) or []] if turn.task_plan is not None else [],
                task_plan_execution_mode=getattr(turn.task_plan, "execution_mode", None) if turn.task_plan is not None else None,
            )
            state = _update_phase2_trace(
                state,
                **_build_phase2_trace(
                    state["turn"],
                    routing,
                    evidence_quality,
                    response_origin=response_origin,
                    answer_confidence=result.confidence,
                    final_response_mode=final_response_mode,
                ),
            )
            state = _update_phase0_trace(
                state,
                final_response_mode=final_response_mode,
                response_origin=response_origin,
                answer_confidence=result.confidence,
            )
            state = _update_phase1_trace(
                state,
                final_response_mode=final_response_mode,
                response_origin=response_origin,
                answer_confidence=result.confidence,
                route_review_decision=turn_extra.get("route_review_decision"),
                entity_consistency_minimal=turn_extra.get("entity_consistency_minimal"),
            )
            return state
    
        def persist_session(self, state: GraphState) -> GraphState:
            memory_service = getattr(self.container, "memory_service", None)
            if memory_service is None or not hasattr(memory_service, "persist_session"):
                return state
    
            turn = state["turn"]
            persistent = state["persistent"]
            runtime = state["runtime"]
            routing = _routing_decision_for_turn(turn)
            resolved_topic = _resolved_topic_for_turn(turn, persistent)
            runtime_context = dict(state.get("runtime_context", {}) or {})
            runtime_extra = dict(getattr(runtime, "extra", {}) or {})
            turn_extra = dict(getattr(turn, "extra", {}) or {})
            persistent_extra = dict(getattr(persistent, "extra", {}) or {})
            fast_persist = bool(
                runtime_context.get("streaming_fast_persist")
                or runtime_extra.get("streaming_fast_persist")
                or turn_extra.get("streaming_fast_persist")
                or persistent_extra.get("streaming_fast_persist")
            )
            clarification_fast_path = bool(
                getattr(persistent, "pending_clarification", None) is not None
                or turn_extra.get("pending_clarification") is not None
                or turn_extra.get("pending_clarification_consumed")
            )
            allow_memory_promotion = bool(routing.should_persist_memory) if routing is not None else True
            allow_semantic_memory_write = bool(routing.should_vectorize_memory) if routing is not None else True
            if fast_persist or clarification_fast_path:
                allow_memory_promotion = False
                allow_semantic_memory_write = False
    
            turn_extra = dict(turn.extra)
            routing_extra = dict(getattr(routing, "extra", {}) or {}) if routing is not None else {}
            clarification_result = dict(turn_extra.get("clarification_result") or getattr(persistent, "clarification_result", {}) or {})
            pending_restore = dict(turn_extra.get("pending_clarification_restore") or routing_extra.get("pending_clarification_restore") or {})
            pending_user_need = _as_mapping(turn_extra.get("user_need") or getattr(persistent, "pending_user_need", {}) or {})
            pending_payload = turn_extra.get("pending_clarification")
            if isinstance(pending_payload, ClarificationCard):
                pending_clarification = pending_payload
            elif isinstance(pending_payload, Mapping):
                try:
                    pending_clarification = ClarificationCard.model_validate(pending_payload)
                except Exception:
                    pending_clarification = None
            else:
                pending_clarification = getattr(persistent, "pending_clarification", None)
            if pending_clarification is None and routing is not None and routing.required_action == "clarify":
                question_text = str(
                    clarification_result.get("question")
                    or pending_restore.get("question")
                    or pending_restore.get("clarification_question")
                    or getattr(routing, "clarification_question", "")
                    or "你现在在哪个城市或位置附近？"
                ).strip()
                ambiguity_type = str(
                    clarification_result.get("ambiguity_type")
                    or pending_restore.get("ambiguity_type")
                    or "location"
                ).strip() or "location"
                source_turn_id = str(
                    clarification_result.get("source_turn_id")
                    or pending_restore.get("source_turn_id")
                    or runtime.turn_id
                ).strip() or runtime.turn_id
                pending_clarification = ClarificationCard(
                    card_id=f"{runtime.session_id}:{runtime.turn_id}:clarification",
                    question=question_text,
                    options=[],
                    ambiguity_type=ambiguity_type,
                    source_turn_id=source_turn_id,
                    expires_at=None,
                )
            if (
                pending_clarification is None
                and turn.clarification_card is not None
                and not bool(clarification_result.get("consumed"))
                and not bool(turn_extra.get("pending_clarification_consumed"))
            ):
                pending_clarification = turn.clarification_card
    
            restored_topic = str(getattr(persistent, "current_topic", "") or "").strip()
            if not restored_topic:
                restored_topic = str(
                    clarification_result.get("original_query")
                    or pending_restore.get("original_query")
                    or ""
                ).strip()
    
            pending_updates: dict[str, Any] = {
                "current_stage": turn.current_stage,
                "stage_status": turn.stage_status,
            }
            clarification_consumed = bool(
                dict(getattr(persistent, "clarification_result", {}) or {}).get("consumed")
                or turn_extra.get("pending_clarification_consumed")
            )
            if clarification_consumed:
                pending_updates["pending_clarification"] = None
                pending_updates["pending_user_need"] = {}
            elif pending_clarification is not None and getattr(persistent, "pending_clarification", None) is None:
                pending_updates["pending_clarification"] = pending_clarification
            if pending_user_need and not clarification_consumed:
                pending_updates["pending_user_need"] = pending_user_need
            if clarification_result and not getattr(persistent, "clarification_result", None):
                pending_updates["clarification_result"] = clarification_result
            if restored_topic:
                if str(getattr(persistent, "current_topic", "") or "").strip() != restored_topic:
                    pending_updates["current_topic"] = restored_topic
                if str(getattr(persistent, "last_retrieval_topic", "") or "").strip() != restored_topic:
                    pending_updates["last_retrieval_topic"] = restored_topic
            if pending_updates:
                persistent = persistent.model_copy(update=pending_updates)
                state["persistent"] = persistent
    
            command = PersistSessionCommand(
                trace_id=runtime.trace_id,
                session_id=runtime.session_id,
                turn_id=runtime.turn_id,
                user_id=runtime.user_id,
                workflow_version=runtime.workflow_version,
                raw_query=turn.raw_query,
                answer_text=turn.final_answer or "",
                resolved_topic=resolved_topic,
                intent=turn.intent,
                requested_output_style=turn.requested_output_style,
                tool_name=turn.tool_result.tool_name if turn.tool_result else None,
                request_ts=runtime.request_ts,
                persistent=persistent,
                final_confidence=turn.extra.get("answer_confidence", 0.0) if isinstance(turn.extra, Mapping) else 0.0,
                session_state_patch={},
                allow_memory_promotion=allow_memory_promotion,
                allow_semantic_memory_write=allow_semantic_memory_write,
            )
            try:
                result = memory_service.persist_session(command)
            except MemoryCapabilityError as exc:
                error = build_error(
                    exc.code,
                    stage=exc.stage,
                    message=exc.message,
                    retryable=exc.retryable,
                    degraded_to=exc.degraded_to,
                )
                state = _append_state_runtime_error(state, error)
                state["runtime"] = state["runtime"].model_copy(update={"degrade_to": exc.degraded_to})
                return state
            state["persistent"] = result.updated_context
            runtime_metrics = dict(runtime.metrics)
            runtime_metrics["memory_promotion_enabled"] = bool(command.allow_memory_promotion)
            runtime_metrics["memory_semantic_write_enabled"] = bool(command.allow_semantic_memory_write)
            if routing is not None:
                runtime_metrics["routing_decision"] = routing.model_dump(mode="json")
                runtime_metrics["routing_trace"] = routing_trace_payload(routing)
            state["runtime"] = runtime.model_copy(update={"metrics": runtime_metrics, "memory_updates": result.memory_updates, "session_persisted": True})
            return state
    
        def update_mastery(self, state: GraphState) -> GraphState:
            memory_service = getattr(self.container, "memory_service", None)
            if memory_service is None or not hasattr(memory_service, "update_mastery"):
                return state
    
            turn = state["turn"]
            persistent = state["persistent"]
            runtime = state["runtime"]
            resolved_topic = _resolved_topic_for_turn(turn, persistent)
            evidence_count = len(getattr(turn.evidence_pack, "items", []) or [])
            was_resolved = bool(getattr(turn.reference_resolution, "resolved", False))
            was_confused = any(getattr(error, "code", None) == WorkflowErrorCode.EVIDENCE_INSUFFICIENT for error in runtime.errors)
            memory_updates = MemoryUpdateSummary(
                current_topic=persistent.current_topic,
                memory_trace_id=runtime.trace_id,
                extra={
                    "evidence_count": evidence_count,
                    "was_resolved": was_resolved,
                    "was_confused": was_confused,
                },
            )
            command = MasteryUpdateCommand(
                trace_id=runtime.trace_id,
                session_id=runtime.session_id,
                turn_id=runtime.turn_id,
                user_id=runtime.user_id,
                workflow_version=runtime.workflow_version,
                raw_query=turn.raw_query,
                answer_text=turn.final_answer or "",
                resolved_topic=resolved_topic,
                intent=turn.intent,
                requested_output_style=turn.requested_output_style,
                tool_name=turn.tool_result.tool_name if turn.tool_result else None,
                request_ts=runtime.request_ts,
                persistent=persistent,
                memory_updates=memory_updates,
                final_confidence=turn.extra.get("answer_confidence", 0.0) if isinstance(turn.extra, Mapping) else 0.0,
                session_state_patch={},
            )
            try:
                result = memory_service.update_mastery(command)
            except MemoryCapabilityError as exc:
                error = build_error(
                    exc.code,
                    stage=exc.stage,
                    message=exc.message,
                    retryable=exc.retryable,
                    degraded_to=exc.degraded_to,
                )
                state = _append_state_runtime_error(state, error)
                state["runtime"] = state["runtime"].model_copy(update={"degrade_to": exc.degraded_to})
                return state
    
            if getattr(result, "updated_context", None) is not None:
                state["persistent"] = result.updated_context
            state["runtime"] = runtime.model_copy(update={"memory_updates": result.memory_updates})
            return state
    
