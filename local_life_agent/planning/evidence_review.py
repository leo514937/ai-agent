"""DEPRECATED_COMPAT: legacy top-level re-export for evidence review."""

from .evidence.evidence_review import (
    _classify_status,
    _detect_failed_as_empty,
    _detect_unknown_as_false,
    review_evidence,
)
