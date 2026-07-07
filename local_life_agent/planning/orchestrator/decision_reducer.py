from __future__ import annotations

from typing import Any, Iterable

from .conflict_resolver import ConflictResolver, _as_dict
from .worker_result import WorkerResult


def _pick_answer_type(answer_types: list[str]) -> str:
    for preferred in ("comparison", "recommendation", "single_shop_query", "clarification"):
        if preferred in answer_types:
            return preferred
    return "single_shop_query" if answer_types else "general"


class DecisionReducer:
    """Merge worker decision outputs conservatively."""

    @staticmethod
    def reduce(worker_results: Iterable[WorkerResult | dict[str, Any]]) -> dict[str, Any]:
        normalized = [item.to_dict() if isinstance(item, WorkerResult) else dict(item or {}) for item in worker_results]
        conflict_report = ConflictResolver.resolve(normalized)

        answer_types: list[str] = []
        overall_ranking: list[dict[str, Any]] = []
        selected_targets: list[dict[str, Any]] = []
        claims: list[dict[str, Any]] = []
        forbidden_claims: list[str] = []
        must_mention_unknowns: list[str] = []
        answerable_facets: list[str] = []
        unknown_facets: list[str] = []
        failed_facets: list[str] = []
        required_disclaimers: list[str] = []
        uncertainty_notes: list[str] = list(conflict_report.uncertainty_notices)
        winner_provenance: dict[str, Any] = {}
        winner_uncertainty_note = ""
        stat_winner: dict[str, Any] | None = None
        best_for: dict[str, dict[str, Any]] = {}
        decision_context: dict[str, Any] = {}
        style_hints: list[str] = []
        candidate_summaries: list[dict[str, Any]] = []

        for item in normalized:
            decision_plan = _as_dict(item.get("decision_plan"))
            state_patch = _as_dict(item.get("state_patch"))
            combined = {**state_patch, **decision_plan}
            answer_type = str(combined.get("answer_type", "") or "").strip()
            if answer_type:
                answer_types.append(answer_type)
            overall_ranking.extend([_as_dict(entry) for entry in combined.get("overall_ranking") or combined.get("ranking") or []])
            selected_targets.extend([_as_dict(entry) for entry in combined.get("selected_targets") or []])
            claims.extend([_as_dict(entry) for entry in combined.get("claims") or []])
            forbidden_claims.extend([str(item).strip() for item in combined.get("forbidden_claims") or [] if str(item).strip()])
            candidate_summaries.extend([_as_dict(entry) for entry in combined.get("candidate_summaries") or []])
            decision_context.update(_as_dict(combined.get("decision_context")))
            style_hints.extend([str(item).strip() for item in combined.get("style_hints") or [] if str(item).strip()])
            best_for.update(_as_dict(combined.get("best_for")))
            must_mention_unknowns.extend([str(item).strip() for item in combined.get("must_mention_unknowns") or [] if str(item).strip()])
            answerable_facets.extend([str(item).strip() for item in combined.get("answerable_facets") or [] if str(item).strip()])
            unknown_facets.extend([str(item).strip() for item in combined.get("unknown_facets") or [] if str(item).strip()])
            failed_facets.extend([str(item).strip() for item in combined.get("failed_facets") or [] if str(item).strip()])
            required_disclaimers.extend([str(item).strip() for item in combined.get("required_disclaimers") or [] if str(item).strip()])
            if stat_winner is None:
                stat_winner = _as_dict(combined.get("statistical_winner")) or None
                if not stat_winner:
                    winner_shop_id = str(combined.get("winner_shop_id", "") or "").strip()
                    winner_shop_name = str(combined.get("winner_shop_name", "") or "").strip()
                    if winner_shop_id or winner_shop_name:
                        stat_winner = {
                            "shop_id": winner_shop_id,
                            "shop_name": winner_shop_name,
                            "winner_shop_id": winner_shop_id,
                            "winner_shop_name": winner_shop_name,
                        }
            if not winner_provenance and combined.get("winner_provenance"):
                winner_provenance = _as_dict(combined.get("winner_provenance"))

        winner_shop_id = conflict_report.winner_shop_id
        if not winner_shop_id and stat_winner:
            winner_shop_id = str(stat_winner.get("shop_id", "") or stat_winner.get("winner_shop_id", "")).strip()
        if conflict_report.has_conflict:
            winner_uncertainty_note = "; ".join(conflict_report.uncertainty_notices) or "conflicting worker results"
            stat_winner = None
            winner_shop_id = ""

        if not winner_provenance:
            winner_provenance = {
                "worker_count": len(normalized),
                "task_ids": [str(item.get("task_id", "")).strip() for item in normalized if str(item.get("task_id", "")).strip()],
            }

        return {
            "answer_type": _pick_answer_type(answer_types),
            "selected_targets": selected_targets,
            "overall_ranking": overall_ranking,
            "main_recommendation": stat_winner or (selected_targets[0] if selected_targets else None),
            "winner_shop_id": winner_shop_id,
            "winner_shop_name": _as_dict(stat_winner).get("shop_name", "") if stat_winner else "",
            "best_for": best_for,
            "factual_points": [str(item.get("factual_point", "")).strip() for item in normalized if str(item.get("factual_point", "")).strip()],
            "uncertainty_notes": uncertainty_notes,
            "statistical_winner": stat_winner,
            "winner_provenance": winner_provenance,
            "winner_uncertainty_note": winner_uncertainty_note,
            "forbidden_claims": list(dict.fromkeys(forbidden_claims)),
            "style_hints": list(dict.fromkeys(style_hints)),
            "decision_context": decision_context,
            "candidate_summaries": candidate_summaries,
            "must_mention_unknowns": list(dict.fromkeys([str(item).strip() for item in decision_context.get("must_mention_unknowns", []) if str(item).strip()])),
            "answerable_facets": list(dict.fromkeys([str(item).strip() for item in decision_context.get("answerable_facets", []) if str(item).strip()])),
            "unknown_facets": list(dict.fromkeys([str(item).strip() for item in decision_context.get("unknown_facets", []) if str(item).strip()])),
            "failed_facets": list(dict.fromkeys([str(item).strip() for item in decision_context.get("failed_facets", []) if str(item).strip()])),
            "required_disclaimers": list(dict.fromkeys([str(item).strip() for item in decision_context.get("required_disclaimers", []) if str(item).strip()])),
            "conversation_continuity": _as_dict(decision_context.get("conversation_continuity")),
            "decision_source": "complex_orchestrator_reducer",
            "decision_confidence": 0.75 if not conflict_report.has_conflict else 0.4,
            "decision_mode": "reduced",
            "fallback_used": conflict_report.has_conflict,
            "evidence_preserved": True,
            "decision_reason": "reduced from worker results",
            "claim_bindings": claims,
            "winner_evidence_refs": [str(item.get("evidence_id", "")).strip() for item in claims if str(item.get("evidence_id", "")).strip()],
            "must_mention_unknowns": list(dict.fromkeys(must_mention_unknowns)),
            "answerable_facets": list(dict.fromkeys(answerable_facets)),
            "unknown_facets": list(dict.fromkeys(unknown_facets)),
            "failed_facets": list(dict.fromkeys(failed_facets)),
            "required_disclaimers": list(dict.fromkeys(required_disclaimers)),
            "next_action": "run_workflow",
            "reason": "reduced worker results",
            "insufficient_evidence": conflict_report.has_conflict and not stat_winner,
            "comparison_support_status": "conflicted" if conflict_report.has_conflict else "supported",
            "ranking_preserved": not conflict_report.has_conflict,
            "conflict_summary": conflict_report.to_dict(),
        }
