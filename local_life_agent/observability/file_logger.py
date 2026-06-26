"""Shared file logger for local life agent execution traces."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


_LOGGER_NAME = "local_life_agent.python_service"
_LOGGER: logging.Logger | None = None


def _log_path() -> Path:
    project_root = Path(__file__).resolve().parents[2]
    log_dir = project_root / "var"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "python_service.log"


def get_python_service_logger() -> logging.Logger:
    """Return a singleton logger that writes to var/python_service.log."""
    global _LOGGER
    if _LOGGER is not None:
        return _LOGGER

    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not any(isinstance(handler, RotatingFileHandler) for handler in logger.handlers):
        handler = RotatingFileHandler(
            _log_path(),
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        formatter = logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    _LOGGER = logger
    return logger

