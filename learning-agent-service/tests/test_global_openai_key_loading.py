from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import _bootstrap  # noqa: F401
import httpx
from openai import AuthenticationError

from learning_agent_service.config.settings import Settings
import learning_agent_service.config.settings as settings_module
from learning_agent_service.infrastructure.db.openai_client import FailoverOpenAIClient, OpenRouterFilterTransport


class GlobalOpenAIKeyLoadingTestCase(unittest.TestCase):
    def test_service_env_file_overrides_process_env_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service_dir = Path(tmpdir) / "learning-agent-service"
            service_dir.mkdir()
            service_env = service_dir / ".env"
            service_env.write_text("OPENAI_API_KEY=local-api-key\n", encoding="utf-8")

            with patch.object(
                settings_module,
                "ENV_FILE_CANDIDATES",
                (str(service_env),),
            ), patch.dict(os.environ, {"OPENAI_API_KEY": "global-api-key"}, clear=True):
                settings = Settings()

        self.assertEqual(settings.openai.api_key, "local-api-key")

    def test_settings_falls_back_to_parent_env_file_for_openai_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            service_dir = root_dir / "learning-agent-service"
            service_dir.mkdir()

            global_env = root_dir / ".env"
            global_env.write_text("OPENAI_API_KEY=global-api-key\n", encoding="utf-8")

            with patch.object(
                settings_module,
                "ENV_FILE_CANDIDATES",
                (str(global_env), str(service_dir / ".env")),
            ), patch.dict(os.environ, {}, clear=True):
                settings = Settings()

        self.assertEqual(settings.openai.api_key, "global-api-key")

    def test_service_env_file_overrides_global_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            service_dir = root_dir / "learning-agent-service"
            service_dir.mkdir()

            global_env = root_dir / ".env"
            service_env = service_dir / ".env"
            global_env.write_text("OPENAI_API_KEY=global-api-key\n", encoding="utf-8")
            service_env.write_text("OPENAI_API_KEY=local-api-key\n", encoding="utf-8")

            with patch.object(
                settings_module,
                "ENV_FILE_CANDIDATES",
                (str(global_env), str(service_env)),
            ), patch.dict(os.environ, {}, clear=True):
                settings = Settings()

        self.assertEqual(settings.openai.api_key, "local-api-key")

    def test_failover_openai_client_switches_to_next_candidate_on_auth_error(self) -> None:
        response = httpx.Response(401, request=httpx.Request("POST", "https://example.com"))

        class _BadResponses:
            def create(self, *args, **kwargs):
                raise AuthenticationError("invalid key", response=response, body={"error": "invalid"})

            def stream(self, *args, **kwargs):
                return _BadStreamManager()

        class _GoodResponses:
            def create(self, *args, **kwargs):
                return {"answer_text": "ok"}

            def stream(self, *args, **kwargs):
                return _GoodStreamManager()

        class _BadStreamManager:
            def __enter__(self):
                raise AuthenticationError("invalid key", response=response, body={"error": "invalid"})

            def __exit__(self, exc_type, exc, tb):
                return False

        class _GoodStreamManager:
            def __enter__(self):
                return "stream-ok"

            def __exit__(self, exc_type, exc, tb):
                return False

        class _Client:
            def __init__(self, responses):
                self.responses = responses

        client = FailoverOpenAIClient([
            _Client(_BadResponses()),
            _Client(_GoodResponses()),
        ])

        result = client.responses.create(model="gpt-test", input="ping")

        self.assertEqual(result["answer_text"], "ok")
        with client.responses.stream(model="gpt-test", input="ping") as stream:
            self.assertEqual(stream, "stream-ok")

    def test_openrouter_filter_transport_removes_keep_alive_sse_events(self) -> None:
        class _FakeStream(httpx.SyncByteStream):
            def __iter__(self):
                yield b"event: response.created\ndata: {}\n\n"
                yield b"event: response.keep_alive\ndata: {}\n\n"
                yield b"event: response.output_text.delta\ndata: hello\n\n"

            def close(self):
                return None

        request = httpx.Request("POST", "https://example.com")
        response = httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            stream=_FakeStream(),
            request=request,
        )

        with patch.object(httpx.HTTPTransport, "handle_request", return_value=response):
            filtered_response = OpenRouterFilterTransport().handle_request(request)

        body = b"".join(filtered_response.stream)
        self.assertIn(b"response.created", body)
        self.assertIn(b"response.output_text.delta", body)
        self.assertNotIn(b"response.keep_alive", body)


if __name__ == "__main__":
    unittest.main()
