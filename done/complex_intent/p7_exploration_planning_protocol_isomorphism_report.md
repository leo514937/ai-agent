# P7 exploration_planning 协议同构与共享 adapter 报告

## 范围

本次仅覆盖 `complex_intent_query_architecture_stabilization_plan.md` 中的 P7：`exploration_planning` 协议同构与共享 adapter。

明确未进入 P8 及后续阶段。

## 已完成内容

- 新增共享适配层 `local_life_agent/planning/shared/evidence_adapter.py`
- 为探索工作流补齐 `EvidencePack` / `AnswerPlan` / state writeback 的共享转换入口
- 将 `exploration_planning_workflow` 保持为独立 workflow handler，没有引入 subgraph / workflow merge / fan-out
- 给 `EvidenceItem` 与 `EvidencePack` 补充了探索协议所需字段
- 让 `state_update_plan` 识别 `workflow_name=exploration_planning`
- 增加 P7 专属回归测试 `local_life_agent/tests/test_p7_exploration_protocol.py`

## 关键实现点

- `exploration_planning` 继续作为独立 workflow 运行，不依赖新的平行 workflow 链路
- 工具结果先进入共享 adapter，再归一到单个 `EvidencePack`
- 探索计划只保留 `ExplorationPlan` 允许的字段，避免把调试字段塞进协议对象
- 当工具结果出现失败时，探索 workflow 直接回退，避免带着失败事实继续生成成功答案
- `state_update_plan` 通过 `workflow_name` 区分探索写回逻辑，并复用共享 adapter 的写回规则

## 验证结果

已通过：

- `python -m compileall local_life_agent`
- `pytest local_life_agent/tests/test_p7_exploration_protocol.py -q`
- `pytest local_life_agent/tests/test_exploration_planning_workflow.py -q`
- `pytest local_life_agent/tests/test_orchestration_router.py -q`

## 结论

P7 的探索规划协议已完成同构化收敛，shared adapter 已接入，独立 workflow 边界保持不变。

当前实现仍保留保守回退策略：只要探索链路中出现失败工具结果，就回退而不伪装成功，这与现有仓库的安全语义一致。
