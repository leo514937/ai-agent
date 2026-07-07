from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..domain.schemas import ClarificationRequest, ErrorEnvelope


class ResponseDirective(BaseModel):
    model_config = ConfigDict(extra="forbid")

    directive_kind: str = "response"
    answer_text: str = ""
    answer_type: str = ""
    response_mode: str = ""
    reason: str = ""
    fallback_reason: str = ""
    trace_id: str = ""
    final_response: str = ""
    preview_text: str = ""
    answer_source: str = ""
    fallback_template_type: str = ""
    clarification_request: ClarificationRequest | None = None
    error_envelope: ErrorEnvelope | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class EarlyResponseDirective(ResponseDirective):
    directive_kind: str = "early_response"


def build_response_directive(
    *,
    directive_kind: str = "response",
    answer_text: str = "",
    answer_type: str = "",
    response_mode: str = "",
    reason: str = "",
    fallback_reason: str = "",
    trace_id: str = "",
    final_response: str = "",
    preview_text: str = "",
    answer_source: str = "",
    fallback_template_type: str = "",
    clarification_request: ClarificationRequest | dict[str, Any] | None = None,
    error_envelope: ErrorEnvelope | dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> ResponseDirective:
    """Build the minimal response directive used across fallback workflows."""

    clarification_request_obj = clarification_request
    if isinstance(clarification_request_obj, dict):
        try:
            clarification_request_obj = ClarificationRequest.model_validate(clarification_request_obj)
        except Exception:
            clarification_request_obj = None
    error_envelope_obj = error_envelope
    if isinstance(error_envelope_obj, dict):
        try:
            error_envelope_obj = ErrorEnvelope.model_validate(error_envelope_obj)
        except Exception:
            error_envelope_obj = None
    return ResponseDirective(
        directive_kind=str(directive_kind or "response"),
        answer_text=str(answer_text or ""),
        answer_type=str(answer_type or ""),
        response_mode=str(response_mode or ""),
        reason=str(reason or ""),
        fallback_reason=str(fallback_reason or ""),
        trace_id=str(trace_id or ""),
        final_response=str(final_response or ""),
        preview_text=str(preview_text or ""),
        answer_source=str(answer_source or ""),
        fallback_template_type=str(fallback_template_type or ""),
        clarification_request=clarification_request_obj,
        error_envelope=error_envelope_obj,
        metadata=dict(metadata or {}),
    )


def build_early_response_directive(
    *,
    answer_text: str = "",
    answer_type: str = "",
    response_mode: str = "",
    reason: str = "",
    fallback_reason: str = "",
    trace_id: str = "",
    preview_text: str = "",
    answer_source: str = "",
    fallback_template_type: str = "",
    clarification_request: ClarificationRequest | dict[str, Any] | None = None,
    error_envelope: ErrorEnvelope | dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> EarlyResponseDirective:
    """Build a structured early-response directive for guard / clarify paths."""

    directive = build_response_directive(
        directive_kind="early_response",
        answer_text=answer_text,
        answer_type=answer_type,
        response_mode=response_mode,
        reason=reason,
        fallback_reason=fallback_reason,
        trace_id=trace_id,
        final_response="",
        preview_text=preview_text or answer_text,
        answer_source=answer_source,
        fallback_template_type=fallback_template_type,
        clarification_request=clarification_request,
        error_envelope=error_envelope,
        metadata=metadata,
    )
    return EarlyResponseDirective.model_validate(directive.model_dump())
