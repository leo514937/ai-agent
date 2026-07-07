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


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, str(default)))
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
ENABLE_LLM_VERBALIZER = True

# --- LLM Config File (.env) ---
# The config file lives at <project_root>/config/.env.
# Format: KEY=VALUE lines (standard .env format).
# Lines starting with # are comments; blank lines are ignored.
# Values here override environment variables.
# The LLM_API_KEY env var is used as fallback if the key is empty in the file.
_CONFIG_DIR = os.path.join(os.path.dirname(__file__), "config")
_DOTENV_PATH = os.path.join(_CONFIG_DIR, ".env")


def _parse_dotenv(path: str) -> dict[str, str]:
    """Parse a .env file into a dict. No external dependency needed.

    Under pytest the file is skipped by default so tests stay fast.
    Set ``LOCAL_LIFE_TEST_LLM=1`` to re-enable real LLM config for
    acceptance / smoke-test runs.
    """
    if "PYTEST_CURRENT_TEST" in os.environ and os.environ.get("LOCAL_LIFE_TEST_LLM") != "1":
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
# "rule_based" = offline fallback only, never the normal happy path
# "fake_llm"   = injected fake backend for tests
# "real_llm"   = connected to a real LLM provider (OpenAI-compatible)
LOCAL_LIFE_LLM_BACKEND: str = _llm_cfg_str("LOCAL_LIFE_LLM_BACKEND", "LLM_BACKEND", "real_llm")
LLM_BACKEND: str = LOCAL_LIFE_LLM_BACKEND
if LLM_BACKEND not in ("rule_based", "fake_llm", "real_llm"):
    raise ValueError(
        f"LLM_BACKEND={LLM_BACKEND!r} is invalid. "
        "Accepted values: 'rule_based', 'fake_llm', 'real_llm'."
    )

ENABLE_REAL_LLM: bool = _llm_cfg_bool("ENABLE_REAL_LLM", "LLM_ENABLED", True)
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

ENABLE_LLM_VERBALIZER = _llm_cfg_bool("ENABLE_LLM_VERBALIZER", "ENABLE_LLM_VERBALIZER", True)

# --- Tools ---
TOOL_DEFAULT_TIMEOUT_MS = 2000

# --- Rewrite ---
MAX_REWRITE_ATTEMPTS = 2

# --- Clarification ---
CLARIFICATION_TTL_SECONDS = 300

# --- Session Store ---
SESSION_STORE_BACKEND: str = _env_str("LOCAL_LIFE_SESSION_STORE_BACKEND", "memory")
SESSION_REDIS_URL: str = _env_str("LOCAL_LIFE_SESSION_REDIS_URL", _env_str("REDIS_URL", "redis://localhost:6379/0"))
SESSION_REDIS_KEY_PREFIX: str = _env_str("LOCAL_LIFE_SESSION_REDIS_KEY_PREFIX", "local_life:session")
SESSION_REDIS_MAX_CONNECTIONS: int = _env_int("LOCAL_LIFE_SESSION_REDIS_MAX_CONNECTIONS", 10)
SESSION_REDIS_SOCKET_TIMEOUT_SECONDS: float = _env_float("LOCAL_LIFE_SESSION_REDIS_SOCKET_TIMEOUT_SECONDS", 2.0)
SESSION_REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS: float = _env_float("LOCAL_LIFE_SESSION_REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS", 2.0)
SESSION_TTL_CONVERSATION_CONTEXT_SECONDS: int = _env_int("LOCAL_LIFE_SESSION_TTL_CONVERSATION_CONTEXT_SECONDS", 1800)
SESSION_TTL_FOCUS_CONTEXT_SECONDS: int = _env_int("LOCAL_LIFE_SESSION_TTL_FOCUS_CONTEXT_SECONDS", 1800)
SESSION_TTL_RECOMMENDATION_CONTEXT_SECONDS: int = _env_int("LOCAL_LIFE_SESSION_TTL_RECOMMENDATION_CONTEXT_SECONDS", 600)
SESSION_TTL_COMPARISON_CONTEXT_SECONDS: int = _env_int("LOCAL_LIFE_SESSION_TTL_COMPARISON_CONTEXT_SECONDS", 600)
SESSION_TTL_PENDING_CLARIFICATION_SECONDS: int = _env_int("LOCAL_LIFE_SESSION_TTL_PENDING_CLARIFICATION_SECONDS", 300)
SESSION_TTL_USER_PREFERENCE_SUMMARY_SECONDS: int = _env_int("LOCAL_LIFE_SESSION_TTL_USER_PREFERENCE_SUMMARY_SECONDS", 86400)
SESSION_TTL_EXECUTION_COUNTERS_SECONDS: int = _env_int("LOCAL_LIFE_SESSION_TTL_EXECUTION_COUNTERS_SECONDS", 300)
SESSION_TTL_DEFAULT_SECONDS: int = _env_int("LOCAL_LIFE_SESSION_TTL_DEFAULT_SECONDS", SESSION_TTL_CONVERSATION_CONTEXT_SECONDS)

# --- Mock Data ---
MOCK_LOCATION = {"name": "北京邮电大学", "lat": 39.9609, "lng": 116.3581}

# --- Database ---
DB_HOST: str = _env_str("LOCAL_LIFE_DB_HOST", "localhost")
DB_PORT: int = _env_int("LOCAL_LIFE_DB_PORT", 3306)
DB_NAME: str = _env_str("LOCAL_LIFE_DB_NAME", "hmdp")
DB_USER: str = _env_str("LOCAL_LIFE_DB_USER", "root")
DB_PASSWORD: str = _env_str("LOCAL_LIFE_DB_PASSWORD", "123456")

# --- Debug ---
DEBUG_ENABLED = True  # Set to False in production

# ====================================================================
# Tool Backend
# ====================================================================
# Accepted values: "db", "java_api"
# Override via: LOCAL_LIFE_TOOL_BACKEND
_TOOL_BACKEND_RAW = _env_str("LOCAL_LIFE_TOOL_BACKEND", "db")
if _TOOL_BACKEND_RAW not in ("db", "java_api"):
    raise ValueError(
        f"LOCAL_LIFE_TOOL_BACKEND={_TOOL_BACKEND_RAW!r} is invalid. "
        "Accepted values: 'db', 'java_api'."
    )
TOOL_BACKEND: str = _TOOL_BACKEND_RAW  # "db" | "java_api"

# Java backend connection parameters (only used when TOOL_BACKEND="java_api")
JAVA_BACKEND_BASE_URL: str = _env_str("LOCAL_LIFE_JAVA_BASE_URL", "http://localhost:8081")
JAVA_BACKEND_TIMEOUT_MS: int = _env_int("LOCAL_LIFE_JAVA_TIMEOUT_MS", 3000)
JAVA_BACKEND_MAX_RETRIES: int = 1

# === P2: Replan limits ===
# Maximum number of expand_search rounds before hard stop
MAX_EXPAND_SEARCH_ROUNDS: int = _env_int("LOCAL_LIFE_MAX_EXPAND_SEARCH", 1)
# Maximum number of replan_evidence rounds before hard stop
MAX_REPLAN_EVIDENCE_ROUNDS: int = _env_int("LOCAL_LIFE_MAX_REPLAN_EVIDENCE", 1)
