# 11 Workflow Pattern Mapping

## 目标

本文件定义 workflow 到 Core、状态、工具、阶段、测试的映射总表。

它必须和前面文档保持一致：

- 当前真实主链路仍是单主链路
- 当前只有一级 `top_intent_router`
- 当前已有 `orchestration_router` 的 shadow 版本
- 当前已有 `workflow_runner` 与 `workflow registry`
- 当前没有启用真实多 workflow 主链路分流
- 当前主链路仍只是 `DiscoveryDecisionWorkflow` 的演进雏形

## 当前事实与最终目标边界

### 当前事实

- 当前已经存在 workflow registry
- 当前已经存在 workflow runner
- 当前 registry 里已经挂上合法 workflow 名称与可调用适配器
- 当前主链路仍不是最终多 workflow 执行事实

### 最终目标

- 用 workflow pattern mapping 表驱动路由和执行
- 让 `workflow_runner` 在 Phase 5 后按 registry 调度 workflow

## Phase / 优先级映射

### 优先级口径

- P0：`DiscoveryDecisionWorkflow`，Phase 3 固化雏形，Phase 5 后正式注册
- P1：`DeterministicToolWorkflow`，Phase 6 后拆出
- P2：`DirectResponseWorkflow`，Phase 7 后拆出
- P3：`ClarificationFallbackWorkflow`，Phase 7 后拆出
- P4：`ExplorationPlanningWorkflow`，Phase 8 后实现

### 说明

- P0 不表示当前已经有正式 `DiscoveryDecisionWorkflow`
- P1 / P2 / P3 / P4 不表示当前已经有这些 workflow
- P0~P4 只是落地优先级
- 真正实现阶段以 Phase 0~9 为准

## workflow 总映射表

| workflow | 所属 Phase | 当前状态 | 典型 task_type | response_mode | 必需 Core | 可选 Core | 是否需要 ToolCall | 可用 existing tool | future tool 依赖 | 失败路径 | 关键验收 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `DirectResponseWorkflow` | Phase 7 后拆出 | 当前未作为独立 workflow 实现；当前 chat / capability 仍由当前主链路或入口分支处理 | `chat`、`capability` | `direct_response` | `ResponseCore`、`StateCore` | `PlanningCore` | 否 | 否 | 否 | 信息不足 -> `clarification_fallback` | 无工具也能稳定回答能力边界；能力外请求不进入 RAG / 交易链路 |
| `DeterministicToolWorkflow` | Phase 6 后拆出 | 当前未作为独立 workflow 实现；当前单店事实查询仍可能经过当前主链路处理 | `shop_status`、`shop_distance`、`shop_price`、`shop_coupon`、`shop_review_summary`、`shop_scene_fit` | `tool_answer` | `PlanningCore`、`CandidateCore`、`ExecutionCore`、`EvidenceCore`、`ResponseCore`、`StateCore` | 否 | 是 | `get_shop_detail`、`get_coupon_list`、`check_open_status`、`get_distance_eta`、`get_shop_review_summary` | `get_shop_status`、`get_shop_business_hours`、`get_shop_price_info`、`get_scene_fit_score` | target 不明确 / 工具失败 -> `clarification_fallback` | target 明确时可轻链路回答；target 不明确时必须澄清；工具失败不能胡编 |
| `DiscoveryDecisionWorkflow` | Phase 3 固化雏形，Phase 5 后正式注册 | 当前主链路是其演进雏形；当前还没有正式 `workflow_runner` 注册 | `shop_search`、`recommendation`、`comparison`、`condition_refine`、`scene_recommendation`、`deal_compare` | `recommendation`、`comparison`、`search_list`、`refinement` | `PlanningCore`、`CandidateCore`、`ExecutionCore`、`EvidenceCore`、`DecisionCore`、`ResponseCore`、`StateCore` | 否 | 通常需要 | `search_shops`、`resolve_shop`、`get_shop_detail`、`get_coupon_list`、`check_open_status`、`get_distance_eta`、`get_shop_cards`、`get_shop_review_summary`、`get_deal_list` | `search_pois`、`search_deals`、`calculate_value_score`、`get_scene_fit_score`、`rerank_candidates`、`filter_candidates` | 无结果 / 指代失败 / 证据不足 / 决策不足 -> `clarification_fallback` | 搜索 / 推荐 / 对比 / 条件筛选稳定回归；不依赖 recall rank 作为唯一排序依据；winner 必须由 DecisionCore 基于 EvidencePack 决定 |
| `ExplorationPlanningWorkflow` | Phase 8 后实现 | 最小独立 workflow 已落地；当前仍保持 Phase 8 边界，不扩展到共享 Core | `local_trip_plan`、`date_plan`、`family_activity_plan`、`coffee_then_dinner`、`eat_and_play_plan` | `exploration_plan` | `PlanningCore`、`CandidateCore`、`ExecutionCore`、`EvidenceCore`、`DecisionCore`、`ResponseCore`、`StateCore` | 否 | 通常需要 | 视场景可用 `search_shops`、`get_shop_detail`、`check_open_status`、`get_distance_eta`、`get_shop_review_summary` | `search_pois`、`search_business_areas`、`estimate_travel_time`、`calculate_distance` | 信息不足 / 无法形成 itinerary -> `clarification_fallback` | 能输出 itinerary / plan；不会编造真实商家事实；不会执行交易动作；不会无限扩展 |
| `ClarificationFallbackWorkflow` | Phase 7 后拆出 | 当前未作为独立 workflow 实现；Phase 1 可强化现有 clarification / review / fallback 行为，但不新增独立 workflow | `unknown`、`ambiguous`、`reference_failed`、`no_result`、`tool_failure`、`missing_required_slot`、`low_confidence`、`out_of_scope` | `clarify`、`fallback` | `ResponseCore`、`StateCore` | `PlanningCore`、`CandidateCore` | 通常不需要 | 否 | 否 | 无法澄清则输出安全降级 | 指代失败会澄清；工具失败会可信降级；能力外请求会说明边界；不会继续硬跑推荐链路 |

## 各 workflow 详细映射

### 1. DirectResponseWorkflow

#### 适用场景

- chat
- capability
- 能力边界说明
- 不支持 RAG / 交易 / 退款 / 下单 / 支付 / 预约 时的说明

#### 典型 task_type

- `chat`
- `capability`

#### 所属 Phase

- Phase 7 后拆出

#### 当前状态

- 当前未作为独立 workflow 实现
- 当前由 `workflow_registry` 占位注册，真实主链路仍走现有入口分支

#### 输入状态

- `top_intent`
- `semantic_frame`
- `response_mode`

#### 输出状态

- `workflow_name = direct_response`
- `response_mode = direct_response`
- `final_response`

#### 必需 Core

- `ResponseCore`
- `StateCore`

#### 可选 Core

- `PlanningCore`

#### 是否需要 ToolCall

- 否

#### 可用 existing tool

- 否

#### 可能依赖 future tool

- 否

#### 禁止能力

- 查真实商家事实
- 调用交易工具
- 编造商家信息
- 解释平台政策细则
- 执行 RAG / 政策检索

#### 执行步骤

1. 识别为直接回答
2. 可选做最小语义理解
3. 直接生成回答
4. 做基础 verifier

#### 失败路径

- 语义不足时进入 `clarification_fallback`

#### 关键验收

- 无工具也能回答能力边界
- 能力外请求不会进入 RAG / 交易链路

#### 测试阶段

- Phase 7 后

---

### 2. DeterministicToolWorkflow

#### 适用场景

- 店铺状态
- 距离
- 优惠券
- 营业时间
- 评价摘要

#### 典型 task_type

- `shop_status`
- `shop_distance`
- `shop_price`
- `shop_coupon`
- `shop_review_summary`
- `shop_scene_fit`

#### 所属 Phase

- Phase 6 后拆出

#### 当前状态

- 当前未作为独立 workflow 实现
- 当前 registry 中存在兼容适配器，用于承接 shadow 路径和当前链路事实

#### 输入状态

- `goal_type`
- `requires_tool`
- `current_shop`
- `ReferenceResolutionResult`
- `semantic_frame`

#### 输出状态

- `workflow_name = deterministic_tool`
- `tool_result_set`
- `evidence_pack`
- `answer_plan`
- `final_response`

#### 必需 Core

- `PlanningCore`
- `CandidateCore`
- `ExecutionCore`
- `EvidenceCore`
- `ResponseCore`
- `StateCore`

#### 可选 Core

- 否

#### 是否需要 ToolCall

- 是

#### 可用 existing tool

- `get_shop_detail`
- `get_coupon_list`
- `check_open_status`
- `get_distance_eta`
- `get_shop_review_summary`

#### 可能依赖 future tool

- `get_shop_status`
- `get_shop_business_hours`
- `get_shop_price_info`
- `get_scene_fit_score`

#### 禁止能力

- 多候选综合推荐
- 最终 winner 决策
- 交易 / 预约 / 支付 / 退款

#### 执行步骤

1. 解析确定性单店任务
2. 生成最小工具计划
3. 执行工具
4. 构建证据
5. 生成答案
6. verifier 校验

#### 失败路径

- target 不明确 -> `clarification_fallback`
- 工具失败 -> `clarification_fallback`

#### 关键验收

- target 明确时可以轻链路回答
- target 不明确时必须进入 `clarification_fallback`
- 工具失败必须形成 `failed_tools` / fallback，而不是胡编

#### 测试阶段

- Phase 6 后

---

### 3. DiscoveryDecisionWorkflow

#### 适用场景

- 搜索
- 推荐
- 多店对比
- 条件筛选
- 场景推荐
- 团购比较

#### 典型 task_type

- `shop_search`
- `recommendation`
- `comparison`
- `condition_refine`
- `scene_recommendation`
- `deal_compare`

#### 所属 Phase

- Phase 3 固化雏形
- Phase 5 后正式注册为 `discovery_decision`

#### 当前状态

- 当前主链路是它的演进雏形
- 当前已正式注册到 `workflow_registry`
- 当前可由 `workflow_runner` 调度到 registry handler

#### 输入状态

- `semantic_frame`
- `goal_type`
- `comparison_targets`
- `active_constraints`
- `last_recommendation_list`
- `current_shop`
- `ReferenceResolutionResult`

#### 输出状态

- `workflow_name = discovery_decision`
- `tool_result_set`
- `evidence_pack`
- `decision_plan`
- `answer_plan`
- `final_response`

#### 必需 Core

- `PlanningCore`
- `CandidateCore`
- `ExecutionCore`
- `EvidenceCore`
- `DecisionCore`
- `ResponseCore`
- `StateCore`

#### 可选 Core

- 否

#### 是否需要 ToolCall

- 通常需要

#### 可用 existing tool

- `search_shops`
- `resolve_shop`
- `get_shop_detail`
- `get_coupon_list`
- `check_open_status`
- `get_distance_eta`
- `get_shop_cards`
- `get_shop_review_summary`
- `get_deal_list`

#### 可能依赖 future tool

- `search_pois`
- `search_deals`
- `calculate_value_score`
- `get_scene_fit_score`
- `rerank_candidates`
- `filter_candidates`

#### 禁止能力

- future tool 不能写成当前事实
- `rank_shops` / `rerank_candidates` / `filter_candidates` 不能替代 `DecisionCore` 的最终决策职责
- RAG / 交易 / 订单 mutation 不能进入 workflow

#### 执行步骤

1. Controlled plan
2. 生成工具计划
3. 执行工具
4. 构建证据
5. Review 证据
6. 生成决策
7. Review 决策
8. 生成回答
9. verifier 校验

#### 失败路径

- 无结果 -> `clarification_fallback`
- 指代失败 -> `clarification_fallback`
- 证据不足 -> `clarification_fallback`
- 决策不足 -> `clarification_fallback`

#### 关键验收

- 搜索 / 推荐 / 对比 / 条件筛选稳定回归
- 推荐不依赖 `recall_rank` 作为唯一排序依据
- 明显过远、未营业、超预算、类目不匹配的店不能无理由首推
- `DecisionPlan` / `EvidencePack` / `AnswerPlan` 可追踪

#### 测试阶段

- Phase 3 雏形
- Phase 5 后正式注册

---

### 4. ExplorationPlanningWorkflow

#### 适用场景

- `local_trip_plan`
- `date_plan`
- `family_activity_plan`
- `coffee_then_dinner`
- `eat_and_play_plan`

#### 典型 task_type

- `local_trip_plan`
- `date_plan`
- `family_activity_plan`

#### 所属 Phase

- Phase 8 后实现

#### 当前状态

- 当前未作为独立 workflow 实现
- 当前 registry 中仅占位，不进入真实主链路

#### 输入状态

- `semantic_frame`
- `active_constraints`
- `pending_clarification`
- `task_complexity`

#### 输出状态

- `workflow_name = exploration_planning`
- `decision_plan`
- `answer_plan`
- `final_response`

#### 必需 Core

- `PlanningCore`
- `CandidateCore`
- `ExecutionCore`
- `EvidenceCore`
- `DecisionCore`
- `ResponseCore`
- `StateCore`

#### 可选 Core

- 否

#### 是否需要 ToolCall

- 通常需要

#### 可用 existing tool

- 视场景可用 `search_shops`
- 视场景可用 `get_shop_detail`
- 视场景可用 `check_open_status`
- 视场景可用 `get_distance_eta`
- 视场景可用 `get_shop_review_summary`

#### 可能依赖 future tool

- `search_pois`
- `search_business_areas`
- `estimate_travel_time`
- `calculate_distance`

#### 禁止能力

- 最多 3 个 subgoal 外继续扩张
- 无限 replan
- 开放式 `ReAct` loop
- 不下单、不预约、不交易

#### 执行步骤

1. 识别探索式规划意图
2. 解析约束与偏好
3. 生成探索计划
4. 必要时澄清
5. 输出规划建议

#### 失败路径

- 信息不足 -> `clarification_fallback`

#### 关键验收

- 能输出 itinerary / plan
- 不会编造真实商家事实
- 不会执行交易动作
- 不会无限扩展

#### 测试阶段

- Phase 8 后

---

### 5. ClarificationFallbackWorkflow

#### 适用场景

- `unknown`
- `ambiguous`
- `reference_failed`
- `no_result`
- `tool_failure`
- `missing_required_slot`
- `low_confidence`
- `out_of_scope`

#### 典型 task_type

- `unknown`
- `ambiguous`
- `reference_failed`

#### 所属 Phase

- Phase 7 后拆出

#### 当前状态

- 当前未作为独立 workflow 实现
- 当前 registry 中仅占位，不进入真实主链路

#### 输入状态

- `pending_clarification`
- `workflow_reason`
- `semantic_frame`
- `tool_result_set`

#### 输出状态

- `workflow_name = clarification_fallback`
- `response_mode = clarify`
- `final_response`

#### 必需 Core

- `ResponseCore`
- `StateCore`

#### 可选 Core

- `PlanningCore`
- `CandidateCore`

#### 是否需要 ToolCall

- 通常不需要

#### 可用 existing tool

- 否

#### 可能依赖 future tool

- 否

#### 禁止能力

- 硬跑下游链路
- 编造事实
- 把 forbidden 能力转成 hidden tool path
- 执行 RAG / 交易 / mutation

#### 执行步骤

1. 识别失败或歧义
2. 生成澄清问题或可信失败文案
3. 不输出未验证事实

#### 失败路径

- 若仍无法澄清，则输出安全降级

#### 关键验收

- 指代失败会澄清
- 工具失败会可信降级
- 能力外请求会说明边界
- 不会继续硬跑推荐链路

#### 测试阶段

- Phase 7 后

## 与 OrchestrationRouter 的关系

- `orchestration_router` 是 Phase 4
- `workflow_runner` / registry 是 Phase 5
- mapping 表主要服务 Phase 5 之后的 `workflow_runner` 注册与执行

### mapping 使用规则

1. `orchestration_router` 只产出 `OrchestrationDecision`
2. `workflow_runner` 根据 `workflow_name` 查 `WORKFLOW_REGISTRY`
3. workflow pattern mapping 决定每条 workflow 使用哪些 Core、状态和工具
4. `response_mode` 只决定回答形式，不能反向决定 workflow
5. `task_type` 需要通过 policy table 映射到 workflow，不能靠大段 `if / elif`

## ToolCall-only 与 forbidden 边界

- 所有 workflow 都必须遵守 ToolCall-only 本地生活非交易边界
- 任何 workflow 都不能调用 RAG、政策问答、交易、支付、退款、预约、订单 mutation
- future tool 不能写成 existing tool
- forbidden tool 不能通过 fallback hidden path 进入链路

## 测试映射

### DirectResponseWorkflow

- 能力说明
- 不支持 RAG / 交易说明
- 不调用工具

### DeterministicToolWorkflow

- target 明确时查营业 / 距离 / 券 / 评价摘要
- target 不明确时 `clarification_fallback`
- 工具失败不胡编

### DiscoveryDecisionWorkflow

- 推荐一家适合约会的日料，别太贵
- 附近有什么咖啡店
- 第一家和第三家哪个好
- 换个便宜点的
- 不依赖 search rank

### ExplorationPlanningWorkflow

- 下午先喝咖啡再吃饭
- 晚上约会先吃饭再散步
- 不超过 subgoal / replan 限制

### ClarificationFallbackWorkflow

- 无历史候选时“第二家”
- 指代不清
- 工具失败
- 无结果

### 说明

- 这些测试按 Phase 执行
- Phase 1 不要求后续独立 workflow 全部存在

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
- 自由 `ReAct` loop
- 开放式 `multi-agent handoff`

## 当前事实、近期改造、最终目标

### 当前事实

- 当前已经有 workflow registry 和 workflow runner
- 当前主链路仍只是 DiscoveryDecision 的演进雏形

### 近期改造

- 先把 mapping 表固定下来
- 再按 Phase 4 以后逐个 workflow 落地

### 最终目标

- 用 workflow pattern mapping 表驱动路由和执行

## 可执行建议

1. 先把这张 mapping 表固定下来
2. 再按 Phase 5 以后逐个 workflow 落地
3. 不要把 future tool 当成现有事实写进主链路文档
4. 如果某条 workflow 的 Core 组合继续膨胀，优先拆分而不是加参数

## 可执行版补充

### workflow 与 Core 的总映射

| workflow | 必需 Core | 可选 Core | 核心状态字段 | 关键验收 |
| --- | --- | --- | --- | --- |
| `DirectResponseWorkflow` | `ResponseCore`、`StateCore` | `PlanningCore` | `top_intent`、`workflow_name`、`response_mode` | 无工具也能稳定回答能力边界 |
| `DeterministicToolWorkflow` | `PlanningCore`、`CandidateCore`、`ExecutionCore`、`EvidenceCore`、`ResponseCore`、`StateCore` | - | `goal_type`、`tool_result_set`、`evidence_pack`、`answer_plan` | 单店事实可直接落地 |
| `DiscoveryDecisionWorkflow` | `PlanningCore`、`CandidateCore`、`ExecutionCore`、`EvidenceCore`、`DecisionCore`、`ResponseCore`、`StateCore` | - | `comparison_targets`、`decision_plan`、`last_recommendation_list` | 搜索 / 推荐 / 对比可回归 |
| `ExplorationPlanningWorkflow` | `PlanningCore`、`CandidateCore`、`ExecutionCore`、`EvidenceCore`、`DecisionCore`、`ResponseCore`、`StateCore` | - | `active_constraints`、`pending_clarification` | 复杂规划不胡编 |
| `ClarificationFallbackWorkflow` | `ResponseCore`、`StateCore` | `PlanningCore`、`CandidateCore` | `pending_clarification`、`workflow_reason` | 歧义和失败能收口 |

### mapping 规则

1. workflow 的选择先看 `orchestration_pattern`，再看 `workflow_name`
2. `response_mode` 只能跟回答形式相关，不能反向决定 workflow
3. `future tool` 只影响某些 workflow 的可用能力，不影响当前事实定义
4. 同一 workflow 内如果 Core 职责变多，优先拆分而不是继续加参数

### 验收清单

- 每条 workflow 都能对应到明确的 Core 组合
- 每条 workflow 都有清晰的输入状态和输出状态
- 每条 workflow 都有“是否依赖 future tool”的明确标记
- mapping 表和 `03/05/10/12` 的字段命名一致
