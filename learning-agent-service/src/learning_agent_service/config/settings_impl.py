"""Environment-driven settings for the standalone learning agent service.

The module keeps a small compatibility surface for early integration:
- ``Settings`` / ``ServiceSettings`` remain available.
- ``get_settings`` remains memoized.
- Nested settings classes can be imported directly by infrastructure factories.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, model_validator

if TYPE_CHECKING:
    from pydantic_settings import BaseSettings, SettingsConfigDict
else:
    try:
        from pydantic_settings import BaseSettings, SettingsConfigDict
    except Exception:  # pragma: no cover - optional at authoring time
        BaseSettings = BaseModel
        SettingsConfigDict = dict


SERVICE_ROOT = Path(__file__).resolve().parents[3]
PROJECT_ROOT = SERVICE_ROOT.parent
# 优先级：进程环境 > 服务目录 .env > 项目根目录 .env
ENV_FILE_CANDIDATES = (
    str(PROJECT_ROOT / ".env"),
    str(SERVICE_ROOT / ".env"),
)


@lru_cache(maxsize=1)
def _load_env_file_values(env_files: tuple[str, ...]) -> dict[str, str]:
    values: dict[str, str] = {}
    for file_path in env_files:
        path = Path(file_path)
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8-sig")
        except OSError:
            continue
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export ") :].lstrip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not key:
                continue
            value = value.strip()
            if value and value[0] == value[-1] and value[0] in {'"', "'"}:
                value = value[1:-1]
            values[key] = value
    return values


def _env_file_value(name: str) -> str | None:
    return _load_env_file_values(ENV_FILE_CANDIDATES).get(name)


def _env(name: str, default: Any) -> Any:
    value = os.getenv(name)
    if value is None or value == "":
        file_value = _env_file_value(name)
        if file_value is None or file_value == "":
            return default
        return file_value
    return value


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        file_value = _env_file_value(name)
        if file_value is None or file_value == "":
            return default
        value = file_value
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_any(names: tuple[str, ...], default: Any) -> Any:
    for name in names:
        value = os.getenv(name)
        if value is not None and value != "":
            return value
        file_value = _env_file_value(name)
        if file_value is not None and file_value != "":
            return file_value
    return default


def _env_bool_any(names: tuple[str, ...], default: bool) -> bool:
    value = _env_any(names, None)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _env_csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        file_value = _env_file_value(name)
        if file_value is None or file_value.strip() == "":
            return default
        value = file_value
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _unique_nonempty_strings(*values: Any) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return tuple(ordered)


class AppSettings(BaseModel):
    service_name: str = "local-life-agent-service"
    environment: str = "development"
    debug: bool = False
    workflow_version: str = "local-life-agent/v1"
    request_timeout_seconds: float = 30.0
    prefer_real_adapters: bool = True
    allow_in_memory_fallback: bool = True


class PostgresSettings(BaseModel):
    dsn: str = ""
    echo: bool = False
    pool_size: int = 5
    max_overflow: int = 10
    pool_pre_ping: bool = True


class RedisSettings(BaseModel):
    url: str = "redis://localhost:6379/0"
    socket_timeout_seconds: int = 5
    key_prefix: str = "learn"
    session_ttl_seconds: int = 86400
    summary_ttl_seconds: int = 86400
    clarification_ttl_seconds: int = 3600
    tool_cache_ttl_seconds: int = 900
    embedding_cache_ttl_seconds: int = 86400


class QdrantSettings(BaseModel):
    url: str = "http://localhost:6333"
    api_key: str = ""
    timeout_seconds: int = 5
    prefer_grpc: bool = False
    knowledge_collection: str = "local_life_hybrid_chunks"
    local_life_hybrid_collection: str = "local_life_hybrid_chunks"
    local_life_parent_child_collection: str = "local_life_parent_child_chunks"
    memory_collection: str = "user_semantic_memory"
    user_memory_collection: str = "user_semantic_memory"
    memory_vector_name: str = "embedding"
    memory_vector_size: int | None = 4096
    memory_distance: str = "cosine"
    knowledge_vector_name: str = "embedding"
    knowledge_sparse_vector_name: str = "sparse_embedding"
    knowledge_vector_size: int | None = 4096
    knowledge_distance: str = "cosine"

    @model_validator(mode="after")
    def _validate_collection_roles(self) -> QdrantSettings:
        role_names = {
            "local_life_hybrid_collection": self.local_life_hybrid_collection,
            "local_life_parent_child_collection": self.local_life_parent_child_collection,
            "memory_collection": self.memory_collection,
        }
        normalized: dict[str, str] = {}
        duplicates: list[str] = []
        for role, value in role_names.items():
            text = str(value or "").strip()
            if not text:
                continue
            key = text.lower()
            if key in normalized:
                duplicates.append(f"{role}={text} duplicates {normalized[key]}")
                continue
            normalized[key] = f"{role}={text}"
        if duplicates:
            raise ValueError(
                "Qdrant collection roles must use distinct collection names; "
                + "; ".join(duplicates)
            )
        return self


class EmbeddingSettings(BaseModel):
    memory_provider: str = "openai"
    memory_model: str = "qwen-embedding-8b"


class MemoryRecallSettings(BaseModel):
    episodic_keywords: tuple[str, ...] = Field(default_factory=tuple)
    procedural_keywords: tuple[str, ...] = Field(default_factory=tuple)
    same_session_boost: float = 0.2
    current_topic_boost: float = 0.15
    history_summary_boost: float = 0.1
    active_plan_boost: float = 0.25
    final_summary_boost: float = 0.2
    recency_window_seconds: int = 60 * 60 * 24 * 7
    episodic_threshold: float = 0.55
    procedural_threshold: float = 0.5
    top_k: int = 5
    token_budget: int = 1200


class OpenAISettings(BaseModel):
    api_key: str = ""
    api_key_candidates: tuple[str, ...] = Field(default_factory=tuple)
    base_url: str = ""
    organization: str | None = None
    project: str | None = None
    timeout_seconds: int = 30
    max_retries: int = 2
    responses_model: str = "gpt-5.4"
    embedding_model: str = "qwen-embedding-8b"
    embedding_model_version: str = ""


class ObservabilitySettings(BaseModel):
    log_level: str = "INFO"
    json_logs: bool = True
    include_caller: bool = False
    outbox_batch_size: int = 100
    outbox_poll_interval_seconds: float = 1.0
    outbox_max_attempts: int = 10


class HybridRouterSettings(BaseSettings):
    """混合路由器配置"""
    model_config = SettingsConfigDict(
        env_prefix="LEARNING_AGENT_",
        env_file=ENV_FILE_CANDIDATES,
        env_file_encoding="utf-8",
        extra="ignore",
    )
    
    # LLM配置
    enable_hybrid_router_llm: bool = True  # 是否启用LLM路由
    hybrid_router_llm_model: str = "gpt-4o-mini"  # LLM模型
    hybrid_router_llm_timeout: float = 5.0  # LLM超时（秒）
    hybrid_router_llm_max_retries: int = 2  # LLM最大重试次数
    
    # 缓存配置
    hybrid_router_cache_ttl: int = 300  # 缓存TTL（秒）
    hybrid_router_cache_size: int = 1000  # 缓存大小
    
    # 降级配置
    hybrid_router_fallback_confidence_threshold: float = 0.5  # 降级阈值
    
    # 监控配置
    hybrid_router_enable_trace: bool = True  # 启用路由追踪
    
    # 流量控制配置（灰度发布）
    hybrid_router_traffic_percentage: float = 100.0  # LLM路由流量百分比（0-100）
    hybrid_router_rollout_stage: str = "full"  # 灰度阶段：disabled/testing/canary/progressive/full


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE_CANDIDATES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "local-life-agent-service"
    environment: str = "development"
    debug: bool = False
    workflow_version: str = "local-life-agent/v1"
    api_prefix: str = "/internal/v1"
    default_response_mode: str = "detailed"
    internal_api_token: str = ""
    java_business_base_url: str = ""
    java_business_internal_token: str = ""
    java_business_timeout_seconds: float = 5.0
    java_business_enable_fallback: bool = True
    local_life_candidate_limit: int = 5
    local_life_default_radius_km: float = 3.0
    prefer_real_adapters: bool = True
    allow_in_memory_fallback: bool = True
    workflow_checkpoint_enabled: bool = True
    workflow_checkpoint_sqlite_path: str = "var/langgraph/checkpoints.sqlite"
    local_life_use_langgraph: bool = True
    local_life_require_langgraph_in_test: bool = True
    local_life_trace_enabled: bool = True
    local_life_answer_linter_enabled: bool = True
    local_life_golden_cases_required: bool = True
    enable_route_review: bool = True
    enable_required_facets: bool = True
    enable_required_facets_to_plans: bool = True
    enable_min_entity_consistency_check: bool = True
    enable_trace_harness: bool = False
    enable_replay_harness: bool = False
    enable_tool_mock_harness: bool = False
    enable_rag_golden_evidence_harness: bool = False
    enable_evaluation_harness: bool = False
    enable_partial_grounded: bool = True
    enable_slot_clarify: bool = True
    enable_rag_plus_tool_partial_answer: bool = True
    enable_task_plan_for_local_life: bool = True
    enable_answer_verifier: bool = True
    answer_verifier_mode: str = "warn_only"
    enable_online_dense_retrieval: bool = True
    enable_online_sparse_retrieval: bool = True
    enable_bm25_sparse_retrieval: bool = True
    enable_remote_reranker: bool = True
    reranker_provider: str = "remote"
    enable_llm_query_rewrite: bool = True
    enable_rag: bool = False
    enable_hyde_sparse_retrieval: bool = False
    llm_query_rewrite_min_query_length: int = 6
    llm_query_rewrite_low_confidence_threshold: float = 0.5
    llm_query_rewrite_model: str = ""
    llm_query_rewrite_temperature: float = 0.0
    hyde_sparse_retrieval_model: str = ""
    hyde_sparse_retrieval_temperature: float = 0.0
    intent_confidence_threshold: float = 0.5
    reference_resolution_confidence_threshold: float = 0.5
    metadata_filter_confidence_threshold: float = 0.5
    bm25_k1: float = 1.5
    bm25_b: float = 0.75
    remote_reranker_endpoint: str = ""
    remote_reranker_api_key: str = ""
    remote_reranker_model: str = ""
    remote_reranker_timeout_seconds: float = 10.0
    memory_retrieval_prompt_limit: int = 4
    memory_retrieval_state_limit: int = 6
    memory_retrieval_rag_limit: int = 6
    memory_retrieval_tool_limit: int = 4
    memory_retrieval_token_budget: int = 1200
    memory_retrieval_semantic_top_k: int = 5
    memory_retrieval_episodic_keywords: tuple[str, ...] = (
        "debug",
        "troubleshoot",
        "troubleshooting",
        "排错",
        "故障",
        "implementation",
        "实现",
        "problem",
    )
    memory_retrieval_procedural_keywords: tuple[str, ...] = (
        "how-to",
        "how to",
        "workflow",
        "tool",
        "步骤",
        "流程",
        "怎么",
        "如何",
        "debug",
        "implementation",
    )
    memory_recall: MemoryRecallSettings = Field(default_factory=MemoryRecallSettings)
    memory_injection_prompt_limit: int = 4
    memory_injection_state_limit: int = 8
    memory_injection_tool_limit: int = 4
    memory_injection_rag_limit: int = 6
    memory_injection_semantic_limit: int = 6
    memory_injection_episodic_limit: int = 3
    memory_injection_procedural_limit: int = 3
    memory_injection_token_budget: int = 1200

    app: AppSettings = Field(default_factory=AppSettings)
    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    qdrant: QdrantSettings = Field(default_factory=QdrantSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    openai: OpenAISettings = Field(default_factory=OpenAISettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    hybrid_router: HybridRouterSettings = Field(default_factory=HybridRouterSettings)

    dense_top_k: int = 10
    sparse_top_k: int = 8
    metadata_top_k: int = 8
    fusion_top_k: int = 15
    rrf_k: int = 60
    rrf_dense_weight: float = 1.0
    rrf_sparse_weight: float = 1.0
    rrf_metadata_weight: float = 0.6
    rerank_top_k: int = 8
    evidence_top_n: int = 5
    evidence_min_n: int = 4
    low_score_threshold: float = 0.55
    evidence_strong_score_threshold: float = 0.45
    topic_consistency_threshold: float = 0.35
    dedup_similarity_threshold: float = 0.82
    rewrite_retry_limit: int = 1
    memory_governance_low_confidence_threshold: float = 0.35
    memory_governance_low_stability_threshold: float = 0.45
    memory_conflict_supersede_margin: float = 0.05
    memory_conflict_merge_similarity_threshold: float = 0.65
    memory_promotion_preference_promote_count: int = 3
    consolidation_minimum_duplicate_group_size: int = 2
    consolidation_max_conflicts: int = 8
    consolidation_confirmed_explicitness: float = 1.0
    consolidation_inferred_explicitness: float = 0.5
    consolidation_recency_window_seconds: int = 60 * 60 * 24 * 7
    orchestrator_confirmed_confidence_threshold: float = 0.8

    def __init__(self, **data: Any) -> None:
        app_name = data.pop("app_name", _env("LEARNING_AGENT_SERVICE_NAME", "local-life-agent-service"))
        environment = data.pop("environment", _env("LEARNING_AGENT_ENV", "development"))
        debug = data.pop("debug", _env_bool("LEARNING_AGENT_DEBUG", False))
        workflow_version = data.pop("workflow_version", _env("LEARNING_AGENT_WORKFLOW_VERSION", "local-life-agent/v1"))
        internal_api_token = data.pop("internal_api_token", _env("LEARNING_AGENT_INTERNAL_API_TOKEN", "")) or ""
        java_business_base_url = data.pop(
            "java_business_base_url",
            _env("LEARNING_AGENT_JAVA_BUSINESS_BASE_URL", ""),
        ) or ""
        java_business_internal_token = data.pop(
            "java_business_internal_token",
            _env("LEARNING_AGENT_JAVA_BUSINESS_INTERNAL_TOKEN", ""),
        ) or ""
        if not java_business_internal_token:
            java_business_internal_token = internal_api_token
        java_business_timeout_seconds = float(
            data.pop(
                "java_business_timeout_seconds",
                _env("LEARNING_AGENT_JAVA_BUSINESS_TIMEOUT_SECONDS", 5.0),
            )
        )
        java_business_enable_fallback = bool(
            data.pop(
                "java_business_enable_fallback",
                _env_bool("LEARNING_AGENT_JAVA_BUSINESS_ENABLE_FALLBACK", True),
            )
        )
        local_life_candidate_limit = int(
            data.pop(
                "local_life_candidate_limit",
                _env("LEARNING_AGENT_LOCAL_LIFE_CANDIDATE_LIMIT", 5),
            )
        )
        local_life_default_radius_km = float(
            data.pop(
                "local_life_default_radius_km",
                _env("LEARNING_AGENT_LOCAL_LIFE_DEFAULT_RADIUS_KM", 3.0),
            )
        )
        request_timeout_seconds = float(
            data.pop("request_timeout_seconds", _env("LEARNING_AGENT_REQUEST_TIMEOUT_SECONDS", 30.0))
        )
        prefer_real_adapters = bool(
            data.pop("prefer_real_adapters", _env_bool("LEARNING_AGENT_PREFER_REAL_ADAPTERS", True))
        )
        allow_in_memory_fallback = bool(
            data.pop("allow_in_memory_fallback", _env_bool("LEARNING_AGENT_ALLOW_IN_MEMORY_FALLBACK", True))
        )
        workflow_checkpoint_enabled = bool(
            data.pop(
                "workflow_checkpoint_enabled",
                _env_bool("LEARNING_AGENT_WORKFLOW_CHECKPOINT_ENABLED", True),
            )
        )
        workflow_checkpoint_sqlite_path = (
            data.pop(
                "workflow_checkpoint_sqlite_path",
                _env("LEARNING_AGENT_WORKFLOW_CHECKPOINT_SQLITE_PATH", "var/langgraph/checkpoints.sqlite"),
            )
            or "var/langgraph/checkpoints.sqlite"
        )
        local_life_use_langgraph = bool(
            data.pop(
                "local_life_use_langgraph",
                _env_bool_any(
                    ("LEARNING_AGENT_LOCAL_LIFE_USE_LANGGRAPH", "LOCAL_LIFE_USE_LANGGRAPH"),
                    True,
                ),
            )
        )
        local_life_require_langgraph_in_test = bool(
            data.pop(
                "local_life_require_langgraph_in_test",
                _env_bool_any(
                    ("LEARNING_AGENT_LOCAL_LIFE_REQUIRE_LANGGRAPH_IN_TEST", "LOCAL_LIFE_REQUIRE_LANGGRAPH_IN_TEST"),
                    True,
                ),
            )
        )
        local_life_trace_enabled = bool(
            data.pop(
                "local_life_trace_enabled",
                _env_bool_any(("LEARNING_AGENT_LOCAL_LIFE_TRACE_ENABLED", "LOCAL_LIFE_TRACE_ENABLED"), True),
            )
        )
        local_life_answer_linter_enabled = bool(
            data.pop(
                "local_life_answer_linter_enabled",
                _env_bool_any(
                    ("LEARNING_AGENT_LOCAL_LIFE_ANSWER_LINTER_ENABLED", "LOCAL_LIFE_ANSWER_LINTER_ENABLED"),
                    True,
                ),
            )
        )
        local_life_golden_cases_required = bool(
            data.pop(
                "local_life_golden_cases_required",
                _env_bool_any(
                    ("LEARNING_AGENT_LOCAL_LIFE_GOLDEN_CASES_REQUIRED", "LOCAL_LIFE_GOLDEN_CASES_REQUIRED"),
                    True,
                ),
            )
        )
        enable_route_review = bool(
            data.pop("enable_route_review", _env_bool("LEARNING_AGENT_ENABLE_ROUTE_REVIEW", True))
        )
        enable_required_facets = bool(
            data.pop("enable_required_facets", _env_bool("LEARNING_AGENT_ENABLE_REQUIRED_FACETS", True))
        )
        enable_required_facets_to_plans = bool(
            data.pop(
                "enable_required_facets_to_plans",
                _env_bool("LEARNING_AGENT_ENABLE_REQUIRED_FACETS_TO_PLANS", True),
            )
        )
        enable_min_entity_consistency_check = bool(
            data.pop(
                "enable_min_entity_consistency_check",
                _env_bool("LEARNING_AGENT_ENABLE_MIN_ENTITY_CONSISTENCY_CHECK", True),
            )
        )
        enable_trace_harness = bool(
            data.pop("enable_trace_harness", _env_bool("LEARNING_AGENT_ENABLE_TRACE_HARNESS", False))
        )
        enable_replay_harness = bool(
            data.pop("enable_replay_harness", _env_bool("LEARNING_AGENT_ENABLE_REPLAY_HARNESS", False))
        )
        enable_tool_mock_harness = bool(
            data.pop("enable_tool_mock_harness", _env_bool("LEARNING_AGENT_ENABLE_TOOL_MOCK_HARNESS", False))
        )
        enable_rag_golden_evidence_harness = bool(
            data.pop(
                "enable_rag_golden_evidence_harness",
                _env_bool("LEARNING_AGENT_ENABLE_RAG_GOLDEN_EVIDENCE_HARNESS", False),
            )
        )
        enable_evaluation_harness = bool(
            data.pop("enable_evaluation_harness", _env_bool("LEARNING_AGENT_ENABLE_EVALUATION_HARNESS", False))
        )
        enable_partial_grounded = bool(
            data.pop("enable_partial_grounded", _env_bool("LEARNING_AGENT_ENABLE_PARTIAL_GROUNDED", True))
        )
        enable_slot_clarify = bool(
            data.pop("enable_slot_clarify", _env_bool("LEARNING_AGENT_ENABLE_SLOT_CLARIFY", True))
        )
        enable_rag_plus_tool_partial_answer = bool(
            data.pop(
                "enable_rag_plus_tool_partial_answer",
                _env_bool("LEARNING_AGENT_ENABLE_RAG_PLUS_TOOL_PARTIAL_ANSWER", True),
            )
        )
        enable_task_plan_for_local_life = bool(
            data.pop(
                "enable_task_plan_for_local_life",
                _env_bool("LEARNING_AGENT_ENABLE_TASK_PLAN_FOR_LOCAL_LIFE", True),
            )
        )
        enable_answer_verifier = bool(
            data.pop("enable_answer_verifier", _env_bool("LEARNING_AGENT_ENABLE_ANSWER_VERIFIER", True))
        )
        answer_verifier_mode = str(
            data.pop("answer_verifier_mode", _env("LEARNING_AGENT_ANSWER_VERIFIER_MODE", "warn_only"))
        ).strip().lower() or "warn_only"
        enable_online_dense_retrieval = bool(
            data.pop("enable_online_dense_retrieval", _env_bool("LEARNING_AGENT_ENABLE_ONLINE_DENSE_RETRIEVAL", True))
        )
        enable_online_sparse_retrieval = bool(
            data.pop("enable_online_sparse_retrieval", _env_bool("LEARNING_AGENT_ENABLE_ONLINE_SPARSE_RETRIEVAL", True))
        )
        enable_bm25_sparse_retrieval = bool(
            data.pop("enable_bm25_sparse_retrieval", _env_bool("LEARNING_AGENT_ENABLE_BM25_SPARSE_RETRIEVAL", True))
        )
        enable_remote_reranker = bool(
            data.pop("enable_remote_reranker", _env_bool("LEARNING_AGENT_ENABLE_REMOTE_RERANKER", True))
        )
        reranker_provider = str(data.pop("reranker_provider", _env("LEARNING_AGENT_RERANKER_PROVIDER", "remote")) or "").strip().lower()
        enable_llm_query_rewrite = bool(
            data.pop("enable_llm_query_rewrite", _env_bool("LEARNING_AGENT_ENABLE_LLM_QUERY_REWRITE", True))
        )
        enable_rag = bool(
            data.pop("enable_rag", _env_bool("LEARNING_AGENT_ENABLE_RAG", False))
        )
        enable_hyde_sparse_retrieval = bool(
            data.pop("enable_hyde_sparse_retrieval", _env_bool("LEARNING_AGENT_ENABLE_HYDE_SPARSE_RETRIEVAL", False))
        )
        llm_query_rewrite_min_query_length = int(
            data.pop(
                "llm_query_rewrite_min_query_length",
                _env("LEARNING_AGENT_LLM_QUERY_REWRITE_MIN_QUERY_LENGTH", 6),
            )
        )
        llm_query_rewrite_low_confidence_threshold = float(
            data.pop(
                "llm_query_rewrite_low_confidence_threshold",
                _env("LEARNING_AGENT_LLM_QUERY_REWRITE_LOW_CONFIDENCE_THRESHOLD", 0.5),
            )
        )
        llm_query_rewrite_model = data.pop("llm_query_rewrite_model", _env("LEARNING_AGENT_LLM_QUERY_REWRITE_MODEL", "")) or ""
        llm_query_rewrite_temperature = float(
            data.pop(
                "llm_query_rewrite_temperature",
                _env("LEARNING_AGENT_LLM_QUERY_REWRITE_TEMPERATURE", 0.0),
            )
        )
        hyde_sparse_retrieval_model = data.pop(
            "hyde_sparse_retrieval_model",
            _env("LEARNING_AGENT_HYDE_SPARSE_RETRIEVAL_MODEL", ""),
        ) or ""
        hyde_sparse_retrieval_temperature = float(
            data.pop(
                "hyde_sparse_retrieval_temperature",
                _env("LEARNING_AGENT_HYDE_SPARSE_RETRIEVAL_TEMPERATURE", 0.0),
            )
        )
        intent_confidence_threshold = float(
            data.pop(
                "intent_confidence_threshold",
                _env("LEARNING_AGENT_INTENT_CONFIDENCE_THRESHOLD", 0.5),
            )
        )
        reference_resolution_confidence_threshold = float(
            data.pop(
                "reference_resolution_confidence_threshold",
                _env("LEARNING_AGENT_REFERENCE_RESOLUTION_CONFIDENCE_THRESHOLD", 0.5),
            )
        )
        metadata_filter_confidence_threshold = float(
            data.pop(
                "metadata_filter_confidence_threshold",
                _env("LEARNING_AGENT_METADATA_FILTER_CONFIDENCE_THRESHOLD", 0.5),
            )
        )
        bm25_k1 = float(data.pop("bm25_k1", _env("LEARNING_AGENT_BM25_K1", 1.5)))
        bm25_b = float(data.pop("bm25_b", _env("LEARNING_AGENT_BM25_B", 0.75)))
        rrf_dense_weight = float(data.pop("rrf_dense_weight", _env("LEARNING_AGENT_RRF_DENSE_WEIGHT", 1.0)))
        rrf_sparse_weight = float(data.pop("rrf_sparse_weight", _env("LEARNING_AGENT_RRF_SPARSE_WEIGHT", 1.0)))
        rrf_metadata_weight = float(data.pop("rrf_metadata_weight", _env("LEARNING_AGENT_RRF_METADATA_WEIGHT", 0.6)))
        fusion_top_k = int(data.pop("fusion_top_k", _env("LEARNING_AGENT_FUSION_TOP_K", 15)))
        remote_reranker_endpoint = data.pop(
            "remote_reranker_endpoint",
            _env("LEARNING_AGENT_REMOTE_RERANKER_ENDPOINT", ""),
        ) or ""
        remote_reranker_api_key = data.pop(
            "remote_reranker_api_key",
            _env("LEARNING_AGENT_REMOTE_RERANKER_API_KEY", ""),
        ) or ""
        remote_reranker_model = data.pop(
            "remote_reranker_model",
            _env("LEARNING_AGENT_REMOTE_RERANKER_MODEL", ""),
        ) or ""
        remote_reranker_timeout_seconds = float(
            data.pop(
                "remote_reranker_timeout_seconds",
                _env("LEARNING_AGENT_REMOTE_RERANKER_TIMEOUT_SECONDS", 10.0),
            )
        )
        low_score_threshold = float(
            data.pop("low_score_threshold", _env("LEARNING_AGENT_LOW_SCORE_THRESHOLD", 0.55))
        )
        evidence_strong_score_threshold = float(
            data.pop(
                "evidence_strong_score_threshold",
                _env("LEARNING_AGENT_EVIDENCE_STRONG_SCORE_THRESHOLD", 0.45),
            )
        )
        topic_consistency_threshold = float(
            data.pop(
                "topic_consistency_threshold",
                _env("LEARNING_AGENT_TOPIC_CONSISTENCY_THRESHOLD", 0.35),
            )
        )
        dedup_similarity_threshold = float(
            data.pop(
                "dedup_similarity_threshold",
                _env("LEARNING_AGENT_DEDUP_SIMILARITY_THRESHOLD", 0.82),
            )
        )
        rewrite_retry_limit = int(data.pop("rewrite_retry_limit", _env("LEARNING_AGENT_REWRITE_RETRY_LIMIT", 1)))
        memory_retrieval_prompt_limit = int(
            data.pop(
                "memory_retrieval_prompt_limit",
                _env("LEARNING_AGENT_MEMORY_RETRIEVAL_PROMPT_LIMIT", 4),
            )
        )
        memory_retrieval_state_limit = int(
            data.pop(
                "memory_retrieval_state_limit",
                _env("LEARNING_AGENT_MEMORY_RETRIEVAL_STATE_LIMIT", 6),
            )
        )
        memory_retrieval_rag_limit = int(
            data.pop(
                "memory_retrieval_rag_limit",
                _env("LEARNING_AGENT_MEMORY_RETRIEVAL_RAG_LIMIT", 6),
            )
        )
        memory_retrieval_tool_limit = int(
            data.pop(
                "memory_retrieval_tool_limit",
                _env("LEARNING_AGENT_MEMORY_RETRIEVAL_TOOL_LIMIT", 4),
            )
        )
        memory_retrieval_token_budget = int(
            data.pop(
                "memory_retrieval_token_budget",
                _env("LEARNING_AGENT_MEMORY_RETRIEVAL_TOKEN_BUDGET", 1200),
            )
        )
        memory_retrieval_semantic_top_k = int(
            data.pop(
                "memory_retrieval_semantic_top_k",
                _env("LEARNING_AGENT_MEMORY_RETRIEVAL_SEMANTIC_TOP_K", 5),
            )
        )
        memory_retrieval_episodic_keywords = tuple(
            data.pop(
                "memory_retrieval_episodic_keywords",
                _env_csv(
                    "LEARNING_AGENT_MEMORY_RETRIEVAL_EPISODIC_KEYWORDS",
                    (
                        "debug",
                        "troubleshoot",
                        "troubleshooting",
                        "排错",
                        "故障",
                        "implementation",
                        "实现",
                        "problem",
                    ),
                ),
            )
        )
        memory_retrieval_procedural_keywords = tuple(
            data.pop(
                "memory_retrieval_procedural_keywords",
                _env_csv(
                    "LEARNING_AGENT_MEMORY_RETRIEVAL_PROCEDURAL_KEYWORDS",
                    (
                        "how-to",
                        "how to",
                        "workflow",
                        "tool",
                        "步骤",
                        "流程",
                        "怎么",
                        "如何",
                        "debug",
                        "implementation",
                    ),
                ),
            )
        )
        memory_recall_episodic_keywords = tuple(
            data.pop(
                "memory_recall_episodic_keywords",
                _env_csv(
                    "LEARNING_AGENT_MEMORY_RECALL_EPISODIC_KEYWORDS",
                    memory_retrieval_episodic_keywords,
                ),
            )
        )
        memory_recall_procedural_keywords = tuple(
            data.pop(
                "memory_recall_procedural_keywords",
                _env_csv(
                    "LEARNING_AGENT_MEMORY_RECALL_PROCEDURAL_KEYWORDS",
                    memory_retrieval_procedural_keywords,
                ),
            )
        )
        memory_recall_same_session_boost = float(
            data.pop(
                "memory_recall_same_session_boost",
                _env("LEARNING_AGENT_MEMORY_RECALL_SAME_SESSION_BOOST", 0.2),
            )
        )
        memory_recall_current_topic_boost = float(
            data.pop(
                "memory_recall_current_topic_boost",
                _env("LEARNING_AGENT_MEMORY_RECALL_CURRENT_TOPIC_BOOST", 0.15),
            )
        )
        memory_recall_history_summary_boost = float(
            data.pop(
                "memory_recall_history_summary_boost",
                _env("LEARNING_AGENT_MEMORY_RECALL_HISTORY_SUMMARY_BOOST", 0.1),
            )
        )
        memory_recall_active_plan_boost = float(
            data.pop(
                "memory_recall_active_plan_boost",
                _env("LEARNING_AGENT_MEMORY_RECALL_ACTIVE_PLAN_BOOST", 0.25),
            )
        )
        memory_recall_final_summary_boost = float(
            data.pop(
                "memory_recall_final_summary_boost",
                _env("LEARNING_AGENT_MEMORY_RECALL_FINAL_SUMMARY_BOOST", 0.2),
            )
        )
        memory_recall_recency_window_seconds = int(
            data.pop(
                "memory_recall_recency_window_seconds",
                _env("LEARNING_AGENT_MEMORY_RECALL_RECENCY_WINDOW_SECONDS", 60 * 60 * 24 * 7),
            )
        )
        memory_recall_episodic_threshold = float(
            data.pop(
                "memory_recall_episodic_threshold",
                _env("LEARNING_AGENT_MEMORY_RECALL_EPISODIC_THRESHOLD", 0.55),
            )
        )
        memory_recall_procedural_threshold = float(
            data.pop(
                "memory_recall_procedural_threshold",
                _env("LEARNING_AGENT_MEMORY_RECALL_PROCEDURAL_THRESHOLD", 0.5),
            )
        )
        memory_recall_top_k = int(
            data.pop(
                "memory_recall_top_k",
                _env("LEARNING_AGENT_MEMORY_RECALL_TOP_K", 5),
            )
        )
        memory_recall_token_budget = int(
            data.pop(
                "memory_recall_token_budget",
                _env("LEARNING_AGENT_MEMORY_RECALL_TOKEN_BUDGET", 1200),
            )
        )
        memory_injection_prompt_limit = int(
            data.pop(
                "memory_injection_prompt_limit",
                _env("LEARNING_AGENT_MEMORY_INJECTION_PROMPT_LIMIT", 4),
            )
        )
        memory_injection_state_limit = int(
            data.pop(
                "memory_injection_state_limit",
                _env("LEARNING_AGENT_MEMORY_INJECTION_STATE_LIMIT", 8),
            )
        )
        memory_injection_tool_limit = int(
            data.pop(
                "memory_injection_tool_limit",
                _env("LEARNING_AGENT_MEMORY_INJECTION_TOOL_LIMIT", 4),
            )
        )
        memory_injection_rag_limit = int(
            data.pop(
                "memory_injection_rag_limit",
                _env("LEARNING_AGENT_MEMORY_INJECTION_RAG_LIMIT", 6),
            )
        )
        memory_injection_semantic_limit = int(
            data.pop(
                "memory_injection_semantic_limit",
                _env("LEARNING_AGENT_MEMORY_INJECTION_SEMANTIC_LIMIT", 6),
            )
        )
        memory_injection_episodic_limit = int(
            data.pop(
                "memory_injection_episodic_limit",
                _env("LEARNING_AGENT_MEMORY_INJECTION_EPISODIC_LIMIT", 3),
            )
        )
        memory_injection_procedural_limit = int(
            data.pop(
                "memory_injection_procedural_limit",
                _env("LEARNING_AGENT_MEMORY_INJECTION_PROCEDURAL_LIMIT", 3),
            )
        )
        memory_injection_token_budget = int(
            data.pop(
                "memory_injection_token_budget",
                _env("LEARNING_AGENT_MEMORY_INJECTION_TOKEN_BUDGET", 1200),
            )
        )
        memory_governance_low_confidence_threshold = float(
            data.pop(
                "memory_governance_low_confidence_threshold",
                _env("LEARNING_AGENT_MEMORY_GOVERNANCE_LOW_CONFIDENCE_THRESHOLD", 0.35),
            )
        )
        memory_governance_low_stability_threshold = float(
            data.pop(
                "memory_governance_low_stability_threshold",
                _env("LEARNING_AGENT_MEMORY_GOVERNANCE_LOW_STABILITY_THRESHOLD", 0.45),
            )
        )
        memory_conflict_supersede_margin = float(
            data.pop(
                "memory_conflict_supersede_margin",
                _env("LEARNING_AGENT_MEMORY_CONFLICT_SUPERSEDE_MARGIN", 0.05),
            )
        )
        memory_conflict_merge_similarity_threshold = float(
            data.pop(
                "memory_conflict_merge_similarity_threshold",
                _env("LEARNING_AGENT_MEMORY_CONFLICT_MERGE_SIMILARITY_THRESHOLD", 0.65),
            )
        )
        memory_promotion_preference_promote_count = int(
            data.pop(
                "memory_promotion_preference_promote_count",
                _env("LEARNING_AGENT_MEMORY_PROMOTION_PREFERENCE_PROMOTE_COUNT", 3),
            )
        )
        consolidation_minimum_duplicate_group_size = int(
            data.pop(
                "consolidation_minimum_duplicate_group_size",
                _env("LEARNING_AGENT_CONSOLIDATION_MINIMUM_DUPLICATE_GROUP_SIZE", 2),
            )
        )
        consolidation_max_conflicts = int(
            data.pop(
                "consolidation_max_conflicts",
                _env("LEARNING_AGENT_CONSOLIDATION_MAX_CONFLICTS", 8),
            )
        )
        consolidation_confirmed_explicitness = float(
            data.pop(
                "consolidation_confirmed_explicitness",
                _env("LEARNING_AGENT_CONSOLIDATION_CONFIRMED_EXPLICITNESS", 1.0),
            )
        )
        consolidation_inferred_explicitness = float(
            data.pop(
                "consolidation_inferred_explicitness",
                _env("LEARNING_AGENT_CONSOLIDATION_INFERRED_EXPLICITNESS", 0.5),
            )
        )
        consolidation_recency_window_seconds = int(
            data.pop(
                "consolidation_recency_window_seconds",
                _env("LEARNING_AGENT_CONSOLIDATION_RECENCY_WINDOW_SECONDS", 60 * 60 * 24 * 7),
            )
        )
        orchestrator_confirmed_confidence_threshold = float(
            data.pop(
                "orchestrator_confirmed_confidence_threshold",
                _env("LEARNING_AGENT_ORCHESTRATOR_CONFIRMED_CONFIDENCE_THRESHOLD", 0.8),
            )
        )
        if not reranker_provider:
            reranker_provider = "remote" if enable_remote_reranker else "heuristic"
        if reranker_provider not in {"heuristic", "remote"}:
            reranker_provider = "heuristic"

        if "app" not in data:
            data["app"] = AppSettings(
                service_name=app_name,
                environment=environment,
                debug=debug,
                workflow_version=workflow_version,
                request_timeout_seconds=request_timeout_seconds,
                prefer_real_adapters=prefer_real_adapters,
                allow_in_memory_fallback=allow_in_memory_fallback,
            )

        if "postgres" not in data:
            data["postgres"] = PostgresSettings(
                dsn=data.pop("postgres_dsn", _env("LEARNING_AGENT_POSTGRES_DSN", "")) or "",
                echo=bool(data.pop("postgres_echo", _env_bool("LEARNING_AGENT_POSTGRES_ECHO", False))),
                pool_size=int(data.pop("postgres_pool_size", _env("LEARNING_AGENT_POSTGRES_POOL_SIZE", 5))),
                max_overflow=int(data.pop("postgres_max_overflow", _env("LEARNING_AGENT_POSTGRES_MAX_OVERFLOW", 10))),
                pool_pre_ping=bool(
                    data.pop("postgres_pool_pre_ping", _env_bool("LEARNING_AGENT_POSTGRES_POOL_PRE_PING", True))
                ),
            )

        if "redis" not in data:
            data["redis"] = RedisSettings(
                url=data.pop("redis_url", _env("LEARNING_AGENT_REDIS_URL", "redis://localhost:6379/0"))
                or "redis://localhost:6379/0",
                socket_timeout_seconds=int(
                    data.pop("redis_socket_timeout_seconds", _env("LEARNING_AGENT_REDIS_SOCKET_TIMEOUT_SECONDS", 5))
                ),
                key_prefix=data.pop("redis_key_prefix", _env("LEARNING_AGENT_REDIS_KEY_PREFIX", "learn")) or "learn",
                session_ttl_seconds=int(
                    data.pop("redis_session_ttl_seconds", _env("LEARNING_AGENT_REDIS_SESSION_TTL_SECONDS", 86400))
                ),
                summary_ttl_seconds=int(
                    data.pop("redis_summary_ttl_seconds", _env("LEARNING_AGENT_REDIS_SUMMARY_TTL_SECONDS", 86400))
                ),
                clarification_ttl_seconds=int(
                    data.pop("redis_clarification_ttl_seconds", _env("LEARNING_AGENT_REDIS_CLARIFICATION_TTL_SECONDS", 3600))
                ),
                tool_cache_ttl_seconds=int(
                    data.pop("redis_tool_cache_ttl_seconds", _env("LEARNING_AGENT_REDIS_TOOL_CACHE_TTL_SECONDS", 900))
                ),
            )

        if "qdrant" not in data:
            data["qdrant"] = QdrantSettings(
                url=data.pop("qdrant_url", _env("LEARNING_AGENT_QDRANT_URL", "http://localhost:6333"))
                or "http://localhost:6333",
                api_key=data.pop("qdrant_api_key", _env("LEARNING_AGENT_QDRANT_API_KEY", "")) or "",
                timeout_seconds=int(
                    data.pop("qdrant_timeout_seconds", _env("LEARNING_AGENT_QDRANT_TIMEOUT_SECONDS", 5))
                ),
                prefer_grpc=bool(data.pop("qdrant_prefer_grpc", _env_bool("LEARNING_AGENT_QDRANT_PREFER_GRPC", False))),
                knowledge_collection=(
                    data.pop(
                        "knowledge_collection",
                        _env("LEARNING_AGENT_QDRANT_KNOWLEDGE_COLLECTION", "local_life_hybrid_chunks"),
                    )
                    or "local_life_hybrid_chunks"
                ),
                local_life_hybrid_collection=(
                    data.pop(
                        "local_life_hybrid_collection",
                        _env("LEARNING_AGENT_QDRANT_LOCAL_LIFE_HYBRID_COLLECTION", "local_life_hybrid_chunks"),
                    )
                    or "local_life_hybrid_chunks"
                ),
                local_life_parent_child_collection=(
                    data.pop(
                        "local_life_parent_child_collection",
                        _env(
                            "LEARNING_AGENT_QDRANT_LOCAL_LIFE_PARENT_CHILD_COLLECTION",
                            "local_life_parent_child_chunks",
                        ),
                    )
                    or "local_life_parent_child_chunks"
                ),
                memory_collection=(
                    data.pop(
                        "memory_collection",
                        _env("LEARNING_AGENT_QDRANT_MEMORY_COLLECTION", _env("LEARNING_AGENT_QDRANT_USER_MEMORY_COLLECTION", "user_semantic_memory")),
                    )
                    or "user_semantic_memory"
                ),
                user_memory_collection=(
                    data.pop(
                        "user_memory_collection",
                        _env("LEARNING_AGENT_QDRANT_USER_MEMORY_COLLECTION", _env("LEARNING_AGENT_QDRANT_MEMORY_COLLECTION", "user_semantic_memory")),
                    )
                    or "user_semantic_memory"
                ),
                memory_vector_name=(
                    data.pop(
                        "memory_vector_name",
                        _env("LEARNING_AGENT_QDRANT_MEMORY_VECTOR_NAME", "embedding"),
                    )
                    or "embedding"
                ),
                memory_vector_size=(
                    int(
                        data.pop(
                            "memory_vector_size",
                            _env("LEARNING_AGENT_QDRANT_MEMORY_VECTOR_SIZE", 4096),
                        )
                    )
                ),
                memory_distance=(
                    data.pop(
                        "memory_distance",
                        _env("LEARNING_AGENT_QDRANT_MEMORY_DISTANCE", "cosine"),
                    )
                    or "cosine"
                ),
                knowledge_vector_name=(
                    data.pop("knowledge_vector_name", _env("LEARNING_AGENT_QDRANT_KNOWLEDGE_VECTOR_NAME", "embedding"))
                    or "embedding"
                ),
                knowledge_sparse_vector_name=(
                    data.pop(
                        "knowledge_sparse_vector_name",
                        _env("LEARNING_AGENT_QDRANT_KNOWLEDGE_SPARSE_VECTOR_NAME", "sparse_embedding"),
                    )
                    or "sparse_embedding"
                ),
                knowledge_vector_size=int(
                    data.pop(
                        "knowledge_vector_size",
                        _env("LEARNING_AGENT_QDRANT_KNOWLEDGE_VECTOR_SIZE", 4096),
                    )
                ),
                knowledge_distance=(
                    data.pop(
                        "knowledge_distance",
                        _env("LEARNING_AGENT_QDRANT_KNOWLEDGE_DISTANCE", "cosine"),
                    )
                    or "cosine"
                ),
            )

        if "embedding" not in data:
            memory_embedding_model = data.pop(
                "memory_embedding_model",
                _env_any(
                    (
                        "LEARNING_AGENT_MEMORY_EMBEDDING_MODEL",
                        "LEARNING_AGENT_OPENAI_EMBEDDING_MODEL",
                        "OPENAI_EMBEDDING_MODEL",
                    ),
                    "qwen-embedding-8b",
                ),
            ) or "qwen-embedding-8b"
            data["embedding"] = EmbeddingSettings(
                memory_provider=(
                    data.pop(
                        "memory_embedding_provider",
                        _env("LEARNING_AGENT_MEMORY_EMBEDDING_PROVIDER", "openai"),
                    )
                    or "openai"
                ),
                memory_model=memory_embedding_model,
            )

        if "memory_recall" not in data:
            data["memory_recall"] = MemoryRecallSettings(
                episodic_keywords=memory_recall_episodic_keywords,
                procedural_keywords=memory_recall_procedural_keywords,
                same_session_boost=memory_recall_same_session_boost,
                current_topic_boost=memory_recall_current_topic_boost,
                history_summary_boost=memory_recall_history_summary_boost,
                active_plan_boost=memory_recall_active_plan_boost,
                final_summary_boost=memory_recall_final_summary_boost,
                recency_window_seconds=memory_recall_recency_window_seconds,
                episodic_threshold=memory_recall_episodic_threshold,
                procedural_threshold=memory_recall_procedural_threshold,
                top_k=memory_recall_top_k,
                token_budget=memory_recall_token_budget,
            )

        if "openai" not in data:
            openai_api_key_candidates = _unique_nonempty_strings(
                data.pop("openai_api_key", None),
                _env_file_value("LEARNING_AGENT_OPENAI_API_KEY"),
                _env_file_value("AI_API_KEY"),
                _env_file_value("OPENAI_API_KEY"),
                _env("LEARNING_AGENT_OPENAI_API_KEY", ""),
                _env("AI_API_KEY", ""),
                _env("OPENAI_API_KEY", ""),
            )
            data["openai"] = OpenAISettings(
                api_key=openai_api_key_candidates[0] if openai_api_key_candidates else "",
                api_key_candidates=openai_api_key_candidates,
                base_url=(
                    data.pop("openai_base_url", _env("LEARNING_AGENT_OPENAI_BASE_URL", ""))
                    or _env("OPENAI_BASE_URL", "")
                )
                or "",
                organization=data.pop("openai_organization", _env("LEARNING_AGENT_OPENAI_ORGANIZATION", None))
                or _env("OPENAI_ORG_ID", None),
                project=data.pop("openai_project", _env("LEARNING_AGENT_OPENAI_PROJECT", None))
                or _env("OPENAI_PROJECT", None),
                timeout_seconds=int(data.pop("openai_timeout_seconds", _env("LEARNING_AGENT_OPENAI_TIMEOUT_SECONDS", 30))),
                max_retries=int(data.pop("openai_max_retries", _env("LEARNING_AGENT_OPENAI_MAX_RETRIES", 2))),
                responses_model=(
                    data.pop("openai_model", _env("LEARNING_AGENT_OPENAI_RESPONSES_MODEL", "gpt-5.4")) or "gpt-5.4"
                ),
                embedding_model=(
                    data.pop(
                        "openai_embedding_model",
                        _env("LEARNING_AGENT_OPENAI_EMBEDDING_MODEL", "qwen-embedding-8b"),
                    )
                    or "qwen-embedding-8b"
                ),
                embedding_model_version=(
                    data.pop(
                        "openai_embedding_model_version",
                        _env("LEARNING_AGENT_OPENAI_EMBEDDING_MODEL_VERSION", ""),
                    )
                    or ""
                ),
            )

        if "observability" not in data:
            data["observability"] = ObservabilitySettings(
                log_level=data.pop("log_level", _env("LEARNING_AGENT_LOG_LEVEL", "INFO")) or "INFO",
                json_logs=bool(data.pop("json_logs", _env_bool("LEARNING_AGENT_JSON_LOGS", True))),
                include_caller=bool(data.pop("include_caller", _env_bool("LEARNING_AGENT_LOG_INCLUDE_CALLER", False))),
                outbox_batch_size=int(data.pop("outbox_batch_size", _env("LEARNING_AGENT_OUTBOX_BATCH_SIZE", 100))),
                outbox_poll_interval_seconds=float(
                    data.pop("outbox_poll_interval_seconds", _env("LEARNING_AGENT_OUTBOX_POLL_INTERVAL_SECONDS", 1.0))
                ),
                outbox_max_attempts=int(
                    data.pop("outbox_max_attempts", _env("LEARNING_AGENT_OUTBOX_MAX_ATTEMPTS", 10))
                ),
            )

        data.setdefault("app_name", data["app"].service_name)
        data.setdefault("environment", data["app"].environment)
        data.setdefault("debug", data["app"].debug)
        data.setdefault("workflow_version", data["app"].workflow_version)
        data.setdefault("internal_api_token", internal_api_token)
        data.setdefault("java_business_base_url", java_business_base_url)
        data.setdefault("java_business_internal_token", java_business_internal_token)
        data.setdefault("java_business_timeout_seconds", java_business_timeout_seconds)
        data.setdefault("java_business_enable_fallback", java_business_enable_fallback)
        data.setdefault("local_life_candidate_limit", local_life_candidate_limit)
        data.setdefault("local_life_default_radius_km", local_life_default_radius_km)
        data.setdefault("prefer_real_adapters", data["app"].prefer_real_adapters)
        data.setdefault("allow_in_memory_fallback", data["app"].allow_in_memory_fallback)
        data.setdefault("workflow_checkpoint_enabled", workflow_checkpoint_enabled)
        data.setdefault("workflow_checkpoint_sqlite_path", workflow_checkpoint_sqlite_path)
        data.setdefault("local_life_use_langgraph", local_life_use_langgraph)
        data.setdefault("local_life_require_langgraph_in_test", local_life_require_langgraph_in_test)
        data.setdefault("local_life_trace_enabled", local_life_trace_enabled)
        data.setdefault("local_life_answer_linter_enabled", local_life_answer_linter_enabled)
        data.setdefault("local_life_golden_cases_required", local_life_golden_cases_required)
        data.setdefault("enable_route_review", enable_route_review)
        data.setdefault("enable_required_facets", enable_required_facets)
        data.setdefault("enable_required_facets_to_plans", enable_required_facets_to_plans)
        data.setdefault("enable_min_entity_consistency_check", enable_min_entity_consistency_check)
        data.setdefault("enable_trace_harness", enable_trace_harness)
        data.setdefault("enable_replay_harness", enable_replay_harness)
        data.setdefault("enable_tool_mock_harness", enable_tool_mock_harness)
        data.setdefault("enable_rag_golden_evidence_harness", enable_rag_golden_evidence_harness)
        data.setdefault("enable_evaluation_harness", enable_evaluation_harness)
        data.setdefault("enable_partial_grounded", enable_partial_grounded)
        data.setdefault("enable_slot_clarify", enable_slot_clarify)
        data.setdefault("enable_rag_plus_tool_partial_answer", enable_rag_plus_tool_partial_answer)
        data.setdefault("enable_task_plan_for_local_life", enable_task_plan_for_local_life)
        data.setdefault("enable_answer_verifier", enable_answer_verifier)
        data.setdefault("answer_verifier_mode", answer_verifier_mode)
        data.setdefault("enable_online_dense_retrieval", enable_online_dense_retrieval)
        data.setdefault("enable_online_sparse_retrieval", enable_online_sparse_retrieval)
        data.setdefault("enable_bm25_sparse_retrieval", enable_bm25_sparse_retrieval)
        data.setdefault("enable_remote_reranker", enable_remote_reranker or reranker_provider == "remote")
        data.setdefault("reranker_provider", reranker_provider)
        data.setdefault("enable_llm_query_rewrite", enable_llm_query_rewrite)
        data.setdefault("enable_rag", enable_rag)
        data.setdefault("enable_hyde_sparse_retrieval", enable_hyde_sparse_retrieval)
        data.setdefault("llm_query_rewrite_min_query_length", llm_query_rewrite_min_query_length)
        data.setdefault("llm_query_rewrite_low_confidence_threshold", llm_query_rewrite_low_confidence_threshold)
        data.setdefault("llm_query_rewrite_model", llm_query_rewrite_model)
        data.setdefault("llm_query_rewrite_temperature", llm_query_rewrite_temperature)
        data.setdefault("hyde_sparse_retrieval_model", hyde_sparse_retrieval_model)
        data.setdefault("hyde_sparse_retrieval_temperature", hyde_sparse_retrieval_temperature)
        data.setdefault("intent_confidence_threshold", intent_confidence_threshold)
        data.setdefault("reference_resolution_confidence_threshold", reference_resolution_confidence_threshold)
        data.setdefault("metadata_filter_confidence_threshold", metadata_filter_confidence_threshold)
        data.setdefault("bm25_k1", bm25_k1)
        data.setdefault("bm25_b", bm25_b)
        data.setdefault("rrf_dense_weight", rrf_dense_weight)
        data.setdefault("rrf_sparse_weight", rrf_sparse_weight)
        data.setdefault("rrf_metadata_weight", rrf_metadata_weight)
        data.setdefault("fusion_top_k", fusion_top_k)
        data.setdefault("remote_reranker_endpoint", remote_reranker_endpoint)
        data.setdefault("remote_reranker_api_key", remote_reranker_api_key)
        data.setdefault("remote_reranker_model", remote_reranker_model)
        data.setdefault("remote_reranker_timeout_seconds", remote_reranker_timeout_seconds)
        data.setdefault("low_score_threshold", low_score_threshold)
        data.setdefault("evidence_strong_score_threshold", evidence_strong_score_threshold)
        data.setdefault("topic_consistency_threshold", topic_consistency_threshold)
        data.setdefault("dedup_similarity_threshold", dedup_similarity_threshold)
        data.setdefault("rewrite_retry_limit", rewrite_retry_limit)
        data.setdefault("memory_retrieval_prompt_limit", memory_retrieval_prompt_limit)
        data.setdefault("memory_retrieval_state_limit", memory_retrieval_state_limit)
        data.setdefault("memory_retrieval_rag_limit", memory_retrieval_rag_limit)
        data.setdefault("memory_retrieval_tool_limit", memory_retrieval_tool_limit)
        data.setdefault("memory_retrieval_token_budget", memory_retrieval_token_budget)
        data.setdefault("memory_retrieval_semantic_top_k", memory_retrieval_semantic_top_k)
        data.setdefault("memory_retrieval_episodic_keywords", memory_retrieval_episodic_keywords)
        data.setdefault("memory_retrieval_procedural_keywords", memory_retrieval_procedural_keywords)
        data.setdefault("memory_injection_prompt_limit", memory_injection_prompt_limit)
        data.setdefault("memory_injection_state_limit", memory_injection_state_limit)
        data.setdefault("memory_injection_tool_limit", memory_injection_tool_limit)
        data.setdefault("memory_injection_rag_limit", memory_injection_rag_limit)
        data.setdefault("memory_injection_semantic_limit", memory_injection_semantic_limit)
        data.setdefault("memory_injection_episodic_limit", memory_injection_episodic_limit)
        data.setdefault("memory_injection_procedural_limit", memory_injection_procedural_limit)
        data.setdefault("memory_injection_token_budget", memory_injection_token_budget)
        data.setdefault("memory_governance_low_confidence_threshold", memory_governance_low_confidence_threshold)
        data.setdefault("memory_governance_low_stability_threshold", memory_governance_low_stability_threshold)
        data.setdefault("memory_conflict_supersede_margin", memory_conflict_supersede_margin)
        data.setdefault("memory_conflict_merge_similarity_threshold", memory_conflict_merge_similarity_threshold)
        data.setdefault("memory_promotion_preference_promote_count", memory_promotion_preference_promote_count)
        data.setdefault("consolidation_minimum_duplicate_group_size", consolidation_minimum_duplicate_group_size)
        data.setdefault("consolidation_max_conflicts", consolidation_max_conflicts)
        data.setdefault("consolidation_confirmed_explicitness", consolidation_confirmed_explicitness)
        data.setdefault("consolidation_inferred_explicitness", consolidation_inferred_explicitness)
        data.setdefault("consolidation_recency_window_seconds", consolidation_recency_window_seconds)
        data.setdefault("orchestrator_confirmed_confidence_threshold", orchestrator_confirmed_confidence_threshold)
        super().__init__(**data)

    def safe_dump(self) -> dict[str, Any]:
        if hasattr(self, "model_dump"):
            data = self.model_dump(mode="json")
        else:  # pragma: no cover - compatibility path.
            data = self.dict()  # type: ignore[attr-defined]
        if data.get("openai", {}).get("api_key"):
            data["openai"]["api_key"] = "***"
        if data.get("openai", {}).get("api_key_candidates"):
            data["openai"]["api_key_candidates"] = ["***"] * len(data["openai"]["api_key_candidates"])
        if data.get("qdrant", {}).get("api_key"):
            data["qdrant"]["api_key"] = "***"
        if data.get("internal_api_token"):
            data["internal_api_token"] = "***"
        return data

    def environment_name(self) -> str:
        return str(getattr(self, "environment", "") or getattr(self.app, "environment", "") or "").strip().lower()

    def is_production_like(self) -> bool:
        return self.environment_name() in {"production", "prod", "staging", "preprod", "preview"}

    def is_dev_like(self) -> bool:
        return self.environment_name() in {"development", "dev", "local", "test", "testing", "ci"}

    def policy_settings(self):
        from learning_agent_service.config.policies import (
            PolicySettings,
            WorkflowUnderstandingPolicyConfig,
        )
        from learning_agent_service.memory.conflict import MemoryConflictPolicyConfig
        from learning_agent_service.memory.consolidation import ConsolidationPolicyConfig
        from learning_agent_service.memory.governance import MemoryGovernancePolicyConfig
        from learning_agent_service.memory.injection import MemoryInjectionPolicyConfig
        from learning_agent_service.memory.orchestrator import MemoryOrchestratorPolicyConfig
        from learning_agent_service.memory.promotion import PromotionConfig
        from learning_agent_service.memory.retrieval import RetrievalPolicyConfig
        from learning_agent_service.rag.evidence import EvidenceGovernanceConfig
        from learning_agent_service.rag.hybrid import HybridRetrieverConfig
        from learning_agent_service.rag.retrieval.shared import RRFConfig
        from learning_agent_service.rag.rewrite import QueryRewriteConfig

        return PolicySettings(
            workflow_understanding=WorkflowUnderstandingPolicyConfig(
                intent_confidence_threshold=self.intent_confidence_threshold,
                reference_resolution_confidence_threshold=self.reference_resolution_confidence_threshold,
                metadata_filter_confidence_threshold=self.metadata_filter_confidence_threshold,
            ),
            memory_retrieval=RetrievalPolicyConfig(
                prompt_limit=self.memory_retrieval_prompt_limit,
                state_limit=self.memory_retrieval_state_limit,
                rag_limit=self.memory_retrieval_rag_limit,
                tool_limit=self.memory_retrieval_tool_limit,
                token_budget=self.memory_retrieval_token_budget,
                semantic_top_k=self.memory_retrieval_semantic_top_k,
                episodic_keywords=self.memory_recall.episodic_keywords or self.memory_retrieval_episodic_keywords,
                procedural_keywords=self.memory_recall.procedural_keywords or self.memory_retrieval_procedural_keywords,
            ),
            memory_injection=MemoryInjectionPolicyConfig(
                prompt_limit=self.memory_injection_prompt_limit,
                state_limit=self.memory_injection_state_limit,
                tool_limit=self.memory_injection_tool_limit,
                rag_limit=self.memory_injection_rag_limit,
                semantic_limit=self.memory_injection_semantic_limit,
                episodic_limit=self.memory_injection_episodic_limit,
                procedural_limit=self.memory_injection_procedural_limit,
                token_budget=self.memory_injection_token_budget,
            ),
            memory_governance=MemoryGovernancePolicyConfig(
                low_confidence_threshold=self.memory_governance_low_confidence_threshold,
                low_stability_threshold=self.memory_governance_low_stability_threshold,
            ),
            memory_conflict=MemoryConflictPolicyConfig(
                supersede_margin=self.memory_conflict_supersede_margin,
                merge_similarity_threshold=self.memory_conflict_merge_similarity_threshold,
            ),
            memory_promotion=PromotionConfig(
                preference_promote_count=self.memory_promotion_preference_promote_count,
            ),
            consolidation=ConsolidationPolicyConfig(
                minimum_duplicate_group_size=self.consolidation_minimum_duplicate_group_size,
                max_conflicts=self.consolidation_max_conflicts,
                confirmed_explicitness=self.consolidation_confirmed_explicitness,
                inferred_explicitness=self.consolidation_inferred_explicitness,
                recency_window_seconds=self.consolidation_recency_window_seconds,
            ),
            orchestrator=MemoryOrchestratorPolicyConfig(
                confirmed_confidence_threshold=self.orchestrator_confirmed_confidence_threshold,
            ),
            evidence_governance=EvidenceGovernanceConfig(
                low_score_threshold=self.low_score_threshold,
                strong_score_threshold=self.evidence_strong_score_threshold,
                dedup_similarity_threshold=self.dedup_similarity_threshold,
                topic_consistency_threshold=self.topic_consistency_threshold,
                min_items=self.evidence_min_n,
                max_items=self.evidence_top_n,
            ),
            hybrid_retriever=HybridRetrieverConfig(
                dense_top_k=self.dense_top_k,
                sparse_top_k=self.sparse_top_k,
                metadata_top_k=self.metadata_top_k,
                fusion_top_k=self.fusion_top_k,
                rrf_k=self.rrf_k,
                rerank_top_k=self.rerank_top_k,
                metadata_filter_confidence_threshold=self.metadata_filter_confidence_threshold,
            ),
            rrf=RRFConfig(
                k=self.rrf_k,
                route_weights={
                    "dense": self.rrf_dense_weight,
                    "sparse": self.rrf_sparse_weight,
                    "metadata": self.rrf_metadata_weight,
                },
            ),
            query_rewrite=QueryRewriteConfig(
                llm_enabled=self.enable_llm_query_rewrite,
                short_query_max_chars=self.llm_query_rewrite_min_query_length,
                low_confidence_threshold=self.llm_query_rewrite_low_confidence_threshold,
                llm_retry_limit=self.rewrite_retry_limit,
                llm_model=self.llm_query_rewrite_model or self.openai.responses_model,
                llm_temperature=self.llm_query_rewrite_temperature,
                hyde_enabled=self.enable_hyde_sparse_retrieval,
                hyde_model=self.hyde_sparse_retrieval_model or self.openai.responses_model,
                hyde_temperature=self.hyde_sparse_retrieval_temperature,
            ),
        )


ServiceSettings = Settings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def load_settings() -> Settings:
    return get_settings()

__all__ = [name for name in globals() if not name.startswith("__")]
