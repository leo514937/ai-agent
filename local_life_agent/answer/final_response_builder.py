"""Final response builder for the agent response DTO."""

from __future__ import annotations


def build_final_response(
    answer_text: str, trace_id: str, session_id: str,
    clarification: str | None = None, cards: list | None = None
) -> dict:
    """Construct the final response DTO dict."""
    return {
        "answer_text": answer_text,
        "trace_id": trace_id,
        "session_id": session_id,
        "clarification": clarification,
        "cards": cards or [],
    }
