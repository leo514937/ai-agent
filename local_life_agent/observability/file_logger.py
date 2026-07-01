"""Shared file logger for local life agent execution traces."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


_LOGGER_NAME = "local_life_agent.python_service"
_LOGGER: logging.Logger | None = None
_LOG_CONTEXT: ContextVar[dict[str, Any]] = ContextVar("local_life_agent_log_context", default={})

_ANSI_RESET = "\x1b[0m"
_ANSI_COLORS: dict[str, str] = {
    "debug": "\x1b[36m",
    "info": "\x1b[32m",
    "warn": "\x1b[33m",
    "error": "\x1b[31m",
    "route": "\x1b[35m",
    "llm": "\x1b[34m",
    "tool": "\x1b[96m",
    "node": "\x1b[90m",
}


def _log_paths() -> list[Path]:
    project_root = Path(__file__).resolve().parents[2]
    log_dir = project_root / "var"
    log_dir.mkdir(parents=True, exist_ok=True)
    return [log_dir / "python_service.log"]


def get_python_service_logger() -> logging.Logger:
    """Return a singleton logger that writes to var/python_service.log."""
    global _LOGGER
    if _LOGGER is not None:
        return _LOGGER

    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    if not any(isinstance(handler, RotatingFileHandler) for handler in logger.handlers):
        formatter = logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        for path in _log_paths():
            handler = RotatingFileHandler(
                path,
                maxBytes=5 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)

    _LOGGER = logger
    return logger


def summarize_for_log(value: Any, *, max_len: int = 400, max_items: int = 8) -> str:
    """Return a compact single-line preview safe for file logging."""
    try:
        if hasattr(value, "model_dump"):
            value = value.model_dump()
        elif hasattr(value, "value"):
            value = getattr(value, "value")

        if isinstance(value, dict):
            items = list(value.items())[:max_items]
            rendered = json.dumps(dict(items), ensure_ascii=False, default=str)
        elif isinstance(value, (list, tuple, set)):
            items = list(value)[:max_items]
            rendered = json.dumps(items, ensure_ascii=False, default=str)
        else:
            rendered = str(value)
    except Exception:
        rendered = "<unserializable>"

    rendered = rendered.replace("\r", "\\r").replace("\n", "\\n")
    if len(rendered) > max_len:
        return f"{rendered[:max_len]}...(truncated)"
    return rendered


def ansi_tag(tag: str, tone: str = "info") -> str:
    color = _ANSI_COLORS.get(tone, _ANSI_COLORS["info"])
    return f"{color}{tag}{_ANSI_RESET}"


def current_log_context() -> dict[str, Any]:
    return dict(_LOG_CONTEXT.get())


def set_log_context(**fields: Any):
    merged = current_log_context()
    for key, value in fields.items():
        if value is None or value == "":
            continue
        merged[key] = value
    return _LOG_CONTEXT.set(merged)


def reset_log_context(token: Any) -> None:
    _LOG_CONTEXT.reset(token)


@contextmanager
def log_context(**fields: Any):
    token = set_log_context(**fields)
    try:
        yield
    finally:
        reset_log_context(token)


def log_kv(
    logger: logging.Logger,
    level: int,
    tag: str,
    *,
    tone: str = "info",
    **fields: Any,
) -> None:
    """Write a color-tagged key=value log line."""
    merged_fields = {**current_log_context(), **fields}
    parts: list[str] = []
    for key, value in merged_fields.items():
        if value is None or value == "":
            continue
        if isinstance(value, bool):
            parts.append(f"{key}={'true' if value else 'false'}")
        else:
            parts.append(f"{key}={summarize_for_log(value)}")
    message = " ".join(parts)
    logger.log(level, "%s %s", tag, message)

