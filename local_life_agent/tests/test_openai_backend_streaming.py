from __future__ import annotations

import pytest

from local_life_agent.llm.client import call_llm
from local_life_agent.llm.openai_backend import OpenAICompatibleBackend
from local_life_agent.streaming.runtime import TurnRegistry, TurnControl, bind_turn_control


class _FakeStreamResponse:
    def __init__(self, lines: list[str]):
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self):
        return None

    def iter_lines(self):
        for line in self._lines:
            yield line


class _FakeClient:
    def __init__(self, timeout=None):
        self.timeout = timeout
        self.seen_payload = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def stream(self, method, url, headers=None, json=None):
        self.seen_payload = json
        assert method == "POST"
        assert json["stream"] is True
        return _FakeStreamResponse(
            [
                'data: {"choices":[{"delta":{"content":"川味"}}]}',
                'data: {"choices":[{"delta":{"content":"轩"}}]}',
                "data: [DONE]",
            ]
        )


def test_openai_backend_streams_delta_chunks(monkeypatch):
    client = _FakeClient()
    monkeypatch.setattr("local_life_agent.llm.openai_backend.httpx.Client", lambda timeout=None: client)

    backend = OpenAICompatibleBackend(
        provider="openrouter",
        model="test-model",
        endpoint="https://example.com/v1/chat/completions",
        api_key="test-key",
        timeout_seconds=1,
    )

    chunks: list[str] = []
    result = backend(
        prompt="你好",
        system_prompt="系统",
        timeout_ms=1000,
        stream_handler=chunks.append,
    )

    assert chunks == ["川味", "轩"]
    assert result["ok"] is True
    assert result["raw"] == "川味轩"
    assert result["transport"] == "httpx_stream"


def test_call_llm_raises_turn_cancelled_before_backend_invocation():
    registry = TurnRegistry()
    registry.start_turn("session-cancel", "turn-cancel", "trace-cancel")
    registry.mark_user_cancelled("session-cancel", "turn-cancel", reason="user_stop")

    control = TurnControl(
        registry=registry,
        session_id="session-cancel",
        turn_id="turn-cancel",
        trace_id="trace-cancel",
    )

    called = {"count": 0}

    def backend(*args, **kwargs):
        called["count"] += 1
        return {"ok": True, "content": "不应执行"}

    with bind_turn_control(control):
        with pytest.raises(Exception) as exc_info:
            call_llm("prompt", backend=backend, max_retries=0)

    assert "user_stop" in str(exc_info.value).lower()
    assert called["count"] == 0


def test_openai_backend_stops_streaming_when_user_cancels_midway(monkeypatch):
    registry = TurnRegistry()
    registry.start_turn("session-mid", "turn-mid", "trace-mid")

    class _CancelAfterFirstChunkClient(_FakeClient):
        def stream(self, method, url, headers=None, json=None):
            self.seen_payload = json
            assert method == "POST"
            assert json["stream"] is True
            return _FakeStreamResponse(
                [
                    'data: {"choices":[{"delta":{"content":"川味"}}]}',
                    'data: {"choices":[{"delta":{"content":"轩"}}]}',
                    "data: [DONE]",
                ]
            )

    client = _CancelAfterFirstChunkClient()
    monkeypatch.setattr("local_life_agent.llm.openai_backend.httpx.Client", lambda timeout=None: client)

    backend = OpenAICompatibleBackend(
        provider="openrouter",
        model="test-model",
        endpoint="https://example.com/v1/chat/completions",
        api_key="test-key",
        timeout_seconds=1,
    )

    chunks: list[str] = []

    def stream_handler(delta: str) -> None:
        chunks.append(delta)
        if len(chunks) == 1:
            registry.mark_user_cancelled("session-mid", "turn-mid", reason="user_stop")

    from local_life_agent.streaming.runtime import TurnControl, bind_turn_control

    control = TurnControl(registry=registry, session_id="session-mid", turn_id="turn-mid", trace_id="trace-mid")

    with bind_turn_control(control):
        with pytest.raises(Exception) as exc_info:
            backend(
                prompt="你好",
                system_prompt="系统",
                timeout_ms=1000,
                stream_handler=stream_handler,
            )

    assert "user_stop" in str(exc_info.value).lower()
    assert chunks == ["川味"]
