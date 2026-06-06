from typing import Iterable

from learning_agent_service.domain.utils import clean_text as _clean_text

from .helpers import *  # noqa: F403
from .stream_context import StreamRunContext


class LocalLifeStreamComposeMixin:
    def _stage_compose_and_finalize(self, ctx: StreamRunContext) -> Iterable[SseEnvelope]:
        command = ctx.command
        persistent = ctx.persistent
        client_context = ctx.client_context
        _session_context = ctx.session_context
        _clean_session_context = ctx.clean_session_context
        session_current_shop_before = ctx.session_current_shop_before
        session_current_shop_id_before = ctx.session_current_shop_id_before
        _last_candidates_before = ctx.last_candidates_before
        _low_information_input = ctx.low_information_input
        _understanding = ctx.understanding
        slots = ctx.slots
        clarification = ctx.clarification
        intent = ctx.intent
        user_need = ctx.user_need
        _arbitration_result = ctx.arbitration_result
        state = ctx.state
        query_route = ctx.query_route
        review_result = ctx.review_result
        execution_requirements = ctx.execution_requirements
        execution_contract = ctx.execution_contract
        target_shop = ctx.target_shop
        answer_contract = ctx.answer_contract
        single_shop_mode = bool(target_shop and (target_shop.shop_id is not None or target_shop.shop_name is not None))
        _resolved_shop_ids = ctx.resolved_shop_ids
        selected_shop = ctx.selected_shop
        structured_candidates = ctx.structured_candidates
        ranked_candidates = ctx.ranked_candidates
        evidence_claims = ctx.evidence_claims
        source_summary = ctx.source_summary
        _qdrant_pack = ctx.qdrant_pack
        facet_bundle = ctx.facet_bundle or FacetResultBundle()
        coupon_result_obj = ctx.coupon_result_obj
        safety_result = ctx.safety_result
        _tool_plan = ctx.tool_plan
        tool_name = ctx.tool_name
        tool_output = ctx.tool_output or {}
        extra_tool_outputs = list(ctx.extra_tool_outputs)
        first_shop_name = ctx.first_shop_name
        tool_input_summary = ctx.tool_input_summary
        top_shop = ctx.top_shop
        response_hint = ctx.response_hint
        verification_result = ctx.verification_result
        if answer_contract is not None and answer_contract.answer_style == "multi_shop_recommendation":
            ranked_candidates, recommendation_tool_scope = _filter_recommendation_candidates_by_realtime(
                ranked_candidates,
                facet_bundle=facet_bundle,
                answer_contract=answer_contract,
            )
            state.metrics["recommendation_tool_scope"] = recommendation_tool_scope
            top_shop = ranked_candidates[0] if ranked_candidates else None

        if coupon_result_obj:
            state.metrics["coupon_result"] = coupon_result_obj.model_dump(mode="json")
        state.metrics["facet_result_bundle"] = facet_bundle.model_dump(mode="json")

        state.metrics["local_life_tool_results"] = list(state.tool_results)
        safety_result = self.safety_guard.evaluate(
            raw_query=command.message,
            slots=slots,
            ranked_candidates=ranked_candidates,
            evidence_claims=evidence_claims,
            intent=intent,
            selected_shop_id=top_shop.shop_id if top_shop else None,
            selected_shop_name=top_shop.name if top_shop else None,
            client_context=client_context,
        )
        state.approval_required = safety_result.approval_required
        state.approval_request = dict(safety_result.approval_request)
        state.transaction_draft = safety_result.transaction_draft.model_dump(mode="json") if safety_result.transaction_draft else {}
        state.safety_result = safety_result.model_dump(mode="json")
        if safety_result.approval_required:
            _mark_stage(
                state,
                "approval",
                "blocked",
                route_decision=state.route_decision,
                route_reason=safety_result.reason,
                detail={"approval_request": state.approval_request, "risk_level": safety_result.risk_level},
            )
        else:
            _mark_stage(
                state,
                "approval",
                "completed",
                route_decision=state.route_decision,
                route_reason=safety_result.reason,
                detail={"risk_level": safety_result.risk_level},
            )
        if safety_result.approval_required and safety_result.approval_request:
            yield _event(
                EventType.APPROVAL_REQUIRED,
                trace_id=command.trace_id,
                session_id=command.session_id,
                turn_id=command.turn_id,
                workflow_version=self.settings.workflow_version,
                payload=ApprovalRequiredPayload(
                    step_id="local-life-transaction-approval",
                    reason=safety_result.reason,
                    approval_request=safety_result.approval_request,
                    risk_level=safety_result.risk_level,
                    current_stage=state.current_stage,
                    stage_status=state.stage_status,
                    route_decision=state.route_decision,
                    route_reason=state.route_reason,
                ).model_dump(mode="json"),
            )
        _mark_stage(
            state,
            "compose",
            "running",
            detail={"selected_shop_id": top_shop.shop_id if top_shop else None},
        )
        # Day3 Hardening: Avoid calling _summarize_tool_output if no tool was executed (tool_name is None)
        tool_summary_text = ""
        if tool_name:
            tool_summary_text = _summarize_tool_output(
                tool_name,
                tool_output,
                shop_name=selected_shop.name if selected_shop is not None else tool_input_summary.get("shop_name"),
            )
        # 拼接所有额外工具的摘要，确保多 facet 查询的每个维度都体现在答案中
        if extra_tool_outputs:
            extra_summaries = [
                _summarize_tool_output(
                    ename,
                    eout,
                    shop_name=eout.get("shop_name") if isinstance(eout, Mapping) else (selected_shop.name if selected_shop is not None else first_shop_name),
                )
                for ename, eout in extra_tool_outputs
            ]
            extra_summaries_text = "。".join(s for s in extra_summaries if s)
            if tool_summary_text and extra_summaries_text:
                tool_summary_text = tool_summary_text.rstrip("。") + "；" + extra_summaries_text
            elif extra_summaries_text:
                tool_summary_text = extra_summaries_text
        compact_query = str(command.message or "").replace(" ", "")
        recommendation_like_query = any(
            token in compact_query
            for token in ("附近", "周边", "推荐", "几家", "多推荐", "多家")
        )
        recommendation_clear_session_shop = recommendation_like_query and not any(
            token in str(command.message or "") for token in ("它", "他", "她", "这家", "这店", "这间", "刚才那家", "刚才那个", "这商家", "这个商家")
        )
        if recommendation_clear_session_shop:
            prior_shop_name = _clean_text(session_current_shop_before or persistent.current_shop or persistent.selected_shop_name)
            prior_shop_id = session_current_shop_id_before
            if prior_shop_name or prior_shop_id is not None:
                ranked_candidates = [
                    candidate
                    for candidate in ranked_candidates
                    if _clean_text(candidate.name) != prior_shop_name and candidate.shop_id != prior_shop_id
                ]
                evidence_claims = [
                    claim
                    for claim in evidence_claims
                    if _clean_text(getattr(claim, "shop_name", None)) != prior_shop_name and getattr(claim, "shop_id", None) != prior_shop_id
                ]
        facet_keyword_query = any(
            token in compact_query
            for token in ("券", "优惠", "营业", "开门", "开着", "营业时间", "现在营业吗", "现在开吗", "营业吗", "距离", "有多远", "导航", "路线", "怎么走", "怎么去")
        )
        if facet_keyword_query:
            response_hint = {}
        if recommendation_clear_session_shop or (answer_contract is not None and answer_contract.answer_style in {"facet_multi", "multi_shop_recommendation"}):
            response_hint = {}
        evidence_pack = build_evidence_pack(
            raw_query=command.message,
            ranked_candidates=ranked_candidates,
            evidence_claims=evidence_claims,
            slots=slots,
            source_summary={**source_summary, "tool_summary_text": tool_summary_text},
            safety_result=state.safety_result,
            rag_mode="single_shop_rag" if single_shop_mode else "recommendation_rag",
            target_shop_id=target_shop.shop_id if (single_shop_mode and target_shop and target_shop.shop_id is not None) else None,
        )
        response_hint = self._build_response_hint(
            raw_query=command.message,
            slots=slots,
            ranked_candidates=ranked_candidates,
            evidence_claims=evidence_claims,
            evidence_pack=evidence_pack,
            clarification=clarification if clarification.need_clarification else None,
            source_mode=source_summary["source_mode"],
            degraded_reason=source_summary["degraded_reason"],
            knowledge_freshness=source_summary["knowledge_freshness"],
            route_decision=state.route_decision,
            route_reason=state.route_reason,
            safety_result=state.safety_result,
            approval_required=safety_result.approval_required,
            answer_contract=answer_contract,
        )
        if tool_summary_text and not response_hint.get("answer_text"):
            response_hint = {
                **dict(response_hint),
                "answer_text": tool_summary_text,
            }
        if state.metrics.get("shop_mismatch_warning"):
            hint_text = response_hint.get("answer_text") or ""
            if "未查到" not in hint_text:
                mismatch_prefix = state.metrics["shop_mismatch_warning"]
                if structured_candidates:
                    mismatch_prefix += f"{structured_candidates[0].name}。"
                response_hint["answer_text"] = mismatch_prefix + "\n" + hint_text
        verification_result = GroundedVerifier().verify(
            answer_plan=response_hint,
            evidence_pack=evidence_pack,
            ranked_candidates=ranked_candidates,
            safety_result=state.safety_result,
            coupon_result=coupon_result_obj,
        )
        state.metrics.update(
            {
                "answer_plan_enabled": bool(response_hint),
                "answer_plan_valid": bool(verification_result.passed),
                "answer_plan_confidence": verification_result.confidence,
                "evidence_pack_item_count": len(evidence_pack.items),
                "verifier_passed": verification_result.passed,
                "verifier_warnings": list(verification_result.warnings),
            }
        )

        forbid_fallback = (
            execution_contract.get("forbid_global_fallback")
            if isinstance(execution_contract, dict)
            else getattr(execution_contract, "forbid_global_fallback", False)
        )
        current_topic_value = target_shop.shop_name if target_shop and target_shop.shop_name else (selected_shop.name if selected_shop else (top_shop.name if top_shop and not forbid_fallback else slots.category or slots.scene))
        current_shop_value = target_shop.shop_name if target_shop and target_shop.shop_name else (selected_shop.name if selected_shop else state.metrics.get("local_life_execution_contract", {}).get("resolved_shop_name") or (top_shop.name if top_shop and not forbid_fallback else None) or (None if forbid_fallback else (persistent.current_shop or persistent.selected_shop_name or client_context.get("shopName") or client_context.get("shop_name") or client_context.get("selected_shop_name") or client_context.get("current_shop"))))
        if recommendation_clear_session_shop:
            current_shop_value = None
        if command.message and _clean_text(current_shop_value) == _clean_text(command.message):
            current_shop_value = persistent.current_shop or persistent.selected_shop_name or current_shop_value

        bundle = build_response_bundle(
            raw_query=command.message,
            slots=slots,
            answer_contract=answer_contract,
            ranked_candidates=ranked_candidates,
            evidence_claims=evidence_claims,
            answer_plan=response_hint,
            verification_result=verification_result,
            evidence_pack=evidence_pack,
            page=command.page,
            current_topic=current_topic_value,
            current_shop=current_shop_value,
            selected_shop_id=target_shop.shop_id if target_shop and target_shop.shop_id is not None else (selected_shop.id if selected_shop else (top_shop.shop_id if top_shop and not forbid_fallback else None) or (None if forbid_fallback else (persistent.selected_shop_id or client_context.get("shopId") or client_context.get("shop_id") or client_context.get("selected_shop_id")))),
            source="local-life-agent",
            fallback=source_summary["source_mode"] not in {"java_business", "mixed_java_catalog"},
            facet_result_bundle=facet_bundle,
            mode=(safety_result.transaction_draft.action if safety_result.transaction_draft else _mode_from_intent(intent)),
            client_context=client_context,
            approval_required=safety_result.approval_required,
            approval_request=safety_result.approval_request,
            transaction_draft=state.transaction_draft,
            safety_result=state.safety_result,
            route_decision=state.route_decision,
            route_reason=state.route_reason,
            current_stage=state.current_stage,
            stage_status=state.stage_status,
            stage_timeline=list(state.stage_timeline),
            model_hint=response_hint,
            source_mode=source_summary["source_mode"],
            degraded_reason=source_summary["degraded_reason"],
            knowledge_freshness=source_summary["knowledge_freshness"],
            user_need=user_need,
            graph_trace=state.metrics,
        )
        bundle = sanitize_local_life_output(
            bundle,
            shop_lookup={candidate.shop_id: candidate.name for candidate in ranked_candidates if getattr(candidate, "shop_id", None) is not None},
        )
        pronoun_tokens = ("它", "他", "她", "这家", "这店", "这间", "刚才那家", "刚才那个", "这商家", "这个商家")
        has_pronoun = any(token in str(command.message or "") for token in pronoun_tokens)
        explicit_turn_shop_name = _clean_text(query_explicit_shop_name)
        if recommendation_like_query and not explicit_turn_shop_name and not has_pronoun:
            prior_shop_name = _clean_text(session_current_shop_before or persistent.current_shop or persistent.selected_shop_name)
            prior_shop_id = session_current_shop_id_before
            if prior_shop_name or prior_shop_id is not None:
                ranked_candidates = [
                    candidate
                    for candidate in ranked_candidates
                    if _clean_text(candidate.name) != prior_shop_name and candidate.shop_id != prior_shop_id
                ]
                evidence_claims = [
                    claim
                    for claim in evidence_claims
                    if _clean_text(getattr(claim, "shop_name", None)) != prior_shop_name and getattr(claim, "shop_id", None) != prior_shop_id
                ]
        if recommendation_like_query and "推荐理由" not in str(bundle.answer_text or "") and not (response_hint and response_hint.get("answer_text")):
            bundle = bundle.model_copy(
                update={
                    "answer_text": build_multi_shop_recommendation_answer(
                        bundle.current_topic or command.message,
                        ranked_candidates,
                        evidence_claims,
                        user_need=user_need,
                        facet_result_bundle=facet_bundle,
                    )
                }
            )
        query_explicit_shop_name = None
        try:
            from ..entity_resolver import _explicit_entity_from_query
        except Exception:  # pragma: no cover - defensive fallback for import cycles
            _explicit_entity_from_query = None  # type: ignore[assignment]
        if _explicit_entity_from_query is not None:
            query_explicit_shop_name = _clean_text(_explicit_entity_from_query(command.message))
        explicit_shop_name = (
            query_explicit_shop_name
            or _clean_text(getattr(target_shop, "shop_name", None))
            or _clean_text(getattr(slots, "shop_query", None))
            or _clean_text(
                next(
                    (getattr(ref, "name", None) for ref in (getattr(user_need, "context_refs", []) or []) if getattr(ref, "name", None)),
                    None,
                )
            )
            or _clean_text(getattr(selected_shop, "name", None))
        )
        if recommendation_like_query and not query_explicit_shop_name and not any(token in str(command.message or "") for token in ("它", "他", "她", "这家", "这店", "这间", "刚才那家", "刚才那个", "这商家", "这个商家")):
            explicit_shop_name = ""
        if (
            explicit_shop_name
            and explicit_shop_name not in str(bundle.answer_text or "")
            and not (response_hint and response_hint.get("answer_text"))
        ):
            bundle = bundle.model_copy(
                update={
                    "answer_text": (
                        f"{explicit_shop_name}：{bundle.answer_text}"
                        if bundle.answer_text
                        else explicit_shop_name
                    )
                }
            )
        bundle_metrics = {**dict(bundle.metrics), **dict(state.metrics)}
        if "tool_plan" not in bundle_metrics and "tool_plan" in state.metrics:
            bundle_metrics["tool_plan"] = state.metrics["tool_plan"]
        if "latest_turn_message" not in bundle_metrics:
            bundle_metrics["latest_turn_message"] = command.message
        answer_style_metric = str(bundle_metrics.get("answer_style") or "").strip().lower()
        if not answer_style_metric:
            answer_style_metric = "multi_shop_recommendation" if recommendation_like_query else "single_shop_review"
        if not bundle_metrics.get("answer_quality"):
            final_answer_text = str(bundle.answer_text or "")
            final_answer_char_count = len(final_answer_text)
            answer_depth_level = "detailed" if final_answer_char_count >= 220 else "normal"
            if answer_style_metric in {"coupon_only", "open_status_only", "distance_only", "clarification"}:
                answer_depth_level = "short"
            bundle_metrics["answer_quality"] = {
                "final_answer": final_answer_text,
                "answer_style": answer_style_metric,
                "answer_depth_level": answer_depth_level,
                "answer_min_sections": 3 if answer_style_metric == "multi_shop_recommendation" else 4,
                "answer_min_chars": 220 if answer_style_metric == "multi_shop_recommendation" else 120,
                "clean_evidence_count": int(bundle_metrics.get("clean_evidence_count") or 0),
                "strong_evidence_count": int(bundle_metrics.get("strong_evidence_count") or 0),
                "medium_evidence_count": int(bundle_metrics.get("medium_evidence_count") or 0),
                "answer_char_count": final_answer_char_count,
                "section_count": len([line for line in final_answer_text.splitlines() if line.strip() and not line.lstrip().startswith("-")]),
                "bullet_count": sum(1 for line in final_answer_text.splitlines() if line.lstrip().startswith(("-", "•", "*")) or re.match(r"^\s*\d+[.、]", line)),
                "duplicate_sentence_count": 0,
                "duplicate_ratio": 0.0,
                "answer_too_short": final_answer_char_count < (220 if answer_style_metric == "multi_shop_recommendation" else 120),
                "answer_too_repetitive": False,
                "depth_limited_by_evidence": False,
                "expanded_by_quality_gate": False,
                "deduped_by_repetition_guard": False,
                "recommendation_duplicate_shop_count": 0,
                "final_answer_char_count": final_answer_char_count,
                "delta_count": 0,
                "evidence_coverage": 0.0,
                "forbidden_facet_leak": False,
                "unsupported_realtime_claim": False,
            }
        bundle_metrics.setdefault("answer_depth_policy", {
            "answer_style": answer_style_metric,
            "depth_level": bundle_metrics["answer_quality"]["answer_depth_level"],
            "min_sections": bundle_metrics["answer_quality"]["answer_min_sections"],
            "max_sections": 6 if answer_style_metric == "multi_shop_recommendation" else 5,
            "min_bullets_per_section": 2 if answer_style_metric == "multi_shop_recommendation" else 1,
            "min_chars": bundle_metrics["answer_quality"]["answer_min_chars"],
            "clean_evidence_count": bundle_metrics["answer_quality"]["clean_evidence_count"],
            "strong_evidence_count": bundle_metrics["answer_quality"]["strong_evidence_count"],
            "medium_evidence_count": bundle_metrics["answer_quality"]["medium_evidence_count"],
            "depth_limited_by_evidence": bundle_metrics["answer_quality"]["depth_limited_by_evidence"],
        })
        bundle_metrics.setdefault("repetition_guard", {
            "deduped": False,
            "duplicate_sentence_count": 0,
            "duplicate_ratio": 0.0,
            "recommendation_duplicate_shop_count": 0,
        })
        bundle_context = {
            **dict(bundle.context),
            "metrics": dict(bundle_metrics),
            "user_need": user_need.model_dump(mode="json"),
            "pending_user_need": {} if not clarification.need_clarification else user_need.model_dump(mode="json"),
            "route_review": review_result.model_dump(mode="json"),
            "execution_requirements": execution_requirements.model_dump(mode="json"),
            "reviewed_route": query_route.as_dict(),
            "clarification": clarification.model_dump(mode="json"),
            "tool_results": list(state.tool_results),
        }
        bundle = bundle.model_copy(
            update={
                "metrics": bundle_metrics,
                "context": bundle_context,
            }
        )
        state.current_topic = bundle.current_topic
        state.selected_shop_id = bundle.selected_shop_id
        state.mode = bundle.mode
        state.source = bundle.source
        state.answer_text = bundle.answer_text
        state.cards = list(bundle.cards)
        state.suggested_replies = list(bundle.suggested_replies)
        state.metrics = dict(bundle_metrics)
        compact_query = str(command.message or "").replace(" ", "")
        recommendation_like_query = any(
            token in compact_query
            for token in ("附近", "周边", "推荐", "几家", "多推荐", "多家")
        )
        final_evidence_shop_ids: list[int] = []
        for claim in evidence_claims:
            claim_map = _as_mapping(claim)
            shop_id_value = claim_map.get("shop_id") or _as_mapping(claim_map.get("metadata")).get("shop_id")
            if shop_id_value in (None, ""):
                continue
            try:
                shop_id_int = int(shop_id_value)
            except Exception:
                continue
            if shop_id_int not in final_evidence_shop_ids:
                final_evidence_shop_ids.append(shop_id_int)
        if not final_evidence_shop_ids and state.selected_shop_id is not None:
            try:
                final_evidence_shop_ids = [int(state.selected_shop_id)]
            except Exception:
                final_evidence_shop_ids = []
        if final_evidence_shop_ids:
            state.metrics["evidence_shop_ids"] = list(final_evidence_shop_ids)
            state.metrics["evidence_shop_groups"] = [
                {"shop_id": sid, "evidence_count": final_evidence_shop_ids.count(sid)}
                for sid in list(dict.fromkeys(final_evidence_shop_ids))
            ]
        if recommendation_like_query:
            state.metrics["answer_style"] = "multi_shop_recommendation"
            state.metrics["rag_mode"] = "recommendation_rag"
            state.metrics["route_gate"] = {
                "branch": "recommendation",
                "required_action": "rag_plus_tool",
                "route_candidate": state.metrics.get("route_gate", {}).get("route_candidate") if isinstance(state.metrics.get("route_gate"), Mapping) else None,
                "route_reason": state.metrics.get("route_gate", {}).get("route_reason") if isinstance(state.metrics.get("route_gate"), Mapping) else None,
            }
        else:
            state.metrics.setdefault("rag_mode", "single_shop_rag")
            if "route_gate" not in state.metrics:
                state.metrics["route_gate"] = {
                    "branch": "rag",
                    "required_action": "rag_retrieval",
                    "route_candidate": None,
                    "route_reason": None,
                }
        final_metrics = {**dict(bundle.metrics), **dict(state.metrics)}
        if "tool_plan" not in final_metrics and "tool_plan" in state.metrics:
            final_metrics["tool_plan"] = state.metrics["tool_plan"]
        if final_metrics.get("latest_turn_message") in (None, ""):
            final_metrics["latest_turn_message"] = state.metrics.get("latest_turn_message") or command.message
        final_context_metrics = {
            **dict(bundle.context.get("metrics") or {}),
            **final_metrics,
        }
        state.route_decision = bundle.route_decision or state.route_decision
        state.route_reason = bundle.route_reason or state.route_reason
        state.current_stage = bundle.current_stage or state.current_stage
        state.stage_status = bundle.stage_status or state.stage_status
        state.stage_timeline = list(bundle.stage_timeline or state.stage_timeline)
        _mark_stage(
            state,
            "final",
            "completed",
            route_decision=state.route_decision,
            route_reason=state.route_reason,
            detail={"selected_shop_id": state.selected_shop_id, "approval_required": state.approval_required},
        )
        bundle = bundle.model_copy(
            update={
                "route_decision": state.route_decision,
                "route_reason": state.route_reason,
                "current_stage": state.current_stage,
                "stage_status": state.stage_status,
                "stage_timeline": list(state.stage_timeline),
                "metrics": final_metrics,
                "context": {
                    **dict(bundle.context),
                    "metrics": final_context_metrics,
                    "route_decision": state.route_decision,
                    "route_reason": state.route_reason,
                    "current_stage": state.current_stage,
                    "stage_status": state.stage_status,
                    "stage_timeline": list(state.stage_timeline),
                    "pending_user_need": {} if not clarification.need_clarification else user_need.model_dump(mode="json"),
                },
            }
        )
        self._persist_context(
            persistent,
            state,
            command,
            slots=slots,
            ranked_candidates=ranked_candidates,
            bundle=bundle,
        )
        bundle = bundle.model_copy(
            update={
                "metrics": {
                    **dict(bundle.metrics),
                    **dict(state.metrics),
                    "tool_plan": state.metrics.get("tool_plan", dict(bundle.metrics).get("tool_plan")),
                    "latest_turn_message": state.metrics.get("latest_turn_message") or command.message,
                },
                "context": {
                    **dict(bundle.context),
                    "metrics": {
                        **dict(bundle.metrics),
                        **dict(state.metrics),
                        "tool_plan": state.metrics.get("tool_plan", dict(bundle.metrics).get("tool_plan")),
                        "latest_turn_message": state.metrics.get("latest_turn_message") or command.message,
                    },
                    "target_shop_resolution": dict(state.metrics.get("target_shop_resolution") or {}),
                },
            }
        )
        yield _event(
            EventType.FINAL,
            trace_id=command.trace_id,
            session_id=command.session_id,
            turn_id=command.turn_id,
            workflow_version=self.settings.workflow_version,
            payload=bundle.model_dump(mode="json"),
        )
        return bundle

