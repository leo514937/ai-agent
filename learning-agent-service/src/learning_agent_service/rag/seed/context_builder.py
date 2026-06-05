from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from .core import *  # noqa: F401,F403
from .entity_resolver import *  # noqa: F401,F403

def _build_shop_chunks(
    *,
    shop: ShopRecord,
    shop_type: ShopTypeRecord,
    business_client: JavaBusinessClient,
    voucher_limit: int,
    blog_limit: int,
    voucher_ids: set[int] | None = None,
) -> list[KnowledgeChunk]:
    try:
        vouchers = list(_safe_list(business_client.get_coupon_list(shop.id)))[: max(0, int(voucher_limit))]
    except Exception:
        vouchers = []
    if voucher_ids:
        vouchers = [voucher for voucher in vouchers if voucher is not None and int(voucher.id) in voucher_ids]
    try:
        blogs = list(_safe_list(business_client.get_shop_blogs(shop.id, limit=blog_limit)))[: max(0, int(blog_limit))]
    except Exception:
        blogs = []
    child_chunks = _build_shop_child_chunks(
        shop=shop,
        shop_type=shop_type,
        vouchers=vouchers,
        blogs=blogs,
    )
    parent_chunk = _build_shop_parent_chunk(
        shop=shop,
        shop_type=shop_type,
        child_chunks=child_chunks,
        vouchers=vouchers,
        blogs=blogs,
    )
    return [parent_chunk, *child_chunks]


def _build_shop_child_chunks(
    *,
    shop: ShopRecord,
    shop_type: ShopTypeRecord,
    vouchers: Sequence[VoucherRecord],
    blogs: Sequence[BlogRecord],
) -> list[KnowledgeChunk]:
    chunks: list[KnowledgeChunk] = []
    chunks.append(_build_merchant_profile_chunk(shop, shop_type, vouchers=vouchers, blogs=blogs))
    chunks.extend(_build_merchant_review_chunks(shop, shop_type, blogs=blogs, vouchers=vouchers))
    chunks.extend(
        _build_package_description_chunks(
            shop=shop,
            shop_type=shop_type,
            vouchers=vouchers,
        )
    )
    chunks.extend(_build_blog_note_chunks(shop=shop, shop_type=shop_type, blogs=blogs))
    return chunks


def _build_shop_parent_chunk(
    *,
    shop: ShopRecord,
    shop_type: ShopTypeRecord,
    child_chunks: Sequence[KnowledgeChunk],
    vouchers: Sequence[VoucherRecord],
    blogs: Sequence[BlogRecord],
) -> KnowledgeChunk:
    city = _infer_city(shop.address)
    parent_chunk_id = f"local-life:shop:{shop.id}:parent-summary"
    child_chunk_ids = tuple(chunk.chunk_id for chunk in child_chunks)
    child_roles = tuple(
        chunk.chunk_role
        for chunk in child_chunks
        if chunk.chunk_role
    )
    summary_text = _compose_shop_parent_summary_text(
        shop=shop,
        shop_type=shop_type,
        city=city,
        child_chunks=child_chunks,
        vouchers=vouchers,
        blogs=blogs,
    )
    return _make_chunk(
        source_type="merchant_profile",
        document_id=parent_chunk_id,
        chunk_id=parent_chunk_id,
        chunk_index=1,
        title=f"{shop.name} 商家整体摘要",
        text=summary_text,
        summary=_truncate_text(summary_text, max_chars=160),
        category="local_life",
        chunk_type="concept",
        subcategory=shop_type.name,
        chunk_level="parent",
        parent_id=f"shop:{shop.id}",
        parent_title=shop.name,
        parent_chunk_id=parent_chunk_id,
        child_chunk_ids=child_chunk_ids,
        child_roles=child_roles,
        chunk_role="merchant_parent_summary",
        entity_type="shop",
        entity_id=f"shop:{shop.id}",
        sibling_source_types=(
            "merchant_profile",
            "merchant_review",
            "package_description",
            "local_guide",
        ),
        sibling_roles=(
            "merchant_profile",
            "merchant_review_summary",
            "merchant_scene_fit",
            "merchant_pitfall_summary",
            "merchant_blog_note",
            "package_description",
        ),
        metadata={
            "shop_id": shop.id,
            "shop_type_id": shop_type.id,
            "shop_name": shop.name,
            "area": shop.area,
            "city": city,
            "is_active": True,
            "version": LOCAL_LIFE_VERSION,
            "chunk_level": "parent",
            "chunk_role": "merchant_parent_summary",
            "parent_id": f"shop:{shop.id}",
            "parent_title": shop.name,
            "parent_chunk_id": parent_chunk_id,
            "child_chunk_ids": list(child_chunk_ids),
            "child_roles": list(child_roles),
            "entity_type": "shop",
            "entity_id": f"shop:{shop.id}",
            "parent_summary_kind": "merchant_parent_summary",
            "voucher_count": len(vouchers),
            "blog_count": len(blogs),
        },
        tags=_chunk_tags(shop, shop_type, city, source_type="merchant_profile", extra=("parent_summary", "merchant_parent_summary")),
    )


def split_long_text_by_semantic_units(
    text: str,
    *,
    max_chars: int = LOCAL_LIFE_LONG_TEXT_MAX_CHARS,
    overlap_chars: int = LOCAL_LIFE_LONG_TEXT_OVERLAP_CHARS,
) -> list[str]:
    normalized = _normalize_text_block(text)
    if not normalized:
        return []
    if len(normalized) < LOCAL_LIFE_LONG_TEXT_MIN_SPLIT_CHARS:
        return [normalized]

    units = _split_semantic_units(normalized)
    if not units:
        return [normalized]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for unit in units:
        for piece in _split_overlong_unit(unit, max_chars=max_chars):
            piece_len = len(piece)
            if current and current_len + piece_len > max_chars:
                chunk_text = "".join(current).strip()
                if chunk_text:
                    chunks.append(chunk_text)
                overlap = _semantic_overlap_text(chunk_text, overlap_chars)
                current = [overlap] if overlap else []
                current_len = len(overlap)
            current.append(piece)
            current_len += piece_len
    if current:
        chunk_text = "".join(current).strip()
        if chunk_text:
            chunks.append(chunk_text)
    return [chunk for chunk in chunks if chunk]


def _normalize_text_block(text: str) -> str:
    return " ".join(part.strip() for part in str(text or "").splitlines() if part.strip()).strip()


def _split_semantic_units(text: str) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n+", str(text or "")) if part.strip()]
    if not paragraphs:
        return []
    units: list[str] = []
    for paragraph in paragraphs:
        sentence_units = re.split(r"(?<=[。！？!?；;])", paragraph)
        for sentence in sentence_units:
            sentence = sentence.strip()
            if sentence:
                units.append(sentence)
    return units


def _split_overlong_unit(unit: str, *, max_chars: int) -> list[str]:
    text = str(unit or "").strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    sub_units = [part.strip() for part in re.split(r"(?<=[，,、：:])", text) if part.strip()]
    if len(sub_units) > 1:
        merged: list[str] = []
        current = ""
        for part in sub_units:
            if not current:
                current = part
                continue
            if len(current) + len(part) <= max_chars:
                current += part
            else:
                merged.append(current)
                current = part
        if current:
            merged.append(current)
        return merged
    return [text[i : i + max_chars] for i in range(0, len(text), max_chars)]


def _semantic_overlap_text(text: str, overlap_chars: int) -> str:
    if overlap_chars <= 0:
        return ""
    units = _split_semantic_units(text)
    if not units:
        return ""
    overlap: list[str] = []
    total = 0
    for unit in reversed(units):
        if overlap and total + len(unit) > overlap_chars:
            break
        overlap.append(unit)
        total += len(unit)
        if total >= overlap_chars:
            break
    return "".join(reversed(overlap)).strip()


def _join_natural(items: Sequence[str]) -> str:
    values = [str(item).strip() for item in items if str(item).strip()]
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return "和".join(values)
    return "、".join(values[:-1]) + "和" + values[-1]


def _truncate_text(text: str, *, max_chars: int) -> str:
    normalized = _normalize_text_block(text)
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max(0, max_chars - 1)].rstrip() + "…"


def _chunk_role_label(chunk_role: str | None) -> str:
    role = str(chunk_role or "").strip()
    return _LOCAL_LIFE_CHUNK_ROLE_LABELS.get(role, role)


def _source_type_label(source_type: str | None) -> str:
    source = str(source_type or "").strip()
    return _LOCAL_LIFE_SOURCE_TYPE_LABELS.get(source, source)


def _search_keywords(*values: Any) -> tuple[str, ...]:
    tokens: list[str] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            candidates = [value]
        elif isinstance(value, Iterable):
            candidates = [str(item) for item in value if item not in (None, "")]
        else:
            candidates = [str(value)]
        for candidate in candidates:
            candidate = str(candidate).strip()
            if candidate and candidate not in tokens:
                tokens.append(candidate)
    return tuple(tokens)


def _compose_shop_parent_summary_text(
    *,
    shop: ShopRecord,
    shop_type: ShopTypeRecord,
    city: str | None,
    child_chunks: Sequence[KnowledgeChunk],
    vouchers: Sequence[VoucherRecord],
    blogs: Sequence[BlogRecord],
) -> str:
    matched_texts = {
        chunk.chunk_role: _truncate_text(chunk.text, max_chars=70)
        for chunk in child_chunks
        if chunk.chunk_role in {
            "merchant_profile",
            "merchant_review_summary",
            "merchant_scene_fit",
            "merchant_pitfall_summary",
            "package_description",
            "merchant_blog_note",
        }
        and chunk.text
    }
    lines = [
        f"{shop.name} 位于{city or '未知城市'}{shop.area or '未知商圈'}，是一家{shop_type.name}商家。",
    ]
    profile_bits = [
        f"人均约{_format_price(shop.avg_price)}元" if shop.avg_price is not None else "",
        f"评分{_format_score(shop.score)}" if shop.score is not None else "",
        f"评论数{_format_int(shop.comments)}" if shop.comments is not None else "",
    ]
    profile_text = "，".join(bit for bit in profile_bits if bit)
    if profile_text:
        lines.append(f"基础信息显示{profile_text}。")
    if shop.open_hours:
        lines.append(f"营业时间为{shop.open_hours}。")
    if shop.parking:
        lines.append("支持停车。")
    if shop.family_friendly:
        lines.append("适合家庭聚餐。")
    if shop.elder_friendly:
        lines.append("对长辈相对友好。")
    if matched_texts.get("merchant_review_summary"):
        lines.append(f"评价摘要提示：{matched_texts['merchant_review_summary']}")
    if matched_texts.get("merchant_scene_fit"):
        lines.append(f"适合场景提示：{matched_texts['merchant_scene_fit']}")
    if matched_texts.get("merchant_pitfall_summary"):
        lines.append(f"主要注意点：{matched_texts['merchant_pitfall_summary']}")
    if vouchers:
        lines.append(f"当前有{len(vouchers)}张套餐或优惠券可参考，优先核对规则和有效期。")
    if blogs:
        lines.append(f"还有{len(blogs)}篇探店笔记可补充判断。")
    if matched_texts.get("merchant_blog_note"):
        lines.append(f"探店笔记提示：{matched_texts['merchant_blog_note']}")
    summary = _normalize_text_block(" ".join(lines))
    return _truncate_text(summary, max_chars=480)


def _compose_shop_type_parent_summary_text(
    *,
    shop_type: ShopTypeRecord,
    shops: Sequence[ShopRecord],
    child_chunks: Sequence[KnowledgeChunk],
) -> str:
    areas = _join_natural([shop.area for shop in shops if shop.area])
    shop_names = _join_natural([shop.name for shop in shops[:3] if shop.name])
    scene_chunks = [
        _truncate_text(chunk.text, max_chars=60)
        for chunk in child_chunks
        if chunk.chunk_role == "local_guide" and chunk.text
    ]
    lines = [f"{shop_type.name} 本地攻略用于筛选同类商家，优先看商圈、人均、评分和营业时间。"]
    if areas:
        lines.append(f"常见商圈包括{areas}。")
    if shop_names:
        lines.append(f"代表商家有{shop_names}。")
    if scene_chunks:
        lines.append(f"攻略补充提示：{scene_chunks[0]}")
    return _truncate_text(_normalize_text_block(" ".join(lines)), max_chars=380)


def _compose_platform_rule_parent_summary_text(
    *,
    title: str,
    text: str,
    child_chunks: Sequence[KnowledgeChunk],
) -> str:
    snippets = [
        _truncate_text(chunk.text, max_chars=80)
        for chunk in child_chunks
        if chunk.chunk_role == "platform_rule" and chunk.text
    ]
    lines = [f"{title} 主要说明平台规则的适用边界、限制条件和核对顺序。"]
    if text:
        lines.append(_truncate_text(text, max_chars=180))
    if snippets:
        lines.append(f"拆分后的规则补充：{snippets[0]}")
    return _truncate_text(_normalize_text_block(" ".join(lines)), max_chars=320)


def _build_merchant_profile_chunk(
    shop: ShopRecord,
    shop_type: ShopTypeRecord,
    *,
    vouchers: Sequence[VoucherRecord],
    blogs: Sequence[BlogRecord],
) -> KnowledgeChunk:
    city = _infer_city(shop.address)
    lines = [
        f"{shop.name} 是一家{shop_type.name}商家，位于{shop.area or '未知商圈'}。",
        f"地址：{shop.address or '未知'}。",
        f"人均约{_format_price(shop.avg_price)}元，评分{_format_score(shop.score)}，评论数{_format_int(shop.comments)}。",
    ]
    if shop.open_hours:
        lines.append(f"营业时间：{shop.open_hours}。")
    if shop.parking:
        lines.append("支持停车。")
    if shop.family_friendly:
        lines.append("适合家庭聚餐。")
    if shop.elder_friendly:
        lines.append("对长辈友好。")
    if shop.review_summary:
        lines.append(f"评价摘要：{shop.review_summary}")
    if shop.evidence_texts:
        lines.append("典型评价：" + "；".join(shop.evidence_texts[:3]))
    if vouchers:
        lines.append(f"当前可参考的优惠券有{len(vouchers)}张。")
    if blogs:
        lines.append(f"相关探店笔记有{len(blogs)}篇。")
    text = " ".join(lines)
    return _make_chunk(
        source_type="merchant_profile",
        document_id=f"local-life:shop:{shop.id}:merchant-profile",
        chunk_index=1,
        title=f"{shop.name} 商家介绍",
        text=text,
        category="local_life",
        chunk_type="concept",
        subcategory=shop_type.name,
        chunk_level="child",
        parent_id=f"shop:{shop.id}",
        parent_title=shop.name,
        parent_chunk_id=f"local-life:shop:{shop.id}:parent-summary",
        chunk_role="merchant_profile",
        entity_type="shop",
        entity_id=f"shop:{shop.id}",
        sibling_source_types=(
            "merchant_profile",
            "merchant_review",
            "package_description",
            "local_guide",
        ),
        sibling_roles=(
            "merchant_profile",
            "merchant_review_summary",
            "merchant_scene_fit",
            "merchant_pitfall_summary",
            "merchant_blog_note",
            "package_description",
        ),
        metadata={
            "shop_id": shop.id,
            "shop_type_id": shop_type.id,
            "shop_name": shop.name,
            "area": shop.area,
            "city": city,
            "is_active": True,
            "version": LOCAL_LIFE_VERSION,
            "voucher_count": len(vouchers),
            "blog_count": len(blogs),
        },
        tags=_chunk_tags(shop, shop_type, city, source_type="merchant_profile"),
    )


def _build_merchant_review_chunks(
    shop: ShopRecord,
    shop_type: ShopTypeRecord,
    *,
    blogs: Sequence[BlogRecord],
    vouchers: Sequence[VoucherRecord],
 ) -> list[KnowledgeChunk]:
    city = _infer_city(shop.address)
    signals = _extract_review_signals(shop, shop_type, blogs=blogs, vouchers=vouchers)
    chunks: list[KnowledgeChunk] = []
    summary_text = _compose_review_summary_text(
        shop=shop,
        positive_points=signals["positive_points"],
        negative_points=signals["negative_points"],
        keywords=signals["keywords"],
        suitable_scenes=signals["suitable_scenes"],
        unsuitable_scenes=signals["unsuitable_scenes"],
    )
    if summary_text:
        chunks.append(
            _make_chunk(
                source_type="merchant_review",
                document_id=f"local-life:shop:{shop.id}:merchant-review-summary",
                chunk_index=1,
                title=f"{shop.name} 评价摘要",
                text=summary_text,
                category="local_life",
                chunk_type="concept",
                subcategory=shop_type.name,
                chunk_level="child",
                parent_id=f"shop:{shop.id}",
                parent_title=shop.name,
                parent_chunk_id=f"local-life:shop:{shop.id}:parent-summary",
                chunk_role="merchant_review_summary",
                entity_type="shop",
                entity_id=f"shop:{shop.id}",
                sibling_source_types=(
                    "merchant_profile",
                    "merchant_review",
                    "package_description",
                    "local_guide",
                ),
                sibling_roles=(
                    "merchant_profile",
                    "merchant_review_summary",
                    "merchant_scene_fit",
                    "merchant_pitfall_summary",
                    "merchant_blog_note",
                    "package_description",
                ),
                metadata={
                    "shop_id": shop.id,
                    "shop_type_id": shop_type.id,
                    "shop_name": shop.name,
                    "area": shop.area,
                    "city": city,
                    "is_active": True,
                    "version": LOCAL_LIFE_VERSION,
                    "summary_kind": "merchant_review_summary",
                },
                tags=_chunk_tags(shop, shop_type, city, source_type="merchant_review"),
            )
        )
    scene_fit_text = _compose_scene_fit_text(shop=shop, shop_type=shop_type, signals=signals)
    if scene_fit_text:
        chunks.append(
            _make_chunk(
                source_type="merchant_review",
                document_id=f"local-life:shop:{shop.id}:merchant-scene-fit",
                chunk_index=1,
                title=f"{shop.name} 适合场景",
                text=scene_fit_text,
                category="local_life",
                chunk_type="roadmap",
                subcategory=shop_type.name,
                chunk_level="child",
                parent_id=f"shop:{shop.id}",
                parent_title=shop.name,
                parent_chunk_id=f"local-life:shop:{shop.id}:parent-summary",
                chunk_role="merchant_scene_fit",
                entity_type="shop",
                entity_id=f"shop:{shop.id}",
                sibling_source_types=(
                    "merchant_profile",
                    "merchant_review",
                    "package_description",
                    "local_guide",
                ),
                sibling_roles=(
                    "merchant_profile",
                    "merchant_review_summary",
                    "merchant_scene_fit",
                    "merchant_pitfall_summary",
                    "merchant_blog_note",
                    "package_description",
                ),
                metadata={
                    "shop_id": shop.id,
                    "shop_type_id": shop_type.id,
                    "shop_name": shop.name,
                    "area": shop.area,
                    "city": city,
                    "is_active": True,
                    "version": LOCAL_LIFE_VERSION,
                    "scene_kind": "merchant_scene_fit",
                },
                tags=_chunk_tags(shop, shop_type, city, source_type="merchant_review", extra=("scene_fit",)),
            )
        )
    pitfall_text = _compose_pitfall_summary_text(shop=shop, shop_type=shop_type, signals=signals)
    if pitfall_text:
        chunks.append(
            _make_chunk(
                source_type="merchant_review",
                document_id=f"local-life:shop:{shop.id}:merchant-pitfall-summary",
                chunk_index=1,
                title=f"{shop.name} 避坑信息",
                text=pitfall_text,
                category="local_life",
                chunk_type="pitfall",
                subcategory=shop_type.name,
                chunk_level="child",
                parent_id=f"shop:{shop.id}",
                parent_title=shop.name,
                parent_chunk_id=f"local-life:shop:{shop.id}:parent-summary",
                chunk_role="merchant_pitfall_summary",
                entity_type="shop",
                entity_id=f"shop:{shop.id}",
                sibling_source_types=(
                    "merchant_profile",
                    "merchant_review",
                    "package_description",
                    "local_guide",
                ),
                sibling_roles=(
                    "merchant_profile",
                    "merchant_review_summary",
                    "merchant_scene_fit",
                    "merchant_pitfall_summary",
                    "merchant_blog_note",
                    "package_description",
                ),
                metadata={
                    "shop_id": shop.id,
                    "shop_type_id": shop_type.id,
                    "shop_name": shop.name,
                    "area": shop.area,
                    "city": city,
                    "is_active": True,
                    "version": LOCAL_LIFE_VERSION,
                    "pitfall_kind": "merchant_pitfall_summary",
                },
                tags=_chunk_tags(shop, shop_type, city, source_type="merchant_review", extra=("pitfall",)),
            )
        )
    return chunks


def _build_package_description_chunks(
    *,
    shop: ShopRecord,
    shop_type: ShopTypeRecord,
    vouchers: Sequence[VoucherRecord],
) -> list[KnowledgeChunk]:
    chunks: list[KnowledgeChunk] = []
    for voucher in vouchers:
        if voucher is None:
            continue
        chunks.append(_build_package_description_chunk(shop, shop_type, voucher))
    return chunks


def _build_package_description_chunk(
    shop: ShopRecord,
    shop_type: ShopTypeRecord,
    voucher: VoucherRecord,
) -> KnowledgeChunk:
    city = _infer_city(shop.address)
    lines = [
        f"{shop.name} 的套餐/优惠券《{voucher.title}》主要适合关注价格和规则的用户。",
        f"支付金额{_format_price(voucher.pay_value)}元，抵扣金额{_format_price(voucher.actual_value)}元。",
    ]
    if voucher.sub_title:
        lines.append(f"副标题是“{voucher.sub_title}”。")
    if voucher.rules:
        lines.append(f"使用规则是：{voucher.rules}。")
    if voucher.stock is not None:
        lines.append(f"库存大约还有{voucher.stock}张。")
    if voucher.begin_time:
        lines.append(f"生效时间：{voucher.begin_time}。")
    if voucher.end_time:
        lines.append(f"失效时间：{voucher.end_time}。")
    text = " ".join(lines)
    return _make_chunk(
        source_type="package_description",
        document_id=f"local-life:package-description:voucher:{voucher.id}",
        chunk_index=1,
        title=f"{shop.name} 套餐说明 - {voucher.title}",
        text=text,
        category="local_life",
        chunk_type="qa",
        subcategory=shop_type.name,
        chunk_level="child",
        parent_id=f"shop:{shop.id}",
        parent_title=shop.name,
        parent_chunk_id=f"local-life:shop:{shop.id}:parent-summary",
        chunk_role="package_description",
        entity_type="voucher",
        entity_id=f"voucher:{voucher.id}",
        metadata={
            "shop_id": shop.id,
            "shop_type_id": shop_type.id,
            "voucher_id": voucher.id,
            "shop_name": shop.name,
            "area": shop.area,
            "city": city,
            "is_active": True,
            "version": LOCAL_LIFE_VERSION,
            "chunk_role": "package_description",
            "parent_id": f"shop:{shop.id}",
            "parent_title": shop.name,
            "entity_type": "voucher",
            "entity_id": f"voucher:{voucher.id}",
        },
        tags=_chunk_tags(shop, shop_type, city, source_type="package_description", extra=(voucher.title,)),
    )


def _build_blog_note_chunks(
    *,
    shop: ShopRecord,
    shop_type: ShopTypeRecord,
    blogs: Sequence[BlogRecord],
) -> list[KnowledgeChunk]:
    chunks: list[KnowledgeChunk] = []
    city = _infer_city(shop.address)
    for blog in blogs:
        if blog is None:
            continue
        parts: list[str] = []
        if blog.title:
            parts.append(str(blog.title).strip())
        if blog.content:
            parts.append(str(blog.content).strip())
        raw_text = _normalize_text_block(" ".join(part for part in parts if part))
        if not raw_text:
            continue
        segments = split_long_text_by_semantic_units(raw_text)
        if not segments:
            continue
        for index, segment in enumerate(segments, start=1):
            suffix = f"第{index}/{len(segments)}部分" if len(segments) > 1 else "笔记"
            text = f"{shop.name} 的探店笔记《{blog.title or '未命名'}》{suffix}：{segment}"
            chunks.append(
                _make_chunk(
                    source_type="merchant_review",
                    document_id=f"local-life:merchant-blog:shop:{shop.id}:blog:{blog.id}",
                    chunk_index=index,
                    title=f"{shop.name} 探店笔记 - {blog.title or blog.id}",
                    text=text,
                    category="local_life",
                    chunk_type="qa",
                    subcategory=shop_type.name,
                    chunk_level="child",
                    parent_id=f"shop:{shop.id}",
                    parent_title=shop.name,
                    parent_chunk_id=f"local-life:shop:{shop.id}:parent-summary",
                    chunk_role="merchant_blog_note",
                    entity_type="blog",
                    entity_id=f"blog:{blog.id}",
                    sibling_source_types=(
                        "merchant_profile",
                        "merchant_review",
                        "package_description",
                        "local_guide",
                    ),
                    sibling_roles=(
                        "merchant_profile",
                        "merchant_review_summary",
                        "merchant_scene_fit",
                        "merchant_pitfall_summary",
                        "merchant_blog_note",
                        "package_description",
                    ),
                    metadata={
                        "shop_id": shop.id,
                        "shop_type_id": shop_type.id,
                        "shop_name": shop.name,
                        "blog_id": blog.id,
                        "blog_title": blog.title,
                        "area": shop.area,
                        "city": city,
                        "is_active": True,
                        "version": LOCAL_LIFE_VERSION,
                        "chunk_role": "merchant_blog_note",
                        "parent_id": f"shop:{shop.id}",
                        "parent_title": shop.name,
                        "entity_type": "blog",
                        "entity_id": f"blog:{blog.id}",
                    },
                    tags=_chunk_tags(shop, shop_type, city, source_type="merchant_review", extra=(blog.title or "", "merchant_blog_note")),
                )
            )
    return chunks


def _build_local_guide_chunks(*, shop_type: ShopTypeRecord, shops: Sequence[ShopRecord]) -> list[KnowledgeChunk]:
    if not shops:
        return []
    city = _infer_city(shops[0].address) if shops else None
    areas = list(dict.fromkeys(shop.area for shop in shops if shop.area))
    scene_hints = _guide_scene_hints(shops)
    shop_names = [shop.name for shop in shops[:5] if shop.name]
    lead_lines = [
        f"{shop_type.name} 本地攻略：",
        "如果你在筛选同类型商家，可以先看商圈、人均、评分和营业时间。",
    ]
    if areas:
        lead_lines.append("常见商圈：" + "、".join(areas[:5]) + "。")
    if scene_hints:
        lead_lines.append("适用场景：" + "、".join(scene_hints) + "。")
    if shop_names:
        lead_lines.append("代表商家：" + "、".join(shop_names) + "。")
    text = " ".join(lead_lines)
    guide_key = _stable_key("local-guide", shop_type.id, shop_type.name, tuple(areas), tuple(shop_names))
    child_chunks: list[KnowledgeChunk] = []
    for index, segment in enumerate(split_long_text_by_semantic_units(text), start=1):
        child_chunks.append(
            _make_chunk(
                source_type="local_guide",
                document_id=f"local-life:local-guide:type:{shop_type.id}",
                chunk_index=index,
                title=f"{shop_type.name} 本地生活攻略",
                text=segment,
                category="local_life",
                chunk_type="roadmap",
                subcategory=shop_type.name,
                chunk_level="child",
                parent_id=f"shop_type:{shop_type.id}",
                parent_title=shop_type.name,
                parent_chunk_id=f"local-life:shop-type:{shop_type.id}:parent-summary",
                chunk_role="local_guide",
                entity_type="shop_type_guide",
                entity_id=f"shop_type:{shop_type.id}",
                sibling_roles=("local_guide",),
                metadata={
                    "shop_type_id": shop_type.id,
                    "shop_type_name": shop_type.name,
                    "area_list": areas,
                    "shop_names": shop_names,
                    "city": city,
                    "is_active": True,
                    "version": LOCAL_LIFE_VERSION,
                    "guide_key": guide_key,
                    "chunk_role": "local_guide",
                    "parent_id": f"shop_type:{shop_type.id}",
                    "parent_title": shop_type.name,
                    "entity_type": "shop_type_guide",
                    "entity_id": f"shop_type:{shop_type.id}",
                },
                tags=(
                    shop_type.name,
                    "local_guide",
                    *(tuple(areas[:3]) if areas else ()),
                    *(tuple(scene_hints[:3]) if scene_hints else ()),
                ),
            )
        )
    parent_chunk = _build_shop_type_parent_chunk(shop_type=shop_type, shops=shops, child_chunks=child_chunks)
    return [parent_chunk, *child_chunks]


def _build_shop_type_parent_chunk(
    *,
    shop_type: ShopTypeRecord,
    shops: Sequence[ShopRecord],
    child_chunks: Sequence[KnowledgeChunk],
) -> KnowledgeChunk:
    city = _infer_city(shops[0].address) if shops else None
    areas = list(dict.fromkeys(shop.area for shop in shops if shop.area))
    parent_chunk_id = f"local-life:shop-type:{shop_type.id}:parent-summary"
    child_chunk_ids = tuple(chunk.chunk_id for chunk in child_chunks)
    child_roles = tuple(chunk.chunk_role for chunk in child_chunks if chunk.chunk_role)
    summary_text = _compose_shop_type_parent_summary_text(
        shop_type=shop_type,
        shops=shops,
        child_chunks=child_chunks,
    )
    return _make_chunk(
        source_type="local_guide",
        document_id=parent_chunk_id,
        chunk_id=parent_chunk_id,
        chunk_index=1,
        title=f"{shop_type.name} 商家类型整体摘要",
        text=summary_text,
        summary=_truncate_text(summary_text, max_chars=140),
        category="local_life",
        chunk_type="roadmap",
        subcategory=shop_type.name,
        chunk_level="parent",
        parent_id=f"shop_type:{shop_type.id}",
        parent_title=shop_type.name,
        parent_chunk_id=parent_chunk_id,
        child_chunk_ids=child_chunk_ids,
        child_roles=child_roles,
        chunk_role="shop_type_parent_summary",
        entity_type="shop_type",
        entity_id=f"shop_type:{shop_type.id}",
        sibling_roles=("local_guide",),
        metadata={
            "shop_type_id": shop_type.id,
            "shop_type_name": shop_type.name,
            "area_list": areas,
            "shop_names": [shop.name for shop in shops[:5] if shop.name],
            "city": city,
            "is_active": True,
            "version": LOCAL_LIFE_VERSION,
            "chunk_level": "parent",
            "chunk_role": "shop_type_parent_summary",
            "parent_id": f"shop_type:{shop_type.id}",
            "parent_title": shop_type.name,
            "parent_chunk_id": parent_chunk_id,
            "child_chunk_ids": list(child_chunk_ids),
            "child_roles": list(child_roles),
            "entity_type": "shop_type",
            "entity_id": f"shop_type:{shop_type.id}",
        },
        tags=(
            shop_type.name,
            "shop_type_parent_summary",
            *(tuple(areas[:3]) if areas else ()),
        ),
    )


def _build_platform_rule_chunks() -> tuple[KnowledgeChunk, ...]:
    chunks: list[KnowledgeChunk] = []
    for index, row in enumerate(_PLATFORM_RULE_ROWS, start=1):
        segments = split_long_text_by_semantic_units(row["text"])
        child_chunks: list[KnowledgeChunk] = []
        for part_index, text in enumerate(segments, start=1):
            suffix = f"第{part_index}" if len(segments) > 1 else ""
            child_chunks.append(
                _make_chunk(
                    source_type="platform_rule",
                    document_id=f"local-life:platform-rule:{row['rule_id']}",
                    chunk_index=part_index,
                    title=row["title"],
                    text=text if not suffix else f"{row['title']}{suffix}：{text}",
                    category="local_life",
                    chunk_type=row["chunk_type"],
                    subcategory=row["subcategory"],
                    chunk_level="child",
                    parent_id=f"platform_rule:{row['rule_id']}",
                    parent_title=row["title"],
                    parent_chunk_id=f"local-life:platform-rule:{row['rule_id']}:parent-summary",
                    chunk_role="platform_rule",
                    entity_type="platform_rule",
                    entity_id=f"platform_rule:{row['rule_id']}",
                    sibling_roles=("platform_rule",),
                    metadata={
                        "rule_id": row["rule_id"],
                        "is_active": True,
                        "version": LOCAL_LIFE_VERSION,
                        "rule_order": index,
                        "chunk_role": "platform_rule",
                        "parent_id": f"platform_rule:{row['rule_id']}",
                        "parent_title": row["title"],
                        "entity_type": "platform_rule",
                        "entity_id": f"platform_rule:{row['rule_id']}",
                    },
                    tags=("platform_rule", row["rule_id"]),
                )
            )
        parent_chunk = _build_platform_rule_parent_chunk(row=row, child_chunks=child_chunks, rule_order=index)
        chunks.extend([parent_chunk, *child_chunks])
    return tuple(chunks)


def _build_platform_rule_parent_chunk(
    *,
    row: Mapping[str, Any],
    child_chunks: Sequence[KnowledgeChunk],
    rule_order: int,
) -> KnowledgeChunk:
    parent_chunk_id = f"local-life:platform-rule:{row['rule_id']}:parent-summary"
    child_chunk_ids = tuple(chunk.chunk_id for chunk in child_chunks)
    child_roles = tuple(chunk.chunk_role for chunk in child_chunks if chunk.chunk_role)
    summary_text = _compose_platform_rule_parent_summary_text(
        title=str(row["title"]),
        text=str(row["text"]),
        child_chunks=child_chunks,
    )
    return _make_chunk(
        source_type="platform_rule",
        document_id=parent_chunk_id,
        chunk_id=parent_chunk_id,
        chunk_index=1,
        title=f"{row['title']} 整体摘要",
        text=summary_text,
        summary=_truncate_text(summary_text, max_chars=120),
        category="local_life",
        chunk_type=row["chunk_type"],
        subcategory=row["subcategory"],
        chunk_level="parent",
        parent_id=f"platform_rule:{row['rule_id']}",
        parent_title=row["title"],
        parent_chunk_id=parent_chunk_id,
        child_chunk_ids=child_chunk_ids,
        child_roles=child_roles,
        chunk_role="platform_rule_parent_summary",
        entity_type="platform_rule",
        entity_id=f"platform_rule:{row['rule_id']}",
        sibling_roles=("platform_rule",),
        metadata={
            "rule_id": row["rule_id"],
            "is_active": True,
            "version": LOCAL_LIFE_VERSION,
            "rule_order": rule_order,
            "chunk_level": "parent",
            "chunk_role": "platform_rule_parent_summary",
            "parent_id": f"platform_rule:{row['rule_id']}",
            "parent_title": row["title"],
            "parent_chunk_id": parent_chunk_id,
            "child_chunk_ids": list(child_chunk_ids),
            "child_roles": list(child_roles),
            "entity_type": "platform_rule",
            "entity_id": f"platform_rule:{row['rule_id']}",
        },
        tags=("platform_rule", f"{row['rule_id']}", "platform_rule_parent_summary"),
    )


def _compose_review_summary_text(
    *,
    shop: ShopRecord,
    positive_points: Sequence[str],
    negative_points: Sequence[str],
    keywords: Sequence[str],
    suitable_scenes: Sequence[str],
    unsuitable_scenes: Sequence[str],
) -> str:
    lines = []
    if positive_points:
        lines.append("好评点：" + "；".join(positive_points[:3]) + "。")
    if negative_points:
        lines.append("差评点：" + "；".join(negative_points[:3]) + "。")
    if keywords:
        lines.append("高频关键词：" + "、".join(keywords[:6]) + "。")
    if suitable_scenes:
        lines.append("适合场景：" + "、".join(suitable_scenes[:6]) + "。")
    if unsuitable_scenes:
        lines.append("不适合场景：" + "、".join(unsuitable_scenes[:6]) + "。")
    if not lines:
        return ""
    return f"{shop.name} 的口碑摘要：" + " ".join(lines)


def _compose_scene_fit_text(
    *,
    shop: ShopRecord,
    shop_type: ShopTypeRecord,
    signals: Mapping[str, Sequence[str]],
) -> str:
    scene_items = list(signals.get("suitable_scenes") or [])
    if not scene_items:
        return ""
    return (
        f"{shop.name} 属于{shop_type.name}，更适合{_join_natural(scene_items)}。"
        " 从现有评价和店铺特征看，这类场景下更容易获得稳定体验。"
    )


def _compose_pitfall_summary_text(
    *,
    shop: ShopRecord,
    shop_type: ShopTypeRecord,
    signals: Mapping[str, Sequence[str]],
) -> str:
    pitfall_items = list(signals.get("pitfall_items") or [])
    if not pitfall_items:
        return ""
    return (
        f"{shop.name}（{shop_type.name}）的避坑信息主要是：{_join_natural(pitfall_items[:5])}。"
        " 如果在高峰期或节假日去，建议提前规划。"
    )


def _extract_review_signals(
    shop: ShopRecord,
    shop_type: ShopTypeRecord,
    *,
    blogs: Sequence[BlogRecord],
    vouchers: Sequence[VoucherRecord],
) -> dict[str, list[str]]:
    text_fragments: list[str] = []
    if shop.review_summary:
        text_fragments.append(str(shop.review_summary))
    text_fragments.extend(str(text) for text in shop.evidence_texts[:5] if text)
    for blog in blogs[:3]:
        if blog.title:
            text_fragments.append(str(blog.title))
        if blog.content:
            text_fragments.append(str(blog.content[:400]))
    if vouchers:
        text_fragments.append("有优惠券可参考")
    combined = " ".join(text_fragments)
    positive_points: list[str] = []
    negative_points: list[str] = []
    keywords: list[str] = []
    suitable_scenes: list[str] = []
    unsuitable_scenes: list[str] = []
    pitfall_items: list[str] = []

    if any(keyword in combined for keyword in ("安静", "安静", "静")):
        positive_points.append("环境相对安静")
        keywords.append("安静")
        suitable_scenes.extend([item for item in ("约会", "家庭聚餐", "带长辈") if item not in suitable_scenes])
    if any(keyword in combined for keyword in ("家庭", "爸妈", "长辈", "老人")):
        positive_points.append("适合家庭一起吃饭")
        keywords.append("家庭")
        suitable_scenes.extend([item for item in ("家庭聚餐", "带长辈") if item not in suitable_scenes])
    if any(keyword in combined for keyword in ("停车",)):
        positive_points.append("停车条件在部分时段还能接受")
        keywords.append("停车")
        if "停车方便" not in suitable_scenes:
            suitable_scenes.append("停车方便")
    if any(keyword in combined for keyword in ("排队", "等位")):
        negative_points.append("高峰期可能要排队")
        pitfall_items.append("排队久")
        unsuitable_scenes.append("工作日午晚高峰")
    if any(keyword in combined for keyword in ("吵", "嘈杂")):
        negative_points.append("环境可能偏吵")
        pitfall_items.append("太吵")
    if any(keyword in combined for keyword in ("贵", "价格高", "偏高")):
        negative_points.append("价格可能偏高")
        pitfall_items.append("价格偏高")
    if any(keyword in combined for keyword in ("慢", "上菜慢", "服务慢")):
        negative_points.append("服务节奏可能偏慢")
        pitfall_items.append("服务慢")
    if any(keyword in combined for keyword in ("预约",)):
        negative_points.append("部分场景建议提前预约")
        pitfall_items.append("需要预约")
    if any(keyword in combined for keyword in ("节假日", "假日")):
        pitfall_items.append("节假日不可用")
    if any(keyword in combined for keyword in ("不方便", "难停", "停车难")):
        pitfall_items.append("停车不方便")

    if not positive_points:
        positive_points.append("口碑整体偏稳")
    if not negative_points:
        negative_points.append("暂无明显负面反馈")
    if not keywords:
        keywords.extend([shop.name, shop.area or shop_type.name])
    if not suitable_scenes:
        suitable_scenes.extend([item for item in ("朋友聚餐", "日常吃饭") if item not in suitable_scenes])
    if not unsuitable_scenes:
        unsuitable_scenes.extend([item for item in ("高峰期",) if item not in unsuitable_scenes])
    if not pitfall_items:
        pitfall_items.append("暂无明显硬伤，但建议结合时间段和预算判断")

    return {
        "positive_points": list(dict.fromkeys(positive_points)),
        "negative_points": list(dict.fromkeys(negative_points)),
        "keywords": list(dict.fromkeys(keywords)),
        "suitable_scenes": list(dict.fromkeys(suitable_scenes)),
        "unsuitable_scenes": list(dict.fromkeys(unsuitable_scenes)),
        "pitfall_items": list(dict.fromkeys(pitfall_items)),
    }


def _make_chunk(
    *,
    source_type: str,
    document_id: str,
    chunk_index: int,
    chunk_id: str | None = None,
    title: str,
    text: str,
    category: str,
    chunk_type: str,
    subcategory: str | None = None,
    summary: str | None = None,
    chunk_level: str = "child",
    parent_id: str | None = None,
    parent_title: str | None = None,
    parent_chunk_id: str | None = None,
    child_chunk_ids: Sequence[str] = (),
    child_roles: Sequence[str] = (),
    chunk_role: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    sibling_source_types: Sequence[str] = (),
    sibling_roles: Sequence[str] = (),
    metadata: Mapping[str, Any] | None = None,
    tags: Sequence[str] = (),
) -> KnowledgeChunk:
    chunk_id = chunk_id or f"{document_id}:chunk-{int(chunk_index):03d}"
    payload_metadata = dict(metadata or {})
    payload_metadata.setdefault("chunk_level", chunk_level)
    if parent_id is not None:
        payload_metadata.setdefault("parent_id", parent_id)
    if parent_title is not None:
        payload_metadata.setdefault("parent_title", parent_title)
    if parent_chunk_id is not None:
        payload_metadata.setdefault("parent_chunk_id", parent_chunk_id)
    if child_chunk_ids:
        payload_metadata.setdefault("child_chunk_ids", list(dict.fromkeys(str(item) for item in child_chunk_ids if item)))
    if child_roles:
        payload_metadata.setdefault("child_roles", list(dict.fromkeys(str(item) for item in child_roles if item)))
    if chunk_role is not None:
        payload_metadata.setdefault("chunk_role", chunk_role)
    if entity_type is not None:
        payload_metadata.setdefault("entity_type", entity_type)
    if entity_id is not None:
        payload_metadata.setdefault("entity_id", entity_id)
    chunk_role_label = _chunk_role_label(chunk_role)
    source_type_label = _source_type_label(source_type)
    if chunk_role_label:
        payload_metadata.setdefault("chunk_role_label", chunk_role_label)
    if source_type_label:
        payload_metadata.setdefault("source_type_label", source_type_label)
    if sibling_source_types:
        payload_metadata.setdefault("sibling_source_types", list(dict.fromkeys(str(item) for item in sibling_source_types if item)))
    if sibling_roles:
        payload_metadata.setdefault("sibling_roles", list(dict.fromkeys(str(item) for item in sibling_roles if item)))
    payload_metadata.setdefault(
        "search_keywords",
        list(
            _search_keywords(
                title,
                parent_title,
                payload_metadata.get("shop_name"),
                payload_metadata.get("city"),
                payload_metadata.get("area"),
                payload_metadata.get("subcategory"),
                payload_metadata.get("chunk_role_label"),
                payload_metadata.get("source_type_label"),
                tags,
            )
        ),
    )
    return KnowledgeChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        text=text,
        title=title,
        summary=summary if summary is not None else _summarize_text(text),
        category=category,
        subcategory=subcategory,
        source_type=source_type,
        chunk_type=chunk_type,
        chunk_level=chunk_level,
        version=LOCAL_LIFE_VERSION,
        parent_id=parent_id,
        parent_title=parent_title,
        parent_chunk_id=parent_chunk_id,
        child_chunk_ids=tuple(str(item) for item in child_chunk_ids if item),
        child_roles=tuple(str(item) for item in child_roles if item),
        chunk_role=chunk_role,
        entity_type=entity_type,
        entity_id=entity_id,
        is_latest=True,
        is_active=bool(payload_metadata.get("is_active", True)),
        hash=hashlib.sha1(f"{document_id}:{chunk_id}:{text}".encode()).hexdigest(),
        tags=tuple(dict.fromkeys(str(tag) for tag in tags if tag)),
        metadata=payload_metadata,
    )


def _chunk_to_point(
    chunk: KnowledgeChunk,
    *,
    embedding_adapter: Any,
    vector_name: str,
    vector_size: int,
) -> Any:
    dense_text = chunk.searchable_dense_text() or chunk.searchable_text()
    vector = embedding_adapter.embed(dense_text)
    if len(vector) != int(vector_size):
        raise RuntimeError(
            f"Embedding dimension mismatch for {chunk.chunk_id}: expected {vector_size}, got {len(vector)}"
        )
    payload = chunk.to_payload()
    payload.setdefault("dense_text", dense_text)
    payload.setdefault("sparse_text", chunk.searchable_sparse_text())
    point_id = uuid.uuid5(uuid.NAMESPACE_URL, f"local-life:{chunk.chunk_id}")
    named_vector = {vector_name: vector}
    if PointStruct is not None:
        return PointStruct(id=point_id, vector=named_vector, payload=payload)
    return {"id": point_id, "vector": named_vector, "payload": payload}


def _upsert_points(qdrant_client: Any, collection_name: str, points: Sequence[Any]) -> None:
    upsert = getattr(qdrant_client, "upsert", None)
    if not callable(upsert):
        raise RuntimeError("Qdrant client does not expose upsert")
    try:
        upsert(collection_name=collection_name, points=list(points), wait=True)
    except TypeError:
        upsert(collection_name=collection_name, points=list(points))


def ensure_local_life_payload_indexes(qdrant_client: Any, *, collection_name: str) -> tuple[str, ...]:
    create_payload_index = getattr(qdrant_client, "create_payload_index", None)
    if not callable(create_payload_index):
        return ()
    created_fields: list[str] = []
    for field_name, field_schema in _LOCAL_LIFE_PAYLOAD_INDEXES:
        if _create_payload_index(create_payload_index, collection_name, field_name, field_schema):
            created_fields.append(field_name)
        else:
            created_fields.append(field_name)
    return tuple(created_fields)


def _create_payload_index(create_payload_index: Any, collection_name: str, field_name: str, field_schema: Any) -> bool:
    try:
        create_payload_index(
            collection_name=collection_name,
            field_name=field_name,
            field_schema=field_schema,
            wait=True,
        )
        return True
    except TypeError as schema_error:
        try:
            create_payload_index(
                collection_name=collection_name,
                field_name=field_name,
                field_type=field_schema,
                wait=True,
            )
            return True
        except Exception as field_type_error:
            if _is_payload_index_already_exists_error(field_type_error):
                _LOGGER.info(
                    "local_life_seed_payload_index_exists collection=%s field=%s",
                    collection_name,
                    field_name,
                )
                return False
            raise field_type_error from schema_error
    except Exception as exc:
        if _is_payload_index_already_exists_error(exc):
            _LOGGER.info(
                "local_life_seed_payload_index_exists collection=%s field=%s",
                collection_name,
                field_name,
            )
            return False
        raise


def _is_payload_index_already_exists_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(
        token in text
        for token in (
            "already exists",
            "already exist",
            "already created",
            "index already",
            "duplicate",
            "conflict",
        )
    )


def _cleanup_stale_points(
    qdrant_client: Any,
    *,
    collection_name: str,
    current_chunk_ids: Sequence[str],
    scoped_parent_ids: Sequence[str] = (),
    scoped_update: bool = False,
) -> int:
    delete = getattr(qdrant_client, "delete", None)
    if not callable(delete):
        return 0
    must_not = []
    if current_chunk_ids:
        must_not.append(
            HasIdCondition(has_id=[uuid.uuid5(uuid.NAMESPACE_URL, f"local-life:{chunk_id}") for chunk_id in current_chunk_ids])
        )
    must = [
        FieldCondition(key="category", match=MatchValue(value="local_life")),
    ]
    parent_ids = [str(parent_id) for parent_id in scoped_parent_ids if str(parent_id).strip()]
    if scoped_update:
        if not parent_ids:
            _LOGGER.info("local_life_seed_skip_stale_cleanup_due_to_empty_scope collection=%s", collection_name)
            return 0
        must.append(FieldCondition(key="parent_id", match=MatchAny(any=parent_ids)))
    filter_selector = Filter(
        must=must,
        must_not=must_not or None,
    )
    response = delete(collection_name=collection_name, points_selector=filter_selector, wait=True)
    deleted = _extract_deleted_count(response)
    return deleted


def _extract_deleted_count(response: Any) -> int:
    if response is None:
        return 0
    for name in ("deleted_count", "deleted", "points_deleted"):
        value = _extract_value(response, name)
        if value is not None:
            try:
                return int(value)
            except Exception:
                continue
    return 0


def _validate_collection_vector_shape(
    qdrant_client: Any,
    *,
    collection_name: str,
    vector_name: str,
    vector_size: int,
) -> None:
    get_collection = getattr(qdrant_client, "get_collection", None)
    if not callable(get_collection):
        return
    info = get_collection(collection_name)
    vectors = _extract_vectors_config(info)
    candidate = None
    if isinstance(vectors, Mapping):
        candidate = vectors.get(vector_name)
        if candidate is None and len(vectors) == 1:
            candidate = next(iter(vectors.values()))
    else:
        candidate = vectors
    if candidate is None:
        raise LocalLifeQdrantCollectionShapeError(
            f"Qdrant collection {collection_name} does not expose vector config"
        )
    current_size = _extract_value(candidate, "size")
    current_distance = _extract_value(candidate, "distance")
    if current_size is not None and int(current_size) != int(vector_size):
        raise LocalLifeQdrantCollectionShapeError(
            f"Qdrant collection {collection_name} vector size mismatch: expected {vector_size}, got {current_size}"
        )
    if current_distance is not None and str(current_distance).lower() != "cosine":
        raise LocalLifeQdrantCollectionShapeError(
            f"Qdrant collection {collection_name} distance mismatch: expected cosine, got {current_distance}"
        )


def _extract_vectors_config(info: Any) -> Any:
    if isinstance(info, Mapping):
        config = info.get("config", info)
        if isinstance(config, Mapping):
            params = config.get("params", config)
            if isinstance(params, Mapping):
                return params.get("vectors") or params.get("vectors_config")
            return _extract_value(params, "vectors") or _extract_value(params, "vectors_config")
        params = _extract_value(config, "params")
        if params is not None:
            return _extract_value(params, "vectors") or _extract_value(params, "vectors_config")
        return _extract_value(config, "vectors") or _extract_value(config, "vectors_config")
    config = _extract_value(info, "config")
    if config is not None:
        params = _extract_value(config, "params")
        if params is not None:
            vectors = _extract_value(params, "vectors")
            if vectors is not None:
                return vectors
            return _extract_value(params, "vectors_config")
    params = _extract_value(info, "params")
    if params is not None:
        vectors = _extract_value(params, "vectors")
        if vectors is not None:
            return vectors
        return _extract_value(params, "vectors_config")
    return _extract_value(info, "vectors") or _extract_value(info, "vectors_config")


def _extract_value(obj: Any, name: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, Mapping):
        return obj.get(name)
    return getattr(obj, name, None)

__all__ = [name for name in globals() if not name.startswith("__")]
