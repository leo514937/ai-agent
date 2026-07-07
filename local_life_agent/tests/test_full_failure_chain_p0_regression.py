from __future__ import annotations

from typing import Any

from local_life_agent.domain.candidate import CandidateSource, CandidateSpec, GoalType, LocalLifeGoalDraft
from local_life_agent.domain.goal import GoalPlan
from local_life_agent.planning.decision.decision_planner import plan_decision_with_llm
from local_life_agent.target.candidate_resolver import CandidateResolver
from local_life_agent.target.reference_resolver import _infer_comparison_mentions_from_text
from local_life_agent.tools.db_tools import get_distance_eta, search_shops


def test_value_for_money_text_does_not_generate_comparison_mentions() -> None:
    text = "推荐北京邮电大学附近的火锅或烧烤，要性价比高的"

    mentions = _infer_comparison_mentions_from_text(text)

    assert mentions == []


def test_search_shops_geocodes_known_location_for_distance_sorting() -> None:
    result = search_shops("火锅", location={"location_name": "北京邮电大学"}, limit=3)

    assert result["success"] is True
    assert result["result_status"] == "ok"
    assert result["data"], "should return at least one shop"
    assert any(item.get("distance_km") is not None for item in result["data"])


def test_get_distance_eta_geocodes_known_location() -> None:
    result = get_distance_eta("shop_sc_01", {"location_name": "北京邮电大学"})

    assert result["success"] is True
    assert result["result_status"] == "ok"
    assert result["data"]["distance_km"] is not None


def test_candidate_resolver_discovery_uses_state_location(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_search(query: str, **kw: Any) -> dict[str, Any]:
        captured["query"] = query
        captured["kwargs"] = dict(kw)
        return {
            "success": True,
            "result_status": "ok",
            "data": [
                {"shop_id": "shop_1", "shop_name": "测试店", "rating": 4.9, "distance_km": 1.2},
            ],
        }

    resolver = CandidateResolver(search_shops_fn=fake_search)
    goal = LocalLifeGoalDraft(goal_type=GoalType.RECOMMENDATION, candidate_source=CandidateSource.DISCOVERY, candidate_limit=1)
    spec = CandidateSpec(source=CandidateSource.DISCOVERY, query="火锅", limit=1)

    result = resolver.resolve_discovery(goal, spec, state={"user_location": {"location_name": "北京邮电大学"}})

    assert result.status.name == "RESOLVED"
    assert captured["kwargs"]["location"]["lat"] is not None
    assert captured["kwargs"]["location"]["lng"] is not None


def test_llm_decision_planner_falls_back_when_llm_returns_unsupported() -> None:
    goal = GoalPlan(goal_type="recommendation", goal_summary="推荐附近火锅")
    candidate_set = {"candidates": [{"shop_id": "shop_1", "shop_name": "测试店"}]}
    evidence_pack = {
        "target_shop_ids": ["shop_1"],
        "facet_results": [
            {"facet": "coupon", "status": "ok", "result_status": "ok"},
            {"facet": "open_status", "status": "ok", "result_status": "ok"},
        ],
        "evidence_items": [
            {
                "evidence_id": "evi_1",
                "shop_id": "shop_1",
                "facet": "coupon",
                "result_status": "ok",
                "value": [{"title": "满50减12"}],
            }
        ],
    }

    def fake_llm_call(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {
            "ok": True,
            "content": {
                "decision_type": "unsupported",
                "goal_id": "goal_1",
                "candidates": [],
                "answerable_facets": [],
                "unknown_facets": [],
                "failed_facets": [],
                "decision_context": {},
                "claims": [],
                "caveats": [],
                "forbidden_claims": [],
                "must_mention_unknowns": [],
                "semantic_frame": {},
                "semantic_parse_source": "",
                "grounding_status": "",
                "missing_slot_type": "",
                "router_policy_decision": {},
                "router_policy_conflicts": [],
                "exploration_stages": [],
                "stage_queries": [],
                "stage_evidence_requirements": [],
                "stage_statuses": [],
                "scene": "",
                "time": "",
                "location": {},
                "facet_statuses": {},
                "grounded_facts": {},
                "facet_reasons": {},
                "evidence_status": "grounded",
                "comparison_support_status": "",
                "ranking_preserved": True,
                "unsupported_reasons": [],
                "unknown_fields": [],
                "failed_tools": [],
                "partial_fields": [],
                "evidence_review_result": {},
                "answer_verify_result": {},
                "decision_source": "llm_decision_planner",
                "decision_confidence": 0.0,
                "claim_bindings": [],
                "winner_evidence_refs": [],
                "missing_fields": [],
                "next_action": "",
                "reason": "",
                "decision_reason": "",
                "insufficient_evidence": True,
            },
            "raw": "{}",
            "error_code": "",
            "error_message": "",
            "llm_backend": "fake",
        }

    plan, meta = plan_decision_with_llm(
        goal_plan=goal,
        candidate_set=candidate_set,
        evidence_pack=evidence_pack,
        llm_call=fake_llm_call,
        strict=False,
    )

    assert plan is not None
    assert plan.decision_type.value != "unsupported"
    assert "shop_1" in plan.candidates
    assert meta["error_code"] == "DECISION_PLANNER_UNSUPPORTED_FALLBACK"
