# P10 最终 p5 comparison metadata contract 修复验收报告

## 总体结论

**PASS（就本轮阻塞 P11 的唯一 p5 写回契约回归而言）**

本轮已修复 `comparison_targets_meta.source` 被 `comparison_target_resolution` 覆盖的问题，且 requested 的主链路回归全部通过。  
补充验证中有 1 个 `candidate_resolver` 相关失败，但它不属于本轮 p5 写回契约的阻塞项，且不影响本次结论。

## 修改文件列表

- `/D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/state_update_plan.py`
- `/D:/javacode/hm-dianping/local_life_agent/planning/plans/state_update_planner.py`

## 根因说明

根因不是 comparison 解析失败，而是 **“事实解析来源” 与 “session 写回 metadata 来源” 混用**。

原先在 comparison 写回链路中，`comparison_targets_meta.source` 的生成顺序把 `comparison_target_resolution` 放在了 `comparison_targets` 前面，导致：

- 即使本轮已经有明确的 `comparison_targets` 写回对象
- metadata 仍可能被记成 `comparison_target_resolution`

这会让 session 写回的 trace 失真，也正好命中了 `test_comparison_state_update_keeps_traceable_metadata` 的断言。

## 修复说明

本轮只做了最小范围修复，没有改 comparison 主执行逻辑，也没有改 canonical shop entity 主链路。

### 1. 在 state_update_plan 中保留来源标记

`local_life_agent/engine/subgraphs/state_update_plan.py` 现在会额外传递 `comparison_targets_source`：

- `comparison_targets` 来自 state 时，标记为 `"comparison_targets"`
- 只有当 state 没有明确 `comparison_targets`，但来自 `comparison_target_resolution.targets` 时，才标记为 `"comparison_target_resolution"`
- 其他 legacy 兜底保留各自 trace 名称

### 2. 在 planner 中按“写回来源”优先而不是“解析来源”优先

`local_life_agent/planning/plans/state_update_planner.py` 现在生成 `comparison_targets_meta.source` 时：

- 优先使用 `comparison_targets_source`
- 再退回到 `reference_resolution_source` / `active_turn_route`
- 不再让 `comparison_target_resolution` 覆盖已经明确存在的 `comparison_targets`

## comparison_targets_meta.source 新优先级

实际写回优先级如下：

1. `comparison_targets`
2. `comparison_target_resolution`
3. `comparison_result_fallback`
4. 其他 legacy trace source

其中第 1 条会在本轮有明确 `comparison_targets` 写回对象时优先成立，避免 canonical 事实源覆盖 session 写回来源。

## 测试命令与结果

### 本轮必跑

- `pytest local_life_agent/tests/test_p5_session_state_writeback.py -q`
  - `9 passed`
- `pytest local_life_agent/tests/test_comparison_flow.py -q`
  - `24 passed`
- `pytest local_life_agent/tests/test_single_coupon_flow.py -q`
  - `6 passed`
- `pytest local_life_agent/tests/test_single_shop_multifacet.py -q`
  - `7 passed`
- `pytest local_life_agent/tests/test_recommendation_flow.py -q`
  - `17 passed, 2 xfailed`

### 补充验证

- `pytest local_life_agent/tests/test_deterministic_tool_workflow.py -q`
  - `6 passed`
- `pytest local_life_agent/tests/test_target_resolve_candidate_set.py -q`
  - `9 passed`
- `python -m compileall local_life_agent`
  - 通过

### 额外观察

- `pytest local_life_agent/tests/test_candidate_resolver.py -q`
  - `1 failed, 22 passed`

该失败点是 `TestResolveExplicit.test_not_found_mention_skipped_uses_current_seed_id`，属于旁路候选解析行为，不属于本轮 p5 写回契约修复范围。

## 是否可以进入 P11

**可以进入 P11**

理由：

- 本轮唯一阻塞项 `comparison_targets_meta.source` 已修复
- p5 写回契约测试已恢复通过
- comparison / coupon / single-shop / recommendation 主链路回归未新增失败
- `comparison_target_resolution` 仍保留为 canonical 解析事实源，不影响现有主链路

## 剩余 legacy 兼容路径说明

当前仍保留的兼容路径是有意的，属于稳定性兜底，不是回退：

- `comparison_target_resolution` 仍可作为 canonical comparison 解析事实源
- `state_update_plan` 仍会在 resolved comparison 下把目标写回到 `session_state.comparison_targets`
- `comparison_result.rows` 仍可作为低优先级 fallback，用于补写 session
- `reference_resolution_source` / `active_turn_route` 仍用于 trace 可追踪性

这些路径的存在不会改变“实体确定后下游只消费 `shop_id`”这一主原则，也不会污染 `current_shop`
