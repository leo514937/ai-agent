"""
shop_id 过滤函数

实现按 shop_id 过滤 RAG 检索结果的功能。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..local_life.schemas import ShopRecord


def filter_by_shop_id(
    items: list[dict[str, Any]],
    shop_id: int | None,
) -> list[dict[str, Any]]:
    """
    按 shop_id 过滤 RAG 检索结果
    
    Args:
        items: RAG 检索结果列表
        shop_id: 店铺 ID，None 表示不过滤
    
    Returns:
        过滤后的结果列表
    """
    if shop_id is None:
        return items
    
    filtered = []
    for item in items:
        item_shop_id = item.get("shop_id") or item.get("shopId")
        if item_shop_id is not None and int(item_shop_id) == shop_id:
            filtered.append(item)
    
    return filtered


def extract_shop_id_from_tool_result(tool_result: dict[str, Any]) -> int | None:
    """从 tool_result 中提取 shop_id"""
    # 从 shop 字段提取
    shop = tool_result.get("shop")
    if shop and isinstance(shop, dict):
        shop_id = shop.get("id") or shop.get("shop_id")
        if shop_id:
            return int(shop_id)
    
    # 从顶层字段提取
    shop_id = tool_result.get("shop_id") or tool_result.get("shopId")
    if shop_id:
        return int(shop_id)
    
    return None


def extract_shop_id_from_rag_result(rag_result: dict[str, Any]) -> int | None:
    """从 rag_result 中提取 shop_id"""
    # 从 evidence items 提取
    evidence_items = rag_result.get("evidence_items", [])
    for item in evidence_items:
        shop_id = item.get("shop_id")
        if shop_id:
            return int(shop_id)
    
    return None
