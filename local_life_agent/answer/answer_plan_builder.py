"""Answer plan builder for the single-shop multi-facet flow."""

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


def _facet_triage(facet_results: list[dict[str, Any]] | None) -> dict[str, list[str]]:
    answerable: list[str] = []
    unknown: list[str] = []
    failed: list[str] = []
    for item in facet_results or []:
        facet = str((item or {}).get("facet", "") or "").strip()
        if not facet:
            continue
        status = str((item or {}).get("status", (item or {}).get("result_status", "unknown")) or "unknown").lower()
        if status in {"ok", "partial"}:
            if facet not in answerable:
                answerable.append(facet)
        elif status in {"failed", "error", "circuit_open", "backend_unavailable"}:
            if facet not in failed:
                failed.append(facet)
        else:
            if facet not in unknown:
                unknown.append(facet)
    return {
        "answerable_facets": answerable,
        "unknown_facets": unknown,
        "failed_facets": failed,
    }


def _required_disclaimers(unknown_facets: list[str], failed_facets: list[str]) -> list[str]:
    disclaimers: list[str] = []
    if unknown_facets:
        disclaimers.append(f"部分信息暂无法确认: {', '.join(unknown_facets)}")
    if failed_facets:
        disclaimers.append(f"部分工具结果失败: {', '.join(failed_facets)}")
    return disclaimers


def build_answer_plan(
    task_type: str,
    evidence: dict,
    clarification: dict | None = None,
    review_action: str | None = None,
) -> dict:
    """Plan how the answer should be structured."""
    evidence = _to_dict(evidence)
    clarification = _to_dict(clarification)
    review_action = str(review_action or evidence.get("review_action") or evidence.get("evidence_review_action") or "").strip().lower()
    snapshot = evidence.get("ranking_snapshot") or {}
    facet_results = evidence.get("facet_results") or snapshot.get("facet_results") or []
    requested_facets = evidence.get("requested_facets") or snapshot.get("requested_facets") or []
    status = snapshot.get("status", "unknown")
    shop_id = snapshot.get("shop_id", "")
    shop_name = snapshot.get("shop_name", "")
    coupon_titles = snapshot.get("coupon_titles") or []
    comparison_matrix = evidence.get("comparison_matrix") or {}
    comparison_rows = comparison_matrix.get("rows") or []
    target_shop_ids = evidence.get("target_shop_ids") or ([shop_id] if shop_id else [])
    triage = _facet_triage(facet_results)
    if not any(triage.values()):
        triage = {
            "answerable_facets": list(evidence.get("answerable_facets") or []),
            "unknown_facets": list(evidence.get("unknown_facets") or []),
            "failed_facets": list(evidence.get("failed_facets") or []),
        }
    required_disclaimers = list(evidence.get("required_disclaimers") or _required_disclaimers(triage["unknown_facets"], triage["failed_facets"]))

    answer_type = "single_shop_query"
    fallback_template_type = "multi_facet_unknown"
    must_mention_unknowns: list[str] = []

    if clarification.get("clarification") or review_action == "clarify":
        answer_type = "clarification"
        fallback_template_type = "clarification"
    elif task_type == "recommendation":
        answer_type = "recommendation"
        fallback_template_type = "recommendation"
    elif task_type == "comparison" or comparison_rows:
        answer_type = "comparison"
        fallback_template_type = "comparison"
    elif status == "ok":
        fallback_template_type = "multi_facet_ok"
    elif status == "empty":
        fallback_template_type = "multi_facet_empty"
    elif status == "failed":
        fallback_template_type = "multi_facet_failed"
    elif status == "circuit_open":
        fallback_template_type = "multi_facet_circuit_open"
    else:
        must_mention_unknowns = [facet for facet in requested_facets if facet]
    if review_action in {"degrade", "fallback"}:
        fallback_template_type = f"evidence_{review_action}"
    elif review_action in {"retry", "replan_missing_facets", "expand_search"}:
        fallback_template_type = f"evidence_{review_action}"

    response_sections = [
        {
            "section_id": "summary",
            "section_type": "summary",
            "target_shop_ids": target_shop_ids,
            "status": status,
            "task_type": task_type,
        },
    ]

    for item in facet_results:
        facet = item.get("facet", "")
        section = {
            "section_id": f"facet_{facet}",
            "section_type": facet,
            "required": bool(item.get("required", False)),
            "status": item.get("status", "unknown"),
        }
        if facet == "coupon":
            section["coupon_titles"] = coupon_titles
            section["shop_name"] = shop_name
        elif facet == "open_status":
            section["open_status"] = snapshot.get("open_status", "unknown")
            section["shop_name"] = shop_name
        elif facet == "distance":
            section["distance_km"] = snapshot.get("distance_km")
            section["eta_minutes"] = snapshot.get("eta_minutes")
            section["shop_name"] = shop_name
        response_sections.append(section)

    if answer_type == "comparison" and comparison_rows:
        for item in comparison_rows:
            if not isinstance(item, dict):
                continue
            response_sections.append(
                {
                    "section_id": f"shop_{item.get('shop_id', '')}",
                    "section_type": "comparison_row",
                    "shop_id": item.get("shop_id", ""),
                    "shop_name": item.get("shop_name", ""),
                    "rank": item.get("rank", 0),
                    "open_status": item.get("open_status", "unknown"),
                    "coupon_status": item.get("coupon_status", "unknown"),
                    "rating": item.get("rating"),
                    "distance_km": item.get("distance_km"),
                    "eta_minutes": item.get("eta_minutes"),
                }
            )

    allowed_claims = []
    if status == "ok" and shop_id:
        for idx, title in enumerate(coupon_titles, start=1):
            allowed_claims.append(
                {
                    "claim_id": f"claim_{idx}",
                    "shop_id": shop_id,
                    "facet": "coupon",
                    "evidence_ids": [f"evi_coupon_{idx}"],
                    "claim_type": "coupon_available",
                    "value": title,
                    "verbalization_hint": title,
                }
            )

    return {
        "answer_type": answer_type,
        "facets": evidence.get("facets", []),
        "target_resolution": evidence.get("target_resolution"),
        "conflicting_facets": evidence.get("conflicting_facets", []),
        "ranking_policy": evidence.get("ranking_policy"),
        "answerable_facets": triage["answerable_facets"],
        "unknown_facets": triage["unknown_facets"],
        "failed_facets": triage["failed_facets"],
        "required_disclaimers": required_disclaimers,
        "target_shop_ids": target_shop_ids,
        "response_sections": response_sections,
        "allowed_claims": allowed_claims,
        "required_claims": [],
        "must_mention_unknowns": must_mention_unknowns,
        "forbidden_claims": evidence.get("forbidden_claims", []),
        "ranking_snapshot_id": snapshot.get("snapshot_id", ""),
        "comparison_matrix_id": comparison_matrix.get("matrix_id", ""),
        "tone": "neutral",
        "fallback_template_type": fallback_template_type,
    }
