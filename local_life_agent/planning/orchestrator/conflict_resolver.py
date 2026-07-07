from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .worker_result import WorkerResult


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        if isinstance(dumped, dict):
            return dumped
    return dict(getattr(value, "__dict__", {}) or {})


@dataclass
class ConflictReport:
    has_conflict: bool = False
    conflicts: list[str] = field(default_factory=list)
    winner_shop_id: str = ""
    uncertainty_notices: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "has_conflict": self.has_conflict,
            "conflicts": list(self.conflicts),
            "winner_shop_id": self.winner_shop_id,
            "uncertainty_notices": list(self.uncertainty_notices),
            "provenance": dict(self.provenance),
        }


class ConflictResolver:
    """Resolve inconsistent evidence or decision outputs conservatively."""

    @staticmethod
    def resolve(worker_results: Iterable[WorkerResult | dict[str, Any]]) -> ConflictReport:
        normalized: list[dict[str, Any]] = []
        for item in worker_results:
            if isinstance(item, WorkerResult):
                normalized.append(item.to_dict())
            else:
                normalized.append(dict(item or {}))

        shop_ids = [str(_as_dict(item.get("decision_plan")).get("winner_shop_id", "") or item.get("winner_shop_id", "")).strip() for item in normalized]
        shop_ids = [shop_id for shop_id in shop_ids if shop_id]
        answer_types = [
            str(_as_dict(item.get("decision_plan")).get("answer_type", "") or item.get("answer_type", "")).strip()
            for item in normalized
            if str(_as_dict(item.get("decision_plan")).get("answer_type", "") or item.get("answer_type", "")).strip()
        ]

        conflicts: list[str] = []
        uncertainty_notices: list[str] = []
        if len(set(shop_ids)) > 1:
            conflicts.append(f"winner_conflict:{','.join(dict.fromkeys(shop_ids))}")
            uncertainty_notices.append("multiple workers produced different winners")
        if len(set(answer_types)) > 1:
            conflicts.append(f"answer_type_conflict:{','.join(dict.fromkeys(answer_types))}")
            uncertainty_notices.append("multiple workers produced different answer types")

        provenance = {
            "worker_count": len(normalized),
            "task_ids": [str(item.get("task_id", "")).strip() for item in normalized if str(item.get("task_id", "")).strip()],
        }
        return ConflictReport(
            has_conflict=bool(conflicts),
            conflicts=conflicts,
            winner_shop_id=shop_ids[0] if len(set(shop_ids)) == 1 and shop_ids else "",
            uncertainty_notices=uncertainty_notices,
            provenance=provenance,
        )
