from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List

from ...domain.contracts import (
    PlanExecutionSummary,
    PlanStep,
    StepResult,
    ToolExecutionCommand,
    ToolNormalizationRequest,
)
from ...domain.enums import IntentType, ToolExecutionStatus
from ...domain.errors import WorkflowErrorCode, build_error
from ...domain.state import GraphState
from ...tools.models import SideEffectLevel


@dataclass(frozen=True)
class PlanExecutionPolicy:
    max_steps: int = 8
    max_tool_rounds: int = 3
    max_replans: int = 1


EventAppender = Callable[[GraphState, str, Dict[str, Any]], GraphState]


@dataclass
class ReactStepExecutor:
    container: Any
    append_event: EventAppender
    policy: PlanExecutionPolicy = field(default_factory=PlanExecutionPolicy)

    def plan_planner(self, state: GraphState) -> GraphState:
        turn = state["turn"]
        plan = self._normalize_plan(turn.plan)
        task_plan = getattr(turn, "task_plan", None)
        if not plan and task_plan is not None and getattr(task_plan, "steps", None):
            plan = self._normalize_plan(list(task_plan.steps))
        if not plan:
            plan = self._build_default_plan(state)
        turn_extra = dict(turn.extra)
        turn_extra.setdefault("plan_replan_count", 0)
        state["turn"] = turn.model_copy(
            update={
                "plan": plan,
                "current_step_index": 0,
                "current_step": plan[0] if plan else None,
                "need_replan": False,
                "replan_reason": None,
                "final_task_summary": None,
                "extra": turn_extra,
            }
        )
        if plan and not self._has_event(state, "plan_execution_started"):
            state = self.append_event(
                state,
                "plan_execution_started",
                {
                    "plan": [step.model_dump(mode="json") for step in plan],
                    "total_steps": len(plan),
                    "current_step_index": 0,
                    "execution_mode": turn.execution_mode,
                    "risk_level": turn.risk_level,
                },
            )
        return state

    def plan_validator(self, state: GraphState) -> GraphState:
        turn = state["turn"]
        plan = self._normalize_plan(turn.plan)
        if not plan:
            return self._mark_replan(
                state,
                reason="计划为空，无法进入复杂任务执行。",
                stage="plan_validator",
                code=WorkflowErrorCode.INVALID_CONTRACT,
            )

        for step in plan[: self.policy.max_steps]:
            candidates = self._candidate_tools(step, turn.execution_mode)
            if not candidates:
                if self._step_can_run_without_tools(step):
                    continue
                return self._mark_replan(
                    state,
                    reason="步骤没有任何可用工具。",
                    stage="plan_validator",
                    code=WorkflowErrorCode.INVALID_CONTRACT,
                )

            if step.requires_approval or step.risk_level == "high":
                return self._request_approval(
                    state,
                    step=step,
                    tool_name=candidates[0],
                    reason="步骤显式要求人工审批或风险等级过高。",
                )

            safe_candidates = [tool_name for tool_name in candidates if not self._tool_requires_approval(tool_name, step)]
            if not safe_candidates:
                return self._request_approval(
                    state,
                    step=step,
                    tool_name=candidates[0],
                    reason="步骤候选工具都需要人工审批。",
                )
        return state

    def step_executor(self, state: GraphState) -> GraphState:
        turn = state["turn"]
        plan = self._normalize_plan(turn.plan)
        if not plan:
            return self._mark_replan(
                state,
                reason="计划为空，无法执行步骤。",
                stage="step_executor",
                code=WorkflowErrorCode.INVALID_CONTRACT,
            )

        step_results = list(turn.step_results)
        if turn.current_step_index >= len(plan):
            return state

        start_index = min(max(turn.current_step_index, 0), len(plan) - 1)
        if turn.need_human_approval or turn.approval_request:
            step = turn.current_step or plan[start_index]
            request = dict(turn.approval_request)
            if not request:
                request = {
                    "step_id": step.step_id,
                    "goal": step.goal,
                    "risk_level": step.risk_level,
                    "reason": "需要人工审批。",
                }
            approval_result = StepResult(
                step_id=step.step_id,
                status="need_approval",
                tools_used=[],
                observations=[f"步骤 {step.step_id} 需要人工审批。"],
                result=None,
                error="需要人工审批",
                next_action="await_approval",
            )
            if not step_results or step_results[-1].step_id != approval_result.step_id:
                step_results.append(approval_result)
            state["turn"] = turn.model_copy(
                update={
                    "step_results": step_results,
                    "need_human_approval": True,
                    "approval_request": request,
                    "current_step_index": start_index,
                    "current_step": step,
                }
            )
            state = self.append_event(
                state,
                "plan_step_result",
                {
                    "step_result": approval_result.model_dump(mode="json"),
                    "step_input": dict(getattr(step, "input_payload", {}) or {}),
                    "current_step_index": start_index,
                    "total_steps": len(plan),
                },
            )
            return state

        executed_steps = 0
        for index in range(start_index, len(plan)):
            if executed_steps >= self.policy.max_steps:
                state = self._mark_replan(
                    state,
                    reason="步骤数量超过执行上限。",
                    stage="step_executor",
                    code=WorkflowErrorCode.INVALID_CONTRACT,
                )
                break

            step = plan[index]
            state["turn"] = state["turn"].model_copy(
                update={
                    "current_step_index": index,
                    "current_step": step,
                }
            )
            result = self._execute_step(state, step)
            step_results.append(result)
            state["turn"] = state["turn"].model_copy(update={"step_results": step_results})
            state = self.append_event(
                state,
                "plan_step_result",
                {
                    "step_result": result.model_dump(mode="json"),
                    "step_input": dict(getattr(step, "input_payload", {}) or {}),
                    "current_step_index": index,
                    "total_steps": len(plan),
                },
            )
            executed_steps += 1

            if result.status == "need_approval":
                state["turn"] = state["turn"].model_copy(update={"need_human_approval": True})
                break
            if result.status == "failed":
                state = self._mark_replan(
                    state,
                    reason=result.error or f"步骤 {step.step_id} 执行失败。",
                    stage="step_executor",
                    code=WorkflowErrorCode.INTERNAL_ERROR,
                )
                break

        if not state["turn"].need_replan and not state["turn"].need_human_approval:
            remaining_steps = len(plan) - len(step_results)
            if remaining_steps > 0:
                state = self._mark_replan(
                    state,
                    reason="步骤未全部执行完，需要继续规划。",
                    stage="step_executor",
                    code=WorkflowErrorCode.INVALID_CONTRACT,
                )
        return state

    def progress_checker(self, state: GraphState) -> GraphState:
        turn = state["turn"]
        plan = self._normalize_plan(turn.plan)
        completed = len([result for result in turn.step_results if result.status == "success"])
        total = len(plan)
        metrics = dict(state["runtime"].metrics)
        metrics.update(
            {
                "plan_steps_completed": completed,
                "plan_steps_total": total,
                "plan_step_results": len(turn.step_results),
            }
        )
        state["runtime"] = state["runtime"].model_copy(update={"metrics": metrics})
        if total and completed >= total and not turn.need_human_approval:
            state["turn"] = turn.model_copy(update={"need_replan": False, "replan_reason": None})
        return state

    def plan_reviewer(self, state: GraphState) -> GraphState:
        turn = state["turn"]
        summary = self._build_summary(turn)
        state["turn"] = turn.model_copy(update={"final_task_summary": summary})
        if not self._has_event(state, "plan_execution_summary") or int(turn.extra.get("plan_replan_count", 0) or 0) > 0:
            state = self.append_event(
                state,
                "plan_execution_summary",
                {"summary": summary.model_dump(mode="json")},
            )
        return state

    def human_approval_stub(self, state: GraphState) -> GraphState:
        turn = state["turn"]
        request = dict(turn.approval_request)
        if not request and turn.current_step is not None:
            request = {
                "step_id": turn.current_step.step_id,
                "goal": turn.current_step.goal,
                "risk_level": turn.current_step.risk_level,
            }
            state["turn"] = turn.model_copy(update={"approval_request": request, "need_human_approval": True})
            turn = state["turn"]
        if request and not self._has_event(state, "approval_required"):
            state = self.append_event(
                state,
                "approval_required",
                {
                    "step_id": str(request.get("step_id") or ""),
                    "reason": str(request.get("reason") or "需要人工审批"),
                    "approval_request": request,
                    "risk_level": str(request.get("risk_level") or turn.risk_level),
                },
            )
            
        is_langgraph = False
        runtime = state.get("runtime")
        if runtime is not None:
            trace = dict(runtime.metrics.get("phase5_trace", {}) or {})
            if trace.get("runner_backend") == "langgraph" or trace.get("graph_runtime") == "langgraph":
                is_langgraph = True
        if is_langgraph:
            from langgraph.errors import NodeInterrupt
            raise NodeInterrupt(request)
            
        return state

    def replanner(self, state: GraphState) -> GraphState:
        turn = state["turn"]
        turn_extra = dict(turn.extra)
        replan_count = int(turn_extra.get("plan_replan_count", 0) or 0)
        if replan_count >= self.policy.max_replans:
            return self._mark_replan(
                state,
                reason="重规划次数已达上限。",
                stage="replanner",
                code=WorkflowErrorCode.INVALID_CONTRACT,
            )

        fallback_plan = self._build_recovery_plan(state)
        turn_extra["plan_replan_count"] = replan_count + 1
        state["turn"] = turn.model_copy(
            update={
                "plan": fallback_plan,
                "current_step_index": 0,
                "current_step": fallback_plan[0] if fallback_plan else None,
                "need_replan": False,
                "replan_reason": None,
                "need_human_approval": False,
                "approval_request": {},
                "final_task_summary": None,
                "extra": turn_extra,
            }
        )
        if fallback_plan:
            state = self.append_event(
                state,
                "plan_replanned",
                {
                    "reason": str(turn.replan_reason or "触发重规划"),
                    "previous_steps": len(turn.plan),
                    "total_steps": len(fallback_plan),
                    "plan": [step.model_dump(mode="json") for step in fallback_plan],
                },
            )
        return state

    def _execute_step(self, state: GraphState, step: PlanStep) -> StepResult:
        turn = state["turn"]
        candidates = self._candidate_tools(step, turn.execution_mode)
        if not candidates:
            if self._step_can_run_without_tools(step):
                return StepResult(
                    step_id=step.step_id,
                    status="success",
                    observations=[f"步骤 {step.step_id} 不依赖额外工具，直接基于现有上下文整理结果。"],
                    result={"summary": step.goal},
                    error=None,
                    next_action="next_step",
                )
            return StepResult(
                step_id=step.step_id,
                status="failed",
                observations=[f"步骤 {step.step_id} 没有可执行工具。"],
                result=None,
                error="没有可用工具",
                next_action="replan",
            )

        safe_candidates = [tool_name for tool_name in candidates if not self._tool_requires_approval(tool_name, step)]
        if safe_candidates:
            candidates = safe_candidates
        else:
            tool_name = candidates[0]
            request = {
                "step_id": step.step_id,
                "goal": step.goal,
                "tool_name": tool_name,
                "risk_level": step.risk_level,
                "reason": "工具需要人工审批。",
            }
            state["turn"] = state["turn"].model_copy(
                update={
                    "need_human_approval": True,
                    "approval_request": request,
                }
            )
            return StepResult(
                step_id=step.step_id,
                status="need_approval",
                tools_used=[tool_name],
                observations=[f"步骤 {step.step_id} 需要人工审批后才能使用 {tool_name}。"],
                result=None,
                error="需要人工审批",
                next_action="await_approval",
            )

        observations: List[str] = []
        tools_used: List[str] = []
        last_output: Any = None

        for round_index, tool_name in enumerate(candidates[: self.policy.max_tool_rounds]):
            selection = self._build_tool_selection(state, step, tool_name)
            raw_result = self.container.tool_executor.execute(ToolExecutionCommand(selection=selection))
            normalized = self.container.tool_result_normalizer.normalize(ToolNormalizationRequest(result=raw_result))
            tools_used.append(normalized.tool_name or tool_name)
            last_output = normalized.normalized_output
            observations.extend(self._observations_from_tool_result(tool_name, normalized.normalized_output))
            self._update_runtime_metrics(state, normalized, tool_name)

            if normalized.status in {ToolExecutionStatus.SUCCESS, ToolExecutionStatus.DEGRADED}:
                if normalized.status == ToolExecutionStatus.DEGRADED:
                    observations.append("工具结果已降级返回。")
                return StepResult(
                    step_id=step.step_id,
                    status="success",
                    tools_used=tools_used,
                    observations=observations,
                    result=last_output,
                    error=None,
                    next_action="next_step",
                )

            if round_index < len(candidates) - 1:
                observations.append(f"{tool_name} 执行失败，尝试下一个候选工具。")

        return StepResult(
            step_id=step.step_id,
            status="failed",
            tools_used=tools_used,
            observations=observations or [f"步骤 {step.step_id} 未能得到稳定结果。"],
            result=last_output,
            error="工具执行失败",
            next_action="replan",
        )

    def _build_tool_selection(self, state: GraphState, step: PlanStep, tool_name: str):
        _ = state["turn"]
        topic = self._topic_from_state(state)
        payload = self._tool_input_for_name(state, tool_name, step, topic)
        if isinstance(getattr(step, "input_payload", None), dict) and step.input_payload:
            payload = {**payload, **dict(step.input_payload)}
        if not payload:
            payload = {"topic": topic}
        return self.container.tool_planner.plan_from_name(tool_name, payload)

    def _tool_input_for_name(self, state: GraphState, tool_name: str, step: PlanStep, topic: str) -> Dict[str, Any]:
        return {"topic": topic}

    def _observations_from_tool_result(self, tool_name: str, payload: Dict[str, Any]) -> List[str]:
        data = payload.get("data") if isinstance(payload, dict) else payload
        observations: List[str] = []
        if isinstance(data, dict):
            if "matches" in data:
                observations.append("检索到 {count} 条候选知识。".format(count=len(data.get("matches") or [])))
            if "detail" in data:
                observations.append(str(data.get("detail")))
            if "topic" in data and not observations:
                observations.append("围绕主题 {topic} 获取了工具结果。".format(topic=data.get("topic")))
        elif isinstance(data, str):
            observations.append(data)
        else:
            observations.append(json.dumps(data, ensure_ascii=False))
        if not observations:
            observations.append("工具返回了结构化结果。")
        return observations

    def _update_runtime_metrics(self, state: GraphState, normalized, tool_name: str) -> None:
        runtime = state["runtime"]
        metrics = dict(runtime.metrics)
        metrics["plan_tool_rounds"] = int(metrics.get("plan_tool_rounds", 0) or 0) + 1
        metrics["last_plan_tool"] = tool_name
        if normalized.extra.get("degraded"):
            metrics["plan_degraded_tools"] = int(metrics.get("plan_degraded_tools", 0) or 0) + 1
        state["runtime"] = runtime.model_copy(update={"metrics": metrics})

    def _build_summary(self, turn) -> PlanExecutionSummary:
        plan = self._normalize_plan(turn.plan)
        completed_steps = len([item for item in turn.step_results if item.status == "success"])
        total_steps = len(plan)
        if turn.need_human_approval:
            status = "need_approval"
        elif turn.need_replan and completed_steps < total_steps:
            status = "partial" if completed_steps > 0 else "failed"
        elif total_steps and completed_steps >= total_steps:
            status = "completed"
        elif completed_steps > 0:
            status = "partial"
        else:
            status = "failed"

        key_findings: List[str] = []
        for result in turn.step_results:
            key_findings.extend(result.observations[:1])
        final_decision = turn.replan_reason or turn.final_answer
        if not final_decision and turn.step_results:
            last_result = turn.step_results[-1]
            if isinstance(last_result.result, dict):
                final_decision = str(last_result.result.get("summary") or last_result.result.get("detail") or "")
            elif isinstance(last_result.result, str):
                final_decision = last_result.result
        if not final_decision:
            final_decision = "等待人工审批" if turn.need_human_approval else "计划已完成"
        return PlanExecutionSummary(
            status=status,  # type: ignore[arg-type]
            completed_steps=completed_steps,
            total_steps=total_steps,
            key_findings=key_findings[:5],
            final_decision=final_decision,
        )

    def _build_default_plan(self, state: GraphState) -> List[PlanStep]:
        turn = state["turn"]
        intent = turn.intent
        topic = self._topic_from_state(state)
        goal = turn.raw_query.strip() or topic
        if intent == IntentType.FOLLOW_UP:
            return [
                PlanStep(
                    step_id="follow-up-1",
                    goal=f"基于当前上下文整理 {topic} 追问中的关键点",
                    expected_output="保守的追问结论",
                    risk_level="low",
                ),
            ]
        if intent in {IntentType.COMPARE, IntentType.EXPLAIN, IntentType.SUMMARY}:
            return [
                PlanStep(
                    step_id="analysis-1",
                    goal=f"基于当前已检索证据整理 {topic} 的保守结论",
                    expected_output="可直接用于回答的结论",
                    risk_level="low",
                ),
            ]
        return [
            PlanStep(
                step_id="fallback-1",
                goal=goal or "基于当前上下文完成复杂任务整理",
                expected_output="稳定的任务执行结论",
                risk_level="low",
            )
        ]

    def _build_recovery_plan(self, state: GraphState) -> List[PlanStep]:
        topic = self._topic_from_state(state)
        return [
            PlanStep(
                step_id="replan-analysis",
                goal=f"基于当前上下文重组 {topic} 的保守答案",
                expected_output="保守可回答的结论",
                risk_level="low",
            )
        ]

    def _candidate_tools(self, step: PlanStep, execution_mode: str) -> List[str]:
        registry = self._tool_registry()
        candidates: List[str] = []
        for tool_name in step.allowed_tools:
            if registry is None:
                continue
            if not registry.is_registered(tool_name):
                continue
            spec = registry.get(tool_name).spec
            if execution_mode not in spec.allowed_execution_modes and "auto" not in spec.allowed_execution_modes:
                continue
            candidates.append(tool_name)
        return candidates

    def _tool_requires_approval(self, tool_name: str, step: PlanStep) -> bool:
        registry = self._tool_registry()
        if registry is None or not registry.is_registered(tool_name):
            return True
        spec = registry.get(tool_name).spec
        if step.requires_approval or step.risk_level == "high":
            return True
        if spec.requires_approval:
            return True
        if spec.side_effect_level != SideEffectLevel.NONE:
            return True
        if step.risk_level == "medium" and spec.side_effect_level == SideEffectLevel.HIGH:
            return True
        return False

    @staticmethod
    def _step_can_run_without_tools(step: PlanStep) -> bool:
        return not step.allowed_tools and not step.requires_approval and step.risk_level == "low"

    def _request_approval(self, state: GraphState, *, step: PlanStep, tool_name: str, reason: str) -> GraphState:
        request = {
            "step_id": step.step_id,
            "goal": step.goal,
            "tool_name": tool_name,
            "risk_level": step.risk_level,
            "reason": reason,
        }
        state["turn"] = state["turn"].model_copy(
            update={
                "need_human_approval": True,
                "approval_request": request,
                "current_step": step,
            }
        )
        if not self._has_event(state, "approval_required"):
            state = self.append_event(
                state,
                "approval_required",
                {
                    "step_id": step.step_id,
                    "reason": reason,
                    "approval_request": request,
                    "risk_level": step.risk_level,
                },
            )
        return state

    def _mark_replan(
        self,
        state: GraphState,
        *,
        reason: str,
        stage: str,
        code: WorkflowErrorCode,
    ) -> GraphState:
        runtime = state["runtime"]
        errors = list(runtime.errors)
        errors.append(
            build_error(
                code,
                stage=stage,
                message=reason,
                retryable=False,
                is_terminal=False,
            )
        )
        state["runtime"] = runtime.model_copy(update={"errors": errors})
        state["turn"] = state["turn"].model_copy(update={"need_replan": True, "replan_reason": reason})
        return state

    def _topic_from_state(self, state: GraphState) -> str:
        turn = state["turn"]
        persistent = state["persistent"]
        if isinstance(turn.slots.get("topic"), str) and str(turn.slots["topic"]).strip():
            return str(turn.slots["topic"]).strip()
        if persistent.current_topic:
            return persistent.current_topic
        topic_hint = turn.slots.get("topic_hint") or state["runtime"].topic_hint
        if topic_hint:
            return str(topic_hint)
        return turn.raw_query or "general-topic"

    def _normalize_plan(self, plan: List[PlanStep]) -> List[PlanStep]:
        normalized: List[PlanStep] = []
        for _index, item in enumerate(plan):
            if isinstance(item, PlanStep):
                normalized.append(item)
                continue
            if isinstance(item, dict):
                try:
                    normalized.append(PlanStep.model_validate(item))
                except Exception:
                    continue
        return normalized[: self.policy.max_steps]

    def _tool_registry(self):
        executor = getattr(self.container, "tool_executor", None)
        return getattr(executor, "registry", None)

    @staticmethod
    def _has_event(state: GraphState, event_type: str) -> bool:
        return any(envelope.event_type == event_type for envelope in state["runtime"].emitted_events)
