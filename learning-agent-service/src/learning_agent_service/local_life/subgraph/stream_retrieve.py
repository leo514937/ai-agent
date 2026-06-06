from typing import Any, Iterable

from .helpers import *  # noqa: F403
from .stream_context import StreamRunContext


class LocalLifeStreamRetrieveMixin:
    def _stage_retrieve_and_tools(self, ctx: StreamRunContext) -> Iterable[SseEnvelope]:
        command = ctx.command
        _persistent = ctx.persistent
        client_context = ctx.client_context
        _session_context = ctx.session_context
        _clean_session_context = ctx.clean_session_context
        _session_current_shop_before = ctx.session_current_shop_before
        _session_current_shop_id_before = ctx.session_current_shop_id_before
        _last_candidates_before = ctx.last_candidates_before
        _low_information_input = ctx.low_information_input
        understanding = ctx.understanding
        slots = ctx.slots
        _clarification = ctx.clarification
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
        is_recommendation = str(getattr(user_need, "intent", "") or "") in (
            "local_life_recommend",
            "restaurant_recommendation",
        )
        resolved_shop_ids = ctx.resolved_shop_ids
        selected_shop = ctx.selected_shop
        structured_candidates = ctx.structured_candidates
        ranked_candidates = ctx.ranked_candidates
        evidence_claims = ctx.evidence_claims
        source_summary = ctx.source_summary
        qdrant_pack = ctx.qdrant_pack
        facet_bundle = ctx.facet_bundle or FacetResultBundle()
        coupon_result_obj = ctx.coupon_result_obj
        tool_plan = ctx.tool_plan
        tool_name = ctx.tool_name
        tool_output = ctx.tool_output or {}
        extra_tool_outputs = list(ctx.extra_tool_outputs)
        first_shop_name = ctx.first_shop_name
        tool_input_summary = ctx.tool_input_summary
        top_shop = ctx.top_shop
        response_hint = ctx.response_hint
        verification_result = ctx.verification_result
        if execution_requirements.execute_rag and execution_requirements.execute_tools:
            state.route_decision = "rag_plus_tool"

        filters = {
            "city": slots.city,
            "radius_km": slots.location.radius_km,
            "category": slots.category,
            "scene": slots.scene,
            "preferences": list(slots.preferences),
            "avoid": list(slots.avoid),
            "page": command.page,
        }
        _mark_stage(
            state,
            "retrieval",
            "running",
            detail=filters,
        )
        yield _event(
            EventType.RETRIEVAL_STARTED,
            trace_id=command.trace_id,
            session_id=command.session_id,
            turn_id=command.turn_id,
            workflow_version=self.settings.workflow_version,
            payload=RetrievalStartedPayload(
                semantic_query=understanding.semantic_query,
                keyword_query=understanding.keyword_query,
                retrieval_filters=filters,
                current_stage=state.current_stage,
                stage_status=state.stage_status,
                route_decision=state.route_decision,
                route_reason=state.route_reason,
            ).model_dump(mode="json"),
        )

        # 优先从 execution_requirements 取带常约束的 candidate_shop_ids
        req_candidate_shop_ids: list[int] = list(execution_requirements.candidate_shop_ids or [])
        if not req_candidate_shop_ids and execution_contract.candidate_shop_ids:
            req_candidate_shop_ids = list(execution_contract.candidate_shop_ids)

        tool_name = execution_requirements.execute_tools[0] if execution_requirements.execute_tools else _tool_name_for_intent(intent)
        # 第一个确定性 shop_id：execution_requirements 最先，其次 resolved_shop_ids
        first_shop_id = (
            execution_contract.resolved_shop_id
            or execution_requirements.resolved_shop_id
            or (req_candidate_shop_ids[0] if req_candidate_shop_ids else None)
            or (resolved_shop_ids[0] if resolved_shop_ids else None)
            or (slots.shop_ids[0] if slots.shop_ids else None)
        )
        # 获取确定性店名：context_refs 解析出的店名 > slots.shop_query
        first_shop_name: str | None = None
        if user_need.context_refs:
            for ref in user_need.context_refs:
                if ref.name and ref.name not in ("",):
                    first_shop_name = ref.name
                    break
        first_shop_name = execution_contract.resolved_shop_name or first_shop_name or slots.shop_query or slots.category or slots.city
        tool_input_summary = _tool_input_summary(
            intent,
            filters=filters,
            slots=slots,
            tool_name=tool_name,
            selected_shop_id=first_shop_id,
            selected_shop_name=first_shop_name,
        )
        search_call_id = f"call-{uuid4().hex[:8]}"
        _mark_stage(
            state,
            "tool",
            "running",
            detail={"tool_name": tool_name, "tool_call_id": search_call_id},
        )
        yield _event(
            EventType.TOOL_CALL,
            trace_id=command.trace_id,
            session_id=command.session_id,
            turn_id=command.turn_id,
            workflow_version=self.settings.workflow_version,
            payload=ToolCallPayload(
                tool_name=tool_name,
                tool_call_id=search_call_id,
                input_summary=tool_input_summary,
                current_stage=state.current_stage,
                stage_status=state.stage_status,
                route_decision=state.route_decision,
                route_reason=state.route_reason,
            ).model_dump(mode="json"),
        )

        # 如果 execution_requirements 指定了 candidate_shop_ids，直接居 business_client 查详情
        # 优先级：execution_requirements.candidate_shop_ids > resolved_shop_ids > search
        eff_resolved_shop_ids = req_candidate_shop_ids or resolved_shop_ids
        structured_candidates: list[Any] = []
        if eff_resolved_shop_ids:
            for shop_id in eff_resolved_shop_ids[: getattr(self.settings, "local_life_candidate_limit", 5)]:
                try:
                    structured_candidates.append(self.business_client.get_shop_detail(int(shop_id)))
                except Exception:
                    _LOGGER.exception("local_life_reference_shop_detail_failed")
        elif query_route.route != "realtime_tool" and (query_route.use_business_candidates or slots.shop_query or (target_shop and target_shop.shop_name)):
            structured_candidates = self.business_client.search_candidates(
                query=understanding.semantic_query or understanding.keyword_query or command.message,
                slots=slots,
                limit=getattr(self.settings, "local_life_candidate_limit", 5),
            )

            # 精确门店和分店匹配校验 (P0-Fix-3)
            shop_query = (slots.shop_query or understanding.keyword_query or command.message or "")
            branch_word = None
            for area_word in ["国贸", "水晶城", "望京", "三里屯", "五道口", "中关村"]:
                if area_word in shop_query:
                    branch_word = area_word
                    break

            if branch_word:
                exact_matches = []
                for shop in structured_candidates:
                    shop_name = getattr(shop, "name", "") or ""
                    shop_area = getattr(shop, "area", "") or ""
                    if branch_word in shop_name or branch_word in shop_area:
                        exact_matches.append(shop)
                if exact_matches:
                    structured_candidates = exact_matches

        if slots.category and slots.category.strip() and query_route.use_business_candidates and not eff_resolved_shop_ids:
            normalized_cat = slots.category.strip()
            filtered_list = []
            for shop in structured_candidates:
                t_name = str(
                    getattr(shop, "type_name", None)
                    or (shop.structured_features.get("type_name") if hasattr(shop, "structured_features") and isinstance(shop.structured_features, dict) else None)
                    or getattr(shop, "type_name_raw", None)
                    or ""
                ).strip()
                s_name = str(getattr(shop, "name", "") or "")

                is_match = False
                if normalized_cat in s_name:
                    is_match = True
                elif t_name:
                    if (normalized_cat in t_name) or (t_name in normalized_cat):
                        is_match = True

                if is_match:
                    filtered_list.append(shop)
            if filtered_list:
                structured_candidates = filtered_list

        if target_shop and target_shop.shop_name and query_route.use_business_candidates and not eff_resolved_shop_ids:
            normalized_query = target_shop.shop_name.strip()
            filtered_by_name = []
            for shop in structured_candidates:
                s_name = str(getattr(shop, "name", "") or "")
                if _is_name_match(normalized_query, s_name):
                    filtered_by_name.append(shop)
            structured_candidates = filtered_by_name
        elif slots.shop_query and slots.shop_query.strip() and query_route.use_business_candidates and not eff_resolved_shop_ids:
            normalized_query = slots.shop_query.strip()
            filtered_by_name = []
            for shop in structured_candidates:
                s_name = str(getattr(shop, "name", "") or "")
                if _is_name_match(normalized_query, s_name):
                    filtered_by_name.append(shop)

            # If the user explicitly asked for a shop name and NO candidates match,
            # clear the candidates to avoid hallucinating about another shop.
            structured_candidates = filtered_by_name

        recommendation_intent = str(getattr(user_need, "intent", "") or "")
        if (
            not structured_candidates
            and query_route.use_business_candidates
            and recommendation_intent in ("local_life_recommend", "restaurant_recommendation")
            and not (target_shop and target_shop.shop_id is not None)
        ):
            fallback_limit = max(5, int(getattr(user_need, "recommendation_count", 3) or 3))
            structured_candidates = self.catalog.search_shops(
                query=understanding.semantic_query or understanding.keyword_query or command.message,
                slots=slots,
                limit=fallback_limit,
            )
            if structured_candidates:
                state.metrics["catalog_recommendation_fallback"] = True
                state.metrics["catalog_recommendation_fallback_reason"] = "empty_business_candidates"

        state.structured_candidates = structured_candidates
        _mark_stage(
            state,
            "tool",
            "completed",
            detail={"tool_name": tool_name, "candidate_count": len(structured_candidates)},
        )

        vouchers_by_shop_id: dict[int, list[dict[str, Any]]] = {}
        blog_claims = []
        hot_blogs = self.business_client.get_blog_hot(current=1)
        for shop in structured_candidates[:3]:
            if int(shop.id) not in vouchers_by_shop_id:
                vouchers = self.business_client.get_coupon_list(shop.id)
                vouchers_by_shop_id[int(shop.id)] = list(vouchers)
            else:
                vouchers = vouchers_by_shop_id[int(shop.id)]
            shop_blogs = [blog for blog in hot_blogs if blog.shop_id == shop.id]
            for blog in shop_blogs[:2]:
                blog_claims.append(
                    {
                        "chunk_id": f"blog-{blog.id}",
                        "shop_id": shop.id,
                        "claim": "探店笔记提到口碑不错",
                        "support_text": f"{blog.title}：{blog.content}",
                        "source_type": "探店笔记",
                        "confidence": 0.72,
                        "metadata": {"shop_name": shop.name},
                    }
                )

        retrieval_strategy = query_route.retrieval_strategy
        qdrant_pack = None
        qdrant_claims: list[Any] = []
        if query_route.route == "realtime_tool":
            structured_candidates = []
        elif self.local_life_retriever is not None and query_route.use_qdrant:
            try:
                # ★ RAG 过滤优先级：execution_requirements.candidate_shop_ids > resolved_shop_ids > structured_candidates
                rag_candidate_shop_ids = req_candidate_shop_ids or resolved_shop_ids or [shop.id for shop in structured_candidates] or list(query_route.candidate_shop_ids)
                if not rag_candidate_shop_ids and slots.shop_ids:
                    rag_candidate_shop_ids = list(slots.shop_ids)

                # Single shop hard filter
                if single_shop_mode and target_shop and target_shop.shop_id is not None:
                    rag_candidate_shop_ids = [target_shop.shop_id]
                    child_k = query_route.child_top_k or getattr(self.settings, "local_life_child_top_k", 30)
                    parent_k = query_route.parent_top_k or getattr(self.settings, "local_life_parent_top_k", 5)
                    state.metrics["rag_mode"] = "single_shop_rag"
                else:
                    # Broad recommendation RAG: child_top_k = 50, parent_top_k = 10
                    child_k = 50
                    parent_k = 10
                    state.metrics["rag_mode"] = "recommendation_rag"

                qdrant_pack = self.local_life_retriever.retrieve_local_life_evidence(
                    understanding.semantic_query or understanding.keyword_query or command.message,
                    route=query_route.route,
                    city=slots.city or self._client_context_text(client_context, "city"),
                    area=self._client_context_text(client_context, "area", "district", "region"),
                    category=slots.category,
                    shop_type_id=self._client_context_int(client_context, "shop_type_id", "typeId", "shopTypeId"),
                    candidate_shop_ids=rag_candidate_shop_ids or None,
                    child_top_k=child_k,
                    parent_top_k=parent_k,
                    sibling_limit_per_parent=query_route.sibling_limit_per_parent
                    or getattr(self.settings, "local_life_sibling_limit_per_parent", 6),
                )
                retrieval_strategy = getattr(qdrant_pack, "retrieval_strategy", retrieval_strategy)
                qdrant_claims = merge_business_facts_with_semantic_evidence(
                    structured_candidates,
                    qdrant_pack,
                    vouchers_by_shop_id=vouchers_by_shop_id,
                    limit=30 if not single_shop_mode else 8,
                )
            except Exception:
                _LOGGER.exception("local_life_parent_child_retriever_failed")


        catalog_evidence_claims = self.catalog.build_evidence(
            query=understanding.semantic_query or understanding.keyword_query or command.message,
            shop_ids=[shop.id for shop in structured_candidates],
            slots=slots,
            limit=8,
        )
        evidence_claims = self._merge_evidence_claims(qdrant_claims, catalog_evidence_claims)
        if blog_claims:
            from ..schemas import EvidenceClaim

            evidence_claims = [
                *evidence_claims,
                *[EvidenceClaim.model_validate(item) for item in blog_claims],
            ]
        evidence_claims = self._dedupe_evidence_claims(evidence_claims)
        evidence_claims = EvidenceScopeGuard.filter_evidence_claims(
            evidence_claims,
            ranked_candidates=structured_candidates,
            evidence_pack=qdrant_pack,
            target_shop_id=target_shop.shop_id if (single_shop_mode and target_shop) else None,
        )
        rag_guardrail = LocalLifeRagGuardrail()
        rag_guardrail_result = rag_guardrail.apply(
            raw_query=understanding.semantic_query or understanding.keyword_query or command.message,
            latest_turn_message=command.message,
            rag_mode="single_shop_rag" if single_shop_mode else "recommendation_rag",
            evidence_claims=evidence_claims,
            answer_contract=answer_contract,
            target_shop_id=target_shop.shop_id if (single_shop_mode and target_shop) else None,
        )
        evidence_claims = list(rag_guardrail_result.clean_items)
        state.metrics["rag_guardrail"] = dict(rag_guardrail_result.metrics)
        state.metrics["rag_mode"] = rag_guardrail_result.metrics.get("rag_mode")
        state.metrics["rag_quality_status"] = rag_guardrail_result.rag_quality_status
        state.metrics["rag_dirty_reasons"] = list(rag_guardrail_result.dirty_reasons)
        state.metrics["final_clean_evidence_count"] = rag_guardrail_result.metrics.get("final_clean_evidence_count", 0)
        state.metrics["strong_evidence_count"] = rag_guardrail_result.metrics.get("strong_evidence_count", 0)
        state.metrics["medium_evidence_count"] = rag_guardrail_result.metrics.get("medium_evidence_count", 0)
        state.metrics["weak_evidence_count"] = rag_guardrail_result.metrics.get("weak_evidence_count", 0)
        evidence_claims = sorted(evidence_claims, key=lambda item: (-item.confidence, item.chunk_id))[:30 if not single_shop_mode else 8]
        state.evidence_claims = list(evidence_claims)

        # Trace exposure of evidence shop IDs (P2)
        evidence_shop_ids = []
        for claim in evidence_claims:
            claim_map = _as_mapping(claim)
            c_shop_id = claim_map.get("shop_id") or _as_mapping(claim_map.get("metadata")).get("shop_id")
            if c_shop_id is not None:
                evidence_shop_ids.append(int(c_shop_id))
        state.metrics["evidence_shop_ids"] = list(set(evidence_shop_ids))
        state.metrics["evidence_shop_groups"] = [
            {"shop_id": sid, "evidence_count": evidence_shop_ids.count(sid)}
            for sid in set(evidence_shop_ids)
        ]
        state.metrics["single_shop_mode"] = single_shop_mode

        source_summary = self._summarize_sources(
            structured_candidates=structured_candidates,
            vouchers_by_shop_id=vouchers_by_shop_id,
            hot_blogs=hot_blogs,
        )
        if source_summary.get("source_mode") == "java_business":
            source_summary["degraded_reason"] = None
        source_summary["rag_guardrail"] = dict(rag_guardrail_result.metrics)
        if (
            rag_guardrail_result.degraded
            and source_summary.get("source_mode") != "java_business"
            and not source_summary.get("degraded_reason")
        ):
            source_summary["degraded_reason"] = rag_guardrail_result.degraded_reason
        state.metrics.update(
            {
                "local_life_route": query_route.route,
                "local_life_route_reason": query_route.route_reason,
                "local_life_retrieval_strategy": retrieval_strategy,
                "local_life_user_need": user_need.model_dump(mode="json"),
                "local_life_route_review": review_result.model_dump(mode="json"),
                "local_life_execution_requirements": execution_requirements.model_dump(mode="json"),
            }
        )
        _mark_stage(
            state,
            "grounding",
            "completed",
            detail={"evidence_count": len(evidence_claims), "candidate_count": len(structured_candidates)},
        )
        yield _event(
            EventType.RETRIEVAL_RESULT,
            trace_id=command.trace_id,
            session_id=command.session_id,
            turn_id=command.turn_id,
            workflow_version=self.settings.workflow_version,
            payload=RetrievalResultPayload(
                retrieval_strategy=retrieval_strategy,
                retrieval_hit_count=int(getattr(qdrant_pack, "total_child_hits", 0) or 0)
                if qdrant_pack is not None
                else len(structured_candidates),
                evidence_used_count=len(evidence_claims),
                current_stage=state.current_stage,
                stage_status=state.stage_status,
                route_decision=state.route_decision,
                route_reason=state.route_reason,
            ).model_dump(mode="json"),
        )
        candidate_profiles = fuse_candidates(
            structured_candidates,
            evidence_claims,
            slots=slots,
            vouchers_by_shop_id={shop_id: self._coerce_vouchers(vouchers) for shop_id, vouchers in vouchers_by_shop_id.items()},
        )
        ranked_candidates = rank_candidates(candidate_profiles, slots)
        if slots.category and slots.category.strip() and not eff_resolved_shop_ids:
            normalized_cat = slots.category.strip()
            filtered_list = []
            for shop in ranked_candidates:
                t_name = str(
                    getattr(shop, "type_name", None)
                    or (shop.structured_features.get("type_name") if hasattr(shop, "structured_features") and isinstance(shop.structured_features, dict) else None)
                    or getattr(shop, "type_name_raw", None)
                    or ""
                ).strip()
                s_name = str(getattr(shop, "name", "") or "")

                is_match = False
                if normalized_cat in s_name:
                    is_match = True
                elif t_name:
                    if (normalized_cat in t_name) or (t_name in normalized_cat):
                        is_match = True

                if is_match:
                    filtered_list.append(shop)
            if filtered_list:
                ranked_candidates = filtered_list

        # RAG top1 fallback if target_shop is not set
        if not is_recommendation and (not target_shop or target_shop.confidence == 0.0) and ranked_candidates:
            from ..target_shop_policy import TargetShop
            first = ranked_candidates[0]
            target_shop = TargetShop(
                shop_id=first.shop_id,
                shop_name=first.name,
                source="rag_fallback",
                resolution_source="rag_fallback",
                confidence=0.7,
                is_explicit_in_current_turn=False,
                reason="ranked_candidate_top1_fallback",
                candidate_shop_ids=[first.shop_id]
            )
            single_shop_mode = True
            state.metrics.update({
                "target_shop": target_shop.model_dump(mode="json"),
                "target_shop.source": target_shop.source,
                "target_shop.shop_id": target_shop.shop_id,
                "target_shop.shop_name": target_shop.shop_name,
                "single_shop_mode": single_shop_mode,
            })

        # Reorder ranked_candidates to put target_shop.shop_id at index 0
        if target_shop and target_shop.shop_id is not None and ranked_candidates:
            target_idx = -1
            for i, cand in enumerate(ranked_candidates):
                if int(cand.shop_id) == int(target_shop.shop_id):
                    target_idx = i
                    break
            if target_idx != -1:
                target_cand = ranked_candidates.pop(target_idx)
                ranked_candidates.insert(0, target_cand)

        top_shop = ranked_candidates[0] if ranked_candidates else None

        # Determine selected_shop: target_shop.shop_id takes absolute precedence!
        if target_shop and target_shop.shop_id is not None:
            selected_shop = next(
                (shop for shop in structured_candidates if int(shop.id) == int(target_shop.shop_id)),
                None,
            ) or next(
                (shop for shop in structured_candidates if top_shop is not None and int(shop.id) == int(top_shop.shop_id)),
                None,
            ) or (structured_candidates[0] if structured_candidates else None)
        else:
            # selected_shop 优先级：execution_requirements.resolved_shop_id > ranked_candidates[0] > structured_candidates[0]
            # 这里确保“这家营业吗”绑定的是指代消解后的店，而不是排名第一个
            req_resolved_id = execution_requirements.resolved_shop_id or (req_candidate_shop_ids[0] if req_candidate_shop_ids else None)
            if req_resolved_id is None:
                req_resolved_id = execution_contract.get("resolved_shop_id") if isinstance(execution_contract, dict) else getattr(execution_contract, "resolved_shop_id", None)

            if req_resolved_id is not None:
                selected_shop = next(
                    (shop for shop in structured_candidates if shop.id == req_resolved_id),
                    None,
                ) or next(
                    (shop for shop in structured_candidates if top_shop is not None and shop.id == top_shop.shop_id),
                    None,
                ) or (structured_candidates[0] if structured_candidates else None)
            else:
                forbid_fallback = (
                    execution_contract.get("forbid_global_fallback")
                    if isinstance(execution_contract, dict)
                    else getattr(execution_contract, "forbid_global_fallback", False)
                )
                if forbid_fallback:
                    selected_shop = next(
                        (shop for shop in structured_candidates if top_shop is not None and shop.id == top_shop.shop_id),
                        None,
                    )
                else:
                    selected_shop = next(
                        (shop for shop in structured_candidates if top_shop is not None and shop.id == top_shop.shop_id),
                        None,
                    ) or (structured_candidates[0] if structured_candidates else None)
        facet_bundle = FacetResultBundle()
        coupon_result_obj = None

        tool_plan = LocalLifeToolPlanner.plan(
            answer_contract=answer_contract,
            target_shop=target_shop,
            user_need=user_need,
            latest_turn_message=command.message,
            current_intent=str(getattr(user_need, "intent", "") or intent.value if hasattr(intent, "value") else intent),
            ranked_candidates=ranked_candidates,
        )
        state.metrics["tool_plan"] = tool_plan.model_dump(mode="json")
        state.metrics["latest_turn_message"] = command.message
        state.metrics["current_intent"] = tool_plan.current_intent
        state.metrics["tool_degraded"] = False
        state.metrics["tool_error_code"] = []

        tool_name = None
        tool_output = {}
        search_call_id = None
        extra_tool_outputs = []

        execution_runs: list[PlannedToolInput] = list(tool_plan.runs)
        if not execution_runs:
            execution_items = []
            if hasattr(execution_contract, "items") and execution_contract.items:
                execution_items = execution_contract.items
            else:
                from .facet_execution_plan import FacetExecutionItem

                for t_name in execution_requirements.execute_tools or []:
                    facet = "coupon" if t_name == "get_coupon_list" else ("open_status" if t_name == "check_open_status" else ("distance_eta" if t_name == "get_distance_eta" else "other"))
                    execution_items.append(FacetExecutionItem(facet=facet, source="tool", tool_name=t_name))
            fallback_shop_id = selected_shop.id if selected_shop is not None else first_shop_id
            fallback_shop_name = selected_shop.name if selected_shop is not None else first_shop_name
            for item in execution_items:
                if item.source != "tool" or not item.tool_name:
                    continue
                execution_runs.append(
                    PlannedToolInput(
                        tool_name=item.tool_name,
                        facet=item.facet,
                        shop_id=fallback_shop_id,
                        shop_name=fallback_shop_name,
                        source_scope="fallback_candidate",
                    )
                )

        structured_candidate_map = {int(shop.id): shop for shop in structured_candidates if getattr(shop, "id", None) is not None}

        for run in execution_runs:
            current_tool_name = run.tool_name
            current_shop_record = structured_candidate_map.get(int(run.shop_id)) if run.shop_id is not None and int(run.shop_id) in structured_candidate_map else selected_shop
            current_shop_id = run.shop_id if run.shop_id is not None else (current_shop_record.id if current_shop_record is not None else None)
            current_shop_name = run.shop_name or (current_shop_record.name if current_shop_record is not None else first_shop_name)
            current_input = _tool_input_summary(
                intent,
                filters=filters,
                slots=slots,
                tool_name=current_tool_name,
                selected_shop_id=current_shop_id,
                selected_shop_name=current_shop_name,
            )
            current_call_id = f"call-{uuid4().hex[:8]}"

            _mark_stage(
                state,
                "tool",
                "running",
                detail={"tool_name": current_tool_name, "tool_call_id": current_call_id, "shop_id": current_shop_id},
            )
            yield _event(
                EventType.TOOL_CALL,
                trace_id=command.trace_id,
                session_id=command.session_id,
                turn_id=command.turn_id,
                workflow_version=self.settings.workflow_version,
                payload=ToolCallPayload(
                    tool_name=current_tool_name,
                    tool_call_id=current_call_id,
                    input_summary=current_input,
                    current_stage=state.current_stage,
                    stage_status=state.stage_status,
                    route_decision=state.route_decision,
                    route_reason=state.route_reason,
                ).model_dump(mode="json"),
            )

            current_output: dict[str, Any] = {}
            normalized_result = None
            try:
                if current_tool_name == "get_coupon_list":
                    if current_shop_record is not None:
                        vouchers = self.business_client.get_coupon_list(current_shop_record.id)
                        vouchers_by_shop_id[int(current_shop_record.id)] = list(vouchers)
                        current_output = {
                            "shop_id": current_shop_record.id,
                            "shop_name": current_shop_record.name,
                            "count": len(vouchers),
                            "coupons": [voucher.model_dump(mode="json") for voucher in vouchers[:5]],
                            "source": _clean_source(getattr(current_shop_record, "source", None)) or "catalog",
                        }
                        normalized_result = normalize_tool_result(
                            tool_name=current_tool_name,
                            raw_output=current_output,
                            shop_id=current_shop_record.id,
                            shop_name=current_shop_record.name,
                        )
                        coupon_items_list = [
                            CouponItem(
                                coupon_id=str(v.id),
                                title=v.title,
                                status="available" if (v.stock is None or v.stock > 0) else "unavailable",
                                source="realtime_tool",
                                shop_id=current_shop_record.id,
                                price=v.pay_value,
                                original_price=v.actual_value,
                                description=v.sub_title,
                            )
                            for v in vouchers
                        ]
                        coupon_result_obj = CouponResult(
                            shop_id=current_shop_record.id,
                            realtime_available_count=len(vouchers),
                            realtime_total_count=len(vouchers),
                            items=coupon_items_list,
                            query_success=True,
                            source="realtime_tool",
                        )
                        for cand in ranked_candidates:
                            if int(cand.shop_id) == int(current_shop_record.id):
                                cand.vouchers = [v.model_dump(mode="json") if hasattr(v, "model_dump") else dict(v) for v in vouchers]
                    else:
                        current_output = {
                            "shop_id": current_shop_id,
                            "shop_name": current_shop_name,
                            "count": 0,
                            "coupons": [],
                            "source": "catalog",
                        }
                        normalized_result = normalize_tool_result(
                            tool_name=current_tool_name,
                            raw_output=current_output,
                            shop_id=current_shop_id,
                            shop_name=current_shop_name,
                            status="degraded",
                            error_code="selected_shop_not_found",
                            error_message="selected shop not found",
                        )
                        coupon_result_obj = CouponResult(
                            shop_id=int(current_shop_id or 0),
                            realtime_available_count=0,
                            realtime_total_count=0,
                            items=[],
                            query_success=False,
                            source="fallback",
                            error_message="selected_shop_not_found",
                        )
                    facet_bundle.coupon_result = coupon_result_obj
                elif current_tool_name == "check_open_status":
                    if current_shop_record is not None:
                        open_status_info = self.business_client.check_open_status(current_shop_record)
                        current_output = {
                            "shop_id": current_shop_record.id,
                            "shop_name": current_shop_record.name,
                            **open_status_info,
                            "source": _clean_source(getattr(current_shop_record, "source", None)) or "catalog",
                        }
                        normalized_result = normalize_tool_result(
                            tool_name=current_tool_name,
                            raw_output=current_output,
                            shop_id=current_shop_record.id,
                            shop_name=current_shop_record.name,
                        )
                        for cand in ranked_candidates:
                            if int(cand.shop_id) == int(current_shop_record.id):
                                cand.structured_features["open_hours"] = current_output.get("open_hours") or current_output.get("openHours") or cand.structured_features.get("open_hours")
                                cand.structured_features["open_now"] = current_output.get("open_now")
                                cand.structured_features["open_status"] = current_output.get("open_status")
                    else:
                        current_output = {
                            "shop_id": current_shop_id,
                            "shop_name": current_shop_name,
                            "open_status": "unknown",
                            "open_now": None,
                            "source": "catalog",
                        }
                        normalized_result = normalize_tool_result(
                            tool_name=current_tool_name,
                            raw_output=current_output,
                            shop_id=current_shop_id,
                            shop_name=current_shop_name,
                            status="degraded",
                            error_code="selected_shop_not_found",
                            error_message="selected shop not found",
                        )
                    facet_bundle.open_status_result = dict(normalized_result.data)
                elif current_tool_name == "get_distance_eta":
                    if current_shop_record is not None:
                        distance_eta = self.business_client.get_distance_eta(
                            current_shop_record,
                            lat=slots.location.lat,
                            lng=slots.location.lng,
                        )
                        current_output = {
                            "shop_id": current_shop_record.id,
                            "shop_name": current_shop_record.name,
                            **distance_eta,
                            "source": _clean_source(getattr(current_shop_record, "source", None)) or "catalog",
                        }
                        normalized_result = normalize_tool_result(
                            tool_name=current_tool_name,
                            raw_output=current_output,
                            shop_id=current_shop_record.id,
                            shop_name=current_shop_record.name,
                        )
                        for cand in ranked_candidates:
                            if int(cand.shop_id) == int(current_shop_record.id):
                                cand.structured_features["distance_km"] = current_output.get("distance_km")
                    else:
                        current_output = {
                            "shop_id": current_shop_id,
                            "shop_name": current_shop_name,
                            "distance_km": None,
                            "eta_minutes": None,
                            "mode": "drive",
                            "source": "catalog",
                        }
                        normalized_result = normalize_tool_result(
                            tool_name=current_tool_name,
                            raw_output=current_output,
                            shop_id=current_shop_id,
                            shop_name=current_shop_name,
                            status="degraded",
                            error_code="selected_shop_not_found",
                            error_message="selected shop not found",
                        )
                    facet_bundle.distance_eta_result = dict(normalized_result.data)
                elif current_tool_name == "get_shop_detail":
                    if current_shop_record is not None:
                        detail_shop = self.business_client.get_shop_detail(current_shop_record.id)
                        current_output = {
                            "shop_id": detail_shop.id,
                            "shop": detail_shop.model_dump(mode="json"),
                            "open_status": self.business_client.check_open_status(detail_shop),
                            "distance_eta": self.business_client.get_distance_eta(
                                detail_shop,
                                lat=slots.location.lat,
                                lng=slots.location.lng,
                            ),
                            "source": _clean_source(getattr(detail_shop, "source", None)) or "catalog",
                        }
                    else:
                        current_output = {
                            "status": "not_found",
                            "shop_id": current_shop_id,
                            "shop": None,
                            "source": "catalog",
                        }
                    normalized_result = normalize_tool_result(
                        tool_name=current_tool_name,
                        raw_output=current_output,
                        shop_id=current_shop_id,
                        shop_name=current_shop_name,
                        status="success" if current_shop_record is not None else "degraded",
                        error_code=None if current_shop_record is not None else "selected_shop_not_found",
                        error_message=None if current_shop_record is not None else "selected shop not found",
                    )
                else:
                    current_output = {
                        "candidate_count": len(structured_candidates),
                        "candidate_ids": [shop.id for shop in structured_candidates],
                        "shops": [shop.model_dump(mode="json") for shop in structured_candidates[:5]],
                    }
                    normalized_result = normalize_tool_result(
                        tool_name=current_tool_name,
                        raw_output=current_output,
                        shop_id=current_shop_id,
                        shop_name=current_shop_name,
                    )
            except TimeoutError as exc:
                current_output = {
                    "shop_id": current_shop_id,
                    "shop_name": current_shop_name,
                    "source": "catalog",
                }
                normalized_result = normalize_tool_result(
                    tool_name=current_tool_name,
                    raw_output=current_output,
                    shop_id=current_shop_id,
                    shop_name=current_shop_name,
                    status="timeout",
                    error_message=str(exc),
                )
            except Exception as exc:
                current_output = {
                    "shop_id": current_shop_id,
                    "shop_name": current_shop_name,
                    "source": "catalog",
                }
                normalized_result = normalize_tool_result(
                    tool_name=current_tool_name,
                    raw_output=current_output,
                    shop_id=current_shop_id,
                    shop_name=current_shop_name,
                    status="error",
                    error_message=str(exc),
                )

            facet_bundle.tool_results.append(normalized_result)
            degraded = normalized_result.status in {"timeout", "error", "unsupported", "degraded"}
            retryable = normalized_result.status == "timeout"
            if degraded:
                state.metrics["tool_degraded"] = True
            if normalized_result.error_code:
                state.metrics["tool_error_code"] = list(dict.fromkeys([*(state.metrics.get("tool_error_code") or []), normalized_result.error_code]))

            yield _event(
                EventType.TOOL_RESULT,
                trace_id=command.trace_id,
                session_id=command.session_id,
                turn_id=command.turn_id,
                workflow_version=self.settings.workflow_version,
                payload=ToolResultPayload(
                    tool_name=current_tool_name,
                    tool_call_id=current_call_id,
                    status=normalized_result.status,
                    degraded=degraded,
                    retryable=retryable,
                    error_code=normalized_result.error_code,
                    error_message=normalized_result.error_message,
                    output=dict(normalized_result.data),
                    current_stage=state.current_stage,
                    stage_status="completed",
                    route_decision=state.route_decision,
                    route_reason=state.route_reason,
                ).model_dump(mode="json"),
            )

            state.tool_results.append(
                {
                    "tool_name": current_tool_name,
                    "tool_call_id": current_call_id,
                    "facet": normalized_result.facet,
                    "shop_id": normalized_result.shop_id,
                    "shop_name": normalized_result.shop_name,
                    "status": normalized_result.status,
                    "error_code": normalized_result.error_code,
                    "error_message": normalized_result.error_message,
                    "fetched_at": normalized_result.fetched_at,
                    "is_realtime": normalized_result.is_realtime,
                    "confidence": normalized_result.confidence,
                    "input_summary": dict(current_input),
                    "output": dict(normalized_result.data),
                }
            )

            if len(state.tool_results) == 1:
                tool_name = current_tool_name
                search_call_id = current_call_id
                tool_output = dict(normalized_result.data)
            else:
                extra_tool_outputs.append((current_tool_name, dict(normalized_result.data)))

            _mark_stage(
                state,
                "tool",
                "completed",
                detail={"tool_name": current_tool_name, "candidate_count": len(structured_candidates), "shop_id": current_shop_id, "tool_status": normalized_result.status},
            )
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

