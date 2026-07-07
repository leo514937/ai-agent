# 第二层：任务决策与证据层 — 架构报告（更新版）

> 当前范围：`planning/orchestration_router.py`、`engine/workflow_registry.py`、`engine/workflow_runner.py`、`engine/subgraphs/planning_subgraph.py`、`engine/subgraphs/execution_review_subgraph.py`、`planning/evidence/`、`planning/decision/`、`planning/orchestrator/`
>
> 目标：把“路由决策、目标规划、工具计划、证据构建、决策审查、复杂任务编排”统一到二层。

---

## 1. 第二层职责边界

第二层负责把第一层的 `SemanticFrame` 变成可执行的计划，并根据证据决定继续、澄清、扩展、降级还是结束。

**负责**
- 编排决策：`OrchestrationDecision`
- workflow 注册表分发
- 目标规划 / 目标审查
- `TargetResolve`
- `EvidencePlanner` / `ExecutionPlan`
- 工具执行与证据构建
- `DecisionPlan` / `DecisionReview`
- 搜索扩展、重规划、复杂编排

**不负责**
- 最终自然语言组织
- 会话持久化
- 输入级校验 / 归一化

---

## 2. 第二层总流程

```text
understanding_subgraph
  → orchestration_router_shadow（只记不改）
  → workflow_runner
  → workflow_registry lookup
  → planning_subgraph
      → goal_planner / goal_review
      → target_resolve
      → evidence_planner / plan_validator
  → execution_review_subgraph
      → tool_execute / stage executor
      → evidence_build / evidence_review
      → decision_planner / decision_review
  → response_subgraph 或 retry / clarify / fallback
```

---

## 3. 编排路由：`orchestration_router.py`

文件：[`planning/orchestration_router.py`](../local_life_agent/planning/orchestration_router.py)

它输出 `OrchestrationDecision`，核心不是“答案类型”，而是：
- `workflow_name`
- `workflow_entry_name`
- `orchestration_pattern`
- `response_mode`
- `task_complexity`
- `requires_tool`
- `requires_clarification`

当前的主分支包括：
- `direct_response`
- `single_shop_fact_workflow` / `deterministic_tool`
- `recommendation_decision_workflow`
- `comparison_decision_workflow`
- `clarification_fallback`
- `exploration_planning`
- `complex_orchestrator_workflow`

`workflow_runner.py` 会把用户可见别名映射回注册名，再调用具体 handler。

---

## 4. workflow 注册与调度

### `workflow_registry.py`

当前 registry 是白名单式的，至少包含：
- `discovery_decision`
- `recommendation_decision_workflow`
- `comparison_decision_workflow`
- `direct_response`
- `single_shop_fact_workflow`
- `deterministic_tool`（兼容别名）
- `clarification_fallback`
- `exploration_planning`
- `complex_orchestrator_workflow`

### `workflow_runner.py`

职责：
- 读取 `OrchestrationDecision`
- 查 registry
- 设置 `workflow_callable`
- 在失败时写回 fallback patch
- 保持 workflow 入口和实际执行器分离

---

## 5. 规划子图：`planning_subgraph`

文件：[`engine/subgraphs/planning_subgraph.py`](../local_life_agent/engine/subgraphs/planning_subgraph.py)

它是“计划生成层”：

1. `goal_planner`
2. `goal_review`
3. `target_resolve`
4. `evidence_planner`
5. `plan_validator`
6. `expand_search` / `ranking_policy` / `review_policy`

当前已拆出来的共享模块包括：
- `planning/goal/`
- `planning/evidence/`
- `planning/policies/`
- `planning/budget/`
- `planning/orchestrator/`

关键点：
- `ExecutionPlan.stages` 已成为明确的执行结构
- `expand_search` 是策略动作，不再清空用户硬约束
- `ExecutionBudget`、`ReviewPolicy`、`RankingPolicy` 都是可配置对象

---

## 6. 执行审查子图：`execution_review_subgraph`

文件：[`engine/subgraphs/execution_review_subgraph.py`](../local_life_agent/engine/subgraphs/execution_review_subgraph.py)

它负责把计划真正落地，再根据结果决定是否进入回答层。

执行链路大致是：
- `stage_tool_executor` / `tool_batch_executor`
- `tool_result_cache`
- `evidence_builder`
- `evidence_review`
- `decision_planner`
- `decision_review`

它还支持：
- 并行 stage 执行
- `depends_on` 拓扑
- 同轮同店同 facet 的缓存复用
- 证据不足时回到 planning_subgraph 重试或扩展搜索

---

## 7. 工具边界

工具层现在通过：
- `tools/definitions.py`
- `tools/schemas.py`
- `tools/validators.py`
- `tools/registry.py`
- `tools/gateway.py`

来统一注册、校验和调用。

第二层不能绕过 gateway 直接读数据库或直接调用未注册工具。

---

## 8. 复杂任务编排

`planning/orchestrator/` 现在承载复杂多阶段任务的 DAG / reducer / conflict resolver：
- `SubTaskDAG`
- `WorkerResult`
- `EvidenceReducer`
- `DecisionReducer`
- `ConflictResolver`

适用场景：
- 多子任务问题拆解
- 结果合并
- 矛盾证据裁决

它不是普通推荐/对比问句的默认兜底。

---

## 9. 结论

第二层已经从“单个 planning 子图”升级为“**编排 + 计划 + 执行审查 + 复杂任务 DAG**”的完整决策层。

它负责把“该查什么、怎么查、查完够不够”说清楚，并把不确定性显式传给第三层。
