from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from learning_agent_service.domain.utils import as_mapping as _as_mapping, clean_text as _clean_text

from learning_agent_service.local_life.answer_contract import AnswerContract
from learning_agent_service.local_life.answer_depth_policy import derive_answer_depth_policy
from learning_agent_service.local_life.answer_linter import lint_answer
from learning_agent_service.local_life.answer_planner import (
    EvidencePack,
    GroundedVerificationResult,
    LocalLifeAnswerPlan,
    parse_answer_plan_payload,
)
from learning_agent_service.local_life.answer_structure_composer import AnswerStructureComposer
from learning_agent_service.local_life.facet_result_bundle import FacetResultBundle
from learning_agent_service.local_life.realtime_contract import fallback_message_for_facet
from learning_agent_service.local_life.schemas import (
    EvidenceClaim,
    RankedCandidate,
    SuggestedReply,
)


def _coerce_facet_result_bundle(
    facet_result_bundle: Any | None,
) -> FacetResultBundle | None:
    if facet_result_bundle is None:
        return None
    if isinstance(facet_result_bundle, FacetResultBundle):
        return facet_result_bundle
    bundle_map = _as_mapping(facet_result_bundle)
    if not bundle_map:
        return None
    try:
        return FacetResultBundle.model_validate(bundle_map)
    except Exception:
        return None


def _tool_result_for_facet(
    facet_result_bundle: Any | None,
    facet: str,
    shop_id: int | None = None,
):
    facet_bundle = _coerce_facet_result_bundle(facet_result_bundle)
    if facet_bundle is None:
        return None
    return facet_bundle.find_tool_result(facet, shop_id=shop_id)


def _tool_result_source(tool_result: Any) -> str:
    if tool_result is None:
        return ""
    source = _clean_text(getattr(tool_result, "source", None))
    if not source and isinstance(tool_result, Mapping):
        source = _clean_text(tool_result.get("source"))
    return str(source or "").lower().strip()


def _tool_result_data(tool_result: Any) -> dict[str, Any]:
    if tool_result is None:
        return {}
    data = _as_mapping(getattr(tool_result, "data", None))
    if data:
        return dict(data)
    normalized_output = _as_mapping(getattr(tool_result, "normalized_output", None))
    if normalized_output:
        nested_data = _as_mapping(normalized_output.get("data"))
        if nested_data:
            return dict(nested_data)
        return dict(normalized_output)
    if isinstance(tool_result, Mapping):
        return dict(tool_result)
    return {}


def _strict_tool_result_is_trusted(tool_result: Any) -> bool:
    return _tool_result_source(tool_result) not in {"catalog", "fallback"}


def _coupon_titles_from_tool_result(tool_result: Any) -> list[str]:
    if not _strict_tool_result_is_trusted(tool_result):
        return []
    data = _tool_result_data(tool_result)
    coupons = list(data.get("coupons") or data.get("items") or [])
    titles: list[str] = []
    for coupon in coupons[:3]:
        coupon_map = _as_mapping(coupon)
        if str(_clean_text(coupon_map.get("source")) or "").lower().strip() in {"catalog", "fallback"}:
            return []
        title = coupon_map.get("title") or coupon_map.get("name")
        if title:
            titles.append(str(title))
    return titles


def _coupon_tool_count(
    facet_result_bundle: FacetResultBundle | None,
    *,
    shop_id: int | None = None,
) -> int | None:
    tool_result = _tool_result_for_facet(facet_result_bundle, "coupon", shop_id=shop_id)
    if tool_result is None:
        return None
    try:
        return int(tool_result.data.get("count") or 0)
    except Exception:
        return 0


def _evidence_quality_counts(
    evidence_claims: Sequence[EvidenceClaim] | None,
) -> tuple[int, int, int]:
    clean_count = 0
    strong_count = 0
    medium_count = 0
    for claim in evidence_claims or []:
        confidence = 0.0
        try:
            confidence = float(getattr(claim, "confidence", 0.0) or 0.0)
        except Exception:
            confidence = 0.0
        clean_count += 1
        if confidence >= 0.7:
            strong_count += 1
        elif confidence >= 0.4:
            medium_count += 1
    return clean_count, strong_count, medium_count


def build_coupon_only_answer(
    topic_name: str, 
    ranked_candidates: Sequence[RankedCandidate], 
    evidence_claims: Sequence[EvidenceClaim],
    facet_result_bundle: FacetResultBundle | None = None
) -> str:
    facet_bundle = _coerce_facet_result_bundle(facet_result_bundle)
    shop_id = ranked_candidates[0].shop_id if ranked_candidates else None
    tool_result = _tool_result_for_facet(facet_bundle, "coupon", shop_id=shop_id)
    coupon_data = _tool_result_data(tool_result)
    if tool_result is None or not _strict_tool_result_is_trusted(tool_result):
        fallback_text = fallback_message_for_facet("coupon", topic_name)
        if fallback_text:
            return f"实时优惠券信息：{fallback_text}"
        return f"{topic_name}实时优惠券信息暂时无法确认，建议以店铺页面显示为准。"
    if str(_clean_text(coupon_data.get("shop_source")) or "").lower().strip() in {"catalog", "fallback"}:
        fallback_text = fallback_message_for_facet("coupon", topic_name)
        if fallback_text:
            return f"实时优惠券信息：{fallback_text}"
        return f"{topic_name}实时优惠券信息暂时无法确认，建议以店铺页面显示为准。"
    if tool_result.status in {"timeout", "error", "degraded", "unsupported"}:
        fallback_text = fallback_message_for_facet("coupon", topic_name)
        if fallback_text:
            return f"实时优惠券信息：{fallback_text}"
        return f"{topic_name}实时优惠券信息暂时无法确认，建议以店铺页面显示为准。"

    coupon_count = _coupon_tool_count(facet_bundle, shop_id=shop_id)
    if coupon_count is None:
        if facet_bundle and facet_bundle.coupon_result and _clean_text(getattr(facet_bundle.coupon_result, "source", None)).lower() in {"realtime_tool", "java"}:
            coupon_count = facet_bundle.coupon_result.realtime_available_count

    if coupon_count > 0:
        titles = _coupon_titles_from_tool_result(tool_result)
        title_text = "、".join(titles)
        if title_text:
            return f"{topic_name}当前有{coupon_count}张券：{title_text}。"
        return f"{topic_name}当前有{coupon_count}张券。"
    
    coupon_claims = _summarize_coupon_claims(evidence_claims)
    if coupon_claims:
        return f"{topic_name}实时接口未查到当前可用券。虽然知识库里有优惠或套餐线索：{coupon_claims}，但历史描述需以实时接口为准。"
        
    return f"{topic_name}实时优惠券信息暂时不可用，当前接口暂无可用券。"

def build_open_status_only_answer(
    topic_name: str,
    ranked_candidates: Sequence[RankedCandidate],
    evidence_claims: Sequence[EvidenceClaim],
    facet_result_bundle: FacetResultBundle | None = None,
) -> str:
    facet_bundle = _coerce_facet_result_bundle(facet_result_bundle)
    shop_id = ranked_candidates[0].shop_id if ranked_candidates else None
    tool_result = _tool_result_for_facet(facet_bundle, "open_status", shop_id=shop_id)
    if tool_result is None or not _strict_tool_result_is_trusted(tool_result):
        return fallback_message_for_facet("open_status", topic_name) or f"{topic_name}暂时无法确认当前营业状态。"
    if str(_clean_text(_tool_result_data(tool_result).get("shop_source")) or "").lower().strip() in {"catalog", "fallback"}:
        return fallback_message_for_facet("open_status", topic_name) or f"{topic_name}暂时无法确认当前营业状态。"
    if tool_result.status in {"timeout", "error", "degraded", "unsupported"}:
        return fallback_message_for_facet("open_status", topic_name) or f"{topic_name}暂时无法确认当前营业状态。"
    open_status = str(tool_result.data.get("open_status") or "").strip().lower()
    if open_status == "open" or tool_result.data.get("open_now") is True:
        open_hours = tool_result.data.get("open_hours") or tool_result.data.get("openHours")
        if open_hours:
            return f"{topic_name}现在营业中，营业时间是 {open_hours}。"
        return f"{topic_name}现在营业中。"
    if open_status == "closed" or tool_result.data.get("open_now") is False:
        open_hours = tool_result.data.get("open_hours") or tool_result.data.get("openHours")
        if open_hours:
            return f"{topic_name}现在未营业，营业时间是 {open_hours}。"
        return f"{topic_name}现在未营业。"
    return fallback_message_for_facet("open_status", topic_name) or f"{topic_name}暂时无法确认当前营业状态。"


def build_distance_only_answer(
    topic_name: str,
    ranked_candidates: Sequence[RankedCandidate],
    evidence_claims: Sequence[EvidenceClaim],
    facet_result_bundle: FacetResultBundle | None = None,
) -> str:
    facet_bundle = _coerce_facet_result_bundle(facet_result_bundle)
    shop_id = ranked_candidates[0].shop_id if ranked_candidates else None
    tool_result = _tool_result_for_facet(facet_bundle, "distance_eta", shop_id=shop_id)
    if tool_result is None or not _strict_tool_result_is_trusted(tool_result):
        return fallback_message_for_facet("distance_eta", topic_name) or f"抱歉，暂时无法确认与{topic_name}的距离。"
    if str(_clean_text(_tool_result_data(tool_result).get("shop_source")) or "").lower().strip() in {"catalog", "fallback"}:
        return fallback_message_for_facet("distance_eta", topic_name) or f"抱歉，暂时无法确认与{topic_name}的距离。"
    if tool_result.status in {"timeout", "error", "degraded", "unsupported"}:
        return fallback_message_for_facet("distance_eta", topic_name) or f"抱歉，暂时无法确认与{topic_name}的距离。"
    distance_km = _tool_result_data(tool_result).get("distance_km")
    if distance_km is not None:
        return f"{topic_name}距离你约{_format_distance(distance_km)}。"
    return fallback_message_for_facet("distance_eta", topic_name) or f"抱歉，暂时无法确认与{topic_name}的距离。"

def build_comparison_answer(
    topic_name: str,
    ranked_candidates: Sequence[RankedCandidate],
    evidence_claims: Sequence[EvidenceClaim],
    answer_contract: AnswerContract | None = None,
    user_need: Any | None = None,
    facet_result_bundle: FacetResultBundle | None = None,
) -> str:
    clean_count, strong_count, medium_count = _evidence_quality_counts(evidence_claims)
    policy = derive_answer_depth_policy(
        answer_contract,
        clean_evidence_count=clean_count,
        strong_evidence_count=strong_count,
        medium_evidence_count=medium_count,
    )
    composer = AnswerStructureComposer()
    result = composer.compose(
        answer_contract=answer_contract,
        topic_name=topic_name,
        ranked_candidates=list(ranked_candidates),
        evidence_claims=list(evidence_claims),
        answer_depth_policy=policy,
        user_need=user_need,
        facet_result_bundle=facet_result_bundle,
    )
    return result.answer_text


def _answer_realtime_claim_supported(
    *,
    user_need: Any | None,
    facet_result_bundle: FacetResultBundle | None,
    ranked_candidates: Sequence[RankedCandidate],
) -> bool:
    req_facet_names = [f.name for f in getattr(user_need, "required_facets", []) or []] if user_need is not None else []
    realtime_facets = [facet for facet in req_facet_names if facet in {"coupon", "open_status", "distance_eta"}]
    if not realtime_facets:
        return True

    if not ranked_candidates:
        top_shop_id = None
    else:
        top_shop_id = ranked_candidates[0].shop_id

    for facet in realtime_facets:
        if facet_result_bundle is None:
            return False
        if facet == "distance_eta":
            if _tool_result_for_facet(facet_result_bundle, facet, shop_id=top_shop_id) is None:
                return False
            continue
        result = _tool_result_for_facet(facet_result_bundle, facet, shop_id=top_shop_id)
        if result is None:
            return False
    return True


def validate_answer_against_contract(
    answer_text: str | None, 
    answer_contract: AnswerContract, 
    topic_name: str, 
    ranked_candidates: Sequence[RankedCandidate], 
    evidence_claims: Sequence[EvidenceClaim],
    facet_result_bundle: FacetResultBundle | None = None,
    user_need: Any | None = None,
    answer_context: Any | None = None,
) -> str:
    if not answer_contract:
        return answer_text or ""

    if not answer_text:
        answer_text = ""
    lint_result = lint_answer(
        answer_text=answer_text,
        answer_contract=answer_contract,
        topic_name=topic_name,
        ranked_candidates=ranked_candidates,
        evidence_claims=evidence_claims,
        facet_result_bundle=facet_result_bundle,
        user_need=user_need,
        answer_context=answer_context,
    )

    cleaned_lines = []
    if lint_result.repaired_text:
        cleaned_lines = [line for line in lint_result.repaired_text.split("\n") if line.strip()]
    validated_text = "\n".join(cleaned_lines).strip()

    if lint_result.severity == "block" or not validated_text:
        if answer_contract.answer_style == "coupon_only":
            return build_coupon_only_answer(topic_name, ranked_candidates, evidence_claims, facet_result_bundle=facet_result_bundle)
        elif answer_contract.answer_style == "open_status_only":
            return build_open_status_only_answer(topic_name, ranked_candidates, evidence_claims, facet_result_bundle=facet_result_bundle)
        elif answer_contract.answer_style == "distance_only":
            return build_distance_only_answer(topic_name, ranked_candidates, evidence_claims, facet_result_bundle=facet_result_bundle)
        elif answer_contract.answer_style == "clarification":
            return answer_text
        elif answer_contract.answer_style == "single_shop_review":
            return build_single_shop_review_answer(topic_name, ranked_candidates, evidence_claims)
        elif answer_contract.answer_style == "facet_multi":
            return _build_facet_driven_answer(
                current_topic=topic_name,
                ranked_candidates=ranked_candidates,
                evidence_claims=evidence_claims,
                user_need=user_need,
                facet_result_bundle=facet_result_bundle,
            )
        elif answer_contract.answer_style == "multi_shop_recommendation":
            return build_multi_shop_recommendation_answer(
                topic_name,
                ranked_candidates,
                evidence_claims,
                user_need=user_need,
                facet_result_bundle=facet_result_bundle,
            )
        elif answer_contract.answer_style == "comparison":
            return build_comparison_answer(
                topic_name=topic_name,
                ranked_candidates=ranked_candidates,
                evidence_claims=evidence_claims,
                answer_contract=answer_contract,
                user_need=user_need,
                facet_result_bundle=facet_result_bundle,
            )
        else:
            return answer_text

    return validated_text



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


def _build_guardrail_degraded_answer(
    *,
    answer_contract: AnswerContract | None,
    evidence_pack: EvidencePack | None,
    current_topic: str,
) -> str | None:
    if answer_contract is None or evidence_pack is None:
        return None
    source_summary = dict(evidence_pack.source_summary or {})
    rag_guardrail = _as_mapping(source_summary.get("rag_guardrail"))
    if not rag_guardrail or not rag_guardrail.get("degraded"):
        return None
    if evidence_pack.items:
        return None
    degraded_reason = _clean_text(rag_guardrail.get("degraded_reason") or source_summary.get("degraded_reason"))
    if degraded_reason:
        return degraded_reason
    if answer_contract.answer_style == "multi_shop_recommendation":
        topic = current_topic or "\u8fd9\u9644\u8fd1"
        return (
            f"{topic}\uff1a\u5f53\u524d\u8bc1\u636e\u8fd8\u4e0d\u591f\u5b8c\u6574\uff0c\u6211\u5148\u7ed9\u4f60\u4e00\u4e2a\u4fdd\u5b88\u63a8\u8350\u3002\n"
            "\u63a8\u8350\u7406\u7531\uff1a\u73b0\u6709\u4fe1\u606f\u4e0d\u8db3\u4ee5\u7a33\u5b9a\u5224\u65ad\u6700\u4f18\u5546\u5bb6\uff0c\u4f46\u53ef\u4ee5\u5148\u6309\u8ddd\u79bb\u3001\u53e3\u5473\u548c\u73af\u5883\u7ee7\u7eed\u7b5b\u9009\u3002\n"
            "\u5982\u679c\u4f60\u613f\u610f\uff0c\u6211\u53ef\u4ee5\u7ee7\u7eed\u5e2e\u4f60\u627e\u66f4\u9002\u5408\u7ea6\u4f1a\u6216\u66f4\u9002\u5408\u805a\u9910\u7684\u63a8\u8350\u3002"
        )
    if answer_contract.answer_style == "single_shop_review":
        return f"我目前没有检索到{current_topic or '这家店'}相关的可靠评价证据，暂时不能直接判断。"
    return None

def _infer_topic_from_query(raw_query: str) -> str | None:
    text = (raw_query or "").strip().rstrip("？?。.!！")
    if not text:
        return None
    if text in {"它", "这家", "这店", "这间", "这商家", "这个商家"}:
        return None
    if any(token in text for token in ("天气", "气温", "预报", "温度")):
        return None
    suffixes = (
        "现在营业吗",
        "现在有券吗",
        "现在开吗",
        "有几张券",
        "有可用优惠券吗",
        "有券吗",
        "营业吗",
        "怎么样",
        "好不好",
        "值不值",
        "适合吗",
    )
    changed = True
    while changed and text:
        changed = False
        for suffix in sorted(suffixes, key=len, reverse=True):
            if text.endswith(suffix):
                text = text[: -len(suffix)].strip(" ，,;；")
                changed = True
                break
    if not text or text in {"它", "这家", "这店", "这间", "这商家", "这个商家"}:
        return None
    return text


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
        text: str | None
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
    facet_result_bundle: FacetResultBundle | None = None,
) -> str:
    facet_bundle = _coerce_facet_result_bundle(facet_result_bundle)
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
        coupon_count = 0
        if facet_bundle and facet_bundle.coupon_result:
            coupon_count = facet_bundle.coupon_result.realtime_available_count
        else:
            coupon_count = len(ranked_candidates[0].vouchers) if (ranked_candidates and ranked_candidates[0].vouchers) else 0

        voucher_summaries: list[str] = []
        if ranked_candidates and coupon_count > 0:
            for voucher in ranked_candidates[0].vouchers[:3]:
                title = _clean_text(voucher.get("title") or voucher.get("name"))
                pay_value = voucher.get("pay_value") or voucher.get("payValue")
                actual_value = voucher.get("actual_value") or voucher.get("actualValue")
                if title and pay_value not in (None, "") and actual_value not in (None, ""):
                    voucher_summaries.append(f"{title}（{_format_price(pay_value)} 代 {_format_price(actual_value)}）")
                elif title:
                    voucher_summaries.append(title)
        if voucher_summaries:
            sections.append(f"券信息：{shop_name} 当前有{coupon_count}张券：{'、'.join(voucher_summaries)}。")
        else:
            coupon_claims = _summarize_coupon_claims(evidence_claims)
            if coupon_claims:
                sections.append(
                    f"券信息：{shop_name} 实时接口未查到当前可用券。虽然知识库里有优惠或套餐线索：{coupon_claims}，但历史描述需以实时接口为准。"
                )
            else:
                sections.append(f"券信息：{shop_name} 暂时没看到可用券。")

    # Open Status Section
    if user_need is not None and "open_status" in req_facet_names:
        shop_id = ranked_candidates[0].shop_id if ranked_candidates else None
        tool_result = _tool_result_for_facet(facet_bundle, "open_status", shop_id=shop_id)
        if tool_result is None or tool_result.status in {"timeout", "error", "degraded", "unsupported"}:
            sections.append(f"营业状态：{fallback_message_for_facet('open_status', shop_name) or f'{shop_name}暂时无法确认当前营业状态。'}")
        else:
            open_status = str(tool_result.data.get("open_status") or "").strip().lower()
            open_hours = tool_result.data.get("open_hours") or tool_result.data.get("openHours")
            if open_status == "open" or tool_result.data.get("open_now") is True:
                sections.append(f"营业状态：{shop_name} 现在营业中。" + (f"营业时间是 {open_hours}。" if open_hours else ""))
            elif open_status == "closed" or tool_result.data.get("open_now") is False:
                sections.append(f"营业状态：{shop_name} 现在未营业。" + (f"营业时间是 {open_hours}。" if open_hours else ""))
            else:
                sections.append(f"营业状态：{fallback_message_for_facet('open_status', shop_name) or f'{shop_name}暂时无法确认当前营业状态。'}")

    # Environment/Scene Section
    if user_need is None or "scene_fit" in req_facet_names or "category" in req_facet_names:
        sections.append(f"{shop_name}：环境评价：{_summarize_environment_claims(evidence_claims)}")

    if not sections:
        sections.append(f"{shop_name}：环境评价：{_summarize_environment_claims(evidence_claims)}")

    return "\n".join(sections)


def _build_facet_driven_answer(
    *,
    current_topic: str | None,
    ranked_candidates: Sequence[RankedCandidate],
    evidence_claims: Sequence[EvidenceClaim],
    user_need: Any | None = None,
    facet_result_bundle: FacetResultBundle | None = None,
) -> str:
    facet_bundle = _coerce_facet_result_bundle(facet_result_bundle)
    req_facet_names = [f.name for f in getattr(user_need, "required_facets", []) or []] if user_need is not None else []
    if not req_facet_names:
        return _build_coupon_environment_answer(
            current_topic=current_topic,
            ranked_candidates=ranked_candidates,
            evidence_claims=evidence_claims,
            user_need=user_need,
            facet_result_bundle=facet_bundle,
        )

    top_candidate = ranked_candidates[0] if ranked_candidates else None
    topic_name = _clean_text(current_topic) or (top_candidate.name if top_candidate else "这家店")
    answer_contract = None
    if user_need is not None:
        try:
            answer_contract = AnswerContract.build_contract(user_need, target_shop=top_candidate)
        except Exception:
            answer_contract = None
    if answer_contract is not None:
        clean_count, strong_count, medium_count = _evidence_quality_counts(evidence_claims)
        policy = derive_answer_depth_policy(
            answer_contract,
            clean_evidence_count=clean_count,
            strong_evidence_count=strong_count,
            medium_evidence_count=medium_count,
        )
        composer = AnswerStructureComposer()
        composed = composer.compose(
            answer_contract=answer_contract,
            topic_name=topic_name,
            ranked_candidates=list(ranked_candidates),
            evidence_claims=list(evidence_claims),
            answer_depth_policy=policy,
            user_need=user_need,
            facet_result_bundle=facet_bundle,
        )
        if composed.answer_text:
            return composed.answer_text
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
        shop_id = top_candidate.shop_id if top_candidate is not None else None
        tool_result = _tool_result_for_facet(facet_bundle, "coupon", shop_id=shop_id)
        if tool_result is not None and tool_result.status in {"timeout", "error", "degraded", "unsupported"}:
            sections.append(f"券信息：{fallback_message_for_facet('coupon', topic_name) or f'{topic_name}暂时无法确认实时优惠券信息。'}")
        else:
            coupon_count = _coupon_tool_count(facet_bundle, shop_id=shop_id)
            if coupon_count is None:
                if facet_bundle and facet_bundle.coupon_result:
                    coupon_count = facet_bundle.coupon_result.realtime_available_count
                else:
                    coupon_count = len(top_candidate.vouchers) if (top_candidate and top_candidate.vouchers) else 0

            coupon_text = _summarize_coupon_claims(evidence_claims)
            if top_candidate is not None and top_candidate.vouchers and coupon_count > 0:
                voucher = top_candidate.vouchers[0]
                title = _clean_text(voucher.get("title") or voucher.get("name")) or "优惠券"
                pay_value = voucher.get("pay_value") or voucher.get("payValue")
                actual_value = voucher.get("actual_value") or voucher.get("actualValue")
                if pay_value not in (None, "") and actual_value not in (None, ""):
                    sections.append(f"券信息：{title}（{_format_price(pay_value)} 代 {_format_price(actual_value)}）。")
                else:
                    sections.append(f"券信息：{title}。")
            elif coupon_text:
                sections.append(f"券信息：{topic_name} 实时接口未查到当前可用券。虽然知识库里有优惠或套餐线索：{coupon_text}，但历史描述需以实时接口为准。")
            else:
                sections.append(f"券信息：{topic_name} 暂时没看到可用券。")

    if "open_status" in req_facet_names:
        shop_id = top_candidate.shop_id if top_candidate is not None else None
        tool_result = _tool_result_for_facet(facet_bundle, "open_status", shop_id=shop_id)
        if tool_result is None or tool_result.status in {"timeout", "error", "degraded", "unsupported"}:
            sections.append(f"营业状态：{fallback_message_for_facet('open_status', topic_name) or f'{topic_name}暂时无法确认当前营业状态。'}")
        else:
            open_status = str(tool_result.data.get("open_status") or "").strip().lower()
            open_hours = tool_result.data.get("open_hours") or tool_result.data.get("openHours")
            if open_status == "open" or tool_result.data.get("open_now") is True:
                sections.append(f"营业状态：{topic_name} 现在营业中。" + (f"营业时间是 {open_hours}。" if open_hours else ""))
            elif open_status == "closed" or tool_result.data.get("open_now") is False:
                sections.append(f"营业状态：{topic_name} 现在未营业。" + (f"营业时间是 {open_hours}。" if open_hours else ""))
            else:
                sections.append(f"营业状态：{fallback_message_for_facet('open_status', topic_name) or f'{topic_name}暂时无法确认当前营业状态。'}")

    if "distance_eta" in req_facet_names and top_candidate is not None:
        tool_result = _tool_result_for_facet(facet_bundle, "distance_eta", shop_id=top_candidate.shop_id)
        if tool_result is None or tool_result.status in {"timeout", "error", "degraded", "unsupported"}:
            sections.append(f"距离信息：{fallback_message_for_facet('distance_eta', topic_name) or f'{topic_name}暂时无法确认距离信息。'}")
        else:
            sections.append(
                f"距离信息：{topic_name} 距离你约{_format_distance(tool_result.data.get('distance_km'))}。"
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
        facet_result_bundle=facet_bundle,
    )



def build_single_shop_review_answer(topic_name: str, ranked_candidates: Sequence[RankedCandidate], evidence_claims: Sequence[EvidenceClaim]) -> str:
    display_name = str(topic_name or "").strip()
    top_candidate = ranked_candidates[0] if ranked_candidates else None
    name = display_name or (top_candidate.name if top_candidate is not None else "\u8fd9\u5bb6\u5e97")
    sections: list[str] = []
    if top_candidate is not None:
        score_val = top_candidate.structured_features.get("score")
        score_text = f"{float(score_val):.1f}" if score_val not in (None, "") else "0.0"
        price_text = _format_price(top_candidate.structured_features.get("avg_price"))
        distance_text = _format_distance(top_candidate.structured_features.get("distance_km"))
        sections.append(f"{name}\uff1a\u8bc4\u5206 {score_text}\uff0c\u4eba\u5747\u7ea6 {price_text}\uff0c\u8ddd\u4f60\u7ea6 {distance_text}\u3002")
        address_text = _clean_text(top_candidate.structured_features.get("address"))
        if address_text:
            sections.append(f"\u5730\u5740\uff1a{address_text}\u3002")
        reason = _candidate_reason(top_candidate)
        if reason:
            sections.append(f"\u63a8\u8350\u7406\u7531\uff1a{reason}\u3002")
    elif display_name:
        sections.append(f"{name}\uff1a\u76ee\u524d\u8bc1\u636e\u6709\u9650\uff0c\u5148\u628a\u5b83\u5f53\u4f5c\u5019\u9009\u770b\u3002")

    env_summary = _summarize_environment_claims(evidence_claims)
    if env_summary:
        sections.append(env_summary)
    sections.append("\u9002\u5408\u573a\u666f\uff1a\u9002\u5408\u60f3\u5148\u5feb\u901f\u5224\u65ad\uff0c\u518d\u51b3\u5b9a\u662f\u5426\u5230\u5e97\u3002")
    sections.append("\u5230\u5e97\u5efa\u8bae\uff1a\u5148\u770b\u8425\u4e1a\u72b6\u6001\u548c\u5b9e\u65f6\u4fe1\u606f\uff0c\u518d\u51b3\u5b9a\u662f\u5426\u73b0\u5728\u53bb\u3002")
    return "\n".join(sections)


def build_multi_shop_recommendation_answer(
    topic_name: str,
    ranked_candidates: Sequence[RankedCandidate],
    evidence_claims: Sequence[EvidenceClaim],
    user_need: Any | None = None,
    facet_result_bundle: FacetResultBundle | None = None,
) -> str:
    count = 3
    if user_need is not None and hasattr(user_need, "recommendation_count"):
        try:
            count = max(1, int(getattr(user_need, "recommendation_count")))
        except Exception:
            count = 3

    req_facet_names = [f.name for f in getattr(user_need, "required_facets", []) or []] if user_need is not None else []
    raw_query = str(getattr(user_need, "raw_query", "") or "")
    scene_requested = "scene_fit" in req_facet_names or any(token in raw_query for token in ("\u7ea6\u4f1a", "\u60c5\u4fa3", "\u5bb6\u5ead\u805a\u9910", "\u5b89\u9759", "\u5e26\u5a46"))
    coupon_requested = "coupon" in req_facet_names
    coupon_like_query = any(token in raw_query.replace(" ", "") for token in ("\u5238", "\u4f18\u60e0", "\u56e2\u8d2d", "\u4ee3\u91d1\u5238"))
    open_requested = "open_status" in req_facet_names

    if not ranked_candidates:
        lines = ["\u6211\u5148\u5e2e\u4f60\u63a8\u8350\u4e00\u4e9b\u66f4\u5339\u914d\u7684\u9910\u5385\u65b9\u5411\uff1a", ""]
        if scene_requested:
            lines.append("\u573a\u666f\uff1a\u9002\u5408\u7ea6\u4f1a\u3002")
        lines.append("\u63a8\u8350\u7406\u7531\uff1a\u5f53\u524d\u8bc1\u636e\u91cc\u6709\u8f83\u5f3a\u7684\u5019\u9009\u65b9\u5411\uff0c\u5efa\u8bae\u5148\u6309\u8ddd\u79bb\u3001\u53e3\u5473\u548c\u73af\u5883\u518d\u7ec6\u7b5b\u3002")
        if coupon_requested or coupon_like_query:
            lines.append("\u5238\uff1a\u5982\u679c\u4f60\u613f\u610f\uff0c\u6211\u53ef\u4ee5\u7ee7\u7eed\u5e2e\u4f60\u67e5\u5b9e\u65f6\u4f18\u60e0\u3002")
        if open_requested:
            lines.append("\u8425\u4e1a\uff1a\u5982\u679c\u4f60\u613f\u610f\uff0c\u6211\u4e5f\u53ef\u4ee5\u7ee7\u7eed\u5e2e\u4f60\u786e\u8ba4\u5b9e\u65f6\u8425\u4e1a\u72b6\u6001\u3002")
        lines.append("\u5982\u679c\u4f60\u613f\u610f\uff0c\u6211\u53ef\u4ee5\u7ee7\u7eed\u6309\u9884\u7b97\u3001\u8ddd\u79bb\u6216\u573a\u666f\u5e2e\u4f60\u7f29\u5c0f\u8303\u56f4\u3002")
        return "\n".join(lines)

    lines = ["\u6211\u5e2e\u4f60\u63a8\u8350\u4ee5\u4e0b\u8fd9\u51e0\u5bb6\u5e97\uff1a", ""]
    for index, candidate in enumerate(ranked_candidates[:count], start=1):
        score_value = candidate.structured_features.get("score")
        score_text = f"{float(score_value):.1f}" if score_value is not None else "0.0"
        parts = [
            f"{index}. {candidate.name}\uff1a\u8ddd\u4f60\u7ea6 {_format_distance(candidate.structured_features.get('distance_km'))}\uff0c\u4eba\u5747\u7ea6 {_format_price(candidate.structured_features.get('avg_price'))}\uff0c\u8bc4\u5206 {score_text}\u3002"
        ]
        reason = _candidate_reason(candidate)
        parts.append(f"\u63a8\u8350\u7406\u7531\uff1a{reason}\u3002" if reason else "\u63a8\u8350\u7406\u7531\uff1a\u5f53\u524d\u5019\u9009\u91cc\u5b83\u7684\u7efc\u5408\u4fe1\u606f\u6bd4\u8f83\u9760\u524d\uff0c\u503c\u5f97\u4f18\u5148\u67e5\u770b\u3002")
        if scene_requested:
            parts.append("\u573a\u666f\uff1a\u9002\u5408\u7ea6\u4f1a\u3002")
        if coupon_requested or coupon_like_query:
            coupon_tool_result = _tool_result_for_facet(facet_result_bundle, "coupon", shop_id=candidate.shop_id)
            if coupon_tool_result is not None and coupon_tool_result.status in {"timeout", "error", "degraded", "unsupported"}:
                parts.append("\u5238\uff1a\u6682\u65f6\u67e5\u4e0d\u5230\u5b9e\u65f6\u5238\u4fe1\u606f\uff0c\u4ee5\u5e97\u94fa\u9875\u9762\u4e3a\u51c6\u3002")
            elif coupon_tool_result is not None and coupon_tool_result.status == "empty":
                parts.append("\u5238\uff1a\u5b9e\u65f6\u63a5\u53e3\u6682\u65f6\u672a\u67e5\u5230\u53ef\u7528\u5238\u3002")
            else:
                parts.append("\u5238\uff1a\u5982\u679c\u4f60\u613f\u610f\uff0c\u6211\u53ef\u4ee5\u7ee7\u7eed\u5e2e\u4f60\u67e5\u5b9e\u65f6\u4f18\u60e0\u3002")
        if open_requested:
            open_tool_result = _tool_result_for_facet(facet_result_bundle, "open_status", shop_id=candidate.shop_id)
            if open_tool_result is None or open_tool_result.status in {"timeout", "error", "degraded", "unsupported"}:
                parts.append("\u8425\u4e1a\uff1a\u6682\u65f6\u65e0\u6cd5\u786e\u8ba4\u5b9e\u65f6\u8425\u4e1a\u72b6\u6001\u3002")
            else:
                open_status = str(open_tool_result.data.get("open_status") or "").strip().lower()
                open_hours = open_tool_result.data.get("open_hours") or open_tool_result.data.get("openHours")
                hours_text = f"\u8425\u4e1a\u65f6\u95f4\uff1a{open_hours}\u3002" if open_hours else ""
                if open_status == "open" or open_tool_result.data.get("open_now") is True:
                    parts.append(f"\u8425\u4e1a\uff1a\u5f53\u524d\u8425\u4e1a\u4e2d\u3002{hours_text}")
                elif open_status == "closed" or open_tool_result.data.get("open_now") is False:
                    parts.append(f"\u8425\u4e1a\uff1a\u5f53\u524d\u672a\u8425\u4e1a\u3002{hours_text}")
                else:
                    parts.append("\u8425\u4e1a\uff1a\u6682\u65f6\u65e0\u6cd5\u786e\u8ba4\u5b9e\u65f6\u8425\u4e1a\u72b6\u6001\u3002")
        lines.append("\n".join(parts))

    lines.append("")
    lines.append("\u7efc\u5408\u5efa\u8bae")
    lines.append("- \u5982\u679c\u4f60\u66f4\u5728\u610f\u6c14\u56f4\u548c\u7a33\u5b9a\u6027\uff0c\u5efa\u8bae\u5148\u4ece\u524d\u4e24\u5bb6\u5f00\u59cb\u770b\u3002")
    lines.append("- \u5982\u679c\u4f60\u8981\u7ee7\u7eed\u67e5\u5238\u6216\u8425\u4e1a\uff0c\u6211\u53ef\u4ee5\u7acb\u523b\u63a5\u7740\u8ffd\u67e5\u3002")
    return "\n".join(lines)


__all__ = [name for name in globals() if not name.startswith("__") and not name.startswith("_legacy_")]
