"""Trace-only location context DTO."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class LocationContext(BaseModel):
    """Serialisable view of the user location context."""

    model_config = ConfigDict(extra="forbid")

    location_name: str = ""
    lat: float | None = None
    lng: float | None = None
    location_status: str = ""
    location_source: str = ""
    location_fingerprint: str = ""
    radius_meters: int | None = None

    @classmethod
    def from_trace(
        cls,
        *,
        location_name: str = "",
        lat: float | None = None,
        lng: float | None = None,
        location_status: str = "",
        location_source: str = "",
        location_fingerprint: str = "",
        radius_meters: int | None = None,
    ) -> LocationContext:
        return cls(
            location_name=str(location_name or ""),
            lat=lat,
            lng=lng,
            location_status=str(location_status or ""),
            location_source=str(location_source or ""),
            location_fingerprint=str(location_fingerprint or ""),
            radius_meters=radius_meters if radius_meters is None else int(radius_meters),
        )

    def trace_dict(self) -> dict[str, Any]:
        return self.model_dump()
