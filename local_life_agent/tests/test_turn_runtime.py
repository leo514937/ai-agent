from __future__ import annotations

from ..streaming.runtime import (
    TurnCancelledError,
    TurnControl,
    TurnRegistry,
    TurnStatus,
    bind_turn_control,
    get_turn_control,
)


def test_turn_registry_tracks_disconnect_cancel_and_finish():
    registry = TurnRegistry()

    record = registry.start_turn("session-1", "turn-1", "trace-1")
    assert record.status == TurnStatus.RUNNING
    assert registry.get("session-1", "turn-1").status == TurnStatus.RUNNING

    registry.mark_client_disconnected("session-1", "turn-1")
    assert registry.get("session-1", "turn-1").status == TurnStatus.CLIENT_DISCONNECTED

    registry.mark_finished("session-1", "turn-1", "最终答案")
    finished = registry.get("session-1", "turn-1")
    assert finished.status == TurnStatus.FINISHED
    assert finished.final_answer == "最终答案"

    registry.start_turn("session-2", "turn-2", "trace-2")
    registry.mark_user_cancelled("session-2", "turn-2", reason="user_stop")
    cancelled = registry.get("session-2", "turn-2")
    assert cancelled.status == TurnStatus.USER_CANCELLED
    assert cancelled.cancel_reason == "user_stop"

    registry.mark_finished("session-2", "turn-2", "不会覆盖")
    cancelled_again = registry.get("session-2", "turn-2")
    assert cancelled_again.status == TurnStatus.USER_CANCELLED
    assert cancelled_again.final_answer == ""


def test_turn_control_raises_when_registry_marks_user_cancelled():
    registry = TurnRegistry()
    registry.start_turn("session-3", "turn-3", "trace-3")
    registry.mark_user_cancelled("session-3", "turn-3", reason="user_stop")

    control = TurnControl(registry=registry, session_id="session-3", turn_id="turn-3", trace_id="trace-3")
    assert control.is_user_cancelled() is True

    with bind_turn_control(control):
        current = get_turn_control()
        assert current is not None
        try:
            current.raise_if_cancelled()
        except TurnCancelledError as exc:
            assert "user_stop" in str(exc)
        else:  # pragma: no cover - defensive
            raise AssertionError("expected TurnCancelledError")
