请你严格基于当前仓库真实代码，调研并设计“第二层：任务决策与证据层”的全面升级方案，将方案文档输出到 `todo/second_layer/` 目录。

重要要求：

1. 只做代码调研和方案文档，不要直接修改业务代码。
2. 不要根据经验脑补，必须以当前仓库实际代码为准。
3. 如果已有文档描述和真实代码不一致，以真实代码为准，并在报告中指出偏差。
4. 本次目标是：调研当前第二层真实实现，参考业界模式，设计可执行的升级方案，使第二层能够高效处理简单、中等、复杂、超复杂本地生活 query。
5. 最终请把所有分析和解决方案放到 `todo/second_layer/` 下。如果目录不存在，请创建。
6. 不要声称已经完成改造，只能说“已形成解决方案文档”。
7. 不要直接改业务代码，不要删除文件，不要迁移 import。
8. 必须关注运行效果、响应速度、成本控制、复杂问题覆盖、工具重复调用、状态污染、并行依赖、最终回答一致性等问题。

本次调研范围：

重点扫描以下模块及其直接依赖：

* `local_life_agent/engine/subgraphs/orchestration_router_shadow.py`
* `local_life_agent/planning/orchestration_router.py`
* `local_life_agent/engine/workflow_runner.py`
* `local_life_agent/engine/workflow_registry.py`
* `local_life_agent/engine/subgraphs/planning_subgraph.py`
* `local_life_agent/engine/subgraphs/execution_review_subgraph.py`
* `local_life_agent/engine/_routes.py`
* `local_life_agent/planning/` 下与 goal / evidence / decision / review / plans 相关模块
* `local_life_agent/execution/` 下与工具执行、批处理、并行、core 相关模块
* `local_life_agent/evidence/` 下与 EvidencePack / EvidenceBuilder / review 相关模块
* `local_life_agent/decision/` 或 `domain/decision.py` 相关模块
* `local_life_agent/tools/gateway.py`
* `local_life_agent/tools/registry.py`
* `local_life_agent/tools/db_tools.py`
* `local_life_agent/domain/graph_state.py`
* `local_life_agent/domain/state.py`
* `local_life_agent/domain/schemas.py`
* 与 `ExecutionPlan`、`ToolCallSpec`、`EvidencePack`、`DecisionPlan`、`GoalPlan`、`CandidateSet`、`OrchestrationDecision`、`SessionState` 相关的定义和测试

请优先确认当前第二层真实数据流：

```text
understanding_subgraph
  → orchestration_router_shadow
  → workflow_runner
  → planning_subgraph / response_subgraph
  → execution_review_subgraph
  → response_subgraph / retry planning
```

当前报告中提到的已知事实需要核验：

1. `orchestration_router_shadow` 是否仍然叫 shadow，但其输出 `workflow_name` 会被 `workflow_runner` 消费？
2. `workflow_runner` 是否只做 registry dispatch，还是仍然存在隐藏路由逻辑？
3. `_route_workflow_runner` 是否仍然用 `response_mode == "comparison"` 这类字段兜底进入 `planning_subgraph`？
4. 当前 workflow registry 中有哪些 workflow？分别 entry_node 是什么？
5. `deterministic_tool` 是否直接进入 `response_subgraph`？它是否真的完成工具查询和 EvidencePack 构建？
6. `discovery_decision` 是否是进入 `planning_subgraph` 的主路径？
7. `exploration_planning` 是否只是 response-only？是否缺少真实工具证据链？
8. `planning_subgraph` 是否过大，内部是否混合 goal planning、target resolve、candidate set、evidence planning、clarification、fallback 等多种职责？
9. `target_resolve` 是否承担过多职责？
10. `evidence_planner` 对推荐、对比、单店任务是否有不同策略？
11. 当前工具执行是否只是 search_calls + remaining_specs 两阶段，而不是通用 DAG / stages executor？
12. `ExecutionPlan.stages` 是否真实驱动执行，还是字段存在但未充分使用？
13. `expand_search` 是否存在清空 filters / sort_by 的逻辑？
14. replan / expand_search 计数器是否放在 `SessionState.replan_counters`，是否可能跨轮污染？
15. EvidenceReview、DecisionPlanner、DecisionReview 是否存在重复 review / 过重链路问题？
16. 推荐排序是否有明确 `RankingPolicy`，还是主要依赖 LLM / 隐式规则？
17. 距离工具归一化是否藏在 planning_subgraph 内部，例如 `get_distance_eta` 改写为 `calculate_distance_km`？
18. 第二层是否会直接 mutate `SessionState` 或写入跨轮字段？
19. 是否存在 `ToolResultCache` / `EvidenceCache` / request coalescing，避免多个 workflow 重复查同一家店的券、营业、距离？
20. 是否存在 `WorkerResult` / `DecisionFragment` / `GlobalEvidencePack` / `FinalDecisionPlan` 这类 MapReduce 结构化 reduce 契约？
21. 是否有复杂 query 的 orchestrator-worker / map-reduce 实现，还是所有复杂任务都走一个大 planning_subgraph？
22. 第二层 trace 是否能解释 router、workflow、planner、tool、evidence、review、decision、retry、fallback、reduce 的耗时和决策原因？

请输出到 `todo/second_layer/`，建议文件结构：

```text
todo/second_layer/
  01_second_layer_fact_baseline.md
  02_second_layer_problem_analysis.md
  03_second_layer_target_architecture.md
  04_second_layer_workflow_design.md
  05_second_layer_contract_design.md
  06_second_layer_execution_and_cache_design.md
  07_second_layer_map_reduce_design.md
  08_second_layer_review_ranking_budget_design.md
  09_second_layer_migration_plan.md
  10_second_layer_test_plan.md
```

如果你认为合并更合适，可以合并，但必须保证内容完整。

一、`01_second_layer_fact_baseline.md`

请写清楚真实代码现状：

* 第二层真实调用链
* 每个节点读写的关键 state 字段
* 当前注册的 workflow 名称、entry_node、handler、是否真实执行工具
* `orchestration_router_shadow` 的真实职责
* `workflow_runner` 的真实职责
* `_routes.py` 在第二层中的真实路由逻辑
* `planning_subgraph` 内部节点和职责
* `execution_review_subgraph` 内部节点和职责
* 当前工具执行模式：是否两阶段、是否并行、是否支持 DAG
* 当前 EvidencePack / DecisionPlan / GoalPlan / ExecutionPlan 的真实字段
* 当前 review / retry / fallback / expand_search 的真实逻辑
* 当前缺失能力：ReviewPolicy、RankingPolicy、ExecutionBudget、ToolResultCache、EvidenceReducer、DecisionReducer、ComplexOrchestrator 等

要求：每个结论都要标注对应文件和函数名，最好带行号。

二、`02_second_layer_problem_analysis.md`

请按 P0 / P1 / P2 分析问题。

必须覆盖以下 P0 问题：

1. 轻重链路未分层
   风险：简单单店事实 query 走重链路，复杂 query 又被塞进一个大 planning_subgraph，影响速度和稳定性。

2. `deterministic_tool` 可能过轻
   风险：“有券吗 / 营业吗 / 距离多远”这类事实问题如果直接进 response_subgraph，可能绕过工具证据链。

3. `orchestration_router_shadow` 命名与真实执行权不一致
   风险：如果它的输出会被下游消费，就不应继续叫纯 shadow。

4. `_route_workflow_runner` 隐藏路由判断
   风险：如果仍通过 `response_mode == comparison` 等字段进入 planning，会破坏 router 权威。

5. `expand_search` 放宽策略过粗
   风险：清空 filters / sort_by 会丢失用户硬约束，例如品类、位置、预算、营业状态。

6. retry / replan 计数放在 SessionState
   风险：本轮执行预算污染跨轮会话，导致后续 query 错误降级。

7. 推荐排序权威不清
   风险：LLM 可能推荐距离很远、价格不合适、无券或不符合硬约束的店。

8. MapReduce 缺少结构化 reducer 契约
   风险：复杂 query 如果多 workflow 并行，最终回答可能变成多个自然语言片段拼接，产生冲突和重复。

必须覆盖以下 P1 问题：

9. `planning_subgraph` 文件过大，职责混杂
10. `target_resolve` 过重，混合商户解析、候选构建、对比目标、澄清策略
11. EvidenceReview 和 DecisionPlanner 可能重复消耗 LLM
12. 工具执行缺少通用 DAG / StageExecutor
13. 缺少 ToolResultCache / EvidenceCache / request coalescing
14. worker 子任务如果未来并行，可能污染主 SessionState
15. exploration_planning 如果 response-only，无法处理真实吃喝玩乐组合规划
16. 距离工具 alias / argument normalize 藏在 planning 层，边界不清
17. 第二层 trace / latency / cost span 不完整

必须覆盖以下 P2 问题：

18. workflow 命名和 entry_node 不够表达真实职责
19. legacy alias 映射是否会掩盖真实路由
20. fallback/degrade reason 是否结构化不足
21. 简单 query 缺少 latency benchmark
22. 复杂 query 缺少 E2E case 集

三、`03_second_layer_target_architecture.md`

请给出目标架构，参考业界模式，但必须适配本地生活 Agent。

目标架构建议：

```text
active_orchestration_router
  → direct_response_workflow
  → clarification_workflow
  → single_shop_fact_workflow
  → recommendation_decision_workflow
  → comparison_decision_workflow
  → exploration_planning_workflow
  → complex_orchestrator_workflow
```

请说明每个 workflow 的职责：

1. `direct_response_workflow`
   处理闲聊、能力说明、安全拒答、非本地生活等不需要工具的 query。

2. `clarification_workflow`
   处理缺信息、歧义、候选选择、pending clarification、无效澄清回复等。

3. `single_shop_fact_workflow`
   处理单店事实查询：券、营业、距离、评分、评价、价格等。要求轻链路、强工具、低 LLM 调用。

4. `recommendation_decision_workflow`
   处理找店、推荐、筛选、排序、偏好权衡、多轮推荐 refine。要求有 RankingPolicy，不允许完全依赖 LLM 排名。

5. `comparison_decision_workflow`
   处理多店对比、winner 选择、trade-off、场景适配比较。

6. `exploration_planning_workflow`
   处理吃饭 + 逛街 + 咖啡 + 电影 + 带长辈半日活动等多阶段本地生活规划。

7. `complex_orchestrator_workflow`
   处理超复杂组合 query，使用 orchestrator-worker / map-reduce，将子任务 map 到不同 workflow worker，最后 reduce 结构化证据和决策。

请强调：

* 简单 query 不走 MapReduce。
* 中等 query 走单业务 workflow。
* 超复杂 query 才走 complex_orchestrator_workflow。
* 所有 workflow 共享底层能力包，不重复实现工具和证据逻辑。

共享能力包建议：

```text
TargetResolver
CandidateSpecBuilder
CandidateSetBuilder
EvidencePlanner
ToolPlanCompiler
PlanValidator
StageToolExecutor
EvidenceBuilder
SufficiencyChecker
RankingPolicy
ReviewPolicy
DecisionPlanner
DecisionReview
ExecutionBudget
ExpandSearchPolicy
ToolResultCache
EvidenceCache
EvidenceReducer
ConflictResolver
DecisionReducer
```

四、`04_second_layer_workflow_design.md`

请分别设计 7 个 workflow 的内部流程。

必须包含：

### `single_shop_fact_workflow`

```text
target_resolve
→ deterministic_evidence_plan
→ plan_validator
→ tool_execute
→ evidence_build
→ deterministic_sufficiency_check
→ response_subgraph
```

要求：

* 不默认走 LLM evidence_review。
* 不默认走 LLM decision_planner。
* 必须查工具。
* 必须产生 EvidencePack 或 EvidenceFragment。
* 适合“有券吗 / 营业吗 / 距离多远 / 评分怎么样”。

### `recommendation_decision_workflow`

```text
goal_plan / candidate_spec
→ search_shops
→ evidence_enrichment
→ hard_constraint_filter
→ ranking_policy
→ evidence_review
→ decision_plan
→ response_subgraph
```

要求：

* 硬约束过滤在前。
* 软偏好排序在后。
* RankingPolicy 是排序权威。
* LLM 主要负责偏好权衡和解释，不直接绕过评分策略。

### `comparison_decision_workflow`

```text
multi_target_resolve
→ comparison_evidence_plan
→ stage_tool_execute
→ comparison_matrix
→ evidence_review
→ decision_planner
→ decision_review
→ response_subgraph
```

要求：

* 多店证据并行查。
* 构建 comparison_matrix。
* winner / tradeoff 必须基于 EvidencePack。

### `exploration_planning_workflow`

```text
itinerary_goal_planner
→ stage_decomposition
→ stage_candidate_search
→ cross_stage_evidence_build
→ itinerary_decision_planner
→ response_subgraph
```

要求：

* 不允许 response-only。
* 必须考虑距离、营业、时间衔接、预算、场景适配。
* 可以复用 recommendation workflow 的候选能力。

### `complex_orchestrator_workflow`

```text
query_decomposer
→ subtask_validator
→ subtask_dag_builder
→ workflow_mapper
→ stage_worker_executor
→ evidence_reducer
→ conflict_resolver
→ decision_reducer
→ response_subgraph
```

要求：

* worker 输出结构化 WorkerResult，不输出最终自然语言。
* reducer 生成 GlobalEvidencePack 和 FinalDecisionPlan。
* 统一由 response_subgraph 生成最终回答。

五、`05_second_layer_contract_design.md`

请设计或建议新增这些契约对象，说明它们属于 GraphState、Domain DTO、Trace 还是 SessionState：

```python
TaskComplexity
WorkflowKind
ReviewPolicy
ExecutionBudget
ExpandSearchPolicy
RankingPolicy
ToolCallCacheKey
ToolResultCacheEntry
EvidenceCacheEntry
SubTask
SubTaskDAG
WorkerState
WorkerResult
DecisionFragment
GlobalEvidencePack
EvidenceConflict
ConflictResolution
FinalDecisionPlan
WorkflowTrace
ReduceTrace
```

必须说明：

* WorkerState 不允许写 SessionState。
* WorkerResult 可以包含 `session_write_proposal`，但不能直接持久化。
* FinalDecisionPlan 是最终回答依据。
* GlobalEvidencePack 是多 workflow 证据合并结果。
* EvidenceConflict 用于记录多个 workflow 的事实冲突。
* ConflictResolver 不能简单投票，必须基于 source、freshness、required、confidence、hard constraint 优先级裁决。

六、`06_second_layer_execution_and_cache_design.md`

请设计执行、并行、缓存和预算方案。

必须覆盖：

1. `StageToolExecutor`
   从写死 search/follow-up 两阶段，升级为支持 `ExecutionPlan.stages` 或 `SubTaskDAG` 的执行器。

2. 工具依赖 DAG
   每个 tool_call / subtask 需要：

```python
id
tool_name
args
depends_on
required
timeout_ms
retry_policy
degrade_policy
cache_key
```

3. `ToolResultCache` / `EvidenceCache`
   解决多个 worker 重复查同一家店的券、营业、距离问题。

4. request coalescing / single-flight
   如果多个 worker 同时请求同一个 cache_key，只发起一次真实工具调用。

5. freshness / TTL
   不同工具不同 TTL：

   * 营业状态：短 TTL
   * 距离 ETA：短 TTL
   * 优惠券：中 TTL
   * 店铺基础信息：较长 TTL
   * 评价摘要：较长 TTL

6. ExecutionBudget
   不同 workflow 预算不同：

```text
single_shop_fact:
  max_llm_calls = 0~1
  max_tool_calls = 1~3
  max_replan_rounds = 0

recommendation:
  max_llm_calls = 1~3
  max_tool_calls = 5~15
  max_replan_rounds = 1

comparison:
  max_llm_calls = 2~4
  max_tool_calls = N shops × facets
  max_replan_rounds = 1

complex_orchestrator:
  max_llm_calls = 3~6
  max_parallel_workers = 3~5
  max_subtask_count = 5~8
```

7. retry / replan 计数
   优先放 GraphState / ExecutionBudget，不应放 SessionState，避免跨轮污染。

七、`07_second_layer_map_reduce_design.md`

请专门设计复杂 query 的 MapReduce / Orchestrator-Worker 方案。

必须覆盖：

1. 什么时候进入 MapReduce：

   * 多阶段任务
   * 多目标对比
   * 多约束推荐
   * 推荐 + 对比混合
   * 多地点 / 多时间组合规划

2. 什么时候不进入 MapReduce：

   * 单店有券吗
   * 这家营业吗
   * 离我多远
   * 简单附近推荐

3. map 阶段：

   * query_decomposer 生成 SubTask
   * workflow_mapper 映射到 workflow worker
   * stage_worker_executor 按 DAG 执行

4. reduce 阶段：

   * EvidenceReducer 合并 EvidencePack
   * ConflictResolver 解决冲突
   * DecisionReducer 生成 FinalDecisionPlan
   * response_subgraph 统一生成最终回答

5. 不能 reduce 自然语言：

   * 错误：worker 各自生成一段话，最后拼接
   * 正确：worker 输出 EvidencePack / DecisionFragment，reducer 生成 FinalDecisionPlan

6. 冲突解决策略：

   * 工具事实优先于 LLM 推断
   * 新鲜数据优先于过期数据
   * required facet 优先于 optional facet
   * 硬约束优先于软偏好
   * 无法解决的事实冲突标记 unknown，不编造
   * 推荐结论冲突转换成 trade-off，而不是强行掩盖

7. 输出：

   * GlobalEvidencePack
   * EvidenceConflict list
   * FinalDecisionPlan
   * ReduceTrace

八、`08_second_layer_review_ranking_budget_design.md`

请设计 ReviewPolicy、RankingPolicy、ExpandSearchPolicy、BudgetPolicy。

### ReviewPolicy

按 workflow 控制 review：

```text
single_shop_fact:
  goal_review = skip / deterministic
  evidence_review = deterministic
  decision_planner = deterministic
  decision_review = skip

recommendation:
  goal_review = conditional
  evidence_review = required
  decision_planner = hybrid
  decision_review = deterministic sanity check

comparison:
  goal_review = conditional
  evidence_review = required
  decision_planner = LLM
  decision_review = deterministic sanity check

complex_orchestrator:
  evidence_review = per subtask optional
  final_decision_review = required
```

### RankingPolicy

本地生活推荐排序不能完全依赖 LLM，必须明确：

```text
hard constraints filter
→ objective scoring
→ soft preference scoring
→ scene fit scoring
→ LLM explanation / trade-off
```

硬约束示例：

* 品类
* 位置范围
* 必须营业
* 明确预算上限
* 明确不能接受的条件

软偏好示例：

* 有券
* 环境好
* 安静
* 适合约会
* 适合长辈
* 性价比高

### ExpandSearchPolicy

不能直接 `filters = {}`。必须分层放宽：

```text
1. 增加 limit
2. 扩大 radius
3. 放宽 soft preferences
4. 保留 hard constraints
5. 在回答里说明放宽了哪些条件
```

### BudgetPolicy

控制：

* max_llm_calls
* max_tool_calls
* max_parallel_workers
* max_total_latency_ms
* max_replan_rounds
* max_expand_rounds
* max_subtask_count

九、`09_second_layer_migration_plan.md`

请给出渐进式迁移计划，不要推倒重来。

建议阶段：

### Phase A：事实冻结与边界测试

* 输出第二层真实调用链
* 输出 workflow registry 矩阵
* 输出 route 字段矩阵
* 输出 review / retry / fallback 矩阵
* 不改变业务逻辑

### Phase B：策略层先行

* 新增 ReviewPolicy / ExecutionBudget / ExpandSearchPolicy 的设计和测试
* 先不拆图，只让现有 planning_subgraph 可以读取策略

### Phase C：升级 deterministic_tool → single_shop_fact_workflow

* 确保单店事实查询也走工具证据链
* 减少不必要 LLM review

### Phase D：拆 discovery_decision

* 拆出 recommendation_decision_workflow
* 拆出 comparison_decision_workflow
* 保留 discovery_decision legacy alias 一段兼容期

### Phase E：升级 ExecutionPlan.stages / StageToolExecutor

* 从两阶段 search/follow-up 逐步升级 DAG/stage 执行
* 加 ToolResultCache / EvidenceCache

### Phase F：增加 RankingPolicy 和 ExpandSearchPolicy

* 推荐排序权威从 LLM 转为 hybrid ranking
* expand_search 不再清空硬约束

### Phase G：升级 exploration_planning_workflow

* 从 response-only 升级为真实多阶段本地生活规划 workflow

### Phase H：增加 complex_orchestrator_workflow

* 只处理超复杂 query
* 引入 SubTaskDAG、WorkerResult、EvidenceReducer、DecisionReducer、ConflictResolver

### Phase I：收缩旧 planning_subgraph

* 将大 planning_subgraph 内部能力逐步拆成共享能力包
* 旧入口保留兼容，直到所有 workflow 稳定

### Phase J：最终回归与性能验收

* 全量测试
* 复杂 query E2E
* latency benchmark
* cost benchmark
* trace 完整性检查

十、`10_second_layer_test_plan.md`

请给出测试计划，不要编造当前已存在的测试文件名。新增建议测试必须用 `TODO_ADD_TEST:` 标记。

必须覆盖：

1. 简单单店事实 query 走 `single_shop_fact_workflow`，不触发完整多层 LLM review。
2. 单店事实 query 必须查工具并生成 EvidencePack。
3. 推荐 query 走 `recommendation_decision_workflow`。
4. 对比 query 走 `comparison_decision_workflow`。
5. 吃饭 + 逛街 + 咖啡等多阶段 query 走 `exploration_planning_workflow` 或 `complex_orchestrator_workflow`。
6. 超复杂 query 能被拆成 SubTaskDAG。
7. MapReduce worker 只输出 WorkerResult，不输出最终自然语言。
8. Reducer 生成 FinalDecisionPlan。
9. 多 worker 查询同一家店券/营业/距离时，只发生一次真实工具调用或命中 cache。
10. Worker 不直接写 SessionState。
11. DAG 依赖正确：先 search/resolve，再 detail/coupon/distance。
12. 不能拼接多个 workflow 的自然语言作为最终回答。
13. 冲突事实被记录为 EvidenceConflict。
14. 无法裁决的事实冲突标记 unknown。
15. 推荐冲突转成 trade-off。
16. ExpandSearchPolicy 不清空 hard constraints。
17. retry / replan counter 不跨轮污染。
18. ReviewPolicy 能让简单 query 走轻链路，复杂 query 走重链路。
19. RankingPolicy 能过滤硬约束并按软偏好排序。
20. trace 包含 router、workflow、planner、tool、evidence、review、decision、retry、fallback、reduce span。
21. latency benchmark：简单 fact query 不应明显慢于当前版本。
22. cost benchmark：简单 query LLM 调用次数下降或不增加。
23. regression：comparison / recommendation / single coupon / single shop multifacet 主链路不退化。

建议新增测试文件用：

```text
TODO_ADD_TEST: local_life_agent/tests/test_second_layer_workflow_routing.py
TODO_ADD_TEST: local_life_agent/tests/test_second_layer_single_shop_fact_workflow.py
TODO_ADD_TEST: local_life_agent/tests/test_second_layer_review_policy.py
TODO_ADD_TEST: local_life_agent/tests/test_second_layer_ranking_policy.py
TODO_ADD_TEST: local_life_agent/tests/test_second_layer_expand_search_policy.py
TODO_ADD_TEST: local_life_agent/tests/test_second_layer_execution_budget.py
TODO_ADD_TEST: local_life_agent/tests/test_second_layer_stage_executor.py
TODO_ADD_TEST: local_life_agent/tests/test_second_layer_tool_result_cache.py
TODO_ADD_TEST: local_life_agent/tests/test_second_layer_complex_orchestrator.py
TODO_ADD_TEST: local_life_agent/tests/test_second_layer_map_reduce_reducer.py
TODO_ADD_TEST: local_life_agent/tests/test_second_layer_conflict_resolver.py
TODO_ADD_TEST: local_life_agent/tests/test_second_layer_worker_state_isolation.py
TODO_ADD_TEST: local_life_agent/tests/test_second_layer_trace_contract.py
TODO_ADD_TEST: local_life_agent/tests/test_second_layer_latency_budget.py
```

最终输出要求：

1. 输出你实际扫描的文件列表。
2. 输出第二层真实调用链。
3. 输出文档与真实代码偏差。
4. 输出 P0 / P1 / P2 问题清单。
5. 输出目标架构。
6. 输出 7 个 workflow 的职责和内部流程。
7. 输出共享能力包设计。
8. 输出 MapReduce / Orchestrator-Worker 设计。
9. 输出缓存、DAG、状态隔离、Reducer、冲突解决设计。
10. 输出 ReviewPolicy、RankingPolicy、ExpandSearchPolicy、ExecutionBudget 设计。
11. 输出渐进迁移计划。
12. 输出测试计划和验收标准。
13. 所有文档写入 `todo/second_layer/`。
14. 不要修改业务代码。
15. 不要删除旧 workflow。
16. 不要声称已经完成修复。
17. 如果发现已有 Phase 2 路由权威报告结论与真实代码不一致，请单独列出，不要直接覆盖原报告。
