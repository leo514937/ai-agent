# Architecture Phase 7 Final Regression Report

## 1. 结论

PARTIAL PASS

本阶段完成了最终验收所要求的回归验证动作，但全量测试目录并未达到全绿，因此不能写成完全 `PASS`。  
已经确认的事实是：

- `python -m compileall local_life_agent` 通过
- 与 Phase 6 删除动作直接相关的专项回归通过
- 运行 `pytest local_life_agent/tests -q` 时，失败集中在现有业务链路和 strict-guard / e2e / target-resolve / evidence-planner 等多个独立区域，共 40 个失败

这说明 Phase 7 的“最终验收”只能停在 `PARTIAL PASS`，不能误报为整体稳定。

## 2. 本阶段范围

本阶段只做最终验证，不再引入新架构分支，不再扩大兼容层删除面。

已执行的动作：

- 跑 `compileall`
- 跑 Phase 6 相关专项回归
- 跑全量测试目录，获取最终稳定性事实

## 3. 已通过的验证

以下命令已通过：

- `python -m compileall local_life_agent`
- `pytest local_life_agent/tests/test_top_intent_router.py -q`
- `pytest local_life_agent/tests/test_core_wrappers.py -q`
- `pytest local_life_agent/tests/test_planning_execution_boundary.py -q`
- `pytest local_life_agent/tests/test_phase1_architecture_boundaries.py -q`

结论：

- Phase 6 删除 `semantic/top_intent_router.py` 后没有引入语法或直接兼容性问题
- 顶层 canonical intent parser 路径仍然可用
- 兼容层删改没有破坏最直接的 boundary tests

## 4. 全量回归结果

执行命令：

- `pytest local_life_agent/tests -q`

结果：

- `1270 passed`
- `37 skipped`
- `2 xfailed`
- `40 failed`

失败分布大致落在以下区域：

- `test_comprehensive_graph_e2e.py`
- `test_context_recovery_clarification.py`
- `test_deterministic_tool_workflow.py`
- `test_e2e_llm_main_path.py`
- `test_evidence_planner.py`
- `test_llm_main_path_verification.py`
- `test_llm_semantic_capability_usage_audit.py`
- `test_llm_verbalizer_graph.py`
- `test_p6_complex_query_matrix.py`
- `test_phase7_workflows.py`
- `test_real_llm_acceptance.py`
- `test_semantic_llm_main_path.py`
- `test_strict_guards.py`
- `test_subgraph_core_integration.py`
- `test_target_resolve_candidate_set.py`

这些失败横跨多个独立能力面，说明当前仓库还存在与本次 Phase 6 兼容层清理无直接耦合的历史回归或状态漂移问题。

## 5. 解释与边界

本次 Phase 7 的目标是“最终验收与回归稳定”，但事实显示：

- 局部、目标明确的回归是稳定的
- 全量测试目录仍然有较大失败面
- 失败不是单一文件删除导致的，而是分散在多条业务链路

因此，当前不能把整个仓库标成“已最终验收完成”。

## 6. Phase 7 退出判断

可以结束本轮最终验收动作，但最终状态只能记为 `PARTIAL PASS`。

后续如果要把 Phase 7 真的推进到 `PASS`，需要单独拆出一轮针对这些失败面的修复工作，而不是继续在兼容层清理里硬塞修补。
