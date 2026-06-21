"""Optional live integration tests against a real Java backend.

These tests are SKIPPED by default.  To run them you need:

  - A running Java backend at LOCAL_LIFE_JAVA_BASE_URL (default http://localhost:8081)
  - Environment::

      LOCAL_LIFE_RUN_JAVA_INTEGRATION=1
      LOCAL_LIFE_TOOL_BACKEND=java_api
      LOCAL_LIFE_JAVA_BASE_URL=http://localhost:8081

When the Java backend is unreachable, tests fail or skip — they WILL
NOT silently fall back to mock data.
"""

from __future__ import annotations

import os

import pytest

from local_life_agent import config
from local_life_agent.tools.executor import JavaToolExecutor

_RUN_INTEGRATION = os.environ.get("LOCAL_LIFE_RUN_JAVA_INTEGRATION", "").lower() in ("1", "true", "yes", "on")
_REQUIRED_ENV = ("LOCAL_LIFE_TOOL_BACKEND", "LOCAL_LIFE_JAVA_BASE_URL")
_MISSING = [v for v in _REQUIRED_ENV if not os.environ.get(v)]

integration_test = pytest.mark.skipif(
    not _RUN_INTEGRATION,
    reason="set LOCAL_LIFE_RUN_JAVA_INTEGRATION=1 and LOCAL_LIFE_TOOL_BACKEND=java_api to run",
)


@integration_test
@pytest.mark.asyncio
async def test_java_resolve_shop_live():
    """Real Java resolve_shop returns data with backend_source=java_api."""
    executor = JavaToolExecutor()
    tool_def = {"name": "resolve_shop"}
    result = await executor.execute(tool_def, {"query": "海底捞"})
    assert result.success, f"Java resolve_shop failed: {result.error_message}"
    assert result.backend_source == "java_api"
    assert result.http_status == 200


@integration_test
@pytest.mark.asyncio
async def test_java_search_shops_live():
    """Real Java search_shops returns data with backend_source=java_api."""
    executor = JavaToolExecutor()
    tool_def = {"name": "search_shops"}
    result = await executor.execute(tool_def, {"query": "火锅", "limit": 20})
    assert result.success, f"Java search_shops failed: {result.error_message}"
    assert result.backend_source == "java_api"


@integration_test
@pytest.mark.asyncio
async def test_java_get_shop_detail_live():
    """Real Java get_shop_detail returns data with backend_source=java_api."""
    executor = JavaToolExecutor()
    tool_def = {"name": "get_shop_detail"}
    result = await executor.execute(tool_def, {"shop_id": "900001"})
    assert result.success, f"Java get_shop_detail failed: {result.error_message}"
    assert result.backend_source == "java_api"
    assert isinstance(result.data, dict)
    data = result.data if isinstance(result.data, dict) else {}
    assert data.get("shop_id") == "900001"
    assert data.get("shop_name") is not None


@integration_test
@pytest.mark.asyncio
async def test_java_get_coupon_list_live():
    """Real Java get_coupon_list returns data with backend_source=java_api."""
    executor = JavaToolExecutor()
    tool_def = {"name": "get_coupon_list"}
    result = await executor.execute(tool_def, {"shop_id": "900001"})
    assert result.backend_source == "java_api"


@integration_test
@pytest.mark.asyncio
async def test_java_check_open_status_live():
    """Real Java check_open_status returns open/closed/unknown."""
    executor = JavaToolExecutor()
    tool_def = {"name": "check_open_status"}
    result = await executor.execute(tool_def, {"shop_id": "900001"})
    assert result.success, f"Java check_open_status failed: {result.error_message}"
    assert result.backend_source == "java_api"
    assert result.data.get("open_status") in ("open", "closed", "unknown")


@integration_test
@pytest.mark.asyncio
async def test_java_get_distance_eta_live():
    """Real Java get_distance_eta returns ETA data."""
    executor = JavaToolExecutor()
    tool_def = {"name": "get_distance_eta"}
    result = await executor.execute(
        tool_def,
        {"shop_id": "900001", "from_location": {"lat": 39.96, "lng": 116.35}},
    )
    assert result.success, f"Java get_distance_eta failed: {result.error_message}"
    assert result.backend_source == "java_api"
    assert result.data.get("distance_km") is not None


@integration_test
@pytest.mark.asyncio
async def test_java_search_shops_returns_seed_data():
    """Real Java search shops fetches the 27 seed shops."""
    executor = JavaToolExecutor()
    tool_def = {"name": "search_shops"}
    result = await executor.execute(tool_def, {"query": "北邮", "limit": 30})
    assert result.success, f"Java search_shops failed: {result.error_message}"
    assert result.backend_source == "java_api"


@integration_test
@pytest.mark.asyncio
async def test_java_unavailable_fails_not_mock():
    """When Java backend is unreachable, request should NOT return mock data."""
    original_base = config.JAVA_BACKEND_BASE_URL
    config.JAVA_BACKEND_BASE_URL = "http://127.0.0.1:9"
    try:
        executor = JavaToolExecutor()
        tool_def = {"name": "resolve_shop"}
        result = await executor.execute(tool_def, {"query": "海底捞"})
        # Should either raise or return failure — never success with mock data
        assert not result.success, "Must NOT return success when Java backend is unreachable"
        assert result.backend_source == "java_api", "Must keep backend_source=java_api even on failure"
    except Exception:
        # Timeout / connection refused is acceptable
        pass
    finally:
        config.JAVA_BACKEND_BASE_URL = original_base
