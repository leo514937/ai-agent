# Architecture Phase 5 Tools / DB / Fake Boundary Convergence Report

## 1. 结论

PARTIAL PASS

Phase 5 的核心边界已经收敛到位：`tools/registry.py` 已从“大杂烩”收缩为薄 registry/lookup，tool schema 与 validator 也已经拆到独立模块；`ToolCallGateway` 仍然是唯一工具执行入口；生产 DB client 不再根据 `PYTEST_CURRENT_TEST` 自动切 fixture；`db_tools` 也已切断 runtime 对 `local_life_agent/mock_data/` 的直接读取；`candidate_resolver` 的默认 `resolve_shop` 方向也已改成 canonical `target/shop_resolver.resolve_shop`。

本阶段仍保留两个有意未完全清理的残余，因此不标 `PASS`：

- `tools/db_tools.py` 里的 `resolve_shop` 仍保留 resolution-shaped 兼容输出，尚未进一步收缩成纯原子查询能力
- `domain/schemas.py` 仍保留历史 DTO 兼容窗口，Phase 5 只做了 tool / resolver 相关边界收敛，没有大规模删旧 DTO

因此本阶段结论是 `PARTIAL PASS`。

## 2. 本阶段范围

本阶段只收敛 tools registry、tool schema / validator / gateway、DB client、mock / fixture、resolve_shop / target_resolve / shop_resolver / candidate_resolver 的边界。

本阶段不做：

- 不重写 router
- 不修改 `planning/orchestration_router.py`
- 不改 workflow runner / workflow registry 行为
- 不重构 `engine/workflows/` 和 `engine/subgraphs/`
- 不迁移 `GraphState` / `SessionState` 字段结构
- 不新增第二套状态模型
- 不删除 `core/`
- 不删除 `planning/` 顶层 shim
- 不拆 `_compat.py`
- 不收缩 `graph_builder.py` 公共导出面

## 3. 前置条件检查

已检查前置报告存在且准入满足：

- Phase 0 事实基线报告：存在，结论 `PASS`
- Phase 1 冻结报告：存在，结论 `PASS`
- Phase 2 路由权威层收敛报告：存在，结论 `PASS`
- Phase 3 编排模型收敛报告：存在，结论 `PASS`
- Phase 4 状态与 DTO 契约收敛报告：存在，结论 `PARTIAL PASS`

结论：

- Phase 4 允许进入 Phase 5
- Phase 5 完成后可继续进入 Phase 6，但需要保留少量 `NEEDS_DECISION`

## 4. 当前实现事实调研

### 4.1 `tools/registry.py`

当前 registry 已经不再承担 schema 常量和 validator 实现。

事实：

- `ToolRegistry` 只保留注册、lookup、list 和 `validate_args`
- 具体工具定义来自 `tools/definitions.py`
- input/output schema 来自 `tools/schemas.py`
- 参数校验委托给 `tools/validators.py`

### 4.2 `tools/gateway.py`

`ToolCallGateway` 仍然是统一工具执行入口。

事实：

- 先 registry lookup
- 再参数校验
- 再 circuit breaker
- 再 retry
- 再 executor 执行
- 最后统一 normalizer

没有新增第二个 gateway。

### 4.3 `tools/db_client.py`

生产 DB client 已从“pytest 自动兜底 fixture”改成“显式 fixture 开关”。

事实：

- `_use_fixture_backend()` 只看 `LOCAL_LIFE_DB_FIXTURE_FALLBACK`
- 不再读取 `PYTEST_CURRENT_TEST`
- DB 查询失败时不再静默回退 fixture
- 查询异常会记录日志并抛出，让上层显式降级或失败

### 4.4 `tools/db_tools.py`

`db_tools` 仍然是数据库工具层，但 runtime mock 读取已被隔离。

事实：

- `_mock_lookup_shop` / `_mock_coupons_for_shop` / `_mock_distance_for_shop` 只有在显式 fixture 开关打开时才会读 mock 数据
- mock 数据目录已切到 `local_life_agent/tests/fixtures/mock_data/`
- runtime path 不再直接读取 `local_life_agent/mock_data/`
- `local_life_agent/mock_data/` 继续只服务脚本链路

### 4.5 `tools/definitions.py` / `tools/schemas.py` / `tools/validators.py`

这三者已经形成清晰分工：

- `definitions.py` 管工具元信息、工具名、描述、timeout / retry / circuit breaker 元数据
- `schemas.py` 管 tool input / output schema
- `validators.py` 管参数校验

### 4.6 `target/shop_resolver.py`

`shop_resolver` 仍然是业务级 shop resolver / `shop_id` 绑定权威入口。

事实：

- 对外 `resolve_shop()` 仍是功能入口
- 内部通过 gateway 调用工具
- `_resolve_with_backend()` 负责候选合并、上下文、歧义处理、最终选定结果

### 4.7 `target/candidate_resolver.py`

默认 resolve 回调已经从 `graph_builder` 迁走。

事实：

- `_default_resolve_shop()` 现在直接调用 `target.shop_resolver.resolve_shop`
- 不再默认绕 `engine.graph_builder`
- `search_shops` 的默认路径仍可保留原有实现，但本阶段没有扩张新的业务路由逻辑

### 4.8 `semantic/slot_extractor.py`

slot extractor 仍然保留 `task_type` / `workflow_hint`，但已经显式标成 `DEPRECATED_COMPAT`。

事实：

- 仍输出 `merchant_mentions` / `comparison_targets` / `preference_signals`
- 不输出 `shop_id`
- `task_type` / `workflow_hint` 只是迁移期兼容输出

### 4.9 `mock_data` 与 `tests/fixtures/mock_data`

两套数据源已被明确分工：

- `local_life_agent/tests/fixtures/mock_data/` 是测试权威 fixture
- `local_life_agent/mock_data/` 只允许脚本 / seed / 开发数据处理使用

### 4.10 `domain/schemas.py` 与 tool schema 的关系

`domain/schemas.py` 仍保留大量历史 DTO，它们并不是 tool schema 的权威来源。

与 tools / resolver 直接相关、但仍保留兼容窗口的 DTO 主要有：

- `ExecutionPlan`
- `EvidencePack`
- `ResolveShopResult`
- `AnswerPlan`
- `ComparisonTargetResolution`
- `OrchestrationDecision`
- `DecisionPlan`
- `ExplorationPlan`

canonical tool schema 已迁到 `tools/schemas.py`，这类 DTO 不再承担 tool schema 的权威职责。

## 5. Tool Registry 分层结果

当前分层结果如下：

| 职责 | 当前位置 | 是否应该留在 registry.py | 推荐目标文件 | 风险 | Phase 5 动作 |
|---|---|---|---|---|---|
| 工具名定义 | `tools/definitions.py` | 否 | `definitions.py` | 低 | 已迁出 |
| 工具描述 | `tools/definitions.py` | 否 | `definitions.py` | 低 | 已迁出 |
| handler 绑定元信息 | `tools/definitions.py` | 否 | `definitions.py` | 低 | 已迁出 |
| input schema | `tools/schemas.py` | 否 | `schemas.py` | 低 | 已迁出 |
| output schema | `tools/schemas.py` | 否 | `schemas.py` | 低 | 已迁出 |
| 参数校验 | `tools/validators.py` | 否 | `validators.py` | 低 | 已迁出 |
| registry lookup | `tools/registry.py` | 是 | `registry.py` | 低 | 保留薄 registry |
| fallback 处理 | `tools/gateway.py` / executor | 否 | `gateway.py` | 中 | 保持 gateway 处理 |

结论：

- `registry.py` 已缩成薄 lookup
- 不存在第二个 registry
- 不存在第二个 gateway

## 6. DB / Fixture / Fake 边界结果

### 6.1 生产路径

生产路径现在不再自动静默读取 fixture。

事实：

- `db_client` 不再检查 `PYTEST_CURRENT_TEST`
- 生产失败不会伪装成成功
- controlled degradation 由上层 gateway / normalizer 显式表达

### 6.2 测试路径

测试路径使用显式注入。

事实：

- `tests/conftest.py` 显式设置 `LOCAL_LIFE_DB_FIXTURE_FALLBACK=1`
- `tests/helpers/fake_backends.py` 继续用 monkeypatch 注入 fake backend
- `tests/fakes/mock_tools.py` 仍是测试 fake 工具实现

### 6.3 脚本路径

脚本仍可读取 `local_life_agent/mock_data/`，但这不再是 runtime path。

结论：

- fixture fallback 已显式化
- runtime path 不再直接读 `local_life_agent/mock_data/`
- `tests/fixtures/mock_data/` 是测试权威 fixture

## 7. resolve_shop / target_resolve 权威层级

当前权威层级已经明确：

| 实现 | 当前职责 | 当前调用方 | 是否绑定 shop_id | 是否访问 DB | 推荐层级 | Phase 5 动作 |
|---|---|---|---|---|---|---|
| `tools/db_tools.resolve_shop` | 低层工具级 resolution helper，仍返回 resolution-shaped 结果 | `ToolCallGateway` / 历史调用点 | 是，但偏工具级 | 是 | 低层 DB 工具 | 保留，后续可继续收缩 |
| `target/shop_resolver.resolve_shop` | 业务级 shop resolver / canonical authority | `candidate_resolver`、业务链路 | 是 | 间接通过 gateway / db client | canonical business resolver | 保持权威 |
| `target/candidate_resolver` | 候选生成 / 候选排序 / reference 解析辅助 | planning / resolver 流 | 间接 | 可能 | 候选层 | 默认回调已改向 canonical resolver |

结论：

- 没有新增第三个 resolver 权威实现
- `target/shop_resolver` 是业务级 `shop_id` 绑定权威层
- `candidate_resolver` 不再默认绕 `graph_builder`

## 8. slot_extractor 边界结果

当前决策：

- `task_type` / `workflow_hint` 暂不移除
- 它们已标记为 `DEPRECATED_COMPAT`
- 不作为最终业务决策权威

确认结果：

- `semantic_parse` 仍是 `task_type` / `intent` 的权威来源
- `target_resolve` / `shop_resolver` 仍是最终 `shop_id` 绑定权威
- `slot_extractor` 只保留 anchors / mentions / candidates / spans / signals

## 9. Tool Schema 与 Domain DTO 边界

### 9.1 迁到 `tools/schemas.py` 的部分

- tool input schema
- tool output schema

### 9.2 迁到 `tools/definitions.py` 的部分

- 工具名
- 工具描述
- timeout / retry / circuit breaker 元信息

### 9.3 保留在 domain 的部分

业务事实对象仍保留在 domain canonical owner：

- `DecisionPlan` -> `domain/decision.py`
- `EvidenceReviewResult` -> `domain/evidence.py`
- `ShopCandidate` / `ShopResolutionResult` -> `domain/shop_entity.py`
- `TargetResolutionResult` -> `domain/facets.py`

### 9.4 仍然 `NEEDS_DECISION` 的部分

- `domain/schemas.py` 中哪些历史 DTO 可以在后续阶段按真实调用方删除
- `db_tools.resolve_shop` 是否进一步收缩成更原子的 DB 能力

## 10. 修改方案

本阶段实际修改文件：

- [`local_life_agent/tools/schemas.py`](../local_life_agent/tools/schemas.py)
- [`local_life_agent/tools/definitions.py`](../local_life_agent/tools/definitions.py)
- [`local_life_agent/tools/validators.py`](../local_life_agent/tools/validators.py)
- [`local_life_agent/tools/registry.py`](../local_life_agent/tools/registry.py)
- [`local_life_agent/tools/db_client.py`](../local_life_agent/tools/db_client.py)
- [`local_life_agent/tools/db_tools.py`](../local_life_agent/tools/db_tools.py)
- [`local_life_agent/target/candidate_resolver.py`](../local_life_agent/target/candidate_resolver.py)
- [`local_life_agent/semantic/slot_extractor.py`](../local_life_agent/semantic/slot_extractor.py)
- [`local_life_agent/tests/conftest.py`](../local_life_agent/tests/conftest.py)
- [`local_life_agent/tests/test_phase5_tools_db_boundary.py`](../local_life_agent/tests/test_phase5_tools_db_boundary.py)
- [`local_life_agent/tests/test_slot_extractor_boundary_guard.py`](../local_life_agent/tests/test_slot_extractor_boundary_guard.py)
- [`todo/architecture_phase5_tools_db_boundary_convergence_report.md`](./architecture_phase5_tools_db_boundary_convergence_report.md)
- [`todo/architecture_overlap_analysis.md`](./architecture_overlap_analysis.md)

未修改但已确认不需要修改的文件：

- `planning/orchestration_router.py`
- `engine/workflow_runner.py`
- `engine/workflow_registry.py`
- `engine/workflows/*`
- `engine/subgraphs/*`
- `domain/graph_state.py`
- `domain/state.py`
- `engine/_compat.py`
- `engine/graph_builder.py`

原因：

- 本阶段严格不碰 router / workflow / state model / compat 删除
- 相关实现已经满足 Phase 5 的边界定义

## 11. 防止兼容层和同功能模块变多的措施

已确认：

- 没有新增 wrapper 作为第二权威
- 没有新增第二个 registry
- 没有新增第二个 gateway
- 没有新增第三个 resolver 权威实现
- 没有扩大 `_compat.py` 公共面
- 没有扩大 `graph_builder.py` 公共面
- 没有新增平行 DTO 大杂烩
- 没有违反 canonical import path 冻结原则

## 12. 测试与回归结果

已运行并通过：

- `python -m compileall local_life_agent`
- `pytest local_life_agent/tests/test_phase1_architecture_boundaries.py -q`
- `pytest local_life_agent/tests/test_phase2_routing_authority.py -q`
- `pytest local_life_agent/tests/test_phase3_orchestration_model.py -q`
- `pytest local_life_agent/tests/test_phase4_state_dto_contracts.py -q`
- `pytest local_life_agent/tests/test_phase5_tools_db_boundary.py -q`
- `pytest local_life_agent/tests/test_slot_extractor_boundary_guard.py -q`
- `pytest local_life_agent/tests/test_tool_gateway.py -q`
- `pytest local_life_agent/tests/test_tool_backend_switch.py -q`
- `pytest local_life_agent/tests/test_mock_seed_import.py -q`
- `pytest local_life_agent/tests/test_mock_data_normalization.py -q`
- `pytest local_life_agent/tests/test_target_resolution_contract.py -q`
- `pytest local_life_agent/tests/test_candidate_resolver.py -q`
- `pytest local_life_agent/tests/test_comparison_flow.py -q`
- `pytest local_life_agent/tests/test_single_coupon_flow.py -q`
- `pytest local_life_agent/tests/test_recommendation_flow.py -q`
- `pytest local_life_agent/tests/test_single_shop_multifacet.py -q`
- `pytest local_life_agent/tests/test_semantic_parser.py -q`
- `pytest local_life_agent/tests/test_p5_session_state_writeback.py -q`
- `pytest local_life_agent/tests/test_planning_execution_boundary.py -q`
- `pytest local_life_agent/tests/test_workflow_runner.py -q`
- `pytest local_life_agent/tests/test_workflow_registry.py -q`

结果摘要：

- registry / schemas / validators / gateway 分层测试通过
- DB fixture fallback 隔离测试通过
- runtime mock_data 读取隔离测试通过
- candidate_resolver 默认回调切到 canonical shop resolver
- slot_extractor 的兼容字段已显式标记
- comparison / single_coupon / recommendation / single_shop_multifacet 主链路无退化

## 13. 残余风险

- `db_tools.resolve_shop` 仍是 resolution-shaped helper，后续如果要进一步收缩，需要确认真实调用方
- `domain/schemas.py` 的历史 DTO 兼容窗口仍然存在
- `slot_extractor` 仍保留 `task_type` / `workflow_hint` 兼容字段，虽然已标为 `DEPRECATED_COMPAT`

## 14. Phase 6 准入判断

可以进入 Phase 6。

进入前需要继续保留的 `NEEDS_DECISION` 只有两项：

- `db_tools.resolve_shop` 是否继续收缩成更原子的 DB 能力
- `domain/schemas.py` 历史 DTO 的删除顺序

这两项不会阻断 Phase 6 的兼容层拆分，但需要在删除前按真实调用方再确认一次。
