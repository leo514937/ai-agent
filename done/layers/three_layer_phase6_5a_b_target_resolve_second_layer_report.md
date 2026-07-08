# Phase 6 / 5a-b 目标解析权威归第二层报告

## 结论

`PARTIAL PASS`

本次 5a-b 的主方向已经落地：第一层 `context_recovery` 不再产出 `resolved_target`，`understanding_subgraph` 也不再把实体解析结果写回第一层状态；第二层 `planning_subgraph` 继续承担目标解析、候选集与澄清决策。

当前已经修复了 `comparison_result` 的写回问题，比较结果可以稳定进入 `state/session`。但 comparison 后续引用 `第二家有券吗` 仍没有完全收口，第三轮仍会落到错误的单店详情/空工具路径，而不是稳定发出 `get_coupon_list`。

因此本阶段不能算 PASS，也没有进入 5a-c。

## 前置门禁验收结果

前置门禁满足，5a-b 可以开始实施：

1. 第 5 批 `4p / 4a / 4b / 4c / 4d / 4e` 已在前一阶段验收通过。
2. 第 6 批 `5a-a` 已完成，`load_session` 已拆成 `validate / load / expand`。
3. 推荐、比较、单店、优惠券、端到端主链路在本阶段修改前大体可用。
4. `ResponseContractV1 / final_response` 统一出口在前一阶段保持可用。

## 修改前真实代码调研结果

### 第一层仍有实体解析副作用

调研时确认：

1. `local_life_agent/target/context_recovery.py` 会直接调用 `resolve_references / resolve_comparison_targets`。
2. 当 `resolve_references` 返回 `RESOLVED` 时，`context_recovery` 会构造 `resolved_target`。
3. `local_life_agent/engine/subgraphs/understanding_subgraph.py` 会把 `recovered["resolved_target"]`、`comparison_targets`、`comparison_target_resolution` 写回 state。
4. `understanding_subgraph` 里还存在单店/品牌歧义的兜底解析与澄清副作用。

### 第二层 target_resolve 已存在，但依赖第一层残留

调研时确认：

1. `planning_subgraph._h_target_resolve_candidate_set` 已经是第二层实体解析入口。
2. 它会先看 `resolved_target` 做短路。
3. 比较场景下还会读 `comparison_target_resolution` / `comparison_targets`。
4. 澄清判断只覆盖了部分比较状态，比较歧义语义对齐还不够稳定。

## Rewrite / target resolve 变更后状态

### 改造前

1. 第一层 `context_recovery` 会把引用直接解析成 `resolved_target`。
2. `understanding_subgraph` 会把 `resolved_target` 写入主 state。
3. 第二层因此会被第一层结果短路，`target_resolve` 权威不清晰。

### 改造后

1. `local_life_agent/target/context_recovery.py` 只返回第一层信号：
   - `context_resolution`
   - `reference_resolution_source`
   - `comparison_reference_signal`
2. 不再返回 `resolved_target`。
3. `understanding_subgraph` 不再把 `resolved_target` / 第一层解析结果写回 state。
4. 第二层 `planning_subgraph._h_target_resolve_candidate_set` 继续负责实体解析、候选集、澄清和最终 `resolve_shop_result`。

## `_h_rewrite` / RewriteInstruction 消费情况

本阶段不改 `rewrite loop` 主体，只处理第二层 target resolve authority 与 comparison follow-up 路径。

## 第二层 target_resolve 入口说明

当前真正的第二层目标解析入口仍是：

1. `local_life_agent/engine/subgraphs/planning_subgraph.py::_h_target_resolve`
2. `local_life_agent/engine/subgraphs/planning_subgraph.py::_h_target_resolve_candidate_set`

本次只调整了其输入依赖与部分澄清判定，不重写整套 `planning_subgraph`。

## planning_subgraph 收缩情况

本阶段没有进入完整 5a-c，因此 `planning_subgraph` 仍然保留原有业务逻辑，不是纯 dispatch 层。

本次只做了两个收口动作：

1. 比较澄清判定增加了 `AMBIGUOUS` / `PARTIAL` 一类容错分支。
2. `comparison_result` 的 session writeback 已补齐，避免比较结果在 state update 时丢失。

## 已修改文件清单

1. [`local_life_agent/target/context_recovery.py`](../local_life_agent/target/context_recovery.py)
2. [`local_life_agent/engine/subgraphs/understanding_subgraph.py`](../local_life_agent/engine/subgraphs/understanding_subgraph.py)
3. [`local_life_agent/engine/subgraphs/planning_subgraph.py`](../local_life_agent/engine/subgraphs/planning_subgraph.py)
4. [`local_life_agent/engine/subgraphs/state_update_plan.py`](../local_life_agent/engine/subgraphs/state_update_plan.py)
5. [`local_life_agent/planning/plans/state_update_planner.py`](../local_life_agent/planning/plans/state_update_planner.py)
6. [`local_life_agent/target/reference_resolver.py`](../local_life_agent/target/reference_resolver.py)
7. [`local_life_agent/planning/goal/goal_draft.py`](../local_life_agent/planning/goal/goal_draft.py)
8. [`local_life_agent/engine/subgraphs/execution_review_subgraph.py`](../local_life_agent/engine/subgraphs/execution_review_subgraph.py)
9. [`local_life_agent/planning/orchestration_router.py`](../local_life_agent/planning/orchestration_router.py)

## 没有做的 5a-c 内容

1. 没有进入 `planning_subgraph` 的完整收缩为 dispatch / orchestration 层。
2. 没有拆出 `GoalPlanner / TargetResolver / EvidencePlanner / PlanValidator` 的共享 service。
3. 没有继续做 recommendation / comparison / single_shop 全量共用 service 迁移。
4. 没有继续修改 StageToolExecutor / ToolResultCache 主逻辑。

## 测试结果

### 通过

1. `python -m pytest local_life_agent/tests/test_phase3_completion_contracts.py -q`
2. `python -m pytest local_life_agent/tests/test_phase5_context_trace_v0.py -q`
3. `python -m pytest local_life_agent/tests/test_recommendation_flow.py::test_after_recommendation_first_item_reference_works -q`
4. `python -m pytest local_life_agent/tests/test_recommendation_flow.py::test_recommendation_success_updates_last_recommendation_list_not_current_shop -q`
5. `python -m pytest local_life_agent/tests/test_comparison_flow.py::test_compare_three_from_last_recommendation_list -q`
6. `python -m pytest local_life_agent/tests/test_comparison_flow.py::test_comparison_success_writes_comparison_result_not_overwrite_recommendation_list -q`
7. `python -m pytest local_life_agent/tests/test_e2e_llm_main_path.py::test_comparison_main_path_uses_llm_end_to_end -q`
8. `python -m compileall local_life_agent`

### 仍失败

1. `local_life_agent/tests/test_comparison_flow.py::test_after_comparison_second_item_reference_still_works`

### 说明

当前失败已经从“比较结果写回”收敛到“比较后的二次引用”这一条回归：

- `comparison_result` 已可以写回。
- `第二家有券吗` 仍会在后续链路中丢到错误的单店详情/空工具路径。
- 这说明 comparison follow-up 的工具路由还没有完全收口。

## 是否建议进入 5a-c

`暂不建议立即进入`

原因：

1. 5a-b 仍是 `PARTIAL PASS`，comparison 后续引用仍有回归。
2. 如果现在继续做 5a-c，会把 `planning_subgraph` 收缩问题和当前 comparison 回归混在一起，排障成本会更高。
3. 建议先把“第二家有券吗”这类 comparison follow-up 的工具路由稳定下来，再推进 5a-c。
