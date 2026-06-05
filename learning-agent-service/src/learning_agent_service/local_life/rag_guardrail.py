from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from learning_agent_service.domain.utils import as_mapping as _as_mapping

from .answer_contract import AnswerContract
from .rag_relevance import (
    compatible_facets,
    extract_facet,
    final_relevance_score,
    lexical_overlap,
    metadata_match_score,
    normalize_facet,
    support_level,
)


def _shop_id(item: Any) -> int | None:
    item_map = _as_mapping(item)
    shop_value = item_map.get("shop_id")
    if shop_value in (None, ""):
        shop_value = _as_mapping(item_map.get("metadata")).get("shop_id")
    if shop_value is not None:
        try:
            return int(shop_value)
        except Exception:
            return None
    return None


def _claim_text(item: Any) -> str:
    item_map = _as_mapping(item)
    return str(item_map.get("support_text") or item_map.get("claim") or "").strip()


def _confidence(item: Any) -> float:
    item_map = _as_mapping(item)
    try:
        return float(item_map.get("confidence") or 0.0)
    except Exception:
        return 0.0


def _chunk_id(item: Any) -> str:
    item_map = _as_mapping(item)
    return str(item_map.get("chunk_id") or item_map.get("evidence_id") or "")


def _parent_chunk_id(item: Any) -> str | None:
    item_map = _as_mapping(item)
    metadata = _as_mapping(item_map.get("metadata"))
    parent_chunk_id = metadata.get("parent_chunk_id") or metadata.get("parent_id")
    if parent_chunk_id in (None, ""):
        return None
    return str(parent_chunk_id)


def _chunk_role(item: Any) -> str | None:
    item_map = _as_mapping(item)
    metadata = _as_mapping(item_map.get("metadata"))
    role = metadata.get("chunk_role") or item_map.get("chunk_role")
    if role in (None, ""):
        return None
    return str(role)


@dataclass(frozen=True)
class EvidenceJudgement:
    evidence_id: str
    shop_id: int | None
    shop_match: bool
    facet: str | None
    facet_match: bool
    lexical_overlap: float
    semantic_score: float | None
    rerank_score: float | None
    metadata_match: float
    support_level: str
    drop_reason: str | None
    debug: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RagGuardrailResult:
    clean_items: list[Any]
    weak_items: list[Any]
    dropped_items: list[Any]
    judgements: list[EvidenceJudgement]
    rag_quality_status: str
    dirty_reasons: list[str]
    metrics: dict[str, Any]
    degraded: bool = False
    degraded_reason: str | None = None


class LocalLifeRagGuardrail:
    def apply(
        self,
        *,
        raw_query: str,
        latest_turn_message: str,
        rag_mode: str,
        evidence_claims: Sequence[Any],
        answer_contract: AnswerContract | Mapping[str, Any] | None,
        target_shop_id: int | None = None,
    ) -> RagGuardrailResult:
        if answer_contract is None:
            contract = AnswerContract(
                allowed_facets=[],
                forbidden_facets=[],
                answer_style="single_shop_review",
            )
        elif isinstance(answer_contract, AnswerContract):
            contract = answer_contract
        else:
            raw = dict(answer_contract)
            if "allowed_facets" not in raw:
                raw["allowed_facets"] = []
            if "forbidden_facets" not in raw:
                raw["forbidden_facets"] = []
            if "answer_style" not in raw:
                raw["answer_style"] = "single_shop_review"
            contract = AnswerContract.model_validate(raw)
        allowed_facets: list[str] = []
        for f in (contract.allowed_rag_facets or contract.allowed_facets):
            norm = normalize_facet(f)
            if norm is not None:
                allowed_facets.append(norm)

        forbidden_facets: set[str] = set()
        for f in (contract.forbidden_rag_facets or contract.forbidden_facets):
            norm = normalize_facet(f)
            if norm is not None:
                forbidden_facets.add(norm)

        realtime_facets: set[str] = set()
        for f in (contract.realtime_facets or []):
            norm = normalize_facet(f)
            if norm is not None:
                realtime_facets.add(norm)

        compatible_allowed = compatible_facets(allowed_facets)

        weak_items: list[Any] = []
        dropped_items: list[Any] = []
        judgements: list[EvidenceJudgement] = []
        clean_by_shop: dict[int | None, list[tuple[Any, EvidenceJudgement]]] = defaultdict(list)
        sibling_counter: dict[tuple[int | None, str], int] = defaultdict(int)

        for item in evidence_claims:
            shop_id = _shop_id(item)
            facet = extract_facet(item)
            facet_match = not compatible_allowed or (facet in compatible_allowed if facet is not None else False)
            shop_match = target_shop_id is None or shop_id is None or shop_id == target_shop_id
            lexical = lexical_overlap(latest_turn_message or raw_query, _claim_text(item))
            metadata_score = metadata_match_score(target_shop_id=target_shop_id, item_shop_id=shop_id, facet_match=facet_match)
            score = final_relevance_score(
                confidence=_confidence(item),
                lexical=lexical,
                facet_match=facet_match,
                metadata_score=metadata_score,
            )
            level = support_level(score)
            drop_reason = None

            if rag_mode == "single_shop_rag" and target_shop_id is not None and shop_id is not None and shop_id != target_shop_id:
                drop_reason = "cross_shop"
            elif facet in forbidden_facets:
                drop_reason = "forbidden_facet"
            elif facet in realtime_facets:
                drop_reason = "realtime_facet_from_rag"
            elif not facet_match:
                drop_reason = "forbidden_facet"
            elif level in {"weak", "irrelevant"}:
                drop_reason = "low_relevance"

            judgement = EvidenceJudgement(
                evidence_id=_chunk_id(item),
                shop_id=shop_id,
                shop_match=shop_match,
                facet=facet,
                facet_match=facet_match,
                lexical_overlap=lexical,
                semantic_score=_confidence(item),
                rerank_score=None,
                metadata_match=metadata_score,
                support_level=level,
                drop_reason=drop_reason,
                debug={
                    "parent_chunk_id": _parent_chunk_id(item),
                    "chunk_role": _chunk_role(item),
                    "score": round(score, 4),
                },
            )
            judgements.append(judgement)

            if drop_reason is not None:
                dropped_items.append(item)
                if drop_reason == "low_relevance":
                    weak_items.append(item)
                continue

            clean_by_shop[shop_id].append((item, judgement))

        kept_items: list[Any] = []
        sibling_dropped: list[Any] = []
        if rag_mode == "recommendation_rag":
            for shop_id, pairs in clean_by_shop.items():
                ranked_pairs = sorted(
                    pairs,
                    key=lambda pair: (
                        0 if pair[1].support_level == "strong" else 1,
                        -float(pair[1].debug.get("score") or 0.0),
                        pair[1].evidence_id,
                    ),
                )
                shop_kept = 0
                for item, _ in ranked_pairs:
                    parent_chunk_id = _parent_chunk_id(item)
                    sibling_key = (shop_id, parent_chunk_id or "")
                    if parent_chunk_id and sibling_counter[sibling_key] >= 2:
                        sibling_dropped.append(item)
                        continue
                    if shop_kept >= 2:
                        sibling_dropped.append(item)
                        continue
                    kept_items.append(item)
                    shop_kept += 1
                    if parent_chunk_id:
                        sibling_counter[sibling_key] += 1
        else:
            ranked_pairs = sorted(
                [pair for pairs in clean_by_shop.values() for pair in pairs],
                key=lambda pair: (
                    0 if pair[1].support_level == "strong" else 1,
                    -float(pair[1].debug.get("score") or 0.0),
                    pair[1].evidence_id,
                ),
            )
            for item, _ in ranked_pairs:
                parent_chunk_id = _parent_chunk_id(item)
                sibling_key = (_shop_id(item), parent_chunk_id or "")
                if parent_chunk_id and sibling_counter[sibling_key] >= 2:
                    sibling_dropped.append(item)
                    continue
                kept_items.append(item)
                if parent_chunk_id:
                    sibling_counter[sibling_key] += 1

        dropped_items.extend(sibling_dropped)
        rejection_counts = Counter(judgement.drop_reason or "kept" for judgement in judgements if judgement.drop_reason)
        if sibling_dropped:
            rejection_counts["sibling_limit"] += len(sibling_dropped)

        strong_count = sum(1 for judgement in judgements if judgement.drop_reason is None and judgement.support_level == "strong")
        medium_count = sum(1 for judgement in judgements if judgement.drop_reason is None and judgement.support_level == "medium")
        weak_count = sum(1 for judgement in judgements if judgement.support_level == "weak")

        if kept_items:
            rag_quality_status = "ok"
        elif weak_items:
            rag_quality_status = "weak"
        elif dropped_items:
            rag_quality_status = "dirty"
        else:
            rag_quality_status = "empty"

        dirty_reasons: list[str] = []
        if rejection_counts.get("cross_shop"):
            dirty_reasons.append("cross_shop_detected")
        if rejection_counts.get("forbidden_facet") or rejection_counts.get("realtime_facet_from_rag"):
            dirty_reasons.append("forbidden_facet_detected")
        if rejection_counts.get("low_relevance"):
            dirty_reasons.append("low_relevance_only")
        if rejection_counts.get("sibling_limit"):
            dirty_reasons.append("sibling_trimmed")
        if not dirty_reasons and rag_quality_status == "empty":
            dirty_reasons.append("no_evidence")

        degraded = not kept_items
        degraded_reason = self._degraded_reason(
            rag_mode=rag_mode,
            latest_turn_message=latest_turn_message,
            allowed_facets=allowed_facets,
            dirty_reasons=dirty_reasons,
        ) if degraded else None

        metrics = {
            "rag_mode": rag_mode,
            "latest_turn_message": latest_turn_message,
            "retrieval_query": raw_query,
            "raw_evidence_count": len(evidence_claims),
            "dropped_by_shop_count": rejection_counts.get("cross_shop", 0),
            "dropped_by_facet_count": rejection_counts.get("forbidden_facet", 0) + rejection_counts.get("realtime_facet_from_rag", 0),
            "dropped_by_relevance_count": rejection_counts.get("low_relevance", 0),
            "dropped_by_sibling_count": rejection_counts.get("sibling_limit", 0),
            "final_clean_evidence_count": len(kept_items),
            "strong_evidence_count": strong_count,
            "medium_evidence_count": medium_count,
            "weak_evidence_count": weak_count,
            "rag_quality_status": rag_quality_status,
            "rag_dirty_reasons": list(dirty_reasons),
            "final_allowed_facets": [facet for facet in allowed_facets if facet],
            "forbidden_facets": [facet for facet in sorted(forbidden_facets) if facet],
            "recommendation_shop_count": len({_shop_id(item) for item in kept_items if _shop_id(item) is not None}) if rag_mode == "recommendation_rag" else 0,
            "degraded": degraded,
            "degraded_reason": degraded_reason,
        }

        return RagGuardrailResult(
            clean_items=kept_items,
            weak_items=weak_items,
            dropped_items=dropped_items,
            judgements=judgements,
            rag_quality_status=rag_quality_status,
            dirty_reasons=dirty_reasons,
            metrics=metrics,
            degraded=degraded,
            degraded_reason=degraded_reason,
        )

    @staticmethod
    def _degraded_reason(
        *,
        rag_mode: str,
        latest_turn_message: str,
        allowed_facets: Sequence[str],
        dirty_reasons: Sequence[str],
    ) -> str:
        facet_text = "、".join(allowed_facets) if allowed_facets else "当前问题"
        if rag_mode == "recommendation_rag":
            return (
                "我目前没有找到足够多同时满足这些条件的商家证据，暂时不强行推荐。"
                "你可以放宽条件，例如先只看“附近 + 适合约会”，再筛选有券或营业状态。"
            )
        return (
            f"我目前没有检索到这家店与“{facet_text}”直接相关的可靠评价证据，不能直接判断。"
            "你可以补充更具体的问题，例如环境、排队、价格或适合场景。"
        )
