"""Reference resolver for multi-turn context and anaphora."""

from __future__ import annotations

import re
from typing import Any

from .. import config
from ..domain.schemas import ComparisonTargetResolution
from ..domain.state import SessionState


def _unwrap_resolve_shop_result(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    data = raw.get("data")
    if isinstance(data, dict) and "status" in data:
        return data
    return raw

_SINGLE_DEICTIC_HINTS = ("这家", "它", "那家", "这间", "那间")
_LIST_DEICTIC_HINTS = ("这三家", "这几家", "这几间", "这些", "上面这些", "刚才这几家", "这几个", "这三个")
_ORDINAL_RE = re.compile(r"第\s*([1-9一二三四五六七八九十])\s*(个|家|间|店)?")
_LIST_COUNT_RE = re.compile(r"(这|前)\s*([1-9]\d*|[一二两三四五六七八九十]+)\s*(家|个|间)")

_CHINESE_TO_INT = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def _session_get(session_state: dict | SessionState | None, field: str) -> Any:
    if session_state is None:
        return None
    if isinstance(session_state, SessionState):
        return getattr(session_state, field, None)
    if isinstance(session_state, dict):
        return session_state.get(field)
    return getattr(session_state, field, None)


def _shop_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    return dict(value) if isinstance(value, dict) else {}


def _recommendation_candidates(session_state: dict | SessionState | None) -> list[dict[str, Any]]:
    raw = _session_get(session_state, "last_recommendation_list") or []
    candidates: list[dict[str, Any]] = []
    for item in raw:
        shop = _shop_dict(item)
        if shop.get("shop_id") and shop.get("shop_name"):
            candidates.append(shop)
    return candidates


def _current_shop(session_state: dict | SessionState | None) -> dict[str, Any]:
    return _shop_dict(_session_get(session_state, "current_shop"))


def _frame_dict(semantic_frame: dict | Any | None) -> dict[str, Any]:
    return _shop_dict(semantic_frame)


def _parse_number_token(raw: str) -> int | None:
    token = str(raw or "").strip()
    if not token:
        return None
    if token.isdigit():
        return int(token)
    return _CHINESE_TO_INT.get(token)


def _parse_ordinal(text: str) -> int | None:
    compact = text.replace(" ", "")
    match = _ORDINAL_RE.search(compact)
    if not match:
        return None
    return _parse_number_token(match.group(1))


def _parse_list_size(text: str) -> int | None:
    compact = text.replace(" ", "")
    if "这三家" in compact:
        return 3
    match = _LIST_COUNT_RE.search(compact)
    if not match:
        return None
    return _parse_number_token(match.group(2))


def _resolved_target(shop: dict[str, Any], *, source: str, source_ref: str) -> dict[str, Any]:
    return {
        "shop_id": str(shop.get("shop_id", "")).strip(),
        "shop_name": str(shop.get("shop_name", "")).strip(),
        "source": source,
        "source_ref": source_ref,
    }


def _comparison_shop(shop: dict[str, Any]) -> dict[str, Any]:
    return {
        "shop_id": str(shop.get("shop_id", "")).strip(),
        "shop_name": str(shop.get("shop_name", "")).strip(),
    }


def _append_unique(targets: list[dict[str, Any]], target: dict[str, Any]) -> None:
    shop_id = str(target.get("shop_id", "")).strip()
    shop_name = str(target.get("shop_name", "")).strip()
    if not shop_id and not shop_name:
        return
    key = shop_id or shop_name
    if any((str(item.get("shop_id", "")).strip() or str(item.get("shop_name", "")).strip()) == key for item in targets):
        return
    targets.append(target)


def _resolve_ordinal_reference(reference: str, session_state: dict | SessionState | None) -> dict[str, Any]:
    index = _parse_ordinal(reference)
    candidates = _recommendation_candidates(session_state)
    if index is None:
        return {"status": "unresolved", "reason": "ordinal_not_detected", "source_ref": reference}
    if 1 <= index <= len(candidates):
        return {
            "status": "resolved",
            "reason": "ordinal_reference",
            "target": _comparison_shop(
                candidates[index - 1],
            ),
        }
    return {
        "status": "out_of_range",
        "reason": "ordinal_out_of_range",
        "requested_index": index,
        "candidate_count": len(candidates),
        "source_ref": reference,
    }


def _resolve_deictic_reference(reference: str, session_state: dict | SessionState | None) -> dict[str, Any]:
    compact = str(reference or "").strip()
    recommendation_candidates = _recommendation_candidates(session_state)
    is_list = (compact in _LIST_DEICTIC_HINTS) or bool(_LIST_COUNT_RE.search(compact))
    if is_list:
        count = _parse_list_size(compact)
        selected = recommendation_candidates[:count] if count else recommendation_candidates
        if selected:
            return {
                "status": "resolved_list",
                "reason": "recommendation_list_reference",
                "targets": [_comparison_shop(shop) for shop in selected],
            }
        return {
            "status": "ambiguous",
            "reason": "list_reference_without_recommendations",
            "source_ref": compact,
        }
    if compact in _SINGLE_DEICTIC_HINTS:
        current_shop = _current_shop(session_state)
        if current_shop.get("shop_id") and current_shop.get("shop_name"):
            return {
                "status": "resolved",
                "reason": "current_shop_reference",
                "target": _comparison_shop(current_shop),
            }
        return {
            "status": "ambiguous",
            "reason": "pronoun_without_current_shop",
            "source_ref": compact,
        }
    return {"status": "unresolved", "reason": "deictic_not_detected", "source_ref": compact}


def resolve_comparison_targets(
    text: str,
    session_state: dict | SessionState | None,
    semantic_frame: dict | Any | None = None,
) -> dict[str, Any]:
    """Resolve multi-target comparison references from semantic structure first."""
    frame = _frame_dict(semantic_frame)
    merchant_mentions = [str(item).strip() for item in frame.get("merchant_mentions", []) or [] if str(item).strip()]
    explicit_mention_count = len(merchant_mentions)
    targets: list[dict[str, Any]] = []
    unresolved_targets: list[dict[str, Any]] = []
    resolved_explicit_queries: set[str] = set()
    comparison_targets = frame.get("comparison_targets", []) or []
    ordinal_references = [str(item).strip() for item in frame.get("ordinal_references", []) or [] if str(item).strip()]
    deictic_references = [str(item).strip() for item in frame.get("deictic_references", []) or [] if str(item).strip()]
    reference_mentions = [str(item).strip() for item in frame.get("reference_mentions", []) or [] if str(item).strip()]

    def _resolve_explicit(query: str) -> dict[str, Any]:
        try:
            from ..engine import graph_builder as _graph_builder
        except Exception:
            return {"status": "NOT_FOUND", "error_code": "SHOP_RESOLVE_FAILED"}
        try:
            return _unwrap_resolve_shop_result(_graph_builder.resolve_shop(query, location={}))
        except Exception:
            return {"status": "NOT_FOUND", "error_code": "SHOP_RESOLVE_FAILED"}

    if not comparison_targets:
        comparison_targets = []
        for token in ordinal_references:
            comparison_targets.append({"reference": "ordinal", "source_text": token, "shop_name": token})
        for token in deictic_references:
            comparison_targets.append({"reference": "deictic", "source_text": token, "shop_name": token})
        for token in reference_mentions:
            if _parse_ordinal(token) is not None:
                comparison_targets.append({"reference": "ordinal", "source_text": token, "shop_name": token})
                continue
            if token in _SINGLE_DEICTIC_HINTS or token in _LIST_DEICTIC_HINTS or token.startswith("这") or token.startswith("那"):
                comparison_targets.append({"reference": "deictic", "source_text": token, "shop_name": token})
        if not comparison_targets:
            compact_text = str(text or "").replace(" ", "")
            for match in _ORDINAL_RE.finditer(compact_text):
                token = match.group(0).strip()
                if token:
                    comparison_targets.append({"reference": "ordinal", "source_text": token, "shop_name": token})
            for token in _LIST_DEICTIC_HINTS + _SINGLE_DEICTIC_HINTS:
                if token in compact_text:
                    comparison_targets.append({
                        "reference": "deictic",
                        "source_text": token,
                        "shop_name": token,
                    })

    for item in comparison_targets:
        target = _shop_dict(item)
        reference_type = str(target.get("reference", "")).strip()
        source_ref = str(target.get("source_text", "") or target.get("shop_name", "")).strip()
        if reference_type == "explicit":
            query = str(target.get("shop_name", "")).strip()
            if not query:
                continue
            resolved = _resolve_explicit(query)
            status = str(resolved.get("status", "") or "").upper()
            if status == "RESOLVED":
                shop = resolved.get("shop") or resolved.get("resolved_shop") or {}
                _append_unique(targets, _comparison_shop(_shop_dict(shop)))
                resolved_explicit_queries.add(query)
                continue
            if status == "AMBIGUOUS":
                cand_list = resolved.get("candidates") or []
                if cand_list:
                    for cand in cand_list:
                        cand_dict = _shop_dict(cand.get("shop") if isinstance(cand, dict) else cand)
                        _append_unique(targets, _comparison_shop(cand_dict))
                unresolved_targets.append(
                    {
                        "reference": "explicit",
                        "query": query,
                        "source_ref": source_ref,
                        "candidates": [
                            _comparison_shop(_shop_dict(cand.get("shop") if isinstance(cand, dict) else cand))
                            for cand in cand_list
                            if _shop_dict(cand.get("shop") if isinstance(cand, dict) else cand)
                        ],
                    }
                )
                return ComparisonTargetResolution(
                    status="NEED_CLARIFICATION",
                    targets=targets,
                    unresolved_targets=unresolved_targets,
                    ambiguous_target={"source_ref": source_ref, "reference": reference_type},
                    reason=str(resolved.get("reason", "comparison_reference_ambiguous")),
                    prompt="请明确你说的是哪家店。",
                ).model_dump()
            unresolved_targets.append(
                {"reference": "explicit", "query": query, "source_ref": source_ref}
            )
            continue
        if reference_type == "ordinal":
            resolved = _resolve_ordinal_reference(source_ref, session_state)
        elif reference_type == "deictic":
            resolved = _resolve_deictic_reference(source_ref, session_state)
        else:
            continue
        status = resolved.get("status")
        if status == "resolved":
            _append_unique(targets, _comparison_shop(_shop_dict(resolved.get("target", {}))))
            continue
        if status == "resolved_list":
            for candidate in resolved.get("targets", []) or []:
                _append_unique(targets, _comparison_shop(_shop_dict(candidate)))
            continue
        if status == "ambiguous":
            return ComparisonTargetResolution(
                status="NEED_CLARIFICATION",
                targets=targets,
                unresolved_targets=unresolved_targets,
                ambiguous_target={"source_ref": source_ref, "reference": reference_type},
                reason=str(resolved.get("reason", "comparison_reference_ambiguous")),
                prompt="请明确你说的是哪家店。",
            ).model_dump()
        if status == "out_of_range":
            return ComparisonTargetResolution(
                status="NOT_FOUND",
                targets=targets,
                unresolved_targets=unresolved_targets,
                ambiguous_target={"source_ref": source_ref, "reference": reference_type},
                reason=str(resolved.get("reason", "ordinal_out_of_range")),
                prompt="引用的店铺编号超出了上一次推荐范围。",
            ).model_dump()

    for query in frame.get("merchant_mentions", []) or []:
        query_text = str(query or "").strip()
        if not query_text:
            continue
        if query_text in resolved_explicit_queries:
            continue
        if any(
            query_text == str(item.get("shop_name", "")).strip()
            or query_text == str(item.get("shop_name", "")).strip().split("(", 1)[0].strip()
            for item in targets
        ):
            continue
        resolved = _resolve_explicit(query_text)
        status = str(resolved.get("status", "") or "").upper()
        if status == "RESOLVED":
            shop = resolved.get("shop") or resolved.get("resolved_shop") or {}
            _append_unique(targets, _comparison_shop(_shop_dict(shop)))
            resolved_explicit_queries.add(query_text)
            continue
        if status == "AMBIGUOUS":
            cand_list = resolved.get("candidates") or []
            if cand_list:
                for cand in cand_list:
                    cand_dict = _shop_dict(cand.get("shop") if isinstance(cand, dict) else cand)
                    _append_unique(targets, _comparison_shop(cand_dict))
            unresolved_targets.append(
                {
                    "reference": "explicit",
                    "query": query_text,
                    "source_ref": query_text,
                    "candidates": [
                        _comparison_shop(_shop_dict(cand.get("shop") if isinstance(cand, dict) else cand))
                        for cand in cand_list
                        if _shop_dict(cand.get("shop") if isinstance(cand, dict) else cand)
                    ],
                }
            )
            if explicit_mention_count < 2:
                return ComparisonTargetResolution(
                    status="NEED_CLARIFICATION",
                    targets=targets,
                    unresolved_targets=unresolved_targets,
                    ambiguous_target={"source_ref": query_text, "reference": "explicit"},
                    reason=str(resolved.get("reason", "comparison_reference_ambiguous")),
                    prompt="请明确你说的是哪家店。",
                ).model_dump()
            if not any(item.get("query") == query_text for item in unresolved_targets):
                unresolved_targets.append({"reference": "explicit", "query": query_text, "source_ref": query_text})

    deduped_count = len(targets)
    if deduped_count > config.COMPARISON_MAX_SHOP_LIMIT:
        return ComparisonTargetResolution(
            status="TOO_MANY",
            targets=targets,
            unresolved_targets=unresolved_targets,
            reason="comparison_too_many_shops",
            prompt="最多支持 5 家店对比，请缩小范围后再试。",
        ).model_dump()
    if unresolved_targets:
        if deduped_count == 0:
            return ComparisonTargetResolution(
                status="NEED_CLARIFICATION",
                targets=[],
                unresolved_targets=unresolved_targets,
                reason=str(unresolved_targets[0].get("reason", "") or "comparison_targets_need_clarification"),
                prompt="请明确你说的是哪家店。",
            ).model_dump()
        if deduped_count >= 2 and explicit_mention_count >= 2:
            return ComparisonTargetResolution(
                status="RESOLVED",
                targets=targets,
                unresolved_targets=[],
                reason="comparison_targets_resolved",
            ).model_dump()
        return ComparisonTargetResolution(
            status="NEED_CLARIFICATION",
            targets=targets,
            unresolved_targets=unresolved_targets,
            reason="comparison_targets_need_clarification",
            prompt="请明确你说的是哪家店。",
        ).model_dump()
    if deduped_count == 1:
        return ComparisonTargetResolution(
            status="NEED_CLARIFICATION",
            targets=targets,
            unresolved_targets=[],
            reason="comparison_requires_at_least_two_shops",
            prompt="对比至少需要两家不同的店，请补充另一家店名。",
        ).model_dump()
    if deduped_count >= 2:
        return ComparisonTargetResolution(
            status="RESOLVED",
            targets=targets,
            unresolved_targets=[],
            reason="comparison_targets_resolved",
        ).model_dump()
    if deduped_count == 0 and not unresolved_targets:
        return ComparisonTargetResolution(
            status="NOT_FOUND",
            targets=[],
            unresolved_targets=[],
            reason="comparison_targets_missing",
        ).model_dump()
    return ComparisonTargetResolution(
        status="PARTIAL",
        targets=targets,
        unresolved_targets=unresolved_targets,
        reason="comparison_targets_partial",
    ).model_dump()


def _semantic_frame_has_reference_fields(frame: dict[str, Any]) -> bool:
    """Check whether the semantic frame provides explicit reference fields."""
    ordinal = frame.get("ordinal_references") or []
    deictic = frame.get("deictic_references") or []
    mentions = frame.get("merchant_mentions") or []
    targets = frame.get("comparison_targets") or []
    return bool(ordinal or deictic or mentions or targets)


def resolve_references(
    text: str,
    session_state: dict | SessionState | None,
    semantic_frame: dict | Any | None = None,
) -> dict[str, Any]:
    """Resolve ordinal or pronoun references using the session context.

    When the semantic_frame provides explicit reference fields, those are
    consumed first.  The raw-text fallback (re-parsing the original text)
    is only used when the frame had no reference fields at all — this
    avoids duplicate semantic parsing of raw_text that was already
    handled upstream.
    """
    frame = _frame_dict(semantic_frame)
    if str(frame.get("shop_id", "") or "") or str(frame.get("tool_name", "") or "") or str(frame.get("error_code", "") or "") == "SCHEMA_VALIDATION_FAILED":
        return {"status": "unresolved", "reason": "forbidden_semantic_frame", "resolution_source": "semantic_frame"}
    ordinal_refs = [str(item).strip() for item in frame.get("ordinal_references", []) or [] if str(item).strip()]
    deictic_refs = [str(item).strip() for item in frame.get("deictic_references", []) or [] if str(item).strip()]

    # Track whether the semantic frame provided explicit reference fields
    has_semantic_refs = _semantic_frame_has_reference_fields(frame)

    if ordinal_refs:
        result = _resolve_ordinal_reference(ordinal_refs[0], session_state)
        result["resolution_source"] = "semantic_frame"
        return result
    for reference in deictic_refs:
        resolved = _resolve_deictic_reference(reference, session_state)
        if resolved.get("status") != "unresolved":
            resolved["resolution_source"] = "semantic_frame"
            return resolved

    # When the semantic frame explicitly provided reference fields that
    # yielded no resolution, trust the frame and do NOT fall back to raw-text
    # re-parsing. This prevents duplicate processing of input that the
    # semantic parser already handled.
    if has_semantic_refs:
        return {"status": "unresolved", "reason": "no_reference_detected", "resolution_source": "semantic_frame"}

    # Fall back to raw-text parsing only when the semantic frame had no
    # reference fields at all (rule_based / fallback_rules origin).
    compact = (text or "").strip()
    if not compact:
        return {"status": "unresolved", "reason": "empty_text", "resolution_source": "raw_text"}

    ordinal_result = _resolve_ordinal_reference(compact, session_state)
    if ordinal_result.get("status") != "unresolved":
        ordinal_result["resolution_source"] = "raw_text"
        return ordinal_result

    deictic_result = _resolve_deictic_reference(compact, session_state)
    if deictic_result.get("status") != "unresolved":
        deictic_result["resolution_source"] = "raw_text"
        return deictic_result

    return {"status": "unresolved", "reason": "no_reference_detected", "resolution_source": "raw_text"}
