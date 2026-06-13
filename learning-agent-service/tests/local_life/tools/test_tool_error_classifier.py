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

from learning_agent_service.tools.tool_error_classifier import classify_tool_error


class ToolErrorClassifierTestCase(unittest.TestCase):
    def test_classifies_timeout_empty_permission_invalid_and_service_unavailable(self) -> None:
        timeout = classify_tool_error(
            tool_name="get_coupon_list",
            status="timeout",
            payload={},
            errors={"message": "tool timed out"},
        )
        empty_result = classify_tool_error(
            tool_name="get_coupon_list",
            status="success",
            payload={"count": 0, "coupons": []},
            errors={},
        )
        permission_error = classify_tool_error(
            tool_name="create_booking",
            status="rejected",
            payload={},
            errors={"message": "approval denied"},
            approval_required=True,
            approval_status="rejected",
        )
        invalid_params = classify_tool_error(
            tool_name="get_shop_detail",
            status="degraded",
            payload={},
            errors={"message": "invalid parameter: shop_id"},
        )
        service_unavailable = classify_tool_error(
            tool_name="check_open_status",
            status="degraded",
            payload={},
            errors={"message": "java business service unavailable"},
        )

        self.assertEqual(timeout.category, "timeout")
        self.assertTrue(timeout.retryable)
        self.assertEqual(empty_result.category, "empty_result")
        self.assertFalse(empty_result.retryable)
        self.assertEqual(permission_error.category, "permission_error")
        self.assertFalse(permission_error.retryable)
        self.assertEqual(invalid_params.category, "invalid_params")
        self.assertFalse(invalid_params.retryable)
        self.assertEqual(service_unavailable.category, "service_unavailable")
        self.assertTrue(service_unavailable.retryable)


if __name__ == "__main__":
    unittest.main()
