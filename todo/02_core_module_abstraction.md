# 02 核心模块抽象

## 目标

本文件定义的是目标抽象方向，不代表当前阶段全部落地。
当前可开工范围仍以 Phase 1 为准，Phase 1 只做单主链路能力边界收口。

采用“双层命名”：

- 能力包 / 能力职责：面向架构说明
- Core 模块：面向代码落地

核心原则：

- Core 不依赖 LangGraph
- subgraph 调 Core
- Core 不调用 subgraph
- Core 可单测
- Core 通过 schema / policy / registry / prompt-driven classification 驱动
- 避免大量 `if / elif / else` 堆叠

## 当前事实 / 近期改造 / 最终目标 / future work

### 当前事实

- 当前代码中 Planning / Candidate / Execution / Evidence / Decision / Response / State 这些职责都已经不同程度存在。
- 但它们还没有完全以独立 Core 模块形式落地。
- 当前仍然是 subgraph + 若干 planning / evidence / decision / answer 工具函数混合组织。
- 当前外层图不应在 Phase 1 改动。

### 近期改造

- Phase 1 只做薄封装和职责收口。
- Phase 1 优先抽可单测的 Core 边界。
- Phase 1 不要求一次性搬空原模块。
- Phase 1 不新增 `orchestration_router`。
- Phase 1 不新增 `workflow_runner`。
- Phase 1 不新增多 workflow。

### 最终目标

- 最终目标是 subgraph 只负责编排和状态流转。
- 业务能力沉到 Core。
- Core 可单测、可复用、可被不同 workflow 组合。

### future work

- 后续再把 Core 组合进 `DiscoveryDecisionWorkflow`、`DeterministicToolWorkflow` 等多 workflow。
- 后续再扩展更复杂的 exploration planning。
- 后续可补充 future tool。

future workflow 不是当前代码事实。
future workflow 不是 Phase 1 实现范围。

## Core 双层命名和映射

能力包是架构语义，Core 模块是代码落地边界，subgraph 调 Core，Core 不依赖 LangGraph。

| 能力包 | Core 模块 |
| --- | --- |
| `IntentPlanningAbility` | `PlanningCore` |
| `ContextMemoryAbility` | `StateCore` |
| `ReferenceResolutionAbility` | `CandidateCore / StateCore` |
| `SearchRecallAbility` | `ExecutionCore + search_shops` |
| `EvidenceEnrichmentAbility` | `EvidenceCore` |
| `CandidateDecisionAbility` | `DecisionCore` |
| `ComparisonDecisionAbility` | `DecisionCore` |
| `AnswerGroundingAbility` | `ResponseCore` |
| `ReviewSufficiencyAbility` | `EvidenceCore / DecisionCore` |
| `AnswerVerifierAbility` | `ResponseCore` |
| `TraceObservabilityAbility` | `StateCore / observability` |

## Core 数据流

推荐主链路的内部职责流为：

```text
PlanningCore
  -> CandidateCore
  -> ExecutionCore
  -> EvidenceCore
  -> DecisionCore
  -> ResponseCore
  -> StateCore
```

这不是 Phase 1 新增 workflow。
这是把现有 `planning_subgraph` / `execution_review_subgraph` / `response_subgraph` / `state_update_plan` 内部职责收口后的逻辑边界。

## 七个 Core 的职责边界

### 1. PlanningCore

输入：

- user semantic frame
- session context summary
- pending clarification
- active constraints

输出：

- `GoalPlan`
- `EvidencePlan`
- `missing_fields`
- `confidence`
- `next_action`

允许：

- 理解目标
- 生成结构化计划
- 判断证据需求

禁止：

- 直接调用工具
- 直接读 DB
- 选择最终推荐 winner
- 生成最终自然语言回答

Phase 1 落地：

- 先包现有 `planning_subgraph` 中 `goal_planner` / `evidence_planner` 相关逻辑
- 不改变 `planning_subgraph` 外层路由

验收标准：

- 计划输出可序列化
- 缺字段状态显式返回
- 不依赖外部工具调用即可单测

### 2. CandidateCore

输入：

- `current_shop`
- `last_recommendation_list`
- `last_answer_order`
- user reference text
- candidate list
- comparison target hints

输出：

- `CandidateSet`
- `ReferenceResolutionResult`
- `comparison_targets`
- `current_shop_patch`
- `requires_clarification`

允许：

- 统一处理“这家 / 它 / 第一家 / 第二家 / 第一家和第三家”
- 维护候选上下文
- 输出澄清问题

禁止：

- 最终推荐排序
- 默认选择第一家
- 在无历史候选时强行解析序号
- 生成最终回答

Phase 1 落地：

- 以 `target/reference_resolver.py` 为主要收口点
- planning / clarification / observability 只消费解析结果或记录解析来源
- 不让 `trace.py` 成为实际解析实现

验收标准：

- 无历史候选时不能凭空解析第二家
- 对推荐 / 对比 / 查店的解析结果可复用
- 解析失败会显式要求澄清

### 3. ExecutionCore

输入：

- `ToolPlan`
- `ToolCallSet`
- runtime context
- tool registry

输出：

- `ToolResultSet`
- `failed_tools`
- `partial_success`
- `latency`
- `status`

允许：

- 执行 ToolCall
- 处理工具失败、超时、空结果、部分成功

禁止：

- 做推荐决策
- 改写用户偏好
- 生成最终回答
- 编造工具结果

Phase 1 落地：

- 复用现有 `ToolCallGateway` / `BatchToolExecutor`
- 不改变工具语义
- `search_shops` 仍作为工具，但只应承担召回语义

验收标准：

- 工具失败、超时、空结果都有显式状态
- 不把失败伪装成成功
- tool registry 之外的调用不可进入主链路

### 4. EvidenceCore

输入：

- `ToolResultSet`
- `GoalPlan`
- `CandidateSet`
- user constraints

输出：

- `EvidencePack`
- `missing_fields`
- `unknowns`
- `failed_tools`
- `evidence_review_result`

允许：

- 合并工具结果
- 补事实
- 标记缺失
- 做 evidence review

禁止：

- 选择最终 winner
- 做最终推荐排序
- 生成最终回答
- 把 search rank 固化为最终排序

Phase 1 落地：

- 以 `build_evidence()` 为主要收口点
- `build_evidence` 可以保留 `recall_rank` / `evidence_quality_score` 等事实字段
- 但最终选择必须交给 `DecisionCore`

验收标准：

- 缺关键字段时不能通过 evidence review
- EvidencePack 必须可追溯到 tool result
- 不以召回顺序替代最终决策

### 5. DecisionCore

输入：

- `EvidencePack`
- `CandidateSet`
- `GoalPlan`
- user constraints
- ranking policy

输出：

- `DecisionPlan`
- `selected_targets`
- `overall_ranking`
- `winner_shop_id`
- `rejected_candidates`
- `rationale_points`
- `claim_bindings`
- `confidence`
- `next_action`

允许：

- 基于证据做综合决策
- 搜索 TopN
- 推荐首推和备选
- 多店对比 winner
- 单店属性判断

禁止：

- 调工具
- 读 DB
- 编造事实
- 生成最终自然语言回答
- 盲目依赖 `search_shops` 返回顺序

Phase 1 落地：

- 以 `planning/decision/candidate_decision.py` 为主要收口点
- 推荐要综合距离、价格、营业状态、评分、优惠、评价摘要、场景适配、用户约束
- 明显过远、未营业、超预算、类目不匹配的店不能无理由首推

验收标准：

- 决策不依赖召回 rank
- 首推结果可由 evidence 解释
- comparison winner 和 recommendation winner 都有明确理由

### 6. ResponseCore

输入：

- `AnswerPlan`
- `DecisionPlan`
- `EvidencePack`
- `response_mode`
- `response_style`

输出：

- `final_response`
- `verifier_result`
- `rewrite_result`

允许：

- 生成自然语言回答
- 控制回复风格和多样性
- 执行 `AnswerVerifier`
- 必要时 rewrite

禁止：

- 改变 `DecisionCore` 的选择结果
- 绕过 `EvidencePack` 编造事实
- 直接根据 `tool_result_set` 重新挑店
- 承诺下单、退款、支付、预约

Phase 1 落地：

- 以 answer generation / answer verifier 为主要收口点
- 先保证回答不越权，不要求一次性实现复杂风格系统

验收标准：

- 回答必须经过 verifier 或等价校验
- 不得引入 EvidencePack 外事实
- 能在不同 response_style 下保持事实一致

### 7. StateCore

输入：

- `GraphState` delta
- `SessionState before`
- runtime events
- node outputs

输出：

- `StatePatch`
- `SessionState after`
- `event_log`
- `trace_spans`
- `state_keys_changed`

允许：

- 维护状态补丁
- 记录多轮候选
- 记录 `current_shop` / `last_answer_order` / `last_evidence_pack`
- 记录日志和 trace

禁止：

- 做业务决策
- 生成回答
- 修改事实结果
- 持久化敏感隐私明文

Phase 1 落地：

- 补齐 `SessionState` 字段
- 让 `state_update_plan` 消费 `StatePatch`
- 结构化日志写入 `var\\python_service.log`

验收标准：

- 状态补丁可回放
- event log 与 trace spans 能对齐
- 不把业务事实和运行时推断混写

## Phase 1 落地方式

1. 先把现有逻辑包成薄 Core。
2. Core 先作为边界和测试单元存在。
3. subgraph 继续保留，外层图不改。
4. Core 先接住现有 planning / evidence / decision / answer / state 逻辑，再逐步拆细。
5. 后续阶段再把 Core 组合进 workflow。

## 日志与测试要求

### 日志

每个 Core 的关键入口和出口都要记录结构化日志。

日志统一写入 `var\\python_service.log`。

日志字段至少包括：

- `session_id`
- `turn_id`
- `core_name`
- `input_summary`
- `output_summary`
- `state_keys_changed`
- `latency_ms`
- `status`
- `error_code`
- `next_action`

禁止记录：

- 手机号
- token
- 支付信息
- 完整敏感地址

### 测试

每个 Core 必须可单测。

每个 Core 至少有最小 happy path 和 failure / missing field case。

必须覆盖：

- `DecisionCore` 必须有“不依赖 search rank”的测试
- `CandidateCore` 必须有“无历史候选时不能解析第二家”的测试
- `EvidenceCore` 必须有“缺关键字段不能通过 evidence review”的测试
- `ResponseCore` 必须有“不能编造 EvidencePack 外事实”的测试

## 禁止范围

当前阶段仍然不做：

- RAG
- 交易
- 下单
- 支付
- 退款
- 取消订单
- 预约提交
- 订单 mutation tool
- 自由 ReAct loop
- 开放式 multi-agent handoff

这些不是 Core 模块职责。

## 可执行建议

1. 先定义 Core 的输入输出 schema。
2. 再把现有逻辑迁移成薄适配层。
3. Core 内避免用大段 `if / elif / else`，优先 policy table 和 registry。
4. Phase 1 只收口边界，不改外层图。

## 可执行版补充

### Core 设计检查表

| Core 模块 | 输入 | 输出 | 依赖 | 不做什么 | 验收标准 |
| --- | --- | --- | --- | --- | --- |
| PlanningCore | goal / semantic_frame / context | GoalPlan / EvidencePlan | schema、prompt、policy | 不直接调工具，不直接读 DB | 产出的 plan 可序列化，且字段满足 validator |
| CandidateCore | current_shop / last_recommendation_list / comparison_targets | CandidateSet / ReferenceResolutionResult | StateCore、candidate schema | 不做最终推荐 | 指代解析和候选集状态可回放 |
| ExecutionCore | ToolPlan / ToolCallSet | ToolResultSet | gateway、executor、tool registry | 不做推荐、不编事实 | 工具失败、超时、空结果都有显式状态 |
| EvidenceCore | ToolResultSet / GoalPlan | EvidencePack | evidence schema、review rules | 不做 winner 选择 | EvidencePack 与工具结果一一可追踪 |
| DecisionCore | EvidencePack / CandidateSet | DecisionPlan | evidence、policy、ranking policy | 不直接调用工具 | 决策不依赖召回顺序 |
| ResponseCore | AnswerPlan / DecisionPlan / EvidencePack | final_response | verifier、verbalizer、style policy | 不改事实 | 回答经过 verifier 后才可出图 |
| StateCore | state diff / runtime events | StatePatch / trace spans | observability、session state | 不做业务判断 | 状态变更可被审计 |

### 统一约束

1. 每个 Core 必须有独立单测。
2. 每个 Core 必须支持纯函数式输入输出或近似纯函数式封装。
3. Core 只承担单一职责，不承接跨职责兜底。
4. 如果一个模块需要同时承担两类以上核心职责，优先拆分而不是继续加参数。

### 验收清单

- 输入输出 schema 已冻结并可被校验。
- 每个 Core 都有最小可运行样例。
- 每个 Core 都能在不依赖 LangGraph 的前提下单测。
- `ResponseCore` 和 `DecisionCore` 的边界清晰，不互相越权。
- `DecisionCore` 不依赖 `search_shops` 召回顺序。
- `CandidateCore` 在无历史候选时不会伪造序号解析。
- `EvidenceCore` 对关键缺失有明确失败信号。
- `StateCore` 的 patch 与 trace 可审计。
