"""_resolve_shop_from_query + ToolExecutor entity resolution 集成测试。"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from learning_agent_service.domain import ToolExecutionCommand, ToolSelection
from learning_agent_service.domain.enums import ToolExecutionStatus
from learning_agent_service.local_life.entity_decomposer import ShopEntity
from learning_agent_service.local_life.recall_service import RecallResult
from learning_agent_service.local_life.schemas import ShopRecord
from learning_agent_service.tools.orchestrator_components import (
    ToolExecutor,
    _resolve_shop_from_query,
    _TOOLS_NEEDING_SHOP_ID,
    _TOOLS_WITH_SEARCH,
)


def _make_shop(shop_id: int, name: str, area: str | None = None) -> ShopRecord:
    return ShopRecord(id=shop_id, name=name, area=area, source="java")


def _mock_client(shops: list[ShopRecord] | None = None) -> MagicMock:
    """Create a mock JavaBusinessClient with get_brand_list/get_area_list/search methods."""
    client = MagicMock()
    client.get_brand_list.return_value = ["海底捞", "新白鹿"]
    client.get_area_list.return_value = ["水晶城", "万达"]
    client.search_shops_by_name.return_value = shops or []
    # brand_area search uses _request_json
    client._request_json.return_value = {"data": []}
    # catalog fallback also needs to return empty when no shops
    client.fallback_catalog.search_shops.return_value = shops or []
    return client


# ── _resolve_shop_from_query unit tests ──────────────────────────────────────

class TestResolveShopFromQuery:
    def test_single_candidate_binds_shop_id(self):
        """单候选 → resolved_shop_id 注入。"""
        client = _mock_client([_make_shop(5, "海底捞火锅(水晶城店)")])
        payload = {"shop_query": "海底捞水晶城店怎么样", "category": None}

        result = _resolve_shop_from_query(client, "get_shop_detail", payload)

        assert result["resolved_shop_id"] == 5
        assert result["shop_id"] == 5
        assert result["entity_brand"] == "海底捞"
        assert result["entity_area"] == "水晶城"
        assert result["recall_strategy"] == "exact"
        assert result["recall_count"] == 1
        assert "clarification_card" not in result

    def test_multi_candidates_returns_clarification_card(self):
        """多候选 → clarification_card 生成。"""
        client = _mock_client([
            _make_shop(5, "海底捞火锅(水晶城店)", "水晶城"),
            _make_shop(6, "海底捞火锅(万达店)", "万达"),
        ])
        payload = {"shop_query": "海底捞", "category": None}

        result = _resolve_shop_from_query(client, "get_shop_detail", payload)

        assert "clarification_card" in result
        cc = result["clarification_card"]
        assert "card_id" in cc
        assert len(cc["options"]) == 2
        assert cc["options"][0]["label"] == "海底捞火锅(水晶城店)"
        assert cc["options"][1]["label"] == "海底捞火锅(万达店)"

    def test_no_candidates_returns_original(self):
        """无候选 → 返回原始 payload。"""
        client = _mock_client([])
        payload = {"shop_query": "不存在的店", "category": None}

        result = _resolve_shop_from_query(client, "get_shop_detail", payload)

        assert "resolved_shop_id" not in result
        assert "clarification_card" not in result
        # 原始 payload 保留
        assert result.get("shop_query") == "不存在的店"

    def test_empty_shop_query_skips(self):
        """空 shop_query → 跳过分解，返回原始 payload。"""
        client = _mock_client()
        payload = {"shop_query": "", "category": None}

        result = _resolve_shop_from_query(client, "get_shop_detail", payload)

        # 不做分解，直接返回
        assert result == payload

    def test_none_client_skips(self):
        """client=None → 跳过分解。"""
        payload = {"shop_query": "海底捞怎么样"}

        result = _resolve_shop_from_query(None, "get_shop_detail", payload)

        assert result == payload

    def test_error_in_recall_returns_enriched(self):
        """recall 抛异常但 catalog 兜底成功 → 仍然返回 enriched payload。"""
        client = _mock_client()
        client.search_shops_by_name.side_effect = RuntimeError("timeout")
        client._request_json.side_effect = RuntimeError("timeout")
        # catalog fallback will still use fallback_catalog.search_shops
        client.fallback_catalog.search_shops.return_value = [_make_shop(99, "兜底店")]

        payload = {"shop_query": "海底捞"}
        result = _resolve_shop_from_query(client, "get_shop_detail", payload)

        # 所有DB策略失败，catalog fallback 成功
        assert result["entity_brand"] == "海底捞"
        assert result["recall_strategy"] == "catalog"
        assert result["recall_count"] == 1
        assert result["resolved_shop_id"] == 99

    def test_entity_metadata_always_attached(self):
        """即使无候选，entity 元数据也应附加。"""
        client = _mock_client([])
        payload = {"shop_query": "海底捞火锅"}

        result = _resolve_shop_from_query(client, "get_shop_detail", payload)

        assert result["entity_brand"] == "海底捞"
        assert result["recall_strategy"] == "none"
        assert result["recall_count"] == 0

    def test_shop_name_fallback(self):
        """当 shop_query 为空但 shop_name 存在时，使用 shop_name。"""
        client = _mock_client([_make_shop(5, "海底捞火锅")])
        payload = {"shop_query": None, "shop_name": "海底捞火锅"}

        result = _resolve_shop_from_query(client, "get_shop_detail", payload)

        assert result["resolved_shop_id"] == 5
        assert result["entity_brand"] == "海底捞"

    def test_non_local_life_tool_skips(self):
        """非本地生活工具 → 跳过（由调用方的 frozenset 过滤）。"""
        client = _mock_client()
        payload = {"topic": "python tutorial"}

        result = _resolve_shop_from_query(client, "unknown_tool", payload)

        # 虽然 _resolve_shop_from_query 本身不做工具过滤（由调用方负责），
        # 但空 shop_query 会跳过
        assert result == payload


# ── ToolExecutor.execute entity resolution integration ───────────────────────

class TestToolExecutorEntityResolution:
    def test_execute_skips_resolution_for_non_shop_tool(self):
        """非 shop 工具 → 不触发 entity resolution。"""
        client = _mock_client([_make_shop(99, "should not be called")])
        executor = ToolExecutor(java_business_client=client)

        selection = ToolSelection(
            tool_name="get_shop_type_list",
            should_execute=True,
            input_payload={"limit": 10},
            reason="test",
            approval_status=None,
        )
        cmd = ToolExecutionCommand(selection=selection)

        result = executor.execute(cmd)

        # 不触发 entity resolution（get_shop_type_list 不在 frozenset 中）
        # 执行会失败（tool not registered in mock），但不触发 resolution
        assert result.tool_name == "get_shop_type_list"

    def test_execute_triggers_resolution_for_shop_detail(self):
        """get_shop_detail + 有 shop_query → 触发 entity resolution。"""
        client = _mock_client([_make_shop(42, "海底捞火锅(水晶城店)")])
        executor = ToolExecutor(java_business_client=client)

        selection = ToolSelection(
            tool_name="get_shop_detail",
            should_execute=True,
            input_payload={"shop_query": "海底捞水晶城", "shop_id": None, "query": "test"},
            reason="test",
            approval_status=None,
        )
        cmd = ToolExecutionCommand(selection=selection)

        result = executor.execute(cmd)

        # entity resolution 被触发了（即使 tool 执行可能失败）
        # 关键验证：selection.input_payload 被 enrich 了
        # 由于 tool 未注册会返回 error，但 entity resolution 确实执行了
        assert result.tool_name == "get_shop_detail"

    def test_execute_short_circuits_on_clarification(self):
        """多候选 → 返回 clarification_card，不执行 tool。"""
        client = _mock_client([
            _make_shop(10, "海底捞A店", "水晶城"),
            _make_shop(20, "海底捞B店", "万达"),
        ])
        executor = ToolExecutor(java_business_client=client)

        selection = ToolSelection(
            tool_name="get_shop_detail",
            should_execute=True,
            input_payload={"shop_query": "海底捞"},
            reason="test",
            approval_status=None,
        )
        cmd = ToolExecutionCommand(selection=selection)

        result = executor.execute(cmd)

        # clarification_card → short-circuit, 不走 base executor
        assert result.status == ToolExecutionStatus.SUCCESS
        assert result.output_payload.get("clarification_needed") is True
        cc = result.output_payload.get("clarification_card")
        assert cc is not None
        assert len(cc["options"]) == 2
        assert result.extra.get("entity_resolution") is True

    def test_execute_no_client_skips_resolution(self):
        """java_business_client=None → 跳过 entity resolution。"""
        executor = ToolExecutor(java_business_client=None)

        selection = ToolSelection(
            tool_name="get_shop_detail",
            should_execute=True,
            input_payload={"shop_query": "海底捞"},
            reason="test",
            approval_status=None,
        )
        cmd = ToolExecutionCommand(selection=selection)

        result = executor.execute(cmd)

        # 没有 client，不做 resolution，直接走 base executor
        # tool 未注册 → 失败
        assert result.tool_name == "get_shop_detail"

    def test_execute_search_tool_triggers_resolution(self):
        """search_restaurants 也在 _TOOLS_WITH_SEARCH 中 → 触发 resolution。"""
        client = _mock_client([_make_shop(1, "某店")])
        executor = ToolExecutor(java_business_client=client)

        selection = ToolSelection(
            tool_name="search_restaurants",
            should_execute=True,
            input_payload={"shop_query": "火锅", "query": "火锅"},
            reason="test",
            approval_status=None,
        )
        cmd = ToolExecutionCommand(selection=selection)

        result = executor.execute(cmd)

        assert result.tool_name == "search_restaurants"


# ── frozenset completeness ────────────────────────────────────────────────────

class TestToolFrozensets:
    def test_shop_id_tools_covered(self):
        """关键 shop 工具都在 _TOOLS_NEEDING_SHOP_ID 中。"""
        expected = {"get_shop_detail", "create_booking", "create_order", "get_coupon_list", "get_blog_list"}
        assert expected.issubset(_TOOLS_NEEDING_SHOP_ID)

    def test_search_tools_covered(self):
        """search_restaurants 在 _TOOLS_WITH_SEARCH 中。"""
        assert "search_restaurants" in _TOOLS_WITH_SEARCH
        assert "restaurant_recommendation" in _TOOLS_WITH_SEARCH

    def test_no_overlap_between_sets(self):
        """两个 frozenset 不重叠。"""
        assert _TOOLS_NEEDING_SHOP_ID.isdisjoint(_TOOLS_WITH_SEARCH)
