"""Execution plan builder — assembles a concrete plan of tool calls
from the task type, resolved target, and planned facets.
"""


def build_execution_plan(
    task_type: str, target: dict, facets: list[str]
) -> dict:
    """Build an execution plan dict with ordered tool calls.

    Args:
        task_type: The task to execute.
        target: Resolved shop/entity target.
        facets: Facets to query.

    Returns:
        Execution plan dict with tool_call list and metadata.
    """
    raise NotImplementedError("Execution plan builder not yet implemented")
