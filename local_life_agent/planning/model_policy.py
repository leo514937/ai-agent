from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class NodeModelProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_name: str
    primary_model: str
    fallback_model: str = ""
    timeout_ms: int = 0
    max_retries: int = 0
    fallback_strategy: str = "rule_template"
    temperature: float = 0.0
    notes: str = ""


NODE_MODEL_POLICY: dict[str, NodeModelProfile] = {
    "hard_guard": NodeModelProfile(
        node_name="hard_guard",
        primary_model="rules",
        fallback_model="rules",
        timeout_ms=50,
        max_retries=0,
        fallback_strategy="direct_response",
        notes="pure allow/deny gate",
    ),
    "top_intent_router": NodeModelProfile(
        node_name="top_intent_router",
        primary_model="fast_model",
        fallback_model="rules",
        timeout_ms=3000,
        max_retries=1,
        fallback_strategy="rule_based_intent",
        notes="top intent classification",
    ),
    "semantic_parse": NodeModelProfile(
        node_name="semantic_parse",
        primary_model="balanced_model",
        fallback_model="rules",
        timeout_ms=1800,
        max_retries=1,
        fallback_strategy="diagnostic_rules",
        notes="structured semantic extraction",
    ),
    "goal_planner": NodeModelProfile(
        node_name="goal_planner",
        primary_model="balanced_model",
        fallback_model="rules",
        timeout_ms=15000,
        max_retries=1,
        fallback_strategy="clarification",
        notes="plan draft generation",
    ),
    "decision_planner": NodeModelProfile(
        node_name="decision_planner",
        primary_model="strong_model",
        fallback_model="balanced_model",
        timeout_ms=15000,
        max_retries=1,
        fallback_strategy="degrade",
        notes="final decision selection",
    ),
    "evidence_review": NodeModelProfile(
        node_name="evidence_review",
        primary_model="balanced_model",
        fallback_model="rules",
        timeout_ms=8000,
        max_retries=1,
        fallback_strategy="precheck_result",
        notes="evidence sufficiency review",
    ),
    "answer_generate": NodeModelProfile(
        node_name="answer_generate",
        primary_model="strong_model",
        fallback_model="balanced_model",
        timeout_ms=8000,
        max_retries=1,
        fallback_strategy="deterministic_composer",
        notes="natural answer generation",
    ),
    "answer_verify": NodeModelProfile(
        node_name="answer_verify",
        primary_model="balanced_model",
        fallback_model="rules",
        timeout_ms=5000,
        max_retries=1,
        fallback_strategy="rewrite_instruction",
        notes="verify claims before finalization",
    ),
}


def get_node_model_profile(node_name: str) -> NodeModelProfile | None:
    return NODE_MODEL_POLICY.get(str(node_name or "").strip())


_PROMPT_TO_NODE_NAME: dict[str, str] = {
    "evidence_sufficiency_review": "evidence_review",
    "goal_planner": "goal_planner",
    "decision_planner": "decision_planner",
    "evidence_planner": "evidence_planner",
    "answer_verifier": "answer_verify",
}


def get_prompt_model_profile(prompt_name: str) -> NodeModelProfile | None:
    node_name = _PROMPT_TO_NODE_NAME.get(str(prompt_name or "").strip(), str(prompt_name or "").strip())
    return get_node_model_profile(node_name)


def build_model_policy_summary() -> dict[str, dict[str, str | int | float]]:
    return {name: profile.model_dump() for name, profile in NODE_MODEL_POLICY.items()}
