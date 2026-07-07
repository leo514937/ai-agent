# Phase 6 / 5a-b / 5a-c cross-layer convergence report

## 结论
PASS

## 前置门禁验收结果
本轮收口前，相关前置门禁已满足：

1. 第 5 批前半段能力已稳定：
   - `ContextualizedTurn / FocusContext`
   - `ErrorEnvelope / EarlyResponseDirective`
   - `hard_guard / slot_extractor / active_turn_resolver` 边界收紧
   - `pending_clarification / clarification_request` 收敛
2. 第 6 批前两段已稳定：
   - `5a-a load_session` 已拆分
   - `5a-b target_resolve` 权威已归第二层
3. 本轮补齐后，`5a-c planning_subgraph` 已作为兼容编排层稳定运行，并通过相关回归。

## 修改前真实代码调研结果
本次收口前，真实代码已经呈现出第 6 批目标形态：

1. 第一层不再承担实体解析权威：
   - `local_life_agent/target/context_recovery.py` 只保留上下文/引用信号，不再写 `resolved_target`
   - `local_life_agent/engine/subgraphs/understanding_subgraph.py` 不再把第一层解析结果回写成单一真值
2. 第二层承担 target resolve：
   - `local_life_agent/engine/subgraphs/planning_subgraph.py::_h_target_resolve_candidate_set`
   - comparison / recommendation / single_shop 的目标解析都进入第二层候选集与澄清决策
3. shared service 已经存在并被复用：
   - `local_life_agent/planning/goal/goal_planner.py`
   - `local_life_agent/planning/evidence/evidence_planner.py`
   - `local_life_agent/planning/plans/plan_validator.py`
   - `local_life_agent/planning/plans/execution_plan_builder.py`
4. `planning_subgraph` 已更多呈现为兼容编排层：
   - 负责路由、目标解析、证据规划、计划校验的串联
   - 不再把第一层的 `resolved_target` 当作权威入口

## 5a-a / 5a-b / 5a-c 完成状态

### 5a-a：load_session 拆分
已完成。

当前 session 读取链路按职责分离为：
- `validate_session_input`
- `load_session_state`
- `expand_session_context`

非法输入不会提前触发无意义 session I/O，旧字段仍保持兼容展开。

### 5a-b：target_resolve 权威归第二层
已完成。

当前目标解析的权威入口仍在第二层：
- `planning_subgraph._h_target_resolve`
- `planning_subgraph._h_target_resolve_candidate_set`

第一层仅产出引用/上下文信号，不再直接产出 `resolved_target` 真值。

### 5a-c：planning_subgraph 收缩
已完成到兼容编排层状态。

当前 `planning_subgraph` 主要承担：
- 编排 goal review
- 编排 target resolve
- 编排 evidence planner
- 编排 plan validator
- 处理 clarify / fallback / execute 路由

共享能力已经下沉到第二层服务，`planning_subgraph` 不再承担独立的一整套平行实现。

## 第二层 target_resolve 权威入口说明
当前真实权威入口是：

1. `local_life_agent/engine/subgraphs/planning_subgraph.py::_h_target_resolve`
2. `local_life_agent/engine/subgraphs/planning_subgraph.py::_h_target_resolve_candidate_set`

它们负责：
- 解析显式店名、序数引用、指代引用、比较对象引用
- 生成候选集 / 澄清 / resolved target
- 为 recommendation / comparison / single_shop 提供统一目标解析结果

第一层 `context_recovery` 不再写实体解析权威。

## planning_subgraph 收缩说明
`planning_subgraph` 的职责边界已经明显收缩：

- 不再作为第一层解析真值的来源
- 不再与第二层形成并行实体解析体系
- 将目标解析、证据规划、计划校验都串到共享 service 上
- 保留兼容路由和老入口，避免破坏现有主链路

这符合第 6 批“收缩为 dispatch / orchestration 层”的目标。

## 与第 5 / 第 6 批的兼容关系
本轮收口没有破坏前序批次能力：

- `ContextualizedTurn / FocusContext` 继续可用
- `ErrorEnvelope / EarlyResponseDirective` 继续可用
- clarification 恢复链路保持
- recommendation / comparison / single_shop / coupon / e2e 主链路保持

## 实际修改文件清单
本轮新增：

- [`todo/three_layer_phase6_5a_b_5a_c_cross_layer_convergence_report.md`](./three_layer_phase6_5a_b_5a_c_cross_layer_convergence_report.md)

阶段实现相关文件（已存在于仓库中）：

- [`local_life_agent/target/context_recovery.py`](../local_life_agent/target/context_recovery.py)
- [`local_life_agent/engine/subgraphs/understanding_subgraph.py`](../local_life_agent/engine/subgraphs/understanding_subgraph.py)
- [`local_life_agent/engine/subgraphs/planning_subgraph.py`](../local_life_agent/engine/subgraphs/planning_subgraph.py)
- [`local_life_agent/engine/subgraphs/state_update_plan.py`](../local_life_agent/engine/subgraphs/state_update_plan.py)
- [`local_life_agent/planning/plans/state_update_planner.py`](../local_life_agent/planning/plans/state_update_planner.py)
- [`local_life_agent/target/reference_resolver.py`](../local_life_agent/target/reference_resolver.py)
- [`local_life_agent/planning/goal/goal_draft.py`](../local_life_agent/planning/goal/goal_draft.py)
- [`local_life_agent/engine/subgraphs/execution_review_subgraph.py`](../local_life_agent/engine/subgraphs/execution_review_subgraph.py)
- [`local_life_agent/planning/orchestration_router.py`](../local_life_agent/planning/orchestration_router.py)

## 明确没有做的第 7 批和后续内容
未做：

- SessionStore interface 抽象
- 分区 TTL
- RedisSessionStore
- Redis fallback
- Trace / Eval / ResponseContract V2
- complex_orchestrator / MapReduce
- ClaimVerifier L2/L3

## 测试结果
已通过：

- `python -m pytest local_life_agent/tests/test_phase6_session_load_split.py -q`
- `python -m pytest local_life_agent/tests/test_target_resolve_candidate_set.py -q`
- `python -m pytest local_life_agent/tests/test_phase4b_claim_l1_and_workflow_split.py -q`
- `python -m pytest local_life_agent/tests/test_phase5_context_v1.py -q`
- `python -m pytest local_life_agent/tests/test_recommendation_flow.py -q`
- `python -m pytest local_life_agent/tests/test_comparison_flow.py -q`
- `python -m pytest local_life_agent/tests/test_single_coupon_flow.py -q`
- `python -m pytest local_life_agent/tests/test_single_shop_multifacet.py -q`
- `python -m pytest local_life_agent/tests/test_e2e_llm_main_path.py -q`
- `python -m pytest local_life_agent/tests/test_phase3_completion_contracts.py -q`

## 是否建议进入第 7 批
建议进入第 7 批。

当前第 6 批已经完成最终收口，session 基础设施升级可以在既有稳定语义之上推进。
