from __future__ import annotations

from collections import OrderedDict
from typing import Any, Iterable

from .conflict_resolver import ConflictResolver, _as_dict
from .worker_result import WorkerResult


def _merge_list_field(items: Iterable[Any]) -> list[Any]:
    merged: list[Any] = []
    seen: set[str] = set()
    for item in items:
        key = repr(item)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


class EvidenceReducer:
    """Merge multiple worker evidence outputs without losing provenance."""

    @staticmethod
    def reduce(worker_results: Iterable[WorkerResult | dict[str, Any]]) -> dict[str, Any]:
        normalized = [item.to_dict() if isinstance(item, WorkerResult) else dict(item or {}) for item in worker_results]
        conflict_report = ConflictResolver.resolve(normalized)

        tool_results: dict[str, Any] = OrderedDict()
        evidence_items: list[dict[str, Any]] = []
        citations: list[dict[str, Any]] = []
        cards: list[dict[str, Any]] = []
        claims: list[dict[str, Any]] = []
        uncertainty_notices: list[str] = list(conflict_report.uncertainty_notices)
        provenance: list[dict[str, Any]] = []
        answerable_facets: list[str] = []
        unknown_facets: list[str] = []
        failed_facets: list[str] = []
        comparison_rows: list[dict[str, Any]] = []
        stage_queries: list[str] = []
        stage_statuses: list[str] = []

        for item in normalized:
            provenance.append(
                {
                    "task_id": item.get("task_id", ""),
                    "workflow_name": item.get("workflow_name", ""),
                    "status": item.get("status", ""),
                }
            )
            evidence_pack = _as_dict(item.get("evidence_pack"))
            state_patch = _as_dict(item.get("state_patch"))
            combined = {**state_patch, **evidence_pack}
            tool_results.update(_as_dict(combined.get("tool_results")))
            evidence_items.extend([_as_dict(entry) for entry in combined.get("evidence_items") or []])
            citations.extend([_as_dict(entry) for entry in combined.get("citations") or []])
            cards.extend([_as_dict(entry) for entry in combined.get("cards") or []])
            claims.extend([_as_dict(entry) for entry in combined.get("claims") or []])
            answerable_facets.extend([str(item).strip() for item in combined.get("answerable_facets") or [] if str(item).strip()])
            unknown_facets.extend([str(item).strip() for item in combined.get("unknown_facets") or [] if str(item).strip()])
            failed_facets.extend([str(item).strip() for item in combined.get("failed_facets") or [] if str(item).strip()])
            comparison_matrix = _as_dict(combined.get("comparison_matrix"))
            comparison_rows.extend([_as_dict(row) for row in comparison_matrix.get("rows") or []])
            stage_queries.extend([str(item).strip() for item in combined.get("stage_queries") or [] if str(item).strip()])
            stage_statuses.extend([str(item).strip() for item in combined.get("stage_statuses") or [] if str(item).strip()])

        return {
            "tool_results": dict(tool_results),
            "evidence_items": evidence_items,
            "citations": citations,
            "cards": cards,
            "claims": claims,
            "answerable_facets": list(dict.fromkeys(answerable_facets)),
            "unknown_facets": list(dict.fromkeys(unknown_facets)),
            "failed_facets": list(dict.fromkeys(failed_facets)),
            "comparison_matrix": {"rows": comparison_rows, "status": "reduced"} if comparison_rows else {},
            "uncertainty_notices": uncertainty_notices,
            "provenance": provenance,
            "conflict_summary": conflict_report.to_dict(),
            "stage_queries": list(dict.fromkeys(stage_queries)),
            "stage_statuses": list(dict.fromkeys(stage_statuses)),
        }
