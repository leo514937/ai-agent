"""Text normalizer for raw user text.

The goal is conservative cleanup: trim whitespace, unify common
Chinese/English punctuation, and collapse repeated whitespace without
touching business keywords or shop names.
"""

from __future__ import annotations

import re
import unicodedata


_PUNCT_TRANSLATION = str.maketrans(
    {
        "，": ",",
        "。": ".",
        "！": "!",
        "？": "?",
        "：": ":",
        "；": ";",
        "（": "(",
        "）": ")",
        "【": "[",
        "】": "]",
        "《": "<",
        "》": ">",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "、": ",",
        "—": "-",
        "－": "-",
        "～": "~",
        "　": " ",
    }
)


def normalize_text(text: str) -> str:
    """Normalize raw text for downstream processing."""
    if not isinstance(text, str):
        return ""

    normalised = unicodedata.normalize("NFKC", text)
    normalised = normalised.translate(_PUNCT_TRANSLATION)
    normalised = normalised.strip()
    normalised = re.sub(r"[\t\r\n\f\v ]+", " ", normalised)
    return normalised
