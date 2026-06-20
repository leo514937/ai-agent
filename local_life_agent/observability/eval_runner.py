"""Evaluation runner — runs test cases against the agent and
produces regression reports.
"""


def run_eval(test_cases: list[dict]) -> dict:
    """Execute a batch of evaluation test cases.

    Args:
        test_cases: List of test case dicts (input, expected_output).

    Returns:
        Aggregated evaluation report dict.
    """
    raise NotImplementedError("Eval runner not yet implemented")
