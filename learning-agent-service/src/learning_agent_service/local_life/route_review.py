from __future__ import annotations

import dataclasses
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence

from .query_router import LocalLifeRouteDecision
from .schemas import ClarificationDecision, RouteExecutionRequirement, RouteReviewResult, UserNeed, SuggestedReply


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
        
        # 优先使用 TargetShopPolicy 从 session 继承实体
        from .target_shop_policy import TargetShopPolicy
        from .entity_resolver import _explicit_entity_from_query
        explicit_entity = _explicit_entity_from_query(user_need.raw_query)
        target_shop = TargetShopPolicy().resolve_target(
            raw_query=user_need.raw_query,
            slots=user_need.slots,
            session_context=session_context,
            explicit_entity=explicit_entity
        )
        
        resolved_shop_id = None
        candidate_shop_ids = []
        
        if target_shop.shop_id:
            resolved_shop_id = target_shop.shop_id
            candidate_shop_ids = [resolved_shop_id]
        elif user_need.context_refs:
            for ref in user_need.context_refs:
                if ref.type == "shop" and ref.id:
                    try:
                        resolved_shop_id = int(ref.id)
                        candidate_shop_ids = [resolved_shop_id]
                        break
                    except (ValueError, TypeError):
                        pass

        required_facet_names = [f.name for f in user_need.required_facets]
        if not required_facet_names:
            query_text = (user_need.raw_query or "").replace(" ", "")
            inferred_facet_names: list[str] = []
            coupon_tokens = ("券", "优惠", "领券", "打折", "代金券", "折扣", "有券", "团购")
            open_tokens = ("营业", "开门", "开着", "营业时间", "现在营业吗", "现在开吗", "营业吗")
            distance_tokens = ("距离", "有多远", "导航", "路线", "怎么走", "怎么去")

            if any(token in query_text for token in coupon_tokens):
                inferred_facet_names.append("coupon")
            if any(token in query_text for token in open_tokens):
                inferred_facet_names.append("open_status")
            if any(token in query_text for token in distance_tokens):
                inferred_facet_names.append("distance_eta")

            if inferred_facet_names:
                required_facet_names = inferred_facet_names
        print(f"[DEBUG RouteReview] resolved_shop_id={resolved_shop_id}, required_facet_names={required_facet_names}, session_context={session_context}, target_shop={target_shop}, explicit_entity={explicit_entity}")
        # DAY3 HARDENING: Front-end Routing Interception for Coupon queries without explicit target shops
        is_coupon_query = "coupon" in required_facet_names or any(x in user_need.raw_query for x in ["券", "优惠", "代金券", "团购"])
        has_no_target_shop = not resolved_shop_id and not (target_shop and (target_shop.shop_id or target_shop.shop_name)) and not explicit_entity
        
        if is_coupon_query and has_no_target_shop:
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

        # Extract facets for easier checking
        required_facet_names = [f.name for f in user_need.required_facets]
        has_dynamic_facet = any(name in required_facet_names for name in ("coupon", "open_status", "distance_eta"))
        has_static_facet = any(name in required_facet_names for name in ("scene_fit", "shop_detail", "price"))

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
        # 如果有指代词，但是 context_refs 为空，且利用 TargetShopPolicy 也没能从 Session 继承实体，才触发澄清
        if has_pronoun:
            from .target_shop_policy import TargetShopPolicy
            from .entity_resolver import _explicit_entity_from_query
            explicit_entity = _explicit_entity_from_query(user_need.raw_query)
            target_shop = TargetShopPolicy().resolve_target(
                raw_query=user_need.raw_query,
                slots=user_need.slots,
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
            
            # Case 5: Retain slot clarification for vague nearby queries without location
            elif not has_location_ctx:
                new_clarification = ClarificationDecision(need_clarification=False)
                reviewed_route = LocalLifeRouteDecision(
                    route="structured_first",
                    retrieval_strategy="business_candidates->parent_child_rag->shop_rerank",
                    route_reason="default_nearby_recommendation",
                    candidate_shop_ids=(),
                    use_business_candidates=True,
                    use_qdrant=True,
                )
                exec_reqs = RouteExecutionRequirement(
                    required_facets=[],
                    execute_tools=[],
                    execute_rag=True,
                    reference_needed=False,
                )
                return RouteReviewResult(
                    reviewed_route=reviewed_route,
                    execution_requirements=exec_reqs,
                    review_reason="Vague nearby recommendation query without location context defaults to broad recommendation search.",
                    intercepted=True,
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

            reviewed_route = LocalLifeRouteDecision(
                route="realtime_tool",
                retrieval_strategy="java_business_tool_only",
                route_reason="dynamic_single_facet_query",
                candidate_shop_ids=initial_route.candidate_shop_ids,
                parent_top_k=0,
                child_top_k=0,
                sibling_limit_per_parent=0,
                preferred_roles=(),
                use_business_candidates=True,
                use_qdrant=False,  # Exclude Qdrant retrieval for pure dynamic facet
                extra=initial_route.extra,
            )

            exec_reqs = RouteExecutionRequirement(
                required_facets=required_facet_names,
                execute_tools=tools_to_run,
                execute_rag=False,
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
                candidate_shop_ids=initial_route.candidate_shop_ids,
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
                candidate_shop_ids=initial_route.candidate_shop_ids,
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
