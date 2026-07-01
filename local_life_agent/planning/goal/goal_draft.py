"""Goal-draft and CandidateSpec builders for the P0 CandidateSet flow.

Translates the LLM-derived ``SemanticFrame`` into:

  - ``LocalLifeGoalDraft`` — the structured goal that drives the
    candidate resolution strategy.
  - ``CandidateSpec`` — the concrete spec consumed by CandidateResolver.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any

from ...domain.candidate import (
    CandidateSet,
    CandidateSource,
    CandidateSpec,
    CandidateStatus,
    GoalType,
    LocalLifeGoalDraft,
)
from ...domain.enums import TaskType
from ...domain.schemas import SemanticFrame


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


def _stringify_category(value: Any) -> str:
    """Normalize category values into a search-friendly string."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple, set)):
        parts = [str(item).strip() for item in value if str(item).strip()]
        return " ".join(parts)
    return str(value).strip()


def _goal_type_from_task_type(task_type: TaskType | str | None) -> GoalType:
    """Map the legacy TaskType enum to the new GoalType enum."""
    if task_type is None:
        return GoalType.UNSUPPORTED
    raw = task_type.value if isinstance(task_type, TaskType) else str(task_type)
    mapping: dict[str, GoalType] = {
        TaskType.recommendation.value: GoalType.RECOMMENDATION,
        TaskType.comparison.value: GoalType.COMPARISON,
        TaskType.single_shop_query.value: GoalType.SINGLE_SHOP_QUERY,
        TaskType.coupon_query.value: GoalType.SINGLE_SHOP_QUERY,
    }
    return mapping.get(raw, GoalType.UNSUPPORTED)


def _candidate_source_from_frame(frame: SemanticFrame) -> CandidateSource:
    """Derive the candidate source from the SemanticFrame.

    Priority:
      1. If frame has ``candidate_source`` set explicitly → use it.
      2. If there are explicit ``merchant_mentions >= 2`` and
         structured refs   → MIXED
      3. If there are explicit ``merchant_mentions >= 1`` → EXPLICIT
      4. If there are ordinal/deictic references → CONTEXT
      5. Otherwise → DISCOVERY
    """
    # Check explicit field from LLM
    if frame.candidate_source is not None:
        try:
            return CandidateSource(frame.candidate_source)
        except Exception:
            pass

    mentions = list(frame.merchant_mentions or [])
    ordinals = list(frame.ordinal_references or [])
    deictics = list(frame.deictic_references or [])
    comparison_targets = list(frame.comparison_targets or [])
    reference_mentions = list(frame.reference_mentions or [])

    has_structured_refs = bool(ordinals or deictics or comparison_targets or reference_mentions)
    has_mentions = len(mentions) >= 1

    if has_mentions and has_structured_refs:
        return CandidateSource.MIXED
    if has_mentions:
        return CandidateSource.EXPLICIT
    if has_structured_refs:
        return CandidateSource.CONTEXT
    return CandidateSource.DISCOVERY


def _infer_explicit_mentions_from_text(raw_text: str) -> list[str]:
    """从原文里保守提取明确店名片段，供 explicit 解析使用。"""
    text = str(raw_text or "").strip()
    if not text:
        return []

    mentions: list[str] = []
    bracket_pattern = r"[\u4e00-\u9fffA-Za-z0-9·&]+[（(][^）)]+[）)]"
    mentions.extend(re.findall(bracket_pattern, text))

    cut_markers = (
        "有券",
        "团购",
        "营业",
        "开门",
        "多久",
        "多远",
        "距离",
        "离我",
        "多少钱",
        "便宜",
        "优惠",
        "套餐",
    )
    cut_index = len(text)
    for marker in cut_markers:
        idx = text.find(marker)
        if 0 < idx < cut_index:
            cut_index = idx
    if cut_index < len(text):
        prefix = text[:cut_index].strip(" ，,。?？！!~")
        if prefix and any(token in prefix for token in ("店", "馆", "轩", "居", "坊", "园", "楼", "火锅", "烧烤", "餐厅", "饭店", "酒楼")):
            mentions.append(prefix)
        elif (
            prefix
            and 2 <= len(prefix) <= 12
            and any("\u4e00" <= ch <= "\u9fff" for ch in prefix)
            and not any(token in prefix for token in ("这家", "那家", "第一家", "第二家", "第三家", "附近", "推荐"))
        ):
            mentions.append(prefix)

    ordered: list[str] = []
    seen: set[str] = set()
    for mention in mentions:
        cleaned = str(mention).strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            ordered.append(cleaned)
    return ordered


def build_local_life_goal_draft(
    semantic_frame: SemanticFrame | dict[str, Any] | None,
    state: dict[str, Any] | None = None,
) -> LocalLifeGoalDraft:
    """Build a LocalLifeGoalDraft from the current SemanticFrame and state.

    Args:
        semantic_frame: The LLM-parsed semantic frame (or serialized dict).
        state: Optional GraphState dict for additional context.

    Returns:
        A populated LocalLifeGoalDraft.
    """
    frame: SemanticFrame | None = None
    if isinstance(semantic_frame, SemanticFrame):
        frame = semantic_frame
    elif isinstance(semantic_frame, dict):
        try:
            frame = SemanticFrame.model_validate(semantic_frame)
        except Exception:
            frame = None
    if frame is None:
        return LocalLifeGoalDraft(
            goal_type=GoalType.UNSUPPORTED,
            candidate_source=CandidateSource.DISCOVERY,
            source_origin="fallback",
        )

    goal_type = _goal_type_from_task_type(frame.task_type)
    candidate_source = _candidate_source_from_frame(frame)
    candidate_category = ""
    if isinstance(frame.hard_constraints, dict):
        candidate_category = _stringify_category(frame.hard_constraints.get("category", ""))
    if not candidate_category:
        candidate_category = _stringify_category(frame.candidate_category)

    # Parse candidate_limit from frame or hard_constraints
    candidate_limit: int | None = None
    if frame.candidate_limit is not None:
        candidate_limit = frame.candidate_limit
    else:
        # Check if numeric like "two" → "两家" in raw text
        limit_str = str(frame.hard_constraints.get("count", "") or "")
        if limit_str.isdigit():
            candidate_limit = int(limit_str)

    # Apply explicit quantity semantics
    requested_count: int
    min_required: int
    max_allowed: int
    if goal_type == GoalType.COMPARISON:
        requested_count = candidate_limit or 2
        min_required = 2
        max_allowed = candidate_limit or 5
    elif goal_type == GoalType.RECOMMENDATION:
        requested_count = candidate_limit or 3
        min_required = 1
        max_allowed = candidate_limit or 5
    elif goal_type == GoalType.SINGLE_SHOP_QUERY:
        requested_count = candidate_limit or 1
        min_required = 1
        max_allowed = candidate_limit or 1
    else:
        requested_count = candidate_limit or 1
        min_required = 1
        max_allowed = candidate_limit or 5

    candidate_limit = requested_count

    # Extract evidence needs (required facets + focused facets)
    required_facets: list[str] = []
    optional_facets: list[str] = []
    for facet_spec in frame.facets or []:
        spec_dict = _to_dict(facet_spec)
        name_raw = spec_dict.get("name", "") or ""
        name = str(name_raw.value) if isinstance(name_raw, Enum) else str(name_raw)
        if not name:
            continue
        if spec_dict.get("required"):
            required_facets.append(name)
        else:
            optional_facets.append(name)

    evidence_needs = list(required_facets)
    for facet in frame.focused_facets or []:
        if facet and facet not in evidence_needs:
            evidence_needs.append(facet)

    # Determine source origin
    semantic_source = str(frame.semantic_source or "")
    fallback_reason = str(frame.fallback_reason or "")
    if fallback_reason:
        source_origin = "llm+fallback" if semantic_source else "fallback"
    elif semantic_source:
        source_origin = semantic_source
    else:
        source_origin = "llm"

    return LocalLifeGoalDraft(
        goal_type=goal_type,
        candidate_source=candidate_source,
        candidate_category=candidate_category or None,
        candidate_limit=candidate_limit,
        evidence_needs=evidence_needs,
        required_facets=required_facets,
        optional_facets=optional_facets,
        requested_count=requested_count,
        min_required=min_required,
        max_allowed=max_allowed,
        max_candidates=5,
        source_origin=source_origin,
    )


def build_candidate_spec(
    goal: LocalLifeGoalDraft,
    semantic_frame: SemanticFrame | dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
) -> CandidateSpec:
    """Build a CandidateSpec from the LocalLifeGoalDraft.

    Args:
        goal: The goal draft driving resolution.
        semantic_frame: Optional SemanticFrame for additional detail.
        state: Optional GraphState dict.

    Returns:
        A CandidateSpec ready for CandidateResolver.
    """
    frame: SemanticFrame | None = None
    if isinstance(semantic_frame, SemanticFrame):
        frame = semantic_frame
    elif isinstance(semantic_frame, dict):
        try:
            frame = SemanticFrame.model_validate(semantic_frame)
        except Exception:
            frame = None

    spec = CandidateSpec(source=goal.candidate_source)

    # Category and query
    cat = goal.candidate_category or ""
    spec.category = cat

    # Build query
    query_parts: list[str] = []
    if cat:
        query_parts.append(cat)
    if frame is not None:
        ranking = frame.ranking_signals or {}
        query_terms = ranking.get("query_terms", []) if isinstance(ranking, dict) else []
        if isinstance(query_terms, list):
            for qt in query_terms:
                if qt and qt not in query_parts:
                    query_parts.append(str(qt))
    spec.query = " ".join(query_parts)

    # Location scope
    if state:
        mock_loc = state.get("user_context")
        if isinstance(mock_loc, dict):
            status = str(mock_loc.get("location_status", "") or "").lower()
            source = str(mock_loc.get("location_source", "") or "").lower()
            if status not in {"provided", "test_mock"} and source not in {"provided", "test_mock"}:
                mock_loc = None
        if isinstance(mock_loc, dict):
            spec.location_scope = {
                "name": str(mock_loc.get("name", "") or ""),
                "lat": float(mock_loc.get("lat", 0)),
                "lng": float(mock_loc.get("lng", 0)),
            }

    # Sort / limit / filters
    if frame is not None:
        raw_sort = getattr(frame, "candidate_sort_by", None)
        if raw_sort:
            spec.sort_by = raw_sort if isinstance(raw_sort, list) else [raw_sort]

    spec.limit = goal.candidate_limit
    if goal.goal_type == GoalType.SINGLE_SHOP_QUERY and goal.candidate_source == CandidateSource.DISCOVERY:
        # Discovery-style single-shop queries need enough breadth to detect
        # ambiguity instead of collapsing to the first hit.
        spec.limit = max(spec.limit or 0, 5)

    # Explicit mentions
    if frame is not None:
        merchant_mentions = [str(item).strip() for item in (frame.merchant_mentions or []) if str(item).strip()]
        branch_mentions = [str(item).strip() for item in (frame.branch_mentions or []) if str(item).strip()]
        full_mentions = [item for item in merchant_mentions if "(" in item or "（" in item]
        inferred_mentions: list[str] = []
        if state:
            inferred_mentions = _infer_explicit_mentions_from_text(str(state.get("raw_text", "") or ""))
        if goal.goal_type == GoalType.SINGLE_SHOP_QUERY and goal.candidate_source in {CandidateSource.EXPLICIT, CandidateSource.MIXED}:
            if inferred_mentions:
                spec.explicit_mentions = inferred_mentions
            elif full_mentions:
                spec.explicit_mentions = full_mentions
            elif merchant_mentions and branch_mentions:
                spec.explicit_mentions = [f"{merchant_mentions[0]}({branch_mentions[0]})"]
            else:
                spec.explicit_mentions = merchant_mentions
        else:
            spec.explicit_mentions = merchant_mentions
        if (
            goal.goal_type == GoalType.SINGLE_SHOP_QUERY
            and goal.candidate_source in {CandidateSource.EXPLICIT, CandidateSource.MIXED}
            and len(spec.explicit_mentions) > 1
        ):
            # Multi-mention single-shop queries need enough breadth to
            # surface ambiguity instead of collapsing to the first hit.
            spec.limit = max(spec.limit or 0, len(spec.explicit_mentions))
        if (
            goal.goal_type == GoalType.SINGLE_SHOP_QUERY
            and goal.candidate_source in {CandidateSource.EXPLICIT, CandidateSource.MIXED}
            and not spec.explicit_mentions
            and state
        ):
            inferred_mentions = _infer_explicit_mentions_from_text(str(state.get("raw_text", "") or ""))
            if inferred_mentions:
                spec.explicit_mentions = inferred_mentions
                if len(spec.explicit_mentions) > 1:
                    spec.limit = max(spec.limit or 0, len(spec.explicit_mentions))
        if (
            goal.goal_type == GoalType.SINGLE_SHOP_QUERY
            and goal.candidate_source in {CandidateSource.EXPLICIT, CandidateSource.MIXED}
            and spec.explicit_mentions
        ):
            spec.query = " ".join(spec.explicit_mentions)

    # Context ref
    if goal.candidate_source == CandidateSource.CONTEXT and frame is not None:
        refs = (list(frame.ordinal_references or []) +
                list(frame.deictic_references or []))
        spec.context_ref = " ".join(refs) if refs else None

    # Filters
    if frame is not None:
        hc = frame.hard_constraints or {}
        if isinstance(hc, dict):
            for key, value in hc.items():
                if key not in ("category", "count") and value is not None:
                    spec.filters[key] = value
    if state:
        ac = state.get("active_constraints") or {}
        for key, value in (ac.items() if isinstance(ac, dict) else {}):
            if key not in spec.filters:
                spec.filters[key] = value

    # Ranking signals
    if frame is not None:
        rs = frame.ranking_signals or {}
        if isinstance(rs, dict):
            spec.ranking_signals = dict(rs)

    return spec
