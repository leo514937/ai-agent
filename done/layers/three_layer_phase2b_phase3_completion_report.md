# 三层改造 Phase 2-B + Phase 3 完成报告

## 1. 结论

**PARTIAL PASS**

本次已经完成 Phase 2-B 的最小闭环补完，并完成 Phase 3 的核心实现收敛：

- 统一了 `final_response` 的图内出口，`response_subgraph._h_final_response` 成为主写入点。
- 补齐了 `RewriteInstruction` 的最小接入。
- 收敛了 `single_shop_fact_workflow` 主入口与 `deterministic_tool` legacy alias。
- 补齐了 `ReviewPolicy / ExecutionBudget` 的最小读取闭环。
- 完成了 `RankingPolicy / ExpandSearchPolicy` 的最小可执行收敛。
- 增加了 `ToolResultCache` / single-flight 风格批内去重。
- 增加了 `StageToolExecutor v1`。
- 增加了 `ResponseContractV1`。

但全量测试仍有一批旧语义 / 旧断言失败，说明仓库整体还处于“核心链路已稳住，但旧测试矩阵并未完全与新语义对齐”的状态，因此不能记为 PASS。

## 2. 修改前真实代码调研结果

调研结论基于仓库内真实实现，不按文档假设直接改：

- `planning/budget/budget_context.py` 已存在，且可作为预算读取入口。
- `planning/budget/execution_budget.py` 已存在，说明预算 DTO 不是本次新造。
- `planning/policies/review_policy.py` 已存在，且已经能从 state 读出 review policy。
- `planning/policies/ranking_policy.py` 之前主要是函数式逻辑，本次补了最小 DTO 和硬约束过滤。
- `engine/workflow_registry.py` 里 `single_shop_fact_workflow` 已经是语义主入口，`deterministic_tool` 只是 alias。
- `engine/workflow_runner.py` 已能消费上述别名，不需要重写 registry 主语义。
- `engine/subgraphs/response_subgraph.py` 是回答层统一出口的核心位置。
- `engine/subgraphs/execution_review_subgraph.py` 仍是工具执行 / 证据构建 / review 的关键桥接点。
- `answer/response_directive.py`、`answer/rewrite_instruction.py`、`answer/composers/` 已存在，适合做复用与兼容，不适合重造 DTO。

## 3. Phase 2-B 补完情况

### 3.1 `final_response` 统一出口

已完成图内统一出口收敛：

- `response_subgraph._h_final_response` 负责生成 `final_response`、`preview_text`、`response_directive`、`response_contract_v1`。
- direct / clarify / fallback / deterministic_tool / exploration 的最终文本尽量都回到同一出口派生。
- `engine/workflows/exploration_planning_workflow.py` 已去掉直接写 `final_response` 的路径。

同时保留了少量 legacy bypass 的兼容读取，避免旧路径因为历史状态字段不完整而直接空回答。

### 3.2 `RewriteInstruction` 最小接入

已完成最小接入：

- `_h_answer_verify` 在空 evidence / 空 draft 时会生成 `RewriteInstruction`。
- verifier failure 会携带 `rewrite_instruction` 进入 rewrite loop。
- `_h_rewrite` 会保留 instruction，并继续走 verbalizer / fallback 的最小循环。

本阶段没有引入 claim-driven rewrite，也没有引入 ClaimExtractor / ClaimVerifier。

### 3.3 `single_shop_fact_workflow` 主入口收敛

已确认并保留：

- `single_shop_fact_workflow` 是 registry 主入口。
- `deterministic_tool` 保持 legacy alias。
- 未复制平行 workflow。

### 3.4 `ReviewPolicy / ExecutionBudget` 最小闭环

已补齐：

- `ReviewPolicy` 和 `ExecutionBudget` 可从现有 `BudgetContext` 读取。
- review round、rewrite round、tool call / llm call 的默认值可以统一消费。
- 没有引入独立预算系统，也没有替换 `BudgetContext`。

## 4. `final_response` 写入点修改前后对比

### 修改前

- 多个 workflow / fallback 节点存在分散写入或直写最终文本的历史路径。
- 某些路径依赖 `final_response` 之外的字段，但终端输出只看 `final_response`，容易出现空回答。

### 修改后

- 图内主出口统一到 `response_subgraph._h_final_response`。
- `response_contract_v1` 由统一出口派生。
- `agent.py` 增加了一个很窄的终端兼容提取，优先读 `final_response`，再读 `draft_response` / `preview_text` / `response_directive` / `response_contract_v1`，用于兜底旧路径。

这层兼容是为了保证旧测试和 legacy bypass 不会直接变成空回答，不是新的第二套最终出口。

## 5. 4 个 workflow bypass 收敛情况

已收敛的部分：

- `direct_response_workflow`
- `clarification_fallback_workflow`
- `deterministic_tool_workflow`
- `exploration_planning_workflow`

这些流程现在不再各自独立维护一套最终回答出口，而是尽量把结果回流到统一响应层。

仍保留的 legacy 兼容：

- 部分旧路由与旧 state 字段仍存在兼容读取。
- `agent.py` 终端出参仍保留了对 `draft_response` / `response_directive` / `response_contract_v1` 的窄兜底。

## 6. RewriteInstruction 接入方式

接入方式是最小化的：

- verifier 在失败时生成 `RewriteInstruction`。
- rewrite loop 读取该 instruction，但不做 claim 级别重写。
- 失败 / disabled / timeout 情况优先回落到 deterministic composer 或可信降级回答。

## 7. `single_shop_fact_workflow` 主入口与 legacy alias

- `single_shop_fact_workflow` 作为语义主入口保留。
- `deterministic_tool` 继续作为兼容 alias。
- 没有复制出另一套 workflow，也没有改 registry 主语义。

## 8. ReviewPolicy / ExecutionBudget 最小闭环说明

已完成的最小对象 / 读取路径：

- `ReviewPolicy`
- `ExecutionBudget`
- `BudgetContext`

当前只做最小接入：

- review / rewrite 的上限可读。
- tool call / llm call 的预算可读。
- 默认值保守。

未做：

- 完整策略编排框架
- StageToolExecutor 的全功能调度
- RankingPolicy 的复杂策略系统

## 9. Phase 3 完成情况

### 9.1 RankingPolicy / ExpandSearchPolicy

已实现最小收敛：

- hard constraints 先过滤再排序。
- closed / failed / detail_failed 候选不会进入最终推荐结果。
- `score_candidate` 输出 `failed_constraints` 和 `provenance`。
- `ExpandSearchPolicy` 提供最小策略对象，不清空用户 hard constraints。

### 9.2 ToolResultCache / single-flight

已实现最小批内去重：

- 同一批次同 `shop_id + facet + args + query_scope` 的调用会去重。
- cache hit 不会重复触发真实调用。
- 缓存范围限定在 run / batch 范围，没有引入全局缓存系统。

### 9.3 StageToolExecutor v1

已实现最小阶段执行器：

- 读取 `ExecutionPlan.stages`。
- 按 stage 顺序执行。
- `depends_on` 未满足时不提前执行。
- 同 stage 内仍复用批执行。

### 9.4 ResponseContract V1

已实现最小 V1：

- `answer_text`
- `answer_type`
- `response_mode`
- `trace_id`
- `verifier_result`
- `fallback_reason`
- `uncertainty_notices`

并可由 `ResponseDirective` 派生。

## 10. `last_recommendation_list` / recommendation 写回

本阶段保留了推荐链路的现有写回路径，并修补了批执行结果的规范化，避免测试桩返回“业务原始结果”时导致 `ToolResult` 解析失败。

推荐结果写回仍以会话状态更新路径为准，没有改成分散写字段。

## 11. 实际修改文件清单

新增：

- [`local_life_agent/answer/response_contract.py`](../local_life_agent/answer/response_contract.py)
- [`local_life_agent/planning/evidence/tool_result_cache.py`](../local_life_agent/planning/evidence/tool_result_cache.py)
- [`local_life_agent/planning/evidence/stage_tool_executor.py`](../local_life_agent/planning/evidence/stage_tool_executor.py)
- [`local_life_agent/tests/test_phase3_completion_contracts.py`](../local_life_agent/tests/test_phase3_completion_contracts.py)

修改：

- [`local_life_agent/agent.py`](../local_life_agent/agent.py)
- [`local_life_agent/answer/__init__.py`](../local_life_agent/answer/__init__.py)
- [`local_life_agent/domain/graph_state.py`](../local_life_agent/domain/graph_state.py)
- [`local_life_agent/engine/subgraphs/response_subgraph.py`](../local_life_agent/engine/subgraphs/response_subgraph.py)
- [`local_life_agent/engine/subgraphs/execution_review_subgraph.py`](../local_life_agent/engine/subgraphs/execution_review_subgraph.py)
- [`local_life_agent/engine/workflows/exploration_planning_workflow.py`](../local_life_agent/engine/workflows/exploration_planning_workflow.py)
- [`local_life_agent/engine/workflows/direct_response_workflow.py`](../local_life_agent/engine/workflows/direct_response_workflow.py)
- [`local_life_agent/engine/workflows/clarification_fallback_workflow.py`](../local_life_agent/engine/workflows/clarification_fallback_workflow.py)
- [`local_life_agent/engine/workflows/deterministic_tool_workflow.py`](../local_life_agent/engine/workflows/deterministic_tool_workflow.py)
- [`local_life_agent/planning/evidence/__init__.py`](../local_life_agent/planning/evidence/__init__.py)
- [`local_life_agent/planning/policies/__init__.py`](../local_life_agent/planning/policies/__init__.py)
- [`local_life_agent/planning/policies/ranking_policy.py`](../local_life_agent/planning/policies/ranking_policy.py)
- [`local_life_agent/tools/gateway.py`](../local_life_agent/tools/gateway.py)

## 12. 明确没有做的后续内容

本次没有做，也不应被误认为已完成：

- ResponseContract V2
- ClaimExtractor / ClaimVerifier
- ContextualizedTurn / FocusContext
- Redis SessionStore
- complex_orchestrator / MapReduce
- recommendation / comparison 独立 workflow 重拆
- workflow registry 主语义改造
- 第一层输入结构大改
- 第二层完整策略框架重构

## 13. 测试结果

### 已通过的重点回归

- `python -m pytest local_life_agent/tests/test_phase3_completion_contracts.py -q`
  - `4 passed`
- `python -m pytest local_life_agent/tests/test_single_coupon_flow.py -q`
  - `6 passed`
- `python -m pytest local_life_agent/tests/test_comparison_flow.py -q`
  - `24 passed`
- `python -m pytest local_life_agent/tests/test_single_shop_multifacet.py -q`
  - `7 passed`
- `python -m pytest local_life_agent/tests/test_deterministic_tool_workflow.py -q`
  - `3 passed`
- `python -m pytest local_life_agent/tests/test_workflow_runner.py -q`
  - `6 passed`
- `python -m pytest local_life_agent/tests/test_phase7_workflows.py -q`
  - `10 passed`
- `python -m pytest local_life_agent/tests/test_recommendation_flow.py -q`
  - `17 passed, 2 xfailed`
- `python -m pytest local_life_agent/tests/test_e2e_llm_main_path.py -q`
  - `7 passed, 1 skipped`
- `python -m pytest local_life_agent/tests/test_comprehensive_graph_e2e.py -q`
  - `27 passed`
- `python -m pytest local_life_agent/tests/test_llm_verbalizer.py -q`
  - `14 passed`
- `python -m pytest local_life_agent/tests/test_answer_verifier.py -q`
  - `23 passed`
- `python -m compileall local_life_agent`
  - 通过

### 全量回归结果

- `python -m pytest local_life_agent/tests -q`
- 结果：`1284 passed, 50 failed, 37 skipped, 2 xfailed`

### 全量失败的主要性质

失败集中在以下几类：

- 旧的单元测试仍假设 `answer_verify` 在空 evidence / 空 draft 下默认 pass。
- 一些 clarification / pending / prompt 文案的旧断言仍按旧文本匹配。
- 一些 goal draft / planner 边界测试仍基于旧状态访问方式。
- 一些 semantic / router / planning 边界测试与当前新语义不完全一致。

这些失败说明仓库里仍有一批历史测试与新的安全边界、统一出口语义没有完全同步。

## 14. 是否建议进入 Phase 4

**暂不建议直接进入 Phase 4。**

建议先做一次专门的“旧测试矩阵语义对齐”或“历史失败修复”批次，重点处理：

- clarification 文案统一
- `answer_verify` 旧断言迁移
- planner / goal draft 的边界兼容
- router 旧语义测试清理

当前阶段的核心结构已经收敛，但全量测试仍未收敛到稳定通过，因此更适合先做一轮语义对齐，再进入下一阶段。
