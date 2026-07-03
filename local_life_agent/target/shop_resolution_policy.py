"""Scoring and decision policy for canonical shop entity resolution."""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

from .shop_alias import build_generated_aliases
from .shop_name_normalizer import normalize_shop_record, normalize_shop_name_text
from ..domain.shop_entity import ShopCandidate, ShopResolutionResult, ShopResolutionSource, ShopResolutionStatus


_EXACT_ALIAS_SOURCES = {
    ShopResolutionSource.exact_name,
    ShopResolutionSource.normalized_exact,
    ShopResolutionSource.manual_alias,
    ShopResolutionSource.generated_alias,
}


def _compact(value: Any) -> str:
    return "".join(str(value or "").split()).strip().lower()


def _shop_name_key(shop: dict[str, Any]) -> str:
    normalized = normalize_shop_record(shop)
    return _compact(normalized.get("normalized_text"))


def _branch_anchor_key(shop: dict[str, Any]) -> str:
    components = (normalize_shop_record(shop).get("components") or {})
    return _compact(components.get("branch_anchor"))


def _brand_key(shop: dict[str, Any]) -> str:
    components = (normalize_shop_record(shop).get("components") or {})
    return _compact(components.get("brand"))


def _city_key(shop: dict[str, Any]) -> str:
    components = (normalize_shop_record(shop).get("components") or {})
    return _compact(components.get("city"))


def _location_hint(location: dict[str, Any] | None) -> bool:
    if not isinstance(location, dict):
        return False
    return location.get("lat") is not None and location.get("lng") is not None


def _alias_list(shop: dict[str, Any]) -> list[str]:
    aliases = []
    alias = shop.get("alias")
    if isinstance(alias, str) and alias.strip():
        aliases.append(alias)
    for item in shop.get("aliases", []) or []:
        text = str(item or "").strip()
        if text:
            aliases.append(text)
    return aliases


def _is_high_confidence_alias(source: ShopResolutionSource, score: float) -> bool:
    return source in _EXACT_ALIAS_SOURCES and score >= 0.88


def _score_item(
    query: str,
    shop: dict[str, Any],
    *,
    source: ShopResolutionSource,
    fuzzy_allowed: bool,
    session_shop_ids: set[str],
    unique_candidate: bool,
    user_location: dict[str, Any] | None = None,
) -> tuple[ShopCandidate, dict[str, Any]]:
    normalized = normalize_shop_record(shop)
    components = normalized.get("components") or {}
    shop_id = str(shop.get("shop_id", "") or "").strip()
    name = str(shop.get("shop_name", "") or "").strip()
    brand = _compact(components.get("brand"))
    city = _compact(components.get("city"))
    branch_anchor = _compact(components.get("branch_anchor"))
    mall_short_name = _compact(components.get("mall_short_name"))
    category = _compact(components.get("category"))
    geo_match = bool(_location_hint(user_location) and (shop.get("lat") is not None) and (shop.get("lng") is not None))
    query_norm = _compact(query)
    aliases = { _compact(alias) for alias in _alias_list(shop) if _compact(alias) }
    generated_aliases = {_compact(alias) for alias in build_generated_aliases(shop) if _compact(alias)}
    canonical_name = _compact(normalized.get("normalized_text"))
    name_key = _shop_name_key(shop)
    exact_name = bool(query_norm and query_norm == name_key)
    normalized_exact = bool(query_norm and query_norm == canonical_name)
    manual_alias = bool(query_norm and query_norm in aliases)
    generated_alias = bool(query_norm and query_norm in generated_aliases)
    branch_mention = bool(branch_anchor and branch_anchor in query_norm)
    brand_exact = bool(brand and brand in query_norm)
    mall_anchor = bool(mall_short_name and mall_short_name in query_norm)
    city_match = bool(city and city in query_norm)
    session_context_match = bool(shop_id and shop_id in session_shop_ids)
    exact_alias_match = exact_name or normalized_exact or manual_alias
    high_confidence_alias = manual_alias or generated_alias or exact_name or normalized_exact
    exact_match = exact_name or normalized_exact
    typo_score = 0.0
    if fuzzy_allowed:
        typo_score = SequenceMatcher(None, query_norm, name_key or canonical_name).ratio() if (name_key or canonical_name) else 0.0

    score = 0.02
    if exact_name:
        score += 0.72
    if normalized_exact:
        score += 0.68
    if manual_alias:
        score += 0.58
    if generated_alias:
        score += 0.52
    if branch_mention:
        score += 0.16
    if brand_exact:
        score += 0.14
    if mall_anchor:
        score += 0.11
    if city_match:
        score += 0.07
    if session_context_match:
        score += 0.16
    if geo_match:
        score += 0.05
    if exact_alias_match:
        score += 0.08
    if fuzzy_allowed:
        if typo_score >= 0.95:
            score += 0.18
        elif typo_score >= 0.88:
            score += 0.12
        elif typo_score >= 0.8:
            score += 0.06
        elif typo_score >= 0.7:
            score += 0.02

    if unique_candidate and (exact_alias_match or session_context_match):
        score += 0.04
    if len(session_shop_ids) > 1 and not session_context_match:
        score -= 0.03

    score = max(0.0, min(1.0, score))
    source_reason = []
    if exact_name:
        source_reason.append("exact_name")
    if normalized_exact:
        source_reason.append("normalized_exact")
    if manual_alias:
        source_reason.append("manual_alias")
    if generated_alias:
        source_reason.append("generated_alias")
    if branch_mention:
        source_reason.append("branch_anchor")
    if brand_exact:
        source_reason.append("brand_anchor")
    if city_match:
        source_reason.append("city_match")
    if session_context_match:
        source_reason.append("session_context")
    if geo_match:
        source_reason.append("geo_match")
    if fuzzy_allowed and typo_score:
        source_reason.append(f"typo_score={typo_score:.3f}")
    if unique_candidate:
        source_reason.append("unique_candidate")

    if exact_name:
        candidate_source = ShopResolutionSource.exact_name
    elif normalized_exact:
        candidate_source = ShopResolutionSource.normalized_exact
    elif manual_alias:
        candidate_source = ShopResolutionSource.manual_alias
    elif generated_alias:
        candidate_source = ShopResolutionSource.generated_alias
    elif branch_mention:
        candidate_source = ShopResolutionSource.branch_mention
    elif brand_exact:
        candidate_source = ShopResolutionSource.brand_anchor
    elif mall_anchor:
        candidate_source = ShopResolutionSource.branch_mention
    elif fuzzy_allowed and typo_score:
        candidate_source = ShopResolutionSource.restricted_fuzzy
    else:
        candidate_source = source

    candidate = ShopCandidate(
        shop_id=shop_id,
        shop_name=name,
        canonical_name=str(normalized.get("normalized_text", "") or name),
        branch_name=str(components.get("branch_anchor", "") or ""),
        alias=sorted({*aliases, *generated_aliases}),
        score=score,
        source=candidate_source,
        match_reason=";".join(source_reason) or "reference",
        raw=dict(shop),
    )
    details = {
        "brand_exact": brand_exact,
        "branch_anchor_match": branch_mention,
        "mall_anchor_match": mall_anchor,
        "city_match": city_match,
        "session_context_match": session_context_match,
        "geo_match": geo_match,
        "alias_type": "manual" if manual_alias else "generated" if generated_alias else "exact" if exact_match else "branch" if branch_mention else "brand" if brand_exact else "fuzzy" if typo_score else "",
        "exact_match": exact_match,
        "typo_score": typo_score,
        "source": candidate_source.value if hasattr(candidate_source, "value") else str(candidate_source),
        "score": score,
    }
    return candidate, details


def decide_shop_resolution(
    *,
    mention: str,
    shops: list[dict[str, Any]],
    task_type: str = "",
    session_shop_ids: list[str] | None = None,
    current_shop: dict[str, Any] | None = None,
    active_shop: dict[str, Any] | None = None,
    user_location: dict[str, Any] | None = None,
    allow_no_mention: bool = True,
    fuzzy_allowed: bool = False,
    trace: list[dict[str, Any]] | None = None,
) -> ShopResolutionResult:
    session_shop_id_set = {str(item).strip() for item in (session_shop_ids or []) if str(item).strip()}
    trace = list(trace or [])
    query = str(mention or "").strip()
    query_norm = _compact(query)

    if not query_norm and not current_shop and not active_shop:
        status = ShopResolutionStatus.no_mention if allow_no_mention else ShopResolutionStatus.not_found
        return ShopResolutionResult(
            status=status,
            mention=query,
            needs_clarification=False if status == ShopResolutionStatus.no_mention else True,
            resolution_reason="no_mention" if status == ShopResolutionStatus.no_mention else "missing_mention",
            candidate_count=0,
            trace=trace,
        )

    scored: list[tuple[ShopCandidate, dict[str, Any]]] = []
    unique_candidate = len(shops) == 1
    for shop in shops:
        candidate, details = _score_item(
            query_norm or query,
            shop,
            source=ShopResolutionSource.candidate_resolver,
            fuzzy_allowed=fuzzy_allowed,
            session_shop_ids=session_shop_id_set,
            unique_candidate=unique_candidate,
            user_location=user_location,
        )
        if candidate.shop_id:
            scored.append((candidate, details))

    scored.sort(key=lambda item: (item[0].score, item[0].shop_id), reverse=True)
    candidates = [item[0] for item in scored]
    top1 = candidates[0] if candidates else None
    top2 = candidates[1] if len(candidates) > 1 else None
    top1_score = float(top1.score if top1 else 0.0)
    top2_score = float(top2.score if top2 else 0.0)
    margin = top1_score - top2_score if top2 else top1_score
    best_trace = scored[0][1] if scored else {}
    brand_exact = bool(best_trace.get("brand_exact"))
    branch_anchor_match = bool(best_trace.get("branch_anchor_match"))
    exact_alias_match = bool(best_trace.get("exact_match"))
    high_confidence_alias = bool(best_trace.get("alias_type") in {"manual", "generated", "exact"})
    session_context_match = bool(best_trace.get("session_context_match"))
    geo_match = bool(best_trace.get("geo_match"))
    unique_exact = unique_candidate and exact_alias_match
    ambiguous_penalty = 0.06 if len(candidates) > 1 else 0.0
    top1_score = max(0.0, min(1.0, top1_score - ambiguous_penalty))

    if not candidates:
        return ShopResolutionResult(
            status=ShopResolutionStatus.low_confidence if query_norm else ShopResolutionStatus.no_mention,
            mention=query,
            needs_clarification=bool(query_norm),
            resolution_reason="no_candidate_match" if query_norm else "no_mention",
            candidate_count=0,
            trace=trace + [{"mention": query, "result": "no_candidates"}],
        )

    if top1 and unique_exact and high_confidence_alias:
        return ShopResolutionResult(
            status=ShopResolutionStatus.resolved,
            mention=query,
            shop_id=top1.shop_id,
            shop_name=top1.shop_name,
            canonical_name=top1.canonical_name,
            branch_name=top1.branch_name,
            alias=list(top1.alias or []),
            confidence=top1_score,
            source=top1.source,
            resolution_reason="unique_exact_alias",
            needs_clarification=False,
            clarification_question="",
            candidates=candidates[:5],
            selected_candidate=top1,
            candidate_count=len(candidates),
            trace=trace + [{"mention": query, "result": "resolved_unique_exact", "details": best_trace}],
        )

    if top1_score >= 0.88 and (margin >= 0.12 or unique_candidate) and (brand_exact or high_confidence_alias) and (branch_anchor_match or exact_alias_match):
        if session_context_match or geo_match or unique_exact or brand_exact:
            return ShopResolutionResult(
                status=ShopResolutionStatus.resolved,
                mention=query,
                shop_id=top1.shop_id,
                shop_name=top1.shop_name,
                canonical_name=top1.canonical_name,
                branch_name=top1.branch_name,
                alias=list(top1.alias or []),
                confidence=top1_score,
                source=top1.source,
                resolution_reason="high_confidence_match",
                needs_clarification=False,
                clarification_question="",
                candidates=candidates[:5],
                selected_candidate=top1,
                candidate_count=len(candidates),
                trace=trace + [{"mention": query, "result": "resolved", "details": best_trace, "margin": margin, "ambiguity_penalty": ambiguous_penalty}],
            )

    if len(candidates) == 1:
        if top1_score >= 0.72 and (high_confidence_alias or session_context_match or geo_match or unique_exact):
            return ShopResolutionResult(
                status=ShopResolutionStatus.resolved,
                mention=query,
                shop_id=top1.shop_id,
                shop_name=top1.shop_name,
                canonical_name=top1.canonical_name,
                branch_name=top1.branch_name,
                alias=list(top1.alias or []),
                confidence=top1_score,
                source=top1.source,
                resolution_reason="single_candidate",
                needs_clarification=False,
                clarification_question="",
                candidates=candidates,
                selected_candidate=top1,
                candidate_count=1,
                trace=trace + [{"mention": query, "result": "resolved_single", "details": best_trace}],
            )
        return ShopResolutionResult(
            status=ShopResolutionStatus.low_confidence,
            mention=query,
            shop_id=top1.shop_id,
            shop_name=top1.shop_name,
            canonical_name=top1.canonical_name,
            branch_name=top1.branch_name,
            alias=list(top1.alias or []),
            confidence=top1_score,
            source=top1.source,
            resolution_reason="single_candidate_low_confidence",
            needs_clarification=True,
            clarification_question="请提供更完整的店名或分店信息。",
            candidates=candidates,
            selected_candidate=top1,
            candidate_count=1,
            trace=trace + [{"mention": query, "result": "low_confidence_single", "details": best_trace}],
        )

    if top1_score < 0.58:
        return ShopResolutionResult(
            status=ShopResolutionStatus.low_confidence,
            mention=query,
            shop_id=top1.shop_id,
            shop_name=top1.shop_name,
            canonical_name=top1.canonical_name,
            branch_name=top1.branch_name,
            alias=list(top1.alias or []),
            confidence=top1_score,
            source=top1.source,
            resolution_reason="low_confidence_match",
            needs_clarification=True,
            clarification_question="请提供更完整的店名或分店信息。",
            candidates=candidates[:5],
            selected_candidate=top1,
            candidate_count=len(candidates),
            trace=trace + [{"mention": query, "result": "low_confidence", "details": best_trace, "margin": margin, "ambiguity_penalty": ambiguous_penalty}],
        )

    if len(candidates) > 1 and margin < 0.12:
        return ShopResolutionResult(
            status=ShopResolutionStatus.ambiguous,
            mention=query,
            confidence=top1_score,
            source=top1.source,
            resolution_reason="top_candidates_too_close",
            needs_clarification=True,
            clarification_question="请补充更完整的店名或分店信息。",
            candidates=candidates[:5],
            selected_candidate=top1,
            candidate_count=len(candidates),
            trace=trace + [{"mention": query, "result": "ambiguous", "details": best_trace, "margin": margin, "ambiguity_penalty": ambiguous_penalty}],
        )

    if query_norm and (brand_exact or branch_anchor_match or high_confidence_alias):
        return ShopResolutionResult(
            status=ShopResolutionStatus.low_confidence,
            mention=query,
            shop_id=top1.shop_id,
            shop_name=top1.shop_name,
            canonical_name=top1.canonical_name,
            branch_name=top1.branch_name,
            alias=list(top1.alias or []),
            confidence=top1_score,
            source=top1.source,
            resolution_reason="insufficient_disambiguation_signals",
            needs_clarification=True,
            clarification_question="请补充更完整的店名或分店信息。",
            candidates=candidates[:5],
            selected_candidate=top1,
            candidate_count=len(candidates),
            trace=trace + [{"mention": query, "result": "low_confidence_signals", "details": best_trace}],
        )

    return ShopResolutionResult(
        status=ShopResolutionStatus.ambiguous if len(candidates) > 1 else ShopResolutionStatus.not_found,
        mention=query,
        confidence=top1_score,
        source=top1.source if top1 else ShopResolutionSource.reference,
        resolution_reason="ambiguous" if len(candidates) > 1 else "not_found",
        needs_clarification=bool(len(candidates) > 1 or query_norm),
        clarification_question="请提供更完整的店名或分店信息。" if query_norm else "",
        candidates=candidates[:5],
        selected_candidate=top1,
        candidate_count=len(candidates),
        trace=trace + [{"mention": query, "result": "ambiguous_or_not_found", "details": best_trace}],
    )
