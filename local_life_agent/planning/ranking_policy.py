"""Deterministic recommendation ranking policy."""

from __future__ import annotations

from typing import Any

from ..config import RECOMMENDATION_FINAL_TOP_K


def _to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        return dumped if isinstance(dumped, dict) else {}
    return dict(getattr(value, "__dict__", {}) or {})


def _as_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def infer_recommendation_query(semantic_frame: dict[str, Any]) -> str:
    """Infer the search query used for recommendation recall."""
    frame = _to_dict(semantic_frame)
    mentions = frame.get("merchant_mentions") or []
    if mentions:
        return str(mentions[0]).strip()

    primary_task = str(frame.get("primary_task", "") or "").strip().lower()
    if "hotpot" in primary_task or "火锅" in primary_task:
        return "火锅"

    # Strip common intent-direction verbs from start AND end to extract the core subject
    task_stripped = primary_task
    for _pfx in ("附近推荐", "推荐附近", "推荐", "找", "附近", "查询", "寻找", "有", "来", "求推荐", "求", "想找", "想要", "需要", "有没有"):
        if task_stripped.startswith(_pfx):
            task_stripped = task_stripped[len(_pfx):].strip()
            break
    # Remove trailing intent words and particles
    for _sfx in ("的店", "的地方", "的馆子", "的餐厅", "推荐", "的", "一下", "呗", "吧", "呢", "吗", "啊"):
        if task_stripped.endswith(_sfx):
            task_stripped = task_stripped[:-len(_sfx)].strip()
            break
    if task_stripped and task_stripped != primary_task and len(task_stripped) >= 2:
        return task_stripped

    signals = _to_dict(frame.get("ranking_signals"))
    for key in ("query", "category", "keyword"):
        value = signals.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    query_terms = _as_list(signals.get("query_terms"))
    if query_terms:
        return query_terms[0]

    soft_preferences = _to_dict(frame.get("soft_preferences"))
    scene_terms = _as_list(soft_preferences.get("scene_terms"))
    if scene_terms:
        return scene_terms[0]
    return ""


def _candidate_text(candidate: dict[str, Any]) -> str:
    parts = [
        str(candidate.get("shop_name", "")),
        str(candidate.get("category", "")),
        str(candidate.get("sub_category", "")),
        " ".join(str(item) for item in candidate.get("tags", []) or []),
    ]
    return " ".join(part for part in parts if part).lower()


def _terms_match(terms: list[str], candidate: dict[str, Any]) -> bool:
    if not terms:
        return False
    haystack = _candidate_text(candidate)
    return any(term and term.lower() in haystack for term in terms)


def _distance_score(distance_km: Any) -> float:
    try:
        value = float(distance_km)
    except Exception:
        return 0.0
    if value < 0:
        return 0.0
    if value >= 10:
        return 0.0
    return max(0.0, 1.0 - (value / 10.0))


def _rating_score(rating: Any) -> float:
    try:
        value = float(rating)
    except Exception:
        return 0.0
    return max(0.0, min(1.0, value / 5.0))


def _coupon_score(candidate: dict[str, Any]) -> float:
    coupon_count = candidate.get("coupon_count")
    if coupon_count is None:
        return 0.0
    try:
        count = int(coupon_count)
    except Exception:
        return 0.0
    return 1.0 if count > 0 else 0.0


def _open_status_score(candidate: dict[str, Any]) -> float:
    status = str(candidate.get("open_status", "") or "").lower()
    if status == "open":
        return 1.0
    if status == "closed":
        return 0.0
    return 0.0


def _category_match_score(preferences: dict[str, Any], candidate: dict[str, Any]) -> float:
    query_terms = _as_list(preferences.get("query_terms"))
    return 1.0 if _terms_match(query_terms, candidate) else 0.0


def _tag_match_score(preferences: dict[str, Any], candidate: dict[str, Any]) -> float:
    scene_terms = _as_list(preferences.get("scene_terms"))
    return 1.0 if _terms_match(scene_terms, candidate) else 0.0


def _risk_penalty(candidate: dict[str, Any]) -> float:
    if candidate.get("detail_failed"):
        return 100.0
    if str(candidate.get("open_status", "")).lower() == "closed":
        return 100.0
    return 0.0


def score_candidate(candidate: dict[str, Any], preferences: dict[str, Any]) -> dict[str, Any]:
    """Assign a deterministic score and traceable reason codes."""
    candidate = _to_dict(candidate)
    preferences = _to_dict(preferences)

    component_scores = {
        "category_match": _category_match_score(preferences, candidate),
        "open_status_score": _open_status_score(candidate),
        "distance_score": _distance_score(candidate.get("distance_km")),
        "rating_score": _rating_score(candidate.get("rating")),
        "coupon_score": _coupon_score(candidate),
        "tag_match_score": _tag_match_score(preferences, candidate),
        "risk_penalty": _risk_penalty(candidate),
    }

    total_score = (
        component_scores["category_match"] * 30
        + component_scores["open_status_score"] * 25
        + component_scores["distance_score"] * 20
        + component_scores["rating_score"] * 15
        + component_scores["coupon_score"] * 10
        + component_scores["tag_match_score"] * 10
        - component_scores["risk_penalty"]
    )

    reason_codes: list[str] = []
    degradation_notes: list[str] = []
    evidence_refs: list[str] = []

    if component_scores["category_match"]:
        reason_codes.append("category_match")
    if component_scores["tag_match_score"]:
        reason_codes.append("scene_fit")
    if component_scores["open_status_score"]:
        reason_codes.append("open_now")
        evidence_refs.append("open_status")
    elif str(candidate.get("open_status", "")).lower() == "closed":
        reason_codes.append("closed")
        degradation_notes.append("shop_closed_removed_or_penalized")
    else:
        degradation_notes.append("open_status_unknown")
    if candidate.get("distance_km") is not None:
        reason_codes.append("distance_known")
        evidence_refs.append("distance")
    else:
        reason_codes.append("distance_unknown")
        degradation_notes.append("distance_missing")
    if component_scores["rating_score"]:
        reason_codes.append("rating_known")
        evidence_refs.append("rating")
    else:
        reason_codes.append("rating_unknown")
        degradation_notes.append("rating_missing")
    if component_scores["coupon_score"]:
        reason_codes.append("has_coupon")
        evidence_refs.append("coupon")
    elif candidate.get("coupon_count") == 0:
        reason_codes.append("coupon_empty")
    else:
        reason_codes.append("coupon_unknown")
        degradation_notes.append("coupon_unknown")
    if component_scores["risk_penalty"]:
        reason_codes.append("risk_penalty")

    return {
        **candidate,
        "score": round(total_score, 4),
        "total_score": round(total_score, 4),
        "component_scores": {key: round(value, 4) for key, value in component_scores.items()},
        "reason_codes": reason_codes,
        "degradation_notes": degradation_notes,
        "evidence_refs": evidence_refs,
        "score_breakdown": {
            "category_match": round(component_scores["category_match"] * 30, 4),
            "open_status_score": round(component_scores["open_status_score"] * 25, 4),
            "distance_score": round(component_scores["distance_score"] * 20, 4),
            "rating_score": round(component_scores["rating_score"] * 15, 4),
            "coupon_score": round(component_scores["coupon_score"] * 10, 4),
            "tag_match_score": round(component_scores["tag_match_score"] * 10, 4),
            "risk_penalty": round(component_scores["risk_penalty"], 4),
        },
    }


def rank_candidates(candidates: list, preferences: dict) -> list:
    """Rank shop candidates by the fixed scoring formula."""
    scored = [score_candidate(candidate, preferences) for candidate in candidates or []]
    scored.sort(
        key=lambda item: (
            -float(item.get("total_score", 0.0) or 0.0),
            -float(item.get("rating", 0.0) or 0.0),
            float(item.get("distance_km", 9999.0) or 9999.0),
            str(item.get("shop_id", "")),
        )
    )
    return scored[:RECOMMENDATION_FINAL_TOP_K]
