from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from learning_agent_service.domain.utils import as_mapping as _as_mapping, clean_text as _clean_text

from .answer_depth_policy import AnswerDepthPolicy, build_answer_structure_requirements
from .clarification_strategy import ClarificationStrategy
from .scene_policy import ScenePolicy


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
        bullets.append("- 适合场景：适合先看证据再下决定。")
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
        ("到店建议", ["先看营业状态、券和排队，再决定是否现在去。"]),
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


def _compose_clarification(topic_name: str, user_need: Any | None = None) -> str:
    """结构化澄清模板"""
    if user_need is not None:
        missing_slots = getattr(user_need, "missing_slots", []) or []
        intent = str(getattr(user_need, "intent", "") or "")
        constraints = _as_mapping(getattr(user_need, "constraints", {}) or {})
        asked_slots = [
            str(slot or "").strip()
            for slot in (constraints.get("clarification_asked_slots") or [])
            if str(slot or "").strip()
        ]
        context_shop = _clean_text(
            constraints.get("current_shop")
            or constraints.get("selected_shop_name")
            or constraints.get("shop_name")
        )
        priority_slot = str(
            constraints.get("clarification_priority_slot")
            or ClarificationStrategy.get_clarification_priority(
                missing_slots=missing_slots,
                intent=intent,
                has_context_shop=bool(context_shop),
            )
            or ""
        ).strip()
        ordered_slots = [priority_slot] if priority_slot else []
        ordered_slots.extend(
            str(slot or "").strip()
            for slot in missing_slots
            if str(slot or "").strip() and str(slot or "").strip() not in ordered_slots
        )
        chosen_slot = ordered_slots[0] if ordered_slots else ""
        if chosen_slot and ClarificationStrategy.should_avoid_repeat_clarification(
            current_slot=chosen_slot,
            asked_slots=asked_slots,
            context_shop=context_shop or None,
        ):
            for slot in ordered_slots[1:]:
                if not ClarificationStrategy.should_avoid_repeat_clarification(
                    current_slot=slot,
                    asked_slots=asked_slots,
                    context_shop=context_shop or None,
                ):
                    chosen_slot = slot
                    break

        if chosen_slot == "shop_name":
            reason = str(getattr(user_need, "clarify_reason", "") or "")
            if "reference_resolution_failed" in reason:
                return "您问的是哪一家店呢？由于之前提到过多这家店或者我没有找到相关记录，请直接告诉我店名。"
            return "请问您想了解哪一家店的具体信息呢？可以告诉我店名或品牌。"

        if chosen_slot in {"location", "city"}:
            if intent == "recommendation":
                return "为了给您推荐更准确的店铺，请问您目前在哪个城市或者哪个商圈附近呢？"
            return "好的，请告诉我您所在的具体位置或城市，我来为您查询周边信息。"

        if chosen_slot == "category":
            return "请问您具体想找什么类型的店呢？比如火锅、烧烤、粤菜、还是咖啡甜点？"

    return "我还需要您补充一点信息，才能继续回答。请告诉我您具体想了解什么？"


def _dimension_signal(claims: list[str], positive_keywords: list[str], negative_keywords: list[str]) -> int:
    score = 0
    for claim in claims:
        if any(keyword in claim for keyword in positive_keywords):
            score += 1
        if any(keyword in claim for keyword in negative_keywords):
            score -= 1
    return score


def _comparison_scene_context(topic_name: str, user_need: Any | None) -> tuple[str | None, list[str]]:
    constraints = _as_mapping(getattr(user_need, "constraints", {}) or {})
    raw_query = _clean_text(getattr(user_need, "raw_query", "") or "")
    scene = _clean_text(constraints.get("scene_detected") or constraints.get("scene"))
    if not scene and raw_query:
        scene = ScenePolicy.detect_scene(raw_query)
    if not scene:
        scene = ScenePolicy.detect_scene(topic_name)
    preferred_facets = [str(item) for item in (constraints.get("scene_preferred_facets") or []) if str(item).strip()]
    if not preferred_facets and raw_query:
        preferred_facets = ScenePolicy.get_preferred_facets(raw_query)
    return scene or None, preferred_facets


def _comparison_priority_dimensions(scene: str | None, preferred_facets: list[str]) -> list[str]:
    scene_priority_map = {
        "约会": ["environment", "service", "score", "distance", "price"],
        "商务宴请": ["service", "environment", "score", "distance", "price"],
        "家庭聚餐": ["environment", "service", "price", "distance", "score"],
        "带父母": ["environment", "service", "distance", "price", "score"],
        "带小孩": ["environment", "service", "price", "distance", "score"],
        "朋友聚餐": ["taste", "environment", "price", "distance", "score"],
        "一个人": ["price", "distance", "taste", "score", "environment"],
        "深夜": ["distance", "environment", "taste", "score", "price"],
    }
    facet_dimension_map = {
        "environment": "environment",
        "atmosphere": "environment",
        "private_room": "environment",
        "family_friendly": "environment",
        "elderly_friendly": "environment",
        "child_friendly": "environment",
        "comfortable": "environment",
        "group_friendly": "environment",
        "service": "service",
        "taste": "taste",
        "portion_size": "price",
        "late_night": "distance",
        "hours": "distance",
        "parking": "distance",
    }
    ordered = list(scene_priority_map.get(scene or "", []))
    for facet in preferred_facets:
        dimension = facet_dimension_map.get(str(facet))
        if dimension and dimension not in ordered:
            ordered.append(dimension)
    for fallback in ("score", "price", "distance", "environment", "taste", "service"):
        if fallback not in ordered:
            ordered.append(fallback)
    return ordered


def _compose_comparison(topic_name: str, ranked_candidates: list[dict[str, Any]], grouped_claims: dict[int | None, list[str]], requirements: dict[str, Any], user_need: Any | None = None) -> str:
    """结构化对比答案模板"""
    if len(ranked_candidates) < 2:
        if ranked_candidates:
            return _compose_single_shop_review(topic_name, ranked_candidates[0], grouped_claims, requirements)
        return f"{topic_name or '对比结果'}：当前证据不足，无法进行有效对比。"

    shop_a = ranked_candidates[0]
    shop_b = ranked_candidates[1]
    name_a = _clean_text(shop_a.get("name") or shop_a.get("shop_name")) or "店铺A"
    name_b = _clean_text(shop_b.get("name") or shop_b.get("shop_name")) or "店铺B"

    structured_a = shop_a.get("structured_features") or {}
    structured_b = shop_b.get("structured_features") or {}

    claims_a = _unique_text(grouped_claims.get(shop_a.get("shop_id"), []))
    claims_b = _unique_text(grouped_claims.get(shop_b.get("shop_id"), []))
    scene, preferred_facets = _comparison_scene_context(topic_name, user_need)
    priority_dimensions = _comparison_priority_dimensions(scene, preferred_facets)

    dimensions: list[tuple[str, str, str]] = []

    if structured_a.get("score") not in (None, "") or structured_b.get("score") not in (None, ""):
        score_a = str(structured_a.get("score") or "暂无")
        score_b = str(structured_b.get("score") or "暂无")
        dimensions.append(("综合评分", f"{name_a}约{score_a}", f"{name_b}约{score_b}"))

    if structured_a.get("avg_price") not in (None, "") or structured_b.get("avg_price") not in (None, ""):
        price_a = str(structured_a.get("avg_price") or "暂无")
        price_b = str(structured_b.get("avg_price") or "暂无")
        dimensions.append(("人均消费", f"{name_a}约{price_a}元", f"{name_b}约{price_b}元"))

    if structured_a.get("distance_km") not in (None, "") or structured_b.get("distance_km") not in (None, ""):
        dist_a = str(structured_a.get("distance_km") or "暂无")
        dist_b = str(structured_b.get("distance_km") or "暂无")
        dimensions.append(("距离", f"{name_a}约{dist_a}公里", f"{name_b}约{dist_b}公里"))

    env_claims_a = [c for c in claims_a if any(kw in c for kw in ["环境", "装修", "氛围", "安静", "吵闹"])]
    env_claims_b = [c for c in claims_b if any(kw in c for kw in ["环境", "装修", "氛围", "安静", "吵闹"])]
    if env_claims_a or env_claims_b:
        env_a = env_claims_a[0] if env_claims_a else "暂无明确评价"
        env_b = env_claims_b[0] if env_claims_b else "暂无明确评价"
        dimensions.append(("环境氛围", f"{name_a}：{env_a}", f"{name_b}：{env_b}"))

    taste_claims_a = [c for c in claims_a if any(kw in c for kw in ["口味", "好吃", "味道", "口感"])]
    taste_claims_b = [c for c in claims_b if any(kw in c for kw in ["口味", "好吃", "味道", "口感"])]
    if taste_claims_a or taste_claims_b:
        taste_a = taste_claims_a[0] if taste_claims_a else "暂无明确评价"
        taste_b = taste_claims_b[0] if taste_claims_b else "暂无明确评价"
        dimensions.append(("口味口感", f"{name_a}：{taste_a}", f"{name_b}：{taste_b}"))

    service_claims_a = [c for c in claims_a if any(kw in c for kw in ["服务", "态度", "热情", "周到"])]
    service_claims_b = [c for c in claims_b if any(kw in c for kw in ["服务", "态度", "热情", "周到"])]
    if service_claims_a or service_claims_b:
        service_a = service_claims_a[0] if service_claims_a else "暂无明确评价"
        service_b = service_claims_b[0] if service_claims_b else "暂无明确评价"
        dimensions.append(("服务态度", f"{name_a}：{service_a}", f"{name_b}：{service_b}"))

    if not any(d[0] in {"环境氛围", "口味口感", "服务态度"} for d in dimensions) and (claims_a or claims_b):
        claim_a = claims_a[0] if claims_a else "暂无明确评价"
        claim_b = claims_b[0] if claims_b else "暂无明确评价"
        dimensions.append(("用户评价", f"{name_a}：{claim_a}", f"{name_b}：{claim_b}"))

    if not dimensions:
        dimensions.append(("综合对比", f"{name_a}和{name_b}各有特点", "建议结合距离、预算和场景综合考虑"))

    lines = [f"{topic_name or '对比结果'}：我从几个维度帮你对比一下这两家店。"]
    if scene:
        lines.append(f"如果你更看重{scene}场景，我会优先关注{'、'.join(priority_dimensions[:3])}这几个维度。")

    dimension_key_map = {
        "综合评分": "score",
        "人均消费": "price",
        "距离": "distance",
        "环境氛围": "environment",
        "口味口感": "taste",
        "服务态度": "service",
        "用户评价": "taste",
        "综合对比": "score",
    }
    dimensions = sorted(
        dimensions,
        key=lambda item: priority_dimensions.index(dimension_key_map.get(item[0], "score"))
        if dimension_key_map.get(item[0], "score") in priority_dimensions
        else len(priority_dimensions),
    )

    lines.append("\n对比维度")
    for dim_name, val_a, val_b in dimensions:
        lines.append(f"- {dim_name}：")
        lines.append(f"  - {val_a}")
        lines.append(f"  - {val_b}")

    env_signal_a = _dimension_signal(claims_a, ["环境", "装修", "氛围", "安静", "适合约会", "包间"], ["吵闹", "太吵", "环境差", "拥挤"])
    env_signal_b = _dimension_signal(claims_b, ["环境", "装修", "氛围", "安静", "适合约会", "包间"], ["吵闹", "太吵", "环境差", "拥挤"])
    taste_signal_a = _dimension_signal(claims_a, ["口味", "好吃", "味道", "口感", "肉质"], ["难吃", "一般", "踩雷"])
    taste_signal_b = _dimension_signal(claims_b, ["口味", "好吃", "味道", "口感", "肉质"], ["难吃", "一般", "踩雷"])
    service_signal_a = _dimension_signal(claims_a, ["服务", "态度", "热情", "周到"], ["服务差", "冷淡", "爱答不理"])
    service_signal_b = _dimension_signal(claims_b, ["服务", "态度", "热情", "周到"], ["服务差", "冷淡", "爱答不理"])

    weighted_scores = {name_a: 0.0, name_b: 0.0}
    dimension_advantages: list[tuple[str, str]] = []

    def _record_advantage(winner: str, dimension_key: str, base_weight: float) -> None:
        weight = base_weight
        if dimension_key in priority_dimensions[:2]:
            weight *= 1.6
        elif dimension_key in priority_dimensions[:4]:
            weight *= 1.2
        weighted_scores[winner] += weight
        dimension_advantages.append((winner, dimension_key))

    try:
        score_a_val = float(structured_a["score"]) if structured_a.get("score") not in (None, "") else None
    except (ValueError, TypeError):
        score_a_val = None
    try:
        score_b_val = float(structured_b["score"]) if structured_b.get("score") not in (None, "") else None
    except (ValueError, TypeError):
        score_b_val = None
    if score_a_val is not None and score_b_val is not None and score_a_val != score_b_val:
        _record_advantage(name_a if score_a_val > score_b_val else name_b, "score", 2.0)

    try:
        price_a_val = float(structured_a["avg_price"]) if structured_a.get("avg_price") not in (None, "") else None
    except (ValueError, TypeError):
        price_a_val = None
    try:
        price_b_val = float(structured_b["avg_price"]) if structured_b.get("avg_price") not in (None, "") else None
    except (ValueError, TypeError):
        price_b_val = None
    if price_a_val is not None and price_b_val is not None and price_a_val != price_b_val:
        _record_advantage(name_a if price_a_val < price_b_val else name_b, "price", 1.0)

    try:
        dist_a_val = float(structured_a["distance_km"]) if structured_a.get("distance_km") not in (None, "") else None
    except (ValueError, TypeError):
        dist_a_val = None
    try:
        dist_b_val = float(structured_b["distance_km"]) if structured_b.get("distance_km") not in (None, "") else None
    except (ValueError, TypeError):
        dist_b_val = None
    if dist_a_val is not None and dist_b_val is not None and dist_a_val != dist_b_val:
        _record_advantage(name_a if dist_a_val < dist_b_val else name_b, "distance", 1.0)

    if env_signal_a != env_signal_b:
        _record_advantage(name_a if env_signal_a > env_signal_b else name_b, "environment", 2.0)
    if taste_signal_a != taste_signal_b:
        _record_advantage(name_a if taste_signal_a > taste_signal_b else name_b, "taste", 1.5)
    if service_signal_a != service_signal_b:
        _record_advantage(name_a if service_signal_a > service_signal_b else name_b, "service", 1.5)

    winner = name_a if weighted_scores[name_a] >= weighted_scores[name_b] else name_b
    loser = name_b if winner == name_a else name_a
    top_reasons = [
        {"environment": "环境氛围", "taste": "口味口感", "service": "服务体验", "price": "预算友好度", "distance": "距离便利度", "score": "综合评分"}.get(dimension, dimension)
        for shop_name, dimension in dimension_advantages
        if shop_name == winner
    ]
    top_reasons = _unique_text(top_reasons)[:3]

    lines.append("\n综合建议")
    if scene and weighted_scores[winner] != weighted_scores[loser]:
        lines.append(f"- 如果你主要看重{scene}场景，我会更偏向{winner}。")
        if top_reasons:
            lines.append(f"- 主要原因是它在{'、'.join(top_reasons)}上更贴近这个场景。")
        lines.append(f"- 如果你更在意另一侧的预算或距离，也可以再看看{loser}。")
    elif weighted_scores[name_a] > weighted_scores[name_b]:
        lines.append(f"- 综合看下来，{name_a}略占优势。")
    elif weighted_scores[name_b] > weighted_scores[name_a]:
        lines.append(f"- 综合看下来，{name_b}略占优势。")
    else:
        lines.append("- 两家各有优势，建议结合距离、预算和场景再做最后选择。")

    return "\n".join(lines)


def _compose_multi_shop_recommendation(topic_name: str, ranked_candidates: list[dict[str, Any]], grouped_claims: dict[int | None, list[str]], requirements: dict[str, Any]) -> str:
    lines = [f"{topic_name or '推荐结果'}：我先给你列出当前更值得看的几家。"]
    unique_candidates: list[dict[str, Any]] = []
    seen_shop_ids: set[int] = set()
    for candidate in ranked_candidates:
        shop_id = candidate.get("shop_id")
        try:
            shop_id_int = int(shop_id) if shop_id is not None else None
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
            shop_id_int = int(shop_id) if shop_id is not None else None
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
        elif style == "comparison":
            answer_text = _compose_comparison(topic_name, candidate_maps, grouped_claims, requirements, user_need)
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
            answer_text = _compose_clarification(topic_name, user_need)
        else:
            answer_text = _compose_single_shop_review(topic_name, candidate_maps[0] if candidate_maps else {}, grouped_claims, requirements)

        sections = [line for line in answer_text.splitlines() if line.strip() and not line.lstrip().startswith("-")]
        bullet_count = _bullet_count(answer_text)
        _sentence_count(answer_text)
        return AnswerStructureResult(
            answer_text=answer_text.strip(),
            sections=[{"title": section} for section in sections],
            section_count=len(sections),
            bullet_count=bullet_count,
            duplicate_sentence_count=0,
            duplicate_ratio=0.0,
            recommendation_duplicate_shop_count=max(0, len(candidate_maps) - len({str(item.get("shop_id")) for item in candidate_maps if item.get("shop_id") not in (None, "")})),
        )
