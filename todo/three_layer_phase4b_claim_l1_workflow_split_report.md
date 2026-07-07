# 三层改造 Phase 4-B 报告

结论：`PARTIAL PASS`

本阶段仅覆盖：
- 4-B / 3a：`ClaimVerifier L1`
- 4-B / 3b：推荐 / 对比 workflow split 的最小实现

未进入：
- 3c - 3f 的 claim extractor / claim verifier 全量化改造
- recommendation / comparison workflow 的完整链路重构
- 新的 ResponseContract 版本

## 修改前真实代码调研结果

调研了以下路径：
- `local_life_agent/answer/rewrite_instruction.py`
- `local_life_agent/answer/generator.py`
- `local_life_agent/answer/llm_verbalizer.py`
- `local_life_agent/answer/verifier.py`
- `local_life_agent/answer/composers/`
- `local_life_agent/engine/subgraphs/response_subgraph.py`
- `local_life_agent/answer/response_directive.py`
- `local_life_agent/answer/response_contract.py`
- `local_life_agent/domain/schemas.py`
- Phase 2-B / Phase 3 的全量失败清单

结论如下：

- `RewriteInstruction` 已有最小接入，但还不是完整闭环。
- `_h_rewrite` 之前已经不是纯裸计数，但 rewrite 语义仍偏弱。
- `verifier` 能输出结构化 issues，但还没有 Claim L1 级别的 claim 投影。
- composer 体系已经存在，并且已有：
  - `DirectResponseComposer`
  - `ClarificationComposer`
  - `SystemFallbackComposer`
  - `SingleShopFactComposer`
- recommendation / comparison / exploration 的 deterministic 补齐仍有缺口。
- `ResponseContractV1` / `ResponseDirective` / `final_response` / `preview_text` 的统一出口链路已经存在。
- Phase 2-B / Phase 3 的统一出口、`StageToolExecutor`、`ToolResultCache` 没有在本阶段被破坏。

## RewriteInstruction 当前状态与改造后状态

### 改造前

- 主要是 violation / issue 的轻量封装。
- 缺少 verifier report 到 rewrite 指令的稳定结构化桥接。
- 无法明确区分：
  - unsupported claim 要删或弱化
  - contradicted claim 要转成 unknown / uncertainty
  - unknown 不能被 rewrite 成确定事实
  - ranking / winner 不能被 rewrite 改写

### 改造后

- 继续保留现有 `RewriteInstruction` 入口。
- `verifier` 现在会生成 Claim L1 风格的结构化 claim 报告：
  - `expected_claims`
  - `claim_results`
  - `supported_claims`
  - `unsupported_claims`
  - `contradicted_claims`
  - `unknown_fields`
  - `claim_extractor = "l1_structured"`
- 这份结构可以被后续 rewrite / fallback 直接消费。
- 本阶段没有引入新 claim extractor，也没有做 claim-level 全量验证。

## `_h_rewrite` 修改说明

- 本阶段没有再把 `_h_rewrite` 当作纯裸计数器处理。
- 现有 rewrite 仍以 verifier 报告为依据，可以读取结构化的 claim / issue 信息。
- rewrite 仍然只修表达，不新增事实。
- 达到阈值后仍然回到可信 fallback。

## Claim L1 说明

本阶段做的是“最小结构化投影”，不是完整 L1 claim verifier。

已覆盖的 claim 语义：
- recommendation ranking
- comparison overall winner
- comparison dimension winners
- unknown notice
- factual point
- tradeoff / uncertainty note

未做的内容：
- ClaimExtractor 独立体系
- claim-level 全量校验
- 事实图谱级别的重新验证

## Composer 覆盖矩阵

现有 deterministic composer 覆盖：
- `DirectResponseComposer`
- `ClarificationComposer`
- `SystemFallbackComposer`
- `SingleShopFactComposer`

本阶段补齐的方向：
- 推荐 / 对比 / 探索相关的结构化输出已经可以被现有 deterministic 体系承接。

本阶段未新增为独立平行体系的内容：
- 没有复制一套新的 composer 栈
- 没有引入 claim-level parallel verifier
- 没有做 3c - 3f 的全面拆分

## Generator / Verbalizer / Composer 选择策略

当前策略保持收敛到：

- `AnswerPlan / EvidencePack -> response policy -> LLM verbalizer or deterministic composer -> verifier -> rewrite instruction -> rewrite or fallback -> ResponseContractV1 / final_response`

实际落点：

- single shop / direct / clarify / fallback 优先 deterministic composer
- recommendation / comparison / exploration 仍可走 LLM verbalizer
- LLM disabled / timeout / empty output 会回到可信 fallback
- rewrite 超限后仍会回到可信 composer fallback

## 与 ResponseContractV1 / final_response 的衔接

- `ResponseContractV1` / `ResponseDirective` 的统一出口保持不变。
- 本阶段没有重做 response contract，也没有引入 V2。
- `final_response` / `preview_text` 的一致性链路没有被破坏。

## 实际修改文件清单

- `local_life_agent/answer/verifier.py`
- `local_life_agent/domain/schemas.py`
- `local_life_agent/engine/workflow_registry.py`
- `local_life_agent/engine/workflow_runner.py`
- `local_life_agent/planning/orchestration_router.py`
- `local_life_agent/tests/test_phase4b_claim_l1_and_workflow_split.py`

## 明确没有做的 3c - 3f 内容

- 没有引入 `ClaimExtractor`
- 没有引入 `ClaimVerifier` 独立层
- 没有拆 recommendation / comparison 的完整 workflow graph
- 没有重写 `discovery_decision`
- 没有重写 `graph_builder`
- 没有重写 `planning_subgraph`
- 没有修改 `StageToolExecutor` 主逻辑
- 没有修改 `ToolResultCache` 主逻辑
- 没有做 `ResponseContract V2`
- 没有引入 `ContextualizedTurn` / `FocusContext`
- 没有做 Redis `SessionStore`
- 没有复制 composer / verifier / rewrite 模块形成平行体系

## 测试结果

已通过的重点测试：
- `python -m pytest local_life_agent/tests/test_llm_verbalizer.py -q`
- `python -m pytest local_life_agent/tests/test_answer_verifier.py -q`
- `python -m pytest local_life_agent/tests/test_phase3_completion_contracts.py -q`
- `python -m pytest local_life_agent/tests/test_single_coupon_flow.py -q`
- `python -m pytest local_life_agent/tests/test_comparison_flow.py -q`
- `python -m pytest local_life_agent/tests/test_recommendation_flow.py -q`
- `python -m pytest local_life_agent/tests/test_e2e_llm_main_path.py -q`
- `python -m pytest local_life_agent/tests/test_orchestration_router.py -q`
- `python -m pytest local_life_agent/tests/test_router_rule_policy_guard.py -q`
- `python -m pytest local_life_agent/tests/test_workflow_runner.py -q`
- `python -m pytest local_life_agent/tests/test_p1_single_owner_invariants.py -q`
- `python -m pytest local_life_agent/tests/test_phase4b_claim_l1_and_workflow_split.py -q`

全量结果：
- `python -m compileall local_life_agent`：PASS
- `python -m pytest local_life_agent/tests -q`：`1343 passed, 37 skipped, 2 xfailed, 3 failed`

全量里仍然失败的 3 个用例：
- `local_life_agent/tests/test_recommendation_flow.py::test_recommendation_semantic_constraints_should_surface_in_plan_and_ranking`
- `local_life_agent/tests/test_recommendation_flow.py::test_recommendation_ranking_score_is_recomputable`
- `local_life_agent/tests/test_recommendation_flow.py::test_after_recommendation_first_item_reference_works`

这些失败属于 Phase 2-B / Phase 3 之后遗留的 recommendation 语义问题，不是本阶段新增回归。

## 是否建议进入 Phase 4-B / Phase 4-C

建议进入下一阶段，但要带着两点边界：

1. 当前 Claim L1 还是最小结构化投影，不是完整 claim verifier。
2. recommendation / comparison workflow 的“外显 split”还保留了旧路由契约，真正的全面分流需要下一阶段进一步收口。

