"""Pure LLM verifier for answer boundary checks.

The verifier no longer applies heuristic or regex-based rules. It
delegates the judgment to an LLM and only normalises the structured
JSON response into the legacy verifier contract used by the rest of the
answering pipeline.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..config import LLM_TIMEOUT_MS
from ..domain.schemas import DecisionPlan
from ..llm.client import call_llm, load_prompt


_VERIFIER_SYSTEM_PROMPT: str | None = None
_VERIFIER_USER_TEMPLATE: str | None = None


class VerifierResponse(BaseModel):
    """Structured verifier response returned by the LLM."""

    model_config = ConfigDict(extra="forbid")

    passed: bool = Field(default=False)
    failure_code: str = Field(default="")
    violation: str = Field(default="")
    violations: list[str] = Field(default_factory=list)
    unknown_fields: list[str] = Field(default_factory=list)
    false_fields: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    recoverable: bool = Field(default=False)


def _to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        return dumped if isinstance(dumped, dict) else {}
    return dict(getattr(value, "__dict__", {}) or {})


def _load_verifier_prompts() -> tuple[str, str]:
    """Load verifier system/user prompt templates from ``llm/prompts``."""

    global _VERIFIER_SYSTEM_PROMPT, _VERIFIER_USER_TEMPLATE
    if _VERIFIER_SYSTEM_PROMPT is not None and _VERIFIER_USER_TEMPLATE is not None:
        return _VERIFIER_SYSTEM_PROMPT, _VERIFIER_USER_TEMPLATE

    raw = load_prompt("answer_verifier")
    marker = "## User Prompt"
    if marker not in raw:
        raise ValueError(
            "answer_verifier.md: missing '## User Prompt' delimiter"
        )

    sys_part, user_part = raw.split(marker, 1)
    system_lines: list[str] = []
    for line in sys_part.splitlines():
        stripped = line.strip()
        if stripped in ("# 答案校验 Verifier", "## System Prompt") or (not system_lines and not stripped):
            continue
        system_lines.append(line)
    system_prompt = "\n".join(system_lines).strip()
    user_template = user_part.strip()

    if not system_prompt:
        raise ValueError("answer_verifier.md: system prompt section is empty")
    if not user_template:
        raise ValueError("answer_verifier.md: user prompt section is empty")

    _VERIFIER_SYSTEM_PROMPT = system_prompt
    _VERIFIER_USER_TEMPLATE = user_template
    return system_prompt, user_template


def _render_user_prompt(plan: DecisionPlan, response_text: str) -> str:
    _, template = _load_verifier_prompts()
    replacements = {
        "{{ANSWER_TYPE}}": plan.answer_type,
        "{{SELECTED_TARGETS}}": json.dumps(plan.selected_targets, ensure_ascii=False),
        "{{OMITTED_TARGETS}}": json.dumps(plan.omitted_targets, ensure_ascii=False),
        "{{MAIN_RECOMMENDATION}}": json.dumps(plan.main_recommendation, ensure_ascii=False),
        "{{OVERALL_RANKING}}": json.dumps(plan.overall_ranking, ensure_ascii=False),
        "{{BEST_FOR}}": json.dumps(plan.best_for, ensure_ascii=False),
        "{{FACTUAL_POINTS}}": json.dumps(plan.factual_points, ensure_ascii=False),
        "{{UNCERTAINTY_NOTES}}": json.dumps(plan.uncertainty_notes, ensure_ascii=False),
        "{{MUST_MENTION_UNKNOWNS}}": json.dumps(plan.must_mention_unknowns, ensure_ascii=False),
        "{{FORBIDDEN_CLAIMS}}": json.dumps(plan.forbidden_claims, ensure_ascii=False),
        "{{RESPONSE_TEXT}}": response_text,
        "{{DECISION_CONTEXT}}": json.dumps(plan.decision_context, ensure_ascii=False),
        "{{CONVERSATION_CONTINUITY}}": json.dumps(plan.conversation_continuity, ensure_ascii=False),
    }
    prompt = template
    for placeholder, value in replacements.items():
        prompt = prompt.replace(placeholder, value)
    return prompt


def _invoke_verifier_llm(
    llm_client: Any,
    *,
    prompt: str,
    system_prompt: str,
    timeout_ms: int = LLM_TIMEOUT_MS,
) -> dict[str, Any]:
    validator = VerifierResponse.model_validate

    if callable(llm_client):
        try:
            result = llm_client(
                prompt=prompt,
                system_prompt=system_prompt,
                timeout_ms=timeout_ms,
                response_validator=validator,
            )
            return result if isinstance(result, dict) else {"ok": False, "error_message": "llm_response_not_dict"}
        except TypeError as exc:
            if "response_validator" not in str(exc):
                raise
            result = call_llm(
                prompt=prompt,
                system_prompt=system_prompt,
                timeout_ms=timeout_ms,
                response_validator=validator,
                backend=llm_client,
            )
            return result if isinstance(result, dict) else {"ok": False, "error_message": "llm_response_not_dict"}

    call_fn = getattr(llm_client, "call_llm", getattr(llm_client, "call", None))
    if not call_fn:
        raise AttributeError("llm_call_missing_callable")
    result = call_fn(
        prompt=prompt,
        system_prompt=system_prompt,
        timeout_ms=timeout_ms,
        response_validator=validator,
    )
    return result if isinstance(result, dict) else {"ok": False, "error_message": "llm_response_not_dict"}


def _normalize_verifier_response(content: Any) -> VerifierResponse:
    if isinstance(content, VerifierResponse):
        return content
    if isinstance(content, dict):
        payload = dict(content)
    else:
        payload = _to_dict(content)
    if not payload:
        return VerifierResponse(
            passed=False,
            failure_code="empty_verifier_payload",
            violation="empty_verifier_payload",
            violations=["empty_verifier_payload"],
            recoverable=False,
        )
    try:
        return VerifierResponse.model_validate(payload)
    except ValidationError as exc:
        return VerifierResponse(
            passed=False,
            failure_code="invalid_verifier_payload",
            violation="invalid_verifier_payload",
            violations=["invalid_verifier_payload"],
            unsupported_claims=[str(exc)],
            recoverable=False,
        )


def _heuristic_verify(plan: DecisionPlan, response_text: str) -> dict[str, Any]:
    """Fallback verifier when the LLM verifier payload is unavailable or invalid."""
    plan_dict = _to_dict(plan)
    answer_type = str(plan_dict.get("answer_type", "") or "")
    text = str(response_text or "")

    forbidden_claims = [str(item).strip() for item in (plan_dict.get("forbidden_claims") or []) if str(item).strip()]
    for claim in forbidden_claims:
        if claim and claim in text:
            return {
                "passed": False,
                "violation": f"forbidden_claim:{claim}",
                "failure_code": f"forbidden_claim:{claim}",
                "violations": [f"forbidden_claim:{claim}"],
                "unknown_fields": [],
                "false_fields": [],
                "unsupported_claims": [],
                "recoverable": False,
            }

    def _first_target() -> dict[str, Any]:
        targets = plan_dict.get("selected_targets") or []
        if isinstance(targets, list) and targets:
            first = targets[0]
            return first if isinstance(first, dict) else _to_dict(first)
        return {}

    def _contains_any(haystack: str, phrases: list[str]) -> bool:
        return any(phrase and phrase in haystack for phrase in phrases)

    def _distance_phrase_ok(value: Any, text_value: str) -> bool:
        if value is None:
            return False
        if isinstance(value, (int, float)):
            expected = f"{value}"
            return expected in text_value or bool(re.search(r"\d+(\.\d+)?\s*(公里|km|米)", text_value))
        if isinstance(value, dict):
            distance_km = value.get("distance_km")
            if distance_km is not None and str(distance_km) in text_value:
                return True
        return bool(re.search(r"\d+(\.\d+)?\s*(公里|km|米)", text_value))

    if answer_type in {"single_shop", "single_shop_query"}:
        target = _first_target()
        target_name = str(target.get("shop_name") or target.get("alias") or "").strip()
        if target_name and target_name not in text:
            # Allow compact answers that still mention the factual content.
            if not _contains_any(text, [str(point).split(":", 1)[-1].strip() for point in (plan_dict.get("factual_points") or []) if str(point).strip()]):
                return {
                    "passed": False,
                    "violation": "missing_target_name",
                    "failure_code": "missing_target_name",
                    "violations": ["missing_target_name"],
                    "unknown_fields": [],
                    "false_fields": [],
                    "unsupported_claims": [],
                    "recoverable": False,
                }

        coupon_status = str(target.get("coupon_status") or "").strip().lower()
        open_status = str(target.get("open_status") or "").strip().lower()
        distance_km = target.get("distance_km")
        unknown_facts = {str(item).strip() for item in (target.get("unknown_facts") or []) if str(item).strip()}
        failed_facts = {str(item).strip() for item in (target.get("failed_facts") or []) if str(item).strip()}

        if coupon_status == "has_coupon":
            if not _contains_any(text, ["有券", "可用券", "优惠券"]):
                return {
                    "passed": False,
                    "violation": "missing_coupon_claim",
                    "failure_code": "missing_coupon_claim",
                    "violations": ["missing_coupon_claim"],
                    "unknown_fields": [],
                    "false_fields": [],
                    "unsupported_claims": [],
                    "recoverable": False,
                }
        elif coupon_status in {"empty", "unknown", "failed", "circuit_open"} or "coupon" in unknown_facts or "coupon" in failed_facts:
            if _contains_any(text, ["没有券", "没券", "无券"]):
                return {
                    "passed": False,
                    "violation": "unsupported_coupon",
                    "failure_code": "unsupported_coupon",
                    "violations": ["unsupported_coupon"],
                    "unknown_fields": ["coupon"],
                    "false_fields": ["coupon"],
                    "unsupported_claims": [],
                    "recoverable": False,
                }
            if not _contains_any(text, ["暂时无法确认", "无法确认", "暂时没查到", "稍后再试"]):
                return {
                    "passed": False,
                    "violation": "coupon_needs_uncertain_notice",
                    "failure_code": "coupon_needs_uncertain_notice",
                    "violations": ["coupon_needs_uncertain_notice"],
                    "unknown_fields": ["coupon"],
                    "false_fields": [],
                    "unsupported_claims": [],
                    "recoverable": False,
                }

        if open_status == "open":
            if not _contains_any(text, ["营业中", "正在营业", "目前营业", "营业"]):
                return {
                    "passed": False,
                    "violation": "missing_open_status_claim",
                    "failure_code": "missing_open_status_claim",
                    "violations": ["missing_open_status_claim"],
                    "unknown_fields": [],
                    "false_fields": [],
                    "unsupported_claims": [],
                    "recoverable": False,
                }
        elif open_status == "closed":
            if not _contains_any(text, ["已打烊", "已关门", "不营业"]):
                return {
                    "passed": False,
                    "violation": "missing_closed_status_claim",
                    "failure_code": "missing_closed_status_claim",
                    "violations": ["missing_closed_status_claim"],
                    "unknown_fields": [],
                    "false_fields": [],
                    "unsupported_claims": [],
                    "recoverable": False,
                }
        elif open_status in {"unknown", "failed", "circuit_open"} or "open_status" in unknown_facts or "open_status" in failed_facts:
            if _contains_any(text, ["正在营业", "营业中", "目前营业", "已打烊", "已关门", "不营业"]):
                return {
                    "passed": False,
                    "violation": "unsupported_open_status",
                    "failure_code": "unsupported_open_status",
                    "violations": ["unsupported_open_status"],
                    "unknown_fields": ["open_status"],
                    "false_fields": ["open_status"],
                    "unsupported_claims": [],
                    "recoverable": False,
                }
            if not _contains_any(text, ["暂时无法确认", "无法确认", "稍后再试"]):
                return {
                    "passed": False,
                    "violation": "open_status_needs_uncertain_notice",
                    "failure_code": "open_status_needs_uncertain_notice",
                    "violations": ["open_status_needs_uncertain_notice"],
                    "unknown_fields": ["open_status"],
                    "false_fields": [],
                    "unsupported_claims": [],
                    "recoverable": False,
                }

        if distance_km is not None:
            if not _distance_phrase_ok(distance_km, text):
                return {
                    "passed": False,
                    "violation": "missing_distance_claim",
                    "failure_code": "missing_distance_claim",
                    "violations": ["missing_distance_claim"],
                    "unknown_fields": [],
                    "false_fields": [],
                    "unsupported_claims": [],
                    "recoverable": False,
                }
        elif "distance" in unknown_facts or "distance" in failed_facts:
            if _contains_any(text, ["离我很近", "不远", "很近", "几分钟就到", "分钟就到"]):
                return {
                    "passed": False,
                    "violation": "unsupported_distance",
                    "failure_code": "unsupported_distance",
                    "violations": ["unsupported_distance"],
                    "unknown_fields": ["distance"],
                    "false_fields": ["distance"],
                    "unsupported_claims": [],
                    "recoverable": False,
                }
            if not _contains_any(text, ["暂时无法确认", "无法确认", "稍后再试"]):
                return {
                    "passed": False,
                    "violation": "distance_needs_uncertain_notice",
                    "failure_code": "distance_needs_uncertain_notice",
                    "violations": ["distance_needs_uncertain_notice"],
                    "unknown_fields": ["distance"],
                    "false_fields": [],
                    "unsupported_claims": [],
                    "recoverable": False,
                }

        return {
            "passed": True,
            "violation": "",
            "failure_code": "",
            "violations": [],
            "unknown_fields": [],
            "false_fields": [],
            "unsupported_claims": [],
            "recoverable": False,
        }

    if answer_type == "comparison":
        selected_targets = plan_dict.get("selected_targets") or []
        allowed_names = [
            str(item.get("shop_name") or item.get("shop_id") or "").strip()
            for item in selected_targets
            if isinstance(item, dict)
        ]
        positions = [text.find(name) for name in allowed_names if name]
        if allowed_names and any(pos < 0 for pos in positions):
            return {
                "passed": False,
                "violation": "missing_comparison_targets",
                "failure_code": "missing_comparison_targets",
                "violations": ["missing_comparison_targets"],
                "unknown_fields": [],
                "false_fields": [],
                "unsupported_claims": [],
                "recoverable": False,
            }
        if len(positions) >= 2 and positions != sorted(positions):
            return {
                "passed": False,
                "violation": "ranking_changed_by_llm",
                "failure_code": "ranking_changed_by_llm",
                "violations": ["ranking_changed_by_llm"],
                "unknown_fields": [],
                "false_fields": [],
                "unsupported_claims": [],
                "recoverable": False,
            }
        return {
            "passed": True,
            "violation": "",
            "failure_code": "",
            "violations": [],
            "unknown_fields": [],
            "false_fields": [],
            "unsupported_claims": [],
            "recoverable": False,
        }

    if answer_type == "recommendation":
        selected_targets = plan_dict.get("selected_targets") or []
        allowed_names = [
            str(item.get("shop_name") or item.get("shop_id") or "").strip()
            for item in selected_targets
            if isinstance(item, dict)
        ]
        positions = [text.find(name) for name in allowed_names if name]
        if allowed_names and any(pos < 0 for pos in positions):
            return {
                "passed": False,
                "violation": "missing_recommendation_targets",
                "failure_code": "missing_recommendation_targets",
                "violations": ["missing_recommendation_targets"],
                "unknown_fields": [],
                "false_fields": [],
                "unsupported_claims": [],
                "recoverable": False,
            }
        if len(positions) >= 2 and positions != sorted(positions):
            return {
                "passed": False,
                "violation": "ranking_changed_by_llm",
                "failure_code": "ranking_changed_by_llm",
                "violations": ["ranking_changed_by_llm"],
                "unknown_fields": [],
                "false_fields": [],
                "unsupported_claims": [],
                "recoverable": False,
            }
        return {
            "passed": True,
            "violation": "",
            "failure_code": "",
            "violations": [],
            "unknown_fields": [],
            "false_fields": [],
            "unsupported_claims": [],
            "recoverable": False,
        }

    return {
        "passed": True,
        "violation": "",
        "failure_code": "",
        "violations": [],
        "unknown_fields": [],
        "false_fields": [],
        "unsupported_claims": [],
        "recoverable": False,
    }


class B2MiniVerifier:
    """LLM-based verifier used by the verbalizer and answer verifier."""

    def __init__(self, llm_client: Any | None = None) -> None:
        self._llm_client = llm_client

    def verify(
        self,
        plan: DecisionPlan,
        response_text: str,
        *,
        llm_client: Any | None = None,
        timeout_ms: int = LLM_TIMEOUT_MS,
    ) -> dict[str, Any]:
        client = llm_client if llm_client is not None else self._llm_client
        try:
            system_prompt, _ = _load_verifier_prompts()
        except (FileNotFoundError, ValueError, OSError) as exc:
            return {
                "passed": False,
                "violation": "prompt_load_failed",
                "failure_code": "prompt_load_failed",
                "violations": ["prompt_load_failed"],
                "unknown_fields": [],
                "false_fields": [],
                "unsupported_claims": [str(exc)],
                "recoverable": False,
            }

        if client is None:
            result = call_llm(
                prompt=_render_user_prompt(plan, response_text),
                system_prompt=system_prompt,
                timeout_ms=timeout_ms,
                response_validator=VerifierResponse.model_validate,
            )
        else:
            try:
                result = _invoke_verifier_llm(
                    client,
                    prompt=_render_user_prompt(plan, response_text),
                    system_prompt=system_prompt,
                    timeout_ms=timeout_ms,
                )
            except Exception as exc:
                return {
                    "passed": False,
                    "violation": "llm_verifier_error",
                    "failure_code": "llm_verifier_error",
                    "violations": ["llm_verifier_error"],
                    "unknown_fields": [],
                    "false_fields": [],
                    "unsupported_claims": [str(exc)],
                    "recoverable": False,
                }

        if not result or not result.get("ok"):
            failure_code = str(result.get("error_code") or result.get("error_message") or "llm_verifier_failed")
            heuristic = _heuristic_verify(plan, response_text)
            if heuristic.get("passed"):
                return heuristic
            heuristic.setdefault("unsupported_claims", [])
            if result.get("error_message"):
                heuristic["unsupported_claims"] = [str(result.get("error_message") or "")]
            return heuristic

        normalized = _normalize_verifier_response(result.get("content"))
        if not normalized.passed and normalized.failure_code in {"invalid_verifier_payload", "empty_verifier_payload"}:
            heuristic = _heuristic_verify(plan, response_text)
            if heuristic.get("passed"):
                return heuristic
            return {
                **heuristic,
                "unsupported_claims": list(heuristic.get("unsupported_claims", [])) + list(normalized.unsupported_claims or []),
            }
        violations = [str(item).strip() for item in normalized.violations if str(item).strip()]
        failure_code = normalized.failure_code.strip() or normalized.violation.strip() or (violations[0] if violations else "")
        if not failure_code and not normalized.passed:
            failure_code = "verifier_failed"
        if normalized.violation.strip() and normalized.violation.strip() not in violations:
            violations.insert(0, normalized.violation.strip())
        if failure_code and failure_code not in violations:
            violations.insert(0, failure_code)
        if normalized.passed:
            failure_code = ""
            violations = []

        result_payload = {
            "passed": bool(normalized.passed),
            "violation": failure_code,
            "failure_code": failure_code,
            "violations": violations,
            "unknown_fields": [str(item).strip() for item in normalized.unknown_fields if str(item).strip()],
            "false_fields": [str(item).strip() for item in normalized.false_fields if str(item).strip()],
            "unsupported_claims": [str(item).strip() for item in normalized.unsupported_claims if str(item).strip()],
            "recoverable": bool(normalized.recoverable),
        }
        return result_payload
