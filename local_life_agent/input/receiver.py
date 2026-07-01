"""Input receiver for raw user text.

This module assembles the first turn payload and injects the mock user
context only when it is explicitly provided by a test or caller.
"""

from __future__ import annotations

from typing import Any

from ..core.state_core import build_missing_user_context
from ..domain.schemas import TurnInput, UserContext
from .validator import validate_basic_input


def receive_input(raw_text: Any, *, user_context: UserContext | None = None) -> dict:
    """Accept raw user input and assemble the initial turn payload.

    The function performs basic transport validation, injects the mock
    location context only when explicitly supplied, and returns a
    serialisable dict. It does not make any intent decisions.
    """
    validation = validate_basic_input(raw_text)
    user_context = user_context or build_missing_user_context()

    if not validation["valid"]:
        return {
            "input_type": validation["input_type"],
            "raw_text": validation["raw_text"],
            "user_context": user_context.model_dump(),
            "error_code": validation["error_code"],
            "error_message": validation["error_message"],
        }

    turn_input = TurnInput(
        input_type="text",
        raw_text=validation["raw_text"],
        user_context=user_context,
    )
    return turn_input.model_dump()
