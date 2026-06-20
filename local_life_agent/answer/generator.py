"""Deterministic answer generator for the single-shop multi-facet flow."""

from __future__ import annotations

from typing import Any


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


def _shop_display_name(evidence: dict[str, Any]) -> str:
    snapshot = evidence.get("ranking_snapshot") or {}
    if snapshot.get("shop_name"):
        return snapshot["shop_name"]
    for item in evidence.get("evidence_items") or []:
        if isinstance(item, dict) and item.get("shop_name"):
            return item["shop_name"]
    for item in evidence.get("unknown_items") or []:
        if isinstance(item, dict) and item.get("shop_name"):
            return item["shop_name"]
    return "这家店"


def _facet_sentence(facet: str, snapshot: dict[str, Any]) -> str:
    status = snapshot.get("facet_statuses", {}).get(facet, snapshot.get("status", "unknown"))
    shop_name = snapshot.get("shop_name") or "这家店"

    if facet == "coupon":
        titles = snapshot.get("coupon_titles") or []
        if status == "ok":
            if titles:
                top_titles = "、".join(titles[:3])
                return f"{shop_name}有券，当前可用券有：{top_titles}"
            return f"{shop_name}有可用券"
        if status == "empty":
            return f"{shop_name}当前暂无可用券"
        if status == "failed":
            return f"获取{shop_name}优惠券信息失败，建议稍后再试"
        if status == "circuit_open":
            return f"{shop_name}优惠券服务暂时不可用，请稍后再试"
        return f"暂时无法确认{shop_name}的优惠券情况"

    if facet == "open_status":
        open_status = str(snapshot.get("open_status", "unknown") or "unknown")
        if status == "ok":
            if open_status == "open":
                return f"{shop_name}目前营业中"
            if open_status == "closed":
                return f"{shop_name}目前已打烊"
            return f"{shop_name}当前营业状态未知"
        if status == "failed":
            return f"获取{shop_name}营业状态失败，建议稍后再试"
        if status == "circuit_open":
            return f"{shop_name}营业状态服务暂时不可用，请稍后再试"
        return f"暂时无法确认{shop_name}的营业状态"

    if facet == "distance":
        distance_km = snapshot.get("distance_km")
        eta_minutes = snapshot.get("eta_minutes")
        if status == "ok" and distance_km is not None:
            if eta_minutes is not None:
                return f"{shop_name}距离约{distance_km}公里，预计{eta_minutes}分钟可到"
            return f"{shop_name}距离约{distance_km}公里"
        if status == "failed":
            return f"获取{shop_name}距离信息失败，建议稍后再试"
        if status == "circuit_open":
            return f"{shop_name}距离服务暂时不可用，请稍后再试"
        return f"暂时无法确认{shop_name}的距离"

    return ""


def generate_answer(answer_plan: dict, evidence: dict) -> str:
    """Generate a final natural language answer."""
    answer_plan = _to_dict(answer_plan)
    evidence = _to_dict(evidence)
    snapshot = evidence.get("ranking_snapshot") or {}
    shop_name = _shop_display_name(evidence)
    status = snapshot.get("status", "unknown")
    facet_results = snapshot.get("facet_results") or []

    if facet_results:
        parts = []
        for item in facet_results:
            facet = item.get("facet", "")
            sentence = _facet_sentence(facet, snapshot)
            if sentence:
                parts.append(sentence)
        if parts:
            return "；".join(parts) + "。"

    if status == "ok":
        return f"{shop_name}信息已确认。"
    if status == "empty":
        return f"{shop_name}当前暂无可用信息。"
    if status == "failed":
        return f"获取{shop_name}信息失败，建议稍后再试。"
    if status == "circuit_open":
        return f"{shop_name}相关服务暂时不可用，请稍后再试。"

    if answer_plan.get("answer_type") == "clarification":
        clarification = answer_plan.get("response_sections", [{}])[0].get("clarification", "")
        if clarification:
            return clarification
        return f"请提供更完整的{shop_name}店名。"

    return f"暂时无法确认{shop_name}的相关信息。"
