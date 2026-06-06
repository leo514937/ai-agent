# Routing Package Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `learning_agent_service/application/routing.py` 拆成 `application/router/` 包，并把 `workflow`/`tools` 的路由相关调用一次性迁到新模块，同时保留旧入口兼容，保证 chat 接口验收全绿、没有飘红。

**Architecture:** 新的 `application/router/` 包承载所有路由决策、review、trace、task/plan 逻辑，`application/routing.py` 退化为纯兼容外壳，只负责 re-export。`application/workflow/*` 与 `tools/service.py` 只从 `application.router` 取符号，不再直接依赖旧大文件，这样可以先完成结构分层，再用现有 chat 测试验证行为没有回归。

**Tech Stack:** Python 3.11, pytest, existing FastAPI / workflow runtime, dataclasses, Pydantic models already in the repo.

---

### Task 1: Create the new `application/router/` package and move routing logic behind a compatibility facade

**Files:**
- Create: `learning-agent-service/src/learning_agent_service/application/router/__init__.py`
- Create: `learning-agent-service/src/learning_agent_service/application/router/base.py`
- Create: `learning-agent-service/src/learning_agent_service/application/router/decision.py`
- Create: `learning-agent-service/src/learning_agent_service/application/router/review.py`
- Create: `learning-agent-service/src/learning_agent_service/application/router/trace.py`
- Modify: `learning-agent-service/src/learning_agent_service/application/routing.py`
- Test: `learning-agent-service/tests/test_router_package_exports.py`

- [ ] **Step 1: Write the failing test**

```python
from learning_agent_service.application import routing as legacy_routing
from learning_agent_service.application.router import build_initial_routing_decision, routing_trace_payload
from learning_agent_service.domain.contracts import PersistentSessionContext


def test_router_package_exports_match_legacy_module() -> None:
    assert build_initial_routing_decision is legacy_routing.build_initial_routing_decision
    assert routing_trace_payload is legacy_routing.routing_trace_payload


def test_router_package_can_build_basic_decision() -> None:
    routing = build_initial_routing_decision("你好", PersistentSessionContext())
    assert routing.required_action == "direct_answer"
    assert routing.route_candidate == "greeting"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest learning-agent-service/tests/test_router_package_exports.py -q`
Expected: FAIL with `ModuleNotFoundError` or import attribute errors because `application/router/` does not exist yet.

- [ ] **Step 3: Write the minimal implementation**

```python
# learning_agent_service/application/router/__init__.py
from .base import RoutingBuildContext, normalize_query
from .decision import (
    apply_fast_decision_to_routing,
    build_evidence_quality,
    build_initial_routing_decision,
    build_rewrite_decision,
)
from .review import (
    build_clarification_question,
    can_enter_retrieval,
    can_enter_tool,
    ensure_retrieval_plan,
    ensure_task_plan,
    ensure_tool_plan,
    should_persist_memory,
    should_run_tool,
)
from .trace import (
    _update_phase0_trace,
    _update_phase1_trace,
    _update_phase2_trace,
    _update_phase3_trace,
    _update_phase4_trace,
    routing_trace_payload,
)

# learning_agent_service/application/routing.py
from .router import *  # noqa: F401,F403
```

The implementation should keep the real code in the new package modules and turn `routing.py` into a thin compatibility wrapper. Any private helpers that `workflow/*` still imports must also be re-exported from `application.router` so the call-site migration can be completed in the next task without breaking runtime imports.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest learning-agent-service/tests/test_router_package_exports.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add learning-agent-service/src/learning_agent_service/application/router learning-agent-service/src/learning_agent_service/application/routing.py learning-agent-service/tests/test_router_package_exports.py
git commit -m "feat: split routing into router package"
```

### Task 2: Migrate workflow and tool call sites to import from `application.router`

**Files:**
- Modify: `learning-agent-service/src/learning_agent_service/application/workflow/adapters.py`
- Modify: `learning-agent-service/src/learning_agent_service/application/workflow/runner.py`
- Modify: `learning-agent-service/src/learning_agent_service/application/workflow/subgraphs.py`
- Modify: `learning-agent-service/src/learning_agent_service/tools/service.py`
- Modify: `learning-agent-service/tests/test_legacy_routing_purge.py` only if the new module layout requires a narrower scan target
- Test: `learning-agent-service/tests/test_workflow_runner.py`
- Test: `learning-agent-service/tests/test_workflow_rag_gate.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path


def test_workflow_modules_import_new_router_package() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "learning_agent_service" / "application" / "workflow"
    targets = [
        root / "adapters.py",
        root / "runner.py",
        root / "subgraphs.py",
    ]
    for path in targets:
        text = path.read_text(encoding="utf-8")
        assert "from ..routing import" not in text
        assert "from ..router import" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest learning-agent-service/tests/test_workflow_runner.py -q`
Expected: FAIL until the workflow modules point at `application.router` instead of `application.routing`.

- [ ] **Step 3: Write the minimal import migration**

```python
# learning_agent_service/application/workflow/adapters.py
from ..router import (
    _apply_route_review,
    _build_answer_contract,
    _build_answer_verifier_result,
    _build_entity_join_result,
    _mark_routing_blocked,
    _pending_clarification_matches_query,
    _update_phase0_trace,
    _update_phase1_trace,
    _update_phase2_trace,
    _update_phase3_trace,
    _update_phase4_trace,
    apply_fast_decision_to_routing,
    build_evidence_quality,
    build_initial_routing_decision,
    build_rewrite_decision,
    ensure_retrieval_plan,
    ensure_task_plan,
    ensure_tool_plan,
    normalize_query,
    routing_trace_payload,
    should_persist_memory as routing_should_persist_memory,
)

# learning_agent_service/application/workflow/runner.py
from ..router import _looks_like_unserviceable_location, _pending_clarification_matches_query

# learning_agent_service/application/workflow/subgraphs.py
from ..router import can_enter_retrieval, can_enter_tool, should_run_tool as routing_should_run_tool, _update_phase3_trace

# learning_agent_service/tools/service.py
from learning_agent_service.application.router import build_clarification_question
```

Do not change behavior in this step; only move the import surface so the workflow path depends on the new package. Keep the compatibility `routing.py` shim in place so any tests or external callers that still import `learning_agent_service.application.routing` continue to work during the migration window.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest learning-agent-service/tests/test_workflow_runner.py learning-agent-service/tests/test_workflow_rag_gate.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add learning-agent-service/src/learning_agent_service/application/workflow/adapters.py learning-agent-service/src/learning_agent_service/application/workflow/runner.py learning-agent-service/src/learning_agent_service/application/workflow/subgraphs.py learning-agent-service/src/learning_agent_service/tools/service.py
git commit -m "refactor: migrate workflow routing imports"
```

### Task 3: Verify chat interface behavior and keep the legacy purge green

**Files:**
- Test: `learning-agent-service/tests/test_chat_workflow.py`
- Test: `learning-agent-service/tests/local_life/test_day5_workflow_graph_chat.py`
- Test: `learning-agent-service/tests/local_life/test_day6_langgraph_chat_stream.py`
- Test: `learning-agent-service/tests/test_legacy_routing_purge.py`

- [ ] **Step 1: Run the chat-facing regression suite**

Run:
`python -m pytest learning-agent-service/tests/test_chat_workflow.py learning-agent-service/tests/local_life/test_day5_workflow_graph_chat.py learning-agent-service/tests/local_life/test_day6_langgraph_chat_stream.py -q`

Expected: PASS with no new `E`/`F` lines and no fallback/import noise in the output.

- [ ] **Step 2: Run the legacy purge check**

Run:
`python -m pytest learning-agent-service/tests/test_legacy_routing_purge.py -q`

Expected: PASS. The purge scan should still see no new `if ... route_decision/slots/decision` branching in the runtime files, and the compatibility wrapper must not reintroduce legacy logic.

- [ ] **Step 3: If any chat failure appears, fix only the router split or import migration**

```python
# Example shape for a local fix:
if routing is None:
    return legacy_routing.build_initial_routing_decision(...)
```

Use this only as a temporary compatibility path if a caller still depends on the old module boundary. Do not add new behavior branches in workflow nodes just to satisfy the refactor.

- [ ] **Step 4: Re-run the suite and confirm the terminal is clean**

Run:
`python -m pytest learning-agent-service/tests/test_chat_workflow.py learning-agent-service/tests/local_life/test_day5_workflow_graph_chat.py learning-agent-service/tests/local_life/test_day6_langgraph_chat_stream.py learning-agent-service/tests/test_legacy_routing_purge.py -q`

Expected: all tests PASS, and there is no red summary output.

- [ ] **Step 5: Commit**

```bash
git add learning-agent-service/tests/test_chat_workflow.py learning-agent-service/tests/local_life/test_day5_workflow_graph_chat.py learning-agent-service/tests/local_life/test_day6_langgraph_chat_stream.py learning-agent-service/tests/test_legacy_routing_purge.py
git commit -m "test: verify router split through chat"
```

---

## Self-Review

**Spec coverage:** This plan covers the two requested outcomes from `todo/learning-agent-service-refactor-plan.md` P1: split `application/routing.py` into a router package and migrate workflow-related call sites to the new modules. It also keeps the old `application.routing` import path alive long enough for chat and purge tests to stay green.

**Placeholder scan:** No `TBD`, `TODO`, or “write tests for the above” placeholders remain. Every task names concrete files, includes an actual code shape, and ends with an exact verification command.

**Type consistency:** The plan uses one import surface name throughout: `application.router`. The compatibility file stays `application.routing`, but it only re-exports the new package, so workflow code and chat tests can coexist during the migration.
