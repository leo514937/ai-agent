# Phase 5 Workflow Runner / Registry 验收报告

## 1. 结论

PARTIAL PASS

## 2. 验收范围

本轮只做 Phase 5 的验收、审计、测试和报告，不继续开发新功能。

## 3. 代码审计结果

### 真实位置

- [`local_life_agent/engine/workflow_registry.py`](/D:/javacode/hm-dianping/local_life_agent/engine/workflow_registry.py)
- [`local_life_agent/engine/workflow_runner.py`](/D:/javacode/hm-dianping/local_life_agent/engine/workflow_runner.py)
- [`local_life_agent/engine/graph_builder.py`](/D:/javacode/hm-dianping/local_life_agent/engine/graph_builder.py)
- [`local_life_agent/engine/subgraphs/orchestration_router_shadow.py`](/D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/orchestration_router_shadow.py)
- [`local_life_agent/planning/orchestration_router.py`](/D:/javacode/hm-dianping/local_life_agent/planning/orchestration_router.py)
- [`local_life_agent/domain/state.py`](/D:/javacode/hm-dianping/local_life_agent/domain/state.py)
- [`local_life_agent/domain/schemas.py`](/D:/javacode/hm-dianping/local_life_agent/domain/schemas.py)
- [`local_life_agent/observability/file_logger.py`](/D:/javacode/hm-dianping/local_life_agent/observability/file_logger.py)
- [`local_life_agent/observability/trace.py`](/D:/javacode/hm-dianping/local_life_agent/observability/trace.py)

### 审计结论

- `WorkflowRegistry` 是白名单注册表，合法名称被限制在 5 个枚举值内。
- `workflow_runner` 只读取 `orchestration_decision.workflow_name` 并查 registry，再调 handler。
- `discovery_decision` 已真实注册并接入主链路薄适配。
- `deterministic_tool`、`direct_response`、`clarification_fallback`、`exploration_planning` 都保持显式占位或适配器，没有提前拆成独立 workflow。
- `workflow_runner` 没有调用工具、读 DB、做业务排序或直接生成最终回答。
- `graph_builder` 已把 `orchestration_router_shadow -> workflow_runner` 接线接上，且仍保留 Phase 4 shadow 路径。
- `var/python_service.log` 中可观察到 `workflow_runner` 与 `orchestration_router_shadow` 的结构化日志。

## 4. Registry 验收

- 白名单 key：`direct_response`、`deterministic_tool`、`discovery_decision`、`exploration_planning`、`clarification_fallback`
- `discovery_decision`：`status=registered`，`entry_node=planning_subgraph`
- `direct_response`：`status=unsupported`
- `deterministic_tool`：`status=not_implemented`，通过 Phase 5 兼容适配器返回 fallback
- `clarification_fallback`：`status=not_implemented`
- `exploration_planning`：`status=not_implemented`
- 非法 workflow 和未注册 workflow 都会拒绝，不会静默执行

## 5. Runner 验收

- `workflow_runner` 读取 `orchestration_decision`，并优先以其中的 `workflow_name` 为准。
- 对缺失、非法、未注册、未实现和异常路径都有安全 fallback。
- runner 没有重新判断用户意图，也没有根据 `response_mode` 或 `task_type` 自行分流。
- runner 没有绕过 registry 直接执行业务 workflow。
- runner 日志能记录 `workflow_name`、`orchestration_pattern`、`workflow_run_status`、`workflow_runner_reason`、`workflow_runner_error`、`workflow_registered`、`workflow_callable`、`next_action`、`latency_ms`。

## 6. DiscoveryDecision 接入验收

- `discovery_decision` 仍复用当前主链路雏形，没有被重写成新的独立业务中心。
- registry 命中的真实可执行入口仍然是 `planning_subgraph`。
- 推荐 / 搜索 / 对比 / 条件筛选的现有主链路没有被破坏。
- `DecisionPlan / EvidencePack / AnswerPlan` 仍可追踪。

## 7. Scope Drift 检查

- 没有提前实现 Phase 6 / Phase 7 / Phase 8 的独立 workflow。
- 没有引入 RAG、交易、支付、退款、预约、订单 mutation、自由 ReAct loop 或开放式 multi-agent handoff。
- 没有把 `workflow_runner` 写成新的业务判断中心。
- 没有发现 Phase 5 新增 regression。

## 8. Fallback 验收

- `workflow_name` 为空或缺失：`WORKFLOW_DECISION_MISSING`
- `workflow_name` 非法：`WORKFLOW_NOT_REGISTERED`
- `workflow_name` 未注册：`WORKFLOW_NOT_REGISTERED`
- `workflow_name` 合法但未实现：`WORKFLOW_NOT_IMPLEMENTED`
- workflow callable 抛异常：`WORKFLOW_RUN_FAILED`
- fallback 只返回安全调度结果，不编造事实，不污染会话业务字段

## 9. 日志验收

### 观察到的字段

- `timestamp`
- `session_id`
- `turn_id`
- `node_name`
- `workflow_name`
- `orchestration_pattern`
- `workflow_reason`
- `input_summary`
- `output_summary`
- `state_keys_changed`
- `latency_ms`
- `status`
- `next_action`
- `error_code`
- `error_message`
- `workflow_registered`
- `workflow_callable`

### 日志摘要

- `var/python_service.log` 已存在且持续写入。
- `workflow_runner` 命中时可看到 `WORKFLOW_RUNNER` 结构化日志。
- `orchestration_router_shadow` 命中时可看到 `ROUTE_DECISION` 与 `NODE_EVENT`。
- 敏感信息未在抽样日志中暴露。

## 10. 测试结果

### 已通过的专项命令

- `python -m compileall local_life_agent`
- `pytest local_life_agent/tests/test_orchestration_router.py -q`
- `pytest local_life_agent/tests/test_workflow_registry.py -q`
- `pytest local_life_agent/tests/test_workflow_runner.py -q`
- `pytest local_life_agent/tests/test_05_graph.py -q`
- `pytest local_life_agent/tests/test_trace_observability.py -q`
- `pytest local_life_agent/tests/test_comparison_flow.py -q -k 'compare_first_item_and_explicit_shop'`
- `pytest local_life_agent/tests/test_recommendation_flow.py -q -k 'recommendation_failure_does_not_pollute_session'`
- `pytest local_life_agent/tests/test_single_coupon_flow.py -q -k 'fuzzy_shop_does_not_call_coupon_tool'`
- `pytest local_life_agent/tests/test_comparison_flow.py local_life_agent/tests/test_recommendation_flow.py local_life_agent/tests/test_single_coupon_flow.py -q -k 'compare_first_item_and_explicit_shop or recommendation_failure_does_not_pollute_session or fuzzy_shop_does_not_call_coupon_tool'`

### 结果摘要

- Phase 5 相关专项测试全部通过。
- 点名的 3 条历史顺序敏感用例单跑通过，合跑也通过。
- `pytest local_life_agent/tests -q` 全量回归超时后仍显示存在历史失败与环境缺失。

## 11. 全量回归结果

全量命令：

```bash
pytest local_life_agent/tests -q
```

结果：

- 命令在 120s 超时后中断。
- 结果摘要：`27 failed, 934 passed, 12 skipped, 2 xfailed, 25 errors`
- 主要错误包含：
  - `local_life_agent/tests/test_mock_data_normalization.py` 读取缺失的 `local_life_agent/mock_data/shops.json`
  - 一些旧的 LLM / 流式 / 语义回退断言失败
  - 个别旧的语义和回答回退测试仍然不稳定
- 这些失败不属于 Phase 5 新增 regression。

## 12. 文档回写检查

本轮实际只更新了本报告本身，用于把旧的 PASS 记录改成当前验收结果。

## 13. 未处理项

- 全量回归中的历史失败仍需单独收敛。
- `local_life_agent/mock_data/shops.json` 缺失导致一批归一化测试无法运行。
- 旧的语义 / 流式 / 回退测试中仍有与 Phase 5 无关的失败。

## 14. 是否允许进入 Phase 6

允许，但建议先单独处理全量回归中的历史失败和缺失数据，再继续扩大实现面。

## 附录：本轮不做的事情

- 不把主链路切成真实多 workflow 分流
- 不把 `orchestration_router` 的 shadow 结果当作最终业务事实
- 不拆出 `DeterministicToolWorkflow`、`DirectResponseWorkflow` 等独立执行链
- 不继续扩大实现范围
- 不修复全量回归里与 Phase 5 无关的历史失败

## Phase 9 事实补记

- 后续 Phase 9 重新核验已通过，且未引入新 workflow / tool。
- 当前 registry 仍只保留五条 workflow 白名单，`placeholder` 分支已清理。
- 当前全量回归仍为 `1013 passed, 12 skipped, 2 xfailed`。
