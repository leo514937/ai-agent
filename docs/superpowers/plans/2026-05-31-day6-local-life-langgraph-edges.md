# Day6 Local Life LangGraph Edges Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 local life 的核心分支收拢到 LangGraph conditional edges，并在 chat/stream 端完成 Day1-Day6 的最终用户视角验收。

**Architecture:** 复用现有 `application/workflow` 的 compiled graph 作为主编排，在 `understand_turn` 之后增加一层 `route_gate` 选择器，把 clarify / tool / rag / rag_plus_tool / recommendation / direct 分支明确化。`context` 仍由 `entity_resolver` / `target_shop_policy` / `route_review` 负责收敛，`harness` 继续保留 `phase*trace` 主记录，同时兼容旧验收键，保证 chat SSE 和离线测试读取同一套语义。

**Tech Stack:** Python 3.11, LangGraph, FastAPI SSE, Pydantic, pytest, existing local_life workflow modules.

---

### Task 1: 补 route_gate conditional edges

**Files:**
- Modify: `learning-agent-service/src/learning_agent_service/application/workflow/builder.py`
- Modify: `learning-agent-service/src/learning_agent_service/application/workflow/subgraphs.py`
- Modify: `learning-agent-service/src/learning_agent_service/application/workflow/runner.py`

- [ ] **Step 1: Write the failing chat acceptance for Day6 route_gate**

```python
def test_day6_route_gate_langgraph_chat(self):
    result = self.client.post_message(
        message="海底捞水晶城店现在营业吗？",
        session_id="day6-route-gate-001",
    )
    assert result.final_answer
    assert result.metrics.get("phase5_trace", {}).get("runner_kind") == "langgraph"
```

- [ ] **Step 2: Run the targeted test to confirm the current graph does not expose the new route_gate semantics**

Run: `python -m pytest learning-agent-service/tests/local_life/test_day6_langgraph_edges_chat.py::Day6LangGraphEdgesChatTestCase::test_day6_route_gate_langgraph_chat -q`
Expected: FAIL until `route_gate` is introduced and wired into the compiled graph.

- [ ] **Step 3: Implement the route_gate node and conditional edge selector**

```python
def route_gate(state: GraphState) -> GraphState:
    return state

def route_decider(state: GraphState) -> str:
    routing = state["turn"].routing_decision
    if routing is not None and routing.blocked:
        return "clarify"
    if routing is None:
        return "direct"
    action = str(routing.required_action).strip().lower()
    if action in {"clarify", "tool_call", "rag_retrieval", "rag_plus_tool", "direct_answer"}:
        return action
    return "direct"
```

- [ ] **Step 4: Re-run the targeted test and confirm the final SSE still carries `phase*trace` plus compatibility metrics**

Run: `python -m pytest learning-agent-service/tests/local_life/test_day6_langgraph_edges_chat.py::Day6LangGraphEdgesChatTestCase::test_day6_route_gate_langgraph_chat -q`
Expected: PASS with `phase5_trace.runner_kind == "langgraph"` and no missing metrics regression.

### Task 2: Stabilize context and answer-contract flow for Day6 branches

**Files:**
- Modify: `learning-agent-service/src/learning_agent_service/local_life/entity_resolver.py`
- Modify: `learning-agent-service/src/learning_agent_service/local_life/target_shop_policy.py`
- Modify: `learning-agent-service/src/learning_agent_service/local_life/route_review.py`
- Modify: `learning-agent-service/src/learning_agent_service/local_life/response_builder.py`

- [ ] **Step 1: Add regression tests for explicit shop override, pronoun inheritance, coupon-only, and recommendation routing in chat**

```python
def test_day6_context_priority_chat(self):
    first = self.client.post_message("海底捞水晶城店怎么样？", session_id="day6-context-001")
    second = self.client.post_message("巴奴毛肚火锅怎么样？", session_id="day6-context-001")
    assert "巴奴" in second.final_answer
    assert second.metrics.get("target_shop.source") == "current_query"
```

- [ ] **Step 2: Run the targeted regression and confirm it fails only when context priority leaks**

Run: `python -m pytest learning-agent-service/tests/local_life/test_day6_langgraph_edges_chat.py::Day6LangGraphEdgesChatTestCase::test_day6_context_priority_chat -q`
Expected: PASS after the resolver and route review are aligned.

- [ ] **Step 3: Tighten resolver / route review priority and ensure answer contract still strips forbidden facets**

```python
def route_priority():
    return "explicit_entity > pronoun_session > session > rag_fallback"
```

- [ ] **Step 4: Re-run chat checks for coupon/open-status/recommendation and verify no facet leak**

Run: `python -m pytest learning-agent-service/tests/local_life/test_day6_langgraph_edges_chat.py -q`
Expected: PASS.

### Task 3: Expand harness compatibility for Day6 acceptance

**Files:**
- Modify: `learning-agent-service/src/learning_agent_service/application/workflow/adapters.py`
- Modify: `learning-agent-service/src/learning_agent_service/testing/harness.py`
- Modify: `learning-agent-service/tests/local_life/chat_test_client.py`

- [ ] **Step 1: Add a failing check for legacy metric keys in the final SSE payload**

```python
assert "rag_mode" in result.metrics
assert "coupon_result" in result.metrics
assert "facet_result_bundle" in result.metrics
```

- [ ] **Step 2: Run the failure to confirm the current payload still needs explicit compatibility writing**

Run: `python -m pytest learning-agent-service/tests/local_life/test_day6_langgraph_edges_chat.py::Day6LangGraphEdgesChatTestCase::test_day6_metrics_compatibility_chat -q`
Expected: FAIL before compat mapping is added.

- [ ] **Step 3: Implement final payload compatibility mapping and harness extraction alignment**

```python
final_metrics = {
    **metrics,
    "target_shop.source": target_shop_source,
    "single_shop_mode": single_shop_mode,
    "answer_contract": answer_contract_dump,
    "rag_mode": rag_mode,
    "coupon_result": coupon_result_dump,
    "facet_result_bundle": facet_result_bundle_dump,
    "local_life_execution_contract": execution_contract_dump,
}
```

- [ ] **Step 4: Re-run the full Day1-Day6 chat suite**

Run: `python -m pytest learning-agent-service/tests/local_life/test_day1_target_shop_chat.py learning-agent-service/tests/local_life/test_day2_answer_contract_chat.py learning-agent-service/tests/local_life/test_day3_tools_coupon_chat.py learning-agent-service/tests/local_life/test_day4_rag_recommendation_chat.py learning-agent-service/tests/local_life/test_day5_workflow_graph_chat.py learning-agent-service/tests/local_life/test_day6_langgraph_edges_chat.py -q`
Expected: PASS.

### Task 4: Document remaining gaps

**Files:**
- Create or modify: `todo/fix.md`

- [ ] **Step 1: Collect any unresolved Day6 regressions from the chat acceptance run**
- [ ] **Step 2: Write the unresolved issues with reproduction queries and the exact metrics or answer text that failed**
- [ ] **Step 3: Confirm the fix log only contains unresolved items and not already-passed cases**

---

## Self-Review

**Spec coverage:** This plan covers Day6 conditional edges, context hardening, harness compatibility, chat-stream verification, and failure logging.

**Placeholder scan:** No TBD-style placeholders remain; each task has concrete files, code shape, and a test command.

**Type consistency:** The plan uses the same `phase*trace`, `answer_contract`, `coupon_result`, `facet_result_bundle`, and `local_life_execution_contract` names already present in the codebase.
