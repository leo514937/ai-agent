"""Unified configuration for the local life agent runtime.

All engineering and budget parameters are centralized here.
Never hardcode these values in implementation code.
"""

# --- Concurrency & Deadline ---
MAX_CONCURRENCY = 8
DEADLINE_MS = 6000
MAX_TOOL_CALLS = 40

# --- Search & Recommendation ---
SEARCH_LIMIT = 20
RECOMMENDATION_CANDIDATE_TOP_K = 8
RECOMMENDATION_FINAL_TOP_K = 3
RECOMMENDATION_ENRICH_TOOLS = [
    "get_shop_detail",
    "check_open_status",
    "get_coupon_list",
]

# --- Comparison ---
COMPARISON_FULL_DETAIL_SHOP_LIMIT = 3
COMPARISON_FOCUSED_SHOP_LIMIT = 5
COMPARISON_MAX_SHOP_LIMIT = 5

# --- LLM ---
LLM_TIMEOUT_MS = 3000
LLM_CONFIDENCE_THRESHOLD = 0.8
SEMANTIC_FALLBACK_ENABLED = True

# --- Tools ---
TOOL_DEFAULT_TIMEOUT_MS = 2000

# --- Rewrite ---
MAX_REWRITE_ATTEMPTS = 2

# --- Clarification ---
CLARIFICATION_TTL_SECONDS = 300

# --- Mock Data ---
MOCK_LOCATION = {"name": "北京邮电大学", "lat": 39.9609, "lng": 116.3581}

# --- Debug ---
DEBUG_ENABLED = True  # Set to False in production
