"""
显式对话状态机

定义对话级别的状态流转，管理多轮对话的生命周期。
"""
from __future__ import annotations

from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class DialogState(str, Enum):
    """对话状态枚举"""
    IDLE = "idle"                          # 空闲状态，等待用户输入
    CLARIFYING = "clarifying"              # 追问状态，等待用户补充信息
    SEARCHING = "searching"                # 检索状态，正在查询信息
    COMPARING = "comparing"                # 对比状态，正在对比多家店
    ANSWERING = "answering"                # 回答状态，正在生成答案
    FOLLOW_UP = "follow_up"                # 跟进状态，处理后续问题
    ERROR = "error"                        # 错误状态，系统异常
    DEGRADED = "degraded"                  # 降级状态，使用兜底策略


class DialogTransition(BaseModel):
    """状态转移定义"""
    from_state: DialogState
    to_state: DialogState
    trigger: str
    condition: str | None = None


class DialogContext(BaseModel):
    """对话上下文，扩展PersistentSessionContext"""
    current_state: DialogState = DialogState.IDLE
    previous_state: DialogState | None = None
    state_history: list[DialogState] = Field(default_factory=list)
    transition_count: int = 0
    max_transitions: int = 20
    state_timeout_seconds: int = 300
    last_state_change_at: float | None = None
    
    # 任务上下文
    current_task: str | None = None  # query/recommend/comparison/clarification
    active_intent: str | None = None
    comparison_targets: list[str] = Field(default_factory=list)
    pending_slots: list[str] = Field(default_factory=list)
    task_state: str | None = None  # in_progress/completed/clarified


# 状态转移表
TRANSITIONS: list[DialogTransition] = [
    DialogTransition(from_state=DialogState.IDLE, to_state=DialogState.CLARIFYING, trigger="missing_info"),
    DialogTransition(from_state=DialogState.IDLE, to_state=DialogState.SEARCHING, trigger="has_info"),
    DialogTransition(from_state=DialogState.IDLE, to_state=DialogState.COMPARING, trigger="comparison_intent"),
    DialogTransition(from_state=DialogState.CLARIFYING, to_state=DialogState.SEARCHING, trigger="info_provided"),
    DialogTransition(from_state=DialogState.CLARIFYING, to_state=DialogState.IDLE, trigger="cancel"),
    DialogTransition(from_state=DialogState.SEARCHING, to_state=DialogState.ANSWERING, trigger="results_found"),
    DialogTransition(from_state=DialogState.SEARCHING, to_state=DialogState.DEGRADED, trigger="no_results"),
    DialogTransition(from_state=DialogState.SEARCHING, to_state=DialogState.ERROR, trigger="system_error"),
    DialogTransition(from_state=DialogState.COMPARING, to_state=DialogState.ANSWERING, trigger="comparison_done"),
    DialogTransition(from_state=DialogState.ANSWERING, to_state=DialogState.FOLLOW_UP, trigger="answer_provided"),
    DialogTransition(from_state=DialogState.FOLLOW_UP, to_state=DialogState.IDLE, trigger="conversation_end"),
    DialogTransition(from_state=DialogState.FOLLOW_UP, to_state=DialogState.SEARCHING, trigger="new_query"),
    DialogTransition(from_state=DialogState.DEGRADED, to_state=DialogState.IDLE, trigger="conversation_end"),
    DialogTransition(from_state=DialogState.ERROR, to_state=DialogState.IDLE, trigger="reset"),
]


class DialogStateMachine:
    """对话状态机管理器"""

    def __init__(self) -> None:
        self._transition_map: dict[DialogState, list[DialogTransition]] = {}
        for t in TRANSITIONS:
            if t.from_state not in self._transition_map:
                self._transition_map[t.from_state] = []
            self._transition_map[t.from_state].append(t)

    def get_initial_state(self) -> DialogContext:
        """获取初始对话上下文"""
        return DialogContext()

    def can_transition(self, context: DialogContext, trigger: str) -> bool:
        """检查是否可以进行状态转移"""
        if context.transition_count >= context.max_transitions:
            return False
        
        current = context.current_state
        if current not in self._transition_map:
            return False
        
        for t in self._transition_map[current]:
            if t.trigger == trigger:
                return True
        return False

    def transition(self, context: DialogContext, trigger: str) -> DialogContext:
        """执行状态转移"""
        if not self.can_transition(context, trigger):
            return context
        
        current = context.current_state
        for t in self._transition_map[current]:
            if t.trigger == trigger:
                import time
                new_context = context.model_copy(update={
                    "previous_state": current,
                    "current_state": t.to_state,
                    "state_history": context.state_history + [current],
                    "transition_count": context.transition_count + 1,
                    "last_state_change_at": time.time(),
                })
                return new_context
        
        return context

    def determine_trigger(
        self,
        context: DialogContext,
        has_clarification: bool = False,
        has_results: bool = False,
        is_comparison: bool = False,
        has_error: bool = False,
        is_degraded: bool = False,
    ) -> str | None:
        """根据当前情况确定触发器"""
        current = context.current_state
        
        if current == DialogState.IDLE:
            if has_clarification:
                return "missing_info"
            if is_comparison:
                return "comparison_intent"
            if has_results:
                return "has_info"
        
        elif current == DialogState.CLARIFYING:
            if not has_clarification:
                return "info_provided"
        
        elif current == DialogState.SEARCHING:
            if has_error:
                return "system_error"
            if is_degraded:
                return "no_results"
            if has_results:
                return "results_found"
        
        elif current == DialogState.COMPARING:
            if has_results:
                return "comparison_done"
        
        elif current == DialogState.ANSWERING:
            return "answer_provided"
        
        elif current == DialogState.FOLLOW_UP:
            if has_clarification:
                return "new_query"
        
        return None

    def get_state_info(self, context: DialogContext) -> dict[str, Any]:
        """获取当前状态信息"""
        return {
            "current_state": context.current_state.value,
            "previous_state": context.previous_state.value if context.previous_state else None,
            "transition_count": context.transition_count,
            "current_task": context.current_task,
            "active_intent": context.active_intent,
            "comparison_targets": context.comparison_targets,
            "pending_slots": context.pending_slots,
        }


# 全局状态机实例
dialog_state_machine = DialogStateMachine()