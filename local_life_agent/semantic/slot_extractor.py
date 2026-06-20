"""Slot extraction — extracts structured fields from user utterances.

Pulls out entities like shop names, categories, price ranges,
distance preferences, and other query constraints.
"""


def extract_slots(text: str, top_intent: str) -> dict:
    """Extract typed slots from the user's utterance.

    Args:
        text: Normalized user text.
        top_intent: The classified top-level intent.

    Returns:
        Dict with extracted slot values.
    """
    raise NotImplementedError("Slot extractor not yet implemented")
