# DeterministicToolWorkflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a minimal independent `DeterministicToolWorkflow` for explicit single-shop factual queries and register it behind `workflow_runner` without changing the DiscoveryDecision main chain.

**Architecture:** Keep the workflow as a thin, single-purpose dispatcher. It should validate the target shop, map one task type to one existing tool, build evidence from tool output, produce an answer plan, and verify the response. Fallbacks should remain conservative and reuse the existing clarification / safe-failure behavior rather than introducing Phase 7 workflows.

**Tech Stack:** Python, Pydantic, existing LangGraph state models, existing tool gateway/registry, existing evidence/answer/verifier pipeline, pytest.

---

### Task 1: Lock the Phase 6 behavior with tests first

**Files:**
- Create: `local_life_agent/tests/test_deterministic_tool_workflow.py`
- Modify: `local_life_agent/tests/test_workflow_registry.py`
- Modify: `local_life_agent/tests/test_workflow_runner.py`

- [ ] **Step 1: Write the failing test**

```python
from local_life_agent.engine.workflow_registry import WORKFLOW_REGISTRY

def test_deterministic_tool_registry_entry_becomes_real_callable():
    registration = WORKFLOW_REGISTRY.lookup("deterministic_tool")
    assert registration.status == "registered"
    assert registration.entry_node is not None
```

```python
from local_life_agent.engine.workflow_runner import h_workflow_runner

def test_workflow_runner_dispatches_deterministic_tool(monkeypatch):
    state = {
        "trace_id": "trace_1",
        "session_id": "session_1",
        "turn_id": "turn_1",
        "task_type": "shop_status",
        "workflow_name": "deterministic_tool",
        "orchestration_pattern": "deterministic_tool",
        "orchestration_decision": {
            "orchestration_pattern": "deterministic_tool",
            "workflow_name": "deterministic_tool",
            "workflow_reason": "single-shop status query",
            "task_complexity": "low",
            "requires_tool": True,
            "requires_clarification": False,
            "response_mode": "tool_answer",
            "confidence": 0.9,
            "missing_fields": [],
            "next_action": "run_workflow",
        },
        "current_shop": {"shop_id": "900001", "shop_name": "测试店"},
        "semantic_frame": {"task_type": "shop_status", "primary_task": "open_status"},
        "event_log": [],
    }
    result = h_workflow_runner(state)
    assert result["workflow_name"] == "deterministic_tool"
```

```python
from local_life_agent.engine.workflows.deterministic_tool_workflow import run_deterministic_tool_workflow

def test_shop_status_uses_open_status_tool(monkeypatch):
    calls = []
    def fake_dispatch(tool_name, args):
        calls.append((tool_name, dict(args)))
        return {"success": True, "result_status": "ok", "data": {"is_open": True}}
    # patch the gateway in the implementation module
    result = run_deterministic_tool_workflow({
        "task_type": "shop_status",
        "current_shop": {"shop_id": "900001", "shop_name": "测试店"},
        "trace_id": "trace_1",
        "session_id": "session_1",
        "turn_id": "turn_1",
    })
    assert calls[0][0] == "check_open_status"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest local_life_agent/tests/test_deterministic_tool_workflow.py -q`
Expected: FAIL because the workflow module and/or registry behavior is missing.

- [ ] **Step 3: Write minimal implementation**

Implement the new workflow module with a small policy table, explicit single-shop target validation, existing-tool dispatch, evidence construction, answer planning, verifier check, and safe fallback for ambiguous targets or tool failure.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest local_life_agent/tests/test_deterministic_tool_workflow.py -q`
Expected: PASS.

### Task 2: Register the real deterministic workflow

**Files:**
- Modify: `local_life_agent/engine/workflow_registry.py`
- Modify: `local_life_agent/engine/workflow_runner.py` only if required for compatibility, without adding new business logic

- [ ] **Step 1: Write the failing test**

Add a registry assertion that `deterministic_tool` is no longer `not_implemented` and that the registered callable reports a real dispatch path.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest local_life_agent/tests/test_workflow_registry.py -q`
Expected: FAIL until the registry points at the new workflow callable.

- [ ] **Step 3: Write minimal implementation**

Replace the `deterministic_tool` placeholder registration with the new callable, keep `direct_response` / `clarification_fallback` / `exploration_planning` as placeholders, and do not change runner policy.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest local_life_agent/tests/test_workflow_registry.py -q`
Expected: PASS.

### Task 3: Cover target ambiguity, fallback, and pollution guards

**Files:**
- Create: `local_life_agent/tests/test_deterministic_tool_workflow.py`
- Modify: `local_life_agent/tests/test_workflow_runner.py`
- Modify: `local_life_agent/tests/test_05_graph.py` only if graph wiring needs a small assertion update

- [ ] **Step 1: Write the failing test**

Add cases for:
- missing target -> no tool call, safe fallback
- multiple targets -> no tool call, safe fallback
- "第二家" without history -> no tool call, safe fallback
- tool failure -> `failed_tools` and fallback
- empty tool result -> unknown/empty, no fabrication
- no pollution of `last_recommendation_list`, `last_answer_order`, or `comparison_targets`

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest local_life_agent/tests/test_deterministic_tool_workflow.py -q`
Expected: FAIL for the new edge cases until implemented.

- [ ] **Step 3: Write minimal implementation**

Add target resolution helpers that only accept explicit single-shop anchors from validated shop state and reject ambiguous or multi-target requests. Keep answer generation strictly bound to `EvidencePack` and `AnswerPlan`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest local_life_agent/tests/test_deterministic_tool_workflow.py -q`
Expected: PASS.

### Task 4: Verify regression boundaries and write the Phase 6 report

**Files:**
- Modify: `todo/0000_execution_order_and_progress.md`
- Modify: `todo/03_workflow_design.md`
- Modify: `todo/04_migration_phases.md`
- Modify: `todo/05_state_and_schema_design.md`
- Modify: `todo/06_toolcall_only_scope.md`
- Modify: `todo/07_testing_and_acceptance.md`
- Modify: `todo/09_implementation_todo.md`
- Modify: `todo/11_workflow_pattern_mapping.md`
- Modify: `todo/12_prompt_policy_and_logging_guidelines.md`
- Create: `todo/phase6_deterministic_tool_workflow_report.md`

- [ ] **Step 1: Run verification commands**

Run:
- `python -m compileall local_life_agent`
- `pytest local_life_agent/tests/test_orchestration_router.py -q`
- `pytest local_life_agent/tests/test_workflow_registry.py -q`
- `pytest local_life_agent/tests/test_workflow_runner.py -q`
- `pytest local_life_agent/tests/test_deterministic_tool_workflow.py -q`
- `pytest local_life_agent/tests/test_05_graph.py -q`
- `pytest local_life_agent/tests/test_trace_observability.py -q`

- [ ] **Step 2: Confirm DiscoveryDecision remains intact**

Run the relevant existing recommendation / comparison regression tests and confirm they still pass or that any remaining failures are pre-existing and unrelated to Phase 6.

- [ ] **Step 3: Write the Phase 6 report**

Document the workflow entry point, registry registration, runner dispatch, supported task types, existing tools, future tools, fallback rules, logging fields, test results, and any remaining historical failures.

