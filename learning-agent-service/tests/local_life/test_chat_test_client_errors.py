from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

TESTS_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = TESTS_DIR.parent
SRC_ROOT = PROJECT_ROOT / "src"
for candidate in (str(TESTS_DIR), str(PROJECT_ROOT), str(SRC_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from chat_test_client import ChatStreamTestClient


class ChatStreamTestClientErrorHandlingTestCase(unittest.TestCase):
    def test_connection_error_is_wrapped_with_actionable_message(self) -> None:
        client = ChatStreamTestClient(base_url="http://127.0.0.1:8000/internal/v1/chat/stream")
        request = httpx.Request("POST", client.base_url)
        connect_error = httpx.ConnectError("connection refused", request=request)

        with patch.object(client.client, "stream", side_effect=connect_error):
            with self.assertRaises(RuntimeError) as context:
                client.post_message("你好", "session-1")

        message = str(context.exception)
        self.assertIn("无法连接到 chat 流接口", message)
        self.assertIn("start_python.ps1", message)


if __name__ == "__main__":
    unittest.main()
