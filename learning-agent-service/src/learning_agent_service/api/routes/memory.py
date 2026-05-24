from __future__ import annotations

from ..compat import APIRouter
from ..contracts import (
    MemoryActionRequest,
    MemoryActionResponse,
    MemoryAccessLogListResponse,
    MemoryCandidateListResponse,
    MemoryDeletionJobListResponse,
    MemoryListResponse,
    MemoryRecordSummary,
    MemoryTraceListResponse,
    MemoryTraceSummary,
)
from ..dependencies import LearningAgentService
from ..errors import raise_http_error
from ..internal_auth import internal_token_header, require_internal_token


def register_memory_routes(router: APIRouter, service: LearningAgentService) -> None:
    @router.get("/internal/v1/memory/records", response_model=MemoryListResponse)
    async def list_memory_records(
        user_id: str,
        scope: str | None = None,
        query: str | None = None,
        limit: int = 50,
        x_internal_token: str | None = internal_token_header(),
    ) -> MemoryListResponse:
        require_internal_token(x_internal_token)
        try:
            return service.list_memory_records(user_id=user_id, scope=scope, query=query, limit=limit)
        except RuntimeError as exc:
            raise_http_error(exc, status_code=503, default_code="LEARN-5600", stage="memory_records")

    @router.get("/internal/v1/memory/records/{memory_id}", response_model=MemoryRecordSummary)
    async def get_memory_record(
        memory_id: str,
        x_internal_token: str | None = internal_token_header(),
    ) -> MemoryRecordSummary:
        require_internal_token(x_internal_token)
        try:
            return service.get_memory_record(memory_id)
        except RuntimeError as exc:
            raise_http_error(exc, status_code=404, default_code="LEARN-5600", stage="memory_record")

    @router.get("/internal/v1/memory/candidates", response_model=MemoryCandidateListResponse)
    async def list_memory_candidates(
        user_id: str,
        limit: int = 50,
        x_internal_token: str | None = internal_token_header(),
    ) -> MemoryCandidateListResponse:
        require_internal_token(x_internal_token)
        try:
            return service.list_memory_candidates(user_id=user_id, limit=limit)
        except RuntimeError as exc:
            raise_http_error(exc, status_code=503, default_code="LEARN-5600", stage="memory_candidates")

    @router.get("/internal/v1/memory/traces", response_model=MemoryTraceListResponse)
    async def list_memory_traces(
        user_id: str,
        session_id: str | None = None,
        turn_id: str | None = None,
        limit: int = 20,
        x_internal_token: str | None = internal_token_header(),
    ) -> MemoryTraceListResponse:
        require_internal_token(x_internal_token)
        try:
            return service.list_memory_traces(
                user_id=user_id,
                session_id=session_id,
                turn_id=turn_id,
                limit=limit,
            )
        except RuntimeError as exc:
            raise_http_error(exc, status_code=503, default_code="LEARN-5600", stage="memory_traces")

    @router.get("/internal/v1/memory/traces/{trace_id}", response_model=MemoryTraceSummary)
    async def get_memory_trace(
        trace_id: str,
        x_internal_token: str | None = internal_token_header(),
    ) -> MemoryTraceSummary:
        require_internal_token(x_internal_token)
        try:
            return service.get_memory_trace(trace_id)
        except RuntimeError as exc:
            raise_http_error(exc, status_code=404, default_code="LEARN-5600", stage="memory_trace")

    @router.get("/internal/v1/memory/records/{memory_id}/access-logs", response_model=MemoryAccessLogListResponse)
    async def list_memory_access_logs(
        memory_id: str,
        x_internal_token: str | None = internal_token_header(),
    ) -> MemoryAccessLogListResponse:
        require_internal_token(x_internal_token)
        try:
            return service.list_memory_access_logs(memory_id)
        except RuntimeError as exc:
            raise_http_error(exc, status_code=503, default_code="LEARN-5600", stage="memory_access_logs")

    @router.get("/internal/v1/memory/deletion-jobs", response_model=MemoryDeletionJobListResponse)
    async def list_memory_deletion_jobs(
        limit: int = 50,
        x_internal_token: str | None = internal_token_header(),
    ) -> MemoryDeletionJobListResponse:
        require_internal_token(x_internal_token)
        try:
            return service.list_memory_deletion_jobs(limit=limit)
        except RuntimeError as exc:
            raise_http_error(exc, status_code=503, default_code="LEARN-5600", stage="memory_deletion_jobs")

    @router.post("/internal/v1/memory/candidates/{candidate_id}/confirm", response_model=MemoryActionResponse)
    async def confirm_memory_candidate(
        candidate_id: str,
        request: MemoryActionRequest,
        x_internal_token: str | None = internal_token_header(),
    ) -> MemoryActionResponse:
        require_internal_token(x_internal_token)
        try:
            return service.confirm_memory_candidate(candidate_id, request)
        except RuntimeError as exc:
            raise_http_error(exc, status_code=404, default_code="LEARN-5600", stage="memory_candidate_confirm")

    @router.post("/internal/v1/memory/candidates/{candidate_id}/reject", response_model=MemoryActionResponse)
    async def reject_memory_candidate(
        candidate_id: str,
        request: MemoryActionRequest,
        x_internal_token: str | None = internal_token_header(),
    ) -> MemoryActionResponse:
        require_internal_token(x_internal_token)
        try:
            return service.reject_memory_candidate(candidate_id, request)
        except RuntimeError as exc:
            raise_http_error(exc, status_code=404, default_code="LEARN-5600", stage="memory_candidate_reject")

    @router.post("/internal/v1/memory/records/{memory_id}/supersede", response_model=MemoryActionResponse)
    async def supersede_memory_record(
        memory_id: str,
        request: MemoryActionRequest,
        x_internal_token: str | None = internal_token_header(),
    ) -> MemoryActionResponse:
        require_internal_token(x_internal_token)
        try:
            return service.supersede_memory_record(memory_id, request)
        except RuntimeError as exc:
            raise_http_error(exc, status_code=400, default_code="LEARN-5600", stage="memory_supersede")

    @router.post("/internal/v1/memory/records/{memory_id}/delete", response_model=MemoryActionResponse)
    async def delete_memory_record(
        memory_id: str,
        request: MemoryActionRequest,
        x_internal_token: str | None = internal_token_header(),
    ) -> MemoryActionResponse:
        require_internal_token(x_internal_token)
        try:
            return service.delete_memory_record(memory_id, request)
        except RuntimeError as exc:
            raise_http_error(exc, status_code=400, default_code="LEARN-5600", stage="memory_delete")
