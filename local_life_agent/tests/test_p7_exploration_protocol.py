from __future__ import annotations

from typing import Any

from local_life_agent.domain.schemas import OrchestrationDecision
from local_life_agent.engine.workflow_registry import WORKFLOW_REGISTRY
from local_life_agent.engine.workflows import exploration_planning_workflow as exploration_workflow_module
from local_life_agent.planning.orchestration_router import route_orchestration
from local_life_agent.planning.plans.state_update_planner import plan_state_update
from local_life_agent.planning.shared import evidence_adapter
from local_life_agent.planning.shared.evidence_adapter import (
    build_answer_plan_from_evidence,
    build_evidence_pack_from_tool_results,
    normalize_tool_result_to_evidence,
)
from local_life_agent.tests.helpers.fake_backends import FakeLocalLifeBackend, install_fake_runtime
from local_life_agent.tests.fakes import mock_tools


def _decision(task_type: str, workflow_reason: str | None = None) -> OrchestrationDecision:
    return OrchestrationDecision(
        orchestration_pattern="exploration_planning",
        workflow_name="exploration_planning",
        workflow_reason=workflow_reason or f"{task_type} exploration",
        task_complexity="high",
        requires_tool=True,
        requires_clarification=False,
        response_mode="exploration_plan",
        confidence=0.88,
        missing_fields=[],
        next_action="run_workflow",
    )


def _state(
    raw_text: str,
    *,
    task_type: str = "date_plan",
    lat: float = 39.9609,
    lng: float = 116.3581,
    facets: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "trace_id": "trace_p7",
        "session_id": "session_p7",
        "turn_id": "turn_p7",
        "task_type": task_type,
        "raw_text": raw_text,
        "normalized_text": raw_text,
        "semantic_frame": {
            "task_type": task_type,
            "primary_task": task_type,
            "facets": facets
            or [
                {"name": "restaurant", "group": "category", "required": True},
                {"name": "coffee", "group": "category", "required": True},
                {"name": "date_scene", "group": "scene", "required": True},
                {"name": "travel_time", "group": "location", "required": False},
                {"name": "nearby", "group": "location", "required": False},
            ],
            "hard_constraints": {},
            "soft_preferences": {},
            "ranking_signals": {},
            "need_context": False,
        },
        "user_context": {"lat": lat, "lng": lng, "location_status": "provided", "location_source": "test"},
        "event_log": [],
    }


def _install_runtime(monkeypatch, backend: FakeLocalLifeBackend) -> None:
    install_fake_runtime(monkeypatch, backend)
    monkeypatch.setattr(exploration_workflow_module, "dispatch_tool_call", backend.dispatch_tool_call)
    monkeypatch.setattr(evidence_adapter, "verify_answer", backend.verify_answer)


def _shop_by_name(name: str) -> dict[str, Any]:
    for shop in mock_tools._all_shops():
        if str(shop.get("shop_name", "") or "") == name:
            return dict(shop)
    raise AssertionError(f"找不到测试商家: {name}")


def _patch_search_catalog(monkeypatch, backend: FakeLocalLifeBackend, *, empty_queries: set[str] | None = None) -> None:
    empty_queries = set(empty_queries or set())
    catalog = {
        "咖啡": _shop_by_name("瑞幸咖啡(北邮店)"),
        "餐厅": _shop_by_name("海底捞(牡丹园店)"),
        "海底捞": _shop_by_name("海底捞(牡丹园店)"),
        "川味轩": _shop_by_name("川味轩(知春路店)"),
    }

    def _search_shops(query: str, location: dict[str, Any] | None = None, limit: int | None = None) -> dict[str, Any]:
        compact = str(query or "").strip()
        if not compact or any(marker and marker in compact for marker in empty_queries):
            return {"success": True, "result_status": "empty", "data": [], "total": 0}
        items: list[dict[str, Any]] = []
        for marker, shop in catalog.items():
            if marker in compact:
                items.append(dict(shop))
        if not items:
            return {"success": True, "result_status": "empty", "data": [], "total": 0}
        if limit is not None:
            items = items[: max(0, int(limit))]
        return {"success": True, "result_status": "ok", "data": items, "total": len(items)}

    monkeypatch.setattr(backend, "search_shops", _search_shops)


def _dump(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return dict(value)
    return {}


def test_exploration_planning_router_runner_boundary(monkeypatch):
    backend = FakeLocalLifeBackend(scenario_name="p7_boundary")
    _install_runtime(monkeypatch, backend)
    _patch_search_catalog(monkeypatch, backend)
    monkeypatch.setattr(
        exploration_workflow_module,
        "verify_answer_plan",
        lambda answer, evidence, task_type: {"passed": True, "issues": [], "suggested_fix": "", "task_type": task_type},
    )

    state = _state(
        "五道口附近晚上约会怎么安排",
        task_type="date_plan",
        facets=[
            {"name": "restaurant", "group": "category", "required": True},
            {"name": "coffee", "group": "category", "required": True},
            {"name": "date_scene", "group": "scene", "required": True},
        ],
    )
    state["semantic_frame"] = {
        "task_type": "date_plan",
        "primary_task": "exploration",
        "workflow_hint": "exploration_planning",
        "scene": "date",
        "time": "evening",
        "location": {"text": "五道口附近", "location_name": "五道口附近"},
        "exploration_stages": [
            {"stage_id": "stage_1", "stage_type": "eat", "candidate_query": "餐厅", "order": 1, "required": True, "evidence_requirements": ["detail", "open_status", "distance"]},
            {"stage_id": "stage_2", "stage_type": "coffee", "candidate_query": "咖啡店", "order": 2, "required": True, "evidence_requirements": ["detail", "open_status", "distance"]},
        ],
        "hard_constraints": {},
        "soft_preferences": {},
        "ranking_signals": {},
        "need_context": False,
        "confidence": 0.92,
    }
    decision = route_orchestration(state)

    assert decision["workflow_name"] == "exploration_planning"
    assert decision["orchestration_pattern"] == "exploration_planning"
    assert decision["response_mode"] == "exploration_plan"
    registration = WORKFLOW_REGISTRY.lookup("exploration_planning")
    assert registration.entry_node == "response_subgraph"
    assert registration.callable_name == "run_exploration_planning_workflow"


def test_exploration_planning_retains_route_facets(monkeypatch):
    backend = FakeLocalLifeBackend(scenario_name="p7_facets")
    _install_runtime(monkeypatch, backend)
    _patch_search_catalog(monkeypatch, backend)
    monkeypatch.setattr(
        exploration_workflow_module,
        "verify_answer_plan",
        lambda answer, evidence, task_type: {"passed": True, "issues": [], "suggested_fix": "", "task_type": task_type},
    )

    result = exploration_workflow_module.run_exploration_planning_workflow(
        _state(
            "帮我看海底捞和川味轩哪个好",
            task_type="custom_exploration",
            facets=[
                {"name": "海底捞", "group": "category", "required": True},
                {"name": "川味轩", "group": "category", "required": True},
                {"name": "date_scene", "group": "scene", "required": True},
            ],
        ),
        _decision("custom_exploration"),
    )

    evidence = _dump(result["evidence_pack"])
    assert result["workflow_name"] == "exploration_planning"
    assert set(["海底捞", "川味轩", "date_scene"]).issubset(set(evidence.get("requested_facets", [])))
    assert any(facet in evidence.get("answerable_facets", []) for facet in ("海底捞", "川味轩"))
    assert evidence.get("owner") == "exploration_planning"


def test_exploration_tool_results_normalize_to_single_evidence_pack():
    evidence = build_evidence_pack_from_tool_results(
        workflow_name="exploration_planning",
        owner="exploration_planning",
        semantic_facets=[
            {"name": "restaurant", "group": "category", "required": True},
            {"name": "coffee", "group": "category", "required": True},
            {"name": "date_scene", "group": "scene", "required": True},
        ],
        location_context={"lat": 39.9609, "lng": 116.3581},
        subgoals=[
            {
                "subgoal_id": "subgoal_1",
                "kind": "restaurant",
                "query": "餐厅",
                "sequence_order": 1,
                "selected_candidate": {"shop_id": "shop_r_1", "shop_name": "餐厅A", "rating": 4.8, "distance_km": 1.1, "eta_minutes": 9},
                "search_result": {
                    "call_id": "search_1",
                    "tool_name": "search_shops",
                    "success": True,
                    "result_status": "ok",
                    "data": [{"shop_id": "shop_r_1", "shop_name": "餐厅A", "rating": 4.8, "distance_km": 1.1, "eta_minutes": 9}],
                },
                "tool_results": {
                    "get_shop_detail": {
                        "call_id": "detail_1",
                        "shop_id": "shop_r_1",
                        "tool_name": "get_shop_detail",
                        "success": True,
                        "result_status": "ok",
                        "data": {"shop_id": "shop_r_1", "shop_name": "餐厅A", "avg_price": 88, "rating": 4.8},
                    }
                },
            },
            {
                "subgoal_id": "subgoal_2",
                "kind": "coffee",
                "query": "咖啡店",
                "sequence_order": 2,
                "selected_candidate": None,
                "search_result": {
                    "call_id": "search_2",
                    "tool_name": "search_shops",
                    "success": True,
                    "result_status": "empty",
                    "data": [],
                },
                "tool_results": {},
            },
        ],
    )

    assert evidence.owner == "exploration_planning"
    assert evidence.answerable_facets == ["restaurant"]
    assert set(evidence.unknown_facets) == {"coffee", "date_scene", "travel_time", "nearby"}
    assert evidence.failed_facets == []
    assert evidence.last_recommendation_list[0]["shop_id"] == "shop_r_1"
    assert evidence.evidence_items[0].subgoal_id == "subgoal_1"
    assert evidence.evidence_items[0].route_step == "1"

    answer_plan = build_answer_plan_from_evidence(
        task_type="date_plan",
        evidence_pack=evidence,
        exploration_plan={"subgoals": evidence.route_steps},
    )
    assert answer_plan.answer_type == "exploration_plan"
    assert "coffee" in answer_plan.unknown_facets
    assert answer_plan.required_disclaimers


def test_exploration_partial_success_degrades_without_invention(monkeypatch):
    backend = FakeLocalLifeBackend(scenario_name="p7_partial", empty_search_queries={"咖啡店"})
    _install_runtime(monkeypatch, backend)
    _patch_search_catalog(monkeypatch, backend, empty_queries={"咖啡"})
    monkeypatch.setattr(
        exploration_workflow_module,
        "verify_answer_plan",
        lambda answer, evidence, task_type: {"passed": True, "issues": [], "suggested_fix": "", "task_type": task_type},
    )

    result = exploration_workflow_module.run_exploration_planning_workflow(
        _state(
            "先吃饭再去喝咖啡",
            task_type="custom_exploration",
            facets=[
                {"name": "海底捞", "group": "category", "required": True},
                {"name": "咖啡", "group": "category", "required": True},
                {"name": "date_scene", "group": "scene", "required": True},
            ],
        ),
        _decision("custom_exploration"),
    )

    assert result["workflow_name"] == "clarification_fallback"
    assert result["response_mode"] in {"clarify", "fallback"}
    assert "pending_clarification" in result
    assert "workflow_clarification_request" in result
    assert "海底捞" not in result.get("final_response", "")
    assert "咖啡" not in result.get("final_response", "")


def test_exploration_tool_failure_marks_failed_facets_and_blocks_polluted_writeback(monkeypatch):
    backend = FakeLocalLifeBackend(
        scenario_name="p7_failure",
        tool_failures={"get_distance_eta": "failed"},
    )
    _install_runtime(monkeypatch, backend)
    _patch_search_catalog(monkeypatch, backend)
    monkeypatch.setattr(
        exploration_workflow_module,
        "verify_answer_plan",
        lambda answer, evidence, task_type: {"passed": True, "issues": [], "suggested_fix": "", "task_type": task_type},
    )

    result = exploration_workflow_module.run_exploration_planning_workflow(
        _state(
            "先吃饭再看营业和距离",
            task_type="custom_exploration",
            facets=[
                {"name": "海底捞", "group": "category", "required": True},
                {"name": "川味轩", "group": "category", "required": True},
                {"name": "travel_time", "group": "location", "required": False},
            ],
        ),
        _decision("custom_exploration"),
    )

    assert result["workflow_name"] == "clarification_fallback"
    assert result["response_mode"] in {"clarify", "fallback"}
    assert "pending_clarification" in result
    assert "workflow_clarification_request" in result
    assert "state_update_plan_preview" not in result
    assert "失败" not in result.get("final_response", "")


def test_exploration_answer_verify_failure_rewrites_or_fallbacks(monkeypatch):
    backend = FakeLocalLifeBackend(scenario_name="p7_verify")
    _install_runtime(monkeypatch, backend)
    _patch_search_catalog(monkeypatch, backend)
    monkeypatch.setattr(
        exploration_workflow_module,
        "verify_answer_plan",
        lambda answer, evidence, task_type: {
            "passed": False,
            "issues": ["unsupported_claim"],
            "suggested_fix": "remove unsupported claim",
            "task_type": task_type,
        },
    )

    result = exploration_workflow_module.run_exploration_planning_workflow(
        _state(
            "先吃饭再看营业和距离",
            task_type="custom_exploration",
            facets=[
                {"name": "海底捞", "group": "category", "required": True},
                {"name": "川味轩", "group": "category", "required": True},
                {"name": "travel_time", "group": "location", "required": False},
            ],
        ),
        _decision("custom_exploration"),
    )

    assert result["workflow_name"] == "clarification_fallback"
    assert result["response_mode"] in {"clarify", "fallback"}
    assert "pending_clarification" in result
    assert "workflow_clarification_request" in result


def test_exploration_state_update_plan_uses_shared_writeback_rules():
    directive = plan_state_update(
        {
            "workflow_name": "exploration_planning",
            "task_type": "date_plan",
            "last_recommendation_list": [{"shop_id": "shop_r_1", "shop_name": "餐厅A"}],
            "evidence_pack": {
                "owner": "exploration_planning",
                "last_recommendation_list": [{"shop_id": "shop_r_1", "shop_name": "餐厅A"}],
                "evidence_items": [
                    {"evidence_id": "ev_1", "shop_id": "shop_r_1", "facet": "restaurant", "status": "answerable"}
                ],
            },
            "user_location": {"lat": 39.96, "lng": 116.36, "location_name": "北邮"},
        },
        "date_plan",
        "",
    )

    assert "last_recommendation_list" not in directive["set_fields"]
    assert "last_recommendation_list" in directive["clear_fields"]
    assert "current_shop" in directive["clear_fields"]
    assert "pending_clarification" in directive["clear_fields"]

    blocked = plan_state_update(
        {
            "workflow_name": "exploration_planning",
            "task_type": "date_plan",
            "tool_results": {"call_1": {"tool_name": "get_distance_eta", "result_status": "failed", "success": False}},
            "evidence_pack": {
                "owner": "exploration_planning",
                "evidence_items": [
                    {"evidence_id": "ev_1", "shop_id": "shop_r_1", "facet": "restaurant", "status": "answerable"}
                ],
            },
        },
        "date_plan",
        "",
    )

    assert blocked["set_fields"] == {}
    assert blocked["clear_fields"] == []


def test_p7_does_not_introduce_exploration_subgraph_or_workflow_merge():
    registration = WORKFLOW_REGISTRY.lookup("exploration_planning")
    assert registration.entry_node == "response_subgraph"
    assert registration.callable_name == "run_exploration_planning_workflow"
    source = (exploration_workflow_module.__file__ or "")
    with open(source, "r", encoding="utf-8") as handle:
        source_text = handle.read()
    assert "exploration_planning_subgraph" not in source_text
    assert "workflow_names" not in source_text
    assert "final_responses" not in source_text
    assert "run_clarification_fallback_workflow(" not in source_text
