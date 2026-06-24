"""Unified configuration for the local life agent runtime.

All engineering and budget parameters are centralized here.
Never hardcode these values in implementation code.

Backend configuration supports env-var override for each item
so the same binary can switch between mock (test/dev) and
java_api (staging/production) without code changes.
"""

import os


def _env_str(key: str, default: str) -> str:
    return os.environ.get(key, default)


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, str(default)))
    except (ValueError, TypeError):
        return default


def _env_bool(key: str, default: bool) -> bool:
    val = os.environ.get(key)
    if val is None:
        return default
    return val.lower() in ("1", "true", "yes", "on")


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
LLM_CONFIDENCE_THRESHOLD = 0.8
SEMANTIC_FALLBACK_ENABLED = True
ENABLE_LLM_VERBALIZER = False
LLM_VERBALIZER_FALLBACK_TO_TEMPLATE = True

# --- LLM Config File (.env) ---
# The config file lives at <project_root>/config/.env.
# Format: KEY=VALUE lines (standard .env format).
# Lines starting with # are comments; blank lines are ignored.
# Values here override environment variables.
# The LLM_API_KEY env var is used as fallback if the key is empty in the file.
_CONFIG_DIR = os.path.join(os.path.dirname(__file__), "config")
_DOTENV_PATH = os.path.join(_CONFIG_DIR, ".env")


def _parse_dotenv(path: str) -> dict[str, str]:
    """Parse a .env file into a dict. No external dependency needed."""
    if "PYTEST_CURRENT_TEST" in os.environ:
        return {}
    result: dict[str, str] = {}
    try:
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip()
                # Strip surrounding quotes if present
                if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                    val = val[1:-1]
                if key:
                    result[key] = val
    except (FileNotFoundError, OSError):
        pass
    return result


def load_llm_api_key() -> str:
    """Read API key from config/.env (LLM_API_KEY), falling back to env var LLM_API_KEY."""
    cfg = _parse_dotenv(_DOTENV_PATH)
    key = cfg.get("LLM_API_KEY", "")
    if key:
        return key
    env_name = os.environ.get("REAL_LLM_API_KEY_ENV", "LLM_API_KEY")
    return os.environ.get(env_name, os.environ.get("LLM_API_KEY", ""))


def load_llm_config_value(key: str) -> str:
    """Read an LLM config value from config/.env (provider/model/endpoint)."""
    cfg = _parse_dotenv(_DOTENV_PATH)
    return cfg.get(key, "")


def _llm_cfg_str(primary_key: str, fallback_key: str, default: str) -> str:
    file_value = load_llm_config_value(primary_key) or load_llm_config_value(fallback_key)
    if file_value:
        return file_value
    return _env_str(primary_key, _env_str(fallback_key, default))


def _llm_cfg_bool(primary_key: str, fallback_key: str, default: bool) -> bool:
    raw = load_llm_config_value(primary_key) or load_llm_config_value(fallback_key)
    if raw:
        return raw.lower() in ("1", "true", "yes", "on")
    return _env_bool(primary_key, _env_bool(fallback_key, default))


def _llm_cfg_int(primary_key: str, fallback_key: str, default: int) -> int:
    raw = load_llm_config_value(primary_key) or load_llm_config_value(fallback_key)
    if raw:
        try:
            return int(raw)
        except (ValueError, TypeError):
            return default
    return _env_int(primary_key, _env_int(fallback_key, default))


# --- LLM Backend Selection ---
# Accepted values: "rule_based", "fake_llm", "real_llm"
# "rule_based" = pure rule-based backend (default, no real LLM call)
# "fake_llm"   = injected fake backend for tests
# "real_llm"   = connected to a real LLM provider (OpenAI-compatible)
LOCAL_LIFE_LLM_BACKEND: str = _llm_cfg_str("LOCAL_LIFE_LLM_BACKEND", "LLM_BACKEND", "rule_based")
LLM_BACKEND: str = LOCAL_LIFE_LLM_BACKEND
if LLM_BACKEND not in ("rule_based", "fake_llm", "real_llm"):
    raise ValueError(
        f"LLM_BACKEND={LLM_BACKEND!r} is invalid. "
        "Accepted values: 'rule_based', 'fake_llm', 'real_llm'."
    )

ENABLE_REAL_LLM: bool = _llm_cfg_bool("ENABLE_REAL_LLM", "LLM_ENABLED", False)
LLM_ENABLED: bool = ENABLE_REAL_LLM

REAL_LLM_PROVIDER: str = _llm_cfg_str("REAL_LLM_PROVIDER", "LLM_PROVIDER", "")
LLM_PROVIDER: str = REAL_LLM_PROVIDER

REAL_LLM_MODEL: str = _llm_cfg_str("REAL_LLM_MODEL", "LLM_MODEL", "")
LLM_MODEL: str = REAL_LLM_MODEL

REAL_LLM_ENDPOINT: str = _llm_cfg_str("REAL_LLM_ENDPOINT", "LLM_ENDPOINT", "")
LLM_ENDPOINT: str = REAL_LLM_ENDPOINT

REAL_LLM_TIMEOUT_SECONDS: int = _llm_cfg_int("REAL_LLM_TIMEOUT_SECONDS", "LLM_TIMEOUT_SECONDS", 20)
LLM_TIMEOUT_SECONDS: int = REAL_LLM_TIMEOUT_SECONDS
LLM_TIMEOUT_MS: int = _llm_cfg_int("REAL_LLM_TIMEOUT_MS", "LLM_TIMEOUT_MS", REAL_LLM_TIMEOUT_SECONDS * 1000)

REAL_LLM_API_KEY_ENV: str = _llm_cfg_str("REAL_LLM_API_KEY_ENV", "REAL_LLM_API_KEY_ENV", "LLM_API_KEY")

ENABLE_LLM_VERBALIZER = _llm_cfg_bool("ENABLE_LLM_VERBALIZER", "ENABLE_LLM_VERBALIZER", False)
ENABLE_LLM_TOOL_PLANNER = _llm_cfg_bool("ENABLE_LLM_TOOL_PLANNER", "ENABLE_LLM_TOOL_PLANNER", False)

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

# ====================================================================
# Tool Backend (14.5 — mock ↔ java_api switch)
# ====================================================================
# Accepted values: "mock", "java_api"
# Any other value triggers a ValueError at import time.
# Default: "mock" — ensures existing tests keep passing.
# Override via: LOCAL_LIFE_TOOL_BACKEND
_TOOL_BACKEND_RAW = _env_str("LOCAL_LIFE_TOOL_BACKEND", "db")
if _TOOL_BACKEND_RAW not in ("mock", "java_api", "db"):
    raise ValueError(
        f"LOCAL_LIFE_TOOL_BACKEND={_TOOL_BACKEND_RAW!r} is invalid. "
        "Accepted values: 'mock', 'java_api', 'db'."
    )
TOOL_BACKEND: str = _TOOL_BACKEND_RAW  # "mock" | "java_api"

# Java backend connection parameters (only used when TOOL_BACKEND="java_api")
JAVA_BACKEND_BASE_URL: str = _env_str("LOCAL_LIFE_JAVA_BASE_URL", "http://localhost:8081")
JAVA_BACKEND_TIMEOUT_MS: int = _env_int("LOCAL_LIFE_JAVA_TIMEOUT_MS", 3000)
JAVA_BACKEND_MAX_RETRIES: int = 1

# When True: if Java backend is unavailable the gateway may fall back
# to MockToolExecutor, marking the result as degraded+fallback_from.
# When False (default): Java failure → backend_unavailable, no mock.
ALLOW_TOOL_BACKEND_FALLBACK: bool = _env_bool("LOCAL_LIFE_ALLOW_TOOL_BACKEND_FALLBACK", False)

# === P2: Replan limits ===
# Maximum number of expand_search rounds before hard stop
MAX_EXPAND_SEARCH_ROUNDS: int = _env_int("LOCAL_LIFE_MAX_EXPAND_SEARCH", 1)
# Maximum number of replan_evidence rounds before hard stop
MAX_REPLAN_EVIDENCE_ROUNDS: int = _env_int("LOCAL_LIFE_MAX_REPLAN_EVIDENCE", 1)
