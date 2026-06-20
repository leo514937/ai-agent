"""Task router — decides which task type to execute based on the
resolved semantic frame and target.
"""


def route_task(semantic_frame: dict, resolved_target: dict) -> str:
    """Determine the task type for this turn.

    Args:
        semantic_frame: Parsed user intent and slots.
        resolved_target: Resolved shop/entity target.

    Returns:
        Task type string: "single_shop_query", "recommendation", "comparison", etc.
    """
    raise NotImplementedError("Task router not yet implemented")
