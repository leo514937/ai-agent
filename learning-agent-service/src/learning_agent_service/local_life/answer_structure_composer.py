from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from learning_agent_service.domain.utils import as_mapping as _as_mapping, clean_text as _clean_text

from .answer_depth_policy import AnswerDepthPolicy, build_answer_structure_requirements


def _unique_text(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _clean_text(item)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _candidate_list(value: Any) -> list[dict[str, Any]]:
    items = value or []
    result: list[dict[str, Any]] = []
    for item in items:
        result.append(_as_mapping(item))
    return result


def _sentence_count(text: str) -> int:
    return len([segment for segment in text.replace("\n", "。").split("。") if segment.strip()])


def _bullet_count(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.lstrip().startswith(("-", "•", "*")) or line.lstrip().startswith(tuple(f"{i}." for i in range(1, 10))))


def _group_claims_by_shop(evidence_claims: list[dict[str, Any]]) -> dict[int | None, list[str]]:
    grouped: dict[int | None, list[str]] = defaultdict(list)
    for claim in evidence_claims:
        shop_id = claim.get("shop_id")
        try:
            shop_key = int(shop_id) if shop_id not in (None, "") else None
        except Exception:
            shop_key = None
        text = _clean_text(claim.get("claim") or claim.get("support_text") or claim.get("text"))
        if text:
            grouped[shop_key].append(text)
    return grouped


def _candidate_reason(candidate: dict[str, Any]) -> str:
    reasons = _unique_text([
        *[str(item) for item in candidate.get("explainable_reasons") or []],
        *[str(item) for item in candidate.get("matched_requirements") or []],
    ])
    if reasons:
        return "；".join(reasons[:3])
    structured = candidate.get("structured_features") or {}
    bits: list[str] = []
    if structured.get("score") not in (None, ""):
        bits.append(f"评分{structured.get('score')}")
    if structured.get("avg_price") not in (None, ""):
        bits.append(f"人均约{structured.get('avg_price')}")
    if structured.get("distance_km") not in (None, ""):
        bits.append(f"距你约{structured.get('distance_km')}公里")
    return "；".join(bits) if bits else "证据有限，但当前排序靠前"


def _format_shop_section(index: int, candidate: dict[str, Any], claims: list[str], requirements: dict[str, Any]) -> str:
    name = _clean_text(candidate.get("name") or candidate.get("shop_name") or f"店铺{index}")
    structured = candidate.get("structured_features") or {}
    bullets: list[str] = []
    primary_reason = _candidate_reason(candidate)
    if primary_reason:
        bullets.append(f"- 推荐理由：{primary_reason}")
    for claim in claims[: max(0, int(requirements.get("per_shop_min_reasons", 2)) - 1)]:
        bullets.append(f"- 推荐理由：{claim}")
    if structured.get("avg_price") not in (None, ""):
        bullets.append(f"- 适合场景：如果你在意预算，{name}的人均约{structured.get('avg_price')}。")
    elif structured.get("distance_km") not in (None, ""):
        bullets.append(f"- 适合场景：{name}距离你约{structured.get('distance_km')}公里，适合就近选择。")
    else:
        bullets.append(f"- 适合场景：适合先看证据再下决定。")
    bullets.append("- 注意事项：建议结合时段、排队和现有信息再确认一次。")
    body = "\n".join(bullets)
    return f"{index}. {name}\n{body}"


def _compose_single_shop_review(topic_name: str, candidate: dict[str, Any], grouped_claims: dict[int | None, list[str]], requirements: dict[str, Any]) -> str:
    name = _clean_text(topic_name or candidate.get("name") or candidate.get("shop_name") or "这家店")
    structured = candidate.get("structured_features") or {}
    claims = _unique_text(grouped_claims.get(candidate.get("shop_id"), []) + grouped_claims.get(None, []))
    positive_claims = claims[:2]
    risk_claim = "建议关注排队、时段和是否需要提前订位。"
    if claims:
        risk_claim = f"证据里没有明显硬伤，但仍建议关注 {claims[-1]}。"
    sections = [
        ("总体结论", [f"{name}整体上可以先作为候选，当前证据支持它是一个值得考虑的选择。"]),
        ("核心优点", positive_claims or ["当前证据显示它的综合表现比较稳，核心优点主要来自现有评价和排序。"]),
        ("可能不足", [risk_claim]),
        ("适合场景", [f"如果你更看重{'环境和体验' if 'environment' in requirements.get('sections', []) else '综合表现'}，这家店可以优先看。"]),
        ("到店建议", [f"先看营业状态、券和排队，再决定是否现在去。"]),
    ]
    if structured.get("score") not in (None, ""):
        sections[0] = ("总体结论", [f"{name}整体评分约{structured.get('score')}，可以作为优先候选。"])
    return "\n".join(f"{title}\n" + "\n".join(f"- {bullet}" for bullet in bullets) for title, bullets in sections)


def _compose_facet_multi(requirements: dict[str, Any], grouped_claims: dict[int | None, list[str]]) -> str:
    sections: list[tuple[str, list[str]]] = []
    for title in requirements.get("sections", []):
        if title == "优惠券":
            bullets = grouped_claims.get(None, [])[:2] or ["当前证据里券的信息有限，建议以现有信息为准。"]
        elif title == "营业状态":
            bullets = ["当前只展示营业相关证据，不扩展其他话题。"]
        elif title == "环境评价":
            bullets = grouped_claims.get(None, [])[:2] or ["环境证据有限，但可以结合店铺详情继续看。"]
        else:
            bullets = ["综合看，先按当前证据筛选，再结合现有信息确认。"]
        sections.append((title, bullets))
    return "\n".join(f"{title}\n" + "\n".join(f"- {bullet}" for bullet in bullets) for title, bullets in sections)


def _compose_multi_shop_recommendation(topic_name: str, ranked_candidates: list[dict[str, Any]], grouped_claims: dict[int | None, list[str]], requirements: dict[str, Any]) -> str:
    lines = [f"{topic_name or '推荐结果'}：我先给你列出当前更值得看的几家。"]
    unique_candidates: list[dict[str, Any]] = []
    seen_shop_ids: set[int] = set()
    for candidate in ranked_candidates:
        shop_id = candidate.get("shop_id")
        try:
            shop_id_int = int(shop_id)
        except Exception:
            shop_id_int = None
        if shop_id_int is not None and shop_id_int in seen_shop_ids:
            continue
        if shop_id_int is not None:
            seen_shop_ids.add(shop_id_int)
        unique_candidates.append(candidate)
    if not unique_candidates and grouped_claims:
        fallback_items: list[tuple[str, str]] = []
        seen_names: set[str] = set()
        for shop_id, claims in grouped_claims.items():
            claim_texts = _unique_text(list(claims))
            candidate_name = f"候选店铺{len(fallback_items) + 1}"
            if shop_id is not None:
                candidate_name = f"候选店铺{shop_id}"
            if claim_texts:
                first_claim = claim_texts[0]
                candidate_name = first_claim.split(" ", 1)[0].split("（", 1)[0].strip() or candidate_name
            if candidate_name in seen_names:
                continue
            seen_names.add(candidate_name)
            reason = claim_texts[0] if claim_texts else "当前证据支持先纳入候选。"
            fallback_items.append((candidate_name, reason))
            if len(fallback_items) >= 3:
                break
        if fallback_items:
            for index, (candidate_name, reason) in enumerate(fallback_items, start=1):
                lines.append(f"{index}. {candidate_name}\n- 推荐理由：{reason}\n- 适合场景：适合先纳入候选，再结合距离和预算确认。\n- 注意事项：建议再看营业状态和实时信息。")
            lines.append("综合建议\n- 先按距离、预算和场景筛一轮，再看券和营业状态。")
            return "\n".join(lines)
    for index, candidate in enumerate(unique_candidates[:3], start=1):
        shop_id = candidate.get("shop_id")
        try:
            shop_id_int = int(shop_id)
        except Exception:
            shop_id_int = None
        claims = _unique_text(grouped_claims.get(shop_id_int, []))
        if len(claims) < 2:
            fallback_claims = [
                _candidate_reason(candidate),
                "适合约会/聚餐/日常场景，具体看你的偏好。",
            ]
            claims = _unique_text([*claims, *fallback_claims])
        lines.append(_format_shop_section(index, candidate, claims, requirements))
    lines.append("综合建议\n- 先按距离、预算和场景筛一轮，再看券和营业状态。")
    return "\n".join(lines)


@dataclass(frozen=True)
class AnswerStructureResult:
    answer_text: str
    sections: list[dict[str, Any]] = field(default_factory=list)
    section_count: int = 0
    bullet_count: int = 0
    duplicate_sentence_count: int = 0
    duplicate_ratio: float = 0.0
    recommendation_duplicate_shop_count: int = 0


class AnswerStructureComposer:
    def compose(
        self,
        *,
        answer_contract: Any | None,
        topic_name: str,
        ranked_candidates: list[Any] | None,
        evidence_claims: list[Any] | None,
        answer_depth_policy: AnswerDepthPolicy,
        user_need: Any | None = None,
        facet_result_bundle: Any | None = None,
    ) -> AnswerStructureResult:
        requirements = build_answer_structure_requirements(answer_contract, answer_depth_policy)
        candidate_maps = _candidate_list(ranked_candidates)
        claims = [_as_mapping(item) for item in (evidence_claims or [])]
        grouped_claims = _group_claims_by_shop(claims)
        style = answer_depth_policy.answer_style
        if style == "multi_shop_recommendation" and not candidate_maps and claims:
            synthetic_candidates: list[dict[str, Any]] = []
            seen_names: set[str] = set()
            for index, claim in enumerate(claims, start=1):
                metadata = _as_mapping(claim.get("metadata"))
                candidate_name = _clean_text(
                    metadata.get("shop_name")
                    or metadata.get("parent_shop_name")
                    or metadata.get("entity_shop_name")
                )
                if not candidate_name:
                    title = _clean_text(metadata.get("title") or claim.get("claim") or claim.get("support_text") or claim.get("text"))
                    if title:
                        candidate_name = title.split(" ", 1)[0].split("（", 1)[0].strip()
                if not candidate_name:
                    candidate_name = f"候选店铺{index}"
                if candidate_name in seen_names:
                    continue
                seen_names.add(candidate_name)
                synthetic_candidates.append(
                    {
                        "shop_id": claim.get("shop_id"),
                        "name": candidate_name,
                        "shop_name": candidate_name,
                        "structured_features": {},
                        "explainable_reasons": [
                            _clean_text(claim.get("support_text") or claim.get("claim") or claim.get("text"))
                        ],
                    }
                )
                if len(synthetic_candidates) >= 3:
                    break
            if synthetic_candidates:
                candidate_maps = synthetic_candidates

        if style == "single_shop_review":
            answer_text = _compose_single_shop_review(topic_name, candidate_maps[0] if candidate_maps else {}, grouped_claims, requirements)
        elif style == "facet_multi":
            answer_text = _compose_facet_multi(requirements, grouped_claims)
        elif style == "multi_shop_recommendation":
            answer_text = _compose_multi_shop_recommendation(topic_name, candidate_maps, grouped_claims, requirements)
        elif style == "coupon_only":
            answer_text = f"{topic_name or '这家店'}当前只回答券信息，暂时不扩展到环境或推荐。"
        elif style == "open_status_only":
            answer_text = f"{topic_name or '这家店'}当前只回答营业状态，暂时不扩展到环境或推荐。"
        elif style == "distance_only":
            answer_text = f"{topic_name or '这家店'}当前只回答距离信息，暂时不扩展到环境或推荐。"
        elif style == "clarification":
            answer_text = "我还需要你补充一点信息，才能继续回答。"
        else:
            answer_text = _compose_single_shop_review(topic_name, candidate_maps[0] if candidate_maps else {}, grouped_claims, requirements)

        sections = [line for line in answer_text.splitlines() if line.strip() and not line.lstrip().startswith("-")]
        bullet_count = _bullet_count(answer_text)
        sentence_count = _sentence_count(answer_text)
        return AnswerStructureResult(
            answer_text=answer_text.strip(),
            sections=[{"title": section} for section in sections],
            section_count=len(sections),
            bullet_count=bullet_count,
            duplicate_sentence_count=0,
            duplicate_ratio=0.0,
            recommendation_duplicate_shop_count=max(0, len(candidate_maps) - len({str(item.get("shop_id")) for item in candidate_maps if item.get("shop_id") not in (None, "")})),
        )
