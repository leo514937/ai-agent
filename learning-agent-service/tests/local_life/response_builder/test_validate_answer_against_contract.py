from __future__ import annotations

import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = TESTS_DIR.parent
SRC_ROOT = PROJECT_ROOT / "src"
for candidate in (str(TESTS_DIR), str(PROJECT_ROOT), str(SRC_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import _bootstrap  # noqa: F401

from learning_agent_service.local_life.answer_contract import AnswerContract
from learning_agent_service.local_life.response_builder import validate_answer_against_contract


class ValidateAnswerAgainstContractTestCase(unittest.TestCase):
    def test_keeps_repaired_text_when_lint_is_warning_only(self) -> None:
        contract = AnswerContract(
            original_query="海底捞望京店怎么样？",
            allowed_facets=["environment", "taste", "service", "recommendation_reason", "scene_fit"],
            forbidden_facets=["environment"],
            allowed_tools=[],
            allowed_rag_facets=["environment", "taste", "service", "recommendation_reason", "scene_fit"],
            forbidden_rag_facets=[],
            realtime_facets=[],
            allow_recommendation=False,
            allow_extra_context=True,
            realtime_required=False,
            evidence_policy="balanced",
            answer_style="single_shop_review",
        )

        result = validate_answer_against_contract(
            "整体不错。\n环境也挺安静。\n到店建议：饭点提前去。",
            contract,
            "海底捞望京店",
            ranked_candidates=[],
            evidence_claims=[],
        )

        self.assertEqual(result, "整体不错。\n到店建议：饭点提前去。")
        self.assertNotIn("总体结论", result)
        self.assertNotIn("推荐理由", result)


if __name__ == "__main__":
    unittest.main()
