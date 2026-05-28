from __future__ import annotations

from typing import Any, Mapping, Sequence

from .answer_planner import CandidateEvidenceSummary, EvidenceItem, EvidencePack, SceneFitSummary


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return dict(dumped)
    return {}


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        raw_items = value
    else:
        raw_items = [value]
    result: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        text = _clean_text(item)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _format_coupon_summary(candidate: Mapping[str, Any]) -> str:
    vouchers = candidate.get("vouchers") or []
    if not vouchers:
        return "暂无可见券"
    first = vouchers[0] if vouchers else {}
    if isinstance(first, Mapping):
        title = _clean_text(first.get("title") or first.get("name")) or "优惠券"
        pay_value = first.get("pay_value") or first.get("payValue")
        actual_value = first.get("actual_value") or first.get("actualValue")
        if pay_value not in (None, "") and actual_value not in (None, ""):
            return f"{title}（{pay_value} 代 {actual_value}）"
        return title
    return "有券"


def _infer_scene_fit(candidate: Mapping[str, Any], scene: str | None) -> SceneFitSummary:
    structured = _as_mapping(candidate.get("structured_features"))
    reasons = " ".join(
        [
            _clean_text(candidate.get("name")) or "",
            " ".join(_string_list(candidate.get("explainable_reasons"))),
            " ".join(_string_list(candidate.get("matched_requirements"))),
            _clean_text(candidate.get("review_summary")) or "",
            " ".join(_string_list(candidate.get("risk_flags"))),
        ]
    )
    quiet_score = float(structured.get("quiet_score") or 0.0)
    parking = bool(structured.get("parking"))
    family_friendly = bool(structured.get("family_friendly"))
    elder_friendly = bool(structured.get("elder_friendly"))

    fit = "medium"
    reason = "综合证据看还可以。"
    scene_value = str(scene or "unknown")
    if scene_value == "family_dinner":
        fit = "high" if (family_friendly or elder_friendly or "家庭" in reasons or "爸妈" in reasons) else "medium"
        reason = "适合带爸妈一起吃饭。" if fit == "high" else "有一定家庭聚餐适配度。"
    elif scene_value == "date":
        fit = "high" if (quiet_score >= 0.7 or "约会" in reasons or "安静" in reasons) else "medium"
        reason = "适合约会。" if fit == "high" else "约会可考虑，但不算最强。"
    elif scene_value == "friends":
        fit = "high" if "朋友" in reasons or "聚餐" in reasons else "medium"
        reason = "适合朋友聚餐。" if fit == "high" else "朋友聚餐也能考虑。"
    elif scene_value == "business":
        fit = "high" if quiet_score >= 0.7 else "medium"
        reason = "相对更适合商务场景。" if fit == "high" else "商务场景可用但不算最稳。"
    elif scene_value == "solo":
        fit = "medium"
        reason = "一个人去也可以。"

    if fit != "high" and parking and scene_value in {"family_dinner", "date"}:
        reason = reason.rstrip("。") + "，而且有停车。"

    return SceneFitSummary(scene=scene_value, fit=fit, reason=reason)


def _candidate_summary(candidate: Mapping[str, Any], *, rank: int, evidence_ids: list[str], scene: str | None) -> CandidateEvidenceSummary:
    structured = _as_mapping(candidate.get("structured_features"))
    rank_score = candidate.get("rank_score")
    if rank_score in (None, ""):
        rank_score = structured.get("score")
    try:
        fit_score = float(rank_score or 0.0)
    except Exception:
        fit_score = 0.0
    return CandidateEvidenceSummary(
        shop_id=int(candidate.get("shop_id") or candidate.get("id") or 0),
        name=str(candidate.get("name") or candidate.get("shop_name") or f"shop-{rank}"),
        rank=rank,
        fit_score=fit_score,
        why=_string_list(candidate.get("explainable_reasons") or candidate.get("matched_requirements")),
        risks=_string_list(candidate.get("risk_flags")),
        coupon_summary=_format_coupon_summary(candidate),
        scene_fit=_infer_scene_fit(candidate, scene),
        evidence_used=evidence_ids,
    )


def build_evidence_pack(
    *,
    raw_query: str,
    ranked_candidates: Sequence[Mapping[str, Any] | Any],
    evidence_claims: Sequence[Mapping[str, Any] | Any],
    slots: Mapping[str, Any] | Any,
    source_summary: Mapping[str, Any] | Any,
    safety_result: Mapping[str, Any] | Any,
    max_candidates: int = 5,
    max_evidence_per_candidate: int = 3,
) -> EvidencePack:
    slots_map = _as_mapping(slots)
    source_summary_map = _as_mapping(source_summary)
    safety_result_map = _as_mapping(safety_result)
    scene = _clean_text(slots_map.get("scene"))

    normalized_candidates: list[dict[str, Any]] = [
        _as_mapping(candidate) for candidate in ranked_candidates[: max(0, int(max_candidates))]
    ]
    evidence_by_shop: dict[str, list[EvidenceItem]] = {}
    shop_evidence_map: dict[str, list[str]] = {}
    selected_shop_ids = {
        str(candidate.get("shop_id") or candidate.get("id"))
        for candidate in normalized_candidates
        if candidate.get("shop_id") not in (None, "") or candidate.get("id") not in (None, "")
    }

    for claim in evidence_claims:
        claim_map = _as_mapping(claim)
        shop_id = claim_map.get("shop_id")
        if shop_id in (None, ""):
            metadata_shop_id = _as_mapping(claim_map.get("metadata")).get("shop_id")
            shop_id = metadata_shop_id if metadata_shop_id not in (None, "") else None
        shop_key = str(shop_id) if shop_id not in (None, "") else "unknown"
        if selected_shop_ids and shop_key not in selected_shop_ids:
            continue
        item = EvidenceItem(
            evidence_id=str(claim_map.get("chunk_id") or claim_map.get("evidence_id") or f"{shop_key}-{len(evidence_by_shop.get(shop_key, [])) + 1}"),
            chunk_id=str(claim_map.get("chunk_id") or claim_map.get("evidence_id") or f"{shop_key}-{len(evidence_by_shop.get(shop_key, [])) + 1}"),
            source_type=str(claim_map.get("source_type") or claim_map.get("chunk_type") or "local_life"),
            shop_id=int(shop_id) if shop_id not in (None, "") else None,
            claim=str(claim_map.get("claim") or claim_map.get("support_text") or claim_map.get("text") or ""),
            confidence=float(claim_map.get("confidence") or 0.0),
            metadata=_as_mapping(claim_map.get("metadata")),
            chunk_type=str(claim_map.get("chunk_type") or claim_map.get("chunk_role") or claim_map.get("source_type") or "local_life"),
        )
        evidence_by_shop.setdefault(shop_key, []).append(item)

    for shop_key, items in list(evidence_by_shop.items()):
        items.sort(key=lambda item: (-float(item.confidence or 0.0), item.evidence_id))
        evidence_by_shop[shop_key] = items[: max(0, int(max_evidence_per_candidate))]
        shop_evidence_map[shop_key] = [item.evidence_id for item in evidence_by_shop[shop_key]]

    candidate_summaries: list[CandidateEvidenceSummary] = []
    items: list[EvidenceItem] = []
    for index, candidate in enumerate(normalized_candidates, start=1):
        shop_key = str(candidate.get("shop_id") or candidate.get("id") or "")
        candidate_items = evidence_by_shop.get(shop_key, [])
        items.extend(candidate_items)
        candidate_summaries.append(
            _candidate_summary(
                candidate,
                rank=index,
                evidence_ids=shop_evidence_map.get(shop_key, []),
                scene=scene,
            )
        )

    notes = []
    tool_summary_text = source_summary_map.get("tool_summary_text")
    if tool_summary_text:
        notes.append(str(tool_summary_text))
    degraded_reason = source_summary_map.get("degraded_reason")
    if degraded_reason:
        notes.append(str(degraded_reason))
    if safety_result_map.get("approval_required"):
        notes.append("approval_required")

    truncated = len(ranked_candidates) > len(candidate_summaries) or len(evidence_claims) > len(items)
    return EvidencePack(
        raw_query=raw_query,
        slots=slots_map,
        ranked_candidates=candidate_summaries,
        items=items,
        shop_evidence_map=shop_evidence_map,
        source_summary=source_summary_map,
        safety_result=safety_result_map,
        notes=notes,
        truncated=truncated,
    )


__all__ = ["build_evidence_pack"]
