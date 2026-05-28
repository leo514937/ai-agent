from __future__ import annotations

from typing import Iterable, Optional

from learning_agent_service.domain import ChatTurnCommand, PersistentSessionContext, SseEnvelope
from learning_agent_service.local_life.subgraph import LocalLifeSubgraph
from ..workflow.adapters import WorkflowNodeAdapter
from ..workflow.runner import SequentialWorkflowRunner
from ..workflow.services import (
    PlanExecuteSubgraphServices,
    RagSubgraphServices,
    ToolSubgraphServices,
    UnderstandTurnServices,
    WorkflowServices,
)


class ChatWorkflowService:
    def __init__(self, container) -> None:
        self._container = container
        session_context_store = getattr(container, "session_context_store", None)
        self._workflow = LocalLifeSubgraph(
            settings=container.settings,
            business_client=getattr(container, "java_business_client", None),
            model_assistant=getattr(container, "local_life_assistant", None),
            local_life_retriever=getattr(container, "local_life_retriever", None),
            session_context_store=session_context_store,
        )
        self._workflow_services = self._build_workflow_services()
        self._workflow_runner = SequentialWorkflowRunner(
            services=self._workflow_services,
            workflow_version=container.settings.workflow_version,
        )

    def run(
        self,
        command: ChatTurnCommand,
        persistent_context: Optional[PersistentSessionContext] = None,
    ) -> Iterable[SseEnvelope]:
        session_context_store = getattr(self._container, "session_context_store", None)
        if persistent_context is not None:
            persistent = persistent_context
        elif session_context_store is not None:
            persistent = session_context_store.load(command.session_id, command.user_id)
        else:
            persistent = PersistentSessionContext()
        if self._should_use_local_life_subgraph(command):
            return self._workflow.run_stream(command=command, persistent_context=persistent)
        return self._workflow_runner.run_stream(command=command, persistent_context=persistent)

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
            plan_execute_subgraph=PlanExecuteSubgraphServices(
                plan_planner=adapter.plan_planner,
                plan_validator=adapter.plan_validator,
                step_executor=adapter.step_executor,
                progress_checker=adapter.progress_checker,
                plan_reviewer=adapter.plan_reviewer,
                human_approval_stub=adapter.human_approval_stub,
                replanner=adapter.replanner,
            ),
            compose_answer=adapter.compose_answer,
            persist_session=adapter.persist_session,
            emit_final=adapter.emit_final,
        )

    @staticmethod
    def _should_use_local_life_subgraph(command: ChatTurnCommand) -> bool:
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
        return any(
            token in compact
            for token in ("吃饭", "火锅", "餐厅", "店", "优惠券", "团购", "订座", "预约", "订单", "对比", "哪家", "怎么样", "附近")
        )
