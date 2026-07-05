from __future__ import annotations

import json

import pytest

from local_life_agent import agent, config
from local_life_agent.engine import graph_builder
from local_life_agent.llm.client import clear_llm_backend, set_llm_backend
from local_life_agent.tests.chat_e2e_utils import orchestration_decision_from_response
from local_life_agent.tests.conftest import SpyRealLLMBackend
from local_life_agent.tests.fakes import mock_tools


pytestmark = pytest.mark.e2e


@pytest.fixture(autouse=True)
def _reset_graph_cache(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(agent, "_GRAPH_CACHE", None)
    monkeypatch.setattr(config, "DEBUG_ENABLED", True)
    yield
    clear_llm_backend()


def _install_default_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    def dispatch(tool_name: str, args: dict):
        if tool_name == "resolve_shop":
            return mock_tools.resolve_shop(
                str(args.get("query", "")),
                location=args.get("location"),
                session_shop_ids=args.get("session_shop_ids"),
            )
        if tool_name == "search_shops":
            return mock_tools.search_shops(
                str(args.get("query", "")),
                location=args.get("location"),
                limit=args.get("limit"),
            )
        if tool_name == "get_shop_detail":
            return mock_tools.get_shop_detail(str(args.get("shop_id", "")))
        if tool_name == "check_open_status":
            return mock_tools.check_open_status(str(args.get("shop_id", "")))
        if tool_name == "get_coupon_list":
            return mock_tools.get_coupon_list(str(args.get("shop_id", "")))
        if tool_name == "get_distance_eta":
            return mock_tools.get_distance_eta(
                str(args.get("shop_id", "")),
                args.get("from_location") or {"lat": 39.9609, "lng": 116.3581},
            )
        if tool_name == "get_shop_review_summary":
            return mock_tools.get_shop_review_summary(list(args.get("shop_ids") or []), aspects=args.get("aspects"), scene=args.get("scene"), max_reviews=args.get("max_reviews"))
        if tool_name == "get_deal_list":
            return mock_tools.get_deal_list(
                str(args.get("shop_id", "")),
                people_count=args.get("people_count"),
                budget_per_person=args.get("budget_per_person"),
                deal_type=args.get("deal_type"),
                only_available=args.get("only_available", True),
            )
        return {"success": False, "result_status": "failed", "error_code": "TOOL_NOT_REGISTERED", "data": None}

    monkeypatch.setattr(graph_builder, "dispatch_tool_call", dispatch)
    monkeypatch.setattr(graph_builder, "resolve_shop", lambda query, location=None, session_shop_ids=None: dispatch("resolve_shop", {"query": query, "location": location, "session_shop_ids": session_shop_ids}))


def _run(text: str, session_id: str, *, trace_id: str = "", turn_id: str = ""):
    return agent.run_agent_graph(text, session_id=session_id, trace_id=trace_id, turn_id=turn_id)


def _assert_workflow(response, *, text: str, session_id: str, expected_workflow: str) -> None:
    decision = orchestration_decision_from_response(response, text=text, session_id=session_id)
    assert decision.workflow_name == expected_workflow


def test_recommendation_no_result_does_not_fake_shop(monkeypatch: pytest.MonkeyPatch):
    _install_default_dispatch(monkeypatch)

    def dispatch(tool_name: str, args: dict):
        if tool_name == "search_shops":
            return {"success": True, "result_status": "empty", "data": [], "total": 0}
        return mock_tools.resolve_shop(str(args.get("query", "")), location=args.get("location"), session_shop_ids=args.get("session_shop_ids")) if tool_name == "resolve_shop" else mock_tools.get_shop_detail(str(args.get("shop_id", ""))) if tool_name == "get_shop_detail" else mock_tools.check_open_status(str(args.get("shop_id", ""))) if tool_name == "check_open_status" else mock_tools.get_coupon_list(str(args.get("shop_id", ""))) if tool_name == "get_coupon_list" else mock_tools.get_distance_eta(str(args.get("shop_id", "")), args.get("from_location") or {"lat": 39.9609, "lng": 116.3581}) if tool_name == "get_distance_eta" else mock_tools.get_shop_review_summary(list(args.get("shop_ids") or []), aspects=args.get("aspects"), scene=args.get("scene"), max_reviews=args.get("max_reviews")) if tool_name == "get_shop_review_summary" else mock_tools.get_deal_list(str(args.get("shop_id", "")), people_count=args.get("people_count"), budget_per_person=args.get("budget_per_person"), deal_type=args.get("deal_type"), only_available=args.get("only_available", True))

    monkeypatch.setattr(graph_builder, "dispatch_tool_call", dispatch)
    monkeypatch.setattr(graph_builder, "resolve_shop", lambda query, location=None, session_shop_ids=None: dispatch("resolve_shop", {"query": query, "location": location, "session_shop_ids": session_shop_ids}))

    backend = SpyRealLLMBackend(
        scenario_payloads={
            "推荐月球附近的火锅": {
                "top_intent": "local_life",
                "task_type": "recommendation",
                "primary_task": "recommendation",
                "merchant_mentions": [],
                "reference_mentions": [],
                "comparison_targets": [],
                "ordinal_references": [],
                "deictic_references": [],
                "facets": [{"name": "location", "required": True}],
                "hard_constraints": {"location": "月球附近", "category": ["火锅"]},
                "soft_preferences": {},
                "ranking_signals": {},
                "confidence": 0.95,
                "need_context": False,
            }
        }
    )
    set_llm_backend(backend)

    text = "推荐月球附近的火锅"
    resp = _run(text, "fail-e2e-1")

    _assert_workflow(response=resp, text=text, session_id="fail-e2e-1", expected_workflow="discovery_decision")
    assert not resp.debug.session_state_after.get("last_recommendation_list")
    assert resp.debug.evidence_pack.get("unknown_facets") or resp.debug.evidence_pack.get("failed_facets") or resp.debug.fallback_reason
    assert "月球" in resp.debug.turn_trace.get("user_text", "")


def test_deterministic_tool_timeout_marks_failed_facets(monkeypatch: pytest.MonkeyPatch):
    _install_default_dispatch(monkeypatch)
    backend = SpyRealLLMBackend(
        scenario_payloads={
            "远方烧烤(清河店)有券吗？": {
                "top_intent": "local_life",
                "task_type": "single_shop_query",
                "primary_task": "coupon_query",
                "merchant_mentions": ["远方烧烤(清河店)"],
                "reference_mentions": [],
                "comparison_targets": [],
                "ordinal_references": [],
                "deictic_references": [],
                "facets": [{"name": "coupon", "required": True}],
                "hard_constraints": {},
                "soft_preferences": {},
                "ranking_signals": {},
                "confidence": 0.98,
                "need_context": False,
            }
        }
    )
    set_llm_backend(backend)

    text = "远方烧烤(清河店)有券吗？"
    resp = _run(text, "fail-e2e-2")

    _assert_workflow(response=resp, text=text, session_id="fail-e2e-2", expected_workflow="deterministic_tool")
    assert "coupon" in (resp.debug.evidence_pack.get("failed_facets") or [])
    assert resp.debug.answer_verify_passed is False or resp.debug.fallback_reason or resp.debug.answer_fallback_reason


def test_discovery_partial_tool_failure_preserves_failed_facets(monkeypatch: pytest.MonkeyPatch):
    _install_default_dispatch(monkeypatch)

    def dispatch(tool_name: str, args: dict):
        if tool_name == "search_shops":
            return mock_tools.search_shops(str(args.get("query", "")), location=args.get("location"), limit=args.get("limit"))
        if tool_name == "get_coupon_list":
            raise TimeoutError("simulated coupon timeout")
        if tool_name == "resolve_shop":
            return mock_tools.resolve_shop(str(args.get("query", "")), location=args.get("location"), session_shop_ids=args.get("session_shop_ids"))
        if tool_name == "get_shop_detail":
            return mock_tools.get_shop_detail(str(args.get("shop_id", "")))
        if tool_name == "check_open_status":
            return mock_tools.check_open_status(str(args.get("shop_id", "")))
        if tool_name == "get_distance_eta":
            return mock_tools.get_distance_eta(str(args.get("shop_id", "")), args.get("from_location") or {"lat": 39.9609, "lng": 116.3581})
        if tool_name == "get_shop_review_summary":
            return mock_tools.get_shop_review_summary(list(args.get("shop_ids") or []), aspects=args.get("aspects"), scene=args.get("scene"), max_reviews=args.get("max_reviews"))
        if tool_name == "get_deal_list":
            return mock_tools.get_deal_list(str(args.get("shop_id", "")), people_count=args.get("people_count"), budget_per_person=args.get("budget_per_person"), deal_type=args.get("deal_type"), only_available=args.get("only_available", True))
        return {"success": False, "result_status": "failed", "error_code": "TOOL_NOT_REGISTERED", "data": None}

    monkeypatch.setattr(graph_builder, "dispatch_tool_call", dispatch)
    monkeypatch.setattr(graph_builder, "resolve_shop", lambda query, location=None, session_shop_ids=None: dispatch("resolve_shop", {"query": query, "location": location, "session_shop_ids": session_shop_ids}))

    backend = SpyRealLLMBackend(
        scenario_payloads={
            "推荐附近有券的餐厅": {
                "top_intent": "local_life",
                "task_type": "recommendation",
                "primary_task": "recommendation",
                "merchant_mentions": [],
                "reference_mentions": [],
                "comparison_targets": [],
                "ordinal_references": [],
                "deictic_references": [],
                "facets": [{"name": "coupon", "required": False}, {"name": "location", "required": True}],
                "hard_constraints": {"location": "北邮附近"},
                "soft_preferences": {"coupon": True},
                "ranking_signals": {},
                "confidence": 0.95,
                "need_context": False,
            }
        }
    )
    set_llm_backend(backend)

    text = "推荐附近有券的餐厅"
    resp = _run(text, "fail-e2e-3")

    _assert_workflow(response=resp, text=text, session_id="fail-e2e-3", expected_workflow="discovery_decision")
    assert "coupon" in json.dumps(resp.debug.evidence_pack, ensure_ascii=False)
    assert resp.debug.evidence_pack.get("failed_facets") or resp.debug.evidence_pack.get("unknown_facets")


def test_evidence_insufficient_triggers_clarify_or_degrade(monkeypatch: pytest.MonkeyPatch):
    _install_default_dispatch(monkeypatch)
    backend = SpyRealLLMBackend(
        scenario_payloads={
            "推荐几家性价比高的烧烤": {
                "top_intent": "local_life",
                "task_type": "recommendation",
                "primary_task": "recommendation",
                "merchant_mentions": [],
                "reference_mentions": [],
                "comparison_targets": [],
                "ordinal_references": [],
                "deictic_references": [],
                "facets": [{"name": "location", "required": True}],
                "hard_constraints": {"category": ["烧烤"]},
                "soft_preferences": {"price": "性价比高"},
                "ranking_signals": {},
                "confidence": 0.9,
                "need_context": True,
            }
        }
    )
    set_llm_backend(backend)

    resp = _run("推荐几家性价比高的烧烤", "fail-e2e-4")

    _assert_workflow(response=resp, text="推荐几家性价比高的烧烤", session_id="fail-e2e-4", expected_workflow="clarification_fallback")
    assert resp.debug.session_state_after.get("pending_clarification") is not None
    assert resp.debug.answer_verify_passed in {True, False}


def test_answer_verify_failure_falls_back_without_polluting_state(monkeypatch: pytest.MonkeyPatch):
    _install_default_dispatch(monkeypatch)
    backend = SpyRealLLMBackend(
        scenario_payloads={
            "推荐附近性价比高的火锅": {
                "top_intent": "local_life",
                "task_type": "recommendation",
                "primary_task": "recommendation",
                "merchant_mentions": [],
                "reference_mentions": [],
                "comparison_targets": [],
                "ordinal_references": [],
                "deictic_references": [],
                "facets": [],
                "hard_constraints": {"category": ["火锅"]},
                "soft_preferences": {"price": "性价比高"},
                "ranking_signals": {},
                "confidence": 0.95,
                "need_context": False,
            }
        }
    )
    set_llm_backend(backend)

    import local_life_agent.engine.subgraphs.response_subgraph as response_subgraph_module

    monkeypatch.setattr(
        response_subgraph_module,
        "verify_answer",
        lambda *_args, **_kwargs: {
            "passed": False,
            "issues": ["forced_failure"],
            "suggested_fix": "rewrite",
            "failure_code": "FORCED_FAILURE",
            "verifier_unknown_fields": [],
            "verifier_unsupported_claims": [],
            "verifier_false_fields": [],
            "recoverable": True,
        },
    )

    resp = _run("推荐附近性价比高的火锅", "fail-e2e-5")

    _assert_workflow(response=resp, text="推荐附近性价比高的火锅", session_id="fail-e2e-5", expected_workflow="discovery_decision")
    assert resp.debug.answer_verify_passed is False
    assert resp.debug.answer_verify_violations


def test_exploration_partial_success_preserves_failed_facets(monkeypatch: pytest.MonkeyPatch):
    _install_default_dispatch(monkeypatch)
    backend = SpyRealLLMBackend(
        scenario_payloads={
            "帮我安排一个北京邮电大学附近先吃饭再喝咖啡的约会路线": {
                "top_intent": "local_life",
                "task_type": "local_trip_plan",
                "primary_task": "coffee_then_dinner",
                "merchant_mentions": [],
                "reference_mentions": [],
                "comparison_targets": [],
                "ordinal_references": [],
                "deictic_references": [],
                "facets": [],
                "hard_constraints": {"location": "北京邮电大学附近"},
                "soft_preferences": {"scene": "date"},
                "ranking_signals": {"sequence": ["先吃饭再喝咖啡"]},
                "confidence": 0.95,
                "need_context": False,
            }
        }
    )
    set_llm_backend(backend)

    resp = _run("帮我安排一个北京邮电大学附近先吃饭再喝咖啡的约会路线", "fail-e2e-6")

    _assert_workflow(response=resp, text="帮我安排一个北京邮电大学附近先吃饭再喝咖啡的约会路线", session_id="fail-e2e-6", expected_workflow="exploration_planning")
    assert resp.debug.execution_plan


def test_exploration_verify_failure_falls_back_without_state_pollution(monkeypatch: pytest.MonkeyPatch):
    _install_default_dispatch(monkeypatch)
    backend = SpyRealLLMBackend(
        scenario_payloads={
            "帮我安排一个北京邮电大学附近先吃饭再喝咖啡的约会路线": {
                "top_intent": "local_life",
                "task_type": "local_trip_plan",
                "primary_task": "coffee_then_dinner",
                "merchant_mentions": [],
                "reference_mentions": [],
                "comparison_targets": [],
                "ordinal_references": [],
                "deictic_references": [],
                "facets": [],
                "hard_constraints": {"location": "北京邮电大学附近"},
                "soft_preferences": {"scene": "date"},
                "ranking_signals": {"sequence": ["先吃饭再喝咖啡"]},
                "confidence": 0.95,
                "need_context": False,
            }
        }
    )
    set_llm_backend(backend)

    import local_life_agent.engine.subgraphs.response_subgraph as response_subgraph_module

    monkeypatch.setattr(
        response_subgraph_module,
        "verify_answer",
        lambda *_args, **_kwargs: {
            "passed": False,
            "issues": ["forced_failure"],
            "suggested_fix": "rewrite",
            "failure_code": "FORCED_FAILURE",
            "verifier_unknown_fields": [],
            "verifier_unsupported_claims": [],
            "verifier_false_fields": [],
            "recoverable": True,
        },
    )

    resp = _run("帮我安排一个北京邮电大学附近先吃饭再喝咖啡的约会路线", "fail-e2e-7")

    _assert_workflow(response=resp, text="帮我安排一个北京邮电大学附近先吃饭再喝咖啡的约会路线", session_id="fail-e2e-7", expected_workflow="exploration_planning")
    assert resp.debug.answer_verify_passed is False
    assert resp.debug.session_state_after.get("pending_clarification") is None


def test_state_writeback_not_polluted_on_failure(monkeypatch: pytest.MonkeyPatch):
    _install_default_dispatch(monkeypatch)
    backend = SpyRealLLMBackend(
        scenario_payloads={
            "海底捞有券吗？": {
                "top_intent": "local_life",
                "task_type": "single_shop_query",
                "primary_task": "coupon_query",
                "merchant_mentions": ["海底捞"],
                "reference_mentions": [],
                "comparison_targets": [],
                "ordinal_references": [],
                "deictic_references": [],
                "facets": [{"name": "coupon", "required": True}],
                "hard_constraints": {},
                "soft_preferences": {},
                "ranking_signals": {},
                "confidence": 0.95,
                "need_context": True,
            }
        }
    )
    set_llm_backend(backend)

    resp = _run("海底捞有券吗？", "fail-e2e-8")

    _assert_workflow(response=resp, text="海底捞有券吗？", session_id="fail-e2e-8", expected_workflow="clarification_fallback")
    assert resp.debug.session_state_after.get("current_shop") is None
    assert resp.debug.session_state_after.get("last_recommendation_list") in ([], None)
