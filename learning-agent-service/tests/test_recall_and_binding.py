"""recall_service + shop_binding 单元测试。"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from learning_agent_service.local_life.entity_decomposer import ShopEntity
from learning_agent_service.local_life.recall_service import RecallResult, recall_candidates
from learning_agent_service.local_life.shop_binding import (
    bind_shop_id,
    build_clarification_card,
)
from learning_agent_service.local_life.schemas import ShopRecord


def _make_shop(shop_id: int, name: str, area: str | None = None) -> ShopRecord:
    return ShopRecord(id=shop_id, name=name, area=area, source="java")


class TestRecallService:
    def test_recall_returns_first_hit(self):
        """exact 命中时返回 exact 结果。"""
        mock_client = MagicMock()
        entity = ShopEntity(brand="海底捞", area="水晶城", full_query="海底捞水晶城店")

        # exact 返回 1 个
        mock_client.search_shops_by_name.return_value = [_make_shop(5, "海底捞火锅(水晶城店)")]

        result = recall_candidates(mock_client, entity)
        assert result.strategy == "exact"
        assert len(result.candidates) == 1
        assert result.candidates[0].id == 5

    def test_recall_falls_through_on_empty(self):
        """exact 空 → brand_area 命中。"""
        mock_client = MagicMock()
        entity = ShopEntity(brand="海底捞", area="水晶城", full_query="海底捞水晶城店")

        call_count = 0
        def mock_search(name="", **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:  # exact
                return []
            return [_make_shop(5, "海底捞火锅(水晶城店)")]

        mock_client.search_shops_by_name = mock_search

        # brand_area 使用 _request_json
        mock_client._request_json = MagicMock(return_value={"success": True, "data": [_make_shop(5, "海底捞火锅(水晶城店)").model_dump()]})

        result = recall_candidates(mock_client, entity)
        assert result.strategy in ("brand_area", "brand_only")

    def test_recall_no_candidates(self):
        """所有策略都返回空 → strategy=none。"""
        mock_client = MagicMock()
        mock_client.search_shops_by_name.return_value = []
        mock_client._request_json.return_value = {"success": True, "data": []}
        mock_client.fallback_catalog.search_shops.return_value = []

        entity = ShopEntity(full_query="不存在的店")
        result = recall_candidates(mock_client, entity)
        assert result.strategy == "none"
        assert result.candidates == []


class TestShopBinding:
    def test_single_candidate_binds(self):
        """单候选直接绑定 shop_id。"""
        recall = RecallResult(candidates=[_make_shop(5, "海底捞")], strategy="exact")
        shop_id, card = bind_shop_id(recall)
        assert shop_id == 5
        assert card is None

    def test_multi_candidates_clarification(self):
        """多候选返回 clarification_card。"""
        candidates = [
            _make_shop(5, "海底捞(水晶城店)", area="水晶城"),
            _make_shop(6, "海底捞(万达店)", area="万达"),
        ]
        recall = RecallResult(candidates=candidates, strategy="brand_only")
        shop_id, card = bind_shop_id(recall)
        assert shop_id is None
        assert card is not None
        assert len(card.options) == 2
        assert card.options[0].label == "海底捞(水晶城店)"
        assert card.options[0].value == "5"

    def test_no_candidates(self):
        """无候选返回 (None, None)。"""
        recall = RecallResult(candidates=[], strategy="none")
        shop_id, card = bind_shop_id(recall)
        assert shop_id is None
        assert card is None

    def test_clarification_disabled(self):
        """禁用 clarification 时返回第一个候选。"""
        candidates = [_make_shop(5, "A"), _make_shop(6, "B")]
        recall = RecallResult(candidates=candidates, strategy="brand_only")
        shop_id, card = bind_shop_id(recall, allow_clarification=False)
        assert shop_id == 5
        assert card is None


class TestClarificationCard:
    def test_build_card(self):
        candidates = [
            _make_shop(5, "海底捞(水晶城店)", area="水晶城"),
            _make_shop(6, "海底捞(万达店)", area="万达"),
        ]
        card = build_clarification_card(candidates, source_turn_id="t1")
        assert card.card_id.startswith("cc_")
        assert card.source_turn_id == "t1"
        assert len(card.options) == 2
        assert "水晶城" in (card.options[0].description or "")
