from __future__ import annotations

from ..compat import APIRouter
from ..contracts import SessionStateResponse, SessionHistoryResponse, ReplayRequest, ForkRequest
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


def register_session_history_routes(router: APIRouter, service: LearningAgentService) -> None:
    @router.get("/internal/v1/session/{session_id}/state/history")
    async def get_session_state_history(
        session_id: str,
        x_internal_token: str | None = internal_token_header(),
    ) -> SessionHistoryResponse:
        require_internal_token(x_internal_token)
        try:
            return service.get_session_state_history(session_id)
        except RuntimeError as exc:
            raise_http_error(exc, status_code=503, default_code="LEARN-5600", stage="session_history")

    @router.post("/internal/v1/session/{session_id}/state/replay")
    async def replay_session_state(
        session_id: str,
        request: ReplayRequest,
        x_internal_token: str | None = internal_token_header(),
    ) -> SessionStateResponse:
        require_internal_token(x_internal_token)
        try:
            return service.replay_session_state(session_id, request)
        except RuntimeError as exc:
            raise_http_error(exc, status_code=503, default_code="LEARN-5600", stage="session_replay")

    @router.post("/internal/v1/session/{session_id}/state/fork")
    async def fork_session_state(
        session_id: str,
        request: ForkRequest,
        x_internal_token: str | None = internal_token_header(),
    ) -> SessionStateResponse:
        require_internal_token(x_internal_token)
        try:
            return service.fork_session_state(session_id, request)
        except RuntimeError as exc:
            raise_http_error(exc, status_code=503, default_code="LEARN-5600", stage="session_fork")

