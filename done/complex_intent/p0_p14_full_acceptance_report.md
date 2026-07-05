# P0-P14 全量验收报告

## 1. 总结

**总体结论：FAIL**

本轮验收基于当前 `toolcall` 分支的真实代码与真实测试执行结果，不是仅按文档判断。结论之所以是 `FAIL`，不是因为架构方向错误，而是因为两类关键回归仍未收敛：

- `P6` 复杂 query 测试矩阵中仍有真实失败：`recommendation_plus_reference_dependency` 期望写回 `current_shop`，但实际 `session_after.current_shop` 仍为空。
- `P7` exploration planning 协议在多个 fallback / verify failure 场景中仍没有把 `pending_clarification` 稳定带回结果。

其余大部分 P 项的核心测试已经通过，说明主干协议大体成立，但本轮不能把整体状态判定为“最终验收完成”。

## 2. 已执行测试

### 2.1 核心回归

命令：

```bash
pytest local_life_agent/tests/test_workflow_runner.py local_life_agent/tests/test_workflow_registry.py local_life_agent/tests/test_app_streaming.py local_life_agent/tests/test_exploration_planning_workflow.py -q
```

结果：

- `23 passed`
- `1 warning`

### 2.2 P0-P14 关联回归

命令：

```bash
pytest local_life_agent/tests/test_p1_single_owner_invariants.py local_life_agent/tests/test_p2_router_priority.py local_life_agent/tests/test_p3_facet_protocol.py local_life_agent/tests/test_p4_evidence_decision_answer_protocol.py local_life_agent/tests/test_p5_session_state_writeback.py local_life_agent/tests/test_p6_complex_query_matrix.py local_life_agent/tests/test_p7_exploration_protocol.py local_life_agent/tests/test_p8_evidence_review_iteration.py local_life_agent/tests/test_p9_evidence_planner_capability_budget.py local_life_agent/tests/test_p10_experience_performance.py local_life_agent/tests/test_p11_observability_streaming.py local_life_agent/tests/test_p12_deadline_budget_freshness_ttl.py local_life_agent/tests/test_p13_state_schema_convergence.py local_life_agent/tests/test_stage14_verification.py local_life_agent/tests/test_mapreduce_semantics.py local_life_agent/tests/test_unknown_failed_handling.py local_life_agent/tests/test_tool_gateway.py local_life_agent/tests/test_trace_observability.py -q
```

结果：

- `168 passed`
- `4 failed`

失败点集中在：

- `local_life_agent/tests/test_p6_complex_query_matrix.py::test_p6_complex_query_matrix[recommendation_plus_reference_dependency]`
- `local_life_agent/tests/test_p7_exploration_protocol.py::test_exploration_partial_success_degrades_without_invention`
- `local_life_agent/tests/test_p7_exploration_protocol.py::test_exploration_tool_failure_marks_failed_facets_and_blocks_polluted_writeback`
- `local_life_agent/tests/test_p7_exploration_protocol.py::test_exploration_answer_verify_failure_rewrites_or_fallbacks`

### 2.3 P0 / Router / Prompt 相关回归

命令：

```bash
pytest local_life_agent/tests/test_p0_fact_calibration.py local_life_agent/tests/test_orchestration_router.py local_life_agent/tests/test_p2_end_to_end.py local_life_agent/tests/test_prompt_contract.py -q
```

结果：

- `40 passed`

### 2.4 缺失覆盖

以下用户要求中的测试文件在当前仓库中不存在：

- `local_life_agent/tests/test_state_update*.py`
- `local_life_agent/tests/test_p14_long_term_freeze.py`

其中 `P14` 实际可对应到现有的 `local_life_agent/tests/test_stage14_verification.py`。

## 3. 代码事实摘要

- `workflow_registry` 是白名单注册表，合法 workflow 名字集中在 `LEGAL_WORKFLOW_NAMES`，并且 `discovery_decision` 映射到 `entry_node="planning_subgraph"`。
- `workflow_runner` 只做单 workflow 分发，先做单值 `workflow_name` 归一化，再查 registry，再调用单个 handler，没有生产路径上的多 workflow 合并。
- `orchestration_router` 里明确区分了 direct / deterministic / discovery / exploration / clarification，并对 forbidden scope 做了回退保护。
- `graph_state` 把 `pending_clarification`、`current_shop`、`comparison_targets`、`evidence_pack`、`workflow_name`、`final_response`、`state_update_plan` 等关键字段集中定义。
- `EvidenceReviewResult` 已经包含 `answerable_facets`、`unknown_facets`、`failed_facets`、`unknown_as_false_detected`、`failed_as_empty_detected`、`deadline_remaining_ms`、`budget_context_snapshot`、`stale_facets`、`expired_facets` 等协议字段。
- `deterministic_tool_workflow` 和 `exploration_planning_workflow` 都在走 `EvidencePack` / `AnswerPlan` / `verify_answer_plan` 这类结构化链路，而不是直接把 tool result 当最终答案。

## 4. P0-P14 逐项验收

### P0 finite scope fact calibration / ADR freeze

- 目标：确认范围冻结，只做本地生活问答导购，不进入交易 / 预约 / 支付 / 订单 / RAG / workflow-level MapReduce / 大改 `graph_builder`。
- 代码事实：`direct_response_workflow.py` 明确把 `RAG`、交易、下单、支付、预约、退款列为不支持；`orchestration_router.py` 对 `forbidden` scope 做直接响应回退；`graph_builder.py` 仍是拼装图，不是重写调度。
- 已有测试：`test_p0_fact_calibration.py`、`test_mapreduce_semantics.py`、`test_stage14_verification.py`、`test_prompt_contract.py`。
- 实际测试结果：上述测试通过；`test_p0_fact_calibration.py` / `test_prompt_contract.py` 也通过。
- 结论：**PASS**
- 阻塞问题：无生产路径证据表明交易、预约、支付、订单被放进主链路。
- 最小修复建议：继续保持现状即可，后续只补文档/测试即可。
- 不建议现在做的事：不要为了“扩能力”把交易、订单、支付塞进主 workflow。

### P1 single workflow invariant and single dispatch

- 目标：每 turn 只能有一个 `workflow_name`，`workflow_runner` 只 dispatch 一个 workflow，registry 是白名单。
- 代码事实：`workflow_registry.py` 定义了 `LEGAL_WORKFLOW_NAMES`，只注册 5 个 workflow；`workflow_runner.py` 先用 `_coerce_single_workflow_name` 归一化，再查 `WORKFLOW_REGISTRY.lookup()`，只会调一个 handler；`graph_builder.py` 里 `workflow_runner` 只有单一出边。
- 已有测试：`test_workflow_runner.py`、`test_workflow_registry.py`、`test_p1_single_owner_invariants.py`、`test_orchestration_router.py`、`test_app_streaming.py`。
- 实际测试结果：核心回归 23/23 通过，关联回归中对应测试也通过。
- 结论：**PASS**
- 阻塞问题：无。
- 最小修复建议：保持单 dispatch，不要新增 `workflow_names` 数组式生产路径。
- 不建议现在做的事：不要把 registry 变成多 workflow fan-out 调度器。

### P2 router priority and LLM/rule/keyword conflict protection

- 目标：确认安全、澄清、direct、deterministic、discovery、exploration、clarification 的优先级与冲突保护。
- 代码事实：`orchestration_router.py` 先处理 `top_intent`/forbidden scope，再按 `_EXPLORATION_TASKS`、`_DETERMINISTIC_TASKS`、`_CLARIFICATION_TASKS` 分流；对 `workflow_name` 和 `orchestration_pattern` 不一致也有 fallback 保护。
- 已有测试：`test_orchestration_router.py`、`test_p2_router_priority.py`、`test_p2_end_to_end.py`。
- 实际测试结果：相关测试通过。
- 结论：**PASS**
- 阻塞问题：无。
- 最小修复建议：保持现有优先级表和 fallback 约束。
- 不建议现在做的事：不要让 keyword 规则绕过 router 统一白名单。

### P3 local-life facet protocol and retention

- 目标：facet 从 `SemanticFrame` 进入后续 plan / evidence / answer，并尽量保留 location、scene、coupon、distance、budget、comparison_targets 等关键属性。
- 代码事实：`SemanticFrame`、`GraphState`、`EvidencePack`、`AnswerPlan` 这些对象都保留了 facet 相关字段；`deterministic_tool_workflow.py` 会根据 budget 截断额外 facet；`planning/orchestration_router.py` 也会按场景、推荐、对比、确定性单店事实分流。
- 已有测试：`test_p3_facet_protocol.py`、`test_single_shop_multifacet.py`、`test_recommendation_flow.py`、`test_comparison_flow.py`。
- 实际测试结果：相关专测整体通过，但 `P6` 里 `recommendation_plus_reference_dependency` 仍显示依赖型单店回写有遗漏。
- 结论：**PARTIAL**
- 阻塞问题：依赖式推荐场景里 `current_shop` 回写不够稳定。
- 最小修复建议：把“推荐后引用依赖”的单店归因路径补进 state writeback 判定。
- 不建议现在做的事：不要用硬编码店名或关键词分支去补这个缺口。

### P4 Evidence / Decision / Answer convergence

- 目标：所有回答都必须能回溯到 `EvidencePack`，`DecisionPlan` / `AnswerPlan` 从证据收敛出来，unknown 和 failed 不得被当成 false/empty。
- 代码事实：`domain/evidence.py` 已有 `answerable_facets`、`unknown_facets`、`failed_facets`、`unknown_as_false_detected`、`failed_as_empty_detected`；`deterministic_tool_workflow.py` 和 `exploration_planning_workflow.py` 都会构建 `EvidencePack` 再走 `verify_answer_plan`。
- 已有测试：`test_p4_evidence_decision_answer_protocol.py`、`test_single_coupon_flow.py`、`test_comparison_flow.py`、`test_exploration_planning_workflow.py`、`test_unknown_failed_handling.py`。
- 实际测试结果：相关测试通过。
- 结论：**PASS**
- 阻塞问题：无。
- 最小修复建议：继续保持“证据先行，回答后验”。
- 不建议现在做的事：不要把 tool result 直接拼成最终回答。

### P5 SessionState writeback safety and reference resolution

- 目标：`current_shop`、`last_recommendation_list`、`comparison_targets` 的写回必须安全且可解释。
- 代码事实：`state_update_planner.py` 明确区分 `RESOLVED`、`AMBIGUOUS`、`LOW_CONFIDENCE`、`NOT_FOUND`、`CANDIDATE_SET_RESOLVED`；对 `pending_clarification` 和 `current_shop` 的写回也有条件控制。
- 已有测试：`test_p5_session_state_writeback.py`、`test_single_coupon_flow.py`、`test_single_shop_multifacet.py`、`test_comparison_flow.py`。
- 实际测试结果：专测通过，但 `P6` 的依赖型推荐用例显示 `current_shop` 仍可能漏写。
- 结论：**PASS with note**
- 阻塞问题：缺少“推荐结果 + 引用依赖”这一细分场景的稳态回写。
- 最小修复建议：把 `reference_dependency` / `current_shop` 的写回条件再收敛一层。
- 不建议现在做的事：不要放宽成“只要像店名就写 current_shop”。

### P6 complex query test matrix / golden trace

- 目标：不仅测 final_response，还要测中间态，包括 orchestration_decision、SemanticFrame、GoalPlan、EvidencePack、DecisionPlan、StateUpdatePlan。
- 代码事实：仓库里已有矩阵测试和 golden trace 结构，但当前失败用例显示某些中间态仍没有稳定收敛。
- 已有测试：`test_comprehensive_graph_e2e.py`、`test_p6_complex_query_matrix.py`。
- 实际测试结果：`recommendation_plus_reference_dependency` 失败，断言 `session_after.get("current_shop") is not None` 未通过。
- 结论：**FAIL**
- 阻塞问题：复杂 query 的依赖型写回仍有漏点，影响黄金矩阵的可信度。
- 最小修复建议：补齐推荐结果到 `current_shop` 的回写路径，并重跑 `test_p6_complex_query_matrix.py`。
- 不建议现在做的事：不要用改测试预期来掩盖这个写回问题。

### P7 exploration_planning protocol isomorphism and shared adapter

- 目标：exploration_planning 要和其他 workflow 同构，失败 / 缺信息 / verify fail 都应返回结构化 signal。
- 代码事实：`exploration_planning_workflow.py` 已经接入 `EvidencePack`、`AnswerPlan`、`verify_answer_plan`、`apply_state_update_plan`，但 fallback 逻辑里对 `pending_clarification` 的保留并不稳定。
- 已有测试：`test_exploration_planning_workflow.py`、`test_p7_exploration_protocol.py`。
- 实际测试结果：3 个关键场景失败，原因都是 fallback / verify failure 后结果里没有稳定出现 `pending_clarification`。
- 结论：**FAIL**
- 阻塞问题：exploration 的 fallback 结果没有稳定保持澄清上下文，导致协议同构不完整。
- 最小修复建议：在 exploration 的 fallback patch 里稳定写入 `pending_clarification`，并确认 verify failure 也走同一结构。
- 不建议现在做的事：不要在 workflow 内直接调用另一个 fallback handler 来绕过这个问题。

### P8 evidence insufficiency iteration / degrade / fallback

- 目标：EvidenceReview 能区分 sufficient / insufficient / unknown / failed / stale，并决定 FINISH / REPLAN_EVIDENCE / DEGRADE_ANSWER / FALLBACK / CLARIFY。
- 代码事实：`EvidenceReviewResult` 已经有完整的状态字段和 budget / freshness / stale / expired 表达；`_route_evidence_review` 和 `decision_review` 也有回路控制。
- 已有测试：`test_p8_evidence_review_iteration.py`、`test_single_coupon_flow.py`、`test_unknown_failed_handling.py`。
- 实际测试结果：关联测试通过。
- 结论：**PASS**
- 阻塞问题：无。
- 最小修复建议：继续保持 unknown / failed / empty 的严格区分。
- 不建议现在做的事：不要把 tool failure 静默当成 empty。

### P9 EvidencePlanner facet generation / cropping / budget

- 目标：EvidencePlanner 生成 tool plan 时要裁剪 facet、控制预算和超时，不能无限扩张。
- 代码事实：`deterministic_tool_workflow.py` 已经用 `budget_context_from_state()`、`facet_enrich_budget`、`deadline_remaining_ms`、`max_parallelism`、`ToolBatchExecutor` 约束调用数量；额外 facet 也有 budget 截断。
- 已有测试：`test_p9_evidence_planner_capability_budget.py`、`test_evidence_planner.py`、`test_tool_gateway.py`。
- 实际测试结果：关联测试通过。
- 结论：**PASS**
- 阻塞问题：无。
- 最小修复建议：保持 budget 裁剪逻辑，不要在 planner 里做无限 facet 展开。
- 不建议现在做的事：不要把多 facet 工具调用变成无边界搜索。

### P10 UX / performance: SSE / preview / batch parallel tool / cache

- 目标：streaming / SSE 可用，工具层支持受控并行和 cache，且并行不应升级成 workflow 级 MapReduce。
- 代码事实：`app.py` 的 streaming 路径和 `deterministic_tool_workflow.py` 的 `ToolBatchExecutor` 已经能支撑受控并行；`EvidenceCache` 也有 scope + fingerprint key。
- 已有测试：`test_app_streaming.py`、`test_p10_experience_performance.py`、`test_openai_backend_streaming.py`、`test_tool_backend_observability.py`。
- 实际测试结果：相关测试通过。
- 结论：**PASS**
- 阻塞问题：无。
- 最小修复建议：继续保持工具层并行，不要把 workflow 层升级成 MapReduce。
- 不建议现在做的事：不要给多个 workflow token stream 做 merge。

### P11 observability / metrics / streaming

- 目标：trace_id / turn_id / workflow_name / route decision / tool call / evidence status / degrade reason / state update 都能追踪。
- 代码事实：`GraphState` 保留了 `trace_id`、`turn_id`、`workflow_name`、`workflow_run_status`、`trace_spans`、`event_log`、`metrics_tags`；`workflow_runner`、router 和 workflow 都在打日志。
- 已有测试：`test_p11_observability_streaming.py`、`test_trace_observability.py`、`test_observability_regression.py`。
- 实际测试结果：相关测试通过。
- 结论：**PASS**
- 阻塞问题：无。
- 最小修复建议：继续保留节点级 trace 信息。
- 不建议现在做的事：不要只留 final_response，不留中间 trace。

### P12 deadline / budget / freshness / TTL

- 目标：工具和 LLM 有 timeout / retry / budget，动态事实有 freshness / TTL，超时后能 degrade。
- 代码事实：`BudgetContext` 已有 `tool_round_budget`、`retry_budget`、`expand_search_budget`、`rewrite_budget`、`facet_enrich_budget`、`deadline_remaining_ms`；`EvidenceReviewResult` 也有 `stale_facets`、`expired_facets`、`budget_context_snapshot`。
- 已有测试：`test_p12_deadline_budget_freshness_ttl.py`、`test_evidence_review.py`、`test_tool_gateway.py`。
- 实际测试结果：相关测试通过。
- 结论：**PASS**
- 阻塞问题：无。
- 最小修复建议：继续让动态事实通过 TTL / freshness 边界控制复用。
- 不建议现在做的事：不要把过期的 coupon / open_now / distance 长期复用。

### P13 state type convergence / GraphState schema hygiene

- 目标：GraphState、SessionState、schema 边界清晰，避免大量随意 dict 写入。
- 代码事实：`graph_state.py` 中关键 runtime 字段已经集中定义，`schemas.py` 里 `SemanticFrame` / `PendingClarification` / `ToolResult` 等结构化模型较完整；`state_update_planner.py` 也在集中产出 set/clear directive。
- 已有测试：`test_p13_state_schema_convergence.py`、`test_domain_schemas.py`、`test_phase_e_state_contracts.py`。
- 实际测试结果：相关测试通过。
- 结论：**PASS**
- 阻塞问题：仍有少量 legacy alias 字段，但不影响本轮主链路。
- 最小修复建议：继续收敛重复语义字段，下一步再做轻量 schema 清理。
- 不建议现在做的事：不要一次性把所有 state 字段大迁移成另一个模型。

### P14 freeze forbidden directions

- 目标：确认 forbidden directions 没有进入生产实现，包括 workflow-level MapReduce、ReAct、RAG 扩张、交易 / 预约 / 支付 / 订单、多 workflow 并行抢答、多 `final_response` / `state_update_plan` merge。
- 代码事实：`direct_response_workflow.py` 把 `RAG`、交易、预约、支付、订单写进禁止响应文本；`graph_builder.py` 仍是单图拼装；`workflow_runner.py` 仍是单 workflow 分发；`test_mapreduce_semantics.py` 也在守这个边界。
- 已有测试：`test_stage14_verification.py`、`test_mapreduce_semantics.py`、`test_p0_fact_calibration.py`。
- 实际测试结果：相关测试通过。
- 结论：**PASS**
- 阻塞问题：无生产路径证据表明禁区能力被真正接入。
- 最小修复建议：继续冻结这些方向，后续只做文档和测试加固。
- 不建议现在做的事：不要新增平权 workflow 或 workflow 级并行抢答。

## 5. 最小修复建议汇总

1. 修 `P6` 的依赖型推荐回写：补 `current_shop` 写回路径，然后重跑 `test_p6_complex_query_matrix.py`。
2. 修 `P7` 的 fallback 一致性：在 exploration fallback / verify failure 里稳定保留 `pending_clarification`。
3. 补测试覆盖：如果后续要继续推进，可以补一个真正的 `test_state_update*.py` 约束写回门，再把 `P14` 的冻结验收命名与当前仓库对齐。

## 6. 不建议现在做的事

- 不要把 `P6` 的失败通过改测试预期来吞掉。
- 不要为了修 `P7` 再引入新的 fallback handler bypass。
- 不要把 workflow 级 MapReduce 当作复杂 query 的修复手段。
- 不要把交易 / 预约 / 支付 / 订单能力接进主链路。
