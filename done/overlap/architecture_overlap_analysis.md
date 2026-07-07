# 模块功能重叠与架构混乱分析

> 分析日期: 2026-07-05
> 范围: `local_life_agent/` 全模块
> 适用分支: `toolcall`

## 总体结论

当前问题不是单纯的小 bug，而是架构边界、状态契约、编排控制权、测试/生产隔离混杂在一起的组合问题。现有 P0 / P1 / P2 的大方向判断基本成立，但不能按“问题清单”直接做一次性大删大改。

这份报告的改造原则改成三步：

1. 先冻结权威路径，确认事实基线
2. 再按阶段迁移调用方和契约
3. 最后删除已无真实调用方的兼容层

第一目标不是新增能力，而是稳定现有能力并收敛边界。

## 事实基线

以下现象已从当前仓库结构中直接可见，说明问题确实是“结构性重叠”，不是单点实现瑕疵：

- `core/` 和 `planning/` 顶层壳仍在承接大量历史 import
- 路由逻辑分散在 `planning/orchestration_router.py`、`engine/_routes.py`、`engine/subgraphs/orchestration_router_shadow.py`
- `engine/workflows/` 与 `engine/subgraphs/` 存在两套编排语义
- `domain/graph_state.py`、`domain/graph_state_model.py`、`domain/state.py`、`domain/session_context_summary.py`、`domain/state_validation.py` 的职责有重叠
- `domain/schemas.py` 与拆分后的 `domain/decision.py`、`domain/evidence.py`、`domain/shop_entity.py` 等并存
- `tools/registry.py` 兼具注册、schema、validator 三类职责
- DB / fixture / mock 的边界已经混入生产路径
- `engine/_compat.py` 和 `engine/graph_builder.py` 都承接了过多兼容导出

所以，下面的结论不再把“删除”“统一”“拆分”写成立刻执行的动作，而是写成阶段化迁移动作。

## 改造总阶段

### Phase 0：报告修订与事实基线

- Entry Criteria:
  - 已能定位当前文档和测试目录
  - 需要先完成事实核查，不引入代码改动
- Work Scope:
  - 生成并补全 import 依赖关系、状态字段重叠关系、DTO 重复定义关系、工具 registry 职责混杂点、生产代码读取 fixture/mock 的位置清单
  - 补充当前仓库实际存在的回归测试命名
- Non-goals:
  - 不做大规模代码改动
  - 不删除任何兼容层或旧入口
- Acceptance Criteria:
  - `architecture_overlap_analysis.md` 改写为可执行的分阶段方案
  - 新增风险矩阵
  - 新增阶段验收表
  - 新增执行计划章节
- Regression Commands:
  - `pytest local_life_agent/tests/test_phase0_baseline.py -q`
  - `pytest local_life_agent/tests/test_p0_fact_calibration.py -q`
- Phase 0 事实基线报告:
  - [todo/architecture_overlap_phase0_fact_baseline_report.md](./architecture_overlap_phase0_fact_baseline_report.md)
- Rollback Plan:
  - 只保留文档层改动，若事实点不充分则回退新增段落，不动代码
- Risk Level:
  - 低

### Phase 1：冻结架构入口与 canonical path

- Entry Criteria:
  - Phase 0 的事实清单已补齐
  - 权威 import path 可枚举
- Work Scope:
  - 定义每类能力的权威 import path
  - 标记 deprecated path
  - 禁止新代码继续依赖 `core/`、`planning/` 顶层壳、`graph_builder.py` 的大面积兼容导出口
  - 增加 architecture boundary tests
- Non-goals:
  - 不删除 `core/` 和 `planning/` 壳文件
  - 不做业务逻辑重写
- Acceptance Criteria:
  - 新代码只允许走 canonical path
  - boundary tests 能拦住新增的旧路径依赖
  - deprecated path 只保留兼容，不再扩散
- Regression Commands:
  - `pytest local_life_agent/tests/test_core_wrappers.py -q`
  - `pytest local_life_agent/tests/test_phase1_acceptance.py -q`
- Phase 1 冻结报告:
  - [todo/architecture_phase1_canonical_path_freeze_report.md](./architecture_phase1_canonical_path_freeze_report.md)
- Phase 1 canonical path 清单:
  - [todo/architecture_phase1_canonical_import_paths.md](./architecture_phase1_canonical_import_paths.md)
- Phase 1 边界测试:
  - `local_life_agent/tests/test_phase1_architecture_boundaries.py`
- Rollback Plan:
  - 如果 boundary tests 误伤现有调用，先放宽旧路径限制，只保留告警，不直接删文件
- Risk Level:
  - 中

### Phase 2：路由权威层收敛

- Entry Criteria:
  - canonical route 入口已冻结
  - orchestration decision 的字段来源已可追踪
- Work Scope:
  - 明确 `planning/orchestration_router.py` 是唯一业务路由决策层
  - `engine/_routes.py` 只消费 `OrchestrationDecision`，只做 LangGraph 条件边转换
  - `engine/subgraphs/orchestration_router_shadow.py` 只允许 wrapper 角色，不能再承载真实业务判断
  - router 只产出 workflow / route decision，不产出 review policy、retry policy 或 budget policy
  - `_routes.py` 只做条件边映射，不允许在这里再引入 review 压缩、rewrite 限流或 loop 终止规则
  - 统一 workflow name、route action、fallback reason、clarification route 的归属
- Non-goals:
  - 不在多个层级重复判断同一个 routing decision
  - 不让 workflow 私自绕过统一 router
- Acceptance Criteria:
  - 路由判断只有一个权威来源
  - `_routes.py` 不再重新实现业务判定
  - shadow router 只剩迁移兼容职责
- Regression Commands:
  - `pytest local_life_agent/tests/test_orchestration_router.py -q`
  - `pytest local_life_agent/tests/test_p2_router_priority.py -q`
  - `pytest local_life_agent/tests/test_router_rule_policy_guard.py -q`
- Phase 2 路由权威层收敛报告:
  - [todo/architecture_phase2_routing_authority_convergence_report.md](./architecture_phase2_routing_authority_convergence_report.md)
- Phase 2 边界测试:
  - `pytest local_life_agent/tests/test_phase2_routing_authority.py -q`
- Rollback Plan:
  - 若条件边转换出问题，先回滚 `_routes.py` 的映射层，不回退权威路由定义
- Risk Level:
  - 中高

### Phase 3：编排模型收敛

- Entry Criteria:
  - 权威路由已稳定
  - workflow 与 subgraph 的职责差异已能清楚描述
- Work Scope:
  - 明确 LangGraph 是唯一外层编排
  - `engine/subgraphs/` 作为可复用执行阶段
  - `engine/workflows/` 作为业务 workflow handler / strategy，不再是另一套独立总调度系统
  - 消除 `workflow_runner` 与 `_routes.py` 的双重编排冲突
  - `workflow_runner` 只做 handler / strategy 去重，不再接管总控、review 选择和 retry 策略
  - `planning_subgraph`、`execution_review_subgraph`、`response_subgraph` 的职责边界必须固定，避免 workflow 再包一层“第二套总控”
  - 简单单店 / 单券 / 营业状态 query 走轻量链路，推荐 / 对比 / 多 facet query 才进入完整 evidence review / decision review
  - ReviewPolicy 的编排位置放在 graph 层状态判断之前或之后都可以，但它只能消费 state / budget snapshot，不能替代路由器再做一次业务路由
  - 区分可保留 workflow 与 legacy wrapper
- Non-goals:
  - 不一次性删除所有 workflow
  - 不把 workflow 直接改成全局调度器
- Acceptance Criteria:
  - workflow 不再承担独立总控职责
  - bypass 路径逐步消失
  - 仍保留的 workflow 只做 handler / strategy
  - 简单 query 不应触发整套重 review 链路；复杂 recommendation / comparison 才触发必要 review
  - workflow runner 与 subgraph 的职责在 trace 中可区分
- Regression Commands:
  - `pytest local_life_agent/tests/test_workflow_runner.py -q`
  - `pytest local_life_agent/tests/test_workflow_registry.py -q`
  - `pytest local_life_agent/tests/test_phase7_workflows.py -q`
- Rollback Plan:
  - 先把 workflow 回退成 wrapper，不回退 LangGraph 外层编排
- Risk Level:
  - 高
- Phase 3 编排模型收敛报告:
  - [todo/architecture_phase3_orchestration_model_convergence_report.md](./architecture_phase3_orchestration_model_convergence_report.md)

### Phase 3 状态更新

- 当前结论：`PASS`
- 说明：`workflow_runner` / `workflow_registry` / `engine/subgraphs/` / `engine/workflows/` 的职责边界已可通过测试与实现事实同时验证，LangGraph 仍然是唯一外层编排。
- 下一阶段入口：可以进入 Phase 4

### Phase 4：状态与 DTO 契约收敛

- Entry Criteria:
  - 路由边界已冻结
  - 现有状态字段重复点已盘点
- Work Scope:
  - 明确四类对象边界：

```text
GraphState = 单 turn 图执行态
SessionState = 跨 turn 业务记忆
Domain DTO = 业务事实对象
Observability / Trace = 执行过程元数据
```

  - 收敛 `domain/graph_state.py`、`domain/graph_state_model.py`、`domain/state.py`、`domain/session_context_summary.py`、`domain/state_validation.py`
  - 清理 `domain/schemas.py` 中与 `domain/decision.py`、`domain/evidence.py`、`domain/shop_entity.py` 等重复的旧 DTO
  - 提取统一的 `to_dict` / `as_dict` / `model_dump` 工具
  - 新增或文档化 `ReviewBudget`、`ExecutionBudget`、`RetryState`、`LoopTrace`、`ReviewTrace` 的状态边界：它们属于 `GraphState` / Observability，不属于 Domain DTO
  - `review_results`、`budget_context`、`retry_counters`、`loop_trace`、`review_trace`、`rewrite_count`、`evidence_review_action` 归入执行态或 trace，不要塞进业务事实对象
  - slot_extractor 的输出对象边界改成 `AnchorExtractionResult` / `TextAnchor` / `MentionCandidate` / `ComparisonReferenceCandidate` / `PreferenceSignal` 这类“锚点与候选”表达，不要直接包装成最终业务决策
- Non-goals:
  - 不让多个节点分散写 `SessionState`
  - 不让业务 DTO 继续承载无限增长的 retry / fallback / review metadata
- Acceptance Criteria:
  - 状态对象分层清晰
  - DTO 定义收敛到单一权威位置
  - 执行元数据进入 trace / observability 或明确 metadata envelope
  - trace 中能解释 review 是否触发、为何触发、耗时、结果和是否降级
- Regression Commands:
  - `pytest local_life_agent/tests/test_phase_e_state_contracts.py -q`
  - `pytest local_life_agent/tests/test_p13_state_schema_convergence.py -q`
  - `pytest local_life_agent/tests/test_domain_schemas.py -q`
- Rollback Plan:
  - 先保留旧字段兼容读，不回退新对象边界定义
- Risk Level:
  - 高

### Phase 4 状态更新

- 当前结论：`PARTIAL PASS`
- 说明：`GraphState` / `SessionState` / Domain DTO / Observability 的四层边界已可验证，会话写回已收束到单一路径，统一序列化工具也已落地；但 `domain/schemas.py` 的历史兼容 DTO 仍保留，`slot_extractor` 仍有 `task_type` / `workflow_hint` 兼容输出，因此本阶段不标为完全 `PASS`
- Phase 4 收敛报告：
  - [todo/architecture_phase4_state_dto_contract_convergence_report.md](./architecture_phase4_state_dto_contract_convergence_report.md)
- 下一阶段入口：
  - 可以进入 Phase 5，但需要把 `slot_extractor` 的兼容字段和 `domain/schemas.py` 的历史 DTO 视为 `NEEDS_DECISION`

### Phase 5：工具系统与 DB/fake 边界收敛

- Entry Criteria:
  - 状态契约已基本收敛
  - 工具调用链可追踪
- Work Scope:
  - 拆分 `tools/registry.py` 职责为：

```text
tools/definitions.py
tools/schemas.py
tools/validators.py
tools/registry.py
tools/gateway.py
```

  - 统一 `tools/db_tools.py:resolve_shop()` 与 `target/shop_resolver.py:resolve_shop()` 的层级关系
  - 移除生产 DB client 中根据 `PYTEST_CURRENT_TEST`、环境变量、DB 异常自动回退 fixture 的逻辑
  - fake/mock 数据只允许通过显式 fake backend 或 test fixture 注入
  - 新增 `SlotExtractor Boundary`：`slot_extractor` 只能补文本锚点和候选，不允许做业务决策
  - `slot_extractor` 允许输出原文 merchant mention span、deictic anchor、ordinal anchor、显式位置词、原文品牌候选，但这些都只能是候选，不是最终 `shop_id`
  - `slot_extractor` 不允许判断是否推荐 / 对比 / 用户偏好，不允许覆盖 `semantic_parse` 的 `task_type` / `intent`，也不允许直接决定 `shop_id`
  - `target_resolve` / `shop_resolver` 才是 `shop_id` 绑定权威层，工具层只接收已验证的 `shop_id` 或 `candidate_set`
- Non-goals:
  - 不让生产代码读取 `local_life_agent/mock_data/`
  - 不让 DB 异常被静默假数据吞掉
- Acceptance Criteria:
  - 测试数据只有一套权威来源
  - 生产 DB client 不再自动 fallback 到 fixture
  - tool schema / validator / registry 分工清楚
  - semantic task_type 的权威来源是 LLM `semantic_parse` 或受限 top_intent，不是 `slot_extractor`
  - `shop_id` 绑定的权威来源是 `target_resolve` / `shop_resolver`，不是 `slot_extractor`
  - 新增 architecture boundary test，防止 `slot_extractor` 继续扩张成规则业务大脑
- Regression Commands:
  - `pytest local_life_agent/tests/test_tool_gateway.py -q`
  - `pytest local_life_agent/tests/test_tool_backend_switch.py -q`
  - `pytest local_life_agent/tests/test_mock_seed_import.py -q`
  - `pytest local_life_agent/tests/test_mock_data_normalization.py -q`
  - `pytest local_life_agent/tests/test_target_resolution_contract.py -q`
  - `pytest local_life_agent/tests/test_phase5_tools_db_boundary.py -q`
  - `pytest local_life_agent/tests/test_slot_extractor_boundary_guard.py -q`
- Rollback Plan:
  - 若生产路径受影响，先恢复显式失败，不恢复静默 fixture fallback
- Risk Level:
  - 高

### Phase 5 状态更新

- 当前结论：`PARTIAL PASS`
- 说明：`tools/registry.py` 已拆分为 `definitions.py` / `schemas.py` / `validators.py` / `registry.py` 的清晰分层，gateway 仍是唯一执行入口；`db_client` 不再根据 `PYTEST_CURRENT_TEST` 自动切 fixture，`db_tools` 也已切断 runtime 对 `local_life_agent/mock_data/` 的直接读取，并且 `candidate_resolver` 默认回调已改为 `target/shop_resolver.resolve_shop`。残余项是 `db_tools.resolve_shop` 仍保留 resolution-shaped 兼容输出，`slot_extractor` 的 `task_type` / `workflow_hint` 仍是 `DEPRECATED_COMPAT`，`domain/schemas.py` 也仍保留历史 DTO 兼容窗口。
- Phase 5 收敛报告：
  - [todo/architecture_phase5_tools_db_boundary_convergence_report.md](./architecture_phase5_tools_db_boundary_convergence_report.md)
- 下一阶段入口：
  - 可以进入 Phase 6，但需接受 `NEEDS_DECISION`：`db_tools.resolve_shop` 是否进一步收缩成更原子的 DB 能力，以及历史 DTO 的后续删除顺序

### Phase 6：兼容层与大杂烩拆分

- Entry Criteria:
  - 前五阶段的权威路径和契约已能支撑迁移
  - import 扫描可用于判定真实调用方
- Work Scope:
  - 拆分 `engine/_compat.py`
  - 收缩 `engine/graph_builder.py` 的公共导出表面
  - 迁移完成后删除 `core/` 纯转发层
  - 迁移完成后删除 `planning/` 顶层 re-export 壳
  - 删除 `semantic/top_intent_router.py` 等死文件
  - 删除 debug `print`
  - 清理空目录和明显 legacy 文件
- Non-goals:
  - 不在调用方未迁移完成前删除兼容入口
  - 不为了目录整洁破坏已通过的主链路
- Acceptance Criteria:
  - 每个删除动作前都有 import 扫描结果证明没有真实调用方
  - 删除前后都有专项回归
- Regression Commands:
  - `pytest local_life_agent/tests/test_core_wrappers.py -q`
  - `pytest local_life_agent/tests/test_planning_execution_boundary.py -q`
  - `pytest local_life_agent/tests/test_top_intent_router.py -q`
  - `pytest local_life_agent/tests/test_stage14_verification.py -q`
- Rollback Plan:
  - 已删除兼容层只能通过 revert 单项补回，不回滚整个重构序列
- Risk Level:
  - 中高

### Phase 6 状态更新

- 当前结论：`PARTIAL PASS`
- 说明：已删除确认零调用方的 `semantic/top_intent_router.py`，并清理两个脚手架/诊断场景中的调试 `print`；但 `core/` 与 `planning/` 顶层兼容壳仍有大量测试依赖，`engine/graph_builder.py` 的公共导出面也尚未完全收缩，因此本阶段不适合标为完全 `PASS`
- Phase 6 收敛报告：
  - [todo/architecture_phase6_compat_cleanup_report.md](./architecture_phase6_compat_cleanup_report.md)
- 下一阶段入口：
  - 可以进入 Phase 7，但要把 `core/` / `planning/` 的删壳与 `graph_builder` 导出收缩视为后续迁移项，而不是当前验收阻断项

### Phase 7：最终验收与回归稳定

- Entry Criteria:
  - 前六阶段已完成并通过专项回归
  - 权威路径、路由、状态、工具、兼容层都已收敛
- Work Scope:
  - 跑全量单测
  - 跑 comparison / single coupon / recommendation / clarification / location / semantic parser / workflow routing 专项测试
  - 跑真实 LLM + 真实 DB 的端到端冒烟测试
  - 验证没有生产路径读取 fixture / mock
  - 验证 architecture boundary tests 通过
  - 验证简单单店 / 单券 / 营业状态 query 不触发完整 5 层 LLM review，复杂 recommendation / comparison 才触发必要 review
  - 验证 `plan_validator` 仍然只是 deterministic schema / tool whitelist / 参数校验
  - 验证 `decision_review` 默认是 deterministic sanity check，只有复杂推荐 / 对比或低置信度时才启用 LLM
  - 验证 `answer_verify` 保留，但 rewrite 次数上限固定且超限后进入 controlled degrade
  - 验证 retry / rewrite / replan 超过预算后不再循环，必须进入 clarify / degrade / fallback
  - 验证 trace 中可见 `review_trigger_reason`、`retry_reason`、`budget_consumed`、`degrade_reason`
  - 输出最终验收报告
- Non-goals:
  - 不再引入新架构分支
  - 不再扩大问题列表
- Acceptance Criteria:
  - 重点场景回归全绿
  - 无生产 fixture 误用
  - 无旧路径新增依赖
  - 复杂 query 只触发必要 review，不出现简单 query 也连跑多层 LLM review 的现象
  - `slot_extractor` 不再输出 final task_type / final shop_id
  - trace 可解释每个 review 是否运行以及为什么运行
- Regression Commands:
  - `python -m compileall local_life_agent`
  - `pytest local_life_agent/tests -q`
  - `RUN_E2E_TESTS=1 pytest local_life_agent/tests/test_comprehensive_graph_e2e.py -q -m e2e`
  - `RUN_INTEGRATION_TESTS=1 pytest local_life_agent/tests/test_real_llm_integration.py -q -m integration`
  - `TODO_ADD_TEST: local_life_agent/tests/test_review_policy_budget.py`
  - `TODO_ADD_TEST: local_life_agent/tests/test_retry_loop_guard.py`
  - `TODO_ADD_TEST: local_life_agent/tests/test_trace_review_visibility.py`
- Rollback Plan:
  - 若最终验收失败，回到对应 Phase 的边界冻结状态，不继续删兼容层
- Risk Level:
  - 中

### Phase 7 状态更新

- 当前结论：`PARTIAL PASS`
- 说明：`compileall` 通过，Phase 6 相关专项回归通过，但全量 `pytest local_life_agent/tests -q` 仍有 40 个失败，失败分布横跨 e2e、strict guards、target resolve、evidence planner 和 LLM main path 等多个独立区域，因此不能把最终验收写成完全 `PASS`
- Phase 7 收敛报告：
  - [todo/architecture_phase7_final_regression_report.md](./architecture_phase7_final_regression_report.md)
- 下一步建议：
  - 单独拆一轮面向失败面的修复，不要继续把修复混进 compat cleanup 或文档整理

## 风险矩阵

| 风险 | 触发信号 | 影响 | 缓解方式 | 主要阶段 |
|---|---|---|---|---|
| 过早删除 `core/` / `planning/` 壳 | 旧 import 仍在使用 | 直接断链 | 先 freeze，再 import 扫描，再删 | Phase 1 / 6 |
| 路由重复判断 | 同一 decision 在多层出现分支逻辑 | 行为漂移 | 只保留 `planning/orchestration_router.py` 为权威 | Phase 2 |
| workflow 与 subgraph 双调度 | `workflow_runner` 和 `_routes.py` 同时改写执行路径 | 回归难定位 | workflow 降级为 handler / strategy | Phase 3 |
| 状态字段继续扩散 | `SessionState` 被多个节点写入 | 难以验证 | 明确四层边界，禁止分散写回 | Phase 4 |
| 生产 fallback 到 fixture | DB 异常时 silently 成功 | 掩盖真实故障 | 显式失败或 controlled degradation | Phase 5 |
| 兼容层一次性收缩过猛 | import 扫描未完成就删除 | 大面积报错 | 分批删除，每批跑专项回归 | Phase 6 |
| review 链路过重 | 简单 query 也触发多层 review / LLM review | 延迟和成本飙升 | 引入 ReviewPolicy / ReviewBudget，简单 query 只做 deterministic sufficiency check | Phase 3 / 4 / 7 |
| slot_extractor 规则膨胀 | `slot_extractor` 开始决定 task_type / shop_id / preference | semantic drift，边界失真 | 只保留 anchors / candidates / spans，新增 boundary test | Phase 4 / 5 / 7 |
| retry / rewrite 无限循环 | 同一 failed_plan 重复执行，rewrite 永远重试 | 卡住链路、产生成本 | 增加 turn-level budget、loop_trace、last_failed_plan_id | Phase 4 / 7 |

## 阶段验收表

| Phase | 验收对象 | 退出标志 |
|---|---|---|
| 0 | 文档与事实基线 | 风险矩阵、执行计划、验收表补齐 |
| 1 | canonical path | 旧路径冻结，新代码不再扩散 |
| 2 | routing authority | 路由决策单点收敛 |
| 3 | orchestration model | workflow 降级，subgraph 复用 |
| 4 | state / DTO contract | 四层边界清晰，重复 DTO 收敛 |
| 5 | tools / DB boundary | registry 分层，fixture 不进生产 |
| 6 | compat cleanup | 真实调用方清空后再删除 |
| 7 | final regression | 全量回归通过并输出验收报告 |

## 禁止事项

- 不要在 Phase 1 前直接删除 `core/`
- 不要在 Phase 1 前直接删除 `planning/` 顶层壳
- 不要在未确认权威路由前重写所有 workflow
- 不要把 router 再写成 review policy / retry policy 的第二套总控
- 不要把 `top_intent_router` 改成全局 LLM 总控
- 不要把 `active_turn_resolver` 扩成大型 ContextGate
- 不要把 `StateUpdatePlan` 的写回逻辑分散到多个节点
- 不要让 `slot_extractor` 继续决定 `task_type`、`preference`、`shop_id`
- 不要让 `answer_verify`、`evidence_review`、`rewrite` 在没有预算上限时无限循环
- 不要为了目录好看破坏已通过的 comparison / single_coupon / recommendation 链路
- 不要让生产 DB client 静默 fallback 到 fixture
- 不要新增未经 schema / validator 约束的 tool

## P0 / P1 / P2 安全化调整

| 类别 | 优先级 | 原始问题 | 安全化动作 |
|---|---|---|---|
| 架构 | P0 | 删除 `core/` 整个包 | Phase 1 标记 deprecated，Phase 6 在调用方迁移完成且 import 扫描通过后删除 |
| 架构 | P0 | 删除 `planning/` 顶层壳文件 | Phase 1 冻结新 import，Phase 6 迁移完成后删除 |
| 架构 | P0 | 收敛路由逻辑 | Phase 2 统一到 `planning/orchestration_router.py`，`engine/_routes.py` 只做条件边转换 |
| 架构 | P0 | 统一 `engine/workflows/` 与 `engine/subgraphs/` | Phase 3 明确 LangGraph 外层编排、subgraph 执行阶段、workflow handler / strategy 的层级，消除双重调度 |
| 架构 | P0 | 拆分 `engine/_compat.py` | Phase 6 按职责拆分，先迁移调用方再删除大杂烩 |
| 架构 | P0 | 收敛 `tools/registry.py` 职责 | Phase 5 拆成 definitions / schemas / validators / registry / gateway |
| 架构 | P0 | 处理 `tools/db_client.py` 的 fixture 回退 | Phase 5 改成显式失败或 controlled degradation，不再自动兜底 |
| 架构 | P0 | 统一 `resolve_shop` 两套实现 | Phase 5 明确原子工具与业务 resolver 的层级，必要时合并成单一权威实现 |
| 架构 | P0 | 压缩 review 链路 | Phase 3/4 定义 ReviewPolicy / ReviewBudget / ReviewTrace，简单 query 走 deterministic sufficiency check，复杂 query 才启用 LLM review |
| 架构 | P0 | 限制 `slot_extractor` 职责 | Phase 4/5 收缩为 anchors / candidates / spans，禁止 task_type / preference / shop_id 决策 |
| 架构 | P0 | 收敛 retry / rewrite 循环 | Phase 4/7 增加 turn-level budget、loop_trace、last_failed_plan_id，超限进入 degrade / clarify |
| 契约 | P0 | 合并状态模型 | Phase 4 先定义 GraphState / SessionState / Domain DTO / Observability 四层边界，再逐步迁移字段 |
| 契约 | P0 | 清理 `domain/schemas.py` 的旧 DTO | Phase 4 逐步收敛重复 DTO，保留兼容读写窗口后再删旧定义 |
| 简单 | P0 | 删除 `semantic/top_intent_router.py` | Phase 6 先确认无真实调用方，再删除 |
| 简单 | P0 | 删除调试 `print` | 立即清理，但只限明确的 debug 输出，不顺手改其他逻辑 |
| 架构 | P1 | 统一 mock 数据源 | Phase 5 收敛到一套权威 fixture，不再双来源分叉 |
| 架构 | P1 | 把 `session/store.py` 抽成可替换后端 | 作为 Phase 4 / 5 的延伸，不抢在状态契约收敛前单独扩张 |
| 架构 | P1 | 收缩 `graph_builder.py` 兼容导出 | Phase 1 冻结新增导出，Phase 6 再逐步删旧导出 |
| 架构 | P1 | 收敛 `answer/` 主入口与 verifier / verbalizer 边界 | 先明确职责，再决定是否合并，不做一次性重写 |
| 架构 | P1 | 拆分 `llm/client.py` 的职责 | 先拆调用控制流与 prompt 加载，再处理后端选择 |
| 契约 | P1 | 提取重复的 `_to_dict` / `_as_dict` | 先抽统一工具，再替换高频调用点 |
| 契约 | P1 | 统一编排枚举位置 | 先确认枚举权威域层，再迁移引用 |
| 契约 | P1 | 明确 `streaming/` 和 `observability/` 事件边界 | 先定义协议边界，再去重字段 |
| 简单 | P1 | 处理超大型文件 | 优先做局部收口，不为了拆分而拆分 |
| 简单 | P1 | 清理 TODO / FIXME / XXX / HACK | 逐项清理，避免顺手改业务 |
| 简单 | P1 | 删除空目录 `tests/cases/` | Phase 6 在确认无引用后清理 |
| 简单 | P2 | 明确 `eval/` 与 `tests/` 分工 | 先定义职责，再决定是否合并执行器 |
| 简单 | P2 | 统一测试命名 | 作为低风险整理项，不影响主链路 |
| 简单 | P2 | 处理 `input/` 的包定位 | 仅在不影响调用面的前提下收口 |
| 简单 | P2 | 评估 `observability/file_logger.py` | 保留或替换都可以，但不要在主线改动时顺手重构日志栈 |
| 简单 | P2 | 处理 `llm_verbalizer` 的去留 | 先确认是否仍被主链路使用，再决定保留策略 |
| 简单 | P2 | 统一 `planning/plans/` 命名 | 作为最后的目录整理项，不影响 Phase 1-6 |

## 验收命令占位

以下命令都来自当前仓库内实际存在的测试文件名；若后续发现某条命令需要额外环境变量，再单独标记 `TODO_VERIFY`。

- comparison flow
  - `pytest local_life_agent/tests/test_comparison_flow.py -q`
- single coupon flow
  - `pytest local_life_agent/tests/test_single_coupon_flow.py -q`
- recommendation flow
  - `pytest local_life_agent/tests/test_recommendation_flow.py -q`
- single shop multi-facet
  - `pytest local_life_agent/tests/test_single_shop_multifacet.py -q`
- semantic parser / semantic frame schema
  - `pytest local_life_agent/tests/test_semantic_parser.py -q`
  - `pytest local_life_agent/tests/test_01_5_schemas.py -q`
  - `pytest local_life_agent/tests/test_domain_schemas.py -q`
- orchestration router
  - `pytest local_life_agent/tests/test_orchestration_router.py -q`
- workflow routing
  - `pytest local_life_agent/tests/test_workflow_runner.py -q`
  - `pytest local_life_agent/tests/test_workflow_registry.py -q`
- db tools / fixture boundary
  - `pytest local_life_agent/tests/test_tool_gateway.py -q`
  - `pytest local_life_agent/tests/test_tool_backend_switch.py -q`
  - `pytest local_life_agent/tests/test_mock_seed_import.py -q`
  - `pytest local_life_agent/tests/test_mock_data_normalization.py -q`
- full graph e2e
  - `RUN_E2E_TESTS=1 pytest local_life_agent/tests/test_comprehensive_graph_e2e.py -q -m e2e`
  - `RUN_E2E_TESTS=1 pytest local_life_agent/tests/test_chat_interface_full_e2e.py -q -m e2e`
- architecture boundary tests
  - `pytest local_life_agent/tests/test_core_wrappers.py -q`
  - `pytest local_life_agent/tests/test_planning_execution_boundary.py -q`
  - `pytest local_life_agent/tests/test_phase1_acceptance.py -q`

## 仍需下一阶段事实核查

- `tools/db_client.py` 的 fixture fallback 是否还存在未覆盖的隐藏分支
- `local_life_agent/mock_data/` 与 `local_life_agent/tests/fixtures/mock_data/` 的最终权威来源选择
- `SessionState` 写回到底应该由哪些节点负责
- `RUN_E2E_TESTS` / `RUN_INTEGRATION_TESTS` 在当前 CI 里的默认开关
- Phase 1 已冻结 canonical path，并新增 boundary test，后续事实核查可以直接基于该冻结面继续推进
- Phase 2 已完成路由权威层收敛，后续可以直接进入 Phase 3 的编排模型收敛，不应再把 query / intent 路由逻辑散到 `_routes.py`、shadow 或 registry
