from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ...domain.state import GraphState, clone_graph_state


class StateHandler(Protocol):
    def __call__(self, state: GraphState) -> GraphState: ...


def passthrough_handler(state: GraphState) -> GraphState:
    return clone_graph_state(state)


@dataclass
class UnderstandTurnServices:
    # 这里是理解子图的可插拔实现：parse_intent_slots 往往是模型/LLM 分类，resolve_reference 是检索式消歧，ambiguity_check 是规则。
    parse_intent_slots: StateHandler = passthrough_handler
    resolve_reference: StateHandler = passthrough_handler
    ambiguity_check: StateHandler = passthrough_handler
    rag_gate: StateHandler = passthrough_handler
    evidence_gate: StateHandler = passthrough_handler
    rewrite_query: StateHandler = passthrough_handler

    def __post_init__(self) -> None:
        if self.rag_gate is passthrough_handler and self.evidence_gate is not passthrough_handler:
            self.rag_gate = self.evidence_gate
        elif self.evidence_gate is passthrough_handler and self.rag_gate is not passthrough_handler:
            self.evidence_gate = self.rag_gate


@dataclass
class EvidenceSubgraphServices:
    # 证据子图的实现由外部注入，编排层只负责调度，真正能力可以是检索、重排或模型打分。
    hybrid_retrieve: StateHandler = passthrough_handler
    evaluate_evidence: StateHandler = passthrough_handler
    citation_builder: StateHandler = passthrough_handler


@dataclass
class ToolSubgraphServices:
    # 工具子图同样是注入式实现，编排层不关心具体工具 API，只关心调度结果。
    tool_planner: StateHandler = passthrough_handler
    tool_executor: StateHandler = passthrough_handler
    tool_result_normalizer: StateHandler = passthrough_handler


@dataclass
class PlanExecuteSubgraphServices:
    # 复杂计划执行的各步也都是注入式：planner/reviewer 偏规则编排，step_executor 负责真正执行。
    plan_planner: StateHandler = passthrough_handler
    plan_validator: StateHandler = passthrough_handler
    step_executor: StateHandler = passthrough_handler
    progress_checker: StateHandler = passthrough_handler
    plan_reviewer: StateHandler = passthrough_handler
    human_approval_stub: StateHandler = passthrough_handler
    replanner: StateHandler = passthrough_handler


@dataclass
class MainGraphServices:
    # 主图节点大多是规则编排与状态收口，具体业务逻辑由这些注入的 handler 完成。
    resolve_target_shop: StateHandler = passthrough_handler
    clarification_or_reject: StateHandler = passthrough_handler
    build_answer_contract: StateHandler = passthrough_handler
    build_source_contract: StateHandler = passthrough_handler
    complexity_router: StateHandler = passthrough_handler
    hard_guard: StateHandler = passthrough_handler
    request_legality: StateHandler = passthrough_handler
    query_safety: StateHandler = passthrough_handler
    query_merge_for_local_life: StateHandler = passthrough_handler
    merged_query_safety: StateHandler = passthrough_handler
    top_level_intent_router: StateHandler = passthrough_handler
    identity_answer: StateHandler = passthrough_handler
    capability_answer: StateHandler = passthrough_handler
    direct_chat_answer: StateHandler = passthrough_handler
    out_of_scope_response: StateHandler = passthrough_handler
    illegal_request_response: StateHandler = passthrough_handler
    safety_reject_response: StateHandler = passthrough_handler
    direct_executor: StateHandler = passthrough_handler
    workflow_executor: StateHandler = passthrough_handler
    clarification_node: StateHandler = passthrough_handler
    rule_review: StateHandler = passthrough_handler
    select_required_sources: StateHandler = passthrough_handler
    final_answer: StateHandler = passthrough_handler
    merge_or_rank: StateHandler = passthrough_handler
    contract_review: StateHandler = passthrough_handler
    prepare_retry: StateHandler = passthrough_handler
    final_answer_safety: StateHandler = passthrough_handler
    final_safety_fallback: StateHandler = passthrough_handler
    repair_answer: StateHandler = passthrough_handler
    final_with_limitations: StateHandler = passthrough_handler
    target_requirement_router: StateHandler = passthrough_handler
    resolve_comparison_targets: StateHandler = passthrough_handler
    prepare_recommendation_context: StateHandler = passthrough_handler
    response_builder: StateHandler = passthrough_handler


@dataclass
class WorkflowServices:
    load_context: StateHandler = passthrough_handler
    consume_pending_clarification: StateHandler = passthrough_handler
    conversation_recap_direct_response: StateHandler = passthrough_handler
    understand_turn: UnderstandTurnServices = field(default_factory=UnderstandTurnServices)
    evidence_subgraph: EvidenceSubgraphServices = field(default_factory=EvidenceSubgraphServices)
    tool_subgraph: ToolSubgraphServices = field(default_factory=ToolSubgraphServices)
    plan_execute: PlanExecuteSubgraphServices = field(default_factory=PlanExecuteSubgraphServices)
    main_graph: MainGraphServices = field(default_factory=MainGraphServices)
    compose_answer: StateHandler = passthrough_handler
    persist_session: StateHandler = passthrough_handler
    emit_final: StateHandler = passthrough_handler
