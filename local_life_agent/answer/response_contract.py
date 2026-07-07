from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .response_directive import ResponseDirective


class ResponseContractV1(BaseModel):
    """Minimal unified final-response contract for Phase 3."""

    model_config = ConfigDict(extra="forbid")

    answer_text: str = ""
    answer_type: str = ""
    response_mode: str = ""
    trace_id: str = ""
    verifier_result: str = ""
    fallback_reason: str = ""
    uncertainty_notices: list[str] = Field(default_factory=list)
    preview_text: str = ""
    answer_source: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_response_contract_v2(
        cls,
        contract: "ResponseContractV2" | dict[str, Any] | None = None,
        *,
        verifier_result: str = "",
        fallback_reason: str = "",
        uncertainty_notices: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "ResponseContractV1":
        if contract is None:
            contract_obj = ResponseContractV2()
        elif isinstance(contract, ResponseContractV2):
            contract_obj = contract
        elif isinstance(contract, dict):
            try:
                contract_obj = ResponseContractV2.model_validate(contract)
            except Exception:
                contract_obj = ResponseContractV2()
        else:
            contract_obj = ResponseContractV2()
        metadata_obj = dict(metadata or contract_obj.metadata or {})
        if getattr(contract_obj, "reason", "") and not metadata_obj.get("reason"):
            metadata_obj["reason"] = str(getattr(contract_obj, "reason", "") or "")
        for key in ("claims", "citations", "cards", "response_policy", "clarification", "safety_notice", "trace_summary"):
            value = getattr(contract_obj, key, None)
            if value is not None and key not in metadata_obj:
                metadata_obj[key] = value
        return cls(
            answer_text=str(contract_obj.answer_text or contract_obj.preview_text or contract_obj.final_response or "").strip(),
            answer_type=str(contract_obj.answer_type or ""),
            response_mode=str(contract_obj.response_mode or ""),
            trace_id=str(contract_obj.trace_id or ""),
            verifier_result=str(verifier_result or str((contract_obj.metadata or {}).get("verifier_result", "")) or ""),
            fallback_reason=str(fallback_reason or contract_obj.fallback_reason or ""),
            uncertainty_notices=list(uncertainty_notices or []),
            preview_text=str(contract_obj.preview_text or contract_obj.answer_text or contract_obj.final_response or "").strip(),
            answer_source=str(contract_obj.answer_source or ""),
            metadata=metadata_obj,
        )

    @classmethod
    def from_response_directive(
        cls,
        directive: ResponseDirective | dict[str, Any] | None = None,
        *,
        verifier_result: str = "",
        fallback_reason: str = "",
        uncertainty_notices: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "ResponseContractV1":
        if directive is None:
            directive_obj = ResponseDirective()
        elif isinstance(directive, ResponseDirective):
            directive_obj = directive
        elif isinstance(directive, dict):
            try:
                directive_obj = ResponseDirective.model_validate(directive)
            except Exception:
                directive_obj = ResponseDirective()
        else:
            directive_obj = ResponseDirective()
        answer_text = str(directive_obj.final_response or directive_obj.preview_text or directive_obj.answer_text or "").strip()
        preview_text = str(directive_obj.preview_text or answer_text or "").strip()
        metadata_obj = dict(metadata or directive_obj.metadata or {})
        if getattr(directive_obj, "reason", "") and not metadata_obj.get("reason"):
            metadata_obj["reason"] = str(getattr(directive_obj, "reason", "") or "")
        error_envelope = getattr(directive_obj, "error_envelope", None)
        if error_envelope is not None and "error_envelope" not in metadata_obj:
            metadata_obj["error_envelope"] = (
                error_envelope.model_dump() if hasattr(error_envelope, "model_dump") else dict(getattr(error_envelope, "__dict__", {}) or {})
            )
        clarification_request = getattr(directive_obj, "clarification_request", None)
        if clarification_request is not None and "clarification_request" not in metadata_obj:
            metadata_obj["clarification_request"] = (
                clarification_request.model_dump() if hasattr(clarification_request, "model_dump") else dict(getattr(clarification_request, "__dict__", {}) or {})
            )
        return cls(
            answer_text=answer_text,
            answer_type=str(directive_obj.answer_type or ""),
            response_mode=str(directive_obj.response_mode or ""),
            trace_id=str(directive_obj.trace_id or ""),
            verifier_result=str(verifier_result or str((directive_obj.metadata or {}).get("verifier_result", "")) or ""),
            fallback_reason=str(fallback_reason or directive_obj.fallback_reason or ""),
            uncertainty_notices=list(uncertainty_notices or []),
            preview_text=preview_text,
            answer_source=str(directive_obj.answer_source or ""),
            metadata=metadata_obj,
        )


class ResponseContractV2(ResponseContractV1):
    """Extended authoritative final-response contract for Phase 8."""

    claims: list[dict[str, Any]] = Field(default_factory=list)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    cards: list[dict[str, Any]] = Field(default_factory=list)
    confidence_band: str = ""
    response_policy: dict[str, Any] = Field(default_factory=dict)
    clarification: dict[str, Any] = Field(default_factory=dict)
    safety_notice: list[str] = Field(default_factory=list)
    trace_summary: dict[str, Any] = Field(default_factory=dict)
    final_response: str = ""

    @classmethod
    def from_response_directive(
        cls,
        directive: ResponseDirective | dict[str, Any] | None = None,
        *,
        verifier_result: str = "",
        fallback_reason: str = "",
        uncertainty_notices: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        claims: list[dict[str, Any]] | None = None,
        citations: list[dict[str, Any]] | None = None,
        cards: list[dict[str, Any]] | None = None,
        confidence_band: str = "",
        response_policy: dict[str, Any] | None = None,
        clarification: dict[str, Any] | None = None,
        safety_notice: list[str] | None = None,
        trace_summary: dict[str, Any] | None = None,
    ) -> "ResponseContractV2":
        if directive is None:
            directive_obj = ResponseDirective()
        elif isinstance(directive, ResponseDirective):
            directive_obj = directive
        elif isinstance(directive, dict):
            try:
                directive_obj = ResponseDirective.model_validate(directive)
            except Exception:
                directive_obj = ResponseDirective()
        else:
            directive_obj = ResponseDirective()
        metadata_obj = dict(metadata or directive_obj.metadata or {})
        answer_text = str(directive_obj.final_response or directive_obj.preview_text or directive_obj.answer_text or "").strip()
        preview_text = str(directive_obj.preview_text or answer_text or "").strip()
        if getattr(directive_obj, "reason", "") and not metadata_obj.get("reason"):
            metadata_obj["reason"] = str(getattr(directive_obj, "reason", "") or "")
        error_envelope = getattr(directive_obj, "error_envelope", None)
        if error_envelope is not None and "error_envelope" not in metadata_obj:
            metadata_obj["error_envelope"] = (
                error_envelope.model_dump() if hasattr(error_envelope, "model_dump") else dict(getattr(error_envelope, "__dict__", {}) or {})
            )
        clarification_request = getattr(directive_obj, "clarification_request", None)
        if clarification_request is not None and "clarification_request" not in metadata_obj:
            metadata_obj["clarification_request"] = (
                clarification_request.model_dump() if hasattr(clarification_request, "model_dump") else dict(getattr(clarification_request, "__dict__", {}) or {})
            )
        return cls(
            answer_text=answer_text,
            answer_type=str(directive_obj.answer_type or ""),
            response_mode=str(directive_obj.response_mode or ""),
            trace_id=str(directive_obj.trace_id or ""),
            verifier_result=str(verifier_result or str((directive_obj.metadata or {}).get("verifier_result", "")) or ""),
            fallback_reason=str(fallback_reason or directive_obj.fallback_reason or ""),
            uncertainty_notices=list(uncertainty_notices or []),
            preview_text=preview_text,
            answer_source=str(directive_obj.answer_source or ""),
            metadata=metadata_obj,
            claims=list(claims or []),
            citations=list(citations or []),
            cards=list(cards or []),
            confidence_band=str(confidence_band or ""),
            response_policy=dict(response_policy or {}),
            clarification=dict(clarification or {}),
            safety_notice=[str(item).strip() for item in (safety_notice or []) if str(item).strip()],
            trace_summary=dict(trace_summary or {}),
            final_response=answer_text,
        )

    def to_v1(
        self,
        *,
        verifier_result: str = "",
        fallback_reason: str = "",
        uncertainty_notices: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ResponseContractV1:
        return ResponseContractV1.from_response_contract_v2(
            self,
            verifier_result=verifier_result,
            fallback_reason=fallback_reason,
            uncertainty_notices=uncertainty_notices,
            metadata=metadata,
        )
