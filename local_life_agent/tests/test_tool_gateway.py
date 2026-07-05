"""Contract tests for todo/08 — ToolCallGateway pipeline.

Verifies the 6-step Gateway pipeline under every expected execution
path so the Planner and graph nodes can trust the result shape.

Coverage:
  - Successful execution -> ``result_status == "ok"``
  - Empty result         -> ``result_status == "empty"``
  - Timeout -> retry exhausted -> ``result_status == "unknown"``
  - Circuit breaker open  -> ``result_status == "circuit_open"``
  - Schema validation fail -> ``result_status == "failed"``, error_code == "SCHEMA_VALIDATION_FAILED"
  - Unregistered tool      -> ``result_status == "failed"``, error_code == "SCHEMA_VALIDATION_FAILED"
  - Every response is a dict with standardised keys
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from .fakes import mock_tools
from ..tools.circuit_breaker import get_circuit_breaker_manager
from ..tools.executor import RawToolResult, ToolExecutor
from ..tools.gateway import ToolCallGateway, dispatch_tool_call


# ═══════════════════════════════════════════════════════════════════
# Helpers: sync wrappers so we don't need pytest-asyncio
# ═══════════════════════════════════════════════════════════════════


def _gw(executor: ToolExecutor | None = None, reset_cb: bool = True) -> ToolCallGateway:
    """Fresh Gateway with optional circuit-breaker reset."""
    if reset_cb:
        get_circuit_breaker_manager().reset_all()
    return ToolCallGateway(executor=executor)


def _mock_gw() -> ToolCallGateway:
    """Fresh Gateway wired with a tests-only fake executor."""
    return _gw(executor=_FakeExecutor())


def _call(gw: ToolCallGateway, tool: str, kwargs: dict) -> dict[str, Any]:
    """Synchronous convenience: run *gw.call()* via ``asyncio.run``."""
    return asyncio.run(gw.call(tool, kwargs))


# ═══════════════════════════════════════════════════════════════════
# Deterministic executor (predictable results for error-path tests)
# ═══════════════════════════════════════════════════════════════════


class _DetExecutor(ToolExecutor):
    """Pre-configured results per tool name."""

    def __init__(self, preset: dict[str, Any] | None = None):
        self.preset = preset or {}

    async def execute(self, tool_def: dict, args: dict[str, Any]) -> RawToolResult:
        p = self.preset.get(tool_def["name"])
        if p is None:
            return RawToolResult(data=None, success=False, error_code="TOOL_NOT_REGISTERED")
        if p.get("raise_timeout"):
            raise TimeoutError("Simulated timeout")
        return RawToolResult(
            data=p.get("data"),
            success=p.get("success", True),
            error_code=p.get("error_code"),
            error_message=p.get("error_message", ""),
        )


class _FakeExecutor(ToolExecutor):
    @property
    def backend_source(self) -> str:
        return "tests_fake"

    async def execute(self, tool_def: dict, args: dict[str, Any]) -> RawToolResult:
        tool_name = tool_def["name"]
        if tool_name == "resolve_shop":
            data = mock_tools.resolve_shop(str(args.get("query", "")), location=args.get("location"), session_shop_ids=args.get("session_shop_ids"))
            return RawToolResult(data=data, success=True, backend_source=self.backend_source)
        if tool_name == "search_shops":
            data = mock_tools.search_shops(str(args.get("query", "")), location=args.get("location"), limit=args.get("limit"))
            return RawToolResult(data=data.get("data"), success=True, backend_source=self.backend_source)
        if tool_name == "get_shop_detail":
            data = mock_tools.get_shop_detail(str(args.get("shop_id", "")))
            return RawToolResult(data=data.get("data"), success=data.get("success", False), error_code=data.get("error_code"), error_message=data.get("error_message", ""), backend_source=self.backend_source)
        if tool_name == "get_coupon_list":
            try:
                data = mock_tools.get_coupon_list(str(args.get("shop_id", "")))
            except TimeoutError:
                raise
            return RawToolResult(data=data.get("data"), success=data.get("success", False), error_code=data.get("error_code"), error_message=data.get("error_message", ""), backend_source=self.backend_source)
        if tool_name == "check_open_status":
            data = mock_tools.check_open_status(str(args.get("shop_id", "")))
            return RawToolResult(data=data.get("data"), success=data.get("success", False), error_code=data.get("error_code"), error_message=data.get("error_message", ""), backend_source=self.backend_source)
        if tool_name == "get_distance_eta":
            data = mock_tools.get_distance_eta(str(args.get("shop_id", "")), args.get("from_location") or {"lat": 39.9609, "lng": 116.3581})
            return RawToolResult(data=data.get("data"), success=data.get("success", False), error_code=data.get("error_code"), error_message=data.get("error_message", ""), backend_source=self.backend_source)
        if tool_name == "calculate_distance_km":
            data = mock_tools.calculate_distance_km(args.get("origin"), args.get("destination"), args.get("mode", "straight_line"))
            return RawToolResult(data=data.get("data"), success=data.get("success", False), error_code=data.get("error_code"), error_message=data.get("error_message", ""), backend_source=self.backend_source)
        return RawToolResult(data=None, success=False, error_code="TOOL_NOT_REGISTERED", backend_source=self.backend_source)


# ═══════════════════════════════════════════════════════════════════
# §1 — Successful execution
# ═══════════════════════════════════════════════════════════════════


class TestSuccessfulExecution:
    """Happy path: every tool returns data with ``result_status == "ok"``."""

    def test_get_shop_detail(self):
        r = _call(_mock_gw(), "get_shop_detail", {"shop_id": "shop_sc_01"})
        assert r["success"] is True
        assert r["result_status"] == "ok"
        assert r["data"]["shop_id"] == "shop_sc_01"
        assert r["error_code"] is None

    def test_search_shops(self):
        r = _call(_mock_gw(), "search_shops", {"query": "海底捞"})
        assert r["success"] is True
        assert r["result_status"] == "ok"
        assert len(r["data"]) > 0

    def test_check_open_status(self):
        r = _call(_mock_gw(), "check_open_status", {"shop_id": "shop_sc_07"})
        assert r["success"] is True
        assert r["result_status"] == "ok"
        assert r["data"]["open_status"] == "open"

    def test_get_distance_eta(self):
        r = _call(_mock_gw(), "get_distance_eta", {
            "shop_id": "shop_sc_10",
            "from_location": {"lat": 39.9609, "lng": 116.3581},
        })
        assert r["success"] is True
        assert r["result_status"] == "ok"
        assert r["data"]["distance_km"] is not None

    def test_calculate_distance_km(self):
        r = _call(_mock_gw(), "calculate_distance_km", {
            "origin": {"lat": 39.9609, "lng": 116.3581},
            "destination": {"lat": 39.953, "lng": 116.350},
            "mode": "straight_line",
        })
        assert r["success"] is True
        assert r["result_status"] == "ok"
        assert r["data"]["method"] == "haversine"
        assert r["data"]["eta_minutes"] is None
        assert r["data"]["distance_km"] is not None

    def test_resolve_shop_exact(self):
        r = _call(_mock_gw(), "resolve_shop", {"query": "海底捞火锅(水晶城购物中心店)"})
        assert r["success"] is True
        assert r["result_status"] == "ok"
        # resolve_shop returns its full result under ``data`` (non-standard
        # envelope wrapped by MockToolExecutor).
        assert r["data"]["status"] == "RESOLVED"
        assert r["data"]["shop"]["shop_id"] == "shop_sc_01"


# ═══════════════════════════════════════════════════════════════════
# §2 — Empty result
# ═══════════════════════════════════════════════════════════════════


class TestEmptyResult:
    """Tools that succeed but produce no output."""

    def test_coupon_list_empty(self):
        r = _call(_mock_gw(), "get_coupon_list", {"shop_id": "shop_sc_04"})
        assert r["result_status"] == "empty"
        assert r["success"] is True
        assert r["data"] == []

    def test_search_no_match(self):
        r = _call(_mock_gw(), "search_shops", {"query": "__nonsense__"})
        assert r["result_status"] == "empty"
        assert r["success"] is True
        assert r["data"] == []


# ═══════════════════════════════════════════════════════════════════
# §3 — Timeout -> retry -> unknown
# ═══════════════════════════════════════════════════════════════════


class TestTimeoutAndRetry:
    """Consistent timeout exhausts retry and returns ``unknown``."""

    def test_deterministic_timeout(self):
        gw = _gw(executor=_DetExecutor({"resolve_shop": {"raise_timeout": True}}))
        r = _call(gw, "resolve_shop", {"query": "test"})
        assert r["success"] is False
        assert r["result_status"] == "unknown"

    def test_mock_shop_sc06_timeout(self):
        r = _call(_mock_gw(), "get_coupon_list", {"shop_id": "shop_sc_06"})
        assert r["success"] is False
        assert r["result_status"] == "unknown"


# ═══════════════════════════════════════════════════════════════════
# §4 — Circuit breaker open
# ═══════════════════════════════════════════════════════════════════


class TestCircuitBreaker:
    """After threshold failures the gateway short-circuits."""

    def test_circuit_open_returns_early(self):
        cm = get_circuit_breaker_manager()
        cm.reset_all()

        # Trip the breaker BEFORE creating the gateway so _gw does not reset.
        for _ in range(5):
            cm.record_failure("search_shops", threshold=5, recovery_timeout_ms=30000)
        assert cm.is_open("search_shops", threshold=5, recovery_timeout_ms=30000)

        r = _call(_gw(reset_cb=False), "search_shops", {"query": "海底捞"})
        assert r["success"] is False
        assert r["result_status"] == "circuit_open"
        assert r["error_code"] == "CIRCUIT_OPEN"


# ═══════════════════════════════════════════════════════════════════
# §5 — Schema validation failure
# ═══════════════════════════════════════════════════════════════════


class TestValidationFailure:
    """Missing required arguments produce SCHEMA_VALIDATION_FAILED."""

    def test_missing_shop_id(self):
        r = _call(_mock_gw(), "get_shop_detail", {})
        assert r["success"] is False
        assert r["result_status"] == "failed"
        assert r["error_code"] == "SCHEMA_VALIDATION_FAILED"
        assert "Missing required argument 'shop_id'" in r["error_message"]

    def test_missing_query(self):
        r = _call(_mock_gw(), "search_shops", {})
        assert r["success"] is False
        assert r["result_status"] == "failed"
        assert r["error_code"] == "SCHEMA_VALIDATION_FAILED"

    def test_missing_from_location(self):
        r = _call(_mock_gw(), "get_distance_eta", {"shop_id": "shop_sc_01"})
        assert r["success"] is False
        assert r["result_status"] == "failed"
        assert r["error_code"] == "SCHEMA_VALIDATION_FAILED"

    def test_missing_origin_coordinates(self):
        r = _call(_mock_gw(), "calculate_distance_km", {
            "destination": {"lat": 39.953, "lng": 116.350},
            "mode": "straight_line",
        })
        assert r["success"] is False
        assert r["result_status"] == "unknown"
        assert r["data"]["blocked_reason"] == "missing_origin_coordinates"


# ═══════════════════════════════════════════════════════════════════
# §6 — Unregistered tool
# ═══════════════════════════════════════════════════════════════════


class TestUnregisteredTool:
    """Tools not in the registry => validation error."""

    def test_unknown_tool_name(self):
        r = _call(_mock_gw(), "non_existent_tool", {})
        assert r["success"] is False
        assert r["result_status"] == "failed"
        assert r["error_code"] == "SCHEMA_VALIDATION_FAILED"
        assert "non_existent_tool" in r["error_message"]


# ═══════════════════════════════════════════════════════════════════
# §7 — Output shape contract
# ═══════════════════════════════════════════════════════════════════


class TestOutputShape:
    """Every response must contain the standardised ToolResult keys."""

    _KEYS = {"call_id", "shop_id", "tool_name", "success",
             "result_status", "data", "error_code", "error_message",
             "source", "degraded"}

    def test_success(self):
        r = _call(_mock_gw(), "get_shop_detail", {"shop_id": "shop_sc_01"})
        assert self._KEYS.issubset(r.keys())

    def test_validation_error(self):
        r = _call(_mock_gw(), "get_shop_detail", {})
        assert self._KEYS.issubset(r.keys())

    def test_circuit_open(self):
        cm = get_circuit_breaker_manager()
        cm.reset_all()
        for _ in range(5):
            cm.record_failure("search_shops", threshold=5, recovery_timeout_ms=30000)
        r = _call(_gw(), "search_shops", {"query": "test"})
        assert self._KEYS.issubset(r.keys())

    def test_unregistered_tool(self):
        r = _call(_mock_gw(), "no_such_tool", {})
        assert self._KEYS.issubset(r.keys())


# ═══════════════════════════════════════════════════════════════════
# §8 — dispatch_tool_call sync wrapper
# ═══════════════════════════════════════════════════════════════════


class TestDispatchToolCall:
    """The module-level sync convenience wrapper."""

    def test_success(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("local_life_agent.tools.gateway._gateway_instance", ToolCallGateway(executor=_FakeExecutor()))
        r = dispatch_tool_call("get_shop_detail", {"shop_id": "shop_sc_01"})
        assert r["success"] is True
        assert r["result_status"] == "ok"
        assert r["data"]["shop_name"] == "海底捞火锅(水晶城购物中心店)"

    def test_validation_error(self):
        r = dispatch_tool_call("get_shop_detail", {})
        assert r["success"] is False
        assert r["result_status"] == "failed"
        assert r["error_code"] == "SCHEMA_VALIDATION_FAILED"

    def test_empty(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("local_life_agent.tools.gateway._gateway_instance", ToolCallGateway(executor=_FakeExecutor()))
        r = dispatch_tool_call("get_coupon_list", {"shop_id": "shop_sc_04"})
        assert r["result_status"] == "empty"
        assert r["data"] == []

    def test_unknown_tool(self):
        r = dispatch_tool_call("non_existent_tool", {})
        assert r["success"] is False
        assert r["result_status"] == "failed"
