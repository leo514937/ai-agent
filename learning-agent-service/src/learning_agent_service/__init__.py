"""Top-level package metadata for the learning agent service."""

from __future__ import annotations

import os

os.environ.setdefault("PYDANTIC_DISABLE_PLUGINS", "logfire-plugin")

__all__ = ["__version__", "get_version"]

__version__ = "0.1.0"


def get_version() -> str:
    """Return the package version."""
    return __version__
