"""Shared unsupported-intent detection for goal planning and review."""

from __future__ import annotations

from typing import Iterable


BOOKING_UNSUPPORTED_MARKERS: tuple[str, ...] = (
    "订座",
    "订位",
    "预约",
    "预订",
    "预定",
    "booking",
    "reservation",
    "reserve",
    "book a",
    "make a reservation",
)


def detect_booking_unsupported(*texts: str | None) -> tuple[bool, str]:
    """Return whether any text contains a booking/reservation intent marker."""
    normalized = [str(text or "").lower() for text in texts]
    for marker in BOOKING_UNSUPPORTED_MARKERS:
        if any(marker in text for text in normalized):
            return True, marker
    return False, ""


def build_booking_unsupported_reason(marker: str) -> str:
    return f"unsupported_intent: booking/reservation (no tool available): '{marker}'"
