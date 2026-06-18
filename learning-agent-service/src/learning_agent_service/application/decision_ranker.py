"""DecisionRanker — 基于证据的推荐排序和比较解释。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Candidate:
    """候选店铺。"""
    name: str
    score: float = 0.0
    attributes: dict[str, Any] | None = None


@dataclass
class RankedCandidate:
    """排序后的候选店铺。"""
    name: str
    score: float = 0.0
    rank: int = 0
    explanation: str = ""


class DecisionRanker:
    """基于证据的推荐排序和比较解释。"""

    def rank_and_explain(
        self,
        candidates: list[Candidate],
        evidence: list[dict[str, Any]] | None = None,
        query: str = "",
    ) -> list[RankedCandidate]:
        """排序并生成解释。"""
        # 1. 按分数排序
        sorted_candidates = sorted(candidates, key=lambda c: c.score, reverse=True)

        # 2. 生成排名和解释
        result: list[RankedCandidate] = []
        for rank, candidate in enumerate(sorted_candidates, start=1):
            explanation = self._generate_explanation(candidate, query)
            result.append(RankedCandidate(
                name=candidate.name,
                score=candidate.score,
                rank=rank,
                explanation=explanation,
            ))

        return result

    def _generate_explanation(
        self,
        candidate: Candidate,
        query: str,
    ) -> str:
        """生成单个候选的解释。"""
        parts = [f"{candidate.name}评分{candidate.score}分"]
        
        if candidate.attributes:
            if "price" in candidate.attributes:
                parts.append(f"人均{candidate.attributes['price']}")
            if "distance" in candidate.attributes:
                parts.append(f"距离{candidate.attributes['distance']}")
        
        return "，".join(parts)
