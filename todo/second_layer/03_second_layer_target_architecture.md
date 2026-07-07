# 第二层目标架构

## 1. 全貌架构图

```text
active_orchestration_router
  │
  ├─→ [桥接工作流（Layer 1→3，非第二层证据决策）]
  │   ├─→ direct_response_workflow             闲聊/安全拒答/非本地生活
  │   └─→ clarification_workflow                缺信息/歧义/候选选择
  │
  ├─→ [第二层核心工作流（证据驱动决策）]
  │   ├─→ single_shop_fact_workflow            单店事实：券/营业/距离/评分/评价/价格
  │   ├─→ recommendation_decision_workflow     找店/推荐/筛选/排序/偏好权衡
  │   ├─→ comparison_decision_workflow         多店对比/winner选择/trade-off
  │   ├─→ exploration_planning_workflow        多阶段本地生活规划：吃饭+逛街+咖啡
  │   └─→ complex_orchestrator_workflow        超复杂组合query：map-reduce/orchestrator-worker
  │
  └─→ [第三层统一输出]
      └─→ response_subgraph / deterministic_composer
```

**关键层级边界**：
- `direct_response_workflow` 和 `clarification_workflow` 是**桥接工作流**，不是第二层证据决策工作流
- 它们由第一层 Router 判别产出 DirectResponseDirective / ClarificationRequest，第三层 deterministic composer 输出
- 第二层真正核心是 5 个证据驱动决策工作流：single_shop_fact、recommendation、comparison、exploration、complex_orchestrator
- 所有 workflow（包括桥接工作流）共享底层能力包，不重复实现工具和证据逻辑

### 1.1 桥接工作流 vs 第二层核心工作流

| 维度 | 桥接工作流 | 第二层核心工作流 |
|---|---|---|
| **路由源** | Layer 1 Router 直接判定 | Layer 1 Router 判定后进入第二层 |
| **证据决策** | 不需要 | 必须产生 EvidencePack / DecisionPlan |
| **工具调用** | 0 | 每种 workflow 按需调用 |
| **LLM 调用** | 0（Layer 3 composer 模板化输出） | 按 workflow 预算 |
| **输出格式** | 由 Layer 3 deterministic composer 格式化 | response_subgraph 统一输出 |
| **副作用** | 不写 SessionState 业务字段 | 通过 session_write_proposal 写入 |

## 2. 核心原则

| 原则 | 说明 |
|---|---|
| **简单 query 不走重链路** | 单店事实 query 走 `single_shop_fact_workflow`，不触发 LLM review 和重型 DAG |
| **中等 query 走单业务 workflow** | 推荐/对比分别走 `recommendation` / `comparison` workflow |
| **超复杂 query 才走 complex_orchestrator** | 多阶段/多目标组合才进入 MapReduce |
| **所有 workflow 共享能力包** | 不重复实现工具/证据/review/ranking 逻辑 |
| **排序权威确定性优先** | RankingPolicy 决定推荐排序，LLM 只负责偏好权衡和解释 |
| **证据驱动决策** | 最终回答必须基于 EvidencePack / FinalDecisionPlan |

## 3. 7 个 Workflow 职责说明

### 3.1 `direct_response_workflow`（桥接工作流）

| 维度 | 说明 |
|---|---|
| **职责** | 处理闲聊、Agent 能力说明、安全拒答、非本地生活 query |
| **典型输入** | "你好"、"你能做什么"、"帮我写首诗"、"违法请求" |
| **进入条件** | 路由判定为 Direct Answer / 安全拒答 / 非本地生活 |
| **层级归属** | **桥接工作流**：Layer 1 Router 产出 DirectResponseDirective，Layer 3 deterministic composer 输出最终回答 |
| **工具调用** | 无 |
| **EvidencePack** | 不产生 |
| **LLM 预算** | **0 次**（默认由 Layer 3 deterministic composer 模板化输出，不调用 LLM） |
| **当前对应** | `direct_response` workflow + `run_direct_response_workflow` |

### 3.2 `clarification_workflow`（桥接工作流）

| 维度 | 说明 |
|---|---|
| **职责** | 缺信息追问、歧义消解、候选选择、pending clarification 回复、无效澄清回复 |
| **典型输入** | "推荐好吃的"（缺品类）、"A 和 B 呢"（缺对比意图） |
| **进入条件** | 第一层/第二层决策节点产出 ClarificationRequest |
| **层级归属** | **桥接工作流**：由 Layer 2 决策节点产出 ClarificationRequest，Layer 3 格式化输出 |
| **工具调用** | 无 |
| **EvidencePack** | 不产生 |
| **LLM 预算** | **0 次**（默认由 Layer 3 deterministic composer 模板化格式输出，不调用 LLM） |
| **当前对应** | `clarification_fallback` workflow |

### 3.3 `single_shop_fact_workflow`

| 维度 | 说明 |
|---|---|
| **职责** | 单店事实查询：优惠券、营业状态、距离 ETA、评分、评价摘要、价格、团购 |
| **典型输入** | "这家有券吗"、"现在营业吗"、"离我多远"、"评分怎么样" |
| **进入条件** | 路由判定为 deterministic / single-shop fact 类 query |
| **工具调用** | 1~3 次（必须查工具） |
| **EvidencePack** | 必须产生 |
| **LLM 预算** | 0~1 次（尽可能 0 次） |
| **ReviewPolicy** | evidence_review = deterministic, decision_planner = deterministic |
| **当前对应** | `deterministic_tool` workflow + `run_deterministic_tool_workflow` |

### 3.4 `recommendation_decision_workflow`

| 维度 | 说明 |
|---|---|
| **职责** | 找店、推荐、筛选、排序、偏好权衡、多轮推荐 refine、场景化推荐 |
| **典型输入** | "附近推荐火锅"、"便宜一点的呢"、"适合约会的餐厅" |
| **进入条件** | 路由判定为 discovery / recommendation 类 query |
| **工具调用** | 5~15 次 |
| **LLM 预算** | 1~3 次 |
| **排序权威** | RankingPolicy（硬约束过滤 + 客观评分 + 软偏好 + 场景匹配） |
| **ReviewPolicy** | evidence_review = required, decision_planner = hybrid |
| **当前对应** | `discovery_decision` → `planning_subgraph` 路径（需拆分） |

### 3.5 `comparison_decision_workflow`

| 维度 | 说明 |
|---|---|
| **职责** | 多店对比、winner 选择、trade-off 说明、场景适配比较 |
| **典型输入** | "A 和 B 哪个更适合约会"、"帮我比较这三家" |
| **进入条件** | 路由判定为 comparison 类 query |
| **工具调用** | N shops × facets（每家 3~5 个 facet） |
| **LLM 预算** | 2~4 次 |
| **核心产出** | comparison_matrix（结构化对比矩阵） |
| **ReviewPolicy** | evidence_review = required, decision_planner = LLM, decision_review = deterministic |
| **当前对应** | `discovery_decision` + `response_mode == "comparison"` → `planning_subgraph`（需拆分） |

### 3.6 `exploration_planning_workflow`

| 维度 | 说明 |
|---|---|
| **职责** | 多阶段本地生活规划：吃饭 + 逛街 + 咖啡 + 电影 + 带长辈半日活动 |
| **典型输入** | "周末带长辈先吃饭再逛街再喝咖啡" |
| **进入条件** | 路由判定为 exploration / multi-stage 类 query |
| **工具调用** | 多阶段 × 每阶段候选搜索 |
| **LLM 预算** | 3~5 次 |
| **核心能力** | 阶段分解、跨阶段衔接（距离/时间/营业/预算） |
| **当前对应** | `exploration_planning` workflow（已有骨架但需增强跨阶段协调） |

### 3.7 `complex_orchestrator_workflow`

| 维度 | 说明 |
|---|---|
| **职责** | 超复杂组合 query，使用 orchestrator-worker / map-reduce 拆解 |
| **典型输入** | "帮我找周末能带长辈吃饭逛街的路线，顺便看附近有没有适合约会的咖啡馆" |
| **进入条件** | 路由判定为 super_complex / multi-goal / multiple comparison |
| **工具调用** | 多个 worker 聚合，总量可控 |
| **LLM 预算** | 3~6 次（分解 + reduce） |
| **核心能力** | query_decomposer → SubTaskDAG → workflow_mapper → EvidenceReducer → DecisionReducer |
| **当前对应** | 不存在，全新设计 |

> **重要说明**：以下复杂度分层仅覆盖第二层 5 个核心证据决策工作流（single_shop_fact / recommendation / comparison / exploration / complex_orchestrator）。
> `direct_response_workflow` 和 `clarification_workflow` 作为桥接工作流不参与复杂度分层——它们由 Router 直接判别，不由复杂度判定决定。

## 4. 简单/中等/复杂/超复杂 query 分层策略

```text
Query 复杂度判定
  │
  ├─ 简单 (single_shop_fact)
  │   ├─ "这家有券吗"
  │   ├─ "现在营业吗"
  │   ├─ "离我多远"
  │   └─ "评分怎么样"
  │   └─→ single_shop_fact_workflow
  │
  ├─ 中等 (discovery)
  │   ├─ "附近推荐火锅"
  │   ├─ "便宜一点的呢"
  │   └─→ recommendation_decision_workflow
  │   ├─ "A 和 B 哪个好"
  │   └─→ comparison_decision_workflow
  │
  ├─ 复杂 (exploration)
  │   ├─ "周末带长辈吃饭逛街再喝咖啡"
  │   └─→ exploration_planning_workflow
  │
  └─ 超复杂 (multi-goal / super complex)
      ├─ 多目标 + 多约束 + 多地点组合
      └─→ complex_orchestrator_workflow (MapReduce)
```

复杂度判定维度：
| 维度 | 简单 | 中等 | 复杂 | 超复杂 |
|---|---|---|---|---|
| 目标数 | 1 | 1~2 | 2~3 | 3+ |
| 约束条件 | 0~1 | 1~3 | 3~5 | 5+ |
| 涉及店铺数 | 1 | 1~10 | 多阶段 | 多组 |
| 需要规划 | 否 | 否 | 是 | 是 |
| LLM 调用预算 | 0~1 | 1~3 | 3~5 | 3~6 |
| 是否需要 MapReduce | 否 | 否 | 否 | 是 |

## 5. 共享能力包设计

所有 workflow 共享以下能力包，不重复实现：

| 能力包 | 输入 | 输出 | Layer | 职责 |
|---|---|---|---|---|
| `TaskComplexityAnalyzer` | user_input, session_state | TaskComplexity | Router | 判定 query 复杂度 |
| `TargetResolver` | goal_plan, user_input | TargetResolutionResult | Planning | 解析目标店铺、候选集 |
| `CandidateSpecBuilder` | goal_plan, facets | CandidateSearchSpec | Planning | 构建搜索规格 |
| `CandidateSetBuilder` | search_results | CandidateSet | Planning | 构建候选集 |
| `EvidencePlanner` | facets, target_resolution | EvidencePlannerResult | Planning | 规划需要哪些证据 |
| `ToolPlanCompiler` | EvidencePlannerResult | ExecutionPlan | Planning | 逻辑计划→可执行计划 |
| `PlanValidator` | ExecutionPlan, registry | ValidationResult | Planning | DAG 合法性校验 |
| `StageToolExecutor` | ExecutionPlan | tool_results | Execution | 按 DAG 拓扑执行工具 |
| `EvidenceBuilder` | tool_results | EvidencePack | Evidence | 构建证据包 |
| `SufficiencyChecker` | EvidencePack, goal_plan | SufficiencyVerdict | Evidence | 证据充分性判断 |
| `RankingPolicy` | EvidencePack, goal_plan | RankedShopList | Decision | 推荐排序权威 |
| `ReviewPolicy` | workflow_kind | ReviewDecision | Policy | 控制 review 强度 |
| `DecisionPlanner` | EvidencePack, goal_plan | DecisionPlan | Decision | 生成决策 |
| `DecisionReview` | DecisionPlan, EvidencePack | ReviewVerdict | Decision | 决策审查 |
| `ExecutionBudget` | workflow_kind | BudgetAllocation | Policy | 预算分配 |
| `ExpandSearchPolicy` | search_spec | RelaxedSearchSpec | Policy | 扩搜策略 |
| `ToolResultCache` | tool_key | cached_result | Cache | 工具结果缓存 |
| `EvidenceCache` | evidence_key | cached_evidence | Cache | 证据构建缓存 |
| `EvidenceReducer` | list[EvidencePack] | GlobalEvidencePack | Reduce | 多 worker 证据合并 |
| `ConflictResolver` | list[EvidenceConflict] | ConflictResolution | Reduce | 冲突裁决 |
| `DecisionReducer` | list[DecisionFragment] | FinalDecisionPlan | Reduce | 最终决策生成 |

## 6. 对比当前架构的关键改进

| 当前架构 | 目标架构 | 改进点 |
|---|---|---|
| `orchestration_router_shadow`（命名误导） | `active_orchestration_router` | 名称反映真实执行权 |
| `_route_workflow_runner` 三重判定 | workflow 名直接路由 | 消除隐藏路由逻辑 |
| `discovery_decision` 一个大 workflow | `recommendation` + `comparison` 拆分 | 职责分离，策略独立 |
| `deterministic_tool` 入口在 response_subgraph | `single_shop_fact_workflow` 完整链路 | 保证工具证据链 |
| `planning_subgraph` 1369 行大子图 | 共享能力包 + 轻量 workflow | 职责拆分，可维护性 |
| 无 MapReduce | `complex_orchestrator_workflow` | 超复杂 query 结构化解构 |
| `BatchToolExecutor` 平铺并发 | `StageToolExecutor` DAG 拓扑执行 | 按依赖分层调度 |
| LLM 主导推荐排序 | RankingPolicy 确定性优先 | 排序权威明确 |
| `expand_search` 清空 filters | ExpandSearchPolicy 分层放宽 | 保留硬约束 |
| retry 计数在 SessionState | ExecutionBudget 在 GraphState | 不跨轮污染 |
| 无统一 trace | WorkflowTrace + ReduceTrace | 全链路可观测 |

## 7. 约束说明

- 简单 query 不走 MapReduce，不走重型 LLM review
- 中等 query 走单业务 workflow，不进入 complex_orchestrator
- 超复杂 query 才走 complex_orchestrator_workflow
- 所有 workflow 共享底层能力包，不重复实现工具调用、证据构建、排名、预算、review 逻辑
- 不允许 worker 直接写 SessionState
- 不允许 concatenate 多个 worker 的自然语言输出作为最终回答
- `direct_response_workflow` 和 `clarification_workflow` 是桥接工作流非第二层核心——默认 0 LLM 调用，不走证据链
- Worker 层级禁止直接写 SessionState，只能输出 `session_write_proposal`

## 8. SessionState 写入边界与第二层约束

### 8.1 原则

1. **第二层 workflow** 可以写 SessionState 的业务上下文字段（如 `current_shop`、`last_recommendation_list`），但必须通过 `state_update_plan` 作为唯一写入口
2. **Worker（MapReduce 子任务）** 禁止直接写 SessionState，只能通过 `WorkerResult.session_write_proposal` 建议写入
3. **GraphState** 持有执行态和追踪态（中间计划、DAG trace、预算），不跨轮持久化
4. **桥接工作流**（direct_response / clarification）不写 SessionState 业务字段
5. **`state_update_plan`** 是所有 SessionState 写入的闸门——不允许任何节点绕过它直接修改 SessionState

### 8.2 字段写入权限矩阵

| 字段 | 所属 | 允许第二层写 | 仅 state_update_plan 写 | Worker 禁止写 | 说明 |
|---|---|---|---|---|---|
| `last_recommendation_list` | SessionState | ✓ | ✓ | ✓ | 推荐排序结果，第二层 workflow 可以产生 |
| `current_shop` | SessionState | ✓ | ✓ | ✓ | 当前关注店铺，由 target_resolve 输出 |
| `comparison_targets` | SessionState | ✓ | ✓ | ✓ | 对比目标店铺列表 |
| `active_constraints` | SessionState | ✓ | ✓ | ✓ | 活跃筛选条件（品类/预算/位置） |
| `replan_counters` | SessionState | ✗（仅通过 ExecutionBudget） | ✓ | ✓ | 需要迁移到 GraphState 的 ExecutionBudget 中 |
| `pending_clarification` | SessionState | ✓ | ✓ | ✓ | 待处理澄清，仅由 clarification 相关节点产生 |
| `clarification_request` | SessionState | ✓ | ✓ | ✓ | 当前轮澄清请求，与 pending_clarification 同步 |
| `goal_plan_history` | SessionState | ✓（追加模式） | ✓ | ✓ | 历史 goal plan 记录 |
| `preferred_facets` | SessionState | ✓ | ✓ | ✓ | 用户偏好 facet 追踪 |
| `last_search_spec` | SessionState | ✓ | ✓ | ✓ | 最后一次搜索规格 |
| `location_context` | SessionState | ✓ | ✓ | ✓ | 用户实时位置（由第一层更新） |
| `freshness_meta` | SessionState | 仅读取 | ✓ | ✓ | 缓存 freshness 元数据 |

### 8.3 仅属于 GraphState（不进入 SessionState）的字段

| 字段 | 说明 | 写入者 |
|---|---|---|
| `execution_budget` | 当前轮预算 | state_update_plan |
| `trace_spans` | 执行追踪 span | 各节点追加 |
| `workflow_trace` | workflow 级追踪 | workflow_runner |
| `logical_evidence_plan` | 逻辑计划中间态 | planner |
| `execution_plan` | 可执行计划中间态 | ToolPlanCompiler |
| `execution_dag_trace` | DAG 执行轨迹 | StageToolExecutor |
| `event_log` | 事件日志 | 各节点 |
| `worker_results` | worker 输出暂存 | stage_worker_executor |
| `global_evidence_pack` | reduce 后证据 | EvidenceReducer |
| `final_decision_plan` | 最终决策 | DecisionReducer |

### 8.4 禁止 Worker 写入的字段

以下字段 Worker（MapReduce 子任务）在任何情况下都不得直接写入，只能通过 `session_write_proposal` 建议：

- `last_recommendation_list`
- `current_shop`
- `comparison_targets`
- `active_constraints`
- `pending_clarification`
- `replan_counters`
- 所有 `SessionState` 字段（worker 仅 read-only reference）
- 所有 `GraphState` 的执行计划字段（worker 只产 WorkerResult）
