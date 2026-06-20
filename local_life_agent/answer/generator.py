"""Deterministic answer generator for local-life flows."""

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
        return str(snapshot["shop_name"])
    for item in evidence.get("evidence_items") or []:
        if isinstance(item, dict) and item.get("shop_name"):
            return str(item["shop_name"])
    for item in evidence.get("unknown_items") or []:
        if isinstance(item, dict) and item.get("shop_name"):
            return str(item["shop_name"])
    return "这家店"


def _facet_sentence(facet: str, snapshot: dict[str, Any]) -> str:
    status = snapshot.get("facet_statuses", {}).get(facet, snapshot.get("status", "unknown"))
    shop_name = snapshot.get("shop_name") or "这家店"

    if facet == "coupon":
        titles = snapshot.get("coupon_titles") or []
        if status == "ok":
            if titles:
                top_titles = "、".join(str(title) for title in titles[:3])
                return f"{shop_name}有券，当前可用券包括：{top_titles}"
            return f"{shop_name}有可用券"
        if status == "empty":
            return f"{shop_name}当前暂无可用券"
        if status == "failed":
            return f"获取{shop_name}优惠券信息失败，建议稍后再试"
        if status == "circuit_open":
            return f"{shop_name}优惠券服务暂时不可用，请稍后再试"
        return f"暂时无法确认{shop_name}的优惠情况"

    if facet == "open_status":
        open_status = str(snapshot.get("open_status", "unknown") or "unknown").lower()
        if status == "ok":
            if open_status == "open":
                return f"{shop_name}目前营业中"
            if open_status == "closed":
                return f"{shop_name}目前已打烊"
            return f"{shop_name}营业状态暂时无法确认"
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


def _recommendation_sentence(ranked_items: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for idx, item in enumerate(ranked_items[:3], start=1):
        shop_name = str(item.get("shop_name", "")).strip()
        if not shop_name:
            continue
        details: list[str] = []
        distance_km = item.get("distance_km")
        eta_minutes = item.get("eta_minutes")
        open_status = str(item.get("open_status", "") or "").lower()
        coupon_count = item.get("coupon_count")
        rating = item.get("rating")
        if distance_km is not None:
            if eta_minutes is not None:
                details.append(f"距离约{distance_km}公里，预计{eta_minutes}分钟可到")
            else:
                details.append(f"距离约{distance_km}公里")
        if open_status == "open":
            details.append("目前营业中")
        elif open_status == "closed":
            details.append("目前已打烊")
        if coupon_count is not None:
            try:
                count = int(coupon_count)
            except Exception:
                count = None
            if count is not None:
                details.append("有券" if count > 0 else "暂无可用券")
        if rating is not None:
            details.append(f"评分{rating}")
        tail = "，".join(details)
        parts.append(f"{idx}. {shop_name}" + (f"，{tail}" if tail else ""))
    if not parts:
        return "暂时没有找到符合条件的店，建议稍后再试或放宽一点条件。"
    prefix = "附近我推荐这3家："
    if len(parts) < 3:
        prefix = "符合条件的店较少，我先推荐这几家："
    return prefix + "；".join(parts) + "。"


def _comparison_sentence(evidence: dict[str, Any]) -> str:
    matrix = evidence.get("comparison_matrix") or {}
    rows = matrix.get("rows") or []
    if not rows:
        return "暂时没有足够信息做对比。"

    ordered_rows = [row for row in rows if isinstance(row, dict)]
    names = [str(row.get("shop_name", "")).strip() or str(row.get("shop_id", "")).strip() for row in ordered_rows]
    parts: list[str] = []
    if names:
        parts.append("对比了" + "、".join(names) + "。")

    for idx, row in enumerate(ordered_rows, start=1):
        shop_name = str(row.get("shop_name", "")).strip() or str(row.get("shop_id", "")).strip() or f"第{idx}家"
        row_parts: list[str] = []
        rating = row.get("rating")
        distance_km = row.get("distance_km")
        eta_minutes = row.get("eta_minutes")
        open_status = str(row.get("open_status", "unknown") or "unknown").lower()
        coupon_status = str(row.get("coupon_status", "unknown") or "unknown")

        if rating is not None:
            row_parts.append(f"评分{rating}")
        if distance_km is not None:
            if eta_minutes is not None:
                row_parts.append(f"距离约{distance_km}公里，预计{eta_minutes}分钟可到")
            else:
                row_parts.append(f"距离约{distance_km}公里")
        if open_status == "open":
            row_parts.append("营业中")
        elif open_status == "closed":
            row_parts.append("已打烊")
        else:
            row_parts.append("营业状态暂无法确认")

        if coupon_status == "has_coupon":
            titles = row.get("coupon_titles") or []
            if titles:
                row_parts.append("有券：" + "、".join(str(title) for title in titles[:3]))
            else:
                row_parts.append("有券")
        elif coupon_status == "empty":
            row_parts.append("暂无可用券")
        else:
            row_parts.append("优惠暂无法确认")

        parts.append(f"{shop_name}：" + "，".join(row_parts) + "。")

    overall_ranked = matrix.get("overall_ranked") or []
    if overall_ranked:
        best = overall_ranked[0] if isinstance(overall_ranked[0], dict) else {}
        best_name = str(best.get("shop_name", "")).strip() or str(best.get("shop_id", "")).strip()
        if best_name:
            parts.append(f"综合来看，{best_name}目前更占优。")

    winners = matrix.get("dimension_winners") or {}
    winner_notes: list[str] = []
    for dim, label in (("rating", "评分"), ("distance", "距离"), ("open_status", "营业状态"), ("coupon", "优惠")):
        items = winners.get(dim) or []
        names = [str(item.get("shop_name", "")).strip() or str(item.get("shop_id", "")).strip() for item in items if isinstance(item, dict)]
        if names:
            winner_notes.append(f"{label}领先的是" + "、".join(names))
    if winner_notes:
        parts.append("；".join(winner_notes) + "。")

    notes = [str(item).strip() for item in (matrix.get("uncertainty_notes") or []) if str(item).strip()]
    if notes:
        parts.append("不确定项：" + "；".join(notes[:4]) + "。")

    return "".join(parts)


def generate_answer(answer_plan: dict, evidence: dict) -> str:
    """Generate a final natural language answer."""
    answer_plan = _to_dict(answer_plan)
    evidence = _to_dict(evidence)
    snapshot = evidence.get("ranking_snapshot") or {}
    facet_results = evidence.get("facet_results") or snapshot.get("facet_results") or []
    status = snapshot.get("status", "unknown")

    comparison_matrix = evidence.get("comparison_matrix") or {}
    if answer_plan.get("answer_type") == "comparison" or (comparison_matrix.get("rows") or []):
        return _comparison_sentence(evidence)

    if answer_plan.get("answer_type") == "recommendation" or snapshot.get("ranked"):
        ranked_items = snapshot.get("ranked") or snapshot.get("ranked_shops") or []
        return _recommendation_sentence([item for item in ranked_items if isinstance(item, dict)])

    shop_name = _shop_display_name(evidence)

    if facet_results:
        parts = []
        for item in facet_results:
            facet = item.get("facet", "")
            sentence = _facet_sentence(facet, snapshot)
            if sentence:
                parts.append(sentence)
        if parts:
            return "，".join(parts) + "。"

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
