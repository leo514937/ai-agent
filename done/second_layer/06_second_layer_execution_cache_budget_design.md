# 第二层执行、并行、缓存与预算设计

本文件只设计目标方案，不修改业务代码。内容以当前仓库真实实现为基线，重点解决“现在只有 batch 并发，没有真正 DAG 执行器”的问题。

## 1. 当前实现事实

### 1.1 执行器现状

- `local_life_agent/core/execution_core.py`
  - `ExecutionCore.execute_batch()` 只是把工具调用交给 `ToolBatchExecutor`
  - 证据：[execution_core.py:20-25](D:/javacode/hm-dianping/local_life_agent/core/execution_core.py#L20)
- `local_life_agent/planning/evidence/tool_batch_executor.py`
  - `ToolBatchExecutor.execute()` 最终还是走 `BatchToolExecutor.execute_sync()`
  - 证据：[tool_batch_executor.py:18-19](D:/javacode/hm-dianping/local_life_agent/planning/evidence/tool_batch_executor.py#L18)
- `local_life_agent/tools/gateway.py`
  - `BatchToolExecutor.execute()` 只是 `asyncio.gather` + 信号量控制，直接将所有工具调用平铺并发：`await asyncio.gather(*tasks)`
  - 证据：[gateway.py:243-259](D:/javacode/hm-dianping/local_life_agent/tools/gateway.py#L243)
  - 当前不理解 `depends_on` 的拓扑语义——所有工具调用被打平成 `batch_calls` 列表后统一用 `asyncio.gather` 执行，没有按 `depends_on` 分层执行
- **两阶段执行模式的真实路径**：当前 `_h_tool_execute` 将工具调用分为 `search_calls` 和 `remaining_specs` 两个批次顺序执行，先 search 再 follow-up，本质上仍是手写两阶段而非通用 DAG 调度
  - 证据：[execution_review_subgraph.py:124-131](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/execution_review_subgraph.py#L124)

### 1.2 配置级事实

当前执行和预算相关的配置值（来自 `config.py`）：

| 配置项 | 值 | 位置 |
|---|---|---|
| `MAX_CONCURRENCY` | 8 | [config.py:33](D:/javacode/hm-dianping/local_life_agent/config.py#L33) |
| `MAX_TOOL_CALLS` | 40 | [config.py:35](D:/javacode/hm-dianping/local_life_agent/config.py#L35) |
| `TOOL_DEFAULT_TIMEOUT_MS` | 2000 | [config.py:172](D:/javacode/hm-dianping/local_life_agent/config.py#L172) |
| `MAX_EXPAND_SEARCH_ROUNDS` | 1 | [config.py:213](D:/javacode/hm-dianping/local_life_agent/config.py#L213) |
| `MAX_REPLAN_EVIDENCE_ROUNDS` | 1 | [config.py:215](D:/javacode/hm-dianping/local_life_agent/config.py#L215) |
| `DEADLINE_MS` | 参考 `config.py` | [gateway.py:170](D:/javacode/hm-dianping/local_life_agent/tools/gateway.py#L170) |

### 1.3 当前并发控制

当前 `BatchToolExecutor._run_one` 使用 `asyncio.Semaphore` 控制并发，semaphore 初始化为 `max(c.max_parallelism for c in batch_calls)` 和 `max_concurrency` 的最小值，但这是全量均等信号量，没有按 stage/depends_on 分层的并发控制。
  - 证据：[gateway.py:248](D:/javacode/hm-dianping/local_life_agent/tools/gateway.py#L248)

### 1.4 `dispatch_tool_call` 的日志记录

当前工具调用的观测点只有 `dispatch_tool_call()` 中记录的 `[TOOL_CALL]` 和 `[TOOL_RESULT]` 日志，没有 DAG 节点 ID、依赖链、cache key、degrade_reason 等结构化的执行轨迹字段。
  - 证据：[gateway.py:275-321](D:/javacode/hm-dianping/local_life_agent/tools/gateway.py#L275)

### 1.2 缓存现状

- `local_life_agent/planning/evidence/evidence_cache.py`
  - 已有 `EvidenceCache` 类，内部维护 `_store: dict[tuple[str, str], EvidenceCacheRecord]`
  - `get_or_build(scope, payload, builder)` 方法以 `(cache_scope, fingerprint)` 为 key 做证据缓存，`fingerprint` 是 payload 的 `sha256` 哈希的前 16 位
  - 它缓存的是"证据构建结果"，不是"并发工具调用去重"
  - 缓存是纯内存、无 TTL 机制、无 freshness 判断的——一旦写入永不过期
  - 证据：[evidence_cache.py:47-93](D:/javacode/hm-dianping/local_life_agent/planning/evidence/evidence_cache.py#L47)
- `local_life_agent/planning/evidence/evidence_builder.py`
  - `build_evidence()` 使用 `EvidenceCache`，但这是证据构建结果缓存，不是工具调用结果缓存
  - 作用范围更像 evidence-level cache，而非 tool-result-level cache
  - 证据：[evidence_builder.py:876-960](D:/javacode/hm-dianping/local_life_agent/planning/evidence/evidence_builder.py#L876)
- **无 ToolResultCache**：当前没有任何跨 workflow 的工具调用结果缓存。多个 workflow（如推荐 + 单店查询同时查同一家店的距离/营业/券）会重复发起真实工具调用
- **无 single-flight**：没有并发请求去重机制，即使 `cache_key` 相同的请求也不会被合并

### 1.3 预算现状

- `local_life_agent/planning/budget/budget_context.py`
  - `BudgetContext` 已经存在，默认值：`tool_round_budget=2`、`retry_budget=1`、`expand_search_budget=1`、`rewrite_budget=1`、`facet_enrich_budget=6`
  - 提供了 `remaining(field)` 和 `record_exhaustion(reason)` 方法
  - 它是 per-workflow 级预算，但当前 workflow 之间没有共享或继承预算
  - 证据：[budget_context.py:8-62](D:/javacode/hm-dianping/local_life_agent/planning/budget/budget_context.py#L8)
- `local_life_agent/planning/evidence/facet_budget.py`
  - 已有 facet 级预算控制（`FacetBudgetPlan`）
  - 证据：[facet_budget.py:21-43](D:/javacode/hm-dianping/local_life_agent/planning/evidence/facet_budget.py#L21)
- `local_life_agent/domain/schemas.py`
  - `ExecutionPlan` 里已经混入了 `timeout_policy`、`degradation_policy`、`facet_budget_plan`
  - 证据：[schemas.py:1018-1019](D:/javacode/hm-dianping/local_life_agent/domain/schemas.py#L1018)
- **replan/retry 计数器在 SessionState**：`SessionState.replan_counters`（含 `expand_search`、`replan_evidence`、`rewrite`）在 `state.py:136-140`，计数器跨轮持久化，不是 GraphState 级预算
  - 证据：[state.py:136-140](D:/javacode/hm-dianping/local_life_agent/domain/state.py#L136)

### 1.4 现状风险

- `plan_evidence_with_llm()` 可以直接返回 `ExecutionPlan`
- 当前执行器不会按 DAG 拓扑执行
- 同一 `cache_key` 的并发请求没有 single-flight
- 预算、缓存、降级散落在多个层，缺少统一策略对象

证据：

- `[core/execution_core.py](D:/javacode/hm-dianping/local_life_agent/core/execution_core.py)`
- `[tool_batch_executor.py](D:/javacode/hm-dianping/local_life_agent/planning/evidence/tool_batch_executor.py)`
- `[gateway.py](D:/javacode/hm-dianping/local_life_agent/tools/gateway.py)`
- `[evidence_cache.py](D:/javacode/hm-dianping/local_life_agent/planning/evidence/evidence_cache.py)`
- `[evidence_builder.py](D:/javacode/hm-dianping/local_life_agent/planning/evidence/evidence_builder.py)`
- `[budget_context.py](D:/javacode/hm-dianping/local_life_agent/planning/budget/budget_context.py)`

## 2. 目标执行模型

### 2.1 核心原则

- LLM / Planner 只输出逻辑计划
- `ToolPlanCompiler` 负责把逻辑计划编译成受控 `ExecutionPlan.stages` / `SubTaskDAG`
- `PlanValidator` 负责 DAG 合法性
- `StageToolExecutor` 负责按拓扑顺序执行已验证 DAG
- Router 只选择 workflow，不负责解析或执行 DAG

### 2.2 `StageToolExecutor` 责任边界

`StageToolExecutor` 不是“又一个 batch executor”，它应该只做以下事情：

1. 读取已验证的 `ExecutionPlan`
2. 将 `stages` 解析成可执行拓扑层
3. 在同一 stage 内并行执行 `depends_on` 已满足的节点
4. 对同 `cache_key` 的并发节点做 single-flight
5. 处理 required / optional 节点失败策略
6. 输出可观测 trace，而不是直接拼自然语言

### 2.2.1 `StageToolExecutor` 完整执行语义

`StageToolExecutor` 不是"又一个 batch executor"，它的执行语义应严格遵循以下算法：

```text
StageToolExecutor.execute(plan: ExecutionPlan) → ToolResultSet:

1. VALIDATE DAG ACYCLIC
   对 plan.stages 中的所有 tool_calls，验证 depends_on 引用图中不存在环
   环检测算法：DFS-based topological sort，检测 back edge
   有环 → 抛出 ExecutionPlanError，不执行任何工具

2. TOPOLOGICAL SORT
   对依赖图做拓扑排序，输出按依赖顺序排列的 node 列表
   同一 layer 内的节点无依赖关系（可并行）
   Kahn's algorithm: 入度 0 的节点优先处理

3. BUILD READY_QUEUE
   ready_queue ← 所有 depends_on 已全部完成的节点（初始 = 入度 0 节点）
   completed ← ∅
   failed ← ∅

4. STAGE-GATED PARALLEL EXECUTION
   WHILE ready_queue 非空:
     group ← ready_queue 中 max_parallelism 约束下的可并行子集
     对 group 内的每个节点并行执行（asyncio.gather + Semaphore）
     约束条件:
       - 同 stage.depends_on 层内按 stage.max_parallelism 限制并发数
       - 全局不超过 ExecutionBudget.max_parallel_workers
       - 同 cache_key 的节点走 single-flight（只发起一次真实调用）

5. REQUIRED NODE FAILURE HANDLING
   IF 节点.required == true AND 节点执行失败:
     根据节点.degrade_policy 处理:
       - "fallback"   → 调用预注册的 fallback handler，结果标记 degraded
       - "clarify"    → 终止当前 workflow，进入澄清流程
       - "degrade"    → 跳过该节点，结果标记 failed，继续执行
       - 未定义       → 抛出 ExecutionError（保守失败）
     degrade_policy 未命中指定策略时不得静默失败

6. OPTIONAL NODE FAILURE HANDLING
   IF 节点.required == false AND 节点执行失败:
     不阻断主链路
     记录 failed_facets 和 unknown_facets
     该 facet 在 EvidencePack 中标记为 unavailable

7. DEPENDENT NODE FAILURE CASCADE
   IF 节点 A 失败（required 或 optional）:
     依赖 A 的节点 B 的处理方式取决于 B.degrade_policy:
       - "skip"       → 跳过 B，标记为 skipped
       - "degrade"    → 降级执行 B（如用缓存/近似值）
       - "fallback"   → 执行 B 的 fallback handler
       - 未定义且 A 是 required → B 被级联跳过
       - 未定义且 A 是 optional → B 正常执行

8. AGGREGATION
   所有节点的执行结果（success / degraded / skipped / failed）进入 ToolResultSet
   ToolResultSet 包含:
     - results: dict[node_id, ToolResult]
     - failed_nodes: list[node_id]
     - degraded_nodes: list[node_id]
     - skipped_nodes: list[node_id]
     - cache_hits: int
     - total_nodes: int
     - total_latency_ms: int
```

**与当前 `BatchToolExecutor` 的对比**：

| 维度 | 当前 BatchToolExecutor | 目标 StageToolExecutor |
|---|---|---|
| 执行模式 | asyncio.gather 平铺并发 | 按拓扑层分级调度 |
| depends_on | 不理解 | 严格按 depends_on 排序 |
| required/optional | 混同处理 | 严格区分 |
| degrade_policy | 无 | 每节点可配置 |
| single-flight | 无 | cache_key 级别去重 |
| 级联失败 | 无 | 依赖链感知 |
| 输出 | 平铺 list | ToolResultSet（含 trace） |

### 2.3 节点级契约

每个工具节点至少应具备：

```python
ToolCallSpec:
    call_id: str
    tool_name: str
    args: dict
    depends_on: list[str]
    required: bool
    timeout_ms: int | None
    retry_policy: str | dict | None
    degrade_policy: str | dict | None
    cache_key: str | None
    group_id: str | None
    max_parallelism: int | None
```

其中：

- `depends_on` 决定拓扑顺序
- `cache_key` 决定是否复用真实工具结果
- `required` 决定失败是否阻断主链路
- `degrade_policy` 决定失败进入 fallback / clarify / degrade 的方式

## 3. 缓存设计

### 3.1 缓存分层

建议至少分成两层：

1. `ToolResultCache`
   - 缓存单个真实工具调用结果
   - 目标：避免同店同 facet 的重复调用
2. `EvidenceCache`
   - 缓存证据构建结果
   - 目标：避免重复构建 evidence pack

### 3.2 `ToolResultCache` 的 key

`ToolCallCacheKey` 建议由以下部分组成：

- `tool_name`
- `normalized_args`
- `resolved_shop_id`
- `location_context`
- `facet`
- `freshness_bucket`
- `cache_scope`

**与现有 `EvidenceCache` key 的区别**：现有的 `EvidenceCache` key 是 `(cache_scope, sha256(fingerprint)[:16])`，且 cache_scope 通过 `normalize_cache_scope()` 归一化（`evidence_cache.py:23-31`）。`ToolResultCache` 的 key 应更细粒度到单工具调用级别，语义上区分 `(tool_name, shop_id, facet)` 三元组。

证据：[evidence_cache.py:23-36](D:/javacode/hm-dianping/local_life_agent/planning/evidence/evidence_cache.py#L23)

### 3.3 single-flight

同一个 `cache_key` 被多个并发 worker / stage 命中时：

- 只允许一个真实工具请求在飞行中
- 其它请求等待同一结果
- 避免同一家店的券 / 营业 / 距离被多次重复查

### 3.4 TTL / freshness

建议按工具语义设置 TTL。当前代码中 `EvidenceCache` 没有任何 TTL 或 freshness 机制（纯内存、永不过期），因此 TTL 是全新设计：

- **营业状态**（`check_open_status`）：短 TTL（~60s），营业状态可能随时变化
- **距离 ETA**（`get_distance_eta`）：短 TTL（~120s），距离+路况会变化
- **优惠券**（`get_coupon_list`）：中 TTL（~300s），券可能被领完
- **团购**（`get_deal_list`）：中 TTL（~300s）
- **店铺基础信息**（`get_shop_detail`）：较长 TTL（~600s）
- **评价摘要**（`get_shop_review_summary`）：较长 TTL（~600s）
- **搜索**（`search_shops`）：中长 TTL（~300s），搜索结果会随实时数据变化

**与现有 freshness 概念的关系**：`EvidenceItem` 已有 `freshness_class`、`ttl_seconds`、`observed_at_ms`、`is_stale` 字段定义（`schemas.py:1091-1095`），但这些字段目前没有被系统性地用于缓存过期判断。TTL 设计可以复用这些已有字段语义。

证据：[schemas.py:1089-1095](D:/javacode/hm-dianping/local_life_agent/domain/schemas.py#L1089)

### 3.5 当前实现的收敛点

- 现有 `EvidenceCache` 只能作为 evidence-level 缓存
- 现有 `BatchToolExecutor` 不负责去重
- 因此新增 `ToolResultCache` 时，应优先放在工具执行层或 gateway adapter 层，而不是埋在 planning 层

## 4. 预算设计

### 4.1 `ExecutionBudget`

建议统一管理：

- `max_llm_calls`
- `max_tool_calls`
- `max_parallel_workers`
- `max_total_latency_ms`
- `max_replan_rounds`
- `max_expand_rounds`
- `max_subtask_count`

### 4.2 与现有预算对象的关系

- `BudgetContext`（[budget_context.py:8-62](D:/javacode/hm-dianping/local_life_agent/planning/budget/budget_context.py#L8)）可以继续承载运行时剩余预算，其默认值（`tool_round_budget=2`、`retry_budget=1`、`expand_search_budget=1`）可作为新 `ExecutionBudget` 的基线参考
- `FacetBudgetPlan`（[facet_budget.py:21-43](D:/javacode/hm-dianping/local_life_agent/planning/evidence/facet_budget.py#L21)）可以继续承载 facet 层预算
- `SessionState.replan_counters`（[state.py:136-140](D:/javacode/hm-dianping/local_life_agent/domain/state.py#L136)）中的计数器目前跨轮持久化，需要迁入 `ExecutionBudget` 以避免跨轮污染
- 新的 `ExecutionBudget` 应该是顶层统一预算契约，按 workflow 种类预设不同的预算配额

### 4.3 预算优先级

1. 先校验预算是否足以执行当前 workflow
2. 再把预算传给 compiler / validator / executor
3. 执行中只允许在预算边界内 degrade，不允许静默超支

## 5. 失败与降级

### 5.1 required 节点失败

required 节点失败后，必须走明确降级：

- `fallback`
- `clarify`
- `degrade`

不能只返回一个空的“成功结果”。

### 5.2 optional 节点失败

optional 节点失败不能阻断主链路，但必须记录：

- `failed_facets`
- `unknown_facets`
- `degrade_reason`

### 5.3 与当前执行 review 的衔接

当前 `execution_review_subgraph` 已经有 retry / fallback / clarify / expand_search 的路由影子，但这些路径还不是 DAG 执行器的一部分：

- `_h_evidence_review`（[execution_review_subgraph.py:244-292](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/execution_review_subgraph.py#L244)）返回 `REPLAN_EVIDENCE`、`EXPAND_SEARCH`、`CLARIFY`、`DEGRADE_ANSWER`、`FALLBACK` 等路由信号
- `_h_decision_review` 的 `next_action`（[execution_review_subgraph.py:57-103](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/execution_review_subgraph.py#L57)）决定是 retry、expand_search、fallback 还是 proceed
- retry/expand 的计数器通过 `increment_replan_evidence` / `increment_expand_search`（[replan_policy.py:133-148](D:/javacode/hm-dianping/local_life_agent/planning/policies/replan_policy.py#L133)）写入 `SessionState`

证据：

- `[execution_review_subgraph.py:57-103](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/execution_review_subgraph.py#L57)`

## 6. DAG Trace 设计

### 6.1 当前 trace 现状

当前可观测性基础设施：
- `trace_spans` 字段已存在于 `GraphState`（[graph_state.py:187](D:/javacode/hm-dianping/local_life_agent/domain/graph_state.py#L187)），使用 `Annotated[list, add]` 做列表追加
- `dispatch_tool_call` 记录工具调用的 `[TOOL_CALL]` 和 `[TOOL_RESULT]` 日志（[gateway.py:275-321](D:/javacode/hm-dianping/local_life_agent/tools/gateway.py#L275)）
- `event_log` 字段（[graph_state.py:185](D:/javacode/hm-dianping/local_life_agent/domain/graph_state.py#L185)）可记录事件序列
- 但当前没有一个统一的"从路由→计划→执行→证据→决策→回答"的全链路 trace schema

### 6.2 节点级 trace（目标设计）

每个节点至少记录：

### 6.2 stage 级 trace

每个 stage 至少记录：

- 并行节点数
- 开始时间
- 结束时间
- stage 耗时

### 6.3 DAG 总览 trace

总览必须包含：

- DAG 总耗时
- 工具调用次数
- cache 命中率
- 失败节点列表
- 降级原因列表

## 7. Request Coalescing / Single-Flight 设计

### 7.1 问题

多个 worker / stage 同时请求同一个 `cache_key`（如同一家店的券列表）时，当前每个请求都发起一次真实工具调用。

### 7.2 设计

1. **SingleFlight key** = `ToolCallCacheKey`（`tool_name` + `normalized_args` + `shop_id` + `facet`）
2. 第一个请求发起真实调用，后续请求等待同一 `asyncio.Future`
3. 结果返回时，所有等待者同时获得结果
4. 使用 `asyncio.Future` 机制实现：

```python
class SingleFlightExecutor:
    _in_flight: dict[str, asyncio.Future] = {}
    
    async def execute(self, cache_key: str, tool_call: ToolCallSpec) -> Any:
        if cache_key in self._in_flight:
            # 等待已有请求
            return await self._in_flight[cache_key]
        
        future = asyncio.Future()
        self._in_flight[cache_key] = future
        try:
            result = await self._real_execute(tool_call)
            future.set_result(result)
            return result
        except Exception as e:
            future.set_exception(e)
            raise
        finally:
            del self._in_flight[cache_key]
```

### 7.3 与现有工具执行层的集成

- `StageToolExecutor` 内部包装 `SingleFlightExecutor`
- `BatchToolExecutor` 保持为底层原语（不负责去重）
- `ToolResultCache` 提供缓存查询，`SingleFlightExecutor` 提供并发去重

---

## 8. Workflow 级 ExecutionBudget 配额表

### 8.1 配额设计

| 预算项 | single_shop_fact | recommendation | comparison | complex_orchestrator |
|---|---|---|---|---|
| max_llm_calls | 0~1 | 1~3 | 2~4 | 3~6 |
| max_tool_calls | 1~3 | 5~15 | N shops x facets | subtask aggregate |
| max_replan_rounds | 0 | 1 | 1 | per subtask |
| max_expand_rounds | 0 | 1 | 0 | 0 |
| max_parallel_workers | 1 | 1 | 1 | 3~5 |
| max_subtask_count | N/A | N/A | N/A | 5~8 |
| max_total_latency_ms | 2000 | 8000 | 10000 | 15000 |

### 8.2 配额使用规则

1. 每个 workflow dispatch 创建独立的 `ExecutionBudget`
2. 超过 `max_llm_calls` 时，后续 LLM 调用降级为 deterministic
3. 超过 `max_tool_calls` 时，后续工具调用降级为 cache-only
4. 超过 `max_replan_rounds` 时，跳过 replan 直接 degrade
5. 超过 `max_parallel_workers` 时，多余 worker 排队等待

---

## 9. Retry/Replan 计数器迁移方案

### 9.1 问题

当前计数器在 `SessionState.replan_counters`（`state.py:136-140`），跨轮持久化。

### 9.2 迁移目标

| 当前 | 目标 |
|---|---|
| `SessionState.replan_counters` | `ExecutionBudget`（在 `GraphState` 中） |
| 跨轮持久化 | 每轮/每次 workflow dispatch 重置 |
| 隐式继承 | 显式重置 |

### 9.3 迁移步骤

1. **Phase B**: 在 `GraphState` 中新增 `ExecutionBudget` 字段
2. **Phase C**: 在 `workflow_runner` dispatch 时初始化 `ExecutionBudget`
3. **Phase D-E**: 将 `replan_policy.py` 中的 `increment_replan_evidence()` / `increment_expand_search()` 改为读写 `ExecutionBudget`
4. **Phase F-G**: 废弃 `SessionState.replan_counters`（保留兼容读，不再写）
5. **Phase H**: 移除 `SessionState.replan_counters` 的所有写入

### 9.4 兼容方案

```python
# 过渡期：同时支持新旧两个位置
def get_replan_counter(key: str, state: GraphState) -> int:
    if state.execution_budget:
        return state.execution_budget.remaining(key)
    return state.session_state.replan_counters.get(key, 0)
```

---

## 10. DAG Trace 完整设计

### 10.1 WorkflowTrace（workflow 级）

```python
class WorkflowTrace:
    workflow_kind: WorkflowKind
    entry_node: str
    start_time_ms: int
    end_time_ms: int
    nodes_visited: list[str]    # 经过的节点路径
    llm_calls: int
    tool_calls: int
    total_latency_ms: int
```

### 10.2 Per-Node Trace（节点级）

```python
class NodeTrace:
    node_id: str
    tool_name: str
    depends_on: list[str]
    status: str  # "pending" / "running" / "success" / "failed" / "degraded" / "cached"
    latency_ms: int | None
    cache_hit: bool
    cache_key: str | None
    error: str | None
    degrade_reason: str | None
    start_time_ms: int
    end_time_ms: int
```

### 10.3 Per-Stage Trace（stage 级）

```python
class StageTrace:
    stage_id: str
    parallel_nodes: int
    start_time_ms: int
    end_time_ms: int
    stage_latency_ms: int
    tool_call_count: int
    cache_hit_count: int
    cache_hit_rate: float
    failed_nodes: list[str]
    degraded_nodes: list[str]
```

### 10.4 与当前 trace 基础设施的集成

- 复用 `GraphState.trace_spans`（`graph_state.py:187`）的 `Annotated[list, add]` 追加模式
- 新增 `GraphState.workflow_trace: list[WorkflowTrace]`
- 新增 `GraphState.reduce_trace: list[ReduceTrace]`
- `dispatch_tool_call`（`gateway.py:275-321`）补充 `node_id`、`cache_hit`、`degrade_reason` 字段

---

## 11. 从现状到目标的迁移建议

1. 先把现有 `ExecutionPlan` 中的 `stages` 作为输入约束冻结
2. 再新增 `ToolResultCache` 和 single-flight
3. 然后引入 `StageToolExecutor`
4. 再把 replan 计数器迁入 ExecutionBudget
5. 最后把 `BatchToolExecutor` 收缩成底层原语，不再承担上层调度

