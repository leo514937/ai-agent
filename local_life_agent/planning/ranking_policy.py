"""Ranking policy — defines how recommendation results are ranked and
filtered based on user preferences and hard constraints.
"""


def rank_candidates(candidates: list, preferences: dict) -> list:
    """Rank shop candidates by user preferences and ranking signals.

    Args:
        candidates: List of candidate shop dicts.
        preferences: User's soft preferences / ranking signals.

    Returns:
        Ranked list of shop dicts.
    """
    raise NotImplementedError("Ranking policy not yet implemented")
