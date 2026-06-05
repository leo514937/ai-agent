from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from learning_agent_service.domain.utils import clean_text as _clean_text

_OPEN_PATTERNS = (
    (re.compile(r"\bopen\b", re.IGNORECASE), "营业中"),
    (re.compile(r"\bclosed\b", re.IGNORECASE), "未营业"),
)

_INTERNAL_CITATION_PATTERNS = (
    re.compile(r"\s*\[(?:local-life|chunk)[^\]]+\]"),
    re.compile(r"\s*\[[^\]]*(?:local-life:|chunk-\d+)[^\]]*\]"),
)


def _shop_lookup_text(shop_lookup: Mapping[int, str] | None, shop_id: int | str | None) -> str | None:
    if shop_lookup is None or shop_id in (None, ""):
        return None
    try:
        return shop_lookup.get(int(shop_id))
    except Exception:
        return None


def sanitize_local_life_text(
    text: Any,
    *,
    shop_lookup: Mapping[int, str] | None = None,
    fallback_shop_name: str = "这家店",
) -> Any:
    if not isinstance(text, str):
        return text
    result = text
    result = result.replace("0.49000000000000005", "0.5")
    for pattern, replacement in _OPEN_PATTERNS:
        result = pattern.sub(replacement, result)
    for pattern in _INTERNAL_CITATION_PATTERNS:
        result = pattern.sub("", result)
    result = re.sub(r"\s{2,}", " ", result)
    result = re.sub(r"[ \t]+\n", "\n", result)
    result = re.sub(r"\bshop[:_ ]?(\d+)\b", lambda match: _shop_lookup_text(shop_lookup, match.group(1)) or fallback_shop_name, result, flags=re.IGNORECASE)
    result = re.sub(r"\bshop_id\s*=\s*(\d+)\b", lambda match: _shop_lookup_text(shop_lookup, match.group(1)) or fallback_shop_name, result, flags=re.IGNORECASE)
    result = re.sub(r"\bshop_id[:：]\s*(\d+)\b", lambda match: _shop_lookup_text(shop_lookup, match.group(1)) or fallback_shop_name, result, flags=re.IGNORECASE)
    return result.strip()


def sanitize_local_life_output(
    value: Any,
    *,
    shop_lookup: Mapping[int, str] | None = None,
    fallback_shop_name: str = "这家店",
) -> Any:
    if isinstance(value, str):
        return sanitize_local_life_text(value, shop_lookup=shop_lookup, fallback_shop_name=fallback_shop_name)
    if isinstance(value, Mapping):
        return {
            key: sanitize_local_life_output(val, shop_lookup=shop_lookup, fallback_shop_name=fallback_shop_name)
            for key, val in value.items()
        }
    if isinstance(value, list):
        return [sanitize_local_life_output(item, shop_lookup=shop_lookup, fallback_shop_name=fallback_shop_name) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_local_life_output(item, shop_lookup=shop_lookup, fallback_shop_name=fallback_shop_name) for item in value)
    if hasattr(value, "model_dump") and hasattr(value, "model_copy"):
        dumped = value.model_dump(mode="json")
        sanitized = sanitize_local_life_output(dumped, shop_lookup=shop_lookup, fallback_shop_name=fallback_shop_name)
        try:
            return value.model_copy(update=sanitized)
        except Exception:
            return sanitized
    return value
