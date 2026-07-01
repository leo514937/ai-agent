# 05 状态与 Schema 设计

## 目标

统一顶层路由、多轮状态、workflow 状态、证据状态、决策状态、回答状态，避免同一信息在多个地方重复表达。

本文件服务于 Phase 0 / Phase 1 的状态基线和 schema 边界，同时为后续 Core 薄封装、workflow 设计和二级路由预留字段。
其中 future workflow 字段只作为目标 schema 设计，不代表当前运行时事实。

## 状态分层

### 1. GraphState

- 单轮图执行中的临时状态
- 节点之间传递
- 不一定全部持久化

### 2. SessionState

- 多轮会话持久状态
- 保存 `current_shop`、`last_recommendation_list`、`last_answer_order`、`last_selected_shop_ids`、`active_constraints`、`pending_clarification` 等
- 由 `StateCore` 或 `state_update_plan` 汇总写回

### 3. RuntimeContext

- 本轮运行上下文
- 保存 `user_id`、`session_id`、`turn_id`、`location_status`、`tool_availability`、`request_meta` 等
- 不应把 `MOCK_LOCATION` 当真实位置默认注入

### 4. TraceLog / EventLog

- 结构化日志和调试追踪
- 写入 `var\python_service.log`
- 保存摘要，不保存敏感明文

### 5. Core Schema

- `GoalPlan`
- `EvidencePlan`
- `CandidateSet`
- `ReferenceResolutionResult`
- `ToolResultSet`
- `EvidencePack`
- `DecisionPlan`
- `AnswerPlan`
- `VerifierResult`
- `StatePatch`

## 字段阶段标记

阶段枚举：

- `current`：当前已有或当前链路已使用
- `phase1`：Phase 1 必须补齐或收口
- `phase2`：Core 薄封装时稳定
- `phase4_plus`：二级路由 / workflow 分流后启用
- `future`：更后续目标

## 字段总表

| 字段 | 类型 | 所属状态层 | 阶段 | 来源 / 写入者 | 读取者 | 生命周期 | 是否持久化 | 是否可为空 | 语义 | 禁止误用 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `top_intent` | enum | GraphState | current | `top_intent_router` | 当前主链路 gate / future `orchestration_router` | 单轮 | 通常否 | 否 | 一级粗路由意图 | 不能表示 workflow |
| `task_type` | enum | GraphState / SessionState | current | semantic parse / planner | planner / core / review | 单轮+可回写 | 视情况 | 否 | 当前任务类型 | 不能等同 `top_intent` |
| `goal_type` | enum | GraphState / Core Schema | current | planner / prompt | planner / response / review | 单轮 | 否 | 否 | 细粒度任务类型 | 不能等同 `top_intent` |
| `current_shop` | dict | SessionState | current | CandidateCore / ResponseCore / StateCore | CandidateCore / ReferenceResolution | 多轮 | 是 | 是 | 当前目标店 | 不能当最终排名 |
| `last_recommendation_list` | list[dict] | SessionState | current | DecisionCore / ResponseCore | CandidateCore / ReferenceResolution / trace | 多轮 | 是 | 是 | 上轮推荐结果 | 不能等同最终排序 |
| `last_answer_order` | list[str] | SessionState | phase1 | ResponseCore / StateCore | CandidateCore / ReferenceResolution | 多轮 | 是 | 是 | 上轮展示顺序 | 不能等同 `last_recommendation_list` |
| `last_selected_shop_ids` | list[str] | SessionState | phase1 | DecisionCore / StateCore | CandidateCore / ReferenceResolution | 多轮 | 是 | 是 | 上轮真正选中的店 | 不能和展示顺序混用 |
| `last_evidence_pack` | dict | SessionState | phase1 | EvidenceCore / StateCore | ResponseCore / trace replay | 多轮 | 是 | 是 | 上轮证据快照 | 不能直接当最终回答 |
| `comparison_targets` | list[dict] | SessionState / GraphState | current / phase1 | CandidateCore | DecisionCore / EvidenceCore / trace | 单轮+可回写 | 是 | 是 | 对比目标集合 | 不能默认补齐隐含目标 |
| `active_constraints` | dict | SessionState / GraphState | current / phase1 | planner / CandidateCore | PlanningCore / DecisionCore | 多轮 | 是 | 是 | 当前约束集合 | 不能被 response 随意改写 |
| `pending_clarification` | dict | SessionState / GraphState | current | review / fallback | intake / CandidateCore / response | 多轮 | 是 | 是 | 待澄清内容 | 不能表示已确认事实 |
| `orchestration_decision` | dict / model | GraphState | phase4_plus | `orchestration_router`（shadow mode） | trace / log / debug | 单轮 | 否 | 是 | 二级路由影子决策包 | 不能进入 SessionState，不能直接调度 workflow |
| `orchestration_pattern` | enum | GraphState | phase4_plus | `orchestration_router` | `workflow_runner` / trace | 单轮 | 否/trace 可记 | 是 | workflow 分类 | 不能作为当前 Phase 1 路由事实 |
| `workflow_name` | string | GraphState | phase4_plus | `orchestration_router` | `workflow_runner` / trace | 单轮 | 否/trace 可记 | 是 | 具体 workflow 名 | 不能等同 `task_type` |
| `workflow_reason` | string | GraphState | phase4_plus | `orchestration_router` | `workflow_runner` / trace | 单轮 | 否/trace 可记 | 是 | 选择原因 | 不能替代事实判断 |
| `task_complexity` | enum | GraphState | phase4_plus | `orchestration_router` | `workflow_runner` / review | 单轮 | 否/trace 可记 | 是 | 任务复杂度 | 不能决定最终事实 |
| `requires_tool` | bool | GraphState | phase4_plus | router / planner | workflow runner / review | 单轮 | 否/trace 可记 | 否 | 是否需要工具 | 不能表示工具已成功 |
| `requires_clarification` | bool | GraphState | current / phase4_plus | review / router | fallback / workflow runner | 单轮 | 否/trace 可记 | 否 | 是否需要澄清 | 不能表示最终失败 |
| `workflow_run_status` | string | GraphState | phase4_plus | `workflow_runner` | trace / log / route | 单轮 | 否/trace 可记 | 是 | workflow 调度结果状态 | 不能等同业务结果 |
| `workflow_runner_error` | string | GraphState | phase4_plus | `workflow_runner` | trace / log | 单轮 | 否/trace 可记 | 是 | runner 错误码 | 不能覆盖原始路由事实 |
| `workflow_runner_reason` | string | GraphState | phase4_plus | `workflow_runner` | trace / log | 单轮 | 否/trace 可记 | 是 | runner 调度说明 | 不能替代 orchestration reason |
| `workflow_started_at` | string | GraphState | phase4_plus | `workflow_runner` | trace / log | 单轮 | 否/trace 可记 | 是 | runner 开始时间 | 仅用于观测 |
| `workflow_finished_at` | string | GraphState | phase4_plus | `workflow_runner` | trace / log | 单轮 | 否/trace 可记 | 是 | runner 结束时间 | 仅用于观测 |
| `workflow_registered` | bool | GraphState | phase4_plus | `workflow_runner` | trace / log | 单轮 | 否/trace 可记 | 否 | registry 命中标记 | 不能表示 workflow 完成 |
| `workflow_callable` | string | GraphState | phase4_plus | `workflow_runner` | trace / log | 单轮 | 否/trace 可记 | 是 | registry 命中的 callable 名 | 不能表示业务能力完整 |
| `response_mode` | enum | GraphState / Core Schema | current / phase1 | planner / response | ResponseCore / verifier | 单轮 | 否/trace 可记 | 否 | 回答模式 | 不能等同 workflow |
| `response_style` | enum | AnswerPlan / SessionState | phase1 | ResponseCore / planner | ResponseCore / trace | 单轮+可回写 | 可选 | 是 | 表达风格 | 只影响表达，不改变事实 |
| `tool_result_set` | dict | GraphState | current | ExecutionCore | EvidenceCore / trace / debug | 单轮 | 否/trace 可记 | 是 | 工具结果集合 | 不能直接用于最终回答 |
| `evidence_pack` | dict | GraphState / Core Schema | current | EvidenceCore | DecisionCore / ResponseCore / verifier | 单轮 | 否/trace 可记 | 是 | 证据集合 | 不能选择 winner |
| `decision_plan` | dict | GraphState / Core Schema | current | DecisionCore | ResponseCore / verifier | 单轮 | 否/trace 可记 | 是 | 结构化决策 | 不能生成自然语言 |
| `answer_plan` | dict | GraphState / Core Schema | current / phase1 | ResponseCore | ResponseCore / verifier | 单轮 | 否/trace 可记 | 是 | 回答计划 | 不能新增事实 |
| `final_response` | string | GraphState | current | ResponseCore | API / trace / session write | 单轮 | 是 | 是 | 最终回答 | 不能跳过 verifier |

## 字段职责边界

### `top_intent`

- 所属状态层：GraphState
- 阶段：current
- 来源：`top_intent_router`
- 读取者：当前主链路 gate / future `orchestration_router`
- 生命周期：单轮，可写入 trace
- 是否持久化：通常否
- 禁止误用：不能表示 workflow

### `orchestration_pattern`

- 所属状态层：GraphState
- 阶段：phase4_plus
- 来源：`orchestration_router`
- 读取者：`workflow_runner`
- 生命周期：单轮
- 是否持久化：trace 可记录
- 禁止误用：不能作为当前 Phase 1 路由事实

### `orchestration_decision`

- 所属状态层：GraphState
- 阶段：phase4_plus
- 来源：`orchestration_router` 的影子输出
- 读取者：trace / log / debug
- 生命周期：单轮
- 是否持久化：否，且不进入 SessionState
- 禁止误用：不能替代 `decision_plan`，也不能根据 `workflow_name` 直接调度真实 workflow

### `workflow_run_status`

- 所属状态层：GraphState
- 阶段：phase4_plus
- 来源：`workflow_runner`
- 读取者：trace / log / conditional route
- 生命周期：单轮
- 是否持久化：否，且不进入 SessionState
- 禁止误用：不能表示业务完成，也不能替代 `workflow_name`

### `last_answer_order`

- 所属状态层：SessionState
- 阶段：phase1
- 来源：ResponseCore / StateCore
- 读取者：CandidateCore / ReferenceResolution
- 生命周期：多轮
- 是否持久化：是
- 禁止误用：不能和 `last_recommendation_list` 混用；它表示展示顺序，不表示综合排名

### `last_recommendation_list`

- 所属状态层：SessionState
- 阶段：current
- 来源：DecisionCore / EvidenceCore
- 读取者：CandidateCore / ResponseCore / trace
- 生命周期：多轮
- 是否持久化：是
- 禁止误用：不能等同最终推荐排名

### `response_style`

- 所属状态层：AnswerPlan / SessionState
- 阶段：phase1
- 来源：ResponseCore / planner
- 读取者：ResponseCore / trace
- 生命周期：单轮为主，可回写偏好
- 是否持久化：可选
- 禁止误用：只能影响表达方式，不改变事实和决策

## 核心 schema

### 1. ReferenceResolutionResult

建议字段：

- `resolved`
- `reference_type`
- `reference_text`
- `resolved_targets`
- `current_shop_candidate`
- `comparison_targets`
- `requires_clarification`
- `clarification_question`
- `confidence`
- `reason`
- `source`

约束：

- 无历史候选时不能解析“第二家”
- 不能默认选择第一家
- `source` 用于记录解析来自 `current_shop` / `last_answer_order` / `named_shop` / `fallback`

### 2. CandidateSet

建议字段：

- `candidates`
- `candidate_source`
- `raw_order`
- `recall_rank`
- `display_order`
- `current_shop`
- `comparison_targets`
- `missing_targets`

约束：

- `raw_order` / `recall_rank` 不能等同最终排名
- `display_order` 是展示顺序，不等于综合推荐顺序

### 3. ToolResultSet

建议字段：

- `tool_results`
- `failed_tools`
- `partial_success`
- `empty_results`
- `latency`
- `tool_args_summary`
- `tool_status`

约束：

- 不能直接用于最终回答
- 必须先进入 `EvidencePack`

### 4. EvidencePack

建议字段：

- `evidence_items`
- `shop_facts`
- `distance_facts`
- `price_facts`
- `coupon_facts`
- `review_facts`
- `open_status_facts`
- `scene_fit_facts`
- `missing_fields`
- `unknowns`
- `failed_tools`
- `claim_sources`
- `evidence_quality`

约束：

- `EvidencePack` 是事实依据
- `EvidencePack` 不选择 winner
- `EvidencePack` 不生成最终自然语言

### 5. DecisionPlan

建议字段：

- `decision_type`
- `selected_targets`
- `overall_ranking`
- `winner_shop_id`
- `rationale_points`
- `rejected_candidates`
- `unknowns`
- `claim_bindings`
- `confidence`
- `next_action`

约束：

- `DecisionPlan` 是最终推荐 / 对比 / 单店判断的结构化决策
- `DecisionPlan` 不生成自然语言最终回答
- `DecisionPlan` 不调用工具
- `DecisionPlan` 必须能说明为什么没有选某些候选

### 6. AnswerPlan

建议字段：

- `response_mode`
- `response_style`
- `tone`
- `opening_strategy`
- `reasoning_style`
- `candidate_presentation_style`
- `closing_strategy`
- `must_mention_unknowns`
- `forbidden_claims`
- `allowed_claims`
- `final_answer_constraints`

约束：

- `AnswerPlan` 控制表达结构
- 不能改变 `DecisionPlan` 的选择结果
- 不能新增 `EvidencePack` 外事实

### 7. VerifierResult

建议字段：

- `passed`
- `unsupported_claims`
- `changed_decision`
- `missing_required_mentions`
- `forbidden_claims_found`
- `rewrite_required`
- `reason`

约束：

- AnswerVerifier 必须检查最终回答是否和 `EvidencePack` / `DecisionPlan` / `AnswerPlan` 对齐
- 不通过时触发 rewrite 或 fallback

### 8. StatePatch

建议字段：

- `set_fields`
- `clear_fields`
- `append_events`
- `session_updates`
- `trace_updates`
- `state_keys_changed`
- `reason`

约束：

- 状态更新要通过 `StatePatch` 表达
- `StateCore` 不做业务决策
- `StatePatch` 不持久化敏感隐私明文

## MOCK_LOCATION / location schema

### location_status

- `provided`
- `missing`
- `approximate`
- `test_mock`
- `unavailable`

### 位置相关字段

- `user_location`
- `location_status`
- `location_source`
- `requires_location`
- `location_missing_reason`

### 约束

- `MOCK_LOCATION` 只能作为 `test_mock` 或测试上下文
- 主链路运行时不能把 `MOCK_LOCATION` 当作真实 `provided` 位置
- 如果 `location_status = missing`，推荐“附近”类任务必须进入澄清、降级或无位置召回并明确说明

## 日志 schema

### 通用结构化日志字段

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
- `error_code`
- `error_message`
- `next_action`
- `confidence`

### ToolCall 日志字段

- `tool_name`
- `tool_args_summary`
- `tool_status`
- `tool_latency_ms`
- `result_count`
- `error_code`
- `error_message`

### Review 日志字段

- `review_type`
- `passed`
- `missing_fields`
- `confidence`
- `next_action`
- `reason`

### Response / Verifier 日志字段

- `response_mode`
- `response_style`
- `allowed_claim_count`
- `forbidden_claim_count`
- `verifier_passed`
- `rewrite_count`

### 日志路径

- `var\python_service.log`

### 禁止记录

- 手机号
- token
- 支付信息
- 完整敏感地址
- 完整用户隐私明文

## 字段语义约束

- `top_intent ≠ orchestration_pattern`
- `workflow_name ≠ task_type`
- `goal_type ≠ top_intent`
- `response_mode ≠ workflow_name`
- `response_style` 只影响表达方式，不改变事实和决策
- `last_answer_order ≠ last_recommendation_list`
- `raw_order / recall_rank ≠ final ranking`
- `tool_result_set ≠ evidence_pack`
- `evidence_pack ≠ decision_plan`
- `decision_plan ≠ answer_plan`
- `answer_plan ≠ final_response`

## 当前事实、近期改造、最终目标

### 当前事实

- `current_shop`、`last_recommendation_list`、`comparison_targets` 已存在于当前链路中
- `evidence_pack`、`decision_plan`、`answer_plan` 已在主链路使用
- `orchestration_pattern` / `workflow_name` / `workflow_run_status` 已进入 Phase 5 运行时事实
- `workflow_runner` 只做调度与观测，不负责业务判断

### 近期改造

- 补足 `last_evidence_pack`、`last_answer_order`、`response_style` 等字段
- 让 schema 和 Core 边界一致
- 补齐 `SessionState`
- 补齐 Phase 5 workflow dispatch 字段，避免把调度状态误当业务状态

### 最终目标

- 用统一 schema 表达多轮状态和 workflow 状态
- 为 future workflow 分流保留必要字段

## 测试与验收要求

字段测试：

- 所有 phase1 字段都能构造、序列化、断言
- `last_answer_order` 能支撑“第二家”
- 无 `last_answer_order` 时不能解析“第二家”
- `response_style` 不改变 `decision_plan`
- `tool_result_set` 不能直接进入 `final_response`
- `EvidencePack` 缺关键字段时 evidence_review 不通过
- `DecisionPlan` 不依赖 `recall_rank` 作为唯一排序依据
- `location_status = missing` 时不能假装知道附近

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

这些不应进入当前状态字段和 schema 设计。
不要为交易 mutation、支付、退款、预约提交设计当前阶段 schema。

## 可执行建议

1. 先补状态字段，再补逻辑。
2. 路由字段和业务字段不要混写。
3. 回复多样性必须通过 `response_mode + response_style` 控制，而不是靠硬编码模板。
4. 先把 Phase 1 需要的字段补齐，再考虑 Phase 4+ 的 workflow 字段。

## 可执行版补充

### 字段总表

| 字段 | 类型 | 来源 | 语义 | 是否必填 | 备注 |
| --- | --- | --- | --- | --- | --- |
| `top_intent` | enum | 一级路由 | 是否进入本地生活主流程 | 是 | 只做粗路由 |
| `task_type` | enum | planner | 当前任务类型 | 是 | 不能等同 `top_intent` |
| `goal_type` | enum | planner | 当前任务目标类型 | 是 | 不能等同 `top_intent` |
| `orchestration_pattern` | enum | 二级路由 | workflow 分类 | 否 | `phase4_plus` |
| `workflow_name` | string | workflow router | 具体 workflow 名 | 否 | `phase4_plus` |
| `workflow_reason` | string | router / review | 选择原因 | 否 | 用于 trace |
| `task_complexity` | enum | router | 任务复杂度 | 否 | `phase4_plus` |
| `requires_tool` | bool | router / planner | 是否需要工具 | 否 | 影响执行分支 |
| `requires_clarification` | bool | review / fallback | 是否需要澄清 | 否 | 歧义场景 |
| `response_mode` | enum | response planner | 回答模式 | 是 | 影响回答骨架 |
| `response_style` | enum | response planner | 表达风格 | 否 | 只影响表达 |
| `current_shop` | dict | CandidateCore | 当前目标店 | 否 | 单店查询和指代解析使用 |
| `last_recommendation_list` | list[dict] | SessionState | 上轮推荐结果 | 否 | 多轮续问使用 |
| `last_answer_order` | list[str] | SessionState | 上轮回答顺序 | 否 | 用于回溯表达 |
| `last_evidence_pack` | dict | SessionState | 上轮证据包 | 否 | 用于 trace replay |
| `last_selected_shop_ids` | list[str] | SessionState | 上轮选中商家 | 否 | 多轮续问使用 |
| `comparison_targets` | list[dict] | CandidateCore | 对比目标集合 | 否 | 多店对比使用 |
| `active_constraints` | dict | planner | 当前约束 | 否 | 偏好、条件、排除项 |
| `pending_clarification` | dict | review / fallback | 待澄清内容 | 否 | 歧义场景 |
| `tool_result_set` | dict | ExecutionCore | 工具执行结果集合 | 否 | 不直接用于回答 |
| `evidence_pack` | dict | EvidenceCore | 证据集合 | 否 | 回答和决策依据 |
| `decision_plan` | dict | DecisionCore | 决策输出 | 否 | 推荐、对比、winner |
| `answer_plan` | dict | ResponseCore | 回答计划 | 否 | 控制表达与结构 |
| `final_response` | string | ResponseCore | 最终回答 | 否 | 出图前最后一步 |

### 统一约束

1. 所有 phase1 字段都必须能被构造和序列化。
2. 每个 Core 输入输出 schema 必须可被单测覆盖。
3. `DecisionCore` 不依赖 `search_shops` 召回顺序。
4. `CandidateCore` 在无历史候选时不会伪造序号解析。
5. `EvidenceCore` 对关键缺失有明确失败信号。
6. `StateCore` 的 patch 与 trace 可审计。
