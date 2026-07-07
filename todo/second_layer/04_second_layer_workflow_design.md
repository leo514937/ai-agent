# 第二层 Workflow 详细设计

> **层级说明**：以下 7 个 workflow 中，`direct_response_workflow` 和 `clarification_workflow` 为**桥接工作流**（Bridge Workflow），不属于第二层证据决策核心。
>
> - **桥接工作流**：由第一层 Router 判别，默认 0 次 LLM 调用，不产生 EvidencePack，由第三层 deterministic composer 格式化输出
> - **第二层核心工作流**（single_shop_fact / recommendation / comparison / exploration / complex_orchestrator）：负责证据驱动决策，必须产生 EvidencePack 或 DecisionPlan
>
> 本文档中桥接工作流保留作为 workflow registry 的注册条目，但它们的执行路径不经过第二层证据决策链路。

## 1. `direct_response_workflow`（桥接工作流）

### 职责

处理闲聊、Agent 能力说明、安全拒答、非本地生活 query。不需要工具调用，不需要证据构建。

### 层级边界

```
Layer 1 Router 判定为 DirectAnswer/SafetyReject/NonLocalLife
→ 产出 DirectResponseDirective
→ 桥接工作流直接路由至 Layer 3 deterministic composer
→ 格式化输出最终回答
```

**不经过第二层证据决策链路**。

### 节点详情

| 节点 | 职责 | 输入 | 输出 | LLM 调用 |
|---|---|---|---|---|
| `response_subgraph` | Layer 3 composer 格式化输出 | DirectResponseDirective | 最终响应 | 0 |

### 约束

- **默认 LLM 调用 = 0 次**：回答由 Layer 3 deterministic composer 模板化生成，不调用 LLM
- 不创建 EvidencePack
- 不调任何工具
- 不进入 execution_review_subgraph
- 不写 SessionState 业务字段
- 非本地生活 query 不产生任何业务副作用

### 当前对应

当前 `run_direct_response_workflow`（`workflow_registry.py`），entry_node="response_subgraph"。

---

## 2. `clarification_workflow`（桥接工作流）

### 职责

处理缺信息追问、歧义消解、候选选择、pending clarification 回复、无效澄清回复。

### 层级边界

```
Layer 1/2 决策节点判定缺信息/歧义
→ 产出 ClarificationRequest
→ 桥接工作流路由至 Layer 3 deterministic composer
→ 模板化格式化澄清问题
→ 输出追问
```

**不经过第二层证据决策链路**。

### 节点详情

| 节点 | 职责 | 输入 | 输出 | LLM 调用 |
|---|---|---|---|---|
| `response_subgraph` | Layer 3 composer 模板化输出澄清问题 | ClarificationRequest | 最终响应 | 0 |

### 约束

- **默认 LLM 调用 = 0 次**：澄清问题由 Layer 3 composer 模板化生成，不调用 LLM
- 不执行工具
- 不产生 EvidencePack
- 必须记录缺失字段和歧义点到 SessionState（通过 state_update_plan）

### 当前对应

当前 `run_clarification_fallback_workflow`（`workflow_registry.py`），entry_node="response_subgraph"。

---

## 3. `single_shop_fact_workflow`

### 职责

单店事实查询：优惠券、营业状态、距离 ETA、评分、评价摘要、价格、团购。

### 核心设计原则

- **不默认走 LLM evidence_review**
- **不默认走 LLM decision_planner**
- **必须查工具**
- **必须产生 EvidencePack 或 EvidenceFragment**

### 内部流程

```text
target_resolve                           (解析目标店铺ID)
→ deterministic_evidence_plan            (根据 facet 规划证据需求)
→ plan_validator                         (校验工具计划合法性)
→ tool_execute (batch)                   (批量执行工具，并行)
→ evidence_build                         (构建 EvidencePack)
→ deterministic_sufficiency_check        (确定性检查，无 LLM)
→ response_subgraph                      (统一输出)
```

### 节点详情

| 节点 | 职责 | 输入 | 输出 | LLM 调用 |
|---|---|---|---|---|
| `target_resolve` | 解析目标店铺 ID | user_input, session_state | TargetResolutionResult | 0~1 次（仅歧义时） |
| `deterministic_evidence_plan` | 根据 facet 规划工具调用 | facets, target_resolution | ExecutionPlan | 0（模板化规则） |
| `plan_validator` | 校验工具名/shop_id/DAG | ExecutionPlan, registry | ValidationResult | 0 |
| `tool_execute` | 批量执行（并行） | ExecutionPlan.tool_calls | tool_results | 0 |
| `evidence_build` | 构建证据包 | tool_results | EvidencePack | 0 |
| `deterministic_sufficiency_check` | 检查证据完整性（无 LLM） | EvidencePack, required_facets | SufficiencyVerdict | 0 |
| `response_subgraph` | 输出最终回答 | EvidencePack, SufficiencyVerdict | 最终响应 | 0~1 次 |

### 典型 query 示例

| Query | 执行工具 | EvidencePack facet | LLM 调用 |
|---|---|---|---|
| "这家有券吗" | `get_coupon_list` | 优惠券 | 0 |
| "现在营业吗" | `check_open_status` | 营业状态 | 0 |
| "离我多远" | `get_distance_eta` | 距离 | 0 |
| "评分怎么样" | `get_shop_review_summary` | 评分/评价 | 0 |
| "有什么团购" | `get_deal_list` | 团购 | 0 |
| "这家店怎么样"（多facet） | 多工具并行 | 多 facet | 0~1（仅总结时） |

### ExecutionBudget

| 预算项 | 值 |
|---|---|
| max_llm_calls | 0~1 |
| max_tool_calls | 1~3 |
| max_replan_rounds | 0 |
| max_expand_rounds | 0 |
| max_parallel_workers | 1 |

### ReviewPolicy

| Review 类型 | 模式 |
|---|---|
| goal_review | skip |
| evidence_review | deterministic |
| decision_planner | deterministic |
| decision_review | skip |

### 当前对应

当前 `deterministic_tool` workflow + `run_deterministic_tool_workflow`（`deterministic_tool_workflow.py:1046-1234`）。升级方向：保留工具证据链，减少不必要 LLM review。

---

## 4. `recommendation_decision_workflow`

### 职责

找店、推荐、筛选、排序、偏好权衡、多轮推荐 refine、场景化推荐。

### 核心设计原则

- **硬约束过滤在前**
- **软偏好排序在后**
- **RankingPolicy 是排序权威**
- **LLM 主要负责偏好权衡和解释，不绕过评分策略**

### 内部流程

```text
goal_plan / candidate_spec               (理解推荐目标)
→ search_shops                           (搜索候选店铺)
→ evidence_enrichment                    (多facet并行查券/营业/距离/评价)
→ hard_constraint_filter                 (确定性硬约束过滤)
→ ranking_policy                         (客观评分 + 软偏好排序)
→ evidence_review                        (LLM检查证据质量)
→ decision_plan                          (混合模式:规则+LLM偏好解释)
→ response_subgraph                      (统一输出)
```

### 节点详情

| 节点 | 职责 | 输入 | 输出 | LLM 调用 |
|---|---|---|---|---|
| `goal_plan` | 理解推荐意图、约束、偏好 | user_input, session_state | GoalPlan | 1 次 |
| `search_shops` | 搜索候选店铺 | CandidateSearchSpec | 店铺列表 | 0 |
| `evidence_enrichment` | 并行查询各 facet | 店铺列表, facets | 多 shop 证据 | 0 |
| `hard_constraint_filter` | 品类/位置/营业/预算过滤 | 店铺列表, hard_constraints | 过滤后列表 | 0 |
| `ranking_policy` | 客观评分 + 软偏好排序 | EvidencePack, ranking_config | 排序后列表 | 0~1（仅权重调整） |
| `evidence_review` | 检查证据质量和覆盖 | EvidencePack, goal_plan | ReviewVerdict | 1 次 |
| `decision_plan` | 生成推荐决策 + 偏好解释 | EvidencePack, ranking, review | DecisionPlan | 1 次（偏好解释） |
| `response_subgraph` | 输出最终推荐 | DecisionPlan | 最终响应 | 0~1 次 |

### 典型 query 示例

| Query | 关键行为 |
|---|---|
| "附近推荐火锅" | search + 品类过滤 + 评分排序 |
| "便宜一点的呢" | budget 约束 + rerank |
| "适合约会的餐厅" | scene_fit 评分 + 环境/安静偏好 |
| "有券的湘菜馆" | search + coupon 过滤 + 评分排序 |

### ExecutionBudget

| 预算项 | 值 |
|---|---|
| max_llm_calls | 1~3 |
| max_tool_calls | 5~15 |
| max_replan_rounds | 1 |
| max_expand_rounds | 1 |
| max_parallel_workers | 1 |

### ReviewPolicy

| Review 类型 | 模式 |
|---|---|
| goal_review | conditional |
| evidence_review | required |
| decision_planner | hybrid |
| decision_review | deterministic sanity check |

### 当前对应

当前 `discovery_decision` → `planning_subgraph` 路径中的推荐场景。需从大 planning_subgraph 中拆出。

---

## 5. `comparison_decision_workflow`

### 职责

多店对比、winner 选择、trade-off 说明、场景适配比较。

### 核心设计原则

- 多店证据并行查
- 构建 comparison_matrix（字段级对比）
- winner/tradeoff 必须基于 EvidencePack

### 内部流程

```text
multi_target_resolve                     (解析多个比较目标)
→ comparison_evidence_plan               (规划每个比较维度)
→ stage_tool_execute                     (并行查多店证据)
→ comparison_matrix                      (构建结构化对比矩阵)
→ evidence_review                        (检查证据质量和覆盖)
→ decision_planner                       (LLM分析trade-off)
→ decision_review                        (确定性sanity check)
→ response_subgraph                      (统一输出)
```

### 节点详情

| 节点 | 职责 | 输入 | 输出 | LLM 调用 |
|---|---|---|---|---|
| `multi_target_resolve` | 解析多店 ID/名称 | user_input, session_state | list[TargetResolutionResult] | 1 次 |
| `comparison_evidence_plan` | 规划每店的比较维度 | 多店, facets | ExecutionPlan | 0（模板） |
| `stage_tool_execute` | 并行查多店的券/营业/距离/评价 | ExecutionPlan | tool_results | 0 |
| `comparison_matrix` | 构建字段级对比矩阵 | tool_results, shops | ComparisonMatrix | 0 |
| `evidence_review` | 检查证据质量 | EvidencePack, ComparisonMatrix | ReviewVerdict | 1 次 |
| `decision_planner` | LLM 分析 winner 和 trade-off | ComparisonMatrix, ReviewVerdict | DecisionPlan | 1 次 |
| `decision_review` | 确定性 sanity check | DecisionPlan, ComparisonMatrix | ReviewVerdict | 0 |
| `response_subgraph` | 输出对比结果 | DecisionPlan | 最终响应 | 0~1 次 |

### 典型 query 示例

| Query | 关键行为 |
|---|---|
| "A 和 B 哪个更适合约会" | 对比 → scene_fit 评估 → winner |
| "帮我比较这三家火锅店" | 多店 facet 并行 → comparison_matrix |
| "A 和 B 哪家券更多" | 聚焦 coupon facet 对比 |

### ExecutionBudget

| 预算项 | 值 |
|---|---|
| max_llm_calls | 2~4 |
| max_tool_calls | N shops × facets（每家 3~5 次） |
| max_replan_rounds | 1 |
| max_expand_rounds | 0 |
| max_parallel_workers | 1 |

### ReviewPolicy

| Review 类型 | 模式 |
|---|---|
| goal_review | conditional |
| evidence_review | required |
| decision_planner | LLM |
| decision_review | deterministic sanity check |

### 当前对应

当前 `discovery_decision` + `response_mode == "comparison"` → `planning_subgraph`。需解决 `_routes.py:311-320` 中 `response_mode == "comparison"` 的三重判定依赖。

---

## 6. `exploration_planning_workflow`

### 职责

多阶段本地生活规划：吃饭 + 逛街 + 咖啡 + 电影 + 带长辈半日活动。

### 核心设计原则

- 不允许 response-only
- 必须考虑距离、营业、时间衔接、预算、场景适配
- 可以复用 recommendation workflow 的候选能力

### 内部流程

```text
itinerary_goal_planner                   (理解多阶段规划意图)
→ stage_decomposition                    (拆成多个子阶段)
→ stage_candidate_search                 (逐个阶段找候选店)
→ cross_stage_evidence_build             (距离/营业/时间衔接校验)
→ itinerary_decision_planner             (生成完整行程规划)
→ response_subgraph                      (统一输出)
```

### 节点详情

| 节点 | 职责 | 输入 | 输出 | LLM 调用 |
|---|---|---|---|---|
| `itinerary_goal_planner` | 理解多阶段意图 | user_input, session_state | ItineraryGoal | 1 次 |
| `stage_decomposition` | 拆解子阶段 | ItineraryGoal | list[StageSpec] | 1 次 |
| `stage_candidate_search` | 逐阶段搜索候选 | StageSpec list | 每阶段候选列表 | 0（复用 search） |
| `cross_stage_evidence_build` | 距离/时间/营业衔接 | 候选列表, 时间线 | CrossStageEvidence | 0 |
| `itinerary_decision_planner` | 生成完整行程 | CrossStageEvidence, 偏好 | DecisionPlan | 1 次 |
| `response_subgraph` | 输出行程规划 | DecisionPlan | 最终响应 | 0~1 次 |

### 典型 query 示例

| Query | 关键行为 |
|---|---|
| "周末带长辈先吃饭再逛街再喝咖啡" | 3 阶段分解 + 时间线衔接 |
| "下午看电影然后晚上吃火锅" | 2 阶段 + 位置距离约束 |

### 当前对应

当前 `exploration_planning` workflow（`exploration_planning_workflow.py:840-1114`）已有骨架：`_build_subgoals` → `_tool_round_search` → `_tool_round_expand` → `build_evidence_pack_from_tool_results` → `_build_exploration_plan`。需要增强：跨阶段依赖协调、共享能力包复用、统一 `response_subgraph` 输出。

---

## 7. `complex_orchestrator_workflow`

### 职责

超复杂组合 query，使用 orchestrator-worker / map-reduce 拆解。

### 核心设计原则

- worker 输出结构化 WorkerResult，不输出最终自然语言
- reducer 生成 GlobalEvidencePack 和 FinalDecisionPlan
- 统一由 response_subgraph 生成最终回答

### 内部流程

```text
query_decomposer                        (将复杂query拆为子任务)
→ subtask_validator                     (校验子任务DAG合法性)
→ subtask_dag_builder                   (构建子任务DAG)
→ workflow_mapper                       (子任务→workflow worker映射)
→ stage_worker_executor                 (按DAG拓扑执行worker)
→ evidence_reducer                      (合并多worker证据)
→ conflict_resolver                     (解决证据冲突)
→ decision_reducer                      (生成最终决策)
→ response_subgraph                     (统一输出)
```

### 节点详情

| 节点 | 职责 | 输入 | 输出 | LLM 调用 |
|---|---|---|---|---|
| `query_decomposer` | 拆解 query 为子任务 | user_input, session_state | list[SubTask] | 1 次 |
| `subtask_validator` | 校验 DAG 合法性 | SubTaskDAG | ValidationResult | 0 |
| `subtask_dag_builder` | 构建 DAG | list[SubTask] | SubTaskDAG | 0 |
| `workflow_mapper` | 映射子任务到 workflow | SubTaskDAG, registry | list[WorkerSpec] | 0 |
| `stage_worker_executor` | 按 DAG 执行 workers | list[WorkerSpec] | list[WorkerResult] | 0（worker 内部可能调用 LLM） |
| `evidence_reducer` | 合并去重证据 | list[WorkerResult] | GlobalEvidencePack | 0 |
| `conflict_resolver` | 解决证据冲突 | GlobalEvidencePack | list[ConflictResolution] | 0（规则优先） |
| `decision_reducer` | 生成最终决策 | GlobalEvidencePack, ConflictResolution | FinalDecisionPlan | 1 次 |
| `response_subgraph` | 输出最终回答 | FinalDecisionPlan | 最终响应 | 0~1 次 |

### 进入条件（触发 MapReduce）

- 多阶段任务（3+ 阶段）
- 多目标对比（3+ 目标）
- 多约束推荐（5+ 约束条件）
- 推荐 + 对比混合
- 多地点 / 多时间组合规划

### 不进入条件

- 单店有券吗 → single_shop_fact_workflow
- 这家营业吗 → single_shop_fact_workflow
- 离我多远 → single_shop_fact_workflow
- 简单附近推荐 → recommendation_decision_workflow

### ExecutionBudget

| 预算项 | 值 |
|---|---|
| max_llm_calls | 3~6（分解 + reduce） |
| max_parallel_workers | 3~5 |
| max_subtask_count | 5~8 |
| max_tool_calls | 各 subtask 聚合 |
| max_replan_rounds | per subtask configurable |

### ReviewPolicy

| Review 类型 | 模式 |
|---|---|
| evidence_review | per subtask optional |
| final_decision_review | required |

### 当前对应

当前不存在。全新设计。

---

## 共享能力包调用关系矩阵

> **注意**：`direct_response` 和 `clarification` 为桥接工作流，不走第二层证据决策链路，所有能力包均为 ✗。

| Workflow \ 能力包 | TargetResolve | EvidencePlan | PlanValidate | ToolExecute | EvidenceBuild | RankPolicy | EvidenceReview | DecisionPlan | DecisionReview |
|---|---|---|---|---|---|---|---|---|---|
| `direct_response`（桥接） | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| `clarification`（桥接） | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| `single_shop_fact` | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | deterministic | deterministic | skip |
| `recommendation` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | required | hybrid | sanity |
| `comparison` | ✓(multi) | ✓ | ✓ | ✓(multi-shop) | ✓ | ✗ | required | LLM | sanity |
| `exploration` | ✓ | ✓ | ✓ | ✓(multi-stage) | ✓ | ✓ | conditional | LLM | conditional |
| `complex_orchestrator` | via worker | via worker | via worker | via worker | via worker | via worker | per_subtask | reducer | required |
