from __future__ import annotations

from local_life_agent.planning.evidence.evidence_builder import build_evidence
from local_life_agent.target.shop_resolver import _legacy_resolve_shop


def test_legacy_resolve_shop_normalizes_null_location(monkeypatch):
    captured: dict[str, object] = {}

    def fake_dispatch(tool_name: str, kwargs: dict):
        captured["tool_name"] = tool_name
        captured["kwargs"] = dict(kwargs)
        return {
            "status": "NOT_FOUND",
            "reason": "no match",
            "shop": {},
            "candidates": [],
        }

    monkeypatch.setattr("local_life_agent.target.shop_resolver.dispatch_tool_call", fake_dispatch)

    _legacy_resolve_shop("牡丹园小火锅", location=None)

    assert captured["tool_name"] == "resolve_shop"
    assert captured["kwargs"]["location"] == {}


def test_distance_facet_reports_blocked_reason_when_location_missing():
    evidence = build_evidence(
        tool_results={
            "call_coupon": {
                "call_id": "call_coupon",
                "tool_name": "get_coupon_list",
                "shop_id": "shop_1",
                "result_status": "ok",
                "data": [{"title": "双人餐 88 元"}],
            },
            "call_open": {
                "call_id": "call_open",
                "tool_name": "check_open_status",
                "shop_id": "shop_1",
                "result_status": "ok",
                "data": {"open_status": "open"},
            },
        },
        resolved_target={
            "status": "RESOLVED",
            "resolved_shop": {"shop_id": "shop_1", "shop_name": "牡丹园小火锅"},
        },
        execution_plan={
            "task_type": "single_shop_query",
            "plan_id": "plan_distance",
            "facets": [
                {"name": "coupon", "group": "deal", "required": True},
                {"name": "open_status", "group": "status", "required": True},
                {"name": "distance", "group": "location", "required": True},
            ],
            "tool_calls": [
                {"call_id": "call_coupon", "facet": "coupon", "required": True, "target_shop_id": "shop_1"},
                {"call_id": "call_open", "facet": "open_status", "required": True, "target_shop_id": "shop_1"},
                {"call_id": "call_distance", "facet": "distance", "required": True, "target_shop_id": "shop_1"},
            ],
        },
        recommendation_candidates=[],
        comparison_targets=[],
        location={},
    )

    assert evidence["location"] == {}
    assert evidence["facet_statuses"]["coupon"] == "grounded"
    assert evidence["facet_statuses"]["open_status"] == "grounded"
    assert evidence["facet_statuses"]["distance"] == "unknown"
    assert evidence["facet_reasons"]["distance"] == "distance_tool_missing_or_location_unresolved"
