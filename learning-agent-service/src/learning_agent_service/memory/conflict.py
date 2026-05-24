from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone
from typing import Iterable, List, Optional, Sequence

from learning_agent_service.domain.memory import (
    MemoryEdge,
    MemoryEdgeType,
    MemoryPersistenceScope,
    MemoryRecord,
    MemoryScope,
    MemorySensitivity,
    MemoryStatus,
    MemoryType,
)
from learning_agent_service.memory.preference_registry import DEFAULT_PREFERENCE_REGISTRY, PreferenceRegistry


class MemoryConflictResolutionStrategy(str, Enum):
    SUPERSEDE_OLD = "SUPERSEDE_OLD"
    MERGE = "MERGE"
    KEEP_BOTH = "KEEP_BOTH"
    REQUIRE_CONFIRMATION = "REQUIRE_CONFIRMATION"


class ConflictResolutionAction(str, Enum):
    INSERT_NEW = "insert_new"
    UPDATE_EXISTING = "update_existing"
    SUPERSEDE_OLD_INSERT_NEW = "supersede_old_insert_new"
    KEEP_OLD_IGNORE_NEW = "keep_old_ignore_new"
    SESSION_ONLY = "session_only"
    REQUIRE_CLARIFICATION = "require_clarification"


@dataclass
class MemoryConflictResolutionResult:
    strategy: MemoryConflictResolutionStrategy
    winner: MemoryRecord
    losers: List[MemoryRecord] = field(default_factory=list)
    merged_record: Optional[MemoryRecord] = None
    requires_confirmation: bool = False
    reason: str = ""
    edges: List[MemoryEdge] = field(default_factory=list)


@dataclass
class ConflictResolutionDecision:
    action: ConflictResolutionAction
    old_memory_id: Optional[str]
    new_memory: MemoryRecord
    reason: str
    confidence: float
    should_update_profile: bool
    should_update_qdrant: bool
    effective_from: Optional[datetime] = None
    effective_to: Optional[datetime] = None
    normalized_key: Optional[str] = None
    requires_clarification: bool = False


@dataclass
class MemoryConflictPolicyConfig:
    supersede_margin: float = 0.05
    merge_similarity_threshold: float = 0.65


@dataclass
class MemoryConflictResolver:
    """根据新旧记忆内容决定覆盖、合并、保留还是要求确认。"""

    config: MemoryConflictPolicyConfig = field(default_factory=MemoryConflictPolicyConfig)
    preference_registry: PreferenceRegistry = field(default_factory=lambda: DEFAULT_PREFERENCE_REGISTRY)

    def resolve_preference_change(
        self,
        incoming: MemoryRecord,
        existing_records: Sequence[MemoryRecord],
        *,
        temporal_scope: Optional[str] = None,
    ) -> ConflictResolutionDecision:
        normalized_key = incoming.normalized_key or self._normalize_key_from_record(incoming)
        if not normalized_key:
            return ConflictResolutionDecision(
                action=ConflictResolutionAction.KEEP_OLD_IGNORE_NEW,
                old_memory_id=None,
                new_memory=incoming,
                reason="missing_normalized_key",
                confidence=float(incoming.confidence or 0.0),
                should_update_profile=False,
                should_update_qdrant=False,
            )

        active_records = [record for record in existing_records if self._is_active(record)]
        conflicts = [record for record in active_records if self._same_key(record, normalized_key)]
        inferred_scope = temporal_scope or self._temporal_scope_from_record(incoming)
        if temporal_scope == "ambiguous" or self._is_session_only(incoming, inferred_scope):
            reason = "ambiguous_temporal_scope" if temporal_scope == "ambiguous" else "session_only_constraint"
            return ConflictResolutionDecision(
                action=ConflictResolutionAction.SESSION_ONLY,
                old_memory_id=conflicts[0].memory_id if conflicts else None,
                new_memory=incoming.model_copy(
                    update={
                        "normalized_key": normalized_key,
                        "normalized_value": incoming.normalized_value or self._normalized_value(normalized_key, incoming),
                        "persistence_scope": MemoryPersistenceScope.SESSION,
                        "is_active": False,
                    }
                ),
                reason=reason,
                confidence=float(incoming.confidence or 0.0),
                should_update_profile=False,
                should_update_qdrant=False,
                effective_from=datetime.now(timezone.utc),
                normalized_key=normalized_key,
                requires_clarification=temporal_scope == "ambiguous" and "最近" in (incoming.summary or ""),
            )

        if not conflicts:
            return ConflictResolutionDecision(
                action=ConflictResolutionAction.INSERT_NEW,
                old_memory_id=None,
                new_memory=incoming.model_copy(
                    update={
                        "normalized_key": normalized_key,
                        "normalized_value": incoming.normalized_value or self._normalized_value(normalized_key, incoming),
                        "persistence_scope": MemoryPersistenceScope.LONG_TERM,
                        "is_active": True,
                    }
                ),
                reason="no_active_conflict",
                confidence=float(incoming.confidence or 0.0),
                should_update_profile=True,
                should_update_qdrant=incoming.type in {MemoryType.SEMANTIC, MemoryType.EPISODIC, MemoryType.PROCEDURAL},
                effective_from=incoming.effective_from,
                normalized_key=normalized_key,
            )

        best_existing = max(conflicts, key=lambda item: (item.confidence, item.importance, item.updated_at))
        incoming_value = incoming.normalized_value or self._normalized_value(normalized_key, incoming)
        existing_value = best_existing.normalized_value or self._normalized_value(normalized_key, best_existing)
        if incoming_value == existing_value:
            updated = incoming.model_copy(
                update={
                    "memory_id": best_existing.memory_id,
                    "normalized_key": normalized_key,
                    "normalized_value": incoming_value,
                    "persistence_scope": MemoryPersistenceScope.LONG_TERM,
                    "is_active": True,
                    "status": best_existing.status,
                    "effective_from": best_existing.effective_from,
                    "effective_to": best_existing.effective_to,
                    "last_seen_at": datetime.now(timezone.utc),
                    "confidence": max(float(incoming.confidence or 0.0), float(best_existing.confidence or 0.0)),
                }
            )
            return ConflictResolutionDecision(
                action=ConflictResolutionAction.UPDATE_EXISTING,
                old_memory_id=best_existing.memory_id,
                new_memory=updated,
                reason="same_normalized_value",
                confidence=float(updated.confidence or 0.0),
                should_update_profile=True,
                should_update_qdrant=False,
                effective_from=best_existing.effective_from,
                effective_to=best_existing.effective_to,
                normalized_key=normalized_key,
            )

        incoming_long_term = self._is_long_term_change(incoming, inferred_scope)
        if not incoming_long_term:
            return ConflictResolutionDecision(
                action=ConflictResolutionAction.SESSION_ONLY,
                old_memory_id=best_existing.memory_id,
                new_memory=incoming.model_copy(
                    update={
                        "normalized_key": normalized_key,
                        "normalized_value": incoming_value,
                        "persistence_scope": MemoryPersistenceScope.SESSION,
                        "is_active": False,
                    }
                ),
                reason="prefer_session_constraint_for_ambiguous_change",
                confidence=float(incoming.confidence or 0.0),
                should_update_profile=False,
                should_update_qdrant=False,
                effective_from=datetime.now(timezone.utc),
                normalized_key=normalized_key,
            )

        updated = incoming.model_copy(
            update={
                "normalized_key": normalized_key,
                "normalized_value": incoming_value,
                "persistence_scope": MemoryPersistenceScope.LONG_TERM,
                "is_active": True,
                "effective_from": incoming.effective_from or datetime.now(timezone.utc),
                "status": MemoryStatus.ACTIVE,
            }
        )
        return ConflictResolutionDecision(
            action=ConflictResolutionAction.SUPERSEDE_OLD_INSERT_NEW,
            old_memory_id=best_existing.memory_id,
            new_memory=updated,
            reason="explicit_long_term_preference_change",
            confidence=float(updated.confidence or 0.0),
            should_update_profile=True,
            should_update_qdrant=updated.type in {MemoryType.SEMANTIC, MemoryType.EPISODIC, MemoryType.PROCEDURAL},
            effective_from=updated.effective_from,
            effective_to=best_existing.effective_to,
            normalized_key=normalized_key,
        )

    def resolve(self, incoming: MemoryRecord, existing_records: Sequence[MemoryRecord]) -> MemoryConflictResolutionResult:
        if incoming.type in {MemoryType.PREFERENCE, MemoryType.ENTITY} and (incoming.normalized_key or self._normalize_key_from_record(incoming)):
            decision = self.resolve_preference_change(incoming, existing_records, temporal_scope=self._temporal_scope_from_record(incoming))
            if decision.action == ConflictResolutionAction.SUPERSEDE_OLD_INSERT_NEW:
                loser = self._first_conflict(existing_records, decision.normalized_key)
                return MemoryConflictResolutionResult(
                    strategy=MemoryConflictResolutionStrategy.SUPERSEDE_OLD,
                    winner=decision.new_memory,
                    losers=[loser] if loser is not None else [],
                    reason=decision.reason,
                    edges=self._build_edges(incoming, [loser] if loser is not None else []),
                )
            if decision.action == ConflictResolutionAction.UPDATE_EXISTING:
                loser = self._first_conflict(existing_records, decision.normalized_key)
                return MemoryConflictResolutionResult(
                    strategy=MemoryConflictResolutionStrategy.MERGE,
                    winner=decision.new_memory,
                    losers=[loser] if loser is not None else [],
                    merged_record=decision.new_memory,
                    reason=decision.reason,
                )
            if decision.action == ConflictResolutionAction.SESSION_ONLY:
                return MemoryConflictResolutionResult(
                    strategy=MemoryConflictResolutionStrategy.KEEP_BOTH,
                    winner=decision.new_memory,
                    reason=decision.reason,
                )
        conflicts = self._find_conflicts(incoming, existing_records)
        if incoming.sensitivity in {MemorySensitivity.CONFIDENTIAL, MemorySensitivity.RESTRICTED}:
            edges = [
                MemoryEdge(
                    edge_id=f"{incoming.memory_id}:confirmation_required:{record.memory_id}",
                    source_memory_id=record.memory_id,
                    target_memory_id=incoming.memory_id,
                    edge_type=MemoryEdgeType.RELATED_TO,
                    reason="requires_confirmation",
                )
                for record in conflicts
            ]
            return MemoryConflictResolutionResult(
                strategy=MemoryConflictResolutionStrategy.REQUIRE_CONFIRMATION,
                winner=incoming,
                losers=list(conflicts),
                requires_confirmation=True,
                reason="sensitive_memory",
                edges=edges,
            )
        if not conflicts:
            return MemoryConflictResolutionResult(
                strategy=MemoryConflictResolutionStrategy.KEEP_BOTH,
                winner=incoming,
                reason="no_conflicts",
            )

        best_existing = max(conflicts, key=lambda item: (item.confidence, item.importance, item.updated_at))
        if self._should_supersede(incoming, best_existing):
            edges = [
                MemoryEdge(
                    edge_id=f"{loser.memory_id}:superseded_by:{incoming.memory_id}",
                    source_memory_id=loser.memory_id,
                    target_memory_id=incoming.memory_id,
                    edge_type=MemoryEdgeType.SUPERSEDES,
                    reason="higher_confidence_new_memory",
                )
                for loser in conflicts
            ]
            return MemoryConflictResolutionResult(
                strategy=MemoryConflictResolutionStrategy.SUPERSEDE_OLD,
                winner=incoming,
                losers=list(conflicts),
                reason="incoming_memory_has_higher_confidence",
                edges=edges,
            )

        if self._should_merge(incoming, best_existing):
            merged = self._merge_records(incoming, conflicts)
            return MemoryConflictResolutionResult(
                strategy=MemoryConflictResolutionStrategy.MERGE,
                winner=merged,
                losers=list(conflicts),
                merged_record=merged,
                reason="records_are_complementary",
            )

        return MemoryConflictResolutionResult(
            strategy=MemoryConflictResolutionStrategy.KEEP_BOTH,
            winner=incoming,
            losers=list(conflicts),
            reason="retain_parallel_memories",
            edges=[
                MemoryEdge(
                    edge_id=f"{record.memory_id}:related_to:{incoming.memory_id}",
                    source_memory_id=record.memory_id,
                    target_memory_id=incoming.memory_id,
                    edge_type=MemoryEdgeType.RELATED_TO,
                    reason="retain_parallel_memories",
                )
                for record in conflicts
            ],
        )

    def _find_conflicts(
        self,
        incoming: MemoryRecord,
        existing_records: Sequence[MemoryRecord],
    ) -> List[MemoryRecord]:
        conflicts: List[MemoryRecord] = []
        for record in existing_records:
            if record.user_id != incoming.user_id:
                continue
            if record.scope != incoming.scope:
                continue
            if record.type != incoming.type:
                continue
            if incoming.normalized_key or record.normalized_key:
                if not self._same_key(record, incoming.normalized_key or self._normalize_key_from_record(incoming)):
                    continue
            if incoming.topic and record.topic and record.topic != incoming.topic:
                continue
            if record.status in {MemoryStatus.DELETED, MemoryStatus.EXPIRED, MemoryStatus.SUPERSEDED, MemoryStatus.INACTIVE}:
                continue
            conflicts.append(record)
        return conflicts

    def _should_supersede(self, incoming: MemoryRecord, existing: MemoryRecord) -> bool:
        if incoming.confidence >= existing.confidence + self.config.supersede_margin:
            return True
        if incoming.importance >= existing.importance + self.config.supersede_margin:
            return True
        if incoming.summary and existing.summary and incoming.summary != existing.summary:
            similarity = self._text_similarity(incoming.summary, existing.summary)
            return similarity > 0.8 and incoming.confidence >= existing.confidence
        return False

    def _should_merge(self, incoming: MemoryRecord, existing: MemoryRecord) -> bool:
        if not incoming.summary or not existing.summary:
            return False
        similarity = self._text_similarity(incoming.summary, existing.summary)
        return similarity >= self.config.merge_similarity_threshold and incoming.type in {MemoryType.SEMANTIC, MemoryType.EPISODIC}

    @staticmethod
    def _is_active(record: MemoryRecord) -> bool:
        if record.status in {MemoryStatus.DELETED, MemoryStatus.EXPIRED, MemoryStatus.SUPERSEDED, MemoryStatus.INACTIVE}:
            return False
        return bool(getattr(record, "is_active", True))

    @staticmethod
    def _same_key(record: MemoryRecord, normalized_key: Optional[str]) -> bool:
        if not normalized_key:
            return False
        return (record.normalized_key or record.topic or "").strip().lower() == normalized_key.strip().lower()

    @staticmethod
    def _first_conflict(records: Sequence[MemoryRecord], normalized_key: Optional[str]) -> Optional[MemoryRecord]:
        for record in records:
            if normalized_key and MemoryConflictResolver._same_key(record, normalized_key):
                return record
        return None

    @staticmethod
    def _normalize_key_from_record(record: MemoryRecord) -> Optional[str]:
        normalized_key = record.normalized_key or ""
        if normalized_key:
            return normalized_key
        content = record.content if isinstance(record.content, dict) else {}
        for candidate in [str(content.get("normalized_key") or ""), str(content.get("preference_key") or "")]:
            if candidate.strip():
                return candidate.strip()
        return None

    @staticmethod
    def _normalized_value(normalized_key: str, record: MemoryRecord) -> str:
        value = record.normalized_value
        if value:
            return value
        content = record.content if isinstance(record.content, dict) else {}
        raw = str(content.get("normalized_value") or content.get("value") or record.summary or "")
        return DEFAULT_PREFERENCE_REGISTRY.normalize_value(normalized_key, raw)

    @staticmethod
    def _temporal_scope_from_record(record: MemoryRecord) -> str:
        content = record.content if isinstance(record.content, dict) else {}
        return str(content.get("temporal_scope") or getattr(record, "persistence_scope", "") or "")

    @staticmethod
    def _is_session_only(record: MemoryRecord, temporal_scope: Optional[str]) -> bool:
        scope = (temporal_scope or "").lower()
        if scope in {"turn", "session"}:
            return True
        text = f"{record.summary or ''} {record.content if isinstance(record.content, dict) else ''}"
        return DEFAULT_PREFERENCE_REGISTRY.infer_scope(text) == MemoryPersistenceScope.SESSION

    @staticmethod
    def _is_long_term_change(record: MemoryRecord, temporal_scope: Optional[str]) -> bool:
        scope = (temporal_scope or "").lower()
        if scope in {"long_term", "profile", "user"}:
            return True
        text = f"{record.summary or ''} {record.content if isinstance(record.content, dict) else ''}"
        return DEFAULT_PREFERENCE_REGISTRY.is_long_term_intent(text)

    @staticmethod
    def _build_edges(incoming: MemoryRecord, losers: Sequence[MemoryRecord]) -> List[MemoryEdge]:
        return [
            MemoryEdge(
                edge_id=f"{loser.memory_id}:superseded_by:{incoming.memory_id}",
                source_memory_id=loser.memory_id,
                target_memory_id=incoming.memory_id,
                edge_type=MemoryEdgeType.SUPERSEDES,
                reason="preference_change",
            )
            for loser in losers
            if loser is not None
        ]

    def _merge_records(self, incoming: MemoryRecord, conflicts: Sequence[MemoryRecord]) -> MemoryRecord:
        merged_content = {}
        for record in conflicts:
            if isinstance(record.content, dict):
                merged_content.update(record.content)
        if isinstance(incoming.content, dict):
            merged_content.update(incoming.content)
        merged_topic = incoming.topic or next((record.topic for record in conflicts if record.topic), None)
        merged_summary = incoming.summary or next((record.summary for record in conflicts if record.summary), None)
        merged_tags = list(dict.fromkeys([*(incoming.tags or []), *sum((list(record.tags or []) for record in conflicts), [])]))
        merged_entities = list(
            dict.fromkeys([*(incoming.entities or []), *sum((list(record.entities or []) for record in conflicts), [])])
        )
        merged_confidence = max([incoming.confidence, *[record.confidence for record in conflicts]])
        merged_importance = max([incoming.importance, *[record.importance for record in conflicts]])
        merged_stability = min([incoming.stability, *[record.stability for record in conflicts]])
        merged_valid_until = incoming.valid_until
        for record in conflicts:
            if merged_valid_until is None and record.valid_until is not None:
                merged_valid_until = record.valid_until
        return incoming.model_copy(
            update={
                "topic": merged_topic,
                "summary": merged_summary,
                "content": merged_content,
                "tags": merged_tags,
                "entities": merged_entities,
                "confidence": merged_confidence,
                "importance": merged_importance,
                "stability": merged_stability,
                "valid_until": merged_valid_until,
            }
        )

    @staticmethod
    def _text_similarity(left: str, right: str) -> float:
        left_tokens = {token for token in left.lower().split() if token}
        right_tokens = {token for token in right.lower().split() if token}
        if not left_tokens or not right_tokens:
            return 0.0
        overlap = len(left_tokens & right_tokens)
        union = len(left_tokens | right_tokens)
        return overlap / union if union else 0.0
