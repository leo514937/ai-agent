# Phase 5 前置门禁阻塞报告

## 结论

FAIL

当前不能进入第 5 批 `第一层上下文与澄清边界` 的 4a / 4b 实现阶段，只能停在前置核验和阻塞说明。

## 第 4 批前置验收结果

### 已确认完成

- 3a：`RewriteInstruction` 已接入 rewrite loop。
- 3b：完整 deterministic composer 已覆盖主要 answer_type。
- 3c：ClaimExtractor / ClaimVerifier L1 可用。
- 3d：recommendation / comparison 已有真实独立 workflow。
- 3e：comparison winner 已由 matrix / RankingPolicy / DecisionPlan 结构化约束。

### 仍未完全完成

- 3f：`exploration_planning_workflow` 接入共享能力的结果是 `PARTIAL PASS`，不满足“完全完成”的前置要求。

## 修改前真实代码调研结果

本次只做门禁核验与报告复核，没有进入第 5 批代码实现。

我复核了以下已有报告与测试结论：

- `todo/three_layer_phase4c_winner_exploration_shared_capability_report.md`
- `todo/three_layer_phase4b2_workflow_split_completion_report.md`
- `todo/three_layer_phase2b_phase3_completion_report.md`
- `todo/three_layer_phase4a_rewrite_instruction_composer_report.md`

复核结论如下：

- Phase 4-C 报告结论是 `PARTIAL PASS`，不是 `PASS`。
- 4-C 报告中已经明确写出：全量测试仍剩 3 个 recommendation 流失败。
- `test_recommendation_flow.py` 的 3 个失败仍然存在，说明 recommendation 主链路的旧语义还没有完全收敛。
- `comparison_flow`、`single_coupon_flow`、`single_shop_multifacet`、`e2e_llm_main_path`、`phase3_completion_contracts` 当前都能通过，但这不足以覆盖第 5 批前置门禁里对 recommendation 主链路的要求。

## 阻塞原因

### 原因 1：Phase 4-C 不是完全完成态

第 5 批门禁明确要求先确认 3d / 3e / 3f 完成。

当前真实状态是：

- 3d 已完成
- 3e 已完成
- 3f 仍是 `PARTIAL PASS`

因此按门禁定义，第 5 批不能直接进入 4a / 4b。

### 原因 2：recommendation 主链路仍有 3 个失败

刚刚复跑的结果：

- `python -m pytest local_life_agent/tests/test_recommendation_flow.py -q`
  - `3 failed, 14 passed, 2 xfailed`

失败用例如下：

- `test_recommendation_semantic_constraints_should_surface_in_plan_and_ranking`
- `test_recommendation_ranking_score_is_recomputable`
- `test_after_recommendation_first_item_reference_works`

这些失败说明 recommendation 流还没有达到“主链路测试仍通过”的门禁要求。

### 原因 3：第 5 批门禁不只看结构，也看主链路健康度

第 5 批要求里明确写了：

- recommendation / comparison / single_shop 主链路测试仍通过

当前状态并不满足这一条，因此不能进入 4p / 4a / 4b。

## 这次复核到的测试结果

### 通过

- `python -m pytest local_life_agent/tests/test_comparison_flow.py -q`
  - `26 passed`
- `python -m pytest local_life_agent/tests/test_single_coupon_flow.py -q`
  - `6 passed`
- `python -m pytest local_life_agent/tests/test_single_shop_multifacet.py -q`
  - `7 passed`
- `python -m pytest local_life_agent/tests/test_e2e_llm_main_path.py -q`
  - `7 passed, 1 skipped`
- `python -m pytest local_life_agent/tests/test_phase3_completion_contracts.py -q`
  - `4 passed`

### 未通过

- `python -m pytest local_life_agent/tests/test_recommendation_flow.py -q`
  - `3 failed, 14 passed, 2 xfailed`

### 额外说明

- `python -m pytest local_life_agent/tests/test_recommendation_flow.py -q` 的失败与第 5 批要做的 `ContextualizedTurn / FocusContext` 无直接关系，属于推荐流既有语义回归。
- 这意味着当前阻塞不是“第 5 批实现卡住了”，而是“第 4 批前置还没有完全满足进入条件”。

## 第 5 批可否进入

结论：`不能进入`

原因很直接：

- 3f 不是完全完成态。
- recommendation 主链路仍有 3 个失败。
- 门禁要求未满足。

## 实际修改文件清单

- `todo/three_layer_phase5_precheck_blocking_report.md`

## 明确没有做的内容

- 没有做第 5 批 4p / 4a / 4b 的代码实现。
- 没有新增 `ContextualizedTurn`、`FocusContext`、`FreshnessMeta`、`LocationContext`。
- 没有改 `intake_guard_router`、`understanding_subgraph`、`merge_clarification`、`active_turn_resolver`。
- 没有改 `slot_extractor`、`context_recovery`、`reference_resolver`、`domain/state.py` 的第一层逻辑。
- 没有改 `hard_guard` 的路由权威。

## 建议的下一步

1. 先收敛 recommendation 流的 3 个历史失败。
2. 再把 Phase 4-C 的 3f 从 `PARTIAL PASS` 收到可接受的完成态。
3. 之后再重新做第 5 批前置门禁核验。
