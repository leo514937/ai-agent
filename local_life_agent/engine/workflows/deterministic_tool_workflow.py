"""Independent deterministic workflow for explicit single-shop fact queries.

Phase 6 keeps this workflow intentionally small:
- resolve one explicit shop target
- call exactly one tool
- build ExecutionPlan / ToolResult / EvidencePack / AnswerPlan
- generate a deterministic answer from evidence
- verify the answer before handing back to the graph

When target resolution is ambiguous or missing, the workflow returns a
clarification / fallback payload and does not call any tools.
"""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from ...answer.answer_plan_builder import build_answer_plan
from ...answer.response_directive import build_response_directive
from ...answer.verifier import verify_answer
from ... import config
from ...domain.schemas import AnswerPlan, EvidencePack, ExecutionPlan, OrchestrationDecision, ResolveShopResult, ShopRef, ToolCallSpec, ToolResult
from ...domain.state import SessionState
from ...domain.facets import build_target_resolution_result, normalize_query_facets
from ...engine._compat import _log, _unwrap_resolve_shop_result
from ...observability.file_logger import get_python_service_logger, log_kv
from ...planning.evidence.evidence_builder import build_evidence
from ...planning.budget.budget_context import budget_context_from_state
from ...planning.evidence.evidence_cache import get_default_evidence_cache
from ...planning.evidence.tool_batch_executor import ToolBatchExecutor
from ...planning.evidence.tool_capabilities import build_tool_call_dict, preferred_tool_for_facet
from ...planning.goal.goal_planner import _infer_explicit_mentions_from_text
from ...target.clarification import build_pending_clarification, format_pending_prompt
from ...target.reference_resolver import resolve_references
from ...target.shop_resolver import resolve_shop, resolve_shop_entity
from ...tools.gateway import dispatch_tool_call

_LOGGER = get_python_service_logger()

_TASK_TOOL_MAP: dict[str, tuple[str, str]] = {
    "shop_status": ("check_open_status", "open_status"),
    "shop_distance": ("calculate_distance_km", "distance"),
    "shop_coupon": ("get_coupon_list", "coupon"),
    "shop_review_summary": ("get_shop_review_summary", "review_summary"),
    "shop_price": ("get_shop_detail", "price"),
}

_DEAL_TASK_NAMES = {"deal", "group_deal", "group_deal_query", "deal_query", "deal_compare"}


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


def _enum_value(value: Any) -> str:
    if value is None:
        return ""
    raw = getattr(value, "value", value)
    return str(raw or "").strip()


def _session_value(state: dict[str, Any], field: str) -> Any:
    session_state = state.get("session_state")
    if isinstance(session_state, SessionState):
        return getattr(session_state, field, None)
    if isinstance(session_state, dict):
        return session_state.get(field)
    session_state_before = state.get("session_state_before")
    if isinstance(session_state_before, SessionState):
        return getattr(session_state_before, field, None)
    if isinstance(session_state_before, dict):
        return session_state_before.get(field)
    return state.get(field)


def _extract_user_location(state: dict[str, Any]) -> dict[str, Any]:
    candidates = [
        state.get("user_context"),
        state.get("turn_input"),
        _session_value(state, "user_context"),
    ]
    for item in candidates:
        item_dict = _to_dict(item)
        lat = item_dict.get("lat")
        lng = item_dict.get("lng")
        if lat is None or lng is None:
            continue
        try:
            return {
                "lat": float(lat),
                "lng": float(lng),
                "label": str(item_dict.get("location_name", item_dict.get("label", "")) or ""),
            }
        except Exception:
            continue
    return {}


def _location_context(state: dict[str, Any]) -> dict[str, Any]:
    semantic_frame = _to_dict(state.get("semantic_frame"))
    for item in (
        state.get("location"),
        semantic_frame.get("location"),
        state.get("user_location"),
        _session_value(state, "user_context"),
    ):
        item_dict = _to_dict(item)
        if item_dict:
            return item_dict
    return {}


def _resolved_shop_location(state: dict[str, Any]) -> dict[str, Any]:
    for item in (
        state.get("resolved_target"),
        state.get("current_shop"),
        state.get("target_resolution"),
    ):
        item_dict = _to_dict(item)
        shop = _to_dict(item_dict.get("resolved_shop") or item_dict.get("shop") or item_dict.get("current_shop") or item_dict)
        if shop.get("lat") is not None and shop.get("lng") is not None:
            return {
                "lat": shop.get("lat"),
                "lng": shop.get("lng"),
                "label": str(shop.get("shop_name", "") or shop.get("name", "") or ""),
            }
    return {}


def _task_to_tool(task_type: str, semantic_frame: dict[str, Any]) -> tuple[str, str] | None:
    normalized_task = _enum_value(task_type)
    if normalized_task in _TASK_TOOL_MAP:
        return _TASK_TOOL_MAP[normalized_task]
    if normalized_task == "coupon_query":
        return "get_coupon_list", "coupon"
    if normalized_task in _DEAL_TASK_NAMES:
        return "get_deal_list", "deal"

    facets = [
        str(item.get("name", "") or item.get("facet", "") or "").strip()
        for item in (semantic_frame.get("facets") or [])
        if isinstance(item, dict)
    ]
    for facet_name in facets:
        if facet_name == "coupon":
            return "get_coupon_list", "coupon"
        if facet_name == "distance":
            return "calculate_distance_km", "distance"
        if facet_name in {"open_status", "open_now", "status"}:
            return "check_open_status", "open_status"
        if facet_name == "review_summary":
            return "get_shop_review_summary", "review_summary"
        if facet_name == "price":
            return "get_shop_detail", "price"

    if normalized_task == "single_shop_query" and not facets:
        return "get_shop_detail", "detail"

    primary_task = str(semantic_frame.get("primary_task", "") or "").lower()
    for key, tool in _TASK_TOOL_MAP.items():
        if key in primary_task:
            return tool

    if any(token in primary_task for token in ("coupon", "券", "团购", "套餐", "deal")):
        return "get_coupon_list", "coupon"
    if any(token in primary_task for token in ("status", "open", "营业", "开门")):
        return "check_open_status", "open_status"
    if any(token in primary_task for token in ("review", "summary", "评价", "口碑")):
        return "get_shop_review_summary", "review_summary"
    if any(token in primary_task for token in ("price", "cost", "多少钱", "人均")):
        return "get_shop_detail", "price"

    if any(token in primary_task for token in ("deal", "group", "团购", "套餐", "套餐券")):
        return "get_deal_list", "deal"
    if normalized_task == "single_shop_query":
        return "get_shop_detail", "detail"
    return None


def _presentation_task_type(task_type: str, facet: str) -> str:
    normalized_task = _enum_value(task_type)
    if normalized_task in _TASK_TOOL_MAP or normalized_task in _DEAL_TASK_NAMES:
        return normalized_task
    facet_map = {
        "coupon": "shop_coupon",
        "distance": "shop_distance",
        "open_status": "shop_status",
        "review_summary": "shop_review_summary",
        "price": "shop_price",
        "detail": "single_shop_query",
        "deal": "deal_query",
    }
    return facet_map.get(facet, normalized_task or "single_shop_query")


def _sort_candidate_targets(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def _key(item: dict[str, Any]) -> tuple[int, str, str]:
        shop_id = str(item.get("shop_id", "") or "").strip()
        shop_name = str(item.get("shop_name", "") or "").strip()
        return (-len(shop_id), shop_id, shop_name)

    return sorted([dict(item) for item in candidates if isinstance(item, dict)], key=_key)


def _semantic_mention_matches_raw_hint(semantic_mention: str, raw_hint: str) -> bool:
    semantic = re.sub(r"[\s()（）,，。?？！!~·]", "", str(semantic_mention or ""))
    raw = re.sub(r"[\s()（）,，。?？！!~·]", "", str(raw_hint or ""))
    if not semantic or not raw:
        return False
    if raw in semantic:
        return True
    if "店" not in raw:
        return False
    prefix = raw.split("店", 1)[0]
    if len(prefix) <= 3:
        return False
    brand = prefix[:3]
    tail = prefix[-3:] if len(prefix) >= 3 else prefix
    return brand in semantic and tail in semantic


def _looks_like_specific_shop_mention(mention: str) -> bool:
    text = str(mention or "").strip()
    if not text:
        return False
    if any(token in text for token in ("(", "（", ")", "）")):
        return True
    return any(token in text for token in ("店", "馆", "轩", "居", "坊", "楼", "城", "中心", "广场"))


def _raw_text_shop_prefix(raw_text: str) -> str:
    text = str(raw_text or "").strip()
    if not text:
        return ""
    stop_tokens = ("有券", "比呢", "比吧", "比", "对比", "比较", "怎么样", "好不好", "多久能到", "多久到", "多久", "吗", "嘛", "呢", "吧", "想查", "查下", "查一下")
    prefix = text
    for token in stop_tokens:
        idx = prefix.find(token)
        if 0 < idx < len(prefix):
            prefix = prefix[:idx]
            break
    return prefix.strip(" ，,。！？?!~")


def _route_info_from_raw_text(raw_text: str) -> tuple[str, str] | None:
    text = str(raw_text or "")
    lowered = text.lower()
    if "营业" in text or "开门" in text or "open" in lowered:
        return "check_open_status", "open_status"
    if "有券" in text or "优惠券" in text or "团购" in text or "coupon" in lowered:
        return "get_coupon_list", "coupon"
    # “多久”更接近时长/ETA 语义，避免在未显式识别 facet 时误压成距离工具。
    if "距离" in text or "多远" in text or "多久能到" in text or "多久到" in text or "eta" in lowered:
        return "calculate_distance_km", "distance"
    if "评价" in text or "review" in lowered:
        return "get_shop_review_summary", "review_summary"
    if "价格" in text or "多少钱" in text or "price" in lowered:
        return "get_shop_detail", "price"
    return None


def _single_target_from_resolution(resolution: dict[str, Any]) -> dict[str, Any] | None:
    direct_target = resolution.get("target")
    if direct_target is not None:
        shop_dict = _to_dict(direct_target)
        shop_id = str(shop_dict.get("shop_id", "") or "").strip()
        shop_name = str(shop_dict.get("shop_name", "") or "").strip()
        if shop_id and shop_name:
            return {
                "shop_id": shop_id,
                "shop_name": shop_name,
                "address": str(shop_dict.get("address", "") or "").strip(),
                "alias": shop_dict.get("alias", ""),
                "reference": str(resolution.get("reason", "") or resolution.get("reference", "") or ""),
                "source_text": str(resolution.get("source_ref", "") or ""),
            }
    targets = resolution.get("targets") or []
    if len(targets) != 1:
        return None
    target = _to_dict(targets[0])
    shop = target.get("shop") or target.get("resolved_shop") or target
    shop_dict = _to_dict(shop)
    shop_id = str(shop_dict.get("shop_id", "") or "").strip()
    shop_name = str(shop_dict.get("shop_name", "") or "").strip()
    if not shop_id or not shop_name:
        return None
    return {
        "shop_id": shop_id,
        "shop_name": shop_name,
        "address": str(shop_dict.get("address", "") or "").strip(),
        "alias": shop_dict.get("alias", ""),
        "reference": str(target.get("reference", "") or ""),
        "source_text": str(target.get("source_text", "") or ""),
    }


def _resolve_single_shop_target(state: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str]:
    semantic_frame = _to_dict(state.get("semantic_frame"))
    raw_text = str(state.get("raw_text", "") or state.get("normalized_text", "") or "")
    # 优先用上一轮落盘前的会话快照，避免当前 turn 的临时 session 状态覆盖推荐列表。
    session_state = state.get("session_state_before") or state.get("session_state")
    current_shop = _to_dict(_session_value(state, "current_shop"))
    merchant_mentions = [str(item).strip() for item in (semantic_frame.get("merchant_mentions") or []) if str(item).strip()]
    branch_mentions = [str(item).strip() for item in (semantic_frame.get("branch_mentions") or []) if str(item).strip()]
    reference_mentions = [str(item).strip() for item in (semantic_frame.get("reference_mentions") or []) if str(item).strip()]
    shop_target = _to_dict(semantic_frame.get("shop_target"))
    shop_target_name = str(shop_target.get("shop_name", "") or "").strip()
    if shop_target_name and shop_target_name not in merchant_mentions:
        merchant_mentions = [shop_target_name] + merchant_mentions
    raw_text_prefix = _raw_text_shop_prefix(raw_text)
    specific_shop_hint = any(_looks_like_specific_shop_mention(item) for item in merchant_mentions) or bool(branch_mentions)
    canonical = _to_dict(state.get("canonical_shop_entity"))
    if canonical:
        canonical_status = str(canonical.get("status", "") or "").lower()
        if canonical_status == "resolved":
            resolved_shop = {
                "shop_id": str(canonical.get("shop_id", "") or "").strip(),
                "shop_name": str(canonical.get("shop_name", "") or "").strip(),
                "address": "",
                "alias": canonical.get("alias", []),
                "reference": "canonical_shop_entity",
                "source_text": raw_text,
            }
            if resolved_shop["shop_id"] and resolved_shop["shop_name"]:
                return resolved_shop, None, str(canonical.get("resolution_reason", "") or "canonical_shop_entity_resolved")
        if canonical_status == "ambiguous":
            pending = build_pending_clarification(
                original_text=raw_text,
                original_semantic_frame=semantic_frame,
                original_task_type=_enum_value(state.get("task_type")) or _enum_value(semantic_frame.get("task_type")),
                candidate_targets=_sort_candidate_targets([
                    {
                        "shop_id": str(candidate.get("shop_id", "") or "").strip(),
                        "shop_name": str(candidate.get("shop_name", "") or "").strip(),
                        "address": str(candidate.get("raw", {}).get("address", "") if isinstance(candidate.get("raw"), dict) else "").strip(),
                    }
                    for candidate in (canonical.get("candidates") or [])
                    if str(candidate.get("shop_id", "") or "").strip() and str(candidate.get("shop_name", "") or "").strip()
                ]),
                reason=str(canonical.get("resolution_reason", "") or canonical_status or "shop_resolution_need_clarification"),
                source_node="deterministic_tool_workflow",
                )
            return None, pending.model_dump(), str(canonical.get("resolution_reason", "") or canonical_status or "shop_resolution_need_clarification")
        if canonical_status in {"low_confidence", "not_found", "no_mention"} and not specific_shop_hint:
            pending = build_pending_clarification(
                original_text=raw_text,
                original_semantic_frame=semantic_frame,
                original_task_type=_enum_value(state.get("task_type")) or _enum_value(semantic_frame.get("task_type")),
                candidate_targets=_sort_candidate_targets([
                    {
                        "shop_id": str(candidate.get("shop_id", "") or "").strip(),
                        "shop_name": str(candidate.get("shop_name", "") or "").strip(),
                        "address": str(candidate.get("raw", {}).get("address", "") if isinstance(candidate.get("raw"), dict) else "").strip(),
                    }
                    for candidate in (canonical.get("candidates") or [])
                    if str(candidate.get("shop_id", "") or "").strip() and str(candidate.get("shop_name", "") or "").strip()
                ]),
                reason=str(canonical.get("resolution_reason", "") or canonical_status or "shop_resolution_need_clarification"),
                source_node="deterministic_tool_workflow",
            )
            return None, pending.model_dump(), str(canonical.get("resolution_reason", "") or canonical_status or "shop_resolution_need_clarification")
    mention = raw_text_prefix
    if not mention:
        for item in merchant_mentions:
            if _looks_like_specific_shop_mention(item):
                mention = item
                break
    if not mention and merchant_mentions and branch_mentions:
        for merchant in merchant_mentions:
            merchant = str(merchant).strip()
            if not merchant:
                continue
            if _looks_like_specific_shop_mention(merchant):
                mention = merchant
                break
            for branch in branch_mentions:
                branch = str(branch).strip()
                if branch:
                    mention = f"{merchant}({branch})"
                    break
            if mention:
                break
    if not mention:
        for item in branch_mentions + reference_mentions + merchant_mentions:
            if item:
                mention = item
                break
    if not mention:
        inferred_mentions = _infer_explicit_mentions_from_text(raw_text)
        if inferred_mentions:
            mention = inferred_mentions[0]
    facade_result = _to_dict(
        resolve_shop_entity(
            mention,
            session_state=session_state,
            current_shop=current_shop,
            user_location=_extract_user_location(state),
            semantic_frame=semantic_frame,
        )
    )
    facade_status = str(facade_result.get("status", "") or "").lower()
    if facade_status == "resolved" and not mention:
        target = {
            "shop_id": str(facade_result.get("shop_id", "") or "").strip(),
            "shop_name": str(facade_result.get("shop_name", "") or "").strip(),
            "address": str((_to_dict(facade_result.get("selected_candidate") or {}).get("raw", {}) or {}).get("address", "") or ""),
            "alias": facade_result.get("alias", []),
            "reference": "explicit_mention" if mention else "current_shop",
            "source_text": mention or raw_text,
        }
        if target["shop_id"] and target["shop_name"]:
            return target, None, str(facade_result.get("resolution_reason", "") or "explicit_reference_resolved")
    target_resolution = _to_dict(state.get("target_resolution"))
    if target_resolution:
        if bool(target_resolution.get("resolved", False)):
            target = _to_dict(target_resolution.get("target_shop"))
            shop_id = str(target.get("shop_id", "") or "").strip()
            shop_name = str(target.get("shop_name", "") or "").strip()
            if shop_id and shop_name:
                return {
                    "shop_id": shop_id,
                    "shop_name": shop_name,
                    "address": str(target.get("address", "") or "").strip(),
                    "alias": target.get("alias", ""),
                    "reference": str(target_resolution.get("reference_type", "") or target_resolution.get("source", "") or "target_resolution"),
                    "source_text": str(raw_text or ""),
                }, None, str(target_resolution.get("resolution_reason", "") or "target_resolution_resolved")
        unresolved_reason = str(target_resolution.get("unresolved_reason", "") or target_resolution.get("resolution_reason", "") or "")
        if unresolved_reason and not specific_shop_hint:
            pending = build_pending_clarification(
                original_text=raw_text,
                original_semantic_frame=semantic_frame,
                original_task_type=_enum_value(state.get("task_type")) or _enum_value(semantic_frame.get("task_type")),
                candidate_targets=[],
                reason=unresolved_reason,
                source_node="deterministic_tool_workflow",
            )
            return None, pending.model_dump(), unresolved_reason

    explicit_queries: list[str] = []
    merchant_mentions = [str(item).strip() for item in (semantic_frame.get("merchant_mentions") or []) if str(item).strip()]
    branch_mentions = [str(item).strip() for item in (semantic_frame.get("branch_mentions") or []) if str(item).strip()]
    trusted_mentions = [item for item in merchant_mentions if item and item in raw_text]
    inferred_mentions = _infer_explicit_mentions_from_text(raw_text)
    if not trusted_mentions and inferred_mentions:
        trusted_mentions = [
            item
            for item in merchant_mentions
            if any(_semantic_mention_matches_raw_hint(item, hint) for hint in inferred_mentions)
        ]
    full_mentions = [item for item in trusted_mentions if "(" in item or "（" in item]
    if full_mentions:
        explicit_queries = full_mentions
    elif trusted_mentions and branch_mentions and any(branch in raw_text for branch in branch_mentions):
        explicit_queries = [f"{trusted_mentions[0]}({branch_mentions[0]})"]
    else:
        explicit_queries = trusted_mentions
    if not explicit_queries:
        explicit_queries = inferred_mentions
    explicit_queries = [query for query in explicit_queries if query]

    if explicit_queries:
        session_shop_ids: list[str] = []
        current_shop = _to_dict(_session_value(state, "current_shop"))
        if current_shop.get("shop_id"):
            session_shop_ids.append(str(current_shop.get("shop_id", "")).strip())
        for item in _session_value(state, "last_recommendation_list") or []:
            item_dict = _to_dict(item)
            shop_id = str(item_dict.get("shop_id", "") or "").strip()
            if shop_id and shop_id not in session_shop_ids:
                session_shop_ids.append(shop_id)
        fallback_queries: list[str] = []
        if branch_mentions:
            for branch in branch_mentions:
                branch = str(branch).strip()
                if branch and branch in raw_text and branch not in fallback_queries:
                    fallback_queries.append(branch)
        if trusted_mentions and branch_mentions and any(branch in raw_text for branch in branch_mentions):
            for full in trusted_mentions:
                for branch in branch_mentions:
                    full = str(full).strip()
                    branch = str(branch).strip()
                    if not full or not branch:
                        continue
                    combo = f"{full}({branch})"
                    if combo not in fallback_queries:
                        fallback_queries.append(combo)
        for query in fallback_queries:
            if query not in explicit_queries:
                explicit_queries.append(query)
        for query in explicit_queries:
            resolved = _unwrap_resolve_shop_result(_to_dict(resolve_shop(query, location={}, session_shop_ids=session_shop_ids)))
            status = str(resolved.get("status", "") or "").upper()
            if status == "RESOLVED":
                shop = _to_dict(resolved.get("shop") or resolved.get("resolved_shop") or {})
                shop_id = str(shop.get("shop_id", "") or "").strip()
                shop_name = str(shop.get("shop_name", "") or "").strip()
                if shop_id and shop_name:
                    return {
                        "shop_id": shop_id,
                        "shop_name": shop_name,
                        "address": str(shop.get("address", "") or "").strip(),
                        "alias": shop.get("alias", ""),
                        "reference": "explicit_mention",
                        "source_text": query,
                    }, None, "explicit_reference_resolved"
            if status == "AMBIGUOUS":
                pending = build_pending_clarification(
                    original_text=raw_text,
                    original_semantic_frame=semantic_frame,
                    original_task_type=_enum_value(state.get("task_type")) or _enum_value(semantic_frame.get("task_type")),
                    candidate_targets=_sort_candidate_targets([
                        {
                            "shop_id": str(candidate.get("shop_id", "") or "").strip(),
                            "shop_name": str(candidate.get("shop_name", "") or "").strip(),
                            "address": str(candidate.get("address", "") or "").strip(),
                        }
                        for candidate in (resolved.get("candidates") or [])
                        if str(candidate.get("shop_id", "") or "").strip() and str(candidate.get("shop_name", "") or "").strip()
                    ]),
                    reason=str(resolved.get("error_code", "") or "explicit_shop_ambiguous"),
                    source_node="deterministic_tool_workflow",
                )
                return None, pending.model_dump(), "explicit_shop_ambiguous"

    legacy_resolution = _to_dict(state.get("reference_resolution") or state.get("comparison_target_resolution"))
    legacy_targets = legacy_resolution.get("resolved_targets") or legacy_resolution.get("targets") or []
    if isinstance(legacy_targets, list) and legacy_targets:
        normalized_targets: list[dict[str, Any]] = []
        for item in legacy_targets:
            target = _to_dict(item)
            shop = _to_dict(target.get("resolved_shop") or target.get("shop") or target)
            shop_id = str(shop.get("shop_id", "") or "").strip()
            shop_name = str(shop.get("shop_name", "") or "").strip()
            if shop_id and shop_name:
                normalized_targets.append(
                    {
                        "shop_id": shop_id,
                        "shop_name": shop_name,
                        "address": str(shop.get("address", "") or "").strip(),
                        "alias": shop.get("alias", ""),
                    }
                )
        if len(normalized_targets) == 1:
            return normalized_targets[0], None, "reference_resolved"
        if len(normalized_targets) > 1:
            pending = build_pending_clarification(
                original_text=raw_text,
                original_semantic_frame=semantic_frame,
                original_task_type=_enum_value(state.get("task_type")) or _enum_value(semantic_frame.get("task_type")),
                candidate_targets=normalized_targets,
                reason="comparison_targets_need_clarification",
                source_node="deterministic_tool_workflow",
            )
            return None, pending.model_dump(), "comparison_targets_need_clarification"

    resolution = _to_dict(resolve_references(raw_text, session_state, semantic_frame))
    resolution_status = str(resolution.get("status", "") or "").upper()

    if resolution_status == "RESOLVED":
        target = _single_target_from_resolution(resolution)
        if target is not None:
            return target, None, "reference_resolved"

    if resolution_status == "PARTIAL":
        targets = resolution.get("targets") or []
        if len(targets) == 1:
            target = _single_target_from_resolution({**resolution, "targets": targets})
            if target is not None:
                return target, None, "reference_resolved"

    current_shop = _to_dict(_session_value(state, "current_shop"))
    if current_shop.get("shop_id") and current_shop.get("shop_name"):
        has_explicit_reference = any(
            semantic_frame.get(key)
            for key in ("comparison_targets", "ordinal_references", "deictic_references", "merchant_mentions", "branch_mentions")
        )
        if not has_explicit_reference and not raw_text.strip():
            return {
                "shop_id": str(current_shop.get("shop_id", "") or "").strip(),
                "shop_name": str(current_shop.get("shop_name", "") or "").strip(),
                "address": str(current_shop.get("address", "") or "").strip(),
                "alias": current_shop.get("alias", ""),
                "reference": "current_shop",
                "source_text": "",
            }, None, "current_shop"
        if not has_explicit_reference and resolution.get("status") in {"NOT_FOUND", "NEED_CLARIFICATION"}:
            return {
                "shop_id": str(current_shop.get("shop_id", "") or "").strip(),
                "shop_name": str(current_shop.get("shop_name", "") or "").strip(),
                "address": str(current_shop.get("address", "") or "").strip(),
                "alias": current_shop.get("alias", ""),
                "reference": "current_shop",
                "source_text": "",
            }, None, "current_shop"

    reason = str(resolution.get("reason", "") or "shop_target_needs_clarification")
    candidate_targets = [dict(item) for item in (resolution.get("targets") or []) if isinstance(item, dict)]
    pending = build_pending_clarification(
        original_text=raw_text,
        original_semantic_frame=semantic_frame,
        original_task_type=_enum_value(state.get("task_type")) or _enum_value(semantic_frame.get("task_type")),
        candidate_targets=_sort_candidate_targets(candidate_targets),
        reason=reason,
        source_node="deterministic_tool_workflow",
    )
    return None, pending.model_dump(), reason


def _tool_args_for_task(task_type: str, target_shop_id: str, state: dict[str, Any]) -> dict[str, Any]:
    args: dict[str, Any] = {"shop_id": target_shop_id}
    normalized_task = _enum_value(task_type)
    if normalized_task == "shop_distance":
        user_location = _location_context(state)
        target_location = _resolved_shop_location(state)
        args = {
            "origin": user_location or {},
            "destination": target_location or {},
            "mode": "straight_line",
        }
    elif normalized_task == "shop_review_summary":
        semantic_frame = _to_dict(state.get("semantic_frame"))
        facets = [str(item.get("name", "") or item.get("facet", "") or "").strip() for item in semantic_frame.get("facets", []) or [] if isinstance(item, dict)]
        aspects = [facet for facet in facets if facet]
        if aspects:
            args["aspects"] = aspects
    return args


def _build_execution_plan(
    task_type: str,
    target_shop_id: str,
    tool_name: str,
    facet: str,
    args: dict[str, Any],
    state: dict[str, Any],
    *,
    extra_facets: list[str] | None = None,
) -> ExecutionPlan:
    normalized_task = _enum_value(task_type)
    semantic_frame = _to_dict(state.get("semantic_frame"))
    facet_set = normalize_query_facets(semantic_frame, session_state=state.get("session_state") or state.get("session_state_before"), raw_text=str(state.get("raw_text", "") or state.get("normalized_text", "") or ""))
    target_resolution = _to_dict(state.get("target_resolution"))
    if not target_resolution:
        target_resolution = build_target_resolution_result(
            semantic_frame,
            session_state=state.get("session_state") or state.get("session_state_before"),
            raw_text=str(state.get("raw_text", "") or state.get("normalized_text", "") or ""),
        ).model_dump()
    calls: list[dict[str, Any]] = [
        {
            "call_id": "call_1",
            "tool_name": tool_name,
            "args": args,
            "target_shop_id": target_shop_id,
            "required": True,
            "facet": facet,
            "depends_on": [],
            "timeout_ms": 3000,
            "retry_policy": {"max_attempts": 1, "backoff_ms": 200},
            "fallback_policy": {"fallback_tool": "", "fallback_args": {}},
        }
    ]
    for extra_index, extra_facet in enumerate(extra_facets or [], start=2):
        extra_tool = preferred_tool_for_facet(extra_facet, task_type=normalized_task, has_target=True)
        if not extra_tool:
            continue
        if any(str(item.get("facet", "") or "") == extra_facet and str(item.get("tool_name", "") or "") == extra_tool for item in calls):
            continue
        extra_location = _location_context(state)
        extra_destination = _resolved_shop_location(state)
        extra_args = build_tool_call_dict(
            extra_tool,
            extra_facet,
            call_id=f"call_{extra_index}",
            target_shop_id=target_shop_id,
            required=True,
            location=extra_location,
            origin=extra_location,
            destination=extra_destination,
            group_id="deterministic_tool",
        )["args"]
        calls.append(
            {
                "call_id": f"call_{extra_index}",
                "tool_name": extra_tool,
                "args": extra_args,
                "target_shop_id": target_shop_id,
                "required": True,
                "facet": extra_facet,
                "depends_on": [],
                "timeout_ms": 3000,
                "retry_policy": {"max_attempts": 1, "backoff_ms": 200},
                "fallback_policy": {"fallback_tool": "", "fallback_args": {}},
                "group_id": "deterministic_tool",
                "max_parallelism": 1,
            }
        )
    stage = {
        "call_id": "call_1",
        "stage_id": "stage_1",
        "description": f"deterministic call for {normalized_task}",
        "tool_names": [call["tool_name"] for call in calls],
        "depends_on": [],
        "max_parallelism": min(len(calls), 4) if calls else 1,
    }
    return ExecutionPlan.model_validate(
        {
            "plan_id": f"deterministic_{normalized_task}_{target_shop_id}",
            "task_type": normalized_task,
            "facets": [facet.model_dump() if hasattr(facet, "model_dump") else facet for facet in (facet_set.facets or [])],
            "optional_facets": [facet.name for facet in (facet_set.facets or []) if not getattr(facet, "required", False)],
            "target_resolution": target_resolution,
            "conflicting_facets": [item.model_dump() if hasattr(item, "model_dump") else item for item in (facet_set.conflicting_facets or [])],
            "ranking_policy": facet_set.ranking_policy.model_dump() if facet_set.ranking_policy else None,
            "dependencies": [call.get("call_id", "") for call in calls[1:]],
            "tool_calls": calls,
            "stages": [stage],
            "target_shop_ids": [target_shop_id],
            "query_terms": [str(state.get("raw_text", "") or "")],
            "scene_terms": [],
            "open_now_preferred": normalized_task == "shop_status",
            "coupon_preferred": normalized_task == "shop_coupon",
            "nearby_preferred": normalized_task == "shop_distance",
            "plan_source": "deterministic_tool_workflow",
            "planning_notes": ["phase_6_deterministic_tool"],
            "assumptions_used": [],
            "timeout_policy": {"default_timeout_ms": config.TOOL_DEFAULT_TIMEOUT_MS, "max_parallelism": 4},
            "degradation_policy": {"empty_results": "degrade_answer", "partial_results": "partial_answer", "tool_failure": "retry_or_degrade"},
        }
    )


def _normalize_tool_result(call_id: str, tool_name: str, target_shop_id: str, raw_result: dict[str, Any]) -> ToolResult:
    payload = dict(raw_result or {})
    if not payload.get("call_id"):
        payload["call_id"] = call_id
    if not payload.get("tool_name"):
        payload["tool_name"] = tool_name
    if not payload.get("shop_id"):
        payload["shop_id"] = target_shop_id
    if payload.get("error_code") == "":
        payload.pop("error_code", None)
    return ToolResult.model_validate(payload)


def _facet_from_task(task_type: str) -> str:
    normalized_task = _enum_value(task_type)
    if normalized_task in _TASK_TOOL_MAP:
        return _TASK_TOOL_MAP[normalized_task][1]
    if normalized_task in _DEAL_TASK_NAMES:
        return "deal"
    return "detail"


def _batch_facets_for_task(task_type: str, semantic_frame: dict[str, Any], primary_facet: str) -> list[str]:
    normalized_task = _enum_value(task_type)
    semantic_frame = _to_dict(semantic_frame)
    facets: list[str] = []
    for item in semantic_frame.get("facets", []) or []:
        facet = str(item.get("name", "") or item.get("facet", "") or "").strip() if isinstance(item, dict) else str(item or "").strip()
        if not facet or facet == primary_facet or facet in facets:
            continue
        tool_name = preferred_tool_for_facet(facet, task_type=normalized_task, has_target=True)
        if tool_name:
            facets.append(facet)
    return facets


def _budgeted_extra_facets(state: dict[str, Any], extra_facets: list[str]) -> list[str]:
    budget = budget_context_from_state(state)
    if budget.remaining("facet_enrich_budget") <= 0:
        return []
    deadline_remaining = budget.deadline_remaining_ms
    if isinstance(deadline_remaining, int) and deadline_remaining <= 50:
        return []
    if budget.remaining("facet_enrich_budget") <= 1 and len(extra_facets) > 1:
        return extra_facets[:1]
    return list(extra_facets)


def _tool_result_to_text(task_type: str, evidence: dict[str, Any], tool_result: ToolResult) -> str:
    evidence_dict = _to_dict(evidence)
    snapshot = evidence_dict.get("ranking_snapshot") or {}
    shop_name = str(snapshot.get("shop_name", "") or "").strip() or str(tool_result.data.get("shop_name", "") if isinstance(tool_result.data, dict) else "").strip() or "这家店"
    status = str(tool_result.result_status.value if hasattr(tool_result.result_status, "value") else tool_result.result_status or "").lower()
    data = tool_result.data

    if task_type == "shop_status":
        open_status = "unknown"
        if isinstance(data, dict):
            open_status = str(
                data.get("open_status")
                or ("open" if data.get("is_open") is True else "closed" if data.get("is_open") is False else data.get("open_status_text", "unknown"))
            ).lower()
        if status == "ok" and open_status == "open":
            return f"{shop_name}目前营业中。"
        if status == "ok" and open_status == "closed":
            return f"{shop_name}当前未营业。"
        return f"{shop_name}的营业状态暂时无法确认。"

    if task_type == "shop_distance":
        if status == "ok" and isinstance(data, dict):
            distance_km = data.get("distance_km")
            if distance_km is not None:
                return f"{shop_name}的直线距离约 {distance_km} 公里。"
            return f"{shop_name}的直线距离暂时无法确认。"
        return f"{shop_name}的直线距离暂时无法确认。"

    if task_type == "shop_coupon":
        if status == "ok" and isinstance(data, list):
            titles = [str(item.get("title", "")).strip() for item in data if isinstance(item, dict) and str(item.get("title", "")).strip()]
            if titles:
                return f"{shop_name}当前可用优惠券有：{'、'.join(titles[:3])}。"
            return f"{shop_name}当前暂无可用优惠券。"
        if status == "empty":
            return f"{shop_name}当前暂无可用优惠券。"
        return f"{shop_name}的优惠券情况暂时无法确认。"

    if task_type == "shop_review_summary":
        if status in {"ok", "partial"} and isinstance(data, dict):
            items = data.get("items") or []
            first = items[0] if items and isinstance(items[0], dict) else {}
            summary = str(first.get("summary", "") or "").strip()
            rating = first.get("rating")
            highlights = [str(item).strip() for item in first.get("highlights", []) or [] if str(item).strip()]
            parts = [f"{shop_name}的评价摘要："]
            if rating is not None:
                parts.append(f"评分约 {rating} 分")
            if summary:
                parts.append(summary)
            if highlights:
                parts.append(f"亮点：{'、'.join(highlights[:3])}")
            return " ".join(parts) + "。"
        return f"{shop_name}的评价摘要暂时无法确认。"

    if task_type == "shop_price":
        if status == "ok" and isinstance(data, dict):
            avg_price = data.get("avg_price")
            price_level = data.get("price_level")
            if avg_price is not None:
                level_text = f"，价格档位偏{price_level}" if price_level else ""
                return f"{shop_name}的人均约 {avg_price} 元{level_text}。"
        return f"{shop_name}的人均价格暂时无法确认。"

    if task_type in _DEAL_TASK_NAMES:
        if status in {"ok", "partial"} and isinstance(data, dict):
            items = data.get("items") or []
            titles = [str(item.get("title", "")).strip() for item in items if isinstance(item, dict) and str(item.get("title", "")).strip()]
            if titles:
                return f"{shop_name}当前可选团购/套餐有：{'、'.join(titles[:3])}。"
            return f"{shop_name}当前暂无可用团购/套餐。"
        if status == "empty":
            return f"{shop_name}当前暂无可用团购/套餐。"
        return f"{shop_name}的团购/套餐信息暂时无法确认。"

    return f"{shop_name}的信息我已经整理好了。"


def _facet_result_to_text(shop_name: str, facet: str, tool_result: ToolResult) -> str:
    data = tool_result.data if isinstance(tool_result.data, dict) else {}
    status = _enum_value(tool_result.result_status).lower()
    if facet == "coupon":
        if status in {"ok", "partial"}:
            items = data.get("items") or []
            titles = [str(item.get("title", "")).strip() for item in items if isinstance(item, dict) and str(item.get("title", "")).strip()]
            if titles:
                return f"{shop_name}有券，当前可用优惠券有：{'、'.join(titles[:3])}。"
            return f"{shop_name}有券，但当前暂无可用优惠券明细。"
        if status == "empty":
            return f"{shop_name}当前暂无可用优惠券。"
        return f"{shop_name}暂时无法确认优惠券情况。"
    if facet == "open_status":
        open_status = str(data.get("open_status", "") or data.get("status", "") or data.get("value", "") or "").lower()
        if status in {"ok", "partial"} and open_status in {"open", "opened", "open_now", "营业中"}:
            return f"{shop_name}目前营业中。"
        if status in {"ok", "partial"} and open_status in {"closed", "close", "closed_now", "已打烊"}:
            return f"{shop_name}当前不营业。"
        if status == "ok" and not open_status:
            return f"{shop_name}目前营业中。"
        if status == "empty":
            return f"{shop_name}当前不营业。"
        return f"{shop_name}暂时无法确认营业状态。"
    if facet == "distance":
        distance = data.get("distance_km", data.get("distance", data.get("value")))
        if distance is not None and str(distance).strip():
            return f"{shop_name}距离你约{distance}公里。"
        return f"{shop_name}暂时无法确认距离。"
    if facet == "review_summary":
        if status in {"ok", "partial"} and isinstance(data, dict):
            items = data.get("items") or []
            first = items[0] if items and isinstance(items[0], dict) else {}
            summary = str(first.get("summary", "") or "").strip()
            rating = first.get("rating")
            highlights = [str(item).strip() for item in first.get("highlights", []) or [] if str(item).strip()]
            parts = [f"{shop_name}的评价摘要："]
            if rating is not None:
                parts.append(f"评分约 {rating} 分")
            if summary:
                parts.append(summary)
            if highlights:
                parts.append(f"亮点：{'、'.join(highlights[:3])}")
            if len(parts) > 1:
                return " ".join(parts) + "。"
        return f"{shop_name}的评价摘要暂时无法确认。"
    if facet == "price":
        if status == "ok" and isinstance(data, dict):
            avg_price = data.get("avg_price")
            price_level = data.get("price_level")
            if avg_price is not None:
                level_text = f"，价格档位偏{price_level}" if price_level else ""
                return f"{shop_name}的人均约 {avg_price} 元{level_text}。"
        return f"{shop_name}的人均价格暂时无法确认。"
    if facet in _DEAL_TASK_NAMES:
        if status in {"ok", "partial"} and isinstance(data, dict):
            items = data.get("items") or []
            titles = [str(item.get("title", "")).strip() for item in items if isinstance(item, dict) and str(item.get("title", "")).strip()]
            if titles:
                return f"{shop_name}当前可选团购/套餐有：{'、'.join(titles[:3])}。"
            return f"{shop_name}当前暂无可用团购/套餐。"
        if status == "empty":
            return f"{shop_name}当前暂无可用团购/套餐。"
        return f"{shop_name}的团购/套餐信息暂时无法确认。"
    return _tool_result_to_text(_presentation_task_type("single_shop_query", facet), {"resolved_target": {"resolved_shop": {"shop_name": shop_name}}}, tool_result)


def _facet_record_to_text(shop_name: str, record: dict[str, Any]) -> str:
    facet = str(record.get("facet", "") or "").strip()
    status = str(record.get("status", "") or record.get("result_status", "") or "").lower()
    if facet == "coupon":
        value = record.get("value")
        items = record.get("items") or []
        titles = [str(item.get("title", "")).strip() for item in items if isinstance(item, dict) and str(item.get("title", "")).strip()]
        if titles:
            return f"{shop_name}有券，当前可用优惠券有：{'、'.join(titles[:3])}。"
        if isinstance(value, (int, float)) and value > 0:
            return f"{shop_name}有券。"
        if status == "empty":
            return f"{shop_name}当前暂无可用优惠券。"
        if status in {"ok", "partial"}:
            return f"{shop_name}有券。"
        return f"{shop_name}暂时无法确认优惠券情况。"
    if facet == "open_status":
        open_status = str(record.get("open_status") or record.get("value") or "").lower()
        if open_status in {"open", "opened", "open_now", "营业中"}:
            return f"{shop_name}目前营业中。"
        if open_status in {"closed", "close", "closed_now", "已打烊"}:
            return f"{shop_name}已打烊，当前不营业。"
        if status == "empty":
            return f"{shop_name}当前不营业。"
        if status in {"ok", "partial"}:
            return f"{shop_name}目前营业中。"
        return f"{shop_name}暂时无法确认营业状态。"
    if facet == "distance":
        distance = record.get("distance_km", record.get("distance", record.get("value")))
        if distance is not None and str(distance).strip():
            return f"{shop_name}距离你约{distance}公里。"
        if status == "failed":
            return f"{shop_name}暂时无法确认距离。"
        return f"{shop_name}暂时无法确认距离。"
    if facet == "review_summary":
        summary = str(record.get("summary", "") or "").strip()
        rating = record.get("rating")
        highlights = [str(item).strip() for item in record.get("highlights", []) or [] if str(item).strip()]
        parts = [f"{shop_name}的评价摘要："]
        if rating is not None:
            parts.append(f"评分约 {rating} 分")
        if summary:
            parts.append(summary)
        if highlights:
            parts.append(f"亮点：{'、'.join(highlights[:3])}")
        if len(parts) > 1:
            return " ".join(parts) + "。"
        return f"{shop_name}的评价摘要暂时无法确认。"
    if facet == "price":
        avg_price = record.get("avg_price", record.get("value"))
        price_level = record.get("price_level")
        if avg_price is not None:
            level_text = f"，价格档位偏{price_level}" if price_level else ""
            return f"{shop_name}的人均约 {avg_price} 元{level_text}。"
        return f"{shop_name}的人均价格暂时无法确认。"
    if facet in _DEAL_TASK_NAMES:
        items = record.get("items") or []
        titles = [str(item.get("title", "")).strip() for item in items if isinstance(item, dict) and str(item.get("title", "")).strip()]
        if titles:
            return f"{shop_name}当前可选团购/套餐有：{'、'.join(titles[:3])}。"
        if status == "empty":
            return f"{shop_name}当前暂无可用团购/套餐。"
        if status in {"ok", "partial"}:
            return f"{shop_name}当前可选团购/套餐有。"
        return f"{shop_name}的团购/套餐信息暂时无法确认。"
    return ""


def _compose_multi_facet_answer(
    *,
    shop_name: str,
    execution_plan: ExecutionPlan,
    tool_results: dict[str, ToolResult],
    primary_tool_result: ToolResult,
    evidence: EvidencePack,
    facet: str,
) -> str:
    ordered_parts: list[str] = []
    evidence_dict = evidence.model_dump()
    facet_results = [item for item in (evidence_dict.get("facet_results") or []) if isinstance(item, dict)]
    if facet_results:
        for item in facet_results:
            text = _facet_record_to_text(shop_name, item)
            if text:
                ordered_parts.append(text)
    else:
        seen_facets: set[str] = set()
        for call in list(getattr(execution_plan, "tool_calls", []) or []):
            call_dict = _to_dict(call)
            facet_name = str(call_dict.get("facet", "") or "").strip()
            call_id = str(call_dict.get("call_id", "") or "").strip()
            if not facet_name or facet_name in seen_facets:
                continue
            seen_facets.add(facet_name)
            tool_result = tool_results.get(call_id) or primary_tool_result
            ordered_parts.append(_facet_result_to_text(shop_name, facet_name, tool_result))

    if len(ordered_parts) <= 1:
        return _tool_result_to_text(_presentation_task_type("single_shop_query", facet), evidence_dict, primary_tool_result)

    return f"{shop_name}：" + "；".join(part.rstrip("。") for part in ordered_parts if part) + "。"


def _build_success_patch(
    *,
    state: dict[str, Any],
    decision: OrchestrationDecision,
    task_type: str,
    target: dict[str, Any],
    execution_plan: ExecutionPlan,
    tool_results: dict[str, ToolResult],
    primary_tool_result: ToolResult,
    evidence: EvidencePack,
    answer_plan: AnswerPlan,
    facet: str,
) -> dict[str, Any]:
    state_task_type = _enum_value(state.get("task_type")) or _enum_value(_to_dict(state.get("semantic_frame")).get("task_type")) or _enum_value(task_type)
    presentation_task_type = _presentation_task_type(task_type, facet)
    canonical_shop_entity = {
        "status": "resolved",
        "mention": str(target.get("shop_name", "") or ""),
        "shop_id": str(target.get("shop_id", "") or "").strip(),
        "shop_name": str(target.get("shop_name", "") or "").strip(),
        "canonical_name": str(target.get("shop_name", "") or "").strip(),
        "branch_name": "",
        "alias": [],
        "confidence": 1.0,
        "source": "resolved",
        "resolution_reason": "deterministic_target_resolved",
        "needs_clarification": False,
        "clarification_question": "",
        "candidates": [],
        "selected_candidate": None,
        "candidate_count": 1,
        "trace": [{"mention": str(target.get("shop_name", "") or ""), "result": "resolved"}],
    }
    resolved_target = ResolveShopResult(
        status="RESOLVED",
        resolved_shop=ShopRef(shop_id=target["shop_id"], shop_name=target["shop_name"]),
        confidence=1.0,
        reason="deterministic_target_resolved",
    )
    answer_text = _compose_multi_facet_answer(
        shop_name=str(target.get("shop_name", "") or ""),
        execution_plan=execution_plan,
        tool_results=tool_results,
        primary_tool_result=primary_tool_result,
        evidence=evidence,
        facet=facet,
    )
    verify = verify_answer(answer_text, evidence.model_dump(), presentation_task_type)
    if not verify.get("passed", False):
        answer_text = _tool_result_to_text(presentation_task_type, evidence.model_dump(), primary_tool_result)
    response_directive = build_response_directive(
        answer_text=answer_text,
        answer_type=str(getattr(answer_plan, "answer_type", "") or ""),
        response_mode="direct",
        fallback_reason="" if verify.get("passed", False) else "deterministic_verifier_rejected",
        trace_id=str(state.get("trace_id", "") or ""),
        preview_text=answer_text,
        answer_source="deterministic_tool_workflow",
        fallback_template_type=str(getattr(answer_plan, "fallback_template_type", "") or ""),
        metadata={
            "workflow_name": "single_shop_fact_workflow",
            "verifier_result": "pass" if verify.get("passed", False) else "rewrite_needed",
        },
    )
    timestamp = datetime.now(timezone.utc).isoformat()
    return {
        "workflow_name": "single_shop_fact_workflow",
        "orchestration_pattern": "deterministic_tool",
        "task_type": state_task_type,
        "workflow_reason": str(decision.workflow_reason or f"deterministic tool for {presentation_task_type}"),
        "workflow_run_status": "completed",
        "workflow_runner_error": "",
        "workflow_runner_reason": str(decision.workflow_reason or f"deterministic tool for {presentation_task_type}"),
        "workflow_candidate_reason": str(decision.workflow_reason or f"deterministic tool for {presentation_task_type}"),
        "workflow_started_at": timestamp,
        "workflow_finished_at": timestamp,
        "workflow_callable": "run_deterministic_tool_workflow",
        "workflow_registered": True,
        "response_mode": "direct",
        "next_action": "run_workflow",
        "execution_plan": execution_plan,
        "validated_plan": execution_plan,
        "tool_results": tool_results,
        "tool_result_set": tool_results,
        "facets": list(getattr(execution_plan, "facets", []) or []),
        "target_resolution": getattr(execution_plan, "target_resolution", None) or {
            "resolved": True,
            "target_shop": {"shop_id": target["shop_id"], "shop_name": target["shop_name"]},
            "source": "target_resolution",
            "confidence": 1.0,
            "owner": "deterministic_tool_workflow",
            "resolution_reason": "deterministic_target_resolved",
            "reference_type": "current_shop",
            "unresolved_reason": None,
            "comparison_targets": [],
        },
        "conflicting_facets": list(getattr(execution_plan, "conflicting_facets", []) or []),
        "ranking_policy": getattr(execution_plan, "ranking_policy", None),
        "resolved_target": resolved_target,
        "resolve_shop_result": resolved_target,
        "canonical_shop_entity": canonical_shop_entity,
        "canonical_shop_entities": [canonical_shop_entity],
        "shop_resolution_trace": list(canonical_shop_entity.get("trace", []) or []),
        "evidence_pack": evidence,
        "answer_plan": answer_plan,
        "draft_response": answer_text,
        "response_directive": response_directive,
        "answer_source": "deterministic_tool_workflow",
        "preview_text": answer_text,
        "preview_policy_result": {"verified": True, "allowed": True, "reason": "verified"},
        "answer_verify_passed": bool(verify.get("passed", False)),
        "answer_verify_violations": list(verify.get("issues") or []),
        "verify_result": "pass" if verify.get("passed", False) else "rewrite_needed",
        "final_safety_status": "safe" if verify.get("passed", False) else "fallback",
        "fallback_reason": "" if verify.get("passed", False) else "deterministic_verifier_rejected",
        "answer_fallback_reason": "" if verify.get("passed", False) else "deterministic_verifier_rejected",
        "llm_verbalizer_called": False,
        "llm_called": False,
        "llm_backend": "deterministic",
        "llm_verbalizer_violation": None,
        "llm_verbalizer_error": None,
        "generated_llm_answer_before_fallback": "",
        "reference_resolution_source": "deterministic_tool_workflow",
        "comparison_targets": [],
        "last_recommendation_list": state.get("last_recommendation_list", []),
        "last_answer_order": state.get("last_answer_order", []),
        "stream_status": "completed",
    }


def _build_clarify_patch(state: dict[str, Any], decision: OrchestrationDecision, pending: dict[str, Any], reason: str) -> dict[str, Any]:
    state_task_type = _enum_value(state.get("task_type")) or _enum_value(_to_dict(state.get("semantic_frame")).get("task_type"))
    prompt = format_pending_prompt(pending)
    timestamp = datetime.now(timezone.utc).isoformat()
    candidate_targets = [
        {
            "shop_id": str(item.get("shop_id", "") or "").strip(),
            "shop_name": str(item.get("shop_name", "") or "").strip(),
            "address": str(item.get("address", "") or "").strip(),
        }
        for item in (pending.get("candidate_targets") or [])
        if str(item.get("shop_id", "") or "").strip() and str(item.get("shop_name", "") or "").strip()
    ]
    resolve_status = "AMBIGUOUS" if candidate_targets else "NOT_FOUND"
    resolve_kwargs: dict[str, Any] = {
        "status": resolve_status,
        "candidates": candidate_targets,
        "confidence": 0.0,
        "reason": reason,
    }
    if resolve_status == "NOT_FOUND":
        resolve_kwargs["candidates"] = []
    return {
        "workflow_name": "clarification_fallback",
        "orchestration_pattern": "clarification_fallback",
        "task_type": state_task_type,
        "workflow_reason": reason,
        "workflow_run_status": "fallback",
        "workflow_runner_error": "",
        "workflow_runner_reason": reason,
        "workflow_candidate_reason": reason,
        "workflow_started_at": timestamp,
        "workflow_finished_at": timestamp,
        "workflow_callable": "run_deterministic_tool_workflow",
        "workflow_registered": True,
        "response_mode": "clarify",
        "next_action": "clarify",
        "pending_clarification": pending,
        "resolve_shop_result": ResolveShopResult.model_validate(resolve_kwargs),
        "canonical_shop_entity": {
            "status": "ambiguous" if resolve_status == "AMBIGUOUS" else "not_found",
            "mention": str(pending.get("original_text", "") or ""),
            "shop_id": "",
            "shop_name": "",
            "canonical_name": "",
            "branch_name": "",
            "alias": [],
            "confidence": 0.0,
            "source": "reference",
            "resolution_reason": reason,
            "needs_clarification": True,
            "clarification_question": prompt,
            "candidates": candidate_targets,
            "selected_candidate": None,
            "candidate_count": len(candidate_targets),
            "trace": [{"mention": str(pending.get("original_text", "") or ""), "result": "clarify", "reason": reason}],
        },
        "canonical_shop_entities": candidate_targets,
        "shop_resolution_trace": [{"mention": str(pending.get("original_text", "") or ""), "result": "clarify", "reason": reason}],
        "target_resolution": {
            "resolved": False,
            "target_shop": None,
            "source": pending.get("source_node", "deterministic_tool_workflow"),
            "confidence": 0.0,
            "owner": "deterministic_tool_workflow",
            "resolution_reason": reason,
            "reference_type": "current_shop" if "current_shop" in reason else "ordinal_reference" if "ordinal" in reason else "comparison_targets",
            "unresolved_reason": reason,
            "comparison_targets": candidate_targets,
        },
        "draft_response": prompt,
        "response_directive": build_response_directive(
            answer_text=prompt,
            answer_type="clarification",
            response_mode="clarify",
            fallback_reason=reason,
            trace_id=str(state.get("trace_id", "") or ""),
            preview_text=prompt,
            answer_source="clarification_fallback_workflow",
            fallback_template_type="clarify",
        ),
        "answer_source": "clarification_fallback_workflow",
        "answer_verify_passed": False,
        "answer_verify_violations": [],
        "verify_result": "pass",
        "final_safety_status": "safe",
        "fallback_reason": reason,
        "answer_fallback_reason": reason,
        "llm_verbalizer_called": False,
        "llm_called": False,
        "llm_backend": "deterministic",
        "comparison_targets": [],
        "last_recommendation_list": state.get("last_recommendation_list", []),
        "last_answer_order": state.get("last_answer_order", []),
    }


def run_deterministic_tool_workflow(
    state: dict[str, Any],
    decision: OrchestrationDecision | None = None,
    *,
    dispatch_tool_call=None,
) -> dict[str, Any]:
    """Run the Phase 6 deterministic tool workflow."""

    decision = decision or _to_dict(state.get("orchestration_decision"))
    if not isinstance(decision, OrchestrationDecision):
        decision = OrchestrationDecision.model_validate(_to_dict(decision) or {
            "orchestration_pattern": "deterministic_tool",
            "workflow_name": "deterministic_tool",
            "workflow_reason": "deterministic tool workflow",
            "task_complexity": "low",
            "requires_tool": True,
            "requires_clarification": False,
            "response_mode": "tool_answer",
            "confidence": 0.0,
            "missing_fields": [],
            "next_action": "run_workflow",
        })

    semantic_frame = _to_dict(state.get("semantic_frame"))
    task_type = _enum_value(state.get("task_type")) or _enum_value(semantic_frame.get("task_type"))
    if dispatch_tool_call is None:
        from ...engine import graph_builder as _graph_builder

        dispatch_tool_call = _graph_builder.dispatch_tool_call
    route_info = _task_to_tool(task_type, semantic_frame)
    if route_info is None:
        route_info = _route_info_from_raw_text(str(state.get("raw_text", "") or state.get("normalized_text", "") or ""))
    else:
        raw_route_info = _route_info_from_raw_text(str(state.get("raw_text", "") or state.get("normalized_text", "") or ""))
        if raw_route_info is not None and raw_route_info != route_info:
            route_info = raw_route_info
    log_kv(
        _LOGGER,
        20,
        "[SUBGRAPH_ENTER]",
        tone="route",
        subgraph="deterministic_tool_workflow",
        trace_id=state.get("trace_id", ""),
        session_id=state.get("session_id", ""),
        turn_id=state.get("turn_id", ""),
        task_type=task_type,
        workflow_name="deterministic_tool",
    )

    if route_info is None:
        pending = build_pending_clarification(
            original_text=str(state.get("raw_text", "") or ""),
            original_semantic_frame=semantic_frame,
            original_task_type=task_type,
            candidate_targets=[],
            reason="deterministic_task_unsupported",
            source_node="deterministic_tool_workflow",
        ).model_dump()
        patch = _build_clarify_patch(state, decision, pending, "deterministic_task_unsupported")
        patch.update(_log(state, "deterministic_tool_workflow", workflow_name="deterministic_tool", task_type=task_type, status="clarify", reason="deterministic_task_unsupported"))
        return patch

    tool_name, facet = route_info
    target, pending, reason = _resolve_single_shop_target(state)
    if target is None or pending is not None:
        patch = _build_clarify_patch(state, decision, pending or {}, reason)
        patch.update(_log(state, "deterministic_tool_workflow", workflow_name="deterministic_tool", task_type=task_type, status="clarify", reason=reason))
        return patch

    if facet == "distance" and not _extract_user_location(state):
        pending = build_pending_clarification(
            original_text=str(state.get("raw_text", "") or ""),
            original_semantic_frame=semantic_frame,
            original_task_type=task_type,
            candidate_targets=[target],
            reason="missing_exploration_location",
            missing_slot_type="missing_exploration_location",
            source_node="deterministic_tool_workflow",
        ).model_dump()
        patch = _build_clarify_patch(state, decision, pending, "missing_exploration_location")
        patch["workflow_name"] = "clarification_fallback"
        patch["workflow_run_status"] = "fallback"
        patch["response_mode"] = "fallback"
        patch.update(_log(state, "deterministic_tool_workflow", workflow_name="deterministic_tool", task_type=task_type, status="fallback", reason="missing_exploration_location"))
        return patch

    budget = budget_context_from_state(state)
    if budget.remaining("tool_round_budget") <= 0:
        pending = build_pending_clarification(
            original_text=str(state.get("raw_text", "") or ""),
            original_semantic_frame=semantic_frame,
            original_task_type=task_type,
            candidate_targets=[target],
            reason="budget_exhausted:tool_round_budget",
            source_node="deterministic_tool_workflow",
        ).model_dump()
        patch = _build_clarify_patch(state, decision, pending, "budget_exhausted:tool_round_budget")
        patch["workflow_name"] = "clarification_fallback"
        patch["workflow_run_status"] = "fallback"
        patch["response_mode"] = "fallback"
        patch.update(_log(state, "deterministic_tool_workflow", workflow_name="deterministic_tool", task_type=task_type, status="fallback", reason="budget_exhausted:tool_round_budget"))
        return patch

    args = _tool_args_for_task(task_type, target["shop_id"], state)
    semantic_frame = _to_dict(state.get("semantic_frame"))
    extra_facets = _budgeted_extra_facets(state, _batch_facets_for_task(task_type, semantic_frame, facet))
    execution_plan = _build_execution_plan(
        task_type,
        target["shop_id"],
        tool_name,
        facet,
        args,
        state,
        extra_facets=extra_facets,
    )

    batch_executor = ToolBatchExecutor(call_fn=dispatch_tool_call, cache=get_default_evidence_cache())
    raw_results = batch_executor.execute(execution_plan.tool_calls)
    primary_call = raw_results.get("call_1") or {}
    primary_tool_result = _normalize_tool_result("call_1", tool_name, target["shop_id"], primary_call)
    tool_results = {
        call_id: _normalize_tool_result(
            call_id,
            str((result or {}).get("tool_name", "") or tool_name),
            str((result or {}).get("shop_id", "") or target["shop_id"]),
            result,
        )
        for call_id, result in raw_results.items()
    }

    evidence_dict = build_evidence(
        tool_results={call_id: result.model_dump() for call_id, result in tool_results.items()},
        resolved_target={"status": "RESOLVED", "resolved_shop": {"shop_id": target["shop_id"], "shop_name": target["shop_name"]}},
        execution_plan=execution_plan.model_dump(),
        recommendation_candidates=[],
        comparison_targets=[],
        cache=get_default_evidence_cache(),
        cache_scope={
            "workflow": "deterministic_tool_workflow",
            "trace_id": state.get("trace_id", ""),
            "session_id": state.get("session_id", ""),
            "turn_id": state.get("turn_id", ""),
        },
    )

    if facet == "price":
        snapshot = evidence_dict.get("ranking_snapshot") or {}
        if isinstance(primary_tool_result.data, dict):
            snapshot["avg_price"] = primary_tool_result.data.get("avg_price")
            snapshot["price_level"] = primary_tool_result.data.get("price_level")
            evidence_dict["ranking_snapshot"] = snapshot
            facet_results = list(evidence_dict.get("facet_results") or [])
            if facet_results:
                facet_results[-1]["value"] = primary_tool_result.data.get("avg_price")
                facet_results[-1]["status"] = "ok" if primary_tool_result.result_status.value in {"ok", "partial"} else primary_tool_result.result_status.value
                evidence_dict["facet_results"] = facet_results

    evidence = EvidencePack.model_validate(evidence_dict)
    answer_plan = AnswerPlan.model_validate(build_answer_plan(task_type, evidence.model_dump()))

    patch = _build_success_patch(
        state=state,
        decision=decision,
        task_type=task_type,
        target=target,
        execution_plan=execution_plan,
        tool_results=tool_results,
        primary_tool_result=primary_tool_result,
        evidence=evidence,
        answer_plan=answer_plan,
        facet=facet,
    )
    patch["workflow_reason"] = str(decision.workflow_reason or f"deterministic tool for {task_type}")
    patch["workflow_runner_reason"] = patch["workflow_reason"]
    patch["workflow_candidate_reason"] = patch["workflow_reason"]
    patch["workflow_run_status"] = "completed" if patch.get("answer_verify_passed", False) else "fallback"
    if not patch.get("answer_verify_passed", False):
        patch["response_mode"] = "fallback"
        patch["next_action"] = "fallback"
        patch["workflow_runner_error"] = "ANSWER_VERIFIER_FAILED"
    patch.update(_log(state, "deterministic_tool_workflow", workflow_name="deterministic_tool", task_type=task_type, status=patch["workflow_run_status"], tool_name=tool_name, facet=facet, target_shop_id=target["shop_id"], extra_facets=extra_facets, batch_calls=len(tool_results)))
    log_kv(
        _LOGGER,
        20 if patch["workflow_run_status"] == "completed" else 30,
        "[WORKFLOW_RUNNER]",
        tone="route" if patch["workflow_run_status"] == "completed" else "warn",
        node_name="deterministic_tool_workflow",
        workflow_name="deterministic_tool",
        task_type=task_type,
        tool_name=tool_name,
        facet=facet,
        target_shop_id=target["shop_id"],
        status=patch["workflow_run_status"],
    )
    return patch
