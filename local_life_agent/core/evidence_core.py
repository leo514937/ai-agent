"""DEPRECATED_COMPAT: evidence 构建与 review 的兼容壳。

新代码应优先使用 planning/evidence 下的 canonical 实现。
"""

from __future__ import annotations

from typing import Any


class EvidenceCore:
    def build(self, *args: Any, **kwargs: Any):
        from ..planning.evidence.evidence_builder import build_evidence

        return build_evidence(*args, **kwargs)

    def review(self, *args: Any, **kwargs: Any):
        from ..planning.evidence.evidence_review import review_evidence

        return review_evidence(*args, **kwargs)

    def review_with_llm(self, *args: Any, **kwargs: Any):
        from ..planning.evidence.evidence_review import review_evidence_with_llm

        return review_evidence_with_llm(*args, **kwargs)
