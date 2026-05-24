from __future__ import annotations

from learning_agent_service.memory.preference_registry import (
    DEFAULT_PREFERENCE_REGISTRY,
    PreferenceMemorySignal,
    PreferenceRegistry,
    PreferenceRule,
)


def normalize_preference_key(text: str):
    return DEFAULT_PREFERENCE_REGISTRY.normalize_key(text)


def normalize_preference_value(key: str, text: str):
    return DEFAULT_PREFERENCE_REGISTRY.normalize_value(key, text)


def infer_preference_scope(text: str):
    return DEFAULT_PREFERENCE_REGISTRY.infer_scope(text)


def extract_preference_signal(
    *,
    text: str,
    session_id: str | None = None,
    turn_id: str | None = None,
    answer_text: str | None = None,
):
    return DEFAULT_PREFERENCE_REGISTRY.normalize_signal(
        text=text,
        session_id=session_id,
        turn_id=turn_id,
        answer_text=answer_text,
    )


__all__ = [
    "DEFAULT_PREFERENCE_REGISTRY",
    "PreferenceMemorySignal",
    "PreferenceRegistry",
    "PreferenceRule",
    "extract_preference_signal",
    "infer_preference_scope",
    "normalize_preference_key",
    "normalize_preference_value",
]

