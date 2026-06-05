from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from learning_agent_service.domain.utils import utcnow as _utcnow


@dataclass
class TransactionRecord:
    transaction_id: str
    transaction_type: str
    status: str
    approval_state: str = "approved"
    idempotency_key: str | None = None
    shop_id: int | None = None
    shop_name: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)

    def to_payload(self) -> dict[str, Any]:
        key = "booking_id" if self.transaction_type == "booking" else "order_id"
        return {
            key: self.transaction_id,
            "transaction_id": self.transaction_id,
            "transaction_type": self.transaction_type,
            "status": self.status,
            "approval_state": self.approval_state,
            "idempotency_key": self.idempotency_key,
            "shop_id": self.shop_id,
            "shop_name": self.shop_name,
            "payload": dict(self.payload),
            "history": list(self.history),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class InMemoryTransactionStore:
    _records: dict[str, TransactionRecord] = field(default_factory=dict)
    _idempotency_index: dict[tuple[str, str], str] = field(default_factory=dict)

    def create_booking(
        self,
        *,
        shop_id: int | None = None,
        shop_name: str | None = None,
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> TransactionRecord:
        return self._create_record(
            transaction_type="booking",
            status="confirmed",
            approval_state="approved",
            shop_id=shop_id,
            shop_name=shop_name,
            payload=payload,
            idempotency_key=idempotency_key,
        )

    def create_order(
        self,
        *,
        shop_id: int | None = None,
        shop_name: str | None = None,
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> TransactionRecord:
        return self._create_record(
            transaction_type="order",
            status="created",
            approval_state="approved",
            shop_id=shop_id,
            shop_name=shop_name,
            payload=payload,
            idempotency_key=idempotency_key,
        )

    def cancel_order(
        self,
        order_id: str | None,
        *,
        reason: str | None = None,
        idempotency_key: str | None = None,
    ) -> TransactionRecord:
        return self._transition_record(
            order_id,
            status="cancelled",
            transaction_type="order",
            payload={"reason": reason},
            idempotency_key=idempotency_key,
        )

    def refund_order(
        self,
        order_id: str | None,
        *,
        reason: str | None = None,
        idempotency_key: str | None = None,
    ) -> TransactionRecord:
        return self._transition_record(
            order_id,
            status="refunded",
            transaction_type="order",
            payload={"reason": reason},
            idempotency_key=idempotency_key,
        )

    def get_order_status(self, order_id: str | None) -> TransactionRecord:
        record = self._records.get(str(order_id or "").strip())
        if record is None:
            return TransactionRecord(
                transaction_id=str(order_id or f"missing-{uuid4().hex[:8]}"),
                transaction_type="order",
                status="not_found",
                approval_state="unknown",
                payload={},
            )
        return record

    def _create_record(
        self,
        *,
        transaction_type: str,
        status: str,
        shop_id: int | None = None,
        shop_name: str | None = None,
        payload: dict[str, Any] | None = None,
        approval_state: str = "approved",
        idempotency_key: str | None = None,
    ) -> TransactionRecord:
        operation_key = f"{transaction_type}:create"
        normalized_key = str(idempotency_key or "").strip()
        if normalized_key:
            existing_id = self._idempotency_index.get((operation_key, normalized_key))
            if existing_id is not None:
                existing_record = self._records.get(existing_id)
                if existing_record is not None:
                    return existing_record
        transaction_id = f"{transaction_type}-{uuid4().hex[:10]}"
        record = TransactionRecord(
            transaction_id=transaction_id,
            transaction_type=transaction_type,
            status=status,
            approval_state=approval_state,
            idempotency_key=normalized_key or None,
            shop_id=shop_id,
            shop_name=shop_name,
            payload=dict(payload or {}),
            history=[
                {
                    "state": status,
                    "approval_state": approval_state,
                    "timestamp": _utcnow().isoformat(),
                    "payload": dict(payload or {}),
                }
                ],
        )
        self._records[transaction_id] = record
        if normalized_key:
            self._idempotency_index[(operation_key, normalized_key)] = transaction_id
        return record

    def _transition_record(
        self,
        transaction_id: str | None,
        *,
        status: str,
        transaction_type: str,
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> TransactionRecord:
        operation_key = f"{transaction_type}:{status}"
        normalized_key = str(idempotency_key or "").strip()
        if normalized_key:
            existing_id = self._idempotency_index.get((operation_key, normalized_key))
            if existing_id is not None:
                existing_record = self._records.get(existing_id)
                if existing_record is not None:
                    return existing_record
        key = str(transaction_id or "").strip()
        if not key:
            record = TransactionRecord(
                transaction_id=f"missing-{uuid4().hex[:8]}",
                transaction_type=transaction_type,
                status="not_found",
                approval_state="unknown",
                idempotency_key=normalized_key or None,
                payload=dict(payload or {}),
                history=[
                    {
                        "state": "not_found",
                        "approval_state": "unknown",
                        "timestamp": _utcnow().isoformat(),
                        "payload": dict(payload or {}),
                    }
                ],
            )
            if normalized_key:
                self._idempotency_index[(operation_key, normalized_key)] = record.transaction_id
            return record

        record = self._records.get(key)
        if record is None:
            record = TransactionRecord(
                transaction_id=key,
                transaction_type=transaction_type,
                status="not_found",
                approval_state="unknown",
                idempotency_key=normalized_key or None,
                payload=dict(payload or {}),
                history=[
                    {
                        "state": "not_found",
                        "approval_state": "unknown",
                        "timestamp": _utcnow().isoformat(),
                        "payload": dict(payload or {}),
                    }
                ],
            )
            self._records[key] = record
            if normalized_key:
                self._idempotency_index[(operation_key, normalized_key)] = key
            return record

        if normalized_key and record.idempotency_key is None:
            record.idempotency_key = normalized_key
            self._idempotency_index[(operation_key, normalized_key)] = key
        record.status = status
        record.updated_at = _utcnow()
        if payload:
            record.payload.update(payload)
        record.history.append(
            {
                "state": status,
                "approval_state": record.approval_state,
                "timestamp": record.updated_at.isoformat(),
                "payload": dict(payload or {}),
            }
        )
        return record
