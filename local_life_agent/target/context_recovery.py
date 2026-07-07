"""Context recovery for multi-turn conversation state."""

from __future__ import annotations

from typing import Any

from ..domain.state import SessionState


def _frame_dict(semantic_frame: dict | Any | None) -> dict[str, Any]:
    if semantic_frame is None:
        return {}
    if isinstance(semantic_frame, dict):
        return dict(semantic_frame)
    model_dump = getattr(semantic_frame, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        return dumped if isinstance(dumped, dict) else {}
    return dict(getattr(semantic_frame, "__dict__", {}) or {})


def _active_constraints(session_state: dict | SessionState | None) -> dict[str, Any]:
    if session_state is None:
        return {}
    if isinstance(session_state, SessionState):
        value = getattr(session_state, "active_constraints", None)
    elif isinstance(session_state, dict):
        value = session_state.get("active_constraints")
    else:
        value = getattr(session_state, "active_constraints", None)
    return dict(value) if isinstance(value, dict) else {}


def _explicit_constraints(frame: dict[str, Any]) -> dict[str, Any]:
    explicit: dict[str, Any] = {}
    for key in ("hard_constraints", "soft_preferences", "ranking_signals"):
        value = frame.get(key)
        if isinstance(value, dict) and value:
            explicit[key] = dict(value)
    return explicit


def _reference_signal(frame: dict[str, Any], text: str) -> dict[str, Any]:
    merchant_mentions = [str(item).strip() for item in (frame.get("merchant_mentions") or []) if str(item).strip()]
    branch_mentions = [str(item).strip() for item in (frame.get("branch_mentions") or []) if str(item).strip()]
    reference_mentions = [str(item).strip() for item in (frame.get("reference_mentions") or []) if str(item).strip()]
    ordinal_references = [str(item).strip() for item in (frame.get("ordinal_references") or []) if str(item).strip()]
    deictic_references = [str(item).strip() for item in (frame.get("deictic_references") or []) if str(item).strip()]
    comparison_targets = [dict(item) if isinstance(item, dict) else item for item in (frame.get("comparison_targets") or []) if item is not None]

    cue_count = sum(
        1
        for value in (
            merchant_mentions,
            branch_mentions,
            reference_mentions,
            ordinal_references,
            deictic_references,
            comparison_targets,
        )
        if value
    )
    if any(token in str(text or "") for token in ("这家", "那家", "这间", "那间", "它", "第一家", "第二家", "第三家")):
        cue_count += 1

    status = "SIGNAL_ONLY" if cue_count else "NONE"
    reason = "comparison_reference_signal" if comparison_targets else "multi_turn_reference_signal" if cue_count else "no_reference_signal"
    return {
        "status": status,
        "reason": reason,
        "resolution_source": "first_layer_reference_signal",
        "reference_signal": {
            "merchant_mentions": merchant_mentions,
            "branch_mentions": branch_mentions,
            "reference_mentions": reference_mentions,
            "ordinal_references": ordinal_references,
            "deictic_references": deictic_references,
            "comparison_targets": comparison_targets,
        },
    }


def recover_context(
    session_state: dict | SessionState | None,
    semantic_frame: dict | Any,
    text: str | None = None,
) -> dict[str, Any]:
    """Recover first-layer context signals without authoritative entity resolution."""
    frame = _frame_dict(semantic_frame)
    source_text = text or frame.get("original_text") or ""
    explicit_constraints = _explicit_constraints(frame)
    inherited_constraints = {}
    if not explicit_constraints:
        inherited_constraints = _active_constraints(session_state)
    reference_resolution = _reference_signal(frame, source_text)
    if inherited_constraints and "inherited_constraints" not in reference_resolution:
        reference_resolution["inherited_constraints"] = inherited_constraints
    task_type_value = str(getattr(frame.get("task_type"), "value", frame.get("task_type")) or "")
    return {
        "semantic_frame": frame,
        "context_resolution": reference_resolution,
        "reference_resolution_source": "first_layer_reference_signal",
        "comparison_reference_signal": reference_resolution.get("reference_signal", {}) if task_type_value == "comparison" else {},
    }
