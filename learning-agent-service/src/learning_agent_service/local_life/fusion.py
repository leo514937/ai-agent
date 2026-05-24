from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Sequence

from .schemas import CandidateProfile, EvidenceClaim, LocalLifeSlots, RankedCandidate, ShopRecord, VoucherRecord
from learning_agent_service.rag.local_life_retrieval import LocalLifeEvidencePack


def _as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return dumped
    return {}


def _candidate_base_features(shop: ShopRecord) -> dict[str, Any]:
    return {
        "distance_km": shop.distance_km,
        "avg_price": shop.avg_price,
        "score": shop.score,
        "comments": shop.comments,
        "open_hours": shop.open_hours,
        "parking": shop.parking,
        "quiet_score": shop.quiet_score,
        "family_friendly": shop.family_friendly,
        "elder_friendly": shop.elder_friendly,
        "area": shop.area,
        "address": shop.address,
        "type_name": shop.type_name,
        "tags": list(shop.tags),
        "source": shop.source,
    }


def _evidence_group(evidence_claims: Sequence[EvidenceClaim]) -> dict[int, list[EvidenceClaim]]:
    grouped: dict[int, list[EvidenceClaim]] = defaultdict(list)
    for claim in evidence_claims:
        if claim.shop_id is not None:
            grouped[int(claim.shop_id)].append(claim)
    return grouped


def _business_fact_bundle(shop: ShopRecord) -> dict[str, Any]:
    return {
        "shop_id": int(shop.id),
        "shop_name": shop.name,
        "distance_km": shop.distance_km,
        "avg_price": shop.avg_price,
        "score": shop.score,
        "comments": shop.comments,
        "open_hours": shop.open_hours,
        "parking": shop.parking,
        "quiet_score": shop.quiet_score,
        "family_friendly": shop.family_friendly,
        "elder_friendly": shop.elder_friendly,
        "tags": list(shop.tags),
        "area": shop.area,
        "address": shop.address,
        "type_name": shop.type_name,
        "source": shop.source,
    }


def _build_matched_requirements(shop: ShopRecord, slots: LocalLifeSlots, evidence_claims: list[EvidenceClaim]) -> list[str]:
    matched: list[str] = []
    if (slots.location.lat is not None or slots.location.lng is not None or slots.location.city) and shop.distance_km is not None:
        if slots.location.city and shop.area and slots.location.city in shop.area:
            matched.append("离我近")
        elif slots.location.city and shop.address and slots.location.city in shop.address:
            matched.append("离我近")
        elif shop.distance_km <= max(float(slots.location.radius_km), 1.0):
            matched.append("离我近")

    if shop.avg_price is not None:
        if slots.price.per_person_min is not None and slots.price.per_person_max is not None:
            if float(slots.price.per_person_min) <= float(shop.avg_price) <= float(slots.price.per_person_max):
                matched.append("人均预算符合")
        elif slots.price.target is not None:
            if abs(float(shop.avg_price) - float(slots.price.target)) <= 50.0:
                matched.append("人均预算符合")
        elif slots.price.per_person_max is not None and float(shop.avg_price) <= float(slots.price.per_person_max):
            matched.append("人均预算符合")
        elif slots.price.per_person_min is not None and float(shop.avg_price) >= float(slots.price.per_person_min):
            matched.append("人均预算符合")

    if (slots.scene == "family_dinner" or slots.companions) and shop.family_friendly:
        matched.append("适合带爸妈")
    if ("quiet" in slots.preferences and (shop.quiet_score >= 0.75 or any("安静" in claim.support_text for claim in evidence_claims))) or shop.quiet_score >= 0.9:
        matched.append("环境安静")
    if ("parking_available" in slots.preferences and shop.parking) or shop.parking:
        matched.append("有停车")
    if "elder_friendly" in slots.preferences and shop.elder_friendly:
        matched.append("对长辈友好")
    if any(claim.confidence >= 0.8 and "安静" in claim.support_text for claim in evidence_claims):
        matched.append("评论证据支持安静")
    if any(claim.confidence >= 0.7 and ("家里" in claim.support_text or "家庭" in claim.support_text or "爸妈" in claim.support_text) for claim in evidence_claims):
        matched.append("评论证据支持家庭聚餐")
    return list(dict.fromkeys(matched))


def _build_risk_flags(shop: ShopRecord, slots: LocalLifeSlots) -> list[str]:
    flags: list[str] = []
    if slots.price.per_person_max is not None and shop.avg_price is not None and float(shop.avg_price) > float(slots.price.per_person_max):
        flags.append("over_budget")
    if slots.price.per_person_min is not None and shop.avg_price is not None and float(shop.avg_price) < float(slots.price.per_person_min):
        flags.append("too_cheap")
    if slots.location.radius_km is not None and shop.distance_km is not None and float(shop.distance_km) > float(slots.location.radius_km):
        flags.append("far")
    if "quiet" in slots.preferences and shop.quiet_score < 0.55:
        flags.append("noisy")
    if "parking_available" in slots.preferences and not shop.parking:
        flags.append("no_parking")
    if any(tag in {"busy", "queue_risk"} for tag in shop.tags) and any(token in slots.avoid for token in ("busy", "queue_risk")):
        flags.append("long_queue")
    return list(dict.fromkeys(flags))


def _build_reason_list(shop: ShopRecord, slots: LocalLifeSlots, evidence_claims: list[EvidenceClaim]) -> list[str]:
    reasons: list[str] = []
    if shop.distance_km is not None:
        reasons.append(f"距离约{shop.distance_km:.1f}km")
    if shop.avg_price is not None:
        reasons.append(f"人均约{int(round(shop.avg_price))}元")
    if shop.score is not None:
        reasons.append(f"评分{shop.score:.1f}")
    if shop.parking:
        reasons.append("有停车信息")
    if shop.quiet_score >= 0.75:
        reasons.append("店内相对安静")
    if shop.family_friendly:
        reasons.append("适合家庭聚餐")
    if shop.elder_friendly:
        reasons.append("对长辈友好")
    if shop.open_hours:
        reasons.append(f"营业时间{shop.open_hours}")
    if any(claim.confidence >= 0.8 and "安静" in claim.support_text for claim in evidence_claims):
        reasons.append("评论摘要提到环境安静")
    if any(claim.confidence >= 0.7 and ("家里" in claim.support_text or "家庭" in claim.support_text or "爸妈" in claim.support_text) for claim in evidence_claims):
        reasons.append("评论摘要提到适合家庭聚餐")
    for claim in evidence_claims[:2]:
        reasons.append(claim.support_text[:36])
    return list(dict.fromkeys(reasons))


def fuse_candidates(
    structured_candidates: Sequence[ShopRecord],
    evidence_claims: Sequence[EvidenceClaim],
    *,
    slots: LocalLifeSlots,
    vouchers_by_shop_id: Mapping[int, Sequence[VoucherRecord]] | None = None,
) -> list[CandidateProfile]:
    vouchers_by_shop_id = vouchers_by_shop_id or {}
    evidence_map = _evidence_group(evidence_claims)
    profiles: list[CandidateProfile] = []
    for shop in structured_candidates:
        evidence = evidence_map.get(int(shop.id), [])
        profile = CandidateProfile(
            shop_id=int(shop.id),
            name=shop.name,
            matched_requirements=_build_matched_requirements(shop, slots, evidence),
            structured_features=_candidate_base_features(shop),
            evidence_features={
                "quiet": max([claim.confidence for claim in evidence if "安静" in claim.support_text] or [shop.quiet_score]),
                "family_dinner": max([claim.confidence for claim in evidence if any(token in claim.support_text for token in ("家庭", "爸妈", "长辈"))] or [0.0]),
                "elder_friendly": max([claim.confidence for claim in evidence if "长辈" in claim.support_text or "老人" in claim.support_text] or [0.0]),
                "parking": 1.0 if shop.parking else 0.0,
                "value_for_money": 1.0
                if (
                    shop.avg_price is not None
                    and (
                        (
                            slots.price.per_person_min is not None
                            and slots.price.per_person_max is not None
                            and float(slots.price.per_person_min) <= float(shop.avg_price) <= float(slots.price.per_person_max)
                        )
                        or (
                            slots.price.target is not None
                            and abs(float(shop.avg_price) - float(slots.price.target)) <= 50.0
                        )
                        or (
                            slots.price.per_person_max is not None
                            and float(shop.avg_price) <= float(slots.price.per_person_max)
                        )
                    )
                )
                else 0.0,
            },
            risk_flags=_build_risk_flags(shop, slots),
            explainable_reasons=_build_reason_list(shop, slots, evidence),
            vouchers=[voucher.model_dump(mode="json") for voucher in vouchers_by_shop_id.get(int(shop.id), [])],
            blog_snippets=[claim.support_text for claim in evidence if claim.source_type == "探店笔记"],
        )
        profiles.append(profile)
    return profiles


def merge_business_facts_with_semantic_evidence(
    structured_candidates: Sequence[ShopRecord],
    semantic_pack: LocalLifeEvidencePack | None,
    *,
    vouchers_by_shop_id: Mapping[int, Sequence[VoucherRecord]] | None = None,
    limit: int = 8,
) -> list[EvidenceClaim]:
    vouchers_by_shop_id = vouchers_by_shop_id or {}
    business_fact_by_shop_id = {int(shop.id): _business_fact_bundle(shop) for shop in structured_candidates}
    claims: list[EvidenceClaim] = []
    if semantic_pack is None:
        return claims

    seen_chunk_ids: set[str] = set()
    for parent in semantic_pack.parent_evidences:
        business_facts = business_fact_by_shop_id.get(int(parent.shop_id or 0), {})
        voucher_items = [
            voucher.model_dump(mode="json") if hasattr(voucher, "model_dump") else dict(voucher)
            for voucher in vouchers_by_shop_id.get(int(parent.shop_id or 0), [])
        ]
        for chunk in [*parent.matched_chunks, *parent.sibling_chunks]:
            if chunk.chunk_id in seen_chunk_ids:
                continue
            seen_chunk_ids.add(chunk.chunk_id)
            claims.append(
                EvidenceClaim(
                    chunk_id=chunk.chunk_id,
                    shop_id=parent.shop_id,
                    claim=f"{chunk.chunk_role or '本地生活证据'}：{chunk.title or chunk.chunk_id}",
                    support_text=chunk.text,
                    source_type=chunk.chunk_role or chunk.source_type or "local_life",
                    confidence=max(0.0, min(float(chunk.score if chunk.score is not None else parent.parent_score), 1.0)),
                    metadata={
                        **dict(chunk.payload),
                        "parent_id": parent.parent_id,
                        "parent_title": parent.parent_title,
                        "parent_score": parent.parent_score,
                        "chunk_role": chunk.chunk_role,
                        "retrieval_strategy": semantic_pack.retrieval_strategy,
                        "route": semantic_pack.route,
                        "score_breakdown": dict(parent.score_breakdown),
                        "business_facts": dict(parent.business_facts or business_facts),
                        "vouchers": voucher_items,
                    },
                )
            )
            if len(claims) >= max(0, int(limit)):
                return claims
    return claims


__all__ = [
    "fuse_candidates",
    "merge_business_facts_with_semantic_evidence",
]
