from __future__ import annotations

from typing import Optional

from .compat import APIRouter
from .dependencies import LearningAgentService, UnavailableLearningAgentService
from .routes import (
    register_approval_routes,
    register_chat_routes,
    register_feedback_routes,
    register_memory_routes,
    register_session_routes,
)


def create_api_router(
    service: Optional[LearningAgentService] = None,
) -> APIRouter:
    router = APIRouter()
    bound_service = service or UnavailableLearningAgentService()
    register_approval_routes(router, bound_service)
    register_chat_routes(router, bound_service)
    register_session_routes(router, bound_service)
    register_feedback_routes(router, bound_service)
    register_memory_routes(router, bound_service)
    return router
