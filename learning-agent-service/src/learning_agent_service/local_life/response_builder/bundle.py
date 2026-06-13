from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from learning_agent_service.domain.utils import as_mapping as _as_mapping, clean_text as _clean_text
from learning_agent_service.local_life.answer_contract import AnswerContract
from learning_agent_service.local_life.answer_depth_policy import derive_answer_depth_policy
from learning_agent_service.local_life.answer_linter import lint_answer, prune_context_for_contract
from learning_agent_service.local_life.answer_planner import EvidencePack, GroundedVerificationResult, LocalLifeAnswerPlan
from learning_agent_service.local_life.answer_quality_gate import AnswerQualityGate
from learning_agent_service.local_life.answer_sanitizer import sanitize_local_life_output
from learning_agent_service.local_life.final_answer_safety import apply_final_answer_safety
from learning_agent_service.local_life.evidence_scope_guard import EvidenceScopeGuard
from learning_agent_service.local_life.facet_result_bundle import FacetResultBundle
from learning_agent_service.local_life.schemas import (
    EvidenceClaim,
    LocalLifeResponseBundle,
    LocalLifeSlots,
    RankedCandidate,
)

from .answers import (
    _answer_realtime_claim_supported,
    _as_evidence_pack,
    _as_plan,
    _as_verification,
    _build_coupon_environment_answer,
    _build_facet_driven_answer,
    _build_guardrail_degraded_answer,
    _candidate_reason,
    _evidence_quality_counts,
    _format_distance,
    _format_price,
    _infer_topic_from_query,
    _merge_unique_text,
    _normalize_suggested_replies,
    build_coupon_only_answer,
    build_distance_only_answer,
    build_multi_shop_recommendation_answer,
    build_open_status_only_answer,
    build_single_shop_review_answer,
    validate_answer_against_contract,
)
from .presentation import (
    _build_citations,
    _build_citations_from_answer_plan,
    _build_next_steps,
    _build_shop_card,
    _build_suggested_replies,
    _build_task_chain,
    _build_voucher_card,
    _confidence_to_score,
    _filter_citations_by_shop_ids,
    _reply_items_from_strings,
)

def build_response_bundle(
    *,
    raw_query: str,
    slots: LocalLifeSlots,
    answer_contract: AnswerContract | None = None,
    ranked_candidates: Sequence[RankedCandidate],
    evidence_claims: Sequence[EvidenceClaim],
    answer_plan: Mapping[str, Any] | LocalLifeAnswerPlan | None = None,
    verification_result: Mapping[str, Any] | GroundedVerificationResult | None = None,
    evidence_pack: Mapping[str, Any] | EvidencePack | None = None,
    page: str | None,
    current_topic: str | None,
    selected_shop_id: int | None,
    current_shop: str | None = None,
    source: str = "local-life-agent",
    fallback: bool = False,
    mode: str = "recommend",
    client_context: Mapping[str, Any] | None = None,
    approval_required: bool = False,
    approval_request: Mapping[str, Any] | None = None,
    transaction_draft: Mapping[str, Any] | None = None,
    safety_result: Mapping[str, Any] | None = None,
    route_decision: str | None = None,
    route_reason: str | None = None,
    current_stage: str | None = None,
    stage_status: str | None = None,
    stage_timeline: Sequence[Mapping[str, Any]] | None = None,
    model_hint: Mapping[str, Any] | None = None,
    source_mode: str | None = None,
    degraded_reason: str | None = None,
    knowledge_freshness: Mapping[str, Any] | None = None,
    user_need: Any | None = None,
    facet_result_bundle: FacetResultBundle | None = None,
    graph_trace: Mapping[str, Any] | None = None,
) -> LocalLifeResponseBundle:
    client_context = dict(client_context or {})
    approval_request = dict(approval_request or {})
    transaction_draft = dict(transaction_draft or {})
    safety_result = dict(safety_result or {})
    model_hint = _as_mapping(model_hint)
    current_shop = _clean_text(current_shop) or _clean_text(model_hint.get("current_shop"))
    source_mode = source_mode or _clean_text(model_hint.get("source_mode"))
    degraded_reason = degraded_reason or (
        _clean_text(model_hint.get("degraded_reason"))
        if source_mode != "java_business"
        else None
    )
    route_reason = route_reason or _clean_text(model_hint.get("route_reason"))
    knowledge_freshness = dict(knowledge_freshness or _as_mapping(model_hint.get("knowledge_freshness")))
    graph_trace = _as_mapping(graph_trace)
    graph_input_context: dict[str, Any] = {}
    graph_perception_context: dict[str, Any] = {}
    graph_memory_arbitration: dict[str, Any] = {}
    graph_state_diff: dict[str, Any] = {}
    graph_illegal_state_mutation: list[dict[str, Any]] = []
    graph_node_writes: list[dict[str, Any]] = []
    nodes_visited: list[str] = []
    model_illegal_state_mutation: list[dict[str, Any]] = []
    model_node_writes: list[dict[str, Any]] = []
    ranked_candidates = list(ranked_candidates)
    answer_plan_model = _as_plan(answer_plan) or _as_plan(model_hint.get("answer_plan"))
    verification_model = _as_verification(verification_result) or _as_verification(model_hint.get("verification_result"))
    evidence_pack_model = _as_evidence_pack(evidence_pack) or _as_evidence_pack(model_hint.get("evidence_pack"))
    compact_query = (raw_query or "").replace(" ", "")
    recommendation_like_query = any(
        token in compact_query
        for token in ("附近", "周边", "推荐", "几家", "多推荐", "多家")
    )
    current_topic = current_topic or slots.category or slots.scene or "本地生活推荐"
    inferred_topic = _infer_topic_from_query(raw_query)
    if inferred_topic:
        current_topic = inferred_topic
        if not current_shop or current_shop in {"本地生活推荐", slots.category, slots.scene}:
            current_shop = inferred_topic
    model_answer = _clean_text(model_hint.get("answer_text"))
    req_facet_names = [f.name for f in getattr(user_need, "required_facets", []) or []] if user_need is not None else []
    compact_query = (raw_query or "").replace(" ", "")
    recommendation_like_query = any(
        token in compact_query
        for token in ("附近", "周边", "推荐", "几家", "多推荐", "多家")
    )
    user_slots = getattr(user_need, "slots", None)
    explicit_shop_hint = bool(selected_shop_id is not None or current_shop) or bool(getattr(user_slots, "shop_id", None) not in (None, "")) or bool(_clean_text(getattr(user_slots, "shop_name", None))) or bool(_clean_text(getattr(user_slots, "shop_query", None)))
    if (
        answer_contract is not None
        and answer_contract.answer_style == "multi_shop_recommendation"
        and not recommendation_like_query
        and explicit_shop_hint
        and str(getattr(user_need, "intent", "") or "").strip() == "merchant_detail"
    ):
        answer_contract = answer_contract.model_copy(
            update={
                "answer_style": "single_shop_review",
                "allow_recommendation": False,
                "allow_extra_context": True,
                "evidence_policy": "balanced",
            }
        )
    if recommendation_like_query:
        if answer_contract is None:
            answer_contract = AnswerContract(
                original_query=raw_query,
                allowed_facets=["environment", "taste", "service", "recommendation", "scene_fit", "coupon", "open_status", "distance_eta", "price", "shop_detail", "recommendation_reason"],
                forbidden_facets=[],
                allowed_tools=["search_restaurants", "getShopDetail", "recommendShops"],
                allowed_rag_facets=["environment", "taste", "service", "recommendation", "scene_fit", "coupon", "open_status", "distance_eta", "price", "shop_detail", "recommendation_reason"],
                forbidden_rag_facets=[],
                realtime_facets=[],
                allow_recommendation=True,
                allow_extra_context=True,
                realtime_required=False,
                evidence_policy="balanced",
                answer_style="multi_shop_recommendation",
                missing_info_policy="say_unknown",
            )

    # Early fallback check for single shop mode if no candidates are found (P0-Fix)
    # Skip early fallback for multi-facet queries – let _build_facet_driven_answer
    # handle them so all facets (coupon, open_status, etc.) are represented.
    # Also skip in clarify mode since the clarification question should be used.
    _req_facet_count = len(getattr(user_need, "required_facets", None) or []) if user_need else 0
    print(f"[DEBUG response_builder] raw_query: {raw_query}, ranked_candidates: {ranked_candidates}, current_shop: {current_shop}, selected_shop_id: {selected_shop_id}")
    generic_shop_names = {"这家店", "这家", "这店", "该商家", "商家", "当前店家"}
    has_specific_shop_context = bool(current_shop and str(current_shop).strip() not in generic_shop_names)
    if not ranked_candidates and has_specific_shop_context and _req_facet_count <= 1 and mode != "clarify":
        shop_name = current_shop or f"商户{selected_shop_id}"
        import re as _re
        if _re.match(r"^shop:\d+$", str(shop_name)):
            shop_name = "该商家"
        query_text = str(raw_query or "").replace(" ", "")
        has_coupon_query = "券" in query_text or "优惠" in query_text or mode == "coupon" or (
            user_need and any(getattr(f, "name", str(f)) == "coupon" for f in getattr(user_need, "required_facets", []) or [])
        )
        has_open_query = any(token in query_text for token in ("营业", "开门", "开着", "营业时间", "现在营业吗", "现在开吗", "营业吗")) or mode == "open_status" or (
            user_need and any(getattr(f, "name", str(f)) == "open_status" for f in getattr(user_need, "required_facets", []) or [])
        )
        if has_coupon_query:
            answer_text = model_answer or f"{shop_name}实时接口暂无可用券。"
        elif has_open_query:
            answer_text = model_answer or f"{shop_name}暂时无法确认当前营业状态。"
        elif answer_contract is not None and answer_contract.answer_style == "single_shop_review":
            answer_text = model_answer or build_single_shop_review_answer(shop_name, [], evidence_claims)
        else:
            answer_text = model_answer or f"抱歉，系统里暂时没有查到{shop_name}的相关信息。"
        

        bundle = LocalLifeResponseBundle(
            answer_text=answer_text,
            mode=mode,
            source=source,
            source_mode=source_mode,
            degraded_reason=degraded_reason,
            knowledge_freshness=knowledge_freshness,
            fallback=fallback,
            page=page,
            current_topic=current_topic,
            selected_shop_id=selected_shop_id,
            route_decision=route_decision,
            route_reason=route_reason,
            current_stage=current_stage,
            stage_status=stage_status,
            stage_timeline=[dict(item) for item in stage_timeline or []],
            cards=[],
            shops=[],
            vouchers=[],
            suggested_replies=_build_suggested_replies(slots, [], model_hint=model_hint)[:5],
            next_steps=_build_next_steps(mode=mode, ranked_candidates=[]),
            task_chain=_build_task_chain(mode=mode, ranked_candidates=[]),
            ranked_candidates=[],
            citations=[],
            retrieval_summary={
                "retrieval_strategy": "hybrid_catalog+java_business",
                "retrieval_hit_count": 0,
                "evidence_used_count": 0,
                "route_decision": route_decision,
                "route_reason": route_reason,
                "current_stage": current_stage,
                "stage_status": stage_status,
                "source_mode": source_mode,
                "degraded_reason": degraded_reason,
                "knowledge_freshness": knowledge_freshness,
                "model_hint_used": bool(model_hint),
            },
            grounding_status="not_grounded",
            confidence=0.5,
            approval_required=approval_required,
            approval_request=dict(approval_request or {}),
            transaction_draft=dict(transaction_draft or {}),
            safety_result=dict(safety_result or {}),
            metrics={
                "candidate_count": 0,
                "evidence_count": 0,
                "source_mode": source_mode,
                "degraded_reason": degraded_reason,
                "knowledge_freshness": knowledge_freshness,
                "model_hint_used": bool(model_hint),
                "next_steps_count": 0,
                "task_chain_count": 0,
                "answer_contract": answer_contract.model_dump(mode="json") if answer_contract is not None else None,
            },
            context={
                "raw_query": raw_query,
                "current_topic": current_topic,
                "current_shop": current_shop,
                "selected_shop_id": selected_shop_id,
                "selected_shop_name": current_shop,
                "slots": slots.model_dump(mode="json"),
                "client_context": dict(client_context or {}),
                "approval_request": dict(approval_request or {}),
                "transaction_draft": dict(transaction_draft or {}),
                "safety_result": dict(safety_result or {}),
                "route_decision": route_decision,
                "route_reason": route_reason,
                "current_stage": current_stage,
                "stage_status": stage_status,
                "stage_timeline": [dict(item) for item in stage_timeline or []],
                "source_mode": source_mode,
                "degraded_reason": degraded_reason,
                "knowledge_freshness": knowledge_freshness,
                "model_hint_used": bool(model_hint),
                "input_context": graph_input_context or _as_mapping(model_hint.get("input_context")),
                "perception_context": graph_perception_context or _as_mapping(model_hint.get("perception_context")),
                "memory_arbitration": graph_memory_arbitration or _as_mapping(model_hint.get("memory_arbitration")),
                "state_diff": graph_state_diff or _as_mapping(model_hint.get("state_diff")),
                "illegal_state_mutation": graph_illegal_state_mutation or model_illegal_state_mutation,
                "node_writes": graph_node_writes or model_node_writes,
                "nodes_visited": nodes_visited,
            },
        )
        return bundle

    dynamic_facet_names = {"coupon", "open_status", "distance_eta"}
    multi_dynamic_facet_query = len([name for name in req_facet_names if name in dynamic_facet_names]) > 1
    plan_usable = (
        bool(answer_plan_model)
        and bool(verification_model is None or verification_model.passed)
        and not multi_dynamic_facet_query
    )
    allowed_shop_ids = EvidenceScopeGuard.allowed_shop_ids(ranked_candidates=ranked_candidates, evidence_pack=evidence_pack_model)
    if allowed_shop_ids:
        ranked_candidates = [
            candidate
            for candidate in ranked_candidates
            if int(candidate.shop_id) in allowed_shop_ids
        ]
        evidence_claims = [
            claim
            for claim in evidence_claims
            if getattr(claim, "shop_id", None) in allowed_shop_ids
        ]
    if plan_usable and answer_plan_model is not None:
        answer_text = answer_plan_model.answer_text or answer_plan_model.recommendation_summary or model_answer or ""
        if approval_required and answer_plan_model.decision_type in {"booking", "order"}:
            action_label = "订座" if answer_plan_model.decision_type == "booking" else "下单"
            answer_text = (
                f"我已经为你整理好{action_label}草案，确认后我再继续执行，避免直接误操作。"
                + (f"\n\n{answer_text}" if answer_text else "")
            )
        elif approval_required:
            answer_text = (
                "当前这个请求需要你确认后我再继续执行，先给你整理成草案，避免直接误操作。"
                + (f"\n\n{answer_text}" if answer_text else "")
            )

    elif approval_required and transaction_draft:
        action = transaction_draft.get("action") or mode
        action_label = {
            "booking": "订座",
            "order": "下单",
            "cancel": "取消",
            "refund": "退款",
        }.get(str(action), str(action))
        shop_name = transaction_draft.get("shop_name") or current_topic
        answer_text = (
            f"我已经为你整理好{action_label}草案：{shop_name or '目标商户'}。"
            "确认后我再继续执行，避免直接误操作。"
        )
        if model_answer:
            answer_text = f"{answer_text}\n\n{model_answer}"
    elif str(route_decision or "").strip().lower() == "rag_plus_tool":
        answer_text = _build_facet_driven_answer(
            current_topic=current_topic,
            ranked_candidates=ranked_candidates,
            evidence_claims=evidence_claims,
            user_need=user_need,
            facet_result_bundle=facet_result_bundle,
        )
    elif recommendation_like_query:
        answer_text = build_multi_shop_recommendation_answer(
            current_topic,
            ranked_candidates,
            evidence_claims,
            user_need=user_need,
            facet_result_bundle=facet_result_bundle,
        )
    elif user_need is not None and getattr(user_need, "required_facets", None):
        answer_text = _build_facet_driven_answer(
            current_topic=current_topic,
            ranked_candidates=ranked_candidates,
            evidence_claims=evidence_claims,
            user_need=user_need,
            facet_result_bundle=facet_result_bundle,
        )
    elif ranked_candidates:
        summary = model_answer or "我按“{summary}”筛了一下，优先推荐这几家：".format(
            summary="、".join(
                item
                for item in [
                    "离你近" if slots.location.type == "near_user" else None,
                    "人均预算合适" if slots.price.target is not None else None,
                    "适合带爸妈" if slots.scene == "family_dinner" else None,
                    "环境别太吵" if "quiet" in slots.preferences else None,
                    "有停车" if "parking_available" in slots.preferences else None,
                ]
                if item
            )
            or "你的条件"
        )
        lines = [summary, ""]
        for index, candidate in enumerate(ranked_candidates[:3], start=1):
            score_value = candidate.structured_features.get("score")
            score_text = f"{float(score_value):.1f}" if score_value is not None else "0.0"
            lines.append(
                "{index}. {name}，距你约{distance}，人均约{price}，评分{score}。{reason}".format(
                    index=index,
                    name=candidate.name,
                    distance=_format_distance(candidate.structured_features.get("distance_km")),
                    price=_format_price(candidate.structured_features.get("avg_price")),
                    score=score_text,
                    reason=_candidate_reason(candidate),
                )
            )
        if len(ranked_candidates) >= 2:
            lines.append("如果你愿意，我也可以继续帮你对比前两家，或者只看今晚可订的。")
        answer_text = "\n".join(lines)
    else:
        if current_shop or selected_shop_id:
            shop_name = current_shop or f"商户{selected_shop_id}"
            import re as _re
            if _re.match(r"^shop:\d+$", str(shop_name)):
                shop_name = "该商家"
            if answer_contract is not None and answer_contract.answer_style == "single_shop_review":
                answer_text = build_single_shop_review_answer(shop_name, ranked_candidates, evidence_claims)
            elif answer_contract is not None and answer_contract.answer_style == "multi_shop_recommendation" and answer_contract.realtime_required:
                answer_text = "我暂时没有找到同时满足这些实时条件的商家，建议以店铺页面实时信息为准。"
            else:
                answer_text = model_answer or f"抱歉，系统里暂时没有查到{shop_name}的相关信息。"
        else:
            if answer_contract is not None and answer_contract.answer_style == "multi_shop_recommendation" and answer_contract.realtime_required:
                answer_text = "我暂时没有找到同时满足这些实时条件的商家，建议以店铺页面实时信息为准。"
            else:
                answer_text = model_answer or "我暂时没有筛到特别合适的店，你可以再补充一下口味、预算或者距离，我继续帮你找。"

    dynamic_facet_names = {"coupon", "open_status", "distance_eta"}
    if user_need is not None and len([name for name in req_facet_names if name in dynamic_facet_names]) > 1:
        answer_text = _build_facet_driven_answer(
            current_topic=current_topic,
            ranked_candidates=ranked_candidates,
            evidence_claims=evidence_claims,
            user_need=user_need,
            facet_result_bundle=facet_result_bundle,
        )

    # Ensure answer_contract style is respected for building response text
    # Skip answer_contract override in clarify mode – the model_answer
    # already carries the clarification question and must not be replaced.
    if answer_contract is not None and mode != "clarify" and not plan_usable:
        guardrail_degraded_answer = _build_guardrail_degraded_answer(
            answer_contract=answer_contract,
            evidence_pack=evidence_pack_model,
            current_topic=current_topic,
        )
        if guardrail_degraded_answer:
            answer_text = guardrail_degraded_answer
        elif answer_contract.answer_style == "coupon_only":
            answer_text = build_coupon_only_answer(current_topic, ranked_candidates, evidence_claims, facet_result_bundle=facet_result_bundle)
        elif answer_contract.answer_style == "open_status_only":
            answer_text = build_open_status_only_answer(current_topic, ranked_candidates, evidence_claims, facet_result_bundle=facet_result_bundle)
        elif answer_contract.answer_style == "distance_only":
            answer_text = build_distance_only_answer(current_topic, ranked_candidates, evidence_claims, facet_result_bundle=facet_result_bundle)
        elif answer_contract.answer_style == "single_shop_review":
            answer_text = build_single_shop_review_answer(current_topic, ranked_candidates, evidence_claims)
        elif answer_contract.answer_style == "facet_multi":
            answer_text = _build_facet_driven_answer(
                current_topic=current_topic,
                ranked_candidates=ranked_candidates,
                evidence_claims=evidence_claims,
                user_need=user_need,
                facet_result_bundle=facet_result_bundle,
            )
        elif answer_contract.answer_style == "multi_shop_recommendation":
            answer_text = build_multi_shop_recommendation_answer(
                current_topic,
                ranked_candidates,
                evidence_claims,
                user_need=user_need,
                facet_result_bundle=facet_result_bundle,
            )
        answer_text = validate_answer_against_contract(
            answer_text=answer_text,
            answer_contract=answer_contract,
            topic_name=current_topic,
            ranked_candidates=ranked_candidates,
            evidence_claims=evidence_claims,
            facet_result_bundle=facet_result_bundle,
            user_need=user_need,
        )
    elif answer_contract is not None and answer_contract.answer_style == "comparison":
        pass # Keep original comparison text
    elif answer_contract is not None and answer_contract.answer_style == "clarification":
        pass # Keep original clarify text

    query_text = str(raw_query or "").replace(" ", "")
    coupon_query = any(token in query_text for token in ("券", "优惠", "团购", "代金券"))
    open_query = any(token in query_text for token in ("营业", "开门", "开着", "营业时间", "现在营业吗", "现在开吗", "营业吗"))
    distance_query = any(token in query_text for token in ("距离", "有多远", "导航", "路线", "怎么走", "怎么去"))
    scene_query = any(token in query_text for token in ("环境", "氛围", "场景", "适合", "口味", "服务", "推荐"))
    generic_topic_names = {"这家店", "这家", "这店", "该商家", "商家", "当前店家"}
    has_specific_topic = bool(str(current_topic or "").strip() and str(current_topic or "").strip() not in generic_topic_names)
    if has_specific_topic and coupon_query and not (open_query or distance_query or scene_query):
        coupon_answer = build_coupon_only_answer(
            topic_name=current_topic or "这家店",
            ranked_candidates=ranked_candidates,
            evidence_claims=evidence_claims,
            facet_result_bundle=facet_result_bundle,
        )
        if coupon_answer:
            answer_text = coupon_answer

    if (
        model_answer
        and answer_contract is None
        and not plan_usable
        and str(route_decision or "").strip().lower() != "rag_plus_tool"
        and not answer_text.startswith(model_answer)
    ):
        answer_text = f"{model_answer}\n{answer_text}" if answer_text else model_answer

    draft_answer_before_quality = answer_text
    clean_evidence_count, strong_evidence_count, medium_evidence_count = _evidence_quality_counts(evidence_claims)
    answer_depth_policy = derive_answer_depth_policy(
        answer_contract,
        clean_evidence_count=clean_evidence_count,
        strong_evidence_count=strong_evidence_count,
        medium_evidence_count=medium_evidence_count,
    )
    quality_gate = AnswerQualityGate()
    quality_result = quality_gate.finalize(
        draft_answer=draft_answer_before_quality,
        answer_contract=answer_contract,
        answer_depth_policy=answer_depth_policy,
        clean_evidence_count=clean_evidence_count,
        strong_evidence_count=strong_evidence_count,
        medium_evidence_count=medium_evidence_count,
        topic_name=current_topic,
        ranked_candidates=ranked_candidates,
        evidence_claims=list(evidence_claims),
        user_need=user_need,
        facet_result_bundle=facet_result_bundle,
    )
    answer_text = quality_result.final_answer

    if answer_plan_model is not None and verification_model is not None and verification_model.passed:
        if approval_required:
            answer_text = draft_answer_before_quality
        elif answer_plan_model.answer_text:
            answer_text = answer_plan_model.answer_text

    if (
        model_answer
        and answer_contract is None
        and not plan_usable
        and str(route_decision or "").strip().lower() != "rag_plus_tool"
        and not answer_text.startswith(model_answer)
    ):
        answer_text = f"{model_answer}\n{answer_text}" if answer_text else model_answer

    if model_answer and source_mode == "java_business":
        model_index = answer_text.find(model_answer)
        if model_index > 0:
            prefix = answer_text[:model_index]
            if prefix.rstrip().endswith(("：", ":")):
                answer_text = answer_text[model_index:]



    cards: list[dict[str, Any]] = []
    shops: list[dict[str, Any]] = []
    vouchers: list[dict[str, Any]] = []
    
    count = 3
    if user_need is not None and hasattr(user_need, "recommendation_count"):
        count = user_need.recommendation_count

    for candidate in ranked_candidates[:count]:
        cards.append(_build_shop_card(candidate))
        shops.append(
            {
                "id": candidate.shop_id,
                "name": candidate.name,
                "area": candidate.structured_features.get("area"),
                "address": candidate.structured_features.get("address"),
                "avgPrice": candidate.structured_features.get("avg_price"),
                "score": candidate.structured_features.get("score"),
                "comments": candidate.structured_features.get("comments"),
                "openHours": candidate.structured_features.get("open_hours"),
                "image": candidate.structured_features.get("image"),
                "distance": candidate.structured_features.get("distance_km"),
                "reason": _candidate_reason(candidate),
            }
        )
        for voucher in candidate.vouchers[:2]:
            voucher_card = _build_voucher_card(candidate, voucher)
            cards.append(voucher_card)
            vouchers.append(
                {
                    "id": voucher.get("id"),
                    "shopId": candidate.shop_id,
                    "shopName": candidate.name,
                    "title": voucher.get("title"),
                    "subTitle": voucher.get("sub_title") or voucher.get("subTitle"),
                    "payValue": voucher.get("pay_value") or voucher.get("payValue"),
                    "actualValue": voucher.get("actual_value") or voucher.get("actualValue"),
                    "stock": voucher.get("stock"),
                    "beginTime": voucher.get("begin_time") or voucher.get("beginTime"),
                    "endTime": voucher.get("end_time") or voucher.get("endTime"),
                    "rules": voucher.get("rules"),
                }
            )

    if not cards and ranked_candidates:
        cards = [_build_shop_card(candidate) for candidate in ranked_candidates[:count]]
    if not vouchers:
        for candidate in ranked_candidates[:count]:
            if candidate.vouchers:
                vouchers.extend(
                    {
                        "id": voucher.get("id"),
                        "shopId": candidate.shop_id,
                        "shopName": candidate.name,
                        "title": voucher.get("title"),
                        "subTitle": voucher.get("sub_title") or voucher.get("subTitle"),
                        "payValue": voucher.get("pay_value") or voucher.get("payValue"),
                        "actualValue": voucher.get("actual_value") or voucher.get("actualValue"),
                        "stock": voucher.get("stock"),
                        "beginTime": voucher.get("begin_time") or voucher.get("beginTime"),
                        "endTime": voucher.get("end_time") or voucher.get("endTime"),
                        "rules": voucher.get("rules"),
                    }
                    for voucher in candidate.vouchers[:2]
                )

    plan_suggested_replies = _reply_items_from_strings(answer_plan_model.suggested_replies) if plan_usable and answer_plan_model is not None else []
    model_suggested_replies = _normalize_suggested_replies(model_hint.get("suggested_replies"))
    suggested_replies = _build_suggested_replies(
        slots,
        ranked_candidates,
        approval_required=approval_required,
        model_hint=model_hint,
    )
    if plan_suggested_replies:
        seen_pairs = {(str(item.get("label") or ""), str(item.get("prompt") or "")) for item in plan_suggested_replies}
        suggested_replies = [
            *plan_suggested_replies,
            *[
                item
                for item in suggested_replies
                if (str(item.get("label") or ""), str(item.get("prompt") or "")) not in seen_pairs
            ],
        ]
    elif model_suggested_replies:
        seen_pairs = {(str(item.get("label") or ""), str(item.get("prompt") or "")) for item in model_suggested_replies}
        suggested_replies = [
            *model_suggested_replies,
            *[
                item
                for item in suggested_replies
                if (str(item.get("label") or ""), str(item.get("prompt") or "")) not in seen_pairs
            ],
        ]

    if plan_usable and answer_plan_model is not None and answer_plan_model.next_actions:
        next_steps = _merge_unique_text(action.label for action in answer_plan_model.next_actions)
    else:
        next_steps = _build_next_steps(
            mode=mode,
            ranked_candidates=ranked_candidates,
            approval_required=approval_required,
            transaction_draft=transaction_draft,
        )
    if source_mode == "java_business" and (current_shop or selected_shop_id) and not ranked_candidates:
        next_steps = _merge_unique_text(["查看第一家详情", *next_steps])
    task_chain = _build_task_chain(
        mode=mode,
        ranked_candidates=ranked_candidates,
        approval_required=approval_required,
        transaction_draft=transaction_draft,
        next_steps=next_steps,
    )
    if plan_usable and answer_plan_model is not None:
        citations = _build_citations_from_answer_plan(
            answer_plan=answer_plan_model,
            evidence_pack=evidence_pack_model,
            evidence_claims=evidence_claims,
        )
    else:
        citations = _build_citations(evidence_claims)
    citations = _filter_citations_by_shop_ids(citations, allowed_shop_ids)

    retrieval_summary = {
        "retrieval_strategy": "hybrid_catalog+java_business",
        "retrieval_hit_count": len(ranked_candidates),
        "evidence_used_count": len(evidence_claims),
        "route_decision": route_decision,
        "route_reason": route_reason,
        "current_stage": current_stage,
        "stage_status": stage_status,
        "source_mode": source_mode,
        "degraded_reason": degraded_reason,
        "knowledge_freshness": knowledge_freshness,
        "model_hint_used": bool(model_hint) or bool(answer_plan_model),
    }
    grounding_status = "grounded" if evidence_claims else "weakly_grounded" if ranked_candidates else "not_grounded"
    confidence = (
        _confidence_to_score(answer_plan_model.confidence)
        if plan_usable and answer_plan_model is not None
        else round(min(0.98, 0.55 + 0.08 * len(ranked_candidates[:3]) + 0.03 * len(evidence_claims)), 3)
    )
    stage_timeline_payload = [dict(item) for item in stage_timeline or []]
    graph_input_context = _as_mapping(graph_trace.get("input_context"))
    graph_perception_context = _as_mapping(graph_trace.get("perception_context"))
    graph_memory_arbitration = _as_mapping(graph_trace.get("memory_arbitration"))
    graph_state_diff = _as_mapping(graph_trace.get("state_diff"))
    graph_illegal_state_mutation = [dict(item) for item in graph_trace.get("illegal_state_mutation") or [] if isinstance(item, Mapping)]
    graph_node_writes = [dict(item) for item in graph_trace.get("node_writes") or [] if isinstance(item, Mapping)]
    nodes_visited = list(dict.fromkeys([str(item.get("stage") or item.get("node") or "").strip() for item in stage_timeline_payload if isinstance(item, Mapping) and str(item.get("stage") or item.get("node") or "").strip()] + [str(item).strip() for item in graph_trace.get("nodes_visited") or [] if str(item).strip()]))
    raw_model_illegal_state_mutation: Any = model_hint.get("illegal_state_mutation")
    if isinstance(raw_model_illegal_state_mutation, Mapping):
        model_illegal_state_mutation = [dict(raw_model_illegal_state_mutation)]
    elif isinstance(raw_model_illegal_state_mutation, list):
        model_illegal_state_mutation = [dict(item) for item in raw_model_illegal_state_mutation if isinstance(item, Mapping)]
    else:
        model_illegal_state_mutation = []
    raw_model_node_writes: Any = model_hint.get("node_writes")
    if isinstance(raw_model_node_writes, list):
        model_node_writes = [dict(item) for item in raw_model_node_writes if isinstance(item, Mapping)]
    else:
        model_node_writes = []
    metrics: dict[str, Any] = {
        "candidate_count": len(ranked_candidates),
        "evidence_count": len(evidence_claims),
        "source_mode": source_mode,
        "degraded_reason": degraded_reason,
        "knowledge_freshness": knowledge_freshness,
        "model_hint_used": bool(model_hint) or bool(answer_plan_model),
        "next_steps_count": len(next_steps),
        "task_chain_count": len(task_chain),
        "answer_plan_enabled": bool(answer_plan_model),
        "answer_plan_valid": bool(plan_usable),
        "answer_plan_confidence": answer_plan_model.confidence if answer_plan_model is not None else None,
        "evidence_pack_item_count": len(evidence_pack_model.items) if evidence_pack_model is not None else 0,
        "verifier_passed": verification_model.passed if verification_model is not None else None,
        "verifier_warnings": list(verification_model.warnings) if verification_model is not None else [],
        "answer_contract": answer_contract.model_dump(mode="json") if answer_contract is not None else None,
        "answer_depth_policy": (
            {
                "answer_style": quality_result.answer_style,
                "depth_level": quality_result.answer_depth_level,
                "min_sections": quality_result.answer_min_sections,
                "min_chars": quality_result.answer_min_chars,
                "clean_evidence_count": quality_result.clean_evidence_count,
                "strong_evidence_count": quality_result.strong_evidence_count,
                "medium_evidence_count": quality_result.medium_evidence_count,
                "depth_limited_by_evidence": quality_result.depth_limited_by_evidence,
            }
            if quality_result is not None
            else None
        ),
        "repetition_guard": (
            {
                "deduped": quality_result.deduped_by_repetition_guard,
                "duplicate_sentence_count": quality_result.duplicate_sentence_count,
                "duplicate_ratio": quality_result.duplicate_ratio,
                "recommendation_duplicate_shop_count": quality_result.recommendation_duplicate_shop_count,
            }
            if quality_result is not None
            else None
        ),
        "answer_quality": quality_result.model_dump(mode="json") if quality_result is not None else None,
        "answer_realtime_claim_supported": _answer_realtime_claim_supported(
            user_need=user_need,
            facet_result_bundle=facet_result_bundle,
            ranked_candidates=ranked_candidates,
        ),
        "input_context": graph_input_context or _as_mapping(model_hint.get("input_context")),
        "perception_context": graph_perception_context or _as_mapping(model_hint.get("perception_context")),
        "memory_arbitration": graph_memory_arbitration or _as_mapping(model_hint.get("memory_arbitration")),
        "state_diff": graph_state_diff or _as_mapping(model_hint.get("state_diff")),
        "illegal_state_mutation": graph_illegal_state_mutation or model_illegal_state_mutation,
        "node_writes": graph_node_writes or model_node_writes,
        "nodes_visited": nodes_visited,
        "debug_recommendation_like_query": recommendation_like_query,
        "debug_plan_usable": plan_usable,
        "debug_answer_contract_style": answer_contract.answer_style if answer_contract is not None else None,
    }
    if answer_contract is not None:
        metrics.setdefault("answer_style", answer_contract.answer_style)
    else:
        metrics.setdefault("answer_style", None)
    if recommendation_like_query:
        metrics["answer_style"] = "multi_shop_recommendation"
    route_decision_normalized = str(route_decision or "").strip().lower()
    if recommendation_like_query or metrics.get("answer_style") == "multi_shop_recommendation":
        metrics["rag_mode"] = "recommendation_rag"
        metrics.setdefault(
            "route_gate",
            {
                "branch": "recommendation",
                "required_action": "rag_plus_tool",
                "route_candidate": None,
                "route_reason": None,
            },
        )
    elif route_decision_normalized == "clarify":
        metrics.setdefault(
            "route_gate",
            {
                "branch": "clarify",
                "required_action": "clarify",
                "route_candidate": None,
                "route_reason": route_reason,
            },
        )
    elif route_decision_normalized == "rag_plus_tool":
        metrics.setdefault(
            "route_gate",
            {
                "branch": "rag_plus_tool",
                "required_action": "rag_plus_tool",
                "route_candidate": None,
                "route_reason": route_reason,
            },
        )
    elif route_decision_normalized == "tool_call":
        metrics.setdefault(
            "route_gate",
            {
                "branch": "tool",
                "required_action": "tool_call",
                "route_candidate": None,
                "route_reason": route_reason,
            },
        )
    elif selected_shop_id is not None:
        metrics.setdefault("rag_mode", "single_shop_rag")
        metrics.setdefault(
            "route_gate",
            {
                "branch": "rag",
                "required_action": "rag_retrieval",
                "route_candidate": None,
                "route_reason": None,
            },
        )
    evidence_shop_ids: list[int] = []
    for claim in evidence_claims:
        claim_map = claim.model_dump(mode="json") if hasattr(claim, "model_dump") else dict(claim)
        shop_id_value = claim_map.get("shop_id") or (claim_map.get("metadata") or {}).get("shop_id")
        if shop_id_value in (None, ""):
            continue
        try:
            shop_id_int = int(str(shop_id_value))
        except Exception:
            continue
        if shop_id_int not in evidence_shop_ids:
            evidence_shop_ids.append(shop_id_int)
    if not evidence_shop_ids and selected_shop_id is not None:
        evidence_shop_ids = [int(str(selected_shop_id))]
    if evidence_shop_ids:
        metrics["evidence_shop_ids"] = evidence_shop_ids
        metrics["evidence_shop_groups"] = [
            {"shop_id": sid, "evidence_count": evidence_shop_ids.count(sid)}
            for sid in list(dict.fromkeys(evidence_shop_ids))
        ]
    pruning_result = prune_context_for_contract(
        answer_contract,
        ranked_candidates=ranked_candidates,
        evidence_pack=evidence_pack_model,
        evidence_claims=evidence_claims,
    ) if answer_contract is not None else {
        "summary": {
            "answer_style": None,
            "allowed_facets": [],
            "forbidden_facets": [],
            "kept_facets": [],
            "dropped_facets": [],
            "allowed_tools": [],
            "allowed_rag_facets": [],
            "allow_recommendation": False,
            "allow_extra_context": False,
            "realtime_required": False,
            "evidence_policy": "balanced",
            "kept_ranked_candidate_count": len(ranked_candidates),
            "dropped_ranked_candidate_count": 0,
            "kept_evidence_item_count": len(evidence_pack_model.items) if evidence_pack_model is not None else 0,
            "dropped_evidence_item_count": 0,
            "kept_evidence_claim_count": len(evidence_claims),
            "dropped_evidence_claim_count": 0,
        },
        "ranked_candidates": [candidate.model_dump(mode="json") for candidate in ranked_candidates],
        "evidence_pack": evidence_pack_model.model_dump(mode="json") if evidence_pack_model is not None else {},
        "evidence_claims": [claim.model_dump(mode="json") for claim in evidence_claims],
    }
    lint_result = lint_answer(
        answer_text=answer_text,
        answer_contract=answer_contract,
        topic_name=current_topic,
        ranked_candidates=ranked_candidates,
        evidence_claims=evidence_claims,
        facet_result_bundle=facet_result_bundle,
        user_need=user_need,
    ) if answer_contract is not None else None
    metrics["context_pruning"] = dict(_as_mapping(pruning_result.get("summary")))
    metrics["answer_lint"] = lint_result.model_dump(mode="json") if lint_result is not None else {
        "passed": True,
        "severity": "pass",
        "issues": [],
        "forbidden_facets": [],
        "cross_shop_leak": False,
        "unsupported_realtime_claim": False,
        "unsolicited_recommendation": False,
        "repaired_text": None,
    }
    if answer_plan_model is not None:
        metrics["answer_plan_decision_type"] = answer_plan_model.decision_type
        metrics["answer_plan_degraded_reason"] = answer_plan_model.degraded_reason
    if mode == "coupon" and "券信息" not in answer_text and str(getattr(answer_contract, "answer_style", "") or "").strip().lower() != "coupon_only":
        coupon_answer = _build_coupon_environment_answer(
            current_topic=current_topic,
            ranked_candidates=ranked_candidates,
            evidence_claims=evidence_claims,
            user_need=user_need,
            facet_result_bundle=facet_result_bundle,
        )
        if coupon_answer:
            answer_text = coupon_answer
    final_answer_safety = apply_final_answer_safety(
        answer_text=answer_text,
        answer_contract=answer_contract,
        ranked_candidates=ranked_candidates,
        evidence_claims=evidence_claims,
        evidence_pack=evidence_pack_model,
        facet_result_bundle=facet_result_bundle,
        user_need=user_need,
        route_gate={"route_decision": route_decision, "route_reason": route_reason} if route_decision or route_reason else None,
        source_contract=None,
        review_report=None,
        tool_results=[],
    )
    answer_text = final_answer_safety.answer_text
    safety_result = final_answer_safety.to_dict()
    metrics["final_answer_safety"] = safety_result
    metrics["final_answer_audit"] = final_answer_safety.final_answer_audit
    metrics["answer_lint"] = final_answer_safety.answer_lint
    bundle = LocalLifeResponseBundle(
        answer_text=answer_text,
        mode=mode,
        source=source,
        source_mode=source_mode,
        degraded_reason=degraded_reason,
        knowledge_freshness=knowledge_freshness,
        fallback=fallback,
        page=page,
        current_topic=current_topic,
        selected_shop_id=selected_shop_id
        or (
            answer_plan_model.top_choice.shop_id
            if answer_plan_model is not None and answer_plan_model.top_choice is not None
            else (ranked_candidates[0].shop_id if ranked_candidates else None)
        ),
        route_decision=route_decision,
        route_reason=route_reason,
        current_stage=current_stage,
        stage_status=stage_status,
        stage_timeline=stage_timeline_payload,
        cards=cards,
        shops=shops,
        vouchers=vouchers,
        suggested_replies=suggested_replies[:5],
        next_steps=next_steps,
        task_chain=task_chain,
        ranked_candidates=[candidate.model_dump(mode="json") for candidate in ranked_candidates],
        citations=citations,
        retrieval_summary=retrieval_summary,
        grounding_status=grounding_status,
        confidence=confidence,
        approval_required=approval_required,
        approval_request=approval_request,
        transaction_draft=transaction_draft,
        safety_result=safety_result,
        metrics=metrics,
        context={
            "raw_query": raw_query,
            "current_topic": current_topic,
            "current_shop": current_shop,
            "selected_shop_id": selected_shop_id,
            "selected_shop_name": current_shop or (ranked_candidates[0].name if ranked_candidates else None),
            "slots": slots.model_dump(mode="json"),
            "client_context": client_context,
            "approval_request": approval_request,
            "transaction_draft": transaction_draft,
            "safety_result": safety_result,
            "route_decision": route_decision,
            "route_reason": route_reason,
            "current_stage": current_stage,
            "stage_status": stage_status,
            "stage_timeline": stage_timeline_payload,
            "source_mode": source_mode,
            "degraded_reason": degraded_reason,
            "knowledge_freshness": knowledge_freshness,
            "model_hint_used": bool(model_hint),
            "answer_plan": answer_plan_model.model_dump(mode="json") if answer_plan_model is not None else None,
            "answer_verification": verification_model.model_dump(mode="json") if verification_model is not None else None,
            "next_steps": list(next_steps),
            "task_chain": list(task_chain),
            "context_pruning": pruning_result["summary"],
            "answer_lint": metrics["answer_lint"],
        },
    )
    shop_lookup = {
        candidate.shop_id: candidate.name
        for candidate in ranked_candidates
        if getattr(candidate, "shop_id", None) is not None and getattr(candidate, "name", None)
    }
    return sanitize_local_life_output(bundle, shop_lookup=shop_lookup)
