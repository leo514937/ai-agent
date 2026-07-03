"""Generated alias helpers for shop resolution."""

from __future__ import annotations

from typing import Any

from .shop_name_normalizer import normalize_shop_record


def _compact(value: Any) -> str:
    return "".join(str(value or "").split()).strip()


def _combine(*parts: Any) -> str:
    text = "".join(_compact(part) for part in parts if _compact(part))
    return text


def build_generated_aliases(shop: dict[str, Any]) -> list[str]:
    normalized = normalize_shop_record(shop)
    components = normalized.get("components") or {}
    brand = _compact(components.get("brand"))
    city = _compact(components.get("city"))
    branch_anchor = _compact(components.get("branch_anchor"))
    mall_short_name = _compact(components.get("mall_short_name"))
    category = _compact(components.get("category"))
    canonical_name = _compact(normalized.get("normalized_text"))

    aliases = {
        canonical_name,
        _combine(brand, branch_anchor, "店"),
        _combine(brand, city, branch_anchor, "店"),
        _combine(brand, mall_short_name, "店"),
        _combine(brand, category, branch_anchor, "店"),
        _combine(branch_anchor, brand),
        _combine(city, branch_anchor, brand),
        _combine(branch_anchor, brand, "店"),
    }
    return [alias for alias in aliases if alias]

