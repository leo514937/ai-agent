"""Core global enumerations for the local life agent."""

from enum import Enum


class TopIntent(str, Enum):
    local_life = "local_life"
    capability = "capability"
    chat = "chat"
    invalid = "invalid"
    unsafe = "unsafe"
    out_of_scope = "out_of_scope"


class TaskType(str, Enum):
    recommendation = "recommendation"
    single_shop_query = "single_shop_query"
    coupon_query = "coupon_query"  # @deprecated — Use single_shop_query + facets=[coupon]; normalized in route_task()
    comparison = "comparison"
    clarification_reply = "clarification_reply"
    general_chat = "general_chat"


class Facet(str, Enum):
    nearby = "nearby"
    coupon = "coupon"
    discount = "discount"
    group_buy = "group_buy"
    cost_performance = "cost_performance"
    open_status = "open_status"
    open_now = "open_now"
    open_late = "open_late"
    reservation_available = "reservation_available"
    queue_status = "queue_status"
    distance = "distance"
    business_area = "business_area"
    travel_time = "travel_time"
    price = "price"
    avg_price = "avg_price"
    budget = "budget"
    budget_around_x = "budget_around_x"
    price_compare = "price_compare"
    rating = "rating"
    category = "category"
    restaurant = "restaurant"
    hotpot = "hotpot"
    coffee = "coffee"
    dessert = "dessert"
    parent_child = "parent_child"
    entertainment = "entertainment"
    shopping = "shopping"
    environment = "environment"
    taste = "taste"
    service = "service"
    review_summary = "review_summary"
    review_tags = "review_tags"
    popularity = "popularity"
    scene_fit = "scene_fit"
    date_scene = "date_scene"
    family_with_kids = "family_with_kids"
    friends_party = "friends_party"
    quiet = "quiet"
    lively = "lively"
    business_meeting = "business_meeting"
    work_study = "work_study"
    late_night = "late_night"
    not_too_noisy = "not_too_noisy"
    kid_friendly = "kid_friendly"
    parking = "parking"
    private_room = "private_room"
    spicy = "spicy"
    light_food = "light_food"
    vegetarian = "vegetarian"
    current_shop = "current_shop"
    ordinal_reference = "ordinal_reference"
    previous_recommendation = "previous_recommendation"
    comparison_targets = "comparison_targets"


class ToolResultStatus(str, Enum):
    ok = "ok"
    partial = "partial"
    empty = "empty"
    unknown = "unknown"
    failed = "failed"
    error = "error"
    timeout = "timeout"
    unsupported = "unsupported"
    circuit_open = "circuit_open"
    backend_unavailable = "backend_unavailable"


class RefineAction(str, Enum):
    """Normalised follow-up refinement actions from the semantic parser.

    These values are used in ``follow_up.refine_action`` to express
    *what* the user is asking for in a follow-up turn.  The parser
    prompt defines these explicitly so the LLM picks from a fixed set
    instead of inventing synonyms.

    Allowed values:
        - ``cheaper``: user wants a lower price
        - ``closer``: user wants a shorter distance
        - ``higher_rating``: user wants a better rating/score
        - ``better_environment``: user wants better environment
        - ``better_taste``: user wants better taste/flavour
        - ``coupon_lookup``: user is asking about coupons
        - ``open_status_lookup``: user is asking about open hours/status
        - ``distance_lookup``: user is asking about distance/ETA
        - ``comparison``: user wants to compare candidates
        - ``select_candidate``: user selects a candidate (\"first one\", \"this one\")
        - ``restart``: user explicitly wants a fresh start / new direction
        - ``other``: any refinement that doesn't fit the above
    """
    cheaper = "cheaper"
    closer = "closer"
    higher_rating = "higher_rating"
    better_environment = "better_environment"
    better_taste = "better_taste"
    coupon_lookup = "coupon_lookup"
    open_status_lookup = "open_status_lookup"
    distance_lookup = "distance_lookup"
    comparison = "comparison"
    select_candidate = "select_candidate"
    restart = "restart"
    other = "other"


class ErrorCode(str, Enum):
    TOOL_TIMEOUT = "TOOL_TIMEOUT"
    NETWORK_ERROR = "NETWORK_ERROR"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"
    BACKEND_UNAVAILABLE = "BACKEND_UNAVAILABLE"
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    SHOP_NOT_FOUND = "SHOP_NOT_FOUND"
    AMBIGUOUS_SHOP = "AMBIGUOUS_SHOP"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    TOOL_NOT_REGISTERED = "TOOL_NOT_REGISTERED"
    TOOL_UNSUPPORTED = "TOOL_UNSUPPORTED"
    SCHEMA_VALIDATION_FAILED = "SCHEMA_VALIDATION_FAILED"
    LLM_JSON_PARSE_ERROR = "LLM_JSON_PARSE_ERROR"
    LLM_ENUM_OUT_OF_RANGE = "LLM_ENUM_OUT_OF_RANGE"
    ANSWER_VERIFIER_FAILED = "ANSWER_VERIFIER_FAILED"
