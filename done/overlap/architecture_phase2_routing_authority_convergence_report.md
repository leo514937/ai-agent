# Architecture Phase 2 Routing Authority Convergence Report

## 1. 结论

PASS

本阶段只做路由权威层收敛的事实核查、边界确认和测试补强，没有扩大到 workflow/subgraph 编排收敛，也没有改状态、DTO、DB、tools 行为。当前仓库已经满足 Phase 2 的职责划分要求。

## 2. 本阶段范围

本阶段只收敛业务路由权威层：

- `planning/orchestration_router.py` 作为唯一业务路由决策层
- `engine/_routes.py` 只做 LangGraph 条件边转换
- `engine/subgraphs/orchestration_router_shadow.py` 只做 wrapper / observability patch
- `workflow_registry` / `workflow_runner` 只消费 router 产出的 `workflow_name` 并做注册表派发

本阶段不做：

- workflow / subgraph 编排模型重构
- 状态或 DTO 收敛
- tools / DB / mock / fixture 改造
- 新 router 模块或新的 compatibility wrapper

## 3. 前置条件检查

- Phase 0 报告存在且为 `PASS`：[`architecture_overlap_phase0_fact_baseline_report.md`](./architecture_overlap_phase0_fact_baseline_report.md)
- Phase 1 报告存在且为 `PASS`：[`architecture_phase1_canonical_path_freeze_report.md`](./architecture_phase1_canonical_path_freeze_report.md)
- Phase 1 canonical path 清单存在：[`architecture_phase1_canonical_import_paths.md`](./architecture_phase1_canonical_import_paths.md)

结论：Phase 2 准入条件满足。

## 4. 当前实现事实调研

### 4.1 `planning/orchestration_router.py`

事实：

- 这里持有完整的路由决策表，直接产出 `OrchestrationDecision`
- 决策字段包含 `workflow_name`、`orchestration_pattern`、`response_mode`、`next_action`、`requires_clarification`、`requires_tool`、`workflow_reason`、`missing_fields`、`confidence`
- 这里会根据 `task_type`、`semantic_frame`、`top_intent`、`raw_text`、`current_shop`、`comparison_targets` 等信息决定业务路由
- clarification / fallback / forbidden / comparison / deterministic / exploration 的业务分流都在这里完成

判断：

- 这是唯一业务路由决策层
- 这里负责“应该走哪条业务链路”

### 4.2 `engine/_routes.py`

事实：

- 这里主要是 LangGraph 条件边函数和 route map
- `_route_workflow_runner()` 只根据 `workflow_name`、`workflow_callable`、`response_mode` 返回边标签
- `_route_goal_review()`、`_route_decision_review()`、`_route_evidence_review()` 等函数主要消费已有 review 结果或 `next_action`
- 这里仍然有 loop guard / replan counter / fallback edge 逻辑，但它们属于边转换或执行控制，不是重新决定业务 workflow

判断：

- 对 outer workflow routing 来说，它只是 edge adapter
- 没有发现它重新读取 query 文本来决定业务 workflow

### 4.3 `engine/subgraphs/orchestration_router_shadow.py`

事实：

- 该节点调用 `route_orchestration(state)`
- 该节点补 observability / trace patch
- 没有独立的业务路由决策函数
- 其输出字段与 canonical router 输出对齐

判断：

- 这里只是 wrapper + observability patch
- 没有承载独立业务判断

### 4.4 `engine/workflow_registry.py`

事实：

- registry 只维护合法 workflow 白名单
- `lookup()` 只接受 `workflow_name`
- 不存在基于 `query`、`task_type`、`semantic_frame` 的重新路由逻辑
- 未注册 workflow 的 fallback 逻辑不在 registry 内部做，实际由 workflow runner 处理

判断：

- registry 只做 registry / dispatch guard
- 没有业务路由职责

### 4.5 `engine/workflow_runner.py`

事实：

- runner 只读取 router 已产出的 `workflow_name` / `orchestration_decision`
- 它先走 whitelist registry，再调用注册的 handler
- 对非法或缺失 workflow_name 走 controlled fallback
- 没有根据 query / intent / semantic_frame 自行选择 workflow
- 存在 `recommendation_flow` / `comparison_flow` 到 `discovery_decision` 的旧别名映射，但它只是 registry lookup 兼容，不是业务决策

判断：

- runner 没有变成第二套路由器
- 它仍然是派发层

### 4.6 `engine/graph_builder.py`

事实：

- 图构建只 wiring route functions、subgraphs、workflow runner
- 它消费 `OrchestrationDecision` 和 route function 的结果
- 没有在这里新增业务路由判断

判断：

- graph_builder 仍然是构图与挂边，不是新增 router

## 5. 修改方案

本阶段实际修改文件：

- [`local_life_agent/tests/test_phase2_routing_authority.py`](../local_life_agent/tests/test_phase2_routing_authority.py)
- [`todo/architecture_phase2_routing_authority_convergence_report.md`](./architecture_phase2_routing_authority_convergence_report.md)
- [`todo/architecture_overlap_analysis.md`](./architecture_overlap_analysis.md)

修改原因：

- 补充 Phase 2 路由权威层边界测试
- 记录事实调研和收敛结论
- 在总分析文档中挂接 Phase 2 结果

未修改的关键实现文件及原因：

- `local_life_agent/planning/orchestration_router.py`：现有实现已经是业务路由权威层，无需重写
- `local_life_agent/engine/_routes.py`：现有实现已经是 edge adapter，无需新增业务路由
- `local_life_agent/engine/subgraphs/orchestration_router_shadow.py`：现有实现已经是 wrapper，无需改写
- `local_life_agent/engine/workflow_registry.py`：现有实现已经是 whitelist registry，无需改写
- `local_life_agent/engine/workflow_runner.py`：现有实现已经只做派发与 fallback，无需改写
- `local_life_agent/engine/graph_builder.py`：本阶段不扩大公共面

## 6. 路由权威层收敛结果

- `workflow_name` 的权威来源：`planning/orchestration_router.py`
- `route action` 的权威来源：`planning/orchestration_router.py` 产出的 `OrchestrationDecision`
- `fallback reason` / `clarification route` 的归属：业务层归 router，执行失败后的 controlled degradation 保留给 workflow / response 层
- `_routes.py` 当前职责：只做 LangGraph 条件边转换和少量已存在的 loop guard
- `shadow router` 当前职责：wrapper / trace patch，不承载独立业务判断
- `workflow_registry` 当前职责：合法 workflow 白名单和注册表派发，不重新选择 workflow

## 7. 防止兼容层变多的措施

- 没有新增新的 router 模块
- 没有新增新的 compatibility wrapper
- 没有扩大 `_compat.py` 的公共面
- 没有扩大 `graph_builder.py` 的公共面
- 没有违反 Phase 1 canonical import path 冻结

## 8. 测试与回归结果

已运行并通过：

- `python -m compileall local_life_agent`
- `pytest local_life_agent/tests/test_phase2_routing_authority.py -q`
- `pytest local_life_agent/tests/test_phase1_architecture_boundaries.py -q`
- `pytest local_life_agent/tests/test_orchestration_router.py -q`
- `pytest local_life_agent/tests/test_p2_router_priority.py -q`
- `pytest local_life_agent/tests/test_router_rule_policy_guard.py -q`
- `pytest local_life_agent/tests/test_workflow_registry.py -q`
- `pytest local_life_agent/tests/test_comparison_flow.py -q`
- `pytest local_life_agent/tests/test_single_coupon_flow.py -q`
- `pytest local_life_agent/tests/test_recommendation_flow.py -q`
- `pytest local_life_agent/tests/test_single_shop_multifacet.py -q`

结果摘要：

- Phase 2 新增测试通过：6 passed
- Phase 1 boundary tests 继续通过：4 passed
- router / priority / guard / registry 回归通过
- comparison / coupon / recommendation / single-shop 主链路回归通过
- `test_comparison_flow.py` 和 `test_recommendation_flow.py` 仍有已知 pydantic warning / xfailed 项，但无失败

## 9. 残余风险

- `engine/_routes.py` 仍有 review / replan / fallback 的边缘控制逻辑，这些更适合 Phase 3/7 继续细化
- `workflow_runner` 保留了 legacy alias 到 registry entry 的兼容映射，这是当前历史负担，但不构成 Phase 2 阻塞
- `workflow_registry` 的 controlled fallback 仍由 runner 负责，不在本阶段继续拆分
- `tools/db_client.py`、`tools/db_tools.py`、`SessionState` 写回责任、`graph_builder` 公共面压缩都仍然是后续阶段议题

## 10. Phase 3 准入判断

可以进入 Phase 3。

理由：

- Phase 2 已经确认业务路由权威层唯一
- `_routes.py` 没有承担第二套路由器职责
- shadow router 只是 wrapper
- workflow registry / runner 没有重新做业务路由
- 没有引入新的 wrapper 或同功能模块
- 没有扩大 `_compat.py` / `graph_builder.py` 公共面

