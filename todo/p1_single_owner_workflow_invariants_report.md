# P1 Single-Owner Workflow Invariants Report

## 1. Conclusion

PASS

## 2. P0 Inputs

- P0 report: `todo/p0_fact_calibration_and_adr_freeze_report.md`
- ADR: `todo/adr_p0_single_owner_workflow_no_map_reduce.md`
- P0 inherited facts:
  - 当前 workflow 白名单固定为 `direct_response`, `deterministic_tool`, `discovery_decision`, `exploration_planning`, `clarification_fallback`
  - `workflow_runner` 之前已确认是单 dispatch
  - registry `lookup()` 返回单个 `WorkflowRegistration`
  - 未发现 `workflow_names` / `final_responses` / `state_update_plans` 多主字段
  - `_routes.py` 未发现 workflow fan-out
  - `orchestration_router_shadow` 为 active path 上的 shadow node
  - `execution_review_subgraph` 允许 workflow 内部 batch tool/evidence aggregation，但不是顶层 workflow fan-out

## 3. Scope

本轮实际检查 / 修改的文件：

- `local_life_agent/domain/schemas.py`
- `local_life_agent/engine/workflow_runner.py`
- `local_life_agent/tests/test_p0_fact_calibration.py`
- `local_life_agent/tests/test_p1_single_owner_invariants.py`
- `todo/p0_fact_calibration_and_adr_freeze_report.md`

明确未修改：

- `local_life_agent/engine/workflow_registry.py`
- `local_life_agent/engine/_routes.py`
- `local_life_agent/engine/graph_builder.py`
- `local_life_agent/planning/orchestration_router.py`

P0 继承背景，仅作为事实前提，不作为本轮变更：

- `local_life_agent/engine/subgraphs/execution_review_subgraph.py`

## 4. Invariants Locked

- `workflow_name` 单值：PASS
  - `OrchestrationDecision.workflow_name` 增加了单值拒绝校验
  - `workflow_runner` 对 list / tuple / set 的 `workflow_name` 做了空值降级，避免循环 dispatch
- `workflow_runner` 单 dispatch：PASS
  - handler 仅调用一次
  - 运行时没有任何 `List[workflow_name]` 循环 dispatch
- registry 单 lookup：PASS
  - `WORKFLOW_REGISTRY.lookup(name)` 仍然只返回一个 registration
  - 未新增 multi-lookup / fanout API
- routes 无 workflow fan-out：PASS
  - `_route_workflow_runner` 仍只返回单个目标 node
  - 复杂 query 只产生单个 `workflow_name`
- 无 `workflow_names` / `final_responses` / `state_update_plans` 多主字段：PASS
  - 生产 schema / state 未新增这些字段
- 单 `EvidencePack` / `DecisionPlan` / `AnswerPlan` / `final_response` / `state_update_plan`：PASS
  - 这些字段仍保持单对象 / 单值语义
- 复杂 query 不拆多个顶层 workflow：PASS
  - 复杂 query 仅路由到一个合法 `workflow_name`

证据：

- [`schemas.py`](D:/javacode/hm-dianping/local_life_agent/domain/schemas.py#L721)
- [`workflow_runner.py`](D:/javacode/hm-dianping/local_life_agent/engine/workflow_runner.py#L25)
- [`workflow_runner.py`](D:/javacode/hm-dianping/local_life_agent/engine/workflow_runner.py#L55)
- [`workflow_runner.py`](D:/javacode/hm-dianping/local_life_agent/engine/workflow_runner.py#L87)
- [`test_p1_single_owner_invariants.py`](D:/javacode/hm-dianping/local_life_agent/tests/test_p1_single_owner_invariants.py#L58)
- [`test_p1_single_owner_invariants.py`](D:/javacode/hm-dianping/local_life_agent/tests/test_p1_single_owner_invariants.py#L100)
- [`test_p1_single_owner_invariants.py`](D:/javacode/hm-dianping/local_life_agent/tests/test_p1_single_owner_invariants.py#L170)
- [`test_p1_single_owner_invariants.py`](D:/javacode/hm-dianping/local_life_agent/tests/test_p1_single_owner_invariants.py#L309)
- [`test_p1_single_owner_invariants.py`](D:/javacode/hm-dianping/local_life_agent/tests/test_p1_single_owner_invariants.py#L335)

## 5. Code Changes

- [`local_life_agent/domain/schemas.py`](D:/javacode/hm-dianping/local_life_agent/domain/schemas.py#L723)
  - 为 `OrchestrationDecision.workflow_name` 加了单值拒绝校验，list / tuple / set 直接报错
- [`local_life_agent/engine/workflow_runner.py`](D:/javacode/hm-dianping/local_life_agent/engine/workflow_runner.py#L25)
  - 增加 `_coerce_single_workflow_name()`，将 list / tuple / set 统一降级为缺失值
  - 这样 runner 只会走单个 lookup，不会误把多值工作流名当成可迭代目标
- [`local_life_agent/engine/subgraphs/execution_review_subgraph.py`](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/execution_review_subgraph.py#L1)
  - 保持上一轮的术语收口，不改运行逻辑
- [`todo/p0_fact_calibration_and_adr_freeze_report.md`](D:/javacode/hm-dianping/todo/p0_fact_calibration_and_adr_freeze_report.md#L1)
  - 保持 P0 收口报告为 `PASS with note`

## 6. Test Changes

- [`local_life_agent/tests/test_p1_single_owner_invariants.py`](D:/javacode/hm-dianping/local_life_agent/tests/test_p1_single_owner_invariants.py#L1)
  - 新增 `workflow_name` 单值类型测试
  - 新增 `OrchestrationDecision.workflow_name` list 拒绝测试
  - 新增 workflow runner 单 dispatch 测试
  - 新增 list 型 `workflow_name` 不会触发多 handler 的测试
  - 新增 registry 单 lookup / 无 multi API 测试
  - 新增 routes 无 fan-out 测试
  - 新增 GraphState / schemas 多主字段扫描测试
  - 新增单输出对象形态测试

## 7. Commands Run

执行命令：

```bash
python -m compileall local_life_agent
pytest local_life_agent/tests/test_workflow_registry.py \
       local_life_agent/tests/test_workflow_runner.py \
       local_life_agent/tests/test_orchestration_router.py \
       local_life_agent/tests/test_p0_fact_calibration.py \
       local_life_agent/tests/test_p1_single_owner_invariants.py -q
```

结果：

- `compileall` 成功
- `pytest` 通过：`34 passed in 0.72s`

## 8. P1 Acceptance Judgment

- 有 `todo/p1_single_owner_workflow_invariants_report.md`：PASS
- 新增或补齐 P1 自动化测试：PASS
- `workflow_name` 单值被测试锁住：PASS
- `workflow_runner` 单 dispatch 被测试锁住：PASS
- registry 单 lookup 被测试锁住：PASS
- `_routes.py` 无 workflow fan-out 被测试锁住：PASS
- `GraphState` / `schemas` 无多主字段被测试锁住：PASS
- 复杂 query 不会产生多个顶层 workflow 被测试锁住：PASS
- 所有 P1 相关测试通过：PASS
- 没有越界进入 P2-P14：PASS
- 没有删除合法的 workflow 内部 batch / evidence 聚合：PASS
- 报告中明确说明 P0 的 PARTIAL PASS 边界在 P1 如何处理：PASS

## 9. Remaining Risks

- workflow 内部 batch tool execution 仍然存在
- 这不是顶层 workflow Map-Reduce，因为它没有产生多个 active workflow、没有多个 final_response merge、没有多个 state_update_plan merge
- 还有一些更深层的一致性问题仍留在后续 phase，例如 P2/P3/P4 才会处理的 router 语义、facet 协议和 Evidence / Decision / Answer 协议收敛

## 10. Out of Scope Deferred to Later Phases

- P2 router 决策优先级
- P3 facet 协议
- P4 Evidence / Decision / Answer 协议
- P5 SessionState 写回
- P7 exploration_planning 协议同构
