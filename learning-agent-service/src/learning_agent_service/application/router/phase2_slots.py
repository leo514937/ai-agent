from __future__ import annotations

from collections import Counter

from collections.abc import Mapping, Sequence

from typing import Any

from ...domain.contracts import (
    EvidenceItem,
    EvidencePack,
    EvidenceQualityDecision,
)

from .base import (
    _extract_entity_values_from_mapping,
    _normalize_entity_key,
    _phase1_flags,
    _phase2_flags,
)


def _clarification_label_for_slot(slot: str) -> str:

    normalized = str(slot or "").strip().lower()

    if normalized in {"location", "city", "area", "district", "region", "lat", "lng"}:

        return "城市或商圈"

    if normalized in {"shop_id", "shop_name", "shop", "merchant", "merchant_name"}:

        return "店名"

    if normalized in {"shop_detail", "merchant_detail", "detail"}:

        return "门店详情"

    if normalized in {"time", "booking_time", "date", "datetime"}:

        return "时间"

    if normalized in {"voucher_id", "coupon_id", "package_id", "coupon", "package"}:

        return "券或套餐"

    if normalized in {"order_id", "booking_id", "selected_order_id", "selected_booking_id"}:

        return "订单号"

    if normalized in {"category", "type", "type_name"}:

        return "品类"

    if normalized in {"price", "budget", "amount"}:

        return "预算"

    if normalized in {"scene", "scene_fit"}:

        return "场景"

    return normalized or "关键信息"


def _facet_covered_for_phase2(

    facet_name: str,

    *,

    role_tokens: set[str],

    tool_result_present: bool,

    has_matching_shop_evidence: bool,

    city_area_category_consistency: bool,

) -> bool:

    normalized = str(facet_name or "").strip().lower()

    if normalized in {"location", "city", "area"}:

        return city_area_category_consistency

    if normalized in {"scene_fit", "recommendation_reason", "shop_detail"}:

        return bool(role_tokens & {"review", "guide", "detail", "merchant_profile", "merchant_review_summary", "business_evidence"})

    if normalized in {"coupon", "open_status", "distance_eta", "price", "package"}:

        return bool(tool_result_present or role_tokens & {"coupon", "package", "status", "business_evidence", "distance", "navigation"})

    if normalized in {"category", "scene"}:

        return bool(role_tokens or has_matching_shop_evidence)

    if normalized in {"shop_id", "shop_name"}:

        return bool(has_matching_shop_evidence)

    return bool(role_tokens or tool_result_present or has_matching_shop_evidence)


def build_clarification_question(

    missing_slots: Sequence[str] | None = None,

    *,

    clarification_slot: str | None = None,

    required_facets: Sequence[Mapping[str, Any]] | None = None,

    query_text: str | None = None,

    fallback: str | None = None,

) -> str | None:

    normalized_slots = [str(slot).strip().lower() for slot in (missing_slots or []) if str(slot).strip()]

    slot = str(clarification_slot or "").strip().lower() or None



    if not slot and required_facets:

        for facet in required_facets:

            if not isinstance(facet, Mapping):

                continue

            missing_policy = str(facet.get("missing_policy") or "").strip().lower()

            if missing_policy != "ask_clarification":

                continue

            facet_name = str(facet.get("name") or "").strip().lower()

            if facet_name:

                slot = facet_name

                break



    if not slot and normalized_slots:

        slot = normalized_slots[0]



    if not slot:

        text = str(fallback or "").strip()

        return text or None



    if slot in {"location", "city", "area", "district", "region", "lat", "lng"}:

        return "你方便补充一下城市或商圈吗？"

    if slot in {"shop_id", "shop_name", "shop", "merchant", "merchant_name"}:

        return "你是指刚才那家店，还是要重新推荐一家？"

    if slot in {"shop_detail", "merchant_detail", "detail"}:

        return "你是想看哪家店的详情，还是想重新选一家店？"

    if slot in {"time", "booking_time", "date", "datetime"}:

        return "你是问现在，还是某个具体时间？"

    if slot in {"voucher_id", "coupon_id", "package_id", "coupon", "package"}:

        return "你想查哪张券或哪个套餐？"

    if slot in {"order_id", "booking_id", "selected_order_id", "selected_booking_id"}:

        return "你方便补充订单号吗？"

    if slot in {"category", "type", "type_name"}:

        return "你想看的品类是什么？"

    if slot in {"price", "budget", "amount"}:

        return "你方便补充一下预算范围吗？"

    if slot in {"scene", "scene_fit"}:

        return "你更看重哪种场景？"

    if len(normalized_slots) > 1:

        labels = [label for label in dict.fromkeys(_clarification_label_for_slot(item) for item in normalized_slots) if label]

        if labels:

            return f"你方便补充一下{'、'.join(labels[:2])}吗？"

    label = _clarification_label_for_slot(slot)

    return f"你方便补充一下{label}吗？"


def _build_min_entity_consistency(

    *,

    context: Mapping[str, Any],

    evidence_items: Sequence[EvidenceItem],

    tool_payload: Mapping[str, Any] | None = None,

) -> dict[str, Any]:

    target_shop_id = _normalize_entity_key(context.get("shop_id") or context.get("selected_shop_id"))

    target_shop_name = _normalize_entity_key(context.get("shop_name") or context.get("selected_shop_name") or context.get("current_shop"))

    target_voucher_id = _normalize_entity_key(context.get("coupon_id") or context.get("voucher_id"))

    target_package_id = _normalize_entity_key(context.get("package_id"))



    evidence_shop_ids: list[str] = []

    evidence_shop_names: list[str] = []

    evidence_voucher_ids: list[str] = []

    evidence_package_ids: list[str] = []

    for item in evidence_items:

        metadata = dict(getattr(item, "metadata", {}) or {})

        for value in _extract_entity_values_from_mapping(metadata, "shop_id", "parent_shop_id", "entity_shop_id"):

            if value not in evidence_shop_ids:

                evidence_shop_ids.append(value)

        for value in _extract_entity_values_from_mapping(metadata, "shop_name", "parent_shop_name", "entity_shop_name"):

            if value not in evidence_shop_names:

                evidence_shop_names.append(value)

        for value in _extract_entity_values_from_mapping(metadata, "coupon_id", "voucher_id"):

            if value not in evidence_voucher_ids:

                evidence_voucher_ids.append(value)

        for value in _extract_entity_values_from_mapping(metadata, "package_id"):

            if value not in evidence_package_ids:

                evidence_package_ids.append(value)



    tool_payload = dict(tool_payload or {})

    tool_shop_ids = _extract_entity_values_from_mapping(tool_payload, "shop_id", "selected_shop_id")

    tool_shop_names = _extract_entity_values_from_mapping(tool_payload, "shop_name", "selected_shop_name", "current_shop")

    tool_voucher_ids = _extract_entity_values_from_mapping(tool_payload, "coupon_id", "voucher_id")

    tool_package_ids = _extract_entity_values_from_mapping(tool_payload, "package_id")



    cross_entity_risk = False

    mismatch_reason = None

    if len(set(evidence_shop_ids)) > 1 or len(set(evidence_shop_names)) > 1:

        cross_entity_risk = True

        mismatch_reason = "multi_shop_evidence"

    elif target_shop_id and evidence_shop_ids and target_shop_id not in evidence_shop_ids:

        cross_entity_risk = True

        mismatch_reason = "shop_mismatch"

    elif target_shop_name and evidence_shop_names and target_shop_name not in evidence_shop_names:

        cross_entity_risk = True

        mismatch_reason = "shop_mismatch"

    elif target_voucher_id and evidence_voucher_ids and target_voucher_id not in evidence_voucher_ids:

        cross_entity_risk = True

        mismatch_reason = "coupon_mismatch"

    elif target_package_id and evidence_package_ids and target_package_id not in evidence_package_ids:

        cross_entity_risk = True

        mismatch_reason = "package_mismatch"

    elif len(set(tool_shop_ids)) > 1 or len(set(tool_voucher_ids)) > 1 or len(set(tool_package_ids)) > 1:

        cross_entity_risk = True

        mismatch_reason = "multi_entity_tool_payload"



    if target_shop_name and not evidence_shop_ids and not evidence_shop_names:

        cross_entity_risk = True

        mismatch_reason = "shop_missing"



    return {

        "checked": True,

        "passed": not cross_entity_risk,

        "entity_keys": {

            "target": {

                "shop_id": target_shop_id,

                "shop_name": target_shop_name,

                "voucher_id": target_voucher_id,

                "package_id": target_package_id,

            },

            "evidence": {

                "shop_id": evidence_shop_ids,

                "shop_name": evidence_shop_names,

                "voucher_id": evidence_voucher_ids,

                "package_id": evidence_package_ids,

            },

            "tool": {

                "shop_id": tool_shop_ids,

                "shop_name": tool_shop_names,

                "voucher_id": tool_voucher_ids,

                "package_id": tool_package_ids,

            },

        },

        "mismatch_reason": mismatch_reason,

        "cross_entity_risk": cross_entity_risk,

    }


def build_evidence_quality(

    pack: EvidencePack | None,

    *,

    intent_name: str | None = None,

    context: Mapping[str, Any] | None = None,

) -> EvidenceQualityDecision:

    ctx = dict(context or {})

    client_context = ctx.get("client_context")

    client_context_has_anchor = False

    anchor_keys = (

        "shopName",

        "shop_name",

        "selected_shop_name",

        "current_shop",

        "city",

        "current_city",

        "location",

        "current_location",

        "area",

        "current_area",

        "district",

        "region",

    )



    def _mapping_has_anchor(mapping: Mapping[str, Any] | None) -> bool:

        if not isinstance(mapping, Mapping):

            return False

        for key in anchor_keys:

            value = mapping.get(key)

            if isinstance(value, Mapping):

                if any(str(item).strip() for item in value.values() if item not in (None, "", [], {}, ())):

                    return True

                continue

            if str(value or "").strip():

                return True

        return False



    client_context_has_anchor = _mapping_has_anchor(client_context)

    if not client_context_has_anchor:

        session_context_anchor = {key: ctx.get(key) for key in anchor_keys}

        client_context_has_anchor = _mapping_has_anchor(session_context_anchor)

    required_facets_ctx = [dict(item) for item in ctx.get("required_facets") or [] if isinstance(item, Mapping)]

    optional_facets_ctx = [dict(item) for item in ctx.get("optional_facets") or [] if isinstance(item, Mapping)]

    missing_slots_ctx = [str(item).strip() for item in (ctx.get("missing_slots") or []) if str(item).strip()]

    clarification_slot_ctx = str(ctx.get("clarification_slot") or "").strip() or None

    tool_candidates_ctx = [str(item).strip() for item in (ctx.get("tool_candidates") or []) if str(item).strip()]

    routing_action = str(ctx.get("routing_action") or ctx.get("required_action") or "").strip().lower()

    partial_grounded_enabled, slot_clarify_enabled, rag_plus_tool_partial_answer_enabled = _phase2_flags()



    def _is_ask_clarification_facet(facet: Mapping[str, Any]) -> bool:

        return str(facet.get("missing_policy") or "").strip().lower() == "ask_clarification"



    def _facet_names(facets: Sequence[Mapping[str, Any]]) -> list[str]:

        names: list[str] = []

        for facet in facets:

            name = str(facet.get("name") or "").strip()

            if name:

                names.append(name)

        return names



    if pack is None or not pack.items:

        clarification_slot = clarification_slot_ctx

        if not clarification_slot and missing_slots_ctx:

            clarification_slot = missing_slots_ctx[0]

        if not clarification_slot and required_facets_ctx:

            for facet in required_facets_ctx:

                if _is_ask_clarification_facet(facet):

                    clarification_slot = str(facet.get("name") or "").strip() or None

                    if clarification_slot:

                        break

        response_mode = "ask_clarification" if clarification_slot else "no_answer"

        missing_facets = _facet_names(required_facets_ctx)

        return EvidenceQualityDecision(

            evidence_count=0,

            top_score=0.0,

            score_gap=0.0,

            topic_consistency=0.0,

            entity_consistency=0.0,

            city_area_category_consistency=False,

            required_roles_covered=False,

            citation_available=False,

            stale_evidence=False,

            response_mode=response_mode,

            is_valid=False,

            reason="missing_required_slot" if response_mode == "ask_clarification" else "no_evidence",

            fallback_reason="slot_missing" if response_mode == "ask_clarification" else "empty_pack",

            missing_slots=missing_slots_ctx,

            clarification_slot=clarification_slot,

            covered_facets=[],

            missing_facets=missing_facets,

            tool_candidates=tool_candidates_ctx,

            details={

                "dominant_chunk_type": None,

                "chunk_types": {},

                "entity_consistency_minimal": None,

                "required_facets": required_facets_ctx,

                "optional_facets": optional_facets_ctx,

                "missing_slots": missing_slots_ctx,

                "clarification_slot": clarification_slot,

                "covered_facets": [],

                "missing_facets": missing_facets,

                "tool_candidates": tool_candidates_ctx,

                "evidence_after_gate_count": 0,

                "failure_reasons": ["empty_pack" if response_mode == "no_answer" else "slot_missing"],

            },

        )



    items = list(pack.items)

    query_text = str(ctx.get("query_text") or ctx.get("raw_query") or ctx.get("query") or "").strip()

    target_shop_id = str(ctx.get("shop_id") or ctx.get("selected_shop_id") or "").strip() or None

    target_shop_name = str(ctx.get("shop_name") or ctx.get("selected_shop_name") or ctx.get("current_shop") or "").strip() or None

    target_city = str(ctx.get("city") or ctx.get("current_city") or "").strip() or None

    target_area = str(ctx.get("area") or ctx.get("current_area") or "").strip() or None

    target_category = str(ctx.get("category") or ctx.get("current_category") or "").strip() or None

    tool_result_present = bool(ctx.get("tool_result_present") or ctx.get("has_tool_result"))

    tool_result_payload = ctx.get("tool_result_payload")

    role_tokens = {

        str(item.metadata.get("role") or item.chunk_type or "").strip().lower()

        for item in items

        if str(item.metadata.get("role") or item.chunk_type or "").strip()

    }

    shop_ids = {

        str(item.metadata.get("shop_id") or item.metadata.get("parent_shop_id") or item.document_id or "").strip()

        for item in items

        if item.metadata.get("shop_id") or item.metadata.get("parent_shop_id") or item.document_id

    }

    _, _, min_entity_consistency_enabled = _phase1_flags()

    scores = sorted((float(item.score or 0.0) for item in items), reverse=True)

    top_score = scores[0] if scores else 0.0

    second_score = scores[1] if len(scores) > 1 else 0.0

    score_gap = max(top_score - second_score, 0.0)

    citation_available = any(bool(item.citation_chunk_id) for item in items)

    stale_evidence = any(

        bool(item.metadata.get("deprecated") or item.metadata.get("is_deprecated") or item.metadata.get("stale"))

        for item in items

    )



    chunk_types = [str(item.chunk_type or item.metadata.get("chunk_type") or "") for item in items]

    chunk_type_counter = Counter(chunk_types)

    dominant_chunk_type, dominant_chunk_count = chunk_type_counter.most_common(1)[0]

    topic_consistency = dominant_chunk_count / max(len(items), 1)



    parent_ids = [

        str(item.parent_chunk_id or item.metadata.get("parent_chunk_id") or item.document_id or "")

        for item in items

        if (item.parent_chunk_id or item.metadata.get("parent_chunk_id") or item.document_id)

    ]

    parent_counter = Counter(parent_ids)

    entity_consistency = (parent_counter.most_common(1)[0][1] / max(len(parent_ids), 1)) if parent_ids else 0.0

    entity_consistency_minimal = None

    if min_entity_consistency_enabled:

        entity_consistency_minimal = _build_min_entity_consistency(

            context=ctx,

            evidence_items=items,

            tool_payload=tool_result_payload if isinstance(tool_result_payload, Mapping) else None,

        )



    specific_shop_question = bool(

        target_shop_id

        or target_shop_name

        or any(token in query_text for token in ("这家", "那家", "这个店", "那个店", "哪家", "该店"))

    )

    nearby_question = any(token in query_text for token in ("附近", "周边", "离我", "离我近", "附近有什么", "附近有啥"))

    package_question = any(token in query_text for token in ("套餐", "团购", "优惠券", "券", "代金券"))

    pitfall_question = any(token in query_text for token in ("避坑", "踩雷", "雷点", "坑", "不推荐"))



    city_area_category_consistency = bool(

        items

        and all(

            (

                (not target_city or str(item.metadata.get("city") or "").strip() == target_city)

                and (not target_area or str(item.metadata.get("area") or "").strip() == target_area)

                and (not target_category or str(item.metadata.get("category") or "").strip() == target_category)

            )

            for item in items

        )

    )



    required_roles_covered = False

    if intent_name in {"local_life_recommend", "merchant_detail", "package_or_coupon", "comparison"}:

        required_roles_covered = any(

            str(item.metadata.get("role") or item.chunk_type or "").lower()

            in {"review", "guide", "package", "coupon", "detail", "comparison", "concept", "business_evidence"}

            for item in items

        )

    else:

        required_roles_covered = True



    is_valid = True

    reason = "quality_ok"

    fallback_reason = None

    has_matching_shop_evidence = True

    if specific_shop_question:

        has_matching_shop_evidence = bool(

            (target_shop_id and target_shop_id in shop_ids)

            or (target_shop_name and any(target_shop_name in str(item.content or "") for item in items))

        )

    only_platform_rule = bool(role_tokens) and role_tokens <= {"platform_rule"}

    if len(items) < 2:

        is_valid = False

        reason = "too_few_evidence"

        fallback_reason = "insufficient_count"

    elif top_score < 0.35:

        is_valid = False

        reason = "low_top_score"

        fallback_reason = "low_score"

    elif score_gap < 0.04 and len(items) > 1:

        is_valid = False

        reason = "low_score_gap"

        fallback_reason = "ambiguous_ranking"

    elif stale_evidence:

        is_valid = False

        reason = "stale_evidence"

        fallback_reason = "stale_evidence"

    elif specific_shop_question and not has_matching_shop_evidence:

        is_valid = False

        reason = "shop_mismatch"

        fallback_reason = "shop_mismatch"

    elif specific_shop_question and only_platform_rule:

        is_valid = False

        reason = "platform_rule_only"

        fallback_reason = "platform_rule_only"

    elif nearby_question and not city_area_category_consistency:

        is_valid = False

        reason = "geo_mismatch"

        fallback_reason = "geo_mismatch"

    elif package_question and not (tool_result_present or any(role in {"package", "coupon"} for role in role_tokens)):

        is_valid = False

        reason = "required_role_missing"

        fallback_reason = "missing_role"

    elif pitfall_question and not any(role in {"review", "pitfall"} for role in role_tokens):

        is_valid = False

        reason = "required_role_missing"

        fallback_reason = "missing_role"

    elif intent_name in {"local_life_recommend", "merchant_detail", "package_or_coupon"} and not required_roles_covered:

        is_valid = False

        reason = "required_role_missing"

        fallback_reason = "missing_role"

    if entity_consistency_minimal is not None and entity_consistency_minimal.get("cross_entity_risk") and is_valid:

        is_valid = False

        reason = str(entity_consistency_minimal.get("mismatch_reason") or "entity_consistency_mismatch")

        fallback_reason = reason



    facet_covered_names: list[str] = []

    facet_missing_names: list[str] = []

    if required_facets_ctx:

        for facet in required_facets_ctx:

            facet_name = str(facet.get("name") or "").strip()

            if not facet_name:

                continue

            if _facet_covered_for_phase2(

                facet_name,

                role_tokens=role_tokens,

                tool_result_present=tool_result_present,

                has_matching_shop_evidence=has_matching_shop_evidence,

                city_area_category_consistency=city_area_category_consistency,

            ):

                facet_covered_names.append(facet_name)

            else:

                facet_missing_names.append(facet_name)



    if not facet_missing_names and missing_slots_ctx:

        facet_missing_names.extend(item for item in missing_slots_ctx if item not in facet_covered_names)

    if not facet_covered_names and required_roles_covered:

        facet_covered_names.extend(_facet_names(required_facets_ctx[:1]) if required_facets_ctx else [])



    # Force deduplication and mutual exclusion

    facet_covered_names = list(dict.fromkeys(facet_covered_names))

    facet_missing_names = [f for f in list(dict.fromkeys(facet_missing_names)) if f not in facet_covered_names]



    clarification_slot = clarification_slot_ctx

    if not clarification_slot and missing_slots_ctx:

        clarification_slot = missing_slots_ctx[0]

    if not clarification_slot and facet_missing_names:

        clarification_slot = facet_missing_names[0]

    if not clarification_slot and required_facets_ctx:

        for facet in required_facets_ctx:

            if _is_ask_clarification_facet(facet):

                clarification_slot = str(facet.get("name") or "").strip() or None

                if clarification_slot:

                    break



    phase2_enabled = bool(required_facets_ctx or missing_slots_ctx or clarification_slot_ctx)

    ask_clarification_required = bool(

        clarification_slot

        and (

            missing_slots_ctx

            or any(

                _is_ask_clarification_facet(facet) and str(facet.get("name") or "").strip() in facet_missing_names

                for facet in required_facets_ctx

            )

        )

    )

    hard_no_answer_reason = reason in {

        "shop_mismatch",

        "shop_missing",

        "geo_mismatch",

        "multi_shop_evidence",

        "multi_entity_tool_payload",

        "coupon_mismatch",

        "package_mismatch",

    }



    if not items:

        response_mode = (

            "ask_clarification"

            if (ask_clarification_required and slot_clarify_enabled and not client_context_has_anchor)

            else "no_answer"

        )

    elif hard_no_answer_reason and not phase2_enabled:

        response_mode = "no_answer"

    elif not is_valid and ask_clarification_required and slot_clarify_enabled:

        response_mode = "ask_clarification" if not client_context_has_anchor else ("partial_grounded" if partial_grounded_enabled else "weak_answer")

    elif not is_valid and phase2_enabled and (facet_covered_names or facet_missing_names or tool_result_present):

        if partial_grounded_enabled and (routing_action != "rag_plus_tool" or rag_plus_tool_partial_answer_enabled or client_context_has_anchor):

            response_mode = "partial_grounded"

        else:

            response_mode = "weak_answer"

    elif not is_valid and hard_no_answer_reason:

        if (

            phase2_enabled

            and partial_grounded_enabled

            and (routing_action != "rag_plus_tool" or rag_plus_tool_partial_answer_enabled or client_context_has_anchor)

        ):

            response_mode = "partial_grounded"

        else:

            response_mode = "no_answer"

    elif not is_valid and phase2_enabled:

        response_mode = (

            "partial_grounded"

            if (

                partial_grounded_enabled

                and (facet_covered_names or facet_missing_names or tool_result_present)

                and (routing_action != "rag_plus_tool" or rag_plus_tool_partial_answer_enabled or client_context_has_anchor)

            )

            else "weak_answer"

        )

    elif not is_valid:

        response_mode = "weak_answer"

    else:

        response_mode = "grounded"



    failure_reasons = [reason]

    if entity_consistency_minimal is not None and entity_consistency_minimal.get("cross_entity_risk"):

        failure_reasons.append(str(entity_consistency_minimal.get("mismatch_reason") or "entity_consistency_mismatch"))

    if facet_missing_names:

        failure_reasons.append("missing_facets:" + ",".join(dict.fromkeys(facet_missing_names)))

    if missing_slots_ctx:

        failure_reasons.append("missing_slots:" + ",".join(dict.fromkeys(missing_slots_ctx)))



    return EvidenceQualityDecision(

        evidence_count=len(items),

        top_score=top_score,

        score_gap=score_gap,

        topic_consistency=topic_consistency,

        entity_consistency=entity_consistency,

        city_area_category_consistency=city_area_category_consistency,

        required_roles_covered=required_roles_covered,

        citation_available=citation_available,

        stale_evidence=stale_evidence,

        response_mode=response_mode,

        is_valid=is_valid,

        reason=reason,

        fallback_reason=fallback_reason,

        missing_slots=missing_slots_ctx,

        clarification_slot=clarification_slot,

        covered_facets=facet_covered_names,

        missing_facets=facet_missing_names,

        tool_candidates=tool_candidates_ctx,

        details={

            "dominant_chunk_type": dominant_chunk_type,

            "chunk_types": dict(chunk_type_counter),

            "entity_consistency_minimal": entity_consistency_minimal,

            "required_facets": required_facets_ctx,

            "optional_facets": optional_facets_ctx,

            "missing_slots": missing_slots_ctx,

            "clarification_slot": clarification_slot,

            "covered_facets": facet_covered_names,

            "missing_facets": facet_missing_names,

            "tool_candidates": tool_candidates_ctx,

            "evidence_after_gate_count": len(items),

            "tool_result_present": tool_result_present,

            "tool_result_payload": tool_result_payload,

            "retrieval_plan_missing": bool(ctx.get("retrieval_plan_missing")),

            "tool_plan_missing": bool(ctx.get("tool_plan_missing")),

            "tool_slot_missing": bool(ctx.get("tool_slot_missing")),

            "tool_not_allowed": bool(ctx.get("tool_not_allowed")),

            "retrieval_not_allowed": bool(ctx.get("retrieval_not_allowed")),

            "rag_gate_blocked": bool(ctx.get("rag_gate_blocked")),

            "failure_reasons": failure_reasons,

        },

    )
