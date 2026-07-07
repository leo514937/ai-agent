from __future__ import annotations

import inspect

import pytest

from local_life_agent.tools import db_client, db_tools
from local_life_agent.tools.definitions import TOOL_DEFINITIONS
from local_life_agent.tools.gateway import ToolCallGateway
from local_life_agent.tools.registry import ToolRegistry
from local_life_agent.tools.schemas import TOOL_SCHEMA_BY_NAME
from local_life_agent.tools.validators import validate_tool_args
from local_life_agent.target import candidate_resolver as candidate_resolver_module


def test_tool_registry_layers_are_split_across_canonical_modules():
    registry = ToolRegistry()

    assert TOOL_DEFINITIONS
    assert registry.list_tools() == [item["name"] for item in TOOL_DEFINITIONS]
    assert registry.get("resolve_shop")["input_schema"] == TOOL_SCHEMA_BY_NAME["resolve_shop"]["input_schema"]
    assert registry.get("get_shop_cards")["output_schema"] == TOOL_SCHEMA_BY_NAME["get_shop_cards"]["output_schema"]

    missing = registry.validate_args("resolve_shop", {})
    expected = validate_tool_args("resolve_shop", registry.get("resolve_shop"), {})
    assert missing == expected
    assert isinstance(ToolCallGateway(), ToolCallGateway)


def test_db_client_fixture_fallback_is_explicit_not_pytest_implicit(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("LOCAL_LIFE_DB_FIXTURE_FALLBACK", raising=False)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(db_client, "_ensure_connection", _boom)
    with pytest.raises(RuntimeError, match="boom"):
        db_client.query_all_shops()

    monkeypatch.setenv("LOCAL_LIFE_DB_FIXTURE_FALLBACK", "1")
    shops = db_client.query_all_shops()
    assert shops
    assert isinstance(shops[0], dict)
    assert shops[0]["shop_id"]


def test_runtime_db_tools_do_not_read_script_mock_data(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("LOCAL_LIFE_DB_FIXTURE_FALLBACK", raising=False)

    def _unexpected_mock_load(*_args, **_kwargs):
        raise AssertionError("runtime path should not read mock_data")

    monkeypatch.setattr(db_tools, "_load_mock_json", _unexpected_mock_load)
    monkeypatch.setattr(db_client, "query_coupons_by_shop_id", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(db_client, "query_shop_by_id", lambda *_args, **_kwargs: None)

    coupon_result = db_tools.get_coupon_list("shop_sc_01")
    detail_result = db_tools.get_shop_detail("shop_sc_01")

    assert coupon_result["success"] is True
    assert coupon_result["result_status"] == "empty"
    assert detail_result["success"] is False
    assert detail_result["result_status"] == "failed"


def test_candidate_resolver_default_resolves_via_shop_resolver_not_graph_builder():
    source = inspect.getsource(candidate_resolver_module._default_resolve_shop)
    assert "graph_builder" not in source
    assert "shop_resolver" in source

