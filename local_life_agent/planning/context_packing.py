from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..domain.session_context_summary import SessionContextSummary, build_session_context_summary


class ContextPackingRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_name: str
    include_in_prompt: bool = False
    include_in_session_state: bool = True
    preserve_evidence_ref: bool = False
    max_items: int | None = None
    notes: str = ""


class ContextPackingPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_summary: SessionContextSummary = Field(default_factory=SessionContextSummary)
    prompt_fields: dict[str, Any] = Field(default_factory=dict)
    session_only_fields: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    dropped_fields: list[str] = Field(default_factory=list)
    rules: list[ContextPackingRule] = Field(default_factory=list)
    notes: str = ""


DEFAULT_CONTEXT_PACKING_RULES = [
    ContextPackingRule(field_name="current_shop", include_in_prompt=False, include_in_session_state=True, preserve_evidence_ref=False, notes="只保留结构化会话状态"),
    ContextPackingRule(field_name="last_recommendation_list", include_in_prompt=False, include_in_session_state=True, preserve_evidence_ref=True, max_items=5, notes="只保留摘要与引用"),
    ContextPackingRule(field_name="comparison_targets", include_in_prompt=False, include_in_session_state=True, preserve_evidence_ref=True, max_items=5, notes="保留对比对象引用"),
    ContextPackingRule(field_name="active_constraints", include_in_prompt=True, include_in_session_state=True, preserve_evidence_ref=False, notes="短约束可进入 prompt"),
    ContextPackingRule(field_name="pending_clarification", include_in_prompt=True, include_in_session_state=True, preserve_evidence_ref=False, notes="澄清状态可进入 prompt"),
]


def build_context_packing_plan(
    session_state: Any,
    *,
    conversation_continuity: dict[str, Any] | None = None,
    evidence_pack: dict[str, Any] | None = None,
) -> ContextPackingPlan:
    summary = build_session_context_summary(session_state)
    evidence_pack = dict(evidence_pack or {})
    prompt_fields: dict[str, Any] = {
        "session_context": summary.model_dump(),
        "conversation_continuity": dict(conversation_continuity or {}),
    }
    if summary.current_shop_name:
        prompt_fields["current_shop_name"] = summary.current_shop_name
    if summary.last_task_type:
        prompt_fields["last_task_type"] = summary.last_task_type
    if summary.last_recommendation_names:
        prompt_fields["last_recommendation_names"] = list(summary.last_recommendation_names)
    if summary.comparison_target_names:
        prompt_fields["comparison_target_names"] = list(summary.comparison_target_names)
    if summary.preference_hints:
        prompt_fields["preference_hints"] = list(summary.preference_hints)

    evidence_refs: list[str] = []
    for key in ("ranking_snapshot", "comparison_matrix"):
        ref = evidence_pack.get(key, {}) if isinstance(evidence_pack, dict) else {}
        if isinstance(ref, dict) and ref.get("snapshot_id"):
            evidence_refs.append(str(ref["snapshot_id"]))

    session_only_fields = [
        "current_shop",
        "last_recommendation_list",
        "comparison_targets",
        "pending_clarification",
        "active_constraints",
    ]
    dropped_fields = [field for field in ("last_recommendation_list", "comparison_targets") if field not in prompt_fields]
    return ContextPackingPlan(
        session_summary=summary,
        prompt_fields=prompt_fields,
        session_only_fields=session_only_fields,
        evidence_refs=evidence_refs,
        dropped_fields=dropped_fields,
        rules=list(DEFAULT_CONTEXT_PACKING_RULES),
        notes="Structured session context is compacted before prompt injection.",
    )
