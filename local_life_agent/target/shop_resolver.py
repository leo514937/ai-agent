"""Unified facade for canonical shop entity resolution."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from ..domain.candidate import CandidateSource, CandidateSpec, GoalType, LocalLifeGoalDraft
from ..domain.shop_entity import (
    ShopCandidate,
    ShopResolutionResult,
    ShopResolutionSource,
    ShopResolutionStatus,
)
from ..tools import db_client
from ..tools.gateway import dispatch_tool_call
from .candidate_resolver import CandidateResolver
from .shop_name_normalizer import normalize_shop_record
from .shop_resolution_policy import decide_shop_resolution


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


def _shop_identity(shop: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_shop_record(shop)
    components = normalized.get("components") or {}
    return {
        "shop_id": str(shop.get("shop_id", "") or shop.get("id", "") or "").strip(),
        "shop_name": str(shop.get("shop_name", "") or shop.get("name", "") or "").strip(),
        "canonical_name": str(normalized.get("normalized_text", "") or "").strip(),
        "branch_name": str(components.get("branch_anchor", "") or "").strip(),
        "alias": list(dict.fromkeys(
            [
                str(shop.get("alias", "") or "").strip(),
                *[str(item or "").strip() for item in (shop.get("aliases", []) or []) if str(item or "").strip()],
            ]
        )),
        "raw": dict(shop),
    }


def _session_shop_ids(session_state: dict[str, Any] | Any | None, current_shop: dict[str, Any] | None = None) -> list[str]:
    ids: list[str] = []
    current = _to_dict(current_shop)
    if current.get("shop_id"):
        ids.append(str(current.get("shop_id")).strip())

    raw_session = _to_dict(session_state)
    current_shop_data = _to_dict(raw_session.get("current_shop"))
    if current_shop_data.get("shop_id"):
        ids.append(str(current_shop_data.get("shop_id")).strip())

    for item in raw_session.get("last_recommendation_list", []) or []:
        data = _to_dict(item)
        sid = str(data.get("shop_id", "")).strip()
        if sid:
            ids.append(sid)

    for item in raw_session.get("comparison_targets", []) or []:
        data = _to_dict(item)
        shop = data.get("resolved_shop") or data.get("shop") or data
        sid = str(_to_dict(shop).get("shop_id", "")).strip()
        if sid:
            ids.append(sid)

    for item in raw_session.get("canonical_shop_entities", []) or []:
        data = _to_dict(item)
        sid = str(data.get("shop_id", "")).strip()
        if sid:
            ids.append(sid)

    deduped: list[str] = []
    for sid in ids:
        if sid and sid not in deduped:
            deduped.append(sid)
    return deduped


def _candidate_to_shop_dict(candidate: Any) -> dict[str, Any]:
    data = _to_dict(candidate)
    raw = data.get("raw") or data.get("shop") or data.get("resolved_shop") or {}
    raw_dict = _to_dict(raw)
    if raw_dict:
        return raw_dict
    sid = str(data.get("shop_id", "")).strip()
    if sid:
        from ..tools import db_client as _db_client

        shop = _db_client.query_shop_by_id(sid)
        if isinstance(shop, dict):
            return dict(shop)
    return {
        "shop_id": str(data.get("shop_id", "")).strip(),
        "shop_name": str(data.get("shop_name", "")).strip(),
        "alias": list(data.get("alias", []) or []),
    }


def _results_from_candidate_set(
    candidate_set: Any,
    *,
    mention: str,
    session_state: dict[str, Any] | Any | None = None,
    current_shop: dict[str, Any] | None = None,
    user_location: dict[str, Any] | None = None,
) -> ShopResolutionResult:
    data = _to_dict(candidate_set)
    candidates: list[dict[str, Any]] = []
    for item in data.get("candidates", []) or []:
        shop = _candidate_to_shop_dict(item)
        if shop.get("shop_id") or shop.get("shop_name"):
            candidates.append(shop)

    session_shop_ids = _session_shop_ids(session_state, current_shop)
    source = ShopResolutionSource.candidate_resolver if candidates else ShopResolutionSource.reference
    if data.get("source"):
        try:
            source = ShopResolutionSource(str(data.get("source")))
        except Exception:
            pass

    result = decide_shop_resolution(
        mention=mention,
        shops=candidates,
        session_shop_ids=session_shop_ids,
        current_shop=_to_dict(current_shop),
        user_location=user_location,
        fuzzy_allowed=True,
        trace=list(data.get("trace", []) or []),
    )
    if data.get("status") and str(data.get("status")).lower() == "ambiguous" and result.status == ShopResolutionStatus.resolved:
        result.status = ShopResolutionStatus.ambiguous
        result.needs_clarification = True
        result.resolution_reason = str(data.get("reason", "") or result.resolution_reason or "ambiguous")
    if data.get("status") and str(data.get("status")).lower() == "not_found" and not candidates:
        result.status = ShopResolutionStatus.not_found
        result.needs_clarification = bool(mention)
        result.resolution_reason = str(data.get("reason", "") or "not_found")
    result.source = source
    if not result.candidates:
        result.candidates = [
            ShopCandidate(
                shop_id=str(item.get("shop_id", "") or "").strip(),
                shop_name=str(item.get("shop_name", "") or "").strip(),
                canonical_name=str(item.get("canonical_name", "") or "").strip(),
                branch_name=str(item.get("branch_name", "") or "").strip(),
                alias=list(item.get("alias", []) or []),
                score=float(item.get("score", 0.0) or 0.0),
                source=source,
                match_reason=str(item.get("match_reason", "") or ""),
                raw=dict(item.get("raw", {}) or item),
            )
            for item in candidates
            if str(item.get("shop_id", "") or "").strip() or str(item.get("shop_name", "") or "").strip()
        ]
    return result


def _build_candidate_resolver(resolve_shop_fn: Callable | None = None) -> CandidateResolver:
    return CandidateResolver(resolve_shop_fn=resolve_shop_fn or _gateway_resolve_shop)


def _gateway_resolve_shop(query: str, **kw: Any) -> dict[str, Any]:
    return resolve_shop(query, **kw)


def _mention_from_frame(semantic_frame: dict[str, Any] | Any | None) -> str:
    frame = _to_dict(semantic_frame)
    mentions = [str(item).strip() for item in frame.get("merchant_mentions", []) or [] if str(item).strip()]
    if mentions:
        return mentions[0]
    branch_mentions = [str(item).strip() for item in frame.get("branch_mentions", []) or [] if str(item).strip()]
    if branch_mentions:
        return branch_mentions[0]
    comparison_targets = frame.get("comparison_targets", []) or []
    for item in comparison_targets:
        data = _to_dict(item)
        query = str(data.get("shop_name", "") or data.get("source_text", "") or "").strip()
        if query:
            return query
    return ""


def _current_shop(session_state: dict[str, Any] | Any | None, current_shop: dict[str, Any] | None = None) -> dict[str, Any]:
    current = _to_dict(current_shop)
    if current.get("shop_id") or current.get("shop_name"):
        return current
    session = _to_dict(session_state)
    return _to_dict(session.get("current_shop"))


def _legacy_candidate_data(candidate_set: Any) -> dict[str, Any]:
    data = _to_dict(candidate_set)
    candidates: list[dict[str, Any]] = []
    for item in data.get("candidates", []) or []:
        shop = _candidate_to_shop_dict(item)
        if shop.get("shop_id") or shop.get("shop_name"):
            candidates.append(shop)
    return {
        "status": data.get("status", ""),
        "candidates": candidates,
        "source": data.get("source", ""),
        "reason": data.get("reason", ""),
        "trace": data.get("trace", []),
        "fuzzy_allowed": data.get("fuzzy_allowed", False),
    }


def _resolve_with_backend(
    mention: str,
    *,
    session_state: dict[str, Any] | Any | None = None,
    current_shop: dict[str, Any] | None = None,
    user_location: dict[str, Any] | None = None,
    semantic_frame: dict[str, Any] | Any | None = None,
    candidate_resolver: CandidateResolver | None = None,
) -> ShopResolutionResult:
    current = _current_shop(session_state, current_shop)
    mention = str(mention or "").strip()
    if not mention:
        if current.get("shop_id") and current.get("shop_name"):
            normalized = normalize_shop_record(current)
            components = normalized.get("components") or {}
            canonical_name = str(normalized.get("normalized_text", "") or current.get("shop_name", "") or "").strip()
            return ShopResolutionResult(
                status=ShopResolutionStatus.resolved,
                mention="",
                shop_id=str(current.get("shop_id", "") or "").strip(),
                shop_name=str(current.get("shop_name", "") or "").strip(),
                canonical_name=canonical_name,
                branch_name=str(components.get("branch_anchor", "") or ""),
                alias=list(dict.fromkeys(
                    [
                        str(current.get("alias", "") or "").strip(),
                        *[str(item or "").strip() for item in (current.get("aliases", []) or []) if str(item or "").strip()],
                    ]
                )),
                confidence=1.0,
                source=ShopResolutionSource.current_shop,
                resolution_reason="current_shop_inheritance",
                needs_clarification=False,
                candidates=[],
                selected_candidate=ShopCandidate(
                    shop_id=str(current.get("shop_id", "") or "").strip(),
                    shop_name=str(current.get("shop_name", "") or "").strip(),
                    canonical_name=canonical_name,
                    branch_name=str(components.get("branch_anchor", "") or ""),
                    alias=list(dict.fromkeys(
                        [
                            str(current.get("alias", "") or "").strip(),
                            *[str(item or "").strip() for item in (current.get("aliases", []) or []) if str(item or "").strip()],
                        ]
                    )),
                    score=1.0,
                    source=ShopResolutionSource.current_shop,
                    match_reason="current_shop",
                    raw=dict(current),
                ),
                candidate_count=1,
                trace=[{"mention": "", "result": "resolved_current_shop"}],
            )
        return ShopResolutionResult(
            status=ShopResolutionStatus.no_mention,
            mention="",
            resolution_reason="no_mention",
            needs_clarification=False,
            clarification_question="",
            candidate_count=0,
            trace=[{"mention": "", "result": "no_mention"}],
        )

    resolver = candidate_resolver or _build_candidate_resolver()
    frame = _to_dict(semantic_frame)
    task_type = str(frame.get("task_type", "") or "single_shop_query").strip()
    goal = LocalLifeGoalDraft(
        goal_type=GoalType.SINGLE_SHOP_QUERY,
        candidate_source=CandidateSource.EXPLICIT,
        requested_count=1,
        min_required=1,
        max_allowed=5,
        source_origin="facade",
    )
    spec = CandidateSpec(
        source=CandidateSource.EXPLICIT,
        query=mention,
        explicit_mentions=[mention],
        limit=5,
        context_ref=" ".join(
            [str(item).strip() for item in (frame.get("ordinal_references", []) or []) if str(item).strip()]
            + [str(item).strip() for item in (frame.get("deictic_references", []) or []) if str(item).strip()]
        ),
    )
    candidate_set = resolver.resolve(goal, spec, _to_dict(session_state))
    legacy_data = _legacy_candidate_data(candidate_set)
    candidate_shops = list(legacy_data.get("candidates", []))
    if not candidate_shops:
        fallback_result = _legacy_resolve_shop(mention, location=user_location, session_shop_ids=_session_shop_ids(session_state, current))
        legacy_result = _adapt_legacy_result(
            fallback_result,
            mention=mention,
            session_state=session_state,
            current_shop=current,
            user_location=user_location,
        )
        legacy_result.trace.append({"mention": mention, "result": "legacy_fallback"})
        return legacy_result

    result = decide_shop_resolution(
        mention=mention,
        shops=candidate_shops,
        task_type=task_type,
        session_shop_ids=_session_shop_ids(session_state, current),
        current_shop=current,
        user_location=user_location,
        fuzzy_allowed=False,
        trace=[{"mention": mention, "result": "candidate_resolver", "status": getattr(candidate_set, "status", "")}],
    )
    if result.status in {ShopResolutionStatus.ambiguous, ShopResolutionStatus.low_confidence, ShopResolutionStatus.not_found} and len(candidate_shops) == 1:
        single = _shop_identity(candidate_shops[0])
        result.shop_id = single["shop_id"]
        result.shop_name = single["shop_name"]
        result.canonical_name = single["canonical_name"]
        result.branch_name = single["branch_name"]
        result.alias = list(single["alias"] or [])
        result.selected_candidate = ShopCandidate(
            shop_id=single["shop_id"],
            shop_name=single["shop_name"],
            canonical_name=single["canonical_name"],
            branch_name=single["branch_name"],
            alias=list(single["alias"] or []),
            score=1.0,
            source=ShopResolutionSource.candidate_resolver,
            match_reason="single_candidate",
            raw=dict(single["raw"] or candidate_shops[0]),
        )
    return result


def _legacy_resolve_shop(query: str, **kw: Any) -> dict[str, Any]:
    params = dict(kw or {})
    params.setdefault("location", {})
    return dispatch_tool_call("resolve_shop", {"query": query, **params})


def _adapt_legacy_result(
    legacy: dict[str, Any],
    *,
    mention: str,
    session_state: dict[str, Any] | Any | None = None,
    current_shop: dict[str, Any] | None = None,
    user_location: dict[str, Any] | None = None,
) -> ShopResolutionResult:
    legacy = _to_dict(legacy)
    status_raw = str(legacy.get("status", "") or "").strip().upper()
    shop = _to_dict(legacy.get("shop") or legacy.get("resolved_shop") or legacy.get("data") or {})
    candidates = legacy.get("candidates") or []
    shop_list: list[dict[str, Any]] = []
    if shop.get("shop_id") or shop.get("shop_name"):
        shop_list.append(shop)
    for item in candidates:
        candidate = _to_dict(item.get("shop") if isinstance(item, dict) and item.get("shop") is not None else item)
        if candidate.get("shop_id") or candidate.get("shop_name"):
            shop_list.append(candidate)
    if not shop_list and status_raw == "RESOLVED":
        shop_list = [shop] if shop.get("shop_id") or shop.get("shop_name") else []

    result = decide_shop_resolution(
        mention=mention,
        shops=shop_list,
        session_shop_ids=_session_shop_ids(session_state, current_shop),
        current_shop=current_shop,
        user_location=user_location,
        fuzzy_allowed=True,
        trace=[{"mention": mention, "result": "legacy_result", "status": status_raw}],
    )
    if status_raw == "RESOLVED" and shop_list:
        result.status = ShopResolutionStatus.resolved
        result.resolution_reason = str(legacy.get("reason", "") or "legacy_resolved")
    elif status_raw == "AMBIGUOUS":
        result.status = ShopResolutionStatus.ambiguous
        result.needs_clarification = True
        result.resolution_reason = str(legacy.get("reason", "") or "legacy_ambiguous")
    elif status_raw in {"LOW_CONFIDENCE", "LOWCONFIDENCE"}:
        result.status = ShopResolutionStatus.low_confidence
        result.needs_clarification = True
        result.resolution_reason = str(legacy.get("reason", "") or "legacy_low_confidence")
    elif status_raw == "NOT_FOUND":
        result.status = ShopResolutionStatus.not_found
        result.needs_clarification = bool(mention)
        result.resolution_reason = str(legacy.get("reason", "") or "legacy_not_found")
        result.candidates = []
        result.selected_candidate = None
        result.candidate_count = 0
    if result.status == ShopResolutionStatus.resolved and shop_list:
        shop_dict = _shop_identity(shop_list[0])
        result.shop_id = shop_dict["shop_id"]
        result.shop_name = shop_dict["shop_name"]
        result.canonical_name = shop_dict["canonical_name"]
        result.branch_name = shop_dict["branch_name"]
        result.alias = list(shop_dict["alias"] or [])
        result.selected_candidate = ShopCandidate(
            shop_id=shop_dict["shop_id"],
            shop_name=shop_dict["shop_name"],
            canonical_name=shop_dict["canonical_name"],
            branch_name=shop_dict["branch_name"],
            alias=list(shop_dict["alias"] or []),
            score=1.0,
            source=ShopResolutionSource.reference,
            match_reason="legacy_resolve_shop",
            raw=dict(shop_list[0]),
        )
        converted_candidates: list[ShopCandidate] = []
        for item in shop_list:
            shop_dict = _shop_identity(item)
            converted_candidates.append(
                ShopCandidate(
                    shop_id=shop_dict["shop_id"],
                    shop_name=shop_dict["shop_name"],
                    canonical_name=shop_dict["canonical_name"],
                    branch_name=shop_dict["branch_name"],
                    alias=list(shop_dict["alias"] or []),
                    score=float(item.get("score", 1.0) or 1.0),
                    source=ShopResolutionSource.reference,
                    match_reason="legacy_candidate",
                    raw=dict(item),
                )
            )
        result.candidates = converted_candidates
        result.candidate_count = len(result.candidates)
    return result


def resolve_shop_entity(
    mention: str,
    *,
    session_state: dict[str, Any] | Any | None = None,
    current_shop: dict[str, Any] | None = None,
    user_location: dict[str, Any] | None = None,
    semantic_frame: dict[str, Any] | Any | None = None,
    candidate_resolver: CandidateResolver | None = None,
) -> ShopResolutionResult:
    """Resolve a single shop mention into the canonical entity layer."""
    return _resolve_with_backend(
        mention,
        session_state=session_state,
        current_shop=current_shop,
        user_location=user_location,
        semantic_frame=semantic_frame,
        candidate_resolver=candidate_resolver,
    )


def resolve_shop_entities(
    mentions: Iterable[str],
    *,
    session_state: dict[str, Any] | Any | None = None,
    current_shop: dict[str, Any] | None = None,
    user_location: dict[str, Any] | None = None,
    semantic_frame: dict[str, Any] | Any | None = None,
    candidate_resolver: CandidateResolver | None = None,
) -> list[ShopResolutionResult]:
    """Resolve multiple mentions independently."""
    results: list[ShopResolutionResult] = []
    for mention in mentions:
        text = str(mention or "").strip()
        if not text:
            continue
        results.append(
            resolve_shop_entity(
                text,
                session_state=session_state,
                current_shop=current_shop,
                user_location=user_location,
                semantic_frame=semantic_frame,
                candidate_resolver=candidate_resolver,
            )
        )
    return results


class ShopResolver:
    """Resolve a shop mention through the unified tool gateway."""

    def resolve(
        self,
        query: str,
        *,
        location: dict[str, float] | None = None,
        session_shop_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "query": query,
            "location": location,
            "session_shop_ids": session_shop_ids or [],
        }
        return dispatch_tool_call("resolve_shop", payload)


_SHOP_RESOLVER = ShopResolver()


def resolve_shop(
    query: str,
    *,
    location: dict[str, float] | None = None,
    session_shop_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Backward-compatible helper for callers that expect a function."""
    return _SHOP_RESOLVER.resolve(query, location=location, session_shop_ids=session_shop_ids)
