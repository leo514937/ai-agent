"""Session partitioning and TTL policy."""

from __future__ import annotations

from typing import Any

from .. import config

SESSION_PARTITION_CONVERSATION_CONTEXT = "conversation_context"
SESSION_PARTITION_FOCUS_CONTEXT = "focus_context"
SESSION_PARTITION_RECOMMENDATION_CONTEXT = "recommendation_context"
SESSION_PARTITION_COMPARISON_CONTEXT = "comparison_context"
SESSION_PARTITION_PENDING_CLARIFICATION = "pending_clarification"
SESSION_PARTITION_USER_PREFERENCE_SUMMARY = "user_preference_summary"
SESSION_PARTITION_EXECUTION_COUNTERS = "execution_counters"
SESSION_PARTITION_DEFAULT = SESSION_PARTITION_CONVERSATION_CONTEXT

SESSION_FIELD_PARTITION_MAP: dict[str, str] = {
    "current_shop": SESSION_PARTITION_FOCUS_CONTEXT,
    "current_shop_meta": SESSION_PARTITION_FOCUS_CONTEXT,
    "canonical_shop_entity": SESSION_PARTITION_CONVERSATION_CONTEXT,
    "canonical_shop_entities": SESSION_PARTITION_CONVERSATION_CONTEXT,
    "shop_resolution_trace": SESSION_PARTITION_CONVERSATION_CONTEXT,
    "last_recommendation_list": SESSION_PARTITION_RECOMMENDATION_CONTEXT,
    "last_recommendation_list_meta": SESSION_PARTITION_RECOMMENDATION_CONTEXT,
    "active_constraints": SESSION_PARTITION_USER_PREFERENCE_SUMMARY,
    "active_preferences": SESSION_PARTITION_USER_PREFERENCE_SUMMARY,
    "pending_clarification": SESSION_PARTITION_PENDING_CLARIFICATION,
    "pending_clarification_meta": SESSION_PARTITION_PENDING_CLARIFICATION,
    "comparison_targets": SESSION_PARTITION_COMPARISON_CONTEXT,
    "comparison_targets_meta": SESSION_PARTITION_COMPARISON_CONTEXT,
    "comparison_result": SESSION_PARTITION_COMPARISON_CONTEXT,
    "suggested_shop": SESSION_PARTITION_RECOMMENDATION_CONTEXT,
    "last_candidate_spec": SESSION_PARTITION_CONVERSATION_CONTEXT,
    "last_candidate_set": SESSION_PARTITION_CONVERSATION_CONTEXT,
    "active_goal": SESSION_PARTITION_CONVERSATION_CONTEXT,
    "review_results": SESSION_PARTITION_EXECUTION_COUNTERS,
    "last_decision_plan": SESSION_PARTITION_CONVERSATION_CONTEXT,
    "replan_counters": SESSION_PARTITION_EXECUTION_COUNTERS,
}

_PARTITION_CONFIG_ATTRS: dict[str, str] = {
    SESSION_PARTITION_CONVERSATION_CONTEXT: "SESSION_TTL_CONVERSATION_CONTEXT_SECONDS",
    SESSION_PARTITION_FOCUS_CONTEXT: "SESSION_TTL_FOCUS_CONTEXT_SECONDS",
    SESSION_PARTITION_RECOMMENDATION_CONTEXT: "SESSION_TTL_RECOMMENDATION_CONTEXT_SECONDS",
    SESSION_PARTITION_COMPARISON_CONTEXT: "SESSION_TTL_COMPARISON_CONTEXT_SECONDS",
    SESSION_PARTITION_PENDING_CLARIFICATION: "SESSION_TTL_PENDING_CLARIFICATION_SECONDS",
    SESSION_PARTITION_USER_PREFERENCE_SUMMARY: "SESSION_TTL_USER_PREFERENCE_SUMMARY_SECONDS",
    SESSION_PARTITION_EXECUTION_COUNTERS: "SESSION_TTL_EXECUTION_COUNTERS_SECONDS",
}


def partition_for_field(field_name: str) -> str:
    return SESSION_FIELD_PARTITION_MAP.get(str(field_name or "").strip(), SESSION_PARTITION_DEFAULT)


def partition_for_state_field_items(state: Any) -> dict[str, list[str]]:
    fields: dict[str, list[str]] = {}
    for field_name in getattr(state, "model_fields", {}) or {}:
        partition = partition_for_field(field_name)
        fields.setdefault(partition, []).append(field_name)
    return fields


def ttl_seconds_for_partition(partition: str) -> int:
    normalized = str(partition or "").strip()
    attr_name = _PARTITION_CONFIG_ATTRS.get(normalized)
    if attr_name and hasattr(config, attr_name):
        try:
            return int(getattr(config, attr_name))
        except Exception:
            pass
    return int(getattr(config, "SESSION_TTL_DEFAULT_SECONDS", 1800))


def partitions() -> tuple[str, ...]:
    return (
        SESSION_PARTITION_CONVERSATION_CONTEXT,
        SESSION_PARTITION_FOCUS_CONTEXT,
        SESSION_PARTITION_RECOMMENDATION_CONTEXT,
        SESSION_PARTITION_COMPARISON_CONTEXT,
        SESSION_PARTITION_PENDING_CLARIFICATION,
        SESSION_PARTITION_USER_PREFERENCE_SUMMARY,
        SESSION_PARTITION_EXECUTION_COUNTERS,
    )
