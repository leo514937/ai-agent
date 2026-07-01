"""LangGraph State definition — matches todo/05 §1 State Field Table.

Every top-level key is a runtime field in the graph state.  Fields are
grouped by ownership group (唯一写入方 / 主要读取方) per the design doc.
total=False keeps every field optional so that each node only writes
the fields it owns.
"""

from __future__ import annotations

from operator import add
from typing import Annotated, Optional, TypedDict

from .candidate import CandidateSet, CandidateSpec, LocalLifeGoalDraft, ResolutionStage
from .enums import TaskType, TopIntent
from .goal import GoalPlan, GoalReviewResult
from .decision import DecisionPlan, DecisionReviewResult
from .schemas import (
    AnswerPlan,
    ComparisonTargetResolution,
    EvidencePack,
    ExecutionPlan,
    ExplorationPlan,
    OrchestrationDecision,
    PendingClarification,
    ResolveShopResult,
    SemanticFrame,
    ToolResult,
)
from .state import SessionState, SessionWriteDirective


class GraphState(TypedDict, total=False):
    """Full graph state — one dict per turn.

    Field groups and ownership follow todo/05 §1.
    """

    # === 路由标识 (Routing IDs) — write: receive_input, read: all ===
    trace_id: str
    turn_id: str
    session_id: str
    user_id: str

    # === 输入层 (Input Layer) — write: receive_input/normalize_text, read: hard_guard/top_intent_router ===
    raw_text: str
    normalized_text: str
    input_type: str

    # === 顶层意图 (Top Intent) — write: top_intent_router, read: semantic_parse/response_builder ===
    top_intent: Optional[TopIntent]

    # str — written as TaskType.value string by evidence_planner / target_resolve / semantic_parse
    task_type: Optional[str]

    # === 语义帧 (Semantic Frame) — write: semantic_parse/slot_extractor, read: context_recovery/task_router ===
    semantic_frame: Optional[SemanticFrame]

    # === 澄清状态 (Pending Clarification) — write: clarify_decide/resolve_shop, read: check_pending/context_recovery ===
    pending_clarification: Optional[PendingClarification]
    clarification_request: Optional[PendingClarification]
    active_turn_result: dict[str, object]
    active_turn_route: str
    restored_task: str
    selected_candidate: dict
    selected_index: int

    # === 会话记忆 (Session Memory) — write: state_update_planner, read: context_recovery/task_router ===
    current_shop: Optional[dict]
    last_recommendation_list: list
    active_constraints: dict
    comparison_targets: list
    comparison_result: object
    recommendation_candidates: list
    precomputed_tool_results: dict[str, ToolResult]

    # === P2 目标 (Goal) — write: goal_planner/goal_review, read: candidate_resolve/evidence_planner/decision_planner ===
    goal_plan: Optional[GoalPlan]
    goal_review_result: Optional[GoalReviewResult]
    goal_plan_source: str

    # === 候选集 (CandidateSet) — write: goal_draft/candidate_resolve/candidate_review, read: evidence_planner/evidence_build/answer_plan ===
    local_life_goal_draft: Optional[LocalLifeGoalDraft]
    candidate_spec: Optional[CandidateSpec]
    candidate_set: Optional[CandidateSet]
    review_results: Optional[dict]

    # === 解析结果 (Resolve Result) — write: target_resolve/clarify_decide, read: evidence_planner/clarify_decide ===
    resolved_target: Optional[ResolveShopResult]
    resolve_shop_result: Optional[ResolveShopResult]  # §1 文档字段：target_resolve 直接输出
    target_resolution_status: str
    # resolution_stage — 分层语义：candidate_set_resolved | target_resolved | winner_decided
    # writing: planning_subgraph / decision_planner, reading: clarify_decide / state_update_plan
    resolution_stage: Optional[str]

    # === 执行计划 (Execution Plan) — write: evidence_planner/decision_planner, read: plan_validator/tool_execute ===
    execution_plan: Optional[ExecutionPlan]
    validated_plan: Optional[ExecutionPlan]  # §1 文档字段：plan_validator 校验通过后的输出
    execution_plan_source: str

    # === 工具结果 (Tool Results) — write: tool_execute, read: evidence_build/answer_verify ===
    tool_results: dict[str, ToolResult]
    tool_result_set: dict[str, ToolResult]  # §1 文档字段：tool_execute 的输出

    # === 证据层 (Evidence Pack) — write: evidence_build, read: answer_plan_build/answer_verify ===
    evidence_pack: Optional[EvidencePack]

    # === P2 决策 (Decision) — write: decision_planner/decision_review, read: answer_generate ===
    p2_decision_plan: Optional[DecisionPlan]
    decision_review_result: Optional[DecisionReviewResult]

    # === Phase 4 二级路由 (Shadow Orchestration) — write: orchestration_router, read: trace/log only ===
    orchestration_decision: Optional[OrchestrationDecision]
    orchestration_pattern: str
    workflow_name: str
    workflow_reason: str
    task_complexity: str
    requires_tool: bool
    requires_clarification: bool
    next_action: str
    orchestration_error_code: str
    orchestration_error_message: str

    # === Phase 5 workflow dispatch ===
    workflow_run_status: str
    workflow_runner_error: str
    workflow_runner_reason: str
    workflow_started_at: str
    workflow_finished_at: str
    workflow_registered: bool
    workflow_callable: str

    # === 回答层 (Answer Layer) — write: answer_plan_build/answer_generate/final_response_build, read: answer_verify/emit_response ===
    answer_plan: Optional[AnswerPlan]
    exploration_plan: Optional[ExplorationPlan]
    final_response: str

    # === 状态更新 (State Update) — write: state_update_planner, read: persist_session_state ===
    state_update_plan: Optional[SessionWriteDirective]

    # === 观测字段 (Observability) — append: all nodes, read: emit_response/observability ===
    event_log: Annotated[list, add]
    metrics_tags: dict
    trace_spans: Annotated[list, add]
    task_type_source: str  # origin of task_type: llm_semantic | context_recovery | target_resolve_override | pending_clarification_restore
    dropped_facets: list  # facet names filtered out by validation

    # === 会话快照 (Session Snapshot) — write: load_session_state, read: top_intent_router/context_recovery/target_resolve/state_update_plan ===
    session_state_before: Optional[SessionState]  # §1 文档字段：加载时的会话快照
    session_state_after: Optional[SessionState]

    # === P2 Replan counters — write: graph routing, read: graph routing ===
    expand_search_count: int
    replan_evidence_count: int

    # === 运行时辅助 (Runtime aux — not in doc §1 but required for graph operation) ===
    rewrite_count: int
    intake_route: str
    merge_clarification_route: str
    understanding_route: str
    planning_route: str
    execution_review_route: str
    response_route: str
    response_mode: str
    session_state: Optional[SessionState]
    pending_check_result: str
    merge_clarification_result: str
    clarification_result: str
    error_code: str
    error_message: str
    plan_validation_result: str
    failed_stage: str
    guard_result: str
    verify_result: str
    draft_response: str
    semantic_source: str
    fallback_reason: str
    answer_fallback_reason: str
    llm_called: bool
    llm_backend: str
    planning_llm_backend: str
    planning_llm_called: bool
    planning_failure_code: str
    answer_source: str
    llm_verbalizer_violation: Optional[str]
    llm_verbalizer_error: Optional[str]
    generated_llm_answer_before_fallback: str
    comparison_target_resolution: Optional[ComparisonTargetResolution]
    reference_resolution_source: str
    answer_verify_passed: bool
    answer_verify_violations: list[str]
    rewrite_needed: bool
    rewrite_reason: str
    final_safety_status: str
    recommendation_query: str
    subgoals: list
    has_temporal_sequence: bool
    expected_output: str
    exploration_round_count: int
    tool_availability: dict
    location_status: str
    user_location: dict


