# Stage 8 Trace Eval Replay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐本地生活意图路由的 Stage 8 统一 trace 产物，让 trace、golden eval 和 replay 共用同一份结构化数据，不改变既有路由行为。

**Architecture:** 只新增一个轻量的 `trace.py` 统一承载 `RoutingTrace` / `StageTrace` / 构造器，并让现有 `testing/harness.py` 与 `local_life/eval/run_golden_cases.py` 复用这份结构。实现只做数据结构和采集 glue，不改 Stage 1-7 的路由决策与分支行为。

**Tech Stack:** Python 3.11, dataclasses, existing `GraphState`, existing router traces, pytest / unittest.

---

### Task 1: Add unified routing trace types

**Files:**
- Create: `learning-agent-service/src/learning_agent_service/application/router/trace.py`
- Modify: `learning-agent-service/src/learning_agent_service/application/router/__init__.py`
- Test: `learning-agent-service/tests/test_routing_trace_contract.py`

- [ ] **Step 1: Write the failing test**

```python
from learning_agent_service.application.router.trace import StageTrace, RoutingTrace, build_routing_trace

def test_build_routing_trace_collects_stage_snapshots():
    trace = build_routing_trace(
        query="附近有什么推荐",
        session_id="session-1",
        turn_id="turn-1",
        stages={"phase0_trace": {"harness_mode": "off"}},
        final_decision={"required_action": "clarify"},
    )
    assert trace.query == "附近有什么推荐"
    assert trace.session_id == "session-1"
    assert trace.stages["phase0_trace"].output == {"harness_mode": "off"}
    assert trace.final_decision["required_action"] == "clarify"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest -q learning-agent-service/tests/test_routing_trace_contract.py`
Expected: fail because `trace.py` and the dataclasses do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, UTC
from collections.abc import Mapping
from typing import Any


@dataclass(slots=True)
class StageTrace:
    input: Any = None
    output: Any = None
    duration_ms: float = 0.0
    error: str | None = None


@dataclass(slots=True)
class RoutingTrace:
    query: str
    session_id: str
    turn_id: str
    timestamp: str
    stages: dict[str, StageTrace] = field(default_factory=dict)
    final_decision: dict[str, Any] = field(default_factory=dict)
    ground_truth: dict[str, Any] | None = None
    is_correct: bool | None = None


def _as_stage_trace(value: Any) -> StageTrace:
    if isinstance(value, StageTrace):
        return value
    if isinstance(value, Mapping):
        return StageTrace(
            input=value.get("input"),
            output=value.get("output"),
            duration_ms=float(value.get("duration_ms") or 0.0),
            error=value.get("error"),
        )
    return StageTrace(output=value)


def build_routing_trace(
    *,
    query: str,
    session_id: str,
    turn_id: str,
    stages: Mapping[str, Any] | None = None,
    final_decision: Mapping[str, Any] | None = None,
    ground_truth: Mapping[str, Any] | None = None,
    is_correct: bool | None = None,
) -> RoutingTrace:
    return RoutingTrace(
        query=query,
        session_id=session_id,
        turn_id=turn_id,
        timestamp=datetime.now(UTC).isoformat(),
        stages={str(key): _as_stage_trace(value) for key, value in dict(stages or {}).items()},
        final_decision=dict(final_decision or {}),
        ground_truth=dict(ground_truth or {}) if ground_truth is not None else None,
        is_correct=is_correct,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest -q learning-agent-service/tests/test_routing_trace_contract.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add learning-agent-service/src/learning_agent_service/application/router/trace.py learning-agent-service/src/learning_agent_service/application/router/__init__.py learning-agent-service/tests/test_routing_trace_contract.py
git commit -m "feat: add unified routing trace contract"
```

### Task 2: Reuse unified trace in harness and golden eval

**Files:**
- Modify: `learning-agent-service/src/learning_agent_service/testing/harness.py`
- Modify: `learning-agent-service/src/learning_agent_service/local_life/eval/run_golden_cases.py`
- Test: `learning-agent-service/tests/test_phase0_harness.py`
- Test: `learning-agent-service/tests/local_life/test_day7_golden_cases_chat.py`

- [ ] **Step 1: Write the failing test**

```python
from learning_agent_service.application.router.trace import build_routing_trace
from learning_agent_service.testing.harness import TraceHarnessRecorder

def test_trace_harness_recorder_returns_routing_trace_shape():
    recorder = TraceHarnessRecorder()
    snapshot = recorder.record(state, case_id="case-1")
    assert "timestamp" in snapshot
    assert "stages" in snapshot or "phase0_trace" in snapshot
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest -q learning-agent-service/tests/test_phase0_harness.py -k trace`
Expected: fail until recorder emits the unified trace shape.

- [ ] **Step 3: Write minimal implementation**

```python
from dataclasses import asdict

from learning_agent_service.application.router import (
    routing_trace_payload,
)
from learning_agent_service.testing.harness import (
    extract_phase0_trace,
    extract_phase3_trace,
    extract_phase4_trace,
    extract_phase5_trace,
)
from learning_agent_service.application.router.trace import build_routing_trace

def _trace_from_state(state, *, case_id: str | None = None) -> dict[str, object]:
    turn = state["turn"]
    runtime = state["runtime"]
    trace = build_routing_trace(
        query=str(getattr(turn, "raw_query", "") or ""),
        session_id=str(getattr(runtime, "session_id", "") or ""),
        turn_id=str(getattr(runtime, "turn_id", "") or ""),
        stages={
            "phase0_trace": extract_phase0_trace(state),
            "phase3_trace": extract_phase3_trace(state),
            "phase4_trace": extract_phase4_trace(state),
            "phase5_trace": extract_phase5_trace(state),
        },
        final_decision=routing_trace_payload(getattr(turn, "routing_decision", None)),
    )
    snapshot = asdict(trace)
    snapshot["case_id"] = case_id
    return snapshot
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
- `pytest -q learning-agent-service/tests/test_phase0_harness.py`
- `pytest -q learning-agent-service/tests/local_life/test_day7_golden_cases_chat.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add learning-agent-service/src/learning_agent_service/testing/harness.py learning-agent-service/src/learning_agent_service/local_life/eval/run_golden_cases.py learning-agent-service/tests/test_phase0_harness.py learning-agent-service/tests/local_life/test_day7_golden_cases_chat.py
git commit -m "feat: reuse unified routing trace in eval harness"
```

### Task 3: Verify Stage 8 does not change routing behavior

**Files:**
- Test: `learning-agent-service/tests/test_phase3_replay_compare.py`
- Test: `learning-agent-service/tests/test_phase5_runner_compare.py`
- Test: `learning-agent-service/tests/test_phase0_core_replay.py`

- [ ] **Step 1: Run the relevant regression tests**

Run:
- `pytest -q learning-agent-service/tests/test_phase0_core_replay.py`
- `pytest -q learning-agent-service/tests/test_phase3_replay_compare.py`
- `pytest -q learning-agent-service/tests/test_phase5_runner_compare.py`

Expected: PASS with the same routing outcomes as before.

- [ ] **Step 2: Confirm no fallback behavior changed**

Check that the existing trace extraction keys still populate `phase0_trace`, `phase3_trace`, `phase4_trace`, and `phase5_trace` for the old tests.

- [ ] **Step 3: Commit**

```bash
git add learning-agent-service/tests/test_phase0_core_replay.py learning-agent-service/tests/test_phase3_replay_compare.py learning-agent-service/tests/test_phase5_runner_compare.py
git commit -m "test: cover unified trace replay regression"
```
