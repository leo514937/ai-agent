from __future__ import annotations

from enum import Enum


class StrValueEnum(str, Enum):
    """String enum base with stable serialized values."""

    def __str__(self) -> str:
        return str(self.value)


class TurnDecision(StrValueEnum):
    CLARIFY = "clarify"
    DIRECT_ANSWER = "direct_answer"
    RETRIEVE_THEN_ANSWER = "retrieve_then_answer"
    TOOL_THEN_ANSWER = "tool_then_answer"


class RagStatus(StrValueEnum):
    OK = "ok"
    DEGRADED = "degraded"
    EMPTY = "empty"


class ToolExecutionStatus(StrValueEnum):
    SKIPPED = "skipped"
    PENDING_APPROVAL = "pending_approval"
    SUCCESS = "success"
    DEGRADED = "degraded"
    FAILED = "failed"
    REJECTED = "rejected"


class OutputStyle(StrValueEnum):
    BRIEF = "brief"
    DETAILED = "detailed"
    COMPARISON = "comparison"
    GUIDED = "guided"


class IntentType(StrValueEnum):
    EXPLAIN = "explain"
    COMPARE = "compare"
    RECOMMEND = "recommend"
    SUMMARY = "summary"
    FOLLOW_UP = "follow_up"


class PolarityType(StrValueEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    SKEPTICAL = "skeptical"
    NEGATIVE_QUESTION = "negative_question"


class NegativeScopeType(StrValueEnum):
    ACTION = "action"
    SHOP = "shop"
    CATEGORY = "category"
    PRICE = "price"
    DISTANCE = "distance"
    FEATURE = "feature"
    COMPARISON_TARGET = "comparison_target"


class TargetType(StrValueEnum):
    SHOP = "shop"
    BRAND = "brand"
    CATEGORY = "category"
    MALL = "mall"
    AREA = "area"
    DISH = "dish"
    PREVIOUS_CANDIDATE = "previous_candidate"
    AMBIGUOUS = "ambiguous"


class LocalRouteType(StrValueEnum):
    RECOMMENDATION = "recommendation"
    COMPARISON = "comparison"
    SINGLE_SHOP = "single_shop"
    REALTIME_TOOL = "realtime_tool"
    MERCHANT_REASONING = "merchant_reasoning"
    TRANSACTION = "transaction"
    LOCAL_CHAT = "local_chat"
    CLARIFY = "clarify"
