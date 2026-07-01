# Phase 0-3 Freeze Acceptance Before Phase 4

## 1. 总体结论

**PASS_WITH_P2**

结论：

- Phase 0-3 可以冻结。
- 可以进入 Phase 4 设计。
- 不建议直接进入 Phase 4 实现，先补一轮明确的 P2/P3 follow-up 更稳妥。
- 当前未发现新的 P0 / P1 blocker。

下一步最小动作：

- 冻结 Phase 0-3。
- 进入 Phase 4 设计。
- 在进入 Phase 4 实现前，补一次真实 `real_llm` / live E2E 验证与少量测试语义收敛。

## 2. 最新修复报告复核

复核对象：

- [phase0_3_decision_fallback_final_fix_report.md](/D:/javacode/hm-dianping/todo/phase0_3_decision_fallback_final_fix_report.md)

复核结果：

- 该报告声称已切断 `ranking_snapshot -> winner_shop_id` fallback，这一点现在成立。
- `decision_planner` 的 winner 只来自 evidence items 和 comparison matrix 的显式 winner，不再从 `ranking_snapshot` 兜底。
- 证据不足或平局时会返回结构化不足信息，而不是伪造 winner。
- 单店无显式 facet 时补 `detail` 的 fallback 仍然存在且已通过回归。

关键代码证据：

- [local_life_agent/planning/decision/decision_planner.py](/D:/javacode/hm-dianping/local_life_agent/planning/decision/decision_planner.py#L101)
- [local_life_agent/engine/subgraphs/response_subgraph.py](/D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/response_subgraph.py#L179)
- [local_life_agent/planning/plans/state_update_planner.py](/D:/javacode/hm-dianping/local_life_agent/planning/plans/state_update_planner.py#L107)

## 3. 静态搜索结果

### 3.1 Winner fallback

命中说明：

- `decision_planner._extract_ranking()` 只读取 `ranking_snapshot` 做 trace / display 兼容，不作为 winner 来源。
- `decision_planner._find_winner_from_evidence()` 只看 `evidence_items` 与 `comparison_matrix.dimension_winners` 的显式证据。
- `winner_evidence_refs` 只从真实 claim / evidence_ranking 组装，不吸收 `ranking_snapshot`。
- `plan_decision()` 在证据不足或平局时会返回 `winner_shop_id=None`，并带上 `missing_fields` / `next_action` / `reason` / `insufficient_evidence`。

结论：

- 未发现 `ranking_snapshot -> winner_shop_id` 运行时 fallback。
- 未发现 `first candidate` 作为 snapshot 级 winner fallback。

相关位置：

- [local_life_agent/planning/decision/decision_planner.py](/D:/javacode/hm-dianping/local_life_agent/planning/decision/decision_planner.py#L101)
- [local_life_agent/planning/decision/decision_planner.py](/D:/javacode/hm-dianping/local_life_agent/planning/decision/decision_planner.py#L129)
- [local_life_agent/planning/decision/decision_planner.py](/D:/javacode/hm-dianping/local_life_agent/planning/decision/decision_planner.py#L170)
- [local_life_agent/planning/decision/decision_planner.py](/D:/javacode/hm-dianping/local_life_agent/planning/decision/decision_planner.py#L333)

### 3.2 Answer 层越权

命中说明：

- `response_subgraph` 直接从 `decision_to_answer_plan()` 生成 `answer_plan`，没有自己重选 winner。
- `generate_answer()` 只消费 `answer_plan` + `evidence_pack`，没有额外再做 winner 决策。
- `answer/verifier.py` 仍然用 evidence / comparison_matrix / ranking_snapshot 做校验输入，但没有在 answer 层重建 winner。
- `template_fallback` 与 `llm_disabled` 仍然可见：`answer_source`、`template_degraded`、`template_fallback_used` 都会写入 metadata。

结论：

- answer 层没有越权重选 winner。
- fallback / degraded 是可见的，不是静默吞掉。
- `template_fallback` 分支会在 verifier 阶段短路为 pass，但元数据保留了降级痕迹。

相关位置：

- [local_life_agent/engine/subgraphs/response_subgraph.py](/D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/response_subgraph.py#L179)
- [local_life_agent/engine/subgraphs/response_subgraph.py](/D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/response_subgraph.py#L261)
- [local_life_agent/engine/subgraphs/response_subgraph.py](/D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/response_subgraph.py#L275)
- [local_life_agent/answer/verifier.py](/D:/javacode/hm-dianping/local_life_agent/answer/verifier.py#L108)
- [local_life_agent/answer/llm_verbalizer.py](/D:/javacode/hm-dianping/local_life_agent/answer/llm_verbalizer.py#L302)

### 3.3 State persistence

命中说明：

- 唯一持久化出口仍是 `state_update_plan -> persist_session_state`。
- `intake_guard_router` 只负责加载 session，不负责写回。
- `plan_state_update()` 会区分 `resolve_shop_status` 与 `ToolResultStatus`，不会把工具失败和目标解析状态混为一谈。
- 推荐流只写 `last_recommendation_list`，不写 `current_shop`。
- 比较流写 `comparison_targets` / `comparison_result`，并清理 `current_shop`。
- 单店流只在真 `RESOLVED` 场景写 `current_shop`，`tool_failed` 会清掉它。

结论：

- 没有发现绕路写 session 的新路径。
- 没有发现 `current_shop` 被推荐 / 比较错误写入的运行时路径。
- `pending_clarification` 没有被混写成已确认事实。

相关位置：

- [local_life_agent/engine/subgraphs/state_update_plan.py](/D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/state_update_plan.py#L35)
- [local_life_agent/engine/subgraphs/state_update_plan.py](/D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/state_update_plan.py#L107)
- [local_life_agent/planning/plans/state_update_planner.py](/D:/javacode/hm-dianping/local_life_agent/planning/plans/state_update_planner.py#L119)
- [local_life_agent/planning/plans/state_update_planner.py](/D:/javacode/hm-dianping/local_life_agent/planning/plans/state_update_planner.py#L159)
- [local_life_agent/planning/plans/state_update_planner.py](/D:/javacode/hm-dianping/local_life_agent/planning/plans/state_update_planner.py#L169)

### 3.4 Mock / fake backend

命中说明：

- `config.py` 里 `TOOL_BACKEND` 的合法值只有 `db` 和 `java_api`。
- `build_tool_executor()` 只接受 `db` / `java_api`，遇到其他值直接报错。
- `fake_executor.py` 自身也写明是 test-only executor。
- `MOCK_LOCATION` 只在 `config.py` 定义，并且静态搜索只命中 `tests/fakes/comparison_planner.py`，没有运行时代码把它当默认后端。

结论：

- 没有发现 runtime `fake` tool backend 的合法入口。
- 没有发现 runtime `MOCK_LOCATION` 作为真实工具后端默认值的路径。
- 测试夹具里的 fake / mock 仍然只停留在测试目录。

相关位置：

- [local_life_agent/config.py](/D:/javacode/hm-dianping/local_life_agent/config.py)
- [local_life_agent/tools/executor.py](/D:/javacode/hm-dianping/local_life_agent/tools/executor.py#L198)
- [local_life_agent/tools/fake_executor.py](/D:/javacode/hm-dianping/local_life_agent/tools/fake_executor.py#L1)

### 3.5 Phase 4 越界

静态搜索：

- `orchestration_router`
- `workflow_runner`
- `WORKFLOW_REGISTRY`
- `DiscoveryDecisionWorkflow`
- `DeterministicToolWorkflow`
- `DirectResponseWorkflow`
- `ClarificationFallbackWorkflow`
- `ExplorationPlanningWorkflow`

结论：

- 在 `local_life_agent/` 运行时代码中未检出这些 Phase 4+ 名称。
- 当前主链路仍然是现有 LangGraph 子图，不存在已落地的 Phase 4+ workflow 实现。

### 3.6 状态阶段

命中说明：

- `resolution_stage` 现在明确表达 `candidate_set_resolved` / `target_resolved` / `target_not_found`。
- `target_resolution_status` 仍然存在，但更像兼容状态输出，不再是唯一语义总开关。
- `next_action` / `insufficient_evidence` 已在 `decision_planner` 里显式输出。

结论：

- 阶段语义比旧版本清晰。
- 没有发现 `next_action` 在当前冻结范围内被后写覆盖前述失败信号的运行时回退。

相关位置：

- [local_life_agent/engine/subgraphs/planning_subgraph.py](/D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/planning_subgraph.py#L496)
- [local_life_agent/engine/subgraphs/planning_subgraph.py](/D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/planning_subgraph.py#L580)
- [local_life_agent/domain/graph_state.py](/D:/javacode/hm-dianping/local_life_agent/domain/graph_state.py#L89)
- [local_life_agent/planning/decision/decision_planner.py](/D:/javacode/hm-dianping/local_life_agent/planning/decision/decision_planner.py#L273)

## 4. 测试执行结果

### 已执行命令与结果

| 命令 | 结果 |
| --- | --- |
| `python -m compileall local_life_agent` | 通过 |
| `pytest local_life_agent/tests/test_phase0_baseline.py -q` | `13 passed` |
| `pytest local_life_agent/tests/test_phase1_acceptance.py -q` | `6 passed` |
| `pytest local_life_agent/tests/test_target_resolve_candidate_set.py -q` | `9 passed` |
| `pytest local_life_agent/tests/test_comparison_flow.py -q` | `24 passed` |
| `pytest local_life_agent/tests/test_recommendation_flow.py -q` | `17 passed, 2 xfailed` |
| `pytest local_life_agent/tests/test_single_shop_multifacet.py -q` | `7 passed` |
| `pytest local_life_agent/tests/test_single_coupon_flow.py -q` | `6 passed` |
| `pytest local_life_agent/tests/test_p2_end_to_end.py -q` | `9 passed` |
| `pytest local_life_agent/tests/test_comprehensive_graph_e2e.py -q` | `27 passed` |
| `pytest local_life_agent/tests/test_e2e_llm_main_path.py -q` | `7 passed, 1 skipped` |
| `pytest local_life_agent/tests/test_phase_a_contracts.py local_life_agent/tests/test_phase_b_runtime_contracts.py local_life_agent/tests/test_phase_c_evidence_contracts.py local_life_agent/tests/test_phase_d_decision_contracts.py local_life_agent/tests/test_phase_e_state_contracts.py -q` | `15 passed` |
| `pytest local_life_agent/tests/test_core_wrappers.py local_life_agent/tests/test_subgraph_core_integration.py local_life_agent/tests/test_strict_guards.py local_life_agent/tests/test_trace_observability.py -q` | `33 passed` |
| `pytest local_life_agent/tests/test_decision_planner.py -q` | `25 passed` |
| `pytest local_life_agent/tests/test_candidate_decision.py -q` | `7 passed` |
| `pytest local_life_agent/tests/test_evidence_planner.py -q` | `11 passed` |
| `pytest local_life_agent/tests/test_answer_verifier.py -q` | `18 passed` |
| `pytest local_life_agent/tests/test_java_tool_executor.py -q` | `9 passed` |
| `pytest local_life_agent/tests/test_tool_backend_observability.py -q` | `1 passed` |
| `pytest local_life_agent/tests/test_real_llm_contract.py -q` | `15 passed` |

### xfail / skip 说明

- `test_recommendation_flow.py`
  - `test_recommendation_flow_staged_parallel`
  - `test_recommendation_plan_enriches_only_top_8_candidates`
  - 这两个是历史断言，原因是旧测试期望与当前 staged / planner 语义不一致，不是当前冻结的 blocker。
- `test_e2e_llm_main_path.py`
  - `test_e2e_llm_main_path.py:304` skipped
  - 原因：`real_llm` 集成测试缺少 API key。

### 失败分类

- P0 blocker: 无
- P1 high risk: 无
- P2 follow-up: 真实 `real_llm` live E2E 还需要补一次可运行环境验证
- P3 cleanup: 旧测试语义仍有少量 `xfail` / `skip`

## 5. 行为级反例检查

以下结果来自临时本地脚本调用 `plan_decision` / `plan_state_update` / `B2MiniVerifier`，未修改仓库代码。

### 6.1 Snapshot 顺序反例

结果：

- 同一组 evidence，仅交换 `ranking_snapshot` 顺序后，`winner_shop_id` 均为 `None`。
- `winner_evidence_refs` 均为空。

结论：

- `ranking_snapshot` 顺序不参与 winner 决策。
- 没有 snapshot 兜底 winner。

### 6.2 只有 ranking_snapshot 反例

结果：

- `winner_shop_id = None`
- `next_action = clarify`
- `insufficient_evidence = True`
- answer 输出为泛化推荐提示，没有生成“最推荐 X”类 winner 文案。

结论：

- 只有 snapshot 时不会凭空造 winner。
- answer 没有重建 winner。

### 6.3 Recommendation 写回反例

结果：

- `last_recommendation_list` 更新。
- `current_shop` 不更新。

结论：

- 推荐流写回门禁正确。

### 6.4 Comparison 写回反例

结果：

- `comparison_targets` / `comparison_result` 更新。
- `last_recommendation_list` 没有被覆盖。
- `current_shop` 不更新。

结论：

- 比较流写回门禁正确。

### 6.5 Single shop 写回反例

结果：

- 单店明确成功时，`current_shop` 会更新。
- `last_recommendation_list` 会被清理。
- tool failure 时，`current_shop` 不更新且被清理。

结论：

- 单店写回门禁正确。
- tool failure 不会污染 `current_shop`。

### 6.6 Verifier / fallback 反例

结果：

- LLM verifier 返回空/失败时，不会默认 pass。
- 在 `response_text='irrelevant'` 的反例里，heuristic 返回：
  - `passed = False`
  - `failure_code = missing_target_name`
  - `unsupported_claims` 包含 `boom`

结论：

- verifier fallback 不是默认放行。
- 失败时有可见的 failure code。

## 6. Candidate / Target / Winner 冻结结论

结论：

- `candidate_set` 只表示候选。
- `resolved_target` 只表示目标解析结果，不等于 winner。
- `winner_shop_id` 只来自 evidence-backed decision，不来自 `ranking_snapshot`。
- `ranking_snapshot` 已降级为 trace / display / verifier support 输入。
- `resolution_stage` 已足够支撑当前 Phase 0-3 的阶段分层。

相关位置：

- [local_life_agent/engine/subgraphs/planning_subgraph.py](/D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/planning_subgraph.py#L491)
- [local_life_agent/planning/decision/decision_planner.py](/D:/javacode/hm-dianping/local_life_agent/planning/decision/decision_planner.py#L101)
- [local_life_agent/planning/decision/decision_planner.py](/D:/javacode/hm-dianping/local_life_agent/planning/decision/decision_planner.py#L200)

## 7. State Persistence 冻结结论

结论：

- `state_update_plan / StateCore` 仍然是唯一可靠 session 持久化出口。
- `current_shop` 只在真单店 RESOLVED 场景写回。
- `last_recommendation_list` 只在 recommendation 场景写回。
- `comparison_result` / `comparison_targets` 只在 comparison 场景写回。
- `pending_clarification` 不会被误当成已确认事实。
- tool failure 会清理 `current_shop`，不会写入假事实。

相关位置：

- [local_life_agent/planning/plans/state_update_planner.py](/D:/javacode/hm-dianping/local_life_agent/planning/plans/state_update_planner.py#L143)
- [local_life_agent/planning/plans/state_update_planner.py](/D:/javacode/hm-dianping/local_life_agent/planning/plans/state_update_planner.py#L169)
- [local_life_agent/engine/subgraphs/state_update_plan.py](/D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/state_update_plan.py#L127)

## 8. Answer / Verifier 冻结结论

结论：

- answer 层只表达 evidence / decision，不重选 winner。
- `decision_to_answer_plan()` 是从 `DecisionPlan` 到 `AnswerPlan` 的桥接，没有引入新的事实来源。
- verifier 不是默认放行，但 `template_fallback` / `llm_disabled` 的降级路径是显式可见的。
- deterministic summary / fallback metadata 没有越权隐藏。

相关位置：

- [local_life_agent/engine/subgraphs/response_subgraph.py](/D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/response_subgraph.py#L179)
- [local_life_agent/engine/subgraphs/response_subgraph.py](/D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/response_subgraph.py#L261)
- [local_life_agent/answer/llm_verbalizer.py](/D:/javacode/hm-dianping/local_life_agent/answer/llm_verbalizer.py#L308)
- [local_life_agent/answer/b2_mini_verifier.py](/D:/javacode/hm-dianping/local_life_agent/answer/b2_mini_verifier.py#L181)

## 9. Mock / Fake / Real Backend 结论

结论：

- `fake_executor.py` 是 test-only executor，不是 runtime 合法后端。
- `TOOL_BACKEND` 只接受 `db` / `java_api`。
- `MOCK_LOCATION` 仅出现在 `config.py` 常量和测试夹具里，没有进入 runtime 默认后端路径。
- `real_llm_contract` 仍然有效，且本轮测试通过。
- 仍建议后续补一次真正带 API key 的 live E2E，以把 P2 follow-up 收口。

相关位置：

- [local_life_agent/config.py](/D:/javacode/hm-dianping/local_life_agent/config.py)
- [local_life_agent/tools/executor.py](/D:/javacode/hm-dianping/local_life_agent/tools/executor.py#L198)
- [local_life_agent/tools/fake_executor.py](/D:/javacode/hm-dianping/local_life_agent/tools/fake_executor.py#L1)
- [local_life_agent/tests/fakes/comparison_planner.py](/D:/javacode/hm-dianping/local_life_agent/tests/fakes/comparison_planner.py#L128)

## 10. 剩余问题清单

### P0

- 无

### P1

- 无

### P2

- `test_e2e_llm_main_path.py` 的 real_llm 集成仍然受 API key 约束，当前 CI / 本地环境下会跳过。

### P3

- `test_recommendation_flow.py` 仍有 2 个 legacy xfail，需要后续语义收敛时顺手清理。
- `template_fallback` 路径的 verifier 行为虽然可见，但属于降级处理，未来若要更严格可再细化告警粒度。

## 11. 下一步建议

**冻结 Phase 0-3，进入 Phase 4 设计，但实现前先补 P2。**

最小动作：

1. 冻结 Phase 0-3。
2. 进入 Phase 4 设计。
3. 在 Phase 4 实现前，补一次带 API key 的真实 `real_llm` live E2E。
4. 顺手清理少量 legacy `xfail`，避免后续把旧语义误读为回归。

