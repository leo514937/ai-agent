from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from learning_agent_service.domain.memory import MemoryType
from learning_agent_service.memory.extraction import LLMMemoryExtractor, RuleBasedMemoryExtractor
from learning_agent_service.memory.models import (
    ExplicitUserSignals,
    MemoryPromotionInput,
    PersistentSessionContext,
)


class MemoryExtractionTestCase(unittest.TestCase):
    def test_rule_based_extractor_emits_preference_candidate_from_explicit_code_signal(self) -> None:
        payload = MemoryPromotionInput(
            session_id="session-1",
            turn_id="turn-1",
            user_id="user-1",
            query="请默认给代码",
            answer_text="好的",
            explicit_signals=ExplicitUserSignals(
                wants_code_examples=True,
                confirmed_code_examples=True,
            ),
            current_session=PersistentSessionContext(),
        )

        candidates = RuleBasedMemoryExtractor().extract(payload)
        self.assertTrue(any(item.memory_type == MemoryType.PREFERENCE and item.should_promote for item in candidates))

    def test_llm_extractor_is_noop_by_default(self) -> None:
        payload = MemoryPromotionInput(
            session_id="session-2",
            turn_id="turn-2",
            user_id="user-2",
            query="随便问问",
            answer_text="随便答答",
            explicit_signals=ExplicitUserSignals(),
            current_session=PersistentSessionContext(),
        )

        self.assertEqual(LLMMemoryExtractor().extract(payload), [])


if __name__ == "__main__":
    unittest.main()
