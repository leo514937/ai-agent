from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

TESTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent
SRC_ROOT = PROJECT_ROOT / "src"
for candidate in (str(TESTS_DIR), str(PROJECT_ROOT), str(SRC_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from learning_agent_service.config.settings_impl import Settings


class SettingsLocalLifeAliasTestCase(unittest.TestCase):
    def test_short_env_aliases_are_accepted_for_langgraph_flags(self) -> None:
        env = {
            "LOCAL_LIFE_USE_LANGGRAPH": "false",
            "LOCAL_LIFE_LANGGRAPH_FALLBACK_LEGACY": "false",
        }
        with patch.dict(os.environ, env, clear=False):
            settings = Settings()

        self.assertFalse(settings.local_life_use_langgraph)
        self.assertFalse(settings.local_life_langgraph_fallback_legacy)


if __name__ == "__main__":
    unittest.main()
