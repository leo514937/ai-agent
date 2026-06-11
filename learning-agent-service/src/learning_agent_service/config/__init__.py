"""Configuration helpers for the standalone learning agent service."""

from .logging import (
    ServiceLogContext,
    bind_log_context,
    clear_log_context,
    configure_logging,
    get_log_context,
)
from .settings_impl import (
    AppSettings,
    ObservabilitySettings,
    OpenAISettings,
    PostgresSettings,
    QdrantSettings,
    RedisSettings,
    ServiceSettings,
    Settings,
    get_settings,
    load_settings,
)

try:
    from .policies import (
        ConsolidationPolicyConfig,
        MemoryOrchestratorPolicyConfig,
        PolicySettings,
        WorkflowUnderstandingPolicyConfig,
    )
except ModuleNotFoundError:  # pragma: no cover - optional dependency fallback for lightweight test envs
    PolicySettings = None
    ConsolidationPolicyConfig = None
    MemoryOrchestratorPolicyConfig = None
    WorkflowUnderstandingPolicyConfig = None

__all__ = [
    "AppSettings",
    "OpenAISettings",
    "ObservabilitySettings",
    "PostgresSettings",
    "QdrantSettings",
    "RedisSettings",
    "ServiceLogContext",
    "ServiceSettings",
    "Settings",
    "PolicySettings",
    "ConsolidationPolicyConfig",
    "MemoryOrchestratorPolicyConfig",
    "WorkflowUnderstandingPolicyConfig",
    "bind_log_context",
    "clear_log_context",
    "configure_logging",
    "get_log_context",
    "get_settings",
    "load_settings",
]
