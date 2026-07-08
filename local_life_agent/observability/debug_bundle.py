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


class DebugBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = ""
    normalized_query: str = ""
    session_state_before: dict[str, Any] = Field(default_factory=dict)
    semantic_frame: dict[str, Any] = Field(default_factory=dict)
    orchestration_decision: dict[str, Any] = Field(default_factory=dict)
    workflow_name: str = ""
    execution_plan: dict[str, Any] = Field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    tool_results: dict[str, Any] = Field(default_factory=dict)
    evidence_pack: dict[str, Any] = Field(default_factory=dict)
    decision_plan: dict[str, Any] = Field(default_factory=dict)
    answer_plan: dict[str, Any] = Field(default_factory=dict)
    verification_result: dict[str, Any] = Field(default_factory=dict)
    state_update_plan: dict[str, Any] = Field(default_factory=dict)
    session_state_after: dict[str, Any] = Field(default_factory=dict)
    final_response: str = ""
    trace_spans: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


def build_debug_bundle(
    *,
    query: str = "",
    normalized_query: str = "",
    response: Any = None,
    final_state: Any = None,
    trace_spans: list[Any] | None = None,
    errors: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> DebugBundle:
    response_dict = _to_dict(response)
    debug_dict = _to_dict(response_dict.get("debug")) if isinstance(response_dict, dict) else {}
    state_dict = _to_dict(final_state)
    semantic_frame = debug_dict.get("semantic_frame") or state_dict.get("semantic_frame") or {}
    execution_plan = _to_dict(debug_dict.get("execution_plan") or state_dict.get("execution_plan") or {})
    evidence_pack = debug_dict.get("evidence_pack") or state_dict.get("evidence_pack") or {}
    answer_plan = debug_dict.get("answer_plan") or state_dict.get("answer_plan") or {}
    decision_plan = debug_dict.get("decision_plan") or state_dict.get("decision_plan") or {}
    tool_results = debug_dict.get("tool_results") or state_dict.get("tool_results") or {}
    tool_calls = debug_dict.get("tool_calls") or state_dict.get("tool_calls") or execution_plan.get("tool_calls") or []
    session_before = debug_dict.get("session_state_before") or state_dict.get("session_state_before") or {}
    session_after = debug_dict.get("session_state_after") or state_dict.get("session_state_after") or {}
    workflow_name = str(
        debug_dict.get("workflow_name")
        or state_dict.get("workflow_name")
        or response_dict.get("workflow_name")
        or ""
    )
    verification_result = debug_dict.get("verification_result") or state_dict.get("verification_result") or {}
    state_update_plan = debug_dict.get("state_update_plan") or state_dict.get("state_update_plan") or {}
    final_response = str(
        response_dict.get("answer_text")
        or response_dict.get("final_response")
        or state_dict.get("final_response")
        or ""
    )
    return DebugBundle.model_validate(
        {
            "query": str(query or response_dict.get("query") or state_dict.get("raw_text") or ""),
            "normalized_query": str(normalized_query or response_dict.get("normalized_query") or state_dict.get("normalized_text") or ""),
            "session_state_before": session_before if isinstance(session_before, dict) else {},
            "semantic_frame": semantic_frame if isinstance(semantic_frame, dict) else {},
            "orchestration_decision": _to_dict(debug_dict.get("orchestration_decision") or state_dict.get("orchestration_decision")),
            "workflow_name": workflow_name,
            "execution_plan": execution_plan,
            "tool_calls": [dict(item) for item in (tool_calls or []) if isinstance(item, dict)],
            "tool_results": tool_results if isinstance(tool_results, dict) else {},
            "evidence_pack": evidence_pack if isinstance(evidence_pack, dict) else {},
            "decision_plan": decision_plan if isinstance(decision_plan, dict) else {},
            "answer_plan": answer_plan if isinstance(answer_plan, dict) else {},
            "verification_result": verification_result if isinstance(verification_result, dict) else {},
            "state_update_plan": state_update_plan if isinstance(state_update_plan, dict) else {},
            "session_state_after": session_after if isinstance(session_after, dict) else {},
            "final_response": final_response,
            "trace_spans": [dict(item) for item in (trace_spans or []) if isinstance(item, dict)],
            "errors": list(errors or []),
            "metadata": dict(metadata or {}),
        }
    )
