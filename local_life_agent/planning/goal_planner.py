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
  6. NOT generate ToolPlan.
  7. NOT execute tools.
  8. NOT decide candidate or evidence sufficiency.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from ..domain.candidate import GoalType as _GoalType
from ..domain.enums import Facet
from ..domain.goal import GoalPlan, GoalSource
from ..domain.schemas import SemanticFrame
from ..domain.state import SessionState


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
    else:
        cs = frame.get("candidate_source")
        mentions = list(frame.get("merchant_mentions", []) or [])
        ordinals = list(frame.get("ordinal_references", []) or [])
        deictics = list(frame.get("deictic_references", []) or [])

    if cs is not None:
        try:
            return str(cs.value) if hasattr(cs, "value") else str(cs)
        except Exception:
            pass

    has_structured_refs = bool(ordinals or deictics)
    has_mentions = len(mentions) >= 1

    if has_mentions and has_structured_refs:
        return "mixed"
    if has_mentions:
        return "explicit"
    if has_structured_refs:
        return "context"
    return "discovery"


def _get_facets(
    frame: SemanticFrame | dict[str, Any] | None,
) -> tuple[list[str], list[str]]:
    """Extract required and optional facets from the frame."""
    required: list[str] = []
    optional: list[str] = []

    if frame is None:
        return required, optional

    if isinstance(frame, SemanticFrame):
        facet_specs = list(frame.facets or [])
        focused = list(frame.focused_facets or [])
    else:
        facet_specs = list(frame.get("facets", []) or [])
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

    text = (raw_text or "").lower()
    primary = (_get_primary_task(frame) or "").lower()

    # Booking/reservation — no tool support
    booking_keywords = [
        "订座", "订位", "预约", "预订", "预定", "reserve", "booking",
        "book a", "make a reservation",
    ]
    for kw in booking_keywords:
        if kw in text or kw in primary:
            return True, f"unsupported_intent: booking/reservation (no tool available): '{kw}'"

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


def plan_goal(
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

    return GoalPlan(
        goal_type=goal_type_str,
        goal_source=GoalSource.SEMANTIC_FRAME,
        goal_summary=goal_summary,
        candidate_source=candidate_source,
        candidate_category=candidate_category,
        candidate_limit=candidate_limit,
        evidence_needs=evidence_needs,
        required_facets=required_facets,
        optional_facets=optional_facets,
        constraints=constraints,
        unsupported=unsupported,
        unsupported_reason=unsupported_reason,
        source_origin=source_origin,
    )
