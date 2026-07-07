"""Shared helpers for normalizing location-like payloads."""

from __future__ import annotations

from typing import Any


def normalize_location_payload(value: Any) -> dict[str, Any]:
    """Coerce a location payload into a plain dict."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        text = value.strip()
        return {"location_name": text} if text else {}

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        return dict(dumped) if isinstance(dumped, dict) else {}

    payload = dict(getattr(value, "__dict__", {}) or {})
    if payload:
        return payload

    text = str(value).strip()
    return {"location_name": text} if text else {}


def location_has_coordinates(value: Any) -> bool:
    """Return whether the payload carries usable latitude/longitude."""
    payload = normalize_location_payload(value)
    return payload.get("lat") is not None and payload.get("lng") is not None
