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

from learning_agent_service.local_life.prompt_engine import get_prompt_engine


class PromptEngineTestCase(unittest.TestCase):
    def test_loads_scene_config_and_few_shots(self) -> None:
        engine = get_prompt_engine()

        self.assertTrue(engine.has_config("multi_shop_recommendation"))

        messages = engine.build_messages(
            "multi_shop_recommendation",
            "推荐火锅",
            "候选店铺:\n1. 海底捞(望京店)\n2. 巴奴毛肚火锅(三里屯店)",
        )

        self.assertGreaterEqual(len(messages), 4)
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("本地生活助手", messages[0]["content"])
        self.assertEqual(messages[-1]["role"], "user")
        self.assertIn("推荐火锅", messages[-1]["content"])
        self.assertTrue(any(msg["role"] == "assistant" and "海底捞" in msg["content"] for msg in messages))


if __name__ == "__main__":
    unittest.main()
