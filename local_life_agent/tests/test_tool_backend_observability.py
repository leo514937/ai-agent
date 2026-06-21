from __future__ import annotations

from ..tools.gateway import dispatch_tool_call


def test_tool_results_mark_backend_source_mock():
    result = dispatch_tool_call("get_shop_detail", {"shop_id": "shop_sc_05"})

    assert result["backend_source"] == "mock"
    assert result["tool_backend"] == "mock"
