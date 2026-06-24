"""Adapter that turns a constrained ToolPlan into an execution plan."""

from __future__ import annotations

from typing import Any

from .. import config
from ..config import MOCK_LOCATION, TOOL_DEFAULT_TIMEOUT_MS
from ..domain.enums import TaskType
from ..domain.schemas import ExecutionPlan, ToolIntent, ToolPlan
from ..llm.client import LLMBackend
from .execution_plan_builder import build_execution_plan, build_recommendation_execution_plan
from .comparison_planner import plan_comparison
from .llm_tool_planner import ToolPlanDecision, build_tool_plan


MAX_COMPARISON_TARGETS = 5


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


def _task_type_value(value: Any) -> str:
    if hasattr(value, "value"):
        value = getattr(value, "value")
    return str(value or "").strip()


def _intent_names(tool_plan: ToolPlan | None) -> list[str]:
    names: list[str] = []
    if tool_plan is None:
        return names
    for intent in tool_plan.tool_intents:
        name = str(intent.tool_name or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def _first_scene_hint(frame: dict[str, Any]) -> str | None:
    soft_preferences = _to_dict(frame.get("soft_preferences"))
    hard_constraints = _to_dict(frame.get("hard_constraints"))
    scene_terms = [str(item).strip() for item in soft_preferences.get("scene_terms", []) or [] if str(item).strip()]
    if scene_terms:
        return scene_terms[0]
    scene = hard_constraints.get("scene")
    if isinstance(scene, str) and scene.strip():
        return scene.strip()
    return None


def _deal_hints(text: str, frame: dict[str, Any]) -> bool:
    if any(token in text for token in ("团购", "套餐", "双人餐", "多人餐", "双人", "多人", "代金券", "固定价格", "组合套餐")):
        return True
    primary_task = str(frame.get("primary_task", "") or "")
    return "deal" in primary_task.lower()


def _user_location(state: dict[str, Any]) -> dict[str, Any]:
    user_context = state.get("user_context")
    if user_context is None:
        return dict(MOCK_LOCATION)
    user_ctx = _to_dict(user_context)
    if not user_ctx:
        return dict(MOCK_LOCATION)
    lat = user_ctx.get("lat", MOCK_LOCATION["lat"])
    lng = user_ctx.get("lng", MOCK_LOCATION["lng"])
    return {"lat": lat, "lng": lng}


def _single_shop_id(state: dict[str, Any]) -> str:
    resolved_target = _to_dict(state.get("resolved_target") or state.get("resolve_shop_result"))
    if resolved_target.get("status") == "RESOLVED":
        resolved_shop = resolved_target.get("resolved_shop") or resolved_target.get("shop") or {}
        resolved_shop = _to_dict(resolved_shop)
        sid = str(resolved_shop.get("shop_id", "")).strip()
        if sid:
            return sid
    current_shop = _to_dict(state.get("current_shop"))
    sid = str(current_shop.get("shop_id", "")).strip()
    if sid:
        return sid
    return ""


def _comparison_target_ids(state: dict[str, Any]) -> list[str]:
    target_ids: list[str] = []
    for item in state.get("comparison_targets", []) or []:
        data = _to_dict(item)
        resolved_shop = data.get("resolved_shop") or data.get("shop") or data
        resolved_shop = _to_dict(resolved_shop)
        sid = str(resolved_shop.get("shop_id", "")).strip() or str(data.get("shop_id", "")).strip()
        if sid and sid not in target_ids:
            target_ids.append(sid)
    if not target_ids:
        # Fall back to candidate_set (P0 CandidateSet flow)
        cs = state.get("candidate_set")
        if cs is not None:
            cs_dict = _to_dict(cs)
            for c in cs_dict.get("candidates", []) or []:
                sid = str(c.get("shop_id", "")).strip()
                if sid and sid not in target_ids:
                    target_ids.append(sid)
    if not target_ids:
        resolved = _single_shop_id(state)
        if resolved:
            target_ids.append(resolved)
    return target_ids


def _semantic_frame_query(frame: dict[str, Any]) -> tuple[str, str | None]:
    direct_query = str(frame.get("query", "") or frame.get("search_query", "") or "").strip()
    if direct_query:
        return direct_query, None

    constraints = _to_dict(frame.get("constraints"))
    for key in ("cuisine", "category"):
        query = str(constraints.get(key, "") or "").strip()
        if query:
            return query, "fallback_query_from_semantic_frame"

    hard_constraints = _to_dict(frame.get("hard_constraints"))
    for key in ("cuisine", "category"):
        query = str(hard_constraints.get(key, "") or "").strip()
        if query:
            return query, "fallback_query_from_constraints"

    return "", None


def _raw_recommendation_query(raw_text: str) -> str:
    text = str(raw_text or "").strip()
    if not text:
        return ""

    stripped = text
    for prefix in (
        "附近推荐",
        "推荐附近",
        "推荐",
        "找",
        "附近",
        "查询",
        "寻找",
        "有",
        "来",
        "求推荐",
        "求",
        "想找",
        "想要",
        "需要",
        "我要找",
        "想吃",
        "想去",
        "有没有",
    ):
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix):].strip()
            break
    for suffix in ("的店", "的地方", "的馆子", "的餐厅", "推荐", "的", "一下", "呗", "吧", "呢", "吗", "啊"):
        if stripped.endswith(suffix):
            stripped = stripped[:-len(suffix)].strip()
            break
    if stripped and len(stripped) >= 2:
        return stripped
    return ""


def _recommendation_query(state: dict[str, Any]) -> tuple[str, str | None]:
    frame = _to_dict(state.get("semantic_frame"))
    query, reason = _semantic_frame_query(frame)
    if query:
        return query, reason

    session_state = state.get("session_state_before") or state.get("session_state") or {}
    session_dict = _to_dict(session_state)
    for item in session_dict.get("last_recommendation_list", []) or []:
        item_dict = _to_dict(item)
        category = str(item_dict.get("category", "") or "").strip()
        shop_name = str(item_dict.get("shop_name", "") or "").strip()
        if category:
            return category, "fallback_query_from_session_context"
        if "火锅" in shop_name:
            return "火锅", "fallback_query_from_session_context"
    if session_dict.get("last_recommendation_list"):
        first = _to_dict(session_dict["last_recommendation_list"][0])
        first_name = str(first.get("shop_name", "")).strip()
        import re as _re
        core = _re.sub(r"\([^)]*\)", "", first_name).strip() if first_name else ""
        if core:
            return core, "fallback_query_from_session_context"
    raw = str(state.get("raw_text", "") or "").strip()
    raw_query = _raw_recommendation_query(raw)
    if raw_query:
        return raw_query, "fallback_query_from_raw_text"
    return "", "empty_recommendation_query"


def _make_call(
    *,
    call_id: str,
    tool_name: str,
    args: dict[str, Any],
    target_shop_id: str = "",
    required: bool = False,
    facet: str = "",
    depends_on: list[str] | None = None,
    timeout_ms: int = TOOL_DEFAULT_TIMEOUT_MS,
    group_id: str = "",
    max_parallelism: int = 1,
) -> dict[str, Any]:
    return {
        "call_id": call_id,
        "tool_name": tool_name,
        "args": args,
        "target_shop_id": target_shop_id,
        "required": required,
        "facet": facet,
        "depends_on": depends_on or [],
        "timeout_ms": timeout_ms,
        "retry_policy": {"max_attempts": 1 if required else 0, "backoff_ms": 0},
        "fallback_policy": {"fallback_tool": "", "fallback_args": {}},
        "group_id": group_id,
        "max_parallelism": max_parallelism,
    }


def _batch_tool_plan_present(tool_plan: ToolPlan | None) -> bool:
    return any(name in {"get_shop_cards", "get_shop_review_summary", "get_deal_list"} for name in _intent_names(tool_plan))


def _build_single_shop_execution_plan(
    state: dict[str, Any],
    *,
    tool_plan: ToolPlan | None,
    tool_plan_source: str,
    tool_plan_validated: bool,
    tool_plan_fallback_reason: str | None,
) -> dict[str, Any]:
    frame = _to_dict(state.get("semantic_frame"))
    resolved_target = _to_dict(state.get("resolved_target"))
    target = resolved_target.get("resolved_shop") or resolved_target.get("shop") or {}
    target = _to_dict(target)
    shop_id = str(target.get("shop_id", "")).strip() or _single_shop_id(state)
    if not shop_id:
        plan_dict = build_execution_plan(_task_type_value(state.get("task_type") or frame.get("task_type")), resolved_target, frame.get("facets", []))
        plan = ExecutionPlan.model_validate(plan_dict)
        return {
            "execution_plan": plan,
            "tool_plan": tool_plan,
            "tool_plan_source": tool_plan_source,
            "tool_plan_validated": tool_plan_validated,
            "tool_plan_fallback_reason": tool_plan_fallback_reason,
            "tool_plan_reason": None,
        }

    tool_names = set(_intent_names(tool_plan))
    use_batch_plan = bool(tool_names & {"get_shop_cards", "get_shop_review_summary", "get_deal_list"})
    if not use_batch_plan:
        plan_dict = build_execution_plan(_task_type_value(state.get("task_type") or frame.get("task_type")), resolved_target, frame.get("facets", []))
        plan = ExecutionPlan.model_validate(plan_dict)
        return {
            "execution_plan": plan,
            "tool_plan": tool_plan,
            "tool_plan_source": tool_plan_source,
            "tool_plan_validated": tool_plan_validated,
            "tool_plan_fallback_reason": tool_plan_fallback_reason,
            "tool_plan_reason": None,
        }

    facets = frame.get("facets", []) or []
    facet_names = {str(item.get("name", "")).strip() for item in facets if isinstance(item, dict)}
    location = _user_location(state)
    tool_calls: list[dict[str, Any]] = []
    stage_tool_names: list[str] = []
    stage_tools: list[str] = []

    stage_tool_names.append("get_shop_cards")
    stage_tools.append("get_shop_cards")
    tool_calls.append(
        _make_call(
            call_id="call_shop_cards",
            tool_name="get_shop_cards",
            args={
                "shop_ids": [shop_id],
                "user_location": location,
                "need_coupon_brief": True,
                "need_open_status": True,
                "need_distance_eta": True,
                "max_items": 1,
            },
            target_shop_id=shop_id,
            facet="shop_cards",
            group_id="single_shop_batch",
        )
    )

    if "get_shop_review_summary" in tool_names:
        stage_tool_names.append("get_shop_review_summary")
        stage_tools.append("get_shop_review_summary")
        tool_calls.append(
            _make_call(
                call_id="call_review_summary",
                tool_name="get_shop_review_summary",
                args={
                    "shop_ids": [shop_id],
                    "aspects": sorted(facet_names or {"review_summary"}),
                    "scene": _first_scene_hint(frame),
                    "max_reviews": 1,
                },
                target_shop_id=shop_id,
                facet="review_summary",
                group_id="single_shop_batch",
            )
        )

    if "get_deal_list" in tool_names or _deal_hints(str(state.get("raw_text", "") or ""), frame):
        stage_tool_names.append("get_deal_list")
        stage_tools.append("get_deal_list")
        hard_constraints = _to_dict(frame.get("hard_constraints"))
        people_count = hard_constraints.get("people_count")
        budget_per_person = hard_constraints.get("budget_per_person")
        tool_calls.append(
            _make_call(
                call_id="call_deal_list",
                tool_name="get_deal_list",
                args={
                    "shop_id": shop_id,
                    "people_count": people_count if isinstance(people_count, int) else None,
                    "budget_per_person": budget_per_person if isinstance(budget_per_person, (int, float)) else None,
                    "deal_type": hard_constraints.get("deal_type"),
                    "only_available": True,
                },
                target_shop_id=shop_id,
                facet="deal",
                group_id="single_shop_batch",
            )
        )

    if not tool_calls:
        plan_dict = build_execution_plan(_task_type_value(state.get("task_type") or frame.get("task_type")), resolved_target, frame.get("facets", []))
        plan = ExecutionPlan.model_validate(plan_dict)
        return {
            "execution_plan": plan,
            "tool_plan": tool_plan,
            "tool_plan_source": tool_plan_source,
            "tool_plan_validated": tool_plan_validated,
            "tool_plan_fallback_reason": tool_plan_fallback_reason,
            "tool_plan_reason": None,
        }

    plan = ExecutionPlan.model_validate(
        {
            "plan_id": f"plan_{shop_id}_tool_planned",
            "task_type": _task_type_value(state.get("task_type") or frame.get("task_type")),
            "tool_calls": tool_calls,
            "stages": [
                {
                    "stage_id": "stage_1",
                    "description": "LLM tool planner batch plan for single-shop query",
                    "tool_names": sorted(set(stage_tools)),
                    "depends_on": [],
                    "max_parallelism": max(1, min(len(tool_calls), config.MAX_CONCURRENCY)),
                }
            ],
            "target_shop_ids": [shop_id],
        }
    )
    return {
        "execution_plan": plan,
        "tool_plan": tool_plan,
        "tool_plan_source": tool_plan_source,
        "tool_plan_validated": tool_plan_validated,
        "tool_plan_fallback_reason": tool_plan_fallback_reason,
        "tool_plan_reason": None,
    }


def _build_recommendation_execution_plan(
    state: dict[str, Any],
    *,
    tool_plan: ToolPlan | None,
    tool_plan_source: str,
    tool_plan_validated: bool,
    tool_plan_fallback_reason: str | None,
) -> dict[str, Any]:
    frame = _to_dict(state.get("semantic_frame"))
    tool_names = set(_intent_names(tool_plan))
    use_batch_plan = bool(tool_names & {"get_shop_cards", "get_shop_review_summary"})

    if not use_batch_plan:
        query, query_reason = _recommendation_query(state)
        if not query:
            empty_plan = ExecutionPlan.model_validate(
                {
                    "plan_id": "recommendation_plan_empty_query",
                    "task_type": TaskType.recommendation.value,
                    "tool_calls": [],
                    "stages": [],
                    "target_shop_ids": [],
                }
            )
            return {
                "execution_plan": empty_plan,
                "recommendation_query": "",
                "query_terms": [],
                "scene_terms": [],
                "recommendation_candidates": [],
                "tool_plan": tool_plan,
                "tool_plan_source": "fallback",
                "tool_plan_validated": False,
                "tool_plan_fallback_reason": "clarify_required_empty_query",
                "tool_plan_reason": query_reason or "empty_recommendation_query",
            }
        frame_for_plan = dict(frame)
        frame_for_plan["query"] = query
        plan_payload = build_recommendation_execution_plan(
            frame_for_plan,
            location=_user_location(state),
            fallback_query=query,
        )
        plan = ExecutionPlan.model_validate(plan_payload.get("plan", {}))
        return {
            "execution_plan": plan,
            "recommendation_query": plan_payload.get("recommendation_query", query),
            "query_terms": plan_payload.get("query_terms", []),
            "scene_terms": plan_payload.get("scene_terms", []),
            "recommendation_candidates": [],
            "tool_plan": tool_plan,
            "tool_plan_source": tool_plan_source,
            "tool_plan_validated": tool_plan_validated,
            "tool_plan_fallback_reason": tool_plan_fallback_reason,
            "tool_plan_reason": query_reason,
        }

    query, query_reason = _recommendation_query(state)
    if not query:
        empty_plan = ExecutionPlan.model_validate(
            {
                "plan_id": "recommendation_plan_empty_query",
                "task_type": TaskType.recommendation.value,
                "tool_calls": [],
                "stages": [],
                "target_shop_ids": [],
            }
        )
        return {
            "execution_plan": empty_plan,
            "recommendation_query": "",
            "query_terms": [],
            "scene_terms": [],
            "recommendation_candidates": [],
            "tool_plan": tool_plan,
            "tool_plan_source": "fallback",
            "tool_plan_validated": False,
            "tool_plan_fallback_reason": "clarify_required_empty_query",
            "tool_plan_reason": query_reason or "empty_recommendation_query",
        }

    location = _user_location(state)
    soft_preferences = _to_dict(frame.get("soft_preferences"))
    ranking_signals = _to_dict(frame.get("ranking_signals"))
    query_terms = [str(item) for item in ranking_signals.get("query_terms", []) or [] if str(item).strip()]
    scene_terms = [str(item) for item in soft_preferences.get("scene_terms", []) or [] if str(item).strip()]
    batch_aspects = sorted(
        {
            *[str(item.get("name", "")).strip() for item in frame.get("facets", []) or [] if isinstance(item, dict) and str(item.get("name", "")).strip()],
            "review_summary",
        }
    )
    tool_calls: list[dict[str, Any]] = [
        _make_call(
            call_id="call_search_shops",
            tool_name="search_shops",
            args={
                "query": query,
                "location": location,
                "limit": config.SEARCH_LIMIT,
            },
            required=True,
            facet="recall",
            group_id="recommendation_batch",
            max_parallelism=1,
        )
    ]

    tool_calls.append(
        _make_call(
            call_id="call_shop_cards",
            tool_name="get_shop_cards",
            args={
                "shop_ids": "$search_result.shop_ids",
                "user_location": location,
                "need_coupon_brief": True,
                "need_open_status": True,
                "need_distance_eta": True,
                "max_items": config.RECOMMENDATION_CANDIDATE_TOP_K,
            },
            required=False,
            facet="shop_cards",
            depends_on=["call_search_shops"],
            group_id="recommendation_batch",
            max_parallelism=config.MAX_CONCURRENCY,
        )
    )

    if "get_shop_review_summary" in tool_names:
        tool_calls.append(
            _make_call(
                call_id="call_review_summary",
                tool_name="get_shop_review_summary",
                args={
                    "shop_ids": "$search_result.shop_ids",
                    "aspects": batch_aspects,
                    "scene": scene_terms[0] if scene_terms else None,
                    "max_reviews": config.RECOMMENDATION_CANDIDATE_TOP_K,
                },
                required=False,
                facet="review_summary",
                depends_on=["call_search_shops"],
                group_id="recommendation_batch",
                max_parallelism=config.MAX_CONCURRENCY,
            )
        )

    plan = ExecutionPlan.model_validate(
        {
            "plan_id": f"recommendation_plan_{query or 'batch'}",
            "task_type": TaskType.recommendation.value,
            "tool_calls": tool_calls,
            "stages": [
                {
                    "stage_id": "stage_0",
                    "description": "Recall recommendation candidates with search_shops",
                    "tool_names": ["search_shops"],
                    "depends_on": [],
                    "max_parallelism": 1,
                },
                {
                    "stage_id": "stage_1",
                    "description": "LLM tool planner batch enrichment",
                    "tool_names": sorted(set(stage_tool for stage_tool in {"get_shop_cards", "get_shop_review_summary"} if stage_tool in tool_names)),
                    "depends_on": ["stage_0"],
                    "max_parallelism": config.MAX_CONCURRENCY,
                },
            ],
            "target_shop_ids": [],
            "query_terms": query_terms,
            "scene_terms": scene_terms,
            "open_now_preferred": bool(ranking_signals.get("open_now_preferred") or soft_preferences.get("open_now_preferred")),
            "coupon_preferred": bool(ranking_signals.get("coupon_preferred") or soft_preferences.get("coupon_preferred")),
            "nearby_preferred": bool(ranking_signals.get("nearby_preferred") or soft_preferences.get("nearby_preferred")),
        }
    )
    return {
        "execution_plan": plan,
        "recommendation_query": query,
        "query_terms": query_terms,
        "scene_terms": scene_terms,
        "recommendation_candidates": [],
        "tool_plan": tool_plan,
        "tool_plan_source": tool_plan_source,
        "tool_plan_validated": tool_plan_validated,
        "tool_plan_fallback_reason": tool_plan_fallback_reason,
        "tool_plan_reason": query_reason,
    }


def _build_comparison_execution_plan(
    state: dict[str, Any],
    *,
    tool_plan: ToolPlan | None,
    tool_plan_source: str,
    tool_plan_validated: bool,
    tool_plan_fallback_reason: str | None,
) -> dict[str, Any]:
    frame = _to_dict(state.get("semantic_frame"))
    tool_names = set(_intent_names(tool_plan))
    target_ids = _comparison_target_ids(state)
    comparison_reason: str | None = None
    if len(target_ids) > MAX_COMPARISON_TARGETS:
        target_ids = target_ids[:MAX_COMPARISON_TARGETS]
        comparison_reason = "comparison_targets_truncated"
    if len(target_ids) < 2 or not (tool_names & {"get_shop_cards", "get_shop_review_summary"}):
        plan_payload = plan_comparison(
            (state.get("comparison_targets", []) or [])[:MAX_COMPARISON_TARGETS],
            max_detail=config.COMPARISON_FULL_DETAIL_SHOP_LIMIT,
            focus_facets=[str(item) for item in frame.get("focused_facets", []) or [] if str(item).strip()] or None,
            location=_user_location(state),
        )
        plan = ExecutionPlan.model_validate(plan_payload)
        return {
            "execution_plan": plan,
            "comparison_result": {
                "status": "planned",
                "target_shop_ids": target_ids,
                "mode": "comparison",
            },
            "tool_plan": tool_plan,
            "tool_plan_source": tool_plan_source,
            "tool_plan_validated": tool_plan_validated,
            "tool_plan_fallback_reason": tool_plan_fallback_reason,
            "tool_plan_reason": comparison_reason,
        }

    location = _user_location(state)
    focus_facets = [str(item) for item in frame.get("focused_facets", []) or [] if str(item).strip()]
    scene_terms = [str(item) for item in _to_dict(frame.get("soft_preferences")).get("scene_terms", []) or [] if str(item).strip()]
    tool_calls: list[dict[str, Any]] = []
    stage_tools: list[str] = []

    stage_tools.append("get_shop_cards")
    tool_calls.append(
        _make_call(
            call_id="call_shop_cards",
            tool_name="get_shop_cards",
            args={
                "shop_ids": target_ids[: config.COMPARISON_MAX_SHOP_LIMIT],
                "user_location": location,
                "need_coupon_brief": True,
                "need_open_status": True,
                "need_distance_eta": True,
                "max_items": len(target_ids),
            },
            required=False,
            facet="shop_cards",
            group_id="comparison_batch",
        )
    )

    if "get_shop_review_summary" in tool_names:
        stage_tools.append("get_shop_review_summary")
        tool_calls.append(
            _make_call(
                call_id="call_review_summary",
                tool_name="get_shop_review_summary",
                args={
                    "shop_ids": target_ids[: config.COMPARISON_MAX_SHOP_LIMIT],
                    "aspects": focus_facets or ["review_summary"],
                    "scene": scene_terms[0] if scene_terms else None,
                    "max_reviews": len(target_ids),
                },
                required=False,
                facet="review_summary",
                group_id="comparison_batch",
            )
        )

    plan = ExecutionPlan.model_validate(
        {
            "plan_id": f"comparison_plan_{'_'.join(target_ids) or 'batch'}",
            "task_type": TaskType.comparison.value,
            "tool_calls": tool_calls,
            "stages": [
                {
                    "stage_id": "stage_1",
                    "description": "LLM tool planner batch comparison plan",
                    "tool_names": sorted(set(stage_tools)),
                    "depends_on": [],
                    "max_parallelism": max(1, min(len(tool_calls), config.MAX_CONCURRENCY)),
                }
            ],
            "target_shop_ids": target_ids,
        }
    )
    return {
        "execution_plan": plan,
        "comparison_result": {
            "status": "planned",
            "target_shop_ids": target_ids,
            "mode": "comparison",
        },
        "tool_plan": tool_plan,
        "tool_plan_source": tool_plan_source,
        "tool_plan_validated": tool_plan_validated,
        "tool_plan_fallback_reason": tool_plan_fallback_reason,
        "tool_plan_reason": comparison_reason,
    }


def build_execution_plan_with_tool_planner(
    state: dict[str, Any],
    *,
    llm_call: LLMBackend | None = None,
) -> dict[str, Any]:
    """Build the final execution plan, optionally using a constrained LLM tool plan."""

    frame = _to_dict(state.get("semantic_frame"))
    decision = build_tool_plan(
        raw_text=str(state.get("raw_text", "") or ""),
        top_intent=state.get("top_intent"),
        semantic_frame=frame,
        session_state=state.get("session_state_before") or state.get("session_state"),
        llm_call=llm_call,
    )

    task_type = _task_type_value(state.get("task_type") or frame.get("task_type"))
    try:
        if task_type == TaskType.recommendation.value:
            return _build_recommendation_execution_plan(
                state,
                tool_plan=decision.tool_plan,
                tool_plan_source=decision.tool_plan_source,
                tool_plan_validated=decision.tool_plan_validated,
                tool_plan_fallback_reason=decision.tool_plan_fallback_reason,
            )
        if task_type == TaskType.comparison.value:
            return _build_comparison_execution_plan(
                state,
                tool_plan=decision.tool_plan,
                tool_plan_source=decision.tool_plan_source,
                tool_plan_validated=decision.tool_plan_validated,
                tool_plan_fallback_reason=decision.tool_plan_fallback_reason,
            )
        return _build_single_shop_execution_plan(
            state,
            tool_plan=decision.tool_plan,
            tool_plan_source=decision.tool_plan_source,
            tool_plan_validated=decision.tool_plan_validated,
            tool_plan_fallback_reason=decision.tool_plan_fallback_reason,
        )
    except Exception:
        if task_type == TaskType.recommendation.value:
            query, query_reason = _recommendation_query(state)
            if not query:
                empty_plan = ExecutionPlan.model_validate(
                    {
                        "plan_id": "recommendation_plan_empty_query",
                        "task_type": TaskType.recommendation.value,
                        "tool_calls": [],
                        "stages": [],
                        "target_shop_ids": [],
                    }
                )
                return {
                    "execution_plan": empty_plan,
                    "recommendation_query": "",
                    "query_terms": [],
                    "scene_terms": [],
                    "recommendation_candidates": [],
                    "tool_plan": decision.tool_plan,
                    "tool_plan_source": "fallback",
                    "tool_plan_validated": False,
                    "tool_plan_fallback_reason": "clarify_required_empty_query",
                    "tool_plan_reason": query_reason or "empty_recommendation_query",
                }
            frame_for_plan = dict(frame)
            frame_for_plan["query"] = query
            plan_payload = build_recommendation_execution_plan(
                frame_for_plan,
                location=_user_location(state),
                fallback_query=query,
            )
            plan = ExecutionPlan.model_validate(plan_payload.get("plan", {}))
            return {
                "execution_plan": plan,
                "recommendation_query": plan_payload.get("recommendation_query", query),
                "query_terms": plan_payload.get("query_terms", []),
                "scene_terms": plan_payload.get("scene_terms", []),
                "recommendation_candidates": [],
                "tool_plan": decision.tool_plan,
                "tool_plan_source": "fallback",
                "tool_plan_validated": False,
                "tool_plan_fallback_reason": "tool_plan_materialization_failed",
                "tool_plan_reason": query_reason,
            }
        if task_type == TaskType.comparison.value:
            plan_payload = plan_comparison(
                (state.get("comparison_targets", []) or [])[:MAX_COMPARISON_TARGETS],
                max_detail=config.COMPARISON_FULL_DETAIL_SHOP_LIMIT,
                focus_facets=[str(item) for item in frame.get("focused_facets", []) or [] if str(item).strip()] or None,
                location=_user_location(state),
            )
            plan = ExecutionPlan.model_validate(plan_payload)
            return {
                "execution_plan": plan,
                "comparison_result": {
                    "status": "planned",
                    "target_shop_ids": _comparison_target_ids(state),
                    "mode": "comparison",
                },
                "tool_plan": decision.tool_plan,
                "tool_plan_source": "fallback",
                "tool_plan_validated": False,
                "tool_plan_fallback_reason": "tool_plan_materialization_failed",
                "tool_plan_reason": "comparison_targets_truncated" if len(_comparison_target_ids(state)) > MAX_COMPARISON_TARGETS else None,
            }
        plan_payload = build_execution_plan(
            task_type,
            _to_dict(state.get("resolved_target") or state.get("resolve_shop_result")),
            frame.get("facets", []),
        )
        plan = ExecutionPlan.model_validate(plan_payload)
        return {
            "execution_plan": plan,
            "tool_plan": decision.tool_plan,
            "tool_plan_source": "fallback",
            "tool_plan_validated": False,
            "tool_plan_fallback_reason": "tool_plan_materialization_failed",
            "tool_plan_reason": None,
        }
