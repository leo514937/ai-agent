from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from learning_agent_service.domain.utils import as_mapping as _as_mapping, clean_text as _clean_text
from .grounding_policy import HIGH_RISK_FACETS, HYBRID_FACETS, RAG_REQUIRED_FACETS, TOOL_REQUIRED_FACETS, claim_policy_for_facet, is_high_risk_facet

CLAIM_SOURCE_TYPES = (
    "tool_structured",
    "realtime_tool",
    "rag_evidence",
    "rerank_reason",
    "user_context",
    "template",
    "llm_generated",
)

_TOOL_REQUIRED_CLAIMS = set(TOOL_REQUIRED_FACETS)
_RAG_REQUIRED_CLAIMS = set(RAG_REQUIRED_FACETS)
_HYBRID_CLAIMS = set(HYBRID_FACETS)
_FALLBACK_TOKENS = (
    "暂时无法确认",
    "暂时查不到",
    "当前证据不足",
    "不确定",
    "我不能直接",
    "我先不",
    "建议再确认",
    "请告诉我",
    "稍后再试",
    "我先帮你",
    "保留这条线索",
    "先给你一个保守判断",
)


def _flatten_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        parts: list[str] = []
        for key in ("text", "text_content", "claim", "support_text", "reason", "summary", "content", "name", "title"):
            if key in value:
                parts.append(_flatten_text(value.get(key)))
        return " ".join(part for part in parts if part)
    if isinstance(value, (list, tuple, set)):
        return " ".join(_flatten_text(item) for item in value)
    return str(value)


def _claim_fragments(answer_text: str) -> list[str]:
    fragments: list[str] = []
    for raw_line in str(answer_text or "").splitlines():
        line = _clean_text(raw_line)
        line = re.sub(r"\[[^\]]+\]", " ", line)
        line = re.sub(r"【[^】]+】", " ", line)
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        for part in re.split(r"[。！？!?；;]+", line):
            text = _clean_text(part)
            if text:
                fragments.append(text)
    return fragments


def _claim_type(text: str) -> str:
    compact = (_clean_text(text) or "").replace(" ", "")
    if not compact:
        return "generic"
    if any(token in compact for token in _FALLBACK_TOKENS) or any(
        token in compact for token in ("你是指", "请告诉我", "再确认", "重新推荐", "要重新", "补充", "具体一点", "更具体")
    ):
        return "template"
    if any(token in compact for token in ("推荐", "排序", "优先", "更适合", "对比", "比较", "区别", "差别")):
        return "recommendation" if "推荐" in compact or "优先" in compact else "comparison"
    if any(token in compact for token in ("环境", "氛围", "安静", "吵", "包间", "卫生", "排队")):
        return "environment"
    if any(token in compact for token in ("口味", "味道", "好吃", "菜量", "分量")):
        return "taste"
    if any(token in compact for token in ("服务", "态度", "体验", "踩坑", "坑", "差评")):
        return "service"
    if any(token in compact for token in ("约会", "长辈", "带娃", "家庭", "朋友聚餐")) or ("适合" in compact and any(token in compact for token in ("约会", "长辈", "带娃", "家庭"))):
        return "scene_fit"
    if any(token in compact for token in ("评分", "分")):
        return "rating"
    if any(token in compact for token in ("人均", "价格", "预算", "元")):
        return "price"
    if any(token in compact for token in ("距离", "公里", "路程", "导航", "怎么走", "怎么去")):
        return "distance_eta"
    if any(token in compact for token in ("券", "优惠", "团购", "代金券", "套餐", "库存")):
        if any(token in compact for token in ("库存", "余量", "剩余")):
            return "stock"
        return "coupon"
    if any(token in compact for token in ("营业时间", "几号开", "开门时间", "营业", "开门", "开着", "关门")):
        return "open_hours" if "时间" in compact else "open_status"
    if any(token in compact for token in ("地址", "位于", "位置", "门店")):
        return "address"
    if any(token in compact for token in ("订座", "预订", "预约", "订位")):
        return "booking"
    if any(token in compact for token in ("退款", "退费", "退款吗", "可退", "退钱")):
        return "refund"
    if any(token in compact for token in ("支付", "付款", "买单", "收款")):
        return "payment"
    if any(token in compact for token in ("下单", "订单", "取消订单")):
        return "order"
    if any(token in compact for token in ("电话", "联系电话", "手机", "号码")):
        return "phone"
    if any(token in compact for token in ("配送", "送达", "外卖", "多久到", "到店", "送到")):
        return "delivery_eta"
    return "generic"


def _is_fallback_claim(text: str) -> bool:
    compact = (_clean_text(text) or "").replace(" ", "")
    return any(token in compact for token in _FALLBACK_TOKENS)


def _source_ref(
    *,
    source_type: str,
    source_id: str,
    source_label: str | None = None,
    confidence: float = 0.0,
    detail: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "source_type": source_type,
        "source_id": source_id,
        "confidence": round(float(confidence or 0.0), 3),
    }
    if source_label:
        payload["source_label"] = source_label
    if detail:
        payload["detail"] = dict(detail)
    return payload


def _parse_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value).strip())
    except Exception:
        return None


def _entity_info_from_sources(
    sources: Sequence[Mapping[str, Any] | Any] | None,
    *,
    answer_context: Mapping[str, Any] | Any | None = None,
) -> tuple[str | None, int | None, str | None]:
    context_map = _as_mapping(answer_context)
    context_shop_id = _parse_int(context_map.get("selected_shop_id") or context_map.get("current_shop_id"))
    context_entity_name = _clean_text(
        context_map.get("current_shop")
        or context_map.get("selected_shop_name")
        or context_map.get("current_topic")
    ) or None
    entity_id = f"shop:{context_shop_id}" if context_shop_id is not None else (f"shop:{context_entity_name}" if context_entity_name else None)
    shop_id = context_shop_id
    entity_name = context_entity_name

    for source in sources or []:
        source_map = _as_mapping(source)
        detail = _as_mapping(source_map.get("detail"))
        candidate_shop_id = _parse_int(
            source_map.get("shop_id")
            or detail.get("shop_id")
            or detail.get("selected_shop_id")
            or detail.get("candidate_shop_id")
            or detail.get("entity_id")
        )
        candidate_name = _clean_text(
            source_map.get("source_label")
            or source_map.get("shop_name")
            or detail.get("shop_name")
            or detail.get("entity_name")
            or detail.get("name")
        ) or None
        if shop_id is None and candidate_shop_id is not None:
            shop_id = candidate_shop_id
            entity_id = f"shop:{candidate_shop_id}"
        if not entity_name and candidate_name:
            entity_name = candidate_name
        if entity_id is None:
            source_entity_id = _clean_text(source_map.get("entity_id") or detail.get("entity_id"))
            if source_entity_id:
                entity_id = source_entity_id
        if shop_id is not None and entity_name:
            break

    if entity_id is None and shop_id is not None:
        entity_id = f"shop:{shop_id}"
    if entity_id is None and entity_name:
        entity_id = entity_name
    return entity_id, shop_id, entity_name


def _source_index_from_context(
    *,
    ranked_candidates: Sequence[Mapping[str, Any] | Any] | None,
    evidence_claims: Sequence[Mapping[str, Any] | Any] | None,
    facet_result_bundle: Any | None,
    tool_results: Sequence[Mapping[str, Any] | Any] | None,
    answer_context: Mapping[str, Any] | Any | None,
) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {key: [] for key in CLAIM_SOURCE_TYPES}

    for candidate in ranked_candidates or []:
        candidate_map = _as_mapping(candidate)
        shop_id = candidate_map.get("shop_id")
        source_id = f"candidate:{shop_id if shop_id not in (None, '') else _clean_text(candidate_map.get('name')) or 'unknown'}"
        index["tool_structured"].append(
            _source_ref(
                source_type="tool_structured",
                source_id=source_id,
                source_label=_clean_text(candidate_map.get("name") or candidate_map.get("shop_name")) or None,
                confidence=float(candidate_map.get("rank_score") or candidate_map.get("score") or 0.0),
                detail=candidate_map,
            )
        )
        reasons = list(candidate_map.get("explainable_reasons") or [])
        for reason_index, reason in enumerate(reasons, start=1):
            text = _clean_text(reason)
            if not text:
                continue
            index["rerank_reason"].append(
                _source_ref(
                    source_type="rerank_reason",
                    source_id=f"{source_id}:reason:{reason_index}",
                    source_label=text,
                    confidence=0.75,
                    detail={"reason": text, "shop_id": shop_id},
                )
            )

    for claim in evidence_claims or []:
        claim_map = _as_mapping(claim)
        chunk_id = str(claim_map.get("chunk_id") or claim_map.get("evidence_id") or "").strip()
        if not chunk_id:
            continue
        index["rag_evidence"].append(
            _source_ref(
                source_type="rag_evidence",
                source_id=chunk_id,
                source_label=_clean_text(claim_map.get("claim") or claim_map.get("support_text")) or None,
                confidence=float(claim_map.get("confidence") or 0.0),
                detail=claim_map,
            )
        )

    facet_bundle = _as_mapping(facet_result_bundle)
    for tool_item in facet_bundle.get("tool_results") or []:
        tool_map = _as_mapping(tool_item)
        tool_name = _clean_text(tool_map.get("tool_name") or tool_map.get("facet") or "tool_result") or "tool_result"
        source_kind = "realtime_tool" if tool_name in {"check_open_status", "get_coupon_list", "get_distance_eta", "create_booking", "create_order", "get_order_status"} else "tool_structured"
        source_id = str(tool_map.get("id") or tool_map.get("tool_id") or f"{tool_name}:{tool_map.get('shop_id') or 'na'}").strip()
        index[source_kind].append(
            _source_ref(
                source_type=source_kind,
                source_id=source_id,
                source_label=tool_name,
                confidence=0.9 if str(tool_map.get("status") or "").strip().lower() == "success" else 0.5,
                detail=tool_map,
            )
        )
    for key in ("coupon_result", "open_status_result", "distance_eta_result"):
        tool_map = _as_mapping(facet_bundle.get(key))
        if not tool_map:
            continue
        tool_name = {
            "coupon_result": "get_coupon_list",
            "open_status_result": "check_open_status",
            "distance_eta_result": "get_distance_eta",
        }[key]
        index["realtime_tool"].append(
            _source_ref(
                source_type="realtime_tool",
                source_id=str(tool_map.get("tool_id") or tool_map.get("shop_id") or key),
                source_label=tool_name,
                confidence=0.95,
                detail=tool_map,
            )
        )

    for tool_item in tool_results or []:
        tool_map = _as_mapping(tool_item)
        tool_name = _clean_text(tool_map.get("tool_name") or tool_map.get("facet") or "tool_result") or "tool_result"
        normalized_output = _as_mapping(tool_map.get("normalized_output"))
        normalized_data = _as_mapping(normalized_output.get("data")) or _as_mapping(tool_map.get("data"))
        source_kind = "realtime_tool" if tool_name in {"check_open_status", "get_coupon_list", "get_distance_eta", "create_booking", "create_order", "get_order_status"} else "tool_structured"
        source_id = str(tool_map.get("id") or tool_map.get("tool_id") or f"{tool_name}:{tool_map.get('shop_id') or normalized_data.get('shop_id') or 'na'}").strip()
        detail_payload = dict(tool_map)
        if normalized_output:
            detail_payload["normalized_output"] = normalized_output
        if normalized_data and "data" not in detail_payload:
            detail_payload["data"] = normalized_data
        index[source_kind].append(
            _source_ref(
                source_type=source_kind,
                source_id=source_id,
                source_label=tool_name,
                confidence=0.9 if str(tool_map.get("status") or "").strip().lower() == "success" else 0.5,
                detail=detail_payload,
            )
        )

    context_map = _as_mapping(answer_context)
    for key in ("current_shop", "selected_shop_name", "current_topic", "target_shop_name"):
        value = _clean_text(context_map.get(key))
        if not value:
            continue
        index["user_context"].append(
            _source_ref(
                source_type="user_context",
                source_id=f"context:{key}:{value}",
                source_label=value,
                confidence=0.5,
                detail={"key": key, "value": value},
            )
        )

    return index


def _matching_sources_for_claim(
    claim_type: str,
    claim_text: str,
    source_index: Mapping[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    compact = (_clean_text(claim_text) or "").replace(" ", "")
    sources: list[dict[str, Any]] = []
    facet_aliases = {
        "coupon": (("券", "优惠", "团购", "代金券"), ("coupon", "券", "优惠", "团购", "discount", "voucher")),
        "stock": (("库存", "余量", "剩余"), ("stock", "库存", "余量", "剩余")),
        "open_status": (("营业", "开门", "开着", "关门"), ("open_status", "open", "营业", "开门", "status")),
        "open_hours": (("营业时间", "开门时间", "时间"), ("open_hours", "hours", "time", "营业时间", "开门时间")),
        "distance_eta": (("距离", "公里", "路程", "导航"), ("distance", "distance_km", "公里", "路程", "导航")),
        "price": (("人均", "价格", "预算", "元"), ("avg_price", "price", "人均", "价格", "预算", "元")),
        "rating": (("评分", "分", "星"), ("rating", "score", "分", "评分", "星")),
        "address": (("地址", "位置", "位于"), ("address", "location", "地址", "位置", "位于")),
        "booking": (("订座", "预订", "预约"), ("booking", "reservation", "create_booking", "订座", "预订", "预约")),
        "order": (("下单", "订单"), ("order", "create_order", "下单", "订单", "取消订单")),
        "payment": (("支付", "付款", "买单", "收款"), ("payment", "支付", "付款", "买单", "收款")),
        "refund": (("退款", "退费", "退钱"), ("refund", "退款", "退费", "退钱")),
        "phone": (("电话", "联系电话", "手机", "号码"), ("phone", "电话", "联系电话", "手机", "号码")),
        "delivery_eta": (("配送", "送达", "外卖", "多久到", "到店", "送到"), ("delivery", "delivery_eta", "送达", "配送", "外卖", "到店", "送到")),
    }
    for source_type in ("realtime_tool", "tool_structured", "rag_evidence", "rerank_reason", "user_context", "template"):
        for ref in source_index.get(source_type, []):
            label = _clean_text(ref.get("source_label"))
            detail_text = _flatten_text(ref.get("detail"))
            detail_map = _as_mapping(ref.get("detail"))
            haystack = f"{label} {detail_text} {_clean_text(detail_map.get('data'))}".strip()
            if not haystack:
                continue
            if claim_type in {"coupon", "stock", "open_status", "open_hours", "distance_eta", "price", "rating", "address", "booking", "order", "payment", "refund", "phone", "delivery_eta"}:
                claim_keywords, source_keywords = facet_aliases.get(claim_type, ((), ()))
                if any(token in compact for token in claim_keywords) and any(token in haystack.replace(" ", "") for token in source_keywords):
                    sources.append(dict(ref))
            elif claim_type in {"environment", "taste", "service", "pitfall"}:
                if any(token in compact for token in ("环境", "氛围", "安静", "吵", "包间", "口味", "味道", "服务", "态度", "踩坑", "坑")) and any(
                    token in haystack.replace(" ", "") for token in ("环境", "氛围", "安静", "吵", "包间", "口味", "味道", "服务", "态度", "踩坑", "坑", "评价", "笔记")
                ):
                    sources.append(dict(ref))
            elif claim_type == "scene_fit":
                if any(token in compact for token in ("约会", "长辈", "带娃", "家庭", "安静", "包间")) and any(
                    token in haystack.replace(" ", "") for token in ("适合", "家庭", "长辈", "约会", "带娃", "安静", "包间")
                ):
                    sources.append(dict(ref))
            elif claim_type in {"recommendation", "comparison"}:
                if source_type in {"rerank_reason", "rag_evidence", "tool_structured"}:
                    sources.append(dict(ref))
            else:
                if source_type in {"template", "user_context"} and _is_fallback_claim(compact):
                    sources.append(dict(ref))
    return list({item["source_id"]: item for item in sources}.values())


def build_claim_bindings(
    *,
    answer_text: str,
    answer_contract: Any | None,
    ranked_candidates: Sequence[Mapping[str, Any] | Any] | None = None,
    evidence_claims: Sequence[Mapping[str, Any] | Any] | None = None,
    evidence_pack: Any | None = None,
    facet_result_bundle: Any | None = None,
    tool_results: Sequence[Mapping[str, Any] | Any] | None = None,
    answer_context: Mapping[str, Any] | Any | None = None,
    route_gate: Mapping[str, Any] | Any | None = None,
    review_report: Mapping[str, Any] | Any | None = None,
) -> list[dict[str, Any]]:
    fragments = _claim_fragments(answer_text)
    if not fragments:
        return []

    source_index = _source_index_from_context(
        ranked_candidates=ranked_candidates,
        evidence_claims=evidence_claims,
        facet_result_bundle=facet_result_bundle,
        tool_results=tool_results,
        answer_context=answer_context,
    )
    context_map = _as_mapping(answer_context)
    answer_style = _clean_text(_as_mapping(answer_contract).get("answer_style") if answer_contract is not None else context_map.get("answer_style"))
    route_map = _as_mapping(route_gate)
    approval_required = bool(
        context_map.get("approval_required")
        or route_map.get("approval_required")
        or _as_mapping(review_report).get("approval_required")
    )
    claim_bindings: list[dict[str, Any]] = []
    for index, fragment in enumerate(fragments, start=1):
        claim_type = _claim_type(fragment)
        policy = claim_policy_for_facet(claim_type, answer_style=answer_style, approval_required=approval_required)
        matching_sources = _matching_sources_for_claim(claim_type, fragment, source_index)
        source_ids = [str(item.get("source_id")) for item in matching_sources if str(item.get("source_id") or "").strip()]
        source_types_present = {
            str(item.get("source_type") or "").strip().lower()
            for item in matching_sources
            if str(item.get("source_type") or "").strip()
        }
        primary_source_type = "llm_generated"
        support_status = "unsupported"
        entity_id, shop_id, entity_name = _entity_info_from_sources(matching_sources, answer_context=answer_context)
        if _is_fallback_claim(fragment):
            primary_source_type = "template"
            support_status = "supported"
            if not source_ids:
                source_ids = ["template:fallback"]
            matching_sources = [
                {
                    "source_type": "template",
                    "source_id": "template:fallback",
                    "source_label": "fallback_message",
                    "confidence": 1.0,
                }
            ]
        elif matching_sources:
            if policy.support_mode == "all":
                required_source_types = {source_type for source_type in policy.required_source_types if source_type}
                if required_source_types.issubset(source_types_present):
                    support_status = "supported"
                    for preferred_source_type in policy.allowed_primary_source_types:
                        if preferred_source_type in source_types_present:
                            primary_source_type = preferred_source_type
                            break
                    else:
                        primary_source_type = str(matching_sources[0].get("source_type") or "llm_generated")
                else:
                    support_status = "partial"
                    for preferred_source_type in policy.allowed_primary_source_types:
                        if preferred_source_type in source_types_present:
                            primary_source_type = preferred_source_type
                            break
                    else:
                        primary_source_type = str(matching_sources[0].get("source_type") or "llm_generated")
            else:
                for preferred_source_type in policy.allowed_primary_source_types:
                    if preferred_source_type in source_types_present:
                        primary_source_type = preferred_source_type
                        break
                else:
                    primary_source_type = str(matching_sources[0].get("source_type") or "llm_generated")
                support_status = "supported" if primary_source_type != "llm_generated" else "partial"
        else:
            if any(token in (_clean_text(fragment) or "").replace(" ", "") for token in ("推荐", "适合", "可以", "建议")):
                primary_source_type = "template"
                support_status = "supported"
            else:
                support_status = "unsupported"

        if policy.high_risk and support_status == "supported" and primary_source_type not in policy.allowed_primary_source_types and not _is_fallback_claim(fragment):
            support_status = "partial"
        if policy.high_risk and approval_required and support_status == "supported" and not _is_fallback_claim(fragment):
            if primary_source_type not in {"tool_structured", "realtime_tool", "template"}:
                support_status = "partial"

        claim_bindings.append(
            {
                "claim_id": f"claim-{index}",
                "claim_type": claim_type,
                "facet": policy.facet,
                "text": fragment,
                "risk_level": policy.risk_level,
                "entity_id": entity_id,
                "shop_id": shop_id,
                "entity_name": entity_name,
                "primary_source_type": primary_source_type,
                "source_ids": list(dict.fromkeys(source_ids)),
                "supporting_sources": matching_sources,
                "support_status": support_status,
                "extra": {
                    "required_source_types": list(policy.required_source_types),
                    "allowed_primary_source_types": list(policy.allowed_primary_source_types),
                    "support_mode": policy.support_mode,
                    "high_risk": policy.high_risk,
                    "needs_entity_binding": policy.needs_entity_binding,
                },
            }
        )

    return claim_bindings


def summarize_claim_bindings(claim_bindings: Sequence[Mapping[str, Any] | Any]) -> dict[str, Any]:
    bindings = [_as_mapping(binding) for binding in claim_bindings or []]
    total = len(bindings)
    supported = sum(1 for binding in bindings if str(binding.get("support_status") or "").strip().lower() == "supported")
    partial = sum(1 for binding in bindings if str(binding.get("support_status") or "").strip().lower() == "partial")
    unsupported = sum(1 for binding in bindings if str(binding.get("support_status") or "").strip().lower() == "unsupported")
    conflicted = sum(1 for binding in bindings if str(binding.get("support_status") or "").strip().lower() == "conflicted")
    facet_counts: dict[str, int] = {}
    risk_level_counts: dict[str, int] = {}
    entity_count = 0
    seen_entity_ids: set[str] = set()
    for binding in bindings:
        facet = str(binding.get("facet") or binding.get("claim_type") or "generic").strip().lower() or "generic"
        facet_counts[facet] = facet_counts.get(facet, 0) + 1
        risk_level = str(binding.get("risk_level") or "low").strip().lower() or "low"
        risk_level_counts[risk_level] = risk_level_counts.get(risk_level, 0) + 1
        entity_id = str(binding.get("entity_id") or "").strip()
        if entity_id and entity_id not in seen_entity_ids:
            seen_entity_ids.add(entity_id)
            entity_count += 1
    return {
        "claim_count": total,
        "supported_claim_count": supported,
        "partial_claim_count": partial,
        "unsupported_claim_count": unsupported,
        "conflicted_claim_count": conflicted,
        "unsupported_claim_rate": unsupported / max(1, total),
        "support_rate": supported / max(1, total),
        "facet_distribution": dict(sorted(facet_counts.items())),
        "risk_level_distribution": dict(sorted(risk_level_counts.items())),
        "entity_count": entity_count,
    }


def is_high_risk_answer_context(
    *,
    answer_contract: Any | None,
    answer_context: Mapping[str, Any] | Any | None = None,
    route_gate: Mapping[str, Any] | Any | None = None,
    review_report: Mapping[str, Any] | Any | None = None,
    tool_results: Sequence[Mapping[str, Any] | Any] | None = None,
    claim_bindings: Sequence[Mapping[str, Any] | Any] | None = None,
) -> bool:
    contract = _as_mapping(answer_contract)
    context = _as_mapping(answer_context)
    route_map = _as_mapping(route_gate)
    review_map = _as_mapping(review_report)
    tool_names = {
        _clean_text(_as_mapping(item).get("tool_name") or _as_mapping(item).get("facet"))
        for item in (tool_results or [])
        if _clean_text(_as_mapping(item).get("tool_name") or _as_mapping(item).get("facet"))
    }
    if contract.get("realtime_required") or context.get("realtime_required"):
        return True
    if _clean_text(contract.get("answer_style")) in {"coupon_only", "open_status_only", "distance_only"}:
        return True
    if bool(context.get("approval_required") or route_map.get("approval_required") or review_map.get("approval_required")):
        return True
    if any(name in {"create_booking", "create_order", "cancel_order", "refund_order", "get_order_status"} for name in tool_names):
        return True
    if any(
        token in (_clean_text(contract.get("original_query") or context.get("raw_query") or "") or "").replace(" ", "")
        for token in ("订座", "预订", "预约", "下单", "支付", "买单", "退款", "取消订单", "订单", "券", "营业", "距离")
    ):
        return True
    if claim_bindings and any(
        (
            str(_as_mapping(binding).get("risk_level") or "").strip().lower() == "high"
            or str(_as_mapping(binding).get("facet") or _as_mapping(binding).get("claim_type") or "").strip().lower() in HIGH_RISK_FACETS
            or is_high_risk_facet(
                _as_mapping(binding).get("facet") or _as_mapping(binding).get("claim_type"),
                answer_style=contract.get("answer_style"),
                approval_required=bool(context.get("approval_required") or route_map.get("approval_required") or review_map.get("approval_required")),
            )
        )
        for binding in claim_bindings
    ):
        return True
    return False


def build_high_risk_fallback_message(
    *,
    answer_contract: Any | None,
    answer_context: Mapping[str, Any] | Any | None = None,
    issues: Sequence[str] | None = None,
) -> str:
    contract = _as_mapping(answer_contract)
    answer_style = _clean_text(contract.get("answer_style"))
    context = _as_mapping(answer_context)
    raw_query = _clean_text(contract.get("original_query") or context.get("raw_query") or "")
    issue_set = {str(item).strip().lower() for item in (issues or []) if str(item).strip()}
    if "should_clarify_but_answered" in issue_set or "approval_required_violation" in issue_set:
        return "这个问题还需要你补充关键信息，我先不直接确认交易。"
    if answer_style == "coupon_only":
        topic = _clean_text(context.get("current_shop") or context.get("current_topic") or raw_query) or "这家店"
        return f"{topic}的实时券信息暂时无法确认，我先不直接给肯定结论。"
    if answer_style == "open_status_only":
        topic = _clean_text(context.get("current_shop") or context.get("current_topic") or raw_query) or "这家店"
        return f"{topic}的当前营业状态暂时无法确认，我先建议你再核实一次。"
    if answer_style == "distance_only":
        topic = _clean_text(context.get("current_shop") or context.get("current_topic") or raw_query) or "这家店"
        return f"{topic}的距离信息暂时无法稳定确认，我先不直接给具体结论。"
    if answer_style in {"comparison", "multi_shop_recommendation"}:
        return "当前证据还不够稳定，我先给你保守的部分判断。"
    if answer_style == "single_shop_review":
        topic = _clean_text(context.get("current_shop") or context.get("current_topic") or raw_query) or "这家店"
        return f"我目前没有足够可靠的评价证据来稳定判断{topic}，先不直接下结论。"
    return "当前证据不足，我先不直接下结论。"
