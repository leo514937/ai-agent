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
    tool_results = evidence.get("tool_results")
    if isinstance(tool_results, dict):
        return tool_results
    return {}


def _build_shop_name_map(evidence: dict[str, Any]) -> dict[str, str]:
    name_map: dict[str, str] = {}

    def register(item: Any) -> None:
        item_dict = _to_dict(item)
        if not item_dict:
            return
        shop_id = str(item_dict.get("shop_id") or "").strip()
        shop_name = str(item_dict.get("shop_name") or "").strip()
        if shop_id and shop_name and shop_name != shop_id:
            name_map[shop_id] = shop_name
        alias = str(item_dict.get("alias") or "").strip()
        if alias and shop_id and alias != shop_id:
            name_map.setdefault(shop_id, alias)

    ranking_snapshot = evidence.get("ranking_snapshot") or {}
    for item in ranking_snapshot.get("ranked") or ranking_snapshot.get("ranked_shops") or []:
        register(item)

    comparison_matrix = evidence.get("comparison_matrix") or {}
    for item in comparison_matrix.get("rows") or []:
        register(item)
    for item in comparison_matrix.get("overall_ranked") or []:
        register(item)
    for item in (comparison_matrix.get("dimension_winners") or {}).values():
        if isinstance(item, list):
            for sub_item in item:
                register(sub_item)

    for item in evidence.get("last_recommendation_list") or []:
        register(item)
    for item in evidence.get("evidence_items") or []:
        register(item)
    for item in evidence.get("unknown_items") or []:
        register(item)

    return name_map


def _apply_shop_name_map(plan: DecisionPlan, name_map: dict[str, str]) -> None:
    if not name_map:
        return

    def patch_item(item: Any) -> None:
        if not isinstance(item, dict):
            return
        shop_id = str(item.get("shop_id") or "").strip()
        shop_name = str(item.get("shop_name") or "").strip()
        mapped_name = name_map.get(shop_id)
        if mapped_name and (not shop_name or shop_name == shop_id):
            item["shop_name"] = mapped_name

    for item in plan.selected_targets:
        patch_item(item)
    for item in plan.omitted_targets:
        patch_item(item)
    for item in plan.overall_ranking:
        patch_item(item)
    patch_item(plan.main_recommendation)
    for item in plan.candidate_summaries:
        patch_item(item)
    for item in plan.best_for.values():
        patch_item(item)


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


def _semantic_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _normalise_str_list(value: Any) -> list[str]:
    items = _semantic_list(value)
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _normalize_stage_requirements(stages: list[dict[str, Any]]) -> tuple[list[str], list[list[str]], list[str]]:
    stage_queries: list[str] = []
    stage_evidence_requirements: list[list[str]] = []
    stage_statuses: list[str] = []
    for stage in stages:
        stage_dict = _to_dict(stage)
        query = str(stage_dict.get("candidate_query") or stage_dict.get("query") or "").strip()
        if query:
            stage_queries.append(query)
        requirements = [
            str(item).strip()
            for item in _semantic_list(stage_dict.get("evidence_requirements"))
            if str(item).strip()
        ]
        stage_evidence_requirements.append(requirements)
        stage_statuses.append(str(stage_dict.get("status", "planned") or "planned").strip() or "planned")
    return stage_queries, stage_evidence_requirements, stage_statuses


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
    semantic_frame = _to_dict(ev.get("semantic_frame") or ap.get("semantic_frame"))
    exploration_stages = [
        _to_dict(item)
        for item in _semantic_list(ev.get("exploration_stages") or semantic_frame.get("exploration_stages") or ap.get("exploration_stages"))
        if _to_dict(item)
    ]
    stage_queries, stage_evidence_requirements, stage_statuses = _normalize_stage_requirements(
        exploration_stages
    )
    semantic_parse_source = str(ev.get("semantic_parse_source") or semantic_frame.get("semantic_parse_source") or ap.get("semantic_parse_source") or "").strip()
    grounding_status = str(ev.get("grounding_status") or semantic_frame.get("grounding_status") or ap.get("grounding_status") or "").strip()
    missing_slot_type = str(ev.get("missing_slot_type") or semantic_frame.get("missing_slot_type") or ap.get("missing_slot_type") or "").strip()
    router_policy_decision = _to_dict(ev.get("router_policy_decision") or semantic_frame.get("router_policy_decision"))
    router_policy_conflicts = _normalise_str_list(ev.get("router_policy_conflicts") or semantic_frame.get("router_policy_conflicts") or ap.get("router_policy_conflicts"))
    scene = str(ev.get("scene") or semantic_frame.get("scene") or ap.get("scene") or "").strip()
    time = str(ev.get("time") or semantic_frame.get("time") or ap.get("time") or "").strip()
    location = _to_dict(ev.get("location") or semantic_frame.get("location") or ap.get("location"))
    evidence_status = str(ev.get("evidence_status") or "").strip()
    comparison_support_status = str(ev.get("comparison_support_status") or "").strip()
    ranking_preserved = bool(ev.get("ranking_preserved", True))
    unsupported_reasons = _normalise_str_list(ev.get("unsupported_reasons"))
    unknown_fields = _normalise_str_list(ev.get("unknown_fields"))
    failed_tools = _normalise_str_list(ev.get("failed_tools"))
    partial_fields = _normalise_str_list(ev.get("partial_fields"))
    facet_statuses = _to_dict(ev.get("facet_statuses") or ap.get("facet_statuses"))
    grounded_facts = _to_dict(ev.get("grounded_facts") or ap.get("grounded_facts"))
    facet_reasons = _to_dict(ev.get("facet_reasons") or ap.get("facet_reasons"))
    evidence_review_result = _to_dict(ev.get("evidence_review_result"))
    answer_verify_result = _to_dict(ev.get("answer_verify_result"))

    decision_type = None
    if answer_type == "comparison" or (comparison_matrix and (comparison_matrix.get("rows") or comparison_matrix.get("overall_ranked"))):
        decision_type = "comparison"
    elif answer_type == "recommendation":
        decision_type = "recommendation"

    if decision_type in ("recommendation", "comparison"):
        # 1. Extract shop_ids
        shop_ids: list[str] = []
        if decision_type == "comparison":
            rows = comparison_matrix.get("rows") or []
            shop_ids = [str(r.get("shop_id", "")) for r in rows if isinstance(r, dict) and r.get("shop_id")]
            if not shop_ids:
                shop_ids = [str(sid) for sid in ev.get("target_shop_ids", []) or [] if str(sid).strip()]
        else: # recommendation
            shop_ids = [str(sid) for sid in ap.get("target_shop_ids", []) or [] if str(sid).strip()]
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
            "query_terms": ap.get("query_terms") or [],
            "scene_terms": ap.get("scene_terms") or [],
        }
        evaluations = evaluator.evaluate(evidences, decision_type, preferences)

        # 5. Build candidate plan
        forbidden_claims = list(ap.get("forbidden_claims", []))
        must_mention_unknowns = list(ap.get("must_mention_unknowns", []))
        location = str(ap.get("location") or ev.get("location") or "").strip()
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
        _apply_shop_name_map(plan, _build_shop_name_map(ev))
        plan.decision_context = {
            **(plan.decision_context or {}),
            "raw_comparison_rows": (ev.get("comparison_matrix") or {}).get("rows", []) if isinstance(ev.get("comparison_matrix") or {}, dict) else [],
            "raw_ranking_rows": (ev.get("ranking_snapshot") or {}).get("ranked", []) if isinstance(ev.get("ranking_snapshot") or {}, dict) else [],
        }
        plan.semantic_frame = semantic_frame
        plan.semantic_parse_source = semantic_parse_source
        plan.grounding_status = grounding_status
        plan.missing_slot_type = missing_slot_type
        plan.router_policy_decision = router_policy_decision
        plan.router_policy_conflicts = router_policy_conflicts
        plan.exploration_stages = exploration_stages
        plan.stage_queries = stage_queries
        plan.stage_evidence_requirements = stage_evidence_requirements
        plan.stage_statuses = stage_statuses
        plan.scene = scene
        plan.time = time
        plan.location = location
        plan.evidence_status = evidence_status or ("grounded" if not unknown_fields and not failed_tools else "partial" if unknown_fields or failed_tools else "grounded")
        plan.comparison_support_status = comparison_support_status
        plan.ranking_preserved = ranking_preserved
        plan.unsupported_reasons = unsupported_reasons
        plan.unknown_fields = unknown_fields
        plan.failed_tools = failed_tools
        plan.partial_fields = partial_fields
        plan.facet_statuses = facet_statuses
        plan.grounded_facts = grounded_facts
        plan.facet_reasons = facet_reasons
        plan.evidence_review_result = evidence_review_result
        plan.answer_verify_result = answer_verify_result
        if decision_type == "recommendation" and shop_ids:
            shop_id_to_index = {str(sid): i for i, sid in enumerate(shop_ids)}
            plan.overall_ranking.sort(key=lambda x: shop_id_to_index.get(str(x.get("shop_id", "")), 999))
            plan.selected_targets.sort(key=lambda x: shop_id_to_index.get(str(x.get("shop_id", "")), 999))
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
                    dist_str = f"直线距离约 {row_dict.get('distance_km')} 公里"
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
            "coupon_titles": [],
            "eta_minutes": None,
            "distance_km": None,
            "avg_price": None,
            "rating": None,
            "unknown_facts": [],
            "failed_facts": [],
        }

        # Overlay evidence_items values
        for ei in evidence_items:
            ei_dict = _to_dict(ei)
            facet = ei_dict.get("facet")
            val = ei_dict.get("value")
            if facet == "open_status" and val:
                target_dict["open_status"] = str(val).lower()
            elif facet == "coupon":
                if isinstance(val, list):
                    target_dict["coupon_titles"] = [str(item) for item in val if str(item).strip()]
                    target_dict["coupon_status"] = "has_coupon" if val else "empty"
                elif val:
                    target_dict["coupon_status"] = str(val).lower()
            elif facet == "distance" and val is not None:
                try:
                    if isinstance(val, dict):
                        distance_value = val.get("distance_km")
                        if distance_value is not None:
                            target_dict["distance_km"] = float(distance_value)
                        if val.get("eta_minutes") is not None:
                            target_dict["eta_minutes"] = val.get("eta_minutes")
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
                        target_dict["coupon_titles"] = [str(item) for item in val if str(item).strip()]
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
                            if val.get("eta_minutes") is not None:
                                target_dict["eta_minutes"] = val.get("eta_minutes")
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
            titles = target_dict.get("coupon_titles") or []
            facts.append(f"有券：{'、'.join(str(t) for t in titles[:3])}" if titles else "有券")
        elif target_dict["coupon_status"] == "empty":
            facts.append("当前暂无可用优惠券")
        elif "coupon" in target_dict["unknown_facts"]:
            uncertainty_notes.append(f"无法确认 {sname} 的优惠情况")

        if target_dict["distance_km"] is not None:
            dist_str = f"直线距离约 {target_dict['distance_km']} 公里"
            facts.append(dist_str)
        elif "distance" in target_dict["unknown_facts"]:
            uncertainty_notes.append(f"无法确认 {sname} 的距离/时间")

        if target_dict["rating"] is not None:
            facts.append(f"评分为 {target_dict['rating']}")

        if facts:
            factual_points.append(f"{sname}: {'; '.join(facts)}")

    if not facet_statuses and selected_targets:
        first_target = selected_targets[0]
        facet_statuses = {
            "open_status": "grounded" if first_target.get("open_status") in {"open", "closed"} else "unknown",
            "coupon": "grounded" if first_target.get("coupon_status") == "has_coupon" else "empty" if first_target.get("coupon_status") == "empty" else "unknown",
            "distance": "grounded" if first_target.get("distance_km") is not None else "unknown",
            "rating": "grounded" if first_target.get("rating") is not None else "unknown",
            "avg_price": "grounded" if first_target.get("avg_price") is not None else "unknown",
        }
        grounded_facts = {
            "open_status": first_target.get("open_status"),
            "coupon_count": len(first_target.get("coupon_titles") or []) if first_target.get("coupon_status") == "has_coupon" else 0 if first_target.get("coupon_status") == "empty" else None,
            "coupon_titles": list(first_target.get("coupon_titles") or []),
            "distance_km": first_target.get("distance_km"),
            "eta_minutes": first_target.get("eta_minutes"),
            "rating": first_target.get("rating"),
            "avg_price": first_target.get("avg_price"),
        }
        facet_reasons = {
            "distance": "distance_tool_missing_or_location_unresolved" if first_target.get("distance_km") is None else "",
        }
        facet_reasons = {key: value for key, value in facet_reasons.items() if str(value).strip()}

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
        decision_context={
            "raw_comparison_rows": (ev.get("comparison_matrix") or {}).get("rows", []) if isinstance(ev.get("comparison_matrix") or {}, dict) else [],
            "raw_ranking_rows": (ev.get("ranking_snapshot") or {}).get("ranked", []) if isinstance(ev.get("ranking_snapshot") or {}, dict) else [],
        },
        conversation_continuity=conversation_continuity or {},
        semantic_frame=semantic_frame,
        semantic_parse_source=semantic_parse_source,
        grounding_status=grounding_status,
        missing_slot_type=missing_slot_type,
        router_policy_decision=router_policy_decision,
        router_policy_conflicts=router_policy_conflicts,
        exploration_stages=exploration_stages,
        stage_queries=stage_queries,
        stage_evidence_requirements=stage_evidence_requirements,
        stage_statuses=stage_statuses,
        scene=scene,
        time=time,
        location=location,
        facet_statuses=facet_statuses,
        grounded_facts=grounded_facts,
        facet_reasons=facet_reasons,
        evidence_status=evidence_status or ("grounded" if not unknown_fields and not failed_tools else "partial" if unknown_fields or failed_tools else "grounded"),
        comparison_support_status=comparison_support_status,
        ranking_preserved=ranking_preserved,
        unsupported_reasons=unsupported_reasons,
        unknown_fields=unknown_fields,
        failed_tools=failed_tools,
        partial_fields=partial_fields,
        evidence_review_result=evidence_review_result,
        answer_verify_result=answer_verify_result,
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
    """Generate a final natural language answer via LLM verbalizer only.

    Template-based fallback has been removed — this function uses only the
    LLM verbalizer path. If the LLM is unavailable or fails, an error
    message is returned.

    When *metadata_out* is provided, the dict is populated with
    answer-source tracking keys so the caller can record which path
    produced the answer.
    """
    answer_plan = _to_dict(answer_plan)
    evidence = _to_dict(evidence)

    # Track decision metadata
    ap_dict = _to_dict(answer_plan)
    ev_dict = _to_dict(evidence)
    answer_type_meta = ap_dict.get("answer_type", "general")
    comparison_matrix_meta = ev_dict.get("comparison_matrix") or {}
    decision_type_meta = "general"
    if answer_type_meta == "comparison" or (comparison_matrix_meta and (comparison_matrix_meta.get("rows") or comparison_matrix_meta.get("overall_ranked"))):
        decision_type_meta = "comparison"
    elif answer_type_meta == "recommendation":
        decision_type_meta = "recommendation"
    elif answer_type_meta in ("single_shop", "single_shop_query"):
        decision_type_meta = "single_shop"

    candidate_count_meta = 0
    if decision_type_meta == "comparison":
        candidate_count_meta = len(comparison_matrix_meta.get("rows") or [])
    elif decision_type_meta == "recommendation":
        candidate_count_meta = len(ap_dict.get("target_shop_ids") or ev_dict.get("target_shop_ids") or [])
    elif decision_type_meta == "single_shop":
        candidate_count_meta = 1

    metadata: dict[str, Any] = {
        "answer_source": "llm_verbalizer",
        "llm_verbalizer_enabled": True,
        "llm_verbalizer_called": True,
        "llm_used": False,
        "llm_backend": "",
        "answer_verifier_result": "not_run",
        "decision_type": decision_type_meta,
        "candidate_count": candidate_count_meta,
    }

    from .. import config
    from .llm_verbalizer import verbalize_decision_plan

    if not config.ENABLE_LLM_VERBALIZER:
        if metadata_out is not None:
            metadata["answer_source"] = "llm_disabled"
            metadata["llm_verbalizer_enabled"] = False
            metadata["llm_verbalizer_called"] = False
            metadata_out.update(metadata)
        return "【LLM 服务未启用】无法生成自然语言回答。"

    from ..llm.client import call_llm
    client = llm_client or call_llm
    metadata["llm_backend"] = str(getattr(client, "llm_backend", "") or getattr(config, "LLM_BACKEND", ""))

    plan = _build_decision_plan(answer_plan, evidence, conversation_continuity=conversation_continuity)
    verbalized = verbalize_decision_plan(
        plan,
        llm_client=client,
        metadata_out=metadata_out,
        timeout_ms=config.LLM_TIMEOUT_MS,
        rewrite_count=rewrite_count,
        previous_violations=previous_violations,
        in_graph=in_graph,
    )
    metadata["llm_used"] = True

    if metadata_out is not None:
        if "answer_source" not in metadata_out:
            metadata["answer_source"] = "llm_verbalizer_rewrite" if rewrite_count > 0 else "llm_verbalizer"
        for key, value in metadata.items():
            metadata_out.setdefault(key, value)

    return _normalize_coupon_phrase(verbalized)

