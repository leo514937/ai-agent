"""LLM client abstraction layer.

The client is the single entry point for model calls. It handles
timeouts, retries, JSON extraction, enum validation hooks, and fake
backend injection for tests.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field, ValidationError

from ..config import LLM_TIMEOUT_MS
from ..input.normalizer import normalize_text
from ..observability.file_logger import get_python_service_logger, log_kv
from ..streaming.runtime import TurnCancelledError, raise_if_turn_cancelled
from .json_parser import LLMJSONParseError, parse_json_response

_LLM_LOGGER = get_python_service_logger()


class LLMTimeoutError(RuntimeError):
    """Raised when a backend call exceeds the configured timeout."""


class LLMEnumOutOfRange(RuntimeError):
    """Raised when a structured response contains an invalid enum value."""


class LLMBackendError(RuntimeError):
    """Raised when the backend itself crashes."""


LLMBackend = Callable[..., Any]

_LLM_BACKEND: LLMBackend | None = None
_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="llm-client")


def _invalidate_graph_cache() -> None:
    """Drop the cached graph so backend changes take effect on next turn."""
    try:
        from .. import agent as _agent
        _agent._GRAPH_CACHE = None
    except Exception:
        pass


class _TopIntentProbe(BaseModel):
    top_intent: str = Field(...)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = Field(default="")


def set_llm_backend(backend: LLMBackend | None) -> None:
    """Register a fake/mock backend for tests."""
    global _LLM_BACKEND
    _LLM_BACKEND = backend
    _invalidate_graph_cache()


def clear_llm_backend() -> None:
    """Clear the injected backend."""
    set_llm_backend(None)


def ensure_real_llm_backend() -> bool:
    """Ensure the runtime backend is wired for real LLM calls.

    Returns True when a backend is available after the call.
    This is a narrow runtime repair hook for cases where import/order
    or eval wiring left the backend unset even though real LLM config
    and credentials are present.
    """
    global _LLM_BACKEND
    if _LLM_BACKEND is not None:
        return True
    if config.LLM_ENABLED and config.LLM_BACKEND == "real_llm" and config.load_llm_api_key():
        from .openai_backend import OpenAICompatibleBackend

        _LLM_BACKEND = OpenAICompatibleBackend()
        return True
    return False


def get_llm_backend_snapshot() -> dict[str, Any]:
    """Return a lightweight snapshot of the currently active backend."""
    backend = _LLM_BACKEND
    if backend is None:
        return {
            "available": False,
            "backend": "",
            "provider": "",
            "model": "",
        }
    return {
        "available": True,
        "backend": str(
            getattr(backend, "llm_backend", None)
            or getattr(backend, "backend_kind", None)
            or "real_llm"
        ),
        "provider": str(getattr(backend, "provider", "") or ""),
        "model": str(getattr(backend, "model", "") or ""),
    }


def has_llm_backend() -> bool:
    """Return whether a custom backend is currently injected."""
    return _LLM_BACKEND is not None


@lru_cache(maxsize=16)
def load_prompt(name: str) -> str:
    """Load a prompt template from ``llm/prompts``."""
    prompt_path = Path(__file__).resolve().parent / "prompts" / f"{name}.md"
    return prompt_path.read_text(encoding="utf-8")


def _strip_noise(text: str) -> str:
    return re.sub(r"[\s\.,，。！？!?；;:：、~`'\"\-_=+\(\)\[\]{}<>/\\|…·]+", "", text)


def _matches_any(patterns: tuple[str, ...], text: str) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _classify_top_intent(text: str) -> tuple[str, float, str]:
    """Rule-based fallback used when no real backend is installed."""
    normalised = normalize_text(text)
    stripped = normalised.strip()
    compact = _strip_noise(stripped)

    if not stripped:
        return "invalid", 0.0, "empty_input"

    business_patterns = (
        r"附近",
        r"推荐",
        r"周边",
        r"对比",
        r"比较",
        r"比一比",
        r"哪个更",
        r"哪家更",
        r"这三家",
        r"这几家",
        r"第一家",
        r"第二家",
        r"第三家",
        r"这家",
        r"商场",
        r"火锅",
        r"餐厅",
        r"饭店",
        r"店铺",
        r"门店",
        r"优惠",
        r"券",
        r"折扣",
        r"营业",
        r"开门",
        r"距离",
        r"几公里",
        r"评分",
        r"人均",
        r"排队",
        r"订座",
        r"咖啡",
        r"奶茶",
        r"烧烤",
        r"烤肉",
        r"海底捞",
        r"麦当劳",
        r"肯德基",
        r"星巴克",
        r"瑞幸",
        r"喜茶",
        r"蜜雪冰城",
        r"霸王茶姬",
        r"茶百道",
    )
    greeting_patterns = (
        r"^(你好|您好|hello|hi|嗨|哈喽|在吗|在不在)$",
        r"^(早上好|下午好|晚上好)$",
    )
    capability_patterns = (
        r"^(你有什么作用|你能做什么|你可以做什么|你是谁|你是做什么的|你能干嘛|你的功能|你有什么功能)$",
    )
    unsafe_patterns = (
        r"绕过",
        r"黑客",
        r"攻击",
        r"炸弹",
        r"毒品",
        r"诈骗",
        r"违法",
        r"枪",
        r"爆炸",
    )
    out_of_scope_patterns = (
        r"天气",
        r"汇率",
        r"股价",
        r"新闻",
        r"数学",
        r"编程",
        r"历史",
    )

    if _matches_any(business_patterns, stripped):
        return "local_life", 0.97, "contains_business_intent"
    if _matches_any(greeting_patterns, compact):
        return "chat", 0.92, "pure_greeting"
    if _matches_any(capability_patterns, compact):
        return "capability", 0.91, "pure_capability_question"
    if _matches_any(unsafe_patterns, stripped):
        return "unsafe", 0.99, "unsafe_request"
    if _matches_any(out_of_scope_patterns, stripped):
        return "out_of_scope", 0.89, "not_local_life"
    if len(compact) <= 2:
        return "invalid", 0.6, "too_short_or_noise"
    return "out_of_scope", 0.78, "not_local_life"


def _extract_user_text(prompt: str, system_prompt: str) -> str:
    """Best-effort extraction of the user text embedded in a prompt."""
    haystacks = (prompt, system_prompt)
    markers = (
        "User text:",
        "User text：",
        "用户输入:",
        "用户输入：",
        "Input:",
        "Input：",
        "文本:",
        "文本：",
        "TEXT:",
        "TEXT：",
    )
    for haystack in haystacks:
        for marker in markers:
            idx = haystack.lower().find(marker.lower())
            if idx == -1:
                continue
            tail = haystack[idx + len(marker):].strip()
            if tail:
                return tail
    return prompt


def _default_llm_backend(
    prompt: str,
    system_prompt: str = "",
    temperature: float = 0.0,
    timeout_ms: int = LLM_TIMEOUT_MS,
) -> str:
    """Default fallback when no backend has been configured.

    The runtime must not silently degrade to rule-based semantic
    interpretation.  Returning a backend error here forces the caller
    to surface the missing configuration instead of fabricating a
    successful semantic result.
    """
    raise LLMBackendError("LLM_BACKEND_UNAVAILABLE")


def _invoke_backend(
    backend: LLMBackend,
    *,
    prompt: str,
    system_prompt: str,
    temperature: float,
    timeout_ms: int,
) -> Any:
    """Invoke *backend* inside a worker thread to enforce timeout."""
    raise_if_turn_cancelled()

    def _call() -> Any:
        raise_if_turn_cancelled()
        result = backend(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            timeout_ms=timeout_ms,
        )
        if inspect.isawaitable(result):
            result = asyncio.run(result)
        return result

    future = _EXECUTOR.submit(_call)
    try:
        return future.result(timeout=max(timeout_ms, 1) / 1000.0)
    except FuturesTimeoutError as exc:
        future.cancel()
        raise LLMTimeoutError(f"LLM call exceeded {timeout_ms} ms") from exc
    except Exception as exc:  # pragma: no cover - safety net
        raise LLMBackendError(str(exc)) from exc


def _normalise_backend_result(raw_result: Any) -> tuple[str, dict[str, Any] | None, float]:
    """Convert backend output into a raw text payload plus optional dict."""
    if isinstance(raw_result, dict):
        if "content" in raw_result:
            content = raw_result["content"]
            if isinstance(content, dict):
                raw_text = raw_result.get("raw")
                if not isinstance(raw_text, str) or not raw_text.strip():
                    raw_text = json.dumps(content, ensure_ascii=False, default=str)
                confidence = float(raw_result.get("confidence", content.get("confidence", 0.0) if isinstance(content, dict) else 0.0))
                return raw_text, content if isinstance(content, dict) else None, confidence
            if isinstance(content, str):
                raw_text = raw_result.get("raw") or content
                confidence = float(raw_result.get("confidence", 0.0))
                return raw_text, None, confidence
        raw_text = json.dumps(raw_result, ensure_ascii=False, default=str)
        confidence = float(raw_result.get("confidence", 0.0))
        return raw_text, raw_result, confidence

    if isinstance(raw_result, str):
        return raw_result, None, 0.0

    if raw_result is None:
        return "", None, 0.0

    raw_text = str(raw_result)
    return raw_text, None, 0.0


def _validate_output_schema(
    content: Any,
    *,
    response_validator: Callable[[Any], Any] | None,
) -> Any:
    if response_validator is None:
        return content
    try:
        validated = response_validator(content)
    except ValidationError as exc:
        raise LLMEnumOutOfRange(str(exc)) from exc
    except ValueError as exc:
        raise LLMEnumOutOfRange(str(exc)) from exc
    if validated is False:
        raise LLMEnumOutOfRange("response_validator rejected the payload")
    return content if validated is None else validated


def _prompt_tag(prompt: str) -> str:
    """Extract a short 30-char tag from the first non-empty line."""
    for line in prompt.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line[:60]
    return prompt[:60]


def call_llm(
    prompt: str,
    system_prompt: str = "",
    timeout_ms: int = LLM_TIMEOUT_MS,
    *,
    temperature: float = 0.0,
    max_retries: int = 1,
    response_validator: Callable[[Any], Any] | None = None,
    backend: LLMBackend | None = None,
) -> dict[str, Any]:
    """Send a prompt to the LLM and return a structured result.

    The function never raises on backend / parsing failures. Instead it
    returns ``ok=False`` with an ``error_code`` so the business layer can
    degrade gracefully.
    """
    _start_ts = time.monotonic()
    prompt_tag = _prompt_tag(prompt)
    system_tag = _prompt_tag(system_prompt) if system_prompt else "(none)"

    effective_backend = backend or _LLM_BACKEND or _default_llm_backend
    if effective_backend is _default_llm_backend:
        backend_kind = "rule_based"
    else:
        backend_kind = str(
            getattr(effective_backend, "llm_backend", None)
            or getattr(effective_backend, "backend_kind", None)
            or "real_llm"
        )
    if response_validator is not None:
        vname = getattr(response_validator, "__name__", type(response_validator).__name__)
    else:
        vname = "none"

    log_kv(
        _LLM_LOGGER,
        logging.INFO,
        "[LLM_CALL]",
        tone="llm",
        backend=backend_kind,
        temperature=temperature,
        timeout_ms=timeout_ms,
        retries=max_retries,
        prompt_tag=prompt_tag,
        system_tag=system_tag,
        prompt_len=len(prompt),
        system_len=len(system_prompt),
        validator=vname,
    )
    log_kv(
        _LLM_LOGGER,
        logging.DEBUG,
        "[LLM_CALL_RAW]",
        tone="llm",
        backend=backend_kind,
        prompt_preview=prompt,
        system_preview=system_prompt,
    )

    attempts = max(1, int(max_retries) + 1)
    last_error_code = ""
    last_error_message = ""
    last_raw = ""
    last_provider = ""
    last_model = ""
    last_transport = ""

    for attempt in range(1, attempts + 1):
        attempt_start = time.monotonic()
        try:
            raw_result = _invoke_backend(
                effective_backend,
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                timeout_ms=timeout_ms,
            )
            backend_elapsed = (time.monotonic() - attempt_start) * 1000.0
            raw_text, parsed_dict, confidence = _normalise_backend_result(raw_result)
            last_raw = raw_text
            if isinstance(raw_result, dict):
                last_provider = str(raw_result.get("provider", last_provider) or last_provider)
                last_model = str(raw_result.get("model", last_model) or last_model)
                last_transport = str(raw_result.get("transport", last_transport) or last_transport)

            if parsed_dict is not None:
                parsed = parsed_dict
            else:
                parsed = parse_json_response(raw_text)

            parsed = _validate_output_schema(parsed, response_validator=response_validator)
            if isinstance(parsed, dict):
                confidence = float(parsed.get("confidence", confidence))

            _total_elapsed = (time.monotonic() - _start_ts) * 1000.0
            log_kv(
                _LLM_LOGGER,
                logging.INFO,
                "[LLM_RESULT]",
                tone="llm",
                ok=True,
                backend=backend_kind,
                provider=last_provider,
                model=last_model,
                attempt=f"{attempt}/{attempts}",
                backend_ms=int(backend_elapsed),
                total_ms=int(_total_elapsed),
                confidence=round(confidence, 4),
                validator=vname,
                raw_len=len(last_raw),
            )
            log_kv(
                _LLM_LOGGER,
                logging.DEBUG,
                "[LLM_RESULT_RAW]",
                tone="llm",
                ok=True,
                content_preview=parsed,
                raw_preview=last_raw,
            )

            return {
                "ok": True,
                "content": parsed,
                "confidence": confidence,
                "raw": raw_text,
                "error_code": "",
                "error_message": "",
                "llm_backend": backend_kind,
                "provider": last_provider,
                "model": last_model,
                "transport": last_transport,
                "attempts": attempt,
                "temperature": temperature,
                "timeout_ms": timeout_ms,
            }
        except TurnCancelledError:
            raise
        except LLMJSONParseError as exc:
            last_error_code = "LLM_JSON_PARSE_ERROR"
            last_error_message = str(exc)
        except LLMEnumOutOfRange as exc:
            last_error_code = "LLM_ENUM_OUT_OF_RANGE"
            last_error_message = str(exc)
        except LLMTimeoutError as exc:
            last_error_code = "LLM_TIMEOUT"
            last_error_message = str(exc)
        except LLMBackendError as exc:
            last_error_code = "LLM_BACKEND_ERROR"
            last_error_message = str(exc)
        except Exception as exc:  # pragma: no cover - safety net
            last_error_code = "LLM_BACKEND_ERROR"
            last_error_message = str(exc)

        _attempt_elapsed = (time.monotonic() - attempt_start) * 1000.0
        log_kv(
            _LLM_LOGGER,
            logging.WARNING,
            "[LLM_ERROR]",
            tone="warn",
            backend=backend_kind,
            attempt=f"{attempt}/{attempts}",
            elapsed_ms=int(_attempt_elapsed),
            error_code=last_error_code,
            error_message=last_error_message,
            raw_preview=last_raw,
        )

        if attempt < attempts:
            log_kv(
                _LLM_LOGGER,
                logging.INFO,
                "[LLM_RETRY]",
                tone="warn",
                attempt=f"{attempt}/{attempts}",
                retrying_in_ms=int(0.02 * attempt * 1000),
            )
            time.sleep(0.02 * attempt)

    _total_elapsed = (time.monotonic() - _start_ts) * 1000.0
    log_kv(
        _LLM_LOGGER,
        logging.ERROR,
        "[LLM_FAILED]",
        tone="error",
        backend=backend_kind,
        attempts=attempts,
        total_ms=int(_total_elapsed),
        error_code=last_error_code,
        error_message=last_error_message,
        raw_preview=last_raw,
    )

    return {
        "ok": False,
        "content": None,
        "confidence": 0.0,
        "raw": last_raw,
        "error_code": last_error_code or "LLM_BACKEND_ERROR",
        "error_message": last_error_message or "LLM call failed",
        "llm_backend": backend_kind,
        "provider": last_provider,
        "model": last_model,
        "transport": last_transport,
        "attempts": attempts,
        "temperature": temperature,
        "timeout_ms": timeout_ms,
    }


# Auto-register real backend if enabled
from .. import config
if config.LLM_ENABLED and config.LLM_BACKEND == "real_llm":
    from .openai_backend import OpenAICompatibleBackend
    set_llm_backend(OpenAICompatibleBackend())

