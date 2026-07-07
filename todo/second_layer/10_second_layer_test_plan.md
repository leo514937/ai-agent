# 第二层测试计划

本文件只给出测试覆盖与验收标准，不编造现有测试文件名。

## 1. 现有可复用测试

当前仓库里已经有下面这些相关测试，可以优先复用：

- `local_life_agent/tests/test_goal_planner.py`
- `local_life_agent/tests/test_evidence_planner.py`
- `local_life_agent/tests/test_execution_plan_validator.py`
- `local_life_agent/tests/test_planning_execution_boundary.py`
- `local_life_agent/tests/test_deterministic_tool_workflow.py`
- `local_life_agent/tests/test_workflow_runner.py`
- `local_life_agent/tests/test_phase2_routing_authority.py`
- `local_life_agent/tests/test_p9_evidence_planner_capability_budget.py`
- `local_life_agent/tests/test_p10_experience_performance.py`
- `local_life_agent/tests/test_p12_deadline_budget_freshness_ttl.py`
- `local_life_agent/tests/test_subgraph_core_integration.py`

这些测试已经覆盖了部分 validator、workflow dispatch、deterministic workflow、budget、TTL、路由优先级等内容。具体位置：

| 测试文件 | 覆盖内容 | 代码位置 |
|---|---|---|
| `test_goal_planner.py` | GoalPlanner + GoalReview | [tests/test_goal_planner.py](D:/javacode/hm-dianping/local_life_agent/tests/test_goal_planner.py) |
| `test_evidence_planner.py` | EvidencePlanner 计划生成 | [tests/test_evidence_planner.py](D:/javacode/hm-dianping/local_life_agent/tests/test_evidence_planner.py) |
| `test_execution_plan_validator.py` | ExecutionPlanValidator 校验 | [tests/test_execution_plan_validator.py](D:/javacode/hm-dianping/local_life_agent/tests/test_execution_plan_validator.py) |
| `test_planning_execution_boundary.py` | planning 到 execution 边界 | [tests/test_planning_execution_boundary.py](D:/javacode/hm-dianping/local_life_agent/tests/test_planning_execution_boundary.py) |
| `test_deterministic_tool_workflow.py` | 确定性工具工作流 | [tests/test_deterministic_tool_workflow.py](D:/javacode/hm-dianping/local_life_agent/tests/test_deterministic_tool_workflow.py) |
| `test_workflow_runner.py` | workflow dispatch | [tests/test_workflow_runner.py](D:/javacode/hm-dianping/local_life_agent/tests/test_workflow_runner.py) |
| `test_phase2_routing_authority.py` | 路由优先级 | [tests/test_phase2_routing_authority.py](D:/javacode/hm-dianping/local_life_agent/tests/test_phase2_routing_authority.py) |
| `test_p9_evidence_planner_capability_budget.py` | 证据计划能力和预算 | [tests/test_p9_evidence_planner_capability_budget.py](D:/javacode/hm-dianping/local_life_agent/tests/test_p9_evidence_planner_capability_budget.py) |
| `test_p10_experience_performance.py` | 性能和延迟基准 | [tests/test_p10_experience_performance.py](D:/javacode/hm-dianping/local_life_agent/tests/test_p10_experience_performance.py) |
| `test_p12_deadline_budget_freshness_ttl.py` | 截止时间、预算、freshness | [tests/test_p12_deadline_budget_freshness_ttl.py](D:/javacode/hm-dianping/local_life_agent/tests/test_p12_deadline_budget_freshness_ttl.py) |
| `test_subgraph_core_integration.py` | 子图核心集成 | [tests/test_subgraph_core_integration.py](D:/javacode/hm-dianping/local_life_agent/tests/test_subgraph_core_integration.py) |

## 2. 建议新增测试

如果当前没有对应的更细粒度测试，建议补以下文件：

- `TODO_ADD_TEST: local_life_agent/tests/test_second_layer_plan_compiler.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_second_layer_plan_validator.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_second_layer_stage_executor.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_second_layer_dag_trace.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_second_layer_router_boundary.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_second_layer_workflow_routing.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_second_layer_single_shop_fact_workflow.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_second_layer_review_policy.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_second_layer_ranking_policy.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_second_layer_expand_search_policy.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_second_layer_execution_budget.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_second_layer_tool_result_cache.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_second_layer_complex_orchestrator.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_second_layer_map_reduce_reducer.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_second_layer_conflict_resolver.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_second_layer_worker_state_isolation.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_second_layer_trace_contract.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_second_layer_latency_budget.py`

## 3. 必覆盖 case

### 1. 简单单店事实 query 走 `single_shop_fact_workflow`

- 不触发完整多层 LLM review
- 必须查工具
- 必须生成 `EvidencePack`

### 2. 单店事实 query 必须查工具并生成 `EvidencePack`

- 不能纯 LLM 回答
- 工具失败必须显式返回

### 3. 推荐 query 走 `recommendation_decision_workflow`

- 推荐排序要经过 `RankingPolicy`

### 4. 对比 query 走 `comparison_decision_workflow`

- 多店证据并行查
- 输出比较矩阵

### 5. 吃饭 + 逛街 + 咖啡等多阶段 query 走 `exploration_planning_workflow` 或 `complex_orchestrator_workflow`

- 当前 `run_exploration_planning_workflow`（[exploration_planning_workflow.py:840-1114](D:/javacode/hm-dianping/local_life_agent/engine/workflows/exploration_planning_workflow.py#L840)）已不是 response-only，有 `_tool_round_search` 和 `_tool_round_expand` 两轮工具调用
- 升级后应确保：
  - 多阶段之间有跨阶段依赖协调（时间、距离、预算衔接）
  - 使用共享能力包而非自包含实现
  - 输出经由 `response_subgraph` 统一处理

### 6. 超复杂 query 能被拆成 `SubTaskDAG`

- `query_decomposer` 产出子任务
- 子任务有明确依赖

### 7. MapReduce worker 只输出 `WorkerResult`

- worker 不输出最终自然语言

### 8. Reducer 生成 `FinalDecisionPlan`

- 最终回答必须由 reducer + response_subgraph 统一产出

### 9. 多 worker 查询同一家店券 / 营业 / 距离时，只发生一次真实工具调用

- `ToolResultCache` 或 single-flight 生效

### 10. Worker 不直接写 `SessionState`

- 只能产出 `session_write_proposal`

### 11. DAG 依赖正确

- 先 `search/resolve`
- 再 `detail/coupon/distance`

### 12. 不能拼接多个 workflow 的自然语言作为最终回答

- 要有结构化 reducer 输出

### 13. 冲突事实被记录为 `EvidenceConflict`

- 同一 facet 冲突必须留痕

### 14. 无法裁决的事实冲突标记 unknown

- 不得编造

### 15. 推荐冲突转成 trade-off

- 不强行掩盖冲突

### 16. `ExpandSearchPolicy` 不清空 hard constraints

- 只放宽可放宽项

### 17. retry / replan counter 不跨轮污染

- 计数放在执行态或预算态

### 18. `ReviewPolicy` 能让简单 query 走轻链路，复杂 query 走重链路

- 轻量事实查询跳过不必要 review

### 19. `RankingPolicy` 能过滤硬约束并按软偏好排序

- 硬约束先过滤，软偏好后排序

### 20. trace 包含 router、workflow、planner、tool、evidence、review、decision、retry、fallback、reduce span

- 每个阶段都有可读 trace

### 21. latency benchmark

- 简单 fact query 不应明显慢于当前版本

### 22. cost benchmark

- 简单 query LLM 调用次数下降或不增加

### 23. regression

- comparison / recommendation / single coupon / single shop multifacet 主链路不退化

## 4. 建议回归顺序

1. 先跑现有第二层相关测试
2. 再补 compiler / validator / executor / cache 的单测
3. 然后补 workflow / reducer / trace 的集成测试
4. 最后补简单 fact 和复杂 orchestrator 的端到端回归

## 5. 验收标准

- LLM 不能直接把非法 DAG 推进执行
- validator 能拦住非法工具、非法依赖、环、超预算、非法 shop_id
- executor 必须尊重 DAG / stage / cache / degrade
- router 只负责 workflow 选择
- 轻量事实路径和重型 DAG 路径边界清晰
- DAG trace 能把每次执行决策说清楚

## 6. 完整验收标准与测试映射表

| # | 验收标准 | TODO_ADD_TEST |
|---|---|---|
| 1 | 简单单店事实 query 走 single_shop_fact_workflow | test_second_layer_single_shop_fact_workflow.py |
| 2 | 单店必须查工具并生成 EvidencePack | test_second_layer_single_shop_fact_workflow.py |
| 3 | 推荐 query 走 recommendation_decision_workflow | test_second_layer_workflow_routing.py |
| 4 | 对比 query 走 comparison_decision_workflow | test_second_layer_workflow_routing.py |
| 5 | 多阶段 query 走 exploration/complex | test_second_layer_workflow_routing.py |
| 6 | 超复杂 query 被拆成 SubTaskDAG | test_second_layer_complex_orchestrator.py |
| 7 | MapReduce worker 只输出 WorkerResult | test_second_layer_complex_orchestrator.py |
| 8 | Reducer 生成 FinalDecisionPlan | test_second_layer_map_reduce_reducer.py |
| 9 | 多 worker 重复查询只一次真实调用 | test_second_layer_tool_result_cache.py |
| 10 | Worker 不直接写 SessionState | test_second_layer_worker_state_isolation.py |
| 11 | DAG 依赖正确（先 search 再 detail） | test_second_layer_stage_executor.py |
| 12 | 不能拼接多个 workflow 自然语言 | test_second_layer_map_reduce_reducer.py |
| 13 | 冲突事实记录为 EvidenceConflict | test_second_layer_conflict_resolver.py |
| 14 | 无法裁决标记 unknown | test_second_layer_conflict_resolver.py |
| 15 | 推荐冲突转 trade-off | test_second_layer_conflict_resolver.py |
| 16 | ExpandSearchPolicy 不清空 hard constraints | test_second_layer_expand_search_policy.py |
| 17 | retry/replan counter 不跨轮污染 | test_second_layer_execution_budget.py |
| 18 | ReviewPolicy 轻重分流 | test_second_layer_review_policy.py |
| 19 | RankingPolicy 过滤硬约束 | test_second_layer_ranking_policy.py |
| 20 | trace 包含所有 span | test_second_layer_trace_contract.py |
| 21 | latency benchmark | test_second_layer_latency_budget.py |
| 22 | cost benchmark | test_second_layer_latency_budget.py |
| 23 | regression | 现有测试 |

## 7. TODO_ADD_TEST 完整清单（15 个）

- `TODO_ADD_TEST: local_life_agent/tests/test_second_layer_workflow_routing.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_second_layer_single_shop_fact_workflow.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_second_layer_review_policy.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_second_layer_ranking_policy.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_second_layer_expand_search_policy.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_second_layer_execution_budget.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_second_layer_stage_executor.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_second_layer_tool_result_cache.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_second_layer_complex_orchestrator.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_second_layer_map_reduce_reducer.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_second_layer_conflict_resolver.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_second_layer_worker_state_isolation.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_second_layer_trace_contract.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_second_layer_latency_budget.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_second_layer_plan_compiler.py`

