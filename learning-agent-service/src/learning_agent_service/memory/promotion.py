from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Tuple

from learning_agent_service.domain.memory import MemoryCandidate
from learning_agent_service.domain.memory import MemorySource
from learning_agent_service.memory.preferences import extract_preference_signal

from .canonical import CanonicalTopicResolver
from .gates import MemoryPromotionGate
from .models import (
    DurableFactRequest,
    MemoryPromotionInput,
    MemoryPromotionResult,
    PersistSessionPlan,
    PersistentSessionContext,
    SemanticMemoryFact,
    SessionUpdate,
)
from .extraction import LLMMemoryExtractor, RuleBasedMemoryExtractor
from .governance import MemoryGovernancePolicy


def _mapping_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


@dataclass(frozen=True)
class PromotionConfig:
    preference_promote_count: int = 3


@dataclass(frozen=True)
class DurableMemoryWritePlan:
    session_update: SessionUpdate
    preference_patch: Mapping[str, Any]
    session_preference_patch: Mapping[str, Any]
    profile_updates: Tuple[Mapping[str, Any], ...]
    semantic_facts: Tuple[SemanticMemoryFact, ...]
    weak_topics: Tuple[str, ...]
    durable_fact_requests: Tuple[DurableFactRequest, ...]
    outbox_events: Tuple[Mapping[str, Any], ...]


class SessionMemoryUpdater:
    def __init__(self, resolver: Optional[CanonicalTopicResolver] = None) -> None:
        self._resolver = resolver or CanonicalTopicResolver()

    def build_update(
        self,
        current: PersistentSessionContext,
        resolved_topic: Optional[str],
        clarification_result: Optional[Mapping[str, Any]] = None,
        summary_payload: Optional[Mapping[str, Any]] = None,
    ) -> SessionUpdate:
        topic = self._resolver.canonicalize(resolved_topic) if resolved_topic else current.current_topic
        entities = list(current.recent_entities)
        if topic:
            entities.insert(0, topic)
        deduped_entities = tuple(dict.fromkeys(entity for entity in entities if entity))[:5]
        extra_summary = dict(current.extra)
        extra_summary.update(dict(summary_payload or {}))
        current_open_questions = tuple(current.open_questions)
        current_confirmed_facts = tuple(current.confirmed_facts)
        current_next_steps = tuple(current.next_steps)
        open_questions = tuple(dict.fromkeys(current_open_questions + tuple(extra_summary.get("open_questions", ()))))[
            :5
        ]
        confirmed_facts = tuple(dict.fromkeys(current_confirmed_facts + tuple(extra_summary.get("confirmed_facts", ()))))[:8]
        next_steps = tuple(dict.fromkeys(current_next_steps + tuple(extra_summary.get("next_steps", ()))))[:5]
        summary_changed = bool(topic or open_questions or confirmed_facts or next_steps or clarification_result)
        return SessionUpdate(
            current_topic=topic,
            recent_entities=deduped_entities,
            clarification_result=_mapping_dict(clarification_result),
            last_retrieval_topic=topic or current.last_retrieval_topic,
            history_summary=self._build_history_summary(
                current.history_summary,
                topic,
                open_questions=open_questions,
                confirmed_facts=confirmed_facts,
                next_steps=next_steps,
            ),
            open_questions=open_questions,
            confirmed_facts=confirmed_facts,
            next_steps=next_steps,
            summary_version=current.summary_version + (1 if summary_changed else 0),
            summary_updated_at=datetime.now(timezone.utc) if summary_changed else current.summary_updated_at,
            pending_clarification=_mapping_dict(clarification_result) or current.pending_clarification,
        )

    def merge_context(self, current: PersistentSessionContext, update: SessionUpdate) -> PersistentSessionContext:
        extra = dict(current.extra)
        extra.update(dict(update.extra))
        return PersistentSessionContext(
            current_topic=update.current_topic or current.current_topic,
            recent_entities=update.recent_entities or current.recent_entities,
            clarification_result=update.clarification_result or current.clarification_result,
            user_preferences=current.user_preferences,
            last_retrieval_topic=update.last_retrieval_topic or current.last_retrieval_topic,
            history_summary=update.history_summary or current.history_summary,
            open_questions=update.open_questions or current.open_questions,
            confirmed_facts=update.confirmed_facts or current.confirmed_facts,
            next_steps=update.next_steps or current.next_steps,
            summary_version=update.summary_version or current.summary_version,
            summary_updated_at=update.summary_updated_at or current.summary_updated_at,
            pending_clarification=update.pending_clarification,
            extra=extra,
        )

    def _build_history_summary(
        self,
        current_summary: Optional[str],
        topic: Optional[str],
        *,
        open_questions: Tuple[str, ...] = (),
        confirmed_facts: Tuple[str, ...] = (),
        next_steps: Tuple[str, ...] = (),
    ) -> Optional[str]:
        canonical_topic = self._resolver.canonicalize(topic) if topic else ""
        segments = [segment.strip() for segment in (current_summary or "").split(" -> ") if segment.strip()]
        if canonical_topic:
            if canonical_topic in segments:
                segments = [segment for segment in segments if segment != canonical_topic]
            segments.append(canonical_topic)
        if confirmed_facts:
            segments.append("确认:" + "，".join(confirmed_facts[:2]))
        if open_questions:
            segments.append("待解:" + "，".join(open_questions[:2]))
        if next_steps:
            segments.append("下一步:" + "，".join(next_steps[:2]))
        if not segments:
            return current_summary
        return " -> ".join(segments[-4:])


class MemoryPromotionPolicy:
    def __init__(
        self,
        config: PromotionConfig = None,
        resolver: Optional[CanonicalTopicResolver] = None,
        extractor: Optional[RuleBasedMemoryExtractor] = None,
        llm_extractor: Optional[LLMMemoryExtractor] = None,
        governance: Optional[MemoryGovernancePolicy] = None,
        promotion_gate: Optional[MemoryPromotionGate] = None,
    ) -> None:
        self.config = config or PromotionConfig()
        self._resolver = resolver or CanonicalTopicResolver()
        self._updater = SessionMemoryUpdater(self._resolver)
        self._extractor = extractor or RuleBasedMemoryExtractor()
        self._llm_extractor = llm_extractor or LLMMemoryExtractor()
        self._governance = governance or MemoryGovernancePolicy()
        self._promotion_gate = promotion_gate or MemoryPromotionGate()

    def govern_candidates(self, candidates: List[MemoryCandidate]) -> List[MemoryCandidate]:
        return self._governance.evaluate_many(candidates)

    def evaluate(self, payload: MemoryPromotionInput) -> MemoryPromotionResult:
        now = payload.current_time or datetime.now(timezone.utc)
        topic = self._resolver.canonicalize(payload.resolved_topic) if payload.resolved_topic else None
        session_update = self._updater.build_update(
            current=payload.current_session,
            resolved_topic=topic,
            clarification_result=payload.extra.get("clarification_result"),
            summary_payload=payload.extra,
        )

        reasons: List[str] = []
        preference_patch: Dict[str, Any] = {}
        session_preference_patch: Dict[str, Any] = {}
        profile_updates: List[Dict[str, Any]] = []
        durable_fact_requests: List[DurableFactRequest] = []
        semantic_facts: List[SemanticMemoryFact] = []
        outbox_events: List[Mapping[str, Any]] = []

        profile = payload.current_preferences
        counters = dict(profile.answer_style_counter) if profile else {}

        output_style = payload.explicit_signals.preferred_output_style or payload.output_style
        if output_style:
            counters[output_style] = counters.get(output_style, 0) + 1
            preference_patch["answer_style_counter"] = counters
            if (
                payload.explicit_signals.confirmed_output_style
                or counters[output_style] >= self.config.preference_promote_count
            ):
                preference_patch["preferred_output_style"] = output_style
                reasons.append("promoted_output_style")

        preference_signal = extract_preference_signal(
            text=payload.query,
            answer_text=payload.answer_text,
            session_id=payload.session_id,
            turn_id=payload.turn_id,
        )
        if preference_signal is not None:
            if preference_signal.persistence_scope.value == "session" or preference_signal.requires_clarification:
                session_preference_patch[preference_signal.preference_key] = preference_signal.current_value
                session_preference_patch[f"{preference_signal.preference_key}.scope"] = preference_signal.persistence_scope.value
                if preference_signal.requires_clarification:
                    reasons.append("preference_requires_clarification")
            else:
                session_preference_patch[preference_signal.preference_key] = preference_signal.current_value
                profile_updates.append(
                    {
                        "user_id": payload.user_id,
                        "session_id": payload.session_id,
                        "turn_id": payload.turn_id,
                        "preference_key": preference_signal.preference_key,
                        "current_value": preference_signal.current_value,
                        "confidence": preference_signal.confidence,
                        "source_session_id": payload.session_id,
                        "source_turn_id": payload.turn_id,
                        "effective_from": preference_signal.effective_from,
                        "effective_to": preference_signal.effective_to,
                        "status": "active",
                        "is_active": True,
                        "should_update_profile": True,
                        "should_update_qdrant": preference_signal.should_update_qdrant,
                        "persistence_scope": preference_signal.persistence_scope.value,
                        "reason": preference_signal.reason,
                    }
                )

        if preference_patch:
            durable_fact_requests.append(
                DurableFactRequest(
                    fact_type="preference_patch",
                    payload={
                        "user_id": payload.user_id,
                        "session_id": payload.session_id,
                        "turn_id": payload.turn_id,
                        "patch": dict(preference_patch),
                    },
                )
            )

        if topic and self._should_promote_semantic_fact(payload):
            source = str(payload.extra.get("source") or MemorySource.MODEL_INFERRED.value)
            fact_type = str(payload.extra.get("fact_type") or "semantic_fact")
            fact = SemanticMemoryFact(
                fact_id="%s:%s:%s" % (payload.user_id, payload.turn_id, topic),
                topic=topic,
                content=(payload.answer_text or payload.query)[:240],
                fact_type="semantic_fact",
                strength=0.82,
                created_at=now,
                last_referenced_at=now,
                metadata={
                    "intent": payload.intent,
                    "tool_name": payload.tool_name,
                    "output_style": output_style,
                    "source": source,
                    "fact_type": fact_type,
                    "memory_type": "semantic",
                    "scope": "user",
                    "status": "confirmed",
                    "confidence": 0.82,
                    "importance": 0.75,
                    "stability": 0.82,
                    "should_vectorize": True,
                },
            )
            decision = self._promotion_gate.should_promote_semantic_fact(payload, fact)
            if decision.allow_long_term:
                semantic_facts.append(fact)
                reasons.append("promoted_semantic_fact")
            else:
                reasons.append(f"semantic_fact_skipped:{decision.reason}")
                durable_fact_requests.append(
                    DurableFactRequest(
                        fact_type="session_fact",
                        payload={
                            "user_id": payload.user_id,
                            "session_id": payload.session_id,
                            "turn_id": payload.turn_id,
                            "source": MemorySource.SYSTEM_EVENT.value,
                            "fact_type": "session_fact",
                            "memory_type": "short_term",
                            "scope": decision.scope.value,
                            "status": decision.status.value,
                            "should_vectorize": False,
                            "ttl_seconds": decision.ttl_seconds,
                            "importance": 0.2,
                            "stability": 0.2,
                            "confidence": 0.2,
                            "summary": (payload.answer_text or payload.query)[:240],
                            "reason": decision.reason,
                            "clarification_result": _mapping_dict(payload.extra.get("clarification_result")),
                            "missing_slots": _mapping_dict(payload.extra.get("missing_slots")),
                        },
                    )
                )
                session_update = session_update.__class__(
                    current_topic=session_update.current_topic,
                    recent_entities=session_update.recent_entities,
                    clarification_result=session_update.clarification_result,
                    last_retrieval_topic=session_update.last_retrieval_topic,
                    history_summary=session_update.history_summary,
                    open_questions=session_update.open_questions,
                    confirmed_facts=session_update.confirmed_facts,
                    next_steps=session_update.next_steps,
                    summary_version=session_update.summary_version,
                    summary_updated_at=session_update.summary_updated_at,
                    pending_clarification=session_update.pending_clarification
                    or {
                        "reason": decision.reason,
                        "query": payload.query,
                        "answer_text": payload.answer_text,
                        "topic": topic,
                    },
                    extra={
                        **dict(session_update.extra),
                        "semantic_fact_skip_reason": decision.reason,
                        "semantic_fact_scope": decision.scope.value,
                        "semantic_fact_status": decision.status.value,
                        "semantic_fact_ttl_seconds": decision.ttl_seconds,
                    },
                )

        for fact in semantic_facts:
            durable_fact_requests.append(
                DurableFactRequest(
                    fact_type="semantic_memory_fact",
                    payload={
                        "user_id": payload.user_id,
                        "fact_id": fact.fact_id,
                        "topic": fact.topic,
                        "fact_type": fact.fact_type,
                        "strength": fact.strength,
                        "metadata": dict(fact.metadata),
                    },
                )
            )

        if payload.extra.get("clarification_result"):
            durable_fact_requests.append(
                DurableFactRequest(
                    fact_type="clarification_result",
                        payload={
                            "user_id": payload.user_id,
                            "session_id": payload.session_id,
                            "turn_id": payload.turn_id,
                            "clarification_result": _mapping_dict(payload.extra.get("clarification_result")),
                        },
                    )
                )

        extracted_candidates = self._extractor.extract(payload)
        llm_candidates = self._llm_extractor.extract(payload)
        governed_candidates = self.govern_candidates(extracted_candidates + llm_candidates)

        return MemoryPromotionResult(
            session_update=session_update,
            preference_patch=preference_patch,
            session_preference_patch=session_preference_patch,
            profile_updates=tuple(profile_updates),
            semantic_facts=tuple(semantic_facts),
            reasons=tuple(reasons),
            durable_fact_requests=tuple(durable_fact_requests),
            outbox_events=tuple(outbox_events),
            extra={
                "resolved_topic": topic,
                "extracted_candidates": extracted_candidates,
                "llm_candidates": llm_candidates,
                "governed_candidates": governed_candidates,
            },
        )

    def build_write_plan(
        self,
        current: PersistentSessionContext,
        result: MemoryPromotionResult,
    ) -> PersistSessionPlan:
        merged_preferences = dict(current.user_preferences)
        merged_preferences.update(dict(result.preference_patch))
        merged_preferences.update(dict(result.session_preference_patch))
        for profile_update in result.profile_updates:
            merged_preferences[str(profile_update.get("preference_key") or "")] = profile_update.get("current_value")
        updated_context = self._updater.merge_context(
            current,
            result.session_update,
        )
        updated_context = PersistentSessionContext(
            current_topic=updated_context.current_topic,
            recent_entities=updated_context.recent_entities,
            clarification_result=updated_context.clarification_result,
            user_preferences=merged_preferences,
            last_retrieval_topic=updated_context.last_retrieval_topic,
            history_summary=updated_context.history_summary,
            open_questions=updated_context.open_questions,
            confirmed_facts=updated_context.confirmed_facts,
            next_steps=updated_context.next_steps,
            summary_version=updated_context.summary_version,
            summary_updated_at=updated_context.summary_updated_at,
            pending_clarification=updated_context.pending_clarification,
            extra=dict(current.extra),
        )
        return PersistSessionPlan(
            updated_context=updated_context,
            preference_patch=result.preference_patch,
            session_preference_patch=result.session_preference_patch,
            profile_updates=result.profile_updates,
            semantic_facts=result.semantic_facts,
            durable_fact_requests=result.durable_fact_requests,
            outbox_events=result.outbox_events,
            memory_updates={
                "current_topic": updated_context.current_topic,
                "recent_entities": list(updated_context.recent_entities),
                "user_preferences": dict(updated_context.user_preferences),
                "promotion_reasons": list(result.reasons),
                "history_summary": updated_context.history_summary,
                "open_questions": list(updated_context.open_questions),
                "confirmed_facts": list(updated_context.confirmed_facts),
                "next_steps": list(updated_context.next_steps),
                "summary_version": updated_context.summary_version,
                "summary_updated_at": updated_context.summary_updated_at,
            },
        )

    @staticmethod
    def build_write_plan_legacy(result: MemoryPromotionResult) -> DurableMemoryWritePlan:
        return DurableMemoryWritePlan(
            session_update=result.session_update,
            preference_patch=result.preference_patch,
            session_preference_patch=result.session_preference_patch,
            profile_updates=result.profile_updates,
            semantic_facts=result.semantic_facts,
            durable_fact_requests=result.durable_fact_requests,
            outbox_events=result.outbox_events,
        )

    def _should_promote_semantic_fact(
        self,
        payload: MemoryPromotionInput,
    ) -> bool:
        topic = (payload.resolved_topic or "").strip()
        if not topic:
            return False
        text = " ".join(part for part in [payload.query or "", payload.answer_text or ""] if part).strip()
        if not text:
            return False
        return True
