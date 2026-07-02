# P0 Fact Calibration and ADR Freeze Report

## 1. Conclusion

PASS with note

## 2. Scope

实际检查的文件：

- `local_life_agent/engine/workflow_registry.py`
- `local_life_agent/engine/workflow_runner.py`
- `local_life_agent/planning/orchestration_router.py`
- `local_life_agent/engine/_routes.py`
- `local_life_agent/engine/graph_builder.py`
- `local_life_agent/domain/graph_state.py`
- `local_life_agent/domain/schemas.py`
- `local_life_agent/engine/workflows/exploration_planning_workflow.py`
- `local_life_agent/engine/subgraphs/planning_subgraph.py`
- `local_life_agent/engine/subgraphs/execution_review_subgraph.py`
- `local_life_agent/engine/subgraphs/response_subgraph.py`
- `local_life_agent/engine/subgraphs/orchestration_router_shadow.py`
- `local_life_agent/planning/state_update_planner.py`
- `local_life_agent/tests/test_workflow_registry.py`
- `local_life_agent/tests/test_workflow_runner.py`
- `local_life_agent/tests/test_orchestration_router.py`
- `local_life_agent/tests/test_exploration_planning_workflow.py`
- `local_life_agent/tests/test_comprehensive_graph_e2e.py`
- `local_life_agent/tests/test_p0_fact_calibration.py`

## 3. Workflow Registry Facts

- workflow 白名单：`direct_response`, `deterministic_tool`, `discovery_decision`, `exploration_planning`, `clarification_fallback`
- handler 映射：
  - `discovery_decision` -> `_dispatch_discovery_decision`
  - `direct_response` -> `run_direct_response_workflow`
  - `deterministic_tool` -> `run_deterministic_tool_workflow`
  - `clarification_fallback` -> `run_clarification_fallback_workflow`
  - `exploration_planning` -> `run_exploration_planning_workflow`
- `status` 事实：默认 registry 里五个 workflow 都是 `registered`
- placeholder / unsupported / dead branch：
  - 默认 registry 中未看到 `unsupported` 或 `not_implemented` 注册项
  - `WorkflowRegistry` 类支持 `WORKFLOW_STATUS_NOT_IMPLEMENTED` 常量，但默认注册表未使用它
- `exploration_planning` 是否和其他 workflow 在同一 registry 层注册：是
- registry 是否允许一次返回多个 workflow：否，`lookup()` 返回单个 `WorkflowRegistration`

证据：

- [`workflow_registry.py`](D:/javacode/hm-dianping/local_life_agent/engine/workflow_registry.py#L24)
- [`workflow_registry.py`](D:/javacode/hm-dianping/local_life_agent/engine/workflow_registry.py#L151)
- [`workflow_registry.py`](D:/javacode/hm-dianping/local_life_agent/engine/workflow_registry.py#L203)

## 4. Workflow Runner Facts

- 是否单 dispatch：是
- 是否存在 `List[workflow_name]` 循环 dispatch：未发现
- 是否存在多 workflow 并行执行：未发现
- 是否存在多个 workflow 结果 merge：未发现
- 是否存在多个 `final_response` merge：未发现
- 是否存在多个 `state_update_plan` merge：未发现

具体事实：

- `workflow_runner` 从单个 `OrchestrationDecision.workflow_name` 或 `state["workflow_name"]` 读取一个值
- `WORKFLOW_REGISTRY.lookup(workflow_name)` 只返回一个 registration
- `registration.handler(route_state, decision)` 只调用一次
- 结果只做一次 dict patch 合并，不存在 workflow 列表遍历

证据：

- [`workflow_runner.py`](D:/javacode/hm-dianping/local_life_agent/engine/workflow_runner.py#L73)
- [`workflow_runner.py`](D:/javacode/hm-dianping/local_life_agent/engine/workflow_runner.py#L133)
- [`workflow_runner.py`](D:/javacode/hm-dianping/local_life_agent/engine/workflow_runner.py#L171)
- [`workflow_runner.py`](D:/javacode/hm-dianping/local_life_agent/engine/workflow_runner.py#L214)

## 5. Router / Routes Facts

- `orchestration_router` 输出形态：单值 `OrchestrationDecision`
- `orchestration_router` 当前优先级事实：
  - 先走 `_ORCHESTRATION_POLICY_TABLE`
  - 再由 `normalize_route_task()` 和一组确定性辅助函数做规则推导
  - 再由 `validate_orchestration_decision()` 进行归一化和回退
  - 该文件中未看到 LLM 路由调用
- `_routes.py` 是否 fan-out：未发现 workflow fan-out；`_route_workflow_runner` 只返回一个字符串
- `orchestration_router_shadow` 状态：
  - 逻辑角色是 shadow
  - 图上的位置是 active path 上的一个节点
  - 它不改变 active path，只写 shadow decision 并继续到 `workflow_runner`
- 不确定点：
  - 无需进一步检查

证据：

- [`orchestration_router.py`](D:/javacode/hm-dianping/local_life_agent/planning/orchestration_router.py#L39)
- [`orchestration_router.py`](D:/javacode/hm-dianping/local_life_agent/planning/orchestration_router.py#L976)
- [`orchestration_router.py`](D:/javacode/hm-dianping/local_life_agent/planning/orchestration_router.py#L1061)
- [`_routes.py`](D:/javacode/hm-dianping/local_life_agent/engine/_routes.py#L298)
- [`graph_builder.py`](D:/javacode/hm-dianping/local_life_agent/engine/graph_builder.py#L319)
- [`graph_builder.py`](D:/javacode/hm-dianping/local_life_agent/engine/graph_builder.py#L334)
- [`orchestration_router_shadow.py`](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/orchestration_router_shadow.py#L1)

## 6. GraphState / Schema Facts

- `workflow_name` 是否单值：是，`GraphState.workflow_name: str`
- 是否存在 `workflow_names` / `final_responses` / `state_update_plans` 等多主字段：未发现
- 相关单值字段：
  - `evidence_pack`
  - `answer_plan`
  - `final_response`
  - `state_update_plan`
  - `p2_decision_plan`
- 语义判断：
  - `review_results`、`tool_results`、`comparison_targets` 这类字段存在聚合语义，但它们是 workflow 内部的子结果容器，不是 workflow 级多主 merge 字段

证据：

- [`graph_state.py`](D:/javacode/hm-dianping/local_life_agent/domain/graph_state.py#L105)
- [`graph_state.py`](D:/javacode/hm-dianping/local_life_agent/domain/graph_state.py#L108)
- [`graph_state.py`](D:/javacode/hm-dianping/local_life_agent/domain/graph_state.py#L133)
- [`graph_state.py`](D:/javacode/hm-dianping/local_life_agent/domain/graph_state.py#L138)
- [`schemas.py`](D:/javacode/hm-dianping/local_life_agent/domain/schemas.py#L507)
- [`schemas.py`](D:/javacode/hm-dianping/local_life_agent/domain/schemas.py#L604)
- [`schemas.py`](D:/javacode/hm-dianping/local_life_agent/domain/schemas.py#L701)
- [`planning/state_update_planner.py`](D:/javacode/hm-dianping/local_life_agent/planning/plans/state_update_planner.py#L42)

## 7. Exploration Planning Facts

- 是否注册：是
- 是否由 `workflow_runner` 可 dispatch：是
- 是否有独立 handler：是，`run_exploration_planning_workflow`
- 是否直接使用 `dispatch_tool_call`：是，workflow 文件内有本地别名并直接调用
- 是否接入 `execution_review_subgraph`：否
- 是否与 `discovery_decision` 的 `EvidencePack` / `AnswerVerify` / `state_update_plan` 语义完全同构：否

当前差异和风险：

- `exploration_planning` 是独立 workflow，不是 `discovery_decision` 的简单复用
- 它自己完成工具调度、`EvidencePack` 构建、`AnswerPlan` 构建和答案校验
- 它不经过 `execution_review_subgraph`
- 它也不产出 `state_update_plan`

证据：

- [`workflow_registry.py`](D:/javacode/hm-dianping/local_life_agent/engine/workflow_registry.py#L191)
- [`workflow_runner.py`](D:/javacode/hm-dianping/local_life_agent/engine/workflow_runner.py#L182)
- [`graph_builder.py`](D:/javacode/hm-dianping/local_life_agent/engine/graph_builder.py#L431)
- [`exploration_planning_workflow.py`](D:/javacode/hm-dianping/local_life_agent/engine/workflows/exploration_planning_workflow.py#L24)
- [`exploration_planning_workflow.py`](D:/javacode/hm-dianping/local_life_agent/engine/workflows/exploration_planning_workflow.py#L315)
- [`exploration_planning_workflow.py`](D:/javacode/hm-dianping/local_life_agent/engine/workflows/exploration_planning_workflow.py#L656)
- [`exploration_planning_workflow.py`](D:/javacode/hm-dianping/local_life_agent/engine/workflows/exploration_planning_workflow.py#L699)

## 8. ADR Status

- ADR 文件路径：`todo/adr_p0_single_owner_workflow_no_map_reduce.md`
- ADR 核心约束摘要：
  - 当前阶段采用 single-owner workflow
  - 每轮只允许一个 active workflow 拥有最终回答
  - 禁止 workflow 级 Map-Reduce
  - 禁止 `workflow_name -> List[str]`
  - 禁止多个 workflow 并行抢答
  - 禁止多个 `final_response` merge
  - 禁止多个 `state_update_plan` merge
  - 若未来需要并行，只能发生在 workflow 内部 tool/evidence 层，并 reduce 成一个 `EvidencePack`

## 9. Tests / Commands Run

执行过的命令：

```bash
python -m compileall local_life_agent
pytest local_life_agent/tests/test_workflow_registry.py local_life_agent/tests/test_workflow_runner.py local_life_agent/tests/test_orchestration_router.py local_life_agent/tests/test_exploration_planning_workflow.py local_life_agent/tests/test_p0_fact_calibration.py -q
```

结果：

- `compileall` 成功
- `pytest` 通过：`31 passed in 1.35s`

## 10. Remaining Uncertainties

- `orchestration_router_shadow` 的角色没有不确定性：文件和图结构都能确认它是 shadow node on active path
- `workflow_runner` 的单 dispatch 没有不确定性：确认只调用一次 registration handler
- 需要特别标注的边界：
  - `execution_review_subgraph` 内部存在 workflow-internal batch tool/evidence aggregation
  - 这不是 workflow-level fan-out，也不是多 workflow merge
  - 聚合结果回到单个 workflow-owned `EvidencePack`

## 11. P0 Acceptance Judgment

- 有 `todo/p0_fact_calibration_and_adr_freeze_report.md`：PASS
- 有 `todo/adr_p0_single_owner_workflow_no_map_reduce.md`：PASS
- 报告中有可核对事实清单：PASS
- 明确列出 workflow 白名单和 handler：PASS
- 明确判断是否存在单 dispatch：PASS
- 明确判断是否存在 workflow fan-out：PASS
- 明确判断是否存在多主字段：PASS
- 明确说明 `exploration_planning` 当前接入状态：PASS
- 明确说明 `orchestration_router_shadow` 当前状态：PASS
- 不确定处写“不确定，需要进一步检查”：PASS
- 所有相关测试结果写入报告：PASS
- 没有越界进入 P1-P14：PASS

补充判断：

- P0 禁止的是 workflow-level fan-out / multi-workflow merge
- 当前内部 batch tool/evidence aggregation 符合 ADR 边界
- 未发现 workflow 级 Map-Reduce
