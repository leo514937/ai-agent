"""LLM constrained tool-plan proposal for the local-life agent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from .. import config
from ..domain.schemas import ToolIntent, ToolPlan
from ..domain.session_context_summary import build_session_context_summary
from ..llm.client import call_llm, load_prompt
from ..llm.json_parser import LLMJSONParseError, parse_json_response
from ..tools.registry import get_registry


@dataclass
class ToolPlanDecision:
    """Normalized result of the tool-planning step."""

    tool_plan: ToolPlan | None
    tool_plan_source: str
    tool_plan_validated: bool
    tool_plan_fallback_reason: str | None
    llm_called: bool
    llm_backend: str
    raw_response: str = ""


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


def _normalize_task_type(value: Any) -> str:
    if hasattr(value, "value"):
        value = getattr(value, "value")
    return str(value or "").strip()


def _allowed_tool_names() -> set[str]:
    registry = get_registry()
    return set(registry.list_tools())


def _render_prompt(
    *,
    raw_text: str,
    top_intent: str,
    task_type: str,
    semantic_frame: dict[str, Any],
    session_state: Any = None,
) -> str:
    prompt_template = load_prompt("tool_planner")
    summary = build_session_context_summary(session_state)
    summary_json = summary.model_dump_json()
    frame_json = ToolPlan.model_validate(
        {
            "task_type": task_type,
            "primary_task": str(semantic_frame.get("primary_task", "") or ""),
            "purpose": str(semantic_frame.get("primary_task", "") or task_type),
            "confidence": float(semantic_frame.get("confidence", 0.0) or 0.0),
            "tool_intents": [],
            "notes": [],
            "raw_text": raw_text,
            "semantic_source": str(semantic_frame.get("semantic_source", "") or ""),
            "llm_backend": str(semantic_frame.get("llm_backend", "") or ""),
        }
    ).model_dump_json()
    allowed_tools = sorted(_allowed_tool_names())
    return (
        prompt_template
        .replace("{{TEXT}}", raw_text)
        .replace("{{TOP_INTENT}}", top_intent)
        .replace("{{TASK_TYPE}}", task_type)
        .replace("{{SEMANTIC_FRAME}}", frame_json)
        .replace("{{SESSION_CONTEXT}}", summary_json)
        .replace("{{ALLOWED_TOOLS}}", str(allowed_tools))
    )


def _prune_candidate(candidate: ToolPlan) -> ToolPlan:
    seen: set[str] = set()
    intents: list[ToolIntent] = []
    for intent in candidate.tool_intents:
        tool_name = str(intent.tool_name or "").strip()
        if not tool_name or tool_name in seen:
            continue
        seen.add(tool_name)
        notes = [str(item).strip() for item in intent.notes or [] if str(item).strip()]
        depends_on = [str(item).strip() for item in intent.depends_on or [] if str(item).strip()]
        intents.append(
            intent.model_copy(
                update={
                    "tool_name": tool_name,
                    "notes": notes,
                    "depends_on": depends_on,
                }
            )
        )
    return candidate.model_copy(update={"tool_intents": intents})


def _validate_candidate(candidate: ToolPlan, allowed_tools: set[str]) -> tuple[bool, str | None]:
    if not candidate.tool_intents:
        return False, "llm_tool_plan_empty"

    for intent in candidate.tool_intents:
        tool_name = str(intent.tool_name or "").strip()
        if not tool_name:
            return False, "llm_tool_plan_invalid_tool_name"
        if tool_name not in allowed_tools:
            return False, "llm_tool_plan_invalid_tool_name"

    return True, None


def _parse_candidate(payload: Any, *, raw_text: str, semantic_frame: dict[str, Any]) -> ToolPlan:
    candidate_dict = payload
    if isinstance(payload, str):
        candidate_dict = parse_json_response(payload)
    if not isinstance(candidate_dict, dict):
        raise ValueError("llm_tool_plan_invalid_schema")
    candidate_dict = dict(candidate_dict)
    candidate_dict.setdefault("task_type", str(semantic_frame.get("task_type", "") or ""))
    candidate_dict.setdefault("primary_task", str(semantic_frame.get("primary_task", "") or ""))
    candidate_dict.setdefault("purpose", str(semantic_frame.get("primary_task", "") or ""))
    candidate_dict.setdefault("confidence", float(semantic_frame.get("confidence", 0.0) or 0.0))
    candidate_dict.setdefault("tool_intents", [])
    candidate_dict.setdefault("notes", [])
    candidate_dict.setdefault("raw_text", raw_text)
    candidate_dict.setdefault("semantic_source", str(semantic_frame.get("semantic_source", "") or ""))
    candidate_dict.setdefault("llm_backend", str(semantic_frame.get("llm_backend", "") or ""))
    return ToolPlan.model_validate(candidate_dict)


def build_tool_plan(
    *,
    raw_text: str,
    top_intent: Any,
    semantic_frame: Any,
    session_state: Any = None,
    llm_call: Any | None = None,
) -> ToolPlanDecision:
    """Build a validated candidate tool plan or fall back to rule-based."""

    frame = _to_dict(semantic_frame)
    task_type = _normalize_task_type(frame.get("task_type"))
    top_intent_value = _normalize_task_type(top_intent)

    if not config.ENABLE_LLM_TOOL_PLANNER:
        return ToolPlanDecision(
            tool_plan=None,
            tool_plan_source="rule_based",
            tool_plan_validated=True,
            tool_plan_fallback_reason=None,
            llm_called=False,
            llm_backend="",
        )

    prompt = _render_prompt(
        raw_text=raw_text,
        top_intent=top_intent_value,
        task_type=task_type,
        semantic_frame=frame,
        session_state=session_state,
    )
    llm_result = (llm_call or call_llm)(
        prompt,
        system_prompt="",
        timeout_ms=config.LLM_TIMEOUT_MS,
        temperature=0.0,
        max_retries=1,
    )

    llm_backend = str(llm_result.get("llm_backend", "") or "")
    if not llm_result.get("ok"):
        return ToolPlanDecision(
            tool_plan=None,
            tool_plan_source="rule_based",
            tool_plan_validated=False,
            tool_plan_fallback_reason=f"llm_tool_plan_{str(llm_result.get('error_code', 'backend_error')).lower()}",
            llm_called=True,
            llm_backend=llm_backend,
            raw_response=str(llm_result.get("raw", "") or ""),
        )

    try:
        candidate = _parse_candidate(llm_result.get("content"), raw_text=raw_text, semantic_frame=frame)
    except (ValidationError, LLMJSONParseError, ValueError):
        return ToolPlanDecision(
            tool_plan=None,
            tool_plan_source="rule_based",
            tool_plan_validated=False,
            tool_plan_fallback_reason="llm_tool_plan_invalid_schema",
            llm_called=True,
            llm_backend=llm_backend,
            raw_response=str(llm_result.get("raw", "") or ""),
        )

    candidate = _prune_candidate(candidate)
    ok, reason = _validate_candidate(candidate, _allowed_tool_names())
    if not ok:
        return ToolPlanDecision(
            tool_plan=None,
            tool_plan_source="rule_based",
            tool_plan_validated=False,
            tool_plan_fallback_reason=reason,
            llm_called=True,
            llm_backend=llm_backend,
            raw_response=str(llm_result.get("raw", "") or ""),
        )

    return ToolPlanDecision(
        tool_plan=candidate.model_copy(
            update={
                "task_type": task_type or candidate.task_type,
                "raw_text": raw_text,
                "semantic_source": str(frame.get("semantic_source", "") or ""),
                "llm_backend": llm_backend or str(llm_result.get("llm_backend", "") or ""),
            }
        ),
        tool_plan_source="llm_tool_plan",
        tool_plan_validated=True,
        tool_plan_fallback_reason=None,
        llm_called=True,
        llm_backend=llm_backend or str(llm_result.get("llm_backend", "") or ""),
        raw_response=str(llm_result.get("raw", "") or ""),
    )
