"""Context recovery for multi-turn conversation state."""

from __future__ import annotations

from typing import Any

from ..domain.schemas import ResolveShopResult, ShopRef
from ..domain.state import SessionState
from .reference_resolver import resolve_comparison_targets, resolve_references


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


def recover_context(
    session_state: dict | SessionState | None,
    semantic_frame: dict | Any,
    text: str | None = None,
) -> dict[str, Any]:
    """Recover concrete shop targets from session context when possible."""
    frame = _frame_dict(semantic_frame)
    task_type = frame.get("task_type")
    task_type_value = getattr(task_type, "value", task_type)
    mentions = frame.get("merchant_mentions") or []
    explicit_constraints = _explicit_constraints(frame)
    inherited_constraints = {}
    if not explicit_constraints:
        inherited_constraints = _active_constraints(session_state)

    if mentions and str(task_type_value or "") != "comparison":
        resolution = {"status": "explicit_mention"}
        if inherited_constraints:
            resolution["inherited_constraints"] = inherited_constraints
        return {"semantic_frame": frame, "context_resolution": resolution}

    source_text = text or frame.get("original_text") or ""
    if str(task_type_value or "") == "comparison":
        comparison_resolution = resolve_comparison_targets(source_text, session_state, frame)
        return {
            "semantic_frame": frame,
            "comparison_target_resolution": comparison_resolution,
            "comparison_targets": comparison_resolution.get("targets", []),
            "context_resolution": {
                "status": comparison_resolution.get("status", ""),
                "reason": comparison_resolution.get("reason", ""),
                "prompt": comparison_resolution.get("prompt", ""),
            },
        }

    resolution = resolve_references(source_text, session_state, frame)
    if inherited_constraints and "inherited_constraints" not in resolution:
        resolution["inherited_constraints"] = inherited_constraints
    resolution_status = str(resolution.get("status", "") or "").upper()
    if resolution_status == "RESOLVED":
        target = resolution.get("target") or resolution.get("resolved_shop") or {}
        if hasattr(target, "model_dump"):
            target = target.model_dump()
        resolved_target = ResolveShopResult(
            status="RESOLVED",
            resolved_shop=ShopRef(
                shop_id=str(target.get("shop_id", "")),
                shop_name=str(target.get("shop_name", "")),
            ),
            confidence=1.0,
            reason=str(resolution.get("reason", "context_recovered")),
        )
        return {
            "semantic_frame": frame,
            "resolved_target": resolved_target,
            "context_resolution": resolution,
        }

    return {"semantic_frame": frame, "context_resolution": resolution}
