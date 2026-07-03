"""Canonical shop entity layer.

This module defines the normalized shop-resolution contract shared by
recommendation, comparison, single-shop queries, and deterministic tools.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ShopResolutionStatus(str, Enum):
    resolved = "resolved"
    ambiguous = "ambiguous"
    not_found = "not_found"
    low_confidence = "low_confidence"
    no_mention = "no_mention"


class ShopResolutionSource(str, Enum):
    explicit_shop_id = "explicit_shop_id"
    current_shop = "current_shop"
    active_shop = "active_shop"
    ordinal_reference = "ordinal_reference"
    exact_name = "exact_name"
    normalized_exact = "normalized_exact"
    manual_alias = "manual_alias"
    generated_alias = "generated_alias"
    branch_mention = "branch_mention"
    brand_anchor = "brand_anchor"
    candidate_resolver = "candidate_resolver"
    restricted_fuzzy = "restricted_fuzzy"
    reference = "reference"
    geo_hint = "geo_hint"


class ShopCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shop_id: str = ""
    shop_name: str = ""
    canonical_name: str = ""
    branch_name: str = ""
    alias: list[str] = Field(default_factory=list)
    score: float = 0.0
    source: ShopResolutionSource = ShopResolutionSource.reference
    match_reason: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)

    @field_validator("alias", mode="before")
    @classmethod
    def _coerce_alias(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, (list, tuple, set)):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()] if str(value).strip() else []


class ShopResolutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ShopResolutionStatus = ShopResolutionStatus.no_mention
    mention: str = ""
    shop_id: str = ""
    shop_name: str = ""
    canonical_name: str = ""
    branch_name: str = ""
    alias: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    source: ShopResolutionSource = ShopResolutionSource.reference
    resolution_reason: str = ""
    needs_clarification: bool = False
    clarification_question: str = ""
    candidates: list[ShopCandidate] = Field(default_factory=list)
    selected_candidate: ShopCandidate | None = None
    candidate_count: int = 0
    trace: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("alias", mode="before")
    @classmethod
    def _coerce_alias(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, (list, tuple, set)):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()] if str(value).strip() else []

    @model_validator(mode="after")
    def _sync_candidate_count(self) -> ShopResolutionResult:
        if self.candidate_count < 0:
            self.candidate_count = 0
        if not self.candidate_count:
            self.candidate_count = len(self.candidates or [])
        if self.selected_candidate is None and self.candidates:
            self.selected_candidate = self.candidates[0]
        return self

    def as_legacy_dict(self) -> dict[str, Any]:
        """Convert to the legacy resolve_shop payload shape."""
        payload: dict[str, Any] = {
            "status": self.status.value if hasattr(self.status, "value") else str(self.status),
            "shop": {
                "shop_id": self.shop_id,
                "shop_name": self.shop_name,
                "canonical_name": self.canonical_name,
                "branch_name": self.branch_name,
                "alias": list(self.alias or []),
            }
            if self.shop_id or self.shop_name
            else None,
            "resolved_shop": {
                "shop_id": self.shop_id,
                "shop_name": self.shop_name,
                "canonical_name": self.canonical_name,
                "branch_name": self.branch_name,
                "alias": list(self.alias or []),
            }
            if self.shop_id or self.shop_name
            else None,
            "candidates": [
                {
                    "shop_id": cand.shop_id,
                    "shop_name": cand.shop_name,
                    "canonical_name": cand.canonical_name,
                    "branch_name": cand.branch_name,
                    "alias": list(cand.alias or []),
                    "score": cand.score,
                    "source": cand.source.value if hasattr(cand.source, "value") else str(cand.source),
                    "match_reason": cand.match_reason,
                    "raw": cand.raw,
                }
                for cand in (self.candidates or [])
            ],
            "confidence": self.confidence,
            "source": self.source.value if hasattr(self.source, "value") else str(self.source),
            "reason": self.resolution_reason,
            "needs_clarification": self.needs_clarification,
            "clarification_question": self.clarification_question,
            "mention": self.mention,
            "shop_id": self.shop_id,
            "shop_name": self.shop_name,
            "canonical_name": self.canonical_name,
            "branch_name": self.branch_name,
            "candidate_count": self.candidate_count,
            "trace": list(self.trace or []),
        }
        if self.selected_candidate is not None:
            payload["selected_candidate"] = {
                "shop_id": self.selected_candidate.shop_id,
                "shop_name": self.selected_candidate.shop_name,
                "canonical_name": self.selected_candidate.canonical_name,
                "branch_name": self.selected_candidate.branch_name,
                "alias": list(self.selected_candidate.alias or []),
                "score": self.selected_candidate.score,
                "source": self.selected_candidate.source.value
                if hasattr(self.selected_candidate.source, "value")
                else str(self.selected_candidate.source),
                "match_reason": self.selected_candidate.match_reason,
                "raw": self.selected_candidate.raw,
            }
        return payload
