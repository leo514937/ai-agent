from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping, Sequence

from .schemas import CandidateProfile, LocalLifeSlots, RankedCandidate


def _distance_score(candidate: CandidateProfile, slots: LocalLifeSlots) -> float:
    distance = candidate.structured_features.get("distance_km")
    if distance is None:
        return 0.4
    radius = max(slots.location.radius_km, 1.0)
    return max(0.0, 1.0 - float(distance) / (radius * 1.8))


def _price_score(candidate: CandidateProfile, slots: LocalLifeSlots) -> float:
    avg_price = candidate.structured_features.get("avg_price")
    min_price = slots.price.per_person_min
    target = slots.price.target
    max_price = slots.price.per_person_max
    if avg_price is None:
        return 0.5
    if min_price is not None and max_price is not None:
        if float(min_price) <= float(avg_price) <= float(max_price):
            return 1.0
        if float(avg_price) < float(min_price):
            diff = float(min_price) - float(avg_price)
            return max(0.0, 1.0 - diff / max(float(min_price), 100.0))
        diff = float(avg_price) - float(max_price)
        return max(0.0, 1.0 - diff / max(float(max_price), 100.0))
    if target is not None:
        diff = abs(float(avg_price) - float(target))
        return max(0.0, 1.0 - diff / max(float(target), 100.0))
    if max_price is not None:
        return 1.0 if float(avg_price) <= float(max_price) else max(0.0, 1.0 - (float(avg_price) - float(max_price)) / max(float(max_price), 100.0))
    if min_price is not None:
        return 1.0 if float(avg_price) >= float(min_price) else max(0.0, 1.0 - (float(min_price) - float(avg_price)) / max(float(min_price), 100.0))
    return 0.7


def _rating_score(candidate: CandidateProfile) -> float:
    score = candidate.structured_features.get("score")
    if score is None:
        return 0.5
    return min(1.0, max(0.0, float(score) / 5.0))


def _evidence_score(candidate: CandidateProfile) -> float:
    values = list(candidate.evidence_features.values())
    if not values:
        return 0.4
    return max(0.0, min(1.0, sum(values) / len(values)))


def _preference_score(candidate: CandidateProfile, slots: LocalLifeSlots) -> float:
    score = 0.0
    if "quiet" in slots.preferences:
        score += 1.0 if candidate.evidence_features.get("quiet", 0.0) >= 0.6 else 0.0
    if "parking_available" in slots.preferences:
        score += 1.0 if candidate.structured_features.get("parking") else 0.0
    if "elder_friendly" in slots.preferences:
        score += 1.0 if candidate.structured_features.get("elder_friendly") else 0.0
    if "family_dinner" in slots.preferences or slots.scene == "family_dinner":
        score += 1.0 if candidate.structured_features.get("family_friendly") else 0.0
    if "private_room" in slots.preferences and "private_room" in candidate.structured_features.get("tags", []):
        score += 0.5
    return min(1.0, score / 3.0)


def _coupon_score(candidate: CandidateProfile) -> float:
    vouchers = candidate.vouchers or []
    return 1.0 if vouchers else 0.0


def _availability_score(candidate: CandidateProfile) -> float:
    open_hours = candidate.structured_features.get("open_hours")
    return 1.0 if open_hours else 0.5


def _risk_penalty(candidate: CandidateProfile) -> float:
    return min(1.0, 0.18 * len(candidate.risk_flags))


def _as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return dumped
    return {}


def _parent_business_score(evidence: Any) -> float:
    debug_info = _as_mapping(getattr(evidence, "debug_info", {}))
    raw = debug_info.get("business_filter_match_score")
    if raw is None:
        raw = debug_info.get("business_boost_score")
    try:
        return max(0.0, min(float(raw if raw is not None else 0.0), 1.0))
    except Exception:
        return 0.0


def _parent_semantic_score(evidence: Any) -> float:
    debug_info = _as_mapping(getattr(evidence, "debug_info", {}))
    raw = debug_info.get("semantic_parent_score")
    if raw is None:
        raw = getattr(evidence, "parent_score", 0.0)
    try:
        return max(0.0, min(float(raw if raw is not None else 0.0), 1.0))
    except Exception:
        return 0.0


def _parent_preference_score(evidence: Any, slots: LocalLifeSlots | None) -> float:
    if slots is None:
        return 0.0
    facts = _as_mapping(getattr(evidence, "business_facts", {}))
    score = 0.0
    if "quiet" in slots.preferences:
        score += 1.0 if float(facts.get("quiet_score") or 0.0) >= 0.75 else 0.0
    if "parking_available" in slots.preferences:
        score += 1.0 if facts.get("parking") else 0.0
    if "elder_friendly" in slots.preferences:
        score += 1.0 if facts.get("elder_friendly") else 0.0
    if "family_dinner" in slots.preferences or slots.scene == "family_dinner":
        score += 1.0 if facts.get("family_friendly") else 0.0
    if "private_room" in slots.preferences and "private_room" in facts.get("tags", []):
        score += 0.5
    return min(1.0, score / 3.0)


def _parent_availability_score(evidence: Any) -> float:
    facts = _as_mapping(getattr(evidence, "business_facts", {}))
    open_now = facts.get("open_now")
    if open_now is True:
        return 1.0
    if open_now is False:
        return 0.1
    open_hours = facts.get("open_hours")
    if open_hours:
        return 1.0
    return 0.5


def rerank_parent_evidences(
    parent_evidences: Sequence[Any],
    *,
    slots: LocalLifeSlots | None = None,
    route: str | None = None,
) -> list[Any]:
    route_value = str(route or "").strip().lower()
    if not parent_evidences:
        return []

    if route_value == "guide_rule_rag":
        weights = (0.60, 0.10, 0.10, 0.20)
    elif route_value == "compare_multi_parent":
        weights = (0.45, 0.20, 0.25, 0.10)
    else:
        weights = (0.50, 0.20, 0.20, 0.10)

    rescored: list[tuple[float, Any, Mapping[str, float]]] = []
    for evidence in parent_evidences:
        semantic_score = _parent_semantic_score(evidence)
        business_score = _parent_business_score(evidence)
        preference_score = _parent_preference_score(evidence, slots)
        availability_score = _parent_availability_score(evidence)
        rerank_score = (
            semantic_score * weights[0]
            + business_score * weights[1]
            + preference_score * weights[2]
            + availability_score * weights[3]
        )
        breakdown = {
            "semantic_parent_score": round(semantic_score, 3),
            "business_score": round(business_score, 3),
            "user_preference_score": round(preference_score, 3),
            "availability_score": round(availability_score, 3),
            "rerank_score": round(rerank_score, 4),
        }
        rescored.append((rerank_score, evidence, breakdown))

    rescored.sort(
        key=lambda item: (
            -item[0],
            str(getattr(item[1], "shop_name", "") or ""),
            str(getattr(item[1], "parent_id", "") or ""),
        )
    )

    reranked: list[Any] = []
    for score, evidence, breakdown in rescored:
        debug_info = dict(_as_mapping(getattr(evidence, "debug_info", {})))
        score_breakdown = dict(_as_mapping(getattr(evidence, "score_breakdown", {})))
        score_breakdown.update(breakdown)
        debug_info["rerank_score"] = round(score, 4)
        debug_info["rerank_route"] = route_value or debug_info.get("rerank_route", "")
        debug_info["score_breakdown"] = dict(score_breakdown)
        try:
            reranked.append(
                replace(
                    evidence,
                    parent_score=round(score, 4),
                    score_breakdown=score_breakdown,
                    debug_info=debug_info,
                )
            )
        except Exception:
            reranked.append(evidence)
    return reranked


def rank_candidate(candidate: CandidateProfile, slots: LocalLifeSlots) -> RankedCandidate:
    semantic_match_score = min(1.0, 0.1 * len(candidate.matched_requirements) + 0.2 * _evidence_score(candidate))
    distance_score = _distance_score(candidate, slots)
    price_score = _price_score(candidate, slots)
    rating_score = _rating_score(candidate)
    evidence_score = _evidence_score(candidate)
    preference_score = _preference_score(candidate, slots)
    coupon_score = _coupon_score(candidate)
    availability_score = _availability_score(candidate)
    risk_penalty = _risk_penalty(candidate)

    total = (
        0.25 * semantic_match_score
        + 0.15 * distance_score
        + 0.15 * price_score
        + 0.10 * rating_score
        + 0.15 * evidence_score
        + 0.10 * preference_score
        + 0.05 * coupon_score
        + 0.05 * availability_score
        - risk_penalty
    )

    breakdown = {
        "semantic": round(semantic_match_score, 3),
        "distance": round(distance_score, 3),
        "price": round(price_score, 3),
        "rating": round(rating_score, 3),
        "evidence": round(evidence_score, 3),
        "preference": round(preference_score, 3),
        "coupon": round(coupon_score, 3),
        "availability": round(availability_score, 3),
        "risk_penalty": round(risk_penalty, 3),
    }
    payload = candidate.model_dump(mode="json", exclude={"score_breakdown", "rank_score"})
    return RankedCandidate(
        **payload,
        score_breakdown=breakdown,
        rank_score=round(total, 4),
    )


def rank_candidates(candidates: Sequence[CandidateProfile], slots: LocalLifeSlots) -> list[RankedCandidate]:
    ranked = [rank_candidate(candidate, slots) for candidate in candidates]

    def _sort_key(item: RankedCandidate) -> tuple[float, float, float]:
        distance_value = item.structured_features.get("distance_km")
        score_value = item.structured_features.get("score")
        return (
            -item.rank_score,
            float(distance_value) if distance_value is not None else 999.0,
            -float(score_value) if score_value is not None else 0.0,
        )

    ranked.sort(
        key=_sort_key
    )
    return ranked


__all__ = [
    "rank_candidate",
    "rank_candidates",
    "rerank_parent_evidences",
]
