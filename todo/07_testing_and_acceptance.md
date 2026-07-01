# 07 测试与验收

## 目标

本文件定义分阶段测试与验收总表，覆盖当前主链路回归、Core / 模块边界、ToolCall-only 范围、日志、Prompt / Schema / Policy、以及后续 workflow 分流验收。

它必须和前面文档保持一致：

- 当前真实主链路仍是单主链路
- 当前只有一级 `top_intent_router`
- 当前没有正式 `orchestration_router`、`workflow_runner` 和正式多 workflow 分流
- Phase 1 只做单主链路能力边界收口
- workflow 测试矩阵可以写，但必须标注为后续阶段验收目标

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

### 阶段结论

- Workflow 测试矩阵可以保留，但它是后续阶段验收目标，不是当前代码事实。
- Phase 0 / Phase 1 的测试重点仍然是当前单主链路回归、职责边界、状态、证据、决策、回答一致性。

## 测试阶段分层

| 阶段 | 测试目标 | 说明 |
| --- | --- | --- |
| Phase 0 | 当前主链路回归、trace / 日志基线、当前行为快照、节点输入输出摘要可观察 | 先确认现状，不追求重构完成度 |
| Phase 1 | `search_shops` 只召回、`build_evidence` 只补事实、`candidate_decision` 不依赖召回顺序、`reference_resolver` 多轮指代一致、`MOCK_LOCATION` 不作为真实位置、`SessionState` 可序列化、`Review` / `Verifier` 真正触发澄清或降级 | 这是当前收口主战场 |
| Phase 2 | 七个 Core 可单测、Core 不依赖 LangGraph、Core 输入输出 schema 可校验 | 主要验证模块化抽象 |
| Phase 3 | 当前主链路稳定成 `DiscoveryDecisionWorkflow` 雏形、推荐 / 搜索 / 对比 / 筛选稳定回归、`DecisionPlan` / `AnswerPlan` / `EvidencePack` 可追踪 | 属于更稳定的能力收口阶段 |
| Phase 4+ | `orchestration_router`、`workflow_runner`、5 条 workflow 分流测试 | 属于后续 workflow 分流阶段 |
| Phase 5 | `workflow_runner` + whitelist registry + `discovery_decision` 薄适配 | 当前已进入实现期 |

## Phase 0 必测清单

### 必测样例

- 普通问候
- 能力说明
- 附近有什么咖啡店
- 推荐一家适合约会的日料，别太贵
- 第一家和第三家哪个好
- 第二家离我多远
- 换个便宜点的
- 这家现在营业吗
- 无位置时推荐附近店
- 无历史候选时说“第二家”
- 工具失败
- 工具空结果
- 证据不足

### 验收标准

- 能跑通或能稳定复现当前行为。
- 能输出 trace / 日志。
- 能定位失败节点和 `next_action`。
- 能看见当前主链路的真实边界，而不是未来 workflow 假象。

## Phase 1 必测清单

### 必测样例

- `search_shops` 输出不包含 `final_winner` / `best_shop`
- `search_shops` 返回顺序不能直接决定最终推荐
- `build_evidence` 不选择 winner
- `EvidencePack` 缺关键字段时 `evidence_review` 不通过
- `candidate_decision` 推荐要综合距离、价格、营业状态、评分、优惠、评价摘要、场景适配、用户约束
- 明显过远、未营业、超预算、类目不匹配的店不能无理由首推
- `ResponseCore` / `answer_generate` 不能新增 `EvidencePack` 外事实
- `AnswerVerifier` 能拦截未授权事实
- 无 `last_answer_order` 时不能解析“第二家”
- `last_answer_order` 不等于最终推荐排名
- `MOCK_LOCATION` 不能作为真实 `provided location`
- 日志写入 `var\python_service.log`

### 验收标准

- 当前单主链路内的职责边界能被稳定证明。
- 工具、证据、决策、回答之间不互相越权。
- Phase 1 不依赖未来 workflow 也能成立。

## workflow 测试矩阵

当前可以保留 5 条 workflow 测试矩阵，但必须明确它们是后续阶段验收目标，不是当前代码事实。

| workflow | 典型意图 | 阶段 | 说明 |
| --- | --- | --- | --- |
| `DirectResponseWorkflow` | 问候、能力说明、不需要工具的简单问答 | Phase 7 后验收 | 当前可作为目标设计，Phase 1 不要求存在 |
| `DeterministicToolWorkflow` | 店铺状态、距离、营业时间、优惠券、评价摘要 | Phase 6 后验收 | 当前只有单主链路中的工具事实能力雏形 |
| `DiscoveryDecisionWorkflow` | 搜索、推荐、多店对比、条件筛选、场景推荐、团购比较 | Phase 3 作为雏形验收，Phase 5 后作为正式 workflow 验收 | 当前主链路的演进方向 |
| `ExplorationPlanningWorkflow` | local trip plan、date plan、family activity plan 等 | Phase 8 后验收 | 当前不属于 Phase 1 |
| `ClarificationFallbackWorkflow` | 指代不清、多候选、无结果、工具失败、reference_failed | Phase 7 后验收 | 当前可以强化澄清行为，但不要求正式 workflow 落地 |

### 说明

- 当前代码没有正式 5 条 workflow 分流。
- 这些测试矩阵是后续阶段验收目标。
- Phase 1 不要求这些 workflow 都存在。
- Phase 5 只要求 `workflow_runner` / registry / `discovery_decision` 调度稳定，不要求后续 4 条 workflow 全部拆完。

## 当前路由与未来路由测试

### 当前路由测试

- `top_intent_router` 只做一级粗路由。
- `top_intent_router` 不决定具体 workflow。
- `top_intent_router` 能识别 `chat / capability / local_life / unsafe / out_of_scope / invalid`。

### 后续路由测试

- `orchestration_router` 当前以 shadow mode 运行，只写 `GraphState.orchestration_decision`。
- `orchestration_router` 不调用工具。
- `orchestration_router` 不生成最终答案。
- `orchestration_router` 不写入 `SessionState`。
- `orchestration_router` 不改变当前 graph conditional edge。
- `orchestration_router` 低 `confidence` 进入 `clarification_fallback`。
- 推荐问题进入 `discovery_decision`。
- 单店事实查询在 target 明确时进入 `deterministic_tool`。
- 多子目标规划进入 `exploration_planning`。

### 阶段约束

- `orchestration_router` 的 shadow-mode 测试属于 Phase 4。
- Phase 1 不应要求当前代码通过完整 workflow 分流测试。
- `orchestration_decision` 的序列化和 SessionState 隔离应被显式验证。

## Core / 模块边界测试

### PlanningCore

- 不调用工具
- 不读 DB
- 输出 `GoalPlan` / `EvidencePlan` schema 合法

### CandidateCore

- 能解析这家 / 第一家 / 第一家和第三家
- 无历史候选时不能解析第二家
- 不默认选择第一家

### ExecutionCore

- 未知工具被拒绝
- forbidden tool 被拒绝
- 工具失败进入 `failed_tools`
- 不生成推荐话术

### EvidenceCore

- `ToolResultSet` 必须转 `EvidencePack`
- 缺关键字段 `evidence_review` 不通过
- 不选择 winner

### DecisionCore

- 不调用工具
- 不直接读 DB
- 不依赖 `search rank` 作为唯一排序依据
- 明显违反用户约束的候选不能无理由首推

### ResponseCore

- 不直接读取 `tool_result_set` 编事实
- 不改变 `DecisionPlan` 的选择结果
- 不新增 `EvidencePack` 外事实
- verifier 不通过时 rewrite 或 fallback

### StateCore

- `StatePatch` 可序列化
- `last_answer_order` / `last_recommendation_list` 可跨轮读取
- 不持久化敏感隐私明文

## ToolCall-only 测试

### 必测项

- future tool 不能进入 current ToolPlan
- forbidden tool 不能被执行
- unknown tool 被拒绝
- `RAG` / policy retrieval / refund retrieval 不允许出现在工具计划
- `payment` / `refund` / `booking` / `cancel order` mutation tool 不允许出现在工具计划
- `MOCK_LOCATION` 不能伪装成 `get_user_location` 真实返回
- `ToolResultSet` 不能绕过 `EvidencePack` 进入 `final_response`

### 验收标准

- 当前工具白名单和 ToolCall 约束能被测试显式证明。
- forbidden 能力不能通过 mock 混入当前阶段。

## Prompt / Schema / Policy 测试

### 必测项

- `semantic_parse` 输出必须符合 schema
- `goal_planner` 输出必须符合 schema
- `evidence_review` 输出必须包含 `passed / confidence / missing_fields / next_action / reason`
- `decision_planner` 输出必须包含 `selected_targets / rejected_candidates / claim_bindings / confidence`
- `answer_plan` 输出必须包含 `response_mode / allowed_claims / forbidden_claims`
- 低 `confidence` 必须进入 clarification 或 fallback
- policy table 缺失项不能静默进入错误 workflow
- 新增 `task_type` 必须先补 policy / schema / 测试

### 验收标准

- schema 校验失败应当显式暴露，而不是被静默吞掉。
- policy 缺口不能通过宽松默认值掩盖。

## Response 多样性测试

- 同一 `response_mode` 不应只有一种固定模板。
- 不同 `response_style` 可以改变表达方式。
- `response_style` 不能改变事实和决策。
- 多样性不得引入未验证事实。
- `AnswerVerifier` 必须能拦截未授权事实。

## 日志测试

### 关键节点要求

每个关键节点 / Core / ToolCall / Review / Response / Verifier 都要写入 `var\python_service.log`。

### 必测字段

- `timestamp`
- `session_id`
- `turn_id`
- `node_name`
- `core_name`
- `workflow_name`
- `task_type`
- `goal_type`
- `input_summary`
- `output_summary`
- `state_keys_changed`
- `latency_ms`
- `status`
- `next_action`
- `confidence`
- `error_code`
- `error_message`
- `workflow_run_status`
- `workflow_runner_error`
- `workflow_runner_reason`

### 禁止记录

- 手机号
- token
- 支付信息
- 完整敏感地址
- 完整隐私明文

## 真实后端验收

必须覆盖：

- real LLM
- real DB
- real Java API
- SSE 流式输出

### 约束

- 真实后端验收属于集成 / E2E 阶段。
- 不能只靠 mock 判断最终可用。
- 但 Phase 0 / Phase 1 可以先建立最小 mock + trace 基线。

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

- 这些不能作为当前阶段测试目标。
- 不能通过 mock 假装支持。
- 不能出现在当前 ToolPlan、workflow、fallback hidden path。

## 当前事实、近期收口、后续目标

### 当前事实

- 当前测试应以单主链路为准。
- 当前测试重点是工具、证据、决策、回答和状态边界。
- 当前还没有正式多 workflow 分流。

### 近期收口

- 把 Phase 0 / Phase 1 的验证点写具体。
- 把 `search_shops`、`build_evidence`、`DecisionCore`、`ResponseCore` 的边界作为回归重点。
- 把 `MOCK_LOCATION` 的位置边界和日志边界写入验收。

### 后续目标

- Phase 2 再强化 Core 单测和 schema 校验。
- Phase 3 再把当前主链路稳定成 `DiscoveryDecisionWorkflow` 雏形。
- Phase 4+ 再验证 `orchestration_router` 和 workflow 分流。

## 可执行建议

1. 先写能暴露边界问题的测试。
2. 再改实现。
3. 每次改动后跑相关单测和回归。
4. 当前阶段的测试基线不要混入未来 workflow 事实。

## 可执行版补充

### 测试分层

| 层级 | 目标 | 示例 | 验收方式 |
| --- | --- | --- | --- |
| 单元测试 | 验证 Core / schema / policy | `CandidateCore`, `AnswerPlan` | 无需外部依赖即可运行 |
| 节点测试 | 验证单个 graph node | `semantic_parse`, `review_evidence` | 输入输出字段可断言 |
| workflow 测试 | 验证一条 workflow 的行为 | `DiscoveryDecisionWorkflow` | 路由、工具、回复一致 |
| 端到端测试 | 验证真实后端链路 | real LLM / real DB / real Java API | SSE / 回答 / 日志稳定 |

### workflow 验收表

| workflow | 必测输入 | 必测输出 | 必测失败路径 |
| --- | --- | --- | --- |
| `DirectResponseWorkflow` | 问候、能力说明 | 直接回答 | 信息不足时澄清 |
| `DeterministicToolWorkflow` | 状态、距离、券、营业时间 | 工具事实回答 | 工具失败转澄清 |
| `DiscoveryDecisionWorkflow` | 搜索、推荐、对比 | 候选 + 决策 + 回答 | 无结果 / 歧义 / 证据不足 |
| `ExplorationPlanningWorkflow` | 旅行 / 约会 / 家庭规划 | 规划建议 | 信息不足转澄清 |
| `ClarificationFallbackWorkflow` | 歧义、无结果、失败 | 澄清或可信失败 | 不能继续硬跑 |

### 通过标准

- 关键测试必须覆盖“正常路径 + 失败路径 + 降级路径”。
- 新增字段后，必须补至少一条断言该字段的测试。
- 回归不允许只看一条 happy path。
- 日志测试必须能定位到失败节点和 `next_action`。
