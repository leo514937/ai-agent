from __future__ import annotations

from types import SimpleNamespace
import threading

from fastapi.testclient import TestClient

from local_life_agent import app as app_module
from local_life_agent.streaming.runtime import TurnStatus, get_stream_handler, get_turn_registry


def test_stream_chat_events_emits_initial_events_before_graph_finishes(monkeypatch):
    release = threading.Event()
    calls: list[tuple[str, str]] = []
    emitted = threading.Event()

    def fake_run_agent_graph(message: str, session_id: str = "", trace_id: str = "", turn_id: str = ""):
        calls.append((message, session_id))
        handler = get_stream_handler()
        assert handler is not None
        handler("川味轩")
        emitted.set()
        release.wait(timeout=1)
        handler("（知春路店）")
        return SimpleNamespace(
            trace_id="trace-1",
            session_id=session_id or "session-1",
            answer_text="最终答案",
            cards=[{"shop_id": "1"}],
            debug=None,
        )

    monkeypatch.setattr(app_module, "run_agent_graph", fake_run_agent_graph)

    request = app_module.ChatRequest(
        session_id="session-1",
        trace_id="trace-1",
        turn_id="turn-1",
        page="assistant",
        message="对比附近评分最高的两家KTV，看看谁的优惠券多，营业状态如何",
        response_mode="stream",
    )

    stream = app_module._stream_chat_events(request)

    first = next(stream)
    second = next(stream)

    assert "event: trace_started" in first
    assert "event: input_normalized" in second
    assert emitted.wait(timeout=1)
    assert calls == [(request.message, request.session_id)]

    third = next(stream)
    assert "event: answer_delta" in third
    assert "川味轩" in third

    release.set()
    remaining = "".join(stream)

    assert "（知春路店）" in remaining
    assert "event: final" in remaining
    assert "delta_text" in remaining
    assert "最终答案" in remaining


def test_chat_stream_endpoint_exposes_sse(monkeypatch):
    release = threading.Event()

    def fake_run_agent_graph(message: str, session_id: str = "", trace_id: str = "", turn_id: str = ""):
        release.wait(timeout=1)
        return SimpleNamespace(
            trace_id="trace-http-1",
            session_id=session_id or "session-http-1",
            answer_text="最终答案",
            cards=[],
            debug=None,
        )

    monkeypatch.setattr(app_module, "run_agent_graph", fake_run_agent_graph)

    client = TestClient(app_module.app)
    payload = {
        "session_id": "session-http-1",
        "trace_id": "trace-http-1",
        "turn_id": "turn-http-1",
        "page": "assistant",
        "message": "对比附近评分最高的两家KTV，看看谁的优惠券多，营业状态如何",
        "response_mode": "stream",
    }

    with client.stream("POST", "/internal/v1/chat/stream", json=payload) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")

        lines = response.iter_lines()
        def next_nonempty_line():
            for line in lines:
                if line:
                    return line
            raise AssertionError("stream ended unexpectedly")

        first = next_nonempty_line()
        second = next_nonempty_line()
        third = next_nonempty_line()
        fourth = next_nonempty_line()

        assert first.startswith("event: trace_started")
        assert second.startswith("data: ")
        assert third.startswith("event: input_normalized")
        assert fourth.startswith("data: ")

        release.set()

        body = "\n".join(line for line in lines if line)
        assert "event: final" in body


def test_stream_chat_events_marks_client_disconnected_then_finishes(monkeypatch):
    release = threading.Event()

    def fake_run_agent_graph(message: str, session_id: str = "", trace_id: str = "", turn_id: str = ""):
        release.wait(timeout=1)
        return SimpleNamespace(
            trace_id=trace_id or "trace-disconnect",
            session_id=session_id or "session-disconnect",
            answer_text="最终答案",
            cards=[],
            debug=None,
        )

    monkeypatch.setattr(app_module, "run_agent_graph", fake_run_agent_graph)

    request = app_module.ChatRequest(
        session_id="session-disconnect",
        trace_id="trace-disconnect",
        turn_id="turn-disconnect",
        page="assistant",
        message="推荐附近火锅",
        response_mode="stream",
    )

    stream = app_module._stream_chat_events(request)
    next(stream)
    next(stream)

    stream.close()

    registry = get_turn_registry()
    record = registry.get("session-disconnect", "turn-disconnect")
    assert record is not None
    assert record.status == TurnStatus.CLIENT_DISCONNECTED

    release.set()
    for _ in range(20):
        record = registry.get("session-disconnect", "turn-disconnect")
        if record is not None and record.status == TurnStatus.FINISHED:
            break
        threading.Event().wait(0.05)
    assert record is not None
    assert record.status == TurnStatus.FINISHED
    assert record.final_answer == "最终答案"


def test_chat_cancel_endpoint_marks_user_cancelled(monkeypatch):
    client = TestClient(app_module.app)
    payload = {
        "session_id": "session-cancel",
        "turn_id": "turn-cancel",
        "trace_id": "trace-cancel",
        "reason": "user_stop",
    }

    response = client.post("/internal/v1/chat/cancel", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["turn_status"] == "USER_CANCELLED"

    registry = get_turn_registry()
    record = registry.get("session-cancel", "turn-cancel")
    assert record is not None
    assert record.status == TurnStatus.USER_CANCELLED
    assert record.cancel_reason == "user_stop"
