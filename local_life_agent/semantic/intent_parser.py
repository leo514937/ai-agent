"""Top-level intent and semantic frame parsing."""

from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..config import LLM_TIMEOUT_MS, SEMANTIC_FALLBACK_ENABLED
from ..domain.enums import Facet, TaskType, TopIntent
from ..domain.schemas import SemanticFrame
from ..input.normalizer import normalize_text
from ..llm.client import call_llm, load_prompt
from ..llm.json_parser import LLMJSONParseError, parse_json_response
from .slot_extractor import extract_slots


class _TopIntentRouterResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    top_intent: TopIntent
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = Field(default="")


class FacetSpecResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Facet
    required: bool = False


class _SemanticFrameRouterResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    top_intent: TopIntent | None = None
    task_type: TaskType | None = None
    primary_task: str = ""
    facets: list[FacetSpecResponse] = Field(default_factory=list)
    merchant_mentions: list[str] = Field(default_factory=list)
    reference_mentions: list[str] = Field(default_factory=list)
    comparison_targets: list[dict[str, Any]] = Field(default_factory=list)
    ordinal_references: list[str] = Field(default_factory=list)
    deictic_references: list[str] = Field(default_factory=list)
    focused_facets: list[str] = Field(default_factory=list)
    comparison_focus: str = ""
    hard_constraints: dict[str, Any] = Field(default_factory=dict)
    soft_preferences: dict[str, Any] = Field(default_factory=dict)
    ranking_signals: dict[str, Any] = Field(default_factory=dict)
    follow_up: dict[str, Any] | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    need_context: bool = False


_SemanticFrameRouterResponse.model_rebuild()


class TopIntentRouter:
    """Small wrapper to keep the router easy to inject in tests."""

    def __init__(self, llm_call: Callable[..., dict[str, Any]] | None = None):
        self._llm_call = llm_call or call_llm

    def route(self, text: str) -> dict[str, Any]:
        return parse_top_intent(text, llm_call=self._llm_call)


def _validate_router_payload(payload: Any) -> dict[str, Any]:
    try:
        model = _TopIntentRouterResponse.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    return model.model_dump()


def _validate_semantic_payload(payload: Any) -> dict[str, Any]:
    try:
        model = _SemanticFrameRouterResponse.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    return model.model_dump()


def _fallback_intent(normalised_text: str, error_code: str = "") -> TopIntent:
    compact = normalised_text.strip()
    if not compact:
        return TopIntent.invalid
    if error_code:
        return TopIntent.out_of_scope
    if any(
        hint in compact
        for hint in (
            "瀵规瘮",
            "姣旇緝",
            "姣斾竴姣?",
            "姣斿憿",
            "杩欎笁瀹?",
            "杩欏嚑瀹?",
            "绗竴瀹?",
            "绗簩瀹?",
            "绗笁瀹?",
            "鍝釜鏇?",
            "鍝鏇?",
            "璋佹洿",
        )
    ):
        return TopIntent.local_life
    if any("\u4e00" <= ch <= "\u9fff" for ch in compact):
        return TopIntent.local_life
    return TopIntent.out_of_scope


def _annotate_frame(
    frame: SemanticFrame,
    *,
    semantic_source: str,
    llm_backend: str = "",
    fallback_reason: str = "",
    llm_called: bool,
) -> SemanticFrame:
    frame.semantic_source = semantic_source
    frame.llm_backend = llm_backend
    frame.fallback_reason = fallback_reason
    frame.llm_called = llm_called
    return frame


def _fallback_semantic_frame(
    text: str,
    top_intent: str,
    *,
    fallback_reason: str,
    llm_called: bool,
    llm_backend: str = "",
) -> SemanticFrame:
    frame = SemanticFrame.model_validate(extract_slots(text, top_intent))
    return _annotate_frame(
        frame,
        semantic_source="fallback_rules",
        llm_backend=llm_backend,
        fallback_reason=fallback_reason,
        llm_called=llm_called,
    )


def parse_top_intent(text: str, llm_call: Callable[..., dict[str, Any]] | None = None) -> dict[str, Any]:
    normalised_text = normalize_text(text)
    if not normalised_text.strip():
        return {
            "top_intent": TopIntent.invalid,
            "confidence": 0.0,
            "reason": "empty_input",
            "raw": "",
            "error_code": "EMPTY_INPUT",
            "error_message": "input is empty after normalisation",
        }

    prompt_template = load_prompt("top_intent_router")
    rendered_prompt = prompt_template.replace("{{TEXT}}", normalised_text)

    router = TopIntentRouter(llm_call=llm_call)
    result = router._llm_call(
        rendered_prompt,
        system_prompt="",
        timeout_ms=LLM_TIMEOUT_MS,
        temperature=0.0,
        max_retries=1,
        response_validator=_validate_router_payload,
    )

    if result.get("ok"):
        payload = result["content"] or {}
        if not isinstance(payload, dict):
            if isinstance(payload, str):
                try:
                    payload = parse_json_response(payload)
                except LLMJSONParseError:
                    payload = {}
            else:
                payload = {}
        top_intent = payload.get("top_intent", TopIntent.out_of_scope)
        if not isinstance(top_intent, TopIntent):
            try:
                top_intent = TopIntent(top_intent)
            except Exception:
                fallback = _fallback_intent(normalised_text, "LLM_ENUM_OUT_OF_RANGE")
                return {
                    "top_intent": fallback,
                    "confidence": 0.0,
                    "reason": "llm_failed",
                    "raw": result.get("raw", ""),
                    "error_code": "LLM_ENUM_OUT_OF_RANGE",
                    "error_message": "top_intent is outside the allowed enum range",
                }
        confidence = float(payload.get('confidence', result.get('confidence', 0.0)))
        confidence = max(0.0, min(1.0, confidence))
        return {
            "top_intent": top_intent,
            "confidence": confidence,
            "reason": payload.get("reason", ""),
            "raw": result.get("raw", ""),
            "error_code": "",
            "error_message": "",
        }

    fallback = _fallback_intent(normalised_text, result.get("error_code", ""))
    return {
        "top_intent": fallback,
        "confidence": 0.0,
        "reason": "llm_failed",
        "raw": result.get("raw", ""),
        "error_code": result.get("error_code", ""),
        "error_message": result.get("error_message", ""),
    }


def parse_semantic_frame(
    text: str,
    top_intent: str,
    llm_call: Callable[..., dict[str, Any]] | None = None,
    *,
    allow_fallback: bool = SEMANTIC_FALLBACK_ENABLED,
) -> dict[str, Any]:
    """Parse a semantic frame for the local-life flow."""
    normalised_text = normalize_text(text)
    if not normalised_text.strip():
        frame = _annotate_frame(
            SemanticFrame(),
            semantic_source="fallback_rules",
            llm_backend="",
            fallback_reason="empty_input",
            llm_called=False,
        )
        return {
            "semantic_frame": frame,
            "error_code": "EMPTY_INPUT",
            "error_message": "input is empty after normalisation",
            "raw": "",
            "semantic_source": frame.semantic_source,
            "llm_backend": frame.llm_backend,
            "fallback_reason": frame.fallback_reason,
            "llm_called": frame.llm_called,
        }

    if llm_call is None:
        if not allow_fallback:
            return {
                "semantic_frame": None,
                "error_code": "SEMANTIC_LLM_UNAVAILABLE",
                "error_message": "semantic llm backend is unavailable",
                "raw": "",
                "semantic_source": "",
                "llm_backend": "",
                "fallback_reason": "llm_call_unavailable",
                "llm_called": False,
            }
        fallback_frame = _fallback_semantic_frame(
            normalised_text,
            top_intent,
            fallback_reason="llm_call_unavailable",
            llm_called=False,
            llm_backend="",
        )
        return {
            "semantic_frame": fallback_frame,
            "error_code": "",
            "error_message": "",
            "raw": "",
            "semantic_source": fallback_frame.semantic_source,
            "llm_backend": fallback_frame.llm_backend,
            "fallback_reason": fallback_frame.fallback_reason,
            "llm_called": fallback_frame.llm_called,
        }

    prompt_template = load_prompt("local_life_parser")
    rendered_prompt = prompt_template.replace("{{TEXT}}", normalised_text).replace("{{TOP_INTENT}}", top_intent)
    result = llm_call(
        rendered_prompt,
        system_prompt="",
        timeout_ms=LLM_TIMEOUT_MS,
        temperature=0.0,
        max_retries=1,
        response_validator=_validate_semantic_payload,
    )

    if result.get("ok"):
        payload = result["content"] or {}
        if not isinstance(payload, dict):
            if isinstance(payload, str):
                try:
                    payload = parse_json_response(payload)
                except LLMJSONParseError:
                    payload = {}
            else:
                payload = {}
        if "top_intent" not in payload or payload.get("top_intent") is None:
            payload["top_intent"] = TopIntent(top_intent) if top_intent in {item.value for item in TopIntent} else TopIntent.out_of_scope
        llm_backend = str(result.get("llm_backend", "real_llm") or "real_llm")
        # Map backend kinds to semantic source taxonomy.
        #   rule_based → rule_based (pure offline rules, no LLM)
        #   fake_llm   → fake_llm   (test-injected fake)
        #   fake       → fake_llm   (legacy compat)
        #   real_llm   → real_llm   (real LLM provider)
        #   real       → real_llm   (legacy compat)
        #   other      → passthrough
        _source_map = {
            "rule_based": "rule_based",
            "fake_llm": "fake_llm",
            "fake": "fake_llm",
            "real_llm": "real_llm",
            "real": "real_llm",
        }
        semantic_source = _source_map.get(llm_backend, "real_llm")
        frame = _annotate_frame(
            SemanticFrame.model_validate(payload),
            semantic_source=semantic_source,
            llm_backend=llm_backend,
            fallback_reason="",
            llm_called=True,
        )
        if frame.top_intent is None and top_intent in {item.value for item in TopIntent}:
            frame.top_intent = TopIntent(top_intent)
        return {
            "semantic_frame": frame,
            "error_code": "",
            "error_message": "",
            "raw": result.get("raw", ""),
            "semantic_source": frame.semantic_source,
            "llm_backend": frame.llm_backend,
            "fallback_reason": frame.fallback_reason,
            "llm_called": frame.llm_called,
        }

    error_code = result.get("error_code", "") or "SEMANTIC_PARSE_FAILED"
    error_message = result.get("error_message", "") or "semantic parse failed"
    if not allow_fallback:
        return {
            "semantic_frame": None,
            "error_code": error_code,
            "error_message": error_message,
            "raw": result.get("raw", ""),
            "semantic_source": "",
            "llm_backend": str(result.get("llm_backend", "") or ""),
            "fallback_reason": error_code,
            "llm_called": True,
        }

    llm_backend = str(result.get("llm_backend", "real") or "real")
    fallback_frame = _fallback_semantic_frame(
        normalised_text,
        top_intent,
        fallback_reason=error_code,
        llm_called=True,
        llm_backend=llm_backend,
    )
    return {
        "semantic_frame": fallback_frame,
        "error_code": "",
        "error_message": "",
        "raw": result.get("raw", ""),
        "semantic_source": fallback_frame.semantic_source,
        "llm_backend": fallback_frame.llm_backend,
        "fallback_reason": fallback_frame.fallback_reason,
        "llm_called": fallback_frame.llm_called,
    }


