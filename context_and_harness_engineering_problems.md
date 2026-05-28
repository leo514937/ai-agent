# Local Life Agent Service: Remaining Context Engineering & Harness Engineering Issues

This document compiles all remaining structural issues, logical loopholes, and architectural vulnerabilities regarding **Context Engineering** and **Harness Engineering (Testing Framework)** within the Local Life Agent Service.

---

## Part 1: Context Engineering Issues

### 1. `pending_user_need` Lacks Topic-Shift Expiry (重大上下文工程漏洞)
*   **Vulnerability Description**: When the agent requests slot clarifications (such as asking for the user's city), it saves the active query constraints under `pending_user_need` in Redis. In [context_arbitration.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/local_life/context_arbitration.py#L100-L132), if a `pending_user_need` exists, the arbitrator unconditionally merges the new query's slots with the pending slots on the next turn.
*   **Logical Flaw**: If the user decides to change the topic entirely (e.g., "讲个笑话" or "帮我订去上海的高铁票") instead of answering the slot clarification, the arbitrator still forcefully injects the historical restaurant category and price constraints into the new topic, contaminating the session state.
*   **Impact**: Severe cross-topic context contamination and broken conversational transitions.
*   **Suggested Mitigation**: Implement an **Intent Shift Guard** that compares the semantic embedding of the new raw query with the pending intent or category. If they are disjoint, immediately clear `pending_user_need` from Redis and process the query as a new topic.

### 2. Unlimited Memory Growth of `recent_entities` and `last_candidates`
*   **Vulnerability Description**: Every multi-turn recommendation writes historical candidates and selected shop anchors back into the session data in Redis.
*   **Logical Flaw**: There is no sliding window cap or decay mechanism for these lists. Over long conversational threads (e.g., 20+ turns), the serialization overhead grows exponentially.
*   **Impact**: High Redis serialization latency, excessive CPU usage, and high risk of false-positive entity matching during reference resolution.
*   **Suggested Mitigation**: Enforce a strict sliding window limit (e.g., keep only the last **5 candidates**) and automatically clean historical shop anchors that are older than **3 turns**.

### 3. List-Type Slot Merging Semantic Contradictions (槽位合并冲突)
*   **Vulnerability Description**: In `_merge_slots` of [context_arbitration.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/local_life/context_arbitration.py#L46-L47), list-type slots (`avoid`, `preferences`, `companions`) are merged using simple list concatenation:
    ```python
    merged[key] = list(dict.fromkeys([*(pending_slots.get(key) or []), *(merged.get(key) or [])]))
    ```
*   **Logical Flaw**: If a user updates their preference (e.g., changing from "我不想吃辣" to "我想吃微辣的川菜"), the old constraint (`辣` in `avoid`) is merged with the new preference (`川菜`), creating mutually exclusive, self-contradictory logic.
*   **Impact**: Corrupted RAG filtering and inaccurate tool calling arguments.
*   **Suggested Mitigation**: Define an intelligent semantic override scheme where positive changes in category or scene automatically flush conflicting historical negative lists.

### 4. Rigid Page Context (`client_context.shopId`) Overriding User Intent Shifts
*   **Vulnerability Description**: Page context (such as the shop details page the user is currently browsing) is loaded with high priority in [entity_resolver.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/local_life/entity_resolver.py#L128-L139).
*   **Logical Flaw**: If a user is viewing a "Mamala Restaurant" page but types "我累了，推荐水晶城附近的 KTV 吧", the resolver might still bind `resolved_shop_id` to Mamala, restricting subsequent RAG or tool executions to Mamala and causing a mismatch.
*   **Impact**: Mismatched recommendation and poor multi-turn page interaction experience.
*   **Suggested Mitigation**: Implement a category-consistency check. If the slots category (KTV) is disjoint from the page context's entity category (Restaurant), discard the page context binding.

---

## Part 2: Harness Engineering Issues

### 1. Test Sandbox Contamination & Dependency Leakage (测试沙箱未完全隔离)
*   **Vulnerability Description**: Several test suites under `tests/` (such as `test_qdrant_runtime.py` and `tests/rag/test_hybrid_retrieval.py`) invoke physical clients (`QdrantClient`, `Redis`) instead of running inside fully sandboxed mocks.
*   **Logical Flaw**: Executing test suites causes direct physical socket requests. This triggers warning prompts (e.g., `UserWarning: Api key is used with an insecure connection`) and introduces environment sensitivity.
*   **Impact**: High risk of writing test data into production databases (Data Pollution) and flaky tests due to network timing or port configurations.
*   **Suggested Mitigation**: Configure `pytest` to strictly swap all persistent clients with fully isolated in-memory instances (e.g., `QdrantClient(location=":memory:")` and Python-dict based session mocks) during test runs.

### 2. Lack of Streaming SSE Replay & Delta Assertions in `ReplayHarness`
*   **Vulnerability Description**: The [harness.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/testing/harness.py#L211-L289) validation framework executes synchronous test runs and asserts against static, compiled responses.
*   **Logical Flaw**: The production API utilizes asynchronous Server-Sent Events (SSE). The harness is blind to intermediate stream events like `ack`, `heartbeat`, and the token delta streaming process (`answer_delta`).
*   **Impact**: Incapability to detect regressions that break streaming flow, disrupt keep-alive pulse timing, or block initial token latency.
*   **Suggested Mitigation**: Extend the testing framework with a `StreamReplayHarness` that simulates E2E SSE stream packets, validating sequence indexes and streaming delta integrity.

### 3. Flaky Time-Sensitive Assertions (脆弱的耗时/超时断言)
*   **Vulnerability Description**: Test suites simulate slow executions or network latency by calling hardcoded blocking sleeps (e.g., `time.sleep(1.2)` in `test_chat_workflow.py` to trigger LLM routing timeouts).
*   **Logical Flaw**: Real system sleeps depend on CPU schedules, which are highly variable on CI servers or lower-end developer machines.
*   **Impact**: High rate of flaky tests failing on virtualization platforms.
*   **Suggested Mitigation**: Utilize mocking libraries (like `freezegun` or patching `time.time` and `time.sleep` with virtual clocks) to simulate elapsed time without actually blocking threads.

### 4. Lack of Multi-User Concurrency & Session Race Condition Testing
*   **Vulnerability Description**: The testing framework only exercises single-threaded, sequential queries.
*   **Logical Flaw**: FastAPI is highly concurrent. If state parameters inside `LocalLifeTurnState` or global session stores are shared without thread-safety checks, concurrent requests from the same user or different users will bleed into each other.
*   **Impact**: Serious data leakages and thread-safety crashes under high traffic.
*   **Suggested Mitigation**: Write a concurrency test harness inside the `scratch` directory using `asyncio.gather` to send 100+ parallel requests and assert that session variables remain perfectly isolated.

### 5. Test Data Mutation on Shared Local Database (缺乏物理沙箱隔离)
*   **Vulnerability Description**: Tests like `test_local_life_seed.py` and `test_local_life_pipeline.py` write physical seeding rows into the active local SQL or Qdrant databases.
*   **Logical Flaw**: Parallel test runners can conflict or mutate the same records simultaneously, polluting shared resources.
*   **Impact**: Flaky pipeline and slow execution due to shared DB contention.
*   **Suggested Mitigation**: Force all test cases to spin up isolated SQLite in-memory databases and isolated vector spaces for the duration of the test run, wiping them clean on completion.
