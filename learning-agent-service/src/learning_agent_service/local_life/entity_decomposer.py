"""实体分解模块：从自然语言查询中提取 brand/area/category 结构化实体。

这是实体解析链路的第一层——把不透明的 shop_name 字符串拆解为结构化字段，
供后续多策略召回使用。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .schemas import LocalLifeSlots

# ── Hardcoded fallback lists (source: java_business.py:479/486) ──────────────
# 当 JavaBusinessClient 不可用时作为兜底。
_FALLBACK_BRANDS: list[str] = [
    "海底捞", "蔡馬洪涛", "新白鹿", "Mamala", "幸福里",
    "炉鱼", "浅草屋", "羊老三", "开乐迪", "INLOVE", "星聚会",
]

_FALLBACK_AREAS: list[str] = [
    "水晶城", "运河上街", "丝联", "万达", "乐堤港",
    "北城天地", "城西", "武林广场",
]

# ── Category keywords ───────────────────────────────────────────────────────
_CATEGORY_KEYWORDS: list[str] = [
    "火锅", "日料", "西餐", "烧烤", "烤肉", "自助", "甜品",
    "咖啡", "茶饮", "酒吧", "中餐", "家常菜", "川菜", "湘菜",
    "粤菜", "杭帮菜", "泰国菜", "越南菜", "韩国料理", "日本料理",
    "意大利菜", "法国菜", "披萨", "汉堡", "面馆", "粉店",
]

# ── Suffixes to strip from entity name ──────────────────────────────────────
_ENTITY_SUFFIXES: tuple[str, ...] = (
    "现在营业吗", "现在开门营业吗", "开门营业吗", "现在有券吗",
    "有团购吗", "团购吗", "有什么优惠", "优惠吗", "现在能不能订",
    "现在能不能约", "现在开吗", "适合带爸妈吗", "适合家庭聚餐吗",
    "怎么样呢", "有券吗呢", "营业吗呢", "怎么样", "有券吗", "有券",
    "有几张券", "有代金券吗", "有折扣吗", "有套餐吗", "有可用优惠券吗",
    "适合约会吗", "适合吗", "好不好", "值不值得", "值不值", "营业吗",
    "呢", "店呢", "家呢", "商家呢", "哪个呢", "有啥特色", "有什么特色",
    "特色是什么", "在哪里", "在哪", "店", "餐厅", "火锅",
)


@dataclass
class ShopEntity:
    """从自然语言中提取的结构化店铺实体。"""
    brand: str | None = None
    area: str | None = None
    category: str | None = None
    city: str | None = None
    full_query: str = ""
    raw_query: str = ""


def _strip_suffixes(text: str) -> str:
    """递归去除查询中的后缀（如 '怎么样' '有券吗'）。"""
    cleaned = text.strip().rstrip("？?。.!！")
    changed = True
    while changed:
        changed = False
        for suffix in sorted(_ENTITY_SUFFIXES, key=len, reverse=True):
            if cleaned.endswith(suffix):
                cleaned = cleaned[: -len(suffix)].strip(" 的,，。！？!?")
                changed = True
                break
    return cleaned


def _extract_brand(query: str, known_brands: list[str]) -> str | None:
    """从查询中匹配已知品牌名（最长匹配优先）。"""
    query_lower = query.lower()
    # 按长度降序，优先匹配长品牌名
    for brand in sorted(known_brands, key=len, reverse=True):
        if brand.lower() in query_lower:
            return brand
    return None


def _extract_area(query: str, known_areas: list[str]) -> str | None:
    """从查询中匹配已知区域名（最长匹配优先）。"""
    query_lower = query.lower()
    for area in sorted(known_areas, key=len, reverse=True):
        if area.lower() in query_lower:
            return area
    return None


def _extract_category(query: str) -> str | None:
    """从查询中提取分类关键词。"""
    query_lower = query.lower()
    for cat in _CATEGORY_KEYWORDS:
        if cat in query_lower:
            return cat
    return None


def _extract_brand_from_full_name(name: str, known_brands: list[str]) -> str | None:
    """从全称（如 '海底捞火锅(水晶城购物中心店）'）中提取品牌。

    策略：去掉括号内容后，再匹配品牌列表。
    """
    # 去掉括号部分
    bracket_pattern = re.compile(r"[（(][^）)]*[）)]")
    without_brackets = bracket_pattern.sub("", name).strip()
    if without_brackets:
        brand = _extract_brand(without_brackets, known_brands)
        if brand:
            return brand
    # Fallback: 直接匹配原始 name
    return _extract_brand(name, known_brands)


def _extract_area_from_full_name(name: str, known_areas: list[str]) -> str | None:
    """从全称（如 '海底捞火锅(水晶城购物中心店）'）中提取区域。

    策略：从括号内容中提取区域。
    """
    # 提取括号内容
    bracket_match = re.search(r"[（(]([^）)]*)[）)]", name)
    if bracket_match:
        bracket_content = bracket_match.group(1)
        area = _extract_area(bracket_content, known_areas)
        if area:
            return area
    # Fallback: 直接匹配原始 name
    return _extract_area(name, known_areas)


def decompose_shop_query(
    raw_query: str,
    slots: LocalLifeSlots | None = None,
    *,
    known_brands: list[str] | None = None,
    known_areas: list[str] | None = None,
) -> ShopEntity:
    """从自然语言查询中提取结构化店铺实体。

    Args:
        raw_query: 用户原始查询，如 "海底捞水晶城店怎么样"
        slots: 已提取的 slot 信息（可选），用于获取 city 等
        known_brands: 已知品牌列表（可选），None 时使用 hardcoded fallback
        known_areas: 已知区域列表（可选），None 时使用 hardcoded fallback

    Returns:
        ShopEntity 包含 brand/area/category/city 等结构化字段
    """
    brands = known_brands if known_brands is not None else _FALLBACK_BRANDS
    areas = known_areas if known_areas is not None else _FALLBACK_AREAS
    city = getattr(slots, "city", None) if slots is not None else None

    # category 在原始查询上提取（后缀剥离会吃掉 "火锅" 等分类词）
    category = _extract_category(raw_query or "")

    # 清洗查询
    cleaned = _strip_suffixes(raw_query or "")

    # 判断是否包含括号（全称格式）
    has_brackets = bool(re.search(r"[（(][^）)]*[）)]", cleaned))

    if has_brackets:
        brand = _extract_brand_from_full_name(cleaned, brands)
        area = _extract_area_from_full_name(cleaned, areas)
    else:
        brand = _extract_brand(cleaned, brands)
        area = _extract_area(cleaned, areas)

    return ShopEntity(
        brand=brand,
        area=area,
        category=category,
        city=city,
        full_query=raw_query or "",
        raw_query=cleaned,
    )
