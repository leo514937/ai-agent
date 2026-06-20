"""LangGraph State definition — matches todo/05 §1 State Field Table.

Every top-level key is a runtime field in the graph state.  Fields are
grouped by ownership group (唯一写入方 / 主要读取方) per the design doc.
total=False keeps every field optional so that each node only writes
the fields it owns.
"""

from __future__ import annotations

from typing import Optional, TypedDict

from .enums import TaskType, TopIntent
from .schemas import (
    AnswerPlan,
    EvidencePack,
    ExecutionPlan,
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

    task_type: Optional[TaskType]

    # === 语义帧 (Semantic Frame) — write: semantic_parse/slot_extractor, read: context_recovery/task_router ===
    semantic_frame: Optional[SemanticFrame]

    # === 澄清状态 (Pending Clarification) — write: clarify_decide/resolve_shop, read: check_pending/context_recovery ===
    pending_clarification: Optional[PendingClarification]

    # === 会话记忆 (Session Memory) — write: state_update_planner, read: context_recovery/task_router ===
    current_shop: Optional[dict]
    last_recommendation_list: list
    active_constraints: dict
    comparison_targets: list

    # === 解析结果 (Resolve Result) — write: target_resolve/clarify_decide, read: task_plan/clarify_decide ===
    resolved_target: Optional[ResolveShopResult]
    resolve_shop_result: Optional[ResolveShopResult]  # §1 文档字段：target_resolve 直接输出

    # === 执行计划 (Execution Plan) — write: task_plan/facet_planner/comparison_planner, read: plan_validator/tool_execute ===
    execution_plan: Optional[ExecutionPlan]
    validated_plan: Optional[ExecutionPlan]  # §1 文档字段：plan_validator 校验通过后的输出

    # === 工具结果 (Tool Results) — write: tool_execute, read: evidence_build/answer_verify ===
    tool_results: dict[str, ToolResult]
    tool_result_set: dict[str, ToolResult]  # §1 文档字段：tool_execute 的输出

    # === 证据层 (Evidence Pack) — write: evidence_build, read: answer_plan_build/answer_verify ===
    evidence_pack: Optional[EvidencePack]

    # === 回答层 (Answer Layer) — write: answer_plan_build/answer_generate/final_response_build, read: answer_verify/emit_response ===
    answer_plan: Optional[AnswerPlan]
    final_response: str

    # === 状态更新 (State Update) — write: state_update_planner, read: persist_session_state ===
    state_update_plan: Optional[SessionWriteDirective]

    # === 观测字段 (Observability) — append: all nodes, read: emit_response/observability ===
    event_log: list
    metrics_tags: dict
    trace_spans: list

    # === 会话快照 (Session Snapshot) — write: load_session_state, read: top_intent_router/context_recovery/target_resolve/state_update_plan ===
    session_state_before: Optional[SessionState]  # §1 文档字段：加载时的会话快照
    session_state_after: Optional[SessionState]

    # === 运行时辅助 (Runtime aux — not in doc §1 but required for graph operation) ===
    rewrite_count: int
    session_state: Optional[SessionState]
    pending_check_result: str
    error_code: str
    error_message: str
    plan_validation_result: str
    failed_stage: str
    guard_result: str
    verify_result: str
    draft_response: str
