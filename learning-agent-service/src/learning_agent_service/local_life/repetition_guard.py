from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from learning_agent_service.domain.utils import as_mapping as _as_mapping, clean_text as _clean_text


_LOW_INFO_PHRASES = {
    "整体不错",
    "还可以",
    "比较好",
    "值得考虑",
    "体验不错",
    "口碑还行",
    "环境不错",
    "服务不错",
    "味道不错",
}


@dataclass(frozen=True)
class RepetitionGuardResult:
    text: str
    deduped: bool
    duplicate_sentence_count: int
    duplicate_ratio: float
    recommendation_duplicate_shop_count: int


class RepetitionGuard:
    def dedupe(
        self,
        *,
        text: str,
        answer_contract: Any | None = None,
        ranked_candidates: Sequence[Any] | None = None,
    ) -> RepetitionGuardResult:
        source_text = _clean_text(text)
        if not source_text:
            return RepetitionGuardResult(
                text="",
                deduped=False,
                duplicate_sentence_count=0,
                duplicate_ratio=0.0,
                recommendation_duplicate_shop_count=0,
            )

        answer_style = _clean_text(_as_mapping(answer_contract).get("answer_style")) if isinstance(answer_contract, dict) else _clean_text(getattr(answer_contract, "answer_style", None))
        candidate_names = [
            _clean_text(item.get("name") if isinstance(item, dict) else getattr(item, "name", None))
            for item in (ranked_candidates or [])
        ]
        candidate_names = [name for name in candidate_names if name]
        seen_sentences: set[str] = set()
        seen_low_info_phrases: set[str] = set()
        seen_shop_names: set[str] = set()
        output_lines: list[str] = []
        duplicate_sentence_count = 0
        recommendation_duplicate_shop_count = 0

        for raw_line in source_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            shop_name = None
            if answer_style == "multi_shop_recommendation":
                match = re.match(r"^\s*(\d+)[.、]\s*([^，,。]+)", line)
                if match:
                    shop_name = match.group(2).strip()
                    if shop_name in seen_shop_names:
                        duplicate_sentence_count += 1
                        recommendation_duplicate_shop_count += 1
                        continue
                    seen_shop_names.add(shop_name)
            segments = [segment.strip() for segment in re.split(r"[。！？!?；;]+", line) if segment.strip()]
            kept_segments: list[str] = []
            for segment in segments:
                normalized = re.sub(r"\s+", "", segment)
                normalized = re.sub(r"[，,。！？!?；;:：-]+$", "", normalized)
                if not normalized:
                    continue
                low_info_hits = {phrase for phrase in _LOW_INFO_PHRASES if phrase in normalized}
                if low_info_hits and low_info_hits.intersection(seen_low_info_phrases):
                    duplicate_sentence_count += 1
                    continue
                if normalized in seen_sentences:
                    duplicate_sentence_count += 1
                    continue
                seen_sentences.add(normalized)
                seen_low_info_phrases.update(low_info_hits)
                kept_segments.append(segment)
            if not kept_segments:
                continue
            rebuilt = "。".join(kept_segments)
            if not rebuilt.endswith(("。", "！", "!", "？", "?")):
                rebuilt += "。"
            output_lines.append(rebuilt)

        deduped_text = "\n".join(output_lines).strip()
        deduped = deduped_text != source_text
        total_sentence_count = max(1, len([segment for segment in re.split(r"[。！？!?；;\n]+", source_text) if segment.strip()]))
        duplicate_ratio = round(duplicate_sentence_count / total_sentence_count, 3)

        return RepetitionGuardResult(
            text=deduped_text,
            deduped=deduped,
            duplicate_sentence_count=duplicate_sentence_count,
            duplicate_ratio=duplicate_ratio,
            recommendation_duplicate_shop_count=recommendation_duplicate_shop_count,
        )
