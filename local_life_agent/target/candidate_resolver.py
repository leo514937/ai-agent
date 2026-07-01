"""CandidateResolver — resolves CandidateSpec into a CandidateSet.

Provides a single ``resolve()`` entry point that dispatches to the
appropriate resolution strategy based on the candidate source:
  - DISCOVERY  → search shops by category/query
  - EXPLICIT   → resolve specific shop mentions
  - CONTEXT    → use session context for recovery
  - MIXED      → combine explicit mentions + context
"""

from __future__ import annotations

import re
from typing import Any, Callable

from ..config import SEARCH_LIMIT
from ..tools import db_client
from ..domain.candidate import (
    CandidateSet,
    CandidateSource,
    CandidateSpec,
    CandidateStatus,
    ResolvedCandidate,
)


def _unwrap_resolve_shop_result(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    data = raw.get("data")
    if isinstance(data, dict) and "status" in data:
        return data
    return raw


def _default_resolve_shop(query: str, **kw: Any) -> dict[str, Any]:
    from ..engine import graph_builder as gb

    params = dict(kw or {})
    params.setdefault("location", {})
    return gb.resolve_shop(query, **params)


def _default_search_shops(query: str, **kw: Any) -> dict[str, Any]:
    from ..engine import graph_builder as gb

    result = gb.dispatch_tool_call("search_shops", {"query": query, **(kw or {})})
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


def _session_shop_ids(state: dict[str, Any] | None) -> list[str]:
    """Collect shop IDs from session context for follow-up resolution."""
    if not state:
        return []

    ids: list[str] = []
    current_shop = _to_dict(state.get("current_shop"))
    if current_shop.get("shop_id"):
        ids.append(str(current_shop.get("shop_id")).strip())

    for item in state.get("last_recommendation_list", []) or []:
        shop = _to_dict(item)
        sid = str(shop.get("shop_id", "")).strip()
        if sid:
            ids.append(sid)

    for item in state.get("comparison_targets", []) or []:
        data = _to_dict(item)
        shop = data.get("resolved_shop") or data.get("shop") or data
        shop_dict = _to_dict(shop)
        sid = str(shop_dict.get("shop_id", "")).strip()
        if sid:
            ids.append(sid)

    deduped: list[str] = []
    for sid in ids:
        if sid and sid not in deduped:
            deduped.append(sid)
    return deduped


def _normalize_shop_key(value: str) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = re.sub(r"[()\[\]{}（）【】\s、,，.。·\-_/]", "", text)
    return text


def _filter_discovery_candidates_by_mentions(
    candidates: list[ResolvedCandidate],
    mentions: list[str],
) -> list[ResolvedCandidate]:
    """Prefer discovery hits that actually contain the explicit shop mention."""
    if not candidates or not mentions:
        return []

    normalized_mentions = [_normalize_shop_key(mention) for mention in mentions if _normalize_shop_key(mention)]
    if not normalized_mentions:
        return []

    matched: list[ResolvedCandidate] = []
    for candidate in candidates:
        candidate_key = _normalize_shop_key(getattr(candidate, "shop_name", "") or "")
        if not candidate_key:
            continue
        if any(
            mention_key == candidate_key
            or mention_key in candidate_key
            or candidate_key in mention_key
            for mention_key in normalized_mentions
        ):
            matched.append(candidate)

    return matched


def _resolve_exact_shop_match(mention: str) -> list[dict[str, Any]]:
    """Try an exact catalog lookup before falling back to gateway search.

    This keeps explicit single-shop mentions narrow when the query already
    names the exact shop, while preserving the normal tool path for fuzzy
    recovery.
    """
    query = str(mention or "").strip()
    if not query:
        return []

    try:
        matches = db_client.query_shop_by_name(query)
    except Exception:
        return []

    exact_matches: list[dict[str, Any]] = []
    for shop in matches:
        shop_dict = _to_dict(shop)
        if _normalize_shop_key(str(shop_dict.get("shop_name", "") or "")) == _normalize_shop_key(query):
            exact_matches.append(shop_dict)
    if exact_matches:
        return exact_matches
    if len(matches) == 1:
        return [_to_dict(matches[0])]
    return []


def _normalize_discovery_query(query: str) -> str:
    """Strip common human modifiers from discovery-style queries."""
    q = str(query or "").strip()
    if not q:
        return ""

    q = q.replace("，", " ").replace(",", " ").replace("。", " ").replace("、", " ")
    tokens = [token for token in q.split() if token.strip()]
    if len(tokens) > 1:
        stop_prefixes = {
            "附近",
            "周边",
            "周围",
            "推荐",
            "推荐几家",
            "附近有没有",
            "附近推荐",
            "附近推荐几家",
            "约会",
            "便宜一点的",
            "便宜一点",
            "便宜点",
            "更便宜",
            "最好有券",
            "最好有券的",
            "现在营业",
            "现在开门",
            "营业",
            "这家",
            "这三家",
            "第一家",
            "第二家",
            "第三家",
        }
        while len(tokens) > 1 and tokens[0] in stop_prefixes:
            tokens.pop(0)
        if len(tokens) > 1 and tokens[0].endswith("的呢"):
            tokens.pop(0)
        q = " ".join(tokens).strip()
    return q


def _discovery_query_variants(query: str) -> list[str]:
    """Build fallback discovery queries from a combined human query."""
    normalized = _normalize_discovery_query(query)
    if not normalized:
        return []

    stop_terms = {
        "附近",
        "周边",
        "周围",
        "推荐",
        "推荐几家",
        "附近有没有",
        "附近推荐",
        "附近推荐几家",
        "约会",
        "便宜一点的",
        "便宜一点",
        "便宜点",
        "更便宜",
        "最好有券",
        "最好有券的",
        "现在营业",
        "现在开门",
        "营业",
        "这家",
        "这三家",
        "第一家",
        "第二家",
        "第三家",
    }

    variants: list[str] = [normalized]
    tokens = [token for token in normalized.split() if token.strip()]
    for token in tokens:
        if token in stop_terms:
            continue
        if token not in variants:
            variants.append(token)
    return variants


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
            return self.resolve_explicit(goal, spec, state)
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
        state: dict[str, Any] | None = None,
    ) -> CandidateSet:
        """Resolve explicit shop mentions via resolve_shop.

        AMBIGUOUS mentions remain ambiguous and must be clarified.
        NOT_FOUND mentions are skipped.
        """
        if state:
            semantic_frame = _to_dict(state.get("semantic_frame"))
            if str(state.get("error_code", "") or "") == "SCHEMA_VALIDATION_FAILED" or semantic_frame.get("shop_id") or semantic_frame.get("tool_name"):
                return CandidateSet(
                    status=CandidateStatus.NOT_FOUND,
                    source=CandidateSource.EXPLICIT,
                    candidates=[],
                    requested_count=spec.limit or 1,
                    min_required=1,
                    max_allowed=spec.limit or 5,
                )
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
        session_shop_id_list = _session_shop_ids(state)
        for idx, mention in enumerate(mentions):
            kwargs: dict[str, Any] = {}
            if session_shop_id_list:
                kwargs["session_shop_ids"] = session_shop_id_list
            exact_matches = _resolve_exact_shop_match(mention)
            if len(exact_matches) == 1:
                shop = exact_matches[0]
                sid = str(shop.get("shop_id", "")).strip()
                if sid:
                    candidates.append(ResolvedCandidate(
                        shop_id=sid,
                        shop_name=str(shop.get("shop_name", mention)),
                        source=CandidateSource.EXPLICIT,
                        rank=idx,
                        confidence=0.99,
                        raw=shop,
                    ))
                    continue
            if len(exact_matches) > 1:
                for cand in exact_matches:
                    sid = str(cand.get("shop_id", "")).strip()
                    if sid:
                        ambiguous_candidates.append(ResolvedCandidate(
                            shop_id=sid,
                            shop_name=str(cand.get("shop_name", mention)),
                            source=CandidateSource.EXPLICIT,
                            rank=idx,
                            confidence=0.6,
                            raw=cand,
                        ))
                continue

            result = _unwrap_resolve_shop_result(_to_dict(self._resolve_shop(mention, **kwargs)))
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

        if ambiguous_candidates:
            merged: list[ResolvedCandidate] = []
            for item in [*candidates, *ambiguous_candidates]:
                if not any(existing.shop_id == item.shop_id for existing in merged):
                    merged.append(item)
            if len(mentions) >= 2:
                return CandidateSet(
                    status=CandidateStatus.RESOLVED,
                    source=CandidateSource.EXPLICIT,
                    candidates=merged,
                    warnings=["comparison_explicit_ambiguity_tolerated"],
                    requested_count=spec.limit or len(merged) or 1,
                    min_required=2,
                    max_allowed=spec.limit or 5,
                )
            return CandidateSet(
                status=CandidateStatus.AMBIGUOUS,
                source=CandidateSource.EXPLICIT,
                candidates=merged,
                requested_count=spec.limit or len(merged) or 1,
                min_required=2,
                max_allowed=spec.limit or 5,
            )

        if not candidates:
            fallback_query = spec.query or spec.category or " ".join(mentions)
            if fallback_query.strip():
                fallback_spec = CandidateSpec(
                    source=CandidateSource.DISCOVERY,
                    category=spec.category,
                    query=fallback_query,
                    location_scope=spec.location_scope,
                    sort_by=list(spec.sort_by or []),
                    limit=spec.limit,
                    explicit_mentions=[],
                    context_ref=spec.context_ref,
                    filters=dict(spec.filters or {}),
                    ranking_signals=dict(spec.ranking_signals or {}),
                )
                discovery_set = self.resolve_discovery(goal, fallback_spec)
                if discovery_set.status == CandidateStatus.RESOLVED and discovery_set.candidates:
                    matched_candidates = _filter_discovery_candidates_by_mentions(
                        list(discovery_set.candidates or []),
                        list(mentions),
                    )
                    if matched_candidates:
                        return CandidateSet(
                            status=CandidateStatus.RESOLVED,
                            source=CandidateSource.MIXED,
                            candidates=matched_candidates,
                            warnings=["explicit_not_found_fallback_to_discovery"],
                            original_spec=spec,
                            requested_count=spec.limit or len(matched_candidates),
                            min_required=1,
                            max_allowed=spec.limit or 5,
                        )
                    return CandidateSet(
                        status=CandidateStatus.RESOLVED,
                        source=CandidateSource.MIXED,
                        candidates=discovery_set.candidates,
                        warnings=["explicit_not_found_fallback_to_discovery"],
                        original_spec=spec,
                        requested_count=spec.limit or len(discovery_set.candidates),
                        min_required=1,
                        max_allowed=spec.limit or 5,
                    )
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
        context_ref = str(getattr(spec, "context_ref", "") or "").strip()
        single_deictic = any(h in context_ref for h in ("这家", "它", "那家", "这间", "那间"))

        # 1. comparison_targets
        ct = state.get("comparison_targets") or []
        for idx, item in enumerate(ct):
            data = _to_dict(item)
            shop = data.get("resolved_shop") or data.get("shop") or data
            shop_dict = _to_dict(shop)
            sid = str(shop_dict.get("shop_id", "")).strip()
            if sid and not any(c.shop_id == sid for c in candidates):
                candidates.append(ResolvedCandidate(
                    shop_id=sid,
                    shop_name=str(shop_dict.get("shop_name", "")),
                    source=CandidateSource.CONTEXT,
                    rank=idx,
                    confidence=0.9,
                ))

        comparison_resolution = state.get("comparison_target_resolution") if isinstance(state, dict) else None
        comparison_resolution_status = str(_to_dict(comparison_resolution).get("status", "") or "").upper()
        goal_type = getattr(getattr(goal, "goal_type", None), "value", getattr(goal, "goal_type", None))
        if goal_type == "comparison" and comparison_resolution_status:
            if candidates:
                return CandidateSet(
                    status=CandidateStatus.RESOLVED,
                    source=CandidateSource.CONTEXT,
                    candidates=candidates,
                    requested_count=spec.limit or len(candidates),
                    min_required=2,
                    max_allowed=spec.limit or 5,
                )
            return CandidateSet(
                status=CandidateStatus.NOT_FOUND,
                source=CandidateSource.CONTEXT,
                candidates=[],
                requested_count=spec.limit or 1,
                min_required=2,
                max_allowed=spec.limit or 5,
            )

        # 2. last_recommendation_list
        if not single_deictic:
            rec_list = state.get("last_recommendation_list") or []
            for idx, item in enumerate(rec_list):
                shop = _to_dict(item)
                sid = str(shop.get("shop_id", "")).strip()
                if sid and not any(c.shop_id == sid for c in candidates):
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
        query_variants = _discovery_query_variants(spec.query or spec.category or "")
        if not query_variants:
            return CandidateSet(
                status=CandidateStatus.NOT_FOUND,
                source=CandidateSource.DISCOVERY,
                candidates=[],
                requested_count=spec.limit or 1,
                min_required=1,
                max_allowed=spec.limit or SEARCH_LIMIT,
            )

        limit = spec.limit or SEARCH_LIMIT
        candidates: list[ResolvedCandidate] = []
        seen_shop_ids: set[str] = set()
        for query in query_variants:
            if limit and len(candidates) >= limit:
                break

            result = self._search_shops(query)
            data = result.get("data") or []
            if not isinstance(data, list):
                data = []

            for item in data:
                shop = _to_dict(item)
                sid = str(shop.get("shop_id", "")).strip()
                if not sid or sid in seen_shop_ids:
                    continue
                candidates.append(ResolvedCandidate(
                    shop_id=sid,
                    shop_name=str(shop.get("shop_name", "")),
                    source=CandidateSource.DISCOVERY,
                    rank=len(candidates),
                    confidence=float(shop.get("confidence", 0.7)),
                    rating=shop.get("rating"),
                    distance_km=shop.get("distance_km"),
                    raw=shop,
                ))
                seen_shop_ids.add(sid)
                if limit and len(candidates) >= limit:
                    break

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
        explicit_set = self.resolve_explicit(goal, spec, state)
        context_set = self.resolve_context(goal, spec, state)
        discovery_set = self.resolve_discovery(goal, spec)

        merged: list[ResolvedCandidate] = []
        seen_ids: set[str] = set()

        for c in (context_set.candidates or []):
            if c.shop_id and c.shop_id not in seen_ids:
                merged.append(c)
                seen_ids.add(c.shop_id)

        for c in (explicit_set.candidates or []):
            if c.shop_id and c.shop_id not in seen_ids:
                merged.append(c)
                seen_ids.add(c.shop_id)

        comparison_resolution = state.get("comparison_target_resolution") if isinstance(state, dict) else None
        comparison_resolution_status = str(_to_dict(comparison_resolution).get("status", "") or "").upper()
        if getattr(getattr(goal, "goal_type", None), "value", getattr(goal, "goal_type", None)) == "comparison" and comparison_resolution_status:
            if not merged:
                return CandidateSet(
                    status=CandidateStatus.NOT_FOUND,
                    source=CandidateSource.MIXED,
                    candidates=[],
                    requested_count=spec.limit or 1,
                    min_required=2,
                    max_allowed=spec.limit or 5,
                )
            return CandidateSet(
                status=CandidateStatus.RESOLVED,
                source=CandidateSource.MIXED,
                candidates=merged,
                requested_count=spec.limit or len(merged),
                min_required=2,
                max_allowed=spec.limit or 5,
            )

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
