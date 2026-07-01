from __future__ import annotations

from local_life_agent.tools import db_client
from local_life_agent.tools.normalizer import normalize_tool_result
from local_life_agent.tools.registry import TOOL_DEFINITIONS


def _tool_def(name: str) -> dict:
    for tool_def in TOOL_DEFINITIONS:
        if tool_def["name"] == name:
            return tool_def
    raise AssertionError(f"未找到 tool 定义: {name}")


def test_normalize_tool_result_preserves_unsupported_status():
    result = normalize_tool_result(
        "get_shop_cards",
        {
            "success": False,
            "result_status": "unsupported",
            "data": None,
            "backend_source": "java_api",
        },
    )

    assert result["result_status"] == "unsupported"
    assert result["success"] is False


def test_search_shops_and_coupon_list_output_schema_are_plain_arrays():
    search_schema = _tool_def("search_shops")["output_schema"]
    coupon_schema = _tool_def("get_coupon_list")["output_schema"]

    assert search_schema == {"type": "array", "items": search_schema["items"]}
    assert coupon_schema == {"type": "array", "items": coupon_schema["items"]}


def test_coupon_schema_only_exposes_real_fields():
    coupon_props = _tool_def("get_coupon_list")["output_schema"]["items"]["properties"]

    assert set(coupon_props) == {
        "coupon_id",
        "shop_id",
        "title",
        "description",
        "pay_value",
        "actual_value",
        "status",
    }


def test_row_to_coupon_does_not_fabricate_contract_fields():
    coupon = db_client._row_to_coupon(
        {
            "id": 1001,
            "shop_id": 2002,
            "title": "双人餐",
            "sub_title": "工作日可用",
            "rules": "",
            "pay_value": 8800,
            "actual_value": 10800,
            "status": 1,
        }
    )

    assert coupon == {
        "coupon_id": "1001",
        "shop_id": "2002",
        "title": "双人餐",
        "description": "工作日可用",
        "pay_value": 8800,
        "actual_value": 10800,
        "status": "available",
    }
    for fake_field in (
        "discount_type",
        "discount_value",
        "min_consume",
        "valid_from",
        "valid_until",
        "stock",
    ):
        assert fake_field not in coupon


def test_tool_output_status_enum_includes_unsupported_for_phase_a_tools():
    for tool_name in ("get_shop_cards", "get_shop_review_summary", "get_deal_list"):
        assert "unsupported" in _tool_def(tool_name)["output_status_enum"]
