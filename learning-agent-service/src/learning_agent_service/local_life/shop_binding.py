"""集中式 shop_id 绑定与候选列表 clarification_card 生成。

职责：
1. 从 recall_service 召回的候选列表中，绑定唯一 shop_id
2. 多候选时生成 clarification_card 暴露给用户选择
3. 单候选时直接绑定并返回
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from ..domain.contracts import ClarificationCard, ClarificationOption
from .recall_service import RecallResult
from .schemas import ShopRecord


def _make_option(shop: ShopRecord, index: int) -> ClarificationOption:
    """将 ShopRecord 转为 ClarificationOption。"""
    label = shop.name
    value = str(shop.id)
    parts: list[str] = []
    if shop.area:
        parts.append(shop.area)
    if shop.score is not None:
        parts.append(f"评分 {shop.score}")
    if shop.avg_price is not None:
        parts.append(f"人均 ¥{shop.avg_price:.0f}")
    description = "，".join(parts) if parts else None
    return ClarificationOption(
        id=f"opt_{index}",
        label=label,
        value=value,
        description=description,
    )


def build_clarification_card(
    candidates: list[ShopRecord],
    *,
    source_turn_id: str | None = None,
    question: str = "您想了解哪一家？",
    ambiguity_type: str = "multi_shop",
    expires_in_seconds: int = 300,
) -> ClarificationCard:
    """从多候选列表生成 clarification_card。"""
    now = datetime.now(timezone.utc)
    return ClarificationCard(
        card_id=f"cc_{uuid.uuid4().hex[:12]}",
        question=question,
        options=[_make_option(s, i) for i, s in enumerate(candidates)],
        ambiguity_type=ambiguity_type,
        source_turn_id=source_turn_id,
        expires_at=now,
    )


def bind_shop_id(
    recall: RecallResult,
    *,
    source_turn_id: str | None = None,
    allow_clarification: bool = True,
) -> tuple[int | None, ClarificationCard | None]:
    """从 RecallResult 中绑定 shop_id。

    Returns:
        (shop_id, clarification_card)
        - 单候选：(shop_id, None)
        - 多候选 + allow_clarification：(None, card)
        - 无候选：(None, None)
    """
    candidates = recall.candidates
    if not candidates:
        return None, None

    if len(candidates) == 1:
        return candidates[0].id, None

    if allow_clarification and len(candidates) > 1:
        card = build_clarification_card(
            candidates,
            source_turn_id=source_turn_id,
        )
        return None, card

    # fallback: 返回第一个
    return candidates[0].id, None
