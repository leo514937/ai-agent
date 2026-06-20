"""Input receiver — initial entry point for raw user text.

Responsible for accepting the raw input and constructing the
initial TurnInput structure.
"""


def receive_input(raw_text: str) -> dict:
    """Accept and wrap raw user input.

    Args:
        raw_text: Raw text from the user.

    Returns:
        A dict with at least {"input_type": "text", "raw_text": ...}.
    """
    raise NotImplementedError("Input receiver not yet implemented")
