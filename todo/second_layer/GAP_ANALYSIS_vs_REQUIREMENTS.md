# 第二层现有文档 vs 设计需求差距分析

> 分析日期：2026-07-05
> 分析范围：`todo/second_layer/` 下全部 5 个现有文件
> 对比基准：用户完整的设计需求文档（共 10 个文档、22 个问题点、15 个 TODO_ADD_TEST、7 个 workflow 设计等）

---

## 一、文件级覆盖率

| 需求文档 | 现有文件 | 覆盖率 | 状态 |
|---|---|---|---|
| 01_second_layer_fact_baseline.md | `01_second_layer_fact_baseline.md` | ~70% | ⚠️ 有覆盖但缺关键内容 |
| 02_second_layer_problem_analysis.md | `02_second_layer_problem_analysis.md` | ~40% | ⚠️ P0 问题完全不同 |
| 03_second_layer_target_architecture.md | `03_second_layer_solution_plan.md` 内容不匹配 | ~0% | ❌ 文件名不对，内容是 DAG 编译方案而非架构 |
| 04_second_layer_workflow_design.md | ❌ 不存在 | 0% | ❌ 完全缺失 |
| 05_second_layer_contract_design.md | `04_second_layer_contract_design.md` | ~50% | ⚠️ 合同集不同，缺关键合同 |
| 06_second_layer_execution_and_cache_design.md | ❌ 不存在 | 0% | ❌ 完全缺失 |
| 07_second_layer_map_reduce_design.md | ❌ 不存在 | 0% | ❌ 完全缺失 |
| 08_second_layer_review_ranking_budget_design.md | ❌ 不存在 | 0% | ❌ 完全缺失 |
| 09_second_layer_migration_plan.md | `03_second_layer_solution_plan.md` 部分覆盖 | ~30% | ⚠️ 只覆盖了 DAG 编译阶段 |
| 10_second_layer_test_plan.md | `05_second_layer_test_plan.md` | ~40% | ⚠️ 只有 5 个 TODO_ADD_TEST，需求 15 个 |

**总体文件覆盖率：10 个需求文档中，2 个基本覆盖、3 个部分覆盖、5 个完全缺失。**

---

## 二、逐项差距详情

### 2.1 `01_second_layer_fact_baseline.md` 差距

| 需求项 | 现有覆盖 | 差距说明 |
|---|---|---|
| 第二层真实调用链 | ✅ 已覆盖 | 有调用链图和各节点行号引用 |
| 每个节点读写的关键 state 字段 | ⚠️ 部分覆盖 | 提到了 `GraphState` 字段组，但没有做**逐节点读/写矩阵**。例如 `_h_goal_planner` 写了什么字段、读了什么字段没有逐项列出 |
| 当前注册的 workflow 名称/entry_node/handler | ⚠️ 部分覆盖 | 提到了 `deterministic_tool_workflow` 和 `exploration_planning_workflow`，但没有给出完整的 workflow registry 矩阵（全部 5 个 workflow 的 name/entry_node/handler/is_real） |
| _routes.py 在第二层中的真实路由逻辑 | ❌ 未覆盖 | 现有文档完全没有分析 `_routes.py` 中 `_route_workflow_runner`、`_route_decision_review`、`_route_evidence_review` 等关键路由函数 |
| planning_subgraph 内部节点和职责 | ✅ 已覆盖 | 有 6 个步骤的调用链 |
| execution_review_subgraph 内部节点和职责 | ✅ 已覆盖 | 有 6 个步骤的调用链 |
| 工具执行模式 | ✅ 已覆盖 | 指出是 `asyncio.gather` 批处理，非 DAG |
| EvidencePack/DecisionPlan/GoalPlan 真实字段 | ⚠️ 部分覆盖 | 覆盖了 `ExecutionPlan`、`DecisionPlan`、`ToolCallSpec`，但缺少 `EvidencePack` 完整字段描述（~40个字段）、`GoalPlan` 字段描述 |
| review/retry/fallback/expand_search 真实逻辑 | ⚠️ 部分覆盖 | 提到 replan 计数器和 retry，但**缺少 expand_search 清除 filters 的关键事实**（已确认代码 `planning_subgraph.py:1319` 会清空 `relaxed.filters = {}`） |
| 当前缺失能力 | ✅ 已覆盖 | 列出了 `ToolPlanCompiler`、`SubTaskDAG`、`StageToolExecutor` 等 |

### 2.2 `02_second_layer_problem_analysis.md` 差距

用户的 P0 问题（8 个）与现有文档的 P0 问题完全不同：

| 用户要求的 P0 问题 | 现有文档是否覆盖 | 状态 |
|---|---|---|
| P0-1. 轻重链路未分层 | ❌ 未覆盖 | 现有 P0 关注的是"LLM 直接输出 ExecutionPlan" |
| P0-2. deterministic_tool 可能过轻 | ❌ 未覆盖 | 没有将"简单事实 query 绕过工具证据链"作为风险分析 |
| P0-3. orchestration_router_shadow 命名与真实执行权不一致 | ❌ 未覆盖 | 现有文档认为 shadow 是"纯写日志的 Phase 4 节点"，未讨论命名和实际影响力矛盾 |
| P0-4. _route_workflow_runner 隐藏路由判断 | ⚠️ 部分覆盖 | 有"Router 不是纯 Router"的分析，但没有专门针对 `_route_workflow_runner` (文件 `_routes.py:311-320`) 中 `response_mode == comparison` 进入 planning 的风险 |
| P0-5. expand_search 放宽策略过粗（清空 filters） | ❌ **已确认存在的风险** | 现有文档未提及。真实代码 `planning_subgraph.py:1319` 证实 `relaxed.filters = {}` 清空了所有过滤条件 |
| P0-6. retry/replan 计数放在 SessionState 跨轮污染 | ❌ **已确认存在的风险** | 现有文档未提及。`SessionState.replan_counters` (state.py:136-140) 确认 counters 在 SessionState，跨轮持久化 |
| P0-7. 推荐排序权威不清 | ❌ 未覆盖 | 没有讨论 RankingPolicy 是否由 LLM 主导 |
| P0-8. MapReduce 缺少结构化 reducer 契约 | ❌ 未覆盖 | 完全没有 MapReduce 分析 |

现有文档 P0 内容（LLM 输出直接当执行计划、执行器不懂 DAG、router 不纯、validator 缺口、无 DAG trace）虽然也是有效的 P0 问题，但只覆盖了用户需求的 1/8。

### 2.3 `03_second_layer_solution_plan.md` vs 需求 03+09 差距

| 用户需求 | 差距 |
|---|---|
| **03 目标架构**：7 个 workflow 的职责说明 | ❌ 完全缺失。现有文件是"分阶段升级方案"，不是目标架构 |
| 简单/中等/复杂/超复杂 query 分层策略 | ❌ 未设计 |
| 7 个 workflow 各自职责和边界 | ❌ 未设计 |
| 共享能力包（TargetResolver、RankingPolicy 等） | ❌ 未设计 |
| **09 迁移计划**：Phase A-J 渐进式计划 | ❌ 只有 6 个 Phase，且只覆盖 DAG 编译相关 |
| Phase A（事实冻结）、Phase F（RankingPolicy）、Phase G（exploration upgrade）、Phase H（complex_orchestrator）、Phase I（收缩旧 planning）、Phase J（回归验收） | ❌ 全部缺失 |

### 2.4 `04_second_layer_contract_design.md` vs 需求 05 差距

| 用户要求的合同 | 现有覆盖 | 差距 |
|---|---|---|
| TaskComplexity | ❌ 缺失 | 现有文档没有设计 task 复杂度分层 |
| WorkflowKind | ❌ 缺失 | 没有 workflow 枚举/类型定义 |
| ReviewPolicy | ❌ 缺失 | 只有 `NextAction` 枚举，没有完整的 ReviewPolicy |
| ExecutionBudget | ✅ 部分覆盖 | 有 `ExecutionBudget` 字段，但没有按 workflow 区分预算 |
| ExpandSearchPolicy | ❌ 缺失 | 没有 expand_search 的策略对象 |
| RankingPolicy | ⚠️ 已有但不完整 | `RankingPolicy` 已经存在于 `domain.facets`，但现有文档未分析其真实字段 |
| ToolCallCacheKey | ❌ 缺失 | 没有 cache key 的结构设计 |
| ToolResultCacheEntry | ❌ 缺失 | 没有缓存条目设计 |
| EvidenceCacheEntry | ❌ 缺失 | 没有证据缓存条目设计 |
| SubTask / SubTaskDAG | ❌ 缺失 | 现有的 `SubTask` 设计（41-47行）只有逻辑计划级，不是 DAG 级 |
| WorkerState / WorkerResult | ❌ 缺失 | 完全没有 MapReduce 相关合同 |
| DecisionFragment | ❌ 缺失 | 没有决策片段的概念 |
| GlobalEvidencePack | ❌ 缺失 | 没有全局证据包的概念 |
| EvidenceConflict / ConflictResolution | ❌ 缺失 | 没有冲突解决相关合同 |
| FinalDecisionPlan | ❌ 缺失 | 没有最终决策计划的概念 |
| WorkflowTrace / ReduceTrace | ❌ 缺失 | 现有 `ExecutionDagTrace` 只覆盖单 DAG 执行，不覆盖 workflow 级和 reduce trace |
| ToolInvocationRecord | ✅ 已覆盖 | 有设计 |

### 2.5 `05_second_layer_test_plan.md` vs 需求 10 差距

| 用户要求的测试场景 | 现有覆盖 | 差距 |
|---|---|---|
| 场景 1-25（共 25 个验收标准） | ⚠️ 覆盖约 10 个 | 缺少场景 11-25 |
| TODO_ADD_TEST 数量 | 5 个 vs 需求 15 个 | 缺少 10 个 TODO_ADD_TEST |
| 缺少的 TODO_ADD_TEST 包括： | | |
| `test_second_layer_single_shop_fact_workflow.py` | ❌ | 未列出 |
| `test_second_layer_review_policy.py` | ❌ | 未列出 |
| `test_second_layer_ranking_policy.py` | ❌ | 未列出 |
| `test_second_layer_expand_search_policy.py` | ❌ | 未列出 |
| `test_second_layer_execution_budget.py` | ❌ | 未列出 |
| `test_second_layer_complex_orchestrator.py` | ❌ | 未列出 |
| `test_second_layer_map_reduce_reducer.py` | ❌ | 未列出 |
| `test_second_layer_conflict_resolver.py` | ❌ | 未列出 |
| `test_second_layer_worker_state_isolation.py` | ❌ | 未列出 |
| `test_second_layer_trace_contract.py` | ❌ | 未列出 |
| `test_second_layer_latency_budget.py` | ❌ | 未列出 |
| 缺少的验收标准包括： | | |
| RankPolicy 能过滤硬约束并按软偏好排序 | ❌ | 未覆盖 |
| ExpandSearchPolicy 不清空 hard constraints | ❌ | 未覆盖 |
| retry/replan counter 不跨轮污染 | ❌ | 未覆盖 |
| MapReduce worker 只输出 WorkerResult | ❌ | 未覆盖 |
| 冲突事实被记录为 EvidenceConflict | ❌ | 未覆盖 |
| 无法裁决的冲突标记 unknown | ❌ | 未覆盖 |
| trace 包含完整 span 链 | ❌ | 未覆盖 |
| latency/cost benchmark | ❌ | 未覆盖 |

---

## 三、关键真实代码事实（供后续文档修正使用）

以下事实是在代码调研中确认的，现有文档未准确描述：

### 3.1 expand_search 清空 filters（确认代码）

```python
# planning_subgraph.py:1319
relaxed.filters = {}
relaxed.sort_by = []
```

这会丢弃用户的所有硬约束（品类、位置、预算、营业状态等）。现有文档未记录此风险。

### 3.2 retry/replan 计数在 SessionState

```python
# state.py:136-140
replan_counters: dict[str, int] = Field(default_factory=lambda: {
    "expand_search": 0,
    "replan_evidence": 0,
    "rewrite": 0,
})
```

跨轮持久化在 `SessionState`，当前 turn 计数不受重置，后续 query 可能继承已耗尽计数器。

### 3.3 workflow registry 完整矩阵（共 5 个）

```python
# workflow_registry.py:152-201
1. discovery_decision → handler=_dispatch_discovery_decision → entry_node="planning_subgraph" → 真实注册
2. direct_response → handler=run_direct_response_workflow → entry_node="response_subgraph" → 真实注册
3. deterministic_tool → handler=run_deterministic_tool_workflow → entry_node="response_subgraph" → 真实注册
4. clarification_fallback → handler=run_clarification_fallback_workflow → entry_node="response_subgraph" → 真实注册
5. exploration_planning → handler=run_exploration_planning_workflow → entry_node="response_subgraph" → 真实注册
```

注意：
- `discovery_decision` 是唯一 entry_node 为 `planning_subgraph` 的 workflow，其他 4 个都是 `response_subgraph`
- `discovery_decision` 的 handler `_dispatch_discovery_decision` 只是返回一个 dispatch patch，实际仍然走到 `planning_subgraph`

### 3.4 _route_workflow_runner 的三重判定

```python
# _routes.py:311-320
if workflow_name == "discovery_decision" or workflow_callable == "planning_subgraph" or response_mode == "comparison":
    return "planning_subgraph"
return "response_subgraph"
```

`response_mode == "comparison"` 会使比较 query 即使因某种原因丢失了 workflow_name 也仍然进入 planning_subgraph。这不是"纯路由"，是多层兜底。

### 3.5 orchestration_router_shadow 不改变路径但输出被消费

```python
# orchestration_router_shadow.py:20-79
# 它写入 workflow_name / response_mode / next_action
# workflow_runner 读取这些字段决定分发
```

shadow 的输出（特别是 `workflow_name` 和 `response_mode`）不是仅仅用于日志，而是被 `workflow_runner` 和 `_route_workflow_runner` 消费。

---

## 四、必须新增的文档

| 新文件 | 优先级 | 理由 |
|---|---|---|
| `03_second_layer_target_architecture.md` | P0 | 当前完全缺失，是整个方案的基础 |
| `04_second_layer_workflow_design.md` | P0 | 当前完全缺失，需要 7 个 workflow 的内部流程 |
| `06_second_layer_execution_and_cache_design.md` | P0 | 当前完全缺失，影响执行效率和成本 |
| `07_second_layer_map_reduce_design.md` | P0 | 当前完全缺失，复杂 query 的核心方案 |
| `08_second_layer_review_ranking_budget_design.md` | P0 | 当前完全缺失，决定了排序权威性和预算控制 |

### 必须增强的现有文档

| 文件 | 增强项 |
|---|---|
| `01_second_layer_fact_baseline.md` | 补充 _routes.py 路由逻辑、workflow registry 完整矩阵、state 字段逐节点读写矩阵、expand_search 清除 filters 事实、trace span 现状 |
| `02_second_layer_problem_analysis.md` | 补充用户的 8 个 P0 问题（基于真实代码验证的） |
| `03_second_layer_solution_plan.md` | 更名为 `09_second_layer_migration_plan.md`，补充 Phase A-J |
| `04_second_layer_contract_design.md` | 补充 TaskComplexity、WorkflowKind、ReviewPolicy 等缺失合同 |
| `05_second_layer_test_plan.md` | 补充 15 个 TODO_ADD_TEST、15 个验收标准 |

---

## 五、现有文档与代码偏差清单

| # | 现有文档声称 | 真实代码 | 偏差等级 |
|---|---|---|---|
| 1 | 文档称 LLM 直接输出 ExecutionPlan 为当前模式 | 真实代码 `evidence_planner.py:242-352` 确实如此，但文档未提及 `ToolIntentPlan`（schemas.py:1056-1067）作为 LLM-only 中间计划的存在 | 中 |
| 2 | 文档将 `orchestration_router_shadow` 描述为"只写日志不改变路径" | 真实代码中 shadow 写入 `workflow_name`、`response_mode`、`next_action`，这些字段被 `workflow_runner` 和 `_route_workflow_runner` 消费 | **高** |
| 3 | 文档说"workflow_runner 是真正分发器" | 真实代码中 `_route_workflow_runner` (`_routes.py:311-320`) 才是最终的 graph 路由，workflow_runner 只是 registry lookup + dispatch | 中 |
| 4 | 文档未提及 `expand_search` 清除 filters 的行为 | 真实代码 `planning_subgraph.py:1319` 证实 `relaxed.filters = {}` | **高** |
| 5 | 文档未提及 retry/replan 计数器跨轮污染风险 | 真实代码 `SessionState.replan_counters` 持久化在 SessionState，跨轮共享 | **高** |
| 6 | 文档称 `single_shop_fact_workflow` 是理想轻量路径 | 真实代码中不存在该名称，当前对应的是 `deterministic_tool_workflow` | 低（命名偏差） |
| 7 | 文档未分析 `_route_workflow_runner` 的三重判定 | 真实代码 `_routes.py:311-320` 中用 `workflow_name == "discovery_decision" or workflow_callable == "planning_subgraph" or response_mode == "comparison"` 决定路径 | 中 |

---

## 六、总结：下一步行动

### 紧急（P0）
1. 创建 `03_second_layer_target_architecture.md` — 7 个 workflow 的目标架构
2. 创建 `04_second_layer_workflow_design.md` — 7 个 workflow 的内部流程
3. 创建 `06_second_layer_execution_and_cache_design.md` — 执行器、缓存、TTL
4. 创建 `07_second_layer_map_reduce_design.md` — 复杂 query 的 MapReduce
5. 创建 `08_second_layer_review_ranking_budget_design.md` — 策略层

### 重要（P1）
6. 更新 `01_second_layer_fact_baseline.md` — 补充缺失内容
7. 更新 `02_second_layer_problem_analysis.md` — 补充用户的 8 个 P0 问题
8. 重命名 `03_second_layer_solution_plan.md` → `09_second_layer_migration_plan.md` 并扩展
9. 更新 `04_second_layer_contract_design.md` — 补充缺失合同
10. 更新 `05_second_layer_test_plan.md` — 补充测试

### 建议
11. 所有新增和修改完成后，做一次全量回归校验
12. 确保每个文档都标注对应的真实代码行号
