"""Session write strategy planner.

Implements the session write strategy table from
`todo/02_状态转移与路由决策表.md` §2.

Each scenario maps to a directive that tells the state-update planner
which fields to set, which to clear, and what to leave unchanged.
"""

from __future__ import annotations

try:
    from enum import StrEnum
except ImportError:  # Python < 3.11
    from enum import Enum

    class StrEnum(str, Enum):
        pass
from ..domain.state import SessionWriteDirective


# ---------------------------------------------------------------------------
# Scenario identifiers
# ---------------------------------------------------------------------------

class SessionScenario(StrEnum):
    """Enumerates all session-write scenarios from the strategy table."""
    SINGLE_SHOP_COUPON_OK = "single_shop_coupon_ok"
    SINGLE_SHOP_MULTI_FACET_OK = "single_shop_multi_facet_ok"
    NEARBY_RECOMMENDATION_OK = "nearby_recommendation_ok"
    COMPARISON_OK = "comparison_ok"
    RESOLVE_SHOP_AMBIGUOUS = "resolve_shop_ambiguous"
    CLARIFICATION_REPLY_OK = "clarification_reply_ok"
    TOPIC_SWITCH = "topic_switch"
    TOOL_UNKNOWN_FAILED = "tool_unknown_failed"


# ---------------------------------------------------------------------------
# Strategy table
# ---------------------------------------------------------------------------

_SCENARIO_RULES: dict[SessionScenario, SessionWriteDirective] = {
    # 单店查券成功: write current_shop, clear pending
    SessionScenario.SINGLE_SHOP_COUPON_OK: SessionWriteDirective(
        set_fields={"current_shop": None},
        clear_fields=["pending_clarification", "last_recommendation_list"],
    ),
    # 单店多facet成功: write current_shop, clear pending
    SessionScenario.SINGLE_SHOP_MULTI_FACET_OK: SessionWriteDirective(
        set_fields={"current_shop": None},
        clear_fields=["pending_clarification", "last_recommendation_list"],
    ),
    # 附近推荐成功: write last_recommendation_list, clear pending
    SessionScenario.NEARBY_RECOMMENDATION_OK: SessionWriteDirective(
        set_fields={"last_recommendation_list": None},
        clear_fields=["pending_clarification", "current_shop"],
    ),
    # 多店对比成功: clear pending (一般不写 recommendation list)
    SessionScenario.COMPARISON_OK: SessionWriteDirective(
        set_fields={},
        clear_fields=["pending_clarification"],
    ),
    # resolve_shop AMBIGUOUS: write pending_clarification, do NOT clear
    SessionScenario.RESOLVE_SHOP_AMBIGUOUS: SessionWriteDirective(
        set_fields={"pending_clarification": None},
        clear_fields=[],
    ),
    # 用户澄清成功: clear pending; other fields depend on original task
    SessionScenario.CLARIFICATION_REPLY_OK: SessionWriteDirective(
        set_fields={},
        clear_fields=["pending_clarification"],
    ),
    # 用户换话题: clear pending; other fields depend on new task
    SessionScenario.TOPIC_SWITCH: SessionWriteDirective(
        set_fields={},
        clear_fields=["pending_clarification"],
    ),
    # 工具 unknown/failed: no update to target or recommendation
    SessionScenario.TOOL_UNKNOWN_FAILED: SessionWriteDirective(
        set_fields={},
        clear_fields=["pending_clarification"],
    ),
}


def get_directive(scenario: SessionScenario) -> SessionWriteDirective:
    """Look up the base write directive for a scenario.

    Returns a *copy* so callers can safely fill in runtime values.
    """
    return _SCENARIO_RULES[scenario].clone()


def resolve_scenario(
    task_type: str | None,
    resolve_status: str | None,
    is_clarification_reply: bool = False,
    is_topic_switch: bool = False,
    tool_failure_severity: str | None = None,
) -> SessionScenario:
    """Determine the session-write scenario from turn context.

    Args:
        task_type: The classified task type (single_shop_query, recommendation, ...).
        resolve_status: Outcome of target resolution (RESOLVED, AMBIGUOUS, ...).
        is_clarification_reply: Whether this turn processes a clarification reply.
        is_topic_switch: Whether the user clearly switched topics.
        tool_failure_severity: 'required' or 'circuit_open' if a tool failed.

    Returns:
        The matching SessionScenario.
    """
    if is_topic_switch:
        return SessionScenario.TOPIC_SWITCH

    if is_clarification_reply:
        return SessionScenario.CLARIFICATION_REPLY_OK

    if resolve_status == "AMBIGUOUS":
        return SessionScenario.RESOLVE_SHOP_AMBIGUOUS

    if tool_failure_severity in ("required", "circuit_open"):
        return SessionScenario.TOOL_UNKNOWN_FAILED

    # Successful task branches
    if task_type in ("single_shop_query", "coupon_query"):
        return SessionScenario.SINGLE_SHOP_COUPON_OK
    if task_type == "recommendation":
        return SessionScenario.NEARBY_RECOMMENDATION_OK
    if task_type == "comparison":
        return SessionScenario.COMPARISON_OK

    # Default safe fallback
    return SessionScenario.TOOL_UNKNOWN_FAILED
