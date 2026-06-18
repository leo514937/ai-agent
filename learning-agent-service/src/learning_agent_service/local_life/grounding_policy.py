from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from learning_agent_service.domain.utils import clean_text as _clean_text

ClaimRiskLevel = Literal["high", "medium", "low"]
ClaimSupportMode = Literal["any", "all"]

TOOL_REQUIRED_FACETS = frozenset(
    {
        "address",
        "booking",
        "coupon",
        "distance_eta",
        "delivery_eta",
        "open_hours",
        "open_status",
        "order",
        "order_status",
        "payment",
        "phone",
        "price",
        "rating",
        "refund",
        "stock",
    }
)
RAG_REQUIRED_FACETS = frozenset({"environment", "pitfall", "service", "taste"})
HYBRID_FACETS = frozenset({"comparison", "recommendation", "scene_fit"})
HIGH_RISK_FACETS = frozenset(
    {
        "booking",
        "coupon",
        "distance_eta",
        "delivery_eta",
        "open_hours",
        "open_status",
        "order",
        "order_status",
        "payment",
        "phone",
        "refund",
    }
)

_FACET_ALIASES: dict[str, str] = {
    "distance": "distance_eta",
    "open": "open_status",
    "营业": "open_status",
    "营业时间": "open_hours",
    "团购": "coupon",
    "券": "coupon",
    "电话": "phone",
    "配送时间": "delivery_eta",
    "送达时间": "delivery_eta",
}


@dataclass(frozen=True)
class ClaimSourcePolicy:
    facet: str
    risk_level: ClaimRiskLevel
    required_source_types: tuple[str, ...]
    allowed_primary_source_types: tuple[str, ...]
    support_mode: ClaimSupportMode = "any"
    needs_entity_binding: bool = False
    high_risk: bool = False


def normalize_facet_name(value: str | None) -> str:
    cleaned = _clean_text(value)
    if not cleaned:
        return "generic"
    text = cleaned.lower()
    return _FACET_ALIASES.get(text, text)


def claim_policy_for_facet(
    facet: str | None,
    *,
    answer_style: str | None = None,
    approval_required: bool = False,
) -> ClaimSourcePolicy:
    normalized = normalize_facet_name(facet)
    cleaned_style = _clean_text(answer_style)
    style = cleaned_style.lower() if cleaned_style else ""

    if normalized in TOOL_REQUIRED_FACETS:
        risk_level: ClaimRiskLevel = "high" if normalized in HIGH_RISK_FACETS or approval_required else "medium"
        return ClaimSourcePolicy(
            facet=normalized,
            risk_level=risk_level,
            required_source_types=("tool_structured", "realtime_tool"),
            allowed_primary_source_types=("tool_structured", "realtime_tool"),
            support_mode="any",
            needs_entity_binding=True,
            high_risk=normalized in HIGH_RISK_FACETS or approval_required,
        )

    if normalized in RAG_REQUIRED_FACETS:
        return ClaimSourcePolicy(
            facet=normalized,
            risk_level="low",
            required_source_types=("rag_evidence", "rerank_reason"),
            allowed_primary_source_types=("rag_evidence", "rerank_reason"),
            support_mode="any",
            needs_entity_binding=False,
            high_risk=False,
        )

    if normalized == "scene_fit":
        return ClaimSourcePolicy(
            facet=normalized,
            risk_level="medium" if style in {"single_shop_review", "facet_multi"} else "low",
            required_source_types=("tool_structured", "rag_evidence"),
            allowed_primary_source_types=("tool_structured", "realtime_tool", "rag_evidence", "rerank_reason"),
            support_mode="all",
            needs_entity_binding=True,
            high_risk=False,
        )

    if normalized in {"comparison", "recommendation"}:
        return ClaimSourcePolicy(
            facet=normalized,
            risk_level="medium",
            required_source_types=("tool_structured", "rag_evidence", "rerank_reason"),
            allowed_primary_source_types=("tool_structured", "realtime_tool", "rag_evidence", "rerank_reason"),
            support_mode="all",
            needs_entity_binding=True,
            high_risk=False,
        )

    return ClaimSourcePolicy(
        facet=normalized,
        risk_level="low",
        required_source_types=("tool_structured", "realtime_tool", "rag_evidence", "rerank_reason", "user_context", "template"),
        allowed_primary_source_types=("tool_structured", "realtime_tool", "rag_evidence", "rerank_reason", "user_context", "template", "llm_generated"),
        support_mode="any",
        needs_entity_binding=False,
        high_risk=False,
    )


def is_high_risk_facet(facet: str | None, *, answer_style: str | None = None, approval_required: bool = False) -> bool:
    return claim_policy_for_facet(facet, answer_style=answer_style, approval_required=approval_required).high_risk


def supported_source_types_for_facet(facet: str | None, *, answer_style: str | None = None, approval_required: bool = False) -> tuple[str, ...]:
    return claim_policy_for_facet(facet, answer_style=answer_style, approval_required=approval_required).allowed_primary_source_types


def required_source_types_for_facet(facet: str | None, *, answer_style: str | None = None, approval_required: bool = False) -> tuple[str, ...]:
    return claim_policy_for_facet(facet, answer_style=answer_style, approval_required=approval_required).required_source_types

