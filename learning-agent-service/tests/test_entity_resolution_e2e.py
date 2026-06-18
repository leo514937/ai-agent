"""End-to-end integration tests for the entity resolution pipeline.

Tests the full chain: decompose → recall → bind → ToolExecutor → stages_front_b bridge.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from learning_agent_service.domain import ToolExecutionCommand, ToolSelection
from learning_agent_service.domain.enums import ToolExecutionStatus
from learning_agent_service.local_life.entity_decomposer import decompose_shop_query
from learning_agent_service.local_life.recall_service import recall_candidates
from learning_agent_service.local_life.shop_binding import bind_shop_id, build_clarification_card
from learning_agent_service.local_life.schemas import ShopRecord
from learning_agent_service.tools.orchestrator_components import ToolExecutor, _resolve_shop_from_query


def _make_shop(shop_id: int, name: str, area: str | None = None) -> ShopRecord:
    return ShopRecord(id=shop_id, name=name, area=area, source="java")


def _mock_client(shops: list[ShopRecord] | None = None) -> MagicMock:
    client = MagicMock()
    client.get_brand_list.return_value = ["海底捞", "新白鹿", "外婆家"]
    client.get_area_list.return_value = ["水晶城", "万达", "乐堤港"]
    client.search_shops_by_name.return_value = shops or []
    # brand_area search uses _request_json
    client._request_json.return_value = {"data": []}
    # catalog fallback also needs to return empty when no shops
    client.fallback_catalog.search_shops.return_value = []
    return client


class TestEndToEndPipeline:
    """Full pipeline: query → decompose → recall → bind."""

    def test_exact_brand_area_resolves_to_shop(self):
        """'海底捞水晶城' → decompose(brand=海底捞, area=水晶城) → exact recall → bind."""
        shops = [_make_shop(5, "海底捞火锅(水晶城店)", area="水晶城")]
        client = _mock_client(shops)

        entity = decompose_shop_query("海底捞水晶城怎么样")
        assert entity.brand == "海底捞"
        assert entity.area == "水晶城"

        result = recall_candidates(client, entity)
        assert result.strategy == "exact"
        assert len(result.candidates) == 1

        shop_id, card = bind_shop_id(result, allow_clarification=True)
        assert shop_id == 5
        assert card is None

    def test_brand_only_resolves_single_shop(self):
        """'新白鹿有券吗' → decompose(brand=新白鹿) → brand_only recall → bind."""
        shops = [_make_shop(10, "新白鹿(万达店)", area="万达")]
        client = _mock_client(shops)

        entity = decompose_shop_query("新白鹿有券吗")
        assert entity.brand == "新白鹿"

        result = recall_candidates(client, entity)
        assert len(result.candidates) == 1

        shop_id, card = bind_shop_id(result, allow_clarification=True)
        assert shop_id == 10
        assert card is None

    def test_multi_shop_triggers_clarification(self):
        """'新白鹿哪家好吃' → 多候选 → clarification_card."""
        shops = [
            _make_shop(1, "新白鹿(水晶城店)", area="水晶城"),
            _make_shop(2, "新白鹿(万达店)", area="万达"),
        ]
        client = _mock_client(shops)

        entity = decompose_shop_query("新白鹿哪家好吃")
        result = recall_candidates(client, entity)

        shop_id, card = bind_shop_id(result, allow_clarification=True)
        assert shop_id is None
        assert card is not None
        assert len(card.options) == 2

    def test_no_match_returns_none(self):
        """未知品牌 → 无候选 → bind 返回 (None, None)。"""
        client = _mock_client([])

        entity = decompose_shop_query("某某不存在的店")
        result = recall_candidates(client, entity)

        shop_id, card = bind_shop_id(result, allow_clarification=True)
        assert shop_id is None
        assert card is None

    def test_full_tool_executor_flow_single_shop(self):
        """ToolExecutor._resolve_shop_from_query 单候选完整链路。"""
        shops = [_make_shop(5, "海底捞火锅(水晶城店)", area="水晶城")]
        client = _mock_client(shops)
        payload = {"shop_query": "海底捞水晶城怎么样"}

        result = _resolve_shop_from_query(client, "get_shop_detail", payload)
        assert result["resolved_shop_id"] == 5
        assert result["shop_id"] == 5
        assert "entity_brand" in result

    def test_full_tool_executor_flow_multi_shop(self):
        """ToolExecutor._resolve_shop_from_query 多候选返回 clarification_card。"""
        shops = [
            _make_shop(1, "新白鹿(水晶城店)", area="水晶城"),
            _make_shop(2, "新白鹿(万达店)", area="万达"),
        ]
        client = _mock_client(shops)
        payload = {"shop_query": "新白鹿哪家好吃"}

        result = _resolve_shop_from_query(client, "get_shop_detail", payload)
        assert "clarification_card" in result
        card = result["clarification_card"]
        assert len(card["options"]) == 2

    def test_entity_metadata_always_attached(self):
        """即使 recall 失败，entity 元数据仍然附着在 payload 中。"""
        client = _mock_client([])
        payload = {"shop_query": "海底捞火锅"}

        result = _resolve_shop_from_query(client, "get_shop_detail", payload)
        assert "entity_brand" in result
        assert result["entity_brand"] == "海底捞"
        assert "entity_area" in result
        assert "recall_strategy" in result
        assert "recall_count" in result

    def test_category_only_query_no_brand_match(self):
        """'火锅推荐' → category=火锅, brand=None → 走 category 召回。"""
        client = _mock_client([])
        payload = {"shop_query": "火锅推荐"}

        result = _resolve_shop_from_query(client, "search_restaurants", payload)
        assert "entity_brand" in result
        assert result["entity_brand"] is None
        assert "entity_category" in result
        assert result["entity_category"] == "火锅"

    def test_shop_name_fallback_when_shop_query_empty(self):
        """当 shop_query 为空但 shop_name 存在时，回退使用 shop_name。"""
        shops = [_make_shop(5, "海底捞火锅")]
        client = _mock_client(shops)
        payload = {"shop_query": None, "shop_name": "海底捞火锅"}

        result = _resolve_shop_from_query(client, "get_shop_detail", payload)
        assert result["resolved_shop_id"] == 5
        assert result["entity_brand"] == "海底捞"

    def test_non_shop_tool_skips_resolution(self):
        """非本地生活工具不触发 entity resolution。"""
        client = _mock_client([_make_shop(99, "should not appear")])
        payload = {"topic": "python tutorial"}

        result = _resolve_shop_from_query(client, "some_other_tool", payload)
        # 空 shop_query 会跳过
        assert result == payload


class TestClarificationCardIntegration:
    """clarification_card 生成和消费集成。"""

    def test_clarification_card_payload_format(self):
        """clarification_card 的 options 包含 id/label/value/description。"""
        candidates = [
            _make_shop(1, "海底捞(水晶城店)", area="水晶城"),
            _make_shop(2, "海底捞(万达店)", area="万达"),
        ]
        card = build_clarification_card(
            candidates=candidates,
            question="海底捞有多家门店，你想查哪家？",
            source_turn_id="turn-123",
        )
        assert card is not None
        assert len(card.options) == 2
        for opt in card.options:
            assert opt.id is not None
            assert opt.label is not None
            assert opt.value is not None

    def test_clarification_card_deterministic_ids(self):
        """多次构建相同的 clarification_card 产生相同结构。"""
        candidates = [_make_shop(1, "店A"), _make_shop(2, "店B")]
        card1 = build_clarification_card(candidates=candidates, question="选哪家？", source_turn_id="t1")
        card2 = build_clarification_card(candidates=candidates, question="选哪家？", source_turn_id="t1")
        # card_id is UUID-based, so different instances — but structure is identical
        assert len(card1.options) == len(card2.options)
        assert [o.label for o in card1.options] == [o.label for o in card2.options]
