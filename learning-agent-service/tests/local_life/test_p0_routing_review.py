from __future__ import annotations

import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = TESTS_DIR.parent
SRC_ROOT = PROJECT_ROOT / "src"
for candidate in (str(TESTS_DIR), str(PROJECT_ROOT), str(SRC_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import _bootstrap  # noqa: F401

from learning_agent_service.domain import ChatTurnCommand, PersistentSessionContext
from learning_agent_service.local_life.route_review import RouteReview
from learning_agent_service.local_life.schemas import (
    ClarificationDecision,
    LocalLifeIntentType,
    LocalLifeSlots,
    BlogRecord,
    ShopRecord,
    VoucherRecord,
)
from learning_agent_service.local_life.subgraph import LocalLifeSubgraph
from learning_agent_service.local_life.user_need_parser import UserNeedParser
from learning_agent_service.local_life.query_router import LocalLifeRouteDecision
from learning_agent_service.rag.local_life_retrieval import LocalLifeEvidencePack


def _first_event(events, event_type: str):
    return next(event for event in events if event.event_type == event_type)


class _FakeLocalLifeAssistant:
    def suggest_understanding(self, *, raw_query: str, **_: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "normalized_query": raw_query.strip(),
            "semantic_query": raw_query.strip(),
            "keyword_query": raw_query.strip(),
            "confidence": 0.91,
        }
        if "附近" in raw_query and ("餐厅" in raw_query or "推荐个" in raw_query):
            payload["clarification_question"] = "你想看哪个城市或商圈？"
            payload["intent"] = "clarify"
            payload["clarification_type"] = "local_life"
            payload["clarification_options"] = [
                {"label": "发位置", "prompt": "我在北京朝阳"},
                {"label": "给城市", "prompt": "北京"},
            ]
        return payload

    def suggest_response(self, **_: object) -> dict[str, object]:
        return {}


class _FakeJavaBusinessClient:
    enabled = True
    enable_fallback = False

    def __init__(self) -> None:
        self.search_calls = 0
        self.detail_calls: list[int] = []
        self.coupon_calls: list[int] = []
        self.blog_hot_calls = 0

    def search_candidates(self, *, query: str, slots: LocalLifeSlots, limit: int = 5):
        self.search_calls += 1
        return [
            ShopRecord(
                id=1,
                name="卷卷烤肉",
                type_id=1,
                type_name="烤肉",
                area="朝阳",
                address="朝阳区测试路1号",
                x=116.4,
                y=39.9,
                avg_price=128.0,
                sold=88,
                comments=120,
                score=4.7,
                open_hours="10:00-22:00",
                distance_km=1.1,
                parking=True,
                quiet_score=0.85,
                family_friendly=True,
                elder_friendly=True,
                tags=["quiet", "parking_available"],
                review_summary="环境安静，适合约会和家庭聚餐。",
                evidence_texts=["店里环境比较安静。"],
                source="java",
            ),
            ShopRecord(
                id=2,
                name="朴朴家常菜",
                type_id=2,
                type_name="家常菜",
                area="海淀",
                address="海淀区测试路2号",
                x=116.3,
                y=39.95,
                avg_price=98.0,
                sold=66,
                comments=90,
                score=4.5,
                open_hours="09:00-21:00",
                distance_km=2.2,
                parking=False,
                quiet_score=0.6,
                family_friendly=True,
                elder_friendly=True,
                tags=["family_friendly"],
                review_summary="适合家庭聚餐。",
                evidence_texts=["适合带娃。"],
                source="java",
            ),
        ][:limit]

    def get_shop_detail(self, shop_id: int):
        self.detail_calls.append(int(shop_id))
        if int(shop_id) == 1:
            return ShopRecord(
                id=1,
                name="卷卷烤肉",
                type_id=1,
                type_name="烤肉",
                area="朝阳",
                address="朝阳区测试路1号",
                x=116.4,
                y=39.9,
                avg_price=128.0,
                sold=88,
                comments=120,
                score=4.7,
                open_hours="10:00-22:00",
                distance_km=1.1,
                parking=True,
                quiet_score=0.85,
                family_friendly=True,
                elder_friendly=True,
                tags=["quiet", "parking_available"],
                review_summary="环境安静，适合约会和家庭聚餐。",
                evidence_texts=["店里环境比较安静。"],
                source="java",
            )
        return ShopRecord(
            id=int(shop_id),
            name=f"店铺{shop_id}",
            type_id=2,
            type_name="家常菜",
            area="海淀",
            address="海淀区测试路2号",
            x=116.3,
            y=39.95,
            avg_price=98.0,
            sold=66,
            comments=90,
            score=4.5,
            open_hours="09:00-21:00",
            distance_km=2.2,
            parking=False,
            quiet_score=0.6,
            family_friendly=True,
            elder_friendly=True,
            tags=["family_friendly"],
            review_summary="适合家庭聚餐。",
            evidence_texts=["适合带娃。"],
            source="java",
        )

    def get_coupon_list(self, shop_id: int):
        self.coupon_calls.append(int(shop_id))
        return [
            VoucherRecord(
                id=101,
                shop_id=int(shop_id),
                shop_name="卷卷烤肉",
                title="满100减20",
                sub_title="家庭聚餐券",
                pay_value=100.0,
                actual_value=80.0,
                stock=50,
                source="java",
            )
        ]

    def check_open_status(self, shop):
        return {
            "open_status": "open",
            "open_now": True,
            "open_hours": getattr(shop, "open_hours", None),
        }

    def get_distance_eta(self, shop, *, lat, lng):
        return {
            "distance_km": getattr(shop, "distance_km", 1.1),
            "eta_minutes": 12,
            "lat": lat,
            "lng": lng,
        }

    def get_blog_hot(self, current: int = 1):
        self.blog_hot_calls += 1
        return [
            BlogRecord(
                id=201,
                shop_id=1,
                user_id=99,
                title="适合约会的烤肉店",
                content="环境比较安静，适合情侣约会。",
                liked=88,
                comments=12,
                source="java",
            )
        ]


class _FakeLocalLifeRetriever:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def retrieve_local_life_evidence(self, query: str, **kwargs: object) -> LocalLifeEvidencePack:
        payload = {"query": query, **kwargs}
        self.calls.append(payload)
        route = str(kwargs.get("route") or "merchant_reasoning")
        strategy_map = {
            "structured_first": "business_candidates->parent_child_rag->shop_rerank",
            "merchant_reasoning": "parent_child_rag->shop_rerank",
        }
        return LocalLifeEvidencePack(
            query=query,
            filters={
                "city": kwargs.get("city"),
                "area": kwargs.get("area"),
                "category": kwargs.get("category"),
                "candidate_shop_ids": list(kwargs.get("candidate_shop_ids") or []),
            },
            parent_evidences=[],
            total_child_hits=0,
            retrieval_strategy=strategy_map.get(route, "test"),
            route=route,
            route_reason="test",
        )


def _make_subgraph() -> tuple[LocalLifeSubgraph, _FakeJavaBusinessClient, _FakeLocalLifeRetriever]:
    business_client = _FakeJavaBusinessClient()
    retriever = _FakeLocalLifeRetriever()
    subgraph = LocalLifeSubgraph(
        business_client=business_client,
        model_assistant=_FakeLocalLifeAssistant(),
        local_life_retriever=retriever,
    )
    return subgraph, business_client, retriever


class P0RoutingReviewRuntimeTestCase(unittest.TestCase):
    def test_case1_multi_facet_query(self) -> None:
        query = "附近有没有适合约会、现在营业、最好有券的火锅？"
        slots = LocalLifeSlots(category="火锅", scene="date", city="北京")
        user_need = UserNeedParser.parse(
            query,
            slots=slots,
            intent=LocalLifeIntentType.RESTAURANT_RECOMMENDATION,
            client_context={"city": "北京", "lat": 39.9, "lng": 116.4},
            session_context={},
        )
        facet_names = [facet.name for facet in user_need.required_facets]
        self.assertIn("scene_fit", facet_names)
        self.assertIn("open_status", facet_names)
        self.assertIn("coupon", facet_names)
        self.assertIn("category", facet_names)
        self.assertIn("location", facet_names)

        review_result = RouteReview.review(
            user_need=user_need,
            initial_route=LocalLifeRouteDecision(
                route="merchant_reasoning",
                retrieval_strategy="parent_child_rag->shop_rerank",
                route_reason="merchant_reasoning_default",
                use_business_candidates=False,
                use_qdrant=True,
            ),
            clarification=ClarificationDecision(need_clarification=False),
            client_context={"city": "北京", "lat": 39.9, "lng": 116.4},
            session_context={},
        )
        self.assertTrue(review_result.intercepted)
        self.assertTrue(review_result.execution_requirements.execute_rag)
        self.assertIn("get_coupon_list", review_result.execution_requirements.execute_tools)
        self.assertIn("check_open_status", review_result.execution_requirements.execute_tools)

        subgraph, business_client, retriever = _make_subgraph()
        events = list(
            subgraph.run_stream(
                ChatTurnCommand(
                    trace_id="trace-case1",
                    session_id="session-case1",
                    turn_id="turn-case1",
                    user_id="user-case1",
                    message=query,
                    page="meituan_search_box",
                    client_context={"city": "北京", "lat": 39.9, "lng": 116.4},
                )
            )
        )
        self.assertEqual(business_client.search_calls, 1)
        self.assertEqual(len(retriever.calls), 1)
        self.assertEqual(retriever.calls[0]["route"], "structured_first")
        self.assertFalse(any(event.event_type == "clarification_card" for event in events))
        final_payload = _first_event(events, "final").payload
        self.assertTrue(final_payload["context"]["execution_requirements"]["execute_rag"])
        self.assertEqual(final_payload["context"]["route_review"]["reviewed_route"]["route"], "structured_first")
        self.assertIn("满100减20", final_payload["answer_text"])

    def test_case2_dynamic_single_facet(self) -> None:
        query = "这家现在有券吗？"
        slots = LocalLifeSlots()
        user_need = UserNeedParser.parse(
            query,
            slots=slots,
            intent=LocalLifeIntentType.COUPON,
            client_context={},
            session_context={"last_candidates": [{"shop_id": 1, "name": "卷卷烤肉"}]},
        )
        self.assertEqual(len(user_need.context_refs), 1)
        self.assertEqual(user_need.context_refs[0].id, "1")

        review_result = RouteReview.review(
            user_need=user_need,
            initial_route=LocalLifeRouteDecision(
                route="merchant_reasoning",
                retrieval_strategy="parent_child_rag->shop_rerank",
                route_reason="merchant_reasoning_default",
                use_business_candidates=True,
                use_qdrant=True,
            ),
            clarification=ClarificationDecision(need_clarification=False),
            client_context={},
            session_context={"last_candidates": [{"shop_id": 1, "name": "卷卷烤肉"}]},
        )
        self.assertFalse(review_result.execution_requirements.execute_rag)
        self.assertIn("get_coupon_list", review_result.execution_requirements.execute_tools)

        subgraph, business_client, retriever = _make_subgraph()
        events = list(
            subgraph.run_stream(
                ChatTurnCommand(
                    trace_id="trace-case2",
                    session_id="session-case2",
                    turn_id="turn-case2",
                    user_id="user-case2",
                    message=query,
                    page="meituan_search_box",
                ),
                persistent_context=PersistentSessionContext(
                    last_candidates=[{"shop_id": 1, "name": "卷卷烤肉"}]
                ),
            )
        )
        self.assertEqual(business_client.search_calls, 0)
        self.assertEqual(len(retriever.calls), 0)
        final_payload = _first_event(events, "final").payload
        self.assertFalse(final_payload["context"]["execution_requirements"]["execute_rag"])
        self.assertEqual(final_payload["context"]["tool_results"][0]["tool_name"], "get_coupon_list")
        self.assertIn("卷卷烤肉当前有1张券", final_payload["answer_text"])

    def test_case3_static_experience_facet(self) -> None:
        query = "这家适合约会吗？"
        slots = LocalLifeSlots(scene="date")
        user_need = UserNeedParser.parse(
            query,
            slots=slots,
            intent=LocalLifeIntentType.DETAIL,
            client_context={},
            session_context={"last_candidates": [{"shop_id": 1, "name": "卷卷烤肉"}]},
        )
        facet_names = [facet.name for facet in user_need.required_facets]
        self.assertIn("scene_fit", facet_names)
        self.assertNotIn("coupon", facet_names)
        self.assertNotIn("open_status", facet_names)

        review_result = RouteReview.review(
            user_need=user_need,
            initial_route=LocalLifeRouteDecision(
                route="general_chat",
                retrieval_strategy="general_answer_only",
                route_reason="default",
                use_business_candidates=False,
                use_qdrant=False,
            ),
            clarification=ClarificationDecision(need_clarification=False),
            client_context={},
            session_context={"last_candidates": [{"shop_id": 1, "name": "卷卷烤肉"}]},
        )
        self.assertTrue(review_result.execution_requirements.execute_rag)
        self.assertNotIn("get_coupon_list", review_result.execution_requirements.execute_tools)
        self.assertNotIn("check_open_status", review_result.execution_requirements.execute_tools)

        subgraph, business_client, retriever = _make_subgraph()
        events = list(
            subgraph.run_stream(
                ChatTurnCommand(
                    trace_id="trace-case3",
                    session_id="session-case3",
                    turn_id="turn-case3",
                    user_id="user-case3",
                    message=query,
                    page="meituan_search_box",
                ),
                persistent_context=PersistentSessionContext(
                    last_candidates=[{"shop_id": 1, "name": "卷卷烤肉"}]
                ),
            )
        )
        self.assertEqual(business_client.search_calls, 0)
        self.assertEqual(len(retriever.calls), 1)
        self.assertTrue(retriever.calls[0]["candidate_shop_ids"])
        final_payload = _first_event(events, "final").payload
        self.assertTrue(final_payload["context"]["execution_requirements"]["execute_rag"])
        self.assertNotIn("get_coupon_list", final_payload["context"]["route_review"]["execution_requirements"]["execute_tools"])

    def test_case4_intercept_wrong_generic_clarification(self) -> None:
        query = "附近推荐个适合带娃的餐厅"
        subgraph, business_client, retriever = _make_subgraph()
        events = list(
            subgraph.run_stream(
                ChatTurnCommand(
                    trace_id="trace-case4",
                    session_id="session-case4",
                    turn_id="turn-case4",
                    user_id="user-case4",
                    message=query,
                    page="meituan_search_box",
                    client_context={"city": "北京", "lat": 39.9, "lng": 116.4},
                )
            )
        )
        self.assertEqual(business_client.search_calls, 1)
        self.assertEqual(len(retriever.calls), 1)
        self.assertFalse(any(event.event_type == "clarification_card" for event in events))
        final_payload = _first_event(events, "final").payload
        self.assertTrue(final_payload["context"]["execution_requirements"]["execute_rag"])
        self.assertNotIn("请补充", final_payload["answer_text"])

    def test_case5_retain_slot_clarification(self) -> None:
        query = "附近推荐个餐厅"
        subgraph, business_client, retriever = _make_subgraph()
        events = list(
            subgraph.run_stream(
                ChatTurnCommand(
                    trace_id="trace-case5",
                    session_id="session-case5",
                    turn_id="turn-case5",
                    user_id="user-case5",
                    message=query,
                    page="meituan_search_box",
                )
            )
        )
        clarification_event = _first_event(events, "clarification_card")
        final_payload = _first_event(events, "final").payload
        self.assertEqual(business_client.search_calls, 0)
        self.assertEqual(len(retriever.calls), 0)
        self.assertEqual(clarification_event.payload["ambiguity_type"], "slot_clarify")
        self.assertIn("位置", clarification_event.payload["question"])
        self.assertEqual(final_payload["context"]["route_decision"], "clarify")
        self.assertIn("位置", final_payload["answer_text"])

    def test_case6_reference_resolution_failed(self) -> None:
        query = "它现在营业吗？"
        subgraph, business_client, retriever = _make_subgraph()
        events = list(
            subgraph.run_stream(
                ChatTurnCommand(
                    trace_id="trace-case6",
                    session_id="session-case6",
                    turn_id="turn-case6",
                    user_id="user-case6",
                    message=query,
                    page="meituan_search_box",
                )
            )
        )
        clarification_event = _first_event(events, "clarification_card")
        final_payload = _first_event(events, "final").payload
        self.assertEqual(business_client.search_calls, 0)
        self.assertEqual(len(retriever.calls), 0)
        self.assertEqual(clarification_event.payload["ambiguity_type"], "reference_clarify")
        self.assertIn("哪家店", clarification_event.payload["question"])
        self.assertEqual(final_payload["context"]["route_decision"], "clarify")
        self.assertIn("哪家店", final_payload["answer_text"])

    def test_case7_shop_id_extraction_pattern(self) -> None:
        from learning_agent_service.local_life.slot_extractor import extract_slots
        from learning_agent_service.local_life.schemas import QueryUnderstandingResult, LocationNorm

        # Test shop:5 in raw_query
        slots, clarification, intent = extract_slots(
            QueryUnderstandingResult(
                normalized_query="shop:5 有券吗",
                semantic_query="shop:5 有券吗",
                keyword_query="shop:5 有券吗",
                location_norm=LocationNorm(city="北京"),
            ),
            "shop:5 有券吗",
        )
        self.assertEqual(slots.shop_ids, [5])

        # Test shop:12 in shop_query model_hint
        slots, clarification, intent = extract_slots(
            QueryUnderstandingResult(
                normalized_query="有券吗",
                semantic_query="有券吗",
                keyword_query="有券吗",
                location_norm=LocationNorm(city="北京"),
            ),
            "有券吗",
            model_hint={"shop_query": "shop:12"},
        )
        self.assertEqual(slots.shop_ids, [12])

    def test_case8_implicit_reference_resolution(self) -> None:
        # Test implicit reference for "有券吗"
        slots = LocalLifeSlots()
        user_need = UserNeedParser.parse(
            "有券吗",
            slots=slots,
            intent=LocalLifeIntentType.COUPON,
            client_context={},
            session_context={"selected_shop_id": 5, "selected_shop_name": "海底捞"},
        )
        self.assertEqual(len(user_need.context_refs), 1)
        self.assertEqual(user_need.context_refs[0].id, "5")
        self.assertEqual(user_need.context_refs[0].name, "海底捞")

    def test_case9_implicit_reference_resolution_with_shop_str(self) -> None:
        # Test implicit reference for "有券吗" when only current_shop = "shop:5" is stored (RAG fallback path context)
        slots = LocalLifeSlots()
        user_need = UserNeedParser.parse(
            "有券吗",
            slots=slots,
            intent=LocalLifeIntentType.COUPON,
            client_context={},
            session_context={"current_shop": "shop:5", "selected_shop_name": "shop:5"},
        )
        self.assertEqual(len(user_need.context_refs), 1)
        self.assertEqual(user_need.context_refs[0].id, "5")
        self.assertEqual(user_need.context_refs[0].name, "shop:5")

    def test_case10_subgraph_resolve_review_shop_ids_with_shop_str(self) -> None:
        # Test subgraph _resolve_review_shop_ids properly extracts 5 from "shop:5" session context key
        from learning_agent_service.local_life.subgraph import _resolve_review_shop_ids
        slots = LocalLifeSlots()
        user_need = UserNeedParser.parse(
            "有券吗",
            slots=slots,
            intent=LocalLifeIntentType.COUPON,
            client_context={},
            session_context={"current_shop": "shop:5", "selected_shop_name": "shop:5"},
        )
        resolved = _resolve_review_shop_ids(
            user_need=user_need,
            slots=slots,
            session_context={"current_shop": "shop:5", "selected_shop_name": "shop:5"},
        )
        self.assertIn(5, resolved)

    def test_case11_explicit_entity_resolution_with_ellipsis_suffix(self) -> None:
        # Test EntityResolver with "那朴朴家常菜呢？"
        from learning_agent_service.local_life.entity_resolver import EntityResolver
        slots = LocalLifeSlots()
        slots.shop_ids = [2]
        contract = EntityResolver().resolve(
            raw_query="那朴朴家常菜呢？",
            slots=slots,
            session_context={"selected_shop_id": 5, "selected_shop_name": "海底捞"},
        )
        self.assertEqual(contract.resolved_shop_name, "朴朴家常菜")
        self.assertEqual(contract.resolved_shop_id, 2)

    def test_case12_subgraph_category_filtering(self) -> None:
        # Test that when slots.category is "火锅", any non-hotpot shops are filtered out
        subgraph, client, retriever = _make_subgraph()
        
        command = ChatTurnCommand(
            trace_id="trace-category-filter",
            session_id="session-category-filter",
            turn_id="turn-category-filter",
            user_id="user-category-filter",
            message="附近有没有适合情侣约会、现在营业、最好有券的火锅店",
            client_context={"city": "北京", "lat": 39.9, "lng": 116.4},
        )
        
        # 2. Mock three candidates: only shop 5 is hotpot
        from learning_agent_service.local_life.schemas import ShopRecord
        mock_candidates = [
            ShopRecord(
                id=1,
                name="卷卷烤肉",
                type_id=1,
                type_name="烤肉",
                area="朝阳",
                address="朝阳区1号",
                x=116.4,
                y=39.9,
                avg_price=128.0,
                sold=88,
                comments=120,
                score=4.7,
                open_hours="10:00-22:00",
                distance_km=1.1,
                source="java",
            ),
            ShopRecord(
                id=2,
                name="朴朴家常菜",
                type_id=2,
                type_name="家常菜",
                area="海淀",
                address="海淀区2号",
                x=116.3,
                y=39.95,
                avg_price=98.0,
                sold=66,
                comments=90,
                score=4.5,
                open_hours="09:00-21:00",
                distance_km=2.2,
                source="java",
            ),
            ShopRecord(
                id=5,
                name="海底捞火锅",
                type_id=5,
                type_name="火锅",
                area="朝阳",
                address="朝阳区3号",
                x=116.4,
                y=39.9,
                avg_price=104.0,
                sold=99,
                comments=200,
                score=4.8,
                open_hours="10:00-22:00",
                distance_km=1.5,
                source="java",
            ),
        ]
        from unittest.mock import MagicMock
        client.search_candidates = MagicMock(return_value=mock_candidates)
        
        # 3. Execute stream
        events = list(subgraph.run_stream(command))
        
        # 4. Check that only "海底捞火锅" remained in the final ranked candidates
        final_event = _first_event(events, "final")
        payload = final_event.payload
        ranked = payload.get("ranked_candidates", [])
        
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0].get("name"), "海底捞火锅")


if __name__ == "__main__":
    unittest.main()
