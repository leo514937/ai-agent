from __future__ import annotations

from .models import NormalizedToolResult, ToolExecutionResult


class ToolResultNormalizer:
    def normalize(self, execution_result: ToolExecutionResult) -> NormalizedToolResult:
        return NormalizedToolResult(
            tool_name=execution_result.tool_name,
            ok=execution_result.status == "ok",
            status=execution_result.status,
            payload=execution_result.output,
            errors={
                "code": execution_result.error_code,
                "message": execution_result.error_message,
            }
            if execution_result.error_code
            else {},
            degraded=execution_result.degraded,
            retryable=execution_result.retryable,
            degrade_to=execution_result.degrade_to,
        )
