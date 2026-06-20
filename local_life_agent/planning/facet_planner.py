"""Facet planner — determines which facets (coupon, open_status,
distance, price) should be queried for the current task.
"""


def plan_facets(task_type: str, semantic_frame: dict) -> list[str]:
    """Decide which facets to query based on task type and user request.

    Args:
        task_type: Routed task type.
        semantic_frame: User's semantic frame with requested facets.

    Returns:
        Ordered list of facet names to query.
    """
    raise NotImplementedError("Facet planner not yet implemented")
