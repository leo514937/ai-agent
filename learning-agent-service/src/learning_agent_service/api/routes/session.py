from __future__ import annotations

from ..compat import APIRouter
from ..contracts import SessionStateResponse
from ..dependencies import LearningAgentService
from ..errors import raise_http_error
from ..internal_auth import internal_token_header, require_internal_token


def register_session_routes(router: APIRouter, service: LearningAgentService) -> None:
    @router.get("/internal/v1/session/{session_id}/state")
    async def get_session_state(
        session_id: str,
        x_internal_token: str | None = internal_token_header(),
    ) -> SessionStateResponse:
        require_internal_token(x_internal_token)
        try:
            return service.get_session_state(session_id)
        except RuntimeError as exc:
            raise_http_error(exc, status_code=503, default_code="LEARN-5600", stage="session_state")
