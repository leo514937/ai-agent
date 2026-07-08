from __future__ import annotations

import json
from typing import Any

from .sub_task_dag import SubTaskSpec


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _first_text(state: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = state.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (dict, list, tuple, set)) and value:
            return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        if value is not None and not isinstance(value, (dict, list, tuple, set)):
            text = str(value).strip()
            if text:
                return text
    return ""


def build_orchestrator_cache_inputs(
    state: dict[str, Any],
    spec: SubTaskSpec,
    *,
    workflow_name: str,
    tool_version: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    semantic_frame = state.get("semantic_frame")
    if not isinstance(semantic_frame, dict):
        semantic_frame = {}
    scope = {
        "session_id": _first_text(state, "session_id", "sessionId"),
        "trace_id": _first_text(state, "trace_id", "traceId"),
        "workflow_name": _normalize_text(workflow_name),
        "location": _first_text(state, "location", "current_location") or _first_text(semantic_frame, "location"),
        "freshness": _first_text(state, "freshness", "freshness_class") or _first_text(semantic_frame, "freshness", "freshness_class"),
        "tool_version": _normalize_text(tool_version),
    }
    payload = {
        "task_id": _normalize_text(spec.task_id),
        "workflow_name": _normalize_text(workflow_name),
        "depends_on": list(spec.depends_on),
        "payload": dict(spec.payload),
        "description": _normalize_text(spec.description),
        "state_signature": {
            "location": scope["location"],
            "freshness": scope["freshness"],
        },
    }
    return scope, payload
