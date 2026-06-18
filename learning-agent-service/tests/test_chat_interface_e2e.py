from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4
import unittest

from fastapi.testclient import TestClient

TESTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent
SRC_ROOT = PROJECT_ROOT / "src"
for candidate in (str(TESTS_DIR), str(PROJECT_ROOT), str(SRC_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import _bootstrap  # noqa: F401

from chat_test_client import ChatStreamTestClient
from learning_agent_service.app import create_app
from learning_agent_service.api.contracts import ChatStreamRequest, SseEnvelope
from learning_agent_service.config import get_settings


def _envelope(
    *,
    event_type: str,
    trace_id: str,
    session_id: str,
    turn_id: str,
    workflow_version: str,
    payload: dict[str, Any],
) -> SseEnvelope:
    return SseEnvelope(
        event_type=event_type,
        trace_id=trace_id,
        session_id=session_id,
        turn_id=turn_id,
        timestamp=datetime.now(timezone.utc),
        workflow_version=workflow_version,
        payload=payload,
    )


def _parse_sse(raw_text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for block in raw_text.replace("\r\n", "\n").strip().split("\n\n"):
        if not block.strip():
            continue
        event_type = "message"
        event_id = None
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("id:"):
                event_id = line.split(":", 1)[1].strip()
            elif line.startswith("event:"):
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
        events.append({"id": event_id, "event_type": event_type, "data": data})
    return events


@dataclass
class _Scenario:
    route_decision: str
    route_reason: str
    answer_style: str
    branch: str
    answer_text: str
    tool_calls: list[dict[str, Any]]
    metrics: dict[str, Any]


class _ScenarioChatService:
    def __init__(self) -> None:
        self.requests: list[ChatStreamRequest] = []

    def run_stream(self, request: ChatStreamRequest):
        self.requests.append(request)
        scenario = self._scenario_for(request)
        turn_id = request.turn_id or f"turn-{uuid4().hex[:8]}"
        trace_id = request.trace_id
        workflow_version = "test-workflow"

        yield _envelope(
            event_type="ack",
            trace_id=trace_id,
            session_id=request.session_id,
            turn_id=turn_id,
            workflow_version=workflow_version,
            payload={
                "message": "accepted",
                "accepted_at": datetime.now(timezone.utc).isoformat(),
                "current_stage": "accepted",
                "stage_status": "completed",
                "route_reason": "request_accepted",
            },
        )

        yield _envelope(
            event_type="delta",
            trace_id=trace_id,
            session_id=request.session_id,
            turn_id=turn_id,
            workflow_version=workflow_version,
            payload={
                "delta": "处理中",
                "answer_text": "处理中",
            },
        )

        for index, tool_call in enumerate(scenario.tool_calls, start=1):
            yield _envelope(
                event_type="tool_call",
                trace_id=trace_id,
                session_id=request.session_id,
                turn_id=turn_id,
                workflow_version=workflow_version,
                payload={
                    "tool_name": tool_call["tool_name"],
                    "tool_call_id": f"tool-{index}",
                    "input_summary": dict(tool_call.get("input_summary") or {}),
                },
            )
            yield _envelope(
                event_type="tool_result",
                trace_id=trace_id,
                session_id=request.session_id,
                turn_id=turn_id,
                workflow_version=workflow_version,
                payload={
                    "tool_name": tool_call["tool_name"],
                    "tool_call_id": f"tool-{index}",
                    "status": "success",
                    "degraded": False,
                    "retryable": False,
                    "output": dict(tool_call.get("output") or {}),
                },
            )

        yield _envelope(
            event_type="final",
            trace_id=trace_id,
            session_id=request.session_id,
            turn_id=turn_id,
            workflow_version=workflow_version,
            payload={
                "answer_text": scenario.answer_text,
                "route_decision": scenario.route_decision,
                "route_reason": scenario.route_reason,
                "answer_style": scenario.answer_style,
                "used_tools": [tool.get("tool_name") for tool in scenario.tool_calls],
                "metrics": {
                    **scenario.metrics,
                    "routing_trace": {
                        "global_intent_source": "router_agent",
                        "semantic_frame_source": "router_agent",
                        "validator_decision": "validated",
                        "fallback_used": False,
                        "legacy_router_used": False,
                        "final_dispatch_basis": "canonical_route+required_action+facet_plan+required_sources",
                        "canonical_route": scenario.branch,
                    },
                },
                "context": dict(request.client_context or {}),
            },
        )

    def _scenario_for(self, request: ChatStreamRequest) -> _Scenario:
        compact = (request.message or "").replace(" ", "")
        context = dict(request.client_context or {})
        has_shop_context = bool(
            context.get("shopId")
            or context.get("shop_id")
            or context.get("shopName")
            or context.get("shop_name")
        )

        if "忽略之前的指令" in compact or "systemprompt" in compact.lower():
            return _Scenario(
                route_decision="reject",
                route_reason="jailbreak_detected",
                answer_style="rejected",
                branch="jailbreak",
                answer_text="抱歉，这个请求涉及安全限制，我不能继续处理。",
                tool_calls=[],
                metrics={
                    "route_gate": {"branch": "blocked", "required_action": "reject"},
                    "routing_decision": {"required_action": "reject"},
                },
            )

        if "推荐" in compact and ("附近" in compact or "周边" in compact or "几家" in compact):
            return _Scenario(
                route_decision="recommendation",
                route_reason="route_to_recommendation_tool",
                answer_style="multi_shop_recommendation",
                branch="recommendation",
                answer_text="1. A店\n2. B店\n3. C店",
                tool_calls=[
                    {
                        "tool_name": "search_recommendations",
                        "input_summary": {"query": request.message},
                        "output": {"shops": ["A店", "B店", "C店"]},
                    }
                ],
                metrics={
                    "route_gate": {"branch": "recommendation", "required_action": "tool_call"},
                    "routing_decision": {"required_action": "tool_call"},
                    "recommendation_mode": True,
                },
            )

        if "比较" in compact or "对比" in compact or "哪个好" in compact:
            return _Scenario(
                route_decision="comparison",
                route_reason="route_to_comparison_tool",
                answer_style="comparison",
                branch="comparison",
                answer_text="海底捞和巴奴各有优点，适合的场景不同。",
                tool_calls=[
                    {
                        "tool_name": "compare_shop_a",
                        "input_summary": {"shop": "海底捞"},
                        "output": {"shop": "海底捞"},
                    },
                    {
                        "tool_name": "compare_shop_b",
                        "input_summary": {"shop": "巴奴"},
                        "output": {"shop": "巴奴"},
                    },
                ],
                metrics={
                    "route_gate": {"branch": "comparison", "required_action": "tool_call"},
                    "routing_decision": {"required_action": "tool_call"},
                },
            )

        if "预约" in compact or "订座" in compact or "下单" in compact:
            return _Scenario(
                route_decision="transaction",
                route_reason="route_to_transaction_tool",
                answer_style="transaction",
                branch="transaction",
                answer_text="已为你发起预约/交易流程，需要你确认后继续。",
                tool_calls=[
                    {
                        "tool_name": "prepare_transaction",
                        "input_summary": {"message": request.message},
                        "output": {"requires_approval": True},
                    }
                ],
                metrics={
                    "route_gate": {"branch": "tool", "required_action": "tool_call"},
                    "routing_decision": {"required_action": "tool_call"},
                    "approval_required": True,
                },
            )

        if "有券吗" in compact or "优惠券" in compact or "营业" in compact or "多远" in compact or "怎么样" in compact:
            return _Scenario(
                route_decision="tool_call",
                route_reason="route_to_single_shop_tool",
                answer_style="single_shop_review",
                branch="tool",
                answer_text="这家店的事实信息已经查到。",
                tool_calls=[
                    {
                        "tool_name": "query_shop_detail",
                        "input_summary": {"message": request.message},
                        "output": {"shop": context.get("shopName") or context.get("shop_name") or "目标店"},
                    }
                ],
                metrics={
                    "route_gate": {"branch": "tool", "required_action": "tool_call"},
                    "routing_decision": {"required_action": "tool_call"},
                    "single_shop_mode": True,
                },
            )

        if "这家" in compact or "它" in compact or "哪家" in compact:
            return _Scenario(
                route_decision="clarify",
                route_reason="missing_shop_context",
                answer_style="clarification",
                branch="clarify",
                answer_text="请补充一下店名或具体信息，我再继续帮你查。",
                tool_calls=[],
                metrics={
                    "route_gate": {"branch": "clarify", "required_action": "clarify"},
                    "routing_decision": {"required_action": "clarify"},
                    "clarification_needed": True,
                },
            )

        return _Scenario(
            route_decision="direct_answer",
            route_reason="route_to_direct",
            answer_style="direct_chat",
            branch="direct",
            answer_text="可以，我在。你也可以继续问我本地生活相关问题。",
            tool_calls=[],
            metrics={
                "route_gate": {"branch": "direct", "required_action": "direct_answer"},
                "routing_decision": {"required_action": "direct_answer"},
            },
        )


class _ErroringChatService:
    def run_stream(self, request: ChatStreamRequest):
        raise RuntimeError("service unavailable")


class ChatInterfaceEndpointE2ETestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.fake_service = _ScenarioChatService()
        self.app = create_app(self.fake_service)
        self.client = TestClient(self.app)
        self.token = get_settings().internal_api_token

    def _post_stream(self, payload: dict[str, Any], *, token: str | None = None) -> tuple[int, dict[str, str], str]:
        headers = {
            "Accept": "text/event-stream",
        }
        if token is not None:
            headers["X-Internal-Token"] = token
        with self.client.stream("POST", "/internal/v1/chat/stream", json=payload, headers=headers) as response:
            raw = "".join(chunk for chunk in response.iter_text())
            return response.status_code, dict(response.headers), raw

    def test_stream_endpoint_emits_sse_contract_and_preserves_request_context(self) -> None:
        payload = {
            "user_id": "user-1",
            "session_id": "session-1",
            "trace_id": "trace-1",
            "message": "海底捞有券吗",
            "turn_id": "turn-1",
            "page": "assistant",
            "context": {
                "shopName": "海底捞水晶城店",
                "shopId": "1001",
                "current_city": "北京",
            },
        }

        status_code, headers, raw = self._post_stream(payload, token=self.token)
        events = _parse_sse(raw)

        self.assertEqual(status_code, 200)
        self.assertTrue(headers.get("content-type", "").startswith("text/event-stream"))
        self.assertEqual(headers.get("cache-control"), "no-cache")
        self.assertEqual(headers.get("connection"), "keep-alive")
        self.assertEqual(headers.get("x-accel-buffering"), "no")

        self.assertEqual([event["event_type"] for event in events], ["ack", "delta", "tool_call", "tool_result", "final"])
        self.assertEqual([event["id"] for event in events], [
            "session-1:turn-1:1",
            "session-1:turn-1:2",
            "session-1:turn-1:3",
            "session-1:turn-1:4",
            "session-1:turn-1:5",
        ])
        self.assertEqual(self.fake_service.requests[0].client_context, payload["context"])
        final_payload = events[-1]["data"]["payload"]
        self.assertEqual(final_payload["metrics"]["route_gate"]["branch"], "tool")
        self.assertEqual(final_payload["metrics"]["routing_decision"]["required_action"], "tool_call")
        self.assertTrue(final_payload["metrics"]["single_shop_mode"])
        self.assertEqual(
            final_payload["metrics"]["routing_trace"]["final_dispatch_basis"],
            "canonical_route+required_action+facet_plan+required_sources",
        )
        self.assertEqual(final_payload["context"]["shopName"], "海底捞水晶城店")

    def test_stream_endpoint_accepts_context_alias(self) -> None:
        payload = {
            "user_id": "user-2",
            "session_id": "session-2",
            "trace_id": "trace-2",
            "message": "附近有什么推荐的餐厅？",
            "context": {
                "city": "北京",
                "current_city": "北京",
            },
        }

        status_code, _, raw = self._post_stream(payload, token=self.token)
        events = _parse_sse(raw)

        self.assertEqual(status_code, 200)
        self.assertEqual(self.fake_service.requests[0].client_context, payload["context"])
        final_payload = events[-1]["data"]["payload"]
        self.assertEqual(final_payload["metrics"]["route_gate"]["branch"], "recommendation")
        self.assertEqual(final_payload["metrics"]["routing_decision"]["required_action"], "tool_call")
        self.assertTrue(final_payload["metrics"]["recommendation_mode"])
        self.assertEqual(len([event for event in events if event["event_type"] == "tool_call"]), 1)

    def test_stream_endpoint_requires_internal_token(self) -> None:
        payload = {
            "user_id": "user-3",
            "session_id": "session-3",
            "trace_id": "trace-3",
            "message": "你好",
        }

        status_code, _, raw = self._post_stream(payload, token=None)

        self.assertEqual(status_code, 401)
        self.assertIn("LEARN-1401", raw)
        self.assertIn("Missing or invalid internal token", raw)

    def test_stream_endpoint_maps_runtime_errors_to_503(self) -> None:
        app = create_app(_ErroringChatService())
        client = TestClient(app)
        payload = {
            "user_id": "user-4",
            "session_id": "session-4",
            "trace_id": "trace-4",
            "message": "海底捞怎么样",
        }

        with client.stream(
            "POST",
            "/internal/v1/chat/stream",
            json=payload,
            headers={
                "Accept": "text/event-stream",
                "X-Internal-Token": get_settings().internal_api_token,
            },
        ) as response:
            body = response.read().decode("utf-8")

        self.assertEqual(response.status_code, 503)
        self.assertIn("LEARN-5600", body)
        self.assertIn("chat_stream", body)


class LiveChatInterfaceSmokeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.client = ChatStreamTestClient()

    def test_live_chat_stream_returns_non_empty_answer_and_trace(self) -> None:
        result = self.client.post_message(
            message="海底捞怎么样？",
            session_id=f"live-smoke-{uuid4().hex[:8]}",
            extra_payload={
                "shopName": "海底捞水晶城店",
                "shopId": 5,
            },
        )

        self.assertTrue(result.final_answer)
        self.assertTrue(result.events)
        self.assertEqual(result.metrics.get("phase5_trace", {}).get("runner_kind"), "langgraph")
        self.assertIn("routing_decision", result.metrics)
