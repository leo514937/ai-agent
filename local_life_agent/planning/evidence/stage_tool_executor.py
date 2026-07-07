from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...domain.schemas import ExecutionPlan
from .tool_result_cache import ToolResultCache


def _to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        return dumped if isinstance(dumped, dict) else {}
    return dict(getattr(value, "__dict__", {}) or {})


def _stage_tool_calls(stage: Any, plan: ExecutionPlan) -> list[dict[str, Any]]:
    stage_dict = _to_dict(stage)
    tool_names = [str(name).strip() for name in (stage_dict.get("tool_names") or []) if str(name).strip()]
    if not tool_names:
        return []
    stage_id = str(stage_dict.get("stage_id", "") or "").strip()
    calls: list[dict[str, Any]] = []
    for call in plan.tool_calls or []:
        call_dict = _to_dict(call)
        if str(call_dict.get("tool_name", "") or "").strip() not in tool_names:
            continue
        depends_on = [str(item).strip() for item in (call_dict.get("depends_on") or []) if str(item).strip()]
        if depends_on and stage_id and stage_id not in depends_on:
            continue
        calls.append(call_dict)
    return calls


@dataclass
class StageToolExecutorResult:
    results: dict[str, dict[str, Any]]
    executed_stages: list[str]
    cache_hits: int = 0


class StageToolExecutor:
    """Minimal stage-aware tool executor for staged plans."""

    def __init__(self, *, call_fn: Any, cache: ToolResultCache | None = None) -> None:
        self._call_fn = call_fn
        self._cache = cache or ToolResultCache()

    def execute(self, plan: ExecutionPlan | dict[str, Any]) -> StageToolExecutorResult:
        plan_obj = plan if isinstance(plan, ExecutionPlan) else ExecutionPlan.model_validate(plan)
        results: dict[str, dict[str, Any]] = {}
        completed_stages: set[str] = set()
        cache_hits = 0

        stages = list(plan_obj.stages or [])
        if not stages:
            return StageToolExecutorResult(results=results, executed_stages=[], cache_hits=0)

        for stage in stages:
            stage_dict = _to_dict(stage)
            stage_id = str(stage_dict.get("stage_id", "") or "").strip()
            depends_on = [str(item).strip() for item in (stage_dict.get("depends_on") or []) if str(item).strip()]
            if depends_on and not set(depends_on).issubset(completed_stages):
                continue

            stage_calls = _stage_tool_calls(stage, plan_obj)
            if not stage_calls:
                completed_stages.add(stage_id)
                continue

            from ...tools.gateway import BatchToolExecutor

            batch = BatchToolExecutor(call_fn=self._call_fn)
            stage_results = batch.execute_sync(stage_calls)
            for call_id, payload in stage_results.items():
                payload_dict = _to_dict(payload)
                if payload_dict.get("tool_result_cache_hit"):
                    cache_hits += 1
                results[call_id] = payload_dict

            completed_stages.add(stage_id)

        return StageToolExecutorResult(results=results, executed_stages=sorted(completed_stages), cache_hits=cache_hits)

