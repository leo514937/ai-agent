from __future__ import annotations

from dataclasses import asdict, dataclass
from uuid import uuid4

from learning_agent_service.domain.memory import (
    MemoryCandidate,
    MemoryRecord,
    MemoryRetrievalMode,
    MemoryScope,
    MemorySensitivity,
    MemorySource,
    MemoryStatus,
    MemoryTargetStore,
    MemoryType,
)
from learning_agent_service.memory.models import ExplicitUserSignals, MemoryPromotionInput


@dataclass
class RuleBasedMemoryExtractor:
    """从显式用户信号和会话状态中抽取候选记忆。"""

    def extract(self, payload: MemoryPromotionInput) -> list[MemoryCandidate]:
        candidates: list[MemoryCandidate] = []
        candidates.extend(self._extract_preference_candidates(payload))
        candidates.extend(self._extract_session_candidates(payload))
        return candidates

    def _extract_preference_candidates(self, payload: MemoryPromotionInput) -> list[MemoryCandidate]:
        signals = payload.explicit_signals or ExplicitUserSignals()
        candidates: list[MemoryCandidate] = []
        topic = payload.resolved_topic or payload.current_session.current_topic or payload.query or "global"
        query = payload.query or ""
        normalized_query = query.lower()

        if ("中文" in query or "汉语" in query) and "ascii" in normalized_query:
            record = self._build_record(
                payload,
                memory_type=MemoryType.PREFERENCE,
                topic=topic,
                summary="用户偏好：中文回复和 ASCII 图",
                content={
                    "preferred_language": "zh",
                    "preferred_diagram_style": "ascii",
                    "preferred_topic_scope": "agent_architecture",
                },
                confidence=0.88,
                importance=0.9,
                stability=0.88,
                sensitivity=MemorySensitivity.PUBLIC,
                should_vectorize=True,
                tags=["preference", "language", "ascii_diagram"],
            )
            candidates.append(
                self._build_candidate(
                    payload,
                    memory_type=MemoryType.PREFERENCE,
                    record=record,
                    reason="中文和ASCII图偏好",
                    should_promote=True,
                    confidence=0.88,
                    importance=0.9,
                    stability=0.88,
                )
            )

        if signals.preferred_output_style and signals.confirmed_output_style:
            record = self._build_record(
                payload,
                memory_type=MemoryType.PREFERENCE,
                topic=topic,
                summary=f"用户偏好：输出风格 {signals.preferred_output_style}",
                content={"preferred_output_style": signals.preferred_output_style},
                confidence=0.9,
                importance=0.78,
                stability=0.84,
                sensitivity=MemorySensitivity.PUBLIC,
                should_vectorize=False,
                tags=["preference", "output_style"],
            )
            candidates.append(
                self._build_candidate(
                    payload,
                    memory_type=MemoryType.PREFERENCE,
                    record=record,
                    reason="输出风格偏好",
                    should_promote=True,
                    confidence=0.9,
                    importance=0.78,
                    stability=0.84,
                )
            )

        if signals.wants_code_examples or signals.confirmed_code_examples or "代码" in query or "code" in normalized_query:
            record = self._build_record(
                payload,
                memory_type=MemoryType.PREFERENCE,
                topic=topic,
                summary="用户偏好：默认提供代码示例",
                content={
                    "wants_code_examples": bool(signals.wants_code_examples or "代码" in query or "code" in normalized_query),
                    "confirmed_code_examples": bool(signals.confirmed_code_examples),
                },
                confidence=0.86,
                importance=0.76,
                stability=0.82,
                sensitivity=MemorySensitivity.PUBLIC,
                should_vectorize=False,
                tags=["preference", "code_examples"],
            )
            candidates.append(
                self._build_candidate(
                    payload,
                    memory_type=MemoryType.PREFERENCE,
                    record=record,
                    reason="代码示例偏好",
                    should_promote=bool(signals.confirmed_code_examples),
                    confidence=0.86,
                    importance=0.76,
                    stability=0.82,
                )
            )

        return candidates

    def _extract_session_candidates(self, payload: MemoryPromotionInput) -> list[MemoryCandidate]:
        if not payload.answer_text and not payload.query:
            return []
        topic = payload.resolved_topic or payload.current_session.current_topic or payload.query or "session"
        record = self._build_record(
            payload,
            memory_type=MemoryType.SESSION_SUMMARY,
            topic=topic,
            summary=payload.answer_text[:240] or payload.query[:240],
            content={"query": payload.query, "answer": payload.answer_text},
            confidence=0.55,
            importance=0.2,
            stability=0.2,
            sensitivity=MemorySensitivity.INTERNAL,
            should_vectorize=False,
            scope=MemoryScope.SESSION,
            status=MemoryStatus.EPHEMERAL,
            ttl_seconds=3600,
            tags=["session_summary"],
        )
        return [
            self._build_candidate(
                payload,
                memory_type=MemoryType.SESSION_SUMMARY,
                record=record,
                reason="会话摘要",
                should_promote=True,
                confidence=0.8,
                importance=0.8,
                stability=0.7,
            )
        ]

    def _build_candidate(
        self,
        payload: MemoryPromotionInput,
        *,
        memory_type: MemoryType,
        record: MemoryRecord,
        reason: str,
        should_promote: bool,
        confidence: float,
        importance: float,
        stability: float,
    ) -> MemoryCandidate:
        return MemoryCandidate(
            candidate_id=f"{payload.user_id}:{payload.turn_id}:{memory_type.value}:{uuid4().hex[:12]}",
            should_promote=should_promote,
            memory_type=memory_type,
            target_store=MemoryTargetStore.POSTGRES,
            confidence=confidence,
            importance=importance,
            stability=stability,
            reason=reason,
            source_turn_id=payload.turn_id,
            dedupe_key=f"{payload.user_id}:{payload.turn_id}:{memory_type.value}",
            conflict_check_key=f"{payload.user_id}:{record.topic or memory_type.value}:{memory_type.value}",
            governance_action="pending",
            require_confirmation=not should_promote,
            approval_notes=[],
            record=record,
            extra={"topic": record.topic, "source": "rule_based"},
        )

    def _build_record(
        self,
        payload: MemoryPromotionInput,
        *,
        memory_type: MemoryType,
        topic: str,
        summary: str,
        content: dict,
        confidence: float,
        importance: float,
        stability: float,
        sensitivity: MemorySensitivity,
        should_vectorize: bool,
        scope: MemoryScope = MemoryScope.USER,
        status: MemoryStatus = MemoryStatus.ACTIVE,
        ttl_seconds: int | None = None,
        tags: list[str],
    ) -> MemoryRecord:
        return MemoryRecord(
            memory_id=f"{payload.user_id}:{payload.turn_id}:{memory_type.value}:{uuid4().hex[:12]}",
            user_id=payload.user_id,
            session_id=payload.session_id,
            project_id=None,
            topic=topic,
            type=memory_type,
            scope=scope,
            status=status,
            source=MemorySource.MODEL_INFERRED,
            summary=summary,
            content=content,
            confidence=confidence,
            importance=importance,
            stability=stability,
            sensitivity=sensitivity,
            retrieval_mode=MemoryRetrievalMode.AUTO,
            should_vectorize=should_vectorize,
            ttl_seconds=ttl_seconds,
            source_turn_id=payload.turn_id,
            raw_evidence={
                "query": payload.query,
                "answer_text": payload.answer_text,
                "explicit_signals": asdict(payload.explicit_signals),
            },
            tags=tags,
            entities=[topic] if topic else [],
        )


@dataclass
class LLMMemoryExtractor:
    """LLM 抽取接口占位，默认行为是 noop。"""

    enabled: bool = False

    def extract(self, payload: MemoryPromotionInput) -> list[MemoryCandidate]:
        return []
