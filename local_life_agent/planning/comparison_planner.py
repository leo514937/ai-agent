"""Comparison planner — plans how to present a multi-shop comparison,
selecting which shops to compare in detail vs. summary.
"""


def plan_comparison(shops: list, max_detail: int = 3) -> dict:
    """Plan comparison presentation.

    Args:
        shops: List of shops to compare.
        max_detail: Max shops shown with full detail.

    Returns:
        Dict with full_detail_shops, summary_shops, and facets_to_compare.
    """
    raise NotImplementedError("Comparison planner not yet implemented")
