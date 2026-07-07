# 三层改造 Phase 4-A 报告

结论：`PARTIAL PASS`

本阶段只覆盖 3a `RewriteInstruction` 集成增强 和 3b 完整 `DeterministicComposer` 补齐，没有进入 3c-3f。

## 修改前真实代码调研结果

- `local_life_agent/answer/rewrite_instruction.py` 里已经有 `RewriteInstruction`，但能力很薄，核心仍是基于 violation code 的最小结构化封装。
- `local_life_agent/engine/subgraphs/response_subgraph.py` 里的 `_h_rewrite` 仍是裸 `rewrite_count += 1` 风格，没有真正消费 `RewriteInstruction`。
- `local_life_agent/answer/generator.py` 和 `local_life_agent/answer/llm_verbalizer.py` 已经有生成与回退分层，但 rewrite 语义还没有形成闭环。
- `local_life_agent/answer/composers/` 之前只覆盖：
  - `DirectResponseComposer`
  - `ClarificationComposer`
  - `SystemFallbackComposer`
  - `SingleShopFactComposer`
- `RecommendationComposer`、`ComparisonComposer`、`ExplorationPlanComposer` 之前不存在，需要在现有 deterministic composer 体系内补齐，而不是另起一套。
- `ResponseContractV1`、`ResponseDirective`、`final_response`、`preview_text` 的统一出口链路已经存在，本阶段不重做协议，只对接现有链路。
- `StageToolExecutor`、`ToolResultCache`、`ClaimVerifier`、workflow 拆分这几块没有发现本阶段必须介入的破坏。

## RewriteInstruction 当前状态

### 改造前

- 主要来自 violation code 的简单聚合。
- 没有稳定吃进 verifier report 的统一入口。
- 不足以驱动 rewrite 策略分流，只能做轻量提示。
- 无法清楚表达：
  - unsupported claim 要删或弱化
  - contradicted claim 要转成 unknown / uncertainty
  - unknown 不能被 rewrite 成确定事实
  - ranking / winner 不能被 rewrite 改写

### 改造后

- 新增 `RewriteInstruction.from_verifier_report(...)`，可以从 verifier report 结构化生成 rewrite 指令。
- 指令会结合：
  - `violations / issues`
  - `failure_code`
  - `violation`
  - `unsupported_claims`
  - `false_fields`
  - `unknown_fields`
  - `suggested_fix`
  - `DecisionPlan` 中的 allowed claims / factual points / target shop names
- 指令里会同时携带：
  - `unsupported_claims`
  - `contradicted_claims`
  - `required_additions`
  - `claims_to_keep`
- 新增边界类失败码分组，用来判断是否应该走 deterministic composer、LLM 复写，还是可信 fallback：
  - `boundary`
  - `uncertainty`
  - `ranking`

## `_h_rewrite` 修改说明

- `_h_rewrite` 不再只是计数器。
- 现在会读取 `rewrite_instruction`，并生成：
  - `rewrite_mode`
  - `rewrite_strategy`
  - `rewrite_reason`
  - `rewrite_count`
- rewrite 策略会在下面几类之间分流：
  - deterministic composer
  - 带 instruction 的 LLM verbalizer 重写
  - 达到上限后的可信 fallback
- rewrite 只修表达和证据对齐，不新增事实。

## Composer 覆盖矩阵

| Composer | 状态 | 主要职责 | 数据来源 | 备注 |
| --- | --- | --- | --- | --- |
| `DirectResponseComposer` | 已有 | 直接回答 | `DecisionPlan` / `EvidencePack` / `ResponseDirective` | 保持 deterministic |
| `ClarificationComposer` | 已有 | 生成澄清问题 | `DecisionPlan` / `ResponseDirective` | 保持 deterministic |
| `SystemFallbackComposer` | 已有 | 可信失败 / 系统回退 | `ResponseDirective` / `ResponseContractV1` | 不能只吐空抱歉 |
| `SingleShopFactComposer` | 已有 | 单店事实回答 | `DecisionPlan` / `EvidencePack` / `ResponseDirective` | 保持 deterministic |
| `RecommendationComposer` | 新增 | 推荐排序与推荐表达 | `DecisionPlan` / 排名结果 / `EvidencePack` | 保留 ranking 顺序与过滤结果 |
| `ComparisonComposer` | 新增 | 多店对比表达 | `DecisionPlan` / comparison matrix / winner / trade-off | 保留 winner 与 trade-off |
| `ExplorationPlanComposer` | 新增 | 探索型规划表达 | `DecisionPlan` / stages | 保留 stages，不硬压成单店事实 |

### 复用边界

- 没有复制第二套 composer 体系。
- 没有把 recommendation / comparison / exploration workflow 拆成新的平行链路。
- 仍然沿用现有 deterministic composer 入口做分发。

## Generator / Verbalizer / Composer 选择策略

目标是收敛到常见的 `generator -> verifier -> rewrite -> fallback` 模式。

实际策略如下：

- `AnswerPlan` / `EvidencePack` 先进入 response policy。
- 单店、直答、澄清、fallback 优先走 deterministic composer。
- recommendation / comparison / exploration 可以先走 LLM verbalizer。
- 如果 rewrite instruction 指向 ranking / winner / unsupported / contradicted / uncertainty 类问题，则倾向 deterministic rewrite 或可信 fallback。
- `LLM disabled`、`timeout`、`empty output` 不返回占位符，直接进入 deterministic fallback。
- rewrite 超限后必须落到可信 composer fallback。

## 与 ResponseContractV1 / final_response 的衔接

- `ResponseContractV1` 仍然是统一出口的核心承载体。
- `final_response`、`preview_text`、`source` 的语义保持一致，没有引入 V2。
- 本阶段只是在 rewrite / fallback 路径上，让 deterministic composer 和 verifier 的输出都能稳定汇入同一条 contract 线。
- `verbalize_decision_plan()` 在 deterministic rewrite 场景下会保留模板 / 重写元数据，避免最终输出失去来源和预览语义。

## 实际修改文件清单

- `local_life_agent/answer/rewrite_instruction.py`
- `local_life_agent/answer/composers/__init__.py`
- `local_life_agent/answer/composers/deterministic.py`
- `local_life_agent/answer/generator.py`
- `local_life_agent/answer/llm_verbalizer.py`
- `local_life_agent/engine/subgraphs/response_subgraph.py`
- `local_life_agent/tests/test_third_layer_deterministic_composers.py`
- `local_life_agent/tests/test_third_layer_rewrite_instruction.py`
- `local_life_agent/tests/test_third_layer_llm_disabled_fallback.py`
- `local_life_agent/tests/test_llm_verbalizer.py`
- `local_life_agent/tests/test_real_llm_contract.py`

## 明确没有做的内容

- 没有进入 3c-3f。
- 没有引入 `ClaimExtractor`。
- 没有引入 `ClaimVerifier`。
- 没有拆 recommendation / comparison workflow。
- 没有重写 `discovery_decision`。
- 没有重写 `graph_builder`。
- 没有重写 `planning_subgraph`。
- 没有修改 `StageToolExecutor` 主逻辑。
- 没有修改 `ToolResultCache` 主逻辑。
- 没有做 `ResponseContract` V2。
- 没有引入 `ContextualizedTurn` / `FocusContext`。
- 没有做 Redis `SessionStore`。
- 没有复制 composer / verifier / rewrite 模块形成平行体系。
- 没有为了测试硬编码 query、店名、工具结果或固定文案。

## 测试结果

### 本轮复测

- `python -m pytest local_life_agent/tests/test_real_llm_contract.py -q`
  - `15 passed`
- `python -m pytest local_life_agent/tests/test_third_layer_llm_disabled_fallback.py -q`
  - `6 passed`
- `python -m compileall local_life_agent`
  - 通过

### 全量回归

- `python -m pytest local_life_agent/tests -q`
  - `1340 passed, 37 skipped, 2 xfailed, 3 failed`

### 当前仍失败的 3 个用例

- `local_life_agent/tests/test_recommendation_flow.py::test_recommendation_semantic_constraints_should_surface_in_plan_and_ranking`
- `local_life_agent/tests/test_recommendation_flow.py::test_recommendation_ranking_score_is_recomputable`
- `local_life_agent/tests/test_recommendation_flow.py::test_after_recommendation_first_item_reference_works`

### 失败分类

- 这 3 个失败属于 recommendation workflow 的历史语义未对齐问题。
- 它们与本阶段 3a / 3b 的 rewrite / composer / fallback 闭环有关联，但不属于这次新增的 `RewriteInstruction` 或 deterministic composer 直接回归。
- 当前全量失败里没有出现 `StageToolExecutor`、`ToolResultCache`、统一出口 contract 被破坏的证据。

## 是否建议进入 Phase 4-B：ClaimVerifier L1

建议：`可以进入预研，但不建议把 Phase 4-A 视为完全收敛后再无条件推进`

理由：

- 3a / 3b 已经落地。
- rewrite -> composer -> fallback 的闭环已经补上。
- 但 recommendation workflow 仍有 3 个旧语义失败，说明上层推荐链路还有未收敛点。
- 如果 Phase 4-B 要引入更严格的 claim 级验证，最好先确认这些 recommendation 失败属于可接受的历史债务，还是需要在下一阶段一起处理。

