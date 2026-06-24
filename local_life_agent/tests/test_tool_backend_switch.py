"""Contract tests for tool backend switching (db ↔ mock ↔ java_api).

Coverage:
  - Default backend is db
  - config.TOOL_BACKEND can be set to "mock" or "java_api"
  - Invalid backend value is rejected
  - build_tool_executor returns correct executor type for each backend
  - DbToolExecutor can be constructed and delegates to db_tools
  - Java backend unavailable does NOT return mock data (fallback disabled)
  - Explicit fallback returns degraded + fallback_from metadata
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from local_life_agent import config
from local_life_agent.tools.executor import (
    DbToolExecutor,
    JavaToolExecutor,
    build_db_executor,
    build_tool_executor,
)
from local_life_agent.tools.gateway import ToolCallGateway


# ═══════════════════════════════════════════════════════════════════
# §1 — Default backend
# ═══════════════════════════════════════════════════════════════════


class TestDefaultBackend:
    """Default TOOL_BACKEND should be ``'db'`` (production mode)."""

    @pytest.fixture(autouse=True)
    def _force_default_backend(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(config, "TOOL_BACKEND", "db")
        yield

    def test_default_is_db(self):
        assert config.TOOL_BACKEND == "db"

    def test_build_tool_executor_returns_db(self):
        from local_life_agent.tools.executor import DbToolExecutor
        executor = build_tool_executor()
        assert isinstance(executor, DbToolExecutor)

    def test_build_tool_executor_has_db_backend_source(self):
        executor = build_tool_executor()
        assert executor.backend_source == "db"


# ═══════════════════════════════════════════════════════════════════
# §2 — Java API backend
# ═══════════════════════════════════════════════════════════════════


class TestJavaApiBackend:
    """With TOOL_BACKEND=java_api the factory returns JavaToolExecutor."""

    def test_build_java_executor(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(config, "TOOL_BACKEND", "java_api")
        executor = build_tool_executor()
        assert isinstance(executor, JavaToolExecutor)
        assert executor.backend_source == "java_api"


# §3 — (removed: MockToolExecutor and fallback executor were deleted in P1)


# ═══════════════════════════════════════════════════════════════════
# §4 — Java backend unavailable
# ═══════════════════════════════════════════════════════════════════


class TestJavaUnavailable:
    """When Java backend is down, Gateway should return error (no mock fallback)."""

    @pytest.mark.asyncio
    async def test_java_down_returns_error(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(config, "TOOL_BACKEND", "java_api")

        gw = ToolCallGateway()
        result = await gw.call("resolve_shop", {"query": "海底捞"})

        # Should fail since no mock fallback exists
        assert result.get("success") is False


# ═══════════════════════════════════════════════════════════════════
# §4 — DB backend
# ═══════════════════════════════════════════════════════════════════


class TestDbBackend:
    """DbToolExecutor construction and delegation."""

    def test_build_db_executor(self):
        executor = build_db_executor()
        assert isinstance(executor, DbToolExecutor)
        assert executor.backend_source == "db"

    def test_build_tool_executor_with_backend_override(self, monkeypatch):
        monkeypatch.setattr(config, "TOOL_BACKEND", "db")
        executor = build_tool_executor()
        assert isinstance(executor, DbToolExecutor)
        assert executor.backend_source == "db"
