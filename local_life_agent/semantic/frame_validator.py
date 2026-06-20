"""Frame validator — validates the semantic frame for completeness and
consistency. May reject or request clarification for ambiguous frames.
"""


def validate_frame(frame: dict) -> dict:
    """Check that a semantic frame is valid and actionable.

    Args:
        frame: The SemanticFrame dict from intent parsing + slot extraction.

    Returns:
        {"valid": True} or {"valid": False, "issues": [...], "clarification": "..."}.
    """
    raise NotImplementedError("Frame validator not yet implemented")
