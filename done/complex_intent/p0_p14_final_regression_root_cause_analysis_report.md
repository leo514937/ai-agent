# P0-P14 Final Regression Root Cause Analysis Report

## 1. Conclusion

结论：`PARTIAL PASS`，当前属于“可定位根因、但尚未达到最终验收通过”的回归分析阶段。

- `ROOT_CAUSE_CATEGORY = Mixed(ProcessContractRegression + TestExpectationDrift + CompatibilityRegression)`
- `NEED_ARCHITECTURE_REWORK = false`
- `READY_TO_FIX = true`

判定说明：

- 这次失败不是单一的架构失稳，也没有证据表明需要推翻 P0-P14 的 single-owner 主线设计。
- 失败主要集中在若干协议/兼容层：`TurnTrace` 兼容、澄清恢复/目标解析、混合证据回退策略、比较链路主路径、以及一部分旧测试对已演进 schema 的断言失配。
- 结构扫描未发现 workflow-level MapReduce、universal ReAct agent、全局 RAG 默认路径、交易/预约/支付/订单工具、或 graph_builder 重写的生产路径证据。

## 2. Inputs

已读取并核对的输入报告与总方案文档：

- [`todo/p0_p14_full_final_acceptance_report.md`](todo/p0_p14_full_final_acceptance_report.md)
- [`todo/p14_long_term_freeze_and_final_acceptance_report.md`](todo/p14_long_term_freeze_and_final_acceptance_report.md)
- [`todo/p13_state_schema_convergence_report.md`](todo/p13_state_schema_convergence_report.md)
- [`todo/p12_deadline_budget_freshness_ttl_report.md`](todo/p12_deadline_budget_freshness_ttl_report.md)
- [`todo/p11_followup_router_p6_regression_fix_report.md`](todo/p11_followup_router_p6_regression_fix_report.md)
- [`todo/p10_final_p5_comparison_metadata_contract_fix_report.md`](todo/p10_final_p5_comparison_metadata_contract_fix_report.md)
- [`todo/p10_experience_and_performance_report.md`](todo/p10_experience_and_performance_report.md)
- [`todo/p7_p11_unified_acceptance_report.md`](todo/p7_p11_unified_acceptance_report.md)
- [`todo/complex_intent_query_architecture_stabilization_plan.md`](todo/complex_intent_query_architecture_stabilization_plan.md)

同时结合了本轮执行的编译、单测、回归与结构扫描结果。

## 3. Scope

本轮只做最终验收失败根因分析，不做代码修复。

本轮未引入任何新能力，且未尝试：

- 新增 workflow
- 新增 tool
- 引入 RAG 默认路径
- 引入交易 / 预约 / 支付 / 订单能力
- 引入 workflow-level MapReduce
- 引入 universal ReAct Agent
- 重写 `graph_builder`

分析目标是确认失败来自哪里，并给出最小修复顺序，而不是重构整套架构。

## 4. Reproduction Summary

已执行并确认的关键命令与结果：

### 4.1 编译

- `python -m compileall local_life_agent`
- 结果：通过

### 4.2 P0-P14 主回归

已跑过要求中的主回归集合，当前分析阶段的失败集中在以下测试簇：

- `local_life_agent/tests/test_single_coupon_flow.py`
- `local_life_agent/tests/test_unknown_failed_handling.py`
- `local_life_agent/tests/test_context_recovery_clarification.py`
- `local_life_agent/tests/test_candidate_resolver.py`
- `local_life_agent/tests/test_domain_schemas.py`
- `local_life_agent/tests/test_eval_runner.py`
- `local_life_agent/tests/test_prompt_contract.py`
- `local_life_agent/tests/test_e2e_llm_main_path.py`
- `local_life_agent/tests/test_semantic_llm_main_path.py`
- `local_life_agent/tests/test_real_llm_acceptance.py`

### 4.3 直接复现到的关键症状

- `test_timeout_coupon_shop_degrades_controlled`
  - 失败点：断言 `response.debug.tool_results` 中存在 `get_coupon_list` 且 `result_status in {"empty", "ok"}` 未满足。
- `TestUnknownAsFalse::test_coupon_ok_and_distance_empty`
  - 当前 `review_evidence()` 行为返回 `REPLAN_EVIDENCE`，而测试期望 `FINISH`。
- `test_eval_runner.py` 多个用例
  - 统一报错：`TypeError: TurnTrace.__init__() got an unexpected keyword argument 'workflow_name'`
- 比较主路径 e2e
  - 多个用例落入 `clarification_fallback` / `trusted_failure_message`，而不是预期的比较/LLM verbalizer 主路径。
- facet/schema 旧断言
  - `Facet` 枚举数量和 `SemanticFrame.facets` 的类型都已演进，旧测试仍按旧契约断言。

## 5. Failure Classification Matrix

下面按“失败类型 + 根因归类 + 影响范围”进行分类。

### 分类定义

- `A`：环境/外部依赖型失败
- `B`：协议/实现回归，属于真实产品行为偏差
- `C`：测试运行态/上下文/编码/fixture 不稳定
- `D`：测试期望落后于已演进协议，属于断言漂移

### 逐项分类

| 测试 / 失败簇 | 分类 | 结论 |
| --- | --- | --- |
| `test_timeout_coupon_shop_degrades_controlled` | `B` | 失败表面上是超时链路，但实质是工具结果状态与后续证据/调试链路的契约不一致，导致控制降级没有按预期落到可观测结果上。 |
| `TestUnknownAsFalse::test_coupon_ok_and_distance_empty` | `B` | 当前 `review_evidence()` 对“已答复 facet + 空结果 facet”的混合场景选择重规划，而测试仍要求直接结束，这是协议回退/策略漂移，不是环境问题。 |
| `test_pending_reply_number_restores_original_coupon_task` | `B/C` | 说明澄清恢复链路存在真实行为偏差，但此簇里也混有上下文/输入编码影响，需复核固定复现。 |
| `test_pending_reply_chinese_ordinal_restores_task` | `B/C` | 同上，属于恢复语义与会话上下文稳定性问题。 |
| `test_explicit_shop_overrides_current_shop` | `C` | 手工 Unicode 复现可通过，说明 pytest 失败可能与 fixture/状态/编码路径有关，暂不直接上升为架构性回归。 |
| `TestResolveExplicit::test_not_found_mention_skipped_uses_current_seed_id` | `D` | 手工复现可返回期望的 `900007`，更像旧 fixture / 断言对 resolver 路径的假设漂移。 |
| `TestSemanticFrame::test_with_enums` | `D` | facet taxonomy 已扩展，旧测试还在按旧 enum 语义断言。 |
| `TestEnums::test_facet_values` | `D` | `Facet` 集合已从旧的 11 个扩展到更丰富的 taxonomy，测试期望过时。 |
| `test_eval_runner.py` 系列 | `B` | `TurnTrace` 序列化/反序列化兼容性断裂，属于真实的工程契约回归。 |
| `test_prompt_contract.py::TestLoadCases::test_inline_case_passed_to_run_eval_unchanged` | `B` | 由 eval runner 的 `TurnTrace` 兼容问题触发，不是 prompt 解析本身的问题。 |
| `test_e2e_llm_main_path.py` / `test_semantic_llm_main_path.py` / `test_real_llm_acceptance.py` 中的比较路径失败 | `B` | 比较/澄清/目标解析的主路径回退到 `clarification_fallback`，影响核心业务链路。 |

## 6. Root Cause Tree

### 6.1 第一层：失败可以分成三大簇

1. 证据/回退策略簇
2. 澄清恢复 / 目标解析簇
3. 兼容性 / 观测 / 评估簇

### 6.2 第二层：每簇的直接根因

#### A. 证据 / 回退策略簇

- 现象：
  - 混合 facet 场景中，`review_evidence()` 对 `ok + empty` 选择 `REPLAN_EVIDENCE`
  - 仍有测试在要求直接 `FINISH`
- 直接根因：
  - 证据判定策略已经更保守，优先保证不编造结果，但旧测试仍按旧协议假设“只要有一个 ok 就能结束”
- 影响：
  - `test_unknown_failed_handling.py`
  - 单券超时控制降级相关测试

#### B. 澄清恢复 / 目标解析簇

- 现象：
  - 数字回复、中文序数回复、显式店名覆盖当前店等恢复场景在 pytest 中有失败
- 直接根因候选：
  - pending clarification 的恢复链路、explicit mention 覆盖 current_shop 的优先级、以及测试 fixture / 编码输入对 resolver 路径的干扰
- 影响：
  - `test_context_recovery_clarification.py`
  - `test_candidate_resolver.py`
  - 比较/引用类 query 的可恢复性

#### C. 兼容性 / 观测 / 评估簇

- 现象：
  - `run_eval` 在组装 `TurnTrace` 时崩溃
- 直接根因：
  - `TurnTrace.to_dict()` / `TurnTraceModel` 已包含 `workflow_name`
  - 但 `TurnTrace` dataclass 构造函数不接收 `workflow_name`
  - `eval/run_eval.py` 在把 dict 重新喂回 `TurnTrace(**merged)` 时触发 TypeError
- 影响：
  - `test_eval_runner.py`
  - `test_prompt_contract.py`
  - 任何依赖 eval trace 归档的验收流程

### 6.3 根因结论

这次失败不是“架构要推倒重来”，而是：

- 主设计仍稳定
- 但若干关键协议层的语义已演进，相关适配器、回退策略和旧测试还没完全对齐

## 7. Hard Blocker Analysis

### 7.1 单券超时链路

失败测试：

- `local_life_agent/tests/test_single_coupon_flow.py::test_timeout_coupon_shop_degrades_controlled`

关键观察：

- 工具层已经具备超时归一化与空结果标记能力
- 但测试关注的是“最终可观测到的 tool result / debug 结果”
- 当前失败说明：
  - 要么超时结果没有稳定流入 debug/tool_results
  - 要么后续 review / state writeback 对这类结果的可见性与测试预期不一致

判断：

- 这不是架构重做问题
- 这是“工具结果状态 -> 证据层 -> debug 可见性”的链路契约问题

### 7.2 混合证据场景

失败测试：

- `TestUnknownAsFalse::test_coupon_ok_and_distance_empty`

直接复现观察：

- 当前 `review_evidence()` 会把 `coupon ok + distance empty` 判为 `REPLAN_EVIDENCE`
- 而测试还要求 `FINISH`

判断：

- 这是明确的策略漂移
- 当前实现更倾向于谨慎重规划，避免把带空洞证据的结果误当作完全结束
- 若要恢复旧测试，需要统一“空结果是否允许在有足够 answerable facet 时结束”的协议

## 8. Clarification / Target Resolution Cluster

相关失败：

- `test_pending_reply_number_restores_original_coupon_task`
- `test_pending_reply_chinese_ordinal_restores_task`
- `test_explicit_shop_overrides_current_shop`
- `TestResolveExplicit::test_not_found_mention_skipped_uses_current_seed_id`

结论：

- 这个簇里存在真实链路问题，但也混有测试上下文/编码/fixture 不稳定。
- 手工复现显示：
  - explicit shop override 在某些路径上是可工作的
  - `resolve_explicit()` 的目标 ID 也能回到期望值

因此更稳妥的判断是：

- 先把它视为“澄清恢复协议未完全收敛”
- 不把它上升为“必须重构架构”

可能的根因方向：

- pending clarification 恢复时的 task_type / resolved_target 写回优先级不够稳定
- current_shop 覆盖 / 保留的分支与测试假设存在偏差
- pytest 场景中的输入编码或历史状态让某些恢复路径表现不稳定

## 9. Schema / Enum / Eval Compatibility Cluster

### 9.1 facet / enum 旧断言失配

失败测试：

- `TestSemanticFrame::test_with_enums`
- `TestEnums::test_facet_values`

结论：

- 这更像是测试期望过时，而不是生产契约坏掉。
- 当前 `Facet` / `SemanticFrame` 已经演进到更丰富的 taxonomy。
- 旧测试仍按“少量 legacy enum + enum list 语义”断言，自然会失败。

### 9.2 Eval runner 直接崩溃

失败测试：

- `test_eval_runner.py` 多个用例
- `test_prompt_contract.py::TestLoadCases::test_inline_case_passed_to_run_eval_unchanged`

直接根因：

- `TurnTrace` 的字典化输出包含 `workflow_name`
- 但 `TurnTrace` 构造器不接受这个字段
- `run_eval.py` 在做 round-trip 时没有剔除该字段

这属于明确的工程兼容回归，不是架构概念问题。

## 10. Comparison / Main Path Regression Cluster

失败测试：

- `test_comparison_main_path_uses_llm_end_to_end`
- `test_deictic_comparison_clarifies_missing_current_shop`
- `test_comparison_focused_facets_from_llm`
- `test_spy_e2e_query_2_comparison`

当前症状：

- 比较请求更容易进入 `clarification_fallback`
- `trusted_failure_message` 成为最后输出
- 预期的 comparison / verbalizer 主路径没有稳定走通

解释：

- 这不是“加一个新 workflow”造成的问题
- 而是 routing / semantic frame / comparison target resolution / fallback 分类之间的契约没有完全闭合
- 从 spy/fake 路径也能失败，说明不是纯真实 LLM 环境问题

## 11. Architecture Rework Judgment

是否需要架构重做：`false`

判断依据：

- 结构扫描没有发现 P0-P14 明确禁止的生产路径扩张
- 单 owner workflow 仍是单值 dispatch，没有多 workflow fan-out
- 未发现 workflow-level MapReduce、universal ReAct、全局 RAG、交易/预约/支付/订单工具接入
- `GraphState` 仍然是主路径的轻量状态形态，`GraphStateModel` 仍属于 adapter / evaluation 层

当前失败更像：

- 主链路契约回归
- 若干适配器与旧测试脱节
- 局部策略过保守或过宽松

因此：

- 不建议推翻 P0-P14 稳态主线
- 建议按协议层和适配层做最小修复

## 12. Minimal Fix Order

按“影响面最大、最能恢复验收”的顺序，建议如下：

1. 先修证据回退与超时可观测性
   - 目标：让单券超时、空结果、混合证据场景的 `tool_results`、`EvidencePack`、`EvidenceReview` 行为一致
   - 覆盖测试：`test_timeout_coupon_shop_degrades_controlled`、`test_unknown_failed_handling.py`

2. 再修澄清恢复与 explicit mention 覆盖
   - 目标：数字回复、中文序数回复、显式店名覆盖 current_shop 的恢复链路稳定
   - 覆盖测试：`test_context_recovery_clarification.py`、`test_candidate_resolver.py`

3. 处理 `TurnTrace` / `run_eval` 兼容
   - 目标：让评估与验收报告链路重新可运行
   - 覆盖测试：`test_eval_runner.py`、`test_prompt_contract.py`

4. 最后修比较主路径与 LLM 主链路回退
   - 目标：恢复 comparison / deictic comparison / focused facets 的主路径
   - 覆盖测试：`test_e2e_llm_main_path.py`、`test_semantic_llm_main_path.py`、`test_real_llm_acceptance.py`

## 13. Tests To Run After Fix

修复后建议按以下顺序回归：

```bash
python -m compileall local_life_agent
pytest local_life_agent/tests/test_single_coupon_flow.py local_life_agent/tests/test_unknown_failed_handling.py -q -vv
pytest local_life_agent/tests/test_context_recovery_clarification.py local_life_agent/tests/test_candidate_resolver.py -q -vv
pytest local_life_agent/tests/test_domain_schemas.py -q -vv
pytest local_life_agent/tests/test_eval_runner.py local_life_agent/tests/test_prompt_contract.py -q -vv
pytest local_life_agent/tests/test_e2e_llm_main_path.py local_life_agent/tests/test_semantic_llm_main_path.py local_life_agent/tests/test_real_llm_acceptance.py -q -vv
pytest local_life_agent/tests/test_p5_session_state_writeback.py \
       local_life_agent/tests/test_comparison_flow.py \
       local_life_agent/tests/test_single_coupon_flow.py \
       local_life_agent/tests/test_single_shop_multifacet.py \
       local_life_agent/tests/test_recommendation_flow.py -q
```

## 14. Remaining Risks

即使修复上述问题，仍需持续关注：

- P15 prompt 版本管理仍是后续工程项
- P16 Java API 契约校验仍是后续工程项
- P17 图级错误边界仍是后续工程项
- GraphState 全量 BaseModel 迁移仍应保持 deferred
- 真实 DB / Java / LLM / e2e 环境仍需要独立验收
- 线上性能与工具超时仍需持续观察
- 离线评测集仍建议建设

## 15. Final Decision

- `P0_P14_FINAL_ACCEPTANCE = false`
- `ARCHITECTURE_STABLE = true`
- `READY_FOR_POST_P14_ENGINEERING = false`

原因：

- 架构主线没有失稳，因此 `ARCHITECTURE_STABLE = true`
- 但当前仍存在多处协议回归与兼容性问题，导致最终验收不能置为通过
- 这些问题属于“先修协议层与适配层，再重新验收”的范围，而不是推进到 P15-P17 的信号

结论：P0-P14 架构稳态主线仍然成立，但当前最终验收不通过，需要先修复本报告列出的协议/兼容性根因后再重新验收。
