"""DEPRECATED_COMPAT: session state / location 兼容壳。

这个模块只允许旧调用方继续使用，新的状态边界请走 canonical path。
"""

from __future__ import annotations

from typing import Any

from ..domain.schemas import UserContext
from ..domain.state import SessionState, SessionWriteDirective


def build_missing_user_context() -> UserContext:
    return UserContext(
        location_name="",
        lat=None,
        lng=None,
        location_status="missing",
        location_source="receiver",
        requires_location=True,
        location_missing_reason="user_location_not_provided",
    )


def is_location_provided(location: Any) -> bool:
    if location is None:
        return False
    if isinstance(location, UserContext):
        payload = location.model_dump()
    elif isinstance(location, dict):
        payload = dict(location)
    else:
        model_dump = getattr(location, "model_dump", None)
        payload = model_dump() if callable(model_dump) else {}
    if not payload:
        return False
    status = str(payload.get("location_status", "") or "").lower()
    source = str(payload.get("location_source", "") or "").lower()
    if status in {"provided", "test_mock"} or source in {"provided", "test_mock"}:
        return payload.get("lat") is not None and payload.get("lng") is not None
    return False


def extract_location(location: Any) -> dict[str, Any]:
    if not is_location_provided(location):
        return {}
    if isinstance(location, UserContext):
        return location.model_dump()
    if isinstance(location, dict):
        return dict(location)
    model_dump = getattr(location, "model_dump", None)
    return model_dump() if callable(model_dump) else {}


class StateCore:
    """Minimal state utility boundary for session state mutations."""

    def build_session_state(self, **fields: Any) -> SessionState:
        return SessionState(**fields)

    def build_state_patch(
        self,
        set_fields: dict[str, Any] | None = None,
        clear_fields: list[str] | None = None,
    ) -> SessionWriteDirective:
        return SessionWriteDirective(set_fields=set_fields or {}, clear_fields=clear_fields or [])

    def clone_session_state(self, session_state: SessionState) -> SessionState:
        return session_state.model_copy(deep=True)

    def plan_state_update(
        self,
        turn_context: dict[str, Any],
        task_type: str,
        resolve_shop_status: str,
        pending_check_result: str | None = None,
    ) -> dict[str, Any]:
        from ..planning.plans.state_update_planner import plan_state_update

        return plan_state_update(
            turn_context,
            task_type,
            resolve_shop_status,
            pending_check_result=pending_check_result,
        )
