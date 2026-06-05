# Day7：GraphState、Memory Arbitration、Harness、Cutover 与生产硬化

> 目标：把 Day3–Day6 的能力全部纳入 LangGraph 状态生命周期，补齐 Memory Arbitration、全量 Harness、Observability，并完成生产切流与硬化。  
> 产出：不是“能跑”，而是“可验收、可上线、可回滚、可持续防退化”。

---

## 1. Day7 要解决什么

Day7 合并四类最终工作：

```text
1. GraphState 与 Context 生命周期。
2. Memory Arbitration / Current Turn Perception 优先级。
3. Golden Cases / Observability / Error Taxonomy。
4. Cutover / 删除或废弃 legacy fallback / 生产硬化。
```

---

## 2. GraphState 设计

### Input Context

```python
class InputContext:
    raw_query: str
    latest_turn_message: str
    session_id: str
    user_id: str | None
    client_context: dict
    request_ts: str
```

### Turn Runtime State

```python
class TurnRuntimeState:
    normalized_query: str | None
    current_intent: dict | None
    user_need: dict | None
    perception_context: dict | None
    memory_arbitration: dict | None
    target_shop: dict | None
    recommendation_scope: dict | None
    answer_contract: dict | None
    route_decision: dict | None
    rag_plan: dict | None
    rag_evidence_pack: dict | None
    tool_plan: dict | None
    tool_results: list[dict]
    answer_depth_policy: dict | None
    answer_quality_gate: dict | None
    final_answer: str | None
    errors: list[dict]
```

### Persistent Context

```python
class PersistentContext:
    current_shop: dict | None
    last_candidates: list[dict]
    recommendation_scope: dict | None
    pending_clarification: dict | None
    history_summary: str | None
    user_preferences: dict
```

---

## 3. Memory Arbitration

### 3.1 优先级

```text
System / Safety Rules
> Current Turn Perception
> Session Constraints
> Current Profile Projection
> Active Long-term Memory
> Entity Memory
> Historical / Superseded / Inactive Memory
```

---

### 3.2 PerceptionContext

```python
@dataclass
class PerceptionContext:
    raw_query: str
    normalized_query: str | None
    explicit_shop: dict | None
    client_selected_shop: dict | None
    explicit_constraints: dict
    detected_facets: list[str]
    temporal_scope: str
    confidence: float
```

---

### 3.3 MemoryArbitrationResult

```python
@dataclass
class MemoryArbitrationResult:
    effective_context: dict
    winning_sources: dict
    suppressed_memories: list[dict]
    promotion_candidates: list[dict]
    conflict_reason: str | None
```

---

## 4. Temporal Scope

临时表达只写 session：

```text
今天
这次
暂时
先
先别
临时
```

长期表达进入 promotion candidate：

```text
以后
从现在开始
我不再
我戒掉
永远
以后都
```

---

## 5. 节点读写边界

每个 LangGraph 节点必须定义：

```text
requires
writes
invariants
error_behavior
```

禁止：

```text
rag_subgraph 修改 target_shop
tool_subgraph 修改 answer_contract
compose_answer 偷偷补充 forbidden facet
persist_session 把 recommendation 轮写成 current_shop
```

新增：

```text
state_diff
node_writes
illegal_state_mutation
```

---

## 6. Harness 分层

```text
L1 Unit Harness
L2 Node Harness
L3 Route Harness
L4 Chat E2E Harness
L5 Golden Cases Regression
```

所有关键验收必须从：

```text
POST /internal/v1/chat/stream
```

触发。

---

## 7. Golden Cases

新增：

```text
eval/local_life/golden_cases.jsonl
```

覆盖：

```text
Tool 实时信息
RAG 脏数据拦截
RAG 父子/混合检索
Answer Quality
Memory Arbitration
Latest Turn Priority
Recommendation 不被 single_shop 污染
```

---

## 8. Error Taxonomy

```text
LOW_INFO_QUERY
TARGET_SHOP_MISSING
TARGET_SHOP_AMBIGUOUS
TARGET_SHOP_WRONG
ROUTE_MISMATCH
CONTRACT_VIOLATION
FACET_LEAK
RAG_EMPTY
RAG_CROSS_SHOP
RAG_LOW_CONFIDENCE
RAG_DIRTY_CONTEXT
TOOL_TIMEOUT
TOOL_ERROR
TOOL_BAD_RESULT
UNSUPPORTED_REALTIME_CLAIM
ANSWER_TOO_SHORT
ANSWER_REPETITIVE
RECOMMENDATION_DUPLICATE_SHOP
MEMORY_ARBITRATION_ERROR
GRAPH_NODE_ERROR
GRAPH_ILLEGAL_STATE_MUTATION
COMPOSE_ERROR
```

---

## 9. Trace 标准

每轮输出：

```json
{
  "trace_id": "...",
  "runner_kind": "langgraph",
  "graph_runtime": "langgraph",
  "nodes_visited": [],
  "latest_turn_message": "...",
  "current_intent": {},
  "priority_source": "latest_turn_message",
  "target_shop": {},
  "answer_contract": {},
  "tool_plan": {},
  "tool_results": [],
  "rag_guardrail": {},
  "answer_quality": {},
  "memory_arbitration": {},
  "latency": {},
  "errors": []
}
```

---

## 10. 指标体系

```text
success_rate
clarification_rate
tool_timeout_rate
rag_empty_rate
avg_latency_ms
p95_latency_ms
target_shop_accuracy
route_accuracy
facet_leak_rate
cross_shop_rate
dirty_context_rate
unsupported_realtime_claim_rate
answer_too_short_rate
answer_repetitive_rate
recommendation_diversity
latest_turn_priority_failure_rate
```

---

## 11. 回放工具

新增 CLI：

```bash
python -m learning_agent_service.local_life.eval.run_golden_cases \
  --cases eval/local_life/golden_cases.jsonl \
  --output reports/local_life_golden_report.json
```

---

## 12. Cutover 策略

配置：

```text
LOCAL_LIFE_USE_LANGGRAPH=true
LOCAL_LIFE_REQUIRE_LANGGRAPH_IN_TEST=true
LOCAL_LIFE_TRACE_ENABLED=true
LOCAL_LIFE_ANSWER_LINTER_ENABLED=true
LOCAL_LIFE_GOLDEN_CASES_REQUIRED=true
```

Day7 完成后：

```text
LOCAL_LIFE_LANGGRAPH_FALLBACK_LEGACY 应删除或废弃。
test / staging / prod 都应以 LangGraph 为唯一运行时主路径。
```

---

## 13. 删除或废弃的旧入口

```text
ChatWorkflowService 中的 legacy fallback 分支
create_workflow_runner 中用于生产切换到 SequentialWorkflowRunner 的路径
LOCAL_LIFE_LANGGRAPH_FALLBACK_LEGACY 运行时开关
生产代码对 LocalLifeSubgraph 作为主链路的直接依赖
```

---

## 14. 性能预算

```text
整体 p95 < 5s
route + target < 300ms
RAG < 1500ms
Tool < 2000ms
compose + quality gate < 1200ms
```

超过时记录：

```text
slow_trace
node_latencies
tool_latency
rag_latency
compose_latency
quality_gate_latency
```

---

## 15. 验收标准

Day7 完成后必须满足：

```text
1. latest_turn_message 是每轮状态推导第一输入。
2. Current Turn Perception 高于 session / profile / long-term。
3. 临时约束不污染长期记忆。
4. recommendation_scope 与 target_shop 分离。
5. 每个节点输入输出边界清楚。
6. state diff 可观测。
7. golden_cases 通过率 >= 95%。
8. graph_runtime = langgraph。
9. 生产运行时无 legacy fallback 分支。
10. dirty_context_rate = 0。
11. answer_too_short_rate 在核心场景为 0。
12. answer_repetitive_rate 在核心场景为 0。
```

---

## 16. 给 Codex 的执行提示词

```text
你是资深 LangGraph / State Machine / Memory Arbitration / Harness Engineering / Production Hardening 工程师。

Day1-Day6 已完成。请执行 Day7：GraphState、Memory Arbitration、Harness、Cutover 与生产硬化。

必须完成：
1. 定义 InputContext / TurnRuntimeState / PersistentContext。
2. 新增 PerceptionContext 和 MemoryArbitrationPolicy。
3. 实现 Current Turn Perception 优先级。
4. 实现 temporal scope。
5. 每个 LangGraph node 定义 requires/writes/invariants/error_behavior。
6. 增加 state_diff 和 illegal_state_mutation。
7. 新增 golden_cases 和 run_golden_cases CLI。
8. 定义 error taxonomy 和质量指标。
9. 清理或废弃 legacy fallback 运行时入口。
10. 增加性能预算和 slow_trace。
11. 更新 README / ARCHITECTURE / 回滚指南。
12. 所有关键测试从 /internal/v1/chat/stream 触发。
13. 输出最终报告：pass/fail、失败类型分布、性能、剩余风险。

不要只写计划，必须完成代码修改和测试验证。
```
