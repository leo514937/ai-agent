"""Repository implementations owned by Workstream A."""

from .clarification import ClarificationRecordRepository
from .knowledge_governance import KnowledgeGovernanceRepository
from .memory_outbox import MemoryOutboxRepository
from .outbox import OutboxRepository
from .preferences import UserPreferenceRepository
from .preferences import UserProfileProjectionRepository
from .memory_trace_repository import MemoryTraceRepository
from .records import (
    ClarificationRecordEntry,
    KnowledgeDocumentRecord,
    KnowledgeDocumentVersionRecord,
    MemoryOutboxRecord,
    OutboxEventRecord,
    ToolInvocationLogEntry,
    UserPreferenceProfileRecord,
    UserProfilePreferenceRecord,
)
from .runtime_adapters import (
    AdapterStatus,
    DurablePreferenceStore,
    DurableProfileProjectionStore,
    NoOpSemanticMemoryStore,
    OutboxAsyncLogStore,
    RedisSessionContextStore,
    RuntimeComponentMode,
    RuntimeDependencyStatus,
    RuntimeProfile,
)
from .tool_logs import ToolInvocationLogRepository

__all__ = [
    "AdapterStatus",
    "ClarificationRecordEntry",
    "ClarificationRecordRepository",
    "DurablePreferenceStore",
    "DurableProfileProjectionStore",
    "KnowledgeDocumentRecord",
    "KnowledgeDocumentVersionRecord",
    "KnowledgeGovernanceRepository",
    "MemoryTraceRepository",
    "MemoryOutboxRepository",
    "NoOpSemanticMemoryStore",
    "OutboxAsyncLogStore",
    "OutboxEventRecord",
    "OutboxRepository",
    "RedisSessionContextStore",
    "RuntimeComponentMode",
    "RuntimeDependencyStatus",
    "RuntimeProfile",
    "ToolInvocationLogEntry",
    "ToolInvocationLogRepository",
    "UserPreferenceProfileRecord",
    "UserPreferenceRepository",
    "UserProfilePreferenceRecord",
    "UserProfileProjectionRepository",
]
