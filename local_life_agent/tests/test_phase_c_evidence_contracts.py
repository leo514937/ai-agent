from __future__ import annotations

from local_life_agent.answer.generator import _get_tool_results_from_evidence
from local_life_agent.planning.evidence.evidence_builder import build_evidence


def test_build_evidence_preserves_backend_source_on_evidence_items():
    evidence = build_evidence(
        tool_results={
            "call_coupon": {
                "call_id": "call_coupon",
                "shop_id": "shop_1",
                "tool_name": "get_coupon_list",
                "success": True,
                "result_status": "ok",
                "data": [
                    {
                        "coupon_id": "coupon_1",
                        "shop_id": "shop_1",
                        "title": "双人餐 88 元",
                        "description": "工作日可用",
                    }
                ],
                "backend_source": "java_api",
            },
            "call_open": {
                "call_id": "call_open",
                "shop_id": "shop_1",
                "tool_name": "check_open_status",
                "success": True,
                "result_status": "ok",
                "data": {
                    "shop_id": "shop_1",
                    "shop_name": "测试店",
                    "open_status": "open",
                },
                "backend_source": "java_api",
            },
        },
        resolved_target={
            "resolved_shop": {
                "shop_id": "shop_1",
                "shop_name": "测试店",
            }
        },
        execution_plan={
            "task_type": "single_shop_query",
            "tool_calls": [
                {"call_id": "call_coupon", "facet": "coupon", "required": True},
                {"call_id": "call_open", "facet": "open_status", "required": True},
            ],
        },
    )

    coupon_item = next(item for item in evidence["evidence_items"] if item["facet"] == "coupon")
    open_item = next(item for item in evidence["evidence_items"] if item["facet"] == "open_status")

    assert coupon_item["backend_source"] == "java_api"
    assert open_item["backend_source"] == "java_api"
    assert coupon_item["field_path"] == "data[0].title"
    assert evidence["tool_results"]["call_coupon"]["tool_name"] == "get_coupon_list"


def test_answer_generator_only_reads_tool_results_from_evidence_pack():
    tool_results = {"call_1": {"tool_name": "get_coupon_list"}}

    assert _get_tool_results_from_evidence({"tool_results": tool_results}) == tool_results
    assert _get_tool_results_from_evidence({"tool_result_set": tool_results}) == {}
