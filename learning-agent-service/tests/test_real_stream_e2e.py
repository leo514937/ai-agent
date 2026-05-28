from __future__ import annotations

import json
import os
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

import _bootstrap  # noqa: F401
import httpx
import redis


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"


def _load_env_value(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value:
        return value
    if not ENV_FILE.is_file():
        return default

    for raw_line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        if key.strip() != name:
            continue
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        return value
    return default


def _decode_sse(raw: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for block in raw.replace("\r\n", "\n").strip().split("\n\n"):
        if not block.strip():
            continue
        event_type = "message"
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event_type = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].lstrip())
        data_raw = "\n".join(data_lines).strip()
        data: Any = None
        if data_raw:
            try:
                data = json.loads(data_raw)
            except Exception:
                data = data_raw
        events.append({"event_type": event_type, "data": data})
    return events


def _extract_payload(event: dict[str, Any]) -> dict[str, Any]:
    data = event.get("data")
    if isinstance(data, dict):
        payload = data.get("payload")
        if isinstance(payload, dict):
            return payload
        return data
    return {}


def _first_event(events: Iterable[dict[str, Any]], event_type: str) -> dict[str, Any] | None:
    for event in events:
        if event.get("event_type") == event_type:
            return event
    return None


def _stream_url() -> str:
    return os.getenv("LEARNING_AGENT_REAL_STREAM_URL", "http://127.0.0.1:3001/api/ai/chat/stream")


def _session_state_key(session_id: str) -> str:
    prefix = _load_env_value("LEARNING_AGENT_REDIS_KEY_PREFIX", "learn")
    return f"{prefix}:session:{session_id}:state"


@dataclass
class _RealCallResult:
    status_code: int
    events: list[dict[str, Any]]
    final_payload: dict[str, Any]
    clarification_payload: dict[str, Any] | None


class RealStreamE2ETestCase(unittest.TestCase):
    @unittest.skipUnless(os.getenv("RUN_REAL_STREAM_E2E") == "1", "real stream E2E is disabled")
    def test_real_stream_consumes_pending_clarification_and_preserves_session_state(self) -> None:
        client = httpx.Client(timeout=httpx.Timeout(300.0, connect=10.0))
        redis_client = redis.Redis.from_url(
            _load_env_value("LEARNING_AGENT_REDIS_URL", "redis://127.0.0.1:6379/0"),
            decode_responses=True,
        )

        session_recap = f"real-stream-e2e-recap-{uuid4().hex}"
        session_pending = f"real-stream-e2e-pending-{uuid4().hex}"
        session_blocked = f"real-stream-e2e-blocked-{uuid4().hex}"
        session_shop = f"real-stream-e2e-shop-{uuid4().hex}"

        try:
            turn1 = self._call_stream(
                client,
                session_id=session_pending,
                turn_id="real-stream-e2e-pending-turn1",
                trace_id="real-stream-e2e-pending-trace1",
                message="附近有什么推荐菜",
                client_context={"page": "assistant"},
            )
            self.assertIsNotNone(turn1.final_payload)
            self.assertIn("城市", turn1.final_payload.get("answer_text", ""))
            self.assertTrue(self._has_stage(turn1.events, "load_context"))
            self.assertFalse(self._has_stage(turn1.events, "clarification_card"))

            pending_state_turn1 = self._read_session_state(redis_client, session_pending)
            self.assertIsNotNone(pending_state_turn1.get("pending_clarification"))
            self.assertEqual(pending_state_turn1.get("current_topic"), "附近有什么推荐菜")

            turn2 = self._call_stream(
                client,
                session_id=session_pending,
                turn_id="real-stream-e2e-pending-turn2",
                trace_id="real-stream-e2e-pending-trace2",
                message="北京",
                client_context={"page": "assistant"},
            )
            self.assertIsNotNone(turn2.final_payload)
            self.assertTrue(self._has_stage(turn2.events, "consume_pending_clarification"))
            self.assertFalse(self._has_stage(turn2.events, "clarification_card"))
            self.assertFalse(self._contains_text(turn2.events, "你现在在哪个城市或位置附近"))
            self.assertFalse(self._contains_text(turn2.events, "这个问题还不够具体"))
            self.assertFalse(self._contains_text(turn2.events, "你方便补充一下城市或商圈吗"))
            self.assertNotEqual(turn2.final_payload.get("response_mode"), "ask_clarification")
            self.assertNotIn("Tool result", turn2.final_payload.get("answer_text", ""))
            self.assertNotIn("normalized_output", turn2.final_payload.get("answer_text", ""))
            self.assertFalse(
                self._contains_any_text(
                    turn2.final_payload.get("answer_text", ""),
                    ("Tool result", "raw_tool_result", "normalized_output", "{'shop_id'", "shop_detail", "clarification_slot"),
                )
            )

            pending_state_turn2 = self._read_session_state(redis_client, session_pending)
            clarification_result = pending_state_turn2.get("clarification_result") or {}
            self.assertEqual(clarification_result.get("original_query"), "附近有什么推荐菜")
            self.assertEqual(pending_state_turn2.get("current_city"), "北京")
            self.assertEqual(pending_state_turn2.get("current_topic"), "附近有什么推荐菜")
            self.assertIsNone(pending_state_turn2.get("pending_clarification"))
            self.assertIsNone(pending_state_turn2.get("current_shop"))

            recap = self._call_stream(
                client,
                session_id=session_recap,
                turn_id="real-stream-e2e-recap-turn1",
                trace_id="real-stream-e2e-recap-trace1",
                message="你记得我们说过什么吗",
                client_context={"page": "assistant", "shopName": "山城一锅"},
            )
            self.assertIsNotNone(recap.final_payload)
            self.assertIn("山城一锅", recap.final_payload.get("answer_text", ""))
            self.assertIn("继续", recap.final_payload.get("answer_text", ""))
            self.assertTrue(self._has_stage(recap.events, "conversation_recap_direct_response"))
            self.assertFalse(self._has_stage(recap.events, "retrieval_started"))
            self.assertNotEqual(recap.final_payload.get("response_mode"), "ask_clarification")

            shop_turn1 = self._call_stream(
                client,
                session_id=session_shop,
                turn_id="real-stream-e2e-shop-turn1",
                trace_id="real-stream-e2e-shop-trace1",
                message="山城一锅这家店有券吗，环境评价怎么样",
                client_context={"page": "assistant", "shopName": "山城一锅"},
            )
            self.assertIsNotNone(shop_turn1.final_payload)
            self.assertNotIn("补充一下城市", shop_turn1.final_payload.get("answer_text", ""))
            self.assertNotEqual(shop_turn1.final_payload.get("response_mode"), "ask_clarification")
            self.assertFalse(
                self._contains_any_text(
                    shop_turn1.final_payload.get("answer_text", ""),
                    ("Tool result", "raw_tool_result", "normalized_output", "{'shop_id'", "shop_detail", "clarification_slot"),
                )
            )
            shop_state_turn1 = self._read_session_state(redis_client, session_shop)
            print(f"DEBUG: shop_state_turn1 = {shop_state_turn1}")
            self.assertEqual(shop_state_turn1.get("current_shop"), "山城一锅")
            self.assertEqual(shop_state_turn1.get("selected_shop_name"), "山城一锅")

            shop_turn2 = self._call_stream(
                client,
                session_id=session_shop,
                turn_id="real-stream-e2e-shop-turn2",
                trace_id="real-stream-e2e-shop-trace2",
                message="它附近有什么推荐菜",
                client_context={"page": "assistant"},
            )
            self.assertIsNotNone(shop_turn2.final_payload)
            self.assertFalse(self._has_stage(shop_turn2.events, "clarification_card"))
            self.assertNotEqual(shop_turn2.final_payload.get("response_mode"), "ask_clarification")
            self.assertNotIn("补充一下城市", shop_turn2.final_payload.get("answer_text", ""))
            self.assertFalse(
                self._contains_any_text(
                    shop_turn2.final_payload.get("answer_text", ""),
                    ("Tool result", "raw_tool_result", "normalized_output", "{'shop_id'", "shop_detail", "clarification_slot"),
                )
            )
            shop_state_turn2 = self._read_session_state(redis_client, session_shop)
            self.assertEqual(shop_state_turn2.get("current_shop"), "山城一锅")
            self.assertEqual(shop_state_turn2.get("selected_shop_name"), "山城一锅")

            turn3 = self._call_stream(
                client,
                session_id=session_blocked,
                turn_id="real-stream-e2e-blocked-turn1",
                trace_id="real-stream-e2e-blocked-trace1",
                message="附近有什么推荐菜",
                client_context={"page": "assistant"},
            )
            self.assertIsNotNone(turn3.final_payload)
            self.assertIn("城市", turn3.final_payload.get("answer_text", ""))

            turn4 = self._call_stream(
                client,
                session_id=session_blocked,
                turn_id="real-stream-e2e-blocked-turn2",
                trace_id="real-stream-e2e-blocked-trace2",
                message="北极",
                client_context={"page": "assistant"},
            )
            self.assertIsNotNone(turn4.final_payload)
            self.assertFalse(self._has_stage(turn4.events, "consume_pending_clarification"))
            self.assertIn("不太适合本地生活推荐", turn4.final_payload.get("answer_text", ""))
            blocked_state = self._read_session_state(redis_client, session_blocked)
            self.assertIsNotNone(blocked_state.get("pending_clarification"))

            if os.getenv("REAL_STREAM_E2E_EMIT_SUMMARY") == "1":
                print(
                    json.dumps(
                        {
                            "recap": self._summarize(recap),
                            "case3_turn1": self._summarize(turn1),
                            "case3_turn2": self._summarize(turn2),
                            "shop_turn1": self._summarize(shop_turn1),
                            "shop_turn2": self._summarize(shop_turn2),
                            "case4_turn1": self._summarize(turn3),
                            "case4_turn2": self._summarize(turn4),
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
        finally:
            client.close()

    def _call_stream(
        self,
        client: httpx.Client,
        *,
        session_id: str,
        turn_id: str,
        trace_id: str,
        message: str,
        client_context: dict[str, Any],
    ) -> _RealCallResult:
        stream_url = _stream_url()
        if stream_url.endswith(":8000/internal/v1/chat/stream"):
            payload = {
                "message": message,
                "user_id": "real-stream-e2e-user",
                "session_id": session_id,
                "turn_id": turn_id,
                "trace_id": trace_id,
                "page": "assistant",
                "context": client_context,
            }
            headers = {
                "Accept": "text/event-stream",
                "Connection": "close",
                "X-Internal-Token": _load_env_value("LEARNING_AGENT_INTERNAL_API_TOKEN", ""),
            }
        else:
            payload = {
                "message": message,
                "sessionId": session_id,
                "turnId": turn_id,
                "traceId": trace_id,
                "page": "assistant",
                "context": client_context,
            }
            headers = {"Accept": "text/event-stream", "Connection": "close"}
        raw_parts: list[str] = []
        status_code: int | None = None
        try:
            with client.stream(
                "POST",
                stream_url,
                json=payload,
                headers=headers,
            ) as response:
                status_code = response.status_code
                for chunk in response.iter_text():
                    if chunk:
                        raw_parts.append(chunk)
        except httpx.RemoteProtocolError:
            if not raw_parts:
                raise
        raw_text = "".join(raw_parts)
        self.assertEqual(status_code, 200, raw_text)
        events = _decode_sse(raw_text)
        final_event = _first_event(events, "final")
        clarification_event = _first_event(events, "clarification_card")
        self.assertIsNotNone(final_event, raw_text[:2000])
        return _RealCallResult(
            status_code=status_code or 0,
            events=events,
            final_payload=_extract_payload(final_event) if final_event is not None else {},
            clarification_payload=_extract_payload(clarification_event) if clarification_event is not None else None,
        )

    def _read_session_state(self, redis_client: redis.Redis, session_id: str) -> dict[str, Any]:
        raw = redis_client.get(_session_state_key(session_id))
        self.assertIsNotNone(raw, f"session state missing for {session_id}")
        return json.loads(raw)

    def _has_stage(self, events: Iterable[dict[str, Any]], stage_name: str) -> bool:
        for event in events:
            payload = _extract_payload(event)
            if payload.get("stage") == stage_name:
                return True
            if payload.get("current_stage") == stage_name:
                return True
            if payload.get("details", {}).get("stage") == stage_name:
                return True
        return False

    def _contains_text(self, events: Iterable[dict[str, Any]], text: str) -> bool:
        for event in events:
            payload = _extract_payload(event)
            for value in payload.values():
                if isinstance(value, str) and text in value:
                    return True
        return False

    def _contains_any_text(self, text: str, needles: Iterable[str]) -> bool:
        return any(needle in text for needle in needles)

    def _summarize(self, result: _RealCallResult) -> dict[str, Any]:
        final_text = result.final_payload.get("answer_text", "")
        return {
            "status_code": result.status_code,
            "event_types": [event.get("event_type") for event in result.events],
            "final_answer": final_text,
            "final_mode": result.final_payload.get("mode"),
            "final_response_mode": result.final_payload.get("response_mode"),
            "final_route_reason": result.final_payload.get("route_reason"),
            "current_city": result.final_payload.get("current_city"),
            "current_shop": result.final_payload.get("current_shop"),
            "pending_clarification": result.final_payload.get("pending_clarification"),
            "clarification_question": (result.clarification_payload or {}).get("question"),
            "has_forbidden_text": self._contains_any_text(
                final_text,
                (
                    "Tool result",
                    "raw_tool_result",
                    "normalized_output",
                    "{'shop_id'",
                    "shop_detail",
                    "clarification_slot",
                ),
            ),
        }


if __name__ == "__main__":
    unittest.main()
