# 08 风险与非目标

## 目标

本文件定义 Phase 0 到 Phase 9 的风险、非目标、触发条件、缓解措施与验收信号，防止改造过程中范围漂移、能力误写和路由过早复杂化。

它必须和前面文档保持一致：

- 当前真实主链路仍是单主链路
- 当前只有一级 `top_intent_router`
- 当前没有正式 `orchestration_router`、`workflow_runner` 和正式多 workflow 分流
- Phase 1 只做当前单主链路能力边界收口
- future tool、forbidden tool、workflow 目标和当前事实必须分开写

## 当前事实与阶段边界

### 当前真实主链路

```text
intake_guard_router
  -> merge_clarification
  -> understanding_subgraph
  -> planning_subgraph
  -> execution_review_subgraph
  -> response_subgraph
  -> state_update_plan
```

### 当前已有一级路由

- `top_intent_router`

### 当前没有正式落地的能力

- `orchestration_router`
- `workflow_runner`
- 多 workflow 分流
- 正式 `DiscoveryDecisionWorkflow`
- 正式 `DeterministicToolWorkflow`
- 正式 `DirectResponseWorkflow`
- 正式 `ClarificationFallbackWorkflow`
- 正式 `ExplorationPlanningWorkflow`

### 阶段口径

- 不要提前改外层图。
- 不要提前引入二级路由。
- 不要提前引入 `workflow_runner`。
- 不要提前拆多 workflow。
- 不要把 future tool 写成当前事实。

## 非目标分层

### RAG / 政策问答类非目标

- `RAG`
- `RAG retriever`
- `policy index`
- 平台政策解释
- 平台政策问答
- 商家入驻规则问答
- 退款规则问答
- `refund policy retrieval`
- `coupon policy RAG`
- `merchant onboarding RAG`

### 约束

- 当前阶段不做 RAG。
- 当前阶段不做政策检索。
- 当前阶段不做平台规则、商家入驻规则、退款规则解释。
- 不得通过 mock 或 fallback 伪装支持。

### 交易 / mutation 类非目标

- 交易
- 下单
- 支付
- 退款
- 取消订单
- 预约提交
- `transaction mutation tool`
- `payment tool`
- `refund tool`
- `booking submit tool`
- `cancel order mutation tool`
- `order create tool`
- `order update tool`
- `reservation submit tool`
- `payment confirm tool`

### 约束

- 当前阶段不做任何订单状态变更。
- 当前阶段不做任何支付、退款、预约提交。
- 不得设计当前阶段 schema、tool、workflow 或测试 mock 来支持这些能力。

### 架构类非目标

- 自由 `ReAct` loop
- 开放式 `multi-agent handoff`
- 未受控 `tool auto-discovery`
- 无白名单工具执行
- 无限 replan

### 约束

- 当前系统是受控 ToolCall workflow，不做自由开放式 Agent。
- 工具必须白名单控制。
- Planner / Review / Decision 必须受 schema / policy / validator 约束。

### 过早工程化非目标

- Phase 1 重写外层图
- Phase 1 引入 `orchestration_router`
- Phase 1 引入 `workflow_runner`
- Phase 1 拆 5 条 workflow
- Phase 1 一次性大搬迁 Core
- Phase 1 实现 `ExplorationPlanningWorkflow`

### 约束

- Phase 1 只做当前单主链路能力边界收口。
- Core 抽象先薄封装。
- Workflow 后置。

## 风险表

| 风险 | 所属阶段 | 触发条件 | 影响 | 缓解措施 | 验收信号 | 相关文档 |
| --- | --- | --- | --- | --- | --- | --- |
| 过早引入 `workflow_runner` | Phase 1 / Phase 2 / Phase 3 | 外层图尚未稳定时新增 `workflow_runner` | 重构范围过大，主链路回归困难 | 延后到 Phase 5，先稳定 Core 和 `DiscoveryDecision` 雏形 | Phase 5 之前外层图不出现 `workflow_runner` | [`03_workflow_design.md`](./03_workflow_design.md), [`04_migration_phases.md`](./04_migration_phases.md) |
| `orchestration_router` 在 schema 不稳定前引入 | Phase 1 / Phase 2 / Phase 3 | `semantic_frame` / state schema / `ReferenceResolutionResult` 未稳定时做二级路由 | 路由误判，workflow 分流不可信 | 延后到 Phase 4，先冻结字段表、policy、validator | Phase 4 前没有 `orchestration_router` 实现 | [`03_workflow_design.md`](./03_workflow_design.md), [`05_state_and_schema_design.md`](./05_state_and_schema_design.md) |
| `DeterministicToolWorkflow` 过早拆分 | Phase 1 / Phase 2 / Phase 3 | 单主链路未收口时拆单店工具链 | 测试覆盖不足，推荐和单店问答状态断裂 | Phase 6 后再拆，先强化 `reference_resolver` 和 `SessionState` | Phase 6 前不新增独立 deterministic_tool workflow | [`02_core_module_abstraction.md`](./02_core_module_abstraction.md), [`03_workflow_design.md`](./03_workflow_design.md) |
| future tool 被误写成 existing tool | 所有阶段 | 文档中出现未实现工具但未标记 future | 文档与实现不一致，ToolPlan 可能引用不存在工具 | 工具状态表强制标注 existing / to_refactor / future / forbidden | future tool 不进入 current ToolPlan | [`06_toolcall_only_scope.md`](./06_toolcall_only_scope.md) |
| forbidden tool 被 mock 偷渡 | 所有阶段 | 通过 mock 假装支持 RAG、交易、退款、预约、订单 mutation | 测试误判能力范围，后续实现偏航 | forbidden tool 不能进入 registry、ToolPlan、mock、fallback hidden path | forbidden tool 测试必须拒绝执行 | [`06_toolcall_only_scope.md`](./06_toolcall_only_scope.md), [`07_testing_and_acceptance.md`](./07_testing_and_acceptance.md) |
| `ResponseCore` 绕过 `EvidencePack` | Phase 1+ | 回答层直接读 `tool_result_set` 或工具原始结果编事实 | 事实绑定断裂，`AnswerVerifier` 难以校验 | `ResponseCore` 只能基于 `AnswerPlan` / `DecisionPlan` / `EvidencePack` | `ToolResultSet` 不能直接进入 `final_response` | [`02_core_module_abstraction.md`](./02_core_module_abstraction.md), [`05_state_and_schema_design.md`](./05_state_and_schema_design.md) |
| `DecisionCore` 继续依赖 `search rank` | Phase 1+ | `candidate_decision` 仍把 `search_shops` 返回顺序作为最终推荐顺序 | 离得远或不符合约束的店可能被首推 | `DecisionCore` 基于 `EvidencePack`、用户约束、距离、价格、营业状态、评价、优惠、场景适配综合决策 | 推荐不依赖 `recall_rank` 作为唯一依据 | [`02_core_module_abstraction.md`](./02_core_module_abstraction.md), [`06_toolcall_only_scope.md`](./06_toolcall_only_scope.md) |
| `EvidenceCore` 继续选择 winner | Phase 1+ | `build_evidence` 中继续做最终排序、合并推荐、选择 winner | Evidence 和 Decision 边界混乱 | `EvidenceCore` 只补事实、标记 `missing_fields` / `unknowns` / `failed_tools` | `EvidencePack` 不含 `final_winner` / `best_shop` | [`02_core_module_abstraction.md`](./02_core_module_abstraction.md), [`05_state_and_schema_design.md`](./05_state_and_schema_design.md) |
| `MOCK_LOCATION` 残留到主链路 | Phase 0 / Phase 1 | `input/receiver.py` 或 `engine/_compat.py` 继续把 `MOCK_LOCATION` 当真实位置注入 | 附近推荐看似正常，实际依赖静态默认值 | 引入 `location_status` / `location_source` / `requires_location` / `location_missing_reason` | `location_status = missing` 时不能假装知道附近 | [`05_state_and_schema_design.md`](./05_state_and_schema_design.md), [`06_toolcall_only_scope.md`](./06_toolcall_only_scope.md) |
| 大量 `if / elif / else` 继续扩散 | 所有阶段 | 新增 `task_type` 或 workflow 时继续堆分支 | 维护困难，新增能力容易破坏旧逻辑 | `policy table` / `registry` / `schema` / prompt-driven classification | 新增 `task_type` 优先改 policy / schema / prompt / 测试 | [`03_workflow_design.md`](./03_workflow_design.md), [`04_migration_phases.md`](./04_migration_phases.md) |
| 回复模板过度固定 | Phase 1+ | 同一 `response_mode` 只有一套硬模板 | 回复机械、扩展困难 | `response_mode + response_style + answer_plan + verbalizer prompt` | 同 mode 多 style，不引入未验证事实 | [`03_workflow_design.md`](./03_workflow_design.md), [`07_testing_and_acceptance.md`](./07_testing_and_acceptance.md) |
| 日志不结构化 | Phase 0+ | 节点、Core、ToolCall、Review、Verifier 没有结构化日志 | 无法定位路由错、计划错、工具错、证据错、决策错、回答错 | 统一写入 `var\python_service.log`，并固定字段 | 失败场景能看到 `node_name` / `next_action` / `error_code` / `confidence` | [`05_state_and_schema_design.md`](./05_state_and_schema_design.md), [`07_testing_and_acceptance.md`](./07_testing_and_acceptance.md) |
| 状态字段语义混用 | Phase 1+ | `top_intent` / `orchestration_pattern` / `workflow_name` / `goal_type` / `response_mode` 混用 | 路由、规划、回答状态混乱 | 字段语义表和 schema validator | `top_intent ≠ orchestration_pattern`，`response_mode ≠ workflow_name` | [`05_state_and_schema_design.md`](./05_state_and_schema_design.md) |
| `last_answer_order` 被误当最终排名 | Phase 1+ | 多轮指代时把展示顺序当综合推荐顺序 | 续问和对比错位 | 明确 `last_answer_order` 只表示展示顺序，`DecisionPlan` 才表示决策排序 | “第二家”解析基于 `last_answer_order`，但推荐排序不由其决定 | [`05_state_and_schema_design.md`](./05_state_and_schema_design.md), [`07_testing_and_acceptance.md`](./07_testing_and_acceptance.md) |
| 真实后端验收被 mock 替代 | Phase 0+ | 只靠 mock 测试判断功能完成 | real LLM / real DB / real Java API / SSE 问题被掩盖 | 保留真实后端验收阶段 | 最终验收覆盖 real LLM / real DB / real Java API / SSE | [`07_testing_and_acceptance.md`](./07_testing_and_acceptance.md) |

## Phase 风险地图

### Phase 0

- 日志不结构化
- 真实后端验收被 mock 替代
- 当前行为没有基线

### Phase 1

- `search_shops` 继续决定推荐
- `build_evidence` 继续选择 winner
- `candidate_decision` 继续依赖 rank
- `MOCK_LOCATION` 残留
- `ResponseCore` 绕过 `EvidencePack`
- `SessionState` 字段混用

### Phase 2

- Core 抽象过宽
- Core 依赖 LangGraph
- Core 不能单测
- 一次性大搬迁导致回归困难

### Phase 3

- 把 `DiscoveryDecisionWorkflow` 雏形误写成当前正式 workflow
- 主链路还不稳定就准备分流

### Phase 4

- schema 不稳定时引入 `orchestration_router`
- 二级路由和一级路由职责混淆

### Phase 5

- `workflow_runner` 变成业务判断中心
- registry 被 `if / else` 取代

### Phase 6-8

- `deterministic_tool` / `direct_response` / `fallback` / `exploration` 提前膨胀
- exploration 变成无限 replan 或开放式 `ReAct`

### Phase 9

- 文档、测试、实现不同步

## 风险处理规则

- 如果某个实现需求命中非目标：
  - 不进入代码实现
  - 不进入 ToolPlan
  - 不进入 schema
  - 不进入测试 mock
  - 记录为 future / forbidden
  - 必要时输出能力边界说明
- 如果某个实现需求命中高风险：
  - 先补测试
  - 先补 schema
  - 先补日志
  - 先补文档验收
  - 再进入代码实现
- 如果发现当前文档与代码事实冲突：
  - 以代码事实为准
  - 回修 `00_current_architecture_review.md`
  - 再同步后续文档

## Core 模块边界约束

### PlanningCore

- 不读 DB
- 不调工具
- 不生成最终自然语言

### CandidateCore

- 不最终排序
- 不默认第一家
- 不生成最终回答

### ExecutionCore

- 不做推荐决策
- 不生成回答
- 不编造工具结果

### EvidenceCore

- 不最终排序
- 不选择 winner
- 不生成回答

### DecisionCore

- 不调用工具
- 不读 DB
- 不生成最终自然语言
- 不盲目依赖 `search rank`

### ResponseCore

- 不改 `DecisionCore` 选择
- 不绕过 `EvidencePack` 编事实
- 不承诺交易 / 退款 / 支付 / 预约

### StateCore

- 不做业务决策
- 不生成回答
- 不持久化敏感隐私明文

## 禁止范围

当前阶段仍然不做：

- RAG
- 平台政策问答
- 商家入驻规则问答
- 退款规则问答
- 交易
- 下单
- 支付
- 退款
- 取消订单
- 预约提交
- 订单 mutation tool
- 自由 ReAct loop
- 开放式 multi-agent handoff

### 约束

- 这些不能作为当前阶段工具、schema、测试 mock、fallback hidden path。

## 当前事实、近期收口、后续目标

### 当前事实

- 当前风险控制应以单主链路为准。
- 当前风险重点是工具、证据、决策、回答和状态边界。
- 当前还没有正式多 workflow 分流。

### 近期收口

- 把非目标写成硬约束，不给临时实现留口子。
- 把 `search_shops`、`build_evidence`、`DecisionCore`、`ResponseCore` 的边界作为风险重点。
- 把 `MOCK_LOCATION`、日志、状态语义混用写入验收与风险追踪。

### 后续目标

- Phase 2 再强化 Core 单测和 schema 校验。
- Phase 3 再把当前主链路稳定成 `DiscoveryDecisionWorkflow` 雏形。
- Phase 4+ 再验证 `orchestration_router` 和 workflow 分流。

## 可执行建议

1. 先把风险写成可测的验收信号。
2. 再把非目标写成不可绕过的硬约束。
3. 当前阶段不要给 future 和 forbidden 留“临时实现”口子。
4. 一旦发现实现和文档冲突，先回修当前事实文档，再同步后续文档。

## 可执行版补充

### 风险-缓解表

| 风险 | 触发条件 | 影响 | 缓解措施 | 验收信号 |
| --- | --- | --- | --- | --- |
| 过早引入 `workflow_runner` | 外层图尚未稳定 | 重构范围扩大 | 延后到 Phase 5 以后 | Phase 5 之前外层图不变 |
| `orchestration_router` 过早引入 | schema 还在变 | 路由误判 | 先冻结字段表 | Phase 4 前没有 `orchestration_router` |
| `deterministic_tool` 过早拆分 | 单主链路未收口 | 回归变差 | 等 Phase 6 后再拆 | Phase 6 前不新增独立 workflow |
| future tool 被误写成现有能力 | 文档 / 实现不一致 | 事实污染 | future 标记强制化 | future tool 不进入 current ToolPlan |
| `ResponseCore` 越权 | 直接读工具结果编事实 | 回答漂移 | verifier 强制校验 | 未授权事实被拦截 |
| `DecisionCore` 依赖 rank | 召回顺序污染决策 | 推荐不稳定 | 决策只看 evidence | 排序独立可测 |
| `MOCK_LOCATION` 残留 | 默认位置注入主链路 | 测试 / 生产混淆 | 去默认注入 | 复杂 query 不依赖 mock |
| 大量 `if / elif / else` | 新增 `task_type` | 维护困难 | policy table + registry | 分支数量可控 |
| 回复模板固定 | 只保留一个话术 | 表达单一 | `response_style` 机制 | 同 mode 多样化 |
| 日志不结构化 | 失败时无关键字段 | 难排查 | 强制日志字段表 | 可定位错误节点 |

### 非目标验收

- 任何非目标都不得以“临时实现”进入主链路。
- 如果文档里出现未来能力，必须同时标明是 future tool 或后续 phase。
- 设计文档不得把“暂时不做”写成“默认会做”。

