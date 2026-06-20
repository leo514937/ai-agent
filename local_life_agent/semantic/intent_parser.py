"""Top-level intent and semantic frame parsing."""

from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..config import LLM_TIMEOUT_MS
from ..domain.enums import Facet, TaskType, TopIntent
from ..domain.schemas import FacetSpec, SemanticFrame
from ..input.normalizer import normalize_text
from ..llm.client import call_llm, load_prompt
from ..llm.json_parser import LLMJSONParseError, parse_json_response
from .slot_extractor import extract_slots


class _TopIntentRouterResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    top_intent: TopIntent
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = Field(default="")


class _SemanticFrameRouterResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    top_intent: TopIntent | None = None
    task_type: TaskType | None = None
    primary_task: str = ""
    facets: list["FacetSpecResponse"] = Field(default_factory=list)
    merchant_mentions: list[str] = Field(default_factory=list)
    reference_mentions: list[str] = Field(default_factory=list)
    hard_constraints: dict[str, Any] = Field(default_factory=dict)
    soft_preferences: dict[str, Any] = Field(default_factory=dict)
    ranking_signals: dict[str, Any] = Field(default_factory=dict)
    follow_up: dict[str, Any] | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    need_context: bool = False


class FacetSpecResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Facet
    required: bool = False


_SemanticFrameRouterResponse.model_rebuild()


class TopIntentRouter:
    """Small wrapper to keep the router easy to inject in tests."""

    def __init__(self, llm_call: Callable[..., dict[str, Any]] | None = None):
        self._llm_call = llm_call or call_llm

    def route(self, text: str) -> dict[str, Any]:
        return parse_top_intent(text, llm_call=self._llm_call)


def _validate_router_payload(payload: Any) -> dict[str, Any]:
    """Validate the structured LLM payload against the strict schema."""
    try:
        model = _TopIntentRouterResponse.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    return model.model_dump()


def _validate_semantic_payload(payload: Any) -> dict[str, Any]:
    """Validate the structured semantic payload against the strict schema."""
    try:
        model = _SemanticFrameRouterResponse.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    return model.model_dump()


def _fallback_intent(normalised_text: str, error_code: str = "") -> TopIntent:
    """Use a deterministic fallback when the LLM path fails."""
    compact = normalised_text.strip()
    if not compact:
        return TopIntent.invalid
    if error_code in {"LLM_JSON_PARSE_ERROR", "LLM_ENUM_OUT_OF_RANGE"}:
        return TopIntent.out_of_scope
    return TopIntent.local_life


def _fallback_semantic_frame(text: str, top_intent: str) -> SemanticFrame:
    """Use the conservative rule fallback when the semantic LLM path fails."""
    fallback_slots = extract_slots(text, top_intent)
    frame = SemanticFrame.model_validate(fallback_slots)
    return frame


def _frame_payload(frame: SemanticFrame) -> dict[str, Any]:
    return frame.model_dump()


def parse_top_intent(text: str, llm_call: Callable[..., dict[str, Any]] | None = None) -> dict[str, Any]:
    """Classify the top-level intent of the user input.

    The function returns a dict with at least ``top_intent`` (a
    :class:`TopIntent`) and ``confidence``.
    """
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
        confidence = float(payload.get("confidence", result.get("confidence", 0.0)))
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
) -> dict[str, Any]:
    """Parse a semantic frame for the local-life flow.

    The preferred path is an LLM-backed structured response. If that
    fails, we fall back to the conservative rule-based extractor.
    """
    normalised_text = normalize_text(text)
    if not normalised_text.strip():
        return {
            "semantic_frame": SemanticFrame(),
            "error_code": "EMPTY_INPUT",
            "error_message": "input is empty after normalisation",
            "raw": "",
        }

    if llm_call is None:
        fallback_frame = _fallback_semantic_frame(normalised_text, top_intent)
        return {
            "semantic_frame": fallback_frame,
            "error_code": "",
            "error_message": "",
            "raw": "",
        }

    prompt_template = load_prompt("local_life_parser")
    rendered_prompt = (
        prompt_template.replace("{{TEXT}}", normalised_text).replace("{{TOP_INTENT}}", top_intent)
    )
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
            payload["top_intent"] = TopIntent(top_intent) if top_intent in {t.value for t in TopIntent} else TopIntent.out_of_scope
        frame = SemanticFrame.model_validate(payload)
        # Keep the frame conservative even if the LLM omits a few easy
        # fields.  This is a fallback-normalisation step, not a second
        # parser path.
        if frame.top_intent is None and top_intent in {t.value for t in TopIntent}:
            frame.top_intent = TopIntent(top_intent)
        if frame.task_type is None:
            fallback_frame = _fallback_semantic_frame(normalised_text, top_intent)
            if fallback_frame.task_type is not None:
                frame.task_type = fallback_frame.task_type
            if not frame.merchant_mentions:
                frame.merchant_mentions = fallback_frame.merchant_mentions
            if not frame.facets:
                frame.facets = fallback_frame.facets
            if not frame.primary_task:
                frame.primary_task = fallback_frame.primary_task
            frame.need_context = frame.need_context or fallback_frame.need_context
        else:
            fallback_frame = _fallback_semantic_frame(normalised_text, top_intent)
            if fallback_frame.task_type == TaskType.comparison and frame.task_type != TaskType.comparison:
                frame.task_type = TaskType.comparison
                frame.primary_task = "comparison"
                if not frame.merchant_mentions:
                    frame.merchant_mentions = fallback_frame.merchant_mentions
                if not frame.reference_mentions:
                    frame.reference_mentions = fallback_frame.reference_mentions
                frame.need_context = frame.need_context or fallback_frame.need_context
        if not frame.facets and frame.task_type in {TaskType.single_shop_query, TaskType.coupon_query}:
            return {
                "semantic_frame": frame,
                "error_code": "MISSING_FACET",
                "error_message": "请补充你要查询的优惠、营业状态或距离。",
                "raw": result.get("raw", ""),
            }
        if not frame.merchant_mentions and frame.need_context:
            return {
                "semantic_frame": frame,
                "error_code": "",
                "error_message": "",
                "raw": result.get("raw", ""),
            }
        return {
            "semantic_frame": frame,
            "error_code": "",
            "error_message": "",
            "raw": result.get("raw", ""),
        }

    fallback_frame = _fallback_semantic_frame(normalised_text, top_intent)
    error_code = result.get("error_code", "") or "SEMANTIC_PARSE_FAILED"
    error_message = result.get("error_message", "") or "请补充你要查询的店名和优惠券需求。"
    return {
        "semantic_frame": fallback_frame,
        "error_code": error_code,
        "error_message": error_message,
        "raw": result.get("raw", ""),
    }
