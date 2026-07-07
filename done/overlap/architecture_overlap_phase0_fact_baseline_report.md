# Architecture Overlap Phase 0 Fact Baseline Report

## 1. 结论

PASS

本阶段的事实核查、文档补全和低风险测试补充已经完成。`compileall` 通过，且已抽查的 Phase 0 / 基础回归测试通过。Phase 1 可以进入冻结与 boundary test 设计，但后续 Phase 5/7 仍有环境依赖项要单独处理。

## 2. 本阶段范围

本阶段只做事实核查，不做架构改造。

已完成的动作：

- 扫描关键模块 import 依赖
- 核查路由、workflow、subgraph 的职责边界
- 核查状态模型与 DTO 重复定义
- 扫描 `_to_dict` / `_as_dict` / `model_dump` / `dict()` / `asdict` 的重复转换点
- 核查 tools registry、DB client、mock / fixture 边界
- 核查主文档中的测试命令真实性
- 运行 `python -m compileall local_life_agent`
- 运行一组 Phase 0 / 基础回归测试

## 3. import 依赖关系事实

| 模块 | 生产引用 | 测试引用 | 风险等级 | 建议 |
|---|---|---:|---|---|
| `local_life_agent/core/` family | 14 个生产调用方，主要来自 `engine/subgraphs/*`、`planning/shared/*`、`planning/evidence/*`、`input/receiver.py` | 1 个测试调用方：`local_life_agent/tests/test_core_wrappers.py` | 高 | 只能先冻结和标记 deprecated，不能在 Phase 1 直接限制 |
| `local_life_agent/planning/` 顶层 re-export shims | 68 个生产调用方，主要来自 `core/*`、`domain/*`、`engine/*`、`planning/*` 子包 | 15 个测试调用方，覆盖 orchestration、goal、decision、evidence、plan validator 等测试 | 高 | 这些顶层 shim 都是历史兼容入口，Phase 1 只能冻结新 import，不能直接删 |
| `local_life_agent/engine/_compat.py` | 19 个生产调用方，覆盖 `engine/_routes.py`、`engine/graph_builder.py`、`engine/subgraphs/*`、`engine/workflows/*`、`observability/trace.py` | 0 个直接测试 import | 高 | 作为共享兼容层先冻结，Phase 1 不要收缩 API 面 |
| `local_life_agent/engine/graph_builder.py` | 9 个生产调用方，覆盖 `agent.py`、`engine/__init__.py`、`engine/subgraphs/*` | 5 个测试调用方，覆盖 graph、e2e、context recovery、target resolution 等测试 | 高 | 它仍是现实入口和兼容面，Phase 1 只能缩新导出，不能直接断流 |
| `local_life_agent/semantic/top_intent_router.py` | 没有发现外部生产调用方；仅有其自身兼容包装逻辑 | 没有发现外部测试调用方 | 低 | `DEPRECATED_CANDIDATE`，可作为后续安全删除对象 |

补充说明：

- `local_life_agent/planning/__init__.py` 目前只是 legacy shim
- `local_life_agent/planning/*.py` 顶层文件里，`candidate_review.py`、`decision_planner.py`、`evidence_planner.py`、`evidence_review.py`、`goal_planner.py`、`goal_review.py`、`plan_validator.py`、`orchestration_router.py`、`ranking_policy.py`、`replan_policy.py`、`review_policy.py`、`state_update_planner.py` 等都是 star re-export 壳
- `local_life_agent/core/*.py` 也是 thin wrapper family，不是新业务抽象

## 4. canonical import path 候选

| 能力 | 候选权威入口 | 历史入口 | 状态 |
|---|---|---|---|
| semantic parsing | `local_life_agent.semantic.intent_parser.parse_semantic_frame` / `parse_top_intent` | `semantic.top_intent_router`、`engine.graph_builder` re-export | `CANONICAL_CANDIDATE` |
| context recovery | `local_life_agent.target.context_recovery.recover_context` | `engine.graph_builder` re-export、旧相对导出 | `CANONICAL_CANDIDATE` |
| orchestration routing | `local_life_agent.planning.orchestration_router.build_orchestration_decision` / `route_orchestration` | `engine._routes`、`engine.subgraphs.orchestration_router_shadow`、`engine.graph_builder` re-export | `CANONICAL_CANDIDATE` |
| planning goal | `local_life_agent.planning.goal.goal_planner.plan_goal` | `planning.goal_planner`、`engine.graph_builder` re-export | `DEPRECATED_CANDIDATE` |
| evidence building | `local_life_agent.planning.evidence.evidence_builder.build_evidence` | `planning.evidence_planner`、`engine.graph_builder` re-export | `DEPRECATED_CANDIDATE` |
| decision planning | `local_life_agent.planning.decision.decision_planner.plan_decision` | `planning.decision_planner`、`engine.graph_builder` re-export | `DEPRECATED_CANDIDATE` |
| candidate / shop resolving | `local_life_agent.target.candidate_resolver.CandidateResolver` + `local_life_agent.target.shop_resolver.resolve_shop` | `tools.db_tools.resolve_shop`、`engine.graph_builder` re-export | `NEEDS_DECISION` |
| tool gateway | `local_life_agent.tools.gateway.dispatch_tool_call` / `ToolCallGateway` | `engine.graph_builder` re-export | `CANONICAL_CANDIDATE` |
| answer generation | `local_life_agent.answer.generator.generate_answer` | `engine.graph_builder` re-export | `CANONICAL_CANDIDATE` |
| answer verification | `local_life_agent.answer.verifier.verify_answer` | `engine.graph_builder` re-export | `CANONICAL_CANDIDATE` |
| session state access | `local_life_agent.domain.state.SessionState` / `StateUpdatePlan` | `engine.graph_builder` re-export、`session_context_summary` | `CANONICAL_CANDIDATE` |
| graph build entry | `local_life_agent.engine.graph_builder.build_graph` | 旧图入口、测试侧兼容 import | `CANONICAL_CANDIDATE` |

## 5. 路由控制权事实

| 文件 | 真实职责 | workflow name | route action | clarification / fallback / retry | 是否只是 LangGraph 条件边适配 |
|---|---|---|---|---|---|
| `local_life_agent/planning/orchestration_router.py` | 业务路由权威层；构造 `OrchestrationDecision`、`workflow_name`、`orchestration_pattern`、`response_mode`、`next_action`、`workflow_reason` | 是 | 是 | 是，且包含验证 fallback、clarification、comparison conflict 处理 | 否 |
| `local_life_agent/engine/_routes.py` | 条件边与路由标签映射；`_route_goal_review`、`_route_decision_review`、`_route_clarify_decide` 等只是把 state/decision 映射成下一条边 | 否 | 是，但只是边标签 | 有 replan counter / fallback edge 逻辑，但不做业务决策源头 | 是 |
| `local_life_agent/engine/subgraphs/orchestration_router_shadow.py` | shadow wrapper；调用 `route_orchestration`，写 observability patch，不负责真实业务判断 | 否 | 否 | 只写 shadow 决策与日志 | 基本是 |
| `local_life_agent/engine/workflow_registry.py` | workflow 白名单和 dispatch 注册表；只接受合法 workflow 名称，不做业务路由判断 | 否 | 否 | 只做 registry fallback / not registered fallback | 是 |
| `local_life_agent/engine/workflows/*` | workflow 内部实现；负责直接回复、确定性单店工具、澄清兜底、探索规划等局部策略 | 否 | 否 | 各 workflow 自带 fallback/clarify 逻辑，但不是顶层业务路由源 | 否 |
| `local_life_agent/engine/graph_builder.py` | LangGraph 图构建 + 条件边 + 兼容 re-export 面；不应再承担业务判断 | 否 | 是 | 只消费路由结果并把它挂到边上 | 是 |

结论：

- 当前没有发现 `workflow_runner` 绕开统一 router 的生产主路径
- 但 `workflow_registry` + `workflow_runner` 的二级派发层仍然是架构上的第二层编排面，Phase 1 只能先冻结它，不要急着重写

## 6. workflow / subgraph 编排事实

当前 workflow：

| workflow | 当前行为 | 分类 |
|---|---|---|
| `discovery_decision` | 通过 registry adapter 直接分发到 `planning_subgraph` | wrapper / adapter |
| `direct_response` | 直接生成 deterministic reply，不跑工具 | handler / strategy |
| `deterministic_tool` | 解一个明确店铺目标，调用 1 个工具，构造证据并 verify | 独立 workflow |
| `clarification_fallback` | 生成澄清或 fallback 回复 | handler / strategy |
| `exploration_planning` | 多子目标探索，最多 2 轮工具调用，并 verify | 独立 workflow |

当前复用的 subgraph：

- `intake_guard_router`
- `merge_clarification`
- `understanding_subgraph`
- `planning_subgraph`
- `execution_review_subgraph`
- `response_subgraph`
- `state_update_plan`

判断：

- `workflow_runner` 本身没有做业务推理，只是白名单分发
- `discovery_decision` 仍然是主链路 wrapper
- `direct_response`、`clarification_fallback` 更像 handler / strategy
- `deterministic_tool` 和 `exploration_planning` 已经是自包含 workflow，但它们与 subgraph 在“规划 / 证据 / 验证”这一层有明显概念重叠
- 没发现 workflow 与 subgraph 在同一条主链路里重复执行同一个节点的直接证据，但架构上仍存在“双编排面”风险

## 7. 状态与 DTO 事实

### GraphState 字段清单

`GraphState` 目前是单 turn 图执行态，字段很多，但可以分成四类：

- 路由与流程元数据：`workflow_name`、`workflow_reason`、`workflow_candidate_reason`、`workflow_run_status`、`workflow_callable`、`next_action`、`response_mode`、`orchestration_*`
- 业务事实：`semantic_frame`、`task_type`、`current_shop`、`comparison_targets`、`evidence_pack`、`execution_plan`、`answer_plan`
- session 快照：`session_state_before`、`session_state_after`、`session_state`
- observability / trace：`event_log`、`trace_spans`、`metrics_tags`

### SessionState 字段清单

`SessionState` 主要是跨 turn 业务记忆：

- `current_shop`
- `current_shop_meta`
- `canonical_shop_entity`
- `canonical_shop_entities`
- `shop_resolution_trace`
- `last_recommendation_list`
- `last_recommendation_list_meta`
- `active_constraints`
- `pending_clarification`
- `pending_clarification_meta`
- `comparison_targets`
- `comparison_targets_meta`
- `comparison_result`
- `suggested_shop`
- `last_candidate_spec`
- `last_candidate_set`
- `active_goal`
- `review_results`
- `last_decision_plan`
- `replan_counters`

### StateUpdatePlan / SessionWriteDirective

写回相关字段为：

- `set_fields`
- `clear_fields`
- `source`
- `evidence_ref`
- `ttl`
- `location_context`
- `reason`
- `blocked`
- `blocked_reason`
- `no_op`

### 重叠 / 覆盖风险

| 字段或对象 | 风险 |
|---|---|
| `current_shop` | GraphState 和 SessionState 都有，容易出现双写 |
| `last_recommendation_list` | GraphState 只做执行态快照，SessionState 是持久记忆，边界容易混 |
| `comparison_targets` | 在 GraphState、SessionState、TargetResolution/Facet protocol 中都出现 |
| `pending_clarification` | 既是业务记忆，又是当前 turn 执行态 |
| `review_results` | 多个阶段都可能写，容易覆盖 |
| `workflow_name` / `response_mode` / `next_action` | 在 router、workflow runner、graph state、workflow handler 中被镜像 |

### 与 `domain/schemas.py` 重复或相近的 DTO

`domain/schemas.py` 仍保留大量旧 DTO / 兼容 DTO，和专门模块存在重叠：

- `DecisionPlan` ↔ `domain/decision.py`
- `EvidencePack` ↔ `domain/evidence.py`
- `ShopCandidate` / `ResolveShopResult` ↔ `domain/shop_entity.py`
- `OrchestrationDecision` ↔ `planning/orchestration_router.py` 的决策输出
- `ComparisonTargetResolution` / `TargetResolutionResult` ↔ `domain/facets.py`
- `AnswerPlan` / `ExecutionPlan` / `ExplorationPlan` 仍是 `schemas.py` 中的大型共用 DTO

### 哪些字段属于业务事实

- shop / candidate / target resolution 相关字段
- evidence / execution plan / answer plan 相关字段
- comparison / recommendation / review 相关字段

### 哪些字段属于执行元数据

- `workflow_*`
- `orchestration_*`
- `fallback_reason`
- `answer_fallback_reason`
- `answer_verify_*`
- `router_policy_*`
- `event_log`
- `trace_spans`
- `metrics_tags`

## 8. DTO 转换重复逻辑事实

### `_to_dict`

扫描到约 27 个生产或测试位置，集中在：

- `answer/answer_plan_builder.py`
- `answer/generator.py`
- `answer/verifier.py`
- `answer/b2_mini_verifier.py`
- `domain/decision.py`
- `domain/facets.py`
- `domain/graph_state_model.py`
- `engine/_compat.py`
- `engine/workflows/deterministic_tool_workflow.py`
- `planning/orchestration_router.py`
- `planning/decision/*`
- `planning/evidence/*`
- `planning/goal/*`
- `planning/plans/*`
- `planning/shared/evidence_adapter.py`
- `target/candidate_resolver.py`
- `target/shop_resolver.py`

高风险重复实现点：

- `planning/orchestration_router.py`
- `engine/_compat.py`
- `answer/generator.py`
- `answer/verifier.py`
- `domain/decision.py`
- `domain/facets.py`
- `target/candidate_resolver.py`
- `target/shop_resolver.py`

### `_as_dict`

只有两个明显位置：

- `engine/subgraphs/active_turn_resolver.py`
- `target/clarification.py`

### `_coerce_list_value`

四个位置：

- `domain/schemas.py`
- `domain/decision.py`
- `domain/evidence.py`
- `planning/evidence/evidence_builder.py`

### `asdict`

主要是三处：

- `llm/jsonable.py`
- `observability/metrics.py`
- `observability/trace.py`

### `model_dump` / `dict()`

这两类转换非常普遍，说明契约层仍在分散做序列化：

- answer 层
- domain 层
- engine 层
- planning 层
- observability 层

高风险点仍然是本地手写 helper，而不是 `model_dump` 本身。

## 9. tools registry / DB / fixture 事实

| 位置 | 事实 | 风险 |
|---|---|---|
| `tools/registry.py` | 同时持有工具定义、JSON schema、输入校验逻辑和 registry lookup | 不是纯 registry，职责混杂 |
| `tools/gateway.py` | `ToolCallGateway.call()` 是统一执行入口，负责 registry / validator / circuit breaker / retry / executor | 是正确的 gateway，但和 registry 需要分层 |
| `tools/db_client.py` | 生产代码会根据 `PYTEST_CURRENT_TEST` / `LOCAL_LIFE_DB_FIXTURE_FALLBACK` 切到 `local_life_agent/tests/fixtures/mock_data`，且 DB 异常时多处回退 fixture | 高风险，生产路径不应静默兜底 |
| `tools/db_tools.py` | `resolve_shop` 在这里属于 DB 工具层；另外还读取 `local_life_agent/mock_data/` 的 `shops.json` / `coupons.json` / `distance_eta.json` | 生产路径直接读 mock_data，不安全 |
| `target/shop_resolver.py` | 业务级 shop resolver；会调用 `db_client`、`CandidateResolver`、`dispatch_tool_call` | 更接近 canonical business resolver |
| `target/candidate_resolver.py` | 候选集 / 店铺解析逻辑；在默认 path 上又会借 `graph_builder.resolve_shop` | 与 graph_builder / shop_resolver 有耦合 |

### 生产代码读取 mock / fixture

- `tools/db_client.py` 会读取 `local_life_agent/tests/fixtures/mock_data/`
- `tools/db_tools.py` 会读取 `local_life_agent/mock_data/`
- `scripts/check_mock_data.py` 和 `scripts/normalize_mock_data_for_db.py` 也会读取 `local_life_agent/mock_data/`，但它们属于脚本链路，不是 runtime tool path

### fallback 判断

- 测试专用 fallback：`tests/helpers/fake_backends.py`、`tests/fakes/mock_tools.py`
- 生产路径 fallback：`tools/db_client.py`、`tools/db_tools.py`
- 明显需要在 Phase 5 处理的是生产 fallback，而不是测试 fake backend

### mock 数据源判断

当前有两套 mock 数据源：

- `local_life_agent/mock_data/`
- `local_life_agent/tests/fixtures/mock_data/`

建议：

- 测试权威 fixture 优先选 `local_life_agent/tests/fixtures/mock_data/`
- 生产 runtime 不应直接读取任何 mock 目录
- `local_life_agent/mock_data/` 更适合作为脚本输入或历史资产，而不是运行时兜底

## 10. 测试命令真实性

| 命令 | 状态 |
|---|---|
| `python -m compileall local_life_agent` | `EXISTS` |
| `pytest local_life_agent/tests/test_phase0_baseline.py -q` | `EXISTS` |
| `pytest local_life_agent/tests/test_p0_fact_calibration.py -q` | `EXISTS` |
| `pytest local_life_agent/tests/test_comparison_flow.py -q` | `EXISTS` |
| `pytest local_life_agent/tests/test_single_coupon_flow.py -q` | `EXISTS` |
| `pytest local_life_agent/tests/test_recommendation_flow.py -q` | `EXISTS` |
| `pytest local_life_agent/tests/test_single_shop_multifacet.py -q` | `EXISTS` |
| `pytest local_life_agent/tests/test_semantic_parser.py -q` | `EXISTS` |
| `pytest local_life_agent/tests/test_01_5_schemas.py -q` | `EXISTS` |
| `pytest local_life_agent/tests/test_domain_schemas.py -q` | `EXISTS` |
| `pytest local_life_agent/tests/test_orchestration_router.py -q` | `EXISTS` |
| `pytest local_life_agent/tests/test_workflow_runner.py -q` | `EXISTS` |
| `pytest local_life_agent/tests/test_workflow_registry.py -q` | `EXISTS` |
| `pytest local_life_agent/tests/test_tool_gateway.py -q` | `EXISTS` |
| `pytest local_life_agent/tests/test_tool_backend_switch.py -q` | `EXISTS` |
| `pytest local_life_agent/tests/test_mock_seed_import.py -q` | `EXISTS` |
| `pytest local_life_agent/tests/test_mock_data_normalization.py -q` | `EXISTS` |
| `pytest local_life_agent/tests/test_core_wrappers.py -q` | `EXISTS` |
| `pytest local_life_agent/tests/test_planning_execution_boundary.py -q` | `EXISTS` |
| `pytest local_life_agent/tests/test_phase1_acceptance.py -q` | `EXISTS` |
| `pytest local_life_agent/tests/test_phase7_workflows.py -q` | `EXISTS` |
| `RUN_E2E_TESTS=1 pytest local_life_agent/tests/test_comprehensive_graph_e2e.py -q -m e2e` | `NEEDS_ENV` |
| `RUN_E2E_TESTS=1 pytest local_life_agent/tests/test_chat_interface_full_e2e.py -q -m e2e` | `NEEDS_ENV` |
| `RUN_INTEGRATION_TESTS=1 pytest local_life_agent/tests/test_real_llm_integration.py -q -m integration` | `NEEDS_ENV` |
| `pytest local_life_agent/tests -q` | `EXISTS` |

已执行并通过的代表性命令：

- `python -m compileall local_life_agent`
- `pytest local_life_agent/tests/test_phase0_baseline.py -q`
- `pytest local_life_agent/tests/test_p0_fact_calibration.py -q`
- `pytest local_life_agent/tests/test_comparison_flow.py -q`
- `pytest local_life_agent/tests/test_single_coupon_flow.py -q`
- `pytest local_life_agent/tests/test_recommendation_flow.py -q`
- `pytest local_life_agent/tests/test_single_shop_multifacet.py -q`
- `pytest local_life_agent/tests/test_semantic_parser.py -q`
- `pytest local_life_agent/tests/test_workflow_registry.py -q`
- `pytest local_life_agent/tests/test_phase1_acceptance.py -q`
- `pytest local_life_agent/tests/test_orchestration_router.py -q`
- `pytest local_life_agent/tests/test_tool_gateway.py -q`

## 11. 风险与阻塞项

当前没有阻塞 Phase 1 的硬阻塞项，但仍有这些风险：

- `tools/db_client.py` 仍有生产 fixture fallback
- `tools/db_tools.py` 仍直接读 `local_life_agent/mock_data/`
- `planning/` 顶层 shims 和 `core/` wrappers 仍有大量生产依赖
- `engine/_compat.py` 仍是高密度共享兼容层
- `engine/graph_builder.py` 仍是大公共面
- `workflow_runner` / `workflow_registry` / workflows 的双编排风险仍在

## 12. Phase 1 准入判断

可以进入 Phase 1。

理由：

- 事实基线已经足够清楚
- 关键兼容层的 caller 结构已经确认
- 路由、workflow、state、tools、fixture 的主要风险点都已定位
- 已完成 compileall 和基础回归抽查

Phase 1 的正确姿势仍然是冻结和标记，不是删除：

- 先冻结 canonical path
- 先加 architecture boundary tests
- 先标 deprecated
- 再做迁移准备

