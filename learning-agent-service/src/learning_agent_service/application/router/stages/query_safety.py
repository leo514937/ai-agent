from __future__ import annotations

from dataclasses import dataclass, asdict

from ...routing_primitives import normalize_query


_PROMPT_INJECTION_PATTERNS = (
    "ignore previous instructions",
    "ignore all previous instructions",
    "system prompt",
    "developer message",
    "developer prompt",
    "reveal the prompt",
    "reveal hidden prompt",
    "jailbreak",
    "prompt injection",
    "忽略之前的指令",
    "忽略所有指令",
    "系统提示",
    "开发者消息",
    "开发者提示词",
    "泄露提示词",
    "输出系统提示",
    "越权",
)


@dataclass(frozen=True)
class QuerySafetyResult:
    allowed: bool
    blocked: bool
    reason: str | None = None
    required_action: str = "direct_answer"
    route_candidate: str | None = None
    confidence: float = 0.0
    matched_signals: list[str] | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def check_query_safety(
    raw_query: str,
    *,
    client_context: dict[str, object] | None = None,
) -> QuerySafetyResult:
    normalized = normalize_query(raw_query)
    compact = normalized.replace(" ", "")
    lowered = normalized.lower()

    matched: list[str] = []
    for pattern in _PROMPT_INJECTION_PATTERNS:
        if pattern in normalized or pattern.lower() in lowered or pattern in compact:
            matched.append(pattern)

    if matched:
        return QuerySafetyResult(
            allowed=False,
            blocked=True,
            reason="prompt_injection",
            required_action="reject",
            route_candidate="reject",
            confidence=0.98,
            matched_signals=matched,
        )

    if client_context:
        context_text = " ".join(str(value) for value in client_context.values() if value not in (None, "", [], {}, ()))
        if any(marker in context_text.lower() for marker in ("system prompt", "developer message", "jailbreak")):
            return QuerySafetyResult(
                allowed=False,
                blocked=True,
                reason="unsafe_context_payload",
                required_action="reject",
                route_candidate="reject",
                confidence=0.96,
                matched_signals=["client_context"],
            )

    return QuerySafetyResult(
        allowed=True,
        blocked=False,
        reason="safe",
        required_action="direct_answer",
        route_candidate=None,
        confidence=0.5,
        matched_signals=[],
    )
