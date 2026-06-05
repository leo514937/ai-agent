from __future__ import annotations

from collections.abc import Sequence


def normalize_location_text(text: str) -> str:
    return "".join(str(text or "").split()).lower()


def contains_any(text: str, tokens: Sequence[str]) -> bool:
    lowered = text.lower()
    return any(token in text or token.lower() in lowered for token in tokens if token)


def infer_location_hint(query: str) -> str | None:
    normalized = normalize_location_text(query)
    for token in ("附近", "周边", "同城", "本地", "这边", "这里"):
        if token in normalized:
            return token
    return None
