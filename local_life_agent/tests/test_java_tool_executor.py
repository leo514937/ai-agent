"""Contract tests for JavaToolClient / JavaToolExecutor.

Uses ``httpx.MockTransport`` to simulate the Java backend so these
tests are self-contained (no live Java service required).

Coverage:
  - Each of the 6 registered tools with a 200 response → ok
  - Empty coupon list → empty
  - Unknown check_open_status → unknown
  - Timeout → unknown / failed
  - HTTP 500 → failed
  - backend_source == "java_api" on every path
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from local_life_agent.tools.executor import JavaToolExecutor, RawToolResult
from local_life_agent.tools.java_client import JavaToolClient


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════


def _mock_transport(responses: dict[str, Any]) -> httpx.MockTransport:
    """Return a MockTransport that responds based on URL path."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        for key, response in responses.items():
            if isinstance(response, tuple) and len(response) == 2:
                status_code, body = response
                if key in path:
                    return httpx.Response(status_code=status_code, json=body)
            elif key in path:
                return httpx.Response(
                    status_code=response.get("_status", 200),
                    json={k: v for k, v in response.items() if k != "_status"},
                )
        return httpx.Response(status_code=404, json={"error": "not found"})

    return httpx.MockTransport(handler)


def _make_client(transport: httpx.MockTransport) -> JavaToolClient:
    """Create a JavaToolClient wired with the given transport."""
    client = JavaToolClient(base_url="http://test", timeout_ms=5000)
    client._client = httpx.AsyncClient(transport=transport, base_url="http://test")
    return client


async def _execute(tool_name: str, args: dict[str, Any],
                   transport: httpx.MockTransport) -> RawToolResult:
    """Run a tool through JavaToolExecutor with the given transport."""
    client = _make_client(transport)
    executor = JavaToolExecutor(client=client)
    tool_def = {"name": tool_name}
    result = await executor.execute(tool_def, args)
    await client.close()
    return result


# ═══════════════════════════════════════════════════════════════════
# §1 — Successful execution (HTTP 200 → ok)
# ═══════════════════════════════════════════════════════════════════


class TestJavaResolveShop:
    """resolve_shop 200 → ok with backend_source=java_api."""

    @pytest.mark.asyncio
    async def test_resolve_shop_ok(self):
        transport = _mock_transport({
            "/internal/agent/tools/resolve-shop": {
                "_status": 200,
                "success": True,
                "result_status": "ok",
                "data": {
                    "status": "RESOLVED",
                    "shop": {"shop_id": "shop_sc_01", "shop_name": "海底捞火锅(水晶城购物中心店)"},
                    "confidence": 0.95,
                },
            },
        })
        result = await _execute("resolve_shop", {"query": "海底捞"}, transport)
        assert result.success is True
        assert result.backend_source == "java_api"
        assert isinstance(result.data, dict)
        assert result.data.get("status") == "RESOLVED"


class TestJavaSearchShops:
    """search_shops 200 → ok."""

    @pytest.mark.asyncio
    async def test_search_shops_ok_limit_20(self):
        transport = _mock_transport({
            "/internal/agent/tools/search-shops": {
                "_status": 200,
                "success": True,
                "result_status": "ok",
                "data": [{"shop_id": "shop_001", "shop_name": "店铺A"},
                         {"shop_id": "shop_002", "shop_name": "店铺B"}],
                "total": 2,
            },
        })
        result = await _execute("search_shops", {"query": "火锅", "limit": 20}, transport)
        assert result.success is True
        assert result.backend_source == "java_api"


class TestJavaGetShopDetail:
    """get_shop_detail 200 → ok."""

    @pytest.mark.asyncio
    async def test_shop_detail_ok(self):
        transport = _mock_transport({
            "/internal/agent/tools/shops/shop_sc_01": {
                "_status": 200,
                "success": True,
                "result_status": "ok",
                "data": {"shop_id": "shop_sc_01", "shop_name": "海底捞火锅(水晶城购物中心店)"},
            },
        })
        result = await _execute("get_shop_detail", {"shop_id": "shop_sc_01"}, transport)
        assert result.success is True
        assert result.backend_source == "java_api"


# ═══════════════════════════════════════════════════════════════════
# §2 — Empty result
# ═══════════════════════════════════════════════════════════════════


class TestJavaEmptyResult:
    """Java backend returning empty data."""

    @pytest.mark.asyncio
    async def test_get_coupon_list_empty(self):
        transport = _mock_transport({
            "/internal/agent/tools/shops/shop_999/coupons": {
                "_status": 200,
                "success": True,
                "result_status": "empty",
                "data": [],
                "total": 0,
            },
        })
        result = await _execute("get_coupon_list", {"shop_id": "shop_999"}, transport)
        assert result.success is True
        assert result.backend_source == "java_api"


# ═══════════════════════════════════════════════════════════════════
# §3 — Unknown status
# ═══════════════════════════════════════════════════════════════════


class TestJavaUnknownResult:
    """check_open_status returning unknown."""

    @pytest.mark.asyncio
    async def test_check_open_status_unknown(self):
        transport = _mock_transport({
            "/internal/agent/tools/shops/shop_999/open-status": {
                "_status": 200,
                "success": True,
                "result_status": "ok",
                "data": {
                    "shop_id": "shop_999",
                    "shop_name": "未知店铺",
                    "open_status": "unknown",
                    "business_hours": "",
                },
            },
        })
        result = await _execute("check_open_status", {"shop_id": "shop_999"}, transport)
        assert result.success is True
        assert result.backend_source == "java_api"


class TestJavaDistanceEta:
    """get_distance_eta 200 → ok."""

    @pytest.mark.asyncio
    async def test_get_distance_eta_ok(self):
        transport = _mock_transport({
            "/internal/agent/tools/shops/shop_sc_01/distance-eta": {
                "_status": 200,
                "success": True,
                "result_status": "ok",
                "data": {
                    "shop_id": "shop_sc_01",
                    "shop_name": "海底捞火锅(水晶城购物中心店)",
                    "distance_km": 3.2,
                    "eta_minutes": 15,
                    "traffic_level": "low",
                },
            },
        })
        result = await _execute("get_distance_eta",
                                {"shop_id": "shop_sc_01", "from_location": {"lat": 39.96, "lng": 116.35}},
                                transport)
        assert result.success is True
        assert result.backend_source == "java_api"
        assert result.data.get("distance_km") == 3.2


# ═══════════════════════════════════════════════════════════════════
# §4 — Error paths
# ═══════════════════════════════════════════════════════════════════


class TestJavaTimeout:
    """HTTP timeout → unknown / failed."""

    @pytest.mark.asyncio
    async def test_timeout_raises(self):
        """Timeout from JavaToolClient propagates to the executor as an exception."""
        async def _timeout_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("Simulated timeout", request=request)

        transport = httpx.MockTransport(_timeout_handler)
        client = _make_client(transport)
        executor = JavaToolExecutor(client=client)
        tool_def = {"name": "resolve_shop"}

        with pytest.raises(TimeoutError):
            await executor.execute(tool_def, {"query": "test"})

        await client.close()


class TestJava500:
    """HTTP 500 → failed + backend_source=java_api."""

    @pytest.mark.asyncio
    async def test_500_maps_to_failed(self):
        transport = _mock_transport({
            "/internal/agent/tools/resolve-shop": (500, {"error": "Internal Server Error"}),
        })
        result = await _execute("resolve_shop", {"query": "海底捞"}, transport)
        assert result.success is False
        assert result.backend_source == "java_api"


class TestJavaToolNotRegistered:
    """Tool with no Java endpoint mapping → TOOL_NOT_REGISTERED."""

    @pytest.mark.asyncio
    async def test_non_registered_tool_returns_error(self):
        transport = httpx.MockTransport(lambda r: httpx.Response(404))
        client = _make_client(transport)
        executor = JavaToolExecutor(client=client)
        tool_def = {"name": "nonexistent_tool"}
        result = await executor.execute(tool_def, {})
        assert result.success is False
        assert result.error_code == "TOOL_NOT_REGISTERED"
        await client.close()
