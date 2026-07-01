# 12 Prompt / Policy / Logging Guidelines

## 目标

本文件定义 Prompt / Policy / Schema / Logging / Response / Verifier / Core 边界的最终横切规范。

它是规范，不是实现事实。它可以定义 future prompt / policy / logging / response diversity / workflow routing 规范，但不能把 `orchestration_router`、`workflow_runner`、5 条 workflow 写成当前已实现事实。

## 当前事实与阶段边界

### 当前事实

- 当前已经有多个 graph node、Review、Answer Verifier
- 当前日志和策略尚未完全统一
- 当前已有 `orchestration_router` 的 shadow 版本
- 当前已有 `workflow_runner`
- 当前已有 `workflow registry`
- 当前还没有启用真实多 workflow 主链路分流

### 近期改造

- Phase 0：先建立日志、trace、prompt structured output 的规范基线
- Phase 1：把当前单主链路中的 search / evidence / decision / response / state 边界收口
- Phase 2：Core 薄封装后，prompt / policy / logging 接入 Core 边界

### 最终目标

- 用 prompt + policy + schema + validator + registry 支撑二级路由和 workflow 分流
- 用 `response_mode + response_style + answer_plan + verifier` 支撑回答多样性和事实一致性
- 所有关键节点、Core、ToolCall、Review、Response、Verifier 都有结构化日志

### future work

- Phase 4 引入 `orchestration_router`
- Phase 5 引入 `workflow_runner` / workflow registry
- Phase 6-8 拆出各独立 workflow
- 仍然不做 RAG / 交易 / 订单 mutation

## 分工总原则

| 组件 | 主要责任 | 产物 | 约束 |
| --- | --- | --- | --- |
| Prompt | 语义判断、意图归类、约束抽取、证据需求判断、复杂兜底解释 | 结构化 JSON / Pydantic schema | 必须带 `reason / confidence / missing_fields`，不得判断真实商家事实，不得绕过 ToolCall |
| Policy | 路由规则、工具白名单、禁止范围、任务到 workflow 的映射约束 | policy table / registry / mapping | 优先表驱动，不要堆大量 `if / elif / else` |
| Code | schema 校验、policy 执行、fallback、异常处理 | validator / guard / fallback | 必须拒绝 forbidden tool / unknown tool，不能把业务规则硬编码成大分支 |
| ToolCall | 真实事实或候选召回 | ToolResult / candidate list | 不生成最终回答，不决定 winner，不输出推荐话术 |
| Validator | 校验 prompt 输出结构、枚举、confidence、missing_fields、next_action | validation result | 低置信度应进入 clarification / fallback |
| Core | `PlanningCore / CandidateCore / ExecutionCore / EvidenceCore / DecisionCore / ResponseCore / StateCore` | Core inputs/outputs | 各自只做自己的职责 |
| Verifier | 校验 final_response 是否和 `EvidencePack / DecisionPlan / AnswerPlan` 对齐 | verifier result | 拦截未授权事实、改变决策、遗漏 unknown、forbidden claim |

## 不要大量 if / else 堆叠

### 不推荐方式

不要在 `orchestration_router`、workflow runner、review 节点、response 节点里写成大量硬编码分支，例如：

```python
if task_type == "shop_status":
    ...
elif task_type == "shop_distance":
    ...
elif task_type == "recommendation":
    ...
```

### 推荐方式

优先采用：

1. policy table
2. registry / mapping
3. typed schema
4. prompt-driven classification
5. rule + LLM hybrid router
6. declarative workflow definition
7. configurable response style policy

示例：

```python
TASK_ROUTE_POLICY = {
    "shop_status": {
        "workflow": "deterministic_tool",
        "requires_target": "single_shop",
        "response_mode": "tool_answer",
    },
    "recommendation": {
        "workflow": "discovery_decision",
        "requires_target": "candidate_recall",
        "response_mode": "recommendation",
    },
    "comparison": {
        "workflow": "discovery_decision",
        "requires_target": "multi_shop",
        "response_mode": "comparison",
    },
}
```

## Prompt 输出 schema

以下 schema 是规范，不代表 Phase 1 全部新实现。

### top_intent_router prompt

输出：

```json
{
  "top_intent": "local_life | chat | capability | unsafe | out_of_scope | invalid",
  "confidence": 0.0,
  "reason": "",
  "should_enter_local_life": false,
  "requires_direct_response": false,
  "missing_fields": [],
  "safety_flags": []
}
```

要求：

- 只做一级粗路由
- 不判断具体 workflow
- 不调用工具
- 不生成最终回答

### semantic_frame prompt

输出：

```json
{
  "task_type": "shop_search | recommendation | comparison | condition_refine | shop_status | shop_distance | shop_price | shop_coupon | shop_review_summary | shop_scene_fit | local_trip_plan | date_plan | family_activity_plan | coffee_then_dinner | eat_and_play_plan | unknown | ambiguous",
  "goal_type": "search | recommendation | comparison | deterministic_query | exploration_planning | clarify",
  "target_category": "",
  "scene": "",
  "constraints": {
    "location": "",
    "distance": "",
    "price": "",
    "time": "",
    "rating": "",
    "coupon": "",
    "environment": "",
    "other": []
  },
  "references": {
    "has_reference": false,
    "reference_text": "",
    "reference_type": "current_shop | ordinal | named_shop | previous_list | none"
  },
  "comparison_targets": [],
  "subgoals": [],
  "has_temporal_sequence": false,
  "expected_output": "answer | list | recommendation | comparison | itinerary | clarification",
  "requires_tool": true,
  "requires_clarification": false,
  "missing_fields": [],
  "confidence": 0.0,
  "reason": ""
}
```

要求：

- “推荐一家适合约会的日料”是 recommendation，不是 date_plan
- “晚上约会，先吃饭再散步”是 date_plan / exploration_planning
- “第二家离我多远”是 deterministic_query，但后续必须依赖 `ReferenceResolutionResult`
- 低 confidence 必须进入 clarification / fallback

### reference_resolution prompt

输出：

```json
{
  "resolved": false,
  "reference_type": "current_shop | ordinal | named_shop | comparison_ordinals | previous_list | none",
  "reference_text": "",
  "resolved_targets": [],
  "current_shop_candidate": null,
  "comparison_targets": [],
  "requires_clarification": false,
  "clarification_question": "",
  "confidence": 0.0,
  "reason": "",
  "source": "current_shop | last_answer_order | named_shop | fallback | none"
}
```

要求：

- “这家 / 它 / 刚才那家”优先 current_shop
- “第一家 / 第二家 / 第三家”指向 last_answer_order
- “第一家和第三家哪个好”解析为 comparison_targets
- 没有 last_answer_order 时不能解析序号，必须澄清
- 不能默认选择第一家
- 用户给店名可标 named_shop，但不确认事实存在，后续必须工具验证

### orchestration_router prompt

输出：

```json
{
  "orchestration_pattern": "direct_response | deterministic_tool | discovery_decision | exploration_planning | clarification_fallback",
  "workflow_name": "direct_response | deterministic_tool | discovery_decision | exploration_planning | clarification_fallback",
  "workflow_reason": "",
  "task_complexity": "low | medium | high",
  "requires_tool": false,
  "requires_clarification": false,
  "response_mode": "direct_response | tool_answer | search_list | recommendation | comparison | refinement | clarify | fallback | exploration_plan",
  "confidence": 0.0,
  "missing_fields": [],
  "next_action": "run_workflow | clarify | fallback"
}
```

要求：

- 这是 Phase 4 规范，不是当前实现事实
- 推荐 / 搜索 / 对比 / 筛选默认 discovery_decision
- 单店事实查询只有在 target 明确时才 deterministic_tool
- 多子目标规划进入 exploration_planning
- 指代失败、低 confidence、missing_fields 进入 clarification_fallback
- 不支持 RAG / 交易，不路由到不存在的 policy_rag / transaction workflow

### goal_planner prompt

输出：

```json
{
  "goal_type": "search | recommendation | comparison | condition_refine",
  "target_category": "",
  "scene": "",
  "constraints": {},
  "required_facets": [],
  "optional_facets": [],
  "candidate_source": "new_search | previous_list | resolved_targets",
  "evidence_needs": [],
  "ranking_policy_hint": {
    "hard_filters": [],
    "soft_preferences": []
  },
  "requires_clarification": false,
  "missing_fields": [],
  "confidence": 0.0,
  "reason": ""
}
```

要求：

- “附近 / 别太远”必须把 distance / eta 作为 required facet
- “别太贵”必须把 price 作为 required facet
- “适合约会 / 带娃 / 聚餐”必须把 scene_fit / review_summary / environment_tags 作为 required facet
- 缺位置或候选对象时必须 missing_fields，不能编造

### evidence_review prompt

输出：

```json
{
  "passed": false,
  "review_type": "evidence_review",
  "confidence": 0.0,
  "missing_fields": [],
  "weak_fields": [],
  "conflicts": [],
  "next_action": "continue | clarify | expand_search | supplement_evidence | fallback",
  "reason": ""
}
```

要求：

- 推荐至少要覆盖候选基础信息、距离 / ETA、价格 / 预算、营业状态、场景相关证据
- 对比双方必须有可比字段
- 用户明确约束必须被证据覆盖
- 缺关键字段不能形式化通过

### decision_planner prompt

输出：

```json
{
  "decision_type": "search_result | recommendation | comparison | attribute_answer | refine_result",
  "selected_targets": [],
  "overall_ranking": [],
  "winner_shop_id": null,
  "rationale_points": [],
  "rejected_candidates": [],
  "unknowns": [],
  "claim_bindings": [],
  "confidence": 0.0,
  "next_action": "answer | clarify | fallback | supplement_evidence",
  "reason": ""
}
```

要求：

- 只能用 `EvidencePack` 事实
- 推荐必须综合用户约束，不按搜索顺序
- “附近 / 别太远”距离 / ETA 是硬约束或强权重
- “别太贵”价格是强约束或强权重
- 明显过远、超预算、未营业、类目不匹配不应无理由首推
- `rejected_candidates` 必须说明淘汰原因
- `claim_bindings` 必须绑定 evidence item
- 只输出结构化决策，不生成最终自然语言

### answer_plan prompt

输出：

```json
{
  "response_mode": "direct_response | tool_answer | search_list | recommendation | comparison | refinement | clarify | fallback | exploration_plan",
  "response_style": "concise | friendly | analytical | scenario_based | comparison_first | recommendation_first | bullet_light | natural_chat",
  "tone": "",
  "opening_strategy": "",
  "candidate_presentation_style": "",
  "reasoning_style": "",
  "closing_strategy": "",
  "allowed_claims": [],
  "forbidden_claims": [],
  "must_mention_unknowns": [],
  "final_answer_constraints": []
}
```

要求：

- `AnswerPlan` 控制表达结构
- 不能改变 `DecisionPlan` 选择
- 不能新增 `EvidencePack` 外事实
- 如有 unknown / missing_fields 必须规划如何提及

### answer_generate prompt

要求：

- 只能基于 `AnswerPlan / DecisionPlan / EvidencePack`
- 禁止新增未在 `EvidencePack` 出现的事实
- 禁止改变 `DecisionPlan` 推荐 / 排序 / winner
- 禁止编造距离、价格、评分、营业、优惠、评价
- 禁止说已下单 / 预约 / 退款 / 支付
- 禁止 RAG / 政策解释
- 允许自然、多样表达，但事实一致

### answer_verifier prompt

输出：

```json
{
  "passed": false,
  "verifier_type": "answer_verifier",
  "unsupported_claims": [],
  "changed_decision": false,
  "missing_required_mentions": [],
  "forbidden_claims_found": [],
  "rewrite_required": false,
  "reason": ""
}
```

要求：

- 检查是否出现 `EvidencePack` 没有的事实
- 检查是否改变 `DecisionPlan` 选择
- 检查是否编造距离 / 价格 / 优惠 / 评分 / 营业 / 评价
- 检查是否遗漏 unknown / missing_fields
- 检查是否出现下单 / 退款 / 支付 / 预约承诺

## Policy / Registry 规范

### 路由策略

- `task_type -> orchestration_pattern / workflow_name / response_mode`
- Phase 4 后启用

### 工具策略

- `tool_name -> allowed / forbidden / future / existing`
- `ToolPlan` 只能引用 existing allowed tool
- forbidden tool 必须拒绝
- future tool 不能进入 current ToolPlan

### Response 策略

- `response_mode -> allowed response_style`
- `response_mode -> required fields`
- `forbidden_claims` 必须传给 verifier

### Workflow Registry

- Phase 5 后启用
- `workflow_name -> workflow class / callable`
- `workflow_runner` 只根据 registry 调度，不做业务决策
- 当前 registry 以合法 workflow 名称白名单方式收口

### 示例

```python
TASK_ROUTE_POLICY = {
    "recommendation": {
        "workflow_name": "discovery_decision",
        "response_mode": "recommendation",
        "requires_tool": True,
        "requires_target": "candidate_recall",
    },
    "shop_status": {
        "workflow_name": "deterministic_tool",
        "response_mode": "tool_answer",
        "requires_tool": True,
        "requires_target": "single_shop",
    },
}
```

```python
TOOL_POLICY = {
    "search_shops": {"status": "existing", "allowed": True, "role": "recall"},
    "rank_shops": {"status": "future", "allowed": False, "role": "candidate_processing"},
    "payment_tool": {"status": "forbidden", "allowed": False, "role": "transaction"},
}
```

### 约束

- 可以有少量 guard 判断
- 不能把全部业务策略写成大段 `if / elif`
- 新增 task_type 优先改 policy / schema / prompt / 测试

## 日志规范

### 节点 / Core 日志字段

- `timestamp`
- `session_id`
- `turn_id`
- `node_name`
- `core_name`
- `workflow_name`
- `orchestration_pattern`
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
- `weak_fields`
- `conflicts`
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
- `unsupported_claims_count`
- `changed_decision`

### 日志路径

- `var\\python_service.log`

### 敏感信息禁止记录

- 手机号
- token
- 支付信息
- 完整敏感地址
- 完整用户隐私明文

### 约束

- 日志记录摘要，不记录敏感明文
- Phase 0 必须先建立 trace / logging baseline
- 每个关键节点、Core、ToolCall、Review、Response、Verifier 都应能定位
- 失败场景必须能看出是路由、计划、工具、证据、决策还是回答问题

## Response 多样性规范

- `response_mode` 控制回答类型
- `response_style` 控制表达风格
- `answer_plan` 控制内容结构
- `verbalizer prompt` 控制自然语言多样性
- `verifier` 控制事实不漂移

### 必须明确

- 同一 `response_mode` 下允许多种 `response_style`
- `response_style` 不能改变 `DecisionPlan`
- `response_style` 不能新增 `EvidencePack` 外事实
- `ResponseCore` 不能重新选店
- `ResponseCore` 不能绕过 `EvidencePack` 读 `tool_result_set` 编事实
- 为了多样性生成的表达仍必须通过 `AnswerVerifier`

## Core 模块边界

### PlanningCore

- 不读 DB
- 不调用工具
- 不选择最终 winner
- 不生成最终自然语言

### CandidateCore

- 不最终推荐排序
- 不默认选择第一家
- 无历史候选时不能解析“第二家”
- 不生成最终回答

### ExecutionCore

- 不做推荐决策
- 不生成回答
- 不编造工具结果
- 不执行 forbidden / unknown tool

### EvidenceCore

- 不最终排序
- 不选择 winner
- 不生成最终回答
- 不把 search rank 固化为最终排序

### DecisionCore

- 不调用工具
- 不读 DB
- 不生成最终自然语言
- 不盲目依赖 search rank

### ResponseCore

- 不改变 `DecisionCore` 的选择结果
- 不绕过 `EvidencePack` 编事实
- 不直接读取 `tool_result_set` 做事实推断
- 不承诺下单、退款、支付、预约

### StateCore

- 不做业务决策
- 不生成回答
- 不修改事实结果
- 不持久化敏感隐私明文

## Forbidden 范围

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

### 约束

- 这些不能进入 prompt 可执行路径
- 不能进入 policy allowed 项
- 不能进入 ToolPlan
- 不能进入 workflow registry
- 不能通过 mock 或 fallback hidden path 偷渡

## 测试与验收

### Prompt 输出测试

- 每个 prompt 输出符合 schema
- `reason / confidence / missing_fields` 必填
- 低 confidence 进入 clarification / fallback
- prompt 不输出真实商家事实

### Policy 测试

- 新增 task_type 可通过 policy table 映射
- unknown task_type 进入 fallback
- forbidden tool 被拒绝
- future tool 不能进入 current ToolPlan

### Logging 测试

- 每个关键节点有结构化日志
- 日志写入 `var\\python_service.log`
- 失败场景能定位 node / core / tool / review / verifier
- 日志不记录敏感明文

### Response 测试

- 同一 `response_mode` 下不同 `response_style` 表达不同
- `response_style` 不改变 `DecisionPlan`
- `ResponseCore` 不编造 `EvidencePack` 外事实
- `AnswerVerifier` 能拦截 `unsupported_claims`

### Core 边界测试

- `PlanningCore` 不调工具
- `ExecutionCore` 不决策
- `EvidenceCore` 不选 winner
- `DecisionCore` 不调工具
- `ResponseCore` 不改决策
- `StateCore` 不做业务决策

## 当前事实、近期改造、最终目标

### 当前事实

- 当前代码里很多节点已经存在，但日志和策略并不统一
- 当前已经有 workflow registry 和 workflow runner 的基础落地

### 近期改造

- 先写规范，再落实现有节点日志和 schema

### 最终目标

- prompt / policy / logging / response diversity / module boundary 五件事一起收口

## 可执行建议

1. 先把规范文档写全，再推进代码落地
2. routing / review / response 不要靠大段分支硬拼
3. 所有节点日志统一落 `var\\python_service.log`

## 可执行版补充

### Prompt / Policy / Logging 对照表

| 领域 | 责任 | 产物 | 约束 | 验收 |
| --- | --- | --- | --- | --- |
| Prompt | 语义判断、归类、约束抽取 | JSON / schema 输出 | 不得输出真实事实 | 输出可校验 |
| Policy | 决策和白名单 | policy table / registry | 不得写死大量 if/else | 新增任务可通过表驱动 |
| Logging | 状态和排障 | 结构化日志 | 不记录敏感信息 | 可按节点回溯 |
| Response | 事实表达 | `response_mode` / `response_style` | 不得越过 verifier | 同 mode 多样化 |

### 节点日志最小集

| 字段 | 含义 | 必填 |
| --- | --- | --- |
| `timestamp` | 发生时间 | 是 |
| `session_id` | 会话标识 | 是 |
| `turn_id` | 轮次标识 | 是 |
| `node_name` | 当前节点 | 是 |
| `workflow_name` | workflow 名 | 是 |
| `orchestration_pattern` | 路由模式 | 是 |
| `task_type` | 任务类型 | 是 |
| `goal_type` | 目标类型 | 是 |
| `input_summary` | 输入摘要 | 是 |
| `output_summary` | 输出摘要 | 是 |
| `state_keys_changed` | 状态变更键 | 是 |
| `latency_ms` | 延迟 | 是 |
| `status` | 成功/失败 | 是 |
| `error_code` | 错误码 | 否 |
| `error_message` | 错误信息 | 否 |
| `next_action` | 下一步 | 否 |

### Response 多样性验收

- 同一 `response_mode` 至少要支持两种不同表达策略
- `response_style` 只能改变表达，不得改变事实
- `AnswerVerifier` 必须能拦截未授权事实
- 回答模板不得固定到“一条公式走天下”

### 日志验收

- 每个关键节点都能在 `var\\python_service.log` 中定位
- 失败时必须能看出是路由、计划、工具、证据、决策还是回答问题
- 日志字段和 `05` 的 state 字段能对上
