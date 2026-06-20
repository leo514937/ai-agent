"""Basic input validation for raw user turns.

The validator only checks transport-level constraints. It does not try
to infer business intent or semantic meaning.
"""

from __future__ import annotations

from typing import Any


MAX_RAW_TEXT_LENGTH = 2000


class BasicInputValidator:
    """Validate raw user input before normalisation."""

    def __init__(self, max_length: int = MAX_RAW_TEXT_LENGTH):
        self.max_length = max_length

    def validate(self, raw_text: Any) -> dict[str, Any]:
        """Validate one raw input payload."""
        if not isinstance(raw_text, str):
            return {
                "valid": False,
                "input_type": "invalid",
                "raw_text": "",
                "error_code": "INVALID_INPUT_TYPE",
                "error_message": "raw_text must be a string",
            }

        trimmed = raw_text.strip()
        if not trimmed:
            return {
                "valid": False,
                "input_type": "invalid",
                "raw_text": raw_text,
                "error_code": "EMPTY_INPUT",
                "error_message": "raw_text is empty or whitespace only",
            }

        if len(trimmed) > self.max_length:
            return {
                "valid": False,
                "input_type": "invalid",
                "raw_text": raw_text,
                "error_code": "INPUT_TOO_LONG",
                "error_message": f"raw_text exceeds {self.max_length} characters",
            }

        return {
            "valid": True,
            "input_type": "text",
            "raw_text": raw_text,
            "error_code": "",
            "error_message": "",
        }


def validate_basic_input(raw_text: Any, max_length: int = MAX_RAW_TEXT_LENGTH) -> dict[str, Any]:
    """Convenience wrapper around :class:`BasicInputValidator`."""
    return BasicInputValidator(max_length=max_length).validate(raw_text)
