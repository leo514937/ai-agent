from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence
from uuid import uuid4

from learning_agent_service.api.contracts import (
    AckPayload,
    ApprovalSubmitRequest,
    ApprovalSubmitResponse,
    ChatStreamRequest,
    ErrorPayload as ApiErrorPayload,
    EventType,
    FeedbackIssueType,
    FeedbackReportRequest,
    FeedbackReportResponse,
    FeedbackSampleItem,
    FeedbackSampleResponse,
    MemoryActionRequest,
    MemoryActionResponse,
    MemoryAccessLogListResponse,
    MemoryAccessLogSummary,
    MemoryCandidateListResponse,
    MemoryCandidateSummary,
    MemoryDeletionJobListResponse,
    MemoryDeletionJobSummary,
    MemoryListResponse,
    MemoryRecordSummary,
    MemoryTraceListResponse,
    MemoryTraceSummary,
    SessionStateResponse,
    SseEnvelope as ApiSseEnvelope,
)
from learning_agent_service.application.use_cases import (
    ChatWorkflowService,
    SessionQueryService,
)
from learning_agent_service.domain import ChatTurnCommand, GraphRuntimeMeta
from learning_agent_service.domain.guards import validate_memory_record_mutation
from learning_agent_service.domain.memory import MemoryScope, MemoryStatus, MemoryTargetStore
from learning_agent_service.infrastructure.repositories.records import OutboxEventRecord


def _memory_record_summary(record) -> MemoryRecordSummary:
    return MemoryRecordSummary.model_validate(record.model_dump(mode="json"))


def _memory_candidate_summary(candidate) -> MemoryCandidateSummary:
    payload = candidate.model_dump(mode="json") if hasattr(candidate, "model_dump") else dict(candidate)
    if isinstance(payload, dict):
        payload = dict(payload)
        record = payload.get("record")
        if record is not None and not isinstance(record, dict):
            payload["record"] = record.model_dump(mode="json") if hasattr(record, "model_dump") else dict(record)
    return MemoryCandidateSummary.model_validate(payload)


def _memory_trace_summary(trace) -> MemoryTraceSummary:
    return MemoryTraceSummary.model_validate(trace.model_dump(mode="json"))


def _memory_access_log_summary(log) -> MemoryAccessLogSummary:
    return MemoryAccessLogSummary.model_validate(log.model_dump(mode="json"))


def _memory_deletion_job_summary(job) -> MemoryDeletionJobSummary:
    return MemoryDeletionJobSummary.model_validate(job.model_dump(mode="json"))


def _outbox_sample_item(event) -> FeedbackSampleItem:
    payload = {
        "event_id": getattr(event, "id", ""),
        "aggregate_type": getattr(event, "aggregate_type", ""),
        "aggregate_id": getattr(event, "aggregate_id", ""),
        "event_type": getattr(event, "event_type", ""),
        "status": getattr(event, "status", ""),
        "trace_id": getattr(event, "trace_id", None),
        "available_at": getattr(event, "available_at", None),
        "published_at": getattr(event, "published_at", None),
        "payload": dict(getattr(event, "payload", {}) or {}),
        "attempts": int(getattr(event, "attempts", 0) or 0),
        "last_error": getattr(event, "last_error", None),
    }
    return FeedbackSampleItem.model_validate(payload)


class WorkflowLearningAgentService:
    def __init__(self, container) -> None:
        self.container = container
        self.chat_use_case = ChatWorkflowService(container)
        self.session_query_use_case = SessionQueryService(memory_service=container.memory_service)

    def run_stream(self, request: ChatStreamRequest) -> Iterable[ApiSseEnvelope]:
        turn_id = request.turn_id or "turn-{value}".format(value=uuid4().hex[:8])
        command = ChatTurnCommand(
            trace_id=request.trace_id,
            session_id=request.session_id,
            turn_id=turn_id,
            user_id=request.user_id,
            message=request.message,
            page=request.page,
            response_mode=request.response_mode,
            topic_hint=request.topic_hint,
            history_summary=request.history_summary,
            client_context=request.client_context,
        )
        ack = ApiSseEnvelope(
            event_type=EventType.ACK.value,
            trace_id=request.trace_id,
            session_id=request.session_id,
            turn_id=turn_id,
            timestamp=datetime.now(timezone.utc),
            workflow_version=self.container.settings.workflow_version,
            payload=AckPayload(
                message="accepted",
                accepted_at=datetime.now(timezone.utc),
                current_stage="accepted",
                stage_status="completed",
                route_reason="request_accepted",
            ).model_dump(mode="json"),
        )
        yield ack

        persistent = None
        session_context_store = getattr(self.container, "session_context_store", None)
        if session_context_store is not None:
            try:
                persistent = session_context_store.load(request.session_id, request.user_id)
            except Exception:
                persistent = None
        try:
            for event in self.chat_use_case.run(command=command, persistent_context=persistent):
                yield ApiSseEnvelope.model_validate(event.model_dump(mode="json"))
        except Exception as exc:
            yield ApiSseEnvelope(
                event_type=EventType.ERROR.value,
                trace_id=request.trace_id,
                session_id=request.session_id,
                turn_id=turn_id,
                timestamp=datetime.now(timezone.utc),
                workflow_version=self.container.settings.workflow_version,
                payload=ApiErrorPayload(
                    code="LEARN-5600",
                    message=str(exc),
                    retryable=False,
                    stage="chat_stream",
                ).model_dump(mode="json"),
            )

    def get_session_state(self, session_id: str) -> SessionStateResponse:
        context = self.session_query_use_case.get(session_id)
        return SessionStateResponse(
            session_id=session_id,
            current_topic=context.current_topic,
            current_shop=getattr(context, "current_shop", None),
            recent_entities=list(context.recent_entities),
            clarification_result=dict(context.clarification_result),
            user_preferences=dict(context.user_preferences),
            last_retrieval_topic=context.last_retrieval_topic,
            history_summary=context.history_summary,
            open_questions=list(getattr(context, "open_questions", []) or []),
            confirmed_facts=list(getattr(context, "confirmed_facts", []) or []),
            next_steps=list(getattr(context, "next_steps", []) or []),
            summary_version=int(getattr(context, "summary_version", 0) or 0),
            summary_updated_at=getattr(context, "summary_updated_at", None),
            route_decision=getattr(context, "route_decision", None),
            route_reason=getattr(context, "route_reason", None),
            current_stage=getattr(context, "current_stage", None),
            stage_status=getattr(context, "stage_status", None),
            stage_timeline=list(getattr(context, "stage_timeline", []) or []),
            extra=dict(context.extra),
        )

    def submit_approval(self, request: ApprovalSubmitRequest) -> ApprovalSubmitResponse:
        session_context_store = getattr(self.container, "session_context_store", None)
        if session_context_store is None:
            raise RuntimeError("Session context store is unavailable")

        try:
            persistent = session_context_store.load(request.session_id, request.user_id)
        except Exception as exc:
            raise RuntimeError("Unable to load session state for approval") from exc

        decision = str(request.decision or "").strip().lower()
        if decision not in {"approved", "rejected"}:
            raise RuntimeError("Unsupported approval decision")

        approval_request = dict(request.approval_request or {})
        approval_request.setdefault("approval_id", request.approval_id or request.turn_id)
        approval_request["approval_state"] = decision

        extra = dict(getattr(persistent, "extra", {}) or {})
        extra["pending_approval_request"] = approval_request
        extra["pending_approval_state"] = decision
        extra["approval_resume_decision"] = decision
        extra["approval_updated_at"] = datetime.now(timezone.utc).isoformat()

        updated = persistent.model_copy(
            update={
                "extra": extra,
            }
        )
        runtime = GraphRuntimeMeta(
            trace_id=request.trace_id,
            session_id=request.session_id,
            turn_id=request.turn_id,
            workflow_version=self.container.settings.workflow_version,
            request_ts=datetime.now(timezone.utc),
            user_id=request.user_id,
            client_context=dict(request.context or {}),
        )
        try:
            session_context_store.save(updated, runtime)
        except Exception as exc:
            raise RuntimeError("Unable to persist approval decision") from exc

        return ApprovalSubmitResponse(
            session_id=request.session_id,
            trace_id=request.trace_id,
            turn_id=request.turn_id,
            approval_state=decision,
            accepted=True,
            pending_approval=False,
            approval_request=approval_request,
            message="审批结果已记录",
        )

    def report_feedback(self, request: FeedbackReportRequest) -> FeedbackReportResponse:
        outbox = getattr(self.container, "outbox_repository", None)
        if outbox is None:
            raise RuntimeError("Outbox repository is unavailable")
        recorded_at = datetime.now(timezone.utc)
        payload: Dict[str, Any] = {
            "user_id": request.user_id,
            "session_id": request.session_id,
            "turn_id": request.turn_id,
            "thread_id": request.thread_id,
            "trace_id": request.trace_id,
            "issue_type": request.issue_type.value if hasattr(request.issue_type, "value") else str(request.issue_type),
            "is_helpful": request.is_helpful,
            "comment": request.comment,
            "final_payload": dict(request.final_payload or {}),
            "timeline": list(request.timeline or []),
            "retrieval_summary": dict(request.retrieval_summary or {}),
            "memory_used_summary": dict(request.memory_used_summary or {}),
            "context": dict(request.context or {}),
            "recorded_at": recorded_at.isoformat(),
        }
        event = OutboxEventRecord(
            aggregate_type="agent_feedback",
            aggregate_id=request.thread_id or request.session_id,
            event_type=f"feedback.{request.issue_type.value if hasattr(request.issue_type, 'value') else request.issue_type}",
            dedupe_key="feedback:{trace}:{turn}:{issue}".format(
                trace=request.trace_id or request.session_id,
                turn=request.turn_id,
                issue=request.issue_type.value if hasattr(request.issue_type, "value") else str(request.issue_type),
            ),
            payload=payload,
            trace_id=request.trace_id,
            status="pending",
            available_at=recorded_at,
            attempts=0,
            last_error=None,
        )
        saved = outbox.enqueue(event)
        return FeedbackReportResponse(
            feedback_id=str(getattr(saved, "id", "")),
            status=str(getattr(saved, "status", "pending")),
            recorded_at=getattr(saved, "created_at", recorded_at),
            dedupe_key=str(getattr(saved, "dedupe_key", "")),
            payload=dict(getattr(saved, "payload", {}) or {}),
        )

    def list_feedback_samples(self, limit: int = 50) -> FeedbackSampleResponse:
        outbox = getattr(self.container, "outbox_repository", None)
        if outbox is None:
            raise RuntimeError("Outbox repository is unavailable")
        records = [
            _outbox_sample_item(event)
            for event in outbox.list_recent(limit=limit, aggregate_type="agent_feedback", event_type_prefix="feedback.")
        ]
        return FeedbackSampleResponse(records=records, total=len(records))

    def list_memory_records(
        self,
        user_id: str,
        scope: str | None = None,
        query: str | None = None,
        limit: int = 50,
    ) -> MemoryListResponse:
        repository = getattr(self.container, "long_term_repository", None)
        if repository is None:
            raise RuntimeError("Long-term memory repository is unavailable")
        if query:
            records = list(repository.search(query, user_id=user_id, limit=limit))
        elif scope:
            scope_enum = MemoryScope(str(scope).lower())
            records = list(repository.list_by_scope(user_id, scope_enum))
        else:
            finder = getattr(repository, "find_active_by_user", None)
            records = list(finder(user_id)) if callable(finder) else list(repository.search("", user_id=user_id, limit=limit))
        sliced = records[:limit]
        return MemoryListResponse(records=[_memory_record_summary(record) for record in sliced], total=len(records))

    def list_memory_candidates(self, user_id: str, limit: int = 50) -> MemoryCandidateListResponse:
        repository = getattr(self.container, "long_term_repository", None)
        if repository is None:
            raise RuntimeError("Long-term memory repository is unavailable")
        records = list(repository.list_candidates(user_id=user_id))[:limit]
        return MemoryCandidateListResponse(records=[_memory_candidate_summary(item) for item in records], total=len(records))

    def get_memory_record(self, memory_id: str) -> MemoryRecordSummary:
        repository = getattr(self.container, "long_term_repository", None)
        if repository is None:
            raise RuntimeError("Long-term memory repository is unavailable")
        record = repository.get(memory_id)
        if record is None:
            raise RuntimeError(f"Memory record {memory_id} not found")
        return _memory_record_summary(record)

    def list_memory_traces(
        self,
        user_id: str,
        session_id: str | None = None,
        turn_id: str | None = None,
        limit: int = 20,
    ) -> MemoryTraceListResponse:
        repository = getattr(self.container, "memory_trace_repository", None)
        if repository is None:
            raise RuntimeError("Memory trace repository is unavailable")
        if session_id:
            traces = [trace for trace in repository.list_by_session(session_id) if trace.user_id == user_id]
        elif turn_id:
            traces = [trace for trace in repository.list_by_turn(turn_id) if trace.user_id == user_id]
        else:
            traces = list(repository.list_recent_by_user(user_id, limit=limit))
        traces = traces[:limit]
        return MemoryTraceListResponse(records=[_memory_trace_summary(trace) for trace in traces], total=len(traces))

    def get_memory_trace(self, trace_id: str) -> MemoryTraceSummary:
        repository = getattr(self.container, "memory_trace_repository", None)
        if repository is None:
            raise RuntimeError("Memory trace repository is unavailable")
        trace = repository.get_by_trace_id(trace_id)
        if trace is None:
            raise RuntimeError(f"Memory trace {trace_id} not found")
        return _memory_trace_summary(trace)

    def list_memory_access_logs(self, memory_id: str) -> MemoryAccessLogListResponse:
        repository = getattr(self.container, "long_term_repository", None)
        if repository is None:
            raise RuntimeError("Long-term memory repository is unavailable")
        logs = list(repository.list_access_logs(memory_id))
        return MemoryAccessLogListResponse(records=[_memory_access_log_summary(item) for item in logs], total=len(logs))

    def list_memory_deletion_jobs(self, limit: int = 50) -> MemoryDeletionJobListResponse:
        repository = getattr(self.container, "long_term_repository", None)
        if repository is None:
            raise RuntimeError("Long-term memory repository is unavailable")
        jobs = list(repository.list_deletion_jobs())[:limit]
        return MemoryDeletionJobListResponse(records=[_memory_deletion_job_summary(item) for item in jobs], total=len(jobs))

    def confirm_memory_candidate(self, candidate_id: str, request: MemoryActionRequest) -> MemoryActionResponse:
        repository = getattr(self.container, "long_term_repository", None)
        if repository is None:
            raise RuntimeError("Long-term memory repository is unavailable")
        candidate = repository.get_candidate(candidate_id)
        if candidate is None:
            raise RuntimeError(f"Memory candidate {candidate_id} not found")
        mutation_guard = validate_memory_record_mutation(candidate.record)
        if not mutation_guard.allowed:
            raise RuntimeError(mutation_guard.reason.replace("_", " "))
        record = candidate.record.model_copy(
            update={
                "memory_id": candidate.memory_id or candidate.record.memory_id or candidate.candidate_id,
                "user_id": candidate.record.user_id or candidate.user_id,
                "session_id": candidate.record.session_id or candidate.session_id,
                "project_id": candidate.record.project_id or candidate.project_id,
                "topic": candidate.record.topic or candidate.topic,
                "type": candidate.record.type or candidate.memory_type,
                "scope": candidate.record.scope or candidate.scope,
                "status": MemoryStatus.CONFIRMED,
                "source": candidate.record.source,
                "updated_at": datetime.now(timezone.utc),
                "extra": {
                    **dict(candidate.record.extra or {}),
                    "mutation_guard_reason": mutation_guard.reason,
                    "mutation_operation": "confirm",
                },
            }
        )
        stored = repository.upsert(record)
        updated_candidate = repository.update_candidate(
            candidate_id,
            status="confirmed",
            governance_action="confirmed",
            decision_reason=request.reason or candidate.decision_reason or candidate.reason,
            require_confirmation=False,
            extra={
                **dict(candidate.extra or {}),
                "confirmed_memory_id": stored.memory_id,
                "reason": request.reason,
                "mutation_guard_reason": mutation_guard.reason,
            },
        )
        return MemoryActionResponse(
            status="success",
            action="confirm",
            message="candidate confirmed",
            record=_memory_record_summary(stored),
            candidate=_memory_candidate_summary(updated_candidate) if updated_candidate is not None else None,
        )

    def reject_memory_candidate(self, candidate_id: str, request: MemoryActionRequest) -> MemoryActionResponse:
        repository = getattr(self.container, "long_term_repository", None)
        if repository is None:
            raise RuntimeError("Long-term memory repository is unavailable")
        candidate = repository.get_candidate(candidate_id)
        if candidate is None:
            raise RuntimeError(f"Memory candidate {candidate_id} not found")
        mutation_guard = validate_memory_record_mutation(candidate.record)
        if not mutation_guard.allowed:
            raise RuntimeError(mutation_guard.reason.replace("_", " "))
        updated_candidate = repository.update_candidate(
            candidate_id,
            status="rejected",
            governance_action="rejected",
            decision_reason=request.reason or candidate.decision_reason or candidate.reason,
            require_confirmation=False,
            extra={
                **dict(candidate.extra or {}),
                "rejection_reason": request.reason,
                "mutation_guard_reason": mutation_guard.reason,
            },
        )
        return MemoryActionResponse(
            status="success",
            action="reject",
            message="candidate rejected",
            candidate=_memory_candidate_summary(updated_candidate) if updated_candidate is not None else None,
        )

    def supersede_memory_record(self, memory_id: str, request: MemoryActionRequest) -> MemoryActionResponse:
        repository = getattr(self.container, "long_term_repository", None)
        if repository is None:
            raise RuntimeError("Long-term memory repository is unavailable")
        superseded_by = request.superseded_by or request.target_memory_id
        if not superseded_by:
            raise RuntimeError("superseded_by is required")
        reason = request.reason or "manual supersede"
        current = repository.get(memory_id)
        if current is None:
            raise RuntimeError(f"Memory record {memory_id} not found")
        mutation_guard = validate_memory_record_mutation(current)
        if not mutation_guard.allowed:
            raise RuntimeError(mutation_guard.reason.replace("_", " "))
        repository.supersede(memory_id, superseded_by, reason)
        record = repository.get(memory_id)
        if record is not None:
            record = record.model_copy(
                update={
                    "extra": {
                        **dict(record.extra or {}),
                        "mutation_guard_reason": mutation_guard.reason,
                        "mutation_operation": "supersede",
                    }
                }
            )
        return MemoryActionResponse(
            status="success",
            action="supersede",
            message="memory superseded",
            record=_memory_record_summary(record) if record is not None else None,
        )

    def delete_memory_record(self, memory_id: str, request: MemoryActionRequest) -> MemoryActionResponse:
        repository = getattr(self.container, "long_term_repository", None)
        if repository is None:
            raise RuntimeError("Long-term memory repository is unavailable")
        reason = request.reason or "manual delete"
        current = repository.get(memory_id)
        if current is None:
            raise RuntimeError(f"Memory record {memory_id} not found")
        mutation_guard = validate_memory_record_mutation(current)
        if not mutation_guard.allowed:
            raise RuntimeError(mutation_guard.reason.replace("_", " "))
        repository.soft_delete(memory_id, reason)
        record = repository.get(memory_id)
        if record is not None:
            record = record.model_copy(
                update={
                    "extra": {
                        **dict(record.extra or {}),
                        "mutation_guard_reason": mutation_guard.reason,
                        "mutation_operation": "delete",
                    }
                }
            )
        return MemoryActionResponse(
            status="success",
            action="delete",
            message="memory deleted",
            record=_memory_record_summary(record) if record is not None else None,
        )


def create_learning_agent_service(container) -> WorkflowLearningAgentService:
    return WorkflowLearningAgentService(container)
