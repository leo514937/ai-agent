"""Graph component test: _h_target_resolve → CandidateSet path.

Exercises the full _h_target_resolve_candidate_set pipeline WITHOUT
depending on the LLM chain (top_intent_router / semantic_parse) by
directly constructing a GraphState with a pre-populated SemanticFrame
that has ``candidate_source`` set.

Pipeline under test:
  _h_target_resolve (dispatch)
    → _h_target_resolve_candidate_set
      → build_local_life_goal_draft → build_candidate_spec
      → CandidateResolver.resolve → review_candidate_set
      → route by next_action (FINISH / CLARIFY / FALLBACK)
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from ..domain.candidate import CandidateSource, GoalType, LocalLifeGoalDraft
from ..domain.graph_state import GraphState
from ..domain.schemas import ResolveShopResult, SemanticFrame, ShopRef, TaskType
from ..engine.graph_builder import (
    _h_target_resolve,
    _h_target_resolve_candidate_set,
)
from ..engine import graph_builder
from .fakes import mock_tools
from ..target.candidate_resolver import CandidateResolver
from ..planning.review_policy import NextAction, ReviewStatus


# ===================================================================
# Helpers
# ===================================================================


def _state(
    sf: SemanticFrame | dict[str, Any],
    raw_text: str = "",
    session_id: str = "test_cs",
    **extra: Any,
) -> GraphState:
    """Build a minimal GraphState dict with a SemanticFrame."""
    state = {
        "raw_text": raw_text,
        "session_id": session_id,
        "semantic_frame": sf,
        "session_state": {},
        "turn_id": "1",
        "event_log": [],
        "final_response": "",
    }
    state.update(extra)
    return cast(GraphState, state)


def _expect_routing(result: dict[str, Any], next_action: str) -> None:
    """Assert that the result routes correctly for *next_action*."""
    assert "local_life_goal_draft" in result, "missing goal_draft"
    assert "candidate_spec" in result, "missing candidate_spec"
    assert "candidate_set" in result, "missing candidate_set"
    assert "review_results" in result, "missing review_results"
    assert "candidate_review" in result["review_results"]

    review = result["review_results"]["candidate_review"]
    assert review.next_action.value.lower() == next_action.lower(), (
        f"expected next_action={next_action}, got {review.next_action}"
    )


# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture(autouse=True)
def _fake_tool_search(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        graph_builder,
        "CandidateResolver",
        lambda: CandidateResolver(
            resolve_shop_fn=mock_tools.resolve_shop,
            search_shops_fn=mock_tools.search_shops,
        ),
    )


# ===================================================================
# Discovery comparison
# ===================================================================


class TestDiscoveryComparison:
    """Discovery comparison: LLM identifies a category but no explicit shops."""

    def test_discovery_hotpot_resolves_to_finish(self):
        """'火锅' (hotpot) → resolve candidates → ENOUGH → FINISH."""
        sf = SemanticFrame(
            task_type=TaskType.comparison,
            candidate_source=CandidateSource.DISCOVERY.value,
            candidate_category="火锅",
            candidate_limit=3,
        )
        result = _h_target_resolve(_state(sf, raw_text="附近火锅推荐"))
        _expect_routing(result, "finish")

        cs = result["candidate_set"]
        assert len(cs.candidates) > 0, "expected at least 1 candidate for hotpot"
        assert cs.source == CandidateSource.DISCOVERY

        resolve = result.get("resolve_shop_result")
        assert resolve is not None
        assert resolve.status == "RESOLVED", f"expected RESOLVED, got {resolve.status}"

    def test_discovery_unknown_category_clarifies(self):
        """Unknown category → no candidates → CLARIFY."""
        sf = SemanticFrame(
            task_type=TaskType.comparison,
            candidate_source=CandidateSource.DISCOVERY.value,
            candidate_category="nonexistent_category_xyz",
            candidate_limit=3,
        )
        result = _h_target_resolve(_state(sf, raw_text="找一些奇怪的东西"))
        _expect_routing(result, "clarify")

        cs = result["candidate_set"]
        assert len(cs.candidates) == 0

    def test_discovery_recommendation_resolves_to_finish(self):
        """Discovery with RECOMMENDATION goal → resolves → FINISH."""
        sf = SemanticFrame(
            task_type=TaskType.recommendation,
            candidate_source=CandidateSource.DISCOVERY.value,
            candidate_category="火锅",
            candidate_limit=5,
        )
        result = _h_target_resolve(_state(sf, raw_text="附近火锅推荐"))
        _expect_routing(result, "finish")


# ===================================================================
# Explicit comparison
# ===================================================================


class TestExplicitComparison:
    """User explicitly names shops to compare."""

    def test_explicit_known_shops_resolves_to_finish(self):
        """Two known shops → resolved → FINISH."""
        sf = SemanticFrame(
            task_type=TaskType.comparison,
            candidate_source=CandidateSource.EXPLICIT.value,
            merchant_mentions=["海底捞(牡丹园店)", "川味轩(知春路店)"],
            candidate_limit=2,
        )
        result = _h_target_resolve(_state(sf, raw_text="海底捞和川味轩哪个好"))
        _expect_routing(result, "finish")

        cs = result["candidate_set"]
        assert len(cs.candidates) >= 2, "expected at least 2 candidates"
        assert cs.source == CandidateSource.EXPLICIT

    def test_explicit_unknown_shops_clarifies(self):
        """Unknown shops → no candidates → CLARIFY."""
        sf = SemanticFrame(
            task_type=TaskType.comparison,
            candidate_source=CandidateSource.EXPLICIT.value,
            merchant_mentions=["NonexistentShop1", "NonexistentShop2"],
            candidate_limit=2,
        )
        result = _h_target_resolve(_state(sf, raw_text="比较两个不存在的店"))
        _expect_routing(result, "clarify")


# ===================================================================
# Context comparison (re-use previous session candidates)
# ===================================================================


class TestContextComparison:
    """Context comparison: reference previous recommendation list."""

    def test_context_from_recommendation_list_resolves(self):
        """Contextual comparison from session state → FINISH."""
        sf = SemanticFrame(
            task_type=TaskType.comparison,
            candidate_source=CandidateSource.CONTEXT.value,
            candidate_limit=3,
        )
        # last_recommendation_list must be at top-level GraphState (as
        # _h_load_session would set it)
        result = _h_target_resolve(_state(
            sf,
            raw_text="这几家哪个好",
            last_recommendation_list=[
                {"shop_id": "shop_007", "shop_name": "海底捞(牡丹园店)"},
                {"shop_id": "shop_sc_05", "shop_name": "川味轩(知春路店)"},
                {"shop_id": "shop_sc_01", "shop_name": "海底捞火锅(水晶城购物中心店)"},
            ],
        ))
        _expect_routing(result, "finish")

        cs = result["candidate_set"]
        assert len(cs.candidates) >= 2, "expected at least 2 context candidates"
        assert cs.source == CandidateSource.CONTEXT


# ===================================================================
# Missing/empty candidate_source — should still stay on CandidateSet path
# ===================================================================


class TestCandidateSourceBackfill:
    """Missing candidate_source must be backfilled, not routed to legacy."""

    def test_no_candidate_source_is_backfilled(self):
        sf = SemanticFrame(
            task_type=TaskType.comparison,
            merchant_mentions=["海底捞(牡丹园店)", "川味轩(知春路店)"],
        )
        result = _h_target_resolve(_state(sf, raw_text="海底捞和川味轩哪个好"))
        assert "local_life_goal_draft" in result
        assert "candidate_set" in result

    def test_empty_candidate_source_is_backfilled(self):
        sf = SemanticFrame(
            task_type=TaskType.comparison,
            candidate_source="",
            merchant_mentions=["海底捞(牡丹园店)", "川味轩(知春路店)"],
        )
        result = _h_target_resolve(_state(sf, raw_text="哪个好"))
        assert "local_life_goal_draft" in result
        assert "candidate_set" in result


# ===================================================================
# _h_target_resolve_candidate_set direct invocation
# ===================================================================


class TestDirectInvocation:
    """Direct calls to _h_target_resolve_candidate_set (skip dispatch)."""

    def test_minimal_comparison_resolves(self):
        """Minimal comparison frame with discovery source → enters CandidateSet path."""
        sf = SemanticFrame(
            task_type=TaskType.comparison,
            candidate_source=CandidateSource.DISCOVERY.value,
        )
        state = _state(sf, raw_text="test")
        result = _h_target_resolve_candidate_set(state, sf)
        # Should enter CandidateSet path and produce goal_draft
        assert "local_life_goal_draft" in result
        assert "candidate_set" in result
        assert "review_results" in result

    def test_explicit_shop_target_uses_brand_branch_prefix(self, monkeypatch: pytest.MonkeyPatch):
        calls: list[str] = []

        class _FakeResolveResult:
            def __init__(self, payload: dict[str, Any], trace: list[dict[str, Any]] | None = None):
                self._payload = dict(payload)
                self.trace = list(trace or [])

            def model_dump(self) -> dict[str, Any]:
                return dict(self._payload)

        def fake_resolve_shop_entity(mention: str, **kwargs):
            calls.append(mention)
            if mention == "海底捞水晶城店":
                return _FakeResolveResult(
                    {
                        "status": "RESOLVED",
                        "shop_id": "shop_900",
                        "shop_name": "海底捞水晶城店",
                        "resolved_shop": {"shop_id": "shop_900", "shop_name": "海底捞水晶城店"},
                        "confidence": 0.99,
                        "reason": "resolved",
                    },
                    trace=[{"mention": mention, "result": "resolved"}],
                )
            return _FakeResolveResult({"status": "NOT_FOUND", "confidence": 0.0, "reason": "not_found"}, trace=[{"mention": mention, "result": "not_found"}])

        monkeypatch.setattr(
            "local_life_agent.engine.subgraphs.planning_subgraph.resolve_shop_entity",
            fake_resolve_shop_entity,
        )

        sf = SemanticFrame(
            task_type=TaskType.single_shop_query,
            candidate_source=CandidateSource.EXPLICIT.value,
            shop_target={"shop_name": "水晶城店", "text": "水晶城店"},
            merchant_mentions=["水晶城店", "海底捞"],
        )
        result = _h_target_resolve_candidate_set(_state(sf, raw_text="海底捞水晶城店多久能到？"), sf)

        assert calls[0] == "海底捞水晶城店"
        resolve_result = result["resolve_shop_result"]
        assert getattr(resolve_result, "status", "") == "RESOLVED"
        assert result.get("target_resolution_status") == "RESOLVED"
