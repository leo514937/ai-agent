from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ...domain.contracts import (
    AnswerContract,
    AnswerVerifierResult,
    EntityJoinResult,
    RoutingDecision,
    EvidenceQualityDecision,
)
from .base import (
    _extract_entity_key_from_evidence_item,
    _extract_entity_key_from_tool_result,
    _normalize_entity_key,
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

    return AnswerContract(

        original_query=str(getattr(turn, "raw_query", "") or ""),

        required_facets=required_facets,

        evidence_requirements=evidence_requirements,

        tool_requirements=tool_requirements,

        forbidden_without_evidence=forbidden_without_evidence,

        candidate_entities=list(entity_join_result.candidate_entities),

        selected_entity=entity_join_result.selected_entity,

        missing_slots=missing_slots,

        clarification_slot=clarification_slot,

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

