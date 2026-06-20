"""Final response builder — wraps the verified answer and optional
cards into the standard AgentResponse DTO for emission.
"""


def build_final_response(
    answer_text: str, trace_id: str, session_id: str,
    clarification: str | None = None, cards: list | None = None
) -> dict:
    """Construct the final response DTO dict.

    Args:
        answer_text: Final verified answer.
        trace_id: Request trace ID.
        session_id: Session identifier.
        clarification: Optional clarification question.
        cards: Optional card data list.

    Returns:
        Dict matching the AgentResponse format.
    """
    raise NotImplementedError("Final response builder not yet implemented")
