"""
ShopIdEnforcer — 确保 ToolCall 使用 resolved_shop_id。

由 ToolAdapter 内部调用，负责为单店工具注入 resolved_shop_id。
"""

from __future__ import annotations

from typing import Any

from .models import ToolSelection


class ShopIdMissingError(RuntimeError):
    """缺少 resolved_shop_id 时的异常。"""


class ShopIdEnforcer:
    """确保 ToolCall 使用 resolved_shop_id，不做店铺模糊解析。"""

    # 需要 shop_id 的单店工具清单
    SINGLE_SHOP_TOOLS = frozenset({
        "get_coupon_list",
        "check_open_status",
        "get_distance_eta",
        "get_shop_detail",
        "create_booking",
        "restaurant_booking",
        "local_life_booking",
        "book_restaurant",
        "create_order",
        "get_blog_list",
    })

    def enforce_shop_id(
        self,
        tool_selection: ToolSelection,
        resolved_shop: Any = None,
        *,
        shop_id: int | None = None,
    ) -> ToolSelection:
        """强制 ToolCall 使用 resolved_shop_id。

        Args:
            tool_selection: 原始 ToolSelection
            resolved_shop: BusinessObjectResolver 解析结果（可选）
            shop_id: 直接传入的 shop_id（可选，优先级高于 resolved_shop）

        Returns:
            已注入 shop_id 的 ToolSelection

        Raises:
            ShopIdMissingError: 当需要 shop_id 但未提供时
        """
        # 1. 检查是否为单店工具
        if not self._is_single_shop_tool(tool_selection.tool_name):
            return tool_selection

        # 2. 获取最终 shop_id
        final_shop_id: int | None = shop_id
        if final_shop_id is None and resolved_shop is not None:
            final_shop_id = getattr(resolved_shop, "id", None)

        if final_shop_id is None:
            raise ShopIdMissingError(
                f"Tool {tool_selection.tool_name} requires resolved_shop_id"
            )

        # 3. 注入 shop_id 到 input_payload
        input_payload = dict(tool_selection.input_payload)
        input_payload["shop_id"] = final_shop_id

        # 4. 保留 shop_name 作为兼容输入，但不允许用 shop_name 反查 shop_id
        if resolved_shop is not None:
            shop_name = getattr(resolved_shop, "name", None)
            if shop_name:
                input_payload.setdefault("shop_name", shop_name)

        return ToolSelection(
            tool_name=tool_selection.tool_name,
            input_payload=input_payload,
            reason=tool_selection.reason,
            degrade_to=tool_selection.degrade_to,
            timeout_ms=tool_selection.timeout_ms,
            approval_required=tool_selection.approval_required,
            approval_status=tool_selection.approval_status,
            approval_request=tool_selection.approval_request,
        )

    def _is_single_shop_tool(self, tool_name: str) -> bool:
        """判断是否为单店工具。"""
        return tool_name in self.SINGLE_SHOP_TOOLS
