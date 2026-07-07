# 第二层渐进式迁移计划

本文件只描述迁移路线，不修改业务代码。原则是：先冻结事实，再切边界，再引入新契约，最后收缩旧实现。

> ⚠️ **优先级重排说明**：以下 10 个 Phase 按完整路线排列，但**首批实施**应聚焦 5 个最高优先级目标：
>
> | 优先级 | 目标 | 对应 Phase | 验收标准 |
> |---|---|---|---|
> | P0 | 单店事实工具稳定（当前 deterministic_tool 绕过 review 层） | **Phase C**（升级版） | 走确定性 evidence plan + tool execute，不走 LLM review |
> | P0 | 推荐排序不违反硬约束（RankingPolicy 可执行化） | **Phase F**（增强版） | HardConstraintFilter 排除不合条件店铺，_h_expand_search 不清空 filters |
> | P0 | 对比 winner 确定性选择（不靠 LLM 印象） | **Phase D+F** | comparison_matrix + ranking_policy 决定 winner，LLM 只做 trade-off 解释 |
> | P0 | 工具调用不重复（同轮同店同 facet 只查一次） | **Phase E**（优先） | ToolResultCache + single-flight 去重 |
> | P0 | Response 不绕过证据链 | **Phase C+J** | 每次 response 必须引用 EvidencePack，无证据字段标记 UNKNOWN |
> | **P2** | MapReduce / complex_orchestrator | **Phase H** | **第二批实施**，等前 5 项稳定后再启动 |
>
> 也就是说：**Phase C、E（部分）、F 应该优先启动**，Phase H 可以晚 1-2 个迭代周期。所有 Phase 仍按编号顺序推进，但投入资源按此优先级分配。

## Phase A：事实冻结与边界测试

### 目标

- 输出第二层真实调用链
- 输出 workflow registry 矩阵
- 输出 route 字段矩阵
- 输出 review / retry / fallback 矩阵
- 不改变业务逻辑

### 结合当前代码

重点冻结以下路径的 state 读写矩阵、route 字段矩阵、review/retry/fallback 矩阵：

- `orchestration_router_shadow`：[orchestration_router_shadow.py:20-79](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/orchestration_router_shadow.py#L20) — 写入 `workflow_name`、`response_mode`、`next_action` 等 10+ 个字段
- `workflow_runner`：[workflow_runner.py:97-291](D:/javacode/hm-dianping/local_life_agent/engine/workflow_runner.py#L97) — registry lookup + dispatch + fallback patch
- `planning_subgraph`：[planning_subgraph.py:253-1300](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/planning_subgraph.py#L253) — 1369 行的大子图，6 个内部节点
- `execution_review_subgraph`：[execution_review_subgraph.py:57-377](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/execution_review_subgraph.py#L57) — 5 个内部节点
- `deterministic_tool_workflow`：[deterministic_tool_workflow.py:1046-1234](D:/javacode/hm-dianping/local_life_agent/engine/workflows/deterministic_tool_workflow.py#L1046)
- `_route_workflow_runner`：[_routes.py:311-320](D:/javacode/hm-dianping/local_life_agent/engine/_routes.py#L311) — 三重判定路由，迁移时需要特殊处理

Phase A 的输出产物应至少包括：
| 产物 | 描述 |
|---|---|
| 真实调用链图 | Router → Shadow → Runner → Registry → workflow handler |
| workflow registry 矩阵 | 5 个 workflow 的 name/entry_node/handler/is_real |
| route 字段读写矩阵 | 每个 route 节点写了什么 GraphState 字段 |
| review/retry/fallback 矩阵 | 每个 review 节点的 next_action → 路由目标 → 计数器行为 |

## Phase B：策略层先行

### 目标

- 新增 `ReviewPolicy`
- 新增 `ExecutionBudget`
- 新增 `ExpandSearchPolicy`
- 先不拆图，只让现有 planning_subgraph 可以读取策略

### 说明

当前已有散点能力可复用（详细证据见基线文档）：

| 现有能力 | 位置 | 作用 |
|---|---|---|
| `BudgetContext` | [budget_context.py:8-62](D:/javacode/hm-dianping/local_life_agent/planning/budget/budget_context.py#L8) | 运行时剩余预算（默认 tool_round=2） |
| `FacetBudgetPlan` | [facet_budget.py:21-43](D:/javacode/hm-dianping/local_life_agent/planning/evidence/facet_budget.py#L21) | facet 层预算控制 |
| `RankingPolicy` | [facets.py:102-105](D:/javacode/hm-dianping/local_life_agent/domain/facets.py#L102) | 排序策略（当前仅 3 字段） |
| `SessionState.replan_counters` | [state.py:136-140](D:/javacode/hm-dianping/local_life_agent/domain/state.py#L136) | 已有 retry/expand/rewrite 计数器 |
| config 全局上限 | [config.py:213-215](D:/javacode/hm-dianping/local_life_agent/config.py#L213) | MAX_EXPAND_SEARCH_ROUNDS=1, MAX_REPLAN_EVIDENCE_ROUNDS=1 |

Phase B 可以先做“策略统一读取”，不做结构大改。

## Phase C：升级 deterministic_tool → single_shop_fact_workflow

### 目标

- 单店事实查询也走工具证据链
- 减少不必要 LLM review
- 形成轻量 canonical path

### 兼容说明

- 当前仓库里对应能力实际叫 `deterministic_tool_workflow`（`workflow_registry.py:176-182`，entry_node="response_subgraph"），迁移期间应保留 `deterministic_tool` 作为 legacy alias 避免路由断裂
- 当前 `_route_workflow_runner`（[`_routes.py:311-320`](D:/javacode/hm-dianping/local_life_agent/engine/_routes.py#L311)）有三重路由判定：`workflow_name == "discovery_decision" or workflow_callable == "planning_subgraph" or response_mode == "comparison"`，如果 `deterministic_tool` 改名后仍有 `response_mode="comparison"` 的遗留状态，可能被重路由到 `planning_subgraph`——这是迁移必须处理的风险
- 当前 `deterministic_tool_workflow` 的代码（[deterministic_tool_workflow.py:1046-1234](D:/javacode/hm-dianping/local_life_agent/engine/workflows/deterministic_tool_workflow.py#L1046)）已经走工具证据链（ToolBatchExecutor + build_evidence），升级单店事实 workflow 时要确保不倒退这个能力

## Phase D：拆 discovery_decision

### 目标

- 拆出 recommendation_decision_workflow
- 拆出 comparison_decision_workflow
- 保留 `discovery_decision` legacy alias 一段兼容期

### 结合当前代码

- 当前 `workflow_registry` 中 `discovery_decision` 是主链路 workflow 名，entry_node 指向 `planning_subgraph`，handler 是 `_dispatch_discovery_decision`（[workflow_registry.py:152-164](D:/javacode/hm-dianping/local_life_agent/engine/workflow_registry.py#L152)）
- `_dispatch_discovery_decision` 实际上并不执行工具，只是返回一个 dispatch patch，真实执行仍然在 `planning_subgraph`（[workflow_registry.py:139-149](D:/javacode/hm-dianping/local_life_agent/engine/workflow_registry.py#L139)）
- `_route_workflow_runner`（[`_routes.py:311-320`](D:/javacode/hm-dianping/local_life_agent/engine/_routes.py#L311)）的三重判定中，`workflow_name == "discovery_decision"` 和 `workflow_callable == "planning_subgraph"` 都会触发行 planning_subgraph 路由——拆分后需要处理这两个判定条件
- 当前 `planning_subgraph`（1369 行）内部已经包含推荐和对比两种路径的规划逻辑，拆到不同 workflow 时需要审慎提取共享组件

### 拆分解耦的关键风险

1. **`_route_workflow_runner` 的三重判定**（workflow_name / workflow_callable / response_mode）不能直接剥离，需要用 alias 兼容
2. **`planning_subgraph` 内部的 shared helpers**（`_normalize_distance_tool_calls`、`_resolve_recommendation_spec`、`_pending_candidate_targets` 等）需要提取成共享模块
3. **`LEGAL_WORKFLOW_NAMES`**（[workflow_registry.py:24-30](D:/javacode/hm-dianping/local_life_agent/engine/workflow_registry.py#L24)）目前只允许 5 个名称，需要先扩展命名空间

## Phase E：升级 ExecutionPlan.stages / StageToolExecutor

### 目标

- 从两阶段 search/follow-up 逐步升级 DAG / stage 执行
- 加 `ToolResultCache`
- 加 `EvidenceCache` 的单飞复用

### 结合当前代码

- 当前执行路径是两阶段手写顺序：先 `search_calls`，再 `remaining_specs`（[execution_review_subgraph.py:124-131](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/execution_review_subgraph.py#L124)），没有通用 stage 拓扑
- `ExecutionPlan.stages`（[schemas.py:948-961](D:/javacode/hm-dianping/local_life_agent/domain/schemas.py#L948)）已定义但执行器不使用——`_h_tool_execute` 直接读 `plan.tool_calls` 平铺执行
- `ToolResultCache` 不存在，需要全新实现
- 现有 `EvidenceCache`（[evidence_cache.py:47-93](D:/javacode/hm-dianping/local_life_agent/planning/evidence/evidence_cache.py#L47)）是 evidence-level 缓存，不是 tool-result-level
- 这一步是关键边界升级：从"平铺 batch 并发"升级到"按 stage/depends_on 拓扑执行"

## Phase F：增加 RankingPolicy 和 ExpandSearchPolicy

### 目标

- 推荐排序权威从 LLM 转为 hybrid ranking
- expand_search 不再清空 hard constraints

### 说明

这一步要优先收紧推荐与对比场景，不先动轻量事实 workflow。

## Phase G：升级 exploration_planning_workflow

### 目标

- 在当前真实能力基础上，增强多阶段本地生活规划能力
- 处理吃饭、逛街、咖啡、电影、长辈等组合规划

### 与当前代码的关系（重要更正）

**当前 `exploration_planning_workflow` 不是 response-only**。真实代码 `run_exploration_planning_workflow()`（[exploration_planning_workflow.py:840-1114](D:/javacode/hm-dianping/local_life_agent/engine/workflows/exploration_planning_workflow.py#L840)）已经是相当完整的 workflow：

| 步骤 | 函数 | 位置 |
|---|---|---|
| 子目标构建 | `_build_subgoals()` | 840-885 行 |
| 工具查询（search round） | `_tool_round_search()` | 926-930 行 |
| 工具扩搜（expand round） | `_tool_round_expand()` | 937-940 行 |
| 证据构建 | `build_evidence_pack_from_tool_results()` | 943-972 行 |
| 探索计划构建 | `_build_exploration_plan()` | 999-1006 行 |
| 回答计划 | `build_answer_plan_from_evidence()` | 1008-1012 行 |
| 验证器 | `verify_answer_plan()` | 1015 行 |
| 最终回答 | `_compose_final_response()` | 1014 行 |

但当前实现仍有局限：
- 工具调用仅两轮（search + expand），没有更多阶段的 DAG 调度
- 子目标之间没有跨阶段依赖协调（如"先吃饭再逛街"的时间衔接）
- 证据构建在当前 workflow 内完成，没有走 `execution_review_subgraph` 的完整证据/决策/review 链路
- 回答直接由 `_compose_final_response` 拼成自然语言，不是通过 `response_subgraph` 统一输出

**升级方向**：将 `exploration_planning_workflow` 从"自包含的伪独立 workflow"升级为使用共享能力包（`TargetResolver`、`EvidencePlanner`、`RankingPolicy` 等）的正式 workflow，并复用 `response_subgraph` 统一输出。

## Phase H：增加 complex_orchestrator_workflow（⚠️ 第二批实施）

> **第二批实施明确**：Phase H 是"第二阶段"能力，不在首批迭代内。先保证单店事实走稳、推荐不乱选、对比不选错 winner、工具不重复、response 不绕过证据之后，再启动此 Phase。

### 目标

- 只处理超复杂 query
- 引入 `SubTaskDAG`（当前不存在，需新设计）
- 引入 `WorkerResult`（当前不存在，需新设计）
- 引入 `EvidenceReducer` / `DecisionReducer` / `ConflictResolver`（当前不存在，需新设计）

### 依赖前提

- `LEGAL_WORKFLOW_NAMES`（[workflow_registry.py:24-30](D:/javacode/hm-dianping/local_life_agent/engine/workflow_registry.py#L24)）需要增加新 workflow 名称
- `_route_workflow_runner`（[`_routes.py:311-320`](D:/javacode/hm-dianping/local_life_agent/engine/_routes.py#L311)）需要增加新的路由分支
- 当前 `config.py` 中的 `MAX_EXPAND_SEARCH_ROUNDS=1`（[config.py:213](D:/javacode/hm-dianping/local_life_agent/config.py#L213)）和 `MAX_REPLAN_EVIDENCE_ROUNDS=1`（[config.py:215](D:/javacode/hm-dianping/local_life_agent/config.py#L215)）不足以支持复杂 orchestrator 的多轮子任务执行，需要增加 `MAX_SUBTASK_COUNT`、`MAX_PARALLEL_WORKERS` 等新配置

## Phase I：收缩旧 planning_subgraph

### 目标

- 将大 planning_subgraph 内部能力逐步拆成共享能力包
- 旧入口保留兼容，直到所有 workflow 稳定

### 收缩方向

当前 `planning_subgraph`（[planning_subgraph.py](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/planning_subgraph.py)）内部包含的职责及对应行号：

| 职责 | 函数 | 位置 |
|---|---|---|
| goal planning | `_h_goal_planner` | 253-483 行 |
| goal review | `_h_goal_review` | 493-535 行 |
| target resolve | `_h_target_resolve` | 539-590 行（外部 571-760） |
| evidence planner | `_h_evidence_planner` | 1138-1256 行 |
| plan validator | `_h_plan_validator` | 1259-1300 行 |
| expand search | `_h_expand_search` | 1304-1346 行 |
| 工具别名归一化 | `_normalize_distance_tool_calls` | 169-203 行 |

收缩方式：
- 每个职责提取为共享模块，保留原有函数签名兼容
- `planning_subgraph` 入口保留作为旧 workflow 的 dispatch 兼容层
- 所有新 workflow 直接调用共享模块，不走 `planning_subgraph`

## Phase J：最终回归与性能验收

### 目标

- 全量测试
- 复杂 query E2E
- latency benchmark
- cost benchmark
- trace 完整性检查

### 验收标准

| 验收项 | 具体指标 | 验证方式 |
|---|---|---|
| 简单 fact query 延迟 | 不显著慢于当前版本 | latency benchmark |
| 复杂 query 证据链完整性 | 不因拆分丢失任何工具结果 | E2E 回归测试 |
| trace 完整性 | 包含 router→workflow→planner→tool→evidence→review→decision→retry→fallback→reduce 每个 span | trace 合约测试 |
| LLM 调用成本 | 简单 query 不增加甚至减少 LLM 调用次数 | cost benchmark |
| regression | comparison/recommendation/single coupon/single shop multifacet 主链路不退化 | 全量回归测试 |

### 当前已有 benchmark 基线

现有性能测试可作为延迟和成本基线：

- `test_p10_experience_performance.py` — 已有确定性单店多 facet 批量调用的性能记录（[tests/test_p10_experience_performance.py](D:/javacode/hm-dianping/local_life_agent/tests/test_p10_experience_performance.py)）
- `test_p12_deadline_budget_freshness_ttl.py` — 已有截止时间、预算、freshness、TTL 测试（[tests/test_p12_deadline_budget_freshness_ttl.py](D:/javacode/hm-dianping/local_life_agent/tests/test_p12_deadline_budget_freshness_ttl.py)）

Phase J 应在这些基线基础上增加 `test_second_layer_latency_budget.py` 和 `test_second_layer_cost_benchmark.py` 专项测试。

---

## 补充 A：Phase A-J 详细 Checklist

### Phase A 实施文件清单

| 项目 | 内容 |
|---|---|
| **新增文件** | 无（纯文档分析，不产生代码文件） |
| **修改文件** | 无 |
| **Legacy alias 保留** | 所有现有 workflow 名称和路由保持不动 |
| **新增测试** | 无（可使用现有 test_phase2_routing_authority.py 验证路由不变） |
| **完成标准** | 调用链矩阵、registry 矩阵、route 字段矩阵、review/retry/fallback 矩阵全部输出，并与真实代码一致 |
| **回滚方式** | N/A（不修改代码，无回滚风险） |

### Phase A 详细 Checklist

- [ ] 输出第二层真实调用链：Router → Shadow → Runner → Registry → handler
- [ ] 输出 workflow registry 矩阵（5 个 workflow 的 name/entry_node/handler/is_real）
- [ ] 输出 `_route_workflow_runner` 三重判定路由矩阵
- [ ] 输出每个 route 节点的 state 字段读写矩阵
- [ ] 输出 review/retry/fallback 矩阵（每个 review 节点的 next_action → 路由目标 → 计数器行为）
- [ ] 输出 execution_review_subgraph 中 next_action（FINISH/REPLAN_EVIDENCE/EXPAND_SEARCH/CLARIFY/FALLBACK）到 `_routes.py` 路由目标的完整映射
- [ ] 冻结 expand_search 清空 filters 的事实（`planning_subgraph.py:1319`）
- [ ] 冻结 SessionState.replan_counters 跨轮污染事实（`state.py:136-140`）

### Phase B 实施文件清单

| 项目 | 内容 |
|---|---|
| **新增文件** | `domain/policies/review_policy.py`、`domain/policies/execution_budget.py`、`domain/policies/expand_search_policy.py` |
| **修改文件** | `planning_subgraph.py`（新增策略读取入口）、`domain/schemas.py`（新增策略字段） |
| **Legacy alias 保留** | 所有现有策略对象（`BudgetContext`、`FacetBudgetPlan`、`SessionState.replan_counters`）保持读兼容，逐步迁移 |
| **新增测试** | `test_second_layer_review_policy.py`、`test_second_layer_execution_budget.py` |
| **完成标准** | 3 个策略对象设计完毕、单测通过、现有 planning_subgraph 在不使用策略时行为不变 |
| **回滚方式** | 撤销新增策略代码，保留旧路由和旧预算计数 |

### Phase B 详细 Checklist

- [ ] 设计 ReviewPolicy 数据结构和默认值
- [ ] 设计 ExecutionBudget 数据结构和 workflow 级配额
- [ ] 设计 ExpandSearchPolicy 数据结构和放宽策略
- [ ] 在 planning_subgraph 中新增策略读取入口（不改变路由逻辑）
- [ ] 编写 ReviewPolicy / ExecutionBudget / ExpandSearchPolicy 的单元测试
- [ ] 验证现有 planning_subgraph 在读取策略后行为不变

### Phase C 实施文件清单

| 项目 | 内容 |
|---|---|
| **新增文件** | `engine/workflows/single_shop_fact_workflow.py`（封装现有 deterministic_tool 逻辑） |
| **修改文件** | `workflow_registry.py`（注册 `single_shop_fact_workflow`）、`_routes.py`（添加新 workflow 路由条件） |
| **Legacy alias 保留** | `deterministic_tool` 保留为 legacy alias，注册表新旧名称同时解析 |
| **新增测试** | `test_second_layer_single_shop_fact_workflow.py` |
| **完成标准** | 单店事实 query 走 `single_shop_fact_workflow`、必须查工具、必须生成 EvidencePack、不触发 LLM review |
| **回滚方式** | 切换 workflow_registry 入口回 `deterministic_tool`，移除新 workflow 名 |

### Phase C 详细 Checklist

- [ ] 确认 deterministic_tool_workflow 当前走工具证据链
- [ ] 确保单店事实 query 走工具证据链
- [ ] 减少不必要 LLM review（使用 deterministic evidence_review）
- [ ] 保留 deterministic_tool 作为 legacy alias
- [ ] 处理 `_route_workflow_runner` 中 `response_mode == "comparison"` 的重路由风险

### Phase D 实施文件清单

| 项目 | 内容 |
|---|---|
| **新增文件** | `engine/workflows/recommendation_decision_workflow.py`、`engine/workflows/comparison_decision_workflow.py`、`planning/candidate_spec_builder.py` |
| **修改文件** | `workflow_registry.py`（注册新 workflow 名）、`_routes.py`（扩展路由条件）、`planning_subgraph.py`（提取 shared helpers 为共享模块）、`domain/schemas.py`（扩展 `LEGAL_WORKFLOW_NAMES`） |
| **Legacy alias 保留** | `discovery_decision` 保留为 legacy alias，确保路由不中断 |
| **新增测试** | `test_second_layer_workflow_routing.py`（验证推荐/对比/单店 workflow 路由正确） |
| **完成标准** | 推荐和对比流程完全独立、regression 测试通过、路由不退化 |
| **回滚方式** | 切换 `_route_workflow_runner` 回旧的三重判定 + `discovery_decision` 入口 |

### Phase D 详细 Checklist

- [ ] 拆 discovery_decision 为 recommendation_decision_workflow + comparison_decision_workflow
- [ ] 保留 discovery_decision legacy alias（兼容期）
- [ ] 处理 `_route_workflow_runner` 中 `workflow_name == "discovery_decision"` 条件
- [ ] 处理 `_route_workflow_runner` 中 `workflow_callable == "planning_subgraph"` 条件
- [ ] 提取 planning_subgraph 内部 shared helpers 为共享模块
  - [ ] `_normalize_distance_tool_calls` → ToolPlanCompiler 或 gateway adapter
  - [ ] `_resolve_recommendation_spec` → CandidateSpecBuilder
  - [ ] `_pending_candidate_targets` → TargetResolver
- [ ] 扩展 `LEGAL_WORKFLOW_NAMES`（`workflow_registry.py:24-30`）

### Phase E 实施文件清单

| 项目 | 内容 |
|---|---|
| **新增文件** | `planning/compiler/tool_plan_compiler.py`、`execution/stage_tool_executor.py`、`execution/tool_result_cache.py`、`execution/single_flight_executor.py` |
| **修改文件** | `execution_review_subgraph.py`（使用 StageToolExecutor 替代 batch 执行）、`tools/gateway.py`（新增 cache 钩子和 single-flight 集成）、`domain/schemas.py`（补强 `ToolCallSpec`：`cache_key`、`degrade_policy`、`node_id` 字段） |
| **Legacy alias 保留** | `BatchToolExecutor` 保留为底层原语，不删除 |
| **新增测试** | `test_second_layer_stage_executor.py`、`test_second_layer_tool_result_cache.py`、`test_second_layer_plan_compiler.py`、`test_second_layer_dag_trace.py` |
| **完成标准** | DAG 拓扑排序 + stage 级并行 + single-flight 通过单测；现有两阶段 search/follow-up 路径不退化 |
| **回滚方式** | 撤销 StageToolExecutor 调用，切回 BatchToolExecutor 平铺并发 |

### Phase E 详细 Checklist

- [ ] 读取 ExecutionPlan.stages 字段作为执行约束
- [ ] 实现拓扑排序执行器（先执行 `depends_on=[]` 的节点）
- [ ] StageToolExecutor 取代 BatchToolExecutor 的平铺并发
- [ ] 实现 ToolResultCache（以 `(tool_name, shop_id, facet)` 为 key）
- [ ] 实现 single-flight（同一 cache_key 只发起一次真实调用）
- [ ] 保留 BatchToolExecutor 作为底层原语

### Phase F 实施文件清单

| 项目 | 内容 |
|---|---|
| **新增文件** | 无（在现有 `facets.py` 中扩展 `RankingPolicy` 字段） |
| **修改文件** | `domain/facets.py`（扩展 `RankingPolicy`：添加 `hard_filters`、`objective_weights`、`tie_breakers`）、`engine/subgraphs/planning_subgraph.py`（修复 `_h_expand_search` 中 `filters = {}` 行为）、`domain/schemas.py`（`ExecutionPlan`/`EvidencePack` 中同步新增 RankingPolicy 字段） |
| **Legacy alias 保留** | `RankingPolicy.primary_facets` / `secondary_facets` / `tradeoff_notes` 保留为兼容字段 |
| **新增测试** | `test_second_layer_ranking_policy.py`、`test_second_layer_expand_search_policy.py` |
| **完成标准** | RankingPolicy 支持硬约束过滤 + 客观评分 + 平局决胜；expand_search 不再清空 filters/sort_by；单测通过 |
| **回滚方式** | 保留旧 RankingPolicy 和旧 expand_search 实现 |

### Phase F 详细 Checklist

- [ ] 增强 RankingPolicy（添加 hard_constraints、objective_scoring、scene_fit）
- [ ] 实现 RankingPolicy 的 5 步排序：hard_constraints_filter → objective_scoring → soft_preference → scene_fit → LLM_explanation
- [ ] 修改 expand_search 的 relax 逻辑，不再清空 filters/sort_by
- [ ] 实现 ExpandSearchPolicy 的 5 步放宽：increase_limit → expand_radius → relax_soft → retain_hard → report

### Phase G 实施文件清单

| 项目 | 内容 |
|---|---|
| **新增文件** | 无（在现有 `exploration_planning_workflow.py` 中增强，不新建文件） |
| **修改文件** | `engine/workflows/exploration_planning_workflow.py`（引入跨阶段依赖协调、复用共享能力包、输出经由 `response_subgraph`） |
| **Legacy alias 保留** | 保留旧 `_build_subgoals` / `_tool_round_search` / `_tool_round_expand` 入口作为兼容，新增逻辑走共享模块 |
| **新增测试** | `test_second_layer_exploration_workflow.py`（跨阶段协调测试） |
| **完成标准** | exploration 跨阶段依赖协调通过、使用共享能力包、response_subgraph 统一输出、regression 通过 |
| **回滚方式** | 切换回旧 exploration_planning_workflow 实现 |

### Phase G 详细 Checklist

- [ ] 确认当前 exploration_planning_workflow 的能力边界（已有工具调用但缺跨阶段协调）
- [ ] 引入跨阶段依赖协调（时间/距离/预算衔接）
- [ ] 复用共享能力包（TargetResolver、EvidencePlanner、RankingPolicy）
- [ ] 输出经由 response_subgraph 统一处理

### Phase H 实施文件清单

| 项目 | 内容 |
|---|---|
| **新增文件** | `engine/workflows/complex_orchestrator_workflow.py`、`engine/reducers/evidence_reducer.py`、`engine/reducers/conflict_resolver.py`、`engine/reducers/decision_reducer.py`、`domain/dag/sub_task_dag.py`、`domain/worker/worker_state.py`、`domain/worker/worker_result.py` |
| **修改文件** | `workflow_registry.py`（注册 `complex_orchestrator`）、`_routes.py`（增加新路由分支）、`config.py`（新增 `MAX_SUBTASK_COUNT`、`MAX_PARALLEL_WORKERS` 等配置） |
| **Legacy alias 保留** | 无（全新 workflow，无 alias 需求） |
| **新增测试** | `test_second_layer_complex_orchestrator.py`、`test_second_layer_map_reduce_reducer.py`、`test_second_layer_conflict_resolver.py`、`test_second_layer_worker_state_isolation.py`、`test_second_layer_trace_contract.py` |
| **完成标准** | 超复杂 query 可进入 MapReduce；worker 输出 WorkerResult 而非自然语言；reducer 产出 FinalDecisionPlan；冲突裁决 5 层规则生效；单测全部通过 |
| **回滚方式** | Router 中屏蔽 `complex_orchestrator` 路由分支，超复杂 query 仍走旧 `planning_subgraph` |

### Phase H 详细 Checklist

- [ ] 设计 SubTaskDAG 结构
- [ ] 设计 query_decomposer
- [ ] 设计 workflow_mapper（子任务 → workflow worker）
- [ ] 设计 stage_worker_executor（按 DAG 执行）
- [ ] 设计 EvidenceReducer
- [ ] 设计 ConflictResolver（5 层优先级规则）
- [ ] 设计 DecisionReducer
- [ ] 扩展 `LEGAL_WORKFLOW_NAMES` 增加 `complex_orchestrator`
- [ ] 扩展 `_route_workflow_runner` 增加 `complex_orchestrator` 分支
- [ ] 新增 `MAX_SUBTASK_COUNT`、`MAX_PARALLEL_WORKERS` 等配置

### Phase I 实施文件清单

| 项目 | 内容 |
|---|---|
| **新增文件** | `planning/goal/goal_planner.py`、`planning/target/target_resolver.py`、`planning/evidence/evidence_planner_service.py`、`planning/plan_validator_service.py`（从 planning_subgraph 提取为独立服务） |
| **修改文件** | `planning_subgraph.py`（精简为 dispatch 兼容层，所有实际逻辑委托给共享模块） |
| **Legacy alias 保留** | `planning_subgraph.py` 完整保留作为旧 workflow 的 dispatch 兼容层，函数签名不变 |
| **新增测试** | 无（复用现有 `test_goal_planner.py`、`test_evidence_planner.py`、`test_execution_plan_validator.py` 等测试，确保提取后行为一致） |
| **完成标准** | 新 workflow 全走共享模块；旧 planning_subgraph 只做 dispatch；所有提取模块单测通过；regression 通过 |
| **回滚方式** | 保留 planning_subgraph 入口，新 workflow 切回旧 dispatch |

### Phase I 详细 Checklist

- [ ] 提取 planning_subgraph.goal_planner → 共享 GoalPlanner
- [ ] 提取 planning_subgraph.target_resolve → 共享 TargetResolver
- [ ] 提取 planning_subgraph.evidence_planner → 共享 EvidencePlanner
- [ ] 提取 planning_subgraph.plan_validator → 共享 PlanValidator
- [ ] 保留 planning_subgraph 入口作为旧 workflow 的 dispatch 兼容层
- [ ] 新 workflow 直接调用共享模块，不走 planning_subgraph

### Phase J 实施文件清单

| 项目 | 内容 |
|---|---|
| **新增文件** | `tests/test_second_layer_latency_budget.py`、`tests/test_second_layer_cost_benchmark.py` |
| **修改文件** | 无（仅新增测试文件、运行回归） |
| **Legacy alias 保留** | 所有已迁移 workflow 均保留 alias，直到 Phase J 确认稳定后再清理 |
| **新增测试** | `test_second_layer_latency_budget.py`、`test_second_layer_cost_benchmark.py` |
| **完成标准** | 全量回归通过、benchmark 阈值达标、trace 完整性检查通过、延迟/成本不退化 |
| **回滚方式** | 全量回归未通过时，回退到 Phase I 状态继续修复 |

### Phase J 详细 Checklist

- [ ] 全量回归测试（comparison/recommendation/single coupon/single shop multifacet）
- [ ] 复杂 query E2E 测试
- [ ] latency benchmark（简单 fact query 不显著慢于当前版本）
- [ ] cost benchmark（简单 query LLM 调用次数下降或不增加）
- [ ] trace 完整性检查（router → workflow → planner → tool → evidence → review → decision → retry → fallback → reduce）

---

## 补充 B：`_route_workflow_runner` 三重判定兼容方案

### 当前代码

```python
# _routes.py:311-320
if workflow_name == "discovery_decision" or workflow_callable == "planning_subgraph" or response_mode == "comparison":
    return "planning_subgraph"
return "response_subgraph"
```

### 兼容计划

| 阶段 | 处理方式 |
|---|---|
| Phase A-B | 保持现状，记录和文档化该行为 |
| Phase C-D | 在新 workflow 名上扩展条件（OR chain），增加 `single_shop_fact` / `recommendation` / `comparison` |
| Phase E-F | 逐步减少对 `workflow_callable` 和 `response_mode` 的依赖 |
| Phase G-H | 简化为 workflow_name 为主的路由，不再双字段兜底 |
| Phase I-J | 移除三重判定，使用 `active_orchestration_router` 的输出作为唯一路由依据 |

```python
# 目标代码（Phase J）
workflow_name = state.workflow_name  # 来自 active_orchestration_router
if workflow_name in WORKFLOW_ROUTING_TABLE:
    return WORKFLOW_ROUTING_TABLE[workflow_name]
return "response_subgraph"  # fallback
```

---

## 补充 C：共享模块提取计划

| 当前位置 | 目标位置 | 提取时机 |
|---|---|---|
| `planning_subgraph._normalize_distance_tool_calls`（169-203） | `ToolPlanCompiler` 或 `gateway adapter` | Phase D |
| `planning_subgraph._resolve_recommendation_spec` | `CandidateSpecBuilder` | Phase D |
| `planning_subgraph._pending_candidate_targets` | `TargetResolver` | Phase D |
| `planning_subgraph._h_goal_planner` 逻辑 | 共享 `GoalPlanner` service | Phase I |
| `planning_subgraph._h_target_resolve` 逻辑 | 共享 `TargetResolver` service | Phase I |
| `planning_subgraph._h_evidence_planner` 逻辑 | 共享 `EvidencePlanner` service | Phase I |
| `planning_subgraph._h_plan_validator` 逻辑 | 共享 `PlanValidator` service | Phase I |

---

## 补充 D：Benchmark 阈值定义

### D.1 已有基准（继承自当前版本）

| 验收项 | 阈值 | 测量方式 |
|---|---|---|
| 简单 fact query 延迟 | Δ 不超过当前版本 +20% | `test_p10_experience_performance.py` 基线对照 |
| 简单 fact query LLM 调用 | ≤ 当前版本次数 | 每次 LLM 调用计数 |
| 复杂 query 证据链 | 全部工具结果不丢失 | E2E 测试断言 |
| trace 完整性 | 每 query 至少包含 8 个 span | trace 合约测试 |
| regression | 所有现有测试通过 | `pytest local_life_agent/tests -q` |

### D.2 新增 Benchmark 指标

| # | 指标 | 目标值 | 测量方式 | 所属 Phase |
|---|---|---|---|---|
| 1 | **recommendation p95 latency** | ≤ 8000ms（含搜索+证据+排序） | `test_second_layer_latency_budget.py` 中设置 95 分位断言 | J |
| 2 | **comparison p95 latency** | ≤ 10000ms（N 家 × facets 并行查询 + compare） | 同上 | J |
| 3 | **complex_orchestrator p95 latency** | ≤ 15000ms（分解 + 子任务 + reduce） | 同上 | J |
| 4 | **single_shop_fact p95 latency** | ≤ 2000ms | 同上 | J |
| 5 | **complex_orchestrator 最大 subtask 数** | ≤ 8（超过则路由 fallback 到旧 planning_subgraph） | `test_second_layer_complex_orchestrator.py` 中断言 | H |
| 6 | **ToolResultCache 命中率目标** | ≥ 30%（同轮内多 worker/多 workflow 查同店同 facet） | `test_second_layer_tool_result_cache.py` 中统计 cache_hit / total | E |
| 7 | **single-flight 去重断言** | 同一 cache_key 的并发请求只发起 1 次真实调用 | `test_second_layer_tool_result_cache.py` 中 mock 工具调用计数 | E |
| 8 | **LLM call count per workflow** | single_shop_fact: 0~1, recommendation: 1~3, comparison: 2~4, complex_orchestrator: 3~6 | `test_second_layer_cost_benchmark.py` 中断言 | J |
| 9 | **max total tool calls per workflow** | single_shop_fact: 1~3, recommendation: 5~15, comparison: N×3~5, complex: subtask aggregate | `test_second_layer_latency_budget.py` 中断言 | J |
| 10 | **trace span 覆盖率** | 100% 的 workflow 节点应有对应 span 记录 | `test_second_layer_trace_contract.py` 中断言 | H |
| 11 | **worker -> SessionState 隔离断言** | 0 次直接写 SessionState | `test_second_layer_worker_state_isolation.py` 中监控写入计数 | H |
| 12 | **replan counter 跨轮隔离断言** | 每轮起始 replan counter 为 0（不被前一轮继承） | `test_second_layer_execution_budget.py` 中断言 | B |

### D.3 Benchmark 运行方式

```bash
# 全量 benchmark
pytest local_life_agent/tests/test_second_layer_latency_budget.py -v --benchmark
pytest local_life_agent/tests/test_second_layer_cost_benchmark.py -v --benchmark

# 单 workflow benchmark
pytest local_life_agent/tests/test_second_layer_latency_budget.py -k "single_shop_fact" -v
pytest local_life_agent/tests/test_second_layer_latency_budget.py -k "recommendation" -v
pytest local_life_agent/tests/test_second_layer_latency_budget.py -k "comparison" -v
pytest local_life_agent/tests/test_second_layer_latency_budget.py -k "complex_orchestrator" -v
```

### D.4 Benchmark 失败时的策略

| 阶段 | 处理方式 |
|---|---|
| **Phase B-F** | 单 workflow benchmark 失败 → 回退对应 Phase 修改，不阻断其他 Phase |
| **Phase G-H** | 复杂 workflow benchmark 失败 → 可以接受渐进式优化，不要求一次性达标 |
| **Phase J** | 全量 benchmark 未达标 → 禁止合并，修复后再验证 |

---

## 补充 E：回退策略

| 阶段 | 出问题时的回退目标 | 回退方式 |
|---|---|---|
| Phase B/C | 回退到 Phase A（不改变业务代码） | 撤销策略代码，保留旧路由 |
| Phase D/E | 回退到 Phase C | 保留旧 discovery_decision alias，新 workflow 未稳定前不走 |
| Phase F/G | 回退到 Phase E | 保留旧 RankingPolicy / expand_search 实现 |
| Phase H | 回退到 Phase G | 复杂 query 仍走旧 planning_subgraph |
| Phase I | 回退到 Phase H | 保留 planning_subgraph 入口作为 dispatch 兼容层 |
| 任何时候 | 保留 `deterministic_tool` / `discovery_decision` legacy alias | 通过 `LEGAL_WORKFLOW_NAMES` 和 `_routes.py` 的双重兼容 |

