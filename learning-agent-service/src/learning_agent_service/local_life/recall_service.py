"""多策略召回服务：基于实体分解结果，按优先级链式召回候选店铺。

召回策略链：
1. exact   — 用户查询原串 LIKE 匹配
2. brand_area — brand + area 组合查询
3. brand_only — 仅 brand 查询
4. fuzzy   — brand 关键词模糊匹配
5. catalog — 本地 catalog 兜底
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from .entity_decomposer import ShopEntity

if TYPE_CHECKING:
    from ..adapters.java_business import JavaBusinessClient
    from .schemas import ShopRecord

logger = logging.getLogger(__name__)


@dataclass
class RecallResult:
    """一次召回的结果。"""
    candidates: list  # list[ShopRecord]
    strategy: str  # 命中的策略名
    entity: ShopEntity | None = None


def _search_exact(client: "JavaBusinessClient", entity: ShopEntity) -> list["ShopRecord"]:
    """策略1：原串 LIKE 匹配。"""
    query = entity.raw_query or entity.full_query
    if not query:
        return []
    return client.search_shops_by_name(name=query)


def _search_brand_area(client: "JavaBusinessClient", entity: ShopEntity) -> list["ShopRecord"]:
    """策略2：brand + area 组合查询。"""
    if not entity.brand:
        return []
    name = entity.brand
    area = entity.area
    params: dict = {"name": name, "current": 1}
    if area:
        params["area"] = area
    from ..adapters.java_business import _unwrap_result, _coerce_list, _coerce_shop
    from typing import cast
    payload = client._request_json("GET", "/shop/search", params=params)
    raw = [_coerce_shop(item) for item in _coerce_list(_unwrap_result(payload))]
    return cast(list, [item for item in raw if item is not None])


def _search_brand_only(client: "JavaBusinessClient", entity: ShopEntity) -> list["ShopRecord"]:
    """策略3：仅 brand 查询。"""
    if not entity.brand:
        return []
    return client.search_shops_by_name(name=entity.brand)


def _search_fuzzy(client: "JavaBusinessClient", entity: ShopEntity) -> list["ShopRecord"]:
    """策略4：brand 关键词模糊匹配（复用 search_shops_by_name 的内置 fallback）。"""
    if not entity.brand:
        return []
    # search_shops_by_name 内部已有 brand fallback 逻辑
    return client.search_shops_by_name(name=entity.brand)


def _search_catalog(client: "JavaBusinessClient", entity: ShopEntity) -> list["ShopRecord"]:
    """策略5：本地 catalog 兜底。"""
    from .schemas import LocalLifeSlots
    slots = LocalLifeSlots(shop_query=entity.full_query or entity.raw_query)
    return client.fallback_catalog.search_shops(
        query=entity.full_query or entity.raw_query,
        slots=slots,
        limit=5,
    )


# 策略链：名称 → (函数, 描述)
_STRATEGY_CHAIN: list[tuple[str, Any, str]] = [
    ("exact", _search_exact, "原串 LIKE 匹配"),
    ("brand_area", _search_brand_area, "brand + area 组合"),
    ("brand_only", _search_brand_only, "仅 brand 查询"),
    ("fuzzy", _search_fuzzy, "brand 关键词模糊"),
    ("catalog", _search_catalog, "本地 catalog 兜底"),
]


def recall_candidates(
    client: "JavaBusinessClient",
    entity: ShopEntity,
    *,
    strategies: list[str] | None = None,
) -> RecallResult:
    """按优先级链式召回候选店铺。

    Args:
        client: Java 业务客户端
        entity: 实体分解结果
        strategies: 自定义策略顺序（默认使用完整链）

    Returns:
        RecallResult 包含候选列表和命中的策略名
    """
    chain = _STRATEGY_CHAIN
    if strategies:
        strategy_map = {name: (name, fn, desc) for name, fn, desc in _STRATEGY_CHAIN}
        chain = [strategy_map[s] for s in strategies if s in strategy_map]

    for name, fn, desc in chain:
        try:
            candidates = fn(client, entity)
            if candidates:
                logger.info(
                    "recall hit: strategy=%s desc=%s count=%d brand=%s area=%s",
                    name, desc, len(candidates), entity.brand, entity.area,
                )
                return RecallResult(
                    candidates=candidates,
                    strategy=name,
                    entity=entity,
                )
        except Exception as exc:
            logger.warning("recall strategy %s failed: %s", name, exc)
            continue

    return RecallResult(candidates=[], strategy="none", entity=entity)
