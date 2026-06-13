from __future__ import annotations

import asyncio
import inspect
import time
from typing import Any

from pydantic import ValidationError

from .models import RegisteredTool, ToolExecutionResult, ToolSelection
from .registry import ToolRegistry


class ToolExecutor:
    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    async def execute(self, selection: ToolSelection) -> ToolExecutionResult:
        try:
            registered_tool = self._registry.get(selection.tool_name)
        except KeyError:
            return ToolExecutionResult(
                tool_name=selection.tool_name,
                status="failed",
                error_code="LEARN-5304",
                error_message="Tool not registered",
                retryable=False,
                degraded=False,
            )

        start = time.perf_counter()
        approval_required = bool(getattr(registered_tool.spec, "requires_approval", False) or getattr(selection, "approval_required", False))
        approval_status = str(getattr(selection, "approval_status", "") or "").strip().lower()
        approval_request = dict(getattr(selection, "approval_request", {}) or {})
        if approval_required and approval_status != "approved":
            pending_status = "rejected" if approval_status in {"rejected", "deny", "denied"} else "pending_approval"
            approval_request = approval_request or {
                "tool_name": selection.tool_name,
                "input_payload": dict(selection.input_payload),
                "risk_level": getattr(registered_tool.spec, "risk_level", "low"),
                "approval_state": pending_status,
            }
            approval_request.setdefault("approval_state", pending_status)
            return ToolExecutionResult(
                tool_name=selection.tool_name,
                status=pending_status,
                output={},
                retryable=False,
                degraded=False,
                approval_required=True,
                approval_status=approval_status or "pending_approval",
                approval_request=approval_request,
                duration_ms=self._elapsed_ms(start),
            )
        try:
            payload = registered_tool.spec.input_model.model_validate(selection.input_payload)
        except ValidationError as exc:
            return self._error_result(
                selection,
                error_code="LEARN-5302",
                error_message=str(exc),
                retryable=False,
                degraded=False,
                start=start,
            )

        timeout_seconds = self._resolve_timeout_seconds(selection, registered_tool)
        max_attempts = 2 if registered_tool.spec.retryable else 1
        last_error_code = "LEARN-5300"
        last_error_message = "Tool execution failed"
        for attempt in range(max_attempts):
            try:
                raw_output = await asyncio.wait_for(
                    self._invoke_handler(registered_tool, payload),
                    timeout=timeout_seconds,
                )
                validated_output = registered_tool.spec.output_model.model_validate(raw_output)
                return ToolExecutionResult(
                    tool_name=selection.tool_name,
                    status="ok",
                    output=validated_output.model_dump(mode="json"),
                    retryable=False,
                    degraded=False,
                    approval_required=approval_required,
                    approval_status="approved" if approval_required else approval_status or None,
                    approval_request=approval_request,
                    duration_ms=self._elapsed_ms(start),
                )
            except (TimeoutError, asyncio.TimeoutError, asyncio.CancelledError):
                last_error_code = "LEARN-5301"
                last_error_message = "Tool execution timed out"
                if attempt < max_attempts - 1:
                    await asyncio.sleep(0.05 * (2 ** attempt))
                    continue
                return self._error_result(
                    selection,
                    error_code=last_error_code,
                    error_message=last_error_message,
                    retryable=registered_tool.spec.retryable,
                    degraded=registered_tool.spec.degrade_to is not None,
                    degrade_to=registered_tool.spec.degrade_to,
                    start=start,
                    approval_required=approval_required,
                    approval_status=approval_status or ("approved" if approval_required else None),
                    approval_request=approval_request,
                )
            except ValidationError as exc:
                return self._error_result(
                    selection,
                    error_code="LEARN-5302",
                    error_message=str(exc),
                    retryable=False,
                    degraded=False,
                    start=start,
                    approval_required=approval_required,
                    approval_status=approval_status or ("approved" if approval_required else None),
                    approval_request=approval_request,
                )
            except Exception as exc:  # pragma: no cover - defensive branch
                last_error_code = "LEARN-5300"
                last_error_message = str(exc)
                if attempt < max_attempts - 1:
                    await asyncio.sleep(0.05 * (2 ** attempt))
                    continue
                return self._error_result(
                    selection,
                    error_code=last_error_code,
                    error_message=last_error_message,
                    retryable=registered_tool.spec.retryable,
                    degraded=registered_tool.spec.degrade_to is not None,
                    degrade_to=registered_tool.spec.degrade_to,
                    start=start,
                    approval_required=approval_required,
                    approval_status=approval_status or ("approved" if approval_required else None),
                    approval_request=approval_request,
                )

    async def _invoke_handler(self, registered_tool: RegisteredTool, payload: Any) -> Any:
        result = registered_tool.handler(payload)
        if inspect.isawaitable(result):
            return await result
        return result

    def _resolve_timeout_seconds(
        self,
        selection: ToolSelection,
        registered_tool: RegisteredTool,
    ) -> float:
        timeout_ms = selection.timeout_ms or registered_tool.spec.timeout_ms
        return timeout_ms / 1000.0

    def _error_result(
        self,
        selection: ToolSelection,
        error_code: str,
        error_message: str,
        retryable: bool,
        degraded: bool,
        start: float,
        degrade_to: str = None,
        approval_required: bool = False,
        approval_status: str | None = None,
        approval_request: dict | None = None,
    ) -> ToolExecutionResult:
        return ToolExecutionResult(
            tool_name=selection.tool_name,
            status="failed",
            error_code=error_code,
            error_message=error_message,
            retryable=retryable,
            degraded=degraded,
            degrade_to=degrade_to or selection.degrade_to,
            duration_ms=self._elapsed_ms(start),
            approval_required=approval_required,
            approval_status=approval_status,
            approval_request=dict(approval_request or {}),
        )

    def _elapsed_ms(self, start: float) -> int:
        return int((time.perf_counter() - start) * 1000)
