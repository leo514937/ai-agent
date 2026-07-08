from __future__ import annotations

from collections.abc import Generator
from typing import Any
import sys

import pytest

from local_life_agent import agent
from local_life_agent.agent import run_agent_graph
from local_life_agent.engine import graph_builder
from local_life_agent.llm.client import clear_llm_backend, set_llm_backend
from local_life_agent.planning.evidence.evidence_builder import _build_recommendation_evidence
from local_life_agent.planning.plans.execution_plan_builder import build_recommendation_execution_plan
from local_life_agent.semantic.slot_extractor import extract_recommendation_count
from local_life_agent.session.store import reset_session_store
from local_life_agent.tests.test_recommendation_flow import _recommendation_llm_backend


TEST_LOCATION = {
    "location_name": "北京邮电大学",
    "lat": 39.9609,
    "lng": 116.3581,
    "location_status": "test_mock",
    "location_source": "test_mock",
}


@pytest.fixture(autouse=True)
def _inject_test_location(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    reset_session_store()
    set_llm_backend(_recommendation_llm_backend)
    monkeypatch.setattr(graph_builder, "call_llm", _recommendation_llm_backend)
    original_run_agent_graph = agent.run_agent_graph

    def _run_with_location(
        input_text: str,
        session_id: str = "",
        *,
        trace_id: str | None = None,
        turn_id: str | None = None,
        user_context: Any | None = None,
        user_location: dict[str, Any] | None = None,
    ):
        location_payload = user_location or user_context or dict(TEST_LOCATION)
        return original_run_agent_graph(
            input_text,
            session_id=session_id,
            trace_id=trace_id,
            turn_id=turn_id,
            user_context=user_context or location_payload,
            user_location=user_location or location_payload,
        )

    monkeypatch.setattr(agent, "run_agent_graph", _run_with_location)
    monkeypatch.setattr(sys.modules[__name__], "run_agent_graph", _run_with_location)
    yield
    clear_llm_backend()
    reset_session_store()
    agent._GRAPH_CACHE = None


def test_extract_recommendation_count_from_text():
    assert extract_recommendation_count("推荐 3 家火锅") == 3
    assert extract_recommendation_count("帮我推荐10家附近好吃的") == 10
    assert extract_recommendation_count("推荐几家附近好吃的") is None


def test_recommendation_three_shops_respects_requested_count():
    payload = build_recommendation_execution_plan(
        {"task_type": "recommendation", "candidate_limit": 3, "ranking_signals": {"query_terms": ["火锅"]}},
        location=dict(TEST_LOCATION),
    )

    assert payload["plan"]["candidate_limit"] == 3
    assert payload["plan"]["evidence_enrichment_top_k"] >= 3

    evidence = _build_recommendation_evidence(
        [],
        {
            "call_search": {
                "tool_name": "search_shops",
                "result_status": "ok",
                "data": [
                    {"shop_id": "s1", "shop_name": "火锅A", "category": "火锅", "rating": 4.8, "distance_km": 1.0, "open_status": "open"},
                    {"shop_id": "s2", "shop_name": "火锅B", "category": "火锅", "rating": 4.7, "distance_km": 1.2, "open_status": "open"},
                    {"shop_id": "s3", "shop_name": "火锅C", "category": "火锅", "rating": 4.6, "distance_km": 1.4, "open_status": "open"},
                    {"shop_id": "s4", "shop_name": "火锅D", "category": "火锅", "rating": 4.5, "distance_km": 1.6, "open_status": "open"},
                ],
            }
        },
        {},
        {"plan_id": "recommendation_count_3", "query_terms": ["火锅"], "scene_terms": [], "candidate_limit": 3},
        semantic_frame={"task_type": "recommendation", "candidate_limit": 3},
    )
    assert len(evidence.get("ranking_snapshot", {}).get("ranked", [])) <= 3


def test_recommendation_five_shops_respects_requested_count():
    payload = build_recommendation_execution_plan(
        {"task_type": "recommendation", "candidate_limit": 5, "ranking_signals": {"query_terms": ["火锅"]}},
        location=dict(TEST_LOCATION),
    )

    assert payload["plan"]["candidate_limit"] == 5
    assert payload["plan"]["evidence_enrichment_top_k"] >= 5
