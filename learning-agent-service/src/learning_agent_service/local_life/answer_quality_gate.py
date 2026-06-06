from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

from learning_agent_service.domain.utils import as_mapping as _as_mapping, clean_text as _clean_text

from .answer_depth_policy import AnswerDepthPolicy, derive_answer_depth_policy
from .answer_structure_composer import AnswerStructureComposer
from .repetition_guard import RepetitionGuard


def _count_sections(text: str) -> int:
    return len([line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("-")])


def _count_bullets(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.lstrip().startswith(("-", "•", "*")) or re.match(r"^\s*\d+[.、]", line))


def _sentence_count(text: str) -> int:
    return len([segment for segment in re.split(r"[。！？!?；;\n]+", text) if segment.strip()])


class AnswerQualityResult(BaseModel):
    final_answer: str
    answer_style: str
    answer_depth_level: str
    answer_min_sections: int
    answer_min_chars: int
    clean_evidence_count: int
    strong_evidence_count: int
    medium_evidence_count: int
    answer_char_count: int
    section_count: int
    bullet_count: int
    duplicate_sentence_count: int
    duplicate_ratio: float
    answer_too_short: bool
    answer_too_repetitive: bool
    depth_limited_by_evidence: bool
    expanded_by_quality_gate: bool
    deduped_by_repetition_guard: bool
    recommendation_duplicate_shop_count: int
    final_answer_char_count: int
    delta_count: int
    evidence_coverage: float
    forbidden_facet_leak: bool
    unsupported_realtime_claim: bool


class AnswerQualityGate:
    def __init__(
        self,
        *,
        composer: AnswerStructureComposer | None = None,
        repetition_guard: RepetitionGuard | None = None,
    ) -> None:
        self._composer = composer or AnswerStructureComposer()
        self._repetition_guard = repetition_guard or RepetitionGuard()

    def finalize(
        self,
        *,
        draft_answer: str,
        answer_contract: Any | None,
        answer_depth_policy: AnswerDepthPolicy | None,
        clean_evidence_count: int,
        strong_evidence_count: int,
        medium_evidence_count: int,
        topic_name: str,
        ranked_candidates: list[Any] | None,
        evidence_claims: list[Any] | None,
        user_need: Any | None = None,
        facet_result_bundle: Any | None = None,
    ) -> AnswerQualityResult:
        contract_map = _as_mapping(answer_contract)
        style = _clean_text(contract_map.get("answer_style")) or (answer_depth_policy.answer_style if answer_depth_policy else "single_shop_review")
        policy = answer_depth_policy or derive_answer_depth_policy(
            answer_contract,
            clean_evidence_count=clean_evidence_count,
            strong_evidence_count=strong_evidence_count,
            medium_evidence_count=medium_evidence_count,
        )
        structure = self._composer.compose(
            answer_contract=answer_contract,
            topic_name=topic_name,
            ranked_candidates=ranked_candidates,
            evidence_claims=evidence_claims,
            answer_depth_policy=policy,
            user_need=user_need,
            facet_result_bundle=facet_result_bundle,
        )

        draft_text = _clean_text(draft_answer)
        deduped = self._repetition_guard.dedupe(
            text=draft_text,
            answer_contract=answer_contract,
            ranked_candidates=ranked_candidates,
        )
        candidate_text = deduped.text or draft_text
        expanded_by_quality_gate = False
        preserve_recommendation_draft = (
            style == "multi_shop_recommendation"
            and ("推荐理由" in candidate_text or "推荐结果" in candidate_text or "推荐" in candidate_text)
        )
        preserve_structured_draft = any(
            token in candidate_text
            for token in ("券信息：", "环境评价：", "营业状态：", "距离信息：", "推荐结果：")
        )
        if (
            policy.depth_level != "short"
            and not preserve_recommendation_draft
            and not preserve_structured_draft
            and (
                len(candidate_text) < policy.min_chars
                or _count_sections(candidate_text) < policy.min_sections
                or deduped.duplicate_sentence_count > 0
            )
        ):
            candidate_text = structure.answer_text
            expanded_by_quality_gate = candidate_text != draft_text
            deduped = self._repetition_guard.dedupe(
                text=candidate_text,
                answer_contract=answer_contract,
                ranked_candidates=ranked_candidates,
            )
            candidate_text = deduped.text or candidate_text

        if not candidate_text and structure.answer_text:
            candidate_text = structure.answer_text
            expanded_by_quality_gate = True

        final_answer = candidate_text.strip() or draft_text
        answer_char_count = len(draft_text)
        final_answer_char_count = len(final_answer)
        section_count = _count_sections(final_answer)
        bullet_count = _count_bullets(final_answer)
        answer_too_short = final_answer_char_count < policy.min_chars
        answer_too_repetitive = deduped.duplicate_sentence_count > 0 or deduped.duplicate_ratio >= 0.2
        depth_limited_by_evidence = policy.depth_limited_by_evidence or clean_evidence_count < policy.clean_evidence_count
        delta_count = final_answer_char_count - answer_char_count
        evidence_total = max(1, clean_evidence_count + strong_evidence_count + medium_evidence_count)
        evidence_coverage = round(min(1.0, clean_evidence_count / evidence_total), 3)

        forbidden_facet_leak = False
        forbidden_facets = [str(item).strip() for item in contract_map.get("forbidden_facets") or [] if str(item).strip()]
        if forbidden_facets:
            compact = final_answer.replace(" ", "")
            for forbidden in forbidden_facets:
                if forbidden in compact:
                    forbidden_facet_leak = True
                    break

        unsupported_realtime_claim = False
        if not bool(contract_map.get("realtime_required")):
            compact = final_answer.replace(" ", "")
            if any(token in compact for token in ("实时", "刚查", "最新")):
                unsupported_realtime_claim = True

        return AnswerQualityResult(
            final_answer=final_answer,
            answer_style=style,
            answer_depth_level=policy.depth_level,
            answer_min_sections=policy.min_sections,
            answer_min_chars=policy.min_chars,
            clean_evidence_count=clean_evidence_count,
            strong_evidence_count=strong_evidence_count,
            medium_evidence_count=medium_evidence_count,
            answer_char_count=answer_char_count,
            section_count=section_count,
            bullet_count=bullet_count,
            duplicate_sentence_count=deduped.duplicate_sentence_count,
            duplicate_ratio=deduped.duplicate_ratio,
            answer_too_short=answer_too_short,
            answer_too_repetitive=answer_too_repetitive,
            depth_limited_by_evidence=depth_limited_by_evidence,
            expanded_by_quality_gate=expanded_by_quality_gate,
            deduped_by_repetition_guard=deduped.deduped,
            recommendation_duplicate_shop_count=deduped.recommendation_duplicate_shop_count,
            final_answer_char_count=final_answer_char_count,
            delta_count=delta_count,
            evidence_coverage=evidence_coverage,
            forbidden_facet_leak=forbidden_facet_leak,
            unsupported_realtime_claim=unsupported_realtime_claim,
        )
