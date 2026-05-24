from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SafetyBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)


class FactCheckResult(SafetyBaseModel):
    supported_claims: list[str] = Field(default_factory=list)
    weak_claims: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    evidence_score: float = 0.0
    confidence: float = 0.0
    evidence_notes: list[str] = Field(default_factory=list)


class TransactionDraft(SafetyBaseModel):
    action: str
    shop_id: int | None = None
    shop_name: str | None = None
    order_id: str | None = None
    booking_time: str | None = None
    party_size: int | None = None
    amount: float | None = None
    note: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ApprovalRequest(SafetyBaseModel):
    step_id: str
    reason: str
    risk_level: Literal["low", "medium", "high"] = "medium"
    approval_request: dict[str, Any] = Field(default_factory=dict)


class SafetyDecision(SafetyBaseModel):
    allowed: bool = True
    approval_required: bool = False
    risk_level: Literal["low", "medium", "high"] = "low"
    reason: str = "ok"
    policy_flags: list[str] = Field(default_factory=list)
    fact_check: FactCheckResult = Field(default_factory=FactCheckResult)
    transaction_draft: TransactionDraft | None = None
    approval_request: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class SafetyPolicy(SafetyBaseModel):
    min_evidence_score: float = 0.55
    weak_grounding_threshold: float = 0.45
    min_candidate_count: int = 1
    allow_weak_grounding: bool = True
    approval_actions: tuple[str, ...] = (
        "booking",
        "order",
        "cancel",
        "refund",
        "create_booking",
        "create_order",
        "cancel_order",
        "refund_order",
    )
