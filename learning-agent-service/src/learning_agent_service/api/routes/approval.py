from __future__ import annotations

from ..compat import APIRouter
from ..contracts import ApprovalSubmitRequest, ApprovalSubmitResponse
from ..dependencies import LearningAgentService
from ..errors import raise_http_error
from ..internal_auth import internal_token_header, require_internal_token


def register_approval_routes(router: APIRouter, service: LearningAgentService) -> None:
    @router.post("/internal/v1/approval/submit")
    async def submit_approval(
        request: ApprovalSubmitRequest,
        x_internal_token: str | None = internal_token_header(),
    ) -> ApprovalSubmitResponse:
        require_internal_token(x_internal_token)
        try:
            return service.submit_approval(request)
        except RuntimeError as exc:
            raise_http_error(exc, status_code=503, default_code="LEARN-5600", stage="approval_submit")
