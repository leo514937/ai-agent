from __future__ import annotations

from typing import Any

from local_life_agent.planning.orchestration_router import build_orchestration_decision


def response_state_snapshot(response: Any) -> dict[str, Any]:
    debug = getattr(response, "debug", None)
    if debug is None:
        return {}
    before = debug.session_state_before or {}
    after = debug.session_state_after or {}
    semantic_frame = debug.semantic_frame or {}
    trace = debug.turn_trace or {}
    return {
        "before": before,
        "after": after,
        "semantic_frame": semantic_frame,
        "trace": trace,
    }


def orchestration_decision_from_response(response: Any, *, text: str, session_id: str, turn_id: str = "") -> Any:
    snapshot = response_state_snapshot(response)
    before = snapshot["before"] if isinstance(snapshot["before"], dict) else {}
    after = snapshot["after"] if isinstance(snapshot["after"], dict) else {}
    semantic_frame = snapshot["semantic_frame"] if isinstance(snapshot["semantic_frame"], dict) else {}
    state = {
        "raw_text": text,
        "normalized_text": text,
        "session_id": session_id,
        "turn_id": turn_id,
        "semantic_frame": semantic_frame,
        "session_state_before": before,
        "session_state": after,
        "current_shop": after.get("current_shop") or before.get("current_shop"),
        "last_recommendation_list": after.get("last_recommendation_list") or before.get("last_recommendation_list") or [],
        "comparison_targets": after.get("comparison_targets") or before.get("comparison_targets") or [],
        "top_intent": semantic_frame.get("top_intent"),
        "task_type": semantic_frame.get("task_type"),
    }
    return build_orchestration_decision(state)


def sse_event_names(sse_body: str) -> list[str]:
    names: list[str] = []
    for line in sse_body.splitlines():
        if line.startswith("event: "):
            names.append(line.split("event: ", 1)[1].strip())
    return names


def state_after(response: Any) -> dict[str, Any]:
    snapshot = response_state_snapshot(response)
    after = snapshot.get("after")
    return after if isinstance(after, dict) else {}


def state_before(response: Any) -> dict[str, Any]:
    snapshot = response_state_snapshot(response)
    before = snapshot.get("before")
    return before if isinstance(before, dict) else {}
