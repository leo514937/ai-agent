from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import Any

from .query_rewriter import _CITY_NAMES as _LOCAL_LIFE_CITY_NAMES
from .scene_policy import ScenePolicy
from .query_router import LocalLifeRouteDecision
from .schemas import ClarificationDecision, RouteExecutionRequirement, RouteReviewResult, UserNeed


class RouteReview:
    @staticmethod
    def review(
        user_need: UserNeed,
        initial_route: LocalLifeRouteDecision,
        clarification: ClarificationDecision,
        client_context: Mapping[str, Any] | None = None,
        session_context: Mapping[str, Any] | None = None,
    ) -> RouteReviewResult:
        result = RouteReview._review_impl(
            user_need=user_need,
            initial_route=initial_route,
            clarification=clarification,
            client_context=client_context,
            session_context=session_context,
        )
        
        # 优先使用 EntityResolver 从 session 继承实体
        from .entity_resolver import _explicit_entity_from_query, EntityResolver
        explicit_entity = _explicit_entity_from_query(user_need.raw_query)
        target_shop = EntityResolver().resolve_target(
            raw_query=user_need.raw_query,
            slots=user_need.slots,
            client_context=client_context,
            session_context=session_context,
            explicit_entity=explicit_entity
        )
        
        resolved_shop_id = None
        candidate_shop_ids = []
        
        if target_shop.shop_id:
            resolved_shop_id = target_shop.shop_id
            candidate_shop_ids = [resolved_shop_id]
        elif explicit_entity is None and user_need.context_refs:
            for ref in user_need.context_refs:
                if ref.type == "shop" and ref.id:
                    try:
                        resolved_shop_id = int(ref.id)
                        candidate_shop_ids = [resolved_shop_id]
                        break
                    except (ValueError, TypeError):
                        pass

        if target_shop.is_explicit_in_current_turn and not resolved_shop_id:
            candidate_shop_ids = [-1]

        required_facet_names = [f.name for f in user_need.required_facets]
        if not required_facet_names:
            query_text = (user_need.raw_query or "").replace(" ", "")
            inferred_facet_names: list[str] = []
            coupon_tokens = ("券", "优惠", "领券", "打折", "代金券", "折扣", "有券", "团购")
            open_tokens = ("营业", "开门", "开着", "营业时间", "现在营业吗", "现在开吗", "营业吗")
            distance_tokens = ("离我多远", "距离", "有多远", "导航", "路线", "怎么走", "怎么去")
            booking_tokens = ("订座", "预订", "预约", "订位")
            order_tokens = ("下单", "订单", "取消订单")
            phone_tokens = ("电话", "联系电话", "手机", "号码")
            payment_tokens = ("支付", "付款", "买单", "收款")
            refund_tokens = ("退款", "退费", "退钱")
            delivery_tokens = ("配送", "送达", "外卖", "多久到", "到店", "送到")

            if any(token in query_text for token in coupon_tokens):
                inferred_facet_names.append("coupon")
            if any(token in query_text for token in open_tokens):
                inferred_facet_names.append("open_status")
            if any(token in query_text for token in distance_tokens):
                inferred_facet_names.append("distance_eta")
            if any(token in query_text for token in booking_tokens):
                inferred_facet_names.append("booking")
            if any(token in query_text for token in order_tokens):
                inferred_facet_names.append("order")
            if any(token in query_text for token in phone_tokens):
                inferred_facet_names.append("phone")
            if any(token in query_text for token in payment_tokens):
                inferred_facet_names.append("payment")
            if any(token in query_text for token in refund_tokens):
                inferred_facet_names.append("refund")
            if any(token in query_text for token in delivery_tokens):
                inferred_facet_names.append("delivery_eta")

            if inferred_facet_names:
                required_facet_names = inferred_facet_names
        # DAY3 HARDENING: Front-end Routing Interception for Coupon queries without explicit target shops
        is_coupon_query = "coupon" in required_facet_names or any(x in user_need.raw_query for x in ["券", "优惠", "代金券", "团购"])
        is_generic_search = (
            user_need.slots.category is not None
            or user_need.slots.scene is not None
            or any(x in user_need.raw_query for x in ["附近", "推荐", "找个", "搜", "查附近", "有什么"])
        )
        has_no_target_shop = not resolved_shop_id and not (target_shop and (target_shop.shop_id or target_shop.shop_name)) and not explicit_entity
        
        if is_coupon_query and has_no_target_shop and not is_generic_search:
            new_clarification = ClarificationDecision(
                need_clarification=True,
                question="你想查询哪家店的优惠券？请告诉我具体门店名称。",
                ambiguity_type="reference_clarify",
            )

            reviewed_route = LocalLifeRouteDecision(
                route="clarify",
                retrieval_strategy="clarification_only",
                route_reason="coupon_query_without_shop",
                candidate_shop_ids=(),
                use_business_candidates=False,
                use_qdrant=False,
            )
            exec_reqs = RouteExecutionRequirement(
                required_facets=[],
                execute_tools=[],
                execute_rag=False,
                reference_needed=True,
            )
            return RouteReviewResult(
                reviewed_route=reviewed_route,
                execution_requirements=exec_reqs,
                review_reason="Coupon query without target shop. Triggered reference clarification.",
                intercepted=True,
                clarification=new_clarification,
                reviewed_clarification=new_clarification,
            )
        
        # Inject into result
        result = result.model_copy(
            update={
                "resolved_shop_id": resolved_shop_id,
                "candidate_shop_ids": candidate_shop_ids,
                "execution_requirements": result.execution_requirements.model_copy(
                    update={
                        "resolved_shop_id": resolved_shop_id,
                        "candidate_shop_ids": candidate_shop_ids,
                    }
                )
            }
        )
        return result

    @staticmethod
    def _review_impl(
        user_need: UserNeed,
        initial_route: LocalLifeRouteDecision,
        clarification: ClarificationDecision,
        client_context: Mapping[str, Any] | None = None,
        session_context: Mapping[str, Any] | None = None,
    ) -> RouteReviewResult:
        client_ctx = client_context or {}
        session_ctx = session_context or {}
        normalized_query = user_need.raw_query.strip().lower()

        # Resolve explicit target shop early in _review_impl
        from .entity_resolver import _explicit_entity_from_query, EntityResolver
        explicit_entity = _explicit_entity_from_query(user_need.raw_query)
        target_shop = EntityResolver().resolve_target(
            raw_query=user_need.raw_query,
            slots=user_need.slots,
            client_context=client_context,
            session_context=session_ctx,
            explicit_entity=explicit_entity
        )
        resolved_shop_id = None
        if target_shop.shop_id:
            resolved_shop_id = target_shop.shop_id
        elif explicit_entity is None and user_need.context_refs:
            for ref in user_need.context_refs:
                if ref.type == "shop" and ref.id:
                    try:
                        resolved_shop_id = int(ref.id)
                        break
                    except (ValueError, TypeError):
                        pass

        active_candidate_ids = initial_route.candidate_shop_ids
        if target_shop.is_explicit_in_current_turn:
            active_candidate_ids = tuple(target_shop.candidate_shop_ids)
        elif target_shop.candidate_shop_ids:
            active_candidate_ids = tuple(target_shop.candidate_shop_ids)
        elif resolved_shop_id:
            active_candidate_ids = (resolved_shop_id,)


        # Extract facets for easier checking
        required_facet_names = [f.name for f in user_need.required_facets]
        has_dynamic_facet = any(name in required_facet_names for name in ("coupon", "open_status", "distance_eta", "booking", "order", "order_status", "phone", "payment", "refund", "delivery_eta", "open_hours"))
        has_static_facet = any(name in required_facet_names for name in ("scene_fit", "shop_detail", "price"))
        has_explicit_shop_context = bool(
            resolved_shop_id
            or (target_shop and (target_shop.shop_id or target_shop.shop_name))
            or explicit_entity
            or user_need.slots.shop_name
            or user_need.slots.shop_ids
        )

        # Determine if pronouns are used in query
        has_pronoun = any(p in normalized_query for p in ("他", "她", "它", "这家", "这店", "这间", "刚才那家", "这个店", "刚才那个", "这几家", "第一家", "第二家"))

        # Determine if coordinates/city are present in client context
        has_location_ctx = (
            client_ctx.get("city") is not None
            or client_ctx.get("lat") is not None
            or client_ctx.get("lng") is not None
            or user_need.slots.city is not None
            or user_need.slots.location.city is not None
        )

        # 1. Rule: Pronoun reference failure (Case 6)
        # 如果有指代词，但是 context_refs 为空，且利用 EntityResolver 也没能从 Session 继承实体，才触发澄清
        if has_pronoun:
            from .entity_resolver import _explicit_entity_from_query, EntityResolver
            explicit_entity = _explicit_entity_from_query(user_need.raw_query)
            target_shop = EntityResolver().resolve_target(
                raw_query=user_need.raw_query,
                slots=user_need.slots,
                client_context=client_context,
                session_context=session_ctx,
                explicit_entity=explicit_entity
            )
            if not user_need.context_refs and not (target_shop.shop_id or target_shop.shop_name):
                new_clarification = ClarificationDecision(
                    need_clarification=True,
                    question="你问的是哪家店？请告诉我具体店名或选择刚才提到的商家。",
                    ambiguity_type="reference_clarify",
                )
                reviewed_route = LocalLifeRouteDecision(
                    route="clarify",
                    retrieval_strategy="clarification_only",
                    route_reason="reference_resolution_failed",
                    candidate_shop_ids=(),
                    use_business_candidates=False,
                    use_qdrant=False,
                )
                exec_reqs = RouteExecutionRequirement(
                    required_facets=[],
                    execute_tools=[],
                    execute_rag=False,
                    reference_needed=True,
                )
                return RouteReviewResult(
                    reviewed_route=reviewed_route,
                    execution_requirements=exec_reqs,
                    review_reason="Pronoun reference used but no recent shop entity found in session. Triggered reference clarification.",
                    intercepted=True,
                    clarification=new_clarification,
                    reviewed_clarification=new_clarification,
                )

        # 2. Rule: Specific Location Clarification Overriding (Case 4 vs Case 5)
        # If the LLM triggered clarification, or if the location context is completely missing for a vague nearby query
        has_coordinates = (
            client_ctx.get("lat") is not None
            and client_ctx.get("lng") is not None
        )
        missing_location_for_vague_query = (
            any(k in normalized_query for k in ("附近", "推荐", "找个餐厅", "推荐个"))
            and not has_coordinates
        )
        if clarification.need_clarification or missing_location_for_vague_query:
            if has_explicit_shop_context and (has_dynamic_facet or has_static_facet):
                new_clarification = ClarificationDecision(need_clarification=False)
                if has_dynamic_facet and has_static_facet:
                    reviewed_route = LocalLifeRouteDecision(
                        route="structured_first",
                        retrieval_strategy="business_candidates->parent_child_rag->shop_rerank",
                        route_reason="multi_facet_query_alignment",
                        candidate_shop_ids=active_candidate_ids,
                        parent_top_k=5,
                        child_top_k=30,
                        sibling_limit_per_parent=6,
                        preferred_roles=("merchant_profile", "merchant_review_summary", "merchant_scene_fit"),
                        use_business_candidates=True,
                        use_qdrant=True,
                        extra=initial_route.extra,
                    )
                    tools_to_run = []
                    if "coupon" in required_facet_names:
                        tools_to_run.append("get_coupon_list")
                    if "open_status" in required_facet_names:
                        tools_to_run.append("check_open_status")
                    if "distance_eta" in required_facet_names:
                        tools_to_run.append("get_distance_eta")
                    exec_reqs = RouteExecutionRequirement(
                        required_facets=required_facet_names,
                        execute_tools=tools_to_run,
                        execute_rag=True,
                        reference_needed=has_pronoun,
                    )
                    is_intercepted = (
                        initial_route.use_qdrant is not True
                        or initial_route.use_business_candidates is not True
                        or initial_route.route != "structured_first"
                    )
                    return RouteReviewResult(
                        reviewed_route=reviewed_route,
                        execution_requirements=exec_reqs,
                        review_reason="Explicit shop context with mixed facets. Kept aligned routing and suppressed clarification.",
                        intercepted=is_intercepted,
                        clarification=new_clarification,
                        reviewed_clarification=new_clarification,
                    )
                if has_dynamic_facet:
                    tools_to_run = []
                    if "coupon" in required_facet_names:
                        tools_to_run.append("get_coupon_list")
                    if "open_status" in required_facet_names:
                        tools_to_run.append("check_open_status")
                    if "distance_eta" in required_facet_names:
                        tools_to_run.append("get_distance_eta")
                    reviewed_route = LocalLifeRouteDecision(
                        route="realtime_tool",
                        retrieval_strategy="java_business_tool_only",
                        route_reason="dynamic_single_facet_query",
                        candidate_shop_ids=active_candidate_ids,
                        parent_top_k=0 if resolved_shop_id is None else 5,
                        child_top_k=0 if resolved_shop_id is None else 30,
                        sibling_limit_per_parent=0 if resolved_shop_id is None else 6,
                        preferred_roles=() if resolved_shop_id is None else ("merchant_profile", "merchant_review_summary", "merchant_scene_fit"),
                        use_business_candidates=True,
                        use_qdrant=bool(resolved_shop_id),
                        extra=initial_route.extra,
                    )
                    exec_reqs = RouteExecutionRequirement(
                        required_facets=required_facet_names,
                        execute_tools=tools_to_run,
                        execute_rag=bool(resolved_shop_id),
                        reference_needed=has_pronoun,
                    )
                    is_intercepted = initial_route.use_qdrant is not False or initial_route.route != "realtime_tool"
                    return RouteReviewResult(
                        reviewed_route=reviewed_route,
                        execution_requirements=exec_reqs,
                        review_reason="Explicit shop context with dynamic facets. Suppressed clarification and kept tool flow.",
                        intercepted=is_intercepted,
                        clarification=new_clarification,
                        reviewed_clarification=new_clarification,
                    )
                if has_static_facet:
                    reviewed_route = LocalLifeRouteDecision(
                        route="merchant_reasoning" if initial_route.route not in ("structured_first", "merchant_reasoning") else initial_route.route,
                        retrieval_strategy="parent_child_rag->shop_rerank" if initial_route.route not in ("structured_first", "merchant_reasoning") else initial_route.retrieval_strategy,
                        route_reason="static_experience_query",
                        candidate_shop_ids=active_candidate_ids,
                        parent_top_k=initial_route.parent_top_k or 5,
                        child_top_k=initial_route.child_top_k or 30,
                        sibling_limit_per_parent=initial_route.sibling_limit_per_parent or 6,
                        preferred_roles=initial_route.preferred_roles or ("merchant_profile", "merchant_review_summary", "merchant_scene_fit"),
                        use_business_candidates=initial_route.use_business_candidates,
                        use_qdrant=True,
                        extra=initial_route.extra,
                    )
                    exec_reqs = RouteExecutionRequirement(
                        required_facets=required_facet_names,
                        execute_tools=[],
                        execute_rag=True,
                        reference_needed=has_pronoun,
                    )
                    is_intercepted = initial_route.use_qdrant is not True
                    return RouteReviewResult(
                        reviewed_route=reviewed_route,
                        execution_requirements=exec_reqs,
                        review_reason="Explicit shop context with static facets. Suppressed clarification and kept detail flow.",
                        intercepted=is_intercepted,
                        clarification=new_clarification,
                        reviewed_clarification=new_clarification,
                    )
            # Case 4: Strong query + client location -> Override clarification and force search
            if has_location_ctx and any(k in normalized_query for k in ("附近", "推荐", "不踩雷", "适合带娃", "适合约会", "有券")):
                new_clarification = ClarificationDecision(need_clarification=False)
                
                # Align routing to search + RAG
                reviewed_route = dataclasses.replace(
                    initial_route,
                    route="structured_first",
                    retrieval_strategy="business_candidates->parent_child_rag->shop_rerank",
                    use_business_candidates=True,
                    use_qdrant=True,
                )
                
                tools_to_run = []
                if "coupon" in required_facet_names:
                    tools_to_run.append("get_coupon_list")
                if "open_status" in required_facet_names:
                    tools_to_run.append("check_open_status")
                if "distance_eta" in required_facet_names:
                    tools_to_run.append("get_distance_eta")

                exec_reqs = RouteExecutionRequirement(
                    required_facets=required_facet_names,
                    execute_tools=tools_to_run,
                    execute_rag=has_static_facet,
                    reference_needed=False,
                )
                
                return RouteReviewResult(
                    reviewed_route=reviewed_route,
                    execution_requirements=exec_reqs,
                    review_reason="Client location context present. Overrode generic clarification and upgraded to search.",
                    intercepted=True,
                    clarification=new_clarification,
                    reviewed_clarification=new_clarification,
                )
            
            # Case 5: Nearby recommendation without location should continue recommendation flow.
            elif not has_location_ctx:
                scene_detected = ScenePolicy.detect_scene(user_need.raw_query)
                has_city_mention = any(city in normalized_query for city in _LOCAL_LIFE_CITY_NAMES if city)
                nearby_scene_recommendation = any(
                    k in normalized_query
                    for k in ("推荐", "找个餐厅", "推荐个", "最近", "评分最高", "适合", "约会", "家庭聚餐", "商务宴请", "带小孩", "朋友聚餐", "深夜", "一个人")
                ) or bool(scene_detected) or has_city_mention
                if nearby_scene_recommendation and not any(k in normalized_query for k in ("附近", "周边")):
                    new_clarification = ClarificationDecision(need_clarification=False)
                    return RouteReviewResult(
                        reviewed_route=initial_route,
                        execution_requirements=result.execution_requirements,
                        review_reason="Scene or city recommendation without location context kept on recommendation flow.",
                        intercepted=False,
                        clarification=new_clarification,
                        reviewed_clarification=new_clarification,
                    )
                if any(k in normalized_query for k in ("附近", "周边")) and nearby_scene_recommendation:
                    new_clarification = ClarificationDecision(need_clarification=False)
                    return RouteReviewResult(
                        reviewed_route=initial_route,
                        execution_requirements=result.execution_requirements,
                        review_reason="Nearby recommendation query without location context kept on recommendation flow.",
                        intercepted=False,
                        clarification=new_clarification,
                        reviewed_clarification=new_clarification,
                    )

        # 3. Rule: Dynamic Single-Facet Query (Case 2)
        # If query has dynamic facets (coupon, open_status) but NO static experience facets (scene_fit, shop_detail)
        if has_dynamic_facet and not has_static_facet:
            tools_to_run = []
            if "coupon" in required_facet_names:
                tools_to_run.append("get_coupon_list")
            if "open_status" in required_facet_names:
                tools_to_run.append("check_open_status")
            if "distance_eta" in required_facet_names:
                tools_to_run.append("get_distance_eta")

            use_qdrant_flag = bool(
                resolved_shop_id is not None 
                or (explicit_entity is not None and explicit_entity.strip() not in ("他", "她", "它", "这家", "这店", "这间", "刚才那家", "这个店", "刚才那个", "这几家", "第一家", "第二家"))
            )
            execute_rag_flag = use_qdrant_flag
            reviewed_route = LocalLifeRouteDecision(
                route="realtime_tool",
                retrieval_strategy="java_business_tool_only",
                route_reason="dynamic_single_facet_query",
                candidate_shop_ids=active_candidate_ids,
                parent_top_k=0 if not use_qdrant_flag else 5,
                child_top_k=0 if not use_qdrant_flag else 30,
                sibling_limit_per_parent=0 if not use_qdrant_flag else 6,
                preferred_roles=() if not use_qdrant_flag else ("merchant_profile", "merchant_review_summary", "merchant_scene_fit"),
                use_business_candidates=True,
                use_qdrant=use_qdrant_flag,  # Exclude Qdrant retrieval for pure dynamic facet unless explicit shop
                extra=initial_route.extra,
            )

            exec_reqs = RouteExecutionRequirement(
                required_facets=required_facet_names,
                execute_tools=tools_to_run,
                execute_rag=execute_rag_flag,
                reference_needed=has_pronoun,
            )

            is_intercepted = (
                initial_route.use_qdrant is not False
                or initial_route.route != "realtime_tool"
            )

            return RouteReviewResult(
                reviewed_route=reviewed_route,
                execution_requirements=exec_reqs,
                review_reason="Dynamic single-facet query detected. Enforced tools and excluded Qdrant search.",
                intercepted=is_intercepted,
                clarification=clarification,
                reviewed_clarification=clarification,
            )

        # 4. Rule: Multi-Facet Query (Case 1)
        # If query has both static experience facets and dynamic facets
        if has_dynamic_facet and has_static_facet:
            reviewed_route = LocalLifeRouteDecision(
                route="structured_first",
                retrieval_strategy="business_candidates->parent_child_rag->shop_rerank",
                route_reason="multi_facet_query_alignment",
                candidate_shop_ids=active_candidate_ids,
                parent_top_k=5,
                child_top_k=30,
                sibling_limit_per_parent=6,
                preferred_roles=("merchant_profile", "merchant_review_summary", "merchant_scene_fit"),
                use_business_candidates=True,  # Force tools
                use_qdrant=True,              # Force Qdrant
                extra=initial_route.extra,
            )

            tools_to_run = []
            if "coupon" in required_facet_names:
                tools_to_run.append("get_coupon_list")
            if "open_status" in required_facet_names:
                tools_to_run.append("check_open_status")
            if "distance_eta" in required_facet_names:
                tools_to_run.append("get_distance_eta")

            exec_reqs = RouteExecutionRequirement(
                required_facets=required_facet_names,
                execute_tools=tools_to_run,
                execute_rag=True,
                reference_needed=has_pronoun,
            )

            is_intercepted = (
                initial_route.use_qdrant is not True
                or initial_route.use_business_candidates is not True
                or initial_route.route != "structured_first"
            )

            return RouteReviewResult(
                reviewed_route=reviewed_route,
                execution_requirements=exec_reqs,
                review_reason="Multi-facet query containing both static and dynamic requirements. Enforced aligned routing and both data paths.",
                intercepted=is_intercepted,
                clarification=clarification,
                reviewed_clarification=clarification,
            )

        # 5. Rule: Static Experience Facet (Case 3)
        if has_static_facet and not has_dynamic_facet:
            reviewed_route = LocalLifeRouteDecision(
                route="merchant_reasoning" if initial_route.route not in ("structured_first", "merchant_reasoning") else initial_route.route,
                retrieval_strategy="parent_child_rag->shop_rerank" if initial_route.route not in ("structured_first", "merchant_reasoning") else initial_route.retrieval_strategy,
                route_reason="static_experience_query",
                candidate_shop_ids=active_candidate_ids,
                parent_top_k=initial_route.parent_top_k or 5,
                child_top_k=initial_route.child_top_k or 30,
                sibling_limit_per_parent=initial_route.sibling_limit_per_parent or 6,
                preferred_roles=initial_route.preferred_roles or ("merchant_profile", "merchant_review_summary", "merchant_scene_fit"),
                use_business_candidates=initial_route.use_business_candidates,
                use_qdrant=True,  # Force Qdrant for static experience
                extra=initial_route.extra,
            )

            exec_reqs = RouteExecutionRequirement(
                required_facets=required_facet_names,
                execute_tools=[],
                execute_rag=True,
                reference_needed=has_pronoun,
            )

            is_intercepted = initial_route.use_qdrant is not True

            return RouteReviewResult(
                reviewed_route=reviewed_route,
                execution_requirements=exec_reqs,
                review_reason="Static experiential facet query. Enabled Qdrant search and bypassed dynamic tools.",
                intercepted=is_intercepted,
                clarification=clarification,
                reviewed_clarification=clarification,
            )

        # Default fallthrough (no changes)
        exec_reqs = RouteExecutionRequirement(
            required_facets=required_facet_names,
            execute_tools=[],
            execute_rag=initial_route.use_qdrant,
            reference_needed=has_pronoun,
        )
        return RouteReviewResult(
            reviewed_route=initial_route,
            execution_requirements=exec_reqs,
            review_reason="No route review interception required. Retained initial routing decision.",
            intercepted=False,
            clarification=clarification,
            reviewed_clarification=clarification,
        )
