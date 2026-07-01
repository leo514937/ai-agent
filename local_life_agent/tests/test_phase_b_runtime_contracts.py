from __future__ import annotations

import asyncio

from local_life_agent.tools.executor import RawToolResult, ToolExecutor
from local_life_agent.tools.gateway import ToolCallGateway
from local_life_agent.tools.normalizer import normalize_tool_result, normalize_validation_error


class _PresetExecutor(ToolExecutor):
    def __init__(self, raw: RawToolResult):
        self._raw = raw

    async def execute(self, tool_def: dict, args: dict):
        return self._raw


def test_normalize_tool_result_emits_retriable_for_retryable_failures():
    result = normalize_tool_result(
        "resolve_shop",
        {
            "success": False,
            "result_status": "unknown",
            "data": None,
            "error_code": "NETWORK_ERROR",
        },
    )

    assert "retriable" in result
    assert result["retriable"] is True


def test_normalize_validation_error_is_non_retriable():
    result = normalize_validation_error("get_shop_detail", {}, ["missing shop_id"])

    assert result["result_status"] == "failed"
    assert result["retriable"] is False


def test_success_result_is_not_retriable():
    result = normalize_tool_result(
        "get_shop_detail",
        {
            "success": True,
            "result_status": "ok",
            "data": {"shop_id": "1"},
            "backend_source": "db",
        },
    )

    assert result["retriable"] is False


def test_gateway_output_contains_runtime_contract_fields():
    gateway = ToolCallGateway(
        executor=_PresetExecutor(
            RawToolResult(
                data={"shop_id": "1", "shop_name": "测试店"},
                success=True,
                backend_source="tests_fake",
            )
        )
    )

    result = asyncio.run(gateway.call("get_shop_detail", {"shop_id": "1"}))

    assert {
        "call_id",
        "shop_id",
        "tool_name",
        "success",
        "result_status",
        "data",
        "error_code",
        "error_message",
        "source",
        "backend_source",
        "fallback_from",
        "http_status",
        "endpoint",
        "retriable",
    }.issubset(result.keys())
    assert result["backend_source"] == "tests_fake"
    assert result["retriable"] is False
