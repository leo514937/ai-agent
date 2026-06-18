from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class LocalLifeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)


class LocalLifeIntentType(str, Enum):
    RESTAURANT_RECOMMENDATION = "restaurant_recommendation"
    RESTAURANT_COMPARISON = "restaurant_comparison"
    COUPON = "coupon"
    DETAIL = "detail"
    BOOKING = "booking"
    ORDER_STATUS = "order_status"
    NAVIGATION = "navigation"
    CLARIFY = "clarify"


class ShopResolveResult(str, Enum):
    RESOLVED = "resolved"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"
    LOW_CONFIDENCE = "low_confidence"


class LocationNorm(LocalLifeModel):
    type: str = "near_user"
    city: str | None = None
    lat: float | None = None
    lng: float | None = None
    radius_km: float = 3.0


class TimeNorm(LocalLifeModel):
    type: str | None = None
    date: str | None = None
    meal_period: str | None = None
    preferred_time: str | None = None


class PriceNorm(LocalLifeModel):
    per_person_min: float | None = None
    per_person_max: float | None = None
    target: float | None = None


class QueryUnderstandingResult(LocalLifeModel):
    normalized_query: str
    semantic_query: str
    keyword_query: str
    time_norm: TimeNorm | None = None
    location_norm: LocationNorm | None = None
    rewritten_constraints: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    extra: dict[str, Any] = Field(default_factory=dict)


class LocalLifeSlots(LocalLifeModel):
    domain: str = "local_life"
    category: str | None = None
    city: str | None = None
    location: LocationNorm = Field(default_factory=LocationNorm)
    time: TimeNorm = Field(default_factory=TimeNorm)
    price: PriceNorm = Field(default_factory=PriceNorm)
    scene: str | None = None
    companions: list[str] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    action: LocalLifeIntentType | None = None
    tool_name: str | None = None
    tool_input: dict[str, Any] = Field(default_factory=dict)
    shop_query: str | None = None
    shop_ids: list[int] = Field(default_factory=list)
    page: str | None = None


class RequiredFacet(LocalLifeModel):
    name: str
    required: bool
    data_source: Literal[
        "slot",
        "static_rag",
        "dynamic_tool",
        "business_api",
        "memory",
        "client_context",
        "mixed",
    ]
    freshness: Literal["static_ok", "near_realtime_required"]
    entity_keys: list[str] = Field(default_factory=list)
    missing_policy: Literal[
        "partial_grounded",
        "ask_clarification",
        "no_answer",
    ]


class ContextRef(LocalLifeModel):
    type: str
    id: str | None = None
    name: str | None = None
    source: str
    confidence: float = 1.0


class UserNeed(LocalLifeModel):
    intent: str
    raw_query: str
    resolved_query: str
    slots: LocalLifeSlots
    constraints: dict[str, Any] = Field(default_factory=dict)
    required_facets: list[RequiredFacet] = Field(default_factory=list)
    optional_facets: list[RequiredFacet] = Field(default_factory=list)
    missing_slots: list[str] = Field(default_factory=list)
    context_refs: list[ContextRef] = Field(default_factory=list)
    recommendation_count: int = 3



class RouteExecutionRequirement(LocalLifeModel):
    required_facets: list[str] = Field(default_factory=list)
    execute_tools: list[str] = Field(default_factory=list)
    execute_rag: bool = False
    reference_needed: bool = False
    resolved_shop_id: int | None = None
    candidate_shop_ids: list[int] = Field(default_factory=list)


class RouteReviewResult(LocalLifeModel):
    reviewed_route: Any
    execution_requirements: RouteExecutionRequirement
    review_reason: str
    intercepted: bool = False
    clarification: ClarificationDecision | None = None
    reviewed_clarification: ClarificationDecision | None = None
    resolved_shop_id: int | None = None
    candidate_shop_ids: list[int] = Field(default_factory=list)


class ClarificationDecision(LocalLifeModel):
    need_clarification: bool = False
    question: str | None = None
    options: list[SuggestedReply] = Field(default_factory=list)
    ambiguity_type: str | None = None


class ShopTypeRecord(LocalLifeModel):
    id: int
    name: str
    icon: str | None = None
    sort: int = 0


class VoucherRecord(LocalLifeModel):
    id: int
    shop_id: int
    shop_name: str | None = None
    title: str
    sub_title: str | None = None
    rules: str | None = None
    pay_value: float | None = None
    actual_value: float | None = None
    stock: int | None = None
    begin_time: str | None = None
    end_time: str | None = None
    source: str = "catalog"


class BlogRecord(LocalLifeModel):
    id: int
    shop_id: int | None = None
    user_id: int | None = None
    title: str
    content: str
    liked: int = 0
    comments: int = 0
    source: str = "catalog"


class ShopRecord(LocalLifeModel):
    id: int
    name: str
    type_id: int | None = None
    type_name: str | None = None
    area: str | None = None
    address: str | None = None
    x: float | None = None
    y: float | None = None
    avg_price: float | None = None
    sold: int | None = None
    comments: int | None = None
    score: float | None = None
    open_hours: str | None = None
    image: str | None = None
    distance_km: float | None = None
    parking: bool = False
    quiet_score: float = 0.0
    family_friendly: bool = False
    elder_friendly: bool = False
    tags: list[str] = Field(default_factory=list)
    review_summary: str | None = None
    evidence_texts: list[str] = Field(default_factory=list)
    source: str = "catalog"


class EvidenceClaim(LocalLifeModel):
    chunk_id: str
    shop_id: int | None = None
    claim: str
    support_text: str
    source_type: str
    confidence: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class CandidateProfile(LocalLifeModel):
    shop_id: int
    name: str
    matched_requirements: list[str] = Field(default_factory=list)
    structured_features: dict[str, Any] = Field(default_factory=dict)
    evidence_features: dict[str, float] = Field(default_factory=dict)
    risk_flags: list[str] = Field(default_factory=list)
    explainable_reasons: list[str] = Field(default_factory=list)
    vouchers: list[dict[str, Any]] = Field(default_factory=list)
    blog_snippets: list[str] = Field(default_factory=list)
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    rank_score: float = 0.0


class RankedCandidate(CandidateProfile):
    pass


class CardAction(LocalLifeModel):
    type: str
    label: str
    payload: dict[str, Any] = Field(default_factory=dict)


class ShopCard(LocalLifeModel):
    type: Literal["shop_card"] = "shop_card"
    shop_id: int
    title: str
    subtitle: str
    badges: list[str] = Field(default_factory=list)
    reason: str
    actions: list[CardAction] = Field(default_factory=list)


class VoucherCard(LocalLifeModel):
    type: Literal["voucher_card"] = "voucher_card"
    voucher_id: int
    shop_id: int
    title: str
    subtitle: str | None = None
    pay_value: float | None = None
    actual_value: float | None = None
    stock: int | None = None
    rules: str | None = None
    actions: list[CardAction] = Field(default_factory=list)


class SuggestedReply(LocalLifeModel):
    label: str
    prompt: str


class LocalLifeResponseBundle(LocalLifeModel):
    answer_text: str
    mode: str
    source: str = "local-life-agent"
    source_mode: str | None = None
    degraded_reason: str | None = None
    knowledge_freshness: dict[str, Any] = Field(default_factory=dict)
    claim_bindings: list[dict[str, Any]] = Field(default_factory=list)
    fallback: bool = False
    page: str | None = None
    current_topic: str | None = None
    selected_shop_id: int | None = None
    route_decision: str | None = None
    route_reason: str | None = None
    current_stage: str | None = None
    stage_status: str | None = None
    stage_timeline: list[dict[str, Any]] = Field(default_factory=list)
    cards: list[dict[str, Any]] = Field(default_factory=list)
    shops: list[dict[str, Any]] = Field(default_factory=list)
    vouchers: list[dict[str, Any]] = Field(default_factory=list)
    suggested_replies: list[dict[str, Any]] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    task_chain: list[dict[str, Any]] = Field(default_factory=list)
    ranked_candidates: list[dict[str, Any]] = Field(default_factory=list)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    retrieval_summary: dict[str, Any] = Field(default_factory=dict)
    grounding_status: str = "not_grounded"
    confidence: float = 0.0
    approval_required: bool = False
    approval_request: dict[str, Any] = Field(default_factory=dict)
    transaction_draft: dict[str, Any] = Field(default_factory=dict)
    safety_result: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)


class LocalLifeTurnState(LocalLifeModel):
    trace_id: str
    session_id: str
    turn_id: str
    user_id: str
    page: str | None = None
    raw_query: str
    input_context: dict[str, Any] = Field(default_factory=dict)
    client_context: dict[str, Any] = Field(default_factory=dict)
    persistent_context: dict[str, Any] = Field(default_factory=dict)
    perception_context: dict[str, Any] = Field(default_factory=dict)
    memory_arbitration: dict[str, Any] = Field(default_factory=dict)
    understanding: QueryUnderstandingResult | None = None
    slots: LocalLifeSlots = Field(default_factory=LocalLifeSlots)
    clarification: ClarificationDecision = Field(default_factory=ClarificationDecision)
    intent: LocalLifeIntentType = LocalLifeIntentType.RESTAURANT_RECOMMENDATION
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    structured_candidates: list[ShopRecord] = Field(default_factory=list)
    evidence_claims: list[EvidenceClaim] = Field(default_factory=list)
    candidate_profiles: list[CandidateProfile] = Field(default_factory=list)
    ranked_candidates: list[RankedCandidate] = Field(default_factory=list)
    answer_text: str | None = None
    cards: list[dict[str, Any]] = Field(default_factory=list)
    suggested_replies: list[dict[str, Any]] = Field(default_factory=list)
    selected_shop_id: int | None = None
    mode: str = "recommend"
    source: str = "local-life-agent"
    current_topic: str | None = None
    route_decision: str | None = None
    route_reason: str | None = None
    current_stage: str | None = None
    stage_status: str | None = None
    stage_timeline: list[dict[str, Any]] = Field(default_factory=list)
    state_diff: dict[str, Any] = Field(default_factory=dict)
    illegal_state_mutation: list[dict[str, Any]] = Field(default_factory=list)
    node_writes: list[dict[str, Any]] = Field(default_factory=list)
    approval_required: bool = False
    approval_request: dict[str, Any] = Field(default_factory=dict)
    transaction_draft: dict[str, Any] = Field(default_factory=dict)
    safety_result: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    raw_result: dict[str, Any] = Field(default_factory=dict)
    user_need: UserNeed | None = None
    route_review: RouteReviewResult | None = None


class CandidateShop(LocalLifeModel):
    shop_id: int | None = None
    canonical_name: str
    matched_text: str | None = None
    match_type: Literal["exact", "alias", "session", "client", "pronoun", "fuzzy"] = "fuzzy"
    score: float = 0.0

class SemanticSelectionResult(LocalLifeModel):
    follow_up_kind: str = "none"
    anchor_shop_id: int | None = None
    comparison_targets: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float = 0.0

ClarificationDecision.model_rebuild()
RouteReviewResult.model_rebuild()
