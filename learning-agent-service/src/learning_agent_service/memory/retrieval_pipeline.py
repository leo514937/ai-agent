from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from learning_agent_service.domain.guards import allow_memory_injection_status
from learning_agent_service.domain.memory import (
    EntityMemoryStore,
    LongTermMemoryStore,
    MemoryRecord,
    MemoryRetrievalPlan,
    MemoryScope,
    MemoryStatus,
    MemoryType,
    RetrievedMemoryPack,
    SessionMemoryStore,
    ShortTermMemoryStore,
)
from learning_agent_service.memory.models import MemoryRecallPlan, MemoryRecallSignals


@dataclass(frozen=True)
class RetrievalPolicyConfig:
    prompt_limit: int = 4
    state_limit: int = 6
    rag_limit: int = 6
    tool_limit: int = 4
    token_budget: int = 1200
    semantic_top_k: int = 5
    recall_top_k: int = 5
    recall_token_budget: int = 1200
    same_session_boost: float = 0.2
    current_topic_boost: float = 0.15
    history_summary_boost: float = 0.1
    active_plan_boost: float = 0.25
    final_summary_boost: float = 0.2
    recency_window_seconds: int = 60 * 60 * 24 * 7
    episodic_threshold: float = 0.55
    procedural_threshold: float = 0.5
    episodic_keywords: tuple[str, ...] = (
        "debug",
        "troubleshoot",
        "troubleshooting",
        "排错",
        "故障",
        "implementation",
        "实现",
        "problem",
    )
    procedural_keywords: tuple[str, ...] = (
        "how-to",
        "how to",
        "workflow",
        "tool",
        "步骤",
        "流程",
        "怎么",
        "如何",
        "debug",
        "implementation",
    )


@dataclass
class MemoryRetrievalPolicy:
    config: RetrievalPolicyConfig = field(default_factory=RetrievalPolicyConfig)

    def retrieve(
        self,
        *,
        user_id: str,
        session_id: str,
        project_id: str | None,
        raw_query: str,
        intent: str | None,
        current_topic: str | None,
        recent_entities: Sequence[str],
        history_summary: str | None,
        active_plan_id: str | None = None,
        response_mode: str | None = None,
        retrieval_budget: int | None = None,
        session_store: SessionMemoryStore | None = None,
        short_term_store: ShortTermMemoryStore | None = None,
        entity_store: EntityMemoryStore | None = None,
        mastery_store: Any | None = None,
        long_term_store: LongTermMemoryStore | None = None,
        recall_signals: MemoryRecallSignals | None = None,
    ) -> RetrievedMemoryPack:
        plan = MemoryRetrievalPlan(
            user_id=user_id,
            session_id=session_id,
            project_id=project_id,
            raw_query=raw_query or "",
            intent=intent,
            current_topic=current_topic,
            recent_entities=list(recent_entities),
            history_summary=history_summary,
            retrieval_budget=retrieval_budget or self.config.token_budget,
            response_mode=response_mode,
        )
        recall_plan = self.build_recall_plan(
            recall_signals
            or MemoryRecallSignals(
                intent=intent,
                raw_query=raw_query or "",
                current_topic=current_topic,
                history_summary=history_summary,
                recent_entities=tuple(recent_entities),
                active_plan_id=active_plan_id,
                response_mode=response_mode,
                session_id=session_id,
            )
        )
        prompt_memories: list[MemoryRecord] = []
        state_memories: list[MemoryRecord] = []
        tool_memories: list[MemoryRecord] = []
        semantic_memories: list[MemoryRecord] = []
        episodic_memories: list[MemoryRecord] = []
        procedural_memories: list[MemoryRecord] = []
        excluded_memories: list[MemoryRecord] = []
        source_memory_ids: list[str] = []
        budget_left = plan.retrieval_budget

        if session_store is not None:
            try:
                session_context = session_store.load(session_id, user_id)
            except Exception:
                session_context = None
            if session_context is not None:
                if getattr(session_context, "user_preferences", None):
                    profile_record = self._build_profile_record(session_context, user_id, session_id)
                    prompt_memories.append(profile_record)
                    source_memory_ids.append(profile_record.memory_id)
                    budget_left -= self._estimate_tokens(profile_record)
                session_record = self._build_session_record(session_context, user_id, session_id)
                prompt_memories.append(session_record)
                source_memory_ids.append(session_record.memory_id)
                budget_left -= self._estimate_tokens(session_record)

        if short_term_store is not None:
            for item in short_term_store.get_window(session_id, limit=self.config.state_limit):
                record = self._coerce_record(item, user_id=user_id, session_id=session_id)
                if record is None:
                    continue
                if self._status_allows_injection(record.status):
                    state_memories.append(record)
                    source_memory_ids.append(record.memory_id)
                    budget_left -= self._estimate_tokens(record)
                else:
                    excluded_memories.append(record)

        if entity_store is not None:
            entity_candidates = []
            if current_topic:
                entity_candidates.extend(entity_store.search(user_id, current_topic, limit=self.config.state_limit))
            for entity in entity_candidates:
                record = self._coerce_record(entity, user_id=user_id, session_id=session_id)
                if record is None:
                    continue
                if self._status_allows_injection(record.status):
                    state_memories.append(record)
                    source_memory_ids.append(record.memory_id)
                    budget_left -= self._estimate_tokens(record)

        if long_term_store is not None:
            preference_candidates = list(
                long_term_store.search(
                    "",
                    user_id=user_id,
                    limit=self.config.prompt_limit,
                    memory_types=(MemoryType.PREFERENCE,),
                )
            )
            for record in preference_candidates:
                if not self._status_allows_injection(record.status):
                    excluded_memories.append(record)
                    continue
                prompt_memories.append(record)
                source_memory_ids.append(record.memory_id)
                budget_left -= self._estimate_tokens(record)
            semantic_query = " ".join(
                part
                for part in [raw_query, current_topic, history_summary, " ".join(recent_entities)]
                if part
            )
            semantic_candidates = list(
                long_term_store.search(
                    semantic_query,
                    user_id=user_id,
                    limit=recall_plan.top_k,
                    memory_types=(MemoryType.SEMANTIC, MemoryType.PREFERENCE),
                )
            )
            episodic_candidates: list[MemoryRecord] = []
            procedural_candidates: list[MemoryRecord] = []
            if recall_plan.recall_episodic:
                episodic_candidates = list(
                    long_term_store.search(
                        semantic_query,
                        user_id=user_id,
                        limit=recall_plan.top_k,
                        memory_types=(MemoryType.EPISODIC,),
                    )
                )
            if recall_plan.recall_procedural:
                procedural_candidates = list(
                    long_term_store.search(
                        semantic_query,
                        user_id=user_id,
                        limit=recall_plan.top_k,
                        memory_types=(MemoryType.PROCEDURAL,),
                    )
                )
            if not semantic_candidates and not episodic_candidates and not procedural_candidates:
                fallback_records: list[MemoryRecord] = []
                for scope in (MemoryScope.USER, MemoryScope.PROJECT, MemoryScope.GLOBAL):
                    fallback_records.extend(list(long_term_store.list_by_scope(user_id, scope)))
                fallback_records = fallback_records[: recall_plan.top_k]
                for record in fallback_records:
                    if record.type == MemoryType.SEMANTIC:
                        semantic_candidates.append(record)
                    elif record.type == MemoryType.EPISODIC:
                        episodic_candidates.append(record)
                    elif record.type == MemoryType.PROCEDURAL:
                        procedural_candidates.append(record)
                    elif record.type == MemoryType.PREFERENCE:
                        prompt_memories.append(record)
            for record in semantic_candidates + episodic_candidates + procedural_candidates:
                if not self._status_allows_injection(record.status):
                    excluded_memories.append(record)
                    continue
                if record.type == MemoryType.PREFERENCE:
                    prompt_memories.append(record)
                    source_memory_ids.append(record.memory_id)
                    budget_left -= self._estimate_tokens(record)
                elif record.type == MemoryType.SEMANTIC:
                    semantic_memories.append(record)
                    source_memory_ids.append(record.memory_id)
                    budget_left -= self._estimate_tokens(record)
                elif record.type == MemoryType.EPISODIC:
                    episodic_memories.append(record)
                    source_memory_ids.append(record.memory_id)
                    budget_left -= self._estimate_tokens(record)
                elif record.type == MemoryType.PROCEDURAL:
                    procedural_memories.append(record)
                    source_memory_ids.append(record.memory_id)
                    budget_left -= self._estimate_tokens(record)

        prompt_memories = self._truncate(prompt_memories, self.config.prompt_limit, budget_left)
        state_memories = self._truncate(state_memories, self.config.state_limit, budget_left)
        semantic_memories = self._truncate(semantic_memories, self.config.rag_limit, budget_left)
        episodic_memories = self._truncate(episodic_memories, max(1, self.config.recall_top_k), budget_left)
        procedural_memories = self._truncate(procedural_memories, max(1, self.config.recall_top_k), budget_left)
        tool_memories = self._truncate(list(procedural_memories), self.config.tool_limit, budget_left)

        retrieval_reason = "session+entity+long-term"
        if recall_plan.enabled:
            retrieval_reason += f"|recall:{recall_plan.reason or 'signal'}"
        if semantic_memories:
            retrieval_reason += "|semantic"
        if episodic_memories:
            retrieval_reason += "|episodic"
        if procedural_memories:
            retrieval_reason += "|procedural"

        return RetrievedMemoryPack(
            prompt_memories=prompt_memories,
            state_memories=state_memories,
            tool_memories=tool_memories,
            semantic_memories=semantic_memories,
            episodic_memories=episodic_memories,
            procedural_memories=procedural_memories,
            rag_memories=list(semantic_memories),
            excluded_memories=excluded_memories,
            retrieval_reason=retrieval_reason,
            total_token_estimate=sum(
                self._estimate_tokens(record)
                for record in prompt_memories + state_memories + tool_memories + semantic_memories + episodic_memories + procedural_memories
            ),
            source_memory_ids=list(dict.fromkeys(source_memory_ids)),
            retrieval_kind="long_term_memory",
            collection_name=str(getattr(long_term_store, "collection_name", "") or getattr(long_term_store, "_collection_name", "") or ""),
            source_domain="memory",
        )

    @staticmethod
    def _status_allows_injection(status: MemoryStatus) -> bool:
        return allow_memory_injection_status(status)

    def _should_retrieve_episodic(self, intent: str | None, raw_query: str) -> bool:
        return self.build_recall_plan(MemoryRecallSignals(intent=intent, raw_query=raw_query or "")).recall_episodic

    def _should_retrieve_procedural(self, intent: str | None, raw_query: str) -> bool:
        return self.build_recall_plan(MemoryRecallSignals(intent=intent, raw_query=raw_query or "")).recall_procedural

    def build_recall_plan(self, signals: MemoryRecallSignals) -> MemoryRecallPlan:
        query_text = " ".join(
            part
            for part in [
                signals.intent,
                signals.raw_query,
                signals.current_topic,
                signals.history_summary,
                " ".join(signals.recent_entities),
                signals.execution_mode,
                signals.task_complexity,
                str(signals.final_task_summary or ""),
                " ".join(signals.open_questions),
                " ".join(signals.confirmed_facts),
                " ".join(signals.next_steps),
            ]
            if part
        ).lower()

        episodic_score = 0.0
        procedural_score = 0.0
        episodic_reasons: list[str] = []
        procedural_reasons: list[str] = []

        if any(keyword in query_text for keyword in self.config.episodic_keywords):
            episodic_score += 0.35
            episodic_reasons.append("episodic_keyword")
        if any(keyword in query_text for keyword in self.config.procedural_keywords):
            procedural_score += 0.35
            procedural_reasons.append("procedural_keyword")
        if signals.session_id and signals.turn_id:
            episodic_score += self.config.same_session_boost
            procedural_score += self.config.same_session_boost * 0.5
            episodic_reasons.append("same_session")
            procedural_reasons.append("same_session")
        if signals.current_topic:
            episodic_score += self.config.current_topic_boost
            procedural_score += self.config.current_topic_boost * 0.5
            episodic_reasons.append("current_topic")
        if signals.history_summary:
            episodic_score += self.config.history_summary_boost
            procedural_score += self.config.history_summary_boost * 0.5
            episodic_reasons.append("history_summary")
        if signals.active_plan_id:
            episodic_score += self.config.active_plan_boost
            procedural_score += self.config.active_plan_boost
            episodic_reasons.append("active_plan")
            procedural_reasons.append("active_plan")
        if signals.final_task_summary:
            episodic_score += self.config.final_summary_boost
            procedural_score += self.config.final_summary_boost
            episodic_reasons.append("final_task_summary")
            procedural_reasons.append("final_task_summary")
        if signals.execution_mode and str(signals.execution_mode).lower() == "plan_execute":
            procedural_score += 0.25
            procedural_reasons.append("plan_execute")
        if signals.task_complexity and str(signals.task_complexity).lower() == "complex":
            procedural_score += 0.15
            procedural_reasons.append("complex_task")
        if signals.open_questions:
            episodic_score += 0.05
            procedural_score += 0.05
        if signals.next_steps:
            episodic_score += 0.05
            procedural_score += 0.1
        if signals.confirmed_facts:
            episodic_score += 0.05

        episodic_score = min(1.0, episodic_score)
        procedural_score = min(1.0, procedural_score)
        enabled = episodic_score >= self.config.episodic_threshold or procedural_score >= self.config.procedural_threshold
        reason_parts = []
        if episodic_reasons:
            reason_parts.append("episodic:" + ",".join(dict.fromkeys(episodic_reasons)))
        if procedural_reasons:
            reason_parts.append("procedural:" + ",".join(dict.fromkeys(procedural_reasons)))
        if not reason_parts and query_text:
            reason_parts.append("keyword_query")
        return MemoryRecallPlan(
            enabled=enabled,
            episodic_score=episodic_score,
            procedural_score=procedural_score,
            recall_episodic=episodic_score >= self.config.episodic_threshold,
            recall_procedural=procedural_score >= self.config.procedural_threshold,
            reason="|".join(reason_parts),
            top_k=self.config.recall_top_k,
            token_budget=self.config.recall_token_budget,
            same_session_boost=self.config.same_session_boost,
            recency_window_seconds=self.config.recency_window_seconds,
            extra={
                "current_topic": signals.current_topic,
                "history_summary": bool(signals.history_summary),
                "active_plan_id": signals.active_plan_id,
                "execution_mode": signals.execution_mode,
                "task_complexity": signals.task_complexity,
            },
        )

    @staticmethod
    def _estimate_tokens(record: MemoryRecord) -> int:
        text = " ".join(
            [
                record.summary or "",
                str(record.content),
                " ".join(record.tags),
                " ".join(record.entities),
            ]
        )
        return max(8, len(text) // 4 + 1)

    def _truncate(self, records: list[MemoryRecord], limit: int, budget_left: int) -> list[MemoryRecord]:
        selected: list[MemoryRecord] = []
        remaining = budget_left
        for record in sorted(records, key=lambda item: (item.importance, item.confidence, item.updated_at), reverse=True):
            if len(selected) >= limit:
                break
            cost = self._estimate_tokens(record)
            if remaining - cost < 0 and selected:
                continue
            selected.append(record)
            remaining -= cost
        return selected

    @staticmethod
    def _coerce_record(item: Any, *, user_id: str, session_id: str) -> MemoryRecord | None:
        if isinstance(item, MemoryRecord):
            return item
        if isinstance(item, Mapping):
            payload = dict(item)
        elif hasattr(item, "model_dump"):
            payload = item.model_dump(mode="json")
        else:
            return None
        if "role" in payload and "content" in payload and "memory_id" not in payload:
            return MemoryRecord(
                memory_id=f"{session_id}:short-term:{len(payload.get('content', ''))}",
                user_id=user_id,
                session_id=session_id,
                type=MemoryType.SHORT_TERM,
                scope=MemoryScope.SESSION,
                status=MemoryStatus.ACTIVE,
                content={
                    "role": payload.get("role"),
                    "content": payload.get("content"),
                    "turn_id": payload.get("turn_id"),
                },
                summary=str(payload.get("content") or "")[:240],
                source_turn_id=str(payload.get("turn_id") or session_id),
                confidence=0.55,
                importance=0.55,
                tags=["short_term"],
                entities=[str(payload.get("content") or "")[:40]] if payload.get("content") else [],
            )
        payload.setdefault("user_id", user_id)
        payload.setdefault("session_id", session_id)
        payload.setdefault("source_turn_id", "")
        return MemoryRecord.model_validate(payload)

    @staticmethod
    def _build_session_record(context: Any, user_id: str, session_id: str) -> MemoryRecord:
        return MemoryRecord(
            memory_id=f"{session_id}:session-summary",
            user_id=user_id,
            session_id=session_id,
            type=MemoryType.SESSION_SUMMARY,
            scope=MemoryScope.SESSION,
            content={
                "current_topic": getattr(context, "current_topic", None),
                "recent_entities": list(getattr(context, "recent_entities", []) or []),
                "history_summary": getattr(context, "history_summary", None),
                "open_questions": list(getattr(context, "open_questions", []) or []),
                "confirmed_facts": list(getattr(context, "confirmed_facts", []) or []),
                "next_steps": list(getattr(context, "next_steps", []) or []),
            },
            summary=getattr(context, "history_summary", None),
            source_turn_id=session_id,
            confidence=0.8,
            importance=0.8,
            tags=["session_summary"],
            entities=list(getattr(context, "recent_entities", []) or []),
        )

    @staticmethod
    def _build_profile_record(context: Any, user_id: str, session_id: str) -> MemoryRecord:
        preferences = dict(getattr(context, "user_preferences", {}) or {})
        return MemoryRecord(
            memory_id=f"{session_id}:current-profile",
            user_id=user_id,
            session_id=session_id,
            type=MemoryType.PREFERENCE,
            scope=MemoryScope.USER,
            status=MemoryStatus.ACTIVE,
            content=preferences,
            summary="current_profile",
            source_turn_id=session_id,
            confidence=0.95,
            importance=0.9,
            tags=["profile", "preference"],
            entities=list(preferences.keys())[:5],
            normalized_key="current_profile",
            normalized_value="active",
            is_active=True,
        )

