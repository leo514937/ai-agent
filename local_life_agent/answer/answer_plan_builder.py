"""Answer plan builder — plans the structure and content of the
final answer based on evidence and task type.
"""


def build_answer_plan(
    task_type: str, evidence: dict,     clarification: dict | None = None
) -> dict:
    """Plan how the answer should be structured.

    Args:
        task_type: The task type for context.
        evidence: Assembled evidence pack.
        clarification: Active clarification state if any.

    Returns:
        Answer plan dict with sections and data references.
    """
    raise NotImplementedError("Answer plan builder not yet implemented")
