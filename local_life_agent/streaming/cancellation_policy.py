from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CancellationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_disconnect_action: str = "stop"
    user_cancel_action: str = "stop"
    deadline_exceeded_action: str = "fallback"
    tool_timeout_action: str = "degrade"
    llm_timeout_action: str = "fallback"
    partial_result_action: str = "degrade"
    stop_events: list[str] = Field(default_factory=lambda: ["client_disconnect", "user_cancel"])
    degrade_events: list[str] = Field(default_factory=lambda: ["tool_timeout", "partial_result_available"])
    fallback_events: list[str] = Field(default_factory=lambda: ["deadline_exceeded", "llm_timeout"])


DEFAULT_CANCELLATION_POLICY = CancellationPolicy()


def decide_cancellation_action(event_name: str, policy: CancellationPolicy | None = None) -> str:
    policy = policy or DEFAULT_CANCELLATION_POLICY
    event = str(event_name or "").strip().lower()
    if event in set(policy.stop_events):
        return "stop"
    if event in set(policy.degrade_events):
        return "degrade"
    if event in set(policy.fallback_events):
        return "fallback"
    return "continue"
