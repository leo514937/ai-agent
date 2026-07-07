# 三层改造 Phase 2B：ReviewPolicy / ExecutionBudget 最小版补齐报告

## 1. 结论

**PARTIAL PASS**

本阶段补齐了第二层最小策略对象与统一读取入口，`ReviewPolicy` / `ExecutionBudget` 已可创建、可序列化、可从 `BudgetContext` 兼容构造，并接入了 `execution_review_subgraph` 和 `response_subgraph` 的最小读取点。  
但 recommendation / e2e 主链路仍有既有失败，不属于本次最小补齐可安全扩大的范围，因此不能判定为完整 PASS。

## 2. 为什么 Phase 2 原报告中 1D-a 未完成

原 Phase 2 报告里，1D-a 其实停留在“文档设计已存在、代码对象尚未补齐”的状态：

- `planning/policies/review_policy.py` 只有枚举与 `SufficiencyCheckResult`，没有真正的 `ReviewPolicy` DTO。
- `BudgetContext` 已存在，但没有统一的 `ExecutionBudget` 适配对象。
- review / rewrite / fallback / llm / tool 预算仍分散在 `BudgetContext`、`SessionState.replan_counters`、`decision_review.py` 和 `response_subgraph.py` 的局部硬编码中。

所以 Phase 2 原报告没有把 1D-a 作为已完成项，只能算前置条件明确、实现缺口未补。

## 3. 当前真实 policy / budget 实现调研结果

### 3.1 真实目录

- 真实代码目录是 `local_life_agent/planning/policies/`
- 不是文档里写的 `planning/policy/`

### 3.2 `ReviewPolicy` 现状

修改前，`review_policy.py` 只有：

- `ReviewStage`
- `ReviewStatus`
- `NextAction`
- `P0_ALLOWED_NEXT_ACTIONS`
- `SufficiencyCheckResult`
- `assert_p0_next_action_allowed()`

也就是说它还是“review 结果 DTO + 枚举”，不是统一策略对象。

### 3.3 `BudgetContext` 现状

`local_life_agent/planning/budget/budget_context.py` 已存在，且承载的是运行时预算：

- `tool_round_budget`
- `retry_budget`
- `expand_search_budget`
- `rewrite_budget`
- `facet_enrich_budget`

同时它还保存 consumed counters 和 `remaining(field)`。

### 3.4 `ExecutionBudget` 现状

修改前仓库里没有 `ExecutionBudget` 类或等价统一对象。

### 3.5 预算字段散落位置

本次调研确认，预算/轮次相关字段主要散落在：

- `planning/budget/budget_context.py`
- `domain/state.py` 的 `SessionState.replan_counters`
- `planning/decision/decision_review.py` 中的 config 常量判断
- `engine/subgraphs/response_subgraph.py` 中的 rewrite limit 计算
- `engine/subgraphs/execution_review_subgraph.py` 中的 decision review 路由计数

## 4. ReviewPolicy 最小版实现说明

本阶段在 `local_life_agent/planning/policies/review_policy.py` 内补了最小 `ReviewPolicy`：

- `max_review_rounds: int = 2`
- `max_rewrite_rounds: int = 1`
- `allow_fallback: bool = True`
- `allow_clarify: bool = True`

同时补了：

- `ReviewPolicy.from_budget_context()`
- `ReviewPolicy.from_state()`
- `review_policy_from_state()`

保留了现有 `FINISH / CLARIFY / FALLBACK` 语义，没有恢复 Phase 3 才会引入的更细分 action。

## 5. ExecutionBudget 最小版实现说明

本阶段新增了 `local_life_agent/planning/budget/execution_budget.py`：

- `max_tool_calls: int = 10`
- `max_llm_calls: int = 3`
- `max_review_rounds: int = 2`
- `max_rewrite_rounds: int = 1`

并补了：

- `ExecutionBudget.from_budget_context()`
- `ExecutionBudget.from_state()`
- `ExecutionBudget.to_budget_context()`
- `execution_budget_from_state()`
- `execution_budget_from_budget_context()`

它的定位是最小 adapter / DTO，不是替换 `BudgetContext`。

## 6. 与 BudgetContext 的关系

关系是“兼容读取 + 最小适配”，不是双体系并行：

- `BudgetContext` 继续保留为 runtime 预算容器
- `ExecutionBudget` 负责统一读取入口，便于后续阶段聚合 llm / tool / review / rewrite 的上限
- 当前实现没有复制一套新的预算状态机，也没有废弃 `BudgetContext`

## 7. 最小接入点

### 7.1 `execution_review_subgraph`

- 在 decision review 阶段接入了 `review_policy_from_state()` 和 `execution_budget_from_state()`
- `p2_review_decision()` 现在可读取这两个对象做最小限额判断

### 7.2 `response_subgraph`

- rewrite loop 的上限现在同时参考：
  - `_GRAPH_REWRITE_LIMIT`
  - `BudgetContext.remaining("rewrite_budget")`
  - `ExecutionBudget.max_rewrite_rounds`

### 7.3 `decision_review`

- `review_decision()` 现在支持可选的 `review_policy` / `execution_budget`
- `REPLAN_EVIDENCE` / `EXPAND_SEARCH` 的上限读取不再只靠单点 config 常量

## 8. 已修复 / 仍遗留

### 8.1 已修复

- `ReviewPolicy` 最小版 DTO 已补齐
- `ExecutionBudget` 最小版 DTO 已补齐
- `BudgetContext` 与 `ExecutionBudget` 兼容读取已打通
- review / rewrite 的最小读取入口已接入
- 对象可序列化、可从 state 读取

### 8.2 仍遗留

- recommendation 流仍有 4 个失败：
  - closed/detail-failed 商家仍会出现在 answer 文本中
  - `last_recommendation_list` 没有写回 session
  - 推荐后“第一家有券吗”没有触发预期的 coupon tool
- e2e 主路径仍有 2 个失败：
  - ordinal reference 场景仍落到 `clarification_fallback_workflow`
  - deictic comparison 缺少预期澄清文案

这些都不属于本次最小策略对象补齐可以安全顺手解决的范围。

## 9. 实际修改文件

- `/D:/javacode/hm-dianping/local_life_agent/planning/policies/review_policy.py`
- `/D:/javacode/hm-dianping/local_life_agent/planning/budget/execution_budget.py`
- `/D:/javacode/hm-dianping/local_life_agent/planning/budget/__init__.py`
- `/D:/javacode/hm-dianping/local_life_agent/planning/policies/__init__.py`
- `/D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/execution_review_subgraph.py`
- `/D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/response_subgraph.py`
- `/D:/javacode/hm-dianping/local_life_agent/planning/decision/decision_review.py`
- `/D:/javacode/hm-dianping/local_life_agent/tests/test_second_layer_review_policy.py`
- `/D:/javacode/hm-dianping/local_life_agent/tests/test_second_layer_execution_budget.py`

## 10. 明确没有做的后续 Phase 3 内容

本阶段没有做以下事情：

- 没有进入 Phase 3
- 没有拆 discovery_decision
- 没有新增 recommendation / comparison workflow
- 没有引入 ClaimExtractor / ClaimVerifier
- 没有引入 ResponseContract V1/V2
- 没有重写 planning_subgraph
- 没有重写 graph_builder
- 没有新增平行 policy 目录
- 没有复制 BudgetContext 形成两套预算系统
- 没有做 StageToolExecutor / ToolResultCache / RankingPolicy 可执行化
- 没有改 workflow registry 主语义

## 11. 测试结果

### 11.1 通过的定向测试

- `python -m pytest local_life_agent/tests/test_second_layer_review_policy.py -q`
- `python -m pytest local_life_agent/tests/test_second_layer_execution_budget.py -q`
- `python -m pytest local_life_agent/tests/test_workflow_runner.py -q`
- `python -m pytest local_life_agent/tests/test_workflow_registry.py -q`
- `python -m pytest local_life_agent/tests/test_deterministic_tool_workflow.py -q`
- `python -m pytest local_life_agent/tests/test_single_coupon_flow.py -q`
- `python -m pytest local_life_agent/tests/test_comparison_flow.py -q`
- `python -m pytest local_life_agent/tests/test_single_shop_multifacet.py -q`
- `python -m pytest local_life_agent/tests/test_phase7_workflows.py -q`
- `python -m pytest local_life_agent/tests/test_llm_verbalizer.py -q`
- `python -m pytest local_life_agent/tests/test_answer_verifier.py -q`

### 11.2 仍失败的回归

- `python -m pytest local_life_agent/tests/test_recommendation_flow.py -q`
  - 4 failed / 13 passed / 2 xfailed
- `python -m pytest local_life_agent/tests/test_e2e_llm_main_path.py -q`
  - 2 failed / 5 passed / 1 skipped

### 11.3 编译检查

- `python -m compileall local_life_agent`
- 通过

## 12. 是否建议进入 Phase 3

**建议可以进入 Phase 3 的设计/实现准备，但最好先把 recommendation 与 e2e 的遗留单独再做一次定位。**

原因：

- Phase 2B 的最小策略对象已经补齐，第二层基础收敛成立
- 当前遗留主要集中在 recommendation / reference / clarification 主链路
- 这些问题不属于本次 1D-a 的最小契约补齐范围，继续往下走不会自然消失
