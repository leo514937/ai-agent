from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class RequestLegalityResult:
    allowed: bool
    blocked: bool
    reason: str | None = None
    required_action: str = "direct_answer"
    route_candidate: str | None = None
    details: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def check_request_legality(
    *,
    session_id: str | None,
    user_id: str | None,
    turn_id: str | None = None,
    trace_id: str | None = None,
) -> RequestLegalityResult:
    normalized_session_id = str(session_id or "").strip()
    normalized_user_id = str(user_id or "").strip()
    normalized_turn_id = str(turn_id or "").strip()
    normalized_trace_id = str(trace_id or "").strip()

    missing = []
    if not normalized_session_id:
        missing.append("session_id")
    if not normalized_user_id:
        missing.append("user_id")
    if not normalized_turn_id:
        missing.append("turn_id")
    if not normalized_trace_id:
        missing.append("trace_id")

    if missing:
        reason = "missing_" + "_".join(missing)
        return RequestLegalityResult(
            allowed=False,
            blocked=True,
            reason=reason,
            required_action="reject",
            route_candidate="reject",
            details={"missing_fields": missing},
        )

    return RequestLegalityResult(
        allowed=True,
        blocked=False,
        reason="request_legal",
        required_action="direct_answer",
        route_candidate="direct_answer",
        details={"session_id": normalized_session_id, "user_id": normalized_user_id},
    )
