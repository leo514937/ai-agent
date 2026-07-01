"""Runtime helpers for request-scoped streaming callbacks and turn control."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from enum import Enum
import threading
import time
from typing import Callable


StreamHandler = Callable[[str], None]


class TurnStatus(str, Enum):
    RUNNING = "RUNNING"
    CLIENT_DISCONNECTED = "CLIENT_DISCONNECTED"
    USER_CANCELLED = "USER_CANCELLED"
    FINISHED = "FINISHED"
    FAILED = "FAILED"


class TurnCancelledError(RuntimeError):
    """Raised when the current turn was explicitly cancelled by the user."""


@dataclass
class TurnRuntimeRecord:
    session_id: str
    turn_id: str
    trace_id: str
    status: TurnStatus = TurnStatus.RUNNING
    reason: str = ""
    cancel_reason: str = ""
    final_answer: str = ""
    error_message: str = ""
    started_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    updated_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_dict(self) -> dict[str, str | int]:
        return {
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "trace_id": self.trace_id,
            "status": self.status.value,
            "reason": self.reason,
            "cancel_reason": self.cancel_reason,
            "final_answer": self.final_answer,
            "error_message": self.error_message,
            "started_at_ms": self.started_at_ms,
            "updated_at_ms": self.updated_at_ms,
        }


class TurnRegistry:
    """In-memory registry for the lifecycle of active and recent turns."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._turns: dict[tuple[str, str], TurnRuntimeRecord] = {}

    def start_turn(self, session_id: str, turn_id: str, trace_id: str) -> TurnRuntimeRecord:
        session_id = (session_id or "").strip() or "session-anon"
        turn_id = (turn_id or "").strip() or "turn-anon"
        trace_id = (trace_id or "").strip() or "trace-anon"
        with self._lock:
            existing = self._turns.get((session_id, turn_id))
            if existing is not None:
                existing.trace_id = trace_id
                existing.status = TurnStatus.RUNNING
                existing.reason = ""
                existing.cancel_reason = ""
                existing.error_message = ""
                existing.updated_at_ms = int(time.time() * 1000)
                return existing

            for record in self._turns.values():
                if record.session_id == session_id and record.status in {
                    TurnStatus.RUNNING,
                    TurnStatus.CLIENT_DISCONNECTED,
                } and record.turn_id != turn_id:
                    raise ValueError("session already has a running turn")

            record = TurnRuntimeRecord(session_id=session_id, turn_id=turn_id, trace_id=trace_id)
            self._turns[(session_id, turn_id)] = record
            return record

    def get(self, session_id: str, turn_id: str) -> TurnRuntimeRecord | None:
        with self._lock:
            return self._turns.get(((session_id or "").strip(), (turn_id or "").strip()))

    def latest_for_session(self, session_id: str) -> TurnRuntimeRecord | None:
        session_id = (session_id or "").strip()
        with self._lock:
            candidates = [record for record in self._turns.values() if record.session_id == session_id]
            if not candidates:
                return None
            return max(candidates, key=lambda record: record.updated_at_ms)

    def mark_client_disconnected(self, session_id: str, turn_id: str) -> TurnRuntimeRecord | None:
        return self._transition(session_id, turn_id, TurnStatus.CLIENT_DISCONNECTED)

    def mark_user_cancelled(self, session_id: str, turn_id: str, *, reason: str = "user_stop") -> TurnRuntimeRecord | None:
        return self._transition(session_id, turn_id, TurnStatus.USER_CANCELLED, reason=reason, cancel_reason=reason)

    def mark_finished(self, session_id: str, turn_id: str, final_answer: str = "") -> TurnRuntimeRecord | None:
        with self._lock:
            record = self._turns.get(((session_id or "").strip(), (turn_id or "").strip()))
            if record is None or record.status == TurnStatus.USER_CANCELLED:
                return record
            record.status = TurnStatus.FINISHED
            record.final_answer = final_answer or record.final_answer
            record.updated_at_ms = int(time.time() * 1000)
            return record

    def mark_failed(self, session_id: str, turn_id: str, error_message: str = "") -> TurnRuntimeRecord | None:
        return self._transition(session_id, turn_id, TurnStatus.FAILED, reason=error_message, error_message=error_message)

    def clear_terminal(self, session_id: str, turn_id: str) -> None:
        with self._lock:
            record = self._turns.get(((session_id or "").strip(), (turn_id or "").strip()))
            if record is None:
                return
            if record.status in {TurnStatus.FINISHED, TurnStatus.USER_CANCELLED, TurnStatus.FAILED}:
                self._turns.pop((record.session_id, record.turn_id), None)

    def _transition(
        self,
        session_id: str,
        turn_id: str,
        status: TurnStatus,
        *,
        reason: str = "",
        cancel_reason: str = "",
        error_message: str = "",
    ) -> TurnRuntimeRecord | None:
        key = ((session_id or "").strip(), (turn_id or "").strip())
        with self._lock:
            record = self._turns.get(key)
            if record is None:
                return None
            if record.status == TurnStatus.USER_CANCELLED and status != TurnStatus.USER_CANCELLED:
                return record
            record.status = status
            if reason:
                record.reason = reason
            if cancel_reason:
                record.cancel_reason = cancel_reason
            if error_message:
                record.error_message = error_message
            record.updated_at_ms = int(time.time() * 1000)
            return record


_TURN_REGISTRY = TurnRegistry()


def get_turn_registry() -> TurnRegistry:
    return _TURN_REGISTRY


def set_turn_registry(registry: TurnRegistry) -> None:
    global _TURN_REGISTRY
    _TURN_REGISTRY = registry


def reset_turn_registry() -> None:
    set_turn_registry(TurnRegistry())


@dataclass
class TurnControl:
    registry: TurnRegistry
    session_id: str
    turn_id: str
    trace_id: str = ""

    def status(self) -> TurnStatus | None:
        record = self.registry.get(self.session_id, self.turn_id)
        return record.status if record is not None else None

    def is_user_cancelled(self) -> bool:
        return self.status() == TurnStatus.USER_CANCELLED

    def raise_if_cancelled(self) -> None:
        if self.is_user_cancelled():
            record = self.registry.get(self.session_id, self.turn_id)
            reason = record.reason if record is not None else "user_stop"
            raise TurnCancelledError(reason or "user_stop")


_STREAM_HANDLER: ContextVar[StreamHandler | None] = ContextVar(
    "local_life_agent_stream_handler",
    default=None,
)
_TURN_CONTROL: ContextVar[TurnControl | None] = ContextVar(
    "local_life_agent_turn_control",
    default=None,
)


def get_stream_handler() -> StreamHandler | None:
    return _STREAM_HANDLER.get()


def set_stream_handler(handler: StreamHandler | None) -> Token:
    return _STREAM_HANDLER.set(handler)


def reset_stream_handler(token: Token) -> None:
    _STREAM_HANDLER.reset(token)


def get_turn_control() -> TurnControl | None:
    return _TURN_CONTROL.get()


def set_turn_control(control: TurnControl | None) -> Token:
    return _TURN_CONTROL.set(control)


def reset_turn_control(token: Token) -> None:
    _TURN_CONTROL.reset(token)


@contextmanager
def bind_turn_control(control: TurnControl | None):
    token = set_turn_control(control)
    try:
        yield
    finally:
        reset_turn_control(token)


@contextmanager
def bind_stream_handler(handler: StreamHandler | None):
    token = set_stream_handler(handler)
    try:
        yield
    finally:
        reset_stream_handler(token)


def raise_if_turn_cancelled() -> None:
    control = get_turn_control()
    if control is not None:
        control.raise_if_cancelled()
