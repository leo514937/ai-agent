from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

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


class LocationNorm(LocalLifeModel):
    type: str = "near_user"
    city: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    radius_km: float = 3.0


class TimeNorm(LocalLifeModel):
    type: Optional[str] = None
    date: Optional[str] = None
    meal_period: Optional[str] = None
    preferred_time: Optional[str] = None


class PriceNorm(LocalLifeModel):
    per_person_min: Optional[float] = None
    per_person_max: Optional[float] = None
    target: Optional[float] = None


class QueryUnderstandingResult(LocalLifeModel):
    normalized_query: str
    semantic_query: str
    keyword_query: str
    time_norm: Optional[TimeNorm] = None
    location_norm: Optional[LocationNorm] = None
    rewritten_constraints: List[str] = Field(default_factory=list)
    confidence: float = 0.0
    extra: Dict[str, Any] = Field(default_factory=dict)


class LocalLifeSlots(LocalLifeModel):
    domain: str = "local_life"
    category: Optional[str] = None
    city: Optional[str] = None
    location: LocationNorm = Field(default_factory=LocationNorm)
    time: TimeNorm = Field(default_factory=TimeNorm)
    price: PriceNorm = Field(default_factory=PriceNorm)
    scene: Optional[str] = None
    companions: List[str] = Field(default_factory=list)
    preferences: List[str] = Field(default_factory=list)
    avoid: List[str] = Field(default_factory=list)
    action: Optional[LocalLifeIntentType] = None
    tool_name: Optional[str] = None
    tool_input: Dict[str, Any] = Field(default_factory=dict)
    shop_query: Optional[str] = None
    shop_ids: List[int] = Field(default_factory=list)
    page: Optional[str] = None


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
    entity_keys: List[str] = Field(default_factory=list)
    missing_policy: Literal[
        "partial_grounded",
        "ask_clarification",
        "no_answer",
    ]


class ContextRef(LocalLifeModel):
    type: str
    id: Optional[str] = None
    name: Optional[str] = None
    source: str
    confidence: float = 1.0


class UserNeed(LocalLifeModel):
    intent: str
    raw_query: str
    resolved_query: str
    slots: LocalLifeSlots
    constraints: Dict[str, Any] = Field(default_factory=dict)
    required_facets: List[RequiredFacet] = Field(default_factory=list)
    optional_facets: List[RequiredFacet] = Field(default_factory=list)
    missing_slots: List[str] = Field(default_factory=list)
    context_refs: List[ContextRef] = Field(default_factory=list)
    recommendation_count: int = 3



class RouteExecutionRequirement(LocalLifeModel):
    required_facets: List[str] = Field(default_factory=list)
    execute_tools: List[str] = Field(default_factory=list)
    execute_rag: bool = False
    reference_needed: bool = False
    resolved_shop_id: Optional[int] = None
    candidate_shop_ids: List[int] = Field(default_factory=list)


class RouteReviewResult(LocalLifeModel):
    reviewed_route: Any
    execution_requirements: RouteExecutionRequirement
    review_reason: str
    intercepted: bool = False
    clarification: Optional[ClarificationDecision] = None
    reviewed_clarification: Optional[ClarificationDecision] = None
    resolved_shop_id: Optional[int] = None
    candidate_shop_ids: List[int] = Field(default_factory=list)


class ClarificationDecision(LocalLifeModel):
    need_clarification: bool = False
    question: Optional[str] = None
    options: List["SuggestedReply"] = Field(default_factory=list)
    ambiguity_type: Optional[str] = None


class ShopTypeRecord(LocalLifeModel):
    id: int
    name: str
    icon: Optional[str] = None
    sort: int = 0


class VoucherRecord(LocalLifeModel):
    id: int
    shop_id: int
    shop_name: Optional[str] = None
    title: str
    sub_title: Optional[str] = None
    rules: Optional[str] = None
    pay_value: Optional[float] = None
    actual_value: Optional[float] = None
    stock: Optional[int] = None
    begin_time: Optional[str] = None
    end_time: Optional[str] = None
    source: str = "catalog"


class BlogRecord(LocalLifeModel):
    id: int
    shop_id: Optional[int] = None
    user_id: Optional[int] = None
    title: str
    content: str
    liked: int = 0
    comments: int = 0
    source: str = "catalog"


class ShopRecord(LocalLifeModel):
    id: int
    name: str
    type_id: Optional[int] = None
    type_name: Optional[str] = None
    area: Optional[str] = None
    address: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None
    avg_price: Optional[float] = None
    sold: Optional[int] = None
    comments: Optional[int] = None
    score: Optional[float] = None
    open_hours: Optional[str] = None
    image: Optional[str] = None
    distance_km: Optional[float] = None
    parking: bool = False
    quiet_score: float = 0.0
    family_friendly: bool = False
    elder_friendly: bool = False
    tags: List[str] = Field(default_factory=list)
    review_summary: Optional[str] = None
    evidence_texts: List[str] = Field(default_factory=list)
    source: str = "catalog"


class EvidenceClaim(LocalLifeModel):
    chunk_id: str
    shop_id: Optional[int] = None
    claim: str
    support_text: str
    source_type: str
    confidence: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CandidateProfile(LocalLifeModel):
    shop_id: int
    name: str
    matched_requirements: List[str] = Field(default_factory=list)
    structured_features: Dict[str, Any] = Field(default_factory=dict)
    evidence_features: Dict[str, float] = Field(default_factory=dict)
    risk_flags: List[str] = Field(default_factory=list)
    explainable_reasons: List[str] = Field(default_factory=list)
    vouchers: List[Dict[str, Any]] = Field(default_factory=list)
    blog_snippets: List[str] = Field(default_factory=list)
    score_breakdown: Dict[str, float] = Field(default_factory=dict)
    rank_score: float = 0.0


class RankedCandidate(CandidateProfile):
    pass


class CardAction(LocalLifeModel):
    type: str
    label: str
    payload: Dict[str, Any] = Field(default_factory=dict)


class ShopCard(LocalLifeModel):
    type: Literal["shop_card"] = "shop_card"
    shop_id: int
    title: str
    subtitle: str
    badges: List[str] = Field(default_factory=list)
    reason: str
    actions: List[CardAction] = Field(default_factory=list)


class VoucherCard(LocalLifeModel):
    type: Literal["voucher_card"] = "voucher_card"
    voucher_id: int
    shop_id: int
    title: str
    subtitle: Optional[str] = None
    pay_value: Optional[float] = None
    actual_value: Optional[float] = None
    stock: Optional[int] = None
    rules: Optional[str] = None
    actions: List[CardAction] = Field(default_factory=list)


class SuggestedReply(LocalLifeModel):
    label: str
    prompt: str


class LocalLifeResponseBundle(LocalLifeModel):
    answer_text: str
    mode: str
    source: str = "local-life-agent"
    source_mode: Optional[str] = None
    degraded_reason: Optional[str] = None
    knowledge_freshness: Dict[str, Any] = Field(default_factory=dict)
    fallback: bool = False
    page: Optional[str] = None
    current_topic: Optional[str] = None
    selected_shop_id: Optional[int] = None
    route_decision: Optional[str] = None
    route_reason: Optional[str] = None
    current_stage: Optional[str] = None
    stage_status: Optional[str] = None
    stage_timeline: List[Dict[str, Any]] = Field(default_factory=list)
    cards: List[Dict[str, Any]] = Field(default_factory=list)
    shops: List[Dict[str, Any]] = Field(default_factory=list)
    vouchers: List[Dict[str, Any]] = Field(default_factory=list)
    suggested_replies: List[Dict[str, Any]] = Field(default_factory=list)
    next_steps: List[str] = Field(default_factory=list)
    task_chain: List[Dict[str, Any]] = Field(default_factory=list)
    ranked_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    citations: List[Dict[str, Any]] = Field(default_factory=list)
    retrieval_summary: Dict[str, Any] = Field(default_factory=dict)
    grounding_status: str = "not_grounded"
    confidence: float = 0.0
    approval_required: bool = False
    approval_request: Dict[str, Any] = Field(default_factory=dict)
    transaction_draft: Dict[str, Any] = Field(default_factory=dict)
    safety_result: Dict[str, Any] = Field(default_factory=dict)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    context: Dict[str, Any] = Field(default_factory=dict)


class LocalLifeTurnState(LocalLifeModel):
    trace_id: str
    session_id: str
    turn_id: str
    user_id: str
    page: Optional[str] = None
    raw_query: str
    client_context: Dict[str, Any] = Field(default_factory=dict)
    persistent_context: Dict[str, Any] = Field(default_factory=dict)
    understanding: Optional[QueryUnderstandingResult] = None
    slots: LocalLifeSlots = Field(default_factory=LocalLifeSlots)
    clarification: ClarificationDecision = Field(default_factory=ClarificationDecision)
    intent: LocalLifeIntentType = LocalLifeIntentType.RESTAURANT_RECOMMENDATION
    tool_results: List[Dict[str, Any]] = Field(default_factory=list)
    structured_candidates: List[ShopRecord] = Field(default_factory=list)
    evidence_claims: List[EvidenceClaim] = Field(default_factory=list)
    candidate_profiles: List[CandidateProfile] = Field(default_factory=list)
    ranked_candidates: List[RankedCandidate] = Field(default_factory=list)
    answer_text: Optional[str] = None
    cards: List[Dict[str, Any]] = Field(default_factory=list)
    suggested_replies: List[Dict[str, Any]] = Field(default_factory=list)
    selected_shop_id: Optional[int] = None
    mode: str = "recommend"
    source: str = "local-life-agent"
    current_topic: Optional[str] = None
    route_decision: Optional[str] = None
    route_reason: Optional[str] = None
    current_stage: Optional[str] = None
    stage_status: Optional[str] = None
    stage_timeline: List[Dict[str, Any]] = Field(default_factory=list)
    approval_required: bool = False
    approval_request: Dict[str, Any] = Field(default_factory=dict)
    transaction_draft: Dict[str, Any] = Field(default_factory=dict)
    safety_result: Dict[str, Any] = Field(default_factory=dict)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    raw_result: Dict[str, Any] = Field(default_factory=dict)
    user_need: Optional[UserNeed] = None
    route_review: Optional[RouteReviewResult] = None


ClarificationDecision.model_rebuild()
RouteReviewResult.model_rebuild()
