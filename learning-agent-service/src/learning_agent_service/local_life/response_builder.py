from __future__ import annotations

from typing import Any, Mapping, Sequence

from .answer_sanitizer import sanitize_local_life_output
from .evidence_scope_guard import EvidenceScopeGuard
from .answer_planner import EvidencePack, GroundedVerificationResult, LocalLifeAnswerPlan, parse_answer_plan_payload
from .schemas import (
    CardAction,
    EvidenceClaim,
    LocalLifeResponseBundle,
    LocalLifeSlots,
    RankedCandidate,
    ShopCard,
    SuggestedReply,
    VoucherCard,
)


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return dict(dumped)
    return {}


def _as_plan(value: Any) -> LocalLifeAnswerPlan | None:
    if value is None:
        return None
    if isinstance(value, LocalLifeAnswerPlan):
        return value
    if isinstance(value, Mapping):
        return parse_answer_plan_payload(value)
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return parse_answer_plan_payload(dumped)
    return None


def _as_verification(value: Any) -> GroundedVerificationResult | None:
    if value is None:
        return None
    if isinstance(value, GroundedVerificationResult):
        return value
    if isinstance(value, Mapping):
        try:
            return GroundedVerificationResult.model_validate(value)
        except Exception:
            return None
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        if isinstance(dumped, Mapping):
            try:
                return GroundedVerificationResult.model_validate(dumped)
            except Exception:
                return None
    return None


def _as_evidence_pack(value: Any) -> EvidencePack | None:
    if value is None:
        return None
    if isinstance(value, EvidencePack):
        return value
    if isinstance(value, Mapping):
        try:
            return EvidencePack.model_validate(value)
        except Exception:
            return None
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        if isinstance(dumped, Mapping):
            try:
                return EvidencePack.model_validate(dumped)
            except Exception:
                return None
    return None


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _merge_unique_text(*values: Any) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value is None:
            continue
        items = value if isinstance(value, (list, tuple, set)) else (value,)
        for item in items:
            text = _clean_text(item)
            if text and text not in seen:
                seen.add(text)
                merged.append(text)
    return merged


def _normalize_suggested_replies(values: Any) -> list[dict[str, Any]]:
    replies: list[dict[str, Any]] = []
    if not isinstance(values, (list, tuple, set)):
        return replies
    seen: set[tuple[str, str]] = set()
    for item in values:
        if isinstance(item, Mapping):
            label = _clean_text(item.get("label") or item.get("prompt") or item.get("value"))
            prompt = _clean_text(item.get("prompt") or item.get("value") or label)
        else:
            label = _clean_text(item)
            prompt = label
        if not label or not prompt:
            continue
        key = (label, prompt)
        if key in seen:
            continue
        seen.add(key)
        replies.append(SuggestedReply(label=label, prompt=prompt).model_dump(mode="json"))
    return replies


def _format_price(value: Any) -> str:
    if value is None:
        return "未知"
    try:
        return f"{int(round(float(value)))}元"
    except Exception:
        return str(value)


def _format_distance(value: Any) -> str:
    if value is None:
        return "未知距离"
    try:
        distance = float(value)
        return f"{distance:.1f}km"
    except Exception:
        return str(value)


def _top_badges(candidate: RankedCandidate) -> list[str]:
    badges: list[str] = []
    if candidate.structured_features.get("parking"):
        badges.append("可停车")
    if candidate.structured_features.get("family_friendly"):
        badges.append("适合家庭")
    if candidate.structured_features.get("elder_friendly"):
        badges.append("长辈友好")
    if candidate.evidence_features.get("quiet", 0.0) >= 0.6:
        badges.append("安静")
    if candidate.vouchers:
        badges.append("有券")
    return badges[:4]


def _candidate_reason(candidate: RankedCandidate) -> str:
    if candidate.explainable_reasons:
        return "，".join(candidate.explainable_reasons[:3])
    if candidate.matched_requirements:
        return "，".join(candidate.matched_requirements[:3])
    return "符合你的筛选条件"


def _summarize_environment_claims(evidence_claims: Sequence[EvidenceClaim]) -> str:
    claims = list(evidence_claims[:4])
    if not claims:
        return "评价证据有限，暂时没有足够信息判断环境。"

    joined_text = " ".join(
        " ".join(
            part
            for part in [
                _clean_text(getattr(claim, "claim", None)),
                _clean_text(getattr(claim, "support_text", None)),
                _clean_text(getattr(claim, "source_type", None)),
            ]
            if part
        )
        for claim in claims
    ).strip()
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
    for claim in claims[:2]:
        claim_text = _clean_text(getattr(claim, "claim", None))
        support_text = _clean_text(getattr(claim, "support_text", None))
        if claim_text and support_text and claim_text not in support_text:
            text = f"{claim_text}：{support_text}"
        else:
            text = support_text or claim_text
        if not text:
            continue
        if len(text) > 96:
            text = text[:93].rstrip() + "..."
        snippets.append(text)
    if not snippets:
        return "评价证据有限，暂时没有足够信息判断环境。"
    if len(snippets) == 1:
        return f"评价里能看到：{snippets[0]}。"
    return f"评价里能看到：{snippets[0]}；{snippets[1]}。"


def _summarize_coupon_claims(evidence_claims: Sequence[EvidenceClaim]) -> str | None:
    coupon_claims: list[str] = []
    for claim in evidence_claims[:6]:
        source_type = str(getattr(claim, "source_type", "") or "").lower()
        claim_text = _clean_text(getattr(claim, "claim", None))
        support_text = _clean_text(getattr(claim, "support_text", None))
        if source_type in {"voucher_rule", "coupon", "package_description"} or any(
            token in f"{claim_text or ''} {support_text or ''}" for token in ("券", "优惠", "套餐", "团购")
        ):
            text = claim_text or support_text
            if text:
                coupon_claims.append(text)
    if not coupon_claims:
        return None
    deduped: list[str] = []
    seen: set[str] = set()
    for text in coupon_claims:
        if text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return "、".join(deduped[:3])


def _build_coupon_environment_answer(
    *,
    current_topic: str | None,
    ranked_candidates: Sequence[RankedCandidate],
    evidence_claims: Sequence[EvidenceClaim],
    user_need: Any | None = None,
) -> str:
    _raw_shop_name = _clean_text(current_topic) or (ranked_candidates[0].name if ranked_candidates else None) or "这家店"
    # 防止 "shop:5" 等内部 ID 泄露到最终答案中
    import re as _re
    shop_name = _raw_shop_name if not _re.match(r"^shop:\d+$", _raw_shop_name) else "这家店"
    sections: list[str] = []

    req_facet_names = []
    if user_need is not None:
        req_facet_names = [f.name for f in getattr(user_need, "required_facets", []) or []]

    # Voucher Section
    if user_need is None or "coupon" in req_facet_names:
        voucher_summaries: list[str] = []
        if ranked_candidates:
            for voucher in ranked_candidates[0].vouchers[:3]:
                title = _clean_text(voucher.get("title") or voucher.get("name"))
                pay_value = voucher.get("pay_value") or voucher.get("payValue")
                actual_value = voucher.get("actual_value") or voucher.get("actualValue")
                if title and pay_value not in (None, "") and actual_value not in (None, ""):
                    voucher_summaries.append(f"{title}（{_format_price(pay_value)} 代 {_format_price(actual_value)}）")
                elif title:
                    voucher_summaries.append(title)
        if voucher_summaries:
            sections.append(f"券信息：{shop_name} 当前能看到这些券：{'、'.join(voucher_summaries)}。")
        else:
            coupon_claims = _summarize_coupon_claims(evidence_claims)
            if coupon_claims:
                sections.append(
                    f"券信息：{shop_name} 知识库里有优惠或套餐线索：{coupon_claims}，但实时接口暂未查到可用券，建议以实时接口和券规则为准。"
                )
            else:
                sections.append(f"券信息：{shop_name} 暂时没看到可用券。")

    # Open Status Section
    if user_need is not None and "open_status" in req_facet_names:
        open_hours = None
        if ranked_candidates:
            open_hours = ranked_candidates[0].structured_features.get("open_hours") or ranked_candidates[0].structured_features.get("openHours")
        if open_hours:
            sections.append(f"营业状态：{shop_name} 的营业时间是 {open_hours}，当前处于营业中。")
        else:
            sections.append(f"营业状态：{shop_name} 当前正常营业中。")

    # Environment/Scene Section
    if user_need is None or "scene_fit" in req_facet_names or "category" in req_facet_names:
        sections.append(f"环境评价：{_summarize_environment_claims(evidence_claims)}")

    if not sections:
        sections.append(f"环境评价：{_summarize_environment_claims(evidence_claims)}")

    return "\n".join(sections)


def _build_facet_driven_answer(
    *,
    current_topic: str | None,
    ranked_candidates: Sequence[RankedCandidate],
    evidence_claims: Sequence[EvidenceClaim],
    user_need: Any | None = None,
) -> str:
    req_facet_names = [f.name for f in getattr(user_need, "required_facets", []) or []] if user_need is not None else []
    if not req_facet_names:
        return _build_coupon_environment_answer(
            current_topic=current_topic,
            ranked_candidates=ranked_candidates,
            evidence_claims=evidence_claims,
            user_need=user_need,
        )

    top_candidate = ranked_candidates[0] if ranked_candidates else None
    topic_name = _clean_text(current_topic) or (top_candidate.name if top_candidate else "这家店")
    sections: list[str] = []

    if any(name in req_facet_names for name in ("recommendation_reason", "recommendation", "shop_detail")) and top_candidate is not None:
        sections.append(
            f"推荐结果：优先看 {topic_name}。{_candidate_reason(top_candidate)}，"
            f"距你约{_format_distance(top_candidate.structured_features.get('distance_km'))}，"
            f"人均约{_format_price(top_candidate.structured_features.get('avg_price'))}，"
            f"评分{float(top_candidate.structured_features.get('score') or 0.0):.1f}。"
        )

    if "scene_fit" in req_facet_names:
        sections.append(f"场景适配：{_summarize_environment_claims(evidence_claims)}")

    if "coupon" in req_facet_names:
        coupon_text = _summarize_coupon_claims(evidence_claims)
        if top_candidate is not None and top_candidate.vouchers:
            voucher = top_candidate.vouchers[0]
            title = _clean_text(voucher.get("title") or voucher.get("name")) or "优惠券"
            pay_value = voucher.get("pay_value") or voucher.get("payValue")
            actual_value = voucher.get("actual_value") or voucher.get("actualValue")
            if pay_value not in (None, "") and actual_value not in (None, ""):
                sections.append(f"券信息：{title}（{_format_price(pay_value)} 代 {_format_price(actual_value)}）。")
            else:
                sections.append(f"券信息：{title}。")
        elif coupon_text:
            sections.append(f"券信息：{coupon_text}，但实时接口暂未查到可用券，建议以实时接口和券规则为准。")
        else:
            sections.append(f"券信息：{topic_name} 暂时没看到可用券。")

    if "open_status" in req_facet_names:
        if top_candidate is not None:
            open_hours = top_candidate.structured_features.get("open_hours") or top_candidate.structured_features.get("openHours")
            if open_hours:
                sections.append(f"营业状态：{topic_name} 的营业时间是 {open_hours}，当前处于营业中。")
            else:
                sections.append(f"营业状态：{topic_name} 当前正常营业中。")
        else:
            sections.append(f"营业状态：{topic_name} 当前营业情况暂不明确。")

    if "distance_eta" in req_facet_names and top_candidate is not None:
        sections.append(
            f"距离信息：{topic_name} 距离你约{_format_distance(top_candidate.structured_features.get('distance_km'))}。"
        )

    if "price" in req_facet_names and top_candidate is not None:
        sections.append(
            f"价格信息：{topic_name} 人均约{_format_price(top_candidate.structured_features.get('avg_price'))}。"
        )

    if not sections and top_candidate is not None:
        sections.append(
            f"推荐结果：{topic_name}，距你约{_format_distance(top_candidate.structured_features.get('distance_km'))}，"
            f"人均约{_format_price(top_candidate.structured_features.get('avg_price'))}。"
        )

    return "\n".join(sections) if sections else _build_coupon_environment_answer(
        current_topic=current_topic,
        ranked_candidates=ranked_candidates,
        evidence_claims=evidence_claims,
        user_need=user_need,
    )


def _build_shop_card(candidate: RankedCandidate) -> dict[str, Any]:
    subtitle_parts = [
        _format_distance(candidate.structured_features.get("distance_km")),
        f"人均{_format_price(candidate.structured_features.get('avg_price'))}",
    ]
    score = candidate.structured_features.get("score")
    if score is not None:
        subtitle_parts.append(f"评分{float(score):.1f}")
    actions = [
        CardAction(type="open_shop", label="查看详情", payload={"shop_id": candidate.shop_id}).model_dump(mode="json"),
        CardAction(type="navigation", label="导航", payload={"shop_id": candidate.shop_id}).model_dump(mode="json"),
    ]
    if candidate.vouchers:
        actions.append(
            CardAction(type="claim_coupon", label="领券", payload={"shop_id": candidate.shop_id}).model_dump(mode="json")
        )
    actions.append(CardAction(type="booking", label="订座", payload={"shop_id": candidate.shop_id}).model_dump(mode="json"))
    return ShopCard(
        shop_id=candidate.shop_id,
        title=candidate.name,
        subtitle=" · ".join(subtitle_parts),
        badges=_top_badges(candidate),
        reason=_candidate_reason(candidate),
        actions=[CardAction.model_validate(action) for action in actions],
    ).model_dump(mode="json")


def _build_voucher_card(candidate: RankedCandidate, voucher: Mapping[str, Any]) -> dict[str, Any]:
    voucher_id = int(voucher.get("id") or 0)
    title = str(voucher.get("title") or "优惠券")
    subtitle = str(voucher.get("sub_title") or voucher.get("subTitle") or "")
    return VoucherCard(
        voucher_id=voucher_id,
        shop_id=candidate.shop_id,
        title=title,
        subtitle=subtitle or None,
        pay_value=voucher.get("pay_value") or voucher.get("payValue"),
        actual_value=voucher.get("actual_value") or voucher.get("actualValue"),
        stock=voucher.get("stock"),
        rules=voucher.get("rules"),
        actions=[
            CardAction(type="claim_coupon", label="立即领券", payload={"voucher_id": voucher_id, "shop_id": candidate.shop_id}).model_dump(mode="json")
        ],
    ).model_dump(mode="json")


def _build_next_steps(
    *,
    mode: str,
    ranked_candidates: Sequence[RankedCandidate],
    approval_required: bool = False,
    transaction_draft: Mapping[str, Any] | None = None,
) -> list[str]:
    transaction_draft = dict(transaction_draft or {})
    action = str(transaction_draft.get("action") or mode or "").strip().lower()
    action_label = {
        "booking": "订座",
        "order": "下单",
        "cancel": "取消",
        "refund": "退款",
    }.get(action, "继续执行")

    if approval_required:
        confirm_label = "确认继续" if action_label == "继续执行" else f"确认继续{action_label}"
        return _merge_unique_text(
            [
                confirm_label,
                "换一家",
                "先不执行",
            ]
        )[:5]

    if ranked_candidates:
        next_steps = ["查看第一家详情"]
        if len(ranked_candidates) >= 2:
            next_steps.append("对比前两家")
        if any(candidate.vouchers for candidate in ranked_candidates[:3]):
            next_steps.append("先领券再去")
        if action in {"booking", "order"} or transaction_draft:
            next_steps.append(f"继续{action_label}")
        elif mode == "coupon":
            next_steps.append("查看更多优惠")
        next_steps.append("换一批同类型店")
        return _merge_unique_text(next_steps)[:5]

    fallback_steps = {
        "detail": ["看优惠券", "推荐同类型店", "对比附近两家店"],
        "compare": ["推荐更便宜的", "推荐评分更高的", "看优惠券"],
        "voucher": ["查看同店更多优惠", "推荐附近同类店", "对比两家店"],
        "booking": ["继续订座", "换一家更方便的", "补充人数或时间"],
        "order": ["继续下单", "查看券后价格", "换一家更划算的"],
    }
    if mode in fallback_steps:
        return _merge_unique_text(fallback_steps[mode])[:5]
    return _merge_unique_text(["补充预算", "补充距离", "换个品类"])[:5]


def _build_task_chain(
    *,
    mode: str,
    ranked_candidates: Sequence[RankedCandidate],
    approval_required: bool = False,
    transaction_draft: Mapping[str, Any] | None = None,
    next_steps: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    transaction_draft = dict(transaction_draft or {})
    next_steps = list(next_steps or [])
    action = str(transaction_draft.get("action") or mode or "").strip().lower()
    action_label = {
        "booking": "订座",
        "order": "下单",
        "cancel": "取消",
        "refund": "退款",
    }.get(action, "继续执行")

    chain: list[dict[str, Any]] = []

    def add(step: str, label: str, status: str, actions: Sequence[str] | None = None) -> None:
        entry = {"step": step, "label": label, "status": status}
        normalized_actions = _merge_unique_text(actions or [])
        if normalized_actions:
            entry["actions"] = normalized_actions
        chain.append(entry)

    if ranked_candidates:
        add("search", "已完成候选店搜索", "done")
        if len(ranked_candidates) >= 2:
            add("compare", "可以继续对比前两家", "available", ["对比前两家"])
        add("recommend", "已经给出优先推荐", "done")
        if any(candidate.vouchers for candidate in ranked_candidates[:3]):
            add("coupon", "可以先领券再去", "available", ["看优惠券", "立即领券"])
    else:
        add("search", "我先按你的条件帮你找店", "running")
        add("recommend", "可以继续换条件再筛", "available", ["换一批同类型店", "补充预算"])

    if action in {"booking", "order"} or transaction_draft:
        add(
            "reserve_order",
            f"可以继续{action_label}",
            "blocked" if approval_required else "available",
            [action_label, "查看草案"] if approval_required else [action_label, "订座", "下单"],
        )

    if approval_required:
        add("confirm", "需要你确认后再执行", "required", ["确认继续", "先不执行"])

    add("final", "结果已经整理完成", "done", list(next_steps[:3]))
    return chain


def _build_suggested_replies(
    slots: LocalLifeSlots,
    ranked_candidates: Sequence[RankedCandidate],
    *,
    approval_required: bool = False,
    model_hint: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    suggestions = _normalize_suggested_replies(_as_mapping(model_hint).get("suggested_replies"))
    if approval_required:
        suggestions.extend(
            [
                SuggestedReply(label="确认继续", prompt="确认继续").model_dump(mode="json"),
                SuggestedReply(label="换一家", prompt="换一家").model_dump(mode="json"),
                SuggestedReply(label="先不执行", prompt="先不执行").model_dump(mode="json"),
            ]
        )
        return suggestions[:3]
    if ranked_candidates:
        suggestions.extend(
            [
                SuggestedReply(label="只看今晚可订的", prompt="只看今晚可订的").model_dump(mode="json"),
                SuggestedReply(label="换成人均100以内", prompt="换成人均100以内").model_dump(mode="json"),
                SuggestedReply(label="找更安静的", prompt="找更安静的").model_dump(mode="json"),
                SuggestedReply(label="看看有包间的", prompt="看看有包间的").model_dump(mode="json"),
            ]
        )
        if len(ranked_candidates) >= 2:
            suggestions.append(SuggestedReply(label="对比前两家", prompt="对比前两家").model_dump(mode="json"))
    else:
        suggestions.extend(
            [
                SuggestedReply(label="家常菜", prompt="推荐家常菜").model_dump(mode="json"),
                SuggestedReply(label="火锅", prompt="推荐火锅").model_dump(mode="json"),
                SuggestedReply(label="粤菜", prompt="推荐粤菜").model_dump(mode="json"),
            ]
        )
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in suggestions:
        label = _clean_text(item.get("label")) if isinstance(item, Mapping) else None
        prompt = _clean_text(item.get("prompt")) if isinstance(item, Mapping) else None
        if not label or not prompt:
            continue
        key = (label, prompt)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(dict(item))
    return deduped[:5]


def _build_citations(evidence_claims: Sequence[EvidenceClaim]) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    for claim in evidence_claims[:6]:
        citations.append(
            {
                "chunk_id": claim.chunk_id,
                "document_id": str(claim.shop_id) if claim.shop_id is not None else None,
                "source_type": claim.source_type,
                "score": claim.confidence,
                "title": claim.claim,
                "locator": claim.metadata.get("shop_name"),
            }
        )
    return citations


def _filter_citations_by_shop_ids(
    citations: Sequence[Mapping[str, Any]],
    allowed_shop_ids: set[int],
) -> list[dict[str, Any]]:
    if not allowed_shop_ids:
        return [dict(item) for item in citations]
    filtered: list[dict[str, Any]] = []
    for item in citations:
        item_map = _as_mapping(item)
        raw_id = item_map.get("document_id") or item_map.get("shop_id")
        try:
            shop_id = int(raw_id)
        except Exception:
            shop_id = None
        if shop_id is None or shop_id in allowed_shop_ids:
            filtered.append(dict(item_map))
    return filtered


def _build_citations_from_answer_plan(
    *,
    answer_plan: LocalLifeAnswerPlan,
    evidence_pack: EvidencePack | None,
    evidence_claims: Sequence[EvidenceClaim],
) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    evidence_index: dict[str, dict[str, Any]] = {}
    if evidence_pack is not None:
        for item in evidence_pack.items:
            evidence_index[item.evidence_id] = item.model_dump(mode="json")
            evidence_index[item.chunk_id] = item.model_dump(mode="json")
    for claim in evidence_claims:
        evidence_index.setdefault(claim.chunk_id, claim.model_dump(mode="json"))
    for evidence_id in answer_plan.evidence_used[:6]:
        item = evidence_index.get(evidence_id)
        if not item:
            continue
        citations.append(
            {
                "chunk_id": item.get("chunk_id") or item.get("evidence_id"),
                "document_id": str(item.get("shop_id")) if item.get("shop_id") is not None else None,
                "source_type": item.get("source_type"),
                "score": item.get("confidence"),
                "title": item.get("claim"),
                "locator": item.get("metadata", {}).get("shop_name") if isinstance(item.get("metadata"), Mapping) else None,
            }
        )
    return citations


def _reply_items_from_strings(values: Sequence[str]) -> list[dict[str, Any]]:
    replies: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        text = _clean_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        replies.append(SuggestedReply(label=text, prompt=text).model_dump(mode="json"))
    return replies


def _confidence_to_score(confidence: str | None) -> float:
    mapping = {"high": 0.92, "medium": 0.74, "low": 0.5}
    return mapping.get(str(confidence or "").strip().lower(), 0.66)


def build_response_bundle(
    *,
    raw_query: str,
    slots: LocalLifeSlots,
    ranked_candidates: Sequence[RankedCandidate],
    evidence_claims: Sequence[EvidenceClaim],
    answer_plan: Mapping[str, Any] | LocalLifeAnswerPlan | None = None,
    verification_result: Mapping[str, Any] | GroundedVerificationResult | None = None,
    evidence_pack: Mapping[str, Any] | EvidencePack | None = None,
    page: str | None,
    current_topic: str | None,
    selected_shop_id: int | None,
    current_shop: str | None = None,
    source: str = "local-life-agent",
    fallback: bool = False,
    mode: str = "recommend",
    client_context: Mapping[str, Any] | None = None,
    approval_required: bool = False,
    approval_request: Mapping[str, Any] | None = None,
    transaction_draft: Mapping[str, Any] | None = None,
    safety_result: Mapping[str, Any] | None = None,
    route_decision: str | None = None,
    route_reason: str | None = None,
    current_stage: str | None = None,
    stage_status: str | None = None,
    stage_timeline: Sequence[Mapping[str, Any]] | None = None,
    model_hint: Mapping[str, Any] | None = None,
    source_mode: str | None = None,
    degraded_reason: str | None = None,
    knowledge_freshness: Mapping[str, Any] | None = None,
    user_need: Any | None = None,
) -> LocalLifeResponseBundle:
    client_context = dict(client_context or {})
    approval_request = dict(approval_request or {})
    transaction_draft = dict(transaction_draft or {})
    safety_result = dict(safety_result or {})
    model_hint = _as_mapping(model_hint)
    current_shop = _clean_text(current_shop) or _clean_text(model_hint.get("current_shop"))
    source_mode = source_mode or _clean_text(model_hint.get("source_mode"))
    degraded_reason = degraded_reason or _clean_text(model_hint.get("degraded_reason"))
    route_reason = route_reason or _clean_text(model_hint.get("route_reason"))
    knowledge_freshness = dict(knowledge_freshness or _as_mapping(model_hint.get("knowledge_freshness")))
    ranked_candidates = list(ranked_candidates)
    answer_plan_model = _as_plan(answer_plan) or _as_plan(model_hint.get("answer_plan"))
    verification_model = _as_verification(verification_result) or _as_verification(model_hint.get("verification_result"))
    evidence_pack_model = _as_evidence_pack(evidence_pack) or _as_evidence_pack(model_hint.get("evidence_pack"))
    current_topic = current_topic or slots.category or slots.scene or "本地生活推荐"
    model_answer = _clean_text(model_hint.get("answer_text"))
    plan_usable = bool(answer_plan_model) and bool(verification_model is None or verification_model.passed)
    allowed_shop_ids = EvidenceScopeGuard.allowed_shop_ids(ranked_candidates=ranked_candidates, evidence_pack=evidence_pack_model)
    if allowed_shop_ids:
        ranked_candidates = [
            candidate
            for candidate in ranked_candidates
            if int(candidate.shop_id) in allowed_shop_ids
        ]
        evidence_claims = [
            claim
            for claim in evidence_claims
            if getattr(claim, "shop_id", None) in allowed_shop_ids
        ]
    if plan_usable and answer_plan_model is not None:
        answer_text = answer_plan_model.answer_text or answer_plan_model.recommendation_summary or model_answer or ""
        if approval_required and answer_plan_model.decision_type in {"booking", "order"}:
            action_label = "订座" if answer_plan_model.decision_type == "booking" else "下单"
            answer_text = (
                f"我已经为你整理好{action_label}草案，确认后我再继续执行，避免直接误操作。"
                + (f"\n\n{answer_text}" if answer_text else "")
            )
        elif approval_required:
            answer_text = (
                "当前这个请求需要你确认后我再继续执行，先给你整理成草案，避免直接误操作。"
                + (f"\n\n{answer_text}" if answer_text else "")
            )
    elif approval_required and transaction_draft:
        action = transaction_draft.get("action") or mode
        action_label = {
            "booking": "订座",
            "order": "下单",
            "cancel": "取消",
            "refund": "退款",
        }.get(str(action), str(action))
        shop_name = transaction_draft.get("shop_name") or current_topic
        answer_text = (
            f"我已经为你整理好{action_label}草案：{shop_name or '目标商户'}。"
            "确认后我再继续执行，避免直接误操作。"
        )
        if model_answer:
            answer_text = f"{answer_text}\n\n{model_answer}"
    elif str(route_decision or "").strip().lower() == "rag_plus_tool":
        answer_text = _build_facet_driven_answer(
            current_topic=current_topic,
            ranked_candidates=ranked_candidates,
            evidence_claims=evidence_claims,
            user_need=user_need,
        )
    elif user_need is not None and getattr(user_need, "required_facets", None):
        answer_text = _build_facet_driven_answer(
            current_topic=current_topic,
            ranked_candidates=ranked_candidates,
            evidence_claims=evidence_claims,
            user_need=user_need,
        )
    elif ranked_candidates:
        summary = model_answer or "我按“{summary}”筛了一下，优先推荐这几家：".format(
            summary="、".join(
                item
                for item in [
                    "离你近" if slots.location.type == "near_user" else None,
                    "人均预算合适" if slots.price.target is not None else None,
                    "适合带爸妈" if slots.scene == "family_dinner" else None,
                    "环境别太吵" if "quiet" in slots.preferences else None,
                    "有停车" if "parking_available" in slots.preferences else None,
                ]
                if item
            )
            or "你的条件"
        )
        lines = [summary, ""]
        for index, candidate in enumerate(ranked_candidates[:3], start=1):
            score_value = candidate.structured_features.get("score")
            score_text = f"{float(score_value):.1f}" if score_value is not None else "0.0"
            lines.append(
                "{index}. {name}，距你约{distance}，人均约{price}，评分{score}。{reason}".format(
                    index=index,
                    name=candidate.name,
                    distance=_format_distance(candidate.structured_features.get("distance_km")),
                    price=_format_price(candidate.structured_features.get("avg_price")),
                    score=score_text,
                    reason=_candidate_reason(candidate),
                )
            )
        if len(ranked_candidates) >= 2:
            lines.append("如果你愿意，我也可以继续帮你对比前两家，或者只看今晚可订的。")
        answer_text = "\n".join(lines)
    else:
        answer_text = model_answer or "我暂时没有筛到特别合适的店，你可以再补充一下口味、预算或者距离，我继续帮你找。"

    cards: list[dict[str, Any]] = []
    shops: list[dict[str, Any]] = []
    vouchers: list[dict[str, Any]] = []
    for candidate in ranked_candidates[:3]:
        cards.append(_build_shop_card(candidate))
        shops.append(
            {
                "id": candidate.shop_id,
                "name": candidate.name,
                "area": candidate.structured_features.get("area"),
                "address": candidate.structured_features.get("address"),
                "avgPrice": candidate.structured_features.get("avg_price"),
                "score": candidate.structured_features.get("score"),
                "comments": candidate.structured_features.get("comments"),
                "openHours": candidate.structured_features.get("open_hours"),
                "image": candidate.structured_features.get("image"),
                "distance": candidate.structured_features.get("distance_km"),
                "reason": _candidate_reason(candidate),
            }
        )
        for voucher in candidate.vouchers[:2]:
            voucher_card = _build_voucher_card(candidate, voucher)
            cards.append(voucher_card)
            vouchers.append(
                {
                    "id": voucher.get("id"),
                    "shopId": candidate.shop_id,
                    "shopName": candidate.name,
                    "title": voucher.get("title"),
                    "subTitle": voucher.get("sub_title") or voucher.get("subTitle"),
                    "payValue": voucher.get("pay_value") or voucher.get("payValue"),
                    "actualValue": voucher.get("actual_value") or voucher.get("actualValue"),
                    "stock": voucher.get("stock"),
                    "beginTime": voucher.get("begin_time") or voucher.get("beginTime"),
                    "endTime": voucher.get("end_time") or voucher.get("endTime"),
                    "rules": voucher.get("rules"),
                }
            )

    if not cards and ranked_candidates:
        cards = [_build_shop_card(candidate) for candidate in ranked_candidates[:3]]
    if not vouchers:
        for candidate in ranked_candidates[:3]:
            if candidate.vouchers:
                vouchers.extend(
                    {
                        "id": voucher.get("id"),
                        "shopId": candidate.shop_id,
                        "shopName": candidate.name,
                        "title": voucher.get("title"),
                        "subTitle": voucher.get("sub_title") or voucher.get("subTitle"),
                        "payValue": voucher.get("pay_value") or voucher.get("payValue"),
                        "actualValue": voucher.get("actual_value") or voucher.get("actualValue"),
                        "stock": voucher.get("stock"),
                        "beginTime": voucher.get("begin_time") or voucher.get("beginTime"),
                        "endTime": voucher.get("end_time") or voucher.get("endTime"),
                        "rules": voucher.get("rules"),
                    }
                    for voucher in candidate.vouchers[:2]
                )

    plan_suggested_replies = _reply_items_from_strings(answer_plan_model.suggested_replies) if plan_usable and answer_plan_model is not None else []
    model_suggested_replies = _normalize_suggested_replies(model_hint.get("suggested_replies"))
    suggested_replies = _build_suggested_replies(
        slots,
        ranked_candidates,
        approval_required=approval_required,
        model_hint=model_hint,
    )
    if plan_suggested_replies:
        seen_pairs = {(str(item.get("label") or ""), str(item.get("prompt") or "")) for item in plan_suggested_replies}
        suggested_replies = [
            *plan_suggested_replies,
            *[
                item
                for item in suggested_replies
                if (str(item.get("label") or ""), str(item.get("prompt") or "")) not in seen_pairs
            ],
        ]
    elif model_suggested_replies:
        seen_pairs = {(str(item.get("label") or ""), str(item.get("prompt") or "")) for item in model_suggested_replies}
        suggested_replies = [
            *model_suggested_replies,
            *[
                item
                for item in suggested_replies
                if (str(item.get("label") or ""), str(item.get("prompt") or "")) not in seen_pairs
            ],
        ]

    if plan_usable and answer_plan_model is not None and answer_plan_model.next_actions:
        next_steps = _merge_unique_text(action.label for action in answer_plan_model.next_actions)
    else:
        next_steps = _build_next_steps(
            mode=mode,
            ranked_candidates=ranked_candidates,
            approval_required=approval_required,
            transaction_draft=transaction_draft,
        )
    task_chain = _build_task_chain(
        mode=mode,
        ranked_candidates=ranked_candidates,
        approval_required=approval_required,
        transaction_draft=transaction_draft,
        next_steps=next_steps,
    )
    if plan_usable and answer_plan_model is not None:
        citations = _build_citations_from_answer_plan(
            answer_plan=answer_plan_model,
            evidence_pack=evidence_pack_model,
            evidence_claims=evidence_claims,
        )
    else:
        citations = _build_citations(evidence_claims)
    citations = _filter_citations_by_shop_ids(citations, allowed_shop_ids)

    retrieval_summary = {
        "retrieval_strategy": "hybrid_catalog+java_business",
        "retrieval_hit_count": len(ranked_candidates),
        "evidence_used_count": len(evidence_claims),
        "route_decision": route_decision,
        "route_reason": route_reason,
        "current_stage": current_stage,
        "stage_status": stage_status,
        "source_mode": source_mode,
        "degraded_reason": degraded_reason,
        "knowledge_freshness": knowledge_freshness,
        "model_hint_used": bool(model_hint) or bool(answer_plan_model),
    }
    grounding_status = "grounded" if evidence_claims else "weakly_grounded" if ranked_candidates else "not_grounded"
    confidence = (
        _confidence_to_score(answer_plan_model.confidence)
        if plan_usable and answer_plan_model is not None
        else round(min(0.98, 0.55 + 0.08 * len(ranked_candidates[:3]) + 0.03 * len(evidence_claims)), 3)
    )
    stage_timeline_payload = [dict(item) for item in stage_timeline or []]
    metrics = {
        "candidate_count": len(ranked_candidates),
        "evidence_count": len(evidence_claims),
        "source_mode": source_mode,
        "degraded_reason": degraded_reason,
        "knowledge_freshness": knowledge_freshness,
        "model_hint_used": bool(model_hint) or bool(answer_plan_model),
        "next_steps_count": len(next_steps),
        "task_chain_count": len(task_chain),
        "answer_plan_enabled": bool(answer_plan_model),
        "answer_plan_valid": bool(plan_usable),
        "answer_plan_confidence": answer_plan_model.confidence if answer_plan_model is not None else None,
        "evidence_pack_item_count": len(evidence_pack_model.items) if evidence_pack_model is not None else 0,
        "verifier_passed": verification_model.passed if verification_model is not None else None,
        "verifier_warnings": list(verification_model.warnings) if verification_model is not None else [],
    }
    if answer_plan_model is not None:
        metrics["answer_plan_decision_type"] = answer_plan_model.decision_type
        metrics["answer_plan_degraded_reason"] = answer_plan_model.degraded_reason
    bundle = LocalLifeResponseBundle(
        answer_text=answer_text,
        mode=mode,
        source=source,
        source_mode=source_mode,
        degraded_reason=degraded_reason,
        knowledge_freshness=knowledge_freshness,
        fallback=fallback,
        page=page,
        current_topic=current_topic,
        selected_shop_id=selected_shop_id
        or (
            answer_plan_model.top_choice.shop_id
            if answer_plan_model is not None and answer_plan_model.top_choice is not None
            else (ranked_candidates[0].shop_id if ranked_candidates else None)
        ),
        route_decision=route_decision,
        route_reason=route_reason,
        current_stage=current_stage,
        stage_status=stage_status,
        stage_timeline=stage_timeline_payload,
        cards=cards,
        shops=shops,
        vouchers=vouchers,
        suggested_replies=suggested_replies[:5],
        next_steps=next_steps,
        task_chain=task_chain,
        ranked_candidates=[candidate.model_dump(mode="json") for candidate in ranked_candidates],
        citations=citations,
        retrieval_summary=retrieval_summary,
        grounding_status=grounding_status,
        confidence=confidence,
        approval_required=approval_required,
        approval_request=approval_request,
        transaction_draft=transaction_draft,
        safety_result=safety_result,
        metrics=metrics,
        context={
            "raw_query": raw_query,
            "current_topic": current_topic,
            "current_shop": current_shop,
            "selected_shop_id": selected_shop_id,
            "selected_shop_name": current_shop or (ranked_candidates[0].name if ranked_candidates else None),
            "slots": slots.model_dump(mode="json"),
            "client_context": client_context,
            "approval_request": approval_request,
            "transaction_draft": transaction_draft,
            "safety_result": safety_result,
            "route_decision": route_decision,
            "route_reason": route_reason,
            "current_stage": current_stage,
            "stage_status": stage_status,
            "stage_timeline": stage_timeline_payload,
            "source_mode": source_mode,
            "degraded_reason": degraded_reason,
            "knowledge_freshness": knowledge_freshness,
            "model_hint_used": bool(model_hint),
            "answer_plan": answer_plan_model.model_dump(mode="json") if answer_plan_model is not None else None,
            "answer_verification": verification_model.model_dump(mode="json") if verification_model is not None else None,
            "next_steps": list(next_steps),
            "task_chain": list(task_chain),
        },
    )
    shop_lookup = {
        candidate.shop_id: candidate.name
        for candidate in ranked_candidates
        if getattr(candidate, "shop_id", None) is not None and getattr(candidate, "name", None)
    }
    return sanitize_local_life_output(bundle, shop_lookup=shop_lookup)
