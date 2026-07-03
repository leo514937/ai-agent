"""Shop name normalization helpers."""

from __future__ import annotations

import re
import unicodedata
from typing import Any


_CATEGORY_WORDS = (
    "火锅",
    "餐厅",
    "烤肉",
    "料理",
    "饭店",
    "饭馆",
    "酒楼",
    "小吃",
    "快餐",
    "奶茶",
    "咖啡",
    "甜品",
    "甜点",
    "面包",
    "烧烤",
    "面食",
    "饺子",
    "麻辣烫",
    "西餐",
    "中餐",
    "日料",
)

_BRAND_SUFFIXES = ("店", "门店", "分店", "餐厅", "饭店", "馆", "坊", "居", "楼", "园", "轩", "里", "吧")
_MALL_HINTS = ("购物中心", "商场", "广场", "天地", "mall", "center", "century", "时代")
_CITY_RE = re.compile(r"(?P<city>[\u4e00-\u9fff]{2,8}(?:市|区|县|镇|街道|路|街|巷|乡))")


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ("shop_name", "name", "alias", "canonical_name", "branch_name"):
            if key in value and value.get(key):
                return str(value.get(key, "") or "")
        return ""
    return str(value or "")


def _normalize_spacing(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _strip_outer_punctuation(text: str) -> str:
    return text.strip(" \t\r\n,，。;；:：!?！？~`'\"")


def _extract_parenthetical_branch(text: str) -> str:
    match = re.search(r"[（(]([^）)]+)[）)]", text)
    if not match:
        return ""
    return _strip_outer_punctuation(match.group(1))


def _extract_city(text: str, address: str = "") -> str:
    for source in (address, text):
        match = _CITY_RE.search(source or "")
        if match:
            return match.group("city")
    return ""


def _strip_category_words(text: str) -> str:
    result = str(text or "")
    for word in _CATEGORY_WORDS:
        result = result.replace(word, "")
    return result


def _strip_suffixes(text: str) -> str:
    result = str(text or "")
    changed = True
    while changed and result:
        changed = False
        for suffix in sorted(_BRAND_SUFFIXES, key=len, reverse=True):
            if result.endswith(suffix) and len(result) > len(suffix):
                result = result[: -len(suffix)]
                changed = True
    return result


def _extract_brand(core: str) -> str:
    base = _strip_suffixes(_strip_category_words(core))
    base = re.sub(r"[（(].*$", "", base)
    return _strip_outer_punctuation(base)


def _extract_branch_anchor(branch: str) -> str:
    value = _strip_outer_punctuation(_normalize_spacing(branch))
    for suffix in ("购物中心", "商场", "广场", "门店", "分店", "店", "餐厅", "饭店", "门口"):
        value = value.replace(suffix, "")
    return value or _strip_outer_punctuation(_normalize_spacing(branch))


def _extract_mall_short_name(branch_anchor: str) -> str:
    value = str(branch_anchor or "")
    for suffix in _MALL_HINTS:
        if suffix in value:
            value = value.replace(suffix, "")
    return value or branch_anchor


def normalize_shop_name_text(text: Any, *, address: str = "", category: str = "") -> dict[str, Any]:
    raw = _to_text(text)
    raw = unicodedata.normalize("NFKC", raw)
    raw = raw.replace("【", "(").replace("】", ")").replace("（", "(").replace("）", ")")
    raw = _strip_outer_punctuation(raw)
    compact = _normalize_spacing(raw)

    branch_text = _extract_parenthetical_branch(raw)
    branch_text = unicodedata.normalize("NFKC", branch_text).replace("（", "(").replace("）", ")")
    branch_text = _normalize_spacing(branch_text)
    branch_anchor = _extract_branch_anchor(branch_text)
    city = _extract_city(raw, address)
    category_text = _strip_outer_punctuation(_normalize_spacing(category))
    if not category_text:
        for word in _CATEGORY_WORDS:
            if word in raw:
                category_text = word
                break

    core = raw.split("(", 1)[0].split("（", 1)[0]
    brand = _extract_brand(core)
    if not brand and compact:
        brand = _strip_category_words(compact)
        brand = _strip_suffixes(brand)
        brand = _strip_outer_punctuation(brand)

    mall_short_name = _extract_mall_short_name(branch_anchor)
    normalized_text = compact
    if branch_text and branch_text not in normalized_text:
        normalized_text = f"{core}{branch_text}"
    normalized_text = _normalize_spacing(normalized_text)

    components = {
        "brand": brand,
        "city": city,
        "branch_anchor": branch_anchor,
        "mall_short_name": mall_short_name,
        "category": category_text,
        "branch_text": branch_text,
        "has_parenthetical_branch": bool(branch_text),
        "normalized_core": _normalize_spacing(core),
    }
    return {
        "original_text": raw,
        "normalized_text": normalized_text,
        "components": components,
    }


def normalize_shop_record(shop: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(shop, dict):
        shop = {}
    name = str(shop.get("shop_name", "") or shop.get("name", "") or "")
    address = str(shop.get("address", "") or "")
    category = str(shop.get("category", "") or shop.get("sub_category", "") or "")
    normalized = normalize_shop_name_text(name, address=address, category=category)
    normalized["components"]["shop_id"] = str(shop.get("shop_id", "") or shop.get("id", "") or "").strip()
    normalized["components"]["address"] = address
    normalized["components"]["category"] = category
    normalized["components"]["alias"] = shop.get("alias", "")
    normalized["components"]["aliases"] = list(shop.get("aliases", []) or [])
    return normalized

