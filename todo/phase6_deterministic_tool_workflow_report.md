# Phase 6 DeterministicToolWorkflow 验收报告

## 1. 结论

PASS

本轮按用户要求只实现 Phase 6 的最小独立 `DeterministicToolWorkflow`，未引入 Phase 7 / Phase 8 新 workflow。

## 2. 交付范围

- 新增独立 `DeterministicToolWorkflow` 入口模块
- 将 `WorkflowRegistry` 中的 `deterministic_tool` 从 `not_implemented` 升级为真实 callable
- 仅处理明确单店 target 的确定性事实查询
- 复用现有 `Execution` / `ToolResult` / `EvidencePack` / `AnswerPlan` / verifier 链路
- 保持 DiscoveryDecision 主链路不污染
- 补充 Phase 6 专项测试

## 3. 实现结果

### 新增工作流

- [`local_life_agent/engine/workflows/deterministic_tool_workflow.py`](/D:/javacode/hm-dianping/local_life_agent/engine/workflows/deterministic_tool_workflow.py)

实现要点：

- 先做单店 target 解析
- 只在 target 唯一时调用工具
- target 不明确、多 target、`第二家` 无历史候选时，直接进入现有 clarification / fallback 分支
- 执行单次 tool call 后，构造 `ExecutionPlan`、`ToolResult`、`EvidencePack`、`AnswerPlan`
- 使用现有 verifier 校验最终回答
- 成功时不写入 `last_recommendation_list`、`last_answer_order`、`comparison_targets`
- 不做 ranking，不调用 `search_shops`

### Registry 接入

- [`local_life_agent/engine/workflow_registry.py`](/D:/javacode/hm-dianping/local_life_agent/engine/workflow_registry.py)

`deterministic_tool` 已由占位适配器切换为真实 callable。

### Runner 路由

- [`local_life_agent/engine/_routes.py`](/D:/javacode/hm-dianping/local_life_agent/engine/_routes.py)

`workflow_runner` 对 `deterministic_tool` 现在路由到 `response_subgraph`，避免回到推荐主链路。

## 4. 支持的任务映射

明确支持：

- `shop_status` -> `check_open_status`
- `shop_distance` -> `get_distance_eta`
- `shop_coupon` -> `get_coupon_list`
- `shop_review_summary` -> `get_shop_review_summary`
- `shop_price` -> `get_shop_detail`

按现有 task_type 且契约明确时，额外兼容：

- `deal` / `group_deal` 相关 task -> `get_deal_list`

未明确支持的情况保持澄清，不扩展到新 workflow。

## 5. 目标解析与安全边界

已覆盖的安全边界：

- target 不明确时不调用工具
- 多 target 时不调用工具
- 无历史候选却问“第二家”时不调用工具
- 仍沿用现有 clarification / fallback adapter

未做的事情：

- 不新增 `DirectResponseWorkflow`
- 不新增 `ClarificationFallbackWorkflow`
- 不新增 `ExplorationPlanningWorkflow`
- 不把 runner 写成业务判断中心
- 不抽共享 Core

## 6. 测试结果

### 新增专项测试

- [`local_life_agent/tests/test_deterministic_tool_workflow.py`](/D:/javacode/hm-dianping/local_life_agent/tests/test_deterministic_tool_workflow.py)

覆盖点：

- registry 真实 callable
- shop_status 走 `check_open_status`
- target 缺失不调工具
- 多 target 不选第一家
- `第二家` 无历史候选不调工具
- runner 能正确分发到 deterministic workflow

### 已通过命令

- `python -m compileall local_life_agent`
- `pytest local_life_agent/tests/test_deterministic_tool_workflow.py -q`
- `pytest local_life_agent/tests/test_workflow_registry.py -q`
- `pytest local_life_agent/tests/test_workflow_runner.py -q`
- `pytest local_life_agent/tests/test_orchestration_router.py -q`
- `pytest local_life_agent/tests/test_05_graph.py -q`
- `pytest local_life_agent/tests/test_trace_observability.py -q`
- `pytest local_life_agent/tests/test_comparison_flow.py -q -k 'compare_first_item_and_explicit_shop'`
- `pytest local_life_agent/tests/test_recommendation_flow.py -q -k 'recommendation_failure_does_not_pollute_session'`
- `pytest local_life_agent/tests/test_single_coupon_flow.py -q -k 'fuzzy_shop_does_not_call_coupon_tool'`

### 结果摘要

- Phase 6 专项测试通过
- registry / runner / graph / observability 回归通过
- 相关 Phase 5 顺序敏感回归未受影响

## 7. 风险与未扩展项

- 当前只做最小独立 workflow，没有抽共享 Core
- 未新增 Phase 7 / Phase 8 workflow
- `deal` 映射仅在 task_type / contract 明确时启用，保持保守
- 全量测试仍可能存在历史失败，但本轮未引入新的 Phase 6 regression

## 8. 结语

Phase 6 的最小独立 `DeterministicToolWorkflow` 已完成，可作为后续 Phase 7 / Phase 8 拆分的边界基线。
