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

from learning_agent_service.application.workflow.adapters import _build_recommendation_answer_text


class RecommendationAnswerTextTestCase(unittest.TestCase):
    def test_build_recommendation_answer_text_uses_real_names(self) -> None:
        answer = _build_recommendation_answer_text(["海底捞", "巴奴", "新白鹿"], 3)

        self.assertIn("我帮你推荐以下这几家店铺", answer)
        self.assertIn("1. 海底捞", answer)
        self.assertIn("2. 巴奴", answer)
        self.assertIn("3. 新白鹿", answer)
        self.assertNotIn("附近商家A", answer)

    def test_build_recommendation_answer_text_falls_back_to_plain_text(self) -> None:
        answer = _build_recommendation_answer_text([], 3, fallback_text="我暂时没找到合适的店。")

        self.assertEqual(answer, "我暂时没找到合适的店。")
        self.assertNotIn("附近商家A", answer)


if __name__ == "__main__":
    unittest.main()
