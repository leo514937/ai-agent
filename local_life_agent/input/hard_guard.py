"""Hard guard filters — rejects clearly invalid or unsafe input before
semantic processing. Must NOT intercept pending_clarification replies.
"""


def check_hard_guard(text: str) -> dict:
    """Validate input against hard guard rules.

    Args:
        text: Normalized user input.

    Returns:
        {"passed": True} or {"passed": False, "reason": "...", "reply": "..."}.
    """
    raise NotImplementedError("Hard guard not yet implemented")
