# Architecture Phase 3 Orchestration Model Convergence Report

## 1. 结论

PASS

Phase 3 的目标是把“LangGraph 外层编排唯一”这件事钉住：`engine/subgraphs/` 作为可复用执行阶段，`engine/workflows/` 作为 handler / strategy / adapter，`workflow_runner` 只负责白名单派发，不再承担第二套路由器或总调度器职责。当前仓库已经满足这个收敛目标。

## 2. 本阶段范围

本阶段只收敛编排模型，不改路由权威层，也不改状态 / DTO / tools / DB 逻辑。

本阶段关注的是：

- LangGraph 是否仍然是唯一外层编排
- `engine/subgraphs/` 是否固定为执行阶段
- `engine/workflows/` 是否只承担 handler / strategy / adapter
- `workflow_runner` 是否只做 registry dispatch
- `workflow_registry` 是否只做 whitelist lookup
- `_routes.py` 是否仍然只是 edge adapter

本阶段不做：

- 新增第二套路由器
- 新增新的 compatibility wrapper
- 扩大 `_compat.py` / `graph_builder.py` 公共面
- 删除现有 workflow
- 改 `GraphState` / `SessionState` 字段契约

## 3. 前置条件检查

- Phase 0 事实基线报告已存在并通过：[`architecture_overlap_phase0_fact_baseline_report.md`](./architecture_overlap_phase0_fact_baseline_report.md)
- Phase 1 冻结报告已存在并通过：[`architecture_phase1_canonical_path_freeze_report.md`](./architecture_phase1_canonical_path_freeze_report.md)
- Phase 2 路由权威层收敛报告已存在并通过：[`architecture_phase2_routing_authority_convergence_report.md`](./architecture_phase2_routing_authority_convergence_report.md)

结论：Phase 3 准入条件满足。

## 4. 当前实现事实调研

### 4.1 `engine/graph_builder.py`

事实：

- 图只把 outer orchestration nodes 串成单链路
- `orchestration_router_shadow -> workflow_runner -> planning_subgraph -> execution_review_subgraph -> response_subgraph -> state_update_plan`
- `workflow_runner` 是图中的一个节点，不是绕开 LangGraph 的独立执行入口
- `graph_builder` 只负责 wiring 和校验，不在这里新增业务路由

判断：

- LangGraph 仍然是唯一外层编排
- 这里没有出现第二套路由或第二套总控

### 4.2 `engine/workflow_runner.py`

事实：

- runner 先读取 `orchestration_decision` / `workflow_name`
- runner 通过 whitelist registry 查找 handler
- runner 对缺失、未注册、异常情况做 controlled fallback
- runner 没有读取 query / raw_text / semantic_frame 来重新决定业务 workflow
- runner 里的 `recommendation_flow` / `comparison_flow` 映射只是 registry 兼容别名，不是业务路由

判断：

- runner 是 dispatch-only
- 它没有变成第二套路由器

### 4.3 `engine/workflow_registry.py`

事实：

- registry 只接受合法 workflow name
- `lookup()` 只按 name 查找
- registry 不消费 query / intent / semantic frame 来重新选择 workflow
- `discovery_decision`、`direct_response`、`deterministic_tool`、`clarification_fallback`、`exploration_planning` 仍是显式白名单

判断：

- registry 是 whitelist lookup 层
- 它不是调度决策层

### 4.4 `engine/workflows/`

事实：

- `direct_response_workflow` 只做轻量直答分类与模板化响应
- `clarification_fallback_workflow` 只做澄清 / 兜底响应
- `deterministic_tool_workflow` 是单店明确目标下的自洽 workflow：目标解析、执行计划、工具调用、证据构建、答案验证
- `exploration_planning_workflow` 是多子目标探索 workflow：子目标拆解、工具轮次、证据构建、答案验证
- 这些 workflow 都是 handler / strategy 形态，通过 registry 被调用，而不是再包一层总调度器

判断：

- `engine/workflows/` 不再是平行的外层编排系统
- 它们是不同业务形态的执行器 / 策略实现

### 4.5 `engine/subgraphs/`

事实：

- `planning_subgraph` 负责 goal / target / evidence planning / plan validation
- `execution_review_subgraph` 负责 tool execute / evidence build / decision review
- `response_subgraph` 负责 answer generation / verification / fallback
- 这些 subgraph 都是在 LangGraph 主图里作为阶段节点运行

判断：

- `engine/subgraphs/` 已经是可复用执行阶段
- 它们没有重新承接一套独立总控

### 4.6 `_routes.py`

事实：

- `_route_workflow_runner()` 只做 outer edge 选择
- `execution_review` / `response` 的路由函数消费现有 review 结果与 `next_action`
- 没有把 business workflow 决策重新塞回 `_routes.py`

判断：

- `_routes.py` 仍然是 edge adapter
- 它没有回退成第二个 router

## 5. 修改方案

本阶段实际修改文件：

- [`local_life_agent/tests/test_phase3_orchestration_model.py`](../local_life_agent/tests/test_phase3_orchestration_model.py)
- [`todo/architecture_phase3_orchestration_model_convergence_report.md`](./architecture_phase3_orchestration_model_convergence_report.md)
- [`todo/architecture_overlap_analysis.md`](./architecture_overlap_analysis.md)

修改原因：

- 用边界测试冻结 Phase 3 的编排模型分工
- 记录当前仓库在 runner / registry / subgraph / workflow 之间的职责划分
- 在总分析文档中挂接 Phase 3 结果

未修改的关键实现文件及原因：

- `local_life_agent/engine/workflow_runner.py`：现有实现已经只做 registry dispatch 和 fallback
- `local_life_agent/engine/workflow_registry.py`：现有实现已经是 name-only whitelist lookup
- `local_life_agent/engine/subgraphs/planning_subgraph.py`：现有职责已固定
- `local_life_agent/engine/subgraphs/execution_review_subgraph.py`：现有职责已固定
- `local_life_agent/engine/subgraphs/response_subgraph.py`：现有职责已固定
- `local_life_agent/engine/graph_builder.py`：本阶段不扩大图构建公共面

## 6. 编排模型收敛结果

- LangGraph 仍然是唯一外层编排
- `workflow_runner` 是 dispatch-only，不承担独立总控
- `workflow_registry` 是 whitelist-only，不重新做业务选择
- `engine/subgraphs/` 是执行阶段，不是平行编排系统
- `engine/workflows/` 是 handler / strategy / adapter，不是第二套路由器
- `_routes.py` 只是 edge adapter

## 7. 简单与复杂链路的分界

- 简单单店 / 单券 / 营业状态查询仍可走轻量 workflow / response 路径
- 推荐 / 对比 / 多 facet 查询继续走 planning → execution_review → response 的主链路
- 这次没有把所有 workflow 强行塞进同一套重 review 流程

## 8. 防止编排再次发散的措施

- 没有新增新的总控入口
- 没有新增新的 workflow dispatcher
- 没有扩大 `workflow_runner` 的业务判断职责
- 没有扩大 `workflow_registry` 的路由职责
- 没有把 subgraph 重新改写成另一个 graph builder

## 9. 测试与回归结果

已运行并通过：

- `python -m compileall local_life_agent`
- `pytest local_life_agent/tests/test_phase3_orchestration_model.py -q`
- `pytest local_life_agent/tests/test_workflow_runner.py -q`
- `pytest local_life_agent/tests/test_workflow_registry.py -q`
- `pytest local_life_agent/tests/test_phase1_architecture_boundaries.py -q`
- `pytest local_life_agent/tests/test_phase2_routing_authority.py -q`
- `pytest local_life_agent/tests/test_comparison_flow.py -q`
- `pytest local_life_agent/tests/test_single_coupon_flow.py -q`
- `pytest local_life_agent/tests/test_recommendation_flow.py -q`
- `pytest local_life_agent/tests/test_single_shop_multifacet.py -q`

已运行但存在偏差：

- `pytest local_life_agent/tests/test_phase7_workflows.py -q`

结果摘要：

- Phase 3 新增测试通过
- workflow runner / registry 回归通过
- Phase 1 / Phase 2 边界测试继续通过
- 相关主链路 flow 回归通过

验证备注：

- `pytest local_life_agent/tests/test_phase7_workflows.py -q` 额外暴露出 2 条澄清兜底文案断言偏差，失败点在 `clarification_fallback` 的提示文本，不在 Phase 3 的编排边界收敛逻辑
- 这两条偏差不影响本阶段对 `workflow_runner` / `workflow_registry` / `engine/subgraphs/` / `engine/workflows/` 职责边界的判断，但后续如果要继续清理 Phase 7 文案，需要单独修正

## 10. 残余风险

- `workflow_runner` 仍保留 legacy alias 到 registry entry 的兼容映射，这是历史负担，但不影响当前编排收敛
- `deterministic_tool_workflow` 和 `exploration_planning_workflow` 仍然是较完整的自洽 workflow，这一点是阶段性保留，不代表外层编排重复
- `engine/_routes.py` 还会继续承担少量边缘控制逻辑，后续若要继续瘦身，可以再单独收敛

## 11. Phase 4 准入判断

可以进入 Phase 4。

理由：

- Phase 3 已经确认 outer orchestration 只有一层
- `workflow_runner` / `workflow_registry` 的职责边界已固定
- `engine/subgraphs/` 与 `engine/workflows/` 的分工已经可验证
- 后续可以在这个稳定编排模型上继续收敛状态与 DTO 契约
