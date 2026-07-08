"""Deterministic recommendation ranking policy."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ...config import RECOMMENDATION_FINAL_TOP_K


class RankingPolicy(BaseModel):
    """Minimal executable ranking policy."""

    model_config = ConfigDict(extra="forbid")

    hard_constraints: dict[str, Any] = Field(default_factory=dict)
    filters: dict[str, Any] = Field(default_factory=dict)
    sort_by: list[str] = Field(default_factory=lambda: ["total_score", "rating", "distance_km", "shop_id"])
    top_k: int = RECOMMENDATION_FINAL_TOP_K

    def model_post_init(self, __context: Any) -> None:
        try:
            self.top_k = max(int(self.top_k or 0), 1)
        except Exception:
            self.top_k = RECOMMENDATION_FINAL_TOP_K


class ExpandSearchPolicy(BaseModel):
    """Minimal expansion policy that preserves user hard constraints."""

    model_config = ConfigDict(extra="forbid")

    preserve_hard_constraints: bool = True
    preserve_filters: bool = True
    preserve_sort_by: bool = True
    extra_candidate_limit: int = 5

    def expand(self, semantic_frame: dict[str, Any] | None = None) -> dict[str, Any]:
        frame = _to_dict(semantic_frame)
        hard_constraints = _to_dict(frame.get("hard_constraints"))
        filters = _to_dict(frame.get("filters"))
        ranking_signals = _to_dict(frame.get("ranking_signals"))
        candidate_limit = frame.get("candidate_limit")
        try:
            candidate_limit = int(candidate_limit or 0)
        except Exception:
            candidate_limit = 0
        if self.preserve_hard_constraints:
            frame["hard_constraints"] = dict(hard_constraints)
        if self.preserve_filters:
            frame["filters"] = dict(filters)
        if self.preserve_sort_by and ranking_signals.get("sort_by") is not None:
            ranking_signals["sort_by"] = list(ranking_signals.get("sort_by") or [])
        frame["ranking_signals"] = ranking_signals
        frame["candidate_limit"] = max(candidate_limit, self.extra_candidate_limit)
        return frame


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
    direct_query = str(frame.get("query", "") or frame.get("search_query", "") or "").strip()
    if direct_query:
        return direct_query

    constraints = _to_dict(frame.get("constraints"))
    for key in ("cuisine", "category"):
        value = str(constraints.get(key, "") or "").strip()
        if value:
            return value

    mentions = frame.get("merchant_mentions") or []
    if mentions:
        return str(mentions[0]).strip()

    primary_task = str(frame.get("primary_task", "") or "").strip().lower()
    if "hotpot" in primary_task or "火锅" in primary_task:
        return "火锅"

    # Try cuisine from hard_constraints first
    hard_constraints = _to_dict(frame.get("hard_constraints"))
    cuisine = str(hard_constraints.get("cuisine", "") or "").strip()
    if cuisine:
        return cuisine

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


def _hard_constraint_violations(candidate: dict[str, Any], preferences: dict[str, Any]) -> list[str]:
    violations: list[str] = []
    hard_constraints = _to_dict(preferences.get("hard_constraints"))
    if not hard_constraints:
        return violations
    candidate_text = _candidate_text(candidate)
    category = str(hard_constraints.get("category", "") or "").strip().lower()
    if category and category not in candidate_text:
        violations.append("category_mismatch")
    location = str(hard_constraints.get("location", "") or "").strip().lower()
    if location and location not in candidate_text and location not in str(candidate.get("address", "") or "").lower():
        violations.append("location_mismatch")
    open_now = hard_constraints.get("open_now")
    if open_now is True and str(candidate.get("open_status", "")).lower() != "open":
        violations.append("open_now_required")
    return violations


def score_candidate(candidate: dict[str, Any], preferences: dict[str, Any]) -> dict[str, Any]:
    """Assign a deterministic score and traceable reason codes."""
    candidate = _to_dict(candidate)
    preferences = _to_dict(preferences)
    hard_constraint_violations = _hard_constraint_violations(candidate, preferences)

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
    if hard_constraint_violations:
        total_score -= 1000.0

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
    if hard_constraint_violations:
        reason_codes.extend(hard_constraint_violations)
        degradation_notes.extend(hard_constraint_violations)

    return {
        **candidate,
        "score": round(total_score, 4),
        "total_score": round(total_score, 4),
        "component_scores": {key: round(value, 4) for key, value in component_scores.items()},
        "reason_codes": reason_codes,
        "degradation_notes": degradation_notes,
        "evidence_refs": evidence_refs,
        "failed_constraints": hard_constraint_violations,
        "provenance": {
            "hard_constraints": _to_dict(preferences.get("hard_constraints")),
            "filters": _to_dict(preferences.get("filters")),
            "sort_by": list(preferences.get("sort_by") or []),
        },
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


def _extract_brand(shop_name: str | None) -> str:
    """Extract brand name from a Chinese shop name (text before first parenthesis).

    '海底捞(牡丹园店)' -> '海底捞'
    '永和大王(北师大店)' -> '永和大王'
    '金谷园饺子馆' -> '金谷园饺子馆'
    None or '' -> ''
    """
    name = (shop_name or "").strip()
    if not name:
        return ""
    for sep in ("（", "(", " "):
        if sep in name:
            return name.split(sep)[0].strip()
    return name


def _dedup_by_brand(candidates: list[dict], max_per_brand: int = 1) -> list[dict]:
    """Brand-level diversity dedup: keep at most max_per_brand per brand, preserve order."""
    seen: dict[str, int] = {}
    result: list[dict] = []
    for item in candidates:
        brand = _extract_brand(item.get("shop_name", ""))
        if not brand:
            result.append(item)
            continue
        count = seen.get(brand, 0)
        if count >= max_per_brand:
            continue
        seen[brand] = count + 1
        result.append(item)
    return result


def rank_candidates(candidates: list, preferences: dict) -> list:
    """Rank shop candidates by the fixed scoring formula."""
    scored = [score_candidate(candidate, preferences) for candidate in candidates or []]
    surviving = [
        item
        for item in scored
        if not item.get("failed_constraints")
        and str(item.get("open_status", "")).lower() != "closed"
        and not item.get("detail_failed")
    ]
    if not surviving:
        surviving = [
            item
            for item in scored
            if not item.get("failed_constraints")
            and not item.get("detail_failed")
        ]
    scored.sort(
        key=lambda item: (
            -float(item.get("total_score", 0.0) or 0.0),
            -float(item.get("rating", 0.0) or 0.0),
            float(item.get("distance_km", 9999.0) or 9999.0),
            str(item.get("shop_id", "")),
        )
    )
    surviving.sort(
        key=lambda item: (
            -float(item.get("total_score", 0.0) or 0.0),
            -float(item.get("rating", 0.0) or 0.0),
            float(item.get("distance_km", 9999.0) or 9999.0),
            str(item.get("shop_id", "")),
        )
    )
    # Brand-level diversity dedup with backfill
    deduped = _dedup_by_brand(surviving, max_per_brand=1)
    target_k = RECOMMENDATION_FINAL_TOP_K

    if len(deduped) >= target_k:
        return deduped[:target_k]

    # Backfill from remaining survivors by original rank order
    seen_ids: set = {d.get("shop_id") for d in deduped if d.get("shop_id")}
    for item in surviving:
        if len(deduped) >= target_k:
            break
        if item.get("shop_id") in seen_ids:
            continue
        if not item.get("shop_id"):
            # fallback: use shop_name for items without shop_id
            if any(d.get("shop_name") == item.get("shop_name") for d in deduped):
                continue
        seen_ids.add(item.get("shop_id"))
        deduped.append(item)

    return deduped


def _comparison_rank_key(row: dict[str, Any]) -> tuple[float, float, float, float]:
    return (
        -float(row.get("overall_score", row.get("total_score", row.get("score", 0.0))) or 0.0),
        -float(row.get("known_dimensions", 0) or 0.0),
        -float(row.get("rating", 0.0) or 0.0),
        float(row.get("distance_km", 9999.0) or 9999.0),
    )


def derive_comparison_winner(rows: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Derive a strong comparison winner from scored comparison rows.

    The winner is only exposed when the evidence-based ordering is strictly
    better than the runner-up. Pure tie-breakers such as shop_id never create
    a winner.
    """

    ranked = [_to_dict(item) for item in (rows or []) if _to_dict(item)]
    ranked = [
        item
        for item in ranked
        if str(item.get("shop_id", "") or item.get("shop_name", "") or "").strip()
    ]
    provenance = {
        "source": "comparison_matrix",
        "ranking_basis": ["overall_score", "known_dimensions", "rating", "distance_km"],
        "tie_breaker": "shop_id",
        "ranked_shop_ids": [str(item.get("shop_id", "") or "").strip() for item in ranked if str(item.get("shop_id", "") or "").strip()],
    }
    if len(ranked) < 2:
        return {
            "statistical_winner": None,
            "winner_provenance": provenance,
            "winner_uncertainty_note": "比较候选不足，无法确认唯一赢家",
        }

    ranked = sorted(ranked, key=_comparison_rank_key)
    top = ranked[0]
    runner_up = ranked[1]
    top_key = _comparison_rank_key(top)
    runner_up_key = _comparison_rank_key(runner_up)
    if top_key == runner_up_key:
        return {
            "statistical_winner": None,
            "winner_provenance": {
                **provenance,
                "top_candidate": {
                    "shop_id": str(top.get("shop_id", "") or "").strip(),
                    "shop_name": str(top.get("shop_name", "") or "").strip(),
                    "score": round(float(top.get("overall_score", top.get("total_score", top.get("score", 0.0))) or 0.0), 4),
                },
                "runner_up": {
                    "shop_id": str(runner_up.get("shop_id", "") or "").strip(),
                    "shop_name": str(runner_up.get("shop_name", "") or "").strip(),
                    "score": round(float(runner_up.get("overall_score", runner_up.get("total_score", runner_up.get("score", 0.0))) or 0.0), 4),
                },
            },
            "winner_uncertainty_note": "比较证据并列，暂时无法确认唯一赢家",
        }

    top_score = round(float(top.get("overall_score", top.get("total_score", top.get("score", 0.0))) or 0.0), 4)
    runner_up_score = round(float(runner_up.get("overall_score", runner_up.get("total_score", runner_up.get("score", 0.0))) or 0.0), 4)
    winner = {
        "shop_id": str(top.get("shop_id", "") or "").strip(),
        "shop_name": str(top.get("shop_name", "") or "").strip(),
        "score": top_score,
        "score_gap": round(top_score - runner_up_score, 4),
        "known_dimensions": int(top.get("known_dimensions", 0) or 0),
        "reason": f"综合得分 {top_score} 高于 {runner_up_score}",
        "reason_codes": list(top.get("reason_codes") or []),
        "evidence_refs": list(top.get("evidence_refs") or []),
        "component_scores": dict(top.get("component_scores") or {}),
        "score_breakdown": dict(top.get("score_breakdown") or {}),
        "provenance": dict(top.get("provenance") or {}),
    }
    return {
        "statistical_winner": winner,
        "winner_provenance": {
            **provenance,
            "top_candidate": {
                "shop_id": winner["shop_id"],
                "shop_name": winner["shop_name"],
                "score": winner["score"],
                "known_dimensions": winner["known_dimensions"],
            },
            "runner_up": {
                "shop_id": str(runner_up.get("shop_id", "") or "").strip(),
                "shop_name": str(runner_up.get("shop_name", "") or "").strip(),
                "score": runner_up_score,
                "known_dimensions": int(runner_up.get("known_dimensions", 0) or 0),
            },
            "score_gap": winner["score_gap"],
            "winner_rank_key": list(top_key),
            "runner_up_rank_key": list(runner_up_key),
        },
        "winner_uncertainty_note": "",
    }
