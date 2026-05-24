from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from learning_agent_service.domain import ChatTurnCommand, PersistentSessionContext, TurnUnderstandingRequest
from learning_agent_service.rag.heuristics import HeuristicModelGateway
from learning_agent_service.local_life.query_rewriter import normalize_query
from learning_agent_service.local_life.schemas import LocalLifeIntentType
from learning_agent_service.local_life.slot_extractor import extract_slots


class WorkflowRoutingTestCase(unittest.TestCase):
    def test_recommendation_query_routes_to_no_clarification_when_constraints_are_clear(self) -> None:
        client_context = {
            "city": "北京",
            "location": {"lat": 39.9, "lng": 116.4},
            "entry": "meituan_search_box",
            "timestamp": "2026-05-13T18:20:00",
        }
        understanding = normalize_query(
            "今晚想带爸妈吃饭，别太吵，人均150左右，离我近一点",
            client_context=client_context,
            session_context={},
        )
        slots, clarification, intent = extract_slots(
            understanding,
            "今晚想带爸妈吃饭，别太吵，人均150左右，离我近一点",
            client_context=client_context,
            session_context={},
        )

        self.assertEqual(intent, LocalLifeIntentType.RESTAURANT_RECOMMENDATION)
        self.assertFalse(clarification.need_clarification)
        self.assertEqual(slots.city, "北京")
        self.assertEqual(slots.scene, "family_dinner")
        self.assertIn("quiet", slots.preferences)
        self.assertIn("elder_friendly", slots.preferences)
        self.assertEqual(slots.price.target, 150.0)
        self.assertEqual(slots.location.radius_km, 3.0)
        self.assertEqual(slots.page, "meituan_search_box")

    def test_bare_recommendation_query_still_returns_text_path(self) -> None:
        understanding = normalize_query("帮我推荐一下", client_context={}, session_context={})
        slots, clarification, intent = extract_slots(
            understanding,
            "帮我推荐一下",
            client_context={},
            session_context={},
        )

        self.assertEqual(intent, LocalLifeIntentType.RESTAURANT_RECOMMENDATION)
        self.assertFalse(clarification.need_clarification)
        self.assertEqual(slots.category, "餐厅")

    def test_second_candidate_follow_up_routes_to_detail(self) -> None:
        session_context = {
            "last_candidates": [
                {"shop_id": 101, "name": "某某家常菜"},
                {"shop_id": 202, "name": "某某粤菜馆"},
            ]
        }
        understanding = normalize_query("第二家怎么样", client_context={}, session_context=session_context)
        slots, clarification, intent = extract_slots(
            understanding,
            "第二家怎么样",
            client_context={},
            session_context=session_context,
        )

        self.assertEqual(intent, LocalLifeIntentType.DETAIL)
        self.assertFalse(clarification.need_clarification)
        self.assertEqual(slots.shop_ids, [202])
        self.assertEqual(slots.action, LocalLifeIntentType.DETAIL)

    def test_profile_question_keeps_direct_answer_priority_over_shop_context(self) -> None:
        gateway = HeuristicModelGateway()
        request = TurnUnderstandingRequest(
            command=ChatTurnCommand(
                trace_id="trace-1",
                session_id="session-1",
                turn_id="turn-1",
                user_id="user-1",
                message="你有什么功能",
                page="assistant",
                topic_hint="某某家常菜",
                client_context={"page": "assistant"},
            ),
            persistent=PersistentSessionContext(
                current_topic="某某家常菜",
                last_candidates=[{"shop_id": 101, "name": "某某家常菜"}],
            ),
        )

        result = gateway.classify_turn(request)

        self.assertFalse(result.needs_rag)
        self.assertFalse(result.needs_tool)
        self.assertEqual(result.intent.value, "explain")
        self.assertEqual(result.extra["direct_response_kind"], "profile")
        self.assertEqual(result.extra["route_candidate"], "profile")
        self.assertEqual(result.extra["route_candidates"][0]["name"], "profile")
        self.assertFalse(result.key_slots.get("domain") == "local_life")

    def test_topic_hint_alone_does_not_pull_generic_question_into_local_life(self) -> None:
        gateway = HeuristicModelGateway()
        request = TurnUnderstandingRequest(
            command=ChatTurnCommand(
                trace_id="trace-2",
                session_id="session-2",
                turn_id="turn-2",
                user_id="user-2",
                message="你有什么工能",
                page="assistant",
                topic_hint="某某家常菜",
                client_context={"page": "assistant"},
            ),
            persistent=PersistentSessionContext(),
        )

        result = gateway.classify_turn(request)

        self.assertFalse(result.needs_rag)
        self.assertFalse(result.needs_tool)
        self.assertEqual(result.intent.value, "explain")
        self.assertNotEqual(result.extra.get("route_candidate"), "local_life")
        self.assertFalse(result.key_slots.get("domain") == "local_life")


if __name__ == "__main__":
    unittest.main()
