"""
WorkflowIntegration - 新旧系统集成

职责：
- 协调新旧系统组件
- 确保平稳过渡
- 提供兼容性支持
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import time

from learning_agent_service.application.router_agent import RoutingAgent
from learning_agent_service.application.routing_policy_validator import RoutingPolicyValidator
from learning_agent_service.application.tool_chain_manager import ToolChainManager
from learning_agent_service.local_life.hybrid_router import HybridRouter


@dataclass
class IntegrationResult:
    """集成结果"""
    
    success: bool
    data: dict[str, Any] | None = None
    error: str | None = None
    integration_type: str = "hybrid"


@dataclass
class MigrationState:
    """迁移状态"""
    
    new_routing_enabled: bool = False
    legacy_routing_enabled: bool = False
    tool_chain_new_primary: bool = True
    validation_required: bool = True
    transition_phase: str = "planning"


class IntegrationStrategy:
    """集成策略"""
    
    def __init__(self):
        self.routing_strategy = "hybrid"
        self.tool_chain_strategy = "parallel"
        self.workflow_strategy = "composition"
        self.routing_config = {
            "new_agent_weight": 0.7,
            "old_router_weight": 0.3,
            "fallback_threshold": 0.8,
        }
        self.tool_chain_config = {
            "new_chain_primary": True,
            "legacy_chain_backup": True,
            "validation_required": True,
        }
        self.workflow_config = {
            "new_routing_points": ["pre_hard_guard", "routing_decision", "policy_validation"],
            "legacy_routing_points": ["hybrid_routing", "keyword_fallback"],
            "transition_points": ["early_exit", "clarification"],
        }


class WorkflowIntegration:
    """工作流集成 (新旧系统集成)"""
    
    def __init__(
        self,
        new_routing_agent: RoutingAgent,
        old_hybrid_router: HybridRouter,
        new_tool_chain: ToolChainManager,
        legacy_components: dict[str, Any],
    ):
        self.new_routing_agent = new_routing_agent
        self.old_hybrid_router = old_hybrid_router
        self.new_tool_chain = new_tool_chain
        self.legacy_components = legacy_components
        
        # 集成策略
        self.integration_strategy = self._determine_integration_strategy()
        
        # 迁移状态
        self.migration_state = MigrationState()
    
    def _determine_integration_strategy(self) -> IntegrationStrategy:
        """确定集成策略。"""
        
        # 根据组件状态和依赖关系确定最佳集成策略
        strategy = IntegrationStrategy()
        
        # 1. 路由集成策略
        if self.new_routing_agent and self.old_hybrid_router:
            strategy.routing_strategy = "hybrid"
            strategy.routing_config = {
                "new_agent_weight": 0.7,  # 新路由代理权重
                "old_router_weight": 0.3,  # 旧路由权重
                "fallback_threshold": 0.8,  # 降级阈值
            }
        
        # 2. 工具链集成策略
        if self.new_tool_chain and self.legacy_components.get("tool_executor"):
            strategy.tool_chain_strategy = "parallel"
            strategy.tool_chain_config = {
                "new_chain_primary": True,  # 新工具链为主
                "legacy_chain_backup": True,  # 旧工具链为备份
                "validation_required": True,  # 需要验证
            }
        
        # 3. 工作流集成策略
        if self.new_routing_agent and self.legacy_components.get("workflow_controller"):
            strategy.workflow_strategy = "composition"
            strategy.workflow_config = {
                "new_routing_points": ["pre_hard_guard", "routing_decision", "policy_validation"],
                "legacy_routing_points": ["hybrid_routing", "keyword_fallback"],
                "transition_points": ["early_exit", "clarification"],
            }
        
        return strategy
    
    async def execute_with_integration(
        self,
        query: str,
        context: dict[str, Any] | None = None,
        use_new_routing: bool = True,
    ) -> tuple[dict[str, Any], IntegrationResult]:
        """
        执行集成后的工作流。
        
        Args:
            query: 用户查询
            context: 执行上下文
            use_new_routing: 是否使用新路由
            
        Returns:
            (ExecutionResult, IntegrationTrace): 执行结果和集成追踪
        """
        integration_result = IntegrationResult(
            success=True,
            data=None,
            error=None,
            integration_type="hybrid",
        )
        
        try:
            # 1. 确定路由策略
            if use_new_routing and self._should_use_new_routing(query, context):
                routing_result, routing_trace = await self._execute_new_routing(
                    query, context
                )
                integration_result.data = routing_result
            else:
                routing_result, routing_trace = await self._execute_legacy_routing(
                    query, context
                )
                integration_result.data = routing_result
            
            # 2. 执行工具链
            tool_chain_result = await self._execute_tool_chain(
                routing_result, context
            )
            
            # 3. 执行响应生成
            response_result = self._execute_response_generation(
                routing_result, tool_chain_result, context
            )
            
            return response_result, integration_result
            
        except Exception as e:
            integration_result.success = False
            integration_result.error = str(e)
            return {
                "success": False,
                "error": str(e),
                "integration_result": integration_result,
            }, integration_result
    
    def _should_use_new_routing(
        self,
        query: str,
        context: dict[str, Any] | None,
    ) -> bool:
        """判断是否应该使用新路由。"""
        
        # 根据查询特征和上下文决定是否使用新路由
        if context and context.get("force_new_routing"):
            return True
        
        # 检查查询是否复杂
        complex_keywords = ["推荐", "对比", "交易", "预订", "退款"]
        query_lower = query.lower()
        has_complex_keywords = any(keyword in query_lower for keyword in complex_keywords)
        
        # 检查是否有店铺上下文
        has_shop_context = (
            context and (
                context.get("shop_id") or
                context.get("shop_name") or
                context.get("current_shop")
            )
        )
        
        # 复杂查询或有店铺上下文时使用新路由
        return has_complex_keywords or has_shop_context
    
    async def _execute_new_routing(
        self,
        query: str,
        context: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """执行新路由。"""
        
        # 使用新路由代理
        routing_decision, routing_trace = self.new_routing_agent.route(
            query,
            persistent=context.get("persistent") if context else None,
            client_context=context.get("client_context") if context else None,
            resolved_shop=context.get("resolved_shop") if context else None,
        )
        
        return routing_decision, routing_trace
    
    async def _execute_legacy_routing(
        self,
        query: str,
        context: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """执行旧路由。"""
        
        # 使用旧路由（混合路由）
        llm_decision, trace_log = await self.old_hybrid_router.route(
            query,
            session_context=context.get("session_context") if context else None,
            client_context=context.get("client_context") if context else None,
            use_llm=True,
        )
        
        # 转换为新的 RoutingResult 格式
        routing_decision = {
            "capability_line": self._map_legacy_route_to_capability(llm_decision.route),
            "required_action": self._map_legacy_intent_to_action(llm_decision.intent),
            "should_call_tool": llm_decision.route in ["realtime_tool", "compare_multi_parent", "structured_first", "merchant_reasoning"],
            "blocked": llm_decision.intent == "unsafe",
            "blocked_reason": "legacy_security_check" if llm_decision.intent == "unsafe" else None,
            "routing_decision": llm_decision,
            "routing_trace": trace_log,
        }
        
        return routing_decision, trace_log
    
    def _map_legacy_route_to_capability(self, legacy_route: str) -> str:
        """将旧路由映射到新能力线路。"""
        
        route_mapping = {
            "general_chat": "direct",
            "realtime_tool": "single_shop_tool",
            "compare_multi_parent": "comparison_tool",
            "structured_first": "recommendation_tool",
            "merchant_reasoning": "single_shop_tool",
            "guide_rule_rag": "recommendation_tool",
        }
        
        return route_mapping.get(legacy_route, "direct")
    
    def _map_legacy_intent_to_action(self, legacy_intent: str) -> str:
        """将旧意图映射到新动作。"""
        
        intent_mapping = {
            "greeting": "direct_answer",
            "thanks": "direct_answer",
            "farewell": "direct_answer",
            "empty": "direct_answer",
            "low_info": "clarify",
            "profile": "direct_answer",
            "memory_update": "memory_update",
            "conversation_recap": "direct_answer",
            "location_unavailable": "clarify",
            "unsafe": "reject",
            "identity": "direct_answer",
            "capability": "direct_answer",
            "out_of_scope": "direct_answer",
            "unknown": "clarify",
        }
        
        return intent_mapping.get(legacy_intent, "direct_answer")
    
    async def _execute_tool_chain(
        self,
        routing_result: dict[str, Any],
        context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """执行工具链。"""
        
        if not routing_result.get("should_call_tool"):
            return {"message": "不需要执行工具"}
        
        # 提取工具调用参数
        tool_params = self._extract_tool_params(routing_result)
        
        # 执行工具链
        return await self.new_tool_chain.execute_tool_chain(
            tool_params.get("tool_name", ""),
            tool_params.get("input_payload", {}),
            context.get("resolved_shop") if context else None,
        )
    
    def _extract_tool_params(
        self,
        routing_result: dict[str, Any],
    ) -> dict[str, Any]:
        """提取工具调用参数。"""
        
        # 从路由决策中提取工具参数
        facet_plan = routing_result["routing_decision"].facet_plan
        if not facet_plan:
            return {"tool_name": "", "input_payload": {}}
        
        # 选择第一个 facet 作为工具调用
        facet = facet_plan[0]
        
        return {
            "tool_name": facet.tool_name,
            "input_payload": {
                "shop_id": facet.shop_id,
                "query": routing_result["routing_decision"].raw_query,
                "context": "tool_execution",
            },
        }
    
    def _execute_response_generation(
        self,
        routing_result: dict[str, Any],
        tool_chain_result: dict[str, Any],
        context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """执行响应生成。"""
        
        # 根据路由结果和工具链结果生成响应
        if routing_result["capability_line"] in ("clarify", "jailbreak"):
            # Early exit 直接返回响应
            return {
                "response": routing_result["routing_decision"].clarification_question
                if routing_result["capability_line"] == "clarify"
                else "抱歉，我无法帮助您完成此操作。",
                "sources": [],
                "metadata": {
                    "early_exit": True,
                    "capability_line": routing_result["capability_line"],
                },
            }
        
        if tool_chain_result.get("success"):
            # 工具执行成功，生成工具响应
            return {
                "response": f"工具 {tool_chain_result.get('tool_name', '')} 执行成功，结果：{tool_chain_result}",
                "sources": [tool_chain_result],
                "metadata": {
                    "tool_execution": True,
                    "tool_name": tool_chain_result.get('tool_name', ''),
                },
            }
        
        # 工具执行失败，生成错误响应
        return {
            "response": f"抱歉，执行过程中出现错误：{tool_chain_result.get('error', '未知错误')}",
            "sources": [],
            "metadata": {
                "tool_execution_failed": True,
                "error": tool_chain_result.get('error', '未知错误'),
            },
        }