"""P13 GraphState adapter model.

This module provides a validation-only BaseModel view over the legacy
TypedDict GraphState shape. It is intentionally permissive: the production
graph still uses ``GraphState`` as a dict-shaped runtime contract, while
this adapter collects schema issues and canonical aliases without changing
business behavior.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .decision import DecisionPlan as CanonicalDecisionPlan
from .evidence import EvidenceReviewResult
from .facets import TargetResolutionResult
from .goal import GoalPlan, GoalReviewResult
from .schemas import (
    AnswerPlan,
    ContextualizedTurn,
    ComparisonTargetResolution,
    EvidencePack,
    ExecutionPlan,
    FocusContext,
    FreshnessMeta,
    OrchestrationDecision,
    LocationContext,
    ClarificationRequest,
    ResolveShopResult,
    SemanticFrame,
    ToolResult,
)
from .state import SessionState, StateUpdatePlan
from .serialization import to_plain_dict
from ..planning.budget.budget_context import BudgetContext


def _to_dict(value: Any) -> dict[str, Any]:
    return to_plain_dict(value)


def _first_text(value: Any) -> str:
    if isinstance(value, (list, tuple, set)):
        for item in value:
            text = str(item or "").strip()
            if text:
                return text
        return ""
    return str(value or "").strip()


def _enum_text(value: Any) -> str:
    if value is None:
        return ""
    return str(getattr(value, "value", value) or "").strip()


class GraphStateFieldContract(BaseModel):
    """Human-readable state ownership contract for a GraphState field group."""

    model_config = ConfigDict(extra="forbid")

    field_name: str
    owner: str
    canonical_field: str
    compatibility_fields: list[str] = Field(default_factory=list)
    consumers: list[str] = Field(default_factory=list)
    can_clean_now: bool = False
    cleanup_timing: str = "future"
    notes: str = ""


GRAPH_STATE_FIELD_CONTRACTS: dict[str, GraphStateFieldContract] = {
    "tool_results": GraphStateFieldContract(
        field_name="tool_results",
        owner="execution_review_subgraph",
        canonical_field="tool_results",
        compatibility_fields=["tool_result_set"],
        consumers=["evidence_builder", "answer_verify", "metrics"],
        can_clean_now=False,
        cleanup_timing="future",
        notes="tool_result_set is the legacy compatibility mirror.",
    ),
    "target_resolution": GraphStateFieldContract(
        field_name="target_resolution",
        owner="planning_subgraph",
        canonical_field="target_resolution",
        compatibility_fields=["resolved_target", "resolve_shop_result"],
        consumers=["evidence_planner", "decision_planner", "state_update_planner"],
        can_clean_now=False,
        cleanup_timing="future",
        notes="TargetResolutionResult remains the canonical target resolution protocol.",
    ),
    "session_state": GraphStateFieldContract(
        field_name="session_state",
        owner="state_update_plan",
        canonical_field="session_state",
        compatibility_fields=["session_state_before", "session_state_after"],
        consumers=["planning_subgraph", "response_subgraph", "persist_session_state"],
        can_clean_now=False,
        cleanup_timing="future",
        notes="state_update_plan is the only write-back entry point.",
    ),
    "orchestration_decision": GraphStateFieldContract(
        field_name="orchestration_decision",
        owner="orchestration_router",
        canonical_field="orchestration_decision",
        compatibility_fields=["workflow_name", "response_mode", "next_action"],
        consumers=["workflow_runner", "trace", "metrics"],
        can_clean_now=False,
        cleanup_timing="future",
        notes="workflow_name is a high-frequency mirror, not a list.",
    ),
    "evidence_pack": GraphStateFieldContract(
        field_name="evidence_pack",
        owner="execution_review_subgraph",
        canonical_field="evidence_pack",
        compatibility_fields=["evidence_items", "facet_results", "ranking_snapshot", "comparison_matrix"],
        consumers=["answer_plan_builder", "decision_planner", "answer_verify", "metrics"],
        can_clean_now=False,
        cleanup_timing="future",
        notes="EvidencePack remains the factual source of truth for answer planning.",
    ),
}


class GraphStateModel(BaseModel):
    """Validation-only adapter for the dict-shaped GraphState runtime."""

    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    trace_id: str = ""
    turn_id: str = ""
    session_id: str = ""
    user_id: str = ""
    raw_text: str = ""
    normalized_text: str = ""
    input_type: str = ""
    workflow_name: str = ""
    response_mode: str = ""
    task_type: str = ""
    orchestration_decision: OrchestrationDecision | None = None
    top_intent: Any | None = None
    semantic_frame: SemanticFrame | None = None
    semantic_parse_source: str = ""
    schema_validation_result: dict[str, Any] = Field(default_factory=dict)
    grounding_status: str = ""
    missing_slot_type: str = ""
    target_resolution: TargetResolutionResult | None = None
    target_resolution_status: str = ""
    resolved_target: ResolveShopResult | None = None
    resolve_shop_result: ResolveShopResult | None = None
    comparison_target_resolution: ComparisonTargetResolution | None = None
    execution_plan: ExecutionPlan | None = None
    validated_plan: ExecutionPlan | None = None
    decision_plan: CanonicalDecisionPlan | None = None
    p2_decision_plan: CanonicalDecisionPlan | None = None
    answer_plan: AnswerPlan | None = None
    evidence_pack: EvidencePack | None = None
    exploration_plan: Any | None = None
    exploration_stages: list[dict[str, Any]] = Field(default_factory=list)
    stage_queries: list[str] = Field(default_factory=list)
    stage_evidence_requirements: list[list[str]] = Field(default_factory=list)
    stage_statuses: list[str] = Field(default_factory=list)
    scene: str = ""
    time: str = ""
    evidence_status: str = ""
    evidence_review_result: dict[str, Any] = Field(default_factory=dict)
    answer_verify_result: dict[str, Any] = Field(default_factory=dict)
    unsupported_reasons: list[str] = Field(default_factory=list)
    unknown_fields: list[str] = Field(default_factory=list)
    failed_tools: list[str] = Field(default_factory=list)
    partial_fields: list[str] = Field(default_factory=list)
    comparison_support_status: str = ""
    ranking_preserved: bool = True
    comparison_requested: bool = False
    comparison_context_anchor: bool = False
    comparison_multi_target_signal: bool = False
    comparison_resolution_status: str = ""
    comparison_route_reason: str = ""
    state_update_plan: StateUpdatePlan | None = None
    session_state: SessionState | None = None
    session_state_before: SessionState | None = None
    session_state_after: SessionState | None = None
    goal_plan: GoalPlan | None = None
    goal_review_result: GoalReviewResult | None = None
    evidence_review_result: EvidenceReviewResult | None = None
    tool_results: dict[str, ToolResult] = Field(default_factory=dict)
    tool_result_set: dict[str, ToolResult] = Field(default_factory=dict)
    current_shop: dict[str, Any] | None = None
    canonical_shop_entity: dict[str, Any] | None = None
    canonical_shop_entities: list[dict[str, Any]] = Field(default_factory=list)
    last_recommendation_list: list[dict[str, Any]] = Field(default_factory=list)
    comparison_targets: list[dict[str, Any]] = Field(default_factory=list)
    contextualized_turn: ContextualizedTurn | None = None
    focus_context: FocusContext | None = None
    freshness_meta: FreshnessMeta | None = None
    location_context: LocationContext | None = None
    pending_clarification: dict[str, Any] | None = None
    clarification_request: ClarificationRequest | None = None
    clarification_resolution: dict[str, Any] = Field(default_factory=dict)
    resume_strategy: str = ""
    review_results: dict[str, Any] = Field(default_factory=dict)
    budget_context: BudgetContext | None = None
    final_response: str = ""
    preview_text: str = ""
    preview_policy_result: dict[str, Any] = Field(default_factory=dict)
    response_contract_v1: Any | None = None
    response_contract_v2: Any | None = None
    fallback_reason: str = ""
    answer_fallback_reason: str = ""
    planning_started: str = ""
    planning_finished: str = ""
    execution_started: str = ""
    execution_finished: str = ""
    planning_tool_calls_count: int = 0
    execution_tool_calls_count: int = 0
    error_code: str = ""
    error_message: str = ""
    workflow_run_status: str = ""
    workflow_runner_error: str = ""
    workflow_runner_reason: str = ""
    workflow_started_at: str = ""
    workflow_finished_at: str = ""
    workflow_registered: bool = False
    workflow_callable: str = ""
    workflow_candidate_reason: str = ""
    router_policy_decision: dict[str, Any] = Field(default_factory=dict)
    router_policy_conflicts: list[str] = Field(default_factory=list)
    rule_pattern_signals: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _mirror_aliases(self) -> GraphStateModel:
        if self.workflow_name and self.orchestration_decision is not None:
            if not self.orchestration_decision.workflow_name:
                self.orchestration_decision.workflow_name = self.workflow_name
        elif self.orchestration_decision is not None and not self.workflow_name:
            self.workflow_name = self.orchestration_decision.workflow_name
        if self.orchestration_decision is not None and not self.response_mode:
            self.response_mode = self.orchestration_decision.response_mode
        if self.orchestration_decision is not None and not self.workflow_candidate_reason:
            self.workflow_candidate_reason = self.orchestration_decision.workflow_reason
        if self.execution_plan is None and self.validated_plan is not None:
            self.execution_plan = self.validated_plan
        elif self.validated_plan is None and self.execution_plan is not None:
            self.validated_plan = self.execution_plan
        if self.decision_plan is None and self.p2_decision_plan is not None:
            self.decision_plan = self.p2_decision_plan
        elif self.p2_decision_plan is None and self.decision_plan is not None:
            self.p2_decision_plan = self.decision_plan
        if self.resolved_target is None and self.resolve_shop_result is not None:
            self.resolved_target = self.resolve_shop_result
        elif self.resolve_shop_result is None and self.resolved_target is not None:
            self.resolve_shop_result = self.resolved_target
        if self.pending_clarification is not None and self.clarification_request is None:
            try:
                from ..target.clarification import build_clarification_request
                self.clarification_request = build_clarification_request(self.pending_clarification, source_stage="graph_state_model")
            except Exception:
                pass
        if self.tool_results and not self.tool_result_set:
            self.tool_result_set = dict(self.tool_results)
        elif self.tool_result_set and not self.tool_results:
            self.tool_results = dict(self.tool_result_set)
        if self.semantic_frame is not None:
            if not self.semantic_parse_source:
                self.semantic_parse_source = (
                    _enum_text(getattr(self.semantic_frame, "semantic_parse_source", ""))
                    or _enum_text(getattr(self.semantic_frame, "parse_source", ""))
                    or _enum_text(getattr(self.semantic_frame, "semantic_source", ""))
                )
            if not self.grounding_status:
                self.grounding_status = _enum_text(getattr(self.semantic_frame, "grounding_status", ""))
            if not self.missing_slot_type:
                self.missing_slot_type = _enum_text(getattr(self.semantic_frame, "missing_slot_type", ""))
        return self

    @property
    def canonical_workflow_name(self) -> str:
        return _first_text(self.workflow_name or (self.orchestration_decision.workflow_name if self.orchestration_decision else ""))

    @property
    def canonical_decision_plan(self) -> CanonicalDecisionPlan | None:
        return self.decision_plan or self.p2_decision_plan


class GraphStateModelAdapterError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_name: str
    issue_code: str
    message: str
    severity: str = "warning"
    canonical_field: str | None = None
    compatibility_fields: list[str] = Field(default_factory=list)
    observed_value: Any | None = None


class GraphStateValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_valid: bool = True
    model: GraphStateModel
    canonical_state: dict[str, Any] = Field(default_factory=dict)
    issues: list[GraphStateModelAdapterError] = Field(default_factory=list)
    contracts: list[GraphStateFieldContract] = Field(default_factory=list)
    compatibility_fields: list[str] = Field(default_factory=list)


def _build_issue(
    field_name: str,
    issue_code: str,
    message: str,
    *,
    severity: str = "warning",
    canonical_field: str | None = None,
    compatibility_fields: list[str] | None = None,
    observed_value: Any | None = None,
) -> GraphStateModelAdapterError:
    return GraphStateModelAdapterError(
        field_name=field_name,
        issue_code=issue_code,
        message=message,
        severity=severity,
        canonical_field=canonical_field,
        compatibility_fields=list(compatibility_fields or []),
        observed_value=observed_value,
    )


def _coerce_workflow_name(value: Any) -> tuple[str, GraphStateModelAdapterError | None]:
    if isinstance(value, (list, tuple, set)):
        selected = ""
        for item in value:
            text = str(item or "").strip()
            if text:
                selected = text
                break
        issue = _build_issue(
            "workflow_name",
            "multi_value_workflow_name",
            "workflow_name must be a single value; using the first non-empty item for validation",
            canonical_field="workflow_name",
            observed_value=list(value),
        )
        return selected, issue
    return _first_text(value), None


def _compare_alias_pair(
    payload: dict[str, Any],
    *,
    canonical_field: str,
    alias_field: str,
    compatibility_fields: list[str],
) -> GraphStateModelAdapterError | None:
    canonical = payload.get(canonical_field)
    alias = payload.get(alias_field)
    if canonical is None or alias is None:
        return None
    if _to_dict(canonical) == _to_dict(alias):
        return None
    return _build_issue(
        alias_field,
        "alias_conflict",
        f"{alias_field} differs from canonical field {canonical_field}",
        canonical_field=canonical_field,
        compatibility_fields=compatibility_fields,
        observed_value=alias,
    )


def validate_graph_state(state: Any) -> GraphStateValidationResult:
    """Validate a GraphState-shaped payload without changing runtime behavior."""

    payload = _to_dict(state)
    issues: list[GraphStateModelAdapterError] = []
    workflow_name, workflow_issue = _coerce_workflow_name(payload.get("workflow_name"))
    if workflow_issue is not None:
        issues.append(workflow_issue)
    payload["workflow_name"] = workflow_name

    try:
        model = GraphStateModel.model_validate(payload)
    except ValidationError as exc:
        for err in exc.errors():
            field_name = str(err.get("loc", ["graph_state"])[0] or "graph_state")
            issues.append(
                _build_issue(
                    field_name,
                    str(err.get("type", "validation_error")),
                    str(err.get("msg", "GraphState validation failed")),
                    severity="error",
                    observed_value=payload.get(field_name),
                )
            )
        model = GraphStateModel.model_construct(**payload)

    alias_checks = [
        ("tool_results", "tool_result_set", ["tool_results", "tool_result_set"]),
        ("execution_plan", "validated_plan", ["execution_plan", "validated_plan"]),
        ("decision_plan", "p2_decision_plan", ["decision_plan", "p2_decision_plan"]),
        ("resolved_target", "resolve_shop_result", ["resolved_target", "resolve_shop_result"]),
    ]
    for canonical_field, alias_field, compat_fields in alias_checks:
        issue = _compare_alias_pair(payload, canonical_field=canonical_field, alias_field=alias_field, compatibility_fields=compat_fields)
        if issue is not None:
            issues.append(issue)

    canonical_state = model.model_dump(mode="python", exclude_none=True)
    contracts = list(GRAPH_STATE_FIELD_CONTRACTS.values())
    compatibility_fields = sorted({field for contract in contracts for field in contract.compatibility_fields})
    is_valid = not any(issue.severity == "error" for issue in issues)
    return GraphStateValidationResult(
        is_valid=is_valid,
        model=model,
        canonical_state=canonical_state,
        issues=issues,
        contracts=contracts,
        compatibility_fields=compatibility_fields,
    )
