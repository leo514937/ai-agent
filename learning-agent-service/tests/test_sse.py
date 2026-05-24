from __future__ import annotations

import unittest
from datetime import datetime
import threading

import _bootstrap  # noqa: F401
from pydantic import ValidationError

from learning_agent_service.api.contracts import (
    ClarificationCardPayload,
    ClarificationOptionPayload,
    EventType,
    FinalPayload,
    RetrievalStartedPayload,
    SseEnvelope,
    ToolResultPayload,
)
from learning_agent_service.api.sse import build_event_id, serialize_envelope, stream_envelopes


class SseEncodingTestCase(unittest.TestCase):
    def _envelope(self) -> SseEnvelope:
        return SseEnvelope(
            event_type=EventType.FINAL,
            trace_id="trace-1",
            session_id="session-1",
            turn_id="turn-1",
            timestamp=datetime(2026, 3, 27, 12, 0, 0),
            workflow_version="learn-agent/v1",
            payload=FinalPayload(
                answer_text="我按离你近、人均150左右、适合带爸妈、环境安静筛了几家。",
                citations=[
                    {
                        "chunk_id": "review-1",
                        "document_id": "shop-1",
                        "source_type": "review_summary",
                        "score": 0.91,
                        "title": "环境安静",
                        "locator": "某某家常菜",
                    }
                ],
                mode="recommend",
                source="local-life-agent",
                page="meituan_search_box",
                current_topic="某某家常菜",
                selected_shop_id=101,
                cards=[
                    {
                        "type": "shop_card",
                        "shop_id": 101,
                        "title": "某某家常菜",
                        "subtitle": "1.2km · 人均145元 · 评分4.8",
                        "badges": ["安静", "适合家庭"],
                        "reason": "评论摘要中多次提到环境安静，适合家庭聚餐。",
                        "actions": [
                            {"type": "open_shop", "label": "查看详情", "payload": {"shop_id": 101}},
                        ],
                    }
                ],
                shops=[{"id": 101, "name": "某某家常菜"}],
                vouchers=[{"id": 201, "shopId": 101, "title": "满100减20"}],
                suggested_replies=[
                    {"label": "只看今晚可订的", "prompt": "只看今晚可订的"},
                ],
                ranked_candidates=[{"shop_id": 101, "name": "某某家常菜", "rank_score": 0.93}],
                retrieval_summary={
                    "retrieval_strategy": "hybrid_catalog+java_business",
                    "retrieval_hit_count": 1,
                    "evidence_used_count": 1,
                    "evidence_status": "OK",
                },
                grounding_status="grounded",
                confidence=0.93,
                context={"raw_query": "今晚想带爸妈吃饭，别太吵，人均150左右，离我近一点"},
            ).model_dump(mode="json"),
        )

    def test_build_event_id(self) -> None:
        self.assertEqual(build_event_id("s1", "t1", 3), "s1:t1:3")

    def test_serialize_envelope(self) -> None:
        payload = serialize_envelope(self._envelope(), seq=2)
        self.assertIn("id: session-1:turn-1:2", payload)
        self.assertIn("event: final", payload)
        self.assertIn('"workflow_version":"learn-agent/v1"', payload)
        self.assertIn('"mode":"recommend"', payload)
        self.assertIn('"source":"local-life-agent"', payload)
        self.assertIn('"cards":[{"type":"shop_card"', payload)

    def test_stream_envelopes_preserves_order(self) -> None:
        chunks = list(stream_envelopes([self._envelope(), self._envelope()]))
        self.assertEqual(len(chunks), 2)
        self.assertIn("session-1:turn-1:1", chunks[0])
        self.assertIn("session-1:turn-1:2", chunks[1])

    def test_stream_envelopes_emits_keepalive_when_producer_is_slow(self) -> None:
        release = threading.Event()

        def _slow_events():
            yield self._envelope()
            release.wait(timeout=1.0)

        stream = stream_envelopes(_slow_events(), keepalive_seconds=0.01)
        first = next(stream)
        second = next(stream)

        self.assertIn("event: final", first)
        self.assertIn("event: heartbeat", second)
        self.assertIn('"route_reason":"stream_keepalive"', second)

        release.set()
        with self.assertRaises(StopIteration):
            next(stream)

    def test_serialize_clarification_card_with_structured_options(self) -> None:
        envelope = SseEnvelope(
            event_type=EventType.CLARIFICATION_CARD,
            trace_id="trace-1",
            session_id="session-1",
            turn_id="turn-2",
            timestamp=datetime(2026, 3, 27, 12, 0, 0),
            workflow_version="learn-agent/v1",
            payload=ClarificationCardPayload(
                card_id="clarify-1",
                question="你更想吃什么类型？",
                options=[
                    ClarificationOptionPayload(id="1", label="家常菜", value="推荐家常菜"),
                    ClarificationOptionPayload(id="2", label="火锅", value="推荐火锅"),
                ],
                ambiguity_type="local_life",
            ).model_dump(mode="json"),
        )
        chunk = serialize_envelope(envelope, seq=1)
        self.assertIn('"options":[{"id":"1","label":"家常菜","value":"推荐家常菜","description":null}', chunk)

    def test_serialize_envelope_validates_payload_shape(self) -> None:
        envelope = SseEnvelope(
            event_type=EventType.CLARIFICATION_CARD,
            trace_id="trace-1",
            session_id="session-1",
            turn_id="turn-2",
            timestamp=datetime(2026, 3, 27, 12, 0, 0),
            workflow_version="learn-agent/v1",
            payload={
                "card_id": "clarify-1",
                "question": "你更想吃什么类型？",
                "options": ["家常菜"],
            },
        )
        with self.assertRaises(ValidationError):
            serialize_envelope(envelope, seq=1)

    def test_serialize_retrieval_started_event(self) -> None:
        envelope = SseEnvelope(
            event_type=EventType.RETRIEVAL_STARTED,
            trace_id="trace-1",
            session_id="session-1",
            turn_id="turn-3",
            timestamp=datetime(2026, 3, 27, 12, 0, 0),
            workflow_version="learn-agent/v1",
            payload=RetrievalStartedPayload(
                semantic_query="适合带爸妈吃饭 环境安静 人均150",
                keyword_query="带爸妈 安静 人均150 附近 餐厅",
                retrieval_filters={"city": "北京", "radius_km": 3, "scene": "family_dinner"},
            ).model_dump(mode="json"),
        )
        chunk = serialize_envelope(envelope, seq=3)
        self.assertIn("event: retrieval_started", chunk)
        self.assertIn('"retrieval_filters":{"city":"北京"', chunk)

    def test_serialize_tool_result_event(self) -> None:
        envelope = SseEnvelope(
            event_type=EventType.TOOL_RESULT,
            trace_id="trace-1",
            session_id="session-1",
            turn_id="turn-4",
            timestamp=datetime(2026, 3, 27, 12, 0, 0),
            workflow_version="learn-agent/v1",
            payload=ToolResultPayload(
                tool_name="search_restaurants",
                tool_call_id="call-1",
                status="success",
                degraded=False,
                retryable=False,
                output={"candidate_count": 2, "candidate_ids": [101, 102]},
            ).model_dump(mode="json"),
        )
        chunk = serialize_envelope(envelope, seq=4)
        self.assertIn("event: tool_result", chunk)
        self.assertIn('"tool_name":"search_restaurants"', chunk)
        self.assertIn('"candidate_count":2', chunk)


if __name__ == "__main__":
    unittest.main()
