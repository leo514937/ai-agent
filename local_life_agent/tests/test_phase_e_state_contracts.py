from __future__ import annotations

from local_life_agent.engine._compat import _trace_output_summary
from local_life_agent.observability.trace import _infer_tool_call_count


def test_trace_output_summary_prefers_tool_results_over_compat_tool_result_set():
    summary = _trace_output_summary(
        {
            "tool_results": {"call_primary": {"tool_name": "get_coupon_list"}},
            "tool_result_set": {
                "call_legacy_a": {"tool_name": "legacy"},
                "call_legacy_b": {"tool_name": "legacy"},
            },
        }
    )

    assert summary["tool_result_count"] == 1


def test_trace_inference_prefers_tool_results_over_compat_tool_result_set():
    count = _infer_tool_call_count(
        {},
        {
            "tool_results": {"call_primary": {"tool_name": "get_coupon_list"}},
            "tool_result_set": {
                "call_legacy_a": {"tool_name": "legacy"},
                "call_legacy_b": {"tool_name": "legacy"},
            },
        },
    )

    assert count == 1
