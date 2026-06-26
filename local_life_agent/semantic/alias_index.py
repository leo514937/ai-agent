"""Dynamic alias hints derived from MySQL shop names."""

from __future__ import annotations

from functools import lru_cache

from ..input.normalizer import normalize_text
from ..tools.db_client import query_all_shops

_COMMON_SUFFIXES = (
    "火锅",
    "火锅店",
    "餐厅",
    "饭店",
    "咖啡",
    "咖啡店",
    "茶餐厅",
    "烧烤",
    "烤肉",
    "快餐",
    "面馆",
    "饺子馆",
    "麻辣烫",
    "炸酱面",
    "奶茶",
    "甜品",
    "KTV",
    "ktv",
)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _split_aliases(name: str) -> list[str]:
    cleaned = normalize_text(name).strip()
    if not cleaned:
        return []
    aliases = [cleaned]
    for open_ch, close_ch in (("(", ")"), ("（", "）")):
        if open_ch in cleaned and close_ch in cleaned:
            prefix, suffix = cleaned.split(open_ch, 1)
            suffix = suffix.rsplit(close_ch, 1)[0].strip()
            prefix = prefix.strip()
            if prefix:
                aliases.append(prefix)
            if suffix:
                aliases.append(suffix)
    aliases.extend([part.strip() for part in cleaned.replace("·", " ").replace("-", " ").replace("/", " ").split() if part.strip()])
    for candidate in list(aliases):
        for suffix in _COMMON_SUFFIXES:
            if candidate.endswith(suffix) and len(candidate) > len(suffix) + 1:
                aliases.append(candidate[: -len(suffix)].strip())
    return _dedupe(aliases)


@lru_cache(maxsize=1)
def build_alias_index() -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for shop in query_all_shops():
        canonical = normalize_text(shop.get("shop_name", "")).strip()
        if not canonical:
            continue
        aliases = _split_aliases(canonical)
        alias_field = normalize_text(shop.get("alias", "")).strip()
        if alias_field:
            aliases.append(alias_field)
        for alias_item in shop.get("aliases", []) or []:
            aliases.append(normalize_text(alias_item).strip())
        index[canonical] = _dedupe(aliases)
    return index


def iter_alias_tokens() -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    for canonical, aliases in build_alias_index().items():
        for alias in aliases:
            tokens.append((alias, canonical))
    return tokens
