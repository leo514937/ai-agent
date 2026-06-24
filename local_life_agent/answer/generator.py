"""Deterministic answer generator for local-life flows."""

from __future__ import annotations

import re
from typing import Any
from ..domain.schemas import DecisionPlan
from .candidate_decision import (
    CandidateEvidenceCollector,
    CandidateEvaluator,
    build_candidate_decision_plan,
    map_candidate_decision_plan_to_decision_plan,
)

def _get_tool_results_from_evidence(evidence: dict) -> dict[str, Any]:
    # First, check if tool_results is directly in evidence
    tr = evidence.get("tool_results")
    if tr:
        return tr
    
    reconstructed = {}
    
    # Check comparison_matrix
    matrix = evidence.get("comparison_matrix") or {}
    rows = matrix.get("rows") or []
    for row in rows:
        sid = row.get("shop_id")
        if not sid:
            continue
        
        # detail
        detail_status = row.get("detail_status")
        if not detail_status:
            detail_status = "ok" if row.get("rating") is not None else "unknown"
        reconstructed[f"call_detail_{sid}"] = {
            "tool_name": "get_shop_detail",
            "result_status": detail_status,
            "shop_id": sid,
            "data": {
                "shop_id": sid,
                "shop_name": row.get("shop_name", ""),
                "category": row.get("category", ""),
                "avg_price": row.get("avg_price"),
                "rating": row.get("rating"),
                "tags": row.get("tags", []),
            }
        }
        
        # open_status
        open_val = row.get("open_status", "unknown")
        reconstructed[f"call_open_{sid}"] = {
            "tool_name": "check_open_status",
            "result_status": "ok" if open_val in ("open", "closed") else "unknown",
            "shop_id": sid,
            "data": {
                "shop_id": sid,
                "shop_name": row.get("shop_name", ""),
                "open_status": open_val,
            }
        }
        
        # coupon
        c_status = row.get("coupon_status", "unknown")
        c_res = "ok" if c_status == "has_coupon" else ("empty" if c_status == "empty" else "unknown")
        reconstructed[f"call_coupon_{sid}"] = {
            "tool_name": "get_coupon_list",
            "result_status": c_res,
            "shop_id": sid,
            "data": [{"title": t} for t in row.get("coupon_titles", [])] if c_status == "has_coupon" else []
        }
        
        # distance
        dist_km = row.get("distance_km")
        reconstructed[f"call_distance_{sid}"] = {
            "tool_name": "get_distance_eta",
            "result_status": "ok" if dist_km is not None else "unknown",
            "shop_id": sid,
            "data": {
                "shop_id": sid,
                "shop_name": row.get("shop_name", ""),
                "distance_km": dist_km,
                "eta_minutes": row.get("eta_minutes"),
            }
        }
        
    # Check ranking_snapshot
    snapshot = evidence.get("ranking_snapshot") or {}
    ranked = snapshot.get("ranked") or snapshot.get("ranked_shops") or []
    for item in ranked:
        sid = item.get("shop_id")
        if not sid:
            continue
        
        if f"call_detail_{sid}" in reconstructed:
            # Already reconstructed from comparison matrix
            continue
            
        reconstructed[f"call_detail_{sid}"] = {
            "tool_name": "get_shop_detail",
            "result_status": "ok" if item.get("rating") is not None else "unknown",
            "shop_id": sid,
            "data": {
                "shop_id": sid,
                "shop_name": item.get("shop_name", ""),
                "category": item.get("category", ""),
                "avg_price": item.get("avg_price"),
                "rating": item.get("rating"),
                "tags": item.get("tags", []),
            }
        }
        
        open_val = item.get("open_status", "unknown")
        reconstructed[f"call_open_{sid}"] = {
            "tool_name": "check_open_status",
            "result_status": "ok" if open_val in ("open", "closed") else "unknown",
            "shop_id": sid,
            "data": {
                "shop_id": sid,
                "shop_name": item.get("shop_name", ""),
                "open_status": open_val,
            }
        }
        
        coupon_count = item.get("coupon_count")
        c_status = "has_coupon" if coupon_count is not None and coupon_count > 0 else ("empty" if coupon_count == 0 else "unknown")
        reconstructed[f"call_coupon_{sid}"] = {
            "tool_name": "get_coupon_list",
            "result_status": "ok" if c_status == "has_coupon" else ("empty" if c_status == "empty" else "unknown"),
            "shop_id": sid,
            "data": [{"title": "优惠券"}] if c_status == "has_coupon" else []
        }
        
        dist_km = item.get("distance_km")
        reconstructed[f"call_distance_{sid}"] = {
            "tool_name": "get_distance_eta",
            "result_status": "ok" if dist_km is not None else "unknown",
            "shop_id": sid,
            "data": {
                "shop_id": sid,
                "shop_name": item.get("shop_name", ""),
                "distance_km": dist_km,
                "eta_minutes": item.get("eta_minutes"),
            }
        }
        
    return reconstructed


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


def _normalize_coupon_phrase(text: str) -> str:
    if not text:
        return text
    text = re.sub(r"有(?:可用)?优惠券(?:可用|可领|可用券)?", "有券", text)
    text = re.sub(r"当前有券可领", "有券", text)
    return text


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
        parts.append(f"{idx}. {shop_name}" + (f"：{tail}" if tail else ""))
    if not parts:
        return "暂时没有找到符合条件的店，建议稍后再试或者放宽一点条件。"
    count = len(parts)
    from ..config import RECOMMENDATION_FINAL_TOP_K
    if count < RECOMMENDATION_FINAL_TOP_K:
        prefix = f"符合条件的店较少，我先推荐这{count}家："
    else:
        prefix = f"附近我推荐这{count}家："
    return prefix + "；".join(parts) + "。"


def _comparison_sentence(evidence: dict[str, Any]) -> str:
    matrix = evidence.get("comparison_matrix") or {}
    rows = [row for row in (matrix.get("rows") or []) if isinstance(row, dict)]
    if not rows:
        return "暂时没有足够信息做对比。"

    names = [str(row.get("shop_name", "")).strip() or str(row.get("shop_id", "")).strip() for row in rows]
    parts: list[str] = []
    if names:
        parts.append("对比的是" + "、".join(names) + "。")

    all_unknown = True
    for row in rows:
        row_parts: list[str] = []
        shop_name = str(row.get("shop_name", "")).strip() or str(row.get("shop_id", "")).strip() or "这家店"
        rating = row.get("rating")
        distance_km = row.get("distance_km")
        eta_minutes = row.get("eta_minutes")
        open_status = str(row.get("open_status", "unknown") or "unknown").lower()
        coupon_status = str(row.get("coupon_status", "unknown") or "unknown")

        if rating is not None:
            all_unknown = False
            row_parts.append(f"评分{rating}")
        if distance_km is not None:
            all_unknown = False
            if eta_minutes is not None:
                row_parts.append(f"距离约{distance_km}公里，预计{eta_minutes}分钟可到")
            else:
                row_parts.append(f"距离约{distance_km}公里")
        if open_status == "open":
            all_unknown = False
            row_parts.append("目前营业中")
        elif open_status == "closed":
            all_unknown = False
            row_parts.append("目前已打烊")
        else:
            row_parts.append("营业状态暂时无法确认")

        if coupon_status == "has_coupon":
            all_unknown = False
            titles = row.get("coupon_titles") or []
            if titles:
                row_parts.append("有券：" + "、".join(str(title) for title in titles[:3]))
            else:
                row_parts.append("有券")
        elif coupon_status == "empty":
            row_parts.append("暂无可用券")
        else:
            row_parts.append("优惠暂时无法确认")

        parts.append(f"{shop_name}：" + "，".join(row_parts) + "。")

    if all_unknown:
        parts.append("目前可验证信息不足，暂时不能判断谁更好。")
        return "".join(parts)

    overall_ranked = [row for row in (matrix.get("overall_ranked") or []) if isinstance(row, dict)]
    if len(overall_ranked) >= 2:
        best = overall_ranked[0]
        runner_up = overall_ranked[1]
        best_name = str(best.get("shop_name", "")).strip() or str(best.get("shop_id", "")).strip()
        if best_name and best.get("known_dimensions", 0) and best.get("overall_score", 0) != runner_up.get("overall_score", 0):
            parts.append(f"在已知信息里，{best_name}相对更靠前。")

    winners = matrix.get("dimension_winners") or {}
    winner_notes: list[str] = []
    for dim, label in (("rating", "评分"), ("distance", "距离"), ("open_status", "营业状态"), ("coupon", "优惠")):
        items = winners.get(dim) or []
        names = [str(item.get("shop_name", "")).strip() or str(item.get("shop_id", "")).strip() for item in items if isinstance(item, dict)]
        if names:
            if dim == "open_status" and len(names) > 1:
                winner_notes.append("营业状态都在营业中")
            else:
                winner_notes.append(f"{label}领先的是" + "、".join(names))
    if winner_notes:
        parts.append("；".join(winner_notes) + "。")

    notes = [str(item).strip() for item in (matrix.get("uncertainty_notes") or []) if str(item).strip()]
    if notes:
        parts.append("不确定项：" + "；".join(notes[:4]) + "。")

    return "".join(parts)


def _build_decision_plan(
    answer_plan: dict,
    evidence: dict,
    *,
    conversation_continuity: dict[str, Any] | None = None,
) -> DecisionPlan:
    ap = _to_dict(answer_plan)
    ev = _to_dict(evidence)

    answer_type = ap.get("answer_type", "general")
    comparison_matrix = ev.get("comparison_matrix") or {}
    ranking_snapshot = ev.get("ranking_snapshot") or {}

    decision_type = None
    if answer_type == "comparison" or (comparison_matrix and (comparison_matrix.get("rows") or comparison_matrix.get("overall_ranked"))):
        decision_type = "comparison"
    elif answer_type == "recommendation" or (ranking_snapshot and ("ranked" in ranking_snapshot or "ranked_shops" in ranking_snapshot)):
        decision_type = "recommendation"

    if decision_type in ("recommendation", "comparison"):
        # 1. Extract shop_ids
        shop_ids = []
        if decision_type == "comparison":
            rows = comparison_matrix.get("rows") or []
            shop_ids = [str(r.get("shop_id", "")) for r in rows if isinstance(r, dict) and r.get("shop_id")]
            if not shop_ids:
                shop_ids = [str(sid) for sid in ev.get("target_shop_ids", []) or [] if str(sid).strip()]
        else: # recommendation
            ranked = ranking_snapshot.get("ranked") or ranking_snapshot.get("ranked_shops") or []
            shop_ids = [str(r.get("shop_id", "")) for r in ranked if isinstance(r, dict) and r.get("shop_id")]
            if not shop_ids:
                last_rec = ev.get("last_recommendation_list") or []
                shop_ids = [str(r.get("shop_id", "")) for r in last_rec if isinstance(r, dict) and r.get("shop_id")]
            if not shop_ids:
                shop_ids = [str(sid) for sid in ev.get("target_shop_ids", []) or [] if str(sid).strip()]

        # 2. Extract/reconstruct tool_results
        tool_results = ev.get("tool_results") or _get_tool_results_from_evidence(ev)

        # 3. Collector
        collector = CandidateEvidenceCollector()
        evidences = collector.collect(shop_ids, tool_results)

        # 4. Evaluator
        evaluator = CandidateEvaluator()
        preferences = {
            "query_terms": ap.get("query_terms") or ranking_snapshot.get("query_terms") or [],
            "scene_terms": ap.get("scene_terms") or ranking_snapshot.get("scene_terms") or [],
        }
        evaluations = evaluator.evaluate(evidences, decision_type, preferences)

        # 5. Build candidate plan
        forbidden_claims = list(ap.get("forbidden_claims", []))
        must_mention_unknowns = list(ap.get("must_mention_unknowns", []))
        location = ranking_snapshot.get("location") or "北京邮电大学"
        user_goal = ap.get("user_goal") or ""
        if not user_goal and preferences["query_terms"]:
            user_goal = " ".join(preferences["query_terms"])

        candidate_plan = build_candidate_decision_plan(
            decision_type=decision_type,
            user_goal=user_goal,
            location=location,
            evidences=evidences,
            evaluations=evaluations,
            forbidden_claims=forbidden_claims,
            must_mention_unknowns=must_mention_unknowns,
        )

        # 6. Map to legacy DecisionPlan
        plan = map_candidate_decision_plan_to_decision_plan(candidate_plan)
        if decision_type == "recommendation" and shop_ids:
            shop_id_to_index = {str(sid): i for i, sid in enumerate(shop_ids)}
            plan.overall_ranking.sort(key=lambda x: shop_id_to_index.get(str(x.get("shop_id", "")), 999))
            plan.selected_targets.sort(key=lambda x: shop_id_to_index.get(str(x.get("shop_id", "")), 999))
            if plan.overall_ranking:
                plan.main_recommendation = plan.overall_ranking[0]
        return plan

    selected_targets = []
    omitted_targets = []
    overall_ranking = []
    best_for = {}
    factual_points = []
    uncertainty_notes = []
    forbidden_claims = list(ap.get("forbidden_claims", []))
    main_recommendation = None

    if answer_type == "comparison" or (comparison_matrix and (comparison_matrix.get("rows") or comparison_matrix.get("overall_ranked"))):
        rows = comparison_matrix.get("rows", []) or []
        for row in rows:
            row_dict = _to_dict(row)
            if row_dict:
                selected_targets.append(row_dict)
                sname = row_dict.get("shop_name") or row_dict.get("shop_id") or "这家店"
                facts = []
                if row_dict.get("rating") is not None:
                    facts.append(f"评分为 {row_dict.get('rating')}")
                if row_dict.get("distance_km") is not None:
                    dist_str = f"距离为 {row_dict.get('distance_km')} 公里"
                    if row_dict.get("eta_minutes") is not None:
                        dist_str += f"，预计时间 {row_dict.get('eta_minutes')} 分钟"
                    facts.append(dist_str)
                if row_dict.get("open_status") == "open":
                    facts.append("营业状态为：目前营业中")
                elif row_dict.get("open_status") == "closed":
                    facts.append("营业状态为：目前已打烊")

                c_status = row_dict.get("coupon_status")
                if c_status == "has_coupon":
                    titles = row_dict.get("coupon_titles") or []
                    facts.append(f"有券：{'、'.join(str(t) for t in titles[:3])}" if titles else "有券")
                elif c_status == "empty":
                    facts.append("当前暂无可用优惠券")
                elif c_status == "unknown":
                    uncertainty_notes.append(f"无法确认 {sname} 的优惠情况")

                factual_points.append(f"{sname}: {'; '.join(facts)}")

        overall_ranked = comparison_matrix.get("overall_ranked") or []
        for item in overall_ranked:
            overall_ranking.append(_to_dict(item))

        winners = comparison_matrix.get("dimension_winners") or {}
        for dim, label in (("rating", "评分"), ("distance", "距离近"), ("open_status", "营业状态"), ("coupon", "省钱")):
            winners_list = winners.get(dim) or []
            if winners_list:
                for w in winners_list:
                    w_dict = _to_dict(w)
                    if w_dict.get("shop_id"):
                        best_for[label] = {
                            "shop_id": w_dict.get("shop_id"),
                            "shop_name": w_dict.get("shop_name"),
                            "reason": f"在{label}维度领先"
                        }

        notes = comparison_matrix.get("uncertainty_notes") or []
        for note in notes:
            uncertainty_notes.append(str(note))

    elif ranking_snapshot and ("ranked" in ranking_snapshot or "ranked_shops" in ranking_snapshot):
        ranked_shops = ranking_snapshot.get("ranked") or ranking_snapshot.get("ranked_shops") or []
        for item in ranked_shops:
            item_dict = _to_dict(item)
            if item_dict:
                selected_targets.append(item_dict)
                overall_ranking.append(item_dict)

                sname = item_dict.get("shop_name") or "这家店"
                facts = []
                if item_dict.get("rating") is not None:
                    facts.append(f"评分为 {item_dict.get('rating')}")
                if item_dict.get("distance_km") is not None:
                    dist_str = f"距离为 {item_dict.get('distance_km')} 公里"
                    if item_dict.get("eta_minutes") is not None:
                        dist_str += f"，预计时间 {item_dict.get('eta_minutes')} 分钟"
                    facts.append(dist_str)
                if item_dict.get("open_status") == "open":
                    facts.append("营业状态为：目前营业中")
                elif item_dict.get("open_status") == "closed":
                    facts.append("营业状态为：目前已打烊")

                coupon_count = item_dict.get("coupon_count")
                if coupon_count is not None:
                    try:
                        cnt = int(coupon_count)
                    except Exception:
                        cnt = 0
                    facts.append("有券" if cnt > 0 else "暂无可用券")
                factual_points.append(f"{sname}: {'; '.join(facts)}")

        if overall_ranking:
            main_recommendation = overall_ranking[0]

    else:
        facet_results = ev.get("facet_results") or []
        evidence_items = ev.get("evidence_items") or []
        unknown_items = ev.get("unknown_items") or []
        sname = _shop_display_name(ev)
        
        target_dict = {
            "shop_name": sname,
            "shop_id": ev.get("shop_id") or ev.get("target_shop_id") or "",
            "open_status": "unknown",
            "coupon_status": "unknown",
            "distance_km": None,
            "avg_price": None,
            "rating": None,
            "unknown_facts": [],
            "failed_facts": [],
        }

        # Check ranking_snapshot for basic values
        if ranking_snapshot:
            if ranking_snapshot.get("open_status"):
                target_dict["open_status"] = str(ranking_snapshot.get("open_status")).lower()
            if ranking_snapshot.get("coupon_status"):
                target_dict["coupon_status"] = str(ranking_snapshot.get("coupon_status")).lower()
            if ranking_snapshot.get("distance_km") is not None:
                target_dict["distance_km"] = ranking_snapshot.get("distance_km")
            if ranking_snapshot.get("avg_price") is not None:
                target_dict["avg_price"] = ranking_snapshot.get("avg_price")
            if ranking_snapshot.get("rating") is not None:
                target_dict["rating"] = ranking_snapshot.get("rating")

        # Overlay evidence_items values
        for ei in evidence_items:
            ei_dict = _to_dict(ei)
            facet = ei_dict.get("facet")
            val = ei_dict.get("value")
            if facet == "open_status" and val:
                target_dict["open_status"] = str(val).lower()
            elif facet == "coupon":
                if isinstance(val, list):
                    target_dict["coupon_status"] = "has_coupon" if val else "empty"
                elif val:
                    target_dict["coupon_status"] = str(val).lower()
            elif facet == "distance" and val is not None:
                try:
                    if isinstance(val, dict):
                        distance_value = val.get("distance_km")
                        if distance_value is not None:
                            target_dict["distance_km"] = float(distance_value)
                    else:
                        target_dict["distance_km"] = float(val)
                except (ValueError, TypeError):
                    pass
            elif facet == "rating" and val is not None:
                target_dict["rating"] = val
            elif facet == "avg_price" and val is not None:
                target_dict["avg_price"] = val

        # Handle facet_results status overrides
        for item in facet_results:
            item_dict = _to_dict(item)
            facet = item_dict.get("facet")
            status = item_dict.get("status")
            val = item_dict.get("value")
            
            is_failed = status in ("failed", "circuit_open")
            is_unknown = status not in ("ok", "empty") or is_failed

            if facet == "coupon":
                if status == "ok":
                    if isinstance(val, list):
                        target_dict["coupon_status"] = "has_coupon" if val else "empty"
                    elif val:
                        target_dict["coupon_status"] = str(val).lower()
                    else:
                        target_dict["coupon_status"] = "has_coupon"
                elif status == "empty":
                    target_dict["coupon_status"] = "empty"
                else:
                    target_dict["coupon_status"] = status if status else "unknown"
                
                if is_unknown:
                    target_dict["unknown_facts"].append("coupon")
                if is_failed:
                    target_dict["failed_facts"].append("coupon")

            elif facet == "open_status":
                if status == "ok":
                    if val:
                        target_dict["open_status"] = str(val).lower()
                    elif target_dict["open_status"] == "unknown":
                        target_dict["open_status"] = "open"
                else:
                    target_dict["open_status"] = status if status else "unknown"
                
                if is_unknown:
                    target_dict["unknown_facts"].append("open_status")
                if is_failed:
                    target_dict["failed_facts"].append("open_status")

            elif facet == "distance":
                if status == "ok" and val is not None:
                    try:
                        if isinstance(val, dict):
                            distance_value = val.get("distance_km")
                            if distance_value is not None:
                                target_dict["distance_km"] = float(distance_value)
                        else:
                            target_dict["distance_km"] = float(val)
                    except (ValueError, TypeError):
                        pass
                
                if is_unknown:
                    target_dict["unknown_facts"].append("distance")
                if is_failed:
                    target_dict["failed_facts"].append("distance")

            elif facet in ("detail", "rating", "avg_price"):
                if status == "ok" and val is not None:
                    if isinstance(val, dict):
                        if val.get("rating") is not None:
                            target_dict["rating"] = val.get("rating")
                        if val.get("avg_price") is not None:
                            target_dict["avg_price"] = val.get("avg_price")
                    elif facet == "rating":
                        target_dict["rating"] = val
                    elif facet == "avg_price":
                        target_dict["avg_price"] = val
                
                if is_unknown:
                    target_dict["unknown_facts"].append("detail")
                if is_failed:
                    target_dict["failed_facts"].append("detail")

        # Map unknown_items
        for ui in unknown_items:
            ui_dict = _to_dict(ui)
            f = ui_dict.get("facet")
            if f:
                if f == "coupon":
                    if "coupon" not in target_dict["unknown_facts"]:
                        target_dict["unknown_facts"].append("coupon")
                    if target_dict["coupon_status"] not in ("empty", "has_coupon", "failed", "circuit_open"):
                        target_dict["coupon_status"] = "unknown"
                elif f == "open_status":
                    if "open_status" not in target_dict["unknown_facts"]:
                        target_dict["unknown_facts"].append("open_status")
                    if target_dict["open_status"] not in ("open", "closed", "failed", "circuit_open"):
                        target_dict["open_status"] = "unknown"
                elif f == "distance":
                    if "distance" not in target_dict["unknown_facts"]:
                        target_dict["unknown_facts"].append("distance")
                elif f in ("detail", "rating", "avg_price"):
                    if "detail" not in target_dict["unknown_facts"]:
                        target_dict["unknown_facts"].append("detail")

        selected_targets.append(target_dict)

        # Build facts text list for backward compatibility
        facts = []
        if target_dict["open_status"] == "open":
            facts.append("营业状态为：目前营业中")
        elif target_dict["open_status"] == "closed":
            facts.append("营业状态为：目前已打烊")
        elif "open_status" in target_dict["unknown_facts"]:
            uncertainty_notes.append(f"无法确认 {sname} 的营业状态")
            
        if target_dict["coupon_status"] == "has_coupon":
            titles = target_dict.get("coupon_titles") or ranking_snapshot.get("coupon_titles") or []
            facts.append(f"有券：{'、'.join(str(t) for t in titles[:3])}" if titles else "有券")
        elif target_dict["coupon_status"] == "empty":
            facts.append("当前暂无可用优惠券")
        elif "coupon" in target_dict["unknown_facts"]:
            uncertainty_notes.append(f"无法确认 {sname} 的优惠情况")
            
        if target_dict["distance_km"] is not None:
            dist_str = f"距离为 {target_dict['distance_km']} 公里"
            eta = target_dict.get("eta_minutes") or ranking_snapshot.get("eta_minutes")
            if eta is not None:
                dist_str += f"，预计时间 {eta} 分钟"
            facts.append(dist_str)
        elif "distance" in target_dict["unknown_facts"]:
            uncertainty_notes.append(f"无法确认 {sname} 的距离/时间")
            
        if target_dict["rating"] is not None:
            facts.append(f"评分为 {target_dict['rating']}")
            
        if facts:
            factual_points.append(f"{sname}: {'; '.join(facts)}")

    unknowns = ap.get("must_mention_unknowns") or []
    for u in unknowns:
        omitted_targets.append({"shop_name": str(u)})

    return DecisionPlan(
        answer_type=answer_type,
        selected_targets=selected_targets,
        omitted_targets=omitted_targets,
        main_recommendation=main_recommendation,
        overall_ranking=overall_ranking,
        best_for=best_for,
        factual_points=factual_points,
        uncertainty_notes=uncertainty_notes,
        forbidden_claims=forbidden_claims,
        conversation_continuity=conversation_continuity or {},
    )


def generate_answer(
    answer_plan: dict,
    evidence: dict,
    *,
    llm_client: Any | None = None,
    metadata_out: dict | None = None,
    rewrite_count: int = 0,
    previous_violations: list[str] | None = None,
    in_graph: bool = False,
    conversation_continuity: dict[str, Any] | None = None,
) -> str:
    """Generate a final natural language answer.

    When *metadata_out* is provided, the dict is populated with
    answer-source tracking keys so the caller can record which path
    produced the answer.
    """
    answer_plan = _to_dict(answer_plan)
    evidence = _to_dict(evidence)
    snapshot = evidence.get("ranking_snapshot") or {}
    facet_results = evidence.get("facet_results") or snapshot.get("facet_results") or []
    status = snapshot.get("status", "unknown")

    comparison_matrix = evidence.get("comparison_matrix") or {}
    if answer_plan.get("answer_type") == "comparison" or (comparison_matrix.get("rows") or []):
        template_text = _comparison_sentence(evidence)
    elif answer_plan.get("answer_type") == "recommendation" or snapshot.get("ranked"):
        ranked_items = snapshot.get("ranked") or snapshot.get("ranked_shops") or []
        template_text = _recommendation_sentence([item for item in ranked_items if isinstance(item, dict)])
    else:
        shop_name = _shop_display_name(evidence)

        if facet_results:
            parts = []
            for item in facet_results:
                facet = item.get("facet", "")
                sentence = _facet_sentence(facet, snapshot)
                if sentence:
                    parts.append(sentence)
            if parts:
                template_text = "；".join(parts) + "。"
            else:
                template_text = ""
        else:
            if status == "ok":
                template_text = f"{shop_name}信息已确认。"
            elif status == "empty":
                template_text = f"{shop_name}当前暂无可用信息。"
            elif status == "failed":
                template_text = f"获取{shop_name}信息失败，建议稍后再试。"
            elif status == "circuit_open":
                template_text = f"{shop_name}相关服务暂时不可用，请稍后再试。"
            elif answer_plan.get("answer_type") == "clarification":
                clarification = answer_plan.get("response_sections", [{}])[0].get("clarification", "")
                template_text = clarification if clarification else f"请提供更完整的{shop_name}店名。"
            else:
                template_text = f"暂时无法确认{shop_name}的相关信息。"

    # Track answer source
    # NOTE: verbalizer diagnostic fields (answer_fallback_reason,
    # llm_verbalizer_error, generated_llm_answer_before_fallback) are set
    # by verbalize_decision_plan() in metadata_out.  Do NOT include them
    # here with defaults, otherwise metadata_out.update(metadata) below
    # would overwrite the real diagnostic values.
    metadata = {
        "answer_source": "template",
        "llm_verbalizer_enabled": False,
        "llm_verbalizer_called": False,
        "llm_used": False,
        "llm_backend": "",
        "answer_verifier_result": "not_run",
    }
    
    # Track decision metadata
    ap_dict = _to_dict(answer_plan)
    ev_dict = _to_dict(evidence)
    answer_type_meta = ap_dict.get("answer_type", "general")
    comparison_matrix_meta = ev_dict.get("comparison_matrix") or {}
    ranking_snapshot_meta = ev_dict.get("ranking_snapshot") or {}
    
    decision_type_meta = "general"
    if answer_type_meta == "comparison" or (comparison_matrix_meta and (comparison_matrix_meta.get("rows") or comparison_matrix_meta.get("overall_ranked"))):
        decision_type_meta = "comparison"
    elif answer_type_meta == "recommendation" or (ranking_snapshot_meta and ("ranked" in ranking_snapshot_meta or "ranked_shops" in ranking_snapshot_meta)):
        decision_type_meta = "recommendation"
    elif answer_type_meta == "single_shop" or (ranking_snapshot_meta and ranking_snapshot_meta.get("shop_id")):
        decision_type_meta = "single_shop"
        
    candidate_count_meta = 0
    if decision_type_meta == "comparison":
        candidate_count_meta = len(comparison_matrix_meta.get("rows") or [])
    elif decision_type_meta == "recommendation":
        candidate_count_meta = len(ranking_snapshot_meta.get("ranked") or ranking_snapshot_meta.get("ranked_shops") or [])
    elif decision_type_meta == "single_shop":
        candidate_count_meta = 1
        
    metadata["decision_type"] = decision_type_meta
    metadata["candidate_count"] = candidate_count_meta

    # Check Verbalizer config and client
    from .. import config
    from .llm_verbalizer import verbalize_decision_plan

    if config.ENABLE_LLM_VERBALIZER:

        metadata["llm_verbalizer_enabled"] = True
        metadata["llm_verbalizer_called"] = True
        from ..llm.client import call_llm
        client = llm_client or call_llm
        metadata["llm_backend"] = str(getattr(client, "llm_backend", "") or getattr(config, "LLM_BACKEND", ""))
        plan = _build_decision_plan(answer_plan, evidence, conversation_continuity=conversation_continuity)
        verbalized = verbalize_decision_plan(
            plan,
            llm_client=client,
            fallback_text=template_text,
            metadata_out=metadata_out,
            timeout_ms=config.LLM_TIMEOUT_MS,
            rewrite_count=rewrite_count,
            previous_violations=previous_violations,
            in_graph=in_graph,
        )
        metadata["llm_used"] = True
        if rewrite_count > 0:
            metadata["answer_source"] = "llm_verbalizer_rewrite"
        else:
            metadata["answer_source"] = "llm_verbalizer"
        metadata["answer_fallback_reason"] = ""
        metadata["answer_verifier_result"] = "pass"

        verbalized = _normalize_coupon_phrase(verbalized)

        if metadata_out is not None:
            metadata_out.update(metadata)
        return verbalized

    if metadata_out is not None:
        metadata_out.update(metadata)
    return _normalize_coupon_phrase(template_text)

