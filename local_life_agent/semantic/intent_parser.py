"""Top-level intent classification.

Determines whether the user's request falls under local_life,
capability inquiry, casual chat, or is invalid/unsafe.
"""


def parse_top_intent(text: str) -> dict:
    """Classify the top-level intent of user input.

    Args:
        text: Normalized user text.

    Returns:
        Dict with at least {"intent": "..."} and optional confidence.
    """
    raise NotImplementedError("Intent parser not yet implemented")
