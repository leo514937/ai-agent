"""Structured logging utilities for the standalone learning agent service."""

from __future__ import annotations

import contextvars
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .settings import ObservabilitySettings

_LOG_CONTEXT = contextvars.ContextVar("learning_agent_log_context", default=None)
_STANDARD_LOG_RECORD_FIELDS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys())


@dataclass(frozen=True)
class ServiceLogContext:
    """Trace identifiers that should follow a single request across adapters."""

    trace_id: str | None = None
    session_id: str | None = None
    turn_id: str | None = None
    user_id: str | None = None

    def as_dict(self) -> dict[str, str]:
        return {key: value for key, value in self.__dict__.items() if value}


class StructuredJsonFormatter(logging.Formatter):
    """Format logs as JSON for easy ingestion by external observability stacks."""

    def __init__(self, include_caller: bool = False) -> None:
        super().__init__()
        self._include_caller = include_caller

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(get_log_context())
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        if self._include_caller:
            payload["caller"] = "%s:%s" % (record.pathname, record.lineno)
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _STANDARD_LOG_RECORD_FIELDS and not key.startswith("_")
        }
        if extras:
            payload["extra"] = extras
        return json.dumps(payload, ensure_ascii=False, default=str)


class PlainTextFormatter(logging.Formatter):
    """A compact formatter for local development without JSON logs."""

    def format(self, record: logging.LogRecord) -> str:
        base = "[%(levelname)s] %(name)s %(message)s" % {
            "levelname": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        }
        context = get_log_context()
        if context:
            base = "%s %s" % (base, json.dumps(context, ensure_ascii=False, sort_keys=True))
        if record.exc_info:
            return "%s\n%s" % (base, self.formatException(record.exc_info))
        return base


def bind_log_context(**values: str | None) -> None:
    """Merge per-request identifiers into the active log context."""

    current = dict(_LOG_CONTEXT.get() or {})
    for key, value in values.items():
        if value:
            current[key] = value
    _LOG_CONTEXT.set(current)


def clear_log_context() -> None:
    """Clear the active request-scoped log context."""

    _LOG_CONTEXT.set(None)


def get_log_context() -> dict[str, Any]:
    """Return the current logging context snapshot."""

    return dict(_LOG_CONTEXT.get() or {})


def configure_logging(settings: ObservabilitySettings) -> None:
    """Configure root logging for the service process."""

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(settings.log_level.upper())

    handler = logging.StreamHandler()
    if settings.json_logs:
        handler.setFormatter(StructuredJsonFormatter(include_caller=settings.include_caller))
    else:
        handler.setFormatter(PlainTextFormatter())
    root_logger.addHandler(handler)
