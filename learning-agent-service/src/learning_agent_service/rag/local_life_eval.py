from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from learning_agent_service.domain.utils import clean_text as _clean_text
from learning_agent_service.local_life.answer_planner import EvidencePack as LocalLifeEvidencePack


def _string_list(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        values = list(value)
    else:
        values = [value]
    ordered: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = _clean_text(item)
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return tuple(ordered)


def _int_list(value: Any) -> tuple[int, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, bytearray)):
        values = [value]
    elif isinstance(value, Sequence):
        values = list(value)
    else:
        values = [value]
    ordered: list[int] = []
    seen: set[int] = set()
    for item in values:
        try:
            number = int(item)
        except Exception:
            continue
        if number in seen:
            continue
        seen.add(number)
        ordered.append(number)
    return tuple(ordered)


@dataclass(frozen=True)
class LocalLifeRagEvalCase:
    case_id: str
    query: str
    expected_route: str = "rag"
    expected_rag_mode: str = "single_shop_rag"
    expected_shop_id: int | None = None
    expected_facets: tuple[str, ...] = ()
    forbidden_shop_ids: tuple[int, ...] = ()
    expected_keywords: tuple[str, ...] = ()
    turns: tuple[str, ...] = ()
    forbidden_single_shop_anchor: bool = False

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "LocalLifeRagEvalCase":
        raw_turns = raw.get("turns") or []
        if isinstance(raw_turns, str):
            raw_turns = [raw_turns]
        elif not isinstance(raw_turns, Sequence) or isinstance(raw_turns, (bytes, bytearray)):
            raw_turns = [raw_turns]
        turns = tuple(str(text) for item in raw_turns if (text := _clean_text(item)))
        query = _clean_text(raw.get("query") or (turns[-1] if turns else "")) or ""
        return cls(
            case_id=_clean_text(raw.get("case_id") or raw.get("id") or query or "case") or "case",
            query=query,
            expected_route=_clean_text(raw.get("expected_route") or "rag") or "rag",
            expected_rag_mode=_clean_text(raw.get("expected_rag_mode") or "single_shop_rag") or "single_shop_rag",
            expected_shop_id=_to_int(raw.get("expected_shop_id")),
            expected_facets=_string_list(raw.get("expected_facets")),
            forbidden_shop_ids=_int_list(raw.get("forbidden_shop_ids")),
            expected_keywords=_string_list(raw.get("expected_keywords")),
            turns=turns,
            forbidden_single_shop_anchor=bool(raw.get("forbidden_single_shop_anchor", False)),
        )


@dataclass(frozen=True)
class LocalLifeRagEvalObservation:
    case_id: str
    query: str
    answer: str = ""
    metrics: Mapping[str, Any] = field(default_factory=dict)
    evidence_pack: LocalLifeEvidencePack | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "LocalLifeRagEvalObservation":
        evidence_pack = raw.get("evidence_pack")
        if isinstance(evidence_pack, Mapping):
            evidence_pack = LocalLifeEvidencePack.model_validate(evidence_pack)
        return cls(
            case_id=_clean_text(raw.get("case_id") or raw.get("id")) or "case",
            query=_clean_text(raw.get("query")) or "",
            answer=_clean_text(raw.get("answer") or raw.get("final_answer")) or "",
            metrics=dict(raw.get("metrics") or {}),
            evidence_pack=evidence_pack if isinstance(evidence_pack, LocalLifeEvidencePack) else None,
        )


def load_local_life_rag_eval_cases(path: str | Path) -> tuple[LocalLifeRagEvalCase, ...]:
    return tuple(LocalLifeRagEvalCase.from_mapping(item) for item in _load_jsonl(path))


def load_local_life_rag_eval_observations(path: str | Path) -> tuple[LocalLifeRagEvalObservation, ...]:
    return tuple(LocalLifeRagEvalObservation.from_mapping(item) for item in _load_jsonl(path))


def evaluate_local_life_rag_cases(
    cases: Sequence[LocalLifeRagEvalCase],
    observations: Sequence[LocalLifeRagEvalObservation],
) -> dict[str, float | int]:
    case_map = {case.case_id: case for case in cases}
    observation_map = {observation.case_id: observation for observation in observations}

    route_hits = 0
    rag_mode_hits = 0
    single_shop_isolation_hits = 0
    single_shop_case_count = 0
    forbidden_shop_hits = 0
    forbidden_shop_case_count = 0
    facet_hits = 0
    facet_case_count = 0
    keyword_hits = 0
    keyword_case_count = 0
    latest_turn_hits = 0
    latest_turn_case_count = 0
    empty_count = 0
    dirty_context_count = 0
    recommendation_shop_counts: list[int] = []

    matched_case_count = 0
    for case_id, case in case_map.items():
        observation = observation_map.get(case_id)
        if observation is None:
            continue
        matched_case_count += 1

        metrics = dict(observation.metrics or {})
        evidence_pack = observation.evidence_pack
        evidence_items = list(getattr(evidence_pack, "items", []) or [])
        rag_mode = _clean_text(metrics.get("rag_mode") or getattr(evidence_pack, "rag_mode", None))
        route_gate = metrics.get("route_gate") or {}
        branch = _clean_text(route_gate.get("branch") or metrics.get("route_branch"))
        latest_turn_message = _clean_text(metrics.get("latest_turn_message"))
        expected_latest_turn = case.turns[-1] if case.turns else case.query

        if case.expected_route and branch == case.expected_route:
            route_hits += 1
        if case.expected_rag_mode and rag_mode == case.expected_rag_mode:
            rag_mode_hits += 1
        evidence_shop_ids = _observed_shop_ids(observation, evidence_pack)
        if not evidence_items:
            empty_count += 1
        if metrics.get("rag_dirty_reasons") or metrics.get("dirty_reasons"):
            dirty_context_count += 1

        if case.expected_shop_id is not None:
            single_shop_case_count += 1
            if evidence_shop_ids and all(shop_id == case.expected_shop_id for shop_id in evidence_shop_ids):
                single_shop_isolation_hits += 1
        elif case.expected_rag_mode == "recommendation_rag":
            if evidence_shop_ids:
                recommendation_shop_counts.append(len(set(evidence_shop_ids)))

        if case.forbidden_shop_ids and not set(case.forbidden_shop_ids).intersection(evidence_shop_ids):
            forbidden_shop_hits += 1
        if case.forbidden_shop_ids:
            forbidden_shop_case_count += 1
        elif not case.forbidden_shop_ids and case.expected_shop_id is None:
            forbidden_shop_hits += 1
            forbidden_shop_case_count += 1

        observed_facets = _observed_facets(observation, evidence_pack)
        if case.expected_facets:
            facet_case_count += 1
            if set(case.expected_facets).issubset(observed_facets):
                facet_hits += 1
        else:
            facet_hits += 1
            facet_case_count += 1

        observed_text = " ".join(
            filter(
                None,
                [
                    observation.answer,
                    " ".join(item.claim for item in evidence_items if getattr(item, "claim", None)),
                    " ".join(item.source_type for item in evidence_items if getattr(item, "source_type", None)),
                ],
            )
        )
        if case.expected_keywords:
            keyword_case_count += 1
            if all(keyword in observed_text for keyword in case.expected_keywords):
                keyword_hits += 1
        else:
            keyword_hits += 1
            keyword_case_count += 1

        if case.turns or case.query:
            latest_turn_case_count += 1
            if latest_turn_message == expected_latest_turn:
                latest_turn_hits += 1

    recommendation_diversity = (
        sum(recommendation_shop_counts) / float(len(recommendation_shop_counts) or 1)
        if recommendation_shop_counts
        else 0.0
    )

    matched_cases = max(matched_case_count, 1)
    single_shop_cases = max(single_shop_case_count, 1)
    forbidden_cases = max(forbidden_shop_case_count, 1)
    facet_cases = max(facet_case_count, 1)
    keyword_cases = max(keyword_case_count, 1)
    latest_turn_cases = max(latest_turn_case_count, 1)

    return {
        "case_count": len(case_map),
        "matched_case_count": matched_case_count,
        "route_match_rate": route_hits / float(matched_cases),
        "rag_mode_match_rate": rag_mode_hits / float(matched_cases),
        "single_shop_isolation_rate": single_shop_isolation_hits / float(single_shop_cases),
        "forbidden_shop_rate": forbidden_shop_hits / float(forbidden_cases),
        "facet_hit_rate": facet_hits / float(facet_cases),
        "keyword_hit_rate": keyword_hits / float(keyword_cases),
        "latest_turn_priority_rate": latest_turn_hits / float(latest_turn_cases),
        "empty_rate": empty_count / float(matched_cases),
        "dirty_context_rate": dirty_context_count / float(matched_cases),
        "recommendation_diversity": recommendation_diversity,
    }


def format_local_life_rag_eval_report(metrics: Mapping[str, float | int]) -> str:
    lines = [
        "Local Life RAG Eval Report",
        f"case_count: {metrics['case_count']}",
        f"matched_case_count: {metrics['matched_case_count']}",
        f"route_match_rate: {float(metrics['route_match_rate']):.4f}",
        f"rag_mode_match_rate: {float(metrics['rag_mode_match_rate']):.4f}",
        f"single_shop_isolation_rate: {float(metrics['single_shop_isolation_rate']):.4f}",
        f"forbidden_shop_rate: {float(metrics['forbidden_shop_rate']):.4f}",
        f"facet_hit_rate: {float(metrics['facet_hit_rate']):.4f}",
        f"keyword_hit_rate: {float(metrics['keyword_hit_rate']):.4f}",
        f"latest_turn_priority_rate: {float(metrics['latest_turn_priority_rate']):.4f}",
        f"empty_rate: {float(metrics['empty_rate']):.4f}",
        f"dirty_context_rate: {float(metrics['dirty_context_rate']):.4f}",
        f"recommendation_diversity: {float(metrics['recommendation_diversity']):.4f}",
    ]
    return "\n".join(lines)


def summarize_local_life_rag_observation(
    *,
    case: LocalLifeRagEvalCase,
    answer: str = "",
    metrics: Mapping[str, Any] | None = None,
    evidence_pack: LocalLifeEvidencePack | Mapping[str, Any] | None = None,
) -> LocalLifeRagEvalObservation:
    pack = evidence_pack
    if isinstance(pack, Mapping):
        pack = LocalLifeEvidencePack.model_validate(pack)
    return LocalLifeRagEvalObservation(
        case_id=case.case_id,
        query=case.query,
        answer=answer,
        metrics=dict(metrics or {}),
        evidence_pack=pack if isinstance(pack, LocalLifeEvidencePack) else None,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the local life RAG eval suite.")
    parser.add_argument("--cases", required=True, help="Path to rag_eval_cases.jsonl or rag_dirty_cases.jsonl.")
    parser.add_argument("--observations", required=True, help="Path to observed results jsonl.")
    parser.add_argument("--json", action="store_true", help="Print metrics as JSON.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    cases = load_local_life_rag_eval_cases(args.cases)
    observations = load_local_life_rag_eval_observations(args.observations)
    metrics = evaluate_local_life_rag_cases(cases, observations)

    if args.json:
        print(json.dumps(metrics, ensure_ascii=False, indent=2))
    else:
        print(format_local_life_rag_eval_report(metrics))
    return 0


def _observed_shop_ids(
    observation: LocalLifeRagEvalObservation,
    evidence_pack: LocalLifeEvidencePack | None,
) -> set[int]:
    shop_ids: set[int] = set()
    pack = evidence_pack or observation.evidence_pack
    if pack is not None:
        for item in getattr(pack, "items", []) or []:
            shop_id = getattr(item, "shop_id", None)
            if shop_id not in (None, ""):
                try:
                    shop_ids.add(int(shop_id))
                except Exception:
                    continue
        for candidate in getattr(pack, "ranked_candidates", []) or []:
            shop_id = getattr(candidate, "shop_id", None)
            if shop_id not in (None, ""):
                try:
                    shop_ids.add(int(shop_id))
                except Exception:
                    continue
    metrics = dict(observation.metrics or {})
    for shop_id in metrics.get("evidence_shop_ids") or []:
        try:
            shop_ids.add(int(shop_id))
        except Exception:
            continue
    return shop_ids


def _observed_facets(
    observation: LocalLifeRagEvalObservation,
    evidence_pack: LocalLifeEvidencePack | None,
) -> set[str]:
    facets: set[str] = set()
    pack = evidence_pack or observation.evidence_pack
    if pack is not None:
        for item in getattr(pack, "items", []) or []:
            chunk_type = _clean_text(getattr(item, "chunk_type", None))
            source_type = _clean_text(getattr(item, "source_type", None))
            if chunk_type:
                facets.add(chunk_type)
            if source_type:
                facets.add(source_type)
    metrics = dict(observation.metrics or {})
    for facet in metrics.get("rag_guardrail", {}).get("final_allowed_facets", []) or []:
        cleaned = _clean_text(facet)
        if cleaned:
            facets.add(cleaned)
    return {facet for facet in facets if facet}


def _to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except Exception:
        return None


def _load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    path = Path(path)
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
