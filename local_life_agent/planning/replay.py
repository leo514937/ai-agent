from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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


class ReplayCassette(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = ""
    session_state_before: dict[str, Any] = Field(default_factory=dict)
    orchestration_decision: dict[str, Any] = Field(default_factory=dict)
    execution_plan: dict[str, Any] = Field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    tool_results: dict[str, Any] = Field(default_factory=dict)
    evidence_pack: dict[str, Any] = Field(default_factory=dict)
    decision_plan: dict[str, Any] = Field(default_factory=dict)
    answer_plan: dict[str, Any] = Field(default_factory=dict)
    state_update_plan: dict[str, Any] = Field(default_factory=dict)
    final_response: str = ""
    trace_id: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


def build_replay_cassette(
    *,
    query: str = "",
    session_state_before: Any = None,
    orchestration_decision: Any = None,
    execution_plan: Any = None,
    tool_calls: Any = None,
    tool_results: Any = None,
    evidence_pack: Any = None,
    decision_plan: Any = None,
    answer_plan: Any = None,
    state_update_plan: Any = None,
    final_response: str = "",
    trace_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> ReplayCassette:
    return ReplayCassette.model_validate(
        {
            "query": str(query or ""),
            "session_state_before": _to_dict(session_state_before),
            "orchestration_decision": _to_dict(orchestration_decision),
            "execution_plan": _to_dict(execution_plan),
            "tool_calls": [dict(item) for item in (tool_calls or []) if isinstance(item, dict)],
            "tool_results": _to_dict(tool_results),
            "evidence_pack": _to_dict(evidence_pack),
            "decision_plan": _to_dict(decision_plan),
            "answer_plan": _to_dict(answer_plan),
            "state_update_plan": _to_dict(state_update_plan),
            "final_response": str(final_response or ""),
            "trace_id": str(trace_id or ""),
            "metadata": dict(metadata or {}),
        }
    )
