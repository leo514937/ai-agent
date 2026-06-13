from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from learning_agent_service.config import Settings
from learning_agent_service.domain import (
    ClarificationCard,
    MasteryUpdateCommand,
    MasteryUpdateResult,
    MemoryUpdateSummary,
    MemoryWriteResult,
    MemoryWriteTargetResult,
    PersistSessionCommand,
    PersistSessionResult,
)
from learning_agent_service.domain import (
    PersistentSessionContext as DomainPersistentSessionContext,
)
from learning_agent_service.domain.errors import WorkflowErrorCode
from learning_agent_service.domain.guards import validate_memory_write_boundary

from .canonical import CanonicalTopicResolver
from .models import (
    AsyncLogEvent,
    ExplicitUserSignals,
    MemoryCapabilityError,
    MemoryPromotionInput,
    PersistSessionPlan,
    PreferenceProfileWrite,
    SessionPersistenceContext,
    UserPreferenceProfile,
)
from .models import (
    PersistentSessionContext as MemoryPersistentSessionContext,
)
from .preference_registry import DEFAULT_PREFERENCE_REGISTRY
from .promotion import MemoryPromotionPolicy
from .protocols import (
    AsyncLogStore,
    NoOpSemanticMemoryStore,
    PreferenceStore,
    SemanticMemoryStore,
    SessionStore,
    SupportsLoadAny,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class MemoryService:
    session_store: SessionStore
    async_log_store: AsyncLogStore
    settings: Settings
    mastery_store: Any = None
    preference_store: PreferenceStore | None = None
    profile_projection_store: Any = None
    semantic_memory_store: SemanticMemoryStore = field(default_factory=NoOpSemanticMemoryStore)
    promotion_policy: MemoryPromotionPolicy = field(default_factory=MemoryPromotionPolicy)
    topic_resolver: CanonicalTopicResolver = field(default_factory=CanonicalTopicResolver)

    def __post_init__(self) -> None:
        if getattr(self, "semantic_memory_store", None) is None:
            self.semantic_memory_store = NoOpSemanticMemoryStore()

    def persist_session(self, command: PersistSessionCommand) -> PersistSessionResult:
        persistent = command.persistent
        resolved_topic = self._resolve_topic(
            command.resolved_topic,
            persistent.current_topic,
            command.raw_query,
        )
        current_preferences = UserPreferenceProfile(
            user_id=command.user_id,
            extra=dict(persistent.user_preferences),
        )

        promotion_input = MemoryPromotionInput(
            session_id=command.session_id,
            turn_id=command.turn_id,
            user_id=command.user_id,
            query=command.raw_query,
            answer_text=command.answer_text,
            resolved_topic=resolved_topic,
            intent=getattr(command.intent, "value", command.intent) if command.intent else None,
            output_style=getattr(command.requested_output_style, "value", command.requested_output_style) if command.requested_output_style else None,
            tool_name=command.tool_name,
            explicit_signals=self._collect_explicit_signals(command, resolved_topic),
            current_session=self._to_memory_context(persistent),
            current_preferences=current_preferences,
            current_time=command.request_ts,
            extra={
                "clarification_result": dict(persistent.clarification_result),
                "open_questions": list(persistent.open_questions),
                "confirmed_facts": list(persistent.confirmed_facts),
                "next_steps": list(persistent.next_steps),
                "summary_version": persistent.summary_version,
                "summary_updated_at": persistent.summary_updated_at,
            },
        )
        promotion_result = self.promotion_policy.evaluate(promotion_input)
        write_plan = self.promotion_policy.build_write_plan(self._to_memory_context(persistent), promotion_result)
        updated_context = self._to_domain_context(write_plan.updated_context, persistent)
        if command.session_state_patch:
            updated_context = self._merge_session_state_patch(updated_context, command.session_state_patch)
        if current_preferences.extra:
            updated_context = updated_context.model_copy(
                update={
                    "user_preferences": self._merge_user_preferences(
                        updated_context.user_preferences,
                        current_preferences.extra,
                    )
                }
            )
        if not updated_context.current_shop and updated_context.selected_shop_name:
            updated_context = updated_context.model_copy(update={"current_shop": updated_context.selected_shop_name})
        if updated_context.current_shop and not updated_context.selected_shop_name:
            updated_context = updated_context.model_copy(update={"selected_shop_name": updated_context.current_shop})
        if not updated_context.current_topic and updated_context.current_shop:
            updated_context = updated_context.model_copy(update={"current_topic": updated_context.current_shop})
        preserved_updates: dict[str, Any] = {}
        if persistent.pending_clarification is not None and updated_context.pending_clarification is None:
            # 短期澄清态必须跟随 session 一起落盘，否则下一轮无法消费“北京”这类短答。
            preserved_updates["pending_clarification"] = persistent.pending_clarification
        if persistent.clarification_result:
            merged_clarification = dict(updated_context.clarification_result)
            for key, value in dict(persistent.clarification_result).items():
                if key not in merged_clarification or merged_clarification.get(key) in (None, "", [], {}):
                    merged_clarification[key] = value
            if bool(dict(persistent.clarification_result).get("consumed")):
                merged_clarification["consumed"] = True
            preserved_updates["clarification_result"] = merged_clarification
        if persistent.current_city and not updated_context.current_city:
            preserved_updates["current_city"] = persistent.current_city
        if persistent.current_location and not updated_context.current_location:
            preserved_updates["current_location"] = dict(persistent.current_location)
        if preserved_updates:
            updated_context = updated_context.model_copy(update=preserved_updates)
        fallback_topic = self._resolve_topic(
            command.resolved_topic,
            persistent.current_topic,
            command.raw_query,
        )
        raw_query_topic = self.topic_resolver.canonicalize(command.raw_query)
        if (
            not command.resolved_topic
            and not persistent.current_topic
            and fallback_topic == raw_query_topic
        ):
            fallback_topic = (
                self.topic_resolver.canonicalize(persistent.history_summary)
                if persistent.history_summary
                else "general"
        )
        fallback_history_summary = persistent.history_summary or command.raw_query
        if not updated_context.current_topic and fallback_topic:
            updated_context = updated_context.model_copy(update={"current_topic": fallback_topic})
        if not updated_context.history_summary and fallback_history_summary:
            updated_context = updated_context.model_copy(update={"history_summary": fallback_history_summary})

        runtime_context = self._session_runtime_context(command)
        _LOGGER.info(
            "memory_persist_trace start trace_id=%s session_id=%s turn_id=%s allow_memory_promotion=%s allow_semantic_memory_write=%s pending_clarification=%s clarification_consumed=%s current_city=%s current_shop=%s",
            runtime_context.trace_id,
            runtime_context.session_id,
            runtime_context.turn_id,
            bool(command.allow_memory_promotion),
            bool(command.allow_semantic_memory_write),
            bool(getattr(persistent, "pending_clarification", None) is not None),
            bool(dict(getattr(persistent, "clarification_result", {}) or {}).get("consumed")),
            getattr(updated_context, "current_city", None),
            getattr(updated_context, "current_shop", None),
        )
        self._validate_memory_boundary(
            code=WorkflowErrorCode.SESSION_PERSIST_FAILED,
            operation="persist_session",
            user_id=command.user_id,
            runtime=runtime_context,
        )
        persist_started_at = time.perf_counter()
        try:
            self.session_store.save(updated_context, runtime_context)
        except Exception as exc:  # pragma: no cover - delegated to workflow integration
            raise MemoryCapabilityError(
                code=WorkflowErrorCode.SESSION_PERSIST_FAILED,
                stage="persist_session.session_store",
                message=str(exc),
                retryable=True,
                degraded_to="session_not_persisted",
            ) from exc
        _LOGGER.info(
            "memory_persist_trace session_store_saved trace_id=%s session_id=%s turn_id=%s elapsed_ms=%.1f",
            runtime_context.trace_id,
            runtime_context.session_id,
            runtime_context.turn_id,
            (time.perf_counter() - persist_started_at) * 1000.0,
        )

        if not command.allow_memory_promotion:
            memory_write = self._build_memory_write_result(
                operation="persist_session",
                runtime=runtime_context,
                planned_targets=("session_context",),
                target_summaries=[
                    {
                        "target": "session_context",
                        "status": "success",
                        "retryable": False,
                        "reason": "session_context_persisted",
                        "details": {
                            "backend": type(self.session_store).__name__,
                            "session_id": runtime_context.session_id,
                            "user_id": runtime_context.user_id,
                        },
                    }
                ],
                decision_reasons=["memory_promotion_disabled", "skip_long_term_memory_write"],
                extra={
                    "promotion_reasons": [],
                    "write_plan_targets": ["session_context"],
                    "memory_trace_id": runtime_context.trace_id,
                    "profile_projection": None,
                    "policy_snapshot": self._policy_snapshot(),
                    "routing_skip": True,
                    "allow_semantic_memory_write": bool(command.allow_semantic_memory_write),
                },
            )
            memory_updates = MemoryUpdateSummary(
                current_topic=updated_context.current_topic,
                updated_preferences={},
                weak_topics=[],
                semantic_memory={},
                open_questions=list(updated_context.open_questions),
                confirmed_facts=list(updated_context.confirmed_facts),
                next_steps=list(updated_context.next_steps),
                summary_version=updated_context.summary_version,
                summary_updated_at=updated_context.summary_updated_at,
                memory_trace_id=runtime_context.trace_id,
                write_status="skipped",
                write_targets=list(memory_write.write_targets),
                decision_reasons=list(memory_write.decision_reasons),
                degraded_parts=[],
                retryable_failures=[],
                permanent_failures=[],
                memory_write=memory_write,
                extra={
                    "recent_entities": list(updated_context.recent_entities),
                    "history_summary": updated_context.history_summary,
                    "promotion_reasons": [],
                    "diagnostics": {
                        "routing_skip": True,
                        "allow_semantic_memory_write": bool(command.allow_semantic_memory_write),
                    },
                    "policy_snapshot": self._policy_snapshot(),
                },
            )
            return PersistSessionResult(
                updated_context=updated_context,
                memory_updates=memory_updates,
                memory_write=memory_write,
            )

        diagnostics: dict[str, Any] = {}
        session_backend = type(self.session_store).__name__
        session_status = "degraded" if self._is_fallback_backend_name(session_backend) else "success"
        target_summaries: list[dict[str, Any]] = [
            {
                "target": "session_context",
                "status": session_status,
                "retryable": False,
                "reason": (
                    "session_context_persisted"
                    if session_status == "success"
                    else "session_context_persisted_via_fallback_backend"
                ),
                "details": {
                    "backend": session_backend,
                    "session_id": runtime_context.session_id,
                    "user_id": runtime_context.user_id,
                },
            }
        ]
        preference_diagnostics = self._persist_preference_patch(
            command.user_id,
            updated_context,
            write_plan.preference_patch,
        )
        _LOGGER.info(
            "memory_persist_trace preference_done trace_id=%s session_id=%s turn_id=%s status=%s elapsed_ms=%.1f",
            runtime_context.trace_id,
            runtime_context.session_id,
            runtime_context.turn_id,
            preference_diagnostics.get("status") if preference_diagnostics else "skipped",
            (time.perf_counter() - persist_started_at) * 1000.0,
        )
        if preference_diagnostics:
            diagnostics["preference_store"] = preference_diagnostics
            target_summaries.append(preference_diagnostics)

        profile_diagnostics = self._sync_profile_projection(
            user_id=command.user_id,
            updates=write_plan.profile_updates,
            runtime=runtime_context,
        )
        _LOGGER.info(
            "memory_persist_trace profile_done trace_id=%s session_id=%s turn_id=%s status=%s elapsed_ms=%.1f",
            runtime_context.trace_id,
            runtime_context.session_id,
            runtime_context.turn_id,
            profile_diagnostics.get("status") if profile_diagnostics else "skipped",
            (time.perf_counter() - persist_started_at) * 1000.0,
        )
        if profile_diagnostics:
            diagnostics["profile_projection"] = profile_diagnostics
            target_summaries.append(profile_diagnostics)

        semantic_summary = self._sync_semantic_facts(
            user_id=command.user_id,
            facts=write_plan.semantic_facts,
            runtime=runtime_context,
        )
        _LOGGER.info(
            "memory_persist_trace semantic_done trace_id=%s session_id=%s turn_id=%s status=%s elapsed_ms=%.1f facts=%s",
            runtime_context.trace_id,
            runtime_context.session_id,
            runtime_context.turn_id,
            semantic_summary.get("status"),
            (time.perf_counter() - persist_started_at) * 1000.0,
            len(write_plan.semantic_facts),
        )
        target_summaries.append(semantic_summary)
        if semantic_summary.get("failures"):
            diagnostics["semantic_memory"] = {
                "status": semantic_summary.get("status"),
                "failures": list(semantic_summary.get("failures", [])),
            }

        outbox_diagnostics = self._emit_persist_outbox(runtime_context, write_plan)
        _LOGGER.info(
            "memory_persist_trace outbox_done trace_id=%s session_id=%s turn_id=%s status=%s elapsed_ms=%.1f events=%s",
            runtime_context.trace_id,
            runtime_context.session_id,
            runtime_context.turn_id,
            outbox_diagnostics.get("status") if outbox_diagnostics else "skipped",
            (time.perf_counter() - persist_started_at) * 1000.0,
            len(write_plan.durable_fact_requests) + len(write_plan.outbox_events) + 1,
        )
        if outbox_diagnostics:
            diagnostics["outbox"] = outbox_diagnostics
            target_summaries.append(outbox_diagnostics)

        memory_write = self._build_memory_write_result(
            operation="persist_session",
            runtime=runtime_context,
            planned_targets=("session_context", "preference", "profile_projection", "semantic_facts", "outbox"),
            target_summaries=target_summaries,
            decision_reasons=self._collect_write_reasons(promotion_result.reasons, target_summaries),
            extra={
                "promotion_reasons": list(promotion_result.reasons),
                "write_plan_targets": ["session_context", "preference", "profile_projection", "semantic_facts", "outbox"],
                "memory_trace_id": runtime_context.trace_id,
                "profile_projection": profile_diagnostics,
                "policy_snapshot": self._policy_snapshot(),
            },
        )

        memory_updates = MemoryUpdateSummary(
            current_topic=updated_context.current_topic,
            updated_preferences=dict(write_plan.preference_patch),
            weak_topics=[],
            semantic_memory=semantic_summary,
            open_questions=list(updated_context.open_questions),
            confirmed_facts=list(updated_context.confirmed_facts),
            next_steps=list(updated_context.next_steps),
            summary_version=updated_context.summary_version,
            summary_updated_at=updated_context.summary_updated_at,
            memory_trace_id=runtime_context.trace_id,
            write_status=memory_write.status,
            write_targets=list(memory_write.write_targets),
            decision_reasons=list(memory_write.decision_reasons),
            degraded_parts=list(memory_write.degraded_parts),
            retryable_failures=list(memory_write.retryable_failures),
            permanent_failures=list(memory_write.permanent_failures),
            memory_write=memory_write,
            extra={
                "recent_entities": list(updated_context.recent_entities),
                "history_summary": updated_context.history_summary,
                "promotion_reasons": list(promotion_result.reasons),
                "diagnostics": diagnostics,
                "policy_snapshot": self._policy_snapshot(),
            },
        )
        return PersistSessionResult(
            updated_context=updated_context,
            memory_updates=memory_updates,
            memory_write=memory_write,
        )

    def update_mastery(self, command: MasteryUpdateCommand) -> MasteryUpdateResult:
        persistent = command.persistent
        resolved_topic = self._resolve_topic(
            command.resolved_topic,
            persistent.current_topic,
            command.raw_query,
        )
        runtime = self._session_runtime_context(command)
        self._validate_memory_boundary(
            code=WorkflowErrorCode.MASTERY_UPDATE_FAILED,
            operation="update_mastery",
            user_id=command.user_id,
            runtime=runtime,
        )

        topic = resolved_topic or persistent.current_topic or self.topic_resolver.canonicalize(command.raw_query) or "general"
        topic_payload = {
            "topic": topic,
            "current_topic": persistent.current_topic,
            "resolved_topic": resolved_topic,
            "raw_query": command.raw_query,
            "answer_text": command.answer_text,
            "memory_updates": command.memory_updates.model_dump(mode="json"),
        }

        target_summaries: list[dict[str, Any]] = []
        if self.mastery_store is None:
            target_summaries.append(
                {
                    "target": "topic_mastery",
                    "status": "permanent_failure",
                    "retryable": False,
                    "reason": "topic_mastery_store_unavailable",
                    "details": {"backend": "none", "topic": topic},
                }
            )
        else:
            backend_name = type(self.mastery_store).__name__
            try:
                if hasattr(self.mastery_store, "upsert"):
                    self.mastery_store.upsert(command.user_id, topic, topic_payload)
                elif hasattr(self.mastery_store, "save"):
                    self.mastery_store.save(command.user_id, topic, topic_payload)
                else:
                    raise AttributeError("mastery store does not support upsert/save")
                target_summaries.append(
                    {
                        "target": "topic_mastery",
                        "status": "degraded" if self._is_fallback_backend_name(backend_name) else "success",
                        "retryable": False,
                        "reason": (
                            "topic_mastery_persisted_via_fallback_backend"
                            if self._is_fallback_backend_name(backend_name)
                            else "topic_mastery_updated"
                        ),
                        "details": {
                            "backend": backend_name,
                            "user_id": command.user_id,
                            "topic": topic,
                        },
                    }
                )
            except Exception as exc:
                raise MemoryCapabilityError(
                    code=WorkflowErrorCode.MASTERY_UPDATE_FAILED,
                    stage="update_mastery.topic_mastery_store",
                    message=str(exc),
                    retryable=True,
                    degraded_to="topic_mastery_skipped",
                ) from exc

        semantic_backend = type(self.semantic_memory_store).__name__
        try:
            if hasattr(self.semantic_memory_store, "mark_indexed_state"):
                self.semantic_memory_store.mark_indexed_state(command.user_id, topic, True)
            target_summaries.append(
                {
                    "target": "semantic_index",
                    "status": "degraded" if self._is_fallback_backend_name(semantic_backend) else "success",
                    "retryable": False,
                    "reason": (
                        "semantic_index_marked_via_noop"
                        if self._is_fallback_backend_name(semantic_backend)
                        else "semantic_index_marked"
                    ),
                    "details": {
                        "backend": semantic_backend,
                        "user_id": command.user_id,
                        "topic": topic,
                    },
                }
            )
        except Exception as exc:
            raise MemoryCapabilityError(
                code=WorkflowErrorCode.MASTERY_UPDATE_FAILED,
                stage="update_mastery.semantic_memory_store",
                message=str(exc),
                retryable=True,
                degraded_to="semantic_index_skipped",
            ) from exc

        memory_write = self._build_memory_write_result(
            operation="update_mastery",
            runtime=runtime,
            planned_targets=("topic_mastery", "semantic_index"),
            target_summaries=target_summaries,
            decision_reasons=self._collect_write_reasons(
                command.memory_updates.decision_reasons,
                ("topic_mastery", "semantic_index"),
            ),
            extra={
                "topic": topic,
                "resolved_topic": resolved_topic,
                "memory_updates": command.memory_updates.model_dump(mode="json"),
            },
        )

        memory_updates = command.memory_updates.model_copy(
            update={
                "current_topic": command.memory_updates.current_topic or topic,
                "memory_trace_id": runtime.trace_id,
                "write_status": memory_write.status,
                "write_targets": list(memory_write.write_targets),
                "decision_reasons": list(memory_write.decision_reasons),
                "degraded_parts": list(memory_write.degraded_parts),
                "retryable_failures": list(memory_write.retryable_failures),
                "permanent_failures": list(memory_write.permanent_failures),
                "memory_write": memory_write,
                "extra": {
                    **dict(command.memory_updates.extra),
                    "topic": topic,
                    "resolved_topic": resolved_topic,
                },
            }
        )
        updated_context = persistent.model_copy(update={"current_topic": topic})
        return MasteryUpdateResult(
            updated_context=updated_context,
            memory_updates=memory_updates,
            memory_write=memory_write,
        )

    def load_any(self, session_id: str) -> DomainPersistentSessionContext:
        if isinstance(self.session_store, SupportsLoadAny):
            return self.session_store.load_any(session_id)
        return self.session_store.load(session_id, "anonymous")

    def _session_runtime_context(self, command: PersistSessionCommand | MasteryUpdateCommand) -> SessionPersistenceContext:
        return SessionPersistenceContext(
            session_id=command.session_id,
            turn_id=command.turn_id,
            trace_id="%s:%s" % (command.session_id, command.turn_id),
            user_id=command.user_id,
            request_ts=command.request_ts,
        )

    def _resolve_topic(
        self,
        resolved_topic: str | None,
        current_topic: str | None,
        raw_query: str,
    ) -> str:
        resolved = self._canonicalize_topic_candidate(resolved_topic)
        if resolved:
            return resolved

        if current_topic:
            return self.topic_resolver.canonicalize(current_topic)

        return self._canonicalize_topic_candidate(raw_query)

    def _canonicalize_topic_candidate(self, candidate: str | None) -> str:
        text = (candidate or "").strip()
        if not text:
            return ""

        canonical = self.topic_resolver.canonicalize(text)
        normalized = CanonicalTopicResolver._normalize(text)
        if not normalized:
            return ""

        # When canonicalization only mirrors a long instructional sentence,
        # keep the previous topic instead of polluting session memory with a query slug.
        mirrored = normalized.replace(" ", ".")
        query_markers = {
            "compare",
            "difference",
            "differences",
            "explain",
            "how",
            "what",
            "why",
            "vs",
            "tell",
            "show",
            "describe",
            "介绍",
            "解释",
            "对比",
            "区别",
            "怎么",
            "如何",
            "为什么",
            "总结",
        }
        tokens = normalized.split()
        if canonical == mirrored and (len(tokens) > 4 or any(token in query_markers for token in tokens)):
            return ""
        return canonical

    def _collect_explicit_signals(
        self,
        command: PersistSessionCommand,
        resolved_topic: str,
    ) -> ExplicitUserSignals:
        query = command.raw_query or ""
        normalized_query = query.lower()
        return ExplicitUserSignals(
            preferred_output_style=getattr(command.requested_output_style, "value", command.requested_output_style) if command.requested_output_style else None,
            confirmed_output_style=self._is_confirmed_preference_query(query, normalized_query),
            focus_topics=tuple(entity for entity in (command.persistent.current_shop, *command.persistent.recent_entities) if entity),
        )

    def _persist_preference_patch(
        self,
        user_id: str,
        updated_context: DomainPersistentSessionContext,
        preference_patch: Mapping[str, Any],
    ) -> dict[str, Any]:
        if self.preference_store is None or not preference_patch:
            if not preference_patch:
                return {
                    "target": "preference",
                    "status": "skipped",
                    "retryable": False,
                    "reason": "no_preference_patch",
                    "fields": [],
                    "details": {},
                }
            return {
                "target": "preference",
                "status": "permanent_failure",
                "retryable": False,
                "reason": "preference_store_unavailable",
                "fields": sorted(preference_patch.keys()),
                "details": {"backend": "none"},
            }
        try:
            profile = PreferenceProfileWrite(
                user_id=user_id,
                answer_style=updated_context.user_preferences.get("preferred_output_style")
                or updated_context.user_preferences.get("answer_style"),
                explanation_depth=updated_context.user_preferences.get("explanation_depth"),
                extra={
                    "answer_style_counter": dict(updated_context.user_preferences.get("answer_style_counter", {})),
                },
            )
            self.preference_store.upsert(profile)
            return {
                "target": "preference",
                "status": "success",
                "retryable": False,
                "reason": "preference_profile_upserted",
                "fields": sorted(preference_patch.keys()),
                "details": {
                    "backend": type(self.preference_store).__name__,
                    "user_id": user_id,
                },
            }
        except Exception as exc:
            return {
                "target": "preference",
                "status": "retryable_failure",
                "retryable": True,
                "reason": "preference_profile_upsert_failed",
                "fields": sorted(preference_patch.keys()),
                "error": str(exc),
                "details": {
                    "backend": type(self.preference_store).__name__,
                    "user_id": user_id,
                },
            }

    def _sync_semantic_facts(
        self,
        *,
        user_id: str,
        facts: Sequence[Any],
        runtime: SessionPersistenceContext,
    ) -> dict[str, Any]:
        upserted: list[str] = []
        failures: list[str] = []
        if isinstance(self.semantic_memory_store, NoOpSemanticMemoryStore):
            fact_ids = [str(getattr(fact, "fact_id", "")) for fact in facts]
            return {
                "target": "semantic_facts",
                "status": "degraded",
                "retryable": False,
                "reason": "semantic_memory_store_is_noop",
                "upserted_fact_ids": [],
                "rejected_fact_ids": [fact_id for fact_id in fact_ids if fact_id],
                "failures": ["noop_semantic_memory_store"],
                "details": {
                    "backend": type(self.semantic_memory_store).__name__,
                    "user_id": user_id,
                    "session_id": runtime.session_id,
                },
            }
        for fact in facts:
            try:
                self.semantic_memory_store.upsert(user_id, fact)
                upserted.append(fact.fact_id)
            except Exception as exc:
                failures.append("%s: %s" % (fact.fact_id, exc))
                self._append_async_log(
                    AsyncLogEvent(
                        aggregate_type="memory",
                        aggregate_id="%s:%s" % (runtime.session_id, runtime.turn_id),
                        event_type="memory.semantic_fact_failed",
                        dedupe_key="%s:%s:%s" % (runtime.session_id, runtime.turn_id, fact.fact_id),
                        payload={
                            "user_id": user_id,
                            "fact_id": fact.fact_id,
                            "topic": fact.topic,
                            "reason": str(exc),
                        },
                        trace_id=runtime.trace_id,
                    )
                )
        return {
            "target": "semantic_facts",
            "adapter": type(self.semantic_memory_store).__name__,
            "status": "success" if not failures else "retryable_failure",
            "retryable": bool(failures),
            "reason": "semantic_facts_upserted" if not failures else "semantic_facts_partial_failure",
            "upserted_fact_ids": upserted,
            "failures": failures,
            "details": {
                "backend": type(self.semantic_memory_store).__name__,
                "user_id": user_id,
                "session_id": runtime.session_id,
            },
        }

    def _sync_profile_projection(
        self,
        *,
        user_id: str,
        updates: Sequence[Mapping[str, Any]],
        runtime: SessionPersistenceContext,
    ) -> dict[str, Any]:
        if not updates:
            return {
                "target": "profile_projection",
                "status": "skipped",
                "retryable": False,
                "reason": "no_profile_updates",
                "updates": [],
                "details": {"backend": type(self.profile_projection_store).__name__ if self.profile_projection_store is not None else "none"},
            }
        if self.profile_projection_store is None:
            return {
                "target": "profile_projection",
                "status": "permanent_failure",
                "retryable": False,
                "reason": "profile_projection_store_unavailable",
                "updates": [str(item.get("preference_key")) for item in updates if item.get("preference_key")],
                "details": {"backend": "none", "user_id": user_id, "session_id": runtime.session_id},
            }

        failures: list[str] = []
        applied: list[str] = []
        for update in updates:
            try:
                self.profile_projection_store.upsert(
                    {
                        **dict(update),
                        "user_id": user_id,
                        "source_session_id": update.get("source_session_id") or runtime.session_id,
                    }
                )
                applied.append(str(update.get("preference_key") or ""))
            except Exception as exc:
                failures.append(f"{update.get('preference_key')}: {exc}")
        status = "success" if not failures else "retryable_failure"
        return {
            "target": "profile_projection",
            "status": status,
            "retryable": bool(failures),
            "reason": "profile_projection_upserted" if not failures else "profile_projection_partial_failure",
            "updates": applied,
            "failures": failures,
            "details": {
                "backend": type(self.profile_projection_store).__name__,
                "user_id": user_id,
                "session_id": runtime.session_id,
            },
        }

    def _emit_persist_outbox(
        self,
        runtime: SessionPersistenceContext,
        write_plan: PersistSessionPlan,
    ) -> dict[str, Any]:
        failures: list[str] = []
        events_written = 0
        backend_name = type(self.async_log_store).__name__
        for request in write_plan.durable_fact_requests:
            try:
                self._append_async_log(
                    AsyncLogEvent(
                        aggregate_type="memory",
                        aggregate_id="%s:%s" % (runtime.session_id, runtime.turn_id),
                        event_type="memory.%s" % request.fact_type,
                        dedupe_key="%s:%s:%s" % (runtime.session_id, runtime.turn_id, request.fact_type),
                        payload={
                            "session_id": runtime.session_id,
                            "turn_id": runtime.turn_id,
                            "trace_id": runtime.trace_id,
                            **dict(request.payload),
                        },
                        trace_id=runtime.trace_id,
                    )
                )
                events_written += 1
            except Exception as exc:
                failures.append(str(exc))

        for index, event in enumerate(write_plan.outbox_events):
            event_type = str(event.get("event_type") or "memory.outbox")
            try:
                self._append_async_log(
                    AsyncLogEvent(
                        aggregate_type="memory",
                        aggregate_id="%s:%s" % (runtime.session_id, runtime.turn_id),
                        event_type=event_type,
                        dedupe_key="%s:%s:%s:%s" % (runtime.session_id, runtime.turn_id, event_type, index),
                        payload={
                            "session_id": runtime.session_id,
                            "turn_id": runtime.turn_id,
                            "trace_id": runtime.trace_id,
                            **dict(event),
                        },
                        trace_id=runtime.trace_id,
                    )
                )
                events_written += 1
            except Exception as exc:
                failures.append(str(exc))

        try:
            self._append_async_log(
                AsyncLogEvent(
                    aggregate_type="memory",
                    aggregate_id="%s:%s" % (runtime.session_id, runtime.turn_id),
                    event_type="memory.persist_session",
                    dedupe_key="%s:%s:persist_session" % (runtime.session_id, runtime.turn_id),
                    payload={
                        "session_id": runtime.session_id,
                        "turn_id": runtime.turn_id,
                        "trace_id": runtime.trace_id,
                        "current_topic": write_plan.updated_context.current_topic,
                    },
                    trace_id=runtime.trace_id,
                )
            )
            events_written += 1
        except Exception as exc:
            failures.append(str(exc))

        fallback_backend = self._is_fallback_backend_name(backend_name)
        if fallback_backend and not failures:
            return {
                "target": "outbox",
                "status": "degraded",
                "retryable": False,
                "reason": "outbox_persisted_via_fallback_backend",
                "events_written": events_written,
                "failures": [],
                "details": {
                    "session_id": runtime.session_id,
                    "turn_id": runtime.turn_id,
                    "trace_id": runtime.trace_id,
                    "planned_events": len(write_plan.durable_fact_requests) + len(write_plan.outbox_events) + 1,
                    "backend": backend_name,
                },
            }
        if not failures:
            return {
                "target": "outbox",
                "status": "success",
                "retryable": False,
                "reason": "outbox_events_written",
                "events_written": events_written,
                "failures": [],
                "details": {
                    "session_id": runtime.session_id,
                    "turn_id": runtime.turn_id,
                    "trace_id": runtime.trace_id,
                    "planned_events": len(write_plan.durable_fact_requests) + len(write_plan.outbox_events) + 1,
                },
            }
        return {
            "target": "outbox",
            "status": "pending_compensation",
            "retryable": True,
            "reason": "outbox_events_pending_compensation",
            "events_written": events_written,
            "failures": failures,
            "details": {
                "session_id": runtime.session_id,
                "turn_id": runtime.turn_id,
                "trace_id": runtime.trace_id,
                "planned_events": len(write_plan.durable_fact_requests) + len(write_plan.outbox_events) + 1,
                "backend": backend_name,
            },
        }


    def _validate_memory_boundary(
        self,
        *,
        code: WorkflowErrorCode,
        operation: str,
        user_id: str,
        runtime: SessionPersistenceContext,
    ) -> None:
        decision = validate_memory_write_boundary(
            user_id=user_id,
            runtime_user_id=runtime.user_id,
            session_id=runtime.session_id,
            turn_id=runtime.turn_id,
        )
        if not decision.allowed:
            raise MemoryCapabilityError(
                code=code,
                stage=f"{operation}.boundary_validation",
                message=decision.reason.replace("_", " "),
                retryable=False,
                degraded_to=decision.reason,
            )

    @staticmethod
    def _is_fallback_backend_name(backend_name: str) -> bool:
        return backend_name.startswith("InMemory") or backend_name.startswith("NoOp")

    @staticmethod
    def _collect_write_reasons(*reason_sources: Iterable[Any]) -> list[str]:
        reasons: list[str] = []
        for source in reason_sources:
            for reason in source:
                if reason is None:
                    continue
                if isinstance(reason, Mapping):
                    candidate = reason.get("reason") or reason.get("status") or reason.get("target")
                else:
                    candidate = getattr(reason, "reason", None) if hasattr(reason, "reason") else None
                    if candidate is None:
                        candidate = reason
                text = str(candidate).strip()
                if text and text not in reasons:
                    reasons.append(text)
        return reasons

    def _make_target_result(self, summary: Mapping[str, Any]) -> MemoryWriteTargetResult:
        target = str(summary.get("target") or summary.get("adapter") or summary.get("name") or "unknown")
        status = str(summary.get("status") or "success")
        if status not in {"success", "degraded", "retryable_failure", "permanent_failure", "skipped"}:
            status = "success"
        details = dict(summary.get("details") or {})
        for key, value in summary.items():
            if key in {"target", "status", "retryable", "reason", "error", "details"}:
                continue
            details.setdefault(key, value)
        return MemoryWriteTargetResult(
            target=target,
            status=status,
            reason=str(summary.get("reason")) if summary.get("reason") is not None else None,
            retryable=bool(summary.get("retryable", False)),
            error=str(summary.get("error")) if summary.get("error") is not None else None,
            details=details,
        )

    def _build_memory_write_result(
        self,
        *,
        operation: str,
        runtime: SessionPersistenceContext,
        planned_targets: Sequence[str],
        target_summaries: Sequence[Mapping[str, Any]],
        decision_reasons: Sequence[Any],
        extra: Mapping[str, Any] | None = None,
    ) -> MemoryWriteResult:
        target_results = [self._make_target_result(summary) for summary in target_summaries]
        write_targets = list(dict.fromkeys(str(target) for target in planned_targets if str(target)))
        relevant_results = [result for result in target_results if result.status != "skipped"]
        degraded_parts = [result.target for result in relevant_results if result.status == "degraded"]
        retryable_failures = [result.target for result in relevant_results if result.status == "retryable_failure"]
        permanent_failures = [result.target for result in relevant_results if result.status == "permanent_failure"]
        if relevant_results and all(result.status == "permanent_failure" for result in relevant_results):
            status = "permanent_failure"
        elif permanent_failures:
            status = "degraded"
        elif retryable_failures:
            status = "pending_compensation"
        elif degraded_parts:
            status = "degraded"
        else:
            status = "success"
        return MemoryWriteResult(
            trace_id=runtime.trace_id,
            idempotency_key=runtime.trace_id,
            session_id=runtime.session_id,
            turn_id=runtime.turn_id,
            user_id=runtime.user_id,
            operation=operation,
            status=status,
            write_targets=write_targets,
            target_results=target_results,
            decision_reasons=self._collect_write_reasons(decision_reasons, (result.reason for result in target_results)),
            degraded_parts=list(dict.fromkeys(degraded_parts)),
            retryable_failures=list(dict.fromkeys(retryable_failures)),
            permanent_failures=list(dict.fromkeys(permanent_failures)),
            compensation_required=bool(retryable_failures),
            extra=dict(extra or {}),
        )

    def _policy_snapshot(self) -> dict[str, Any]:
        promotion = self.promotion_policy.config
        return {
            "promotion": {
                "preference_promote_count": promotion.preference_promote_count,
            },
        }

    def _append_async_log(self, event: AsyncLogEvent) -> None:
        self.async_log_store.append(event.as_mapping())

    def _preference_profile(self, user_id: str, user_preferences: Mapping[str, Any]) -> UserPreferenceProfile:
        stored_preferences: dict[str, Any] = {}
        if self.profile_projection_store is not None and hasattr(self.profile_projection_store, "list_active"):
            try:
                rows = self._call_with_timeout(
                    lambda: list(self.profile_projection_store.list_active(user_id)),
                    timeout_seconds=0.5,
                )
                for row in rows or []:
                    key = getattr(row, "preference_key", None)
                    value = getattr(row, "current_value", None)
                    if key and value is not None:
                        stored_preferences[str(key)] = value
            except Exception:
                pass
        if self.preference_store is not None:
            try:
                model = self._call_with_timeout(lambda: self.preference_store.get(user_id), timeout_seconds=0.5)
            except Exception:
                # 偏好画像失败不应阻塞 session 落盘，直接退化为当前会话偏好。
                model = None
            if model is not None:
                stored_preferences.update(
                    {
                        "preferred_output_style": getattr(model, "answer_style", None),
                        "answer_style": getattr(model, "answer_style", None),
                        **dict(getattr(model, "extra", {}) or {}),
                    }
                )
        stored_preferences.update(dict(user_preferences))
        stored_preferences.update(DEFAULT_PREFERENCE_REGISTRY.materialize_context(stored_preferences))
        counter = stored_preferences.get("answer_style_counter", {})
        return UserPreferenceProfile(
            user_id=user_id,
            preferred_output_style=stored_preferences.get("preferred_output_style")
            or stored_preferences.get("answer_style"),
            answer_style_counter=counter if isinstance(counter, Mapping) else {},
            extra={
                key: value
                for key, value in stored_preferences.items()
                if key
                not in {
                    "answer_style",
                    "answer_style_counter",
                }
            },
        )

    @staticmethod
    def _call_with_timeout(handler, *, timeout_seconds: float):
        result_queue: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)

        def _run() -> None:
            try:
                result_queue.put(("ok", handler()))
            except Exception as exc:  # pragma: no cover - best-effort fallback
                result_queue.put(("error", exc))

        worker = threading.Thread(target=_run, name="preference-profile-lookup", daemon=True)
        worker.start()
        try:
            status, value = result_queue.get(timeout=timeout_seconds)
        except queue.Empty:
            return None
        if status != "ok":
            return None
        return value

    @staticmethod
    def _merge_user_preferences(
        current: Mapping[str, Any],
        projected: Mapping[str, Any],
    ) -> dict[str, Any]:
        merged = dict(projected)
        merged.update(dict(current))
        return merged

    def _to_memory_context(self, context: DomainPersistentSessionContext) -> MemoryPersistentSessionContext:
        pending = context.pending_clarification.model_dump(mode="json") if context.pending_clarification else None
        return MemoryPersistentSessionContext(
            current_topic=context.current_topic,
            current_shop=context.current_shop,
            recent_entities=tuple(context.recent_entities),
            clarification_result=dict(context.clarification_result),
            user_preferences=dict(context.user_preferences),
            last_retrieval_topic=context.last_retrieval_topic,
            history_summary=context.history_summary,
            open_questions=tuple(context.open_questions),
            confirmed_facts=tuple(context.confirmed_facts),
            next_steps=tuple(context.next_steps),
            summary_version=context.summary_version,
            summary_updated_at=context.summary_updated_at,
            pending_clarification=pending,
            extra=dict(context.extra),
        )

    def _to_domain_context(
        self,
        context: MemoryPersistentSessionContext,
        current: DomainPersistentSessionContext,
    ) -> DomainPersistentSessionContext:
        pending_clarification = None
        if context.pending_clarification:
            try:
                pending_clarification = ClarificationCard.model_validate(context.pending_clarification)
            except Exception:
                pending_clarification = None
        return current.model_copy(
            update={
                "current_topic": context.current_topic,
                "current_shop": context.current_shop,
                "recent_entities": list(context.recent_entities),
                "clarification_result": dict(context.clarification_result),
                "user_preferences": dict(context.user_preferences),
                "last_retrieval_topic": context.last_retrieval_topic,
                "history_summary": context.history_summary,
                "open_questions": list(context.open_questions),
                "confirmed_facts": list(context.confirmed_facts),
                "next_steps": list(context.next_steps),
                "summary_version": context.summary_version,
                "summary_updated_at": context.summary_updated_at,
                "pending_clarification": pending_clarification,
                "extra": dict(context.extra),
            }
        )

    def _merge_session_state_patch(
        self,
        current: DomainPersistentSessionContext,
        patch: Mapping[str, Any],
    ) -> DomainPersistentSessionContext:
        if not patch:
            return current

        merged_extra = dict(current.extra)
        patch_extra = patch.get("extra")
        if isinstance(patch_extra, Mapping):
            merged_extra.update(dict(patch_extra))

        update_payload = {
            key: value
            for key, value in dict(patch).items()
            if key != "extra"
        }
        if merged_extra:
            update_payload["extra"] = merged_extra
        return current.model_copy(update=update_payload)

    @staticmethod
    def _is_confirmed_preference_query(query: str, normalized_query: str) -> bool:
        phrases = ("以后都", "以后默认", "默认用", "一直用", "长期用", "always use", "default to")
        return any(phrase in query or phrase in normalized_query for phrase in phrases)
