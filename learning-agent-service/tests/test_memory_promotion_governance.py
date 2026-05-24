from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from learning_agent_service.memory.models import ExplicitUserSignals, MemoryPromotionInput, PersistentSessionContext
from learning_agent_service.memory.promotion import MemoryPromotionPolicy


class MemoryPromotionGovernanceTestCase(unittest.TestCase):
    def test_evaluate_attaches_governed_candidates(self) -> None:
        result = MemoryPromotionPolicy().evaluate(
            MemoryPromotionInput(
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
        )

        governed_candidates = list(result.extra.get("governed_candidates", []))
        self.assertTrue(governed_candidates)
        self.assertEqual(governed_candidates[0].governance_action, "approve")
        self.assertTrue(governed_candidates[0].should_promote)


if __name__ == "__main__":
    unittest.main()
