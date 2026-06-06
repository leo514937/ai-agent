from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from learning_agent_service.domain.utils import as_mapping as _as_mapping, clean_text as _clean_text
from learning_agent_service.local_life.answer_planner import EvidencePack, LocalLifeAnswerPlan
from learning_agent_service.local_life.schemas import (
    CardAction,
    EvidenceClaim,
    LocalLifeSlots,
    RankedCandidate,
    ShopCard,
    SuggestedReply,
    VoucherCard,
)

from .answers import (
    _candidate_reason,
    _format_distance,
    _format_price,
    _merge_unique_text,
    _normalize_suggested_replies,
    _top_badges,
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
            CardAction(type="claim_coupon", label="立即领券", payload={"voucher_id": voucher_id, "shop_id": candidate.shop_id})
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
        entry: dict[str, Any] = {"step": step, "label": label, "status": status}
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
            shop_id = int(str(raw_id))
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
        item_data = evidence_index.get(evidence_id)
        if not item_data:
            continue
        citations.append(
            {
                "chunk_id": item_data.get("chunk_id") or item_data.get("evidence_id"),
                "document_id": str(item_data.get("shop_id")) if item_data.get("shop_id") is not None else None,
                "source_type": item_data.get("source_type"),
                "score": item_data.get("confidence"),
                "title": item_data.get("claim"),
                "locator": item_data.get("metadata", {}).get("shop_name") if isinstance(item_data.get("metadata"), Mapping) else None,
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


__all__ = [name for name in globals() if not name.startswith("__")]
