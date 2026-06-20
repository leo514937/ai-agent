"""Answer generator — produces natural language answers from
an answer plan and evidence pack.
"""


def generate_answer(answer_plan: dict, evidence: dict) -> str:
    """Generate a final natural language answer.

    Args:
        answer_plan: Plan dict with section structure.
        evidence: Evidence backing the claims.

    Returns:
        Generated answer text (may require verification).
    """
    raise NotImplementedError("Answer generator not yet implemented")
