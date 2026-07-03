from __future__ import annotations

import re

_UNVERIFIED_CLAIM_PATTERNS = (
    r"有券",
    r"优惠券",
    r"营业中",
    r"正在营业",
    r"已打烊",
    r"已关门",
    r"更好",
    r"最(?:高|低|近|远|值得)",
    r"第一",
    r"第二",
    r"第三",
    r"\b\d+(?:\.\d+)?\s*(?:公里|km|元|分钟)\b",
)
_UNVERIFIED_CLAIM_RE = re.compile("|".join(_UNVERIFIED_CLAIM_PATTERNS))


def contains_unverified_claim(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    return bool(_UNVERIFIED_CLAIM_RE.search(normalized))


def can_emit_preview(text: str, *, verified: bool = False) -> bool:
    if verified:
        return bool(str(text or "").strip())
    return bool(str(text or "").strip()) and not contains_unverified_claim(text)


def sanitize_preview_text(text: str, *, verified: bool = False) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    if can_emit_preview(normalized, verified=verified):
        return normalized
    if verified:
        return normalized
    return ""
