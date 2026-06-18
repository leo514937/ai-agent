"""
ToolCallValidator — 校验 tool call 名称、参数和目标约束。

职责：
- 校验 LLM 输出的 tool call 是否属于 registry 白名单
- 校验参数 schema、单店/多店目标、required_target 等约束
- 不负责决定新的 tool_name，只负责判断传入名称是否匹配 registry
- 发现非法 tool call 时直接拒绝，不进入执行层
"""

from __future__ import annotations

from typing import Any

from .models import ToolSelection, ToolSpec
from .registry import ToolRegistry


class ToolCallValidationError(RuntimeError):
    """Tool call 校验失败时的异常。"""


class ToolCallValidator:
    """校验 LLM 输出的 tool call 是否合法。"""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def validate(
        self,
        tool_name: str,
        input_payload: dict[str, Any],
    ) -> ToolSelection:
        """校验 tool call 并返回合法的 ToolSelection。

        Args:
            tool_name: LLM 选择的工具名称
            input_payload: LLM 提供的输入参数

        Returns:
            校验通过的 ToolSelection

        Raises:
            ToolCallValidationError: 当 tool call 不合法时
        """
        if not self._registry.is_registered(tool_name):
            raise ToolCallValidationError(
                f"Tool '{tool_name}' is not registered in the tool registry"
            )

        spec: ToolSpec = self._registry.get(tool_name).spec

        # 校验 input_payload 是否匹配 schema
        validation_errors = self._validate_payload(spec, input_payload)
        if validation_errors:
            raise ToolCallValidationError(
                f"Tool '{tool_name}' payload validation failed: {'; '.join(validation_errors)}"
            )

        return ToolSelection(
            tool_name=tool_name,
            input_payload=input_payload,
            reason=f"validated_by_tool_call_validator",
        )

    def _validate_payload(self, spec: ToolSpec, payload: dict[str, Any]) -> list[str]:
        """校验 payload 是否符合 spec 的 input_model。"""
        errors: list[str] = []

        try:
            spec.input_model(**payload)
        except Exception as e:
            errors.append(str(e))

        # 如果工具需要 shop_id，检查 payload 中是否有
        if spec.requires_shop_id and "shop_id" not in payload:
            errors.append(f"Tool '{spec.name}' requires shop_id in payload")

        return errors
