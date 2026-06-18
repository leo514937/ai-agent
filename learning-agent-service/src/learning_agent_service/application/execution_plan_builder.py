"""
ExecutionPlanBuilder - 根据 FacetPlan 生成执行计划。

职责：
- 解析 FacetPlan，生成可执行的 ToolPlan
- 确保 shop_id 绑定
- 处理多候选场景
- 生成执行顺序
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from learning_agent_service.domain.contracts import FacetPlan
from learning_agent_service.tools.shop_id_enforcer import ShopIdEnforcer


@dataclass
class ExecutionStep:
    """执行步骤。"""
    
    step_id: str
    action: str
    target: str | None
    params: dict[str, Any] = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)
    estimated_latency: int = 0
    approval_required: bool = False
    approval_status: str = "pending"
    approval_request: dict[str, Any] = field(default_factory=dict)


@dataclass
class Dependency:
    """执行依赖关系。"""
    
    from_step: str
    to_step: str
    dependency_type: str  # "sequential", "parallel", "conditional"


@dataclass
class ExecutionStepResult:
    """执行步骤结果。"""
    
    success: bool
    error: str | None = None
    data: dict[str, Any] | None = None


@dataclass
class ExecutionPlan:
    """执行计划。"""
    
    steps: list[ExecutionStep]
    shop_id: int | None
    estimated_latency: int
    dependencies: list[Dependency]
    metadata: dict[str, Any] = field(default_factory=dict)


class ExecutionPlanBuilder:
    """根据 FacetPlan 生成执行计划。"""
    
    def __init__(self):
        self._step_generators = {
            "direct": self._generate_direct_step,
            "single_shop_tool": self._generate_single_shop_step,
            "recommendation_tool": self._generate_recommendation_step,
            "comparison_tool": self._generate_comparison_step,
            "transaction_tool": self._generate_transaction_step,
            "clarify": self._generate_clarification_step,
            "jailbreak": self._generate_security_step,
        }
    
    def build_execution_plan(
        self,
        facet_plan: list[FacetPlan],
        resolved_shop: Any | None = None,
        context: dict[str, Any] | None = None,
    ) -> ExecutionPlan:
        """构建执行计划。"""
        
        # 1. 验证 FacetPlan 一致性
        validated_facets = self._validate_facet_plan(facet_plan, resolved_shop)
        
        # 2. 生成执行步骤
        execution_steps = []
        for facet in validated_facets:
            step = self._generate_step_from_facet(facet, resolved_shop, context)
            if step:
                execution_steps.extend(step)
        
        # 3. 构建执行计划
        plan = ExecutionPlan(
            steps=execution_steps,
            shop_id=resolved_shop.id if resolved_shop else None,
            estimated_latency=self._estimate_latency(execution_steps),
            dependencies=self._build_dependencies(execution_steps),
        )
        
        return plan
    
    def _validate_facet_plan(
        self,
        facet_plan: list[FacetPlan],
        resolved_shop: Any | None,
    ) -> list[FacetPlan]:
        """验证 FacetPlan 一致性。"""
        
        validated_facets = []
        for facet in facet_plan:
            # 注入 shop_id 到 single_shop facet
            if facet.required_target == "single_shop" and resolved_shop:
                facet.extra["shop_id"] = resolved_shop.id
            
            # 设置 execution_mode
            if not facet.execution_mode or facet.execution_mode == "direct":
                facet = facet.model_copy(update={
                    "execution_mode": facet.execution_mode,
                })
            
            validated_facets.append(facet)
        
        return validated_facets
    
    def _generate_step_from_facet(
        self,
        facet: FacetPlan,
        resolved_shop: Any | None,
        context: dict[str, Any] | None,
    ) -> list[ExecutionStep]:
        """从 Facet 生成执行步骤。"""
        
        generator = self._step_generators.get(facet.execution_mode)
        if not generator:
            return []
        
        return generator(facet, resolved_shop, context)
    
    def _generate_direct_step(
        self,
        facet: FacetPlan,
        resolved_shop: Any | None,
        context: dict[str, Any] | None,
    ) -> list[ExecutionStep]:
        """生成直接回答步骤。"""
        
        return [
            ExecutionStep(
                step_id=f"direct_{facet.name}",
                action="direct_answer",
                target=None,
                params={},
                dependencies=[],
                estimated_latency=100,  # 直接回答耗时较短
                approval_required=False,
            )
        ]
    
    def _generate_single_shop_step(
        self,
        facet: FacetPlan,
        resolved_shop: Any | None,
        context: dict[str, Any] | None,
    ) -> list[ExecutionStep]:
        """生成单店工具步骤。"""
        
        if not resolved_shop:
            # 需要先解析店铺
            return [
                ExecutionStep(
                    step_id=f"resolve_shop_{facet.name}",
                    action="resolve_business_object",
                    target="shop",
                    params={
                        "query": context.get("query", "") if context else "",
                        "shop_id": None,
                        "shop_name": None,
                    },
                    dependencies=[],
                    estimated_latency=500,
                    approval_required=False,
                )
            ]
        
        # 生成工具执行步骤
        tool_steps = []
        if facet.tool_name:
            tool_step = self._generate_tool_step(facet.tool_name, resolved_shop, context)
            tool_steps.append(tool_step)
        
        return tool_steps
    
    def _generate_recommendation_step(
        self,
        facet: FacetPlan,
        resolved_shop: Any | None,
        context: dict[str, Any] | None,
    ) -> list[ExecutionStep]:
        """生成推荐工具步骤。"""
        
        # 推荐工具可能需要先搜索店铺
        steps = []
        if not resolved_shop:
            steps.append(ExecutionStep(
                step_id=f"resolve_shop_{facet.name}",
                action="resolve_business_object",
                target="shop",
                params={
                    "query": context.get("query", "") if context else "",
                    "shop_id": None,
                    "shop_name": None,
                },
                dependencies=[],
                estimated_latency=500,
                approval_required=False,
            ))
        
        # 生成推荐步骤
        steps.append(ExecutionStep(
            step_id=f"search_recommendations_{facet.name}",
            action="search_recommendations",
            target="shops",
            params={
                "query": context.get("query", "") if context else "",
                "shop_id": resolved_shop.id if resolved_shop else None,
                "limit": 10,
            },
            dependencies=[s.step_id for s in steps if s.step_id],
            estimated_latency=1000,
            approval_required=False,
        ))
        
        return steps
    
    def _generate_comparison_step(
        self,
        facet: FacetPlan,
        resolved_shop: Any | None,
        context: dict[str, Any] | None,
    ) -> list[ExecutionStep]:
        """生成对比工具步骤。"""
        
        # 对比工具需要多个店铺
        steps = []
        
        # 如果有 resolved_shop，生成店铺解析步骤
        if resolved_shop:
            steps.append(ExecutionStep(
                step_id=f"resolve_shop_{facet.name}",
                action="resolve_business_object",
                target="shop",
                params={
                    "query": context.get("query", "") if context else "",
                    "shop_id": resolved_shop.id,
                    "shop_name": resolved_shop.name,
                },
                dependencies=[],
                estimated_latency=300,
                approval_required=False,
            ))
        
        # 生成对比步骤
        steps.append(ExecutionStep(
            step_id=f"compare_shops_{facet.name}",
            action="compare_shops",
            target="shops",
            params={
                "query": context.get("query", "") if context else "",
                "shop_ids": [resolved_shop.id] if resolved_shop else None,
                "comparison_criteria": ["price", "quality", "service"],
            },
            dependencies=[s.step_id for s in steps if s.step_id],
            estimated_latency=1500,
            approval_required=False,
        ))
        
        return steps
    
    def _generate_transaction_step(
        self,
        facet: FacetPlan,
        resolved_shop: Any | None,
        context: dict[str, Any] | None,
    ) -> list[ExecutionStep]:
        """生成交易工具步骤。"""
        
        # 交易工具需要身份验证和店铺验证
        steps = []
        
        # 身份验证
        steps.append(ExecutionStep(
            step_id=f"authenticate_user_{facet.name}",
            action="authenticate_user",
            target="user",
            params={
                "user_id": context.get("user_id") if context else None,
                "verification_code": None,
            },
            dependencies=[],
            estimated_latency=200,
            approval_required=True,  # 需要用户批准
        ))
        
        # 店铺验证
        if resolved_shop:
            steps.append(ExecutionStep(
                step_id=f"validate_shop_access_{facet.name}",
                action="validate_shop_access",
                target="shop",
                params={
                    "shop_id": resolved_shop.id,
                    "user_id": context.get("user_id") if context else None,
                    "action": "transaction",
                },
                dependencies=[steps[0].step_id],  # 依赖身份验证
                estimated_latency=300,
                approval_required=True,  # 需要店铺批准
            ))
        
        # 生成交易步骤
        steps.append(ExecutionStep(
            step_id=f"execute_transaction_{facet.name}",
            action="execute_transaction",
            target="transaction",
            params={
                "shop_id": resolved_shop.id if resolved_shop else None,
                "transaction_type": facet.name,
                "amount": context.get("amount") if context else None,
                "items": context.get("items") if context else None,
            },
            dependencies=[s.step_id for s in steps if s.step_id],
            estimated_latency=2000,
            approval_required=True,  # 需要最终批准
        ))
        
        return steps
    
    def _generate_clarification_step(
        self,
        facet: FacetPlan,
        resolved_shop: Any | None,
        context: dict[str, Any] | None,
    ) -> list[ExecutionStep]:
        """生成澄清步骤。"""
        
        # 从 context 中获取 missing_slots 和 clarification_question
        missing_slots = context.get("missing_slots", []) if context else []
        clarification_question = context.get("clarification_question") if context else None
        
        return [
            ExecutionStep(
                step_id=f"generate_clarification_{facet.name}",
                action="generate_clarification",
                target="user",
                params={
                    "missing_info": missing_slots,
                    "clarification_question": clarification_question,
                    "context": context,
                },
                dependencies=[],
                estimated_latency=100,
                approval_required=False,
            )
        ]
    
    def _generate_security_step(
        self,
        facet: FacetPlan,
        resolved_shop: Any | None,
        context: dict[str, Any] | None,
    ) -> list[ExecutionStep]:
        """生成安全步骤。"""
        
        return [
            ExecutionStep(
                step_id=f"security_check_{facet.name}",
                action="security_check",
                target="system",
                params={
                    "threat_level": "high",
                    "action": "block",
                    "reason": "security_check",
                },
                dependencies=[],
                estimated_latency=50,
                approval_required=False,
            )
        ]
    
    def _generate_tool_step(
        self,
        tool_name: str,
        resolved_shop: Any | None,
        context: dict[str, Any] | None,
    ) -> ExecutionStep:
        """生成工具步骤。"""
        
        return ExecutionStep(
            step_id=f"execute_tool_{tool_name}",
            action="execute_tool",
            target=tool_name,
            params={
                "tool_name": tool_name,
                "shop_id": resolved_shop.id if resolved_shop else None,
                "input_params": context.get("tool_params", {}) if context else {},
            },
            dependencies=[],
            estimated_latency=1000,
            approval_required=False,
        )
    
    def _estimate_latency(self, steps: list[ExecutionStep]) -> int:
        """估算总延迟。"""
        
        return sum(step.estimated_latency for step in steps)
    
    def _build_dependencies(self, steps: list[ExecutionStep]) -> list[Dependency]:
        """构建依赖关系。"""
        
        dependencies = []
        for i, step in enumerate(steps):
            step_deps = []
            for j in range(i):
                if steps[j].step_id:
                    step_deps.append(Dependency(
                        from_step=steps[j].step_id,
                        to_step=step.step_id,
                        dependency_type="sequential",
                    ))
            dependencies.extend(step_deps)
        
        return dependencies