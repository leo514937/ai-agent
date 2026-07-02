from __future__ import annotations

from typing import Any

DEFAULT_TEST_LOCATION = {"lat": 39.9609, "lng": 116.3581}


def _case(
    name: str,
    *,
    query: str | None = None,
    turns: list[str] | None = None,
    session_id: str,
    route_task: str,
    workflow_name: str,
    expected_facets: list[str],
    initial_session_state: dict[str, Any] | None = None,
    empty_search_queries: list[str] | None = None,
    tool_failures: dict[str, str] | None = None,
    verify_should_fail: bool = False,
    verify_failure_phrase: str = "unsupported claim",
    target_resolution: dict[str, Any] | None = None,
    state_writebacks: dict[str, bool] | None = None,
    golden_trace: str | None = None,
    extra_expectations: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "name": name,
        "query": query,
        "turns": turns,
        "session_id": session_id,
        "route_task": route_task,
        "workflow_name": workflow_name,
        "expected_facets": expected_facets,
        "initial_session_state": initial_session_state or {},
        "empty_search_queries": empty_search_queries or [],
        "tool_failures": tool_failures or {},
        "verify_should_fail": verify_should_fail,
        "verify_failure_phrase": verify_failure_phrase,
        "target_resolution": target_resolution or {},
        "state_writebacks": state_writebacks or {},
        "golden_trace": golden_trace or name,
        "extra_expectations": extra_expectations or {},
    }
    return payload


P6_COMPLEX_QUERY_MATRIX_CASES: list[dict[str, Any]] = [
    _case(
        "multi_constraint_recommendation",
        query="附近推荐几家适合约会、现在营业、最好有券、人均100左右的餐厅",
        session_id="p6_multi_constraint_recommendation",
        route_task="recommendation",
        workflow_name="discovery_decision",
        expected_facets=["nearby", "restaurant", "date_scene", "open_now", "coupon", "budget_around_x"],
        initial_session_state={"user_location": DEFAULT_TEST_LOCATION},
        target_resolution={"resolved": False, "source": None},
        state_writebacks={"last_recommendation_list": True, "current_shop": False, "comparison_targets": False, "pending_clarification": False},
        golden_trace="multi_constraint_recommendation",
    ),
    _case(
        "multi_dimensional_comparison",
        query="第一家和第二家哪家更适合带娃，哪家更便宜？",
        session_id="p6_multi_dimensional_comparison",
        route_task="comparison",
        workflow_name="discovery_decision",
        expected_facets=["ordinal_reference", "comparison_targets", "kid_friendly", "price_compare"],
        initial_session_state={
            "last_recommendation_list": [
                {"shop_id": "shop_sc_05", "shop_name": "川味轩(知春路店)"},
                {"shop_id": "shop_007", "shop_name": "海底捞(牡丹园店)"},
            ]
        },
        target_resolution={"resolved": True, "source": "semantic_frame"},
        state_writebacks={"comparison_targets": True, "current_shop": False, "pending_clarification": False},
        golden_trace="multi_dimensional_comparison",
    ),
    _case(
        "single_shop_multi_facet",
        query="这家有券吗？现在开着吗？离我多远？",
        session_id="p6_single_shop_multi_facet",
        route_task="single_shop_query",
        workflow_name="deterministic_tool",
        expected_facets=["current_shop", "coupon", "open_now", "distance"],
        initial_session_state={
            "current_shop": {"shop_id": "shop_007", "shop_name": "海底捞(牡丹园店)"},
        },
        target_resolution={"resolved": True, "source": "current_shop"},
        state_writebacks={"current_shop": True, "last_recommendation_list": False, "comparison_targets": False},
        golden_trace="single_shop_multi_facet",
    ),
    _case(
        "reference_failure",
        turns=["第一家有券吗", "这家现在开着吗", "刚才那家人均多少", "第一家和第二家哪家更便宜"],
        session_id="p6_reference_failure",
        route_task="reference_failed",
        workflow_name="clarification_fallback",
        expected_facets=["ordinal_reference", "current_shop", "coupon", "open_now", "distance", "price_compare"],
        target_resolution={"resolved": False, "unresolved_reason": "missing_last_recommendation_list"},
        state_writebacks={"pending_clarification": True, "current_shop": False, "last_recommendation_list": False, "comparison_targets": False},
        golden_trace="reference_failure",
    ),
    _case(
        "recommendation_plus_reference_dependency",
        query="推荐附近火锅，第一家远吗",
        session_id="p6_recommendation_plus_reference_dependency",
        route_task="recommendation",
        workflow_name="discovery_decision",
        expected_facets=["nearby", "hotpot", "ordinal_reference", "distance"],
        initial_session_state={
            "user_location": DEFAULT_TEST_LOCATION,
            "last_recommendation_list": [
                {"shop_id": "shop_sc_05", "shop_name": "川味轩(知春路店)"},
                {"shop_id": "shop_007", "shop_name": "海底捞(牡丹园店)"},
            ]
        },
        target_resolution={"resolved": True, "source": "last_recommendation_list"},
        state_writebacks={"last_recommendation_list": True, "current_shop": False},
        golden_trace="recommendation_plus_reference_dependency",
    ),
    _case(
        "partial_tool_failure",
        query="这家有券吗？现在开着吗？离我多远？",
        session_id="p6_partial_tool_failure",
        route_task="single_shop_query",
        workflow_name="deterministic_tool",
        expected_facets=["current_shop", "coupon", "open_now", "distance"],
        initial_session_state={
            "current_shop": {"shop_id": "shop_sc_05", "shop_name": "川味轩(知春路店)"},
        },
        tool_failures={"get_coupon_list": "failed", "check_open_status": "unknown"},
        target_resolution={"resolved": True, "source": "current_shop"},
        state_writebacks={"current_shop": True, "last_recommendation_list": False, "comparison_targets": False},
        golden_trace="partial_tool_failure",
    ),
    _case(
        "empty_search_result",
        query="附近推荐几家适合约会、现在营业、最好有券、人均50以内的高评分日料",
        session_id="p6_empty_search_result",
        route_task="recommendation",
        workflow_name="discovery_decision",
        expected_facets=["nearby", "restaurant", "date_scene", "open_now", "coupon", "budget"],
        initial_session_state={"user_location": DEFAULT_TEST_LOCATION},
        empty_search_queries=["日料"],
        target_resolution={"resolved": False, "source": None},
        state_writebacks={"last_recommendation_list": False, "current_shop": False, "comparison_targets": False},
        golden_trace="empty_search_result",
    ),
    _case(
        "answer_verify_failure",
        query="这家有券吗？现在开着吗？离我多远？",
        session_id="p6_answer_verify_failure",
        route_task="single_shop_query",
        workflow_name="deterministic_tool",
        expected_facets=["current_shop", "coupon", "open_now", "distance"],
        initial_session_state={
            "current_shop": {"shop_id": "shop_sc_05", "shop_name": "川味轩(知春路店)"},
        },
        verify_should_fail=True,
        verify_failure_phrase="有券",
        target_resolution={"resolved": True, "source": "current_shop"},
        state_writebacks={"current_shop": False, "last_recommendation_list": False, "comparison_targets": False},
        golden_trace="answer_verify_failure",
        extra_expectations={"verification_fallback": True},
    ),
    _case(
        "clarification_resume",
        turns=["这家有券吗", "我说的是海底捞人民广场店"],
        session_id="p6_clarification_resume",
        route_task="reference_failed",
        workflow_name="deterministic_tool",
        expected_facets=["current_shop", "coupon"],
        target_resolution={"resolved": True, "source": "current_shop"},
        state_writebacks={"pending_clarification": False, "current_shop": True, "last_recommendation_list": False},
        golden_trace="clarification_resume",
    ),
    _case(
        "conflicting_multi_turn_preference",
        turns=["找几家安静适合聊天的咖啡店", "要热闹一点的"],
        session_id="p6_conflicting_multi_turn_preference",
        route_task="recommendation",
        workflow_name="discovery_decision",
        expected_facets=["coffee", "quiet", "lively"],
        target_resolution={"resolved": False, "source": None},
        state_writebacks={"last_recommendation_list": True, "current_shop": False, "comparison_targets": False},
        golden_trace="conflicting_multi_turn_preference",
        extra_expectations={"conflicting_facets": ["quiet", "lively"]},
    ),
]


P6_SMOKE_CASES: list[dict[str, Any]] = [
    _case(
        "all_tools_timeout_smoke",
        query="这家有券吗？现在开着吗？离我多远？",
        session_id="p6_all_tools_timeout_smoke",
        route_task="single_shop_query",
        workflow_name="deterministic_tool",
        expected_facets=["current_shop", "coupon", "open_now", "distance"],
        initial_session_state={
            "current_shop": {"shop_id": "shop_007", "shop_name": "海底捞(牡丹园店)"},
        },
        tool_failures={"get_coupon_list": "timeout", "check_open_status": "timeout", "get_distance_eta": "timeout"},
        target_resolution={"resolved": True, "source": "current_shop"},
        state_writebacks={"current_shop": True, "last_recommendation_list": False, "comparison_targets": False},
        golden_trace="all_tools_timeout_smoke",
    ),
    _case(
        "malformed_llm_output_smoke",
        query="LLM返回格式异常",
        session_id="p6_malformed_llm_output_smoke",
        route_task="recommendation",
        workflow_name="clarification_fallback",
        expected_facets=[],
        target_resolution={"resolved": False, "source": None},
        state_writebacks={"current_shop": False, "last_recommendation_list": False, "comparison_targets": False},
        golden_trace="malformed_llm_output_smoke",
        extra_expectations={"safe_route_only": True},
    ),
    _case(
        "contradictory_multi_turn_smoke",
        turns=["找几家安静适合聊天的咖啡店", "要热闹一点的"],
        session_id="p6_contradictory_multi_turn_smoke",
        route_task="recommendation",
        workflow_name="discovery_decision",
        expected_facets=["coffee", "quiet", "lively"],
        target_resolution={"resolved": False, "source": None},
        state_writebacks={"last_recommendation_list": True, "current_shop": False, "comparison_targets": False},
        golden_trace="conflicting_multi_turn_preference",
        extra_expectations={"conflict_recorded": True},
    ),
]


GOLDEN_TRACE_NAMES: list[str] = [case["golden_trace"] for case in P6_COMPLEX_QUERY_MATRIX_CASES] + [case["golden_trace"] for case in P6_SMOKE_CASES]


CASE_BY_NAME: dict[str, dict[str, Any]] = {case["name"]: case for case in P6_COMPLEX_QUERY_MATRIX_CASES + P6_SMOKE_CASES}
