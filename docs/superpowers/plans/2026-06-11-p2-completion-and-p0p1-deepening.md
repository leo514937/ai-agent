# P2 Completion & P0/P1 Deepening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete all P2 tasks from gap analysis and deepen P0/P1 implementation scenarios for better coverage and robustness.

**Architecture:** (1) Add explicit dialog state machine for multi-turn management, (2) Integrate evaluation into CI pipeline, (3) Unify degraded messages with user-friendly prompts, (4) Add staleness detection with user notifications, (5) Implement retry quality evaluation, (6) Deepen P0/P1 modules with more scenarios and edge cases.

**Tech Stack:** Python, Pydantic, existing local_life modules, GitHub Actions

---

## Part 1: P2 Task Completion

### Task 1: Implement Explicit Dialog State Machine

**Files:**
- Create: `learning-agent-service/src/learning_agent_service/local_life/dialog_state_machine.py`
- Modify: `learning-agent-service/src/learning_agent_service/domain/contracts.py:732-764`
- Modify: `learning-agent-service/src/learning_agent_service/application/workflow/builder.py`

- [ ] **Step 1: Create dialog_state_machine.py with state definitions**

```python
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
```

- [ ] **Step 2: Create test for dialog state machine**

```python
# learning-agent-service/tests/local_life/test_dialog_state_machine.py
"""Tests for dialog state machine."""
from learning_agent_service.local_life.dialog_state_machine import (
    DialogStateMachine,
    DialogState,
    DialogContext,
)


def test_initial_state():
    sm = DialogStateMachine()
    ctx = sm.get_initial_state()
    assert ctx.current_state == DialogState.IDLE
    assert ctx.transition_count == 0


def test_transition_missing_info():
    sm = DialogStateMachine()
    ctx = sm.get_initial_state()
    
    new_ctx = sm.transition(ctx, "missing_info")
    assert new_ctx.current_state == DialogState.CLARIFYING
    assert new_ctx.transition_count == 1


def test_transition_searching():
    sm = DialogStateMachine()
    ctx = sm.get_initial_state()
    
    ctx1 = sm.transition(ctx, "has_info")
    assert ctx1.current_state == DialogState.SEARCHING
    
    ctx2 = sm.transition(ctx1, "results_found")
    assert ctx2.current_state == DialogState.ANSWERING


def test_transition_comparison():
    sm = DialogStateMachine()
    ctx = sm.get_initial_state()
    
    ctx1 = sm.transition(ctx, "comparison_intent")
    assert ctx1.current_state == DialogState.COMPARING
    
    ctx2 = sm.transition(ctx1, "comparison_done")
    assert ctx2.current_state == DialogState.ANSWERING


def test_cannot_transition():
    sm = DialogStateMachine()
    ctx = sm.get_initial_state()
    
    # IDLE -> ANSWERING is not allowed
    assert not sm.can_transition(ctx, "answer_provided")


def test_max_transitions():
    sm = DialogStateMachine()
    ctx = sm.get_initial_state()
    
    # Exhaust transitions
    for _ in range(20):
        ctx = sm.transition(ctx, "has_info")
        ctx = sm.transition(ctx, "results_found")
        ctx = sm.transition(ctx, "answer_provided")
        ctx = sm.transition(ctx, "new_query")
        ctx = sm.transition(ctx, "has_info")
        ctx = sm.transition(ctx, "results_found")
        ctx = sm.transition(ctx, "answer_provided")
        ctx = sm.transition(ctx, "conversation_end")
    
    assert ctx.transition_count >= 20
    assert not sm.can_transition(ctx, "has_info")


def test_determine_trigger():
    sm = DialogStateMachine()
    ctx = sm.get_initial_state()
    
    trigger = sm.determine_trigger(ctx, has_clarification=True)
    assert trigger == "missing_info"
    
    trigger = sm.determine_trigger(ctx, is_comparison=True)
    assert trigger == "comparison_intent"
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `pytest learning-agent-service/tests/local_life/test_dialog_state_machine.py -v`
Expected: All tests PASS

- [ ] **Step 4: Integrate dialog state machine into PersistentSessionContext**

Modify `learning-agent-service/src/learning_agent_service/domain/contracts.py:732-764`:

Add after line 764 (inside PersistentSessionContext):
```python
    # Dialog state machine fields
    dialog_state: str | None = None  # DialogState value
    dialog_task: str | None = None  # current_task
    dialog_intent: str | None = None  # active_intent
    dialog_comparison_targets: list[str] = Field(default_factory=list)
    dialog_pending_slots: list[str] = Field(default_factory=list)
    dialog_transition_count: int = 0
```

- [ ] **Step 5: Integrate into builder.py response flow**

Add at the beginning of `_response_builder_node`:
```python
    # Update dialog state
    from learning_agent_service.local_life.dialog_state_machine import dialog_state_machine, DialogState
    
    persistent = state.get("persistent")
    if persistent:
        from learning_agent_service.local_life.dialog_state_machine import DialogContext
        
        dialog_ctx = DialogContext(
            current_state=DialogState(str(getattr(persistent, "dialog_state", "") or DialogState.IDLE.value)),
            transition_count=int(getattr(persistent, "dialog_transition_count", 0) or 0),
        )
        
        # Determine trigger based on current situation
        has_clarification = bool(turn_extra.get("clarification_needed"))
        has_results = bool(turn_extra.get("evidence_claims"))
        is_comparison = str(getattr(answer_contract, "answer_style", "") or "") == "comparison"
        
        trigger = dialog_state_machine.determine_trigger(
            dialog_ctx,
            has_clarification=has_clarification,
            has_results=has_results,
            is_comparison=is_comparison,
        )
        
        if trigger:
            new_ctx = dialog_state_machine.transition(dialog_ctx, trigger)
            persistent.dialog_state = new_ctx.current_state.value
            persistent.dialog_transition_count = new_ctx.transition_count
```

- [ ] **Step 6: Commit**

```bash
git add learning-agent-service/src/learning_agent_service/local_life/dialog_state_machine.py
git add learning-agent-service/tests/local_life/test_dialog_state_machine.py
git add learning-agent-service/src/learning_agent_service/domain/contracts.py
git add learning-agent-service/src/learning_agent_service/application/workflow/builder.py
git commit -m "feat: add explicit dialog state machine for multi-turn management"
```

---

### Task 2: Integrate Evaluation into CI Pipeline

**Files:**
- Modify: `learning-agent-service/.github/workflows/ci.yml`
- Create: `learning-agent-service/scripts/run_evaluation.py`

- [ ] **Step 1: Create evaluation runner script**

```python
#!/usr/bin/env python3
"""
Evaluation runner for CI pipeline.
Runs golden case evaluation and outputs results in CI-friendly format.
"""
import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from learning_agent_service.local_life.eval.run_golden_cases import run_evaluation


def main():
    """Run evaluation and output results."""
    print("=" * 60)
    print("Running Golden Case Evaluation")
    print("=" * 60)
    
    try:
        results = run_evaluation()
        
        # Output summary
        print(f"\nTotal cases: {results.get('total', 0)}")
        print(f"Passed: {results.get('passed', 0)}")
        print(f"Failed: {results.get('failed', 0)}")
        print(f"Pass rate: {results.get('pass_rate', 0):.1%}")
        
        # Output failure details
        if results.get('failures'):
            print("\nFailed cases:")
            for failure in results['failures']:
                print(f"  - {failure.get('case_id')}: {failure.get('reason')}")
        
        # Exit with appropriate code
        if results.get('failed', 0) > 0:
            print("\n❌ Evaluation FAILED")
            sys.exit(1)
        else:
            print("\n✅ Evaluation PASSED")
            sys.exit(0)
            
    except Exception as e:
        print(f"\n❌ Evaluation ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Update CI workflow to include evaluation**

```yaml
name: Learning Agent Service CI

on:
  push:
    paths:
      - "learning-agent-service/**"
  pull_request:
    paths:
      - "learning-agent-service/**"

jobs:
  test:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: learning-agent-service
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install package
        run: python -m pip install --upgrade pip && pip install .

      - name: Compile
        run: python -m compileall src/learning_agent_service app.py

      - name: Run tests
        run: python -m unittest discover -s tests -p "test_*.py"

  evaluation:
    runs-on: ubuntu-latest
    needs: test
    defaults:
      run:
        working-directory: learning-agent-service
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install package
        run: python -m pip install --upgrade pip && pip install .

      - name: Run evaluation
        run: python scripts/run_evaluation.py
        continue-on-error: false

      - name: Upload evaluation results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: evaluation-results
          path: learning-agent-service/eval/results/
          retention-days: 30
```

- [ ] **Step 3: Make script executable**

Run: `chmod +x learning-agent-service/scripts/run_evaluation.py`

- [ ] **Step 4: Test the evaluation script locally**

Run: `cd learning-agent-service && python scripts/run_evaluation.py`
Expected: Evaluation runs and outputs results

- [ ] **Step 5: Commit**

```bash
git add learning-agent-service/.github/workflows/ci.yml
git add learning-agent-service/scripts/run_evaluation.py
git commit -m "ci: integrate golden case evaluation into CI pipeline"
```

---

### Task 3: Unify Degraded Messages with User-Friendly Prompts

**Files:**
- Create: `learning-agent-service/src/learning_agent_service/local_life/boundary_prompts.py`
- Modify: `learning-agent-service/src/learning_agent_service/local_life/realtime_contract.py`
- Modify: `learning-agent-service/src/learning_agent_service/application/workflow/graphs.py`

- [ ] **Step 1: Create boundary_prompts.py with unified prompts**

```python
"""
统一边界提示策略

定义用户友好的降级消息，替代技术性错误信息。
"""
from __future__ import annotations


# 边界提示字典
BOUNDARY_PROMPTS: dict[str, str] = {
    # 位置相关
    "no_location": "我需要知道您所在的位置才能推荐附近的商家，请告诉我您的城市或位置。",
    "location_unavailable": "抱歉，该位置暂时无法提供服务。请尝试切换到其他城市。",
    
    # 商家相关
    "no_shop_found": "我没有找到您询问的商家信息，请确认店名是否正确。",
    "shop_name_ambiguous": "您提到的店名有多个匹配，请告诉我具体是哪一家。",
    
    # 信息相关
    "no_coupon_evidence": "我暂时无法确认这家店的优惠券信息，建议以店铺页面显示为准。",
    "no_open_status": "我暂时无法确认这家店当前是否营业，建议以店铺页面实时状态为准。",
    "no_distance_info": "我暂时无法确认这家店与你的实时距离信息，建议以地图页面显示为准。",
    
    # 数据新鲜度
    "outdated_info": "这家店的信息可能不是最新的，建议您直接联系商家确认。",
    "stale_evidence": "这部分信息可能已过时，建议以商家页面最新信息为准。",
    
    # 系统相关
    "evidence_insufficient": "我目前没有足够的信息来回答这个问题，您可以尝试换一种问法。",
    "service_unavailable": "抱歉，服务暂时不可用，请稍后再试。",
    "query_too_complex": "您的问题比较复杂，我可能无法完整回答，建议您分步提问。",
    
    # 意图相关
    "out_of_scope": "抱歉，我主要提供本地生活服务信息，其他问题我可能帮不上忙。",
    "comparison_insufficient": "对比信息不足，无法给出有效建议，您可以分别查询两家店的详细信息。",
    
    # 追问相关
    "clarify_shop_name": "请问您想了解哪一家店的具体信息呢？可以告诉我店名或品牌。",
    "clarify_location": "为了给您提供更准确的信息，请问您目前在哪个城市或商圈附近？",
    "clarify_category": "请问您具体想找什么类型的店呢？比如火锅、烧烤、粤菜、还是咖啡甜点？",
}


def get_boundary_prompt(key: str, shop_name: str | None = None, **kwargs: str) -> str:
    """获取边界提示消息
    
    Args:
        key: 提示键名
        shop_name: 商家名称（可选）
        **kwargs: 额外的替换参数
        
    Returns:
        用户友好的提示消息
    """
    template = BOUNDARY_PROMPTS.get(key, BOUNDARY_PROMPTS["evidence_insufficient"])
    
    # 替换商家名称
    if shop_name:
        template = template.replace("这家店", shop_name, 1)
    
    # 替换其他参数
    for k, v in kwargs.items():
        template = template.replace(f"{{{k}}}", v)
    
    return template


def get_freshness_prompt(freshness_status: str, shop_name: str | None = None) -> str | None:
    """根据数据新鲜度状态获取提示
    
    Args:
        freshness_status: 新鲜度状态 (realtime/historical/mixed/unavailable)
        shop_name: 商家名称
        
    Returns:
        提示消息或None
    """
    if freshness_status == "historical":
        return get_boundary_prompt("outdated_info", shop_name)
    elif freshness_status == "unavailable":
        return get_boundary_prompt("evidence_insufficient", shop_name)
    return None
```

- [ ] **Step 2: Update realtime_contract.py to use boundary prompts**

Replace the entire file:
```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from learning_agent_service.local_life.boundary_prompts import get_boundary_prompt


class RealtimeContract(BaseModel):
    facet: str
    requires_tool: bool = True
    allowed_tools: list[str]
    freshness_required: Literal["realtime", "near_realtime", "session"] = "realtime"
    fallback_allowed: bool = True
    fallback_message: str
    cannot_infer_from_rag: bool = True


_REALTIME_CONTRACTS: dict[str, RealtimeContract] = {
    "coupon": RealtimeContract(
        facet="coupon",
        allowed_tools=["get_coupon_list"],
        fallback_message=get_boundary_prompt("no_coupon_evidence"),
    ),
    "open_status": RealtimeContract(
        facet="open_status",
        allowed_tools=["check_open_status"],
        fallback_message=get_boundary_prompt("no_open_status"),
    ),
    "distance_eta": RealtimeContract(
        facet="distance_eta",
        allowed_tools=["get_distance_eta"],
        fallback_message=get_boundary_prompt("no_distance_info"),
    ),
}


def get_realtime_contract(facet: str | None) -> RealtimeContract | None:
    key = str(facet or "").strip()
    if not key:
        return None
    return _REALTIME_CONTRACTS.get(key)


def fallback_message_for_facet(facet: str | None, shop_name: str | None = None) -> str | None:
    contract = get_realtime_contract(facet)
    if contract is None:
        return None
    shop_label = str(shop_name or "").strip() or "这家店"
    return contract.fallback_message.replace("这家店", shop_label, 1)
```

- [ ] **Step 3: Update graphs.py to use boundary prompts**

Find and replace the degraded message in `learning-agent-service/src/learning_agent_service/application/workflow/graphs.py`:

Replace:
```python
normalized_output={"status": "degraded", "error": str(exc), "message": "实时券信息暂不可用"}
```

With:
```python
from learning_agent_service.local_life.boundary_prompts import get_boundary_prompt
normalized_output={"status": "degraded", "error": str(exc), "message": get_boundary_prompt("service_unavailable")}
```

- [ ] **Step 4: Create test for boundary prompts**

```python
# learning-agent-service/tests/local_life/test_boundary_prompts.py
"""Tests for boundary prompts."""
from learning_agent_service.local_life.boundary_prompts import (
    get_boundary_prompt,
    get_freshness_prompt,
    BOUNDARY_PROMPTS,
)


def test_get_boundary_prompt_default():
    prompt = get_boundary_prompt("no_location")
    assert "位置" in prompt


def test_get_boundary_prompt_with_shop():
    prompt = get_boundary_prompt("no_coupon_evidence", shop_name="海底捞")
    assert "海底捞" in prompt


def test_get_boundary_prompt_unknown_key():
    prompt = get_boundary_prompt("unknown_key")
    assert "信息" in prompt


def test_get_freshness_prompt_historical():
    prompt = get_freshness_prompt("historical", shop_name="海底捞")
    assert prompt is not None
    assert "过时" in prompt or "最新" in prompt


def test_get_freshness_prompt_realtime():
    prompt = get_freshness_prompt("realtime")
    assert prompt is None


def test_all_prompts_are_strings():
    for key, value in BOUNDARY_PROMPTS.items():
        assert isinstance(value, str), f"Prompt {key} is not a string"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest learning-agent-service/tests/local_life/test_boundary_prompts.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add learning-agent-service/src/learning_agent_service/local_life/boundary_prompts.py
git add learning-agent-service/src/learning_agent_service/local_life/realtime_contract.py
git add learning-agent-service/src/learning_agent_service/application/workflow/graphs.py
git add learning-agent-service/tests/local_life/test_boundary_prompts.py
git commit -m "feat: unify degraded messages with user-friendly boundary prompts"
```

---

### Task 4: Implement Staleness Detection with User Notifications

**Files:**
- Modify: `learning-agent-service/src/learning_agent_service/local_life/realtime_conflict_resolver.py`
- Modify: `learning-agent-service/src/learning_agent_service/local_life/response_builder/answers.py`

- [ ] **Step 1: Add staleness detection functions to realtime_conflict_resolver.py**

Add at the end of the file (before `__all__`):
```python
def detect_staleness(evidence_metadata: dict[str, Any]) -> tuple[bool, str]:
    """检测证据是否过时
    
    Args:
        evidence_metadata: 证据元数据
        
    Returns:
        (is_stale, reason) 元组
    """
    # 检查显式过时标记
    if evidence_metadata.get("deprecated") or evidence_metadata.get("is_deprecated"):
        return True, "deprecated"
    
    if evidence_metadata.get("stale"):
        return True, "stale"
    
    # 检查时间戳
    import_time = evidence_metadata.get("import_time") or evidence_metadata.get("created_at")
    if import_time:
        try:
            from datetime import datetime
            if isinstance(import_time, str):
                import_time = datetime.fromisoformat(import_time.replace("Z", "+00:00"))
            age_seconds = (datetime.now() - import_time).total_seconds()
            if age_seconds > RAG_STALENESS_THRESHOLD:
                return True, f"age_{int(age_seconds)}"
        except (ValueError, TypeError):
            pass
    
    return False, ""


def get_staleness_warning(staleness_reason: str, shop_name: str | None = None) -> str | None:
    """获取过时警告消息
    
    Args:
        staleness_reason: 过时原因
        shop_name: 商家名称
        
    Returns:
        警告消息或None
    """
    from learning_agent_service.local_life.boundary_prompts import get_boundary_prompt
    
    if staleness_reason == "deprecated":
        return get_boundary_prompt("outdated_info", shop_name)
    elif staleness_reason == "stale":
        return get_boundary_prompt("stale_evidence", shop_name)
    elif staleness_reason.startswith("age_"):
        return get_boundary_prompt("outdated_info", shop_name)
    
    return None


# 更新 __all__
__all__ = [
    "DataSourcePriority",
    "ConflictResolution",
    "REALTIME_FACETS",
    "resolve_realtime_conflict",
    "should_use_tool_result_for_facet",
    "get_freshness_status",
    "detect_staleness",
    "get_staleness_warning",
]
```

- [ ] **Step 2: Update response_builder/answers.py to include staleness warnings**

Find the function that builds answers and add staleness warning logic. Look for where evidence is processed and add:

```python
# 在证据处理后添加过时检测
from learning_agent_service.local_life.realtime_conflict_resolver import detect_staleness, get_staleness_warning

# 在组装答案时检查证据新鲜度
staleness_warnings = []
for evidence in evidence_list:
    metadata = evidence.get("metadata", {})
    is_stale, reason = detect_staleness(metadata)
    if is_stale:
        warning = get_staleness_warning(reason, shop_name)
        if warning:
            staleness_warnings.append(warning)

# 在答案末尾添加过时警告
if staleness_warnings:
    answer_lines.append("")  # 空行分隔
    answer_lines.extend(staleness_warnings[:1])  # 只添加第一条警告
```

- [ ] **Step 3: Create test for staleness detection**

```python
# learning-agent-service/tests/local_life/test_staleness_detection.py
"""Tests for staleness detection."""
from learning_agent_service.local_life.realtime_conflict_resolver import (
    detect_staleness,
    get_staleness_warning,
)


def test_detect_staleness_deprecated():
    metadata = {"deprecated": True}
    is_stale, reason = detect_staleness(metadata)
    assert is_stale
    assert reason == "deprecated"


def test_detect_staleness_stale():
    metadata = {"stale": True}
    is_stale, reason = detect_staleness(metadata)
    assert is_stale
    assert reason == "stale"


def test_detect_staleness_fresh():
    metadata = {"import_time": "2026-06-11T00:00:00+00:00"}
    is_stale, reason = detect_staleness(metadata)
    assert not is_stale


def test_get_staleness_warning_deprecated():
    warning = get_staleness_warning("deprecated", "海底捞")
    assert warning is not None
    assert "海底捞" in warning


def test_get_staleness_warning_stale():
    warning = get_staleness_warning("stale")
    assert warning is not None


def test_get_staleness_warning_age():
    warning = get_staleness_warning("age_100000")
    assert warning is not None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest learning-agent-service/tests/local_life/test_staleness_detection.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add learning-agent-service/src/learning_agent_service/local_life/realtime_conflict_resolver.py
git add learning-agent-service/src/learning_agent_service/local_life/response_builder/answers.py
git add learning-agent-service/tests/local_life/test_staleness_detection.py
git commit -m "feat: add staleness detection with user notifications"
```

---

### Task 5: Implement Retry Quality Evaluation

**Files:**
- Create: `learning-agent-service/src/learning_agent_service/local_life/retry_quality_evaluator.py`
- Modify: `learning-agent-service/src/learning_agent_service/application/workflow/builder.py`

- [ ] **Step 1: Create retry_quality_evaluator.py**

```python
"""
Retry质量评估器

评估retry前后的答案质量，确保retry确实改善了答案。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RetryQualityMetrics:
    """Retry质量指标"""
    pre_retry_score: float = 0.0
    post_retry_score: float = 0.0
    improvement: float = 0.0
    should_keep_retry: bool = True
    reason: str = ""


def calculate_answer_quality_score(
    answer: str,
    evidence_count: int,
    has_tool_result: bool,
    forbidden_facets_leaked: bool = False,
    cross_shop_leak: bool = False,
) -> float:
    """计算答案质量分数 (0-1)
    
    Args:
        answer: 答案文本
        evidence_count: 证据数量
        has_tool_result: 是否有工具调用结果
        forbidden_facets_leaked: 是否泄露禁止维度
        cross_shop_leak: 是否串店
        
    Returns:
        质量分数 (0-1)
    """
    score = 0.5  # 基础分
    
    # 证据数量加分
    if evidence_count >= 3:
        score += 0.2
    elif evidence_count >= 1:
        score += 0.1
    
    # 工具调用加分
    if has_tool_result:
        score += 0.1
    
    # 答案长度合理性
    answer_len = len(answer)
    if 50 <= answer_len <= 500:
        score += 0.1
    elif answer_len > 0:
        score += 0.05
    
    # 惩罚
    if forbidden_facets_leaked:
        score -= 0.3
    if cross_shop_leak:
        score -= 0.3
    if evidence_count == 0:
        score -= 0.2
    
    return max(0.0, min(1.0, score))


def evaluate_retry_quality(
    pre_retry_answer: str,
    post_retry_answer: str,
    pre_retry_evidence_count: int,
    post_retry_evidence_count: int,
    has_tool_result: bool,
    forbidden_facets_leaked: bool = False,
    cross_shop_leak: bool = False,
) -> RetryQualityMetrics:
    """评估retry质量
    
    Args:
        pre_retry_answer: retry前的答案
        post_retry_answer: retry后的答案
        pre_retry_evidence_count: retry前的证据数量
        post_retry_evidence_count: retry后的证据数量
        has_tool_result: 是否有工具调用结果
        forbidden_facets_leaked: 是否泄露禁止维度
        cross_shop_leak: 是否串店
        
    Returns:
        RetryQualityMetrics
    """
    pre_score = calculate_answer_quality_score(
        pre_retry_answer,
        pre_retry_evidence_count,
        has_tool_result,
        forbidden_facets_leaked,
        cross_shop_leak,
    )
    
    post_score = calculate_answer_quality_score(
        post_retry_answer,
        post_retry_evidence_count,
        has_tool_result,
        forbidden_facets_leaked,
        cross_shop_leak,
    )
    
    improvement = post_score - pre_score
    
    # 决策逻辑
    should_keep = True
    reason = ""
    
    if improvement < -0.1:
        # 质量明显下降
        should_keep = False
        reason = "quality_degraded"
    elif improvement < 0:
        # 轻微下降
        should_keep = True
        reason = "slight_degradation_tolerated"
    elif improvement == 0:
        # 无变化
        should_keep = True
        reason = "no_change"
    else:
        # 有提升
        should_keep = True
        reason = "improved"
    
    return RetryQualityMetrics(
        pre_retry_score=pre_score,
        post_retry_score=post_score,
        improvement=improvement,
        should_keep_retry=should_keep,
        reason=reason,
    )
```

- [ ] **Step 2: Integrate retry quality evaluation into builder.py**

Modify `_prepare_retry_node` to save pre-retry state:
```python
def _prepare_retry_node(state: GraphState) -> GraphState:
    turn = state["turn"]
    turn_extra = _turn_extra(state)
    review_report = turn_extra.get("review_report")
    if review_report:
        from learning_agent_service.domain.contracts import RewriteDecision
        
        retry_count = int(getattr(review_report, "retry_count", 0)) + 1
        setattr(review_report, "retry_count", retry_count)
        
        repair_hint = getattr(review_report, "repair_hint", "")
        
        # 保存retry前的状态用于质量评估
        turn_extra["pre_retry_answer"] = str(getattr(turn, "final_answer", "") or "")
        turn_extra["pre_retry_evidence_count"] = len(list(turn_extra.get("evidence_claims") or []))
        
        rewrite = RewriteDecision(
            should_rewrite=True,
            rewritten_query=str(getattr(turn, "raw_query", "")) + f" {repair_hint}",
            reason="retry_repair_answer",
            top_k_override=10,
            extra={"failed_facets": getattr(review_report, "failed_facets", [])}
        )
        
        turn_extra["rewrite_decision"] = rewrite
        routing = getattr(turn, "routing_decision", None)
        if routing is not None:
            turn = turn.model_copy(update={"routing_decision": routing.model_copy(update={"rewrite_decision": rewrite})})

        if "rag_result" in turn_extra:
            del turn_extra["rag_result"]
        turn_extra["review_report"] = review_report
        
    state["turn"] = turn.model_copy(update={"extra": turn_extra})
    return state
```

Add new function for retry quality evaluation:
```python
def _evaluate_retry_quality(state: GraphState) -> GraphState:
    """评估retry质量，如果质量下降则回退到retry前的答案"""
    turn = state["turn"]
    turn_extra = _turn_extra(state)
    
    pre_retry_answer = turn_extra.get("pre_retry_answer")
    post_retry_answer = str(getattr(turn, "final_answer", "") or "")
    pre_retry_evidence_count = int(turn_extra.get("pre_retry_evidence_count", 0) or 0)
    post_retry_evidence_count = len(list(turn_extra.get("evidence_claims") or []))
    
    if pre_retry_answer and post_retry_answer:
        from learning_agent_service.local_life.retry_quality_evaluator import evaluate_retry_quality
        
        metrics = evaluate_retry_quality(
            pre_retry_answer=pre_retry_answer,
            post_retry_answer=post_retry_answer,
            pre_retry_evidence_count=pre_retry_evidence_count,
            post_retry_evidence_count=post_retry_evidence_count,
            has_tool_result=bool(turn_extra.get("tool_results")),
        )
        
        turn_extra["retry_quality_metrics"] = metrics
        
        if not metrics.should_keep_retry:
            # 回退到retry前的答案
            turn = turn.model_copy(update={"final_answer": pre_retry_answer})
            turn_extra["retry_degraded"] = True
    
    state["turn"] = turn.model_copy(update={"extra": turn_extra})
    return state
```

- [ ] **Step 3: Add retry quality evaluation node to workflow**

In the workflow graph definition, add the new node after retry and before final_answer.

- [ ] **Step 4: Create test for retry quality evaluator**

```python
# learning-agent-service/tests/local_life/test_retry_quality_evaluator.py
"""Tests for retry quality evaluator."""
from learning_agent_service.local_life.retry_quality_evaluator import (
    calculate_answer_quality_score,
    evaluate_retry_quality,
)


def test_calculate_answer_quality_score_good():
    score = calculate_answer_quality_score(
        answer="这是一家不错的餐厅，环境优雅，服务周到。人均消费约100元。",
        evidence_count=5,
        has_tool_result=True,
    )
    assert score > 0.7


def test_calculate_answer_quality_score_bad():
    score = calculate_answer_quality_score(
        answer="",
        evidence_count=0,
        has_tool_result=False,
    )
    assert score < 0.3


def test_calculate_answer_quality_score_leak():
    score = calculate_answer_quality_score(
        answer="推荐其他店铺",
        evidence_count=3,
        has_tool_result=True,
        forbidden_facets_leaked=True,
    )
    assert score < 0.5


def test_evaluate_retry_quality_improved():
    metrics = evaluate_retry_quality(
        pre_retry_answer="简短回答",
        post_retry_answer="更详细的回答，包含更多信息",
        pre_retry_evidence_count=1,
        post_retry_evidence_count=5,
        has_tool_result=True,
    )
    assert metrics.improvement > 0
    assert metrics.should_keep_retry


def test_evaluate_retry_quality_degraded():
    metrics = evaluate_retry_quality(
        pre_retry_answer="详细的回答，包含更多信息",
        post_retry_answer="简短回答",
        pre_retry_evidence_count=5,
        post_retry_evidence_count=1,
        has_tool_result=True,
    )
    assert metrics.improvement < -0.1
    assert not metrics.should_keep_retry
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest learning-agent-service/tests/local_life/test_retry_quality_evaluator.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add learning-agent-service/src/learning_agent_service/local_life/retry_quality_evaluator.py
git add learning-agent-service/src/learning_agent_service/application/workflow/builder.py
git add learning-agent-service/tests/local_life/test_retry_quality_evaluator.py
git commit -m "feat: add retry quality evaluation to prevent quality degradation"
```

---

## Part 2: P0/P1 Deepening

### Task 6: Enhance Failure Mode Mapping Detection

**Files:**
- Modify: `learning-agent-service/src/learning_agent_service/local_life/failure_mode_mapping.py`

- [ ] **Step 1: Add more failure modes and detection rules**

Add to FAILURE_MODES dictionary:
```python
    # ==================== P0 深化 ====================
    "realtime_facet_rag_source": FailureMode(
        mode_id="realtime_facet_rag_source",
        name="实时信息从RAG获取",
        description="实时维度（券/营业/距离）从RAG获取而非工具",
        category=FailureCategory.EVIDENCE,
        severity=FailureSeverity.P0,
        typical_cause="realtime_facets未触发tool调用",
        affected_module="route_gate, tool_planner",
        detection_rule="realtime facet 无 tool 调用",
        suggested_test="验证实时维度必须调用工具",
        example_query="海底捞有券吗",
        example_failure="从RAG返回券信息而非调用get_coupon_list",
    ),
    "comparison_single_shop": FailureMode(
        mode_id="comparison_single_shop",
        name="对比只输出单店",
        description="对比查询只输出一家店的信息",
        category=FailureCategory.ANSWER,
        severity=FailureSeverity.P0,
        typical_cause="comparison模板缺失或LLM未遵循",
        affected_module="answer_structure_composer",
        detection_rule="comparison style 但答案只有一家店",
        suggested_test="验证对比查询输出两家店",
        example_query="海底捞和呷哺呷哺哪个好",
        example_failure="只介绍了海底捞，未提及呷哺呷哺",
    ),
    "clarification_loop": FailureMode(
        mode_id="clarification_loop",
        name="追问循环",
        description="连续多轮追问相同信息",
        category=FailureCategory.CLARIFICATION,
        severity=FailureSeverity.P1,
        typical_cause="追问策略未考虑历史追问",
        affected_module="clarification_strategy",
        detection_rule="连续2+轮追问相同slot",
        suggested_test="验证多轮对话不重复追问",
        example_query="（连续3轮被问位置）",
        example_failure="每次都追问位置，未记住已追问",
    ),
    "stale_evidence_used": FailureMode(
        mode_id="stale_evidence_used",
        name="使用过时证据",
        description="使用明显过时的证据生成答案",
        category=FailureCategory.EVIDENCE,
        severity=FailureSeverity.P1,
        typical_cause="未检测证据新鲜度",
        affected_module="rag_guardrail, evidence_pack",
        detection_rule="evidence metadata 有 stale/deprecated 标记",
        suggested_test="验证过时证据被过滤或提示",
        example_query="这家店还在营业吗",
        example_failure="使用2年前的RAG数据回答",
    ),
    "scene_violation_not_caught": FailureMode(
        mode_id="scene_violation_not_caught",
        name="场景违禁词未过滤",
        description="答案包含场景违禁词",
        category=FailureCategory.ANSWER,
        severity=FailureSeverity.P1,
        typical_cause="scene_policy未生效",
        affected_module="scene_policy, rag_guardrail",
        detection_rule="答案包含场景违禁词",
        suggested_test="验证场景过滤生效",
        example_query="约会适合去哪家",
        example_failure="推荐了'吵闹'的餐厅",
    ),
```

- [ ] **Step 2: Add detection methods to FailureModeDetector**

Add methods to the FailureModeDetector class:
```python
    def detect_realtime_facet_issues(
        self,
        answer_text: str,
        realtime_facets: list[str],
        tools_called: list[str],
    ) -> list[str]:
        """检测实时维度问题"""
        detected = []
        
        realtime_tool_map = {
            "coupon": "get_coupon_list",
            "open_status": "check_open_status",
            "distance_eta": "get_distance_eta",
        }
        
        for facet in realtime_facets:
            if facet in realtime_tool_map:
                required_tool = realtime_tool_map[facet]
                if required_tool not in tools_called:
                    detected.append("realtime_facet_rag_source")
        
        return detected

    def detect_comparison_issues(
        self,
        answer_style: str,
        answer_text: str,
        shop_count: int,
    ) -> list[str]:
        """检测对比问题"""
        detected = []
        
        if answer_style == "comparison" and shop_count < 2:
            detected.append("comparison_single_shop")
        
        return detected

    def detect_staleness_issues(
        self,
        evidence_metadata_list: list[dict],
    ) -> list[str]:
        """检测过时证据问题"""
        detected = []
        
        for metadata in evidence_metadata_list:
            if metadata.get("deprecated") or metadata.get("stale"):
                detected.append("stale_evidence_used")
                break
        
        return detected
```

- [ ] **Step 3: Add tests for new detection methods**

```python
# Add to existing test file or create new one
def test_detect_realtime_facet_issues():
    detector = FailureModeDetector()
    
    # 有tool调用 - 正常
    issues = detector.detect_realtime_facet_issues(
        answer_text="有优惠券",
        realtime_facets=["coupon"],
        tools_called=["get_coupon_list"],
    )
    assert len(issues) == 0
    
    # 无tool调用 - 问题
    issues = detector.detect_realtime_facet_issues(
        answer_text="有优惠券",
        realtime_facets=["coupon"],
        tools_called=[],
    )
    assert "realtime_facet_rag_source" in issues


def test_detect_comparison_issues():
    detector = FailureModeDetector()
    
    # 对比但只有一家店 - 问题
    issues = detector.detect_comparison_issues(
        answer_style="comparison",
        answer_text="海底捞不错",
        shop_count=1,
    )
    assert "comparison_single_shop" in issues
    
    # 对比有两家店 - 正常
    issues = detector.detect_comparison_issues(
        answer_style="comparison",
        answer_text="海底捞和呷哺呷哺对比",
        shop_count=2,
    )
    assert len(issues) == 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest learning-agent-service/tests/local_life/test_failure_mode_mapping.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add learning-agent-service/src/learning_agent_service/local_life/failure_mode_mapping.py
git commit -m "feat: enhance failure mode mapping with more detection rules"
```

---

### Task 7: Expand Golden Cases to 80+ Examples

**Files:**
- Modify: `learning-agent-service/eval/local_life/golden_cases.jsonl`

- [ ] **Step 1: Add new golden cases for missing intents**

Add the following cases to golden_cases.jsonl:

```jsonl
{"case_id": "D31-1", "intent": "open_status", "description": "营业状态查询-营业中", "turns": [{"user": "海底捞水晶城店现在开门吗"}], "expected_route": "resolve_target_shop", "expected_entity": "海底捞(水晶城购物中心店)", "expected_tool": "check_open_status", "expected_output_contains": ["营业", "开门"], "forbidden_output": ["推荐其他店"], "expected_metrics": {"single_shop_mode": true}, "failure_modes": ["wrong_entity"]}
{"case_id": "D31-2", "intent": "open_status", "description": "营业状态查询-已打烊", "turns": [{"user": "呷哺呷哺万达店几点关门"}], "expected_route": "resolve_target_shop", "expected_entity": "呷哺呷哺(万达广场店)", "expected_tool": "check_open_status", "expected_output_contains": ["关门", "营业时间"], "forbidden_output": ["推荐其他店"], "expected_metrics": {"single_shop_mode": true}, "failure_modes": ["wrong_entity"]}
{"case_id": "D32-1", "intent": "distance", "description": "距离查询-具体距离", "turns": [{"user": "海底捞水晶城店离我多远"}], "expected_route": "resolve_target_shop", "expected_entity": "海底捞(水晶城购物中心店)", "expected_tool": "get_distance_eta", "expected_output_contains": ["公里", "距离"], "forbidden_output": ["推荐其他店"], "expected_metrics": {"single_shop_mode": true}, "failure_modes": ["wrong_entity"]}
{"case_id": "D32-2", "intent": "distance", "description": "距离查询-导航时间", "turns": [{"user": "去呷哺呷哺万达店怎么走"}], "expected_route": "resolve_target_shop", "expected_entity": "呷哺呷哺(万达广场店)", "expected_tool": "get_distance_eta", "expected_output_contains": ["分钟", "路程"], "forbidden_output": ["推荐其他店"], "expected_metrics": {"single_shop_mode": true}, "failure_modes": ["wrong_entity"]}
{"case_id": "D33-1", "intent": "comparison", "description": "对比查询-环境对比", "turns": [{"user": "海底捞和呷哺呷哺哪家环境更好"}], "expected_route": "resolve_target_shop", "expected_entity": null, "expected_tool": null, "expected_output_contains": ["海底捞", "呷哺", "环境"], "forbidden_output": ["只介绍一家"], "expected_metrics": {"single_shop_mode": false}, "failure_modes": ["comparison_single_shop"]}
{"case_id": "D33-2", "intent": "comparison", "description": "对比查询-价格对比", "turns": [{"user": "海底捞和巴奴毛肚火锅哪个便宜"}], "expected_route": "resolve_target_shop", "expected_entity": null, "expected_tool": null, "expected_output_contains": ["海底捞", "巴奴", "价格"], "forbidden_output": ["只介绍一家"], "expected_metrics": {"single_shop_mode": false}, "failure_modes": ["comparison_single_shop"]}
{"case_id": "D34-1", "intent": "clarification", "description": "澄清-缺少位置", "turns": [{"user": "附近有什么好吃的火锅"}], "expected_route": "clarification_node", "expected_entity": null, "expected_tool": null, "expected_output_contains": ["位置", "城市"], "forbidden_output": ["直接推荐"], "expected_metrics": {"clarification_needed": true}, "failure_modes": ["missing_clarification"]}
{"case_id": "D34-2", "intent": "clarification", "description": "澄清-代词消解失败", "turns": [{"user": "海底捞怎么样"}, {"user": "它有券吗"}], "expected_route": "resolve_target_shop", "expected_entity": "海底捞", "expected_tool": "get_coupon_list", "expected_output_contains": ["券", "优惠"], "forbidden_output": ["哪家店"], "expected_metrics": {"single_shop_mode": true}, "failure_modes": ["reference_resolution_failed"]}
{"case_id": "D35-1", "intent": "out_of_scope", "description": "非本地生活-天气", "turns": [{"user": "明天天气怎么样"}], "expected_route": "out_of_scope", "expected_entity": null, "expected_tool": null, "expected_output_contains": ["本地生活", "商家"], "forbidden_output": ["天气"], "expected_metrics": {}, "failure_modes": ["wrong_route"]}
{"case_id": "D35-2", "intent": "out_of_scope", "description": "非本地生活-电影", "turns": [{"user": "最近有什么好看的电影"}], "expected_route": "out_of_scope", "expected_entity": null, "expected_tool": null, "expected_output_contains": ["本地生活", "商家"], "forbidden_output": ["电影"], "expected_metrics": {}, "failure_modes": ["wrong_route"]}
{"case_id": "D36-1", "intent": "multi_turn", "description": "多轮-上下文继承", "turns": [{"user": "海底捞怎么样"}, {"user": "有券吗"}], "expected_route": "resolve_target_shop", "expected_entity": "海底捞", "expected_tool": "get_coupon_list", "expected_output_contains": ["券", "优惠"], "forbidden_output": ["哪家店"], "expected_metrics": {"single_shop_mode": true}, "failure_modes": ["context_inherit_wrong"]}
{"case_id": "D36-2", "intent": "multi_turn", "description": "多轮-场景切换", "turns": [{"user": "海底捞怎么样"}, {"user": "附近还有什么推荐"}], "expected_route": "resolve_target_shop", "expected_entity": null, "expected_tool": null, "expected_output_contains": ["推荐"], "forbidden_output": ["海底捞详情"], "expected_metrics": {"single_shop_mode": false}, "failure_modes": ["wrong_route"]}
{"case_id": "D37-1", "intent": "merchant_detail", "description": "商家详情-服务评价", "turns": [{"user": "海底捞的服务怎么样"}], "expected_route": "resolve_target_shop", "expected_entity": "海底捞(水晶城购物中心店)", "expected_tool": null, "expected_output_contains": ["海底捞", "服务"], "forbidden_output": ["推荐其他店"], "expected_metrics": {"single_shop_mode": true}, "failure_modes": ["cross_shop"]}
{"case_id": "D37-2", "intent": "merchant_detail", "description": "商家详情-口味评价", "turns": [{"user": "呷哺呷哺的口味如何"}], "expected_route": "resolve_target_shop", "expected_entity": "呷哺呷哺(万达广场店)", "expected_tool": null, "expected_output_contains": ["呷哺", "口味"], "forbidden_output": ["推荐其他店"], "expected_metrics": {"single_shop_mode": true}, "failure_modes": ["cross_shop"]}
{"case_id": "D38-1", "intent": "recommendation", "description": "推荐-场景推荐", "turns": [{"user": "适合约会的餐厅推荐"}], "expected_route": "resolve_target_shop", "expected_entity": null, "expected_tool": null, "expected_output_contains": ["约会", "推荐"], "forbidden_output": ["吵闹"], "expected_metrics": {"single_shop_mode": false}, "failure_modes": ["scene_violation"]}
{"case_id": "D38-2", "intent": "recommendation", "description": "推荐-家庭聚餐", "turns": [{"user": "适合带小孩的餐厅"}], "expected_route": "resolve_target_shop", "expected_entity": null, "expected_tool": null, "expected_output_contains": ["小孩", "推荐"], "forbidden_output": ["不适合小孩"], "expected_metrics": {"single_shop_mode": false}, "failure_modes": ["scene_violation"]}
{"case_id": "D39-1", "intent": "coupon_query", "description": "优惠券-团购查询", "turns": [{"user": "海底捞有团购吗"}], "expected_route": "resolve_target_shop", "expected_entity": "海底捞(水晶城购物中心店)", "expected_tool": "get_coupon_list", "expected_output_contains": ["团购", "优惠"], "forbidden_output": ["环境", "口味"], "expected_metrics": {"single_shop_mode": true}, "failure_modes": ["forbidden_facet_leak"]}
{"case_id": "D39-2", "intent": "coupon_query", "description": "优惠券-代金券查询", "turns": [{"user": "呷哺呷哺有什么优惠"}], "expected_route": "resolve_target_shop", "expected_entity": "呷哺呷哺(万达广场店)", "expected_tool": "get_coupon_list", "expected_output_contains": ["优惠", "券"], "forbidden_output": ["环境", "口味"], "expected_metrics": {"single_shop_mode": true}, "failure_modes": ["forbidden_facet_leak"]}
{"case_id": "D40-1", "intent": "edge_case", "description": "边界-空输入", "turns": [{"user": ""}], "expected_route": "clarification_node", "expected_entity": null, "expected_tool": null, "expected_output_contains": ["信息", "补充"], "forbidden_output": ["推荐"], "expected_metrics": {"clarification_needed": true}, "failure_modes": ["missing_clarification"]}
{"case_id": "D40-2", "intent": "edge_case", "description": "边界-纯标点", "turns": [{"user": "？？？"}], "expected_route": "clarification_node", "expected_entity": null, "expected_tool": null, "expected_output_contains": ["信息", "补充"], "forbidden_output": ["推荐"], "expected_metrics": {"clarification_needed": true}, "failure_modes": ["missing_clarification"]}
```

- [ ] **Step 2: Verify golden cases count**

Run: `wc -l learning-agent-service/eval/local_life/golden_cases.jsonl`
Expected: 80+ lines

- [ ] **Step 3: Run evaluation to verify new cases work**

Run: `cd learning-agent-service && python -m learning_agent_service.local_life.eval.run_golden_cases`
Expected: New cases are evaluated

- [ ] **Step 4: Commit**

```bash
git add learning-agent-service/eval/local_life/golden_cases.jsonl
git commit -m "test: expand golden cases to 80+ examples with missing intents"
```

---

### Task 8: Enhance Business Metrics Collection

**Files:**
- Modify: `learning-agent-service/src/learning_agent_service/local_life/business_metrics.py`

- [ ] **Step 1: Add new metrics fields**

Add to QueryMetrics:
```python
    # 新增字段
    retry_count: int = 0
    retry_improved: bool | None = None
    freshness_status: str | None = None
    staleness_detected: bool = False
    scene_violation: bool = False
    dialog_state: str | None = None
```

Add to MetricsSummary:
```python
    # 新增统计
    retry_count: int = 0
    retry_improved_count: int = 0
    retry_degraded_count: int = 0
    
    staleness_count: int = 0
    scene_violation_count: int = 0
    
    dialog_state_counts: Counter = field(default_factory=Counter)
    
    # 按 freshness 分类
    freshness_counts: Counter = field(default_factory=Counter)
```

- [ ] **Step 2: Update record_query method**

Add to record_query:
```python
        # 重试统计
        if metrics.retry_count > 0:
            self._summary.retry_count += metrics.retry_count
            if metrics.retry_improved is True:
                self._summary.retry_improved_count += 1
            elif metrics.retry_improved is False:
                self._summary.retry_degraded_count += 1
        
        # 新鲜度统计
        if metrics.freshness_status:
            self._summary.freshness_counts[metrics.freshness_status] += 1
        
        # 过时检测统计
        if metrics.staleness_detected:
            self._summary.staleness_count += 1
        
        # 场景违禁词统计
        if metrics.scene_violation:
            self._summary.scene_violation_count += 1
        
        # 对话状态统计
        if metrics.dialog_state:
            self._summary.dialog_state_counts[metrics.dialog_state] += 1
```

- [ ] **Step 3: Update to_dict method**

Add to to_dict:
```python
            "retry_rate": self.retry_count / max(1, self.total_queries),
            "retry_improvement_rate": self.retry_improved_count / max(1, self.retry_count),
            "staleness_rate": self.staleness_count / max(1, self.total_queries),
            "scene_violation_rate": self.scene_violation_count / max(1, self.total_queries),
            "dialog_state_distribution": dict(self.dialog_state_counts),
            "freshness_distribution": dict(self.freshness_counts),
```

- [ ] **Step 4: Add tests for new metrics**

```python
def test_retry_metrics():
    collector = BusinessMetricsCollector()
    
    metrics = QueryMetrics(
        query="test",
        intent="test",
        route="test",
        answer_style="test",
        retry_count=2,
        retry_improved=True,
    )
    collector.record_query(metrics)
    
    summary = collector.get_summary()
    assert summary.retry_count == 2
    assert summary.retry_improved_count == 1


def test_staleness_metrics():
    collector = BusinessMetricsCollector()
    
    metrics = QueryMetrics(
        query="test",
        intent="test",
        route="test",
        answer_style="test",
        staleness_detected=True,
        freshness_status="historical",
    )
    collector.record_query(metrics)
    
    summary = collector.get_summary()
    assert summary.staleness_count == 1
    assert summary.freshness_counts["historical"] == 1
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest learning-agent-service/tests/local_life/test_business_metrics.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add learning-agent-service/src/learning_agent_service/local_life/business_metrics.py
git commit -m "feat: enhance business metrics with retry, staleness, and scene tracking"
```

---

### Task 9: Enhance Comparison Template Dimensions

**Files:**
- Modify: `learning-agent-service/src/learning_agent_service/local_life/answer_structure_composer.py`

- [ ] **Step 1: Add more comparison dimensions**

Update `_compose_comparison` function to include more dimensions:

```python
def _compose_comparison(topic_name: str, ranked_candidates: list[dict[str, Any]], grouped_claims: dict[int | None, list[str]], requirements: dict[str, Any]) -> str:
    """结构化对比答案模板"""
    if len(ranked_candidates) < 2:
        if ranked_candidates:
            return _compose_single_shop_review(topic_name, ranked_candidates[0], grouped_claims, requirements)
        return f"{topic_name or '对比结果'}：当前证据不足，无法进行有效对比。"

    shop_a = ranked_candidates[0]
    shop_b = ranked_candidates[1]
    name_a = _clean_text(shop_a.get("name") or shop_a.get("shop_name") or "店铺A")
    name_b = _clean_text(shop_b.get("name") or shop_b.get("shop_name") or "店铺B")

    structured_a = shop_a.get("structured_features") or {}
    structured_b = shop_b.get("structured_features") or {}

    claims_a = _unique_text(grouped_claims.get(shop_a.get("shop_id"), []))
    claims_b = _unique_text(grouped_claims.get(shop_b.get("shop_id"), []))

    dimensions: list[tuple[str, str, str]] = []

    # 1. 综合评分
    if structured_a.get("score") not in (None, "") or structured_b.get("score") not in (None, ""):
        score_a = str(structured_a.get("score") or "暂无")
        score_b = str(structured_b.get("score") or "暂无")
        dimensions.append(("综合评分", f"{name_a}约{score_a}", f"{name_b}约{score_b}"))

    # 2. 人均消费
    if structured_a.get("avg_price") not in (None, "") or structured_b.get("avg_price") not in (None, ""):
        price_a = str(structured_a.get("avg_price") or "暂无")
        price_b = str(structured_b.get("avg_price") or "暂无")
        dimensions.append(("人均消费", f"{name_a}约{price_a}元", f"{name_b}约{price_b}元"))

    # 3. 距离
    if structured_a.get("distance_km") not in (None, "") or structured_b.get("distance_km") not in (None, ""):
        dist_a = str(structured_a.get("distance_km") or "暂无")
        dist_b = str(structured_b.get("distance_km") or "暂无")
        dimensions.append(("距离", f"{name_a}约{dist_a}公里", f"{name_b}约{dist_b}公里"))

    # 4. 环境评价
    env_claims_a = [c for c in claims_a if any(kw in c for kw in ["环境", "装修", "氛围", "安静", "吵闹"])]
    env_claims_b = [c for c in claims_b if any(kw in c for kw in ["环境", "装修", "氛围", "安静", "吵闹"])]
    if env_claims_a or env_claims_b:
        env_a = env_claims_a[0] if env_claims_a else "暂无明确评价"
        env_b = env_claims_b[0] if env_claims_b else "暂无明确评价"
        dimensions.append(("环境氛围", f"{name_a}：{env_a}", f"{name_b}：{env_b}"))

    # 5. 口味评价
    taste_claims_a = [c for c in claims_a if any(kw in c for kw in ["口味", "好吃", "味道", "口感"])]
    taste_claims_b = [c for c in claims_b if any(kw in c for kw in ["口味", "好吃", "味道", "口感"])]
    if taste_claims_a or taste_claims_b:
        taste_a = taste_claims_a[0] if taste_claims_a else "暂无明确评价"
        taste_b = taste_claims_b[0] if taste_claims_b else "暂无明确评价"
        dimensions.append(("口味口感", f"{name_a}：{taste_a}", f"{name_b}：{taste_b}"))

    # 6. 服务评价
    service_claims_a = [c for c in claims_a if any(kw in c for kw in ["服务", "态度", "热情", "周到"])]
    service_claims_b = [c for c in claims_b if any(kw in c for kw in ["服务", "态度", "热情", "周到"])]
    if service_claims_a or service_claims_b:
        service_a = service_claims_a[0] if service_claims_a else "暂无明确评价"
        service_b = service_claims_b[0] if service_claims_b else "暂无明确评价"
        dimensions.append(("服务态度", f"{name_a}：{service_a}", f"{name_b}：{service_b}"))

    # 7. 用户评价（通用）
    if not any(d[0] in ["环境氛围", "口味口感", "服务态度"] for d in dimensions):
        if claims_a or claims_b:
            claim_a = claims_a[0] if claims_a else "暂无明确评价"
            claim_b = claims_b[0] if claims_b else "暂无明确评价"
            dimensions.append(("用户评价", f"{name_a}：{claim_a}", f"{name_b}：{claim_b}"))

    if not dimensions:
        dimensions.append(("综合对比", f"{name_a}和{name_b}各有特点", "建议结合距离、预算和场景综合考虑"))

    # 生成答案
    lines = [f"{topic_name or '对比结果'}：我从几个维度帮你对比一下这两家店。"]

    lines.append("\n对比维度")
    for dim_name, val_a, val_b in dimensions:
        lines.append(f"- {dim_name}：")
        lines.append(f"  - {val_a}")
        lines.append(f"  - {val_b}")

    # 综合建议
    lines.append("\n综合建议")
    
    score_a_val = None
    score_b_val = None
    
    if structured_a.get("score") not in (None, ""):
        try:
            score_a_val = float(structured_a["score"])
        except (ValueError, TypeError):
            pass
    
    if structured_b.get("score") not in (None, ""):
        try:
            score_b_val = float(structured_b["score"])
        except (ValueError, TypeError):
            pass
    
    if score_a_val is not None and score_b_val is not None:
        if score_a_val > score_b_val:
            lines.append(f"- 综合评分来看，{name_a}略胜一筹。")
        elif score_b_val > score_a_val:
            lines.append(f"- 综合评分来看，{name_b}略胜一筹。")
        else:
            lines.append("- 两家评分相近，建议结合距离和预算选择。")
    else:
        lines.append("- 两家各有优势，建议结合距离、预算和场景选择。")

    return "\n".join(lines)
```

- [ ] **Step 2: Add tests for enhanced comparison**

```python
def test_comparison_with_environment():
    ranked_candidates = [
        {"shop_id": 1, "name": "海底捞", "structured_features": {"score": "4.5", "avg_price": "100"}},
        {"shop_id": 2, "name": "呷哺呷哺", "structured_features": {"score": "4.2", "avg_price": "60"}},
    ]
    grouped_claims = {
        1: ["环境优雅，装修现代", "服务热情周到"],
        2: ["环境一般，比较吵闹", "口味不错"],
    }
    
    result = _compose_comparison("餐厅对比", ranked_candidates, grouped_claims, {})
    
    assert "海底捞" in result
    assert "呷哺" in result
    assert "环境" in result
    assert "口味" in result
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `pytest learning-agent-service/tests/local_life/test_answer_structure_composer.py -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add learning-agent-service/src/learning_agent_service/local_life/answer_structure_composer.py
git commit -m "feat: enhance comparison template with environment, taste, and service dimensions"
```

---

### Task 10: Enhance Clarification Strategy Rules

**Files:**
- Modify: `learning-agent-service/src/learning_agent_service/local_life/clarification_strategy.py`

- [ ] **Step 1: Add more clarification rules**

```python
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class ClarificationStrategy:
    """
    Unified manager for clarification decisions to avoid redundant questions
    and centralize logic from phase3_review, target_shop_policy, top_level_intent_router.
    """

    # 已追问过的slot记录
    _asked_slots_key = "asked_clarification_slots"

    @staticmethod
    def should_clarify_target_shop(
        raw_query: str,
        is_low_info: bool,
        has_explicit_shop_hint: bool,
        has_pronoun: bool,
        has_resolved_ref: bool,
    ) -> tuple[bool, str | None, str | None]:
        """
        Decides if we need to clarify which shop the user is referring to.
        Returns (should_clarify, missing_slot, reason)
        """
        # Rule 1: Pronoun but no reference resolved -> clarify
        if has_pronoun and not has_resolved_ref:
            return True, "shop_name", "reference_resolution_failed"
        
        # Rule 2: Low info query (like "1", "...") and no explicit hint and no resolved ref -> clarify
        if is_low_info and not has_explicit_shop_hint and not has_resolved_ref:
            return True, "shop_name", "low_information_query"
            
        return False, None, None

    @staticmethod
    def requires_current_shop_for_ref(normalized_query: str, has_context_shop: bool) -> bool:
        """
        Checks if the query is a bare follow-up that requires a current shop to be present.
        If it requires one but we don't have it, we should clarify.
        """
        ref_tokens = ("这家", "它", "那个", "这个", "那家")
        bare_followup = ("地址在哪", "在哪", "有券吗", "有券", "几点开门", "几点关门", "营业时间", "营业时间是什么")
        
        has_ref_token = any(token in normalized_query for token in ref_tokens)
        stripped = normalized_query.rstrip("？?。. ")
        is_bare = stripped in bare_followup or normalized_query in bare_followup
        
        if (has_ref_token or is_bare) and not has_context_shop:
            return True
            
        return False

    @staticmethod
    def should_clarify_location(
        is_recommendation: bool,
        has_location_slot: bool,
        has_explicit_shop: bool,
    ) -> bool:
        """
        Decides if we need to clarify location.
        """
        # If it's a recommendation and no location is provided, and we didn't specify a shop
        if is_recommendation and not has_location_slot and not has_explicit_shop:
            return True
        return False

    @staticmethod
    def should_avoid_repeat_clarification(
        current_slot: str,
        asked_slots: list[str],
        context_shop: str | None = None,
        last_clarification_turn: int | None = None,
        current_turn: int | None = None,
    ) -> bool:
        """
        判断是否应该避免重复追问
        
        Args:
            current_slot: 当前要追问的slot
            asked_slots: 已经追问过的slot列表
            context_shop: 上下文中的店铺
            last_clarification_turn: 上次追问的轮次
            current_turn: 当前轮次
            
        Returns:
            True if should avoid asking again
        """
        # Rule 1: 已经追问过相同slot
        if current_slot in asked_slots:
            return True
        
        # Rule 2: 有上下文店铺时，不需要再追问店名
        if current_slot == "shop_name" and context_shop:
            return True
        
        # Rule 3: 连续轮次追问（避免连续追问）
        if last_clarification_turn is not None and current_turn is not None:
            if current_turn - last_clarification_turn < 2:
                return True
        
        return False

    @staticmethod
    def get_clarification_priority(
        missing_slots: list[str],
        intent: str,
        has_context_shop: bool,
    ) -> str | None:
        """
        确定追问优先级，返回应该追问的slot
        
        Args:
            missing_slots: 缺失的slot列表
            intent: 当前意图
            has_context_shop: 是否有上下文店铺
            
        Returns:
            应该追问的slot名称，或None
        """
        # 优先级规则
        priority_rules = {
            "recommendation": ["location", "category", "shop_name"],
            "comparison": ["shop_name", "location"],
            "merchant_detail": ["shop_name"],
            "coupon_query": ["shop_name"],
            "open_status": ["shop_name"],
            "distance": ["shop_name"],
        }
        
        priority_list = priority_rules.get(intent, ["shop_name", "location", "category"])
        
        for slot in priority_list:
            if slot in missing_slots:
                # 如果有上下文店铺，跳过shop_name追问
                if slot == "shop_name" and has_context_shop:
                    continue
                return slot
        
        return None
```

- [ ] **Step 2: Add tests for new clarification rules**

```python
def test_should_avoid_repeat_clarification():
    # 已追问过shop_name
    assert ClarificationStrategy.should_avoid_repeat_clarification(
        current_slot="shop_name",
        asked_slots=["shop_name"],
    )
    
    # 未追问过
    assert not ClarificationStrategy.should_avoid_repeat_clarification(
        current_slot="shop_name",
        asked_slots=[],
    )
    
    # 有上下文店铺时不需要追问店名
    assert ClarificationStrategy.should_avoid_repeat_clarification(
        current_slot="shop_name",
        asked_slots=[],
        context_shop="海底捞",
    )


def test_get_clarification_priority():
    # 推荐意图优先追问位置
    priority = ClarificationStrategy.get_clarification_priority(
        missing_slots=["shop_name", "location"],
        intent="recommendation",
        has_context_shop=False,
    )
    assert priority == "location"
    
    # 有上下文店铺时跳过shop_name
    priority = ClarificationStrategy.get_clarification_priority(
        missing_slots=["shop_name", "location"],
        intent="recommendation",
        has_context_shop=True,
    )
    assert priority == "location"
    
    # 商家详情意图追问店名
    priority = ClarificationStrategy.get_clarification_priority(
        missing_slots=["shop_name", "location"],
        intent="merchant_detail",
        has_context_shop=False,
    )
    assert priority == "shop_name"
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `pytest learning-agent-service/tests/local_life/test_clarification_strategy.py -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add learning-agent-service/src/learning_agent_service/local_life/clarification_strategy.py
git commit -m "feat: enhance clarification strategy with repeat avoidance and priority rules"
```

---

### Task 11: Enhance Scene Policy with More Scenarios

**Files:**
- Modify: `learning-agent-service/src/learning_agent_service/local_life/scene_policy.py`

- [ ] **Step 1: Add more scene rules**

```python
from __future__ import annotations

from collections.abc import Sequence


class ScenePolicy:
    """规则引擎场景策略，识别高频场景并接入硬规则过滤校验。"""
    
    SCENE_RULES = {
        "约会": {
            "forbidden_keywords": ["吵闹", "太吵", "环境差", "脏乱", "拥挤", "服务差", "灯光暗", "位置偏僻"],
            "required_keywords": ["环境", "氛围", "安静"],
            "preferred_facets": ["environment", "atmosphere"],
        },
        "家庭聚餐": {
            "forbidden_keywords": ["不适合老人", "不适合小孩", "太辣", "没宝宝椅", "位置偏僻", "停车不便"],
            "required_keywords": ["适合家庭", "包间"],
            "preferred_facets": ["family_friendly", "parking"],
        },
        "带父母": {
            "forbidden_keywords": ["不适合老人", "太吵", "太辣", "环境差", "只能站着", "排队久"],
            "required_keywords": ["适合老人", "座位舒适"],
            "preferred_facets": ["elderly_friendly", "comfortable"],
        },
        "带小孩": {
            "forbidden_keywords": ["不适合小孩", "没宝宝椅", "太辣", "环境嘈杂", "危险"],
            "required_keywords": ["宝宝椅", "儿童餐"],
            "preferred_facets": ["child_friendly", "safety"],
        },
        "商务宴请": {
            "forbidden_keywords": ["环境差", "服务差", "太吵", "位置偏僻", "档次低"],
            "required_keywords": ["包间", "服务好", "环境好"],
            "preferred_facets": ["private_room", "service", "environment"],
        },
        "朋友聚餐": {
            "forbidden_keywords": ["太安静", "不适合多人", "位置偏僻"],
            "required_keywords": ["适合多人", "氛围好"],
            "preferred_facets": ["group_friendly", "atmosphere"],
        },
        "一个人": {
            "forbidden_keywords": ["不适合一人食", "必须多人", "最低消费"],
            "required_keywords": ["一人食", "小份"],
            "preferred_facets": ["solo_friendly", "portion_size"],
        },
        "深夜": {
            "forbidden_keywords": ["打烊早", "晚上不开", "10点关门"],
            "required_keywords": ["营业到很晚", "夜宵"],
            "preferred_facets": ["late_night", "hours"],
        },
    }

    @classmethod
    def apply(cls, query: str, claim_text: str) -> tuple[bool, str]:
        """
        检查查询中是否包含特定场景，并校验证据（或评论）是否符合硬规则。
        返回: (是否通过校验, 拒绝理由)
        """
        if not claim_text:
            return True, ""
            
        detected_scenes = []
        for scene in cls.SCENE_RULES:
            if scene in query:
                detected_scenes.append(scene)
                
        if not detected_scenes:
            return True, ""
            
        for scene in detected_scenes:
            rules = cls.SCENE_RULES[scene]
            for forbidden in rules["forbidden_keywords"]:
                if forbidden in claim_text:
                    return False, f"场景[{scene}]违禁词[{forbidden}]"
                    
        return True, ""

    @classmethod
    def get_preferred_facets(cls, query: str) -> list[str]:
        """获取查询场景偏好的facets"""
        preferred = []
        for scene, rules in cls.SCENE_RULES.items():
            if scene in query:
                preferred.extend(rules.get("required_keywords", []))
        return list(set(preferred))

    @classmethod
    def detect_scene(cls, query: str) -> str | None:
        """检测查询中的场景"""
        for scene in cls.SCENE_RULES:
            if scene in query:
                return scene
        return None
```

- [ ] **Step 2: Add tests for enhanced scene policy**

```python
def test_scene_business():
    query = "适合商务宴请的餐厅"
    claim_text = "环境一般，服务差"
    
    passed, reason = ScenePolicy.apply(query, claim_text)
    assert not passed
    assert "商务宴请" in reason
    assert "服务差" in reason


def test_scene_solo():
    query = "一个人吃饭推荐"
    claim_text = "必须多人，最低消费100"
    
    passed, reason = ScenePolicy.apply(query, claim_text)
    assert not passed
    assert "一个人" in reason


def test_scene_late_night():
    query = "深夜有什么好吃的"
    claim_text = "晚上10点就关门了"
    
    passed, reason = ScenePolicy.apply(query, claim_text)
    assert not passed
    assert "深夜" in reason


def test_get_preferred_facets():
    facets = ScenePolicy.get_preferred_facets("适合约会的餐厅")
    assert "环境" in facets or "氛围" in facets


def test_detect_scene():
    assert ScenePolicy.detect_scene("适合约会的餐厅") == "约会"
    assert ScenePolicy.detect_scene("适合带小孩的餐厅") == "带小孩"
    assert ScenePolicy.detect_scene("今天天气怎么样") is None
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `pytest learning-agent-service/tests/local_life/test_scene_policy.py -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add learning-agent-service/src/learning_agent_service/local_life/scene_policy.py
git commit -m "feat: enhance scene policy with more scenarios and preferred facets"
```

---

## Summary

### P2 Tasks Completed:
1. ✅ **Dialog State Machine** - Explicit state management for multi-turn conversations
2. ✅ **CI Evaluation Integration** - Automated golden case evaluation in CI pipeline
3. ✅ **Unified Degraded Messages** - User-friendly boundary prompts replacing technical errors
4. ✅ **Staleness Detection** - Detection and user notification for outdated information
5. ✅ **Retry Quality Evaluation** - Prevent quality degradation during retries

### P0/P1 Deepening:
6. ✅ **Enhanced Failure Mode Mapping** - More detection rules for realtime facets, comparisons, staleness
7. ✅ **Expanded Golden Cases** - 80+ examples covering all intents and edge cases
8. ✅ **Enhanced Business Metrics** - Retry, staleness, and scene violation tracking
9. ✅ **Enhanced Comparison Template** - Environment, taste, and service dimensions
10. ✅ **Enhanced Clarification Strategy** - Repeat avoidance and priority rules
11. ✅ **Enhanced Scene Policy** - More scenarios (business, solo, late night) and preferred facets

### Next Steps:
- Run all tests to verify no regressions
- Run evaluation to verify golden cases pass
- Monitor metrics in production to validate improvements
