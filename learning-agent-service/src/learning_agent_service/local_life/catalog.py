from __future__ import annotations

import re
from math import asin, cos, radians, sin, sqrt
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .schemas import (
    BlogRecord,
    EvidenceClaim,
    LocalLifeSlots,
    PriceNorm,
    ShopRecord,
    ShopTypeRecord,
    VoucherRecord,
)


def _tokenize(text: str) -> set[str]:
    if not text:
        return set()
    tokens: set[str] = set()
    buffer = []
    for char in text.lower():
        if char.isalnum() or "\u4e00" <= char <= "\u9fff":
            buffer.append(char)
        else:
            if buffer:
                tokens.add("".join(buffer))
                buffer.clear()
    if buffer:
        tokens.add("".join(buffer))
    return {token for token in tokens if token}


_GENERIC_CATEGORIES = {"餐厅", "饭店"}
_CATEGORY_ALIASES: dict[str, set[str]] = {
    "家常菜": {"家常菜", "私房菜"},
    "火锅": {"火锅"},
    "粤菜": {"粤菜"},
    "川菜": {"川菜"},
    "烧烤": {"烧烤", "烤肉"},
    "日料": {"日料"},
}

_QUERY_PHRASES = (
    "附近",
    "更近",
    "近一点",
    "离我近",
    "安静",
    "别太吵",
    "有停车",
    "能停车",
    "停车",
    "适合爸妈",
    "带爸妈",
    "长辈",
    "父母",
    "老人",
    "家庭聚餐",
    "聚餐",
    "约会",
    "团建",
    "包间",
    "清淡",
    "少油",
    "少辣",
    "不要网红店",
    "不要排队",
    "少排队",
    "长队",
    "领券",
    "优惠",
    "订座",
    "导航",
    "对比",
)

_CITY_NAMES = (
    "北京",
    "上海",
    "广州",
    "深圳",
    "杭州",
    "成都",
    "重庆",
    "南京",
    "苏州",
    "武汉",
    "西安",
    "天津",
    "长沙",
    "厦门",
    "青岛",
    "宁波",
    "郑州",
)


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6371.0
    d_lat = radians(lat2 - lat1)
    d_lng = radians(lng2 - lng1)
    a = sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lng / 2) ** 2
    return 2 * radius * asin(sqrt(max(0.0, min(1.0, a))))


def _shop_search_blob(shop: ShopRecord) -> str:
    parts = [
        shop.name or "",
        shop.type_name or "",
        shop.area or "",
        shop.address or "",
        " ".join(shop.tags),
        shop.review_summary or "",
        " ".join(shop.evidence_texts),
    ]
    return " ".join(part for part in parts if part).lower()


def _query_terms(text: str) -> list[str]:
    normalized = (text or "").lower()
    terms: list[str] = []
    for city in _CITY_NAMES:
        if city.lower() in normalized:
            terms.append(city)
    for phrase in _QUERY_PHRASES:
        if phrase.lower() in normalized:
            terms.append(phrase)
    for category, aliases in _CATEGORY_ALIASES.items():
        if any(alias.lower() in normalized for alias in aliases):
            terms.append(category)
            terms.extend(alias for alias in aliases if alias.lower() in normalized)
    price_match = re.search(r"人均(\d{2,4})(?:左右|上下|附近)?", normalized)
    if price_match:
        terms.append(f"人均{price_match.group(1)}")
    range_match = re.search(r"(\d{2,4})[-~到](\d{2,4})", normalized)
    if range_match:
        terms.append(f"人均{range_match.group(1)}-{range_match.group(2)}")
    return list(dict.fromkeys(term for term in terms if term))


def _category_matches(category: str, shop: ShopRecord) -> bool:
    if not category:
        return False
    if category in _GENERIC_CATEGORIES:
        return True
    blob = _shop_search_blob(shop)
    aliases = _CATEGORY_ALIASES.get(category, {category})
    return any(alias.lower() in blob for alias in aliases)


def _price_alignment_score(avg_price: float, price: PriceNorm) -> float:
    score = 0.0
    min_price = price.per_person_min
    max_price = price.per_person_max
    target = price.target
    if min_price is not None and max_price is not None:
        if min_price <= avg_price <= max_price:
            score += 3.0
        elif avg_price < min_price:
            score += max(0.0, 1.5 - (float(min_price) - avg_price) / 50.0)
        else:
            score += max(0.0, 1.5 - (avg_price - float(max_price)) / 50.0)
    elif target is not None:
        diff = abs(avg_price - float(target))
        score += max(0.0, 3.0 - diff / 50.0)
    elif max_price is not None:
        if avg_price <= float(max_price):
            score += 2.0
        else:
            score += max(0.0, 1.5 - (avg_price - float(max_price)) / 100.0)
    elif min_price is not None:
        if avg_price >= float(min_price):
            score += 2.0
        else:
            score += max(0.0, 1.5 - (float(min_price) - avg_price) / 100.0)
    else:
        score += 0.5
    return score


DEFAULT_SHOP_TYPES: list[ShopTypeRecord] = [
    ShopTypeRecord(id=1, name="家常菜", icon="🍚", sort=1),
    ShopTypeRecord(id=2, name="火锅", icon="🍲", sort=2),
    ShopTypeRecord(id=3, name="粤菜", icon="🥢", sort=3),
    ShopTypeRecord(id=4, name="烧烤", icon="🍢", sort=4),
    ShopTypeRecord(id=5, name="日料", icon="🍣", sort=5),
]


DEFAULT_SHOPS: list[ShopRecord] = [
    ShopRecord(
        id=1001,
        name="某某家常菜",
        type_id=1,
        type_name="家常菜",
        area="望京",
        address="北京市朝阳区望京街道1号",
        x=116.48,
        y=39.99,
        avg_price=145,
        sold=860,
        comments=1820,
        score=4.8,
        open_hours="11:00-21:30",
        image="https://example.com/shop-1001.jpg",
        distance_km=1.2,
        parking=True,
        quiet_score=0.92,
        family_friendly=True,
        elder_friendly=True,
        tags=["quiet", "family_dinner", "parking", "elder_friendly"],
        review_summary="评论多次提到环境安静，适合带爸妈和家庭聚餐。",
        evidence_texts=["环境比较安静", "有停车位", "服务员对老人很照顾"],
    ),
    ShopRecord(
        id=1002,
        name="京味粤菜馆",
        type_id=3,
        type_name="粤菜",
        area="国贸",
        address="北京市朝阳区建国路88号",
        x=116.47,
        y=39.91,
        avg_price=168,
        sold=520,
        comments=960,
        score=4.7,
        open_hours="10:30-22:00",
        image="https://example.com/shop-1002.jpg",
        distance_km=2.0,
        parking=True,
        quiet_score=0.88,
        family_friendly=True,
        elder_friendly=True,
        tags=["quiet", "private_room", "parking", "light_taste"],
        review_summary="有包间，口味清淡，适合家庭聚餐。",
        evidence_texts=["包间环境安静", "菜品偏清淡", "有停车信息"],
    ),
    ShopRecord(
        id=1003,
        name="辣尚火锅",
        type_id=2,
        type_name="火锅",
        area="三里屯",
        address="北京市朝阳区工体北路",
        x=116.46,
        y=39.94,
        avg_price=118,
        sold=1450,
        comments=2500,
        score=4.6,
        open_hours="10:00-02:00",
        image="https://example.com/shop-1003.jpg",
        distance_km=1.5,
        parking=False,
        quiet_score=0.35,
        family_friendly=False,
        elder_friendly=False,
        tags=["busy", "trendy", "queue_risk"],
        review_summary="氛围热闹，排队多，更适合年轻人聚餐。",
        evidence_texts=["排队较多", "声音比较大", "更热闹"],
    ),
    ShopRecord(
        id=1004,
        name="湖畔私房菜",
        type_id=1,
        type_name="家常菜",
        area="朝阳公园",
        address="北京市朝阳区朝阳公园路",
        x=116.49,
        y=39.93,
        avg_price=180,
        sold=430,
        comments=640,
        score=4.9,
        open_hours="11:00-22:00",
        image="https://example.com/shop-1004.jpg",
        distance_km=3.2,
        parking=True,
        quiet_score=0.95,
        family_friendly=True,
        elder_friendly=True,
        tags=["quiet", "private_room", "parking", "elder_friendly"],
        review_summary="环境安静，适合长辈聚餐。",
        evidence_texts=["环境很安静", "有包间", "适合长辈"],
    ),
    ShopRecord(
        id=1005,
        name="老北京菜馆",
        type_id=1,
        type_name="家常菜",
        area="东直门",
        address="北京市东城区东直门外大街",
        x=116.43,
        y=39.95,
        avg_price=132,
        sold=720,
        comments=1100,
        score=4.5,
        open_hours="10:00-21:00",
        image="https://example.com/shop-1005.jpg",
        distance_km=0.8,
        parking=True,
        quiet_score=0.78,
        family_friendly=True,
        elder_friendly=True,
        tags=["parking", "family_dinner", "value_for_money"],
        review_summary="人均亲民，离地铁口近，适合带家里人吃饭。",
        evidence_texts=["价格亲民", "有停车位", "适合家庭聚餐"],
    ),
]


DEFAULT_VOUCHERS: list[VoucherRecord] = [
    VoucherRecord(
        id=2001,
        shop_id=1001,
        shop_name="某某家常菜",
        title="家庭聚餐券",
        sub_title="150减30，午晚餐可用",
        rules="满150元可用",
        pay_value=120,
        actual_value=150,
        stock=36,
        begin_time="2026-05-01 00:00:00",
        end_time="2026-06-30 23:59:59",
    ),
    VoucherRecord(
        id=2002,
        shop_id=1002,
        shop_name="京味粤菜馆",
        title="清淡双人券",
        sub_title="适合家庭聚餐",
        rules="仅限堂食",
        pay_value=148,
        actual_value=180,
        stock=18,
        begin_time="2026-05-01 00:00:00",
        end_time="2026-06-30 23:59:59",
    ),
    VoucherRecord(
        id=2003,
        shop_id=1005,
        shop_name="老北京菜馆",
        title="午市特惠券",
        sub_title="人均更友好",
        rules="工作日可用",
        pay_value=98,
        actual_value=120,
        stock=48,
        begin_time="2026-05-01 00:00:00",
        end_time="2026-06-30 23:59:59",
    ),
]


DEFAULT_BLOGS: list[BlogRecord] = [
    BlogRecord(
        id=3001,
        shop_id=1001,
        user_id=501,
        title="带爸妈去吃这家，真的挺安静",
        content="店里灯光舒服，服务员会主动帮长辈拉椅子，适合家庭聚餐。",
        liked=86,
        comments=12,
    ),
    BlogRecord(
        id=3002,
        shop_id=1002,
        user_id=502,
        title="清淡口味很适合家里老人",
        content="包间很安静，菜量也足，停车比较方便。",
        liked=74,
        comments=9,
    ),
    BlogRecord(
        id=3003,
        shop_id=1004,
        user_id=503,
        title="环境安静到可以慢慢聊天",
        content="这里更像私房菜，长辈会比较喜欢。",
        liked=65,
        comments=7,
    ),
]


class LocalLifeCatalog:
    def __init__(
        self,
        *,
        shop_types: Optional[Sequence[ShopTypeRecord]] = None,
        shops: Optional[Sequence[ShopRecord]] = None,
        vouchers: Optional[Sequence[VoucherRecord]] = None,
        blogs: Optional[Sequence[BlogRecord]] = None,
    ) -> None:
        self._shop_types = list(shop_types or DEFAULT_SHOP_TYPES)
        self._shops = list(shops or DEFAULT_SHOPS)
        self._vouchers = list(vouchers or DEFAULT_VOUCHERS)
        self._blogs = list(blogs or DEFAULT_BLOGS)
        self._shop_index = {shop.id: shop for shop in self._shops}
        self._type_index = {shop_type.id: shop_type for shop_type in self._shop_types}

    @property
    def shops(self) -> list[ShopRecord]:
        return [shop.model_copy() for shop in self._shops]

    def list_shop_types(self) -> list[ShopTypeRecord]:
        return [item.model_copy() for item in sorted(self._shop_types, key=lambda shop_type: shop_type.sort)]

    def get_shop(self, shop_id: int) -> Optional[ShopRecord]:
        shop = self._shop_index.get(int(shop_id))
        return shop.model_copy() if shop is not None else None

    def get_shop_type(self, type_id: Optional[int]) -> Optional[ShopTypeRecord]:
        if type_id is None:
            return None
        item = self._type_index.get(int(type_id))
        return item.model_copy() if item is not None else None

    def list_vouchers(self, shop_id: int) -> list[VoucherRecord]:
        return [voucher.model_copy() for voucher in self._vouchers if int(voucher.shop_id) == int(shop_id)]

    def list_hot_blogs(self, limit: int = 5) -> list[BlogRecord]:
        ordered = sorted(self._blogs, key=lambda blog: (-blog.liked, -blog.comments, blog.id))
        return [blog.model_copy() for blog in ordered[:limit]]

    def list_user_blogs(self, user_id: int, limit: int = 5) -> list[BlogRecord]:
        ordered = sorted(
            (blog for blog in self._blogs if blog.user_id == int(user_id)),
            key=lambda blog: (-blog.liked, -blog.comments, blog.id),
        )
        if not ordered:
            ordered = self.list_hot_blogs(limit=limit)
        return [blog.model_copy() for blog in ordered[:limit]]

    def list_shop_blogs(self, shop_id: int, limit: int = 3) -> list[BlogRecord]:
        ordered = sorted(
            (blog for blog in self._blogs if blog.shop_id == int(shop_id)),
            key=lambda blog: (-blog.liked, -blog.comments, blog.id),
        )
        if not ordered:
            ordered = self.list_hot_blogs(limit=limit)
        return [blog.model_copy() for blog in ordered[:limit]]

    def search_shops(
        self,
        *,
        query: str = "",
        slots: Optional[LocalLifeSlots] = None,
        limit: int = 5,
        shop_ids: Optional[Sequence[int]] = None,
        type_id: Optional[int] = None,
    ) -> list[ShopRecord]:
        slots = slots or LocalLifeSlots()
        limit = max(1, int(limit or 1))
        candidates = list(self._shops)

        allowed_ids: set[int] | None = None
        if shop_ids:
            allowed_ids = {int(value) for value in shop_ids}
        if slots.shop_ids:
            slot_ids = {int(value) for value in slots.shop_ids}
            allowed_ids = slot_ids if allowed_ids is None else allowed_ids & slot_ids
        if allowed_ids is not None:
            allowed = allowed_ids
            candidates = [shop for shop in candidates if shop.id in allowed]
        if type_id is not None:
            candidates = [shop for shop in candidates if shop.type_id == int(type_id)]
        if slots.category and slots.category not in _GENERIC_CATEGORIES:
            category_matches = [shop for shop in candidates if _category_matches(slots.category, shop)]
            if category_matches:
                candidates = category_matches
        if slots.shop_query:
            shop_query = slots.shop_query.lower()
            query_matches = [shop for shop in candidates if shop_query in _shop_search_blob(shop)]
            if query_matches:
                candidates = query_matches

        query_text = query.lower().strip()
        query_terms = _query_terms(query)
        if slots.category:
            query_terms.extend(_query_terms(slots.category))
        if slots.shop_query:
            query_terms.extend(_query_terms(slots.shop_query))
        query_terms = list(dict.fromkeys(term for term in query_terms if term))
        scored: list[tuple[float, ShopRecord]] = []
        for shop in candidates:
            shop_blob = _shop_search_blob(shop)
            score = 0.0
            if query_text and query_text in shop_blob:
                score += 3.0
            overlap = sum(1 for token in query_terms if token in shop_blob)
            score += overlap * 1.2
            if slots.category and _category_matches(slots.category, shop):
                score += 2.0
            if slots.location.city and (slots.location.city.lower() in shop_blob):
                score += 1.0
            if slots.scene == "family_dinner" and shop.family_friendly:
                score += 2.0
            if "quiet" in slots.preferences and shop.quiet_score >= 0.75:
                score += 2.0
            if "parking_available" in slots.preferences and shop.parking:
                score += 1.5
            if "elder_friendly" in slots.preferences and shop.elder_friendly:
                score += 1.5
            if shop.avg_price is not None:
                score += _price_alignment_score(float(shop.avg_price), slots.price)
            if slots.location.lat is not None and slots.location.lng is not None and shop.x is not None and shop.y is not None:
                distance = _haversine_km(float(slots.location.lat), float(slots.location.lng), float(shop.y), float(shop.x))
                score += max(0.0, 3.5 - distance)
            elif shop.distance_km is not None:
                score += max(0.0, 3.0 - float(shop.distance_km))
            if shop.score is not None:
                score += float(shop.score)
            if shop.comments is not None:
                score += min(1.5, float(shop.comments) / 1000.0)
            if shop.sold is not None:
                score += min(1.0, float(shop.sold) / 2000.0)
            if shop.open_hours:
                score += 0.25
            if shop.parking:
                score += 0.25
            if slots.avoid and any(tag in shop_blob for tag in slots.avoid):
                score -= 2.0
            scored.append((score, shop))

        ordered = sorted(
            scored,
            key=lambda item: (
                -item[0],
                item[1].distance_km if item[1].distance_km is not None else 999.0,
                -(item[1].score or 0.0),
            ),
        )
        results: list[ShopRecord] = []
        for _, shop in ordered[:limit]:
            shop_copy = shop.model_copy()
            if slots.location.lat is not None and slots.location.lng is not None and shop.x is not None and shop.y is not None:
                shop_copy.distance_km = round(
                    _haversine_km(float(slots.location.lat), float(slots.location.lng), float(shop.y), float(shop.x)),
                    2,
                )
            results.append(shop_copy)
        return results

    def build_evidence(
        self,
        *,
        query: str,
        shop_ids: Sequence[int],
        slots: Optional[LocalLifeSlots] = None,
        limit: int = 6,
    ) -> list[EvidenceClaim]:
        slots = slots or LocalLifeSlots()
        query_terms = _query_terms(query)
        claims: list[EvidenceClaim] = []
        seen_supports: set[tuple[int, str]] = set()
        for shop_id in shop_ids:
            shop = self._shop_index.get(int(shop_id))
            if shop is None:
                continue
            candidates = [
                ("review_summary", shop.review_summary or "", 0.84, "评论摘要"),
            ]
            for text in shop.evidence_texts[:3]:
                candidates.append(("review_note", text, 0.76, "评论/笔记"))
            for voucher in self.list_vouchers(shop.id)[:2]:
                candidates.append(("voucher_rule", voucher.rules or voucher.title, 0.73, "优惠券"))
            for blog in self.list_shop_blogs(shop.id)[:2]:
                candidates.append(("blog", f"{blog.title}：{blog.content}", 0.7, "探店笔记"))

            for index, (claim_type, content, base_confidence, source_type) in enumerate(candidates):
                if not content:
                    continue
                signature = (shop.id, content)
                if signature in seen_supports:
                    continue
                seen_supports.add(signature)
                content_blob = content.lower()
                overlap = sum(1 for term in query_terms if term in content_blob)
                confidence = min(0.98, base_confidence + overlap * 0.03)
                claim_name = content.split("。")[0].split("，")[0]
                if claim_type == "review_summary":
                    claim_name = "环境安静" if "安静" in content else "适合家庭聚餐"
                elif claim_type == "voucher_rule":
                    claim_name = "有优惠券"
                elif claim_type == "blog":
                    claim_name = "探店笔记提到口碑不错"
                claims.append(
                    EvidenceClaim(
                        chunk_id=f"{shop.id}-{claim_type}-{index}",
                        shop_id=shop.id,
                        claim=claim_name,
                        support_text=content,
                        source_type=source_type,
                        confidence=round(confidence, 3),
                        metadata={
                            "shop_name": shop.name,
                            "category": shop.type_name,
                            "area": shop.area,
                            "address": shop.address,
                            "scene": slots.scene,
                        },
                    )
                )
        claims.sort(key=lambda item: (-item.confidence, item.shop_id or 0, item.chunk_id))
        return claims[:limit]


_DEFAULT_CATALOG = LocalLifeCatalog()


def get_default_catalog() -> LocalLifeCatalog:
    return _DEFAULT_CATALOG
