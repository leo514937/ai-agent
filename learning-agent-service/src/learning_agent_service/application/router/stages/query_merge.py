from __future__ import annotations

from dataclasses import asdict, dataclass, field
from collections.abc import Mapping
from typing import Any

from ....domain.contracts import PersistentSessionContext
from ....local_life.entity_resolver import _explicit_entity_from_query
from ....local_life.target_shop_policy import _PRONOUNS


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _as_int_list(values: Any) -> list[int]:
    result: list[int] = []
    if values in (None, "", [], {}, ()):
        return result
    items = values if isinstance(values, (list, tuple, set)) else [values]
    for item in items:
        try:
            candidate = int(item)
        except Exception:
            continue
        if candidate not in result:
            result.append(candidate)
    return result


@dataclass(frozen=True)
class LocalLifeQueryMergeResult:
    merged_query: str
    merged_slots: dict[str, Any]
    target_reference: str | None
    sub_intents: list[str]
    missing_slots: list[str]
    confidence: float
    current_shop: str | None = None
    candidate_shop_ids: list[int] = field(default_factory=list)
    comparison_shop_ids: list[int] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["candidate_shop_ids"] = list(self.candidate_shop_ids or [])
        payload["comparison_shop_ids"] = list(self.comparison_shop_ids or [])
        return payload


def merge_local_life_query_context(
    raw_query: str,
    *,
    persistent: PersistentSessionContext,
    parser_slots: Mapping[str, Any] | None = None,
    client_context: Mapping[str, Any] | None = None,
    target_reference: str | None = None,
) -> LocalLifeQueryMergeResult:
    parser_slots = dict(parser_slots or {})
    client_context = dict(client_context or {})

    merged_slots: dict[str, Any] = dict(parser_slots)
    explicit_query_shop = _explicit_entity_from_query(raw_query)
    compact = _normalize_text(raw_query).replace(" ", "")
    recommendation_like = any(token in compact.lower() for token in ("near", "recommend", "附近", "周边", "推荐"))

    current_shop = _normalize_text(
        persistent.current_shop
        or persistent.selected_shop_name
        or client_context.get("selected_shop_name")
        or client_context.get("current_shop")
        or client_context.get("shopName")
        or client_context.get("shop_name")
    ) or None

    if explicit_query_shop:
        current_shop = explicit_query_shop
    elif recommendation_like and not any(pronoun in compact for pronoun in _PRONOUNS):
        current_shop = None
        merged_slots.pop("shop_name", None)
        merged_slots.pop("shop_query", None)

    if current_shop and not _normalize_text(merged_slots.get("shop_name")):
        merged_slots["shop_name"] = current_shop
    if current_shop and not _normalize_text(merged_slots.get("shop_query")):
        merged_slots["shop_query"] = current_shop

    candidate_shop_ids = _as_int_list(parser_slots.get("shop_ids"))
    candidate_shop_ids.extend(_as_int_list(client_context.get("selected_shop_id") or client_context.get("shopId")))
    candidate_shop_ids.extend(_as_int_list(persistent.selected_shop_id))
    candidate_shop_ids = list(dict.fromkeys(candidate_shop_ids))

    comparison_shop_ids = _as_int_list(client_context.get("comparison_shop_ids"))

    if not target_reference:
        target_reference = current_shop or _normalize_text(merged_slots.get("shop_name")) or _normalize_text(merged_slots.get("shop_query")) or None

    compact = _normalize_text(raw_query).replace(" ", "")
    sub_intents: list[str] = []
    lower_compact = compact.lower()
    if any(token in lower_compact for token in ("coupon", "voucher", "discount")):
        sub_intents.append("coupon")
    if any(token in lower_compact for token in ("open", "status", "营业", "开门")):
        sub_intents.append("open_status")
    if any(token in lower_compact for token in ("near", "recommend", "附近", "周边", "推荐")):
        sub_intents.append("recommendation")
    if any(token in lower_compact for token in ("detail", "review", "口碑", "评价", "环境", "介绍")):
        sub_intents.append("detail")
    if any(token in lower_compact for token in ("compare", "vs", "比较", "对比")):
        sub_intents.append("comparison")

    missing_slots = [str(item) for item in (parser_slots.get("missing_slots") or []) if str(item).strip()]
    if any(pronoun in compact for pronoun in _PRONOUNS) and not target_reference and "shop_name" not in missing_slots:
        missing_slots.append("shop_name")

    merged_query = _normalize_text(raw_query)
    if current_shop and any(pronoun in compact for pronoun in _PRONOUNS):
        merged_query = f"{merged_query} (refers to: {current_shop})"

    confidence = 0.0
    try:
        confidence = float(parser_slots.get("confidence") or 0.0)
    except Exception:
        confidence = 0.0
    if current_shop:
        confidence = min(0.99, max(confidence, 0.75))

    return LocalLifeQueryMergeResult(
        merged_query=merged_query,
        merged_slots=merged_slots,
        target_reference=target_reference,
        sub_intents=list(dict.fromkeys(sub_intents)),
        missing_slots=list(dict.fromkeys(missing_slots)),
        confidence=confidence,
        current_shop=current_shop,
        candidate_shop_ids=candidate_shop_ids,
        comparison_shop_ids=comparison_shop_ids,
        details={
            "raw_query": _normalize_text(raw_query),
            "current_shop_from_context": current_shop,
            "candidate_count": len(candidate_shop_ids),
        },
    )
