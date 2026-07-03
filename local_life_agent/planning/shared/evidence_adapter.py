"""Shared evidence / answer / state adapters.

P7 uses this module to keep exploration_planning isomorphic with the
main evidence/answer/state protocol without merging workflows.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from ...answer.verifier import verify_answer
from ...core.state_core import StateCore
from ...domain.schemas import AnswerPlan, EvidenceItem, EvidencePack, ExplorationPlan
from ...domain.state import SessionWriteDirective as _SessionWriteDirective
from ..evidence.evidence_cache import EvidenceCache, get_default_evidence_cache


_FACET_ALIASES: dict[str, str] = {
    "open_status": "open_now",
    "open_now": "open_now",
    "distance": "travel_time",
    "travel_time": "travel_time",
    "coupon": "coupon",
    "discount": "discount",
    "group_buy": "group_buy",
    "rating": "rating",
    "review_tags": "review_tags",
    "review_summary": "review_tags",
    "restaurant": "restaurant",
    "coffee": "coffee",
    "date_scene": "date_scene",
    "nearby": "nearby",
}


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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_facet_name(name: Any) -> str:
    if isinstance(name, dict):
        raw_value = name.get("name", name.get("facet", name.get("value", "")))
    else:
        raw_value = getattr(name, "name", None)
        if raw_value is None:
            raw_value = getattr(name, "facet", None)
        if raw_value is None:
            raw_value = getattr(name, "value", name)
    raw = str(raw_value or "").strip()
    return _FACET_ALIASES.get(raw, raw)


def _tool_result_status(tool_result: Any) -> str:
    raw = _to_dict(tool_result)
    result_status = str(raw.get("result_status", "") or "").strip().lower()
    if result_status:
        return result_status
    if raw.get("success") is True:
        return "ok"
    if raw.get("success") is False:
        return "failed"
    return "unknown"


def _facet_status(result_status: str, *, has_value: bool) -> str:
    if result_status in {"ok", "partial"} and has_value:
        return "answerable"
    if result_status in {"empty", "unknown", ""} or (result_status in {"ok", "partial"} and not has_value):
        return "unknown"
    if result_status in {"failed", "error", "timeout", "unsupported", "circuit_open", "backend_unavailable"}:
        return "failed"
    return "unknown"


def _simplify_shop_item(item: Any) -> dict[str, Any]:
    payload = _to_dict(item)
    return {
        "shop_id": str(payload.get("shop_id", "") or "").strip(),
        "shop_name": str(payload.get("shop_name", payload.get("name", "")) or "").strip(),
        "category": str(payload.get("category", "") or "").strip(),
        "rating": payload.get("rating"),
        "avg_price": payload.get("avg_price"),
        "distance_km": payload.get("distance_km"),
        "eta_minutes": payload.get("eta_minutes"),
        "open_status": payload.get("open_status", payload.get("open_status_text", "unknown")),
        "coupon_count": payload.get("coupon_count"),
        "address": str(payload.get("address", "") or "").strip(),
    }


def _search_item_from_result(tool_result: Any, target_shop_id: str) -> dict[str, Any]:
    raw = _to_dict(tool_result)
    data = raw.get("data")
    items = []
    if isinstance(data, dict):
        items = [item for item in data.get("items", []) or [] if isinstance(item, dict)]
    elif isinstance(data, list):
        items = [item for item in data if isinstance(item, dict)]
    if target_shop_id:
        for item in items:
            if str(item.get("shop_id", "") or "").strip() == target_shop_id:
                return _simplify_shop_item(item)
    if items:
        return _simplify_shop_item(items[0])
    return {}


def _value_for_tool(tool_name: str, tool_result: Any, *, target_shop_id: str = "") -> tuple[Any, str]:
    raw = _to_dict(tool_result)
    data = raw.get("data")
    field_path = "data"
    if tool_name == "search_shops":
        field_path = "data.items"
        if target_shop_id:
            item = _search_item_from_result(tool_result, target_shop_id)
            return (item or []), field_path
        if isinstance(data, list):
            return [_simplify_shop_item(item) for item in data if isinstance(item, dict)], field_path
        if isinstance(data, dict):
            items = data.get("items", [])
            return [_simplify_shop_item(item) for item in items if isinstance(item, dict)], field_path
        return [], field_path
    if tool_name == "get_shop_detail":
        if isinstance(data, dict):
            return {
                "shop_id": str(data.get("shop_id", target_shop_id) or target_shop_id).strip(),
                "shop_name": str(data.get("shop_name", data.get("name", "")) or "").strip(),
                "rating": data.get("rating"),
                "avg_price": data.get("avg_price"),
                "address": data.get("address"),
                "tags": data.get("tags", []),
            }, field_path
        return {}, field_path
    if tool_name == "check_open_status":
        if isinstance(data, dict):
            return {"open_status": data.get("open_status", "unknown")}, "data.open_status"
        return {"open_status": "unknown"}, "data.open_status"
    if tool_name == "get_distance_eta":
        if isinstance(data, dict):
            return {
                "distance_km": data.get("distance_km"),
                "eta_minutes": data.get("eta_minutes"),
            }, field_path
        return {}, field_path
    if tool_name == "get_shop_review_summary":
        if isinstance(data, dict):
            items = [item for item in data.get("items", []) or [] if isinstance(item, dict)]
            return [str(item.get("summary", "") or "").strip() for item in items if str(item.get("summary", "") or "").strip()], field_path
        return [], field_path
    if tool_name in {"get_coupon_list", "get_deal_list"}:
        if isinstance(data, list):
            return [str(item.get("title", "") or "").strip() for item in data if isinstance(item, dict) and str(item.get("title", "") or "").strip()], field_path
        if isinstance(data, dict):
            items = [item for item in data.get("items", []) or [] if isinstance(item, dict)]
            return [str(item.get("title", "") or "").strip() for item in items if str(item.get("title", "") or "").strip()], field_path
        return [], field_path
    return data, field_path


def normalize_tool_result_to_evidence(
    tool_name: str,
    tool_result: Any,
    facets: Iterable[str] | None = None,
    *,
    target_shop_id: str = "",
    target_shop_name: str = "",
    subgoal_id: str = "",
    route_step: str = "",
    owner: str = "exploration_planning",
    evidence_ref: str = "",
) -> list[dict[str, Any]]:
    """Normalize one tool result into one or more evidence items."""

    facet_list = [_normalize_facet_name(facet) for facet in (facets or []) if _normalize_facet_name(facet)]
    if not facet_list:
        facet_list = [_normalize_facet_name(tool_name)]
    raw = _to_dict(tool_result)
    result_status = _tool_result_status(raw)
    value, field_path = _value_for_tool(tool_name, tool_result, target_shop_id=target_shop_id)
    has_value = bool(value or value == 0)
    status = _facet_status(result_status, has_value=has_value)
    item_shop_id = str(raw.get("shop_id", "") or target_shop_id or "").strip()
    item_shop_name = str(raw.get("shop_name", target_shop_name) or target_shop_name or "").strip()

    items: list[dict[str, Any]] = []
    for facet in facet_list:
        evidence_id = evidence_ref or f"{owner}_{subgoal_id or 'step'}_{route_step or 'route'}_{facet}_{item_shop_id or raw.get('call_id', 'evidence')}"
        model = EvidenceItem.model_validate(
            {
                "evidence_id": evidence_id,
                "shop_id": item_shop_id,
                "shop_name": item_shop_name,
                "facet": facet,
                "subgoal_id": subgoal_id,
                "route_step": route_step,
                "tool_name": tool_name,
                "call_id": str(raw.get("call_id", "") or ""),
                "result_status": result_status,
                "status": status,
                "field_path": field_path,
                "value": value,
                "confidence": 1.0 if status == "answerable" else 0.0 if status == "failed" else 0.5,
                "timestamp": _now_iso(),
                "source_type": "tool",
                "backend_source": str(raw.get("backend_source", raw.get("source", "")) or ""),
            }
        )
        items.append(model.model_dump())
    return items


def classify_failed_unknown_answerable_facets(
    requested_facets: Iterable[str] | None,
    evidence_items: Iterable[Any] | None,
    tool_errors: Iterable[str] | None = None,
    no_result_markers: Iterable[str] | None = None,
) -> dict[str, list[str]]:
    """Classify facets with the P4 three-way protocol."""

    requested = [_normalize_facet_name(item) for item in (requested_facets or []) if _normalize_facet_name(item)]
    items = [_to_dict(item) for item in (evidence_items or [])]
    errors = {_normalize_facet_name(item) for item in (tool_errors or []) if _normalize_facet_name(item)}
    no_results = {_normalize_facet_name(item) for item in (no_result_markers or []) if _normalize_facet_name(item)}
    answerable: list[str] = []
    unknown: list[str] = []
    failed: list[str] = []

    for facet in requested:
        facet_items = [
            item
            for item in items
            if _normalize_facet_name(item.get("facet", "")) == facet
        ]
        statuses = {str(item.get("status", item.get("result_status", "unknown")) or "unknown").lower() for item in facet_items}
        if facet in errors or statuses.intersection({"failed", "error", "timeout", "unsupported", "circuit_open", "backend_unavailable"}):
            if facet not in failed:
                failed.append(facet)
            continue
        if statuses.intersection({"ok", "partial", "answerable"}):
            if facet not in answerable:
                answerable.append(facet)
            continue
        if facet in no_results or statuses.intersection({"empty", "unknown"}) or not facet_items:
            if facet not in unknown:
                unknown.append(facet)
            continue
        if facet not in unknown:
            unknown.append(facet)

    return {
        "answerable_facets": answerable,
        "unknown_facets": unknown,
        "failed_facets": failed,
    }


def build_evidence_pack_from_tool_results(
    *,
    workflow_name: str,
    owner: str,
    subgoals: list[dict[str, Any]],
    semantic_facets: Iterable[Any] | None = None,
    location_context: dict[str, Any] | None = None,
    cache: EvidenceCache | None = None,
    cache_scope: dict[str, Any] | str | None = None,
) -> EvidencePack:
    """Build a single EvidencePack for exploration_planning."""

    evidence_items: list[dict[str, Any]] = []
    route_steps: list[dict[str, Any]] = []
    last_recommendation_list: list[dict[str, Any]] = []
    requested_facets: list[str] = []
    tool_results: dict[str, Any] = {}

    for item in semantic_facets or []:
        facet_name = _normalize_facet_name(item.get("name", item.get("facet", item)) if isinstance(item, dict) else item)
        if facet_name and facet_name not in requested_facets:
            requested_facets.append(facet_name)

    if location_context and any(key in location_context for key in ("lat", "lng")):
        for facet in ("nearby", "travel_time"):
            if facet not in requested_facets:
                requested_facets.append(facet)

    for idx, subgoal in enumerate(subgoals, start=1):
        subgoal_id = str(subgoal.get("subgoal_id", f"subgoal_{idx}") or f"subgoal_{idx}")
        route_step = str(subgoal.get("sequence_order", idx) or idx)
        kind = _normalize_facet_name(subgoal.get("kind", ""))
        query = str(subgoal.get("query", "") or "")
        if kind and kind not in requested_facets:
            requested_facets.append(kind)
        selected_candidate = _to_dict(subgoal.get("selected_candidate"))
        search_result = subgoal.get("search_result")
        subgoal_tools = _to_dict(subgoal.get("tool_results"))
        route_summary = {
            "subgoal_id": subgoal_id,
            "route_step": route_step,
            "kind": kind,
            "query": query,
            "status": "unknown",
            "selected_candidate": selected_candidate or None,
            "tool_names": list(subgoal_tools.keys()),
        }
        if selected_candidate:
            last_recommendation_list.append(
                {
                    "rank": len(last_recommendation_list) + 1,
                    "shop_id": str(selected_candidate.get("shop_id", "") or "").strip(),
                    "shop_name": str(selected_candidate.get("shop_name", "") or "").strip(),
                    "category": str(selected_candidate.get("category", "") or "").strip(),
                    "rating": selected_candidate.get("rating"),
                    "distance_km": selected_candidate.get("distance_km"),
                    "eta_minutes": selected_candidate.get("eta_minutes"),
                    "open_status": selected_candidate.get("open_status", "unknown"),
                    "coupon_count": selected_candidate.get("coupon_count"),
                    "route_step": route_step,
                    "subgoal_id": subgoal_id,
                }
            )
            route_summary["status"] = "answerable"
        if search_result is not None:
            tool_results[f"{subgoal_id}:search_shops"] = search_result
            evidence_items.extend(
                normalize_tool_result_to_evidence(
                    "search_shops",
                    search_result,
                    facets=[kind or "nearby"],
                    target_shop_id=str(selected_candidate.get("shop_id", "") or ""),
                    target_shop_name=str(selected_candidate.get("shop_name", "") or ""),
                    subgoal_id=subgoal_id,
                    route_step=route_step,
                    owner=owner,
                    evidence_ref=f"{subgoal_id}:search",
                )
            )
        for tool_name, tool_result in subgoal_tools.items():
            tool_results[f"{subgoal_id}:{tool_name}"] = tool_result
            facets_for_tool = [tool_name]
            if tool_name == "check_open_status":
                facets_for_tool = ["open_now"]
            elif tool_name == "get_distance_eta":
                facets_for_tool = ["travel_time"]
            elif tool_name == "get_shop_review_summary":
                facets_for_tool = ["review_tags"]
            elif tool_name == "get_coupon_list":
                facets_for_tool = ["coupon"]
            elif tool_name == "get_deal_list":
                facets_for_tool = ["group_buy"]
            elif tool_name == "get_shop_detail":
                facets_for_tool = [kind or "restaurant"]
            normalized = normalize_tool_result_to_evidence(
                tool_name,
                tool_result,
                facets=facets_for_tool,
                target_shop_id=str(selected_candidate.get("shop_id", "") or ""),
                target_shop_name=str(selected_candidate.get("shop_name", "") or ""),
                subgoal_id=subgoal_id,
                route_step=route_step,
                owner=owner,
                evidence_ref=f"{subgoal_id}:{tool_name}",
            )
            evidence_items.extend(normalized)
            if normalized and any(item.get("status") == "failed" for item in normalized):
                route_summary["status"] = "failed"
            elif normalized and route_summary["status"] != "failed":
                if any(item.get("status") == "answerable" for item in normalized):
                    route_summary["status"] = "answerable"
                elif route_summary["status"] != "answerable":
                    route_summary["status"] = "unknown"
        if route_summary["status"] == "unknown" and not selected_candidate:
            route_summary["status"] = "unknown"
        route_steps.append(route_summary)

    answerable_facets = [item.get("facet", "") for item in evidence_items if item.get("status") == "answerable"]
    triage = classify_failed_unknown_answerable_facets(requested_facets, evidence_items)
    last_recommendation_ids = [item["shop_id"] for item in last_recommendation_list if item.get("shop_id")]
    ranking_snapshot = {
        "snapshot_id": f"{workflow_name}_{owner}_snapshot",
        "status": "ok" if answerable_facets else ("failed" if triage["failed_facets"] else "empty"),
        "strategy": "sequence_order",
        "ranked": last_recommendation_list,
        "ranked_shops": last_recommendation_list,
        "candidate_count": len(last_recommendation_list),
    }
    facet_results = [
        {
            "facet": str(item.get("facet", "") or ""),
            "status": str(item.get("status", "unknown") or "unknown"),
            "result_status": str(item.get("result_status", "unknown") or "unknown"),
            "shop_id": str(item.get("shop_id", "") or ""),
            "shop_name": str(item.get("shop_name", "") or ""),
            "subgoal_id": str(item.get("subgoal_id", "") or ""),
            "route_step": str(item.get("route_step", "") or ""),
            "value": item.get("value"),
        }
        for item in evidence_items
    ]
    payload = {
            "owner": owner,
            "facets": list(semantic_facets or []),
            "target_resolution": None,
            "conflicting_facets": [],
            "ranking_policy": None,
            "answerable_facets": triage["answerable_facets"],
            "unknown_facets": triage["unknown_facets"],
            "failed_facets": triage["failed_facets"],
            "target_shop_ids": last_recommendation_ids,
            "requested_facets": requested_facets,
            "facet_results": facet_results,
            "evidence_items": evidence_items,
            "unknown_items": [item for item in evidence_items if item.get("status") == "unknown"],
            "route_steps": route_steps,
            "last_recommendation_list": last_recommendation_list,
            "forbidden_claims": [],
            "ranking_snapshot": ranking_snapshot,
            "comparison_matrix": None,
            "tool_results": tool_results,
            "evidence_cache_key": "",
            "evidence_cache_scope": "",
            "evidence_cache_hit": False,
            "evidence_enrichment_top_k": len(last_recommendation_list),
        }
    cache_store = cache or get_default_evidence_cache()
    if cache_store is not None and cache_scope is not None:
        cached_payload, cache_meta = cache_store.get_or_build(
            cache_scope,
            {
                "workflow_name": workflow_name,
                "owner": owner,
                "subgoals": subgoals,
                "semantic_facets": list(semantic_facets or []),
                "location_context": location_context or {},
                "tool_results": tool_results,
            },
            lambda: payload,
        )
        payload = dict(cached_payload)
        payload["evidence_cache_key"] = cache_meta.get("cache_key", "")
        payload["evidence_cache_scope"] = cache_meta.get("cache_scope", "")
        payload["evidence_cache_hit"] = bool(cache_meta.get("cache_hit", False))
    evidence = EvidencePack.model_validate(payload)
    return evidence


def build_answer_plan_from_evidence(
    *,
    task_type: str,
    evidence_pack: EvidencePack | dict[str, Any],
    exploration_plan: ExplorationPlan | dict[str, Any] | None = None,
) -> AnswerPlan:
    """Build an AnswerPlan that only reflects evidence-backed claims."""

    evidence = _to_dict(evidence_pack)
    exploration = _to_dict(exploration_plan)
    triage = classify_failed_unknown_answerable_facets(
        evidence.get("requested_facets", []),
        evidence.get("facet_results", []),
    )
    route_steps = list(evidence.get("route_steps", []) or exploration.get("subgoals", []) or [])
    response_sections: list[dict[str, Any]] = [
        {
            "section_id": "summary",
            "section_type": "summary",
            "target_shop_ids": list(evidence.get("target_shop_ids", []) or []),
            "status": "ok" if triage["answerable_facets"] else ("failed" if triage["failed_facets"] else "unknown"),
            "task_type": task_type,
        }
    ]
    for step in route_steps:
        step_dict = _to_dict(step)
        response_sections.append(
            {
                "section_id": str(step_dict.get("subgoal_id", step_dict.get("route_step", "step"))),
                "section_type": str(step_dict.get("kind", "route_step") or "route_step"),
                "route_step": str(step_dict.get("route_step", "") or ""),
                "subgoal_id": str(step_dict.get("subgoal_id", "") or ""),
                "status": str(step_dict.get("status", "unknown") or "unknown"),
                "shop_id": str((step_dict.get("selected_candidate") or {}).get("shop_id", "") or ""),
                "shop_name": str((step_dict.get("selected_candidate") or {}).get("shop_name", "") or ""),
            }
        )
    allowed_claims = []
    for idx, item in enumerate(evidence.get("evidence_items", []) or [], start=1):
        item_dict = _to_dict(item)
        if str(item_dict.get("status", "") or "") != "answerable":
            continue
        allowed_claims.append(
            {
                "claim_id": item_dict.get("evidence_id", f"claim_{idx}"),
                "shop_id": item_dict.get("shop_id", ""),
                "facet": item_dict.get("facet", ""),
                "evidence_ids": [item_dict.get("evidence_id", "")],
                "claim_type": str(item_dict.get("facet", "") or "factual"),
                "value": item_dict.get("value"),
                "verbalization_hint": "",
            }
        )
    required_disclaimers: list[str] = []
    if triage["unknown_facets"]:
        required_disclaimers.append(f"部分信息暂无法确认: {', '.join(triage['unknown_facets'])}")
    if triage["failed_facets"]:
        required_disclaimers.append(f"部分工具结果失败: {', '.join(triage['failed_facets'])}")
    fallback_template_type = "exploration_plan_partial" if triage["unknown_facets"] or triage["failed_facets"] else "exploration_plan"
    answer_plan = AnswerPlan.model_validate(
        {
            "answer_type": "exploration_plan",
            "facets": list(evidence.get("facets", []) or []),
            "target_resolution": evidence.get("target_resolution"),
            "conflicting_facets": evidence.get("conflicting_facets", []),
            "ranking_policy": evidence.get("ranking_policy"),
            "answerable_facets": triage["answerable_facets"],
            "unknown_facets": triage["unknown_facets"],
            "failed_facets": triage["failed_facets"],
            "required_disclaimers": required_disclaimers,
            "target_shop_ids": list(evidence.get("target_shop_ids", []) or []),
            "response_sections": response_sections,
            "allowed_claims": allowed_claims,
            "required_claims": [],
            "must_mention_unknowns": list(triage["unknown_facets"]),
            "forbidden_claims": list(evidence.get("forbidden_claims", []) or []),
            "ranking_snapshot_id": str((evidence.get("ranking_snapshot") or {}).get("snapshot_id", "") or ""),
            "comparison_matrix_id": str((evidence.get("comparison_matrix") or {}).get("matrix_id", "") or ""),
            "tone": "neutral",
            "fallback_template_type": fallback_template_type,
        }
    )
    return answer_plan


def verify_answer_plan(answer_text: str, evidence_pack: EvidencePack | dict[str, Any], task_type: str) -> dict[str, Any]:
    """Verify a response against evidence using the shared answer verifier."""

    return verify_answer(answer_text, _to_dict(evidence_pack), task_type)


def apply_state_update_plan(
    turn_context: dict[str, Any],
    task_type: str,
    resolve_shop_status: str,
    pending_check_result: str | None = None,
) -> _SessionWriteDirective:
    """Materialize a state update directive using the shared state core."""

    core = StateCore()
    plan_dict = core.plan_state_update(turn_context, task_type, resolve_shop_status, pending_check_result=pending_check_result)
    return core.build_state_patch(
        set_fields=plan_dict.get("set_fields", {}),
        clear_fields=plan_dict.get("clear_fields", []),
    )
