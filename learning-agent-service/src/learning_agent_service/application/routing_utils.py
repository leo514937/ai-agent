from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from ..domain.contracts import RewriteDecision
from .routing_primitives import _content_tokens, normalize_query


def build_rewrite_decision(
    original_query: str,
    rewritten_query: str,
    *,
    confidence: float,
    reason: str,
    preserved_constraints: Sequence[str] | None = None,
    extra: Mapping[str, Any] | None = None,
) -> RewriteDecision:
    original = normalize_query(original_query)
    rewritten = normalize_query(rewritten_query)
    original_tokens = Counter(_content_tokens(original))
    rewritten_tokens = Counter(_content_tokens(rewritten))
    added_terms = list((rewritten_tokens - original_tokens).elements())
    removed_terms = list((original_tokens - rewritten_tokens).elements())
    preserved = list(preserved_constraints or [])
    risky = bool(added_terms) and (confidence < 0.65 or len(added_terms) > max(2, len(preserved) + 1))
    should_retrieve = bool(rewritten and confidence >= 0.4 and not risky)
    return RewriteDecision(
        original_query=original,
        rewritten_query=rewritten or original,
        added_terms=added_terms,
        removed_terms=removed_terms,
        preserved_constraints=preserved,
        confidence=max(0.0, min(float(confidence or 0.0), 1.0)),
        should_retrieve=should_retrieve,
        reason=reason,
        risky_rewrite=risky,
    )
