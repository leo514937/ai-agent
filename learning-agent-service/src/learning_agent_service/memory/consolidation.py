from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Sequence

from learning_agent_service.domain.memory import MemoryConflict, MemoryConsolidationPlan, MemoryRecord, MemorySource, MemoryStatus, MemoryType


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class ConsolidationPolicyConfig:
    minimum_duplicate_group_size: int = 2
    max_conflicts: int = 8
    confirmed_explicitness: float = 1.0
    inferred_explicitness: float = 0.5
    recency_window_seconds: int = 60 * 60 * 24 * 7


@dataclass
class MemoryConsolidationJob:
    config: ConsolidationPolicyConfig = field(default_factory=ConsolidationPolicyConfig)

    def consolidate(self, records: Sequence[MemoryRecord]) -> tuple[List[MemoryRecord], List[MemoryConflict], List[MemoryConsolidationPlan]]:
        grouped: dict[tuple[str, str, str], List[MemoryRecord]] = {}
        for record in records:
            if record.status in {MemoryStatus.DELETED, MemoryStatus.EXPIRED, MemoryStatus.SUPERSEDED}:
                continue
            key = (record.user_id, record.type.value, record.summary or record.memory_id)
            grouped.setdefault(key, []).append(record)

        merged: List[MemoryRecord] = []
        conflicts: List[MemoryConflict] = []
        plans: List[MemoryConsolidationPlan] = []
        for _, items in grouped.items():
            if len(items) < self.config.minimum_duplicate_group_size:
                merged.append(items[0])
                continue
            items = sorted(items, key=lambda item: (item.importance, item.confidence, item.updated_at), reverse=True)
            winner = items[0]
            losers = items[1:]
            merged.append(winner)
            conflict = MemoryConflict(
                conflict_id=f"{winner.memory_id}:conflict",
                winner_memory_id=winner.memory_id,
                loser_memory_ids=[item.memory_id for item in losers],
                conflict_type=f"{winner.type.value}_duplicate",
                reason="重复记忆合并",
                resolved_by=winner.metadata.source if winner.metadata else MemorySource.SYSTEM_EVENT,
                resolved_at=_utcnow(),
            )
            conflicts.append(conflict)
            plans.append(
                MemoryConsolidationPlan(
                    source_memory_ids=[item.memory_id for item in items],
                    target_memory_id=winner.memory_id,
                    action="merge",
                    reason="重复记忆合并",
                )
            )
        return merged, conflicts[: self.config.max_conflicts], plans

    def expire_or_supersede(self, records: Sequence[MemoryRecord]) -> List[MemoryRecord]:
        updated: List[MemoryRecord] = []
        for record in records:
            expires_at = _as_utc(record.expires_at) if record.expires_at else None
            if expires_at and expires_at < _utcnow():
                updated.append(record.model_copy(update={"status": MemoryStatus.EXPIRED, "updated_at": _utcnow()}))
                continue
            updated.append(record)
        return updated

    def score_memory(self, record: MemoryRecord) -> float:
        recency = 0.0
        if record.last_accessed_at is not None:
            delta = max((_utcnow() - _as_utc(record.last_accessed_at)).total_seconds(), 0.0)
            recency_window = max(float(self.config.recency_window_seconds), 1.0)
            recency = max(0.0, 1.0 - min(delta / recency_window, 1.0))
        frequency = float(record.metadata.importance if record.metadata else record.importance)
        confidence = float(record.confidence)
        importance = float(record.importance)
        explicitness = (
            self.config.confirmed_explicitness
            if record.status in {MemoryStatus.CONFIRMED, MemoryStatus.ACTIVE}
            else self.config.inferred_explicitness
        )
        return recency + frequency + confidence + importance + explicitness
