"""Tests for CandidateResolver — explicit / context / discovery / mixed resolution."""

from __future__ import annotations

from typing import Any

import pytest

from ..domain.candidate import (
    CandidateSet,
    CandidateSource,
    CandidateStatus,
    CandidateSpec,
    GoalType,
    LocalLifeGoalDraft,
    ResolvedCandidate,
)
from ..target.candidate_resolver import CandidateResolver


# ===================================================================
# Helpers
# ===================================================================


def _goal(
    goal_type: GoalType = GoalType.COMPARISON,
    candidate_source: CandidateSource = CandidateSource.DISCOVERY,
    candidate_limit: int | None = None,
    **kw: Any,
) -> LocalLifeGoalDraft:
    return LocalLifeGoalDraft(
        goal_type=goal_type,
        candidate_source=candidate_source,
        candidate_limit=candidate_limit,
        **kw,
    )


def _spec(
    source: CandidateSource = CandidateSource.DISCOVERY,
    category: str = "",
    query: str = "",
    limit: int | None = None,
    explicit_mentions: list[str] | None = None,
    **kw: Any,
) -> CandidateSpec:
    return CandidateSpec(
        source=source,
        category=category,
        query=query,
        limit=limit,
        explicit_mentions=explicit_mentions or [],
        **kw,
    )


def _fake_resolve_shop(query: str, **kw: Any) -> dict[str, Any]:
    """Simulate resolve_shop for controlled testing."""
    data: dict[str, Any] = query.lower().strip()
    session_shop_ids = list(kw.get("session_shop_ids") or [])

    if data in ("海底捞(牡丹园店)",):
        return {
            "status": "RESOLVED",
            "shop": {"shop_id": "shop_007", "shop_name": "海底捞(牡丹园店)"},
            "candidates": [],
            "confidence": 0.95,
        }
    if data in ("山城一锅",):
        return {
            "status": "RESOLVED",
            "shop": {"shop_id": "shop_011", "shop_name": "山城一锅"},
            "candidates": [],
            "confidence": 0.95,
        }
    if data == "海底捞":
        return {
            "status": "AMBIGUOUS",
            "shop": None,
            "candidates": [
                {"shop_id": "shop_007", "shop_name": "海底捞(牡丹园店)"},
                {"shop_id": "shop_sc_01", "shop_name": "海底捞火锅(水晶城购物中心店)"},
            ],
            "confidence": 0.5,
        }
    if data in ("nonexistent_shop", "KTV", "不存在的店"):
        return {
            "status": "NOT_FOUND",
            "shop": None,
            "candidates": [],
            "confidence": 0.0,
        }
    if data in ("这家", "它", "第一家") and session_shop_ids:
        return {
            "status": "RESOLVED",
            "shop": {"shop_id": session_shop_ids[0], "shop_name": "上下文店铺"},
            "candidates": [],
            "confidence": 0.9,
        }
    # Default: ambiguous
    return {
        "status": "AMBIGUOUS",
        "shop": None,
        "candidates": [{"shop_id": "shop_007", "shop_name": "海底捞(牡丹园店)"}],
        "confidence": 0.5,
    }


def _fake_search_shops(query: str, **kw: Any) -> dict[str, Any]:
    """Simulate search_shops for controlled testing."""
    q = query.lower().strip()

    if q in ("ktv", "不存在的品类"):
        return {"success": True, "result_status": "ok", "data": []}

    if q in ("火锅", "麻辣烫"):
        return {
            "success": True,
            "result_status": "ok",
            "data": [
                {"shop_id": "shop_007", "shop_name": "海底捞(牡丹园店)", "rating": 4.5, "distance_km": 1.2},
                {"shop_id": "shop_sc_01", "shop_name": "海底捞火锅(水晶城购物中心店)", "rating": 4.3, "distance_km": 3.5},
                {"shop_id": "shop_004", "shop_name": "张亮麻辣烫(北邮店)", "rating": 4.0, "distance_km": 0.5},
            ],
        }

    if q == "咖啡":
        return {
            "success": True,
            "result_status": "ok",
            "data": [
                {"shop_id": "shop_001", "shop_name": "北邮科技大厦咖啡厅", "rating": 4.2, "distance_km": 0.3},
                {"shop_id": "shop_005", "shop_name": "瑞幸咖啡(北邮店)", "rating": 4.1, "distance_km": 0.6},
            ],
        }

    # Default: single result
    return {
        "success": True,
        "result_status": "ok",
        "data": [
            {"shop_id": "shop_001", "shop_name": "北邮科技大厦咖啡厅", "rating": 4.0, "distance_km": 0.5},
        ],
    }


@pytest.fixture
def resolver() -> CandidateResolver:
    """Resolver using fake resolve/search functions."""
    return CandidateResolver(
        resolve_shop_fn=_fake_resolve_shop,
        search_shops_fn=_fake_search_shops,
    )


@pytest.fixture
def real_resolver() -> CandidateResolver:
    """Resolver using real mock_tools (live shops.json)."""
    return CandidateResolver()


# ===================================================================
# resolve_explicit
# ===================================================================


class TestResolveExplicit:
    def test_resolves_two_explicit_mentions(self, resolver: CandidateResolver):
        goal = _goal(goal_type=GoalType.COMPARISON, candidate_source=CandidateSource.EXPLICIT, candidate_limit=2)
        spec = _spec(
            source=CandidateSource.EXPLICIT,
            explicit_mentions=["海底捞(牡丹园店)", "山城一锅"],
            limit=2,
        )
        result = resolver.resolve_explicit(goal, spec)
        assert result.status == CandidateStatus.RESOLVED
        assert len(result.candidates) == 2
        names = {c.shop_name for c in result.candidates}
        assert "海底捞(牡丹园店)" in names
        assert "山城一锅" in names

    def test_no_mentions_returns_not_found(self, resolver: CandidateResolver):
        goal = _goal(goal_type=GoalType.COMPARISON, candidate_source=CandidateSource.EXPLICIT)
        spec = _spec(source=CandidateSource.EXPLICIT, explicit_mentions=[])
        result = resolver.resolve_explicit(goal, spec)
        assert result.status == CandidateStatus.NOT_FOUND

    def test_ambiguous_mention_returns_ambiguous_candidate_set(self, resolver: CandidateResolver):
        """When resolve_shop returns AMBIGUOUS, resolver must keep ambiguity for clarification."""
        goal = _goal(goal_type=GoalType.COMPARISON, candidate_source=CandidateSource.EXPLICIT, candidate_limit=2)
        spec = _spec(
            source=CandidateSource.EXPLICIT,
            explicit_mentions=["海底捞"],
            limit=2,
        )
        result = resolver.resolve_explicit(goal, spec)
        assert result.status == CandidateStatus.AMBIGUOUS
        assert len(result.candidates) >= 2
        assert {c.shop_id for c in result.candidates} >= {"shop_007", "shop_sc_01"}
        assert result.min_required == 2

    def test_not_found_mention_skipped(self, resolver: CandidateResolver):
        goal = _goal(goal_type=GoalType.COMPARISON, candidate_source=CandidateSource.EXPLICIT, candidate_limit=2)
        spec = _spec(
            source=CandidateSource.EXPLICIT,
            explicit_mentions=["海底捞(牡丹园店)", "nonexistent_shop"],
            limit=2,
        )
        result = resolver.resolve_explicit(goal, spec)
        assert result.status == CandidateStatus.RESOLVED
        assert len(result.candidates) == 1
        assert result.candidates[0].shop_id == "shop_007"


# ===================================================================
# resolve_context
# ===================================================================


class TestResolveContext:
    def test_resolves_from_comparison_targets(self, resolver: CandidateResolver):
        goal = _goal(goal_type=GoalType.COMPARISON, candidate_source=CandidateSource.CONTEXT, candidate_limit=2)
        spec = _spec(source=CandidateSource.CONTEXT)
        state: dict[str, Any] = {
            "comparison_targets": [
                {"resolved_shop": {"shop_id": "shop_007", "shop_name": "海底捞(牡丹园店)"}},
                {"resolved_shop": {"shop_id": "shop_sc_01", "shop_name": "海底捞火锅(水晶城购物中心店)"}},
            ],
        }
        result = resolver.resolve_context(goal, spec, state)
        assert result.status == CandidateStatus.RESOLVED
        assert len(result.candidates) == 2

    def test_falls_back_to_last_recommendation_list(self, resolver: CandidateResolver):
        goal = _goal(goal_type=GoalType.COMPARISON, candidate_source=CandidateSource.CONTEXT, candidate_limit=2)
        spec = _spec(source=CandidateSource.CONTEXT)
        state: dict[str, Any] = {
            "last_recommendation_list": [
                {"shop_id": "shop_001", "shop_name": "北邮科技大厦咖啡厅"},
                {"shop_id": "shop_005", "shop_name": "瑞幸咖啡(北邮店)"},
            ],
        }
        result = resolver.resolve_context(goal, spec, state)
        assert result.status == CandidateStatus.RESOLVED
        assert len(result.candidates) == 2

    def test_falls_back_to_current_shop(self, resolver: CandidateResolver):
        goal = _goal(goal_type=GoalType.SINGLE_SHOP_QUERY, candidate_source=CandidateSource.CONTEXT, candidate_limit=1)
        spec = _spec(source=CandidateSource.CONTEXT)
        state: dict[str, Any] = {
            "current_shop": {"shop_id": "shop_007", "shop_name": "海底捞(牡丹园店)"},
        }
        result = resolver.resolve_context(goal, spec, state)
        assert result.status == CandidateStatus.RESOLVED
        assert len(result.candidates) == 1
        assert result.candidates[0].shop_id == "shop_007"

    def test_no_context_returns_not_found(self, resolver: CandidateResolver):
        goal = _goal(goal_type=GoalType.COMPARISON, candidate_source=CandidateSource.CONTEXT)
        spec = _spec(source=CandidateSource.CONTEXT)
        result = resolver.resolve_context(goal, spec, {})
        assert result.status == CandidateStatus.NOT_FOUND


# ===================================================================
# resolve_discovery
# ===================================================================


class TestResolveDiscovery:
    def test_search_returns_results(self, resolver: CandidateResolver):
        goal = _goal(goal_type=GoalType.COMPARISON, candidate_source=CandidateSource.DISCOVERY, candidate_limit=2)
        spec = _spec(source=CandidateSource.DISCOVERY, query="火锅", limit=2)
        result = resolver.resolve_discovery(goal, spec)
        assert result.status == CandidateStatus.RESOLVED
        assert len(result.candidates) == 2
        assert all(c.source == CandidateSource.DISCOVERY for c in result.candidates)

    def test_empty_query_returns_not_found(self, resolver: CandidateResolver):
        goal = _goal(goal_type=GoalType.COMPARISON, candidate_source=CandidateSource.DISCOVERY)
        spec = _spec(source=CandidateSource.DISCOVERY, query="")
        result = resolver.resolve_discovery(goal, spec)
        assert result.status == CandidateStatus.NOT_FOUND

    def test_search_no_results_returns_not_found(self, resolver: CandidateResolver):
        goal = _goal(goal_type=GoalType.COMPARISON, candidate_source=CandidateSource.DISCOVERY)
        spec = _spec(source=CandidateSource.DISCOVERY, query="KTV")
        result = resolver.resolve_discovery(goal, spec)
        assert result.status == CandidateStatus.NOT_FOUND

    def test_search_normalizes_common_modifiers(self, resolver: CandidateResolver):
        goal = _goal(goal_type=GoalType.COMPARISON, candidate_source=CandidateSource.DISCOVERY)
        spec = _spec(source=CandidateSource.DISCOVERY, query="附近 火锅", limit=2)
        result = resolver.resolve_discovery(goal, spec)
        assert result.status == CandidateStatus.RESOLVED
        assert len(result.candidates) == 2

    def test_search_combined_categories_falls_back_to_each_term(self):
        def _multi_term_search(query: str, **kw: Any) -> dict[str, Any]:
            q = str(query or "").strip()
            if q in {"火锅 烧烤", "火锅,烧烤"}:
                return {"success": True, "result_status": "ok", "data": []}
            if q == "火锅":
                return {
                    "success": True,
                    "result_status": "ok",
                    "data": [
                        {"shop_id": "shop_007", "shop_name": "海底捞(牡丹园店)", "rating": 4.5, "distance_km": 1.2},
                    ],
                }
            if q == "烧烤":
                return {
                    "success": True,
                    "result_status": "ok",
                    "data": [
                        {"shop_id": "shop_bb_01", "shop_name": "木屋烧烤(北邮店)", "rating": 4.2, "distance_km": 0.8},
                    ],
                }
            return {"success": True, "result_status": "ok", "data": []}

        resolver = CandidateResolver(search_shops_fn=_multi_term_search)
        goal = _goal(goal_type=GoalType.COMPARISON, candidate_source=CandidateSource.DISCOVERY, candidate_limit=3)
        spec = _spec(source=CandidateSource.DISCOVERY, query="火锅 烧烤", limit=3)
        result = resolver.resolve_discovery(goal, spec)
        assert result.status == CandidateStatus.RESOLVED
        assert {c.shop_id for c in result.candidates} == {"shop_007", "shop_bb_01"}
        assert result.candidates[0].shop_id == "shop_007"

    def test_limit_applied(self, resolver: CandidateResolver):
        """Ensure limit parameter caps the number of candidates."""
        goal = _goal(goal_type=GoalType.COMPARISON, candidate_source=CandidateSource.DISCOVERY, candidate_limit=1)
        spec = _spec(source=CandidateSource.DISCOVERY, query="火锅", limit=1)
        result = resolver.resolve_discovery(goal, spec)
        assert result.status == CandidateStatus.RESOLVED
        assert len(result.candidates) == 1


# ===================================================================
# resolve_mixed
# ===================================================================


class TestResolveMixed:
    def test_mixed_explicit_and_discovery(self, resolver: CandidateResolver):
        goal = _goal(goal_type=GoalType.COMPARISON, candidate_source=CandidateSource.MIXED, candidate_limit=3)
        spec = _spec(
            source=CandidateSource.MIXED,
            query="火锅",
            limit=3,
            explicit_mentions=["海底捞(牡丹园店)"],
        )
        result = resolver.resolve_mixed(goal, spec)
        assert result.status == CandidateStatus.RESOLVED
        # explicit: shop_007 (海底捞) + discovery: shop_sc_01, shop_004 = 3 total (after dedupe)
        assert len(result.candidates) >= 2

    def test_mixed_dedupe_removes_duplicates(self, resolver: CandidateResolver):
        """Mixed resolver should deduplicate by shop_id."""
        spec = _spec(
            source=CandidateSource.MIXED,
            query="火锅",
            limit=5,
            explicit_mentions=["海底捞(牡丹园店)"],
        )
        goal = _goal(goal_type=GoalType.COMPARISON, candidate_source=CandidateSource.MIXED, candidate_limit=5)
        result = resolver.resolve_mixed(goal, spec)
        # shop_007 appears in both explicit and discovery, but dedupe keeps only 1
        shop_ids = [c.shop_id for c in result.candidates]
        assert len(shop_ids) == len(set(shop_ids)), "duplicate shop_ids found"

    def test_mixed_both_empty_returns_not_found(self, resolver: CandidateResolver):
        goal = _goal(goal_type=GoalType.COMPARISON, candidate_source=CandidateSource.MIXED)
        spec = _spec(
            source=CandidateSource.MIXED,
            query="ktv",
            limit=3,
            explicit_mentions=[],
        )
        result = resolver.resolve_mixed(goal, spec)
        assert result.status == CandidateStatus.NOT_FOUND

    def test_mixed_uses_context_when_explicit_is_empty(self, resolver: CandidateResolver):
        goal = _goal(goal_type=GoalType.COMPARISON, candidate_source=CandidateSource.MIXED, candidate_limit=2)
        spec = _spec(source=CandidateSource.MIXED, query="", explicit_mentions=[])
        state: dict[str, Any] = {
            "current_shop": {"shop_id": "shop_007", "shop_name": "海底捞(牡丹园店)"},
        }
        result = resolver.resolve_mixed(goal, spec, state)
        assert result.status == CandidateStatus.RESOLVED
        assert len(result.candidates) == 1
        assert result.candidates[0].shop_id == "shop_007"


# ===================================================================
# resolve (dispatch)
# ===================================================================


class TestResolveDispatch:
    def test_dispatch_explicit(self, resolver: CandidateResolver):
        goal = _goal(goal_type=GoalType.COMPARISON, candidate_source=CandidateSource.EXPLICIT)
        spec = _spec(source=CandidateSource.EXPLICIT, explicit_mentions=["海底捞(牡丹园店)", "山城一锅"])
        result = resolver.resolve(goal, spec)
        assert result.source == CandidateSource.EXPLICIT

    def test_dispatch_context(self, resolver: CandidateResolver):
        goal = _goal(goal_type=GoalType.COMPARISON, candidate_source=CandidateSource.CONTEXT)
        spec = _spec(source=CandidateSource.CONTEXT)
        state: dict[str, Any] = {
            "comparison_targets": [
                {"resolved_shop": {"shop_id": "shop_007", "shop_name": "海底捞(牡丹园店)"}},
            ],
        }
        result = resolver.resolve(goal, spec, state)
        assert result.source == CandidateSource.CONTEXT

    def test_dispatch_discovery(self, resolver: CandidateResolver):
        goal = _goal(goal_type=GoalType.COMPARISON, candidate_source=CandidateSource.DISCOVERY)
        spec = _spec(source=CandidateSource.DISCOVERY, query="火锅", limit=2)
        result = resolver.resolve(goal, spec)
        assert result.source == CandidateSource.DISCOVERY

    def test_dispatch_mixed(self, resolver: CandidateResolver):
        goal = _goal(goal_type=GoalType.COMPARISON, candidate_source=CandidateSource.MIXED)
        spec = _spec(source=CandidateSource.MIXED, query="火锅", explicit_mentions=["海底捞(牡丹园店)"])
        result = resolver.resolve(goal, spec)
        assert result.source == CandidateSource.MIXED

    def test_unknown_source_returns_not_found(self, resolver: CandidateResolver):
        goal = _goal(goal_type=GoalType.UNSUPPORTED)
        spec = _spec(source=CandidateSource.DISCOVERY, query="")
        result = resolver.resolve(goal, spec)
        assert result.status == CandidateStatus.NOT_FOUND
