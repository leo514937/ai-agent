from __future__ import annotations

from local_life_agent.app import _user_context_from_client_context
from local_life_agent.domain.candidate import CandidateSource, GoalType, LocalLifeGoalDraft
from local_life_agent.domain.goal import GoalPlan
from local_life_agent.domain.schemas import AnswerPlan
from local_life_agent.engine.subgraphs import planning_subgraph as planning_module
from local_life_agent.engine.subgraphs.response_subgraph import _h_answer_generate
from local_life_agent.planning.evidence.evidence_review import review_evidence
from local_life_agent.semantic.intent_parser import _normalize_semantic_payload
from local_life_agent.tools.db_tools import search_shops


def test_client_context_location_is_promoted_to_user_context_and_user_location() -> None:
    user_context, user_location = _user_context_from_client_context(
        {
            "city": "北京",
            "location": {"location_name": "五道口附近"},
        }
    )

    assert user_context is not None
    assert user_context.location_name == "五道口附近"
    assert user_context.location_source == "client_context"
    assert user_location["city"] == "北京"
    assert user_location["location_name"] == "五道口附近"


def test_search_shops_requires_location_for_nearby_query() -> None:
    result = search_shops("附近火锅", location={}, limit=5)

    assert result["success"] is False
    assert result["result_status"] == "failed"
    assert result["error_code"] == "LOCATION_REQUIRED"


def test_planning_subgraph_clarifies_nearby_without_location(monkeypatch) -> None:
    def fake_goal_planner(state):
        return {
            "goal_plan": GoalPlan(
                goal_type="recommendation",
                goal_summary="推荐附近好吃的",
                candidate_source="discovery",
                required_facets=["nearby"],
            ),
            "local_life_goal_draft": LocalLifeGoalDraft(
                goal_type=GoalType.RECOMMENDATION,
                candidate_source=CandidateSource.DISCOVERY,
                required_facets=["nearby"],
            ),
            "semantic_frame": state["semantic_frame"],
        }

    def fake_goal_review(_state):
        return {
            "goal_review_result": {
                "stage": "goal_review",
                "status": "enough",
                "next_action": "FINISH",
                "reason": "ok",
            }
        }

    def fail_target_resolve(_state):
        raise AssertionError("target_resolve should not run when location is missing")

    monkeypatch.setattr(planning_module, "_h_goal_planner", fake_goal_planner)
    monkeypatch.setattr(planning_module, "_h_goal_review", fake_goal_review)
    monkeypatch.setattr(planning_module, "_h_target_resolve", fail_target_resolve)

    state = {
        "raw_text": "推荐附近有什么好吃的",
        "normalized_text": "推荐附近有什么好吃的",
        "task_type": "recommendation",
        "semantic_frame": {
            "task_type": "recommendation",
            "missing_slot_type": "",
            "soft_preferences": {"nearby_preferred": True},
            "facets": [{"name": "nearby", "required": True}],
            "location": {},
        },
        "event_log": [],
    }

    result = planning_module.h_planning_subgraph(state)

    assert result["planning_route"] == "clarify"
    assert result["response_mode"] == "clarify"
    assert result.get("pending_clarification") is not None
    assert "target_resolve" not in [item.get("node") for item in result.get("event_log", []) if isinstance(item, dict)]


def test_evidence_review_clarifies_location_required_failure() -> None:
    goal = LocalLifeGoalDraft(
        goal_type=GoalType.RECOMMENDATION,
        candidate_source=CandidateSource.DISCOVERY,
        required_facets=["distance"],
    )
    review = review_evidence(
        goal,
        {
            "facet_results": [
                {
                    "facet": "distance",
                    "tool_name": "search_shops",
                    "result_status": "failed",
                    "error_code": "LOCATION_REQUIRED",
                    "error_message": "need location",
                }
            ],
            "missing_slot_type": "",
            "location": {},
        },
        tool_results={
            "call_search_shops": {
                "tool_name": "search_shops",
                "success": False,
                "result_status": "failed",
                "error_code": "LOCATION_REQUIRED",
                "error_message": "need location",
            }
        },
    )

    assert review.next_action.value == "CLARIFY"
    assert review.action.value == "clarify"
    assert review.clarification_reason == "need_user_location"


def test_semantic_payload_normalizes_known_preference_shapes() -> None:
    normalized = _normalize_semantic_payload(
        {
            "preferences": {"nearby_preferred": True},
            "ranking_policy": "",
        },
        top_intent="local_life",
    )
    assert normalized["preferences"] == [{"type": "nearby_preferred", "value": True}]
    assert normalized["ranking_policy"] is None

    normalized = _normalize_semantic_payload(
        {
            "preferences": ["value_for_money"],
            "ranking_policy": [],
        },
        top_intent="local_life",
    )
    assert normalized["preferences"] == [{"type": "value_for_money"}]
    assert normalized["ranking_policy"] is None


def test_answer_generate_drops_diagnostic_fallback_for_clarification(monkeypatch) -> None:
    def fake_generate_answer(*_args, metadata_out=None, **_kwargs):
        metadata_out["answer_source"] = "deterministic_clarification"
        metadata_out["fallback_reason"] = ""
        metadata_out["answer_fallback_reason"] = ""
        metadata_out["llm_verbalizer_called"] = False
        return "请告诉我你现在在哪个城市、商圈或地标附近。"

    monkeypatch.setattr("local_life_agent.engine.graph_builder.generate_answer", fake_generate_answer)

    result = _h_answer_generate(
        {
            "answer_plan": AnswerPlan(answer_type="clarification", fallback_template_type="clarification"),
            "evidence_pack": {},
            "rewrite_count": 0,
            "answer_verify_violations": [],
            "rewrite_instruction": None,
            "rewrite_mode": "",
            "response_mode": "clarify",
            "trace_id": "trace-test",
            "fallback_reason": "LLM_ENUM_OUT_OF_RANGE",
            "answer_fallback_reason": "LLM_ENUM_OUT_OF_RANGE",
            "pending_clarification": {"reason": "need_user_location"},
            "event_log": [],
        }
    )

    assert "告诉我" in result["draft_response"]
    assert result["fallback_reason"] == ""
    assert result["answer_fallback_reason"] == ""
