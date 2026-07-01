from __future__ import annotations

import pytest

from .. import config as _cfg
from ..tools.executor import build_tool_executor


def test_tool_executor_rejects_unknown_backend():
    """Unknown TOOL_BACKEND values should fail closed instead of silently falling back."""
    old_backend = _cfg.TOOL_BACKEND
    try:
        _cfg.TOOL_BACKEND = "fake"
        with pytest.raises(ValueError, match="Unknown TOOL_BACKEND"):
            build_tool_executor()
    finally:
        _cfg.TOOL_BACKEND = old_backend
