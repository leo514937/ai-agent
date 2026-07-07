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
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from ..config import SEARCH_LIMIT
from ..location_utils import normalize_location_payload
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
    from .shop_resolver import resolve_shop as canonical_resolve_shop

    params = dict(kw or {})
    params.setdefault("location", {})
    return canonical_resolve_shop(query, **params)


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


def _location_from_state(state: dict[str, Any] | None) -> dict[str, Any]:
    if not state:
        return {}
    from ..tools.db_tools import geocode_location

    for key in ("user_location", "user_context"):
        location = geocode_location(normalize_location_payload(state.get(key)))
        if location.get("lat") is not None and location.get("lng") is not None:
            return location
    semantic_frame = normalize_location_payload(state.get("semantic_frame"))
    location = geocode_location(semantic_frame.get("location"))
    if location.get("lat") is not None and location.get("lng") is not None:
        return location
    session = state.get("session_state_before") or state.get("session_state") or {}
    session_payload = normalize_location_payload(session)
    if session_payload:
        location = geocode_location(session_payload.get("location"))
        if location.get("lat") is not None and location.get("lng") is not None:
            return location
    return {}


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


@lru_cache(maxsize=1)
def _seed_shop_id_mapping() -> dict[str, str]:
    """Load the canonical shop-id mapping used by the local seed data."""
    mapping_path = Path(__file__).resolve().parents[2] / "db" / "seed" / "local_life" / "normalized_shop_id_mapping.json"
    try:
        raw = json.loads(mapping_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    mapping: dict[str, str] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            key_text = str(key or "").strip()
            value_text = str(value or "").strip()
            if key_text and value_text:
                mapping[key_text] = value_text
    return mapping


def _canonical_shop_record(shop: Any) -> dict[str, Any]:
    """Prefer canonical fixture/shop-table IDs for a resolved shop record."""

    shop_dict = _to_dict(shop)
    shop_name = str(shop_dict.get("shop_name", "") or "").strip()
    if not shop_name:
        return shop_dict

    shop_id = str(shop_dict.get("shop_id", "") or "").strip()
    seed_mapping = _seed_shop_id_mapping()
    mapped_id = seed_mapping.get(shop_id)
    if mapped_id:
        shop_dict = {**shop_dict, "shop_id": mapped_id}

    try:
        matches = db_client.query_all_shops()
    except Exception:
        matches = []
    if not matches:
        return shop_dict

    normalized_name = _normalize_shop_key(shop_name)
    exact_matches = [
        _to_dict(item)
        for item in matches
        if _normalize_shop_key(str(_to_dict(item).get("shop_name", "") or "")) == normalized_name
    ]
    if not exact_matches:
        return shop_dict

    def _rank(row: dict[str, Any]) -> tuple[int, int, str]:
        sid = str(row.get("shop_id", "") or "").strip()
        is_numeric = sid.isdigit()
        # Prefer canonical numeric ids over synthetic ids like shop_007.
        group = 0 if is_numeric and len(sid) >= 6 else 1 if is_numeric else 2 if sid.startswith("shop_") else 3
        numeric = int(sid) if is_numeric else 0
        return (group, numeric, sid)

    chosen = min(exact_matches, key=_rank)
    chosen_id = str(chosen.get("shop_id", "") or "").strip()
    if chosen_id:
        return chosen
    return shop_dict


def _canonicalize_candidates(candidates: list[ResolvedCandidate]) -> list[ResolvedCandidate]:
    """Normalize candidate shop ids/names to canonical catalog rows when possible."""

    normalized: list[ResolvedCandidate] = []
    for candidate in candidates:
        raw = _canonical_shop_record(candidate.raw or {"shop_id": candidate.shop_id, "shop_name": candidate.shop_name})
        sid = str(raw.get("shop_id", "") or candidate.shop_id).strip()
        shop_name = str(raw.get("shop_name", "") or candidate.shop_name).strip()
        normalized.append(
            ResolvedCandidate(
                shop_id=sid,
                shop_name=shop_name,
                source=candidate.source,
                rank=candidate.rank,
                confidence=candidate.confidence,
                raw=raw if raw else candidate.raw,
            )
        )
    return normalized


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


def _looks_like_specific_shop_mention(mention: str) -> bool:
    text = str(mention or "").strip()
    if not text:
        return False
    if any(token in text for token in ("(", "（", ")", "）")):
        return True
    return any(token in text for token in ("店", "馆", "轩", "居", "坊", "楼", "城", "中心", "广场"))


def _shop_name_fields(shop: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    """Return normalized name, branch, and alias fields for a shop row."""
    shop_name_fields = [
        str(shop.get("shop_name", "") or ""),
        str(shop.get("name", "") or ""),
    ]
    branch_fields = [
        str(shop.get("branch_name", "") or ""),
        str(shop.get("branch", "") or ""),
        str(shop.get("sub_name", "") or ""),
        str(shop.get("store_name", "") or ""),
        str(shop.get("branch_shop_name", "") or ""),
    ]
    alias_fields = [
        str(shop.get("alias", "") or ""),
        *[str(alias or "") for alias in (shop.get("aliases", []) or [])],
    ]
    return (
        [_normalize_shop_key(item) for item in shop_name_fields if _normalize_shop_key(item)],
        [_normalize_shop_key(item) for item in branch_fields if _normalize_shop_key(item)],
        [_normalize_shop_key(item) for item in alias_fields if _normalize_shop_key(item)],
    )


def _explicit_mention_variants(mention: str) -> list[str]:
    """Build conservative normalized variants for an explicit shop mention."""
    query = _normalize_shop_key(mention)
    if not query:
        return []

    variants = [query]
    suffixes = (
        "购物中心店",
        "购物中心",
        "商场店",
        "商场",
        "门店",
        "分店",
        "餐厅",
        "店铺",
        "店",
    )
    queue = [query]
    while queue:
        current = queue.pop(0)
        for suffix in suffixes:
            if current.endswith(suffix):
                shortened = current[: -len(suffix)]
                if shortened and shortened not in variants:
                    variants.append(shortened)
                    queue.append(shortened)
    return variants


def _local_explicit_match_groups(mention: str) -> dict[str, list[dict[str, Any]]]:
    """Resolve one explicit mention against the local shop table with strict priority."""
    query_variants = _explicit_mention_variants(mention)
    if not query_variants:
        return {"full_name": [], "branch_name": [], "alias_exact": [], "unique": [], "ambiguous": []}

    try:
        all_shops = db_client.query_all_shops()
    except Exception:
        all_shops = []

    full_name: list[dict[str, Any]] = []
    branch_name: list[dict[str, Any]] = []
    alias_exact: list[dict[str, Any]] = []
    fuzzy: list[dict[str, Any]] = []

    for shop in all_shops:
        shop_dict = _to_dict(shop)
        shop_id = str(shop_dict.get("shop_id", "") or "").strip()
        if not shop_id:
            continue

        name_fields, branch_fields, alias_fields = _shop_name_fields(shop_dict)
        if not name_fields and not alias_fields:
            continue

        combined_fields = [
            _normalize_shop_key(f"{name}{branch}")
            for name in name_fields
            for branch in branch_fields
            if name and branch
        ]

        if any(query in name_fields for query in query_variants):
            full_name.append(shop_dict)
            continue
        if any(query in combined_fields for query in query_variants):
            branch_name.append(shop_dict)
            continue
        if any(query in alias_fields for query in query_variants):
            alias_exact.append(shop_dict)
            continue

        candidate_texts = [*name_fields, *combined_fields, *alias_fields]
        if any(
            text and any(query in text or text in query for query in query_variants)
            for text in candidate_texts
        ):
            fuzzy.append(shop_dict)

    def _dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            shop_id = str(row.get("shop_id", "") or "").strip()
            if not shop_id or shop_id in seen:
                continue
            seen.add(shop_id)
            deduped.append(row)
        return deduped

    return {
        "full_name": _dedupe(full_name),
        "branch_name": _dedupe(branch_name),
        "alias_exact": _dedupe(alias_exact),
        "unique": _dedupe(fuzzy),
        "ambiguous": _dedupe([*full_name, *branch_name, *alias_exact, *fuzzy]),
    }


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
    """Try exact and high-confidence local catalog matches before gateway fallback."""
    groups = _local_explicit_match_groups(mention)
    ordered: list[dict[str, Any]] = []
    for bucket in ("full_name", "branch_name", "alias_exact", "unique"):
        for shop in groups.get(bucket, []) or []:
            shop_dict = _to_dict(shop)
            shop_id = str(shop_dict.get("shop_id", "") or "").strip()
            if shop_id and not any(str(existing.get("shop_id", "") or "").strip() == shop_id for existing in ordered):
                ordered.append(shop_dict)
    if len(ordered) == 1:
        return ordered
    if len(ordered) > 1 and any(bucket in {"full_name", "branch_name", "alias_exact"} for bucket in ("full_name", "branch_name", "alias_exact") if groups.get(bucket)):
        return ordered
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
        return self.resolve_discovery(goal, spec, state)

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
            local_groups = _local_explicit_match_groups(mention)
            if not _looks_like_specific_shop_mention(mention):
                ambiguous_local_matches = local_groups.get("ambiguous", []) or local_groups.get("unique", [])
                if len(ambiguous_local_matches) > 1:
                    for cand in ambiguous_local_matches:
                        sid = str(cand.get("shop_id", "")).strip()
                        if sid:
                            ambiguous_candidates.append(
                                ResolvedCandidate(
                                    shop_id=sid,
                                    shop_name=str(cand.get("shop_name", mention)),
                                    source=CandidateSource.EXPLICIT,
                                    rank=idx,
                                    confidence=0.6,
                                    raw=cand,
                                )
                            )
                    continue
            ordered_local_matches = (
                local_groups.get("full_name", [])
                or local_groups.get("branch_name", [])
                or local_groups.get("alias_exact", [])
                or local_groups.get("unique", [])
            )
            mention_key = _normalize_shop_key(mention)
            if len(ordered_local_matches) > 1:
                canonical_local_match = _canonical_shop_record(ordered_local_matches[0])
                canonical_key = _normalize_shop_key(str(canonical_local_match.get("shop_name", "") or ""))
                if canonical_key and canonical_key == mention_key:
                    sid = str(canonical_local_match.get("shop_id", "")).strip()
                    if sid:
                        candidates.append(
                            ResolvedCandidate(
                                shop_id=sid,
                                shop_name=str(canonical_local_match.get("shop_name", mention)),
                                source=CandidateSource.EXPLICIT,
                                rank=idx,
                                confidence=0.99,
                                raw=canonical_local_match,
                            )
                        )
                        continue
            if len(ordered_local_matches) == 1:
                shop = _canonical_shop_record(ordered_local_matches[0])
                sid = str(shop.get("shop_id", "")).strip()
                if sid:
                    candidates.append(
                        ResolvedCandidate(
                            shop_id=sid,
                            shop_name=str(shop.get("shop_name", mention)),
                            source=CandidateSource.EXPLICIT,
                            rank=idx,
                            confidence=0.99,
                            raw=shop,
                        )
                    )
                    continue
            if len(ordered_local_matches) > 1:
                for cand in ordered_local_matches:
                    sid = str(cand.get("shop_id", "")).strip()
                    if sid:
                        ambiguous_candidates.append(
                            ResolvedCandidate(
                                shop_id=sid,
                                shop_name=str(cand.get("shop_name", mention)),
                                source=CandidateSource.EXPLICIT,
                                rank=idx,
                                confidence=0.6,
                                raw=cand,
                            )
                        )
                continue

            exact_matches = _resolve_exact_shop_match(mention)
            if len(exact_matches) == 1:
                shop = _canonical_shop_record(exact_matches[0])
                sid = str(shop.get("shop_id", "")).strip()
                if sid:
                    candidates.append(
                        ResolvedCandidate(
                            shop_id=sid,
                            shop_name=str(shop.get("shop_name", mention)),
                            source=CandidateSource.EXPLICIT,
                            rank=idx,
                            confidence=0.99,
                            raw=shop,
                        )
                    )
                    continue
            if len(exact_matches) > 1:
                for cand in exact_matches:
                    sid = str(cand.get("shop_id", "")).strip()
                    if sid:
                        ambiguous_candidates.append(
                            ResolvedCandidate(
                                shop_id=sid,
                                shop_name=str(cand.get("shop_name", mention)),
                                source=CandidateSource.EXPLICIT,
                                rank=idx,
                                confidence=0.6,
                                raw=cand,
                            )
                        )
                continue

            result = _unwrap_resolve_shop_result(_to_dict(self._resolve_shop(mention, **kwargs)))
            status = str(result.get("status", "NOT_FOUND") or "NOT_FOUND")

            if status == "RESOLVED":
                shop = _canonical_shop_record(result.get("shop") or result.get("data") or {})
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
                    cand_dict = _canonical_shop_record(cand)
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
            merged = _canonicalize_candidates(merged)
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
            return CandidateSet(
                status=CandidateStatus.NOT_FOUND,
                source=CandidateSource.EXPLICIT,
                candidates=[],
                requested_count=spec.limit or len(mentions) or 1,
                min_required=1,
                max_allowed=spec.limit or 5,
            )

        candidates = _canonicalize_candidates(candidates)
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
        state: dict[str, Any] | None = None,
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
        location = _location_from_state(state)
        for query in query_variants:
            if limit and len(candidates) >= limit:
                break

            result = self._search_shops(query, location=location or None, limit=limit)
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
        discovery_set = self.resolve_discovery(goal, spec, state)

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
