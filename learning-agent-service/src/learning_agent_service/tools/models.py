from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Optional, Type

from pydantic import BaseModel, Field


class SideEffectLevel(str, Enum):
    NONE = "none"
    LOW = "low"
    HIGH = "high"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_model: Type[BaseModel]
    output_model: Type[BaseModel]
    idempotent: bool
    retryable: bool
    side_effect_level: SideEffectLevel
    risk_level: str = "low"
    allowed_execution_modes: tuple[str, ...] = ("auto", "simple", "plan_execute")
    requires_approval: bool = False
    fallback_strategy: Optional[str] = None
    degrade_to: Optional[str] = None
    timeout_ms: int = 5000


@dataclass(frozen=True)
class RegisteredTool:
    spec: ToolSpec
    handler: Callable[[BaseModel], Any]


class ToolSelection(BaseModel):
    tool_name: str
    input_payload: Dict[str, Any] = Field(default_factory=dict)
    reason: Optional[str] = None
    degrade_to: Optional[str] = None
    timeout_ms: Optional[int] = None
    approval_required: bool = False
    approval_status: Optional[str] = None
    approval_request: Dict[str, Any] = Field(default_factory=dict)


class ToolExecutionResult(BaseModel):
    tool_name: str
    status: str
    output: Dict[str, Any] = Field(default_factory=dict)
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    retryable: bool = False
    degraded: bool = False
    degrade_to: Optional[str] = None
    duration_ms: int = 0
    approval_required: bool = False
    approval_status: Optional[str] = None
    approval_request: Dict[str, Any] = Field(default_factory=dict)


class NormalizedToolResult(BaseModel):
    tool_name: str
    ok: bool
    status: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    errors: Dict[str, Any] = Field(default_factory=dict)
    degraded: bool = False
    retryable: bool = False
    degrade_to: Optional[str] = None
    approval_required: bool = False
    approval_status: Optional[str] = None
    approval_request: Dict[str, Any] = Field(default_factory=dict)
