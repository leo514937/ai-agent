from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence, Tuple

from .models import GovernanceAction, KnowledgeChunk, KnowledgeGovernanceDecision

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_+#.:-]+|[\u4e00-\u9fff]+")


@dataclass(frozen=True)
class GovernanceConfig:
    duplicate_similarity_threshold: float = 0.9


class KnowledgeGovernanceService:
    def __init__(self, config: GovernanceConfig = None) -> None:
        self._config = config or GovernanceConfig()

    def plan_duplicate_cleanup(self, document_id: str, chunks: Sequence[KnowledgeChunk]) -> KnowledgeGovernanceDecision:
        duplicate_ids = self._find_duplicate_ids(chunks)
        if not duplicate_ids:
            return KnowledgeGovernanceDecision(
                action=GovernanceAction.NOOP,
                document_id=document_id,
                reason="no duplicate chunks detected",
            )
        return KnowledgeGovernanceDecision(
            action=GovernanceAction.CLEAN_DUPLICATES,
            document_id=document_id,
            reason="detected duplicate chunks for the same document version",
            affected_chunk_ids=tuple(sorted(duplicate_ids)),
        )

    def plan_version_switch(self, document_id: str, target_version: str, reason: str = "activate newer version") -> KnowledgeGovernanceDecision:
        return KnowledgeGovernanceDecision(
            action=GovernanceAction.ACTIVATE_VERSION,
            document_id=document_id,
            target_version=target_version,
            reason=reason,
        )

    def plan_rebuild(self, document_id: str, reason: str = "rebuild requested") -> KnowledgeGovernanceDecision:
        return KnowledgeGovernanceDecision(
            action=GovernanceAction.REBUILD_DOCUMENT,
            document_id=document_id,
            reason=reason,
        )

    def plan_rollback(self, document_id: str, target_version: str, reason: str = "rollback to previous active version") -> KnowledgeGovernanceDecision:
        return KnowledgeGovernanceDecision(
            action=GovernanceAction.ROLLBACK_VERSION,
            document_id=document_id,
            target_version=target_version,
            reason=reason,
        )

    def deduplicate_chunks(self, chunks: Iterable[KnowledgeChunk]) -> Tuple[KnowledgeChunk, ...]:
        kept: List[KnowledgeChunk] = []
        for chunk in chunks:
            if any(self._similarity(chunk.text, existing.text) >= self._config.duplicate_similarity_threshold for existing in kept):
                continue
            kept.append(chunk)
        return tuple(kept)

    def _find_duplicate_ids(self, chunks: Sequence[KnowledgeChunk]) -> Tuple[str, ...]:
        duplicates: List[str] = []
        kept: List[KnowledgeChunk] = []
        for chunk in chunks:
            if any(self._similarity(chunk.text, existing.text) >= self._config.duplicate_similarity_threshold for existing in kept):
                duplicates.append(chunk.chunk_id)
                continue
            kept.append(chunk)
        return tuple(duplicates)

    @staticmethod
    def _similarity(left: str, right: str) -> float:
        left_tokens = set(token.lower() for token in _TOKEN_PATTERN.findall(left or ""))
        right_tokens = set(token.lower() for token in _TOKEN_PATTERN.findall(right or ""))
        if not left_tokens or not right_tokens:
            return 0.0
        return len(left_tokens & right_tokens) / float(len(left_tokens | right_tokens) or 1)
