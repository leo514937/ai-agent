"""
BusinessObjectResolver - 统一业务对象解析器

将所有单店工具从 shop_name 模糊匹配改为 shop_id 精确绑定。
解决 "海底捞水晶城店怎么样" 查询失败的根本原因。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..adapters.java_business import JavaBusinessClient
    from .schemas import ShopRecord


class ResolutionStrategy(Enum):
    """解析策略"""
    EXACT_ID = "exact_id"           # 直接使用 shop_id
    NAME_EXACT = "name_exact"       # 名称精确匹配
    NAME_FUZZY = "name_fuzzy"       # 名称模糊匹配
    BRAND_AREA = "brand_area"       # 品牌 + 区域匹配
    CLARIFICATION_NEEDED = "clarification_needed"  # 需要用户澄清
    CANDIDATE_LIST = "candidate_list"  # 返回候选列表（推荐意图）
    NOT_FOUND = "not_found"         # 未找到


@dataclass
class ResolvedShop:
    """解析后的店铺信息"""
    id: int | None
    name: str | None
    confidence: float
    source: str  # ResolutionStrategy value
    candidates: list[ShopRecord] | None = None


# 多候选时的置信度阈值
_HIGH_CONFIDENCE_THRESHOLD = 0.8
_MEDIUM_CONFIDENCE_THRESHOLD = 0.6


class BusinessObjectResolver:
    """
    统一业务对象解析器
    
    将所有单店工具从 shop_name 模糊匹配改为 shop_id 精确绑定。
    """

    def __init__(self, client: JavaBusinessClient, catalog: Any = None):
        self._client = client
        self._catalog = catalog

    def resolve(
        self,
        *,
        raw_query: str,
        shop_id: int | None,
        shop_name: str | None,
        brand: str | None,
        area: str | None,
        intent_type: str | None,
    ) -> ResolvedShop:
        """
        解析业务对象
        
        Args:
            raw_query: 原始查询
            shop_id: 已有的店铺 ID
            shop_name: 店铺名称
            brand: 品牌
            area: 区域
            intent_type: 意图类型 (recommendation, coupon_query, detail, etc.)
        
        Returns:
            ResolvedShop: 解析结果
        """
        # 1. shop_id 已有 → 直接用 get_shop_detail 验证，返回 EXACT_ID
        if shop_id is not None:
            return self._resolve_by_id(shop_id)

        # 2. shop_name 精确匹配 → 调用 search_shops_by_name
        if shop_name:
            result = self._resolve_by_name(shop_name, intent_type)
            if result.source != ResolutionStrategy.NOT_FOUND.value:
                return result

        # 3. brand + area → 调用 search_candidates
        if brand or area:
            result = self._resolve_by_brand_area(brand, area, intent_type)
            if result.source != ResolutionStrategy.NOT_FOUND.value:
                return result

        # 4. 全部失败 → NOT_FOUND
        return ResolvedShop(
            id=None,
            name=None,
            confidence=0.0,
            source=ResolutionStrategy.NOT_FOUND.value,
        )

    def _resolve_by_id(self, shop_id: int) -> ResolvedShop:
        """通过 shop_id 解析"""
        try:
            shop = self._client.get_shop_detail(shop_id)
            return ResolvedShop(
                id=shop.id,
                name=shop.name,
                confidence=1.0,
                source=ResolutionStrategy.EXACT_ID.value,
            )
        except Exception:
            return ResolvedShop(
                id=None,
                name=None,
                confidence=0.0,
                source=ResolutionStrategy.NOT_FOUND.value,
            )

    def _resolve_by_name(self, shop_name: str, intent_type: str | None) -> ResolvedShop:
        """通过 shop_name 解析"""
        candidates = self._client.search_shops_by_name(name=shop_name)
        
        if not candidates:
            return ResolvedShop(
                id=None,
                name=None,
                confidence=0.0,
                source=ResolutionStrategy.NOT_FOUND.value,
            )

        if len(candidates) == 1:
            # 单候选：直接返回，高置信度
            shop = candidates[0]
            confidence = self._calculate_name_confidence(shop_name, shop.name)
            return ResolvedShop(
                id=shop.id,
                name=shop.name,
                confidence=confidence,
                source=ResolutionStrategy.NAME_EXACT.value if confidence >= _HIGH_CONFIDENCE_THRESHOLD else ResolutionStrategy.NAME_FUZZY.value,
            )

        # 多候选：根据意图类型处理
        return self._handle_multiple_candidates(candidates, shop_name, intent_type)

    def _resolve_by_brand_area(
        self, brand: str | None, area: str | None, intent_type: str | None
    ) -> ResolvedShop:
        """通过 brand + area 解析"""
        # 构造查询字符串
        query_parts = []
        if brand:
            query_parts.append(brand)
        if area:
            query_parts.append(area)
        query = " ".join(query_parts)
        
        # 使用 search_candidates 需要 query 和 slots
        from .schemas import LocalLifeSlots
        slots = LocalLifeSlots(
            shop_query=query,
            category=brand,
        )
        
        candidates = self._client.search_candidates(
            query=query,
            slots=slots,
        )
        
        if not candidates:
            return ResolvedShop(
                id=None,
                name=None,
                confidence=0.0,
                source=ResolutionStrategy.NOT_FOUND.value,
            )

        if len(candidates) == 1:
            shop = candidates[0]
            return ResolvedShop(
                id=shop.id,
                name=shop.name,
                confidence=_MEDIUM_CONFIDENCE_THRESHOLD,
                source=ResolutionStrategy.BRAND_AREA.value,
            )

        return self._handle_multiple_candidates(candidates, f"{brand or ''} {area or ''}".strip(), intent_type)

    def _handle_multiple_candidates(
        self, candidates: list[ShopRecord], query: str, intent_type: str | None
    ) -> ResolvedShop:
        """处理多候选情况"""
        # 推荐意图 → 返回候选列表
        if intent_type in ("recommendation", "restaurant_recommendation"):
            return ResolvedShop(
                id=None,
                name=None,
                confidence=0.0,
                source=ResolutionStrategy.CANDIDATE_LIST.value,
                candidates=candidates,
            )

        # 其他意图（coupon_query, detail, etc.）→ 需要澄清
        return ResolvedShop(
            id=None,
            name=None,
            confidence=0.0,
            source=ResolutionStrategy.CLARIFICATION_NEEDED.value,
            candidates=candidates,
        )

    def _calculate_name_confidence(self, query: str, matched_name: str) -> float:
        """计算名称匹配置信度"""
        if not query or not matched_name:
            return 0.0
        
        query_lower = query.lower()
        name_lower = matched_name.lower()
        
        # 精确匹配
        if query_lower == name_lower:
            return 1.0
        
        # 包含匹配
        if query_lower in name_lower or name_lower in query_lower:
            return _HIGH_CONFIDENCE_THRESHOLD
        
        # 部分匹配
        common_chars = sum(1 for c in query_lower if c in name_lower)
        total_chars = max(len(query_lower), len(name_lower))
        
        if total_chars == 0:
            return 0.0
        
        return common_chars / total_chars


# 类型导入
from typing import Any
