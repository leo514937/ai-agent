from __future__ import annotations

from typing import Any, Mapping, Sequence

from ..local_life.schemas import EvidenceClaim, LocalLifeIntentType, LocalLifeSlots, RankedCandidate
from .fact_check import evaluate_fact_check
from .policy import ApprovalRequest, SafetyDecision, SafetyPolicy, TransactionDraft


_BOOKING_KEYWORDS = ("订座", "预约", "预订", "订位")
_ORDER_KEYWORDS = ("下单", "购买", "买单", "支付")
_CANCEL_KEYWORDS = ("取消", "撤销", "退订")
_REFUND_KEYWORDS = ("退款", "退钱", "退回", "退款申请")
_STATUS_KEYWORDS = ("订单状态", "订单情况", "订单进度")


def detect_transaction_action(raw_query: str, intent: LocalLifeIntentType | None = None) -> str | None:
    text = (raw_query or "").replace(" ", "")
    if any(token in text for token in _REFUND_KEYWORDS):
        return "refund"
    if any(token in text for token in _CANCEL_KEYWORDS):
        return "cancel"
    if any(token in text for token in _ORDER_KEYWORDS):
        return "order"
    if intent == LocalLifeIntentType.BOOKING or any(token in text for token in _BOOKING_KEYWORDS):
        return "booking"
    if "订单" in text or any(token in text for token in _STATUS_KEYWORDS):
        return "status"
    return None


def _top_candidate(ranked_candidates: Sequence[RankedCandidate]) -> RankedCandidate | None:
    return ranked_candidates[0] if ranked_candidates else None


def _build_transaction_draft(
    *,
    action: str,
    raw_query: str,
    slots: LocalLifeSlots,
    ranked_candidates: Sequence[RankedCandidate],
    selected_shop_id: int | None,
    selected_shop_name: str | None,
) -> TransactionDraft:
    candidate = _top_candidate(ranked_candidates)
    shop_id = selected_shop_id or (candidate.shop_id if candidate is not None else None)
    shop_name = selected_shop_name or (candidate.name if candidate is not None else slots.shop_query)
    booking_time = slots.time.preferred_time or slots.time.date or slots.time.type
    party_size = len(slots.companions) + 1 if slots.companions else None
    amount = None
    if candidate is not None:
        amount = candidate.structured_features.get("avg_price")

    payload = {
        "raw_query": raw_query,
        "scene": slots.scene,
        "preferences": list(slots.preferences),
        "avoid": list(slots.avoid),
        "city": slots.city,
        "booking_time": booking_time,
        "party_size": party_size,
    }
    return TransactionDraft(
        action=action,
        shop_id=shop_id,
        shop_name=shop_name,
        booking_time=booking_time,
        party_size=party_size,
        amount=amount if isinstance(amount, (int, float)) else None,
        note=raw_query,
        payload=payload,
    )


class LocalLifeSafetyGuard:
    def __init__(self, policy: SafetyPolicy | None = None) -> None:
        self.policy = policy or SafetyPolicy()

    def evaluate(
        self,
        *,
        raw_query: str,
        slots: LocalLifeSlots,
        ranked_candidates: Sequence[RankedCandidate],
        evidence_claims: Sequence[EvidenceClaim],
        intent: LocalLifeIntentType | None = None,
        selected_shop_id: int | None = None,
        selected_shop_name: str | None = None,
        client_context: Mapping[str, Any] | None = None,
    ) -> SafetyDecision:
        fact_check = evaluate_fact_check(ranked_candidates=ranked_candidates, evidence_claims=evidence_claims)
        transaction_action = detect_transaction_action(raw_query, intent)
        policy_flags: list[str] = []
        notes: list[str] = list(fact_check.evidence_notes)
        approval_request: dict[str, Any] = {}
        transaction_draft = None
        risk_level = "low"
        approval_required = False
        allowed = True

        if fact_check.evidence_score < self.policy.min_evidence_score:
            policy_flags.append("weak_grounding")
            notes.append("推荐理由的证据强度偏弱。")
            if not self.policy.allow_weak_grounding:
                allowed = False

        if transaction_action in {"booking", "order", "cancel", "refund"}:
            approval_required = True
            risk_level = "medium" if transaction_action in {"booking", "order"} else "high"
            policy_flags.append("transaction_confirmation_required")
            transaction_draft = _build_transaction_draft(
                action=transaction_action,
                raw_query=raw_query,
                slots=slots,
                ranked_candidates=ranked_candidates,
                selected_shop_id=selected_shop_id,
                selected_shop_name=selected_shop_name,
            )
            approval = ApprovalRequest(
                step_id="local-life-transaction-approval",
                reason="需要用户确认后才能执行交易动作。",
                risk_level=risk_level,
                approval_request={
                    "transaction_draft": transaction_draft.model_dump(mode="json"),
                    "client_context": dict(client_context or {}),
                    "selected_shop_id": selected_shop_id,
                    "selected_shop_name": selected_shop_name,
                },
            )
            approval_request = approval.model_dump(mode="json")
            notes.append("交易动作已转为审批草案。")
        elif intent == LocalLifeIntentType.BOOKING:
            approval_required = True
            risk_level = "medium"

        reason = "transaction_confirmation_required" if approval_required else "grounded" if fact_check.evidence_score >= self.policy.min_evidence_score else "weakly_grounded"
        return SafetyDecision(
            allowed=allowed,
            approval_required=approval_required,
            risk_level=risk_level,
            reason=reason,
            policy_flags=policy_flags,
            fact_check=fact_check,
            transaction_draft=transaction_draft,
            approval_request=approval_request,
            notes=notes,
        )
