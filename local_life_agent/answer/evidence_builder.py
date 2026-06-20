"""Evidence builder — assembles verified evidence from tool results
for use in answer generation. Ensures all cited facts are backed
by tool outputs.
"""


def build_evidence(tool_results: dict, resolved_target: dict) -> dict:
    """Build an evidence pack from tool results.

    Args:
        tool_results: Aggregated tool call results.
        resolved_target: Resolved target shop/entity.

    Returns:
        Evidence pack dict with confirmed facts.
    """
    raise NotImplementedError("Evidence builder not yet implemented")
