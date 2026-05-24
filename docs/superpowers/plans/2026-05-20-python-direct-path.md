# Python Direct Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove Java-side local fallback and make local-life turn understanding and tool planning flow through Python LLM-backed components with strict structured outputs.

**Architecture:** Java will become a thin remote relay that always attempts the Python service when configured, without health-based short-circuiting or local response synthesis. Python will own the turn-understanding and tool-planning decisions with OpenAI-backed structured outputs, while keeping the existing rule-based planner as a fallback only when the model path is unavailable.

**Tech Stack:** Java Spring service, Python FastAPI service, OpenAI Responses API, pytest, JUnit 5.

---

### Task 1: Remove Java health-gate short-circuiting

**Files:**
- Modify: `src/main/java/com/hmdp/ai/remote/AiRemoteClient.java`
- Test: `src/test/java/com/hmdp/ai/remote/AiRemoteClientHealthGateTest.java`

- [ ] **Step 1: Write the failing test**

```java
@Test
void shouldTreatConfiguredRemoteAsEnabledEvenBeforeHealthProbe() {
    AiRemoteClient client = new AiRemoteClient();
    ReflectionTestUtils.setField(client, "properties", configuredProperties());
    ReflectionTestUtils.setField(client, "lastHealthProbeHealthy", false);
    assertTrue(client.isEnabled());
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `mvn -Dtest=AiRemoteClientHealthGateTest test`
Expected: FAIL because `isEnabled()` still depends on the cached health probe.

- [ ] **Step 3: Write minimal implementation**

```java
public boolean isEnabled() {
    return properties != null && properties.isAvailable();
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `mvn -Dtest=AiRemoteClientHealthGateTest test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/main/java/com/hmdp/ai/remote/AiRemoteClient.java src/test/java/com/hmdp/ai/remote/AiRemoteClientHealthGateTest.java
git commit -m "feat: remove remote health gate fallback"
```

### Task 2: Keep Java chat path remote-only

**Files:**
- Modify: `src/main/java/com/hmdp/service/AiAssistantService.java`
- Modify: `src/main/java/com/hmdp/service/AiAssistantStreamService.java`
- Test: `src/test/java/com/hmdp/service/AiAssistantServiceRecommendTest.java`
- Test: `src/test/java/com/hmdp/service/AiAssistantStreamServiceTest.java`

- [ ] **Step 1: Write the failing test**

```java
@Test
void shouldNotExposeLocalFallbackResponseBuilder() {
    AiAssistantService service = new AiAssistantService();
    assertThrows(NoSuchMethodException.class, () ->
            AiAssistantService.class.getDeclaredMethod("buildLocalFallbackResponse",
                    AiChatRequest.class, UserDTO.class));
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `mvn -Dtest=AiAssistantServiceRecommendTest test`
Expected: FAIL until the dead local fallback helper is removed.

- [ ] **Step 3: Write minimal implementation**

```java
// Remove buildLocalFallbackResponse and any helper methods that only support it.
// Keep chat() and stream() as remote-only entry points.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `mvn -Dtest=AiAssistantServiceRecommendTest,UiAssistantStreamServiceTest test`
Expected: PASS with updated remote-only assertions.

- [ ] **Step 5: Commit**

```bash
git add src/main/java/com/hmdp/service/AiAssistantService.java src/main/java/com/hmdp/service/AiAssistantStreamService.java src/test/java/com/hmdp/service/AiAssistantServiceRecommendTest.java src/test/java/com/hmdp/service/AiAssistantStreamServiceTest.java
git commit -m "feat: remove java local fallback responses"
```

### Task 3: Add LLM-backed turn understanding for local-life slots

**Files:**
- Modify: `learning-agent-service/src/learning_agent_service/application/dependencies.py`
- Modify: `learning-agent-service/src/learning_agent_service/domain/contracts.py`
- Modify: `learning-agent-service/src/learning_agent_service/local_life/assistant.py`
- Test: `learning-agent-service/tests/test_local_life_pipeline.py`

- [ ] **Step 1: Write the failing test**

```python
def test_local_life_understanding_forces_tool_then_answer(model_gateway):
    result = model_gateway.classify_turn(request)
    assert result.decision == TurnDecision.TOOL_THEN_ANSWER
    assert result.slots["local_life_intent"] == "recommend"
    assert result.slots["tool_name"] == "search_restaurants"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_local_life_pipeline.py -q`
Expected: FAIL because the current merge and slot shaping do not guarantee these fields.

- [ ] **Step 3: Write minimal implementation**

```python
# Preserve model_result for local-life intent when the OpenAI response is valid.
# Ensure slots carry tool_name, local_life_intent, and domain fields for tool planning.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_local_life_pipeline.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add learning-agent-service/src/learning_agent_service/application/dependencies.py learning-agent-service/src/learning_agent_service/domain/contracts.py learning-agent-service/src/learning_agent_service/local_life/assistant.py learning-agent-service/tests/test_local_life_pipeline.py
git commit -m "feat: strengthen local life understanding contract"
```

### Task 4: Add OpenAI-backed tool planning with strict JSON output

**Files:**
- Modify: `learning-agent-service/src/learning_agent_service/application/dependencies.py`
- Modify: `learning-agent-service/src/learning_agent_service/tools/service.py`
- Modify: `learning-agent-service/src/learning_agent_service/domain/protocols.py`
- Test: `learning-agent-service/tests/test_tools.py`

- [ ] **Step 1: Write the failing test**

```python
def test_tool_planner_returns_structured_local_life_selection(openai_runtime):
    selection = planner.plan(request)
    assert selection.tool_name == "search_restaurants"
    assert selection.should_execute is True
    assert selection.input_payload["city"] == "北京"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tools.py -q`
Expected: FAIL because the planner is still rule-based and does not call OpenAI.

- [ ] **Step 3: Write minimal implementation**

```python
# Add an OpenAI-backed planner that returns strict JSON for tool_name,
# should_execute, input_payload, reason, approval_required, approval_request, and extra.
# Wire build_dependencies() to use it when the OpenAI runtime is available.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_tools.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add learning-agent-service/src/learning_agent_service/application/dependencies.py learning-agent-service/src/learning_agent_service/tools/service.py learning-agent-service/src/learning_agent_service/domain/protocols.py learning-agent-service/tests/test_tools.py
git commit -m "feat: add llm-backed tool planner"
```

### Task 5: Verify end-to-end regression coverage

**Files:**
- Modify: `learning-agent-service/tests/test_chat_workflow.py`
- Modify: `src/test/java/com/hmdp/...`

- [ ] **Step 1: Run the targeted test suites**

Run:
`mvn test -DskipTests=false`
`pytest learning-agent-service/tests -q`

- [ ] **Step 2: Confirm no fallback helpers remain in the Java assistant path**

Run:
`Get-ChildItem -Path src/main/java -Recurse -File | Select-String -Pattern 'buildLocalFallbackResponse|local-business-compat'`

- [ ] **Step 3: Confirm the Python path still emits structured final payloads**

Run:
`pytest learning-agent-service/tests/test_chat_workflow.py -q`

- [ ] **Step 4: Commit**

```bash
git add .
git commit -m "feat: route local life traffic through python agent"
```
