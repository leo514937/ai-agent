from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from learning_agent_service.application.rag_gate import (
    ALLOW,
    DENY,
    UNCERTAIN,
    RagGateRequest,
    RagGateVote,
    RagRouteGate,
    classify_rag_rule,
    compose_direct_response_text,
)
from learning_agent_service.domain.enums import IntentType


class RagGateTestCase(unittest.TestCase):
    def test_rule_rejects_greeting(self) -> None:
        vote = classify_rag_rule(RagGateRequest(raw_query="你好"))
        self.assertEqual(vote.vote, DENY)
        self.assertEqual(vote.response_kind, "greeting")

    def test_rule_allows_technical_question(self) -> None:
        vote = classify_rag_rule(
            RagGateRequest(
                raw_query="为什么 ThreadPoolExecutor 不流式？",
                intent=IntentType.EXPLAIN,
                intent_confidence=0.82,
            )
        )
        self.assertEqual(vote.vote, ALLOW)

    def test_rule_allows_profile_question_for_direct_answer_path(self) -> None:
        vote = classify_rag_rule(
            RagGateRequest(
                raw_query="你有什么功能",
                intent=IntentType.EXPLAIN,
                intent_confidence=0.88,
            )
        )

        self.assertEqual(vote.vote, ALLOW)
        self.assertEqual(vote.response_kind, "profile")
        self.assertEqual(vote.reason, "profile_query")

    def test_rule_allows_short_location_answer_when_pending_clarification_exists(self) -> None:
        vote = classify_rag_rule(
            RagGateRequest(
                raw_query="北京",
                pending_clarification={
                    "ambiguity_type": "location",
                    "options": [
                        {"id": "opt-1", "label": "北京", "value": "北京", "description": "北京"},
                    ],
                },
            )
        )

        self.assertEqual(vote.vote, ALLOW)
        self.assertEqual(vote.reason, "pending_clarification")

    def test_vote_combination_is_conservative(self) -> None:
        allow_gate = RagRouteGate(
            llm_judge=lambda request: RagGateVote(vote=ALLOW, reason="llm_allow", confidence=0.7)
        )
        deny_gate = RagRouteGate(
            llm_judge=lambda request: RagGateVote(vote=DENY, reason="llm_deny", confidence=0.7)
        )
        uncertain_gate = RagRouteGate(
            llm_judge=lambda request: RagGateVote(vote=UNCERTAIN, reason="llm_uncertain", confidence=0.2)
        )
        request = RagGateRequest(raw_query="请解释 Spring AOP 为什么这样设计", intent=IntentType.EXPLAIN, intent_confidence=0.91)

        self.assertTrue(allow_gate.decide(request).allowed)
        self.assertFalse(deny_gate.decide(request).allowed)
        self.assertTrue(uncertain_gate.decide(request).allowed)

    def test_direct_response_text_matches_gate_kind(self) -> None:
        self.assertIn("你好，我在", compose_direct_response_text("你好", "greeting"))
        self.assertIn("不客气", compose_direct_response_text("谢谢", "thanks"))
        self.assertIn("更具体", compose_direct_response_text("？", "low_info"))
        self.assertIn("补充", compose_direct_response_text("", "empty"))

    def test_direct_response_text_includes_query_hint_for_technical_turn(self) -> None:
        text = compose_direct_response_text("解释一下 Spring AOP 的原理", None)

        self.assertIn("Spring AOP", text)
        self.assertIn("原理", text)
        self.assertIn("继续", text)

    def test_direct_response_text_includes_profile_summary(self) -> None:
        text = compose_direct_response_text("你有什么功能", "profile")

        self.assertIn("通用问答", text)
        self.assertIn("本地生活", text)
        self.assertIn("推荐", text)

    def test_direct_response_text_handles_unserviceable_location(self) -> None:
        text = compose_direct_response_text("北极", "location_unavailable")

        self.assertIn("不太适合本地生活推荐", text)
        self.assertIn("具体城市", text)


if __name__ == "__main__":
    unittest.main()
