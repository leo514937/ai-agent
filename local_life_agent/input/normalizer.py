"""Text normalizer — preprocesses raw input before hard guard checks.

Applies normalization: trimming, unicode folding, common abbreviation
expansion, and whitespace collation.
"""


def normalize_text(text: str) -> str:
    """Normalize raw text for downstream processing.

    Args:
        text: Raw user input.

    Returns:
        Cleaned and normalized text.
    """
    raise NotImplementedError("Text normalizer not yet implemented")
