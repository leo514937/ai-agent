"""Lightweight, read-only session context summary for LLM prompts.

This module provides a compressed summary of the current session state
that can be safely injected into LLM prompts. It intentionally
excludes ``shop_id``, full recommendation details, and any field that
could let the LLM directly bind a shop or make factual decisions.

    - **Parser** uses ``{{SESSION_CONTEXT}}`` to understand follow-ups,
      ordinal/deictic references, and task continuation vs. switch.
    - **Verbalizer** uses ``conversation_continuity`` (built separately)
      to produce more natural multi-turn responses.

Design constraints:
    - No ``shop_id`` exposure.
    - No full recommendation details (comments, coupon text, etc.).
    - Truncated lists (max 5 names).
    - Truncated constraints (short keys only).
    - ``has_context`` must be checked before relying on other fields.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .state import SessionState

_MAX_NAME_LIST = 5


class SessionContextSummary(BaseModel):
    """Compressed snapshot of session state for LLM prompt injection.

    All fields are optional so that downstream consumers can always
    ``model_dump()`` a complete dict without ``None``-filtering issues.
    """

    has_context: bool = False
    """Whether there is any session context at all."""

    current_shop_name: str | None = None
    """The shop name the user was most recently focused on (if any)."""

    last_task_type: str | None = None
    """The task type of the most recent turn, e.g. ``recommendation``."""

    last_recommendation_present: bool = False
    """True if the last turn produced a recommendation list."""

    last_recommendation_count: int = 0
    """How many shops were in that list."""

    last_recommendation_names: list[str] = Field(default_factory=list)
    """Up to 5 shop names from the last recommendation list."""

    active_constraints: dict[str, Any] = Field(default_factory=dict)
    """Currently active user constraints (short keys only, no full values)."""

    pending_clarification_present: bool = False
    """True if the session has a pending clarification."""

    pending_clarification_type: str | None = None
    """What the pending clarification is about, e.g. ``shop_choice``."""

    comparison_targets_count: int = 0
    """How many shops are in the current comparison set."""

    comparison_target_names: list[str] = Field(default_factory=list)
    """Up to 5 shop names from the comparison target list."""


def build_session_context_summary(
    session_state: SessionState | dict | None,
) -> SessionContextSummary:
    """Build a compressed context summary from a raw session state.

    Returns an empty summary (``has_context=False``) when *session_state*
    is ``None``, empty, or has no meaningful data.
    """
    if session_state is None:
        return SessionContextSummary()

    # Normalise to dict
    if isinstance(session_state, SessionState):
        raw = session_state.model_dump()
    elif isinstance(session_state, dict):
        raw = dict(session_state)
    else:
        raw = {}

    # Extract the interesting bits ---------------------------------

    current_shop_raw = raw.get("current_shop") or {}
    current_shop_name = None
    if isinstance(current_shop_raw, dict):
        current_shop_name = str(current_shop_raw.get("shop_name", "") or current_shop_raw.get("name", "") or "")
        if not current_shop_name:
            current_shop_name = None

    last_recommendation_list = raw.get("last_recommendation_list") or []
    if not isinstance(last_recommendation_list, list):
        last_recommendation_list = []

    rec_names: list[str] = []
    for item in last_recommendation_list:
        if isinstance(item, dict):
            name = str(item.get("shop_name", "") or item.get("name", "") or "")
            if name:
                rec_names.append(name)
        if len(rec_names) >= _MAX_NAME_LIST:
            break

    active_constraints = raw.get("active_constraints") or {}
    if not isinstance(active_constraints, dict):
        active_constraints = {}

    pending_raw = raw.get("pending_clarification") or {}
    pending_type = None
    if isinstance(pending_raw, dict):
        pending_type = str(pending_raw.get("expected_reply_type", "") or pending_raw.get("type", "") or "")
        if not pending_type:
            pending_type = None

    comparison_targets = raw.get("comparison_targets") or []
    if not isinstance(comparison_targets, list):
        comparison_targets = []

    comp_names: list[str] = []
    for item in comparison_targets:
        if isinstance(item, dict):
            name = str(item.get("shop_name", "") or item.get("name", "") or "")
            if name:
                comp_names.append(name)
        if len(comp_names) >= _MAX_NAME_LIST:
            break

    last_task_type_raw = raw.get("last_task_type") or raw.get("task_type") or ""
    last_task_type = str(last_task_type_raw) if last_task_type_raw else None

    has_context = bool(
        current_shop_name
        or last_task_type
        or rec_names
        or active_constraints
        or pending_type
        or comp_names
    )

    return SessionContextSummary(
        has_context=has_context,
        current_shop_name=current_shop_name,
        last_task_type=last_task_type,
        last_recommendation_present=len(last_recommendation_list) > 0,
        last_recommendation_count=len(last_recommendation_list),
        last_recommendation_names=rec_names,
        active_constraints=dict(active_constraints),
        pending_clarification_present=pending_raw is not None and bool(pending_raw),
        pending_clarification_type=pending_type,
        comparison_targets_count=len(comparison_targets),
        comparison_target_names=comp_names,
    )
