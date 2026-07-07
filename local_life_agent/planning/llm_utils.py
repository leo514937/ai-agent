"""Shared helpers for structured LLM planning/review nodes."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from ..config import LLM_TIMEOUT_MS
from ..llm.client import call_llm, load_prompt
from ..llm.json_parser import LLMJSONParseError, parse_json_response
from ..observability.file_logger import get_python_service_logger, log_kv

_PLAN_LOG = get_python_service_logger()


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else ""


def load_two_part_prompt(name: str) -> tuple[str, str]:
    """Load a markdown prompt split into system/user sections."""
    raw = load_prompt(name)
    marker = "## User Prompt"
    if marker not in raw:
        raise ValueError(f"{name}.md: missing '## User Prompt' delimiter")
    sys_part, user_part = raw.split(marker, 1)
    system_lines: list[str] = []
    for line in sys_part.splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") or stripped == "## System Prompt" or (not system_lines and not stripped):
            continue
        system_lines.append(line)
    system_prompt = "\n".join(system_lines).strip()
    user_prompt = user_part.strip()
    if not system_prompt:
        raise ValueError(f"{name}.md: system prompt section is empty")
    if not user_prompt:
        raise ValueError(f"{name}.md: user prompt section is empty")
    return system_prompt, user_prompt


def render_prompt(template: str, replacements: dict[str, Any]) -> str:
    rendered = template
    for key, value in replacements.items():
        if isinstance(value, str):
            rendered = rendered.replace(key, value)
        else:
            rendered = rendered.replace(key, json.dumps(value, ensure_ascii=False, default=str))
    return rendered


def normalize_structured_content(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return dict(content)
    if isinstance(content, BaseModel):
        return content.model_dump()
    if isinstance(content, str):
        try:
            parsed = parse_json_response(content)
            return parsed if isinstance(parsed, dict) else {}
        except LLMJSONParseError:
            return {}
    return {}


def invoke_structured_llm(
    *,
    prompt_name: str,
    replacements: dict[str, Any],
    response_validator: Callable[[Any], Any],
    llm_call: Callable[..., dict[str, Any]] | None = None,
    timeout_ms: int = LLM_TIMEOUT_MS,
    max_retries: int = 0,
) -> dict[str, Any]:
    """Invoke an LLM and require a structured validated payload."""
    system_prompt, user_template = load_two_part_prompt(prompt_name)
    user_prompt = render_prompt(user_template, replacements)
    call = llm_call or call_llm

    validator_name = getattr(response_validator, "__name__", type(response_validator).__name__)
    log_kv(
        _PLAN_LOG,
        logging.INFO,
        "[PLAN_LLM_INVOKE]",
        tone="llm",
        prompt_name=prompt_name,
        validator=validator_name,
        timeout_ms=timeout_ms,
        max_retries=max_retries,
        replacement_keys=list(replacements.keys()),
        user_prompt_hash=_hash_text(user_prompt),
        system_prompt_hash=_hash_text(system_prompt),
    )

    result = call(
        user_prompt,
        system_prompt=system_prompt,
        timeout_ms=timeout_ms,
        temperature=0.0,
        max_retries=max_retries,
        response_validator=response_validator,
    )

    payload = normalize_structured_content(result.get("content"))
    ok = bool(result.get("ok", False))
    log_kv(
        _PLAN_LOG,
        logging.INFO,
        "[PLAN_LLM_RESULT]",
        tone="llm" if ok else "warn",
        prompt_name=prompt_name,
        ok=ok,
        error_code=result.get("error_code", ""),
        llm_backend=result.get("llm_backend", ""),
        payload_preview=payload,
        raw_preview=result.get("raw", ""),
        raw_len=len(str(result.get("raw", ""))),
    )

    return {
        "ok": ok,
        "payload": payload,
        "error_code": str(result.get("error_code", "") or ""),
        "error_message": str(result.get("error_message", "") or ""),
        "llm_backend": str(result.get("llm_backend", "") or ""),
        "raw": str(result.get("raw", "") or ""),
    }


def model_validate_or_error(model_cls: type[BaseModel], payload: Any) -> tuple[BaseModel | None, str]:
    try:
        model = model_cls.model_validate(payload)
    except ValidationError as exc:
        return None, str(exc)
    return model, ""
