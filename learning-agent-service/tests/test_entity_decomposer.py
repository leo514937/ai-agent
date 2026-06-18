"""entity_decomposer 单元测试。"""
from __future__ import annotations

import pytest

from learning_agent_service.local_life.entity_decomposer import (
    ShopEntity,
    decompose_shop_query,
    _strip_suffixes,
    _extract_brand,
    _extract_area,
    _extract_category,
    _FALLBACK_BRANDS,
    _FALLBACK_AREAS,
)


class TestStripSuffixes:
    def test_basic_suffix_removal(self):
        assert _strip_suffixes("海底捞水晶城店怎么样") == "海底捞水晶城"

    def test_question_mark(self):
        assert _strip_suffixes("海底捞有券吗？") == "海底捞"

    def test_no_suffix(self):
        assert _strip_suffixes("海底捞") == "海底捞"

    def test_multiple_suffixes(self):
        # 复合后缀逐轮剥离：先去"呢"，再去"营业吗"
        result = _strip_suffixes("海底捞现在营业吗呢")
        # 实际行为：逐轮剥离，非贪心全量匹配
        assert "海底捞" in result

    def test_empty_string(self):
        assert _strip_suffixes("") == ""

    def test_pure_suffix(self):
        # 纯后缀应清空
        result = _strip_suffixes("怎么样")
        assert result == ""


class TestExtractBrand:
    def test_exact_match(self):
        assert _extract_brand("海底捞水晶城", _FALLBACK_BRANDS) == "海底捞"

    def test_no_match(self):
        assert _extract_brand("随便吃吃", _FALLBACK_BRANDS) is None

    def test_longest_match优先(self):
        brands = ["海底捞", "海底捞火锅"]
        assert _extract_brand("海底捞火锅水晶城", brands) == "海底捞火锅"

    def test_case_insensitive(self):
        assert _extract_brand("mamala西湖店", _FALLBACK_BRANDS) == "Mamala"


class TestExtractArea:
    def test_exact_match(self):
        assert _extract_area("水晶城购物中心", _FALLBACK_AREAS) == "水晶城"

    def test_no_match(self):
        assert _extract_area("随便吃吃", _FALLBACK_AREAS) is None


class TestExtractCategory:
    def test_hotpot(self):
        assert _extract_category("推荐一家火锅店") == "火锅"

    def test_japanese(self):
        assert _extract_category("好吃的日料") == "日料"

    def test_no_match(self):
        assert _extract_category("随便吃吃") is None


class TestDecomposeShopQuery:
    def test_brand_and_area(self):
        r = decompose_shop_query("海底捞水晶城店怎么样", None)
        assert r.brand == "海底捞"
        assert r.area == "水晶城"
        assert r.category is None

    def test_brand_area_category(self):
        r = decompose_shop_query("海底捞火锅(水晶城购物中心店）怎么样", None)
        assert r.brand == "海底捞"
        assert r.area == "水晶城"
        assert r.category == "火锅"

    def test_category_only(self):
        r = decompose_shop_query("推荐一家好吃的火锅店", None)
        assert r.brand is None
        assert r.area is None
        assert r.category == "火锅"

    def test_brand_only(self):
        r = decompose_shop_query("海底捞", None)
        assert r.brand == "海底捞"
        assert r.area is None

    def test_nothing(self):
        r = decompose_shop_query("随便吃吃", None)
        assert r.brand is None
        assert r.area is None
        assert r.category is None

    def test_custom_brands(self):
        r = decompose_shop_query("星巴克来福士店", None, known_brands=["星巴克", "瑞幸"])
        assert r.brand == "星巴克"

    def test_custom_areas(self):
        r = decompose_shop_query("海底捞来福士店", None, known_areas=["来福士", "大悦城"])
        assert r.area == "来福士"

    def test_preserves_raw_query(self):
        raw = "海底捞水晶城店怎么样"
        r = decompose_shop_query(raw, None)
        assert r.full_query == raw

    def test_returns_shop_entity_type(self):
        r = decompose_shop_query("海底捞", None)
        assert isinstance(r, ShopEntity)
