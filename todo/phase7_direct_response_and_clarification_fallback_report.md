# Phase 7 DirectResponseWorkflow / ClarificationFallbackWorkflow 验收报告

## 1. 结论

PASS

本轮按要求只实现 Phase 7 的两个独立 workflow：

- `DirectResponseWorkflow`
- `ClarificationFallbackWorkflow`

未引入 Phase 8，也未重写 `DiscoveryDecision` 或 `DeterministicTool` 主链路。

## 2. 交付范围

- 新增独立 `DirectResponseWorkflow` 入口模块
- 新增独立 `ClarificationFallbackWorkflow` 入口模块
- 将 `WorkflowRegistry` 中的 `direct_response` 与 `clarification_fallback` 从 placeholder/unsupported 切换为真实 callable
- 保持 `workflow_runner` 只做注册表调度，不增加业务判断
- 复用现有 `response_subgraph` 收口，不引入新的 Phase 7/Phase 8 主链路
- 补充 Phase 7 专项测试

## 3. 实现结果

### 新增工作流

- [`local_life_agent/engine/workflows/direct_response_workflow.py`](/D:/javacode/hm-dianping/local_life_agent/engine/workflows/direct_response_workflow.py)
- [`local_life_agent/engine/workflows/clarification_fallback_workflow.py`](/D:/javacode/hm-dianping/local_life_agent/engine/workflows/clarification_fallback_workflow.py)

实现要点：

- `DirectResponseWorkflow`
  - 只处理问候、能力说明、边界说明、无事实直答
  - 不调用工具
  - 不读取 DB
  - 不写 `last_recommendation_list` / `comparison_targets`
  - 输出模板化 `AnswerPlan`、`final_response`、`verifier_result`

- `ClarificationFallbackWorkflow`
  - 处理歧义、指代失败、缺少必要字段、低置信度、无结果、工具失败、受限/不支持能力
  - 不调用工具
  - 不继续硬跑下游链路
  - 对澄清场景输出 `pending_clarification` + 澄清 prompt
  - 对失败/降级场景输出可信 fallback 文本

### Registry 接入

- [`local_life_agent/engine/workflow_registry.py`](/D:/javacode/hm-dianping/local_life_agent/engine/workflow_registry.py)

`direct_response` 和 `clarification_fallback` 已由占位适配器切换为真实 callable，并注册为 `status=registered`、`entry_node=response_subgraph`。

### Runner / Route 收口

- [`local_life_agent/engine/_routes.py`](/D:/javacode/hm-dianping/local_life_agent/engine/_routes.py)

`workflow_runner` 现在只把 `discovery_decision` 送往 `planning_subgraph`，其余 workflow 统一走 `response_subgraph`，不在 runner 里追加业务判断。

### Response 收口兼容

- [`local_life_agent/engine/subgraphs/response_subgraph.py`](/D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/response_subgraph.py)

`response_subgraph` 已兼容 `response_mode="direct_response"`，确保直答 workflow 可以被直接放行，不会误入 answer generation。

## 4. 支持的场景

### DirectResponseWorkflow

覆盖：

- 普通问候
- 能力说明
- 边界说明
- 不支持能力提示
- unsafe / invalid / out_of_scope 的直接回复

不覆盖：

- 商家事实查询
- 工具调用
- 推荐 / 对比 / 排序
- RAG / 交易 / 支付 / 退款 / 预约

### ClarificationFallbackWorkflow

覆盖：

- ambiguous
- reference_failed
- missing_required_slot
- low_confidence
- no_result
- tool_failure
- unsupported
- forbidden

输出：

- 澄清问题
- trusted fallback
- 降级说明

## 5. 测试结果

### 已通过的专项命令

- `python -m compileall local_life_agent`
- `pytest local_life_agent/tests/test_phase7_workflows.py -q`
- `pytest local_life_agent/tests/test_workflow_registry.py -q`
- `pytest local_life_agent/tests/test_workflow_runner.py -q`
- `pytest local_life_agent/tests/test_orchestration_router.py -q`
- `pytest local_life_agent/tests/test_deterministic_tool_workflow.py -q`
- `pytest local_life_agent/tests/test_05_graph.py -q`
- `pytest local_life_agent/tests/test_trace_observability.py -q`
- `pytest local_life_agent/tests/test_comparison_flow.py -q -k 'compare_first_item_and_explicit_shop'`
- `pytest local_life_agent/tests/test_recommendation_flow.py -q -k 'recommendation_failure_does_not_pollute_session'`

### 结果摘要

- Phase 7 新增工作流专项测试通过
- registry / runner / router 回归通过
- graph / observability 回归通过
- deterministic_tool 相关回归通过

## 6. 已知历史敏感项

本轮额外复现到一条既有敏感测试失败：

- [`local_life_agent/tests/test_single_coupon_flow.py`](D:/javacode/hm-dianping/local_life_agent/tests/test_single_coupon_flow.py)
- `test_fuzzy_shop_does_not_call_coupon_tool`

当前失败点：

- 断言 `any(tool_name == "get_coupon_list" for tool_name, _ in calls)` 为 `False`

这个失败与 Phase 7 新增 workflow 没有直接关系，且测试名与断言语义本身不一致，建议后续单独收敛，不要混入 Phase 7 结果。

## 7. 风险与未扩展项

- 未新增 Phase 8 `ExplorationPlanningWorkflow`
- 未引入 RAG、交易、支付、退款、预约、订单 mutation
- 未重写 `DiscoveryDecisionWorkflow`
- 未重写 `DeterministicToolWorkflow`
- 未让 runner 承担更多业务判断

## 8. 结语

Phase 7 的两个独立 workflow 已完成，registry 与 response 收口也已对齐，可作为后续 Phase 8 拆分的边界基线。
