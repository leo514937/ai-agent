from __future__ import annotations

from typing import Any, Dict

from .compat import HTTPException
from .contracts import ErrorPayload


def build_error_payload(
    exc: Exception | Dict[str, Any],
    *,
    default_code: str,
    stage: str,
    retryable: bool = False,
) -> ErrorPayload:
    if isinstance(exc, dict):
        candidate = dict(exc)
    elif exc.args and isinstance(exc.args[0], dict):
        candidate = dict(exc.args[0])
    else:
        candidate = {
            "code": getattr(exc, "code", None),
            "message": getattr(exc, "message", None) or str(exc),
            "retryable": getattr(exc, "retryable", retryable),
            "stage": getattr(exc, "stage", stage),
            "degraded_to": getattr(exc, "degraded_to", None),
            "details": getattr(exc, "details", {}),
        }

    code = candidate.get("code", default_code)
    if hasattr(code, "value"):
        code = code.value

    return ErrorPayload(
        code=str(code or default_code),
        message=str(candidate.get("message") or str(exc)),
        retryable=bool(candidate.get("retryable", retryable)),
        stage=str(candidate.get("stage") or stage),
        degraded_to=candidate.get("degraded_to"),
        details=dict(candidate.get("details") or {}),
    )


def raise_http_error(
    exc: Exception | Dict[str, Any],
    *,
    status_code: int,
    default_code: str,
    stage: str,
    retryable: bool = False,
) -> None:
    payload = build_error_payload(
        exc,
        default_code=default_code,
        stage=stage,
        retryable=retryable,
    )
    raise HTTPException(status_code=status_code, detail=payload.model_dump(mode="json"))
