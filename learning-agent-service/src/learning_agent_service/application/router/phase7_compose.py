from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ...domain.contracts import (
    AnswerContract,
    AnswerVerifierResult,
    LoopCounter,
    EntityJoinResult,
    ReviewReport,
    SemanticParseResult,
    SourceContract,
    RoutingDecision,
    EvidenceQualityDecision,
)
from .base import (
    _extract_entity_key_from_evidence_item,
    _extract_entity_key_from_tool_result,
    _phase4_flags,
    _phase4_mode,
    _PHASE1_DATA_SOURCE_DYNAMIC_TOOL,
    _PHASE1_DATA_SOURCE_STATIC_RAG,
)

def _build_entity_join_result(turn: Any) -> EntityJoinResult:

    rag_result = getattr(turn, "rag_result", None)

    tool_result = getattr(turn, "tool_result", None)

    evidence_pack = getattr(rag_result, "evidence_pack", None) if rag_result is not None else None

    evidence_items = list(getattr(evidence_pack, "items", None) or [])



    evidence_bindings: dict[str, list[str]] = {}

    tool_bindings: dict[str, list[str]] = {}

    candidate_entities: list[str] = []

    issues: list[str] = []



    for item in evidence_items:

        entity_key = _extract_entity_key_from_evidence_item(item)

        if not entity_key:

            continue

        if entity_key not in candidate_entities:

            candidate_entities.append(entity_key)

        evidence_bindings.setdefault(entity_key, []).append(str(getattr(item, "chunk_id", "") or ""))



    tool_entity = _extract_entity_key_from_tool_result(tool_result)

    tool_name = str(getattr(tool_result, "tool_name", "") or "").strip() or "tool_result"

    if tool_entity:

        if tool_entity not in candidate_entities:

            candidate_entities.append(tool_entity)

        tool_bindings.setdefault(tool_entity, []).append(tool_name)



    nonempty_entities = [entity for entity in candidate_entities if entity]

    selected_entity = nonempty_entities[0] if len(set(nonempty_entities)) == 1 else None

    cross_entity_detected = len(set(nonempty_entities)) > 1

    if cross_entity_detected:

        issues.append("cross_entity_stitching")



    extra = {

        "evidence_item_count": len(evidence_items),

        "tool_result_present": tool_result is not None,

        "tool_name": tool_name if tool_result is not None else None,

        "phase4_mode": _phase4_mode(),

    }

    return EntityJoinResult(

        candidate_entities=nonempty_entities,

        evidence_bindings=evidence_bindings,

        tool_bindings=tool_bindings,

        selected_entity=selected_entity,

        cross_entity_detected=cross_entity_detected,

        issues=issues,

        extra=extra,

    )


def _facet_names_from_items(items: Any) -> list[str]:
    facet_names: list[str] = []
    for item in list(items or []):
        if isinstance(item, Mapping):
            facet_name = str(item.get("name") or item.get("facet") or item.get("facet_name") or "").strip()
        else:
            facet_name = str(item or "").strip()
        if facet_name and facet_name not in facet_names:
            facet_names.append(facet_name)
    return facet_names


def _facet_source_map_from_items(items: Any) -> dict[str, Any]:
    source_map: dict[str, Any] = {}
    for item in list(items or []):
        if not isinstance(item, Mapping):
            facet_name = str(item or "").strip()
            if facet_name and facet_name not in source_map:
                source_map[facet_name] = {}
            continue
        facet_name = str(item.get("name") or item.get("facet") or item.get("facet_name") or "").strip()
        if not facet_name:
            continue
        payload = {
            key: value
            for key, value in (
                ("data_source", item.get("data_source")),
                ("source", item.get("source")),
                ("scope_kind", item.get("scope_kind")),
            )
            if value not in (None, "", [], {}, ())
        }
        if payload:
            source_map[facet_name] = payload
        else:
            source_map.setdefault(facet_name, {})
    return source_map


def _int_list_from_values(values: Any) -> list[int]:
    parsed: list[int] = []
    for value in list(values or []):
        try:
            parsed_value = int(value)
        except (TypeError, ValueError):
            continue
        if parsed_value not in parsed:
            parsed.append(parsed_value)
    return parsed

def _build_answer_contract(

    turn: Any,

    routing: RoutingDecision | None,

    evidence_quality: EvidenceQualityDecision | None,

    entity_join_result: EntityJoinResult,

) -> AnswerContract:

    routing_extra = dict(getattr(routing, "extra", {}) or {}) if routing is not None else {}

    required_facets = [dict(item) for item in routing_extra.get("required_facets") or [] if isinstance(item, Mapping)]

    missing_slots = list(getattr(routing, "missing_slots", None) or getattr(evidence_quality, "missing_slots", None) or [])

    clarification_slot = (

        str(getattr(routing, "clarification_slot", "") or "").strip()

        or str(getattr(evidence_quality, "clarification_slot", "") or "").strip()

        or None

    )

    covered_facets = list(getattr(evidence_quality, "covered_facets", None) or [])

    missing_facets = list(getattr(evidence_quality, "missing_facets", None) or [])

    required_facet_names = [

        str(facet.get("name") or "").strip()

        for facet in required_facets

        if str(facet.get("name") or "").strip()

    ]

    dynamic_facets = [

        str(facet.get("name") or "").strip()

        for facet in required_facets

        if str(facet.get("name") or "").strip()

        and str(facet.get("data_source") or "").strip().lower() == _PHASE1_DATA_SOURCE_DYNAMIC_TOOL

    ]

    static_facets = [

        str(facet.get("name") or "").strip()

        for facet in required_facets

        if str(facet.get("name") or "").strip()

        and str(facet.get("data_source") or "").strip().lower() == _PHASE1_DATA_SOURCE_STATIC_RAG

    ]

    evidence_requirements = {

        "required_facets": required_facet_names,

        "covered_facets": covered_facets,

        "missing_facets": missing_facets,

        "static_facets": static_facets,

        "dynamic_facets": dynamic_facets,

        "has_rag_result": getattr(turn, "rag_result", None) is not None,

        "has_evidence_pack": getattr(getattr(turn, "rag_result", None), "evidence_pack", None) is not None,

        "candidate_entities": list(entity_join_result.candidate_entities),

        "selected_entity": entity_join_result.selected_entity,

        "cross_entity_detected": entity_join_result.cross_entity_detected,

    }

    tool_candidates = [str(item) for item in (getattr(evidence_quality, "tool_candidates", None) or []) if str(item).strip()]

    if routing is not None:

        for candidate in getattr(routing, "tool_candidates", None) or []:

            candidate_text = str(candidate or "").strip()

            if candidate_text and candidate_text not in tool_candidates:

                tool_candidates.append(candidate_text)

    tool_bindings = dict(entity_join_result.tool_bindings)

    tool_entity = next(iter(tool_bindings.keys()), None)

    tool_requirements = {

        "tool_candidates": tool_candidates,

        "missing_slots": missing_slots,

        "clarification_slot": clarification_slot,

        "has_tool_result": getattr(turn, "tool_result", None) is not None,

        "tool_entity": tool_entity,

        "tool_bindings": tool_bindings,

    }

    forbidden_without_evidence = list(dict.fromkeys(dynamic_facets))

    routing_contract = getattr(turn, "routing_contract", None)
    allowed_facets = []
    optional_facets = []
    forbidden_facets = []
    facet_source_expectations: dict[str, Any] = {}
    scope_kind: str | None = None
    answer_style: str | None = None
    if routing_contract is not None:
        allowed_facets = list(routing_contract.compose_allowed_facets)
        optional_facets = list(routing_contract.optional_facets)
        forbidden_facets = list(routing_contract.forbidden_facets)
        facet_source_expectations = dict(getattr(routing_contract, "facet_source_map", {}) or {})
        scope_kind = str(getattr(routing_contract, "scope_kind", "") or "").strip() or None
        if not answer_style:
            try:
                from ...local_life.answer_contract import AnswerContract as LocalLifeAnswerContract

                user_need = routing_extra.get("user_need")
                target_shop = None
                target_shop_payload = dict(turn.extra.get("target_shop") or {})
                if target_shop_payload:
                    from ...local_life.target_shop_policy import TargetShop

                    target_shop = TargetShop.model_validate(target_shop_payload)
                if user_need is not None:
                    ll_contract = LocalLifeAnswerContract.build_contract(user_need, target_shop)
                    answer_style = str(getattr(ll_contract, "answer_style", "") or "").strip() or None
                    if not scope_kind:
                        scope_kind = "single_shop" if answer_style == "single_shop_review" else ("multi_shop" if answer_style == "multi_shop_recommendation" else None)
            except Exception:
                pass
    else:
        try:
            from ...local_life.answer_contract import AnswerContract as LocalLifeAnswerContract
            user_need = routing_extra.get("user_need")
            target_shop = None
            target_shop_payload = dict(turn.extra.get("target_shop") or {})
            if target_shop_payload:
                from ...local_life.target_shop_policy import TargetShop
                target_shop = TargetShop.model_validate(target_shop_payload)
            if user_need is not None:
                ll_contract = LocalLifeAnswerContract.build_contract(user_need, target_shop)
                allowed_facets = list(ll_contract.allowed_facets)
                forbidden_facets = list(ll_contract.forbidden_facets)
                answer_style = str(getattr(ll_contract, "answer_style", "") or "").strip() or None
                scope_kind = "single_shop" if answer_style == "single_shop_review" else ("multi_shop" if answer_style == "multi_shop_recommendation" else None)
        except Exception:
            pass
    optional_facets = optional_facets or _facet_names_from_items(routing_extra.get("optional_facets"))
    if not facet_source_expectations:
        facet_source_expectations = _facet_source_map_from_items(required_facets)
        if optional_facets:
            for facet_name in optional_facets:
                facet_source_expectations.setdefault(facet_name, {})
    if not scope_kind:
        scope_kind = str(routing_extra.get("scope_kind") or "").strip() or None
    if not answer_style:
        answer_style = str(routing_extra.get("answer_style") or "").strip() or None
    routing_action = str(getattr(routing, "required_action", "") or "").strip().lower() if routing is not None else ""
    route_candidate = str(getattr(routing, "route_candidate", "") or "").strip().lower() if routing is not None else ""
    raw_query_text = str(getattr(turn, "raw_query", "") or "")
    compact_query_text = raw_query_text.replace(" ", "")
    inferred_coupon = any(token in compact_query_text for token in ("券", "优惠", "领券", "打折", "代金券", "折扣", "有券", "团购"))
    inferred_open = any(token in compact_query_text for token in ("营业", "开门", "开着", "营业时间", "现在营业吗", "现在开吗", "营业吗"))
    inferred_distance = any(token in compact_query_text for token in ("距离", "有多远", "导航", "路线", "怎么走", "怎么去"))
    inferred_comparison = (
        routing_action == "compare"
        or route_candidate == "compare_multi_parent"
        or any(token in compact_query_text for token in ("对比", "比较", "区别", "差别", "哪家更", "哪个更", "更便宜", "更适合", "更好"))
        and any(token in compact_query_text for token in ("和", "比", "vs"))
    )
    multi_facet_requested = len(required_facets) > 1 or len(
        [
            facet
            for facet in required_facets
            if str((facet or {}).get("name") or "").strip() not in {"location", "category"}
        ]
    ) > 1
    if routing_action == "direct_answer" and route_candidate == "out_of_scope":
        answer_style = None
    elif multi_facet_requested or sum(1 for flag in (inferred_coupon, inferred_open, inferred_distance) if flag) > 1:
        answer_style = "facet_multi"
    elif inferred_coupon and not inferred_open and not inferred_distance:
        answer_style = "coupon_only"
    elif inferred_open and not inferred_coupon and not inferred_distance:
        answer_style = "open_status_only"
    elif inferred_distance and not inferred_coupon and not inferred_open:
        answer_style = "distance_only"
    elif inferred_comparison or str(routing_extra.get("top_level_intent") or "").strip().lower() in {"comparison", "restaurant_comparison", "local_life_comparison"}:
        answer_style = "comparison"
    elif any(token in compact_query_text for token in ("附近", "周边", "推荐", "几家", "多推荐", "多家")):
        answer_style = "multi_shop_recommendation"
    elif routing_action == "clarify" or (missing_slots and route_candidate != "out_of_scope"):
        answer_style = "clarification"
    elif not answer_style:
        answer_style = str(routing_extra.get("answer_style") or "").strip() or "single_shop_review"

    return AnswerContract(

        original_query=str(getattr(turn, "raw_query", "") or ""),

        allowed_facets=allowed_facets,

        optional_facets=optional_facets,

        forbidden_facets=forbidden_facets,

        required_facets=required_facets,

        evidence_requirements=evidence_requirements,

        tool_requirements=tool_requirements,

        forbidden_without_evidence=forbidden_without_evidence,

        candidate_entities=list(entity_join_result.candidate_entities),

        selected_entity=entity_join_result.selected_entity,

        missing_slots=missing_slots,

        clarification_slot=clarification_slot,
        answer_style=answer_style,
        scope_kind=scope_kind,
        facet_source_expectations=facet_source_expectations,

        extra={

            "route_candidate": getattr(routing, "route_candidate", None) if routing is not None else None,

            "response_mode": str(getattr(evidence_quality, "response_mode", "") or "").strip().lower(),

            "phase4_mode": _phase4_mode(),

        },

    )

def _answer_verifier_repair_hint(issues: Sequence[str], answer_contract: AnswerContract) -> str:

    issue_set = {str(item).strip().lower() for item in issues if str(item).strip()}

    hints: list[str] = []

    if "cross_entity_stitching" in issue_set:

        hints.append("只保留同一家店的证据和工具结果，不要把不同门店拼在一起。")

    if "required_facets_missing" in issue_set:

        hints.append("先补齐必需 facets，再给结论；缺的部分可以降级为 partial_grounded。")

    if "dynamic_info_without_tool_result" in issue_set:

        hints.append("券、营业状态这类动态信息需要工具结果支撑，缺失时不要强答。")

    if "should_clarify_but_answered" in issue_set:

        hints.append("缺 slot 时先澄清，不要直接回答。")

    if "weak_evidence_claimed_as_certain" in issue_set:

        hints.append("把弱证据改成边界明确的部分判断。")

    if not hints:

        return "当前回答可以继续按可验证证据输出。"

    return "；".join(hints)

def _build_answer_verifier_result(

    request: Any,

    answer_text: str,

    entity_join_result: EntityJoinResult,

    answer_contract: AnswerContract,

) -> AnswerVerifierResult:

    evidence_quality = getattr(request, "evidence_quality", None)

    response_mode = str(

        getattr(request, "final_response_mode", None)

        or getattr(evidence_quality, "response_mode", None)

        or ""

    ).strip().lower()

    verifier_enabled, phase4_mode = _phase4_flags()

    if not verifier_enabled:

        return AnswerVerifierResult(

            passed=True,

            issues=[],

            suggested_response_mode=response_mode or "grounded",

            repair_hint="",

            extra={

                "response_mode": response_mode,

                "candidate_entities": list(answer_contract.candidate_entities),

                "selected_entity": answer_contract.selected_entity,

                "phase4_mode": "skipped",

            },

        )

    issues: list[str] = list(entity_join_result.issues)

    missing_facets = list(answer_contract.evidence_requirements.get("missing_facets") or [])

    dynamic_facets = list(answer_contract.evidence_requirements.get("dynamic_facets") or [])

    missing_slots = list(answer_contract.tool_requirements.get("missing_slots") or [])

    if missing_facets:

        issues.append("required_facets_missing")

    if dynamic_facets and getattr(request, "tool_result", None) is None:

        issues.append("dynamic_info_without_tool_result")

    if missing_slots and response_mode not in {"ask_clarification"}:

        issues.append("should_clarify_but_answered")

    if evidence_quality is not None and not bool(getattr(evidence_quality, "is_valid", True)) and response_mode == "grounded":

        issues.append("weak_evidence_claimed_as_certain")



    normalized_answer = str(answer_text or "").strip()

    if not normalized_answer:

        issues.append("empty_answer")



    dedup_issues: list[str] = []

    seen_issues: set[str] = set()

    for issue in issues:

        normalized_issue = str(issue or "").strip()

        if not normalized_issue or normalized_issue in seen_issues:

            continue

        seen_issues.add(normalized_issue)

        dedup_issues.append(normalized_issue)



    suggested_response_mode = "grounded"

    if "should_clarify_but_answered" in seen_issues:

        suggested_response_mode = "ask_clarification"

    elif "cross_entity_stitching" in seen_issues or "required_facets_missing" in seen_issues or "dynamic_info_without_tool_result" in seen_issues:

        suggested_response_mode = "partial_grounded"

    elif "weak_evidence_claimed_as_certain" in seen_issues:

        suggested_response_mode = "partial_grounded"

    elif "empty_answer" in seen_issues:

        suggested_response_mode = "no_answer"



    return AnswerVerifierResult(

        passed=not dedup_issues,

        issues=dedup_issues,

        suggested_response_mode=suggested_response_mode,

        repair_hint=_answer_verifier_repair_hint(dedup_issues, answer_contract),

        extra={

            "response_mode": response_mode,

            "candidate_entities": list(answer_contract.candidate_entities),

            "selected_entity": answer_contract.selected_entity,

            "phase4_mode": phase4_mode,

        },

    )


def _build_semantic_parse_result(
    turn: Any,
    routing: RoutingDecision | None,
    answer_contract: AnswerContract,
) -> SemanticParseResult:
    routing_extra = dict(getattr(routing, "extra", {}) or {}) if routing is not None else {}
    primary_intent = str(getattr(getattr(routing, "intent", None), "name", "") or "").strip() or None
    top_level_intent = primary_intent or str(routing_extra.get("top_level_intent") or routing_extra.get("answer_style") or answer_contract.answer_style or "").strip() or None
    sub_intents = _facet_names_from_items(routing_extra.get("sub_intents"))
    if not sub_intents:
        sub_intents = [str(item).strip() for item in (routing_extra.get("sub_intent_names") or []) if str(item).strip()]
    required_facets = [str(facet.get("name") or "").strip() for facet in answer_contract.required_facets if str(facet.get("name") or "").strip()]
    optional_facets = list(answer_contract.optional_facets) or _facet_names_from_items(routing_extra.get("optional_facets"))
    forbidden_facets = list(answer_contract.forbidden_facets)
    constraints = dict(routing_extra.get("constraints") or {})
    if answer_contract.scope_kind and "scope_kind" not in constraints:
        constraints["scope_kind"] = answer_contract.scope_kind
    if answer_contract.answer_style and "answer_style" not in constraints:
        constraints["answer_style"] = answer_contract.answer_style
    if answer_contract.facet_source_expectations and "facet_source_expectations" not in constraints:
        constraints["facet_source_expectations"] = dict(answer_contract.facet_source_expectations)
    target_reference = (
        str(routing_extra.get("target_reference") or "").strip()
        or str(answer_contract.selected_entity or "").strip()
        or str(getattr(turn, "extra", {}).get("current_shop") or "").strip()
        or None
    )
    confidence = float(getattr(routing, "confidence", 0.0) or 0.0) if routing is not None else float(routing_extra.get("confidence") or 0.0)
    missing_slots = list(answer_contract.missing_slots or routing_extra.get("missing_slots") or [])
    return SemanticParseResult(
        primary_intent=primary_intent,
        top_level_intent=top_level_intent,
        sub_intents=sub_intents,
        required_facets=required_facets,
        optional_facets=optional_facets,
        forbidden_facets=forbidden_facets,
        constraints=constraints,
        target_reference=target_reference,
        confidence=confidence,
        missing_slots=missing_slots,
        extra={
            "route_candidate": getattr(routing, "route_candidate", None) if routing is not None else routing_extra.get("route_candidate"),
            "phase4_mode": _phase4_mode(),
        },
    )


def _build_source_contract(
    turn: Any,
    routing: RoutingDecision | None,
    answer_contract: AnswerContract,
    *,
    selected_shop_id: int | None = None,
    current_shop: str | None = None,
    explicit_query_shop: str | None = None,
) -> SourceContract:
    routing_extra = dict(getattr(routing, "extra", {}) or {}) if routing is not None else {}
    source_map = dict(answer_contract.facet_source_expectations or {})
    if not source_map:
        source_map = _facet_source_map_from_items(routing_extra.get("required_facets"))
    comparison_shop_ids = _int_list_from_values(routing_extra.get("comparison_shop_ids"))
    candidate_shop_ids = _int_list_from_values(routing_extra.get("candidate_shop_ids"))
    if selected_shop_id is not None and selected_shop_id not in candidate_shop_ids:
        candidate_shop_ids = [selected_shop_id, *candidate_shop_ids]
    scope_kind = (
        str(answer_contract.scope_kind or routing_extra.get("scope_kind") or "").strip()
        or None
    )
    target_reference_source = (
        str(routing_extra.get("target_reference_source") or "").strip()
        or ("explicit_query" if explicit_query_shop else None)
        or ("current_shop" if current_shop else None)
    )
    return SourceContract(
        required_facets=[str(facet.get("name") or "").strip() for facet in answer_contract.required_facets if str(facet.get("name") or "").strip()],
        optional_facets=list(answer_contract.optional_facets) or _facet_names_from_items(routing_extra.get("optional_facets")),
        forbidden_facets=list(answer_contract.forbidden_facets),
        facet_source_map=source_map,
        target_shop_id=selected_shop_id,
        candidate_shop_ids=[shop_id for shop_id in candidate_shop_ids if shop_id is not None],
        comparison_shop_ids=[shop_id for shop_id in comparison_shop_ids if shop_id is not None],
        scope_kind=scope_kind,
        target_reference_source=target_reference_source,
        extra={
            "current_shop": current_shop,
            "explicit_query_shop": explicit_query_shop,
            "route_candidate": getattr(routing, "route_candidate", None) if routing is not None else routing_extra.get("route_candidate"),
        },
    )


def _build_loop_counter(turn: Any, runtime_context: Mapping[str, Any] | None = None) -> LoopCounter:
    turn_extra = dict(getattr(turn, "extra", {}) or {})
    runtime_context = dict(runtime_context or {})
    runtime_metrics = dict(getattr(getattr(turn, "runtime", None), "metrics", {}) or {})

    def _count(*keys: str) -> int:
        for source in (turn_extra, runtime_metrics, runtime_context):
            for key in keys:
                value = source.get(key)
                if value in (None, "", [], {}, ()):
                    continue
                try:
                    return max(0, int(value))
                except (TypeError, ValueError):
                    continue
        return 0

    return LoopCounter(
        retry_rag=_count("retry_rag", "retry_rag_count"),
        retry_tool=_count("retry_tool", "retry_tool_count"),
        retry_step=_count("retry_step", "retry_step_count"),
        repair_answer=_count("repair_answer", "repair_answer_count"),
        replan=_count("replan", "plan_replan_count"),
        extra={
            "graph_recursion_limit": runtime_context.get("graph_recursion_limit"),
            "tool_loop_limit": runtime_context.get("tool_loop_limit"),
            "rewrite_loop_limit": runtime_context.get("rewrite_loop_limit"),
        },
    )


def _build_review_report(
    request: Any,
    answer_text: str,
    entity_join_result: EntityJoinResult,
    answer_contract: AnswerContract,
    verifier_result: AnswerVerifierResult,
    loop_counter: LoopCounter,
    *,
    runtime_context: Mapping[str, Any] | None = None,
) -> ReviewReport:
    phase4_mode = str(verifier_result.extra.get("phase4_mode") or "").strip().lower()
    missing_facets = list(answer_contract.evidence_requirements.get("missing_facets") or [])
    missing_slots = list(answer_contract.tool_requirements.get("missing_slots") or [])
    failed_facets = [str(item).strip() for item in [*missing_facets, *missing_slots] if str(item).strip()]
    if verifier_result.passed:
        decision = "pass"
        retry_target = None
    elif phase4_mode == "enforce" and str(verifier_result.suggested_response_mode or "").strip().lower() == "partial_grounded":
        decision = "repair_answer"
        retry_target = verifier_result.suggested_response_mode
    elif "cross_entity_stitching" in {str(item).strip().lower() for item in verifier_result.issues}:
        decision = "degrade"
        retry_target = verifier_result.suggested_response_mode
    elif missing_facets or missing_slots:
        decision = "repair_answer"
        retry_target = verifier_result.suggested_response_mode
    else:
        decision = "repair_answer" if verifier_result.suggested_response_mode not in {"grounded", "no_answer"} else "degrade"
        retry_target = verifier_result.suggested_response_mode if decision != "pass" else None
    retry_count = int(loop_counter.repair_answer or 0)
    runtime_context = dict(runtime_context or {})
    max_retry_count = int(runtime_context.get("rewrite_loop_limit") or 0)
    if max_retry_count <= 0:
        max_retry_count = int(loop_counter.extra.get("rewrite_loop_limit") or 0)
    if max_retry_count <= 0:
        max_retry_count = 0
    target_step_id = str(runtime_context.get("target_step_id") or "").strip() or None
    if target_step_id is None:
        target_step_id = str(loop_counter.extra.get("target_step_id") or "").strip() or None
    return ReviewReport(
        decision=decision,
        reason=str(verifier_result.repair_hint or verifier_result.suggested_response_mode or "verified").strip(),
        failed_facets=failed_facets,
        repair_hint=str(verifier_result.repair_hint or ""),
        retry_target=retry_target,
        retry_count=retry_count,
        max_retry_count=max_retry_count,
        target_step_id=target_step_id,
        extra={
            "phase4_mode": phase4_mode or _phase4_mode(),
            "verifier_issues": list(verifier_result.issues),
            "answer_confidence": runtime_context.get("answer_confidence"),
            "candidate_entities": list(entity_join_result.candidate_entities),
            "selected_entity": entity_join_result.selected_entity,
            "answer_text_length": len(str(answer_text or "")),
        },
    )

