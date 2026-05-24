from __future__ import annotations

from typing import List, Sequence, Tuple

from .models import Citation, EvidenceItem, EvidencePack


class CitationBuilder:
    def build(self, evidence: EvidencePack) -> Tuple[Citation, ...]:
        return tuple(self._build_single(item) for item in evidence.items)

    def _build_single(self, item: EvidenceItem) -> Citation:
        excerpt = item.chunk.text.strip().replace("\n", " ")
        if len(excerpt) > 180:
            excerpt = excerpt[:177].rstrip() + "..."
        return Citation(
            chunk_id=item.citation_chunk_id or item.chunk.chunk_id,
            document_id=item.chunk.document_id,
            title=item.chunk.title,
            source_type=item.chunk.source_type,
            version=item.chunk.version,
            score=item.score,
            excerpt=excerpt,
            metadata={
                "chunk_type": item.chunk.chunk_type,
                "routes": item.routes,
                "tags": item.chunk.tags,
                "tier": item.tier,
                "source_chunk_id": item.source_chunk_id or item.chunk.chunk_id,
                "citation_chunk_id": item.citation_chunk_id or item.chunk.chunk_id,
                "parent_chunk_id": item.parent_chunk_id or item.chunk.parent_id,
            },
        )
