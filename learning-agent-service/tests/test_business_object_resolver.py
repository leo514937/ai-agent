"""BusinessObjectResolver 测试"""

import pytest
from unittest.mock import MagicMock, patch
from learning_agent_service.local_life.business_object_resolver import (
    BusinessObjectResolver,
    ResolvedShop,
    ResolutionStrategy,
)
from learning_agent_service.local_life.schemas import ShopRecord


@pytest.fixture
def mock_client():
    """Mock JavaBusinessClient"""
    client = MagicMock()
    client.get_shop_detail = MagicMock()
    client.search_shops_by_name = MagicMock()
    client.search_candidates = MagicMock()
    return client


@pytest.fixture
def sample_shops():
    """示例店铺数据"""
    return [
        ShopRecord(id=5, name="海底捞火锅(水晶城购物中心店）", area="江干区"),
        ShopRecord(id=6, name="海底捞火锅(西溪印象城店）", area="西湖区"),
        ShopRecord(id=7, name="海底捞火锅(大悦城店）", area="拱墅区"),
    ]


class TestBusinessObjectResolver:
    """BusinessObjectResolver 测试"""

    def test_resolve_by_exact_id(self, mock_client):
        """测试通过 shop_id 解析"""
        mock_shop = ShopRecord(id=5, name="海底捞火锅(水晶城购物中心店）")
        mock_client.get_shop_detail.return_value = mock_shop

        resolver = BusinessObjectResolver(client=mock_client)
        result = resolver.resolve(
            raw_query="海底捞水晶城店怎么样",
            shop_id=5,
            shop_name=None,
            brand=None,
            area=None,
            intent_type="detail",
        )

        assert result.id == 5
        assert result.name == "海底捞火锅(水晶城购物中心店）"
        assert result.confidence == 1.0
        assert result.source == ResolutionStrategy.EXACT_ID.value

    def test_resolve_by_name_single_candidate(self, mock_client):
        """测试通过名称解析 - 单候选"""
        mock_shop = ShopRecord(id=5, name="海底捞火锅(水晶城购物中心店）")
        mock_client.search_shops_by_name.return_value = [mock_shop]

        resolver = BusinessObjectResolver(client=mock_client)
        result = resolver.resolve(
            raw_query="海底捞水晶城店怎么样",
            shop_id=None,
            shop_name="海底捞水晶城店",
            brand=None,
            area=None,
            intent_type="detail",
        )

        assert result.id == 5
        assert result.name == "海底捞火锅(水晶城购物中心店）"
        assert result.confidence > 0.0  # 有匹配
        assert result.source in (ResolutionStrategy.NAME_EXACT.value, ResolutionStrategy.NAME_FUZZY.value)

    def test_resolve_by_name_multiple_candidates_recommendation(self, mock_client, sample_shops):
        """测试通过名称解析 - 多候选 + 推荐意图"""
        mock_client.search_shops_by_name.return_value = sample_shops

        resolver = BusinessObjectResolver(client=mock_client)
        result = resolver.resolve(
            raw_query="海底捞",
            shop_id=None,
            shop_name="海底捞",
            brand=None,
            area=None,
            intent_type="recommendation",
        )

        assert result.id is None
        assert result.source == ResolutionStrategy.CANDIDATE_LIST.value
        assert result.candidates is not None
        assert len(result.candidates) == 3

    def test_resolve_by_name_multiple_candidates_clarification(self, mock_client, sample_shops):
        """测试通过名称解析 - 多候选 + 单店意图"""
        mock_client.search_shops_by_name.return_value = sample_shops

        resolver = BusinessObjectResolver(client=mock_client)
        result = resolver.resolve(
            raw_query="海底捞",
            shop_id=None,
            shop_name="海底捞",
            brand=None,
            area=None,
            intent_type="coupon_query",
        )

        assert result.id is None
        assert result.source == ResolutionStrategy.CLARIFICATION_NEEDED.value
        assert result.candidates is not None
        assert len(result.candidates) == 3

    def test_resolve_by_brand_area(self, mock_client):
        """测试通过 brand + area 解析"""
        mock_shop = ShopRecord(id=5, name="海底捞火锅(水晶城购物中心店）", area="江干区")
        mock_client.search_candidates.return_value = [mock_shop]

        resolver = BusinessObjectResolver(client=mock_client)
        result = resolver.resolve(
            raw_query="江干区海底捞",
            shop_id=None,
            shop_name=None,
            brand="海底捞",
            area="江干区",
            intent_type="detail",
        )

        assert result.id == 5
        assert result.source == ResolutionStrategy.BRAND_AREA.value

    def test_resolve_not_found(self, mock_client):
        """测试未找到"""
        mock_client.search_shops_by_name.return_value = []
        mock_client.search_candidates.return_value = []

        resolver = BusinessObjectResolver(client=mock_client)
        result = resolver.resolve(
            raw_query="不存在的店",
            shop_id=None,
            shop_name="不存在的店",
            brand=None,
            area=None,
            intent_type="detail",
        )

        assert result.id is None
        assert result.source == ResolutionStrategy.NOT_FOUND.value

    def test_resolve_by_id_not_found(self, mock_client):
        """测试通过 shop_id 解析但未找到"""
        mock_client.get_shop_detail.side_effect = Exception("shop not found")

        resolver = BusinessObjectResolver(client=mock_client)
        result = resolver.resolve(
            raw_query="海底捞水晶城店怎么样",
            shop_id=999,
            shop_name=None,
            brand=None,
            area=None,
            intent_type="detail",
        )

        assert result.id is None
        assert result.source == ResolutionStrategy.NOT_FOUND.value
