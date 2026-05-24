from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class WorkflowErrorCode(str, Enum):
    INVALID_REQUEST = "LEARN-4001"
    INVALID_CONTRACT = "LEARN-4002"
    CLARIFICATION_PENDING = "LEARN-4091"
    LOW_INTENT_CONFIDENCE = "LEARN-4221"
    LOW_REFERENCE_CONFIDENCE = "LEARN-4222"
    INVALID_RETRIEVAL_PLAN = "LEARN-4241"
    KNOWLEDGE_NOT_FOUND = "LEARN-4041"
    EVIDENCE_INSUFFICIENT = "LEARN-4291"
    DENSE_RETRIEVAL_FAILED = "LEARN-5021"
    SPARSE_RETRIEVAL_FAILED = "LEARN-5022"
    METADATA_RETRIEVAL_FAILED = "LEARN-5023"
    RERANK_FAILED = "LEARN-5024"
    TOOL_TIMEOUT = "LEARN-5031"
    MODEL_UNAVAILABLE = "LEARN-5041"
    SESSION_PERSIST_FAILED = "LEARN-5601"
    MASTERY_UPDATE_FAILED = "LEARN-5602"
    ASYNC_LOG_WRITE_FAILED = "LEARN-5603"
    INTERNAL_ERROR = "LEARN-5001"


class TerminalEvent(str, Enum):
    FINAL = "final"
    CLARIFICATION_CARD = "clarification_card"
    ERROR = "error"


@dataclass(frozen=True)
class ErrorInfo:
    code: WorkflowErrorCode
    stage: str
    message: str
    retryable: bool = False
    degraded_to: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    is_terminal: bool = False


def build_error(
    code: WorkflowErrorCode,
    *,
    stage: str,
    message: str,
    retryable: bool = False,
    degraded_to: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    is_terminal: bool = False
) -> ErrorInfo:
    return ErrorInfo(
        code=code,
        stage=stage,
        message=message,
        retryable=retryable,
        degraded_to=degraded_to,
        details=details or {},
        is_terminal=is_terminal,
    )
