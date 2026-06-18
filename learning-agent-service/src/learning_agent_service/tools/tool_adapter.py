"""
ToolAdapter — 将合法 tool call 适配为可执行命令。

负责：
- 接收 ToolCallValidator 校验通过的 ToolSelection
- 调用 ShopIdEnforcer 注入 resolved_shop_id
- 将适配后的命令传递给 ToolExecutor
"""

from __future__ import annotations

from typing import Any

from .models import ToolSelection
from .shop_id_enforcer import ShopIdEnforcer


class ToolAdapter:
    """将合法 tool call 适配为内部执行命令。"""

    def __init__(self, shop_id_enforcer: ShopIdEnforcer | None = None):
        self._shop_id_enforcer = shop_id_enforcer or ShopIdEnforcer()

    def adapt(
        self,
        tool_selection: ToolSelection,
        *,
        resolved_shop: Any = None,
        shop_id: int | None = None,
    ) -> ToolSelection:
        """适配 tool call，注入 resolved_shop_id。

        Args:
            tool_selection: ToolCallValidator 校验通过的 ToolSelection
            resolved_shop: BusinessObjectResolver 解析结果
            shop_id: 直接传入的 shop_id（可选）

        Returns:
            适配后的 ToolSelection（已注入 shop_id）
        """
        # 调用 ShopIdEnforcer 注入 resolved_shop_id
        adapted = self._shop_id_enforcer.enforce_shop_id(
            tool_selection,
            resolved_shop=resolved_shop,
            shop_id=shop_id,
        )
        return adapted
