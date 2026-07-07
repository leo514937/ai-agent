"""Trace-only freshness metadata DTO."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FreshnessMeta(BaseModel):
    """Minimal freshness metadata for trace / evidence observability."""

    model_config = ConfigDict(extra="forbid")

    freshness_class: str = ""
    is_stale: bool = False
    cache_hit: bool = False
    location_fingerprint: str = ""
    observed_at: datetime | None = None
    budget_context_snapshot: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_trace(
        cls,
        *,
        freshness_class: str = "",
        is_stale: bool = False,
        cache_hit: bool = False,
        location_fingerprint: str = "",
        observed_at: datetime | None = None,
        budget_context_snapshot: dict[str, Any] | None = None,
    ) -> FreshnessMeta:
        return cls(
            freshness_class=str(freshness_class or ""),
            is_stale=bool(is_stale),
            cache_hit=bool(cache_hit),
            location_fingerprint=str(location_fingerprint or ""),
            observed_at=observed_at or datetime.now(timezone.utc),
            budget_context_snapshot=dict(budget_context_snapshot or {}),
        )

    def trace_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
