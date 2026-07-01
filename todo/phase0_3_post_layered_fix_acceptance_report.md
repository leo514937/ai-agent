# Phase 0-3 Post Layered Fix Acceptance Report

## 1. 总体结论

**FAIL**

结论原因不是主链路整体崩坏，而是仍然存在一条运行时代码契约回退：

- `local_life_agent/planning/decision/decision_planner.py` 里，`winner_shop_id` 在证据不足或平局时仍会从 `ranking_snapshot` 兜底生成。
- 这与本次验收要求里的硬约束冲突：`winner_shop_id` 只能来自 decision 层的证据决策，不能来自 `ranking_snapshot` fallback。

当前判断：

- 是否可以进入 Phase 4 设计：**不建议**
- 是否可以进入 Phase 4 实现：**不建议**
- 下一步最小动作：**继续修 Phase 0-3，先移除 winner 兜底回退，再复核剩余测试期待是否需要同步更新**

## 2. 本轮修复报告复核

复核对象：[`todo/phase0_3_p0_p1_layered_fix_report.md`](D:/javacode/hm-dianping/todo/phase0_3_p0_p1_layered_fix_report.md)

该报告中的 4 个修复声明，当前源码与测试能证明其中大部分是成立的，但还不足以证明状态契约完全锁死：

1. 候选解析收口：基本成立。`planning_subgraph` 已经区分多候选与单目标，不再把多候选直接打回 `NOT_FOUND`。
2. 单店答案稳定化：基本成立。`response_subgraph` 已经有单店确定性摘要补强。
3. Verifier 兼容层：基本成立。`b2_mini_verifier` 与 `answer/verifier.py` 都有兼容路径。
4. `ExecutionPlan` fallback 结构补齐：成立。

但该报告没有解决最关键的残余问题：

- **`candidate_set_resolved ≠ target_resolved ≠ winner_decided` 仍未被完全锁死**
- 主要原因是 `decision_planner` 仍能在证据不足时从 `ranking_snapshot` 选 winner

所以，前一轮修复报告的“已收口”结论只能算**部分成立**，不能作为 Phase 0-3 彻底验收通过的依据。

## 3. Candidate / Target / Winner 分层验收

### CandidateSet

当前状态是对的：

- `candidate_set` 仍然表示候选召回结果
- 多候选 recommendation / comparison 已经不会再被误打成 `NOT_FOUND`
- `planning_subgraph` 对多候选场景已经能产出 `CANDIDATE_SET_RESOLVED`

相关证据：

- [`local_life_agent/engine/subgraphs/planning_subgraph.py`](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/planning_subgraph.py)
- [`local_life_agent/tests/test_target_resolve_candidate_set.py`](D:/javacode/hm-dianping/local_life_agent/tests/test_target_resolve_candidate_set.py)
- [`local_life_agent/tests/test_comparison_flow.py`](D:/javacode/hm-dianping/local_life_agent/tests/test_comparison_flow.py)
- [`local_life_agent/tests/test_recommendation_flow.py`](D:/javacode/hm-dianping/local_life_agent/tests/test_recommendation_flow.py)

### Target

当前状态基本正确：

- `resolved_target` / `resolve_shop_result` 仍然只表示明确目标解析
- `state_update_plan` 里仍然把 `current_shop` 限制在明确目标场景
- 推荐 / 对比的多候选结果不会直接写成 `current_shop`

相关证据：

- [`local_life_agent/planning/plans/state_update_planner.py`](D:/javacode/hm-dianping/local_life_agent/planning/plans/state_update_planner.py)
- [`local_life_agent/engine/subgraphs/state_update_plan.py`](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/state_update_plan.py)

### Winner

这里仍有硬问题：

- `winner_shop_id` 确实只在 decision 层产生
- 但是 `decision_planner._find_winner_from_evidence()` 在证据不足或平局时，仍然会回退到 `ranking_snapshot`
- 这意味着 `winner_shop_id` 仍然可能间接来自 `ranking_snapshot`

这条路径与验收要求冲突，是本轮 **FAIL** 的核心原因。

相关证据：

- [`local_life_agent/planning/decision/decision_planner.py`](D:/javacode/hm-dianping/local_life_agent/planning/decision/decision_planner.py)

### 补充说明

- `comparison_targets` 已经能作为独立的对比目标集合使用
- `resolution_stage` 已经出现在主链路中，且能区分候选集已解、单目标已解等阶段
- 但这些分层虽然“能用”，还没有把 winner 兜底彻底切断

## 4. 链路回归验收

### comparison

通过。

- `test_comparison_flow.py` 全绿
- 多候选 comparison 可继续走 evidence / decision，不再误入 `NOT_FOUND`

### recommendation

通过主链路回归。

- `test_recommendation_flow.py` 全绿，只有 `2 xfailed`
- 推荐后续引用、写回门禁、不会误写 `current_shop` 这些核心点都通过

### single_shop_multifacet

通过。

- `test_single_shop_multifacet.py` 通过
- `current_shop` 写回门禁也通过专项测试

### single_coupon

通过。

- `test_single_coupon_flow.py` 通过

### p2_end_to_end

通过。

- `test_p2_end_to_end.py` 通过

### comprehensive_graph_e2e

通过。

- `test_comprehensive_graph_e2e.py` 通过

### 需要特别说明的 e2e_llm_main_path

该套件里有 4 个失败，但更像是“测试期待过旧”或“语义策略已变化”，不是主链路回退：

- 推荐 / 比较场景里，测试还在期待 `ranking_snapshot.overall_ranked` 为空，但当前 evidence pack 已保留排序快照
- `ordinal_reference_prefers_semantic_frame` 期待 `resolve_references()` 不返回目标，但当前实现对“第一家”会正常解析到推荐列表中的首家
- `deictic` 相关断言也更偏向旧的澄清话术，当前实现已经更倾向于利用上下文做解析或候选提示

这些失败暂时不构成 Phase 0-3 主链路 blocker，但属于需要回看测试语义的残余项。

## 5. Answer / Verifier / Fallback 验收

当前结论是“基本通过，但仍有边界风险”。

通过点：

- `response_subgraph` 的单店 deterministic summary 主要从 `EvidencePack` 组装，不是在 answer 层重新选店
- `answer/verifier.py` 仍然在做最终校验，不是摆设
- `template_fallback` / `llm_disabled` 路径在日志和 metadata 中是可见的

残余风险：

- `decision_planner` 仍然使用 `ranking_snapshot` 作为 winner 兜底，导致 answer 层最终仍可能拿到一个“不是纯证据推出来的 winner”

相关证据：

- [`local_life_agent/engine/subgraphs/response_subgraph.py`](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/response_subgraph.py)
- [`local_life_agent/answer/generator.py`](D:/javacode/hm-dianping/local_life_agent/answer/generator.py)
- [`local_life_agent/answer/verifier.py`](D:/javacode/hm-dianping/local_life_agent/answer/verifier.py)
- [`local_life_agent/answer/b2_mini_verifier.py`](D:/javacode/hm-dianping/local_life_agent/answer/b2_mini_verifier.py)
- [`local_life_agent/planning/decision/decision_planner.py`](D:/javacode/hm-dianping/local_life_agent/planning/decision/decision_planner.py)

## 6. State Persistence / 写回门禁验收

这一项总体通过。

结论：

- `state_update_plan / StateCore` 仍然是唯一可靠 session 持久化出口
- 没有发现其他运行时代码直接 `save_session` / `update_session` 的绕路写回
- `current_shop`、`last_recommendation_list`、`comparison_result`、`pending_clarification` 的写回门禁在主链路里基本正常

静态证据：

- [`local_life_agent/engine/subgraphs/state_update_plan.py`](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/state_update_plan.py)
- [`local_life_agent/planning/plans/state_update_planner.py`](D:/javacode/hm-dianping/local_life_agent/planning/plans/state_update_planner.py)
- [`local_life_agent/engine/subgraphs/intake_guard_router.py`](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/intake_guard_router.py)

## 7. 静态搜索结果

### 7.1 first-candidate / snapshot fallback

搜索模式：

```bash
Get-ChildItem 'D:/javacode/hm-dianping/local_life_agent/engine','D:/javacode/hm-dianping/local_life_agent/target','D:/javacode/hm-dianping/local_life_agent/planning','D:/javacode/hm-dianping/local_life_agent/core','D:/javacode/hm-dianping/local_life_agent/answer','D:/javacode/hm-dianping/local_life_agent/tests' -Recurse -Include *.py | Select-String -Pattern 'candidates\\[0\\]|selected_targets\\[0\\]|last_recommendation_list\\[0\\]|ranking_snapshot|winner_shop_id|main_recommendation'
```

关键解释：

- `candidates[0]`
  - 主要出现在 `planning_subgraph.py` 的多候选分支代表店选择、以及测试断言中
  - 这类命中是安全的候选代表用法，不是 winner fallback
- `selected_targets[0]`
  - 主要出现在测试里
  - 没有看到 answer 层把它当 winner fallback 的新路径
- `last_recommendation_list[0]`
  - 主要出现在测试和上下文恢复里
  - 仍然属于推荐历史，不是 winner 的直接来源
- `ranking_snapshot`
  - 在 `response_subgraph.py`、`answer/generator.py`、`answer/verifier.py`、`planning/decision/decision_planner.py`、`planning/evidence/evidence_builder.py` 中都有命中
  - 其中真正违规的是 `decision_planner.py` 里 winner 的兜底路径
- `winner_shop_id`
  - 确实主要由 decision 层产出
  - 但 decision 层内部仍有 ranking fallback，契约不够硬
- `main_recommendation`
  - 主要是决策与展示结构里的字段，不是新增 winner 逻辑

### 7.2 session persistence

搜索模式：

```bash
Get-ChildItem 'D:/javacode/hm-dianping/local_life_agent/engine','D:/javacode/hm-dianping/local_life_agent/core','D:/javacode/hm-dianping/local_life_agent/planning','D:/javacode/hm-dianping/local_life_agent/answer','D:/javacode/hm-dianping/local_life_agent/domain','D:/javacode/hm-dianping/local_life_agent/tests' -Recurse -Include *.py | Select-String -Pattern 'session_store|save_session|update_session|persist|current_shop|last_recommendation_list|last_answer_order|comparison_result|pending_clarification'
```

结论：

- 真正的持久化出口主要集中在 [`local_life_agent/engine/subgraphs/state_update_plan.py`](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/state_update_plan.py)
- [`local_life_agent/engine/subgraphs/intake_guard_router.py`](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/intake_guard_router.py) 主要负责加载 session，不是写回
- 其他大量命中属于 GraphState / SessionState mirror、测试断言或上下文恢复，不是绕过持久化门禁的新路径

### 7.3 Phase 4+ 越界

搜索模式：

```bash
Get-ChildItem 'D:/javacode/hm-dianping/local_life_agent' -Recurse -Include *.py | Select-String -Pattern 'orchestration_router|workflow_runner|WORKFLOW_REGISTRY|DiscoveryDecisionWorkflow|DeterministicToolWorkflow|DirectResponseWorkflow|ClarificationFallbackWorkflow|ExplorationPlanningWorkflow'
```

结论：

- 运行时代码里没有发现正式 Phase 4+ workflow 的落地实现
- 当前命中的相关内容如果存在，也主要是文档、注释或未来 schema 预留，不构成越界

## 8. 测试执行结果

### 已执行命令

```bash
python -m compileall local_life_agent
pytest local_life_agent/tests/test_target_resolve_candidate_set.py -q
pytest local_life_agent/tests/test_comparison_flow.py -q
pytest local_life_agent/tests/test_recommendation_flow.py -q
pytest local_life_agent/tests/test_single_shop_multifacet.py -q
pytest local_life_agent/tests/test_single_coupon_flow.py -q
pytest local_life_agent/tests/test_phase0_baseline.py -q
pytest local_life_agent/tests/test_phase1_acceptance.py -q
pytest local_life_agent/tests/test_phase_a_contracts.py local_life_agent/tests/test_phase_b_runtime_contracts.py local_life_agent/tests/test_phase_c_evidence_contracts.py local_life_agent/tests/test_phase_d_decision_contracts.py local_life_agent/tests/test_phase_e_state_contracts.py -q
pytest local_life_agent/tests/test_core_wrappers.py local_life_agent/tests/test_subgraph_core_integration.py local_life_agent/tests/test_strict_guards.py local_life_agent/tests/test_trace_observability.py -q
pytest local_life_agent/tests/test_p2_end_to_end.py -q
pytest local_life_agent/tests/test_e2e_llm_main_path.py -q
pytest local_life_agent/tests/test_comprehensive_graph_e2e.py -q
pytest local_life_agent/tests/test_answer_verifier.py local_life_agent/tests/test_candidate_decision.py local_life_agent/tests/test_decision_planner.py local_life_agent/tests/test_evidence_planner.py -q
pytest local_life_agent/tests/test_java_tool_executor.py local_life_agent/tests/test_tool_backend_observability.py local_life_agent/tests/test_real_llm_contract.py -q
```

### 结果汇总

| 套件 | 结果 |
| --- | --- |
| `python -m compileall local_life_agent` | 通过 |
| `test_target_resolve_candidate_set.py` | 9 passed |
| `test_comparison_flow.py` | 24 passed |
| `test_recommendation_flow.py` | 17 passed, 2 xfailed |
| `test_single_shop_multifacet.py` | 7 passed |
| `test_single_coupon_flow.py` | 6 passed |
| `test_phase0_baseline.py` | 13 passed |
| `test_phase1_acceptance.py` | 6 passed |
| `test_phase_a_contracts.py` + `test_phase_b_runtime_contracts.py` + `test_phase_c_evidence_contracts.py` + `test_phase_d_decision_contracts.py` + `test_phase_e_state_contracts.py` | 14 passed |
| `test_core_wrappers.py` + `test_subgraph_core_integration.py` + `test_strict_guards.py` + `test_trace_observability.py` | 32 passed，1 failed |
| `test_p2_end_to_end.py` | 9 passed |
| `test_e2e_llm_main_path.py` | 3 passed，4 failed，1 skipped |
| `test_comprehensive_graph_e2e.py` | 27 passed |
| `test_answer_verifier.py` + `test_candidate_decision.py` + `test_decision_planner.py` + `test_evidence_planner.py` | 58 passed，1 failed |
| `test_java_tool_executor.py` + `test_tool_backend_observability.py` + `test_real_llm_contract.py` | 25 passed |

### 失败项分类

#### 测试自身过时

1. `local_life_agent/tests/test_subgraph_core_integration.py::test_target_resolve_subgraph_does_not_pick_first_when_multiple_candidates`
   - 当前实现对多候选 recommendation 已经不是 `NOT_FOUND`
   - 测试还在期待旧行为，和当前契约冲突

2. `local_life_agent/tests/test_e2e_llm_main_path.py::test_recommendation_main_path_uses_llm_end_to_end`
   - 测试仍期待 `ranking_snapshot.ranked == []`
   - 当前 evidence pack 会保留排名快照，这不是错误

3. `local_life_agent/tests/test_e2e_llm_main_path.py::test_comparison_main_path_uses_llm_end_to_end`
   - 测试仍期待 `comparison_matrix.overall_ranked == []`
   - 当前实现保留了比较排序快照

4. `local_life_agent/tests/test_e2e_llm_main_path.py::test_ordinal_reference_prefers_semantic_frame`
   - 测试期待“第一家”不解析到目标
   - 当前 resolver 会把 ordinal reference 解析到推荐历史中的对应店，属于更合理的现状

5. `local_life_agent/tests/test_e2e_llm_main_path.py::test_deictic_comparison_clarifies_missing_current_shop`
   - 当前实现更倾向于利用历史上下文给出候选提示，而不是直接强制“请提供完整店名”
   - 这属于语义策略差异，不是主链路回退

#### P2 follow-up

1. `local_life_agent/tests/test_evidence_planner.py::TestPlanEvidence::test_no_facets_defaults_to_detail_for_single_shop_query`
   - 当前 `plan_evidence()` 在 `single_shop_query` 且没有显式 facets 时会返回空 `tool_calls`
   - 这不是主链路 blocker，但说明单店默认 detail 回退还可以再收紧

#### P1 high risk

1. `local_life_agent/planning/decision/decision_planner.py`
   - `winner_shop_id` 在证据不足时仍会回退到 `ranking_snapshot`
   - 这是本次验收里最重要的残余契约问题

## 9. 剩余问题清单

### P0 blocker

- 暂未发现新的 P0 blocker

### P1 high risk

- `winner_shop_id` 仍可由 `ranking_snapshot` 兜底生成
- 这会破坏“winner 只能来自 decision 层证据”的硬约束

### P2 follow-up

- `single_shop_query` 无 facets 时的默认 detail 行为还可以再补齐或明确

### P3

- 部分 e2e 断言仍停留在旧版契约上，建议统一更新测试期望，避免把“更完整的证据快照”误判为回退

## 10. 下一步建议

**不建议进入 Phase 4，继续修 Phase 0-3。**

最小动作建议：

1. 先移除 `decision_planner.py` 中 `ranking_snapshot` 到 `winner_shop_id` 的兜底路径。
2. 明确证据不足时的输出方式，改为 `winner_shop_id=None` + `missing_fields` / `next_action` / `reason`。
3. 再复核 `plan_evidence()` 对 `single_shop_query` 无 facets 场景的默认 detail 逻辑。
4. 重新跑本次验收中的主回归和 e2e，直到 winner 兜底彻底消失。
