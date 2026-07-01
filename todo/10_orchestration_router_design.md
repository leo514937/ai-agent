# 10 Orchestration Router 设计

## 目标

本文件定义二级路由 `orchestration_router` 的目标设计、输入输出 schema、路由规则、实现约束和引入时机。

它必须和前面文档保持一致：

- 当前真实主链路仍是单主链路
- 当前只有一级 `top_intent_router`
- 当前已有 `orchestration_router` 的 Phase 4 shadow 版本
- 当前已有 Phase 5 的 `workflow_runner` 与 `workflow registry`
- 当前主链路仍未切到真实多 workflow 分流
- 当前主链路仍可视为 `DiscoveryDecisionWorkflow` 的演进雏形

## 当前事实与引入时机

### 当前事实

- 当前只有 `top_intent_router`
- 当前已存在 `orchestration_router` 的 Phase 4 影子接入版本
- 当前已存在 `workflow_runner`
- 当前已存在 `workflow registry`
- 当前没有启用真实多 workflow 主链路分流
- 当前主链路只是 DiscoveryDecision 的演进雏形，不是正式 workflow 分流

### 引入时机

- Phase 4 才允许引入 `orchestration_router`
- Phase 5 才允许引入 `workflow_runner` 与 workflow registry
- Phase 6 之后才逐步拆 `DeterministicToolWorkflow` 等子 workflow

### 禁止写法

- 当前还没有真实多 workflow 主链路分流
- 当前还不能把 `workflow_name` 当成主链路事实来描述
- 当前还不能把 `orchestration_router` 的 shadow 决策当作最终执行事实

## 一级路由与二级路由边界

### `top_intent_router`

- 位置：`intake_guard_router` 内部
- 当前状态：当前已存在
- 输入：`raw_text` / `normalized_text`、basic validation result、hard guard result、minimal session context
- 输出：`top_intent`
- 职责：判断是否进入本地生活主流程；粗分 `chat / capability / local_life / unsafe / out_of_scope / invalid`
- 禁止：判断具体 workflow、调用工具、做多轮指代解析、做候选推荐、生成最终推荐答案

### `orchestration_router`

- 位置：`understanding_subgraph` 之后
- 当前状态：已实现 shadow mode 版本，Phase 4 继续完善
- 输入：`top_intent`、`semantic_frame`、`task_type`、`goal_type`、`slots`、`ReferenceResolutionResult`、`current_shop`、`last_recommendation_list`、`last_answer_order`、`comparison_targets`、`active_constraints`、`pending_clarification`、`tool_availability`、`confidence`
- 输出：`orchestration_pattern`、`workflow_name`、`workflow_reason`、`task_complexity`、`requires_tool`、`requires_clarification`、`response_mode`、`confidence`、`missing_fields`、`next_action`
- 职责：只决定 workflow 分流的影子建议；判断是否需要澄清；给出结构化路由原因；低置信度进入 clarification_fallback 或 conservative path
- 禁止：调用工具、生成最终回答、生成自然语言推荐理由、做最终推荐排序、读取 DB、替代 Review / Verifier、直接调度真实 workflow

### 当前落地形态

- `orchestration_decision` 仅写入 `GraphState`
- `orchestration_decision` 不写入 `SessionState`
- `orchestration_router` 只做 shadow mode 记录，不改变现有 conditional edge
- `workflow_runner` 已存在，但当前仍以兼容当前链路为目标，不直接接管真实多 workflow 主链路
- `workflow_name` 在 shadow 路径里是建议与运行记录，不等于最终业务答案

## 为什么不能合并

`top_intent_router` 所在阶段还没有这些信息：

- `semantic_frame`
- `ReferenceResolutionResult`
- `current_shop`
- `last_recommendation_list`
- `last_answer_order`
- `comparison_targets`
- `active_constraints`

因此一级路由无法可靠判断：

- 单店确定性工具查询
- 推荐 / 搜索 / 对比
- 条件续问
- 多子目标探索规划
- 指代失败还是可解析

如果强行合并，会导致：

- 一级路由承担过多职责
- 过早依赖不完整上下文
- 后续 workflow 误判
- 代码里堆大量 `if / elif / else`

## OrchestrationDecision schema

`orchestration_router` 的结构化输出应满足以下 schema：

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

### 约束

- schema 必须可校验
- 低 confidence 不允许硬跑 discovery_decision
- `missing_fields` 非空时应进入 clarify / fallback / conservative path
- `next_action` 必须和 `workflow_name` 一致
- 不允许直接生成自然语言答案
- 当前实现必须是 shadow mode，不能根据 `workflow_name` 真实调度 workflow

## 路由规则

### direct_response

适用：

- `chat`
- `capability`
- `unsafe`
- `out_of_scope`
- `invalid`
- 能力边界说明
- 不支持 RAG / 交易 / 退款 / 下单 / 支付 / 预约 时的说明

进入条件：

- 不需要真实商家事实
- 不需要 ToolCall
- 不需要 EvidencePack

禁止：

- 不能编造商家信息
- 不能解释平台政策
- 不能执行交易

### deterministic_tool

适用：

- `shop_status`
- `shop_distance`
- `shop_price`
- `shop_coupon`
- `shop_review_summary`
- `shop_scene_fit`

进入条件：

- 必须有明确单店 target
- 必须有 `current_shop` 或 `ReferenceResolutionResult.resolved_targets`
- 必须能确认所需工具在 `tool_availability` / registry 中可用

禁止：

- 无历史候选时不能默认解析“第二家”
- 不能做多候选推荐
- 不能替代 `DecisionCore` 做综合推荐

### discovery_decision

适用：

- `shop_search`
- `recommendation`
- `comparison`
- `condition_refine`
- `scene_recommendation`
- `deal_compare`

进入条件：

- 需要候选发现、证据补全、综合决策
- 推荐、搜索、对比、筛选默认走 `discovery_decision`

关键约束：

- 推荐结果必须由 `DecisionCore` 基于 `EvidencePack` 综合决策
- 不能由 `search_shops` 返回顺序决定
- 不能由 `EvidenceCore` 选择 winner
- 不能由 `ResponseCore` 临时挑店

### exploration_planning

适用：

- `local_trip_plan`
- `date_plan`
- `family_activity_plan`
- `coffee_then_dinner`
- `eat_and_play_plan`

进入条件：

- 存在多个本地生活子目标
- 存在时间顺序、组合关系或 itinerary 输出需求

限制：

- 最多 3 个 subgoal
- 最多 2 轮工具扩展
- 禁止无限 replan
- 禁止开放式 `ReAct` loop
- 不下单、不预约、不交易

### clarification_fallback

适用：

- `unknown`
- `ambiguous`
- `reference_failed`
- `no_result`
- `tool_failure`
- `missing_required_slot`
- `low_confidence`

进入条件：

- 信息不足
- 指代失败
- 工具失败或结果为空
- confidence 低于阈值
- `missing_fields` 包含关键字段

职责：

- 输出澄清问题或可信失败
- 不硬跑下游链路
- 不编造事实

## 路由策略实现方式

### 不推荐方式

不要在 `orchestration_router` 里堆大量硬编码分支，例如：

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

示例：

```python
TASK_ROUTE_POLICY = {
    "shop_status": {
        "workflow_name": "deterministic_tool",
        "requires_target": "single_shop",
        "response_mode": "tool_answer",
        "required_fields": ["resolved_targets"],
    },
    "recommendation": {
        "workflow_name": "discovery_decision",
        "requires_target": "candidate_recall",
        "response_mode": "recommendation",
        "required_fields": ["semantic_frame"],
    },
    "comparison": {
        "workflow_name": "discovery_decision",
        "requires_target": "multi_shop",
        "response_mode": "comparison",
        "required_fields": ["comparison_targets"],
    },
}
```

路由流程建议：

```text
1. 读取 semantic_frame / task_type / reference result
2. 查询 TASK_ROUTE_POLICY
3. 校验 required_fields
4. 低 confidence 或 missing_fields 时转 clarification_fallback
5. 构造 OrchestrationDecision
6. 写结构化日志
```

### 约束

- 可以有少量 guard 判断，但不能把全部业务路由堆成大段 `if / elif / else`
- 路由必须可解释、可校验、可回放

## Prompt Engineering 适用点

`orchestration_router` 的复杂兜底判断应优先使用：

- prompt + structured output
- schema 校验
- policy table
- confidence / reason / missing_fields

### Prompt 职责

- 复杂语义下的 workflow 候选判断
- `task_type` 与 route policy 的辅助解释
- `reason / confidence / missing_fields` 输出

### Code 职责

- schema 校验
- policy 约束
- 工具白名单校验
- fallback
- 禁止范围拦截

### Prompt 禁止

- 编造商家事实
- 调用工具
- 生成最终回答
- 绕过 ToolCall 判断真实事实
- 把 RAG / 交易任务路由到可执行链路

### 约束

- prompt 输出必须结构化
- prompt 输出必须带 `reason / confidence / missing_fields`
- prompt 输出必须经过 validator
- 低 confidence 必须进入 `clarification_fallback` 或 conservative path

## 日志和测试要求

### 日志字段

- `timestamp`
- `session_id`
- `turn_id`
- `node_name`
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

### 日志路径

- `var\\python_service.log`

### 测试必须覆盖

- `top_intent_router` 不做 workflow 分流
- `orchestration_router` 当前未实现，Phase 4 前不应出现在当前主链路
- `orchestration_router` 不调用工具
- `orchestration_router` 不生成最终回答
- 推荐 / 搜索 / 对比 / 筛选路由到 `discovery_decision`
- 明确单店 target 的事实查询路由到 `deterministic_tool`
- 无 target 的单店查询进入 `clarification_fallback`
- 多子目标组合请求路由到 `exploration_planning`
- `reference_failed` / `low_confidence` / `missing_fields` 进入 `clarification_fallback`
- RAG / 政策问答 / 交易 / 订单 mutation 不进入可执行 workflow

## 与 workflow_runner 的边界

- `orchestration_router` 只产出 `OrchestrationDecision`
- `workflow_runner` 负责根据 `workflow_name` 调用具体 workflow
- `workflow_runner` 是 Phase 5，不是 Phase 4

### 禁止

- `orchestration_router` 直接实例化 workflow
- `orchestration_router` 直接执行 workflow
- `orchestration_router` 直接调用工具
- `orchestration_router` 直接生成最终回答

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

### 约束

- 这些不能被 `orchestration_router` 路由到可执行 workflow
- 如果用户请求这些能力，应进入 `direct_response` 的能力边界说明或 `clarification_fallback` / `out_of_scope` 可信失败

## 当前事实、近期改造、最终目标

### 当前事实

- 当前已有 `orchestration_router` shadow 路径
- 当前已有 `workflow_runner` 与 `workflow registry`
- 当前主链路仍是 DiscoveryDecision 的演进雏形

### 近期改造

- 先把 policy table、schema、prompt 输出约束写清楚

### 最终目标

- `orchestration_router` 基于结构化输出和 policy 做 workflow 分流

## 可执行建议

1. 先把 `orchestration_router` 设计写死，再等 Phase 4 实装
2. 不要让一级路由承担二级 workflow 判断
3. 不要把局部 review gate 升格成系统级路由
4. Phase 5 的 `workflow_runner` 要单独设计，不要和这里混写

## 可执行版补充

### 输入特征表

| 特征 | 来源 | 用途 | 是否可缺失 |
| --- | --- | --- | --- |
| `top_intent` | 一级路由 | 决定是否进入本地生活主流程 | 否 |
| `semantic_frame` | 语义解析 | 判断任务类型和约束 | 否 |
| `context_recovery` | 多轮状态 | 指代解析和续问 | 是 |
| `current_shop` | CandidateCore | 单店任务识别 | 是 |
| `last_recommendation_list` | SessionState | 续问推荐 | 是 |
| `last_answer_order` | SessionState | 展示顺序回溯 | 是 |
| `comparison_targets` | CandidateCore | 多店对比 | 是 |
| `active_constraints` | planner | 任务约束 | 是 |
| `tool_availability` | registry | 判断是否可走确定性工具 | 是 |
| `confidence` | parser / planner | 决定是否降级 | 是 |

### 路由决策矩阵

| 条件组合 | pattern | workflow_name | response_mode | next_action |
| --- | --- | --- | --- | --- |
| 简单问答、无需工具 | `direct_response` | `direct_response` | `direct_response` | 直接回答 |
| 单店确定性事实 | `deterministic_tool` | `deterministic_tool` | `tool_answer` | 工具执行 |
| 搜索 / 推荐 / 对比 | `discovery_decision` | `discovery_decision` | `discovery_answer` | 规划 + 执行 + 决策 |
| 复杂规划 | `exploration_planning` | `exploration_planning` | `exploration_plan` | 规划 |
| 歧义 / 无结果 / 失败 | `clarification_fallback` | `clarification_fallback` | `clarify` | 澄清或降级 |

### 验收清单

- 输入特征表里的字段都能从现有 state 或 schema 找到来源
- 路由决策矩阵里的每个组合都能被测试覆盖
- `orchestration_router` 不得直接写自然语言答案
- 低 confidence 必须触发保守路径或澄清路径
