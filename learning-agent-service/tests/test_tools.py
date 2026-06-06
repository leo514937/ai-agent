from __future__ import annotations

import asyncio
from datetime import datetime
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import _bootstrap  # noqa: F401
from pydantic import BaseModel

from learning_agent_service.adapters.java_business import JavaBusinessClient
from learning_agent_service.config import Settings
from learning_agent_service.domain import (
    AnswerComposeRequest,
    ChatTurnCommand,
    Citation,
    EvidenceItem,
    EvidencePack,
    MemoryRecord,
    MemoryScope,
    MemoryStatus,
    MemoryType,
    PersistentSessionContext,
    RagResult,
    ToolExecutionCommand,
    ToolExecutionResult as DomainToolExecutionResult,
    ToolNormalizationRequest,
    ToolPlanningRequest,
    ToolSelection as DomainToolSelection,
    build_initial_state,
)
from learning_agent_service.domain.enums import IntentType, RagStatus, ToolExecutionStatus, TurnDecision
from learning_agent_service.local_life.schemas import LocalLifeSlots
from learning_agent_service.tools import (
    RegisteredTool,
    SideEffectLevel,
    ToolExecutor,
    ToolPlanner,
    ToolRegistry,
    ToolSelection,
    ToolSpec,
)
from learning_agent_service.tools.service import (
    ToolExecutor as RuntimeToolExecutor,
    ToolPlanner as RuntimeToolPlanner,
    ToolResultNormalizer as RuntimeToolResultNormalizer,
    build_default_tool_registry,
)
from learning_agent_service.application.dependencies import OpenAIAnswerComposeAdapter
from learning_agent_service.application.router import build_initial_routing_decision
from learning_agent_service.infrastructure.db.openai_client import OpenAIRuntime


class DummyInput(BaseModel):
    topic: str


class DummyOutput(BaseModel):
    summary: str


class ToolsTestCase(unittest.TestCase):
    def _state(self):
        return build_initial_state(
            ChatTurnCommand(
                trace_id="trace-1",
                session_id="session-1",
                turn_id="turn-1",
                user_id="user-1",
                message="推荐一家适合带爸妈吃饭的餐厅",
            )
        )

    def test_tool_planner_maps_local_life_intent_and_slot_to_tool_name(self) -> None:
        selection = ToolPlanner().plan(
            intent="local_life_blog",
            need_tool=True,
            slots={"shop_name": "某某家常菜"},
        )
        self.assertIsNotNone(selection)
        self.assertEqual(selection.tool_name, "get_blog_list")
        self.assertEqual(selection.input_payload["shop_name"], "某某家常菜")

        runtime_selection = RuntimeToolPlanner().plan(
            ToolPlanningRequest(
                raw_query="帮我看看这家店的券",
                decision=TurnDecision.TOOL_THEN_ANSWER,
                intent=IntentType.RECOMMEND,
                slots={
                    "action": "coupon",
                    "shop_name": "某某家常菜",
                    "selected_shop_id": 1001,
                },
                current_topic="某某家常菜",
            )
        )
        self.assertTrue(runtime_selection.should_execute)
        self.assertEqual(runtime_selection.tool_name, "get_coupon_list")
        self.assertEqual(runtime_selection.input_payload["shop_id"], 1001)
        self.assertEqual(runtime_selection.input_payload["shop_name"], "某某家常菜")

        booking_selection = RuntimeToolPlanner().plan(
            ToolPlanningRequest(
                raw_query="帮我订座",
                decision=TurnDecision.TOOL_THEN_ANSWER,
                intent=IntentType.RECOMMEND,
                slots={
                    "shop_name": "某某家常菜",
                    "selected_shop_id": 1001,
                    "time": {"preferred_time": "2026-05-14 19:00"},
                    "companions": ["parents"],
                },
                current_topic="某某家常菜",
            )
        )
        self.assertEqual(booking_selection.tool_name, "create_booking")
        self.assertEqual(booking_selection.input_payload["shop_id"], 1001)
        self.assertEqual(booking_selection.input_payload["party_size"], 2)

        refund_selection = RuntimeToolPlanner().plan(
            ToolPlanningRequest(
                raw_query="帮我退款",
                decision=TurnDecision.TOOL_THEN_ANSWER,
                intent=IntentType.RECOMMEND,
                slots={"order_id": "order-1"},
                current_topic="某某家常菜",
            )
        )
        self.assertEqual(refund_selection.tool_name, "refund_order")
        self.assertEqual(refund_selection.input_payload["order_id"], "order-1")

    def test_registry_registers_and_lists_specs(self) -> None:
        registry = ToolRegistry()
        registry.register(
            RegisteredTool(
                spec=ToolSpec(
                    name="search_restaurants",
                    description="Search restaurants",
                    input_model=DummyInput,
                    output_model=DummyOutput,
                    idempotent=True,
                    retryable=True,
                    side_effect_level=SideEffectLevel.NONE,
                ),
                handler=lambda payload: {"summary": payload.topic},
            )
        )
        self.assertTrue(registry.is_registered("search_restaurants"))
        self.assertEqual(registry.list_specs()[0].name, "search_restaurants")

    def test_builtin_tool_registry_includes_local_life_tools(self) -> None:
        registry = build_default_tool_registry()
        for name in (
            "search_restaurants",
            "get_shop_detail",
            "get_shop_type_list",
            "get_coupon_list",
            "get_blog_list",
            "get_distance_eta",
            "check_open_status",
            "create_booking",
            "create_order",
            "cancel_order",
            "refund_order",
            "get_order_status",
        ):
            with self.subTest(tool=name):
                self.assertTrue(registry.is_registered(name))

    def test_java_business_client_normalizes_transaction_responses(self) -> None:
        client = JavaBusinessClient(
            settings=Settings(
                java_business_base_url="http://java.example",
                java_business_enable_fallback=False,
            )
        )

        with patch.object(
            client,
            "_request_json",
            return_value={
                "data": {
                    "booking": {
                        "transaction_id": "booking-123",
                        "status": "confirmed",
                        "approval_state": "approved",
                        "shop_id": 1001,
                        "shop_name": "某某家常菜",
                    }
                }
            },
        ):
            booking = client.create_booking(
                shop_id=1001,
                shop_name="某某家常菜",
                payload={"booking_time": "2026-05-14 19:00"},
                idempotency_key="booking-idem",
            )
        self.assertIsNotNone(booking)
        self.assertEqual(booking["booking_id"], "booking-123")
        self.assertEqual(booking["transaction_id"], "booking-123")
        self.assertEqual(booking["source"], "java")
        self.assertEqual(booking["idempotency_key"], "booking-idem")

        with patch.object(
            client,
            "_request_json",
            return_value={
                "data": {
                    "order_id": "order-456",
                    "status": "created",
                    "approval_state": "approved",
                    "shop_id": 1001,
                    "shop_name": "某某家常菜",
                }
            },
        ):
            order = client.create_order(
                shop_id=1001,
                shop_name="某某家常菜",
                payload={"amount": 88.0},
                idempotency_key="order-idem",
            )
        self.assertIsNotNone(order)
        self.assertEqual(order["order_id"], "order-456")
        self.assertEqual(order["transaction_type"], "order")
        self.assertEqual(order["idempotency_key"], "order-idem")

    def test_settings_default_java_business_token_inherits_internal_api_token(self) -> None:
        settings = Settings(
            internal_api_token="local-learning-agent-token",
            java_business_base_url="http://java.example",
        )

        self.assertEqual(settings.java_business_internal_token, "local-learning-agent-token")

    def test_java_business_client_uses_internal_api_token_when_java_token_missing(self) -> None:
        captured: dict[str, object] = {}

        class _FakeHttpxClient:
            def __init__(self, *, base_url, timeout, headers):
                captured["base_url"] = base_url
                captured["timeout"] = timeout
                captured["headers"] = dict(headers)

            def close(self) -> None:
                return None

        with patch("learning_agent_service.adapters.java_business.httpx.Client", _FakeHttpxClient):
            client = JavaBusinessClient(
                settings=Settings(
                    internal_api_token="local-learning-agent-token",
                    java_business_base_url="http://java.example",
                )
            )
            client._http_client()

        self.assertEqual(captured["base_url"], "http://java.example")
        self.assertEqual(captured["headers"]["x-internal-token"], "local-learning-agent-token")

    def test_java_business_client_without_fallback_raises_when_backend_is_missing(self) -> None:
        client = JavaBusinessClient(
            settings=Settings(
                java_business_base_url="",
                java_business_enable_fallback=False,
            )
        )

        with self.assertRaises(RuntimeError):
            client.search_candidates(
                query="附近安静能停车的家常菜",
                slots=LocalLifeSlots(city="北京", category="家常菜"),
                limit=2,
            )

    def test_runtime_tool_executor_covers_local_life_paths(self) -> None:
        registry = build_default_tool_registry()
        executor = RuntimeToolExecutor(registry=registry)
        normalizer = RuntimeToolResultNormalizer()

        with patch("learning_agent_service.tools.builtin.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2026, 5, 14, 12, 0, 0)

            detail_result = executor.execute(
                ToolExecutionCommand(
                    selection=DomainToolSelection(
                        tool_name="get_shop_detail",
                        should_execute=True,
                        input_payload={
                            "shop_id": 1001,
                            "query": "某某家常菜",
                            "lat": 39.98,
                            "lng": 116.47,
                        },
                        reason="test",
                        extra={"tool_call_id": "call-detail"},
                    )
                )
            )
            self.assertEqual(detail_result.status, ToolExecutionStatus.SUCCESS)
            self.assertEqual(detail_result.output_payload["data"]["shop"]["id"], 1001)
            self.assertEqual(detail_result.output_payload["data"]["open_status"]["open_status"], "open")
            self.assertIn("distance_eta", detail_result.output_payload["data"])

            normalized_detail = normalizer.normalize(ToolNormalizationRequest(result=detail_result))
            self.assertEqual(normalized_detail.status, ToolExecutionStatus.SUCCESS)
            self.assertEqual(normalized_detail.used_tools, ["get_shop_detail"])
            self.assertEqual(normalized_detail.normalized_output["data"]["shop"]["id"], 1001)

            open_status_result = executor.execute(
                ToolExecutionCommand(
                    selection=DomainToolSelection(
                        tool_name="check_open_status",
                        should_execute=True,
                        input_payload={"shop_id": 1001},
                        reason="test",
                        extra={"tool_call_id": "call-open"},
                    )
                )
            )
            self.assertEqual(open_status_result.status, ToolExecutionStatus.SUCCESS)
            self.assertTrue(open_status_result.output_payload["data"]["open_now"])
            self.assertEqual(open_status_result.output_payload["data"]["open_status"], "open")

        distance_result = executor.execute(
            ToolExecutionCommand(
                selection=DomainToolSelection(
                    tool_name="get_distance_eta",
                    should_execute=True,
                    input_payload={
                        "shop_id": 1001,
                        "lat": 39.98,
                        "lng": 116.47,
                        "mode": "drive",
                    },
                    reason="test",
                    extra={"tool_call_id": "call-distance"},
                )
            )
        )
        self.assertEqual(distance_result.status, ToolExecutionStatus.SUCCESS)
        self.assertGreater(distance_result.output_payload["data"]["distance_km"], 0)
        self.assertEqual(distance_result.output_payload["data"]["mode"], "drive")
        self.assertEqual(distance_result.output_payload["data"]["source"], "catalog")

        coupon_result = executor.execute(
            ToolExecutionCommand(
                selection=DomainToolSelection(
                    tool_name="get_coupon_list",
                    should_execute=True,
                    input_payload={"shop_id": 1001},
                    reason="test",
                    extra={"tool_call_id": "call-coupon"},
                )
            )
        )
        self.assertEqual(coupon_result.status, ToolExecutionStatus.SUCCESS)
        self.assertEqual(coupon_result.output_payload["data"]["shop_id"], 1001)
        self.assertEqual(coupon_result.output_payload["data"]["count"], 1)

        blog_result = executor.execute(
            ToolExecutionCommand(
                selection=DomainToolSelection(
                    tool_name="get_blog_list",
                    should_execute=True,
                    input_payload={"shop_id": 1001},
                    reason="test",
                    extra={"tool_call_id": "call-blog"},
                )
            )
        )
        self.assertEqual(blog_result.status, ToolExecutionStatus.SUCCESS)
        self.assertEqual(blog_result.output_payload["data"]["scope"], "shop")
        self.assertEqual(blog_result.output_payload["data"]["count"], 1)
        self.assertEqual(blog_result.output_payload["data"]["source"], "catalog")

        booking_result = executor.execute(
            ToolExecutionCommand(
                selection=DomainToolSelection(
                    tool_name="create_booking",
                    should_execute=True,
                    input_payload={
                        "shop_id": 1001,
                        "shop_name": "某某家常菜",
                        "booking_time": "2026-05-14 19:00",
                        "party_size": 3,
                        "note": "今晚带爸妈吃饭",
                    },
                    reason="test",
                    extra={"tool_call_id": "call-booking"},
                )
            )
        )
        self.assertEqual(booking_result.status, ToolExecutionStatus.PENDING_APPROVAL)
        self.assertTrue(booking_result.approval_required)
        self.assertEqual(booking_result.approval_status, "not_enabled_in_p0")
        self.assertEqual(booking_result.approval_request["tool_name"], "create_booking")
        self.assertEqual(booking_result.approval_request["approval_state"], "not_enabled_in_p0")
        self.assertEqual(booking_result.extra["error_code"], "LEARN-5305")
        self.assertEqual(booking_result.extra["failure_category"], "approval_required")

        missing_status_result = executor.execute(
            ToolExecutionCommand(
                selection=DomainToolSelection(
                    tool_name="get_order_status",
                    should_execute=True,
                    input_payload={"order_id": "missing-order"},
                    reason="test",
                    extra={"tool_call_id": "call-missing-status"},
                )
            )
        )
        self.assertEqual(missing_status_result.status, ToolExecutionStatus.SUCCESS)
        self.assertEqual(missing_status_result.output_payload["data"]["order"]["status"], "not_found")

        search_result = executor.execute(
            ToolExecutionCommand(
                selection=DomainToolSelection(
                    tool_name="search_restaurants",
                    should_execute=True,
                    input_payload={
                        "query": "附近安静能停车的家常菜",
                        "city": "北京",
                        "category": "家常菜",
                        "preferences": ["quiet", "parking_available"],
                        "limit": 2,
                    },
                    reason="test",
                    extra={"tool_call_id": "call-search"},
                )
            )
        )
        self.assertEqual(search_result.status, ToolExecutionStatus.SUCCESS)
        self.assertGreater(search_result.output_payload["data"]["candidate_count"], 0)
        self.assertEqual(search_result.output_payload["data"]["source"], "catalog")

    def test_runtime_tool_executor_write_tools_are_reserved_in_p0(self) -> None:
        registry = build_default_tool_registry()
        executor = RuntimeToolExecutor(registry=registry)

        pending_order_result = executor.execute(
            ToolExecutionCommand(
                selection=DomainToolSelection(
                    tool_name="create_order",
                    should_execute=True,
                    input_payload={
                        "shop_id": 1001,
                        "shop_name": "某某家常菜",
                        "amount": 88.0,
                        "note": "双人下单",
                        "idempotency_key": "order-idem-1",
                    },
                    reason="test",
                    extra={"tool_call_id": "call-order-pending"},
                )
            )
        )
        self.assertEqual(pending_order_result.status, ToolExecutionStatus.PENDING_APPROVAL)
        self.assertTrue(pending_order_result.approval_required)
        self.assertEqual(pending_order_result.approval_status, "not_enabled_in_p0")
        self.assertEqual(pending_order_result.approval_request["approval_state"], "not_enabled_in_p0")
        self.assertEqual(pending_order_result.extra["error_code"], "LEARN-5305")
        self.assertEqual(pending_order_result.extra["failure_category"], "approval_required")

        approved_order_result = executor.execute(
            ToolExecutionCommand(
                selection=DomainToolSelection(
                    tool_name="create_order",
                    should_execute=True,
                    input_payload={
                        "shop_id": 1001,
                        "shop_name": "某某家常菜",
                        "amount": 88.0,
                        "note": "双人下单",
                        "idempotency_key": "order-idem-1",
                    },
                    reason="test",
                    approval_required=True,
                    approval_status="approved",
                    approval_request=dict(pending_order_result.approval_request),
                    extra={"tool_call_id": "call-order-approved"},
                )
            )
        )
        self.assertEqual(approved_order_result.status, ToolExecutionStatus.PENDING_APPROVAL)
        self.assertEqual(approved_order_result.approval_status, "not_enabled_in_p0")
        self.assertEqual(approved_order_result.approval_request["approval_state"], "not_enabled_in_p0")
        self.assertEqual(approved_order_result.extra["failure_category"], "approval_required")

        cancel_result = executor.execute(
            ToolExecutionCommand(
                selection=DomainToolSelection(
                    tool_name="cancel_order",
                    should_execute=True,
                    input_payload={
                        "order_id": "order-1",
                        "reason": "临时取消",
                    },
                    reason="test"
                )
            )
        )
        self.assertEqual(cancel_result.status, ToolExecutionStatus.PENDING_APPROVAL)
        self.assertEqual(cancel_result.approval_status, "not_enabled_in_p0")
        self.assertEqual(cancel_result.extra["failure_category"], "approval_required")

        refund_result = executor.execute(
            ToolExecutionCommand(
                selection=DomainToolSelection(
                    tool_name="refund_order",
                    should_execute=True,
                    input_payload={"order_id": "order-1", "reason": "用户取消"},
                    reason="test",
                )
            )
        )
        self.assertEqual(refund_result.status, ToolExecutionStatus.PENDING_APPROVAL)
        self.assertEqual(refund_result.approval_status, "not_enabled_in_p0")
        self.assertEqual(refund_result.extra["failure_category"], "approval_required")

    def test_executor_timeout_uses_degrade_to(self) -> None:
        async def slow_handler(payload: DummyInput):
            await asyncio.sleep(0.02)
            return {"summary": payload.topic}

        registry = ToolRegistry()
        registry.register(
            RegisteredTool(
                spec=ToolSpec(
                    name="search_restaurants",
                    description="Search restaurants",
                    input_model=DummyInput,
                    output_model=DummyOutput,
                    idempotent=True,
                    retryable=True,
                    side_effect_level=SideEffectLevel.NONE,
                    degrade_to="catalog-search",
                    timeout_ms=1,
                ),
                handler=slow_handler,
            )
        )

        result = asyncio.run(
            ToolExecutor(registry).execute(
                ToolSelection(tool_name="search_restaurants", input_payload={"topic": "Spring"})
            )
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_code, "LEARN-5301")
        self.assertTrue(result.degraded)
        self.assertEqual(result.degrade_to, "catalog-search")

    def test_runtime_tool_planner_returns_domain_selection(self) -> None:
        selection = RuntimeToolPlanner().plan(
            ToolPlanningRequest(
                raw_query="帮我看这家店的营业状态",
                decision=TurnDecision.TOOL_THEN_ANSWER,
                intent=IntentType.RECOMMEND,
                slots={
                    "action": "open_status",
                    "shop_name": "某某家常菜",
                },
                current_topic="某某家常菜",
            )
        )
        self.assertTrue(selection.should_execute)
        self.assertEqual(selection.tool_name, "check_open_status")
        self.assertEqual(selection.input_payload["shop_name"], "某某家常菜")
        self.assertTrue(selection.extra["tool_call_id"])

    def test_runtime_tool_planner_routes_generic_recommend_to_search_restaurants(self) -> None:
        selection = RuntimeToolPlanner().plan(
            ToolPlanningRequest(
                raw_query="推荐一家适合带爸妈吃饭的餐厅",
                decision=TurnDecision.TOOL_THEN_ANSWER,
                intent=IntentType.RECOMMEND,
                slots={
                    "city": "北京",
                    "location": {"city": "北京"},
                    "scene": "family_dinner",
                    "preferences": ["quiet"],
                },
                current_topic="北京",
            )
        )

        self.assertTrue(selection.should_execute)
        self.assertEqual(selection.tool_name, "search_restaurants")
        self.assertEqual(selection.extra["planning_state"], "mapped")
        self.assertEqual(selection.extra["resolved_intent"], "restaurant_recommendation")
        self.assertEqual(selection.input_payload["city"], "北京")

    def test_runtime_tool_result_normalizer_preserves_error_metadata(self) -> None:
        raw = DomainToolExecutionResult(
            status=ToolExecutionStatus.FAILED,
            tool_name="get_shop_detail",
            output_payload={},
            extra={
                "error_code": "LEARN-5300",
                "error_message": "boom",
                "retryable": True,
                "degraded": False,
                "degrade_to": None,
            },
        )
        normalized = RuntimeToolResultNormalizer().normalize(ToolNormalizationRequest(result=raw))
        self.assertEqual(normalized.status, ToolExecutionStatus.FAILED)
        self.assertFalse(normalized.extra["degraded"])
        self.assertEqual(normalized.extra["errors"]["code"], "LEARN-5300")

    def test_runtime_tool_result_normalizer_classifies_failures(self) -> None:
        normalizer = RuntimeToolResultNormalizer()

        not_found = normalizer.normalize(
            ToolNormalizationRequest(
                result=DomainToolExecutionResult(
                    status=ToolExecutionStatus.FAILED,
                    tool_name="get_shop_detail",
                    output_payload={},
                    extra={"error_code": "LEARN-5300", "error_message": "shop not found"},
                )
            )
        )
        self.assertEqual(not_found.extra["failure_category"], "no_result")

        timeout = normalizer.normalize(
            ToolNormalizationRequest(
                result=DomainToolExecutionResult(
                    status=ToolExecutionStatus.FAILED,
                    tool_name="search_restaurants",
                    output_payload={},
                    extra={"error_code": "LEARN-5301", "error_message": "Tool execution timed out", "retryable": True},
                )
            )
        )
        self.assertEqual(timeout.extra["failure_category"], "timeout")

        unavailable = normalizer.normalize(
            ToolNormalizationRequest(
                result=DomainToolExecutionResult(
                    status=ToolExecutionStatus.FAILED,
                    tool_name="get_coupon_list",
                    output_payload={},
                    extra={"error_code": "LEARN-5300", "error_message": "Java business client is unavailable"},
                )
            )
        )
        self.assertEqual(unavailable.extra["failure_category"], "dependency_unavailable")

        denied = normalizer.normalize(
            ToolNormalizationRequest(
                result=DomainToolExecutionResult(
                    status=ToolExecutionStatus.REJECTED,
                    tool_name="refund_order",
                    output_payload={},
                    approval_required=True,
                    approval_status="rejected",
                    approval_request={"tool_name": "refund_order"},
                    extra={},
                )
            )
        )
        self.assertEqual(denied.extra["failure_category"], "permission_denied")

    def test_answer_composer_prefers_tool_answer_when_business_data_exists(self) -> None:
        from learning_agent_service.tools.service import AnswerComposer

        empty_pack = EvidencePack(evidence_status="EMPTY")
        rag_result = RagResult(status=RagStatus.EMPTY, evidence_pack=empty_pack, evidence_status="EMPTY")
        tool_result = RuntimeToolResultNormalizer().normalize(
            ToolNormalizationRequest(
                result=DomainToolExecutionResult(
                    status=ToolExecutionStatus.SUCCESS,
                    tool_name="get_coupon_list",
                    output_payload={
                        "data": {
                            "shop_id": 1001,
                            "shop_name": "某某家常菜",
                            "count": 1,
                            "coupons": [
                                {
                                    "id": 201,
                                    "title": "满100减20",
                                    "subTitle": "家庭聚餐券",
                                    "payValue": 100,
                                    "actualValue": 80,
                                }
                            ],
                            "source": "java",
                        }
                    },
                )
            )
        )
        output = AnswerComposer().compose(
            AnswerComposeRequest(
                raw_query="这家店有什么券",
                rag_result=rag_result,
                tool_result=tool_result,
            )
        )
        self.assertIn("某某家常菜", output.answer_text)
        self.assertIn("满100减20", output.answer_text)
        self.assertNotIn("知识库", output.answer_text)

    def test_answer_composer_merges_coupon_and_environment_for_rag_plus_tool(self) -> None:
        from learning_agent_service.tools.service import AnswerComposer

        routing = build_initial_routing_decision(
            "卷卷烤肉有券吗，环境怎么样",
            PersistentSessionContext(current_topic="卷卷烤肉", selected_shop_name="卷卷烤肉"),
        )
        self.assertEqual(routing.required_action, "rag_plus_tool")

        tool_result = RuntimeToolResultNormalizer().normalize(
            ToolNormalizationRequest(
                result=DomainToolExecutionResult(
                    status=ToolExecutionStatus.SUCCESS,
                    tool_name="get_coupon_list",
                    output_payload={
                        "data": {
                            "shop_id": 1001,
                            "shop_name": "卷卷烤肉",
                            "count": 1,
                            "coupons": [
                                {
                                    "id": 201,
                                    "title": "满100减20",
                                    "subTitle": "家庭聚餐券",
                                    "payValue": 100,
                                    "actualValue": 80,
                                }
                            ],
                            "source": "java",
                        }
                    },
                    extra={"grounding_source": "business_evidence"},
                )
            )
        )
        rag_result = RagResult(
            status=RagStatus.OK,
            evidence_pack=EvidencePack(
                evidence_status="OK",
                items=[
                    EvidenceItem(
                        chunk_id="env-1",
                        content="环境很安静，包间也挺多，适合家庭聚餐。",
                        score=0.91,
                        document_id="doc-1",
                        chunk_type="review_summary",
                    ),
                    EvidenceItem(
                        chunk_id="env-2",
                        content="整体口碑不错，吃饭氛围比较轻松。",
                        score=0.84,
                        document_id="doc-2",
                        chunk_type="review_note",
                    ),
                ],
            ),
            evidence_status="OK",
        )

        output = AnswerComposer().compose(
            AnswerComposeRequest(
                raw_query="卷卷烤肉有券吗，环境怎么样",
                routing_decision=routing,
                rag_result=rag_result,
                tool_result=tool_result,
            )
        )

        self.assertIn("满100减20", output.answer_text)
        self.assertIn("环境偏安静", output.answer_text)
        self.assertIn("比较适合家庭聚餐", output.answer_text)
        self.assertIn("整体口碑还不错", output.answer_text)

    def test_answer_composer_separates_memory_context_from_rag_evidence(self) -> None:
        from learning_agent_service.domain import MemoryInjectionPlan
        from learning_agent_service.tools.service import AnswerComposer

        memory_plan = MemoryInjectionPlan(
            prompt_memories=[
                MemoryRecord(
                    memory_id="prompt-1",
                    user_id="user-1",
                    type=MemoryType.PREFERENCE,
                    scope=MemoryScope.USER,
                    status=MemoryStatus.CONFIRMED,
                    summary="请优先用中文回答",
                    content={"preferred_output_style": "detailed"},
                    source_turn_id="turn-1",
                    confidence=0.95,
                    importance=0.9,
                )
            ],
            state_memories=[
                MemoryRecord(
                    memory_id="semantic-1",
                    user_id="user-1",
                    type=MemoryType.SEMANTIC,
                    scope=MemoryScope.USER,
                    status=MemoryStatus.ACTIVE,
                    summary="长期语义事实",
                    content={"fact": "semantic"},
                    source_turn_id="turn-1",
                    confidence=0.9,
                    importance=0.85,
                ),
            ],
            tool_memories=[
                MemoryRecord(
                    memory_id="procedural-1",
                    user_id="user-1",
                    type=MemoryType.PROCEDURAL,
                    scope=MemoryScope.USER,
                    status=MemoryStatus.ACTIVE,
                    summary="可复用步骤",
                    content={"sop": "procedural"},
                    source_turn_id="turn-1",
                    confidence=0.87,
                    importance=0.8,
                )
            ],
            rag_memories=[
                MemoryRecord(
                    memory_id="rag-1",
                    user_id="user-1",
                    type=MemoryType.SEMANTIC,
                    scope=MemoryScope.USER,
                    status=MemoryStatus.ACTIVE,
                    summary="RAG 证据",
                    content={"fact": "rag"},
                    source_turn_id="turn-1",
                    confidence=0.9,
                    importance=0.85,
                )
            ],
            hidden_trace_memories=[],
            token_budget=1200,
        )

        rag_pack = EvidencePack(
            evidence_status="OK",
            items=[
                EvidenceItem(
                    chunk_id="rag-1",
                    content="RAG 通过检索证据来约束回答。",
                    score=0.92,
                    document_id="doc-1",
                    chunk_type="concept",
                    citation_chunk_id="rag-1",
                    metadata={"title": "RAG 基础"},
                )
            ],
        )
        output = AnswerComposer().compose(
            AnswerComposeRequest(
                raw_query="继续解释一下",
                rag_result=RagResult(status=RagStatus.OK, evidence_pack=rag_pack, evidence_status="OK"),
                memory_injection_plan=memory_plan,
            )
        )

        self.assertNotIn("Memory context:", output.answer_text)
        self.assertNotIn("Tool result:", output.answer_text)
        self.assertNotIn("请优先用中文回答", output.answer_text)
        self.assertIn("根据知识库中的证据", output.answer_text)
        self.assertIn("RAG 通过检索证据来约束回答。", output.answer_text)

    def test_answer_composer_routes_tool_failures_to_user_friendly_messages(self) -> None:
        from learning_agent_service.tools.service import AnswerComposer

        composer = AnswerComposer()

        no_result = RuntimeToolResultNormalizer().normalize(
            ToolNormalizationRequest(
                result=DomainToolExecutionResult(
                    status=ToolExecutionStatus.SUCCESS,
                    tool_name="get_order_status",
                    output_payload={"data": {"found": False, "status": "not_found", "message": "未找到订单"}},
                )
            )
        )
        timeout = RuntimeToolResultNormalizer().normalize(
            ToolNormalizationRequest(
                result=DomainToolExecutionResult(
                    status=ToolExecutionStatus.FAILED,
                    tool_name="search_restaurants",
                    output_payload={},
                    extra={"error_code": "LEARN-5301", "error_message": "Tool execution timed out", "retryable": True},
                )
            )
        )
        approval = RuntimeToolResultNormalizer().normalize(
            ToolNormalizationRequest(
                result=DomainToolExecutionResult(
                    status=ToolExecutionStatus.PENDING_APPROVAL,
                    tool_name="create_order",
                    output_payload={},
                    approval_required=True,
                    approval_status="not_enabled_in_p0",
                    approval_request={"tool_name": "create_order", "approval_state": "not_enabled_in_p0"},
                    extra={"error_code": "LEARN-5305", "error_message": "Tool is reserved and not enabled in P0"},
                )
            )
        )

        no_result_answer = composer.compose(AnswerComposeRequest(raw_query="查订单", tool_result=no_result))
        timeout_answer = composer.compose(AnswerComposeRequest(raw_query="帮我找店", tool_result=timeout))
        approval_answer = composer.compose(AnswerComposeRequest(raw_query="帮我下单", tool_result=approval))

        self.assertIn("没查到", no_result_answer.answer_text)
        self.assertIn("稍后重试", timeout_answer.answer_text)
        self.assertIn("待确认", approval_answer.answer_text)

    def test_answer_composer_refuses_when_evidence_empty(self) -> None:
        empty_pack = EvidencePack(evidence_status="EMPTY")
        rag_result = RagResult(status=RagStatus.EMPTY, evidence_pack=empty_pack, evidence_status="EMPTY")

        from learning_agent_service.tools.service import AnswerComposer

        output = AnswerComposer().compose(
            AnswerComposeRequest(raw_query="什么是RAG", rag_result=rag_result)
        )
        self.assertNotEqual(output.answer_text, "当前知识库中没有找到足够依据回答该问题。")
        self.assertTrue("上下文" in output.answer_text or "更具体" in output.answer_text)

    def test_answer_composer_uses_llm_for_open_ended_questions_when_evidence_empty(self) -> None:
        calls: list[str] = []

        def fake_llm(request: AnswerComposeRequest):
            calls.append(request.raw_query)
            return {"answer_text": "如果你想看优惠券，告诉我店名或店铺页上下文，我就能继续查。"}

        from learning_agent_service.tools.service import AnswerComposer

        output = AnswerComposer(llm_answerer=fake_llm).compose(
            AnswerComposeRequest(raw_query="看优惠券")
        )

        self.assertEqual(calls, ["看优惠券"])
        self.assertIn("店名", output.answer_text)
        self.assertNotIn("知识库", output.answer_text)

    def test_tool_result_normalizer_renames_coupon_alias_fields(self) -> None:
        normalized = RuntimeToolResultNormalizer().normalize(
            ToolNormalizationRequest(
                result=DomainToolExecutionResult(
                    status=ToolExecutionStatus.SUCCESS,
                    tool_name="get_coupon_list",
                    output_payload={
                        "data": {
                            "shop_name": "某某家常菜",
                            "count": 0,
                            "couponsns": [],
                            "source": "java",
                        }
                    },
                )
            )
        )

        data = normalized.normalized_output["data"]
        self.assertIn("coupons", data)
        self.assertNotIn("couponsns", data)
        self.assertEqual(data["count"], 0)
        self.assertEqual(normalized.extra["failure_category"], "no_result")

    def test_answer_composer_does_not_append_auxiliary_debug_sections(self) -> None:
        from learning_agent_service.tools.service import AnswerComposer

        pack = EvidencePack(
            evidence_status="OK",
            items=[
                EvidenceItem(
                    chunk_id="rag-1",
                    content="RAG 通过检索证据来约束回答。",
                    score=0.92,
                    document_id="doc-1",
                    chunk_type="concept",
                    citation_chunk_id="rag-1",
                    metadata={"title": "RAG 基础"},
                )
            ],
        )
        tool_result = RuntimeToolResultNormalizer().normalize(
            ToolNormalizationRequest(
                result=DomainToolExecutionResult(
                    status=ToolExecutionStatus.SUCCESS,
                    tool_name="get_coupon_list",
                    output_payload={"data": {}},
                )
            )
        )

        output = AnswerComposer().compose(
            AnswerComposeRequest(
                raw_query="这家店有券吗",
                rag_result=RagResult(status=RagStatus.OK, evidence_pack=pack, evidence_status="OK"),
                tool_result=tool_result,
            )
        )

        self.assertNotIn("Tool result:", output.answer_text)
        self.assertNotIn("Memory context:", output.answer_text)
        self.assertNotIn("Episodic context:", output.answer_text)
        self.assertNotIn("Procedural context:", output.answer_text)
        self.assertIn("RAG 通过检索证据来约束回答。", output.answer_text)

    def test_answer_composer_returns_capability_summary_for_profile_turns(self) -> None:
        from learning_agent_service.tools.service import AnswerComposer

        output = AnswerComposer().compose(
            AnswerComposeRequest(
                raw_query="你有什么功能",
                allow_direct_response=True,
                direct_response_kind="profile",
            )
        )

        self.assertIn("通用问答", output.answer_text)
        self.assertIn("本地生活", output.answer_text)
        self.assertIn("代码解释", output.answer_text)

    def test_answer_composer_returns_history_summary_for_conversation_recap(self) -> None:
        from learning_agent_service.tools.service import AnswerComposer

        output = AnswerComposer().compose(
            AnswerComposeRequest(
                raw_query="你记得我们说过什么吗",
                allow_direct_response=True,
                direct_response_kind="conversation_recap",
                history_summary="刚才在聊山城一锅的券和环境评价。",
            )
        )

        self.assertIn("刚才在聊山城一锅的券和环境评价", output.answer_text)
        self.assertNotIn("Tool result:", output.answer_text)
        self.assertNotIn("Memory context:", output.answer_text)

    def test_answer_composer_recap_uses_current_shop_context_when_available(self) -> None:
        from learning_agent_service.tools.service import AnswerComposer

        output = AnswerComposer().compose(
            AnswerComposeRequest(
                raw_query="你记得我们说过什么吗",
                allow_direct_response=True,
                direct_response_kind="conversation_recap",
                history_summary="刚才在聊上一轮的券和环境评价。",
                stream_event_meta={"current_shop": "山城一锅"},
            )
        )

        self.assertIn("山城一锅", output.answer_text)
        self.assertIn("刚才在聊上一轮的券和环境评价", output.answer_text)
        self.assertNotIn("Tool result:", output.answer_text)
        self.assertNotIn("Memory context:", output.answer_text)

    def test_answer_composer_streams_direct_response_deltas_even_with_llm_present(self) -> None:
        emitted_events = []

        def fake_llm(request: AnswerComposeRequest):
            self.fail("direct response should not invoke the llm_answerer")

        from learning_agent_service.tools.service import AnswerComposer

        output = AnswerComposer(llm_answerer=fake_llm).compose(
            AnswerComposeRequest(
                raw_query="你好",
                allow_direct_response=True,
                direct_response_kind="greeting",
                stream_event_sink=emitted_events.append,
            )
        )

        self.assertIn("你好，我在", output.answer_text)
        self.assertGreaterEqual(len(emitted_events), 1)
        self.assertTrue(all(getattr(event, "event_type", "") == "delta" for event in emitted_events))

    def test_answer_composer_streams_tool_answer_deltas_even_with_llm_present(self) -> None:
        emitted_events = []

        def fake_llm(request: AnswerComposeRequest):
            self.fail("tool answers should not invoke the llm_answerer")

        from learning_agent_service.tools.service import AnswerComposer

        tool_result = RuntimeToolResultNormalizer().normalize(
            ToolNormalizationRequest(
                result=DomainToolExecutionResult(
                    status=ToolExecutionStatus.SUCCESS,
                    tool_name="get_coupon_list",
                    output_payload={
                        "data": {
                            "shop_id": 1001,
                            "shop_name": "某某家常菜",
                            "count": 1,
                            "coupons": [
                                {
                                    "id": 201,
                                    "title": "满100减20",
                                    "subTitle": "家庭聚餐券",
                                    "payValue": 100,
                                    "actualValue": 80,
                                }
                            ],
                            "source": "java",
                        }
                    },
                    extra={"grounding_source": "business_evidence"},
                )
            )
        )

        output = AnswerComposer(llm_answerer=fake_llm).compose(
            AnswerComposeRequest(
                raw_query="这家店有什么券",
                tool_result=tool_result,
                stream_event_sink=emitted_events.append,
            )
        )

        self.assertIn("某某家常菜", output.answer_text)
        self.assertGreaterEqual(len(emitted_events), 1)
        self.assertTrue(all(getattr(event, "event_type", "") == "delta" for event in emitted_events))

    def test_answer_composer_does_not_duplicate_llm_streamed_deltas(self) -> None:
        emitted_events = []

        def fake_llm(request: AnswerComposeRequest):
            request.stream_event_sink(
                SimpleNamespace(
                event_type="delta",
                    payload={"delta": "你好", "answer_text": "你好"},
                )
            )
            return {"answer_text": "你好，世界"}

        from learning_agent_service.tools.service import AnswerComposer

        output = AnswerComposer(llm_answerer=fake_llm).compose(
            AnswerComposeRequest(
                raw_query="你好",
                stream_event_sink=emitted_events.append,
            )
        )

        self.assertEqual(output.answer_text, "你好，世界")
        self.assertEqual(len(emitted_events), 1)
        self.assertEqual(getattr(emitted_events[0], "event_type", ""), "delta")

    def test_openai_answer_compose_adapter_streams_delta_events(self) -> None:
        emitted_events = []

        class _FakeStream:
            def __init__(self) -> None:
                self._events = [
                    SimpleNamespace(type="response.reasoning_text.delta", delta="先思考一下"),
                    SimpleNamespace(type="response.output_text.delta", delta="你好"),
                    SimpleNamespace(type="response.output_text.delta", delta="，世界"),
                ]

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def __iter__(self):
                return iter(self._events)

            def get_final_response(self):
                return SimpleNamespace(output_text="你好，世界")

        class _FakeResponses:
            def create(self, *args, **kwargs):
                return SimpleNamespace(output_text="unused")

            def stream(self, *args, **kwargs):
                return _FakeStream()

        runtime = OpenAIRuntime(client=SimpleNamespace(responses=_FakeResponses()), default_model="gpt-test")
        adapter = OpenAIAnswerComposeAdapter(runtime=runtime, model="gpt-test")
        request = AnswerComposeRequest(
            raw_query="你好",
            stream_event_sink=emitted_events.append,
            stream_event_meta={
                "trace_id": "trace-1",
                "session_id": "session-1",
                "turn_id": "turn-1",
                "workflow_version": "test/v1",
                "current_stage": "compose",
                "stage_status": "streaming",
            },
        )

        answer = adapter(request)

        self.assertIn("先思考一下", answer)
        self.assertTrue(answer.endswith("你好，世界"))
        self.assertEqual(len(emitted_events), 3)
        self.assertEqual(emitted_events[0].event_type, "delta")
        self.assertEqual(emitted_events[0].payload["delta"], "先思考一下")
        self.assertIn("先思考一下", emitted_events[0].payload["answer_text"])
        self.assertEqual(emitted_events[1].payload["delta"], "你好")
        self.assertIn("先思考一下", emitted_events[1].payload["answer_text"])
        self.assertEqual(emitted_events[2].payload["answer_text"], answer)
        self.assertEqual(emitted_events[2].workflow_version, "test/v1")

    def test_answer_composer_streams_fallback_answer_deltas_without_llm(self) -> None:
        emitted_events = []
        from learning_agent_service.tools.service import AnswerComposer

        tool_result = RuntimeToolResultNormalizer().normalize(
            ToolNormalizationRequest(
                result=DomainToolExecutionResult(
                    status=ToolExecutionStatus.SUCCESS,
                    tool_name="search_restaurants",
                    output_payload={
                        "data": {
                            "candidates": [
                                {"name": "店A"},
                                {"name": "店B"},
                                {"name": "店C"},
                            ],
                            "candidate_count": 3,
                        }
                    },
                    extra={"grounding_source": "business_evidence"},
                )
            )
        )

        output = AnswerComposer().compose(
            AnswerComposeRequest(
                raw_query="帮我找店",
                tool_result=tool_result,
                stream_event_sink=emitted_events.append,
                stream_event_meta={
                    "trace_id": "trace-2",
                    "session_id": "session-2",
                    "turn_id": "turn-2",
                    "workflow_version": "test/v1",
                    "current_stage": "compose",
                    "stage_status": "streaming",
                },
            )
        )

        self.assertGreaterEqual(len(emitted_events), 2)
        self.assertTrue(all(event.event_type == "delta" for event in emitted_events))
        self.assertEqual(emitted_events[-1].payload["answer_text"], output.answer_text)
        self.assertIn("我先帮你筛到这些更匹配的门店", output.answer_text)

    def test_answer_composer_can_return_direct_response_when_gate_denies_rag(self) -> None:
        from learning_agent_service.tools.service import AnswerComposer

        output = AnswerComposer().compose(
            AnswerComposeRequest(
                raw_query="你好",
                allow_direct_response=True,
                direct_response_kind="greeting",
            )
        )
        self.assertIn("你好，我在", output.answer_text)

    def test_answer_composer_uses_grounded_llm_and_citations_when_evidence_ok(self) -> None:
        calls: list[str] = []

        def fake_llm(request: AnswerComposeRequest):
            calls.append(request.raw_query)
            return {"answer_text": "RAG 依赖检索到的证据。"}

        from learning_agent_service.tools.service import AnswerComposer

        pack = EvidencePack(
            evidence_status="OK",
            items=[
                EvidenceItem(
                    chunk_id="child-1",
                    content="RAG 通过检索证据来约束回答。",
                    score=0.92,
                    document_id="doc-1",
                    chunk_type="concept",
                    citation_chunk_id="child-1",
                    metadata={"title": "RAG 基础"},
                )
            ],
            strong_items=[
                EvidenceItem(
                    chunk_id="child-1",
                    content="RAG 通过检索证据来约束回答。",
                    score=0.92,
                    document_id="doc-1",
                    chunk_type="concept",
                    citation_chunk_id="child-1",
                    metadata={"title": "RAG 基础"},
                )
            ],
        )
        rag_result = RagResult(
            status=RagStatus.OK,
            evidence_pack=pack,
            evidence_status="OK",
            citations=[
                Citation(
                    chunk_id="child-1",
                    document_id="doc-1",
                    source_type="document",
                    version="v1",
                    score=0.92,
                    title="RAG 基础",
                    locator="concept",
                )
            ],
        )
        output = AnswerComposer(llm_answerer=fake_llm).compose(
            AnswerComposeRequest(raw_query="RAG 是什么", rag_result=rag_result)
        )
        self.assertEqual(calls, ["RAG 是什么"])
        self.assertIn("RAG 依赖检索到的证据。", output.answer_text)
        self.assertIn("证据引用", output.answer_text)

    def test_answer_composer_weak_evidence_is_cautious(self) -> None:
        from learning_agent_service.tools.service import AnswerComposer

        weak_pack = EvidencePack(
            evidence_status="WEAK",
            items=[
                EvidenceItem(
                    chunk_id="weak-1",
                    content="RAG 有时候会检索外部证据。",
                    score=0.35,
                    document_id="doc-1",
                    chunk_type="concept",
                    tier="weak",
                )
            ],
            weak_items=[
                EvidenceItem(
                    chunk_id="weak-1",
                    content="RAG 有时候会检索外部证据。",
                    score=0.35,
                    document_id="doc-1",
                    chunk_type="concept",
                    tier="weak",
                )
            ],
        )
        rag_result = RagResult(status=RagStatus.DEGRADED, evidence_pack=weak_pack, evidence_status="WEAK")
        output = AnswerComposer().compose(
            AnswerComposeRequest(raw_query="RAG 是什么", rag_result=rag_result)
        )
        self.assertIn("谨慎判断", output.answer_text)
        self.assertIn("建议补充", output.answer_text)

    def test_builtin_tool_metadata_marks_create_booking_as_approval_required(self) -> None:
        registry = build_default_tool_registry()
        spec = registry.get("create_booking").spec

        self.assertTrue(spec.requires_approval)
        self.assertEqual(spec.allowed_execution_modes, ("plan_execute",))

    def test_builtin_tool_metadata_marks_transaction_tools_as_approval_required(self) -> None:
        registry = build_default_tool_registry()
        booking_spec = registry.get("create_booking").spec
        order_spec = registry.get("create_order").spec
        cancel_spec = registry.get("cancel_order").spec
        refund_spec = registry.get("refund_order").spec

        self.assertTrue(booking_spec.requires_approval)
        self.assertTrue(order_spec.requires_approval)
        self.assertTrue(cancel_spec.requires_approval)
        self.assertTrue(refund_spec.requires_approval)
