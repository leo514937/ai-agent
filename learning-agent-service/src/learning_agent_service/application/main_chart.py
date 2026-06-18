"""
MainChart - 主图分层架构 (准备→安全→路由→子图执行→响应)

职责：
- 管理 5 层架构
- 协调层间通信
- 执行主流程控制
- 提供 trace 记录
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import time
import uuid
from datetime import datetime

from learning_agent_service.application.execution_plan_builder import (
    ExecutionPlanBuilder,
    ExecutionPlan,
    ExecutionStep,
    ExecutionStepResult,
)
from learning_agent_service.application.router_agent import RoutingAgent
from learning_agent_service.application.routing_policy_validator import RoutingPolicyValidator
from learning_agent_service.domain.contracts import RoutingDecision


class MainChart:
    """主图分层架构 (准备→安全→路由→子图执行→响应)"""
    
    def __init__(self):
        self.routing_agent = RoutingAgent()
        self.routing_policy_validator = RoutingPolicyValidator()
        self.execution_plan_builder = ExecutionPlanBuilder()
    
    def execute(
        self,
        query: str,
        context: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """执行主流程。"""
        
        trace = self._create_trace(query, context)
        
        try:
            # 1. 执行准备层
            preparation_result = self._execute_preparation_layer(query, context)
            trace["preparation_result"] = preparation_result
            
            # 2. 执行安全层
            security_result = self._execute_security_layer(preparation_result, context)
            trace["security_result"] = security_result
            
            if not security_result["is_safe"]:
                return self._create_early_exit_result(security_result, trace)
            
            # 3. 执行路由层
            routing_result = self._execute_routing_layer(security_result, context)
            trace["routing_result"] = routing_result
            
            if routing_result["capability_line"] in ("clarify", "jailbreak"):
                return self._create_early_exit_result(routing_result, trace)
            
            # 4. 执行子图层
            subgraph_result = self._execute_subgraph_layer(routing_result, context)
            trace["subgraph_result"] = subgraph_result
            
            # 5. 执行响应层
            response_result = self._execute_response_layer(subgraph_result, context)
            trace["response_result"] = response_result
            
            return response_result, trace
            
        except Exception as e:
            trace["error"] = str(e)
            return {
                "success": False,
                "error": str(e),
                "trace": trace,
            }, trace
    
    def _create_trace(
        self,
        query: str,
        context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """创建追踪信息。"""
        
        return {
            "trace_id": str(uuid.uuid4()),
            "timestamp": datetime.now().isoformat(),
            "query": query,
            "context": context,
            "execution_path": [],
            "layers": [],
            "error": None,
        }
    
    def _execute_preparation_layer(
        self,
        query: str,
        context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """执行准备层。"""
        
        # 简单的准备层实现
        return {
            "context": {
                "query": query,
                "session_id": context.get("session_id") if context else None,
                "client_context": context.get("client_context") if context else None,
                "persistent": context.get("persistent") if context else None,
            },
            "intent": "local_life",
            "slots": {"shop_name": "海底捞"},
            "intent_confidence": 0.95,
        }
    
    def _execute_security_layer(
        self,
        preparation_result: dict[str, Any],
        context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """执行安全层。"""
        
        # 简单的安全检查
        query = preparation_result["context"]["query"]
        
        # 检查是否包含安全威胁
        if any(keyword in query for keyword in ["忽略之前的指令", "system prompt", "jailbreak"]):
            return {
                "is_safe": False,
                "blocked": True,
                "blocked_reason": "security_check_failed",
                "security_checks": ["pre_hard_guard"],
            }
        
        return {
            "context": preparation_result["context"],
            "is_safe": True,
            "blocked": False,
            "blocked_reason": None,
            "security_checks": ["query_analysis"],
        }
    
    def _execute_routing_layer(
        self,
        security_result: dict[str, Any],
        context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """执行路由层。"""
        
        if not security_result["is_safe"]:
            return {
                "capability_line": "jailbreak",
                "required_action": "reject",
                "should_call_tool": False,
                "blocked": True,
                "blocked_reason": security_result["blocked_reason"],
            }
        
        # 执行路由代理
        routing_decision, routing_trace = self.routing_agent.route(
            security_result["context"]["query"],
            persistent=context.get("persistent") if context else None,
            client_context=context.get("client_context") if context else None,
            resolved_shop=context.get("resolved_shop") if context else None,
        )
        
        # 执行路由策略验证器
        validated_decision = self.routing_policy_validator.validate(
            routing_decision,
            resolved_shop=context.get("resolved_shop") if context else None,
        )
        
        return {
            "capability_line": validated_decision.capability_line,
            "required_action": validated_decision.required_action,
            "should_call_tool": validated_decision.should_call_tool,
            "blocked": validated_decision.blocked,
            "blocked_reason": validated_decision.blocked_reason,
            "routing_decision": validated_decision,
            "routing_trace": routing_trace,
        }
    
    def _execute_subgraph_layer(
        self,
        routing_result: dict[str, Any],
        context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """执行子图层。"""
        
        # 构建执行计划
        execution_plan = self.execution_plan_builder.build_execution_plan(
            routing_result["routing_decision"].facet_plan,
            context.get("resolved_shop") if context else None,
            context,
        )
        
        # 执行子图（简化实现）
        results = []
        for step in execution_plan.steps:
            step_result = self._execute_step(step, context)
            results.append(step_result)
        
        return {
            "execution_plan": execution_plan,
            "results": results,
            "success": all(r["success"] for r in results),
        }
    
    def _execute_response_layer(
        self,
        subgraph_result: dict[str, Any],
        context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """执行响应层。"""
        
        # 简单的响应生成
        return {
            "response": "这是一个示例响应。",
            "sources": [],
            "metadata": {
                "execution_time": subgraph_result["execution_plan"].estimated_latency,
                "tool_calls": len([r for r in subgraph_result["results"] if r["action"] == "execute_tool"]),
            },
        }
    
    def _create_early_exit_result(
        self,
        result: dict[str, Any],
        trace: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """创建 early exit 结果。"""
        
        return {
            "success": True,
            "data": result,
            "trace": trace,
            "execution_path": trace.get("execution_path", []),
        }, trace
    
    def _execute_step(
        self,
        step: ExecutionStep,
        context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """执行单个步骤。"""
        
        try:
            if step.action == "direct_answer":
                return self._execute_direct_answer(step, context)
            elif step.action == "execute_tool":
                return self._execute_tool(step, context)
            else:
                return {
                    "success": False,
                    "error": f"未知步骤类型: {step.action}",
                }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }
    
    def _execute_direct_answer(
        self,
        step: ExecutionStep,
        context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """执行直接回答。"""
        
        return {
            "success": True,
            "data": {
                "response": "这是一个直接回答示例。",
                "type": "direct_answer",
            },
        }
    
    def _execute_tool(
        self,
        step: ExecutionStep,
        context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """执行工具。"""
        
        return {
            "success": True,
            "data": {
                "tool_name": step.target,
                "result": f"工具 {step.target} 执行结果",
                "shop_id": step.params.get("shop_id"),
            },
        }
