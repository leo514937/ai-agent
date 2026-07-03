"""GoalPlanner — P2 business-objective abstraction layer.

Replaces the old ``task_type`` hard routing as the authoritative source of
local-life business objectives.  Input: ``SemanticFrame`` + ``SessionState``.
Output: ``GoalPlan`` with candidate/evidence directives.

Responsibilities:
  1. Generate an executable goal from the semantic frame.
  2. Determine goal_type (recommendation / comparison / single_shop_query / refinement / unsupported).
  3. Determine candidate_source (explicit / context / discovery / mixed).
  4. Extract evidence_needs, required / optional facets.
  5. Mark unsupported goals explicitly.
  6. NOT generate execution plans.
  7. NOT execute tools.
  8. NOT decide candidate or evidence sufficiency.
"""

from __future__ import annotations

import logging
import re
from enum import Enum
from typing import Any, Callable

from ...domain.candidate import GoalType as _GoalType
from ...domain.enums import Facet
from ...domain.goal import GoalPlan, GoalSource
from ...domain.schemas import SemanticFrame
from ...domain.state import SessionState
from ...domain.facets import normalize_query_facets
from ...observability.file_logger import get_python_service_logger, log_kv
from .unsupported_intent import (
    build_booking_unsupported_reason,
    detect_booking_unsupported,
)
from ..llm_utils import invoke_structured_llm, model_validate_or_error

_LOGGER = get_python_service_logger()


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


def _get_task_type(frame: SemanticFrame | dict[str, Any] | None) -> str:
    """Extract the task_type string from a SemanticFrame (new or legacy)."""
    if frame is None:
        return ""
    if isinstance(frame, SemanticFrame):
        tt = frame.task_type
    else:
        tt = frame.get("task_type", "")
    if tt is None:
        return ""
    if hasattr(tt, "value"):
        return str(tt.value)
    return str(tt)


def _get_primary_task(frame: SemanticFrame | dict[str, Any] | None) -> str:
    if frame is None:
        return ""
    if isinstance(frame, SemanticFrame):
        return frame.primary_task or ""
    return str(frame.get("primary_task", "") or "")


def _get_candidate_source(frame: SemanticFrame | dict[str, Any] | None) -> str:
    """Derive candidate_source from the frame."""
    if frame is None:
        return "discovery"

    if isinstance(frame, SemanticFrame):
        cs = frame.candidate_source
        mentions = list(frame.merchant_mentions or [])
        ordinals = list(frame.ordinal_references or [])
        deictics = list(frame.deictic_references or [])
        comparison_targets = list(frame.comparison_targets or [])
        reference_mentions = list(frame.reference_mentions or [])
    else:
        cs = frame.get("candidate_source")
        mentions = list(frame.get("merchant_mentions", []) or [])
        ordinals = list(frame.get("ordinal_references", []) or [])
        deictics = list(frame.get("deictic_references", []) or [])
        comparison_targets = list(frame.get("comparison_targets", []) or [])
        reference_mentions = list(frame.get("reference_mentions", []) or [])

    if cs is not None:
        try:
            return str(getattr(cs, "value", cs))
        except Exception:
            pass

    has_structured_refs = bool(ordinals or deictics or comparison_targets or reference_mentions)
    has_mentions = len(mentions) >= 1

    if has_mentions and has_structured_refs:
        return "mixed"
    if has_mentions:
        return "explicit"
    if has_structured_refs:
        return "context"
    return "discovery"


def _infer_explicit_mentions_from_text(raw_text: str) -> list[str]:
    """从原文里尽量保守地提取明确店名片段。"""
    text = str(raw_text or "").strip()
    if not text:
        return []

    mentions: list[str] = []
    bracket_pattern = r"[\u4e00-\u9fffA-Za-z0-9·&]+[（(][^）)]+[）)]"
    mentions.extend(re.findall(bracket_pattern, text))

    cut_markers = (
        "有券",
        "团购",
        "营业",
        "开门",
        "多久",
        "多远",
        "距离",
        "离我",
        "多少钱",
        "便宜",
        "优惠",
        "套餐",
    )
    cut_index = len(text)
    for marker in cut_markers:
        idx = text.find(marker)
        if 0 < idx < cut_index:
            cut_index = idx
    if cut_index < len(text):
        prefix = text[:cut_index].strip(" ，,。?？！!~")
        if prefix and any(token in prefix for token in ("店", "馆", "轩", "居", "坊", "园", "楼", "火锅", "烧烤", "餐厅", "饭店", "酒楼")):
            mentions.append(prefix)
        elif (
            prefix
            and 2 <= len(prefix) <= 12
            and any("\u4e00" <= ch <= "\u9fff" for ch in prefix)
            and not any(token in prefix for token in ("这家", "那家", "第一家", "第二家", "第三家", "附近", "推荐"))
        ):
            mentions.append(prefix)

    ordered: list[str] = []
    seen: set[str] = set()
    for mention in mentions:
        cleaned = str(mention).strip()
        if not cleaned:
            continue
        if any(cleaned == existing or cleaned in existing for existing in ordered):
            continue
        ordered = [existing for existing in ordered if existing not in cleaned]
        if cleaned not in seen:
            seen.add(cleaned)
            ordered.append(cleaned)
    return ordered


def _normalize_goal_plan_from_text(
    plan: GoalPlan,
    semantic_frame: SemanticFrame | dict[str, Any] | None,
    raw_text: str,
    session_state: SessionState | dict[str, Any] | None = None,
) -> GoalPlan:
    """补齐明确店名信号，避免单店查询被误压成推荐。"""
    text = str(raw_text or "")
    frame_task_type = _get_task_type(semantic_frame)
    mentions: list[str] = []
    if isinstance(semantic_frame, SemanticFrame):
        mentions = [str(item).strip() for item in (semantic_frame.merchant_mentions or []) if str(item).strip()]
    elif isinstance(semantic_frame, dict):
        mentions = [str(item).strip() for item in (semantic_frame.get("merchant_mentions", []) or []) if str(item).strip()]
    if not mentions and text:
        mentions = _infer_explicit_mentions_from_text(text)

    comparison_targets: list[dict[str, Any]] = []
    reference_mentions: list[str] = []
    ordinal_references: list[str] = []
    deictic_references: list[str] = []
    if isinstance(semantic_frame, SemanticFrame):
        comparison_targets = [dict(item) for item in (semantic_frame.comparison_targets or []) if str(getattr(item, "shop_name", "") or "").strip() or str(getattr(item, "shop_id", "") or "").strip()]  # type: ignore[arg-type]
        reference_mentions = [str(item).strip() for item in (semantic_frame.reference_mentions or []) if str(item).strip()]
        ordinal_references = [str(item).strip() for item in (semantic_frame.ordinal_references or []) if str(item).strip()]
        deictic_references = [str(item).strip() for item in (semantic_frame.deictic_references or []) if str(item).strip()]
    elif isinstance(semantic_frame, dict):
        comparison_targets = [dict(item) for item in (semantic_frame.get("comparison_targets", []) or []) if str(_to_dict(item).get("shop_name", "") or "").strip() or str(_to_dict(item).get("shop_id", "") or "").strip()]
        reference_mentions = [str(item).strip() for item in (semantic_frame.get("reference_mentions", []) or []) if str(item).strip()]
        ordinal_references = [str(item).strip() for item in (semantic_frame.get("ordinal_references", []) or []) if str(item).strip()]
        deictic_references = [str(item).strip() for item in (semantic_frame.get("deictic_references", []) or []) if str(item).strip()]

    facet_set = normalize_query_facets(semantic_frame, session_state=session_state, raw_text=raw_text)
    plan.facets = list(facet_set.facets or [])
    plan.conflicting_facets = list(facet_set.conflicting_facets or [])
    plan.ranking_policy = facet_set.ranking_policy
    plan.target_resolution = facet_set.target_resolution

    if not mentions:
        return plan

    comparison_hints = ("比", "比较", "对比", "哪个好", "哪个更好", "哪家更好", "谁更好")
    has_comparison_hint = any(hint in text for hint in comparison_hints)
    has_comparison_signal = bool(
        comparison_targets
        or reference_mentions
        or ordinal_references
        or deictic_references
        or (frame_task_type == "comparison")
    )
    if plan.goal_type in {"recommendation", "single_shop_query"} and has_comparison_hint and (len(mentions) >= 2 or has_comparison_signal):
        plan.goal_type = "comparison"
    elif plan.goal_type == "recommendation" and len(mentions) == 1:
        plan.goal_type = "single_shop_query"

    if plan.goal_type == "single_shop_query" and not plan.goal_summary:
        plan.goal_summary = text

    if plan.candidate_source in {"", "discovery", "recommendation"}:
        if plan.goal_type == "comparison" and has_comparison_signal:
            plan.candidate_source = "mixed" if len(mentions) > 1 else "explicit"
        else:
            plan.candidate_source = "explicit" if len(mentions) == 1 else "mixed"

    return plan


def _get_facets(
    frame: SemanticFrame | dict[str, Any] | None,
) -> tuple[list[str], list[str]]:
    """Extract required and optional facets from the frame."""
    required: list[str] = []
    optional: list[str] = []

    if frame is None:
        return required, optional

    if isinstance(frame, SemanticFrame):
        facet_specs = list(frame.facet_set.facets if frame.facet_set and frame.facet_set.facets else frame.facets or [])
        focused = list(frame.focused_facets or [])
    else:
        facet_set = _to_dict(frame.get("facet_set")) if isinstance(frame, dict) else {}
        facet_specs = list((facet_set.get("facets", []) if isinstance(facet_set, dict) else []) or frame.get("facets", []) or [])
        focused = list(frame.get("focused_facets", []) or [])

    for spec in facet_specs:
        spec_dict = _to_dict(spec)
        name_raw = spec_dict.get("name", "") or ""
        name = str(name_raw.value) if isinstance(name_raw, Enum) else str(name_raw)
        if not name:
            continue
        if spec_dict.get("required"):
            if name not in required:
                required.append(name)
        else:
            if name not in optional:
                optional.append(name)

    for f in focused:
        if f and f not in required and f not in optional:
            if not facet_specs:
                required.append(f)
            else:
                optional.append(f)

    return required, optional


def _get_candidate_limit(
    frame: SemanticFrame | dict[str, Any] | None,
    goal_type_str: str,
) -> int | None:
    """Extract candidate_limit from frame or apply goal-type defaults."""
    if frame is None:
        return None

    if isinstance(frame, SemanticFrame):
        limit = frame.candidate_limit
        hc = frame.hard_constraints or {}
    else:
        limit = frame.get("candidate_limit")
        hc = frame.get("hard_constraints", {}) or {}

    if limit is not None:
        return limit

    if isinstance(hc, dict):
        count_str = str(hc.get("count", "") or "")
        if count_str.isdigit():
            return int(count_str)

    # Goal-type defaults
    defaults = {
        "comparison": 2,
        "recommendation": 3,
        "single_shop_query": 1,
        "refinement": 1,
    }
    return defaults.get(goal_type_str, None)


def _get_quantity_semantics(goal_type_str: str, candidate_limit: int | None) -> tuple[int, int, int]:
    if goal_type_str == "comparison":
        requested_count = candidate_limit or 2
        return requested_count, 2, candidate_limit or 5
    if goal_type_str == "recommendation":
        requested_count = candidate_limit or 3
        return requested_count, 1, candidate_limit or 5
    if goal_type_str == "single_shop_query":
        requested_count = candidate_limit or 1
        return requested_count, 1, candidate_limit or 1
    requested_count = candidate_limit or 1
    return requested_count, 1, candidate_limit or 5


def _detect_unsupported_intent(
    frame: SemanticFrame | dict[str, Any] | None,
    raw_text: str,
    goal_type_str: str,
) -> tuple[bool, str]:
    """Detect intents that are outside the supported tool capability.

    Returns (is_unsupported, reason).
    """
    if goal_type_str == "unsupported":
        return True, "goal_type_could_not_be_determined"

    is_booking_intent, marker = detect_booking_unsupported(
        raw_text,
        _get_primary_task(frame),
    )
    if is_booking_intent:
        return True, build_booking_unsupported_reason(marker)

    return False, ""


def _get_evidence_needs(required: list[str], optional: list[str]) -> list[str]:
    """Combine required + optional facets into evidence_needs."""
    needs = list(required)
    for f in optional:
        if f not in needs:
            needs.append(f)
    return needs


def _get_constraints(frame: SemanticFrame | dict[str, Any] | None) -> dict[str, Any]:
    """Extract constraints from the semantic frame."""
    if frame is None:
        return {}
    if isinstance(frame, SemanticFrame):
        return dict(frame.hard_constraints or {})
    return dict(frame.get("hard_constraints", {}) or {})


def _map_goal_type(task_type_str: str) -> str:
    """Map legacy TaskType string to GoalPlan.goal_type string."""
    mapping = {
        "recommendation": "recommendation",
        "comparison": "comparison",
        "single_shop_query": "single_shop_query",
        "coupon_query": "single_shop_query",
        "clarification_reply": "refinement",
        "general_chat": "unsupported",
    }
    return mapping.get(task_type_str, "unsupported")


def _plan_goal_rules(
    semantic_frame: SemanticFrame | dict[str, Any] | None,
    session_state: SessionState | dict[str, Any] | None = None,
    raw_text: str = "",
) -> GoalPlan:
    """Plan an executable goal from the user's structured input.

    This is the P2 replacement for the old ``task_type`` routing.
    It is the **sole** authoritative source for goal-level decisions
    in the local-life flow.

    Args:
        semantic_frame: The parsed semantic frame (or serialised dict).
        session_state: Optional session state for context recovery.
        raw_text: The original user input text (for unsupported detection).

    Returns:
        A ``GoalPlan`` with goal type, candidate directives, evidence needs,
        and unsupported status.
    """
    # --- 1. Determine goal_type ---
    task_type_str = _get_task_type(semantic_frame)
    goal_type_str = _map_goal_type(task_type_str)

    # --- 2. Detect unsupported intents ---
    unsupported, unsupported_reason = _detect_unsupported_intent(
        semantic_frame, raw_text, goal_type_str,
    )

    # --- 3. Derive candidate_source ---
    candidate_source = _get_candidate_source(semantic_frame)

    # --- 4. Extract candidate metadata ---
    candidate_category: str | None = None
    if isinstance(semantic_frame, SemanticFrame):
        candidate_category = semantic_frame.candidate_category or None
        if not candidate_category:
            hc = semantic_frame.hard_constraints or {}
            if isinstance(hc, dict):
                candidate_category = str(hc.get("category", "") or "") or None
    elif isinstance(semantic_frame, dict):
        candidate_category = str(semantic_frame.get("candidate_category", "") or "") or None
        if not candidate_category:
            hc = semantic_frame.get("hard_constraints", {}) or {}
            if isinstance(hc, dict):
                candidate_category = str(hc.get("category", "") or "") or None

    candidate_limit = _get_candidate_limit(semantic_frame, goal_type_str)
    requested_count, min_required, max_allowed = _get_quantity_semantics(goal_type_str, candidate_limit)

    # --- 5. Extract facets ---
    required_facets, optional_facets = _get_facets(semantic_frame)
    evidence_needs = _get_evidence_needs(required_facets, optional_facets)

    # --- 6. Extract constraints ---
    constraints = _get_constraints(semantic_frame)

    # --- 7. Build goal summary ---
    primary_task = _get_primary_task(semantic_frame)
    if primary_task:
        goal_summary = primary_task
    else:
        parts = []
        if candidate_category:
            parts.append(candidate_category)
        if goal_type_str == "comparison":
            parts.append("comparison")
        if evidence_needs:
            parts.append(f"facets: {', '.join(evidence_needs)}")
        goal_summary = " ".join(parts) if parts else f"{goal_type_str} request"

    # --- 8. Determine goal source ---
    source_origin = "goal_planner"
    if isinstance(semantic_frame, SemanticFrame) and semantic_frame.semantic_source:
        source_origin = semantic_frame.semantic_source

    plan = GoalPlan(
        goal_type=goal_type_str,
        goal_source=GoalSource.SEMANTIC_FRAME,
        goal_summary=goal_summary,
        candidate_source=candidate_source,
        candidate_category=candidate_category,
        candidate_limit=candidate_limit,
        requested_count=requested_count,
        min_required=min_required,
        max_allowed=max_allowed,
        evidence_needs=evidence_needs,
        required_facets=required_facets,
        optional_facets=optional_facets,
        constraints=constraints,
        unsupported=unsupported,
        unsupported_reason=unsupported_reason,
        source_origin=source_origin,
        planner_source="deterministic_goal_planner",
        planner_reason="rule_based_planner",
        planner_confidence=0.0,
    )
    return _normalize_goal_plan_from_text(plan, semantic_frame, raw_text, session_state)


def plan_goal_with_llm(
    semantic_frame: SemanticFrame | dict[str, Any] | None,
    session_state: SessionState | dict[str, Any] | None = None,
    raw_text: str = "",
    *,
    llm_call: Callable[..., dict[str, Any]] | None = None,
    strict: bool = False,
) -> tuple[GoalPlan | None, dict[str, Any]]:
    """Plan the goal via LLM and return metadata for graph handlers."""
    log_kv(
        _LOGGER,
        logging.INFO,
        "[GOAL_PLANNER_START]",
        tone="llm",
        raw_text=raw_text,
        semantic_frame=_to_dict(semantic_frame),
        session_context=_to_dict(session_state),
        strict=strict,
    )
    replacements = {
        "{{TEXT}}": str(raw_text or ""),
        "{{SEMANTIC_FRAME}}": _to_dict(semantic_frame),
        "{{SESSION_CONTEXT}}": _to_dict(session_state),
    }
    try:
        llm_result = invoke_structured_llm(
            prompt_name="goal_planner",
            replacements=replacements,
            response_validator=GoalPlan.model_validate,
            llm_call=llm_call,
        )
    except Exception as exc:
        error = {"error_code": "GOAL_PLANNER_PROMPT_ERROR", "error_message": str(exc), "llm_backend": "", "raw": ""}
        log_kv(_LOGGER, logging.ERROR, "[GOAL_PLANNER_ERROR]", tone="error", error=error)
        if strict:
            return None, error
        plan = _plan_goal_rules(semantic_frame, session_state, raw_text)
        plan.planner_source = "deterministic_goal_planner"
        plan.planner_reason = f"llm_prompt_error:{exc}"
        log_kv(_LOGGER, logging.WARNING, "[GOAL_PLANNER_FALLBACK]", tone="warn", plan=plan, error=error)
        return plan, error

    if not llm_result.get("ok"):
        error = {
            "error_code": llm_result.get("error_code") or "GOAL_PLANNER_LLM_FAILED",
            "error_message": llm_result.get("error_message") or "goal planner llm failed",
            "llm_backend": llm_result.get("llm_backend", ""),
            "raw": llm_result.get("raw", ""),
        }
        log_kv(_LOGGER, logging.WARNING, "[GOAL_PLANNER_LLM_FAILED]", tone="warn", error=error)
        if strict:
            return None, error
        plan = _plan_goal_rules(semantic_frame, session_state, raw_text)
        plan.planner_source = "deterministic_goal_planner"
        plan.planner_reason = str(error["error_code"])
        log_kv(_LOGGER, logging.WARNING, "[GOAL_PLANNER_FALLBACK]", tone="warn", plan=plan, error=error)
        return plan, error

    payload = dict(llm_result.get("payload") or {})
    model, validation_error = model_validate_or_error(GoalPlan, payload)
    if model is None:
        error = {
            "error_code": "GOAL_PLAN_SCHEMA_INVALID",
            "error_message": validation_error,
            "llm_backend": llm_result.get("llm_backend", ""),
            "raw": llm_result.get("raw", ""),
        }
        log_kv(_LOGGER, logging.WARNING, "[GOAL_PLANNER_SCHEMA_INVALID]", tone="warn", error=error, payload=payload)
        if strict:
            return None, error
        plan = _plan_goal_rules(semantic_frame, session_state, raw_text)
        plan.planner_source = "deterministic_goal_planner"
        plan.planner_reason = "goal_plan_schema_invalid"
        log_kv(_LOGGER, logging.WARNING, "[GOAL_PLANNER_FALLBACK]", tone="warn", plan=plan, error=error)
        return plan, error

    plan = model
    if not plan.goal_type or not plan.candidate_source:
        error = {
            "error_code": "GOAL_PLAN_INCOMPLETE",
            "error_message": "llm goal plan is missing required goal_type or candidate_source",
            "llm_backend": llm_result.get("llm_backend", ""),
            "raw": llm_result.get("raw", ""),
        }
        log_kv(_LOGGER, logging.WARNING, "[GOAL_PLANNER_INCOMPLETE]", tone="warn", error=error, payload=payload)
        if strict:
            return None, error
        plan = _plan_goal_rules(semantic_frame, session_state, raw_text)
        plan.planner_source = "deterministic_goal_planner"
        plan.planner_reason = "goal_plan_incomplete"
        log_kv(_LOGGER, logging.WARNING, "[GOAL_PLANNER_FALLBACK]", tone="warn", plan=plan, error=error)
        return plan, error
    if not plan.goal_source:
        plan.goal_source = GoalSource.SEMANTIC_FRAME
    plan = _normalize_goal_plan_from_text(plan, semantic_frame, raw_text, session_state)
    plan.source_origin = plan.source_origin or "llm_goal_planner"
    plan.planner_source = plan.planner_source or "llm_goal_planner"
    plan.planner_reason = plan.planner_reason or "llm_structured_plan"
    log_kv(
        _LOGGER,
        logging.INFO,
        "[GOAL_PLANNER_RESULT]",
        tone="llm",
        goal_plan=plan,
        llm_backend=llm_result.get("llm_backend", ""),
    )
    return plan, {
        "error_code": "",
        "error_message": "",
        "llm_backend": llm_result.get("llm_backend", ""),
        "raw": llm_result.get("raw", ""),
    }


def plan_goal(
    semantic_frame: SemanticFrame | dict[str, Any] | None,
    session_state: SessionState | dict[str, Any] | None = None,
    raw_text: str = "",
) -> GoalPlan:
    """Backward-compatible deterministic planner."""
    return _plan_goal_rules(semantic_frame, session_state, raw_text)
