"""State update planner — determines how the session state should
be updated after a turn completes, based on task type and outcomes.
"""


def plan_state_update(
    turn_context: dict, task_type: str, resolve_status: str
) -> dict:
    """Compute the session state delta for this turn.

    Args:
        turn_context: Full GlobalTurnContext for the turn.
        task_type: Executed task type.
        resolve_status: Outcome of shop resolution.

    Returns:
        Dict with keys to set and keys to clear in session state.
    """
    raise NotImplementedError("State update planner not yet implemented")
