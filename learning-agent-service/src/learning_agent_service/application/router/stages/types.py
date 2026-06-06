from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


# ==========================================
# Stage 1: Hard Guard Types
# ==========================================

@dataclass
class HardGuardResult:
    blocked: bool
    reason: str | None = None
    required_action: str | None = None
    route_candidate: str | None = None


# ==========================================
# Stage 2: Signal Policy Types
# ==========================================

@dataclass
class IntentCandidate:
    intent_name: str
    confidence: float
    route: str
    matched_signal: str
    slots: dict[str, Any] = field(default_factory=dict)
    preferred_chunk_roles: list[str] = field(default_factory=list)
    tool_candidates: list[str] = field(default_factory=list)
    missing_slots: list[str] = field(default_factory=list)


@dataclass
class MerchantMatch:
    merchant_name: str
    merchant_id: str | None
    match_type: Literal["exact", "fuzzy", "alias"]
    confidence: float


@dataclass
class PronounMatch:
    pronoun: str
    reference_type: Literal["this", "that", "next", "previous", "ordinal"]
    ordinal: int | None = None  # 第几个
    confidence: float = 0.0


@dataclass
class SignalPolicyResult:
    candidates: list[IntentCandidate] = field(default_factory=list)
    top_confidence: float = 0.0
    matched_signals: list[str] = field(default_factory=list)
    merchant_hit: MerchantMatch | None = None
    pronoun_hit: PronounMatch | None = None
    conflict_resolution: str | None = None


# ==========================================
# Stage 3: LLM Parser Types
# ==========================================

@dataclass
class LLMTargetShop:
    shop_name: str | None
    reference_type: Literal["explicit", "pronoun_inherit", "context_inherit", "none"]
    clarify_if_missing: bool


@dataclass
class LLMParserResult:
    intent: str
    confidence: float
    slots: dict[str, Any] = field(default_factory=dict)
    facet_needs: list[str] = field(default_factory=list)
    needs_rag: bool = False
    needs_tool: bool = False
    needs_clarify: bool = False
    target_shop: LLMTargetShop | None = None
    reason: str = ""
    raw_llm_output: dict[str, Any] | None = None
    missing_slots: list[str] = field(default_factory=list)


# ==========================================
# Stage 4: Target Resolution Types
# ==========================================

@dataclass
class ResolvedTarget:
    shop_id: str | None = None
    shop_name: str | None = None
    confidence: float = 0.0
    source: Literal["explicit", "candidate_selection", "pronoun_inherit", "context_inherit", "none"] = "none"
    resolved_references: list[str] = field(default_factory=list)
    missing: bool = False
    clarification_question: str | None = None
