from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SideEffectLevel(str, Enum):
    NONE = "none"
    LOW = "low"
    HIGH = "high"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    idempotent: bool
    retryable: bool
    side_effect_level: SideEffectLevel
    risk_level: str = "low"
    allowed_execution_modes: tuple[str, ...] = ("auto", "simple", "plan_execute")
    requires_approval: bool = False
    requires_shop_id: bool = False  # v4: 是否需要 resolved_shop_id
    fallback_strategy: str | None = None
    degrade_to: str | None = None
    timeout_ms: int = 5000


@dataclass(frozen=True)
class RegisteredTool:
    spec: ToolSpec
    handler: Callable[[BaseModel], Any]


class ToolSelection(BaseModel):
    tool_name: str
    input_payload: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None
    degrade_to: str | None = None
    timeout_ms: int | None = None
    approval_required: bool = False
    approval_status: str | None = None
    approval_request: dict[str, Any] = Field(default_factory=dict)


class ToolExecutionResult(BaseModel):
    tool_name: str
    status: str
    output: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool = False
    degraded: bool = False
    degrade_to: str | None = None
    duration_ms: int = 0
    approval_required: bool = False
    approval_status: str | None = None
    approval_request: dict[str, Any] = Field(default_factory=dict)


class NormalizedToolResult(BaseModel):
    tool_name: str
    ok: bool
    status: str
    payload: dict[str, Any] = Field(default_factory=dict)
    errors: dict[str, Any] = Field(default_factory=dict)
    degraded: bool = False
    retryable: bool = False
    degrade_to: str | None = None
    approval_required: bool = False
    approval_status: str | None = None
    approval_request: dict[str, Any] = Field(default_factory=dict)
