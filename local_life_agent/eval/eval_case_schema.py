"""Pydantic schemas for JSONL eval case validation.

Provides ``EvalCase`` and ``EvalExpected`` models so every JSONL line is
validated at load time rather than failing silently mid-run.
"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class EvalTurn(BaseModel):
    """A single user turn in an eval case.

    The ``user`` field holds the request text. Backward-compatible with
    both ``{"user": "..."}`` and plain-string turns.
    """

    model_config = ConfigDict(extra="ignore")

    user: str = ""


class EvalExpected(BaseModel):
    """Expected outcomes for an eval case.

    All fields are optional so existing JSONL files load without changes.
    The assertion logic in ``_assert_expected`` accesses these by name.
    """

    model_config = ConfigDict(extra="ignore")

    top_intent: str | None = None
    task_type: str | None = None
    selected_flow: str | None = None
    decision_type: str | None = None
    answer_source: str | None = None
    reference_resolution_source: str | None = None
    forbid_answer_source: list[str] | None = None
    min_candidate_count: int | None = None
    max_rewrite_count: int | None = None
    must_include_violation: list[str] | None = None
    must_not_include_violation: list[str] | None = None
    allow_skipped_if_no_api_key: bool | None = None
    turn_assertions: list[dict[str, Any]] | None = None

    # Catch-all for any other expected keys the runtime checks
    extra: dict[str, Any] = Field(default_factory=dict, alias="_extra")

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Produce a dict excluding None-valued fields.

        This is critical for backward compatibility: ``_assert_expected``
        iterates over every key in the dict, and None would trigger false
        assertion failures (``expected=None observed=...``).
        """
        result = super().model_dump(*args, **{**kwargs, "by_alias": False})
        extra = result.pop("extra", {}) or {}
        if isinstance(extra, dict):
            result.update(extra)
        # Strip None-valued fields so _assert_expected only checks what
        # the JSONL file explicitly specified.
        return {k: v for k, v in result.items() if v is not None}


class EvalCase(BaseModel):
    """A single eval case loaded from a JSONL file.

    Only ``case_id`` is strictly required. All other fields accept
    flexible shapes to accommodate both old-format and new-format cases.
    """

    model_config = ConfigDict(extra="ignore")

    case_id: str
    category: str = "uncategorized"
    turns: list[EvalTurn | str | dict[str, Any]] = Field(default_factory=list)
    expected: EvalExpected = Field(default_factory=EvalExpected)

    def to_dict(self) -> dict[str, Any]:
        """Produce a plain dict compatible with the existing eval runner."""
        expected_dict = self.expected.model_dump()
        return {
            "case_id": self.case_id,
            "category": self.category,
            "turns": [
                t if isinstance(t, (str, dict)) else t.model_dump()
                for t in self.turns
            ],
            "expected": expected_dict,
        }
