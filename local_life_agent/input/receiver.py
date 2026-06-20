"""Input receiver for raw user text.

This module assembles the first turn payload and injects the mock user
context used throughout the MVP.
"""

from __future__ import annotations

from typing import Any

from ..config import MOCK_LOCATION
from ..domain.schemas import TurnInput, UserContext
from .validator import validate_basic_input


def _build_mock_user_context() -> UserContext:
    """Create the shared mock user context used by the MVP."""
    return UserContext(
        location_name=MOCK_LOCATION["name"],
        lat=MOCK_LOCATION["lat"],
        lng=MOCK_LOCATION["lng"],
    )


def receive_input(raw_text: Any) -> dict:
    """Accept raw user input and assemble the initial turn payload.

    The function performs basic transport validation, injects the mock
    location context, and returns a serialisable dict. It does not make
    any intent decisions.
    """
    validation = validate_basic_input(raw_text)
    user_context = _build_mock_user_context()

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
