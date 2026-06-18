from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

TESTS_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = TESTS_DIR.parent
SRC_ROOT = PROJECT_ROOT / "src"
for candidate in (str(TESTS_DIR), str(PROJECT_ROOT), str(SRC_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from learning_agent_service.local_life.facet_result_bundle import FacetResultBundle
from learning_agent_service.local_life.response_builder import build_open_status_only_answer
from learning_agent_service.local_life.tool_result_normalizer import normalize_tool_result


class ToolHarnessOpenStatusTestCase(unittest.TestCase):
    def test_open_status_success_answer_uses_tool(self) -> None:
        bundle = FacetResultBundle(
            tool_results=[
                normalize_tool_result(
                    tool_name="check_open_status",
                    raw_output={"shop_id": 5, "shop_name": "海底捞水晶城店", "open_status": "open", "open_now": True},
                    shop_id=5,
                    shop_name="海底捞水晶城店",
                )
            ]
        )
        candidate = SimpleNamespace(shop_id=5, structured_features={})
        answer = build_open_status_only_answer("海底捞水晶城店", [candidate], [], facet_result_bundle=bundle)
        self.assertIn("营业中", answer)

    def test_open_status_unknown_does_not_guess_from_hours(self) -> None:
        bundle = FacetResultBundle(
            tool_results=[
                normalize_tool_result(
                    tool_name="check_open_status",
                    raw_output={"shop_id": 5, "shop_name": "海底捞水晶城店", "open_status": "unknown", "open_now": None},
                    shop_id=5,
                    shop_name="海底捞水晶城店",
                    status="degraded",
                    error_message="unknown",
                )
            ]
        )
        candidate = SimpleNamespace(shop_id=5, structured_features={"open_hours": "09:00-22:00"})
        answer = build_open_status_only_answer("海底捞水晶城店", [candidate], [], facet_result_bundle=bundle)
        self.assertIn("实时状态", answer)
        self.assertNotIn("营业中", answer)

    def test_open_status_tool_answer_accepts_dict_bundle(self) -> None:
        bundle = {
            "tool_results": [
                normalize_tool_result(
                    tool_name="check_open_status",
                    raw_output={"shop_id": 5, "shop_name": "海底捞水晶城店", "open_status": "open", "open_now": True},
                    shop_id=5,
                    shop_name="海底捞水晶城店",
                ).model_dump(mode="json")
            ]
        }
        candidate = SimpleNamespace(shop_id=5, structured_features={})
        answer = build_open_status_only_answer("海底捞水晶城店", [candidate], [], facet_result_bundle=bundle)
        self.assertIn("营业中", answer)


if __name__ == "__main__":
    unittest.main()
