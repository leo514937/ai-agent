"""Contract tests for todo/07 — Mock scenario library.

Verifies each of the 15 core scenario shops returns the correct mock data
through the tool interface.

Scenarios (from todo/07 §1 — Mock Data 场景表):
  1.  shop_sc_01  5属性齐全店
  2.  shop_sc_02  全部属性缺失店
  3.  shop_sc_03  核心属性缺失店(无评分)
  4.  shop_sc_04  无优惠券店
  5.  shop_sc_05  有优惠券店
  6.  shop_sc_06  券查询timeout店
  7.  shop_sc_07  营业中店
  8.  shop_sc_08  已关门店
  9.  shop_sc_09  营业状态unknown店
  10. shop_sc_10  距离近店(<1km)
  11. shop_sc_11  距离远店(>10km)
  12. shop_sc_12  适合约会tag店
  13. shop_sc_13  不适合约会但有优惠券店
  14. shop_sc_14a 重名店 — 老北京炸酱面·学院路
  15. shop_sc_14b 重名店 — 老北京炸酱面·花园路
  16. shop_sc_15  未知维度(unknown_dimension)
"""

from __future__ import annotations

import pytest

from .fakes.mock_tools import (
    get_shop_detail,
    search_shops,
    get_coupon_list,
    check_open_status,
    get_distance_eta,
)
from ..tools.gateway import dispatch_tool_call


# ===================================================================
# 场景 1–3: 属性完整性
# ===================================================================


class TestScenarioAttributeCompleteness:
    """场景 1–3 — 属性完整性验证."""

    def test_sc01_complete_shop(self):
        """5属性齐全店 — 所有字段均存在."""
        result = get_shop_detail("shop_sc_01")
        assert result["success"] is True
        shop = result["data"]
        assert shop is not None
        assert shop["shop_name"] == "海底捞火锅(水晶城购物中心店)"
        assert shop["category"] == "火锅"
        assert shop.get("rating") is not None
        assert shop.get("open_status") == "open"
        assert shop.get("lat") is not None
        assert shop.get("lng") is not None

    def test_sc02_unknown_shop_returns_not_found(self):
        """不存在的场景 shop_id 应返回 SHOP_NOT_FOUND."""
        result = get_shop_detail("shop_sc_02")
        assert result["success"] is False
        assert result["error_code"] == "SHOP_NOT_FOUND"

    def test_sc03_unknown_shop_returns_not_found(self):
        """不存在的场景 shop_id 应返回 SHOP_NOT_FOUND."""
        result = get_shop_detail("shop_sc_03")
        assert result["success"] is False
        assert result["error_code"] == "SHOP_NOT_FOUND"


# ===================================================================
# 场景 4–6: 优惠券相关
# ===================================================================


class TestScenarioCoupons:
    """场景 4–6 — 优惠券相关验证."""

    def test_sc04_no_coupons(self):
        """无优惠券店 — 返回空列表."""
        result = get_coupon_list("shop_sc_04")
        assert result["success"] is True
        assert result["result_status"] == "empty"
        assert len(result["data"]) == 0
        assert result["total"] == 0

    def test_sc05_has_coupons(self):
        """有优惠券店 — 返回优惠券列表."""
        result = get_coupon_list("shop_sc_05")
        assert result["success"] is True
        assert result["result_status"] == "ok"
        assert len(result["data"]) > 0
        # 川味轩 should have at least one coupon
        names = [c["title"] for c in result["data"]]
        assert any("川味轩" in n or "水煮鱼" in n or "满100减20" in n for n in names)

    def test_sc06_coupon_query_timeout(self):
        """券查询timeout店 — 网关应捕获 TimeoutError 返回 TOOL_TIMEOUT."""
        # Direct call should raise
        with pytest.raises(TimeoutError):
            get_coupon_list("shop_sc_06")
        # Gateway call should catch and wrap
        gw_result = dispatch_tool_call("get_coupon_list", {"shop_id": "shop_sc_06"})
        assert gw_result["success"] is False
        assert gw_result["result_status"] == "unknown"
        assert gw_result["error_code"] == "TOOL_TIMEOUT"


# ===================================================================
# 场景 7–9: 营业状态
# ===================================================================


class TestScenarioOpenStatus:
    """场景 7–9 — 营业状态验证."""

    def test_sc07_open(self):
        """营业中店 — open_status = 'open'."""
        result = check_open_status("shop_sc_07")
        assert result["success"] is True
        assert result["data"]["open_status"] == "open"
        assert result["data"]["shop_name"] == "永和大王(北师大店)"

    def test_sc08_closed(self):
        """已关门店 — open_status = 'closed'."""
        result = check_open_status("shop_sc_08")
        assert result["success"] is True
        assert result["data"]["open_status"] == "closed"

    def test_sc09_unknown(self):
        """营业状态unknown店 — open_status = 'unknown'."""
        result = check_open_status("shop_sc_09")
        assert result["success"] is True
        assert result["data"]["open_status"] == "unknown"


# ===================================================================
# 场景 10–11: 距离
# ===================================================================


class TestScenarioDistance:
    """场景 10–11 — 距离验证."""

    def test_sc10_nearby(self):
        """距离近店 — < 1 km from 北邮."""
        result = get_distance_eta("shop_sc_10", {"lat": 39.9609, "lng": 116.3581})
        assert result["success"] is True
        assert result["data"]["distance_km"] < 1.0

    def test_sc11_far(self):
        """距离远店 — > 10 km from 北邮."""
        result = get_distance_eta("shop_sc_11", {"lat": 39.9609, "lng": 116.3581})
        assert result["success"] is True
        assert result["data"]["distance_km"] > 10.0


# ===================================================================
# 场景 12–13: 标签/维度
# ===================================================================


class TestScenarioTags:
    """场景 12–13 — 标签与维度验证."""

    def test_sc12_suitable_for_date(self):
        """适合约会tag店 — search 应匹配 '约会' tag."""
        result = search_shops("约会")
        assert result["success"] is True
        shop_ids = [s["shop_id"] for s in result["data"]]
        assert "shop_sc_12" in shop_ids

    def test_sc13_not_date_but_has_coupon(self):
        """不适合约会但有优惠券店 — search '约会' 不匹配, 但有优惠券."""
        result = search_shops("约会")
        shop_ids = [s["shop_id"] for s in result["data"]]
        assert "shop_sc_13" not in shop_ids
        # But it has coupons
        coupon_result = get_coupon_list("shop_sc_13")
        assert coupon_result["success"] is True
        assert len(coupon_result["data"]) > 0


# ===================================================================
# 场景 14: 重名店铺消歧
# ===================================================================


class TestScenarioDuplicateName:
    """场景 14a/b — 重名店铺消歧."""

    def test_sc14_duplicate_named_shop(self):
        """搜索 '老北京炸酱面' 应返回两家."""
        result = search_shops("老北京炸酱面")
        assert result["success"] is True
        assert result["total"] >= 2
        shop_ids = [s["shop_id"] for s in result["data"]]
        assert "shop_sc_14a" in shop_ids
        assert "shop_sc_14b" in shop_ids

    def test_sc14a_detail_academy_road(self):
        """学院路店 — 名称含学院路."""
        detail = get_shop_detail("shop_sc_14a")
        assert detail["success"] is True
        assert "学院路" in detail["data"]["shop_name"]

    def test_sc14b_detail_garden_road(self):
        """花园路店 — 名称含花园路."""
        detail = get_shop_detail("shop_sc_14b")
        assert detail["success"] is True
        assert "花园路" in detail["data"]["shop_name"]


# ===================================================================
# 场景 15: 未知维度
# ===================================================================


class TestScenarioUnknownDimension:
    """场景 15 — 未知维度验证."""

    def test_sc15_unknown_dimension(self):
        """未知维度店 — shop_detail 返回且 category 为 '其他'."""
        result = get_shop_detail("shop_sc_15")
        assert result["success"] is True
        shop = result["data"]
        assert shop["shop_name"] == "新品体验店(中关村)"
        assert shop["category"] == "其他"
        # No coupons
        coupon_result = get_coupon_list("shop_sc_15")
        assert coupon_result["result_status"] == "empty"


# ===================================================================
# 工具契约验证 (§3)
# ===================================================================


class TestToolContract:
    """工具契约 — 所有 mock 工具通过 Gateway 返回标准结果."""

    def test_get_shop_detail_through_gateway(self):
        gw = dispatch_tool_call("get_shop_detail", {"shop_id": "shop_sc_01"})
        assert gw["success"] is True
        assert gw["result_status"] == "ok"
        assert gw["tool_name"] == "get_shop_detail"

    def test_search_shops_through_gateway(self):
        gw = dispatch_tool_call("search_shops", {"query": "火锅"})
        assert gw["success"] is True
        assert gw["result_status"] == "ok"

    def test_get_coupon_list_through_gateway(self):
        gw = dispatch_tool_call("get_coupon_list", {"shop_id": "shop_sc_05"})
        assert gw["success"] is True
        assert gw["result_status"] == "ok"
        assert len(gw["data"]) > 0

    def test_check_open_status_through_gateway(self):
        gw = dispatch_tool_call("check_open_status", {"shop_id": "shop_sc_07"})
        assert gw["success"] is True
        assert gw["result_status"] == "ok"

    def test_get_distance_eta_through_gateway(self):
        gw = dispatch_tool_call("get_distance_eta", {
            "shop_id": "shop_sc_10",
            "from_location": {"lat": 39.9609, "lng": 116.3581},
        })
        assert gw["success"] is True
        assert gw["result_status"] == "ok"

    def test_unknown_tool_returns_not_registered(self):
        gw = dispatch_tool_call("nonexistent_tool", {})
        assert gw["success"] is False
        assert gw["error_code"] == "SCHEMA_VALIDATION_FAILED"
