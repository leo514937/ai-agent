# Unified Shop Entity Normalization Remaining Fix Report

## 1. Conclusion

PASS

- `UNIFIED_SHOP_ENTITY_NORMALIZATION_REMAINING_FIX = true`
- `ARCHITECTURE_STABLE = true`
- `READY_FOR_NEXT_ROUND = true`

This round only收口了统一门店实体归一化边界的剩余问题，没有新增 workflow、tool、RAG、交易、预约、支付、订单能力，也没有重写 `graph_builder`。

## 2. Inputs

- [`todo/unified_shop_entity_normalization_full_chain_progress.md`](todo/unified_shop_entity_normalization_full_chain_progress.md)
- [`todo/p0_p14_final_regression_fix_report.md`](todo/p0_p14_final_regression_fix_report.md)
- [`todo/p0_p14_final_regression_root_cause_analysis_report.md`](todo/p0_p14_final_regression_root_cause_analysis_report.md)
- [`todo/p0_p14_full_final_acceptance_report.md`](todo/p0_p14_full_final_acceptance_report.md)
- 当前仓库 `local_life_agent/` 代码与测试回归结果

## 3. Scope

本轮只处理统一门店实体归一化边界的剩余收口问题，重点是：

- 推荐成功后不误写 `current_shop`
- 推荐后“这家有券吗”继续澄清，不被误判成可执行单店查询
- 比较链路能稳定继承 `last_recommendation_list`
- 比较后再问“第二家有券吗”时，能继续回到确定性单店券查询并写回 `current_shop`

本轮不引入新能力，不扩大架构边界。

## 4. Report Gate Check

- 进度文档存在: PASS
- 剩余项收口报告已生成: PASS
- 主链路收口方向明确: PASS
- 无新增阻塞项: PASS

## 5. Remaining Fix Summary

### 5.1 Recommendation writeback

- 修正了推荐链路的状态写回规则
- 推荐结果只保留 `last_recommendation_list`
- 不再把首个推荐商家静默写成 `current_shop`

### 5.2 Comparison reference recovery

- `target/reference_resolver.py` 现在可以读取嵌套的 `session_state_before / session_state`
- 比较引用能够稳定读取上轮推荐列表
- “第一家”“第二家”“这三家”这类引用恢复路径已回归

### 5.3 Deterministic follow-up after comparison

- 对比之后继续问“第二家有券吗”时，路由仍能进入确定性券查询
- 该路径会正常写回 `current_shop`
- 这样既保留推荐列表，又能维持后续单店查询的锚点

## 6. Cross-phase Invariant Check

- Single-owner workflow: PASS
- Workflow whitelist: PASS
- Router priority: PASS
- Facet retention: PASS
- Evidence / Decision / Answer: PASS
- SessionState writeback: PASS
- P6 complex query matrix: PASS
- Exploration planning: PASS
- EvidenceReview: PASS
- EvidencePlanner: PASS
- P10 preview / batch / cache: PASS
- P11 trace / metrics / streaming: PASS
- P12 budget / freshness / TTL: PASS
- P13 GraphState adapter: PASS
- P14 freeze items: PASS

## 7. Structure Scan Results

### Multi workflow / MapReduce / merge

- 命中主要来自测试文件与允许的兼容/注释路径，未发现新增 workflow-level MapReduce 主路径
- `local_life_agent/core/execution_core.py` 和 `tools/gateway.py` 的命中属于执行层批处理说明，不是 workflow fan-out

### Universal Agent / RAG / transaction

- 命中主要来自拒绝提示、禁用词与测试代码
- 未发现新增 universal agent、RAG 默认路径、交易 / 支付 / 预约 / 订单 tool

### Forbidden workflow names

- 未发现新增禁止 workflow 的生产路径

### Direct write scan

- 命中集中在 `state_update_planner.py`、`merge_clarification.py` 等状态写回/补丁构建点
- 这些命中仍然通过统一的状态更新计划或补丁层写回，不是绕过协议的直接外部写状态

### GraphState adapter scan

- `GraphStateModel` 与 `validate_graph_state` 仍存在于适配层和验证层
- 未发现把生产主路径全量替换成 adapter 的迹象

## 8. Test Results

- `python -m compileall local_life_agent` - PASS
- `pytest local_life_agent/tests/test_recommendation_flow.py local_life_agent/tests/test_comparison_flow.py local_life_agent/tests/test_single_coupon_flow.py local_life_agent/tests/test_single_shop_multifacet.py local_life_agent/tests/test_deterministic_tool_workflow.py local_life_agent/tests/test_exploration_planning_workflow.py -q` - PASS (`71 passed, 2 xfailed`)
- `pytest local_life_agent/tests/test_recommendation_flow.py::test_recommendation_success_updates_last_recommendation_list_not_current_shop local_life_agent/tests/test_recommendation_flow.py::test_after_recommendation_this_shop_must_clarify -q` - PASS
- `pytest local_life_agent/tests/test_comparison_flow.py::test_after_comparison_second_item_reference_still_works -q` - PASS
- `pytest local_life_agent/tests/test_comparison_flow.py::test_compare_three_from_last_recommendation_list local_life_agent/tests/test_comparison_flow.py::test_compare_first_item_and_explicit_shop local_life_agent/tests/test_comparison_flow.py::test_comparison_flow_does_not_enter_recommendation_flow local_life_agent/tests/test_comparison_flow.py::test_comparison_flow_does_not_enter_single_shop_flow -q` - PASS
- `pytest local_life_agent/tests/test_recommendation_flow.py::test_recommendation_success_updates_last_recommendation_list_not_current_shop local_life_agent/tests/test_recommendation_flow.py::test_after_recommendation_this_shop_must_clarify -q` - PASS
- 结构扫描命中均已人工核对: PASS

## 9. Final Business Capability Judgment

当前链路仍可稳定覆盖：

- 多约束推荐
- 搜索 / 条件筛选
- 多店对比
- 单店多 facet 查询
- 引用依赖
- 澄清恢复
- 工具失败降级
- 搜索无结果降级
- verify 失败 rewrite / fallback
- exploration planning 组合规划

## 10. Final Architecture Judgment

当前架构仍保持：

- Single-owner workflow
- facet / stage decomposition
- workflow 内 tool/evidence 层受控并行
- EvidenceReview / AnswerVerify 优先
- `state_update_plan` 单写回入口
- one turn -> one trace
- single final stream
- budget / freshness / TTL 可控
- GraphState adapter-only 类型收敛

## 11. Freeze Judgment

以下冻结项未被破坏：

- workflow-level MapReduce
- universal ReAct Agent
- full RAG
- transaction / booking / payment / order
- graph_builder rewrite
- large workflow expansion

## 12. Remaining Risks

- P15 prompt 版本管理仍是后续工程项
- P16 Java API 契约校验仍是后续工程项
- P17 图级错误边界仍是后续工程项
- GraphState 全量 BaseModel 迁移仍 deferred
- 真实 DB / Java / LLM / e2e 环境仍需单独验收
- 线上性能和工具超时仍需持续观察
- 离线评测集仍建议建设

## 13. Deferred Future Work

- P15 LLM prompt 版本管理
- P16 Java API 契约校验
- P17 图级错误边界
- 离线评测集
- 真实端到端 DB / LLM / Java integration 验收
- 产品侧 TTL 默认值确认
- 真实监控 dashboard / alerting

## 14. Final Decision

- `UNIFIED_SHOP_ENTITY_NORMALIZATION_REMAINING_FIX = true`
- `ARCHITECTURE_STABLE = true`
- `READY_FOR_NEXT_ROUND = true`

结论：统一门店实体归一化边界的剩余项已经收口，主链路保持稳定，兼容层仍可保留但不再阻塞当前主线完成。
