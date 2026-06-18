"""
ToolChainManager - 工具链管理器 (Registry → Validator → Adapter → Executor)

职责：
- 管理工具链的完整流程
- 确保工具调用的一致性和安全性
- 提供工具执行的完整支持
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import time

from learning_agent_service.tools.registry import ToolRegistry, RegisteredTool
from learning_agent_service.tools.tool_call_validator import ToolCallValidator
from learning_agent_service.tools.tool_adapter import ToolAdapter
from learning_agent_service.tools.executor import ToolExecutor


@dataclass
class ToolChainResult:
    """工具链执行结果"""
    
    success: bool
    data: dict[str, Any] | Any | None = None
    error: str | None = None
    step: str | None = None
    steps_completed: list[str] | None = None


class ToolChainManager:
    """工具链管理器 (Registry → Validator → Adapter → Executor)"""
    
    def __init__(
        self,
        registry: ToolRegistry,
        validator: ToolCallValidator,
        adapter: ToolAdapter,
        executor: ToolExecutor,
    ):
        self.registry = registry
        self.validator = validator
        self.adapter = adapter
        self.executor = executor
    
    async def execute_tool_chain(
        self,
        tool_name: str,
        input_payload: dict[str, Any],
        resolved_shop: Any | None = None,
    ) -> ToolChainResult:
        """
        执行完整的工具链。
        
        Args:
            tool_name: 工具名称
            input_payload: 输入参数
            resolved_shop: 解析的店铺信息
            
        Returns:
            ToolChainResult 执行结果
        """
        try:
            # 1. 工具注册验证
            if not self.registry.is_registered(tool_name):
                return ToolChainResult(
                    success=False,
                    error=f"Tool '{tool_name}' is not registered in the tool registry",
                    step="registry_validation",
                    steps_completed=["registry_validation"],
                )
            
            # 2. 工具调用验证
            tool_selection = self.validator.validate(tool_name, input_payload)
            
            # 3. 工具适配
            adapted_selection = self.adapter.adapt(
                tool_selection,
                resolved_shop=resolved_shop,
                shop_id=tool_selection.input_payload.get("shop_id"),
            )
            
            # 4. 工具执行
            execution_result = await self.executor.execute(adapted_selection)
            
            return ToolChainResult(
                success=True,
                data=execution_result.model_dump(mode="json") if hasattr(execution_result, 'model_dump') else execution_result,
                steps_completed=["registry_validation", "tool_validation", "tool_adaptation", "tool_execution"],
            )
            
        except Exception as e:
            return ToolChainResult(
                success=False,
                error=f"Tool chain execution failed: {str(e)}",
                step="tool_execution",
                steps_completed=["registry_validation", "tool_validation", "tool_adaptation"],
            )
    
    def register_tool(
        self,
        tool_name: str,
        spec: Any,  # ToolSpec
        handler: Any,  # Callable
    ) -> None:
        """注册工具。"""
        
        registered_tool = RegisteredTool(
            spec=spec,
            handler=handler,
        )
        
        self.registry.register(registered_tool)
    
    def get_tool_spec(self, tool_name: str) -> Any | None:
        """获取工具规范。"""
        
        try:
            registered_tool = self.registry.get(tool_name)
            return registered_tool.spec
        except KeyError:
            return None
    
    def is_tool_registered(self, tool_name: str) -> bool:
        """检查工具是否已注册。"""
        
        return self.registry.is_registered(tool_name)