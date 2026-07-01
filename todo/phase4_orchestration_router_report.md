# Phase 4 OrchestrationRouter 影子接入验收报告

## 结论

本次已完成 Phase 4 的 shadow mode 二级路由接入。

已实现内容：

- 新增 `OrchestrationDecision` schema
- 在 `GraphState` 中新增独立影子字段 `orchestration_decision`
- 在 `planning_subgraph` 中接入 shadow-mode `orchestration_router`
- 将路由决策写入 `GraphState`、trace 和结构化日志
- 保持主链路 conditional edge 不变
- 保持 `SessionState` 不变，不做跨轮持久化

未实现内容：

- `workflow_runner`
- workflow registry
- 基于 `workflow_name` 的真实 workflow 调度
- 真实多 workflow 拆分
- router 调工具
- router 生成最终回答
- router 直接选 winner
- router 写入 `current_shop`

## 字段边界

本次新增字段仅用于 Phase 4 shadow routing：

- `orchestration_decision`

`orchestration_decision` 只存在于 `GraphState`，不会写入 `SessionState`。

## 验证结果

已通过：

- `python -m compileall local_life_agent`
- `pytest local_life_agent/tests/test_orchestration_router.py -q`
- `pytest local_life_agent/tests/test_subgraph_core_integration.py -q`
- `pytest local_life_agent/tests/test_phase_d_decision_contracts.py local_life_agent/tests/test_phase_e_state_contracts.py -q`

## 关键实现文件

- `local_life_agent/domain/schemas.py`
- `local_life_agent/domain/graph_state.py`
- `local_life_agent/planning/orchestration_router.py`
- `local_life_agent/engine/subgraphs/planning_subgraph.py`
- `local_life_agent/tests/test_orchestration_router.py`

## 风险说明

- 当前 `orchestration_router` 仍只是影子决策，不参与真实调度。
- 现有主链路仍以原有 planning / execution / response 路径为准。
- 后续若进入 Phase 5，需要单独引入 `workflow_runner` 与 registry，不可复用当前影子字段做真实分流。
