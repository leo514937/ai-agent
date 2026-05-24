from __future__ import annotations

from ..compat import APIRouter
from ..contracts import FeedbackReportRequest, FeedbackReportResponse, FeedbackSampleResponse
from ..dependencies import LearningAgentService
from ..errors import raise_http_error
from ..internal_auth import internal_token_header, require_internal_token


def register_feedback_routes(router: APIRouter, service: LearningAgentService) -> None:
    @router.post("/internal/v1/feedback/report", response_model=FeedbackReportResponse)
    async def report_feedback(
        request: FeedbackReportRequest,
        x_internal_token: str | None = internal_token_header(),
    ) -> FeedbackReportResponse:
        require_internal_token(x_internal_token)
        try:
            return service.report_feedback(request)
        except RuntimeError as exc:
            raise_http_error(exc, status_code=503, default_code="LEARN-5600", stage="feedback_report")

    @router.get("/internal/v1/feedback/samples", response_model=FeedbackSampleResponse)
    async def list_feedback_samples(
        limit: int = 50,
        x_internal_token: str | None = internal_token_header(),
    ) -> FeedbackSampleResponse:
        require_internal_token(x_internal_token)
        try:
            return service.list_feedback_samples(limit=limit)
        except RuntimeError as exc:
            raise_http_error(exc, status_code=503, default_code="LEARN-5600", stage="feedback_samples")
