from __future__ import annotations

import logging
from collections.abc import Iterable

from learning_agent_service.config import Settings

from learning_agent_service.domain import ChatTurnCommand, PersistentSessionContext, SseEnvelope

from ..workflow.adapters import WorkflowNodeAdapter
from ..workflow.builder import create_workflow_runner
from ..workflow.services import (
    MainGraphServices,
    RagSubgraphServices,
    PlanExecuteSubgraphServices,
    ToolSubgraphServices,
    UnderstandTurnServices,
    WorkflowServices,
)

_LOGGER = logging.getLogger(__name__)

class ChatWorkflowService:
    def __init__(self, container) -> None:
        self._container = container
        self._settings = getattr(container, "settings", None) or Settings()
        self._workflow_services = self._build_workflow_services()
        self._workflow_runner = create_workflow_runner(
            services=self._workflow_services,
            workflow_version=self._settings.workflow_version,
            prefer_langgraph=bool(getattr(self._settings, "local_life_use_langgraph", True)),
            checkpointer=getattr(container, "workflow_checkpointer", None),
        )

    def run(
        self,
        command: ChatTurnCommand,
        persistent_context: PersistentSessionContext | None = None,
    ) -> Iterable[SseEnvelope]:
        settings = getattr(self, "_settings", None) or getattr(self._container, "settings", None) or Settings()
        session_context_store = getattr(self._container, "session_context_store", None)
        if persistent_context is not None:
            persistent = persistent_context
        elif session_context_store is not None:
            persistent = session_context_store.load(command.session_id, command.user_id)
        else:
            persistent = PersistentSessionContext()

        from typing import cast

        def _stream() -> Iterable[SseEnvelope]:
            for event in self._workflow_runner.run_stream(command=command, persistent_context=persistent):
                yield cast(SseEnvelope, event)

        return _stream()

    def _build_workflow_services(self) -> WorkflowServices:
        adapter = WorkflowNodeAdapter(self._container)
        return WorkflowServices(
            load_context=adapter.load_context,
            understand_turn=UnderstandTurnServices(
                parse_intent_slots=adapter.parse_intent_slots,
                resolve_reference=adapter.resolve_reference,
                ambiguity_check=adapter.ambiguity_check,
                rag_gate=adapter.rag_gate,
                rewrite_query=adapter.rewrite_query,
            ),
            consume_pending_clarification=adapter.consume_pending_clarification,
            conversation_recap_direct_response=adapter.conversation_recap_direct_response,
            rag_subgraph=RagSubgraphServices(
                hybrid_retrieve=adapter.hybrid_retrieve,
                evaluate_evidence=adapter.evaluate_evidence,
                citation_builder=adapter.citation_builder,
            ),
            tool_subgraph=ToolSubgraphServices(
                tool_planner=adapter.tool_planner,
                tool_executor=adapter.tool_executor,
                tool_result_normalizer=adapter.tool_result_normalizer,
            ),
            plan_execute=PlanExecuteSubgraphServices(
                plan_planner=adapter.plan_planner,
                plan_validator=adapter.plan_validator,
                step_executor=adapter.step_executor,
                progress_checker=adapter.progress_checker,
                plan_reviewer=adapter.plan_reviewer,
                human_approval_stub=adapter.human_approval_stub,
                replanner=adapter.replanner,
            ),
            main_graph=MainGraphServices(
                resolve_target_shop=adapter.resolve_target_shop,
                clarification_or_reject=adapter.clarification_or_reject,
                build_answer_contract=adapter.build_answer_contract,
                build_source_contract=adapter.build_source_contract,
                complexity_router=adapter.complexity_router,
                hard_guard=adapter.hard_guard,
                request_legality=adapter.request_legality,
                query_safety=adapter.query_safety,
                query_merge_for_local_life=adapter.query_merge_for_local_life,
                merged_query_safety=adapter.merged_query_safety,
                top_level_intent_router=adapter.top_level_intent_router,
                identity_answer=adapter.identity_answer,
                capability_answer=adapter.capability_answer,
                direct_chat_answer=adapter.direct_chat_answer,
                out_of_scope_response=adapter.out_of_scope_response,
                illegal_request_response=adapter.illegal_request_response,
                safety_reject_response=adapter.safety_reject_response,
                direct_executor=adapter.direct_executor,
                workflow_executor=adapter.workflow_executor,
                clarification_node=adapter.clarification_node,
                rule_review=adapter.rule_review,
                select_required_sources=adapter.select_required_sources,
                final_answer=adapter.final_answer,
                merge_or_rank=adapter.merge_or_rank,
                contract_review=adapter.contract_review,
                prepare_retry=adapter.prepare_retry,
                final_answer_safety=adapter.final_answer_safety,
                final_safety_fallback=adapter.final_safety_fallback,
                repair_answer=adapter.repair_answer,
                final_with_limitations=adapter.final_with_limitations,
                response_builder=adapter.response_builder,
            ),
            compose_answer=adapter.compose_answer,
            persist_session=adapter.persist_session,
            emit_final=adapter.emit_final,
        )

    @staticmethod
    def _should_use_local_life_subgraph(
        command: ChatTurnCommand,
        persistent: PersistentSessionContext | None = None,
    ) -> bool:
        message = str(getattr(command, "message", "") or "")
        compact = message.replace(" ", "")
        if any(k in compact for k in ("记得", "聊过", "刚才", "之前", "回忆", "历史", "上下文", "我们说过")):
            return False
        client_context = dict(getattr(command, "client_context", {}) or {})
        page = str(getattr(command, "page", "") or client_context.get("page") or client_context.get("entry") or "").lower()
        if page in {"meituan_search_box", "assistant", "ai", "shop", "shops", "detail"}:
            return True
        if any(key in client_context for key in ("shopId", "shopName", "typeId", "typeName", "city", "location")):
            return True
        # 如果 session 里有待澄清（上轮 LocalLifeSubgraph 提问了题目），当前轮必须继续进入本地生活子图
        if persistent is not None and getattr(persistent, "pending_clarification", None) is not None:
            return True
        return any(
            token in compact
            for token in (
                "吃饭", "火锅", "餐厅", "店", "优惠券", "券", "团购", "订座", "预约", "订单",
                "对比", "哪家", "怎么样", "附近", "它", "这家", "这店", "这间", "这商户",
                # 城市名（用于多轮澄清回答）
                "北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "西安", "南京",
                "重庆", "苏州", "天津", "郑州", "长沙", "宁波",
                # 位置相关补充词
                "商圈", "市区", "朝阳", "海淀", "浦东", "余杭", "滨江",
            )
        )
