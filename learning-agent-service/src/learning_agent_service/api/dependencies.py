from __future__ import annotations

from typing import Iterable, Protocol

from .contracts import (
    ApprovalSubmitRequest,
    ApprovalSubmitResponse,
    ChatStreamRequest,
    FeedbackReportRequest,
    FeedbackReportResponse,
    FeedbackSampleResponse,
    MemoryActionRequest,
    MemoryActionResponse,
    MemoryAccessLogListResponse,
    MemoryCandidateListResponse,
    MemoryDeletionJobListResponse,
    MemoryListResponse,
    MemoryRecordSummary,
    MemoryTraceListResponse,
    MemoryTraceSummary,
    SessionStateResponse,
    SseEnvelope,
)


class LearningAgentService(Protocol):
    def run_stream(self, request: ChatStreamRequest) -> Iterable[SseEnvelope]:
        ...

    def get_session_state(self, session_id: str) -> SessionStateResponse:
        ...

    def submit_approval(self, request: ApprovalSubmitRequest) -> ApprovalSubmitResponse:
        ...

    def report_feedback(self, request: FeedbackReportRequest) -> FeedbackReportResponse:
        ...

    def list_feedback_samples(self, limit: int = 50) -> FeedbackSampleResponse:
        ...

    def list_memory_records(
        self,
        user_id: str,
        scope: str | None = None,
        query: str | None = None,
        limit: int = 50,
    ) -> MemoryListResponse:
        ...

    def list_memory_candidates(
        self,
        user_id: str,
        limit: int = 50,
    ) -> MemoryCandidateListResponse:
        ...

    def get_memory_record(self, memory_id: str) -> MemoryRecordSummary:
        ...

    def list_memory_traces(
        self,
        user_id: str,
        session_id: str | None = None,
        turn_id: str | None = None,
        limit: int = 20,
    ) -> MemoryTraceListResponse:
        ...

    def get_memory_trace(self, trace_id: str) -> MemoryTraceSummary:
        ...

    def list_memory_access_logs(self, memory_id: str) -> MemoryAccessLogListResponse:
        ...

    def list_memory_deletion_jobs(self, limit: int = 50) -> MemoryDeletionJobListResponse:
        ...

    def confirm_memory_candidate(
        self,
        candidate_id: str,
        request: MemoryActionRequest,
    ) -> MemoryActionResponse:
        ...

    def reject_memory_candidate(
        self,
        candidate_id: str,
        request: MemoryActionRequest,
    ) -> MemoryActionResponse:
        ...

    def supersede_memory_record(
        self,
        memory_id: str,
        request: MemoryActionRequest,
    ) -> MemoryActionResponse:
        ...

    def delete_memory_record(
        self,
        memory_id: str,
        request: MemoryActionRequest,
    ) -> MemoryActionResponse:
        ...


class UnavailableLearningAgentService:
    def _raise(self) -> None:
        raise RuntimeError("Learning agent service is not configured.")

    def run_stream(self, request: ChatStreamRequest) -> Iterable[SseEnvelope]:
        self._raise()
        return []

    def get_session_state(self, session_id: str) -> SessionStateResponse:
        self._raise()
        raise AssertionError("unreachable")

    def submit_approval(self, request: ApprovalSubmitRequest) -> ApprovalSubmitResponse:
        self._raise()
        raise AssertionError("unreachable")

    def report_feedback(self, request: FeedbackReportRequest) -> FeedbackReportResponse:
        self._raise()
        raise AssertionError("unreachable")

    def list_feedback_samples(self, limit: int = 50) -> FeedbackSampleResponse:
        self._raise()
        raise AssertionError("unreachable")

    def list_memory_records(
        self,
        user_id: str,
        scope: str | None = None,
        query: str | None = None,
        limit: int = 50,
    ) -> MemoryListResponse:
        self._raise()
        raise AssertionError("unreachable")

    def list_memory_candidates(
        self,
        user_id: str,
        limit: int = 50,
    ) -> MemoryCandidateListResponse:
        self._raise()
        raise AssertionError("unreachable")

    def get_memory_record(self, memory_id: str) -> MemoryRecordSummary:
        self._raise()
        raise AssertionError("unreachable")

    def list_memory_traces(
        self,
        user_id: str,
        session_id: str | None = None,
        turn_id: str | None = None,
        limit: int = 20,
    ) -> MemoryTraceListResponse:
        self._raise()
        raise AssertionError("unreachable")

    def get_memory_trace(self, trace_id: str) -> MemoryTraceSummary:
        self._raise()
        raise AssertionError("unreachable")

    def list_memory_access_logs(self, memory_id: str) -> MemoryAccessLogListResponse:
        self._raise()
        raise AssertionError("unreachable")

    def list_memory_deletion_jobs(self, limit: int = 50) -> MemoryDeletionJobListResponse:
        self._raise()
        raise AssertionError("unreachable")

    def confirm_memory_candidate(
        self,
        candidate_id: str,
        request: MemoryActionRequest,
    ) -> MemoryActionResponse:
        self._raise()
        raise AssertionError("unreachable")

    def reject_memory_candidate(
        self,
        candidate_id: str,
        request: MemoryActionRequest,
    ) -> MemoryActionResponse:
        self._raise()
        raise AssertionError("unreachable")

    def supersede_memory_record(
        self,
        memory_id: str,
        request: MemoryActionRequest,
    ) -> MemoryActionResponse:
        self._raise()
        raise AssertionError("unreachable")

    def delete_memory_record(
        self,
        memory_id: str,
        request: MemoryActionRequest,
    ) -> MemoryActionResponse:
        self._raise()
        raise AssertionError("unreachable")
