from __future__ import annotations

from typing import Any

from ...core.execution_core import ExecutionCore
from ...domain.schemas import EvidencePack
from .evidence_builder import build_evidence
from .evidence_cache import EvidenceCache, get_default_evidence_cache


class ToolBatchExecutor:
    """Thin workflow-facing wrapper over the execution-layer batch executor."""

    def __init__(self, *, call_fn: Any, cache: EvidenceCache | None = None) -> None:
        self._execution_core = ExecutionCore(call_fn=call_fn)
        self._cache = cache or get_default_evidence_cache()

    def execute(self, tool_calls: list[Any]) -> dict[str, dict[str, Any]]:
        return self._execution_core.execute_batch(tool_calls)

    def build_evidence_pack(
        self,
        *,
        tool_results: dict[str, Any],
        resolved_target: dict[str, Any],
        execution_plan: dict[str, Any] | Any | None,
        recommendation_candidates: list[Any] | None = None,
        comparison_targets: list[Any] | None = None,
        cache_scope: dict[str, Any] | str | None = None,
    ) -> tuple[EvidencePack, dict[str, Any]]:
        payload = {
            "tool_results": tool_results or {},
            "resolved_target": resolved_target or {},
            "execution_plan": execution_plan.model_dump() if hasattr(execution_plan, "model_dump") else execution_plan or {},
            "recommendation_candidates": recommendation_candidates or [],
            "comparison_targets": comparison_targets or [],
        }

        def _build() -> dict[str, Any]:
            return build_evidence(
                tool_results=tool_results,
                resolved_target=resolved_target,
                execution_plan=execution_plan,
                recommendation_candidates=recommendation_candidates,
                comparison_targets=comparison_targets,
            )

        evidence_dict, cache_meta = self._cache.get_or_build(cache_scope, payload, _build)
        return EvidencePack.model_validate(evidence_dict), cache_meta
