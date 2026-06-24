"""CandidateResolver — resolves CandidateSpec into a CandidateSet.

Provides a single ``resolve()`` entry point that dispatches to the
appropriate resolution strategy based on the candidate source:
  - DISCOVERY  → search shops by category/query
  - EXPLICIT   → resolve specific shop mentions
  - CONTEXT    → use session context for recovery
  - MIXED      → combine explicit mentions + context
"""

from __future__ import annotations

from typing import Any, Callable

from ..config import SEARCH_LIMIT
from ..domain.candidate import (
    CandidateSet,
    CandidateSource,
    CandidateSpec,
    CandidateStatus,
    ResolvedCandidate,
)
from ..tools.gateway import dispatch_tool_call


def _default_resolve_shop(query: str, **kw: Any) -> dict[str, Any]:
    result = dispatch_tool_call("resolve_shop", {"query": query, **(kw or {})})
    # dispatch_tool_call normalizes the result; extract the raw tool output
    data = result.get("data")
    if isinstance(data, dict) and "status" in data:
        return data
    return result


def _default_search_shops(query: str, **kw: Any) -> dict[str, Any]:
    result = dispatch_tool_call("search_shops", {"query": query, **(kw or {})})
    # dispatch_tool_call normalizes; 'data' may be a list or dict
    data = result.get("data")
    if isinstance(data, list):
        return {"success": True, "result_status": "ok", "data": data, "total": len(data)}
    if isinstance(data, dict) and "data" in data:
        return data
    return result


def _to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        return dumped if isinstance(dumped, dict) else {}
    return dict(getattr(value, "__dict__", {}) or {})


class CandidateResolver:
    """Resolve candidates for a given goal and spec.

    The resolver supports two modes:
      1. Injected functions (for testing): pass resolve_shop_fn/search_shops_fn.
      2. Default (production): uses dispatch_tool_call for all resolution.
    """

    def __init__(
        self,
        resolve_shop_fn: Callable | None = None,
        search_shops_fn: Callable | None = None,
    ):
        self._resolve_shop = resolve_shop_fn or _default_resolve_shop
        self._search_shops = search_shops_fn or _default_search_shops

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def resolve(
        self,
        goal: Any,
        spec: CandidateSpec,
        state: dict[str, Any] | None = None,
    ) -> CandidateSet:
        """Resolve the spec into a CandidateSet.

        Delegates to the appropriate method based on ``spec.source``.
        """
        state = state or {}
        source = spec.source
        if source == CandidateSource.EXPLICIT:
            return self.resolve_explicit(goal, spec)
        if source == CandidateSource.CONTEXT:
            return self.resolve_context(goal, spec, state)
        if source == CandidateSource.MIXED:
            return self.resolve_mixed(goal, spec, state)
        return self.resolve_discovery(goal, spec)

    # ------------------------------------------------------------------
    # Explicit resolution
    # ------------------------------------------------------------------

    def resolve_explicit(
        self,
        goal: Any,
        spec: CandidateSpec,
    ) -> CandidateSet:
        """Resolve explicit shop mentions via resolve_shop.

        AMBIGUOUS mentions take the first candidate.
        NOT_FOUND mentions are skipped.
        """
        mentions = spec.explicit_mentions or []
        if not mentions:
            return CandidateSet(
                status=CandidateStatus.NOT_FOUND,
                source=CandidateSource.EXPLICIT,
                candidates=[],
                requested_count=spec.limit or 1,
                min_required=1,
                max_allowed=spec.limit or 5,
            )

        candidates: list[ResolvedCandidate] = []
        ambiguous_candidates: list[ResolvedCandidate] = []
        for idx, mention in enumerate(mentions):
            result = self._resolve_shop(mention)
            status = str(result.get("status", "NOT_FOUND") or "NOT_FOUND")

            if status == "RESOLVED":
                shop = _to_dict(result.get("shop") or result.get("data") or {})
                sid = str(shop.get("shop_id", "")).strip()
                if sid:
                    candidates.append(ResolvedCandidate(
                        shop_id=sid,
                        shop_name=str(shop.get("shop_name", mention)),
                        source=CandidateSource.EXPLICIT,
                        rank=idx,
                        confidence=float(result.get("confidence", 0.9)),
                        raw=shop,
                    ))
            elif status == "AMBIGUOUS":
                cand_list = result.get("candidates") or []
                for cand in cand_list:
                    cand_dict = _to_dict(cand)
                    sid = str(cand_dict.get("shop_id", "")).strip()
                    if sid:
                        ambiguous_candidates.append(ResolvedCandidate(
                            shop_id=sid,
                            shop_name=str(cand_dict.get("shop_name", mention)),
                            source=CandidateSource.EXPLICIT,
                            rank=idx,
                            confidence=float(result.get("confidence", 0.5)),
                            raw=cand_dict,
                        ))

        if ambiguous_candidates and not candidates:
            first_candidate = ambiguous_candidates[:1]
            return CandidateSet(
                status=CandidateStatus.RESOLVED,
                source=CandidateSource.EXPLICIT,
                candidates=first_candidate,
                requested_count=spec.limit or len(first_candidate) or 1,
                min_required=1,
                max_allowed=spec.limit or 5,
            )

        if not candidates:
            return CandidateSet(
                status=CandidateStatus.NOT_FOUND,
                source=CandidateSource.EXPLICIT,
                candidates=[],
                requested_count=spec.limit or len(mentions) or 1,
                min_required=1,
                max_allowed=spec.limit or 5,
            )

        return CandidateSet(
            status=CandidateStatus.RESOLVED,
            source=CandidateSource.EXPLICIT,
            candidates=candidates,
            requested_count=spec.limit or len(candidates),
            min_required=1,
            max_allowed=spec.limit or 5,
        )

    # ------------------------------------------------------------------
    # Context resolution
    # ------------------------------------------------------------------

    def resolve_context(
        self,
        goal: Any,
        spec: CandidateSpec,
        state: dict[str, Any] | None = None,
    ) -> CandidateSet:
        """Resolve candidates from session context.

        Priority:
          1. comparison_targets
          2. last_recommendation_list
          3. current_shop
        """
        state = state or {}
        candidates: list[ResolvedCandidate] = []

        # 1. comparison_targets
        ct = state.get("comparison_targets") or []
        for idx, item in enumerate(ct):
            data = _to_dict(item)
            shop = data.get("resolved_shop") or data.get("shop") or data
            shop_dict = _to_dict(shop)
            sid = str(shop_dict.get("shop_id", "")).strip()
            if sid:
                candidates.append(ResolvedCandidate(
                    shop_id=sid,
                    shop_name=str(shop_dict.get("shop_name", "")),
                    source=CandidateSource.CONTEXT,
                    rank=idx,
                    confidence=0.9,
                ))

        # 2. last_recommendation_list
        rec_list = state.get("last_recommendation_list") or []
        for idx, item in enumerate(rec_list):
            shop = _to_dict(item)
            sid = str(shop.get("shop_id", "")).strip()
            if sid:
                candidates.append(ResolvedCandidate(
                    shop_id=sid,
                    shop_name=str(shop.get("shop_name", "")),
                    source=CandidateSource.CONTEXT,
                    rank=len(candidates),
                    confidence=0.8,
                    raw=shop,
                ))

        # 3. current_shop
        cs = state.get("current_shop") or {}
        cs_dict = _to_dict(cs)
        cs_sid = str(cs_dict.get("shop_id", "")).strip()
        if cs_sid and not any(c.shop_id == cs_sid for c in candidates):
            candidates.append(ResolvedCandidate(
                shop_id=cs_sid,
                shop_name=str(cs_dict.get("shop_name", "")),
                source=CandidateSource.CONTEXT,
                rank=len(candidates),
                confidence=0.9,
            ))

        if not candidates:
            return CandidateSet(
                status=CandidateStatus.NOT_FOUND,
                source=CandidateSource.CONTEXT,
                candidates=[],
                requested_count=spec.limit or 1,
                min_required=1,
                max_allowed=spec.limit or 5,
            )

        return CandidateSet(
            status=CandidateStatus.RESOLVED,
            source=CandidateSource.CONTEXT,
            candidates=candidates,
            requested_count=spec.limit or len(candidates),
            min_required=1,
            max_allowed=spec.limit or 5,
        )

    # ------------------------------------------------------------------
    # Discovery resolution
    # ------------------------------------------------------------------

    def resolve_discovery(
        self,
        goal: Any,
        spec: CandidateSpec,
    ) -> CandidateSet:
        """Discover shops via search_shops.

        The spec.query or spec.category is used as the search query.
        Empty query returns NOT_FOUND.
        """
        query = spec.query or spec.category or ""
        if not query:
            return CandidateSet(
                status=CandidateStatus.NOT_FOUND,
                source=CandidateSource.DISCOVERY,
                candidates=[],
                requested_count=spec.limit or 1,
                min_required=1,
                max_allowed=spec.limit or SEARCH_LIMIT,
            )

        limit = spec.limit or SEARCH_LIMIT
        result = self._search_shops(query)
        data = result.get("data") or []
        if not isinstance(data, list):
            data = []

        candidates: list[ResolvedCandidate] = []
        for idx, item in enumerate(data):
            shop = _to_dict(item)
            sid = str(shop.get("shop_id", "")).strip()
            if not sid:
                continue
            candidates.append(ResolvedCandidate(
                shop_id=sid,
                shop_name=str(shop.get("shop_name", "")),
                source=CandidateSource.DISCOVERY,
                rank=idx,
                confidence=float(shop.get("confidence", 0.7)),
                rating=shop.get("rating"),
                distance_km=shop.get("distance_km"),
                raw=shop,
            ))

        if not candidates:
            return CandidateSet(
                status=CandidateStatus.NOT_FOUND,
                source=CandidateSource.DISCOVERY,
                candidates=[],
                warnings=["search_shops returned empty results"],
                requested_count=spec.limit or 1,
                min_required=1,
                max_allowed=spec.limit or SEARCH_LIMIT,
            )

        # Apply limit
        if limit and len(candidates) > limit:
            candidates = candidates[:limit]

        return CandidateSet(
            status=CandidateStatus.RESOLVED,
            source=CandidateSource.DISCOVERY,
            candidates=candidates,
            requested_count=spec.limit or len(candidates),
            min_required=1,
            max_allowed=spec.limit or SEARCH_LIMIT,
        )

    # ------------------------------------------------------------------
    # Mixed resolution
    # ------------------------------------------------------------------

    def resolve_mixed(
        self,
        goal: Any,
        spec: CandidateSpec,
        state: dict[str, Any] | None = None,
    ) -> CandidateSet:
        """Combine explicit mentions and discovery search results.

        Deduplicates by shop_id (explicit takes priority).
        """
        explicit_set = self.resolve_explicit(goal, spec)
        discovery_set = self.resolve_discovery(goal, spec)

        merged: list[ResolvedCandidate] = []
        seen_ids: set[str] = set()

        for c in (explicit_set.candidates or []):
            merged.append(c)
            if c.shop_id:
                seen_ids.add(c.shop_id)

        for c in (discovery_set.candidates or []):
            if c.shop_id and c.shop_id not in seen_ids:
                merged.append(c)
                seen_ids.add(c.shop_id)

        if not merged:
            return CandidateSet(
                status=CandidateStatus.NOT_FOUND,
                source=CandidateSource.MIXED,
                candidates=[],
                requested_count=spec.limit or 1,
                min_required=1,
                max_allowed=spec.limit or 5,
            )

        return CandidateSet(
            status=CandidateStatus.RESOLVED,
            source=CandidateSource.MIXED,
            candidates=merged,
            requested_count=spec.limit or len(merged),
            min_required=1,
            max_allowed=spec.limit or 5,
        )
