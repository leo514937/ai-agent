from __future__ import annotations

import os
import sys
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

TESTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent
SRC_ROOT = PROJECT_ROOT / "src"
for candidate in (str(TESTS_DIR), str(PROJECT_ROOT), str(SRC_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from learning_agent_service.config.settings_impl import Settings
import learning_agent_service.config.settings_impl as settings_module


class SettingsLocalLifeAliasTestCase(unittest.TestCase):
    def test_short_env_aliases_are_accepted_for_langgraph_flags(self) -> None:
        env = {
            "LOCAL_LIFE_USE_LANGGRAPH": "false",
        }
        with patch.dict(os.environ, env, clear=False):
            settings = Settings()

        self.assertFalse(settings.local_life_use_langgraph)
        self.assertFalse(hasattr(settings, "local_life_langgraph_fallback_legacy"))

    def test_memory_embedding_model_falls_back_to_openai_embedding_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text("", encoding="utf-8")

            with patch.object(
                settings_module,
                "ENV_FILE_CANDIDATES",
                (str(env_file),),
            ), patch.dict(
                os.environ,
                {"LEARNING_AGENT_OPENAI_EMBEDDING_MODEL": "qwen/qwen3-embedding-8b"},
                clear=True,
            ):
                settings = Settings()

        self.assertEqual(settings.embedding.memory_model, "qwen/qwen3-embedding-8b")


if __name__ == "__main__":
    unittest.main()
