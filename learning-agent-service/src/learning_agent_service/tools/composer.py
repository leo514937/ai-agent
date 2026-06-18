from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
import re
import time
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from learning_agent_service.domain.contracts import (
    AnswerComposeRequest,
    AnswerComposeResult,
    SseEnvelope,
    EvidenceQualityDecision,
)
from learning_agent_service.domain.utils import as_mapping as _as_mapping, clean_text as _clean_text
from learning_agent_service.config import Settings
from learning_agent_service.application.rag_gate import compose_direct_response_text
from learning_agent_service.application.workflow.adapters.helpers import build_clarification_question
from learning_agent_service.local_life.answer_contract import AnswerContract as LocalLifeAnswerContract
from learning_agent_service.local_life.answer_depth_policy import derive_answer_depth_policy
from learning_agent_service.local_life.answer_linter import lint_answer
from learning_agent_service.local_life.answer_policy import derive_answer_policy
from learning_agent_service.local_life.answer_structure_composer import AnswerStructureComposer
from learning_agent_service.local_life.coupon_result import CouponResult
from learning_agent_service.local_life.facet_result_bundle import FacetResultBundle
from learning_agent_service.local_life.response_builder.answers import (
    _build_facet_driven_answer,
    build_comparison_answer,
    build_coupon_only_answer,
    build_distance_only_answer,
    build_multi_shop_recommendation_answer,
    build_open_status_only_answer,
    build_single_shop_review_answer,
)
from learning_agent_service.local_life.response_builder import validate_answer_against_contract
from learning_agent_service.local_life.realtime_result_degrade_policy import build_realtime_degrade_message
from learning_agent_service.local_life.schemas import EvidenceClaim, RankedCandidate
from learning_agent_service.local_life.tool_result_normalizer import ToolResult as FacetToolResult
from .orchestrator_components import *# noqa: F401,F403,F405
from .claim_validator import ClaimValidator, Claim, DataSource
from ..rag.claim_types import ClaimType


_STRICT_TEMPLATE_STYLES = {
    "coupon_only",
    "open_status_only",
    "distance_only",
    "single_shop_review",
}

_STRICT_NATURAL_STYLES = {
    "facet_multi",
    "multi_shop_recommendation",
    "comparison",
}

_GENERIC_SHOP_NAMES = {"这家店", "这家", "这店", "这商家", "这个商家", "店铺", "门店", "商家"}
_STRICT_DYNAMIC_FACETS = {"coupon", "open_status", "distance_eta"}
_STRICT_NATURAL_CONTEXT_KEYS = {
    "answer_branch",
    "answer_style",
    "clarification_slot",
    "confirmed_facts",
    "confirmed_slots",
    "current_shop",
    "current_topic",
    "fact_draft",
    "missing_slots",
    "recommendation_count",
    "required_facets",
    "scene",
    "scene_detected",
    "selected_entity",
    "selected_shop_id",
    "selected_shop_name",
}


def _tool_facet_name(tool_name: str | None) -> str | None:
    mapping = {
        "get_coupon_list": "coupon",
        "check_open_status": "open_status",
        "get_distance_eta": "distance_eta",
    }
    return mapping.get(str(tool_name or "").strip())


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = _clean_text(value)
        if text:
            return text
    return None


def _extract_tool_payload(value: Any) -> dict[str, Any]:
    current = _as_mapping(value)
    for _ in range(3):
        data = current.get("data")
        if isinstance(data, Mapping) and data:
            current = _as_mapping(data)
            continue
        nested = current.get("normalized_output")
        if isinstance(nested, Mapping) and nested:
            current = _as_mapping(nested)
            continue
        break
    return dict(current)


def _build_ranked_candidates(payload: Sequence[Mapping[str, Any]] | None) -> list[RankedCandidate]:
    candidates: list[RankedCandidate] = []
    for item in list(payload or []):
        candidate_map = _as_mapping(item)
        structured_features = _as_mapping(candidate_map.get("structured_features"))
        for key in ("score", "distance_km", "avg_price"):
            if key not in structured_features and candidate_map.get(key) not in (None, ""):
                structured_features[key] = candidate_map.get(key)
        candidate_source = _clean_text(candidate_map.get("source") or structured_features.get("source"))
        if candidate_source:
            structured_features.setdefault("source", candidate_source.lower())
        vouchers = list(candidate_map.get("vouchers") or [])
        try:
            candidate = RankedCandidate.model_validate(
                {
                    "shop_id": candidate_map.get("shop_id"),
                    "name": candidate_map.get("name") or candidate_map.get("shop_name") or "",
                    "matched_requirements": list(candidate_map.get("matched_requirements") or []),
                    "explainable_reasons": list(candidate_map.get("explainable_reasons") or []),
                    "structured_features": structured_features,
                    "vouchers": vouchers,
                    "rank_score": candidate_map.get("rank_score") or candidate_map.get("score") or 0.0,
                }
            )
        except Exception:
            continue
        candidates.append(candidate)
    return candidates


def _candidate_source(candidate: Any) -> str:
    candidate_map = _as_mapping(candidate)
    structured = _as_mapping(candidate_map.get("structured_features"))
    return str(_clean_text(candidate_map.get("source") or structured.get("source") or "") or "").lower().strip()


def _coupon_source_is_trusted(coupon_result: Any) -> bool:
    coupon_map = _as_mapping(coupon_result)
    source = str(_clean_text(coupon_map.get("source") or getattr(coupon_result, "source", None)) or "").lower().strip()
    if source in {"catalog", "fallback"}:
        return False
    items = list(coupon_map.get("items") or [])
    if not items and hasattr(coupon_result, "items"):
        items = list(coupon_result.items or [])
    for item in items:
        item_source = str(_clean_text(_as_mapping(item).get("source")) or "").lower().strip()
        if item_source in {"catalog", "fallback"}:
            return False
    return True


def _build_evidence_claims(request: AnswerComposeRequest) -> list[EvidenceClaim]:
    evidence_pack = request.rag_result.evidence_pack if request.rag_result and request.rag_result.evidence_pack else None
    if evidence_pack is None:
        return []

    claims: list[EvidenceClaim] = []
    for item in list(getattr(evidence_pack, "items", []) or []):
        content = _clean_text(getattr(item, "content", None))
        if not content:
            continue
        metadata = _as_mapping(getattr(item, "metadata", {}))
        try:
            claims.append(
                EvidenceClaim.model_validate(
                    {
                        "chunk_id": str(getattr(item, "chunk_id", "") or ""),
                        "shop_id": metadata.get("shop_id"),
                        "claim": content,
                        "support_text": content,
                        "source_type": str(metadata.get("source_type") or getattr(item, "chunk_type", "") or "rag"),
                        "confidence": float(getattr(item, "score", 0.0) or 0.0),
                        "metadata": metadata,
                    }
                )
            )
        except Exception:
            continue
    return claims


def _build_facet_result_bundle(request: AnswerComposeRequest) -> FacetResultBundle | None:
    raw_bundle = _as_mapping(request.facet_result_bundle)
    raw_tool_results = list(raw_bundle.get("tool_results") or [])
    tool_results: list[FacetToolResult] = []
    now_iso = datetime.now(timezone.utc).isoformat()
    for item in raw_tool_results:
        item_map = _as_mapping(item)
        facet = str(item_map.get("facet") or "").strip() or _tool_facet_name(item_map.get("tool_name"))
        try:
            tool_results.append(
                FacetToolResult.model_validate(
                        {
                            "tool_name": str(item_map.get("tool_name") or "").strip(),
                            "facet": facet,
                            "shop_id": None if item_map.get("shop_id") in (None, "") else str(item_map.get("shop_id")),
                            "shop_name": item_map.get("shop_name"),
                            "status": str(item_map.get("status") or "success").strip().lower(),
                            "data": _as_mapping(item_map.get("data")),
                        "error_code": item_map.get("error_code"),
                        "error_message": item_map.get("error_message"),
                        "source": str(item_map.get("source") or "realtime_tool"),
                        "fetched_at": str(item_map.get("fetched_at") or now_iso),
                        "ttl_seconds": item_map.get("ttl_seconds"),
                        "is_realtime": bool(item_map.get("is_realtime", True)),
                        "confidence": float(item_map.get("confidence") or 1.0),
                    }
                )
            )
        except Exception:
            continue

    tool_result = request.tool_result
    if tool_result is not None:
        tool_name = str(getattr(tool_result, "tool_name", "") or "").strip()
        facet = _tool_facet_name(tool_name)
        if facet and not any(str(item.facet or "").strip() == facet for item in tool_results):
            normalized_output = _extract_tool_payload(getattr(tool_result, "normalized_output", {}))
            data = _extract_tool_payload(
                normalized_output.get("data")
                or normalized_output
                or getattr(tool_result, "data", None)
                or {}
            )
            status = str(getattr(tool_result, "status", "") or "").strip().lower() or "success"
            try:
                tool_results.append(
                    FacetToolResult.model_validate(
                        {
                            "tool_name": tool_name,
                            "facet": facet,
                            "shop_id": None if data.get("shop_id") in (None, "") else str(data.get("shop_id")),
                            "shop_name": data.get("shop_name"),
                            "status": status,
                            "data": data,
                            "error_code": getattr(tool_result, "error_code", None),
                            "error_message": getattr(tool_result, "error_message", None),
                            "source": "realtime_tool",
                            "fetched_at": now_iso,
                            "ttl_seconds": None,
                            "is_realtime": True,
                            "confidence": float(getattr(tool_result, "confidence", 1.0) or 1.0),
                        }
                    )
                )
            except Exception:
                pass

    coupon_result = raw_bundle.get("coupon_result")
    coupon_model = None
    if isinstance(coupon_result, Mapping):
        try:
            coupon_model = CouponResult.model_validate(coupon_result)
        except Exception:
            coupon_model = None
    elif hasattr(coupon_result, "model_dump"):
        try:
            coupon_model = CouponResult.model_validate(coupon_result.model_dump(mode="json"))
        except Exception:
            coupon_model = None

    open_status_result = raw_bundle.get("open_status_result")
    if not isinstance(open_status_result, Mapping):
        open_status_result = _as_mapping(open_status_result)
    distance_eta_result = raw_bundle.get("distance_eta_result")
    if not isinstance(distance_eta_result, Mapping):
        distance_eta_result = _as_mapping(distance_eta_result)

    if not (coupon_model or open_status_result or distance_eta_result or tool_results):
        return None

    return FacetResultBundle(
        coupon_result=coupon_model,
        open_status_result=dict(open_status_result) if isinstance(open_status_result, Mapping) else None,
        distance_eta_result=dict(distance_eta_result) if isinstance(distance_eta_result, Mapping) else None,
        tool_results=tool_results,
    )


def _build_user_need_proxy(request: AnswerComposeRequest, ranked_candidates: Sequence[RankedCandidate]) -> Any:
    answer_context = _as_mapping(request.answer_context)
    required_facets = [SimpleNamespace(name=str(item).strip()) for item in list(answer_context.get("required_facets") or []) if str(item).strip()]
    if not required_facets and request.answer_contract is not None:
        required_facets = [SimpleNamespace(name=str(item).strip()) for item in list(getattr(request.answer_contract, "allowed_facets", []) or []) if str(item).strip()]
    constraints = dict(answer_context)
    constraints.setdefault("current_shop", _first_text(answer_context.get("current_shop"), answer_context.get("current_topic")))
    constraints.setdefault("selected_shop_name", constraints.get("current_shop"))
    constraints.setdefault("shop_name", constraints.get("current_shop"))
    constraints.setdefault("scene", answer_context.get("scene"))
    constraints.setdefault("scene_detected", answer_context.get("scene"))
    recommendation_count = answer_context.get("recommendation_count")
    try:
        recommendation_count = max(1, int(recommendation_count))
    except Exception:
        recommendation_count = max(1, len(list(ranked_candidates)) or 3)
    intent = ""
    routing = request.routing_decision
    if routing is not None and getattr(routing, "intent", None) is not None:
        intent = str(getattr(routing.intent, "name", "") or "").strip()
    return SimpleNamespace(
        raw_query=request.raw_query,
        required_facets=required_facets,
        missing_slots=list(request.missing_slots or []),
        recommendation_count=recommendation_count,
        constraints=constraints,
        intent=intent,
    )


def _build_local_life_contract(request: AnswerComposeRequest) -> LocalLifeAnswerContract | None:
    answer_contract = request.answer_contract
    if answer_contract is None:
        return None

    answer_style = str(getattr(answer_contract, "answer_style", "") or "").strip()
    if not answer_style:
        return None

    allowed_facets = [str(item).strip() for item in list(getattr(answer_contract, "allowed_facets", []) or []) if str(item).strip()]
    forbidden_facets = [str(item).strip() for item in list(getattr(answer_contract, "forbidden_facets", []) or []) if str(item).strip()]
    realtime_facets = [facet for facet in allowed_facets if facet in _STRICT_DYNAMIC_FACETS]
    allowed_rag_facets = [facet for facet in allowed_facets if facet not in _STRICT_DYNAMIC_FACETS]
    forbidden_rag_facets = list(dict.fromkeys([*forbidden_facets, *realtime_facets]))
    allowed_tools: list[str] = []
    if "coupon" in allowed_facets:
        allowed_tools.append("get_coupon_list")
    if "open_status" in allowed_facets:
        allowed_tools.extend(["check_open_status", "getShopDetail", "getBusinessStatus"])
    if "distance_eta" in allowed_facets:
        allowed_tools.append("get_distance_eta")
    if answer_style in {"multi_shop_recommendation", "comparison", "facet_multi"}:
        allowed_tools.extend(["search_restaurants", "getShopDetail", "recommendShops"])
    allow_recommendation = answer_style in {"multi_shop_recommendation", "comparison", "facet_multi"}
    allow_extra_context = allow_recommendation or answer_style == "single_shop_review"
    realtime_required = bool(realtime_facets)

    try:
        return LocalLifeAnswerContract(
            original_query=request.raw_query,
            allowed_facets=allowed_facets,
            forbidden_facets=forbidden_facets,
            allowed_tools=list(dict.fromkeys(allowed_tools)),
            allowed_rag_facets=allowed_rag_facets,
            forbidden_rag_facets=forbidden_rag_facets,
            realtime_facets=realtime_facets,
            allow_recommendation=allow_recommendation,
            allow_extra_context=allow_extra_context,
            realtime_required=realtime_required,
            evidence_policy="strict" if not allow_extra_context else "balanced",
            answer_style=answer_style,
            missing_info_policy="say_unknown",
        )
    except Exception:
        return None


def _resolved_strict_topic_name(request: AnswerComposeRequest, ranked_candidates: Sequence[RankedCandidate]) -> str:
    answer_context = _as_mapping(request.answer_context)
    stream_meta = _as_mapping(request.stream_event_meta)
    answer_contract = request.answer_contract
    topic = _first_text(
        answer_context.get("current_shop"),
        answer_context.get("current_topic"),
        stream_meta.get("current_shop"),
        stream_meta.get("selected_shop_name"),
        getattr(answer_contract, "selected_entity", None) if answer_contract is not None else None,
    )
    if topic and topic not in _GENERIC_SHOP_NAMES:
        return topic
    for candidate in ranked_candidates:
        candidate_name = _clean_text(getattr(candidate, "name", None))
        if candidate_name and candidate_name not in _GENERIC_SHOP_NAMES:
            return candidate_name
    query_text = _clean_text(request.raw_query)
    if query_text and query_text not in _GENERIC_SHOP_NAMES:
        return query_text
    return "这家店"


def _strict_fallback_mode(request: AnswerComposeRequest) -> str:
    evidence_quality = request.evidence_quality
    if list(request.missing_slots or []) or _clean_text(request.clarification_slot) or _clean_text(getattr(evidence_quality, "clarification_slot", None)):
        return "ask_clarification"
    return "no_answer"


def _strict_preflight_check(
    request: AnswerComposeRequest,
    *,
    local_contract: LocalLifeAnswerContract,
    ranked_candidates: Sequence[RankedCandidate],
    facet_bundle: FacetResultBundle | None,
) -> tuple[bool, str | None]:
    answer_style = str(local_contract.answer_style or "").strip().lower()
    topic_name = _resolved_strict_topic_name(request, ranked_candidates)
    top_candidate = ranked_candidates[0] if ranked_candidates else None
    shop_id = getattr(top_candidate, "shop_id", None)

    if answer_style in {"coupon_only", "open_status_only", "distance_only", "single_shop_review"} and topic_name in _GENERIC_SHOP_NAMES:
        return False, _strict_fallback_mode(request)

    if answer_style == "coupon_only":
        if top_candidate is None:
            return False, _strict_fallback_mode(request)
        if _candidate_source(top_candidate) in {"catalog", "fallback"}:
            return False, _strict_fallback_mode(request)
        tool_result = facet_bundle.find_tool_result("coupon", shop_id=shop_id) if facet_bundle is not None else None
        coupon_count = None
        if tool_result is not None:
            if str(_clean_text(getattr(tool_result, "source", None)) or "").lower().strip() in {"catalog", "fallback"}:
                return False, _strict_fallback_mode(request)
            if tool_result.status in {"timeout", "error", "degraded", "unsupported"}:
                return False, _strict_fallback_mode(request)
            try:
                coupon_count = int(tool_result.data.get("count") or 0)
            except Exception:
                coupon_count = 0
        elif facet_bundle is not None and facet_bundle.coupon_result is not None:
            if not _coupon_source_is_trusted(facet_bundle.coupon_result):
                return False, _strict_fallback_mode(request)
            coupon_count = int(getattr(facet_bundle.coupon_result, "realtime_available_count", 0) or 0)
        if coupon_count is None:
            return False, _strict_fallback_mode(request)
        return True, None

    if answer_style == "open_status_only":
        if top_candidate is None:
            return False, _strict_fallback_mode(request)
        if _candidate_source(top_candidate) in {"catalog", "fallback"}:
            return False, _strict_fallback_mode(request)
        tool_result = facet_bundle.find_tool_result("open_status", shop_id=shop_id) if facet_bundle is not None else None
        if tool_result is None:
            return False, _strict_fallback_mode(request)
        if str(_clean_text(getattr(tool_result, "source", None)) or "").lower().strip() in {"catalog", "fallback"}:
            return False, _strict_fallback_mode(request)
        if tool_result.status in {"timeout", "error", "degraded", "unsupported"}:
            return False, _strict_fallback_mode(request)
        open_status = str(tool_result.data.get("open_status") or "").strip().lower()
        if open_status not in {"open", "closed"} and tool_result.data.get("open_now") not in {True, False}:
            return False, _strict_fallback_mode(request)
        return True, None

    if answer_style == "distance_only":
        if top_candidate is None:
            return False, _strict_fallback_mode(request)
        if _candidate_source(top_candidate) in {"catalog", "fallback"}:
            return False, _strict_fallback_mode(request)
        tool_result = facet_bundle.find_tool_result("distance_eta", shop_id=shop_id) if facet_bundle is not None else None
        distance_value = None
        if tool_result is not None:
            if str(_clean_text(getattr(tool_result, "source", None)) or "").lower().strip() in {"catalog", "fallback"}:
                return False, _strict_fallback_mode(request)
        if tool_result is not None and tool_result.status not in {"timeout", "error", "degraded", "unsupported"}:
            distance_value = tool_result.data.get("distance_km")
        if distance_value in (None, ""):
            return False, _strict_fallback_mode(request)
        return True, None

    if answer_style == "single_shop_review":
        if top_candidate is None or not _clean_text(getattr(top_candidate, "name", None)):
            return False, _strict_fallback_mode(request)
        if _candidate_source(top_candidate) in {"catalog", "fallback"}:
            return False, _strict_fallback_mode(request)
        structured = getattr(top_candidate, "structured_features", {}) or {}
        if any(structured.get(key) in (None, "") for key in ("score", "avg_price", "distance_km")):
            return False, _strict_fallback_mode(request)
        return True, None

    if answer_style == "multi_shop_recommendation":
        if not ranked_candidates:
            return False, _strict_fallback_mode(request)
        for candidate in ranked_candidates[:3]:
            if _candidate_source(candidate) in {"catalog", "fallback"}:
                return False, _strict_fallback_mode(request)
            structured = getattr(candidate, "structured_features", {}) or {}
            if not _clean_text(getattr(candidate, "name", None)):
                return False, _strict_fallback_mode(request)
            if any(structured.get(key) in (None, "") for key in ("score", "avg_price", "distance_km")):
                return False, _strict_fallback_mode(request)
        return True, None

    if answer_style == "comparison":
        if len(ranked_candidates) < 2:
            return False, _strict_fallback_mode(request)
        for candidate in ranked_candidates[:2]:
            if _candidate_source(candidate) in {"catalog", "fallback"}:
                return False, _strict_fallback_mode(request)
            structured = getattr(candidate, "structured_features", {}) or {}
            if not _clean_text(getattr(candidate, "name", None)):
                return False, _strict_fallback_mode(request)
            if any(structured.get(key) in (None, "") for key in ("score", "avg_price", "distance_km")):
                return False, _strict_fallback_mode(request)
        return True, None

    if answer_style == "facet_multi":
        requested_facets = [str(item).strip() for item in list(_as_mapping(request.answer_context).get("required_facets") or []) if str(item).strip()]
        if not requested_facets:
            requested_facets = [str(item).strip() for item in list(getattr(local_contract, "allowed_facets", []) or []) if str(item).strip()]
        if not requested_facets:
            return False, _strict_fallback_mode(request)
        if any(facet in _STRICT_DYNAMIC_FACETS for facet in requested_facets):
            if facet_bundle is None:
                return False, _strict_fallback_mode(request)
        if any(facet in {"shop_detail", "recommendation_reason", "scene_fit", "environment", "taste", "service"} for facet in requested_facets):
            if top_candidate is None or not _clean_text(getattr(top_candidate, "name", None)):
                return False, _strict_fallback_mode(request)
            if _candidate_source(top_candidate) in {"catalog", "fallback"}:
                return False, _strict_fallback_mode(request)
            if not _build_evidence_claims(request):
                return False, _strict_fallback_mode(request)
        return True, None

    return False, _strict_fallback_mode(request)


def _strict_required_terms(
    *,
    topic_name: str,
    ranked_candidates: Sequence[RankedCandidate],
    answer_style: str,
) -> list[str]:
    terms: list[str] = []
    topic = _clean_text(topic_name)
    if topic and topic not in _GENERIC_SHOP_NAMES:
        terms.append(topic)

    max_candidates = 2 if answer_style == "comparison" else 3
    for candidate in list(ranked_candidates)[:max_candidates]:
        candidate_name = _clean_text(getattr(candidate, "name", None))
        if candidate_name and candidate_name not in _GENERIC_SHOP_NAMES:
            terms.append(candidate_name)
        structured = getattr(candidate, "structured_features", {}) or {}
        for key in ("score", "avg_price", "distance_km"):
            value = structured.get(key)
            if value in (None, ""):
                continue
            try:
                if key == "score":
                    terms.append(f"{float(value):.1f}")
                elif key == "avg_price":
                    terms.append(f"{int(round(float(value)))}元")
                elif key == "distance_km":
                    distance = float(value)
                    terms.append(f"{distance:.1f}km")
                    terms.append(f"{distance:.1f}公里")
            except Exception:
                terms.append(str(value).strip())

    return [term for term in dict.fromkeys(term for term in terms if term.strip())]


def _strict_natural_answer_is_valid(
    *,
    candidate_answer: str,
    draft_answer: str,
    required_terms: Sequence[str],
    local_contract: LocalLifeAnswerContract,
    topic_name: str,
    ranked_candidates: Sequence[RankedCandidate],
    evidence_claims: Sequence[EvidenceClaim],
    facet_bundle: FacetResultBundle | None,
    user_need: Any | None,
    answer_context: Any | None,
) -> bool:
    candidate_text = _clean_text(candidate_answer)
    draft_text = _clean_text(draft_answer)
    if not candidate_text or not draft_text:
        return False
    for candidate in ranked_candidates[:3]:
        if _candidate_source(candidate) in {"catalog", "fallback"}:
            return False
    if facet_bundle is not None:
        if facet_bundle.coupon_result is not None and not _coupon_source_is_trusted(facet_bundle.coupon_result):
            return False
        for tool_result in list(getattr(facet_bundle, "tool_results", []) or []):
            if str(_clean_text(getattr(tool_result, "source", None)) or "").lower().strip() in {"catalog", "fallback"}:
                return False
    lint_result = lint_answer(
        answer_text=candidate_text,
        answer_contract=local_contract,
        topic_name=topic_name,
        ranked_candidates=ranked_candidates,
        evidence_claims=evidence_claims,
        facet_result_bundle=facet_bundle,
        user_need=user_need,
        answer_context=answer_context,
    )
    if lint_result.severity == "block":
        return False
    for term in required_terms:
        normalized_term = _clean_text(term)
        if normalized_term and normalized_term not in candidate_text:
            return False
    draft_signature = re.sub(r"[\W_]+", "", draft_text).lower()
    candidate_signature = re.sub(r"[\W_]+", "", candidate_text).lower()
    if not draft_signature or not candidate_signature:
        return False
    if candidate_signature == draft_signature:
        return True
    return all(term in candidate_text for term in required_terms if term)


def _sanitize_request_for_strict_natural(request: AnswerComposeRequest, draft_answer: str) -> AnswerComposeRequest:
    answer_context = dict(_as_mapping(request.answer_context))
    sanitized_context = {
        key: value
        for key, value in answer_context.items()
        if key in _STRICT_NATURAL_CONTEXT_KEYS and value not in (None, "", [], {}, ())
    }
    sanitized_context["answer_branch"] = "strict_natural"
    sanitized_context["fact_draft"] = draft_answer
    sanitized_context["confirmed_slots"] = sanitized_context.get("confirmed_slots") or sanitized_context.get("confirmed_facts") or []
    sanitized_context.pop("confirmed_facts", None)
    sanitized_context.pop("history_summary", None)
    sanitized_context.pop("historySummary", None)
    sanitized_context.pop("plan_summary", None)
    sanitized_context.pop("memory_injection_plan", None)
    sanitized_context.pop("client_context", None)
    sanitized_context.pop("clientContext", None)
    sanitized_context.pop("fallback_catalog", None)
    sanitized_context.pop("fallbackCatalog", None)
    sanitized_candidates = []
    for candidate in _build_ranked_candidates(request.ranked_candidates):
        source = _candidate_source(candidate)
        if source in {"catalog", "fallback"}:
            continue
        sanitized_candidates.append(candidate.model_dump(mode="json"))
    sanitized_facet_bundle = None
    facet_bundle = _build_facet_result_bundle(request)
    if facet_bundle is not None:
        facet_bundle_map = dict(_as_mapping(facet_bundle))
        coupon_result = facet_bundle_map.get("coupon_result")
        if coupon_result is not None and not _coupon_source_is_trusted(coupon_result):
            facet_bundle_map["coupon_result"] = None
        tool_results = []
        for tool_result in list(facet_bundle_map.get("tool_results") or []):
            source = str(_clean_text(_as_mapping(tool_result).get("source")) or "").lower().strip()
            if source in {"catalog", "fallback"}:
                continue
            tool_results.append(_as_mapping(tool_result))
        facet_bundle_map["tool_results"] = tool_results
        if any(value not in (None, "", [], {}, ()) for value in facet_bundle_map.values()):
            sanitized_facet_bundle = facet_bundle_map
    return request.model_copy(
        update={
            "history_summary": None,
            "plan_summary": None,
            "memory_injection_plan": None,
            "ranked_candidates": sanitized_candidates,
            "facet_result_bundle": sanitized_facet_bundle,
            "answer_context": sanitized_context,
        }
    )




@dataclass
class AnswerComposer:
    llm_answerer: Callable[[AnswerComposeRequest], Mapping[str, Any] | str] | None = None
    max_citations: int = 4

    def compose(self, request: AnswerComposeRequest) -> AnswerComposeResult:
        if request.allow_direct_response:
            routing = request.routing_decision
            if routing is not None and str(routing.required_action).strip().lower() == "clarify":
                answer_text = self._compose_clarify_response(request, routing)
            elif str(request.direct_response_kind or "").strip().lower() == "conversation_recap":
                answer_text = self._compose_conversation_recap_response(request)
            else:
                answer_text = compose_direct_response_text(
                    request.raw_query,
                    request.direct_response_kind,
                )
            confidence = 0.24 if (routing is not None and routing.required_action == "clarify") else 0.82
            return self._build_result(request, answer_text, confidence, already_streamed=False)

        routing = request.routing_decision
        rag_result = request.rag_result
        evidence_status = self._evidence_status(rag_result)
        evidence_quality = request.evidence_quality
        response_mode = str(
            request.final_response_mode
            or getattr(evidence_quality, "response_mode", "")
            or ""
        ).strip().lower()
        answer_style = str(getattr(request.answer_contract, "answer_style", "") or "").strip().lower()
        answer_policy = derive_answer_policy(
            response_mode=response_mode,
            answer_style=answer_style,
            realtime_required=bool(getattr(request.answer_contract, "realtime_required", False)),
            answer_context=request.answer_context,
        )
        if response_mode == "ask_clarification":
            answer_text = self._compose_clarify_response(request, routing)
            if request.plan_summary is not None or request.tool_result is not None or request.memory_injection_plan is not None:
                answer_text = self._append_auxiliary_sections(request, answer_text, include_auxiliary=True)
            return self._build_result(request, answer_text, 0.2, already_streamed=False)
        if response_mode == "partial_grounded" and request.tool_result is None and rag_result is not None:
            answer_text = self._compose_partial_grounded_answer(request)
            if request.plan_summary is not None or request.tool_result is not None or request.memory_injection_plan is not None:
                answer_text = self._append_auxiliary_sections(request, answer_text, include_auxiliary=True)
            return self._build_result(request, answer_text, 0.55, already_streamed=False)

        if response_mode == "grounded_strict":
            if answer_policy.branch == "strict_natural":
                answer_text = self._compose_grounded_strict_natural_answer(request)
            else:
                answer_text = self._compose_grounded_strict_answer(request)
            if request.plan_summary is not None or request.tool_result is not None or request.memory_injection_plan is not None:
                answer_text = self._append_auxiliary_sections(request, answer_text, include_auxiliary=True)
            return self._build_result(request, answer_text, 0.92, already_streamed=False)

        mixed_answer = self._compose_rag_plus_tool_answer(request)
        if mixed_answer is not None:
            confidence = 0.88 if request.tool_result is not None and request.rag_result is not None else 0.62
            return self._build_result(request, mixed_answer, confidence, already_streamed=False)

        tool_answer = self._compose_tool_answer(request)
        if tool_answer is not None:
            confidence = 0.86 if request.tool_result and request.tool_result.extra.get("grounding_source") == "business_evidence" else 0.42
            return self._build_result(request, tool_answer, confidence, already_streamed=False)

        if response_mode == "no_answer":
            answer_text = self._compose_no_answer(request, evidence_quality)
            if request.plan_summary is not None or request.tool_result is not None or request.memory_injection_plan is not None:
                answer_text = self._append_auxiliary_sections(request, answer_text, include_auxiliary=True)
            return self._build_result(request, answer_text, 0.08, already_streamed=False)
        if response_mode == "weak_answer":
            answer_text = self._compose_weak_answer(request)
            if request.plan_summary is not None or request.tool_result is not None or request.memory_injection_plan is not None:
                answer_text = self._append_auxiliary_sections(request, answer_text, include_auxiliary=True)
            return self._build_result(request, answer_text, 0.38, already_streamed=False)

        if (
            self.llm_answerer is not None
            and evidence_status in {"EMPTY", "WEAK"}
            and request.plan_summary is None
            and request.tool_result is None
            and request.memory_injection_plan is None
            and not response_mode
        ):
            answer, already_streamed = self._compose_open_answer(request)
            if answer:
                confidence = 0.74 if evidence_status == "EMPTY" else 0.62
                return self._build_result(request, answer, confidence, already_streamed=already_streamed)
        if evidence_status == "EMPTY":
            action = str(getattr(routing, "required_action", "") or "").strip().lower()
            if action == "rag_plus_tool" or (request.tool_result is not None and request.tool_result.status == ToolExecutionStatus.SUCCESS):
                mixed_answer = self._compose_rag_plus_tool_answer(request)
                if mixed_answer is not None:
                    return self._build_result(request, mixed_answer, 0.62, already_streamed=False)
                tool_answer = self._compose_tool_answer(request)
                if tool_answer is not None:
                    return self._build_result(request, tool_answer, 0.42, already_streamed=False)
                fallback_ans = "我这边暂时没有查到这家店的详细评价依据或可用券信息。你可以放宽筛选范围，我继续帮你找。"
                return self._build_result(request, fallback_ans, 0.1, already_streamed=False)

            if self.llm_answerer is None:
                answer_text = self._compose_weak_answer(request)
            elif answer_style in _STRICT_TEMPLATE_STYLES and request.answer_contract is not None:
                answer_text = self._compose_empty_evidence_style_answer(request)
            else:
                answer_text = self._compose_weak_answer(request)
            if request.plan_summary is not None or request.tool_result is not None or request.memory_injection_plan is not None:
                answer_text = self._append_auxiliary_sections(request, answer_text, include_auxiliary=True)
            return self._build_result(request, answer_text, 0.05, already_streamed=False)

        if evidence_status == "OK":
            answer, already_streamed = self._compose_grounded_answer(request)
            if not answer:
                answer = self._grounded_fallback(request)
                already_streamed = False
            return self._build_result(
                request,
                answer,
                0.9 if self.llm_answerer is not None else 0.84,
                already_streamed=already_streamed,
            )

        answer = self._compose_weak_answer(request)
        return self._build_result(request, answer, 0.58, already_streamed=False)

    def _compose_open_answer(self, request: AnswerComposeRequest) -> tuple[str | None, bool]:
        payload = None
        already_streamed = False
        if self.llm_answerer is not None:
            try:
                stream_relay = _StreamEventRelay(request.stream_event_sink)
                request_with_relay = request.model_copy(update={"stream_event_sink": stream_relay})
                payload = self.llm_answerer(request_with_relay)
                already_streamed = stream_relay.count > 0
            except Exception:
                payload = None
        answer_text = self._extract_answer_text(payload)
        if not answer_text:
            return None, already_streamed
        return self._append_auxiliary_sections(request, answer_text, include_auxiliary=False), already_streamed

    def _compose_grounded_answer(self, request: AnswerComposeRequest) -> tuple[str, bool]:
        payload = None
        already_streamed = False
        if self.llm_answerer is not None:
            try:
                stream_relay = _StreamEventRelay(request.stream_event_sink)
                request_with_relay = request.model_copy(update={"stream_event_sink": stream_relay})
                payload = self.llm_answerer(request_with_relay)
                already_streamed = stream_relay.count > 0
            except Exception:
                payload = None
        answer_text = self._extract_answer_text(payload)
        if not answer_text:
            answer_text = self._grounded_fallback(request)
        citations = self._collect_citations(request)
        if citations:
            answer_text = self._ensure_citations(answer_text, citations)
        return self._append_auxiliary_sections(request, answer_text, include_auxiliary=True), already_streamed

    def _compose_grounded_strict_answer(self, request: AnswerComposeRequest) -> str:
        ranked_candidates = _build_ranked_candidates(request.ranked_candidates)
        facet_bundle = _build_facet_result_bundle(request)
        local_contract = _build_local_life_contract(request)
        if local_contract is None:
            return self._compose_no_answer(request, request.evidence_quality)

        strict_ready, fallback_mode = _strict_preflight_check(
            request,
            local_contract=local_contract,
            ranked_candidates=ranked_candidates,
            facet_bundle=facet_bundle,
        )
        if not strict_ready:
            if fallback_mode == "ask_clarification":
                return self._compose_clarify_response(request, request.routing_decision)
            return self._compose_no_answer(request, request.evidence_quality)

        topic_name = _resolved_strict_topic_name(request, ranked_candidates)
        evidence_claims = _build_evidence_claims(request)
        user_need = _build_user_need_proxy(request, ranked_candidates)
        
        # 添加 claim 校验：确保 realtime facts 只信 ToolResult
        if facet_bundle is not None:
            tool_results = getattr(facet_bundle, "tool_results", []) or []
            realtime_claims: list[Claim] = []
            for tool_result in tool_results:
                source = str(getattr(tool_result, "source", "") or "").lower().strip()
                if source in {"catalog", "fallback"}:
                    continue
                # 从 tool_result 提取 claims
                if hasattr(tool_result, "tool_name") and hasattr(tool_result, "data"):
                    claims_from_tool = self._extract_claims_from_tool_result(tool_result)
                    realtime_claims.extend(claims_from_tool)
            
            if realtime_claims:
                validator = ClaimValidator()
                validation_result = validator.validate(realtime_claims)
                if validation_result.rejected_claims:
                    import logging
                    logging.getLogger(__name__).warning(
                        f"Realtime claim validation rejected {len(validation_result.rejected_claims)} claims: "
                        f"{validation_result.reasons}"
                    )
                    # 返回错误信息，不进入 LLM answerer 输入
                    return "查询结果中包含无法验证的实时信息，暂时无法给出可靠答案。请稍后重试或补充更多信息。"
        
        template_answer = self._build_strict_template_answer(
            local_contract=local_contract,
            topic_name=topic_name,
            ranked_candidates=ranked_candidates,
            evidence_claims=evidence_claims,
            facet_bundle=facet_bundle,
            user_need=user_need,
        )
        if not template_answer:
            if fallback_mode == "ask_clarification":
                return self._compose_clarify_response(request, request.routing_decision)
            return self._compose_no_answer(request, request.evidence_quality)
        answer_text = validate_answer_against_contract(
            template_answer,
            local_contract,
            topic_name,
            ranked_candidates,
            evidence_claims,
            facet_result_bundle=facet_bundle,
            user_need=user_need,
            answer_context=request.answer_context,
        )
        if not answer_text:
            if fallback_mode == "ask_clarification":
                return self._compose_clarify_response(request, request.routing_decision)
            return self._compose_no_answer(request, request.evidence_quality)
        return answer_text

    def _compose_grounded_strict_natural_answer(self, request: AnswerComposeRequest) -> str:
        ranked_candidates = _build_ranked_candidates(request.ranked_candidates)
        facet_bundle = _build_facet_result_bundle(request)
        local_contract = _build_local_life_contract(request)
        if local_contract is None:
            return self._compose_no_answer(request, request.evidence_quality)

        strict_ready, fallback_mode = _strict_preflight_check(
            request,
            local_contract=local_contract,
            ranked_candidates=ranked_candidates,
            facet_bundle=facet_bundle,
        )
        if not strict_ready:
            if fallback_mode == "ask_clarification":
                return self._compose_clarify_response(request, request.routing_decision)
            return self._compose_no_answer(request, request.evidence_quality)

        topic_name = _resolved_strict_topic_name(request, ranked_candidates)
        evidence_claims = _build_evidence_claims(request)
        user_need = _build_user_need_proxy(request, ranked_candidates)
        
        # 添加 claim 校验：确保 realtime facts 只信 ToolResult
        if facet_bundle is not None:
            tool_results = getattr(facet_bundle, "tool_results", []) or []
            realtime_claims: list[Claim] = []
            for tool_result in tool_results:
                source = str(getattr(tool_result, "source", "") or "").lower().strip()
                if source in {"catalog", "fallback"}:
                    continue
                # 从 tool_result 提取 claims
                if hasattr(tool_result, "tool_name") and hasattr(tool_result, "data"):
                    claims_from_tool = self._extract_claims_from_tool_result(tool_result)
                    realtime_claims.extend(claims_from_tool)
            
            if realtime_claims:
                validator = ClaimValidator()
                validation_result = validator.validate(realtime_claims)
                if validation_result.rejected_claims:
                    import logging
                    logging.getLogger(__name__).warning(
                        f"Realtime claim validation rejected {len(validation_result.rejected_claims)} claims: "
                        f"{validation_result.reasons}"
                    )
                    # 返回错误信息，不进入 LLM answerer 输入
                    return "查询结果中包含无法验证的实时信息，暂时无法给出可靠答案。请稍后重试或补充更多信息。"
        
        clean_count = len(evidence_claims)
        strong_count = sum(1 for claim in evidence_claims if str(getattr(claim, "source_type", "") or "").strip().lower() in {"tool", "realtime_tool"})
        medium_count = max(0, clean_count - strong_count)
        answer_depth_policy = derive_answer_depth_policy(
            local_contract,
            clean_evidence_count=clean_count,
            strong_evidence_count=strong_count,
            medium_evidence_count=medium_count,
        )
        structure = AnswerStructureComposer().compose(
            answer_contract=local_contract,
            topic_name=topic_name,
            ranked_candidates=ranked_candidates,
            evidence_claims=evidence_claims,
            answer_depth_policy=answer_depth_policy,
            user_need=user_need,
            facet_result_bundle=facet_bundle,
        )
        draft_answer = str(structure.answer_text or "").strip()
        if not draft_answer:
            if fallback_mode == "ask_clarification":
                return self._compose_clarify_response(request, request.routing_decision)
            return self._compose_no_answer(request, request.evidence_quality)

        # strict_natural 也必须保持强约束：这里只使用确定性草稿，不再调用通用 LLM 生成正文。
        answer_text = draft_answer

        required_terms = _strict_required_terms(
            topic_name=topic_name,
            ranked_candidates=ranked_candidates,
            answer_style=str(getattr(local_contract, "answer_style", "") or "").strip().lower(),
        )
        if not _strict_natural_answer_is_valid(
            candidate_answer=answer_text,
            draft_answer=draft_answer,
            required_terms=required_terms,
            local_contract=local_contract,
            topic_name=topic_name,
            ranked_candidates=ranked_candidates,
            evidence_claims=evidence_claims,
            facet_bundle=facet_bundle,
            user_need=user_need,
            answer_context=request.answer_context,
        ):
            if fallback_mode == "ask_clarification":
                return self._compose_clarify_response(request, request.routing_decision)
            return self._compose_no_answer(request, request.evidence_quality)

        return answer_text

    def _build_strict_template_answer(
        self,
        *,
        local_contract: LocalLifeAnswerContract,
        topic_name: str,
        ranked_candidates: Sequence[RankedCandidate],
        evidence_claims: Sequence[EvidenceClaim],
        facet_bundle: FacetResultBundle | None,
        user_need: Any | None,
    ) -> str:
        answer_style = str(getattr(local_contract, "answer_style", "") or "").strip().lower()
        if answer_style == "coupon_only":
            return build_coupon_only_answer(topic_name, ranked_candidates, evidence_claims, facet_result_bundle=facet_bundle)
        if answer_style == "open_status_only":
            return build_open_status_only_answer(topic_name, ranked_candidates, evidence_claims, facet_result_bundle=facet_bundle)
        if answer_style == "distance_only":
            return build_distance_only_answer(topic_name, ranked_candidates, evidence_claims, facet_result_bundle=facet_bundle)
        if answer_style == "single_shop_review":
            return build_single_shop_review_answer(topic_name, ranked_candidates, evidence_claims)
        if answer_style == "multi_shop_recommendation":
            return build_multi_shop_recommendation_answer(
                topic_name,
                ranked_candidates,
                evidence_claims,
                user_need=user_need,
                facet_result_bundle=facet_bundle,
            )
        if answer_style == "comparison":
            return build_comparison_answer(
                topic_name=topic_name,
                ranked_candidates=ranked_candidates,
                evidence_claims=evidence_claims,
                answer_contract=local_contract,
                user_need=user_need,
                facet_result_bundle=facet_bundle,
            )
        if answer_style == "facet_multi":
            return _build_facet_driven_answer(
                current_topic=topic_name,
                ranked_candidates=ranked_candidates,
                evidence_claims=evidence_claims,
                user_need=user_need,
                facet_result_bundle=facet_bundle,
            )
        return ""

    def _build_result(
        self,
        request: AnswerComposeRequest,
        answer_text: str,
        confidence: float,
        *,
        already_streamed: bool = False,
    ) -> AnswerComposeResult:
        normalized = str(answer_text or "").strip()
        if str(request.final_response_mode or "").strip().lower() != "grounded_strict":
            normalized = self._append_plan_summary(request, normalized)

        if normalized and not already_streamed:
            self._emit_fallback_answer_stream(request, normalized)
        return AnswerComposeResult(answer_text=normalized, confidence=confidence)

    def _emit_fallback_answer_stream(self, request: AnswerComposeRequest, answer_text: str) -> None:
        stream_sink = request.stream_event_sink
        if stream_sink is None:
            return

        meta = dict(request.stream_event_meta or {})
        chunks = self._chunk_answer_text(answer_text)
        if not chunks:
            return

        accumulated = []
        for chunk in chunks:
            chunk = str(chunk or "")
            if not chunk.strip():
                continue
            accumulated.append(chunk)
            envelope = SseEnvelope(
                event_type="delta",
                trace_id=str(meta.get("trace_id") or ""),
                session_id=str(meta.get("session_id") or ""),
                turn_id=str(meta.get("turn_id") or ""),
                timestamp=datetime.now(timezone.utc),
                workflow_version=str(meta.get("workflow_version") or "learn-agent/v1"),
                payload={
                    "delta": chunk,
                    "answer_text": "".join(accumulated),
                    "current_stage": str(meta.get("current_stage") or "compose"),
                    "stage_status": str(meta.get("stage_status") or "streaming"),
                    "route_decision": meta.get("route_decision"),
                    "route_reason": meta.get("route_reason"),
                },
            )
            if callable(stream_sink):
                stream_sink(envelope)
                time.sleep(0.05)
                continue
            put = getattr(stream_sink, "put", None)
            if callable(put):
                put(envelope)
                time.sleep(0.05)

    @staticmethod
    def _chunk_answer_text(answer_text: str) -> list[str]:
        text = str(answer_text or "").strip()
        if not text:
            return []

        pieces = [piece for piece in re.split(r"(?<=[。！？!?；;\n])", text) if piece]
        if len(pieces) <= 1:
            size = 24
            return [text[i : i + size] for i in range(0, len(text), size)]

        chunks: list[str] = []
        for piece in pieces:
            if len(piece) <= 24:
                chunks.append(piece)
                continue
            chunks.extend(piece[i : i + 24] for i in range(0, len(piece), 24))
        return chunks

    def _compose_tool_answer(self, request: AnswerComposeRequest) -> str | None:
        tool_result = request.tool_result
        if tool_result is None or not tool_result.tool_name:
            return None
        failure_category = str(tool_result.extra.get("failure_category") or "").strip().lower()
        degrade_message = build_realtime_degrade_message(
            tool_name=tool_result.tool_name,
            failure_category=failure_category or str(tool_result.status or "").strip().lower(),
            request=request,
        )
        if failure_category in {"approval_required", "permission_denied", "timeout", "dependency_unavailable", "invalid_params", "service_unavailable"}:
            if degrade_message:
                return degrade_message
        rag_pack = getattr(request.rag_result, "evidence_pack", None) if request.rag_result is not None else None
        rag_items = list(getattr(rag_pack, "items", []) or [])
        if failure_category == "no_tool_mapping":
            return (
                "这次我没能把这类本地生活请求稳定映射到具体工具，所以先不继续执行，避免误路由。"
                "你可以补充店名、城市、距离或想比较的对象，我再重新走一次工具链。"
            )
        if failure_category == "approval_required" or tool_result.status == ToolExecutionStatus.PENDING_APPROVAL:
            return (
                "这个操作还处于待确认状态。当前 P0 版本对下单、订座、取消、退款这类写操作只保留能力预留，"
                "暂时不直接代你执行。你可以先告诉我想确认的店铺或订单信息，我先帮你把可查的信息整理清楚。"
            )
        if failure_category == "permission_denied" or tool_result.status == ToolExecutionStatus.REJECTED:
            return "当前无权查看或执行这项操作。你可以先登录、补充校验信息，或确认当前账号是否有对应权限。"
        if failure_category == "timeout":
            return "刚才查询超时了。你可以稍后重试，我也可以先帮你缩小范围再查。"
        if failure_category == "dependency_unavailable":
            return "相关服务暂时不可用，这次还查不到结果。你可以稍后再试。"
        if failure_category == "no_result" and rag_items:
            return None
        if failure_category == "no_result":
            rag_pack = getattr(request.rag_result, "evidence_pack", None) if request.rag_result is not None else None
            rag_items = list(getattr(rag_pack, "items", []) or [])
            if rag_items:
                return None
            return self._compose_no_result_answer(tool_result.tool_name, tool_result.normalized_output, request)
        if failure_category == "no_result" and rag_items:
            return None
        if tool_result.status == ToolExecutionStatus.SUCCESS and tool_result.extra.get("grounding_source") in ("business_evidence", "mixed_evidence"):
            # 添加 claim 校验：实时事实只接受 Tool 来源
            answer = self._compose_tool_success_answer(tool_result.tool_name, tool_result.normalized_output, request)
            if answer:
                # 校验 claim 类型与来源匹配
                validator = ClaimValidator()
                claims = self._extract_claims_from_tool_result(tool_result)
                shop_id = self._extract_shop_id_from_tool_result(tool_result)
                validation_result = validator.validate(claims, shop_id=shop_id)
                if validation_result.rejected_claims:
                    import logging
                    logging.getLogger(__name__).warning(
                        f"Claim validation rejected {len(validation_result.rejected_claims)} claims: "
                        f"{validation_result.reasons}"
                    )
                    # rejected claims 不能进入 LLM answerer 输入，返回错误信息
                    return "查询结果中包含无法验证的实时信息，暂时无法给出可靠答案。请稍后重试或补充更多信息。"
            return answer
        return None

    def _extract_claims_from_tool_result(self, tool_result: Any) -> list[Claim]:
        """从 tool_result 提取 claims"""
        claims: list[Claim] = []
        tool_name = tool_result.tool_name
        data = tool_result.normalized_output.get("data", {}) if hasattr(tool_result, "normalized_output") else {}
        
        if tool_name == "get_coupon_list":
            coupons = data.get("coupons", [])
            for coupon in coupons[:3]:  # 只取前3个
                claims.append(Claim(
                    type=ClaimType.COUPON,
                    content=coupon.get("title", ""),
                    shop_id=data.get("shop_id"),
                    source=DataSource.TOOL,
                ))
        elif tool_name == "check_open_status":
            if data.get("open_status"):
                claims.append(Claim(
                    type=ClaimType.OPEN_STATUS,
                    content=f"营业状态: {data['open_status']}",
                    shop_id=data.get("shop_id"),
                    source=DataSource.TOOL,
                ))
        elif tool_name == "get_distance_eta":
            if data.get("distance_km"):
                claims.append(Claim(
                    type=ClaimType.DISTANCE,
                    content=f"距离: {data['distance_km']}km, 预计{data.get('eta_minutes', '')}分钟",
                    shop_id=data.get("shop_id"),
                    source=DataSource.TOOL,
                ))
        elif tool_name == "booking":
            if data.get("booking_id") or data.get("status"):
                claims.append(Claim(
                    type=ClaimType.BOOKING,
                    content=f"预约状态: {data.get('status', '已确认')}",
                    shop_id=data.get("shop_id"),
                    source=DataSource.TOOL,
                ))
        elif tool_name == "order":
            if data.get("order_id") or data.get("status"):
                claims.append(Claim(
                    type=ClaimType.ORDER,
                    content=f"订单状态: {data.get('status', '已确认')}",
                    shop_id=data.get("shop_id"),
                    source=DataSource.TOOL,
                ))
        elif tool_name == "get_inventory":
            if data.get("inventory_count") is not None:
                claims.append(Claim(
                    type=ClaimType.INVENTORY,
                    content=f"库存: {data.get('inventory_count', 0)}件",
                    shop_id=data.get("shop_id"),
                    source=DataSource.TOOL,
                ))
        
        return claims

    def _extract_shop_id_from_tool_result(self, tool_result: Any) -> int | None:
        """从 tool_result 提取 shop_id"""
        data = tool_result.normalized_output.get("data", {}) if hasattr(tool_result, "normalized_output") else {}
        shop_id = data.get("shop_id") or data.get("shopId")
        return int(shop_id) if shop_id else None

    def _compose_rag_plus_tool_answer(self, request: AnswerComposeRequest) -> str | None:
        routing = request.routing_decision
        action = str(getattr(routing, "required_action", "") or "").strip().lower()
        if action != "rag_plus_tool":
            return None

        sections: list[str] = []
        coupon_answer = self._compose_tool_answer(request)
        if coupon_answer:
            sections.append(f"券信息：{coupon_answer}")

        environment_answer = self._compose_environment_answer(request)
        if environment_answer:
            sections.append(f"环境评价：{environment_answer}")

        if not sections:
            return None
        
        # 添加来源验证：确保同店评价只来自同 shop_id RAG
        tool_result = request.tool_result
        rag_result = request.rag_result
        if tool_result and rag_result:
            shop_id = self._extract_shop_id_from_tool_result(tool_result)
            if shop_id:
                # 校验 RAG evidence 的 shop_id
                evidence_pack = rag_result.evidence_pack
                if evidence_pack:
                    items = list(evidence_pack.items or [])
                    rag_claims: list[Claim] = []
                    for item in items:
                        item_shop_id = getattr(item, "shop_id", None)
                        content = str(getattr(item, "content", "") or "").strip()
                        if content and item_shop_id:
                            # 创建 RAG claim 进行验证
                            rag_claims.append(Claim(
                                type=ClaimType.REVIEW,
                                content=content[:100],
                                shop_id=int(item_shop_id) if item_shop_id else None,
                                source=DataSource.RAG,
                            ))
                    
                    # 使用 ClaimValidator 验证 RAG claims
                    if rag_claims:
                        validator = ClaimValidator()
                        validation_result = validator.validate(rag_claims, shop_id=shop_id)
                        if validation_result.rejected_claims:
                            import logging
                            logging.getLogger(__name__).warning(
                                f"RAG claim validation rejected {len(validation_result.rejected_claims)} claims: "
                                f"{validation_result.reasons}"
                            )
                            # 返回错误信息，不进入 LLM answerer 输入
                            return "查询结果中包含无法验证的评价信息，暂时无法给出可靠答案。请稍后重试或补充更多信息。"
        
        return "\n".join(sections)

    def _compose_environment_answer(self, request: AnswerComposeRequest) -> str | None:
        rag_result = request.rag_result
        if rag_result is None:
            return None

        evidence_pack = rag_result.evidence_pack
        items = list(evidence_pack.items if evidence_pack else [])
        evidence_status = self._evidence_status(rag_result)
        if not items:
            if evidence_status == "OK":
                return "评价证据有限，暂时没有足够信息判断环境。"
            return "评价证据有限，暂时不敢硬说环境好坏。"

        joined_text = " ".join(str(item.content or "") for item in items[:4]).strip()
        signals: list[str] = []
        if any(token in joined_text for token in ("安静", "不吵", "静")):
            signals.append("环境偏安静")
        if any(token in joined_text for token in ("包间", "私密", "隔音")):
            signals.append("私密性还可以")
        if any(token in joined_text for token in ("家庭聚餐", "聚餐", "带父母", "带长辈", "约会")):
            signals.append("比较适合家庭聚餐或约会")
        if any(token in joined_text for token in ("口碑", "评价不错", "氛围", "体验不错", "服务不错")):
            signals.append("整体口碑还不错")
        if any(token in joined_text for token in ("吵", "排队", "拥挤")):
            signals.append("高峰期可能会偏吵或偏挤")

        if signals:
            return "从评价看，" + "；".join(signals) + "。"

        snippets: list[str] = []
        for item in items[:2]:
            content = str(item.content or "").strip().replace("\n", " ")
            if not content:
                continue
            if len(content) > 96:
                content = content[:93].rstrip() + "..."
            snippets.append(content)
        if not snippets:
            return "评价证据有限，暂时没有足够信息判断环境。"
        if len(snippets) == 1:
            return f"评价里能看到：{snippets[0]}。"
        return f"评价里能看到：{snippets[0]}；{snippets[1]}。"

    def _compose_clarify_response(self, request: AnswerComposeRequest, routing: Any) -> str:
        question = str(getattr(routing, "clarification_question", "") or "").strip()
        if question:
            return question
        clarification_slot = str(getattr(routing, "clarification_slot", "") or getattr(request.evidence_quality, "clarification_slot", "") or request.clarification_slot or "").strip()
        missing_slots = list(getattr(routing, "missing_slots", None) or request.missing_slots or getattr(request.evidence_quality, "missing_slots", None) or [])
        slot_question = build_clarification_question(
            missing_slots,
            clarification_slot=clarification_slot or None,
            query_text=request.raw_query,
        )
        if slot_question:
            return slot_question
        kind = str(request.direct_response_kind or "").strip().lower()
        if kind:
            return compose_direct_response_text(request.raw_query, kind)
        return compose_direct_response_text(request.raw_query, "low_info")

    def _compose_conversation_recap_response(self, request: AnswerComposeRequest) -> str:
        summary = str(request.history_summary or "").strip()
        meta = dict(request.stream_event_meta or {})
        current_shop = str(meta.get("current_shop") or "").strip()
        if not current_shop and request.answer_contract is not None:
            current_shop = str(request.answer_contract.selected_entity or "").strip()
        if not current_shop and request.entity_join_result is not None:
            current_shop = str(request.entity_join_result.selected_entity or "").strip()
        if current_shop and summary:
            return f"我们刚才主要在聊{current_shop}：{summary}。如果你愿意，我可以继续接着这个话题说。"
        if current_shop:
            return f"我们刚才主要在聊{current_shop}。如果你愿意，我可以继续接着这个话题说。"
        if summary:
            return f"我们刚才主要在聊：{summary}。如果你愿意，我可以继续接着这个话题说。"
        return "我能记住我们刚才的上下文，但这一轮还没沉淀出可回顾的摘要。你可以再问我刚才那家店、刚才的券，或者让我继续接着说。"

    def _compose_partial_grounded_answer(self, request: AnswerComposeRequest) -> str:
        evidence_quality = request.evidence_quality
        covered_facets = list(getattr(evidence_quality, "covered_facets", None) or [])
        missing_facets = list(getattr(evidence_quality, "missing_facets", None) or [])
        slot_notes: list[str] = []
        if covered_facets:
            slot_notes.append(f"已确认：{'、'.join(self._facet_labels(covered_facets[:3]))}")
        if missing_facets:
            slot_notes.append(f"暂未确认：{'、'.join(self._facet_labels(missing_facets[:3]))}")
        intro = "目前只能先给你一个部分判断。"
        if slot_notes:
            intro = f"{intro} {'；'.join(slot_notes)}。"
        body = self._grounded_fallback(request)
        if body.startswith("噢，系统服务出现了一点小状况呢") or "RAG_NO_ANSWER" in body:
            return body
        return self._append_auxiliary_sections(request, f"{intro}\n{body}", include_auxiliary=True)

    def _compose_no_result_answer(self, tool_name: str, payload: Mapping[str, Any], request: AnswerComposeRequest | None = None) -> str:
        data = _tool_data(payload)
        shop_name = str(data.get("shop_name") or "这家店").strip() or "这家店"
        concrete_shop_name = ""
        has_static_vouchers = False
        static_info = ""
        
        if request is not None:
            if request.answer_contract:
                contract_extra = _slot_mapping(getattr(request.answer_contract, "extra", {}))
                candidate_shop_name = _optional_str(contract_extra.get("selected_shop_name") or contract_extra.get("current_shop"))
                if candidate_shop_name:
                    concrete_shop_name = candidate_shop_name
            if not concrete_shop_name and request.entity_join_result:
                extra_data = _slot_mapping(getattr(request.entity_join_result, "extra", {}))
                candidate_shop_name = _optional_str(extra_data.get("selected_shop_name") or extra_data.get("current_shop"))
                if candidate_shop_name:
                    concrete_shop_name = candidate_shop_name
            if not concrete_shop_name and request.stream_event_meta:
                meta = _slot_mapping(request.stream_event_meta)
                candidate_shop_name = _optional_str(meta.get("current_shop") or meta.get("selected_shop_name"))
                if candidate_shop_name:
                    concrete_shop_name = candidate_shop_name
            if not concrete_shop_name and request.rag_result and request.rag_result.evidence_pack:
                for ev_item in request.rag_result.evidence_pack.items:
                    meta = _slot_mapping(getattr(ev_item, "metadata", {}))
                    candidate_shop_name = _optional_str(meta.get("shop_name") or meta.get("shopName"))
                    if candidate_shop_name:
                        concrete_shop_name = candidate_shop_name
                        break

            if request.rag_result and request.rag_result.evidence_pack:
                for item in request.rag_result.evidence_pack.items:
                    content = str(item.content or "").strip()
                    meta = getattr(item, "metadata", {}) or {}
                    v_count = meta.get("voucher_count") if isinstance(meta, dict) else None
                    pkg_desc = meta.get("package_description") if isinstance(meta, dict) else None
                    if v_count or pkg_desc:
                        has_static_vouchers = True
                        if v_count:
                            static_info += f"优惠券数量：{v_count}张 "
                        if pkg_desc:
                            static_info += f"套餐说明：{pkg_desc}"
                        break
                    elif "券" in content or "优惠" in content or "套餐" in content:
                        has_static_vouchers = True
                        static_info = "知识库中包含相关优惠或套餐描述"
                        break

        if concrete_shop_name:
            shop_name = concrete_shop_name

        if tool_name == "get_order_status":
            return "我这边还没查到对应的订单信息。你可以补充订单号，或者确认一下是不是查错了门店和订单。"
        if tool_name == "get_coupon_list":
            if has_static_vouchers:
                return f"{shop_name} 实时未查到可用券，可参考券存在（{static_info}）但需以实时接口为准。"
            return f"我这边还没查到 {shop_name} 可用的券。你可以换一家店，或者告诉我想看的店名和区域。"
        if tool_name == "get_shop_detail":
            return "我这边还没定位到你要看的门店。你可以补充店名、区域，或者直接给我店铺 id。"
        if tool_name == "search_restaurants":
            return "我这边暂时没筛到符合条件的门店。你可以放宽预算、距离或口味条件，我继续帮你找。"
        return "我这边还没查到对应结果。你可以补充更具体的对象、范围或条件，我继续帮你查。"

    def _compose_tool_success_answer(self, tool_name: str, payload: Mapping[str, Any], request: AnswerComposeRequest | None = None) -> str:
        data = _tool_data(payload)
        
        concrete_shop_name = ""
        has_static_vouchers = False
        static_info = ""
        
        if request is not None:
            if request.answer_contract:
                contract_extra = _slot_mapping(getattr(request.answer_contract, "extra", {}))
                candidate_shop_name = _optional_str(contract_extra.get("selected_shop_name") or contract_extra.get("current_shop"))
                if candidate_shop_name:
                    concrete_shop_name = candidate_shop_name
            if not concrete_shop_name and request.entity_join_result:
                extra_data = _slot_mapping(getattr(request.entity_join_result, "extra", {}))
                candidate_shop_name = _optional_str(extra_data.get("selected_shop_name") or extra_data.get("current_shop"))
                if candidate_shop_name:
                    concrete_shop_name = candidate_shop_name
            if not concrete_shop_name and request.stream_event_meta:
                meta = _slot_mapping(request.stream_event_meta)
                candidate_shop_name = _optional_str(meta.get("current_shop") or meta.get("selected_shop_name"))
                if candidate_shop_name:
                    concrete_shop_name = candidate_shop_name
            if not concrete_shop_name and request.rag_result and request.rag_result.evidence_pack:
                for ev_item in request.rag_result.evidence_pack.items:
                    meta = _slot_mapping(getattr(ev_item, "metadata", {}))
                    candidate_shop_name = _optional_str(meta.get("shop_name") or meta.get("shopName"))
                    if candidate_shop_name:
                        concrete_shop_name = candidate_shop_name
                        break

            if request.rag_result and request.rag_result.evidence_pack:
                for item in request.rag_result.evidence_pack.items:
                    content = str(item.content or "").strip()
                    meta = getattr(item, "metadata", {}) or {}
                    v_count = meta.get("voucher_count") if isinstance(meta, dict) else None
                    pkg_desc = meta.get("package_description") if isinstance(meta, dict) else None
                    if v_count or pkg_desc:
                        has_static_vouchers = True
                        if v_count:
                            static_info += f"优惠券数量：{v_count}张 "
                        if pkg_desc:
                            static_info += f"套餐说明：{pkg_desc}"
                        break
                    elif "券" in content or "优惠" in content or "套餐" in content:
                        has_static_vouchers = True
                        static_info = "知识库中包含相关优惠或套餐描述"
                        break

        if tool_name == "search_restaurants":
            candidates = list(data.get("candidates") or [])
            names = [str(item.get("name") or "").strip() for item in candidates[:3] if isinstance(item, Mapping)]
            lead = "我先帮你筛到这些更匹配的门店："
            if names:
                lead = f"{lead}{'、'.join(name for name in names if name)}。"
            count = int(data.get('candidate_count') or len(candidates))
            return f"{lead} 当前一共命中 {count} 家，如果你愿意，我可以继续帮你细化到距离、价格或适合的场景。"
        if tool_name == "get_shop_detail":
            shop = _slot_mapping(data.get("shop"))
            shop_name = str(shop.get("name") or "这家店").strip() or "这家店"
            if concrete_shop_name:
                shop_name = concrete_shop_name
            score = shop.get("score")
            avg_price = shop.get("avgPrice") or shop.get("avg_price")
            parts = [f"{shop_name} 的门店信息我查到了"]
            if score not in (None, ""):
                parts.append(f"评分大约 {score}")
            if avg_price not in (None, ""):
                parts.append(f"人均约 {avg_price} 元")
            open_status = _slot_mapping(data.get("open_status"))
            if str(open_status.get("open_status") or "").strip():
                parts.append(f"当前状态是 {open_status.get('open_status')}")
            return "，".join(parts) + "。"
        if tool_name == "get_coupon_list":
            shop_name = str(data.get("shop_name") or "这家店").strip() or "这家店"
            if concrete_shop_name:
                shop_name = concrete_shop_name
            coupons = list(data.get("coupons") or [])
            count = int(data.get("count") or len(coupons) or 0)
            if count <= 0 or not coupons:
                if has_static_vouchers:
                    return f"{shop_name} 实时未查到可用券，可参考券存在（{static_info}）但需以实时接口为准。"
                return f"{shop_name} 目前还没有可用券。你可以换一家店，或者告诉我想看的店名和区域。"
            summaries: list[str] = []
            for coupon in coupons[:3]:
                if not isinstance(coupon, Mapping):
                    continue
                title = str(coupon.get("title") or "").strip()
                pay_value = coupon.get("payValue")
                actual_value = coupon.get("actualValue")
                if title and pay_value not in (None, "") and actual_value not in (None, ""):
                    summaries.append(f"{title}（{pay_value} 元代 {actual_value} 元）")
                elif title:
                    summaries.append(title)
            body = "、".join(summaries) if summaries else "我已经查到可用券"
            return f"{shop_name} 当前能看到这些券：{body}。"
        if tool_name == "get_order_status":
            order = _slot_mapping(data.get("order"))
            order_id = str(order.get("order_id") or order.get("transaction_id") or "").strip()
            status = str(order.get("status") or data.get("status") or "unknown").strip()
            if order_id:
                return f"我查到订单 {order_id} 当前状态是 {status}。"
            return f"我查到这笔订单当前状态是 {status}。"
        if tool_name == "get_distance_eta":
            distance = data.get("distance_km")
            eta = data.get("eta_minutes")
            mode = str(data.get("mode") or "drive")
            return f"按 {mode} 方式估算，距离大约 {distance} 公里，预计 {eta} 分钟左右到。"
        if tool_name == "check_open_status":
            status = str(data.get("open_status") or "unknown")
            return f"我查到这家店当前状态是 {status}。"
        return "我已经根据业务数据查到结果了，如果你愿意，我可以继续往下帮你细化。"

    def _compose_weak_answer(self, request: AnswerComposeRequest) -> str:
        rag_result = request.rag_result
        evidence_pack = rag_result.evidence_pack if rag_result else None
        items = list(evidence_pack.items if evidence_pack else [])
        snippets = [item.content.strip() for item in items[:2] if item.content.strip()]
        if snippets:
            body = "根据当前知识库里的有限证据，我只能给出谨慎判断：{snippets}。如果你希望我继续，建议补充具体范围、版本或背景。".format(
                snippets="；".join(snippets)
            )
        else:
            body = compose_direct_response_text(request.raw_query, "empty")
        return self._append_auxiliary_sections(request, body, include_auxiliary=False)

    def _compose_empty_evidence_style_answer(self, request: AnswerComposeRequest) -> str:
        ranked_candidates = _build_ranked_candidates(request.ranked_candidates)
        facet_bundle = _build_facet_result_bundle(request)
        local_contract = request.answer_contract
        if local_contract is None:
            return self._compose_weak_answer(request)

        topic_name = _resolved_strict_topic_name(request, ranked_candidates)
        evidence_claims = _build_evidence_claims(request)
        user_need = _build_user_need_proxy(request, ranked_candidates)
        answer_text = self._build_strict_template_answer(
            local_contract=local_contract,
            topic_name=topic_name,
            ranked_candidates=ranked_candidates,
            evidence_claims=evidence_claims,
            facet_bundle=facet_bundle,
            user_need=user_need,
        )
        return answer_text or self._compose_weak_answer(request)

    def _compose_no_answer(self, request: AnswerComposeRequest, evidence_quality: EvidenceQualityDecision | None) -> str:
        reason = str(getattr(evidence_quality, "reason", "") or "").strip()
        fallback_reason = str(getattr(evidence_quality, "fallback_reason", "") or "").strip()
        if reason in {"shop_mismatch", "geo_mismatch"}:
            body = "我暂时没有找到足够匹配的依据，没法可靠地直接下结论。你可以补充更具体的店名、区域或目标，我再继续帮你查。 [Code: RAG_NO_ANSWER]"
        elif reason == "required_role_missing":
            body = "目前缺少足够关键的证据类型，不能给出可信结论。你可以补充更具体的问题、店名、套餐或评价维度，我再继续帮你查。 [Code: RAG_NO_ANSWER]"
        elif fallback_reason:
            body = f"我暂时没有找到足够可靠的依据来回答这个问题。你可以补充更多上下文，我再继续帮你查。 [Code: RAG_NO_ANSWER:{fallback_reason}]"
        else:
            body = "我暂时没有找到足够可靠的依据来回答这个问题。你可以补充更多上下文，我再继续帮你查。 [Code: RAG_NO_ANSWER]"
        return self._append_auxiliary_sections(request, body, include_auxiliary=False)

    def _grounded_fallback(self, request: AnswerComposeRequest) -> str:
        rag_result = request.rag_result
        evidence_pack = rag_result.evidence_pack if rag_result else None
        items = list(evidence_pack.items if evidence_pack else [])
        citations = self._collect_citations(request)
        if not items:
            return self._compose_no_answer(request, request.evidence_quality)
        lead = "根据知识库中的证据，可以得到以下结论："
        bullets: list[str] = []
        for item, _citation in zip(items[: self.max_citations], citations or items, strict=False):
            snippet = item.content.strip().replace("\n", " ")
            if len(snippet) > 140:
                snippet = snippet[:137].rstrip() + "..."
            bullets.append(f"- {snippet}")
        return "\n".join([lead, *bullets])

    def _append_auxiliary_sections(self, request: AnswerComposeRequest, answer: str, *, include_auxiliary: bool) -> str:
        return answer

    @staticmethod
    def _append_plan_summary(request: AnswerComposeRequest, answer: str) -> str:
        plan_summary = request.plan_summary
        if plan_summary is None:
            return answer

        answer_text = str(answer or "").strip()
        if "Plan execution" in answer_text:
            return answer_text

        status = str(getattr(plan_summary, "status", "") or "").strip() or "unknown"
        completed_steps = getattr(plan_summary, "completed_steps", None)
        total_steps = getattr(plan_summary, "total_steps", None)
        final_decision = str(getattr(plan_summary, "final_decision", "") or "").strip()
        key_findings = [str(item).strip() for item in getattr(plan_summary, "key_findings", []) or [] if str(item).strip()]

        summary_lines = [f"Plan execution summary: {status}"]
        if completed_steps is not None and total_steps is not None:
            summary_lines[0] = f"{summary_lines[0]} ({completed_steps}/{total_steps})"
        if final_decision:
            summary_lines.append(final_decision)
        if key_findings:
            summary_lines.append("Key findings: " + "；".join(key_findings[:3]))

        summary_text = "\n".join(summary_lines)
        if not answer_text:
            return summary_text
        return f"{answer_text}\n\n{summary_text}"

    @staticmethod
    def _facet_labels(facets: Sequence[str]) -> list[str]:
        labels = {
            "shop_detail": "门店详情",
            "recommendation_reason": "推荐理由",
            "environment": "环境",
            "taste": "口味",
            "service": "服务",
            "scene_fit": "适合场景",
            "coupon": "券",
            "open_status": "营业状态",
            "distance_eta": "距离与时间",
            "price": "价格",
        }
        result: list[str] = []
        for facet in facets:
            key = str(facet or "").strip()
            if not key:
                continue
            result.append(labels.get(key, key))
        return result

    @staticmethod
    def _format_memory_section(title: str, memories: Sequence[Any], *, limit: int) -> str:
        summaries: list[str] = []
        for memory in memories[:limit]:
            summary = getattr(memory, "summary", None) or str(getattr(memory, "content", ""))
            summary = str(summary).strip()
            if summary:
                summaries.append(summary)
        if not summaries:
            return ""
        return f"{title}: {' | '.join(summaries)}"

    def _evidence_status(self, rag_result) -> str:
        if rag_result is None:
            return "EMPTY"
        pack = getattr(rag_result, "evidence_pack", None)
        if pack is None:
            return str(getattr(rag_result, "evidence_status", "EMPTY") or "EMPTY").upper()
        return str(getattr(pack, "evidence_status", getattr(rag_result, "evidence_status", "EMPTY")) or "EMPTY").upper()

    def _collect_citations(self, request: AnswerComposeRequest) -> list[Any]:
        rag_result = request.rag_result
        citations = list(rag_result.citations if rag_result else [])
        if citations:
            return citations[: self.max_citations]
        evidence_pack = rag_result.evidence_pack if rag_result else None
        if evidence_pack is None:
            return []
        collected = []
        for item in evidence_pack.items[: self.max_citations]:
            collected.append(
                {
                    "chunk_id": getattr(item, "citation_chunk_id", None) or item.chunk_id,
                    "document_id": item.document_id,
                    "title": item.metadata.get("title") if isinstance(item.metadata, Mapping) else None,
                }
            )
        return collected

    def _ensure_citations(self, answer_text: str, citations: Sequence[Any]) -> str:
        if any(token in answer_text for token in ("[", "(", "【")):
            return answer_text
        marker_text = " ".join(self._citation_marker(citation) for citation in citations[: self.max_citations])
        if not marker_text:
            return answer_text
        return f"{answer_text}\n\n证据引用：{marker_text}"

    @staticmethod
    def _extract_answer_text(payload: Any) -> str:
        if payload is None:
            return ""
        if isinstance(payload, str):
            return payload.strip()
        if isinstance(payload, Mapping):
            for key in ("answer_text", "answer", "text", "output", "content"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return ""

    @staticmethod
    def _citation_marker(citation: Any) -> str:
        if isinstance(citation, Mapping):
            chunk_id = str(citation.get("chunk_id") or citation.get("citation_chunk_id") or "").strip()
            title = str(citation.get("title") or "").strip()
        else:
            chunk_id = str(getattr(citation, "chunk_id", "") or getattr(citation, "citation_chunk_id", "") or "").strip()
            title = str(getattr(citation, "title", "") or "").strip()
        if title:
            return f"[{chunk_id}:{title}]" if chunk_id else f"[{title}]"
        return f"[{chunk_id}]" if chunk_id else ""


@dataclass
class Finalizer:
    settings: Settings

    def finalize(self, *args, **kwargs) -> SseEnvelope | None:
        return None


def _clean_partial_grounded_answer(self: AnswerComposer, request: AnswerComposeRequest) -> str:
    evidence_quality = request.evidence_quality
    covered_facets = list(getattr(evidence_quality, "covered_facets", None) or [])
    missing_facets = list(getattr(evidence_quality, "missing_facets", None) or [])
    slot_notes: list[str] = []
    if covered_facets:
        slot_notes.append("\u5df2\u786e\u8ba4\uff1a" + "、".join(self._facet_labels(covered_facets[:3])))
    if missing_facets:
        slot_notes.append("\u6682\u672a\u786e\u8ba4\uff1a" + "、".join(self._facet_labels(missing_facets[:3])))

    try:
        from learning_agent_service.local_life.entity_resolver import _explicit_entity_from_query
    except Exception:  # pragma: no cover - defensive fallback
        _explicit_entity_from_query = None  # type: ignore[assignment]

    raw_query = str(request.raw_query or "").strip()
    explicit_topic = _explicit_entity_from_query(raw_query) if _explicit_entity_from_query is not None else None
    meta = dict(request.stream_event_meta or {})
    current_topic = (
        explicit_topic
        or str(meta.get("current_shop") or "").strip()
        or str(getattr(request.answer_contract, "selected_entity", "") or "").strip()
        or str(getattr(request.entity_join_result, "selected_entity", "") or "").strip()
        or "\u8fd9\u5bb6\u5e97"
    )

    intro = "\u76ee\u524d\u53ea\u80fd\u5148\u7ed9\u4f60\u4e00\u4e2a\u90e8\u5206\u5224\u65ad\u3002"
    if current_topic:
        intro = f"{current_topic}\uff1a{intro}"
    if slot_notes:
        intro = intro + " " + "\uff1b".join(slot_notes) + "\u3002"
    body = self._grounded_fallback(request)
    if body.startswith("\u54e6\uff0c\u7cfb\u7edf\u670d\u52a1\u51fa\u73b0\u4e86\u4e00\u70b9\u5c0f\u72b6\u51b5") or "RAG_NO_ANSWER" in body:
        return body
    return self._append_auxiliary_sections(request, f"{intro}\n{body}", include_auxiliary=True)


def _clean_compose_no_result_answer(
    self: AnswerComposer,
    tool_name: str,
    payload: Mapping[str, Any],
    request: AnswerComposeRequest | None = None,
) -> str:
    data = _tool_data(payload)
    shop_name = str(data.get("shop_name") or "\u8fd9\u5bb6\u5e97").strip() or "\u8fd9\u5bb6\u5e97"
    concrete_shop_name = ""
    has_static_vouchers = False
    static_info = ""

    if request is not None:
        if request.answer_contract:
            contract_extra = _slot_mapping(getattr(request.answer_contract, "extra", {}))
            candidate_shop_name = _optional_str(contract_extra.get("selected_shop_name") or contract_extra.get("current_shop"))
            if candidate_shop_name:
                concrete_shop_name = candidate_shop_name
        if not concrete_shop_name and request.entity_join_result:
            extra_data = _slot_mapping(getattr(request.entity_join_result, "extra", {}))
            candidate_shop_name = _optional_str(extra_data.get("selected_shop_name") or extra_data.get("current_shop"))
            if candidate_shop_name:
                concrete_shop_name = candidate_shop_name
        if not concrete_shop_name and request.stream_event_meta:
            meta = _slot_mapping(request.stream_event_meta)
            candidate_shop_name = _optional_str(meta.get("current_shop") or meta.get("selected_shop_name"))
            if candidate_shop_name:
                concrete_shop_name = candidate_shop_name
        if not concrete_shop_name and request.rag_result and request.rag_result.evidence_pack:
            for ev_item in request.rag_result.evidence_pack.items:
                meta = _slot_mapping(getattr(ev_item, "metadata", {}))
                candidate_shop_name = _optional_str(meta.get("shop_name") or meta.get("shopName"))
                if candidate_shop_name:
                    concrete_shop_name = candidate_shop_name
                    break

        if request.rag_result and request.rag_result.evidence_pack:
            for item in request.rag_result.evidence_pack.items:
                content = str(item.content or "").strip()
                meta = getattr(item, "metadata", {}) or {}
                v_count = meta.get("voucher_count") if isinstance(meta, dict) else None
                pkg_desc = meta.get("package_description") if isinstance(meta, dict) else None
                if v_count or pkg_desc:
                    has_static_vouchers = True
                    if v_count:
                        static_info += f"\u4f18\u60e0\u5238\u6570\u91cf\uff1a{v_count}\u5f20\u3002"
                    if pkg_desc:
                        static_info += f"\u5957\u9910\u8bf4\u660e\uff1a{pkg_desc}"
                    break
                elif "\u5238" in content or "\u4f18\u60e0" in content or "\u5957\u9910" in content:
                    has_static_vouchers = True
                    static_info = "\u77e5\u8bc6\u5e93\u4e2d\u5305\u542b\u76f8\u5173\u4f18\u60e0\u6216\u5957\u9910\u63cf\u8ff0\u3002"
                    break

    if concrete_shop_name:
        shop_name = concrete_shop_name

    if tool_name == "get_order_status":
        return "\u6211\u8fd9\u8fb9\u8fd8\u6ca1\u67e5\u5230\u5bf9\u5e94\u7684\u8ba2\u5355\u4fe1\u606f\u3002\u4f60\u53ef\u4ee5\u8865\u5145\u8ba2\u5355\u53f7\uff0c\u6216\u8005\u786e\u8ba4\u4e00\u4e0b\u662f\u4e0d\u662f\u67e5\u9519\u4e86\u95e8\u5e97\u548c\u8ba2\u5355\u3002"
    if tool_name == "get_coupon_list":
        if has_static_vouchers:
            return f"{shop_name}\u5b9e\u65f6\u672a\u67e5\u5230\u53ef\u7528\u5238\uff0c\u4f46\u53ef\u53c2\u8003\u77e5\u8bc6\u5e93\u4e2d\u7684\u4f18\u60e0\u4fe1\u606f\uff1a{static_info}\u3002"
        return f"\u6211\u8fd9\u8fb9\u8fd8\u6ca1\u67e5\u5230 {shop_name} \u53ef\u7528\u7684\u5238\u3002\u4f60\u53ef\u4ee5\u6362\u4e00\u5bb6\u5e97\uff0c\u6216\u8005\u544a\u8bc9\u6211\u60f3\u770b\u7684\u5e97\u540d\u548c\u533a\u57df\u3002"
    if tool_name == "get_shop_detail":
        return "\u6211\u8fd9\u8fb9\u8fd8\u6ca1\u5b9a\u4f4d\u5230\u4f60\u8981\u770b\u7684\u95e8\u5e97\u3002\u4f60\u53ef\u4ee5\u8865\u5145\u5e97\u540d\u3001\u533a\u57df\uff0c\u6216\u8005\u76f4\u63a5\u7ed9\u6211\u5e97\u94fa ID\u3002"
    if tool_name == "search_restaurants":
        return "\u6211\u8fd9\u8fb9\u6682\u65f6\u6ca1\u7b5b\u5230\u7b26\u5408\u6761\u4ef6\u7684\u95e8\u5e97\u3002\u4f60\u53ef\u4ee5\u653e\u5bbd\u9884\u7b97\u3001\u8ddd\u79bb\u6216\u53e3\u5473\u6761\u4ef6\uff0c\u6211\u7ee7\u7eed\u5e2e\u4f60\u627e\u3002"
    return "\u6211\u8fd9\u8fb9\u8fd8\u6ca1\u67e5\u5230\u5bf9\u5e94\u7ed3\u679c\u3002\u4f60\u53ef\u4ee5\u8865\u5145\u66f4\u5177\u4f53\u7684\u5bf9\u8c61\u3001\u8303\u56f4\u6216\u6761\u4ef6\uff0c\u6211\u7ee7\u7eed\u5e2e\u4f60\u67e5\u3002"


AnswerComposer._compose_partial_grounded_answer = _clean_partial_grounded_answer
AnswerComposer._compose_no_result_answer = _clean_compose_no_result_answer
