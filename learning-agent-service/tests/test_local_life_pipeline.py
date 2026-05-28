from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from learning_agent_service.domain import ChatTurnCommand, PersistentSessionContext
from learning_agent_service.local_life import build_response_bundle, extract_slots, normalize_query
from learning_agent_service.local_life.subgraph import LocalLifeSubgraph
from learning_agent_service.rag.local_life_retrieval import LocalLifeEvidencePack
from learning_agent_service.local_life.schemas import (
    BlogRecord,
    EvidenceClaim,
    LocalLifeSlots,
    LocationNorm,
    PriceNorm,
    RankedCandidate,
    ShopRecord,
    VoucherRecord,
)


class _FakeLocalLifeAssistant:
    enabled = True

    def suggest_understanding(self, **_: object) -> dict[str, object]:
        return {
            "normalized_query": "搜索北京今晚家庭聚餐环境安静人均150元的粤菜馆",
            "semantic_query": "北京 今晚 家庭聚餐 环境安静 人均150元 粤菜",
            "keyword_query": "北京 粤菜 安静 150",
            "city": "北京",
            "category": "粤菜",
            "preferences": ["quiet", "parking_available"],
            "companions": ["parents"],
            "confidence": 0.92,
            "route_reason": "model-guided",
        }

    def suggest_response(self, **_: object) -> dict[str, object]:
        return {
            "answer_text": "模型建议：先按你说的条件筛一遍。",
            "suggested_replies": [
                {"label": "看第二家", "prompt": "看第二家"},
                {"label": "找更安静的", "prompt": "找更安静的"},
            ],
        }


class _FakeJavaBusinessClient:
    enabled = True
    enable_fallback = False

    def __init__(self) -> None:
        self.search_calls = 0
        self.coupon_calls = 0
        self.blog_hot_calls = 0

    def search_candidates(self, *, query: str, slots: LocalLifeSlots, limit: int = 5):
        self.search_calls += 1
        return [
            ShopRecord(
                id=1001,
                name="示例粤菜馆",
                type_id=1,
                type_name="粤菜",
                area="朝阳",
                address="朝阳区示例路1号",
                x=116.4,
                y=39.9,
                avg_price=148.0,
                sold=128,
                comments=256,
                score=4.8,
                open_hours="10:00-22:00",
                distance_km=1.2,
                parking=True,
                quiet_score=0.92,
                family_friendly=True,
                elder_friendly=True,
                tags=["quiet", "parking_available"],
                review_summary="环境安静，适合家庭聚餐。",
                evidence_texts=["评论摘要中多次提到环境安静。"],
                source="java",
            )
        ][:limit]

    def get_coupon_list(self, shop_id: int):
        self.coupon_calls += 1
        return [
            VoucherRecord(
                id=2001,
                shop_id=shop_id,
                shop_name="示例粤菜馆",
                title="满100减20",
                sub_title="家庭聚餐券",
                pay_value=100.0,
                actual_value=80.0,
                stock=50,
                source="java",
            )
        ]

    def get_shop_detail(self, shop_id: int):
        return ShopRecord(
            id=shop_id,
            name="示例粤菜馆",
            type_id=1,
            type_name="粤菜",
            area="朝阳",
            address="朝阳区示例路1号",
            x=116.4,
            y=39.9,
            avg_price=148.0,
            sold=128,
            comments=256,
            score=4.8,
            open_hours="10:00-22:00",
            distance_km=1.2,
            parking=True,
            quiet_score=0.92,
            family_friendly=True,
            elder_friendly=True,
            tags=["quiet", "parking_available"],
            review_summary="环境安静，适合家庭聚餐。",
            evidence_texts=["评论摘要中多次提到环境安静。"],
            source="java",
        )

    def check_open_status(self, shop):
        return {
            "status": "open",
            "is_open": True,
            "open_hours": getattr(shop, "open_hours", None) if not isinstance(shop, dict) else shop.get("open_hours"),
        }

    def get_distance_eta(self, shop, *, lat, lng):
        return {
            "distance_km": getattr(shop, "distance_km", 1.2) if not isinstance(shop, dict) else shop.get("distance_km", 1.2),
            "eta_minutes": 12,
            "lat": lat,
            "lng": lng,
        }

    def get_blog_hot(self, current: int = 1):
        self.blog_hot_calls += 1
        return [
            BlogRecord(
                id=3001,
                shop_id=1001,
                user_id=9001,
                title="环境安静的家庭聚餐体验",
                content="店内环境安静，适合带爸妈一起吃饭。",
                liked=88,
                comments=12,
                source="java",
            )
        ][: max(0, int(current))]


class _RecordingSessionContextStore:
    def __init__(self) -> None:
        self.saved_context = None
        self.saved_runtime = None

    def save(self, context, runtime) -> None:
        self.saved_context = context
        self.saved_runtime = runtime


class _FakeLocalLifeRetriever:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def retrieve_local_life_evidence(self, query: str, **kwargs: object) -> LocalLifeEvidencePack:
        payload = {"query": query, **kwargs}
        self.calls.append(payload)
        route = str(kwargs.get("route") or "merchant_reasoning")
        strategy_map = {
            "structured_first": "business_candidates->parent_child_rag->shop_rerank",
            "compare_multi_parent": "business_candidates->multi_parent_rag->shop_rerank",
            "guide_rule_rag": "guide_rule_rag->parent_child_rag",
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


class LocalLifePipelineTestCase(unittest.TestCase):
    def test_model_hint_guides_rewrite_and_slots(self) -> None:
        raw_query = "今晚带爸妈吃饭，别太吵，人均150左右，离我近一点"
        understanding = normalize_query(
            raw_query,
            client_context={"city": "北京"},
            session_context={"current_city": "北京"},
            model_hint={
                "normalized_query": "搜索北京今晚家庭聚餐环境安静人均150元的粤菜馆",
                "semantic_query": "北京 今晚 家庭聚餐 环境安静 人均150元 粤菜",
                "keyword_query": "北京 粤菜 安静 150",
                "city": "北京",
                "category": "粤菜",
                "preferences": ["quiet", "parking_available"],
                "avoid": ["busy"],
                "confidence": 0.92,
                "route_reason": "model-guided",
            },
        )

        self.assertEqual(understanding.normalized_query, "搜索北京今晚家庭聚餐环境安静人均150元的粤菜馆")
        self.assertEqual(understanding.extra["rewrite_source"], "model+rule")
        self.assertEqual(understanding.extra["model_route_reason"], "model-guided")

        slots, clarification, intent = extract_slots(
            understanding,
            raw_query,
            client_context={"city": "北京"},
            session_context={"current_city": "北京"},
            model_hint={
                "city": "北京",
                "category": "粤菜",
                "preferences": ["quiet", "parking_available"],
                "companions": ["parents"],
                "shop_ids": [1001],
                "intent": "detail",
                "tool_name": "get_shop_detail",
                "tool_input": {
                    "shop_id": 1001,
                    "shop_name": "示例粤菜馆",
                    "city": "北京",
                },
                "confidence": 0.92,
            },
        )

        self.assertEqual(slots.city, "北京")
        self.assertEqual(slots.category, "粤菜")
        self.assertIn("quiet", slots.preferences)
        self.assertIn("parking_available", slots.preferences)
        self.assertIn("parents", slots.companions)
        self.assertEqual(slots.shop_ids, [1001])
        self.assertEqual(slots.tool_name, "get_shop_detail")
        self.assertEqual(slots.tool_input["shop_name"], "示例粤菜馆")
        self.assertEqual(intent.value, "detail")
        self.assertFalse(clarification.need_clarification)

    def test_response_bundle_carries_model_and_source_metadata(self) -> None:
        slots = LocalLifeSlots(
            category="粤菜",
            city="北京",
            location=LocationNorm(city="北京"),
            price=PriceNorm(target=150),
            scene="family_dinner",
            preferences=["quiet"],
            companions=["parents"],
        )
        candidate = RankedCandidate(
            shop_id=1001,
            name="示例粤菜馆",
            matched_requirements=["环境安静"],
            structured_features={
                "distance_km": 1.2,
                "avg_price": 138,
                "score": 4.5,
                "comments": 128,
            },
            evidence_features={},
            risk_flags=[],
            explainable_reasons=["离你近", "适合长辈"],
            vouchers=[],
            blog_snippets=[],
            score_breakdown={"distance": 0.5},
            rank_score=0.91,
        )
        claim = EvidenceClaim(
            chunk_id="chunk-1",
            shop_id=1001,
            claim="探店笔记提到环境安静",
            support_text="店内环境安静，适合家庭聚餐。",
            source_type="探店笔记",
            confidence=0.8,
            metadata={"shop_name": "示例粤菜馆"},
        )

        bundle = build_response_bundle(
            raw_query="今晚带爸妈吃饭，别太吵，人均150左右，离我近一点",
            slots=slots,
            ranked_candidates=[candidate],
            evidence_claims=[claim],
            page="meituan_search_box",
            current_topic="示例粤菜馆",
            selected_shop_id=1001,
            model_hint={
                "answer_text": "模型建议：先按你说的条件筛一遍。",
                "suggested_replies": [{"label": "看第二家", "prompt": "看第二家"}],
            },
            source_mode="java_business",
            degraded_reason=None,
            knowledge_freshness={"snapshot_version": "v1", "chunk_count": 12},
        )

        self.assertTrue(bundle.answer_text.startswith("模型建议：先按你说的条件筛一遍。"))
        self.assertEqual(bundle.source_mode, "java_business")
        self.assertIsNone(bundle.degraded_reason)
        self.assertEqual(bundle.retrieval_summary["source_mode"], "java_business")
        self.assertEqual(bundle.metrics["knowledge_freshness"]["snapshot_version"], "v1")
        self.assertEqual(bundle.context["source_mode"], "java_business")
        self.assertEqual(bundle.next_steps[0], "查看第一家详情")
        self.assertEqual(bundle.task_chain[0]["step"], "search")
        self.assertEqual(bundle.suggested_replies[0]["label"], "看第二家")

    def test_build_response_bundle_merges_coupon_and_environment_for_rag_plus_tool(self) -> None:
        slots = LocalLifeSlots(city="北京", location=LocationNorm(type="near_user", city="北京"))
        candidate = RankedCandidate(
            shop_id=1001,
            name="示例粤菜馆",
            matched_requirements=["离你近", "适合长辈"],
            structured_features={
                "distance_km": 1.2,
                "avg_price": 138,
                "score": 4.5,
                "comments": 128,
            },
            evidence_features={},
            risk_flags=[],
            explainable_reasons=["离你近", "适合长辈"],
            vouchers=[
                {
                    "id": 2001,
                    "title": "满100减20",
                    "sub_title": "家庭聚餐券",
                    "pay_value": 100.0,
                    "actual_value": 80.0,
                }
            ],
            blog_snippets=[],
            score_breakdown={"distance": 0.5},
            rank_score=0.91,
        )
        claim = EvidenceClaim(
            chunk_id="chunk-1",
            shop_id=1001,
            claim="探店笔记提到环境安静",
            support_text="店内环境安静，适合家庭聚餐。",
            source_type="探店笔记",
            confidence=0.8,
            metadata={"shop_name": "示例粤菜馆"},
        )

        bundle = build_response_bundle(
            raw_query="示例粤菜馆有券吗，环境怎么样",
            slots=slots,
            ranked_candidates=[candidate],
            evidence_claims=[claim],
            page="meituan_search_box",
            current_topic="示例粤菜馆",
            selected_shop_id=1001,
            route_decision="rag_plus_tool",
            model_hint={"answer_text": "这句不该出现在最终答案里。"},
            source_mode="java_business",
            degraded_reason=None,
            knowledge_freshness={"snapshot_version": "v1", "chunk_count": 12},
        )

        self.assertIn("满100减20", bundle.answer_text)
        self.assertIn("环境偏安静", bundle.answer_text)
        self.assertIn("比较适合家庭聚餐", bundle.answer_text)
        self.assertNotIn("这句不该出现在最终答案里", bundle.answer_text)

    def test_subgraph_uses_java_business_adapter_without_catalog_fallback(self) -> None:
        subgraph = LocalLifeSubgraph(
            business_client=_FakeJavaBusinessClient(),
            model_assistant=_FakeLocalLifeAssistant(),
        )
        events = list(
            subgraph.run_stream(
                ChatTurnCommand(
                    trace_id="trace-1",
                    session_id="session-1",
                    turn_id="turn-1",
                    user_id="user-1",
                    message="今晚带爸妈吃饭，别太吵，人均150左右，离我近一点",
                    page="meituan_search_box",
                    client_context={
                        "city": "北京",
                        "location": {"lat": 39.9, "lng": 116.4},
                        "entry": "meituan_search_box",
                    },
                )
            )
        )

        final_event = next(event for event in events if event.event_type == "final")
        payload = final_event.payload

        self.assertEqual(payload["source_mode"], "java_business")
        self.assertIsNone(payload["degraded_reason"])
        self.assertFalse(payload["fallback"])
        self.assertTrue(payload["answer_text"].startswith("模型建议：先按你说的条件筛一遍。"))
        self.assertEqual(payload["retrieval_summary"]["source_mode"], "java_business")
        self.assertEqual(payload["metrics"]["source_mode"], "java_business")
        self.assertEqual(payload["next_steps"][0], "查看第一家详情")
        self.assertEqual(payload["task_chain"][0]["step"], "search")
        self.assertEqual(payload["suggested_replies"][0]["label"], "看第二家")

    def test_subgraph_persists_current_shop_for_follow_up_turns(self) -> None:
        session_store = _RecordingSessionContextStore()
        subgraph = LocalLifeSubgraph(
            business_client=_FakeJavaBusinessClient(),
            model_assistant=_FakeLocalLifeAssistant(),
            session_context_store=session_store,
        )
        persistent_context = PersistentSessionContext(
            current_shop="示例粤菜馆",
            selected_shop_id=1001,
            selected_shop_name="示例粤菜馆",
            last_candidates=[{"shop_id": 1001, "name": "示例粤菜馆"}],
        )

        events = list(
            subgraph.run_stream(
                ChatTurnCommand(
                    trace_id="trace-current-shop",
                    session_id="session-current-shop",
                    turn_id="turn-current-shop",
                    user_id="user-current-shop",
                    message="这家店推荐菜",
                    page="meituan_search_box",
                    client_context={
                        "city": "北京",
                        "location": {"lat": 39.9, "lng": 116.4},
                        "entry": "meituan_search_box",
                    },
                ),
                persistent_context=persistent_context,
            )
        )

        final_event = next(event for event in events if event.event_type == "final")
        payload = final_event.payload

        self.assertEqual(payload["context"]["current_shop"], "示例粤菜馆")
        self.assertEqual(payload["context"]["selected_shop_name"], "示例粤菜馆")
        self.assertIsNotNone(session_store.saved_context)
        self.assertEqual(session_store.saved_context.current_shop, "示例粤菜馆")
        self.assertEqual(session_store.saved_context.selected_shop_name, "示例粤菜馆")
        self.assertEqual(session_store.saved_context.selected_shop_id, 1001)

    def test_subgraph_routes_structured_queries_through_business_candidates_then_qdrant(self) -> None:
        business_client = _FakeJavaBusinessClient()
        retriever = _FakeLocalLifeRetriever()
        subgraph = LocalLifeSubgraph(
            business_client=business_client,
            model_assistant=_FakeLocalLifeAssistant(),
            local_life_retriever=retriever,
        )

        events = list(
            subgraph.run_stream(
                ChatTurnCommand(
                    trace_id="trace-structured",
                    session_id="session-structured",
                    turn_id="turn-structured",
                    user_id="user-structured",
                    message="朝阳公园附近适合约会的家常菜，评分高，人均150左右，营业中",
                    page="meituan_search_box",
                    client_context={
                        "city": "北京",
                        "location": {"lat": 39.9, "lng": 116.4},
                        "entry": "meituan_search_box",
                    },
                )
            )
        )

        final_event = next(event for event in events if event.event_type == "final")
        payload = final_event.payload

        self.assertEqual(payload["metrics"]["local_life_route"], "structured_first")
        self.assertEqual(payload["metrics"]["local_life_retrieval_strategy"], "business_candidates->parent_child_rag->shop_rerank")
        self.assertEqual(business_client.search_calls, 1)
        self.assertEqual(retriever.calls[0]["route"], "structured_first")

    def test_subgraph_skips_local_life_rag_for_memory_question(self) -> None:
        business_client = _FakeJavaBusinessClient()
        retriever = _FakeLocalLifeRetriever()
        subgraph = LocalLifeSubgraph(
            business_client=business_client,
            model_assistant=_FakeLocalLifeAssistant(),
            local_life_retriever=retriever,
        )

        events = list(
            subgraph.run_stream(
                ChatTurnCommand(
                    trace_id="trace-memory",
                    session_id="session-memory",
                    turn_id="turn-memory",
                    user_id="user-memory",
                    message="你记得我们聊过什么吗",
                    page="meituan_search_box",
                )
            )
        )

        final_event = next(event for event in events if event.event_type == "final")
        payload = final_event.payload

        self.assertEqual(business_client.search_calls, 0)
        self.assertEqual(retriever.calls, [])
        self.assertEqual(payload["metrics"]["local_life_route"], "general_chat")
        self.assertEqual(payload["metrics"]["local_life_retrieval_strategy"], "general_answer_only")
        self.assertEqual(payload["citations"], [])
        self.assertEqual(payload["shops"], [])
        self.assertEqual(payload["vouchers"], [])

    def test_subgraph_routes_realtime_queries_away_from_qdrant(self) -> None:
        business_client = _FakeJavaBusinessClient()
        retriever = _FakeLocalLifeRetriever()
        subgraph = LocalLifeSubgraph(
            business_client=business_client,
            model_assistant=_FakeLocalLifeAssistant(),
            local_life_retriever=retriever,
        )

        events = list(
            subgraph.run_stream(
                ChatTurnCommand(
                    trace_id="trace-realtime",
                    session_id="session-realtime",
                    turn_id="turn-realtime",
                    user_id="user-realtime",
                    message="现在订单状态怎么样，能不能取消",
                    page="meituan_search_box",
                    client_context={"city": "北京"},
                )
            )
        )

        final_event = next(event for event in events if event.event_type == "final")
        payload = final_event.payload

        self.assertEqual(payload["metrics"]["local_life_route"], "realtime_tool")
        self.assertEqual(payload["metrics"]["local_life_retrieval_strategy"], "java_business_tool_only")
        self.assertEqual(business_client.search_calls, 0)
        self.assertEqual(len(retriever.calls), 0)

    def test_subgraph_handles_empty_persistent_context_for_recommend_query(self) -> None:
        subgraph = LocalLifeSubgraph()
        events = list(
            subgraph.run_stream(
                ChatTurnCommand(
                    trace_id="trace-empty-session",
                    session_id="session-empty-session",
                    turn_id="turn-empty-session",
                    user_id="user-empty-session",
                    message="推荐北京望京附近适合带爸妈吃饭、安静、有停车、人均150以内的家常菜",
                    page="ai",
                ),
                persistent_context=None,
            )
        )

        event_types = [event.event_type for event in events]
        self.assertIn("final", event_types)
        self.assertNotIn("clarification_card", event_types)
        self.assertNotIn("error", event_types)
        final_event = next(event for event in events if event.event_type == "final")
        self.assertIn("answer_text", final_event.payload)
        self.assertTrue(final_event.payload["answer_text"])


if __name__ == "__main__":
    unittest.main()
