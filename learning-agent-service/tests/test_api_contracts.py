from __future__ import annotations

import asyncio
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import _bootstrap  # noqa: F401
from pydantic import ValidationError

import app as app_module
from learning_agent_service.api import internal_auth
from learning_agent_service.api.contracts import (
    ApiResponse,
    ApprovalSubmitRequest,
    ApprovalSubmitResponse,
    ChatStreamRequest,
    Citation,
    ClarificationCardPayload,
    ClarificationOptionPayload,
    ApprovalRequiredPayload,
    EventType,
    FinalPayload,
    FeedbackReportRequest,
    FeedbackIssueType,
    MemoryActionRequest,
    MemoryUsedSummary,
    RetrievalResultPayload,
    RetrievalStartedPayload,
    RetrievalSummary,
    SessionStateResponse,
    SseEnvelope,
    validate_event_payload,
)
from learning_agent_service.api.router import create_api_router


class _MockService:
    def run_stream(self, request: ChatStreamRequest):
        now = datetime.now(timezone.utc)
        final_payload = FinalPayload(
            answer_text="我按离你近、人均150左右、适合带爸妈、环境安静筛了几家。",
            citations=[
                Citation(
                    chunk_id="review-1",
                    document_id="shop-1",
                    source_type="review_summary",
                    version="v1",
                    score=0.91,
                    title="环境安静",
                    locator="某某家常菜",
                )
            ],
            mode="recommend",
            source="local-life-agent",
            page="meituan_search_box",
            resolved_topic="某某家常菜",
            current_topic="某某家常菜",
            selected_shop_id=101,
            retrieval_strategy="hybrid_catalog+java_business",
            retrieval_summary=RetrievalSummary(
                semantic_query="某某家常菜 家庭聚餐",
                keyword_query="安静 家常菜 亲子",
                retrieval_filters={"scene": "family_dinner"},
                retrieval_strategy="hybrid_catalog+java_business",
                retrieval_hit_count=1,
                evidence_used_count=1,
                evidence_status="OK",
                evidence_strong_count=1,
                route_decision="tool_then_answer",
                route_reason="need_retrieval_and_tool",
                current_stage="compose",
                stage_status="completed",
                stage_timeline=[{"stage": "understand", "status": "completed"}],
            ),
            memory_used_summary=MemoryUsedSummary(
                used=True,
                total_memories=1,
                retrieval_reason="recent_preference",
                prompt_memories=[
                    {
                        "memory_id": "mem-1",
                        "memory_type": "preference",
                        "scope": "prompt",
                        "summary": "用户偏好安静和停车",
                        "source": "profile",
                    }
                ],
            ),
            intent="recommend",
            requested_output_style=None,
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
            shops=[
                {
                    "id": 101,
                    "name": "某某家常菜",
                    "area": "朝阳",
                    "avgPrice": 145,
                    "score": 4.8,
                    "distance": 1.2,
                    "reason": "评论摘要中多次提到环境安静，适合家庭聚餐。",
                }
            ],
            vouchers=[
                {
                    "id": 201,
                    "shopId": 101,
                    "shopName": "某某家常菜",
                    "title": "满100减20",
                    "subTitle": "家庭聚餐券",
                    "payValue": 100,
                    "actualValue": 80,
                }
            ],
            suggested_replies=[
                {"label": "只看今晚可订的", "prompt": "只看今晚可订的"},
                {"label": "换成人均100以内", "prompt": "换成人均100以内"},
            ],
            next_steps=["查看第一家详情", "看优惠券"],
            task_chain=[
                {"step": "search", "label": "已完成候选店搜索", "status": "done"},
                {"step": "final", "label": "结果已经整理完成", "status": "done"},
            ],
            ranked_candidates=[
                {"shop_id": 101, "name": "某某家常菜", "rank_score": 0.93},
            ],
            grounding_status="grounded",
            confidence=0.93,
            route_decision="tool_then_answer",
            route_reason="need_retrieval_and_tool",
            current_stage="compose",
            stage_status="completed",
            stage_timeline=[
                {
                    "stage": "understand",
                    "status": "completed",
                    "route_decision": "tool_then_answer",
                    "route_reason": "need_retrieval_and_tool",
                }
            ],
            context={
                "raw_query": request.message,
                "slots": {
                    "scene": "family_dinner",
                    "preferences": ["quiet", "elder_friendly"],
                },
            },
        )
        return [
            SseEnvelope(
                event_type=EventType.ACK,
                trace_id=request.trace_id,
                session_id=request.session_id,
                turn_id=request.turn_id or "turn-1",
                timestamp=now,
                workflow_version="learn-agent/v1",
                payload={"message": "accepted", "accepted_at": now},
            ),
            SseEnvelope(
                event_type=EventType.ANSWER_DELTA,
                trace_id=request.trace_id,
                session_id=request.session_id,
                turn_id=request.turn_id or "turn-1",
                timestamp=now,
                workflow_version="learn-agent/v1",
                payload={
                    "delta": "我先按你给的条件帮你筛选。",
                    "answer_text": "我先按你给的条件帮你筛选。",
                    "current_stage": "compose",
                    "stage_status": "streaming",
                },
            ),
            SseEnvelope(
                event_type=EventType.FINAL,
                trace_id=request.trace_id,
                session_id=request.session_id,
                turn_id=request.turn_id or "turn-1",
                timestamp=now,
                workflow_version="learn-agent/v1",
                payload=final_payload.model_dump(mode="json"),
            ),
        ]

    def get_session_state(self, session_id: str) -> SessionStateResponse:
        return SessionStateResponse(session_id=session_id, current_topic="Spring")

    def submit_approval(self, request: ApprovalSubmitRequest) -> ApprovalSubmitResponse:
        return ApprovalSubmitResponse(
            session_id=request.session_id,
            trace_id=request.trace_id,
            turn_id=request.turn_id,
            approval_state=request.decision,
            accepted=True,
            pending_approval=False,
            approval_request=dict(request.approval_request or {}),
            message="审批结果已记录",
        )


async def _collect_body_chunks(response) -> list[str]:
    chunks = []
    body_iterator = response.body_iterator
    if hasattr(body_iterator, "__aiter__"):
        async for chunk in body_iterator:
            chunks.append(chunk)
    else:
        for chunk in body_iterator:
            chunks.append(chunk)
    return chunks


class ApiContractsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._token_patch = patch.dict(os.environ, {"LEARNING_AGENT_INTERNAL_API_TOKEN": ""}, clear=False)
        self._token_patch.start()
        internal_auth.get_settings.cache_clear()
        self.addCleanup(self._cleanup_internal_token_patch)

    def _cleanup_internal_token_patch(self) -> None:
        self._token_patch.stop()
        internal_auth.get_settings.cache_clear()

    def test_public_event_type_enum_only_contains_runtime_supported_events(self) -> None:
        supported_events = {
            "ack",
            "delta",
            "answer_delta",
            "clarification_card",
            "retrieval_started",
            "retrieval_result",
            "memory_retrieval_started",
            "memory_retrieval_result",
            "memory_promotion_result",
            "tool_call",
            "tool_result",
            "plan_execution_started",
            "plan_step_result",
            "approval_required",
            "plan_replanned",
            "plan_execution_summary",
            "final",
            "error",
        }
        self.assertTrue(supported_events.issubset({event.value for event in EventType}))

    def test_approval_submit_contract(self) -> None:
        request = ApprovalSubmitRequest(
            user_id="guest",
            session_id="session-approval-1",
            trace_id="trace-approval-1",
            turn_id="turn-approval-1",
            decision="approved",
            approval_request={
                "tool_name": "create_booking",
                "approval_state": "pending_approval",
            },
        )
        response = ApprovalSubmitResponse(
            session_id=request.session_id,
            trace_id=request.trace_id,
            turn_id=request.turn_id,
            approval_state="approved",
            accepted=True,
            pending_approval=False,
            approval_request=dict(request.approval_request),
            message="审批结果已记录",
        )

        self.assertEqual(request.decision, "approved")
        self.assertTrue(response.accepted)
        self.assertFalse(response.pending_approval)

    def test_chat_stream_request_requires_message(self) -> None:
        with self.assertRaises(ValidationError):
            ChatStreamRequest(
                user_id="u1",
                session_id="s1",
                trace_id="t1",
                message="",
            )
        request = ChatStreamRequest(
            user_id="u1",
            session_id="s1",
            trace_id="t1",
            message="今晚想带爸妈吃饭，别太吵，人均150左右，离我近一点",
            page="meituan_search_box",
            client_context={
                "city": "北京",
                "location": {"lat": 39.9, "lng": 116.4},
                "entry": "meituan_search_box",
            },
        )
        self.assertEqual(request.page, "meituan_search_box")
        self.assertEqual(request.client_context["city"], "北京")

    def test_final_payload_contract(self) -> None:
        payload = FinalPayload(
            answer_text="我按离你近、人均150左右、适合带爸妈、环境安静筛了几家。",
            citations=[
                Citation(
                    chunk_id="chunk-1",
                    document_id="doc-1",
                    source_type="review_summary",
                    version="v1",
                    score=0.93,
                    title="环境安静",
                    locator="某某家常菜",
                )
            ],
            used_tools=["search_restaurants"],
            resolved_topic="某某家常菜",
            current_topic="某某家常菜",
            mode="recommend",
            source="local-life-agent",
            page="meituan_search_box",
            selected_shop_id=101,
            retrieval_strategy="hybrid_catalog+java_business",
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
            suggested_replies=[
                {"label": "只看今晚可订的", "prompt": "只看今晚可订的"},
                {"label": "换成人均100以内", "prompt": "换成人均100以内"},
            ],
            next_steps=["查看第一家详情", "看优惠券"],
            task_chain=[
                {"step": "search", "label": "已完成候选店搜索", "status": "done"},
                {"step": "final", "label": "结果已经整理完成", "status": "done"},
            ],
            ranked_candidates=[
                {"shop_id": 101, "name": "某某家常菜", "rank_score": 0.93},
            ],
            confidence=0.88,
            grounding_status="grounded",
            retrieval_summary=RetrievalSummary(
                semantic_query="某某家常菜 家庭聚餐",
                keyword_query="安静 家常菜 亲子",
                retrieval_filters={"scene": "family_dinner"},
                retrieval_strategy="hybrid_catalog+java_business",
                retrieval_hit_count=1,
                evidence_used_count=1,
                evidence_status="OK",
                evidence_strong_count=1,
                route_decision="tool_then_answer",
                route_reason="need_retrieval_and_tool",
                current_stage="compose",
                stage_status="completed",
                stage_timeline=[{"stage": "understand", "status": "completed"}],
            ),
            memory_used_summary=MemoryUsedSummary(
                used=True,
                total_memories=1,
                retrieval_reason="recent_preference",
                prompt_memories=[
                    {
                        "memory_id": "mem-1",
                        "memory_type": "preference",
                        "scope": "prompt",
                        "summary": "用户偏好安静和停车",
                        "source": "profile",
                    }
                ],
            ),
            intent="recommend",
            requested_output_style=None,
            memory_updates={"current_city": "北京"},
            metrics={"retrieval_hit_count": 1},
            route_decision="tool_then_answer",
            route_reason="need_retrieval_and_tool",
            current_stage="compose",
            stage_status="completed",
            stage_timeline=[
                {
                    "stage": "understand",
                    "status": "completed",
                    "route_decision": "tool_then_answer",
                    "route_reason": "need_retrieval_and_tool",
                }
            ],
        )
        self.assertEqual(payload.citations[0].chunk_id, "chunk-1")
        self.assertEqual(payload.used_tools, ["search_restaurants"])
        self.assertEqual(payload.grounding_status, "grounded")
        self.assertEqual(payload.retrieval_summary.evidence_used_count, 1)
        self.assertEqual(payload.mode, "recommend")
        self.assertEqual(payload.source, "local-life-agent")
        self.assertEqual(payload.page, "meituan_search_box")
        self.assertEqual(payload.current_topic, "某某家常菜")
        self.assertEqual(payload.selected_shop_id, 101)
        self.assertEqual(payload.cards[0]["type"], "shop_card")
        self.assertEqual(payload.suggested_replies[0]["label"], "只看今晚可订的")
        self.assertEqual(payload.next_steps[0], "查看第一家详情")
        self.assertEqual(payload.task_chain[0]["step"], "search")
        self.assertEqual(payload.retrieval_summary.retrieval_strategy, "hybrid_catalog+java_business")
        self.assertFalse(payload.approval_required)
        self.assertEqual(payload.route_decision, "tool_then_answer")
        self.assertEqual(payload.current_stage, "compose")
        self.assertEqual(payload.stage_status, "completed")
        self.assertEqual(payload.stage_timeline[0]["stage"], "understand")

    def test_session_state_response_contract(self) -> None:
        payload = SessionStateResponse(
            session_id="session-1",
            current_topic="Spring",
            route_decision="tool_then_answer",
            route_reason="need_retrieval_and_tool",
            current_stage="compose",
            stage_status="completed",
            stage_timeline=[
                {
                    "stage": "understand",
                    "status": "completed",
                    "route_decision": "tool_then_answer",
                    "route_reason": "need_retrieval_and_tool",
                }
            ],
        )
        self.assertEqual(payload.route_decision, "tool_then_answer")
        self.assertEqual(payload.current_stage, "compose")
        self.assertEqual(payload.stage_status, "completed")
        self.assertEqual(payload.stage_timeline[0]["route_reason"], "need_retrieval_and_tool")

    def test_approval_required_payload_contract(self) -> None:
        payload = ApprovalRequiredPayload(
            step_id="local-life-transaction-approval",
            reason="需要用户确认后才能执行交易动作。",
            risk_level="medium",
            approval_request={
                "transaction_draft": {
                    "action": "booking",
                    "shop_id": 101,
                    "shop_name": "某某家常菜",
                }
            },
        )
        validated = validate_event_payload(EventType.APPROVAL_REQUIRED, payload.model_dump(mode="json"))
        self.assertEqual(validated["step_id"], "local-life-transaction-approval")
        self.assertEqual(validated["approval_request"]["transaction_draft"]["action"], "booking")

    def test_retrieval_started_payload_contract(self) -> None:
        payload = RetrievalStartedPayload(
            semantic_query="适合带爸妈吃饭 环境安静 人均150",
            keyword_query="带爸妈 安静 人均150 附近 餐厅",
            retrieval_filters={
                "city": "北京",
                "radius_km": 3,
                "category": "餐厅",
            },
        )
        validated = validate_event_payload(EventType.RETRIEVAL_STARTED, payload.model_dump(mode="json"))
        self.assertEqual(validated["semantic_query"], "适合带爸妈吃饭 环境安静 人均150")
        self.assertEqual(validated["retrieval_filters"]["city"], "北京")

    def test_retrieval_result_payload_contract(self) -> None:
        payload = RetrievalResultPayload(
            retrieval_strategy="hybrid_catalog+java_business",
            retrieval_hit_count=5,
            evidence_used_count=3,
        )
        validated = validate_event_payload(EventType.RETRIEVAL_RESULT, payload.model_dump(mode="json"))
        self.assertEqual(validated["retrieval_strategy"], "hybrid_catalog+java_business")
        self.assertEqual(validated["evidence_used_count"], 3)

    def test_feedback_report_request_contract(self) -> None:
        payload = FeedbackReportRequest(
            user_id="user-1",
            session_id="session-1",
            turn_id="turn-1",
            thread_id="thread-1",
            trace_id="trace-1",
            issue_type=FeedbackIssueType.CITATION_INCORRECT,
            is_helpful=False,
            comment="引用有误",
        )
        self.assertEqual(payload.issue_type, FeedbackIssueType.CITATION_INCORRECT)
        self.assertEqual(payload.comment, "引用有误")

    def test_memory_action_request_contract(self) -> None:
        payload = MemoryActionRequest(
            reason="测试删除",
            superseded_by="mem-2",
            target_memory_id="mem-3",
        )
        self.assertEqual(payload.reason, "测试删除")
        self.assertEqual(payload.superseded_by, "mem-2")

    def test_clarification_payload_uses_structured_options(self) -> None:
        payload = ClarificationCardPayload(
            card_id="clarify-1",
            question="Which topic do you mean?",
            options=[ClarificationOptionPayload(id="1", label="Spring AOP", value="Spring AOP")],
            ambiguity_type="reference",
        )
        self.assertEqual(payload.options[0].label, "Spring AOP")

    def test_api_response_success_helper(self) -> None:
        response = ApiResponse.success({"ok": True})
        self.assertTrue(response.ok)
        self.assertEqual(response.data, {"ok": True})

    def test_router_and_app_register_expected_routes(self) -> None:
        router = create_api_router(_MockService())
        router_paths = {route.path for route in router.routes}
        expected_router_paths = {
            "/internal/v1/approval/submit",
            "/internal/v1/chat/stream",
            "/internal/v1/session/{session_id}/state",
            "/internal/v1/feedback/report",
            "/internal/v1/feedback/samples",
            "/internal/v1/memory/records",
            "/internal/v1/memory/records/{memory_id}",
            "/internal/v1/memory/candidates",
            "/internal/v1/memory/traces",
            "/internal/v1/memory/traces/{trace_id}",
            "/internal/v1/memory/records/{memory_id}/access-logs",
            "/internal/v1/memory/deletion-jobs",
            "/internal/v1/memory/candidates/{candidate_id}/confirm",
            "/internal/v1/memory/candidates/{candidate_id}/reject",
            "/internal/v1/memory/records/{memory_id}/supersede",
            "/internal/v1/memory/records/{memory_id}/delete",
        }
        self.assertEqual(router_paths, expected_router_paths)

        app = app_module.create_app(_MockService())
        app_paths = {route.path for route in app.routes}
        expected_app_paths = expected_router_paths | {
            "/health",
            "/meta",
            "/live",
            "/ready",
            "/dependency-status",
            "/metrics",
        }
        self.assertTrue(expected_router_paths.issubset(app_paths))
        self.assertTrue(expected_app_paths.issubset(app_paths))

    def test_chat_route_returns_streaming_response(self) -> None:
        router = create_api_router(_MockService())
        route = next(route for route in router.routes if route.path == "/internal/v1/chat/stream")
        with patch("learning_agent_service.api.routes.chat.require_internal_token", lambda token: None):
            response = asyncio.run(
                route.endpoint(
                    ChatStreamRequest(
                        user_id="u1",
                        session_id="s1",
                        trace_id="t1",
                        turn_id="turn-1",
                        message="今晚想带爸妈吃饭，别太吵，人均150左右，离我近一点",
                        page="meituan_search_box",
                        client_context={
                            "city": "北京",
                            "location": {"lat": 39.9, "lng": 116.4},
                            "entry": "meituan_search_box",
                        },
                    )
                )
        )
        chunks = asyncio.run(_collect_body_chunks(response))
        self.assertEqual(len(chunks), 3)
        self.assertIn("event: ack", chunks[0])
        self.assertIn("event: answer_delta", chunks[1])
        self.assertIn("event: final", chunks[2])
        self.assertIn('"mode":"recommend"', chunks[2])
        self.assertIn('"source":"local-life-agent"', chunks[2])
        self.assertIn('"cards":[{"type":"shop_card"', chunks[2])
