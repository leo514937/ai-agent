from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from .core import *# noqa: F401,F403,F405

def _resolve_shop_detail(business_client: JavaBusinessClient, shop: ShopRecord) -> ShopRecord | None:
    if shop is None:
        return None
    try:
        detail = business_client.get_shop_detail(shop.id)
    except Exception:
        detail = None
    if detail is None:
        return shop
    merged = shop.model_copy()
    for field_name, value in detail.model_dump(mode="python").items():
        if value not in (None, "", [], {}):
            setattr(merged, field_name, value)
    return merged


def _safe_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return list(value)


def _dedupe_chunks(chunks: Iterable[KnowledgeChunk]) -> tuple[KnowledgeChunk, ...]:
    seen: dict[str, KnowledgeChunk] = {}
    for chunk in chunks:
        seen[chunk.chunk_id] = chunk
    return tuple(sorted(seen.values(), key=lambda item: (item.source_type or "", item.document_id, item.chunk_id)))


def _summarize_text(text: str, limit: int = 220) -> str:
    collapsed = " ".join(part.strip() for part in text.splitlines() if part.strip())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 3].rstrip() + "..."


def _infer_city(address: str | None) -> str | None:
    text = str(address or "")
    for city in _CITY_HINTS:
        if city in text:
            return city
    match = re.match(r"^([\u4e00-\u9fff]{2,3})", text.strip())
    if match:
        return match.group(1)
    return None


def _derive_review_trend(
    shop: ShopRecord,
    blogs: Sequence[BlogRecord],
    vouchers: Sequence[VoucherRecord],
) -> str:
    fragments = []
    if shop.review_summary:
        fragments.append(shop.review_summary)
    for blog in blogs[:3]:
        if blog.title:
            fragments.append(blog.title)
        if blog.content:
            fragments.append(blog.content)
    if vouchers:
        fragments.append("有优惠券可参考")
    text = " ".join(fragments)
    if any(keyword in text for keyword in ("安静", "安静", "静")):
        return "评论多次提到环境安静"
    if any(keyword in text for keyword in ("家庭", "爸妈", "长辈", "老人")):
        return "适合家庭聚餐"
    if any(keyword in text for keyword in ("排队", "热闹")):
        return "人气较高，可能需要排队"
    return "口碑信息偏正向，可结合具体需求再判断"


def _guide_scene_hints(shops: Sequence[ShopRecord]) -> list[str]:
    hints: list[str] = []
    for shop in shops:
        if shop.family_friendly and "家庭聚餐" not in hints:
            hints.append("家庭聚餐")
        if shop.elder_friendly and "带长辈" not in hints:
            hints.append("带长辈")
        if shop.parking and "停车方便" not in hints:
            hints.append("停车方便")
        if shop.quiet_score >= 0.8 and "环境安静" not in hints:
            hints.append("环境安静")
    return hints


def _chunk_tags(
    shop: ShopRecord,
    shop_type: ShopTypeRecord,
    city: str | None,
    *,
    source_type: str,
    extra: Sequence[str] = (),
) -> tuple[str, ...]:
    tags = [
        source_type,
        shop_type.name,
        shop.area or "",
        city or "",
        shop.name or "",
    ]
    tags.extend(extra)
    return tuple(dict.fromkeys(tag for tag in tags if tag))


def _format_price(value: float | None) -> str:
    if value is None:
        return "未知"
    if float(value).is_integer():
        return str(int(value))
    return f"{float(value):.2f}".rstrip("0").rstrip(".")


def _format_score(value: float | None) -> str:
    if value is None:
        return "0.0"
    score = float(value)
    if score > 5.0:
        score = score / 10.0
    return f"{score:.1f}"


def _format_int(value: int | None) -> str:
    return "0" if value is None else str(int(value))


def _stable_key(*parts: Any) -> str:
    raw = "|".join(str(part) for part in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

__all__ = [name for name in globals() if not name.startswith("__")]
