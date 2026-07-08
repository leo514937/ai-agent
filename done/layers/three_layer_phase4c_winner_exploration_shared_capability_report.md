# Phase 4-C 报告：winner 强约束 + exploration 接入共享能力

## 结论

PARTIAL PASS

## 3a～3d 前置验收

- 3a 已真实完成：`response_subgraph.py` 中 `_h_rewrite` 不再只是裸计数，已经消费 `RewriteInstruction` 并驱动 rewrite route / mode / strategy。
- 3b 已真实完成：`local_life_agent/answer/composers/deterministic.py` 已有 `DirectResponseComposer`、`ClarificationComposer`、`SystemFallbackComposer`、`SingleShopFactComposer`、`RecommendationComposer`、`ComparisonComposer`、`ExplorationPlanComposer`。
- 3c 已真实完成：`local_life_agent/answer/verifier.py` 已具备 L1 claim extraction / verification。
- 3d 已真实完成：`recommendation_decision_workflow.py` 和 `comparison_decision_workflow.py` 已作为独立 workflow 入口存在，且 registry / runner / route 已接通。

## 修改前真实代码调研结果

- `ComparisonMatrix` 只有 `rows` / `overall_ranked` / `dimension_winners`，没有结构化 winner 真值字段。
- `DecisionPlan` 只有 `overall_ranking` / `best_for`，没有 `statistical_winner`。
- `RankingPolicy` 已有可追溯 score / provenance，但没有对 comparison winner 的统一导出 helper。
- `evidence_builder.py` 的 comparison 分支只算了 `overall_ranked`，winner 仍是隐式从排序第一名推导。
- `generator.py` 的 comparison 分支仍会把 `overall_ranked[0]` 当作隐式 winner 真相源。
- `verifier.py` 的 comparison claim 也主要依赖 `overall_ranked[0]`，无法区分“有唯一赢家”和“只是排序第一但没有足够证据确认赢家”。
- `llm_verbalizer.py` 的 comparison fallback 仍有机会从文本层顺着排序顺口表达 winner。
- `exploration_planning_workflow.py` 已经在使用共享的 `build_evidence_pack_from_tool_results`、`build_answer_plan_from_evidence`、`verify_answer_plan`、`apply_state_update_plan`，没有另起一套第二层体系。

## 3e：winner 强约束改造结果

- 新增结构字段：
  - `ComparisonMatrix.statistical_winner`
  - `ComparisonMatrix.winner_provenance`
  - `ComparisonMatrix.winner_uncertainty_note`
  - `DecisionPlan.statistical_winner`
  - `DecisionPlan.winner_provenance`
  - `DecisionPlan.winner_uncertainty_note`
- 新增统一 derivation：
  - `local_life_agent/planning/policies/ranking_policy.py` 新增 `derive_comparison_winner()`。
  - winner 只有在 evidence 排序对 runner-up 明显更优时才生成。
  - tie 只按 `shop_id` 做稳定排序，不会被当成真实 winner。
- `evidence_builder.py`：
  - comparison matrix 现在会落 `statistical_winner` / `winner_provenance` / `winner_uncertainty_note`。
  - winner 由结构化 rows 计算后写回 matrix，而不是交给文案层临时猜。
- `generator.py`：
  - comparison 分支把 `statistical_winner` 写入 `DecisionPlan`。
  - 相关 provenance / uncertainty 也进入 `DecisionPlan.decision_context` 和 final metadata。
- `verifier.py`：
  - comparison winner 校验现在优先使用 `comparison_matrix.statistical_winner`。
  - 如果没有结构化 winner，winner phrase 会被判为 unsupported，而不是默认拿 `overall_ranked[0]` 顶上。
  - `_extract_expected_claims()` 里的 `comparison_winner_overall` 现在只在有结构化 winner 时生成。
- `llm_verbalizer.py`：
  - comparison fallback 现在优先读取 `statistical_winner`。
  - 没有唯一 winner 时会收敛为 trade-off / uncertainty 表达，不会自己造赢家。
- `answer/composers/deterministic.py`：
  - `ComparisonComposer` 现在会直接消费 `statistical_winner`、`winner_provenance`、`winner_uncertainty_note`。
  - 没有唯一 winner 时会明确说“当前还没有足够证据确认唯一赢家”，不会用第一名冒充赢家。

## `_h_rewrite` 改造说明

- 本阶段没有再改 rewrite loop 主逻辑，因为 3a 已经真实接入。
- 3e 只补了 verifier / winner 结构，让 rewrite instruction 能稳定从 comparison winner 相关 issue 里得到“不要强行宣布赢家”的结构化反馈。
- 现有 `RewriteInstruction` 已能消费 `unsupported_comparison_winner`、`ranking_changed_by_llm` 等 issue，并把它们转成 deterministic rewrite / fallback 偏好。

## composer 覆盖矩阵

- `DirectResponseComposer`：已覆盖。
- `ClarificationComposer`：已覆盖。
- `SystemFallbackComposer`：已覆盖。
- `SingleShopFactComposer`：已覆盖。
- `RecommendationComposer`：已覆盖。
- `ComparisonComposer`：已覆盖，并已接入结构化 winner。
- `ExplorationPlanComposer`：已覆盖。

## generator / verbalizer / composer 选择策略

- 单店、直接回复、澄清、可信 fallback 优先走 deterministic composer。
- recommendation / comparison / exploration 仍可走 LLM verbalizer，但 rewrite instruction 或边界校验触发时会回落到 deterministic composer。
- LLM disabled / timeout / empty output 不返回占位符，而是直接走可信 fallback。
- rewrite 超限后会落到可信 composer fallback。
- `ResponseDirective.final_response`、`preview_text`、`ResponseContractV1.answer_text` 的语义保持一致。

## exploration_planning_workflow 接入共享能力说明

- 我调研后确认：`exploration_planning_workflow.py` 已经在使用共享第二层能力，不存在第二套平行 planner。
- 已复用的共享能力包括：
  - `build_evidence_pack_from_tool_results`
  - `build_answer_plan_from_evidence`
  - `verify_answer_plan`
  - `apply_state_update_plan`
- workflow 仍保留自己的 subgoal 拆分与 tool round 调度，但没有复制 `planning_subgraph`、没有做 MapReduce、没有另起 `complex_orchestrator`。
- 这次我没有再加一套探索 planner，避免重复实现。

## 与统一 final_response / ResponseContractV1 的衔接

- 比较与探索的最终出口仍然走统一 response 层。
- `ResponseDirective` 的 `metadata` 现在会带上 `comparison_winner` / `comparison_winner_provenance` / `comparison_winner_uncertainty_note`。
- `ResponseContractV1.from_response_directive()` 仍按现有统一出口把 `answer_text` / `preview_text` / `metadata` 带出来，因此 winner provenance 可以顺着统一出口透传。

## 实际修改文件清单

- `local_life_agent/domain/schemas.py`
- `local_life_agent/planning/policies/ranking_policy.py`
- `local_life_agent/planning/evidence/evidence_builder.py`
- `local_life_agent/answer/generator.py`
- `local_life_agent/answer/verifier.py`
- `local_life_agent/answer/llm_verbalizer.py`
- `local_life_agent/answer/composers/deterministic.py`
- `local_life_agent/tests/test_comparison_flow.py`
- `local_life_agent/tests/test_phase4b_claim_l1_and_workflow_split.py`

## 明确没有做的后续内容

- 没有进入 3c～3f 以外的新增阶段。
- 没有引入 ClaimVerifier L2 / L3。
- 没有做 ResponseContract V2。
- 没有引入 `ContextualizedTurn` / `FocusContext`。
- 没有做 Redis SessionStore。
- 没有做 `complex_orchestrator` / MapReduce。
- 没有重写 `graph_builder`。
- 没有重写整个 `planning_subgraph`。
- 没有复制 exploration workflow 成第二套实现。

## 测试结果

- `python -m pytest local_life_agent/tests/test_llm_verbalizer.py -q` -> 14 passed
- `python -m pytest local_life_agent/tests/test_answer_verifier.py -q` -> 23 passed
- `python -m pytest local_life_agent/tests/test_phase3_completion_contracts.py -q` -> 4 passed
- `python -m pytest local_life_agent/tests/test_phase4b_claim_l1_and_workflow_split.py -q` -> 4 passed
- `python -m pytest local_life_agent/tests/test_comparison_flow.py -q` -> 26 passed
- `python -m pytest local_life_agent/tests/test_phase7_workflows.py -q` -> 10 passed
- `python -m pytest local_life_agent/tests/test_e2e_llm_main_path.py -q` -> 7 passed, 1 skipped
- `python -m compileall local_life_agent` -> passed
- `python -m pytest local_life_agent/tests -q` -> `1346 passed, 37 skipped, 2 xfailed, 3 failed`

## 全量失败分界

- 本阶段没有新增全量失败。
- 全量仍剩下 3 个失败，全部都在 `local_life_agent/tests/test_recommendation_flow.py`：
  - `test_recommendation_semantic_constraints_should_surface_in_plan_and_ranking`
  - `test_recommendation_ranking_score_is_recomputable`
  - `test_after_recommendation_first_item_reference_works`
- 这 3 个更像是既有推荐流语义/回归问题，不是本阶段 3e / 3f 新引入的问题。

## 是否建议进入第 5 批

- 暂不建议直接进入第 5 批。
- 理由：全量测试还保留 3 个推荐流旧失败，建议先把推荐流语义和 ranking snapshot 回归收口，再往第一层上下文与澄清边界推进。
