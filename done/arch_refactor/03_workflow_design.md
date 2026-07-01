# 03 工作流设计

## 目标

本文件定义最终 workflow 设计方向，但不代表当前阶段全部落地。
当前可开工范围仍以 Phase 1 为准，Phase 1 只做单主链路内部职责收口与 Core 边界，不改外层图。

## 当前事实与 Phase 边界

### 当前事实

- 当前仍是单主链路。
- 当前真实主链路没有正式 `orchestration_router` 分流，但已有 Phase 4 shadow mode 影子接入。
- 当前真实主链路没有 `workflow_runner`。
- 当前真实主链路没有 5 条 workflow 分流。
- 当前主链路可以视为 `DiscoveryDecisionWorkflow` 的演进雏形或未来收口方向，但当前代码仍是单主链路 subgraph 组织，不是正式的 workflow 分流实现。

### Phase 边界

#### Phase 1

- 不改外层图
- 不引入 `orchestration_router`
- 不引入 `workflow_runner`
- 不实现多 workflow
- 只做当前单主链路内部职责收口和 Core 边界

#### Phase 2

- Core 抽象进一步稳定
- 公共模块可单测
- 仍不一定需要引入 `workflow_runner`

#### Phase 3

- 可以把当前主链路固化为 `DiscoveryDecisionWorkflow` 的雏形
- 仍要避免大规模多 workflow 分流

#### Phase 4 以后

- 再把 shadow mode 的 `orchestration_router` 升级成正式分流
- 再引入 `workflow_runner`
- 再逐步分流 `DeterministicToolWorkflow` / `DirectResponseWorkflow` / `ClarificationFallbackWorkflow` / `ExplorationPlanningWorkflow`

## 五条 Workflow 的最终目标

### 1. DirectResponseWorkflow

适用：

- `chat`
- `capability`
- 能力边界说明
- 不支持 RAG / 交易 / 退款 / 下单时的说明

禁止：

- 查真实商家事实
- 调用交易工具
- 编造店铺信息

当前阶段：

- 后续阶段引入，不是 Phase 1 实现。

### 2. DeterministicToolWorkflow

适用：

- 这家现在营业吗
- 这家离我多远
- 这家人均多少
- 这家有什么优惠
- 这家差评主要说什么
- 这家适合约会吗

进入条件：

- 必须已解析出明确单店 target
- 需要 `current_shop` 或 `ReferenceResolutionResult`

禁止：

- 无历史候选时默认解析“第二家”
- 做多候选综合推荐

当前阶段：

- 后续阶段从主链路中拆出，不是 Phase 1 实现。

### 3. DiscoveryDecisionWorkflow

适用：

- 搜索
- 推荐
- 多店对比
- 条件筛选
- 场景推荐
- 团购比较
- 换个更近 / 更便宜 / 更安静

它是推荐问题的核心主链路。

必须强调：

- 推荐、搜索、对比、筛选最终都走 `DiscoveryDecisionWorkflow`
- 推荐结果必须由 `DecisionCore` 基于 `EvidencePack` 综合决策
- 不能由 `search_shops` 返回顺序决定
- 不能由 `EvidenceCore` 直接选 winner
- 不能由 `ResponseCore` 临时挑店

当前阶段：

- 当前主链路是它的演进雏形
- Phase 1 只收口当前主链路内部职责
- 正式命名和 `workflow_runner` 分流后续再做

### 4. ExplorationPlanningWorkflow

适用：

- 晚上约会，先吃饭再找附近能散步的地方
- 下午先喝咖啡再吃饭
- 周末带爸妈附近逛逛顺便吃饭
- 半天亲子活动方案
- 吃饭 + 看电影组合

边界：

- 多个本地生活子目标
- 有时间顺序或组合关系
- 输出 itinerary / plan
- 不执行交易、不预约、不下单

限制：

- 最多 3 个 subgoal
- 最多 2 轮工具扩展
- 禁止无限 replan
- 禁止开放式 ReAct loop

当前阶段：

- 最后做，不是 Phase 1 实现。

### 5. ClarificationFallbackWorkflow

适用：

- unknown
- ambiguous
- reference_failed
- no_result
- tool_failure
- missing_required_slot
- low_confidence
- out_of_scope

职责：

- 生成澄清问题
- 输出可信失败
- 降级回答
- 不硬跑下游链路

当前阶段：

- 后续作为独立 workflow 引入
- Phase 1 可以强化现有 clarification / review / fallback 行为，但不新增独立 workflow

## 二级路由设计

### orchestration_router

`orchestration_router` 的正式 workflow 分流仍是目标设计，不是当前执行事实；当前仓库已落地的是 Phase 4 shadow mode 影子决策写入。

#### 输入

- `top_intent`
- `semantic_frame`
- `task_type`
- `goal_type`
- `slots`
- `ReferenceResolutionResult`
- `current_shop`
- `last_recommendation_list`
- `pending_clarification`
- `active_constraints`
- `tool_availability`

#### 输出

- `orchestration_pattern`
- `workflow_name`
- `workflow_reason`
- `task_complexity`
- `requires_tool`
- `requires_clarification`
- `response_mode`
- `confidence`
- `missing_fields`
- `next_action`

#### 约束

- `orchestration_router` 只决定 workflow
- 不调用工具
- 不生成最终答案
- 不做事实判断
- 不做最终推荐
- 低 `confidence` 进入 `clarification_fallback`

### 一级路由与二级路由

- 一级路由是 `top_intent_router`
- 一级路由当前已存在，位于 `intake_guard_router`
- 一级路由只负责粗粒度意图：`chat / capability / local_life / unsafe / out_of_scope / invalid`
- 一级路由只判断是否进入本地生活主流程
- 二级路由是 `orchestration_router`
- 二级路由的正式调度当前未实现，但 shadow mode 已位于 `understanding_subgraph` 之后
- 二级路由只负责 workflow 分流

## workflow_runner 目标设计

`workflow_runner` 的职责是根据 `orchestration_router` 的结构化输出调用对应 workflow。
Phase 5 已引入 `workflow_runner` 与 workflow registry；当前仍是薄调度层，不负责业务判断。
当前 `discovery_decision` 已作为主链路薄适配接入，`deterministic_tool` / `clarification_fallback` / `direct_response` / `exploration_planning` 仍保持显式占位或现有主链路适配，不代表已拆成独立 workflow。

约束：

- `workflow_runner` 不应该写成一堆 `if / elif`
- 应使用 workflow registry / mapping / declarative config
- `workflow_runner` 不做业务决策
- `workflow_runner` 不生成最终回答
- `workflow_runner` 不调用不在白名单内的工具

示例设计：

```python
WORKFLOW_REGISTRY = {
    "direct_response": DirectResponseWorkflow,
    "deterministic_tool": DeterministicToolWorkflow,
    "discovery_decision": DiscoveryDecisionWorkflow,
    "exploration_planning": ExplorationPlanningWorkflow,
    "clarification_fallback": ClarificationFallbackWorkflow,
}
```

这是目标设计示例，不是当前代码事实。

## Prompt / Policy / Schema 约束

### 责任分工

- Prompt 负责语义判断、意图归类、约束抽取、证据需求判断
- Code 负责 schema 校验、policy 约束、工具白名单、fallback
- ToolCall 负责真实事实
- DecisionCore 负责综合决策
- ResponseCore 负责表达
- Verifier 负责事实一致性校验

### 必须遵守

- Prompt 不得直接决定真实事实
- Prompt 不得绕过 ToolCall 生成店铺事实
- Prompt 输出必须经过 validator
- Prompt 输出必须带 `reason / confidence / missing_fields`
- 低 `confidence` 必须进入 `clarification_fallback` 或 conservative path

## Response 多样性与事实一致性

回答设计应分层控制：

- `response_mode` 控制回答类型
- `response_style` 控制表达风格
- `answer_plan` 控制内容结构
- `verbalizer prompt` 控制自然语言多样性
- `verifier` 控制事实不漂移

约束：

- `ResponseCore` 不能改变 `DecisionCore` 的选择结果
- `ResponseCore` 不能新增 `EvidencePack` 外事实
- `ResponseCore` 不能为了表达多样性编造距离、价格、优惠、营业状态、评价

## 日志与测试要求

### 日志

每个 workflow / router / review / response 节点都要写结构化日志到 `var\\python_service.log`。

日志字段至少包括：

- `timestamp`
- `session_id`
- `turn_id`
- `workflow_name`
- `node_name`
- `task_type`
- `goal_type`
- `input_summary`
- `output_summary`
- `latency_ms`
- `status`
- `next_action`
- `confidence`
- `error_code`

禁止记录：

- 手机号
- token
- 支付信息
- 完整敏感地址

### 测试

router 测试：

- `top_intent_router` 不做 workflow 分流
- `orchestration_router` 低置信度进入 `clarification_fallback`
- 推荐问题进入 `discovery_decision`
- 单店事实查询在 target 明确时进入 `deterministic_tool`
- 多子目标规划进入 `exploration_planning`
- 指代失败进入 `clarification_fallback`

workflow 测试：

- `DiscoveryDecisionWorkflow` 不依赖 search rank 决策
- `DeterministicToolWorkflow` 无明确 target 时不执行
- `ExplorationPlanningWorkflow` 不超过 subgoal / replan 限制
- `ResponseCore` 不编造 evidence 外事实

这些测试可以作为后续阶段验收。
Phase 1 只需要保留当前主链路相关回归基线。

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

这些不是 workflow 设计阶段可以突破的边界。

## 可执行建议

1. 先把当前事实和最终目标分开写。
2. Phase 1 只收口单主链路内部职责，不做多 workflow。
3. 后续 workflow 只在后续阶段引入，不在 Phase 1 开工。
4. 路由表先写规范，再写实现。

## 可执行版补充

### Workflow 路由表

| workflow | 典型意图 | 进入条件 | 核心输出 | 失败后去向 | 当前阶段 |
| --- | --- | --- | --- | --- | --- |
| `DirectResponseWorkflow` | chat / capability | 无需工具或仅需最小语义理解 | `final_response` | `clarification_fallback` | Phase 4 以后 |
| `DeterministicToolWorkflow` | shop_status / shop_distance / shop_coupon / shop_review_summary | 单店、确定性、工具可直接回答 | `tool_result_set` / `evidence_pack` / `answer_plan` | `clarification_fallback` | Phase 4 以后 |
| `DiscoveryDecisionWorkflow` | search / recommendation / comparison / condition_refine | 需要候选发现 + 决策 | `decision_plan` / `answer_plan` | `clarification_fallback` | Phase 3 或后续 |
| `ExplorationPlanningWorkflow` | trip / date / family / multi-step plan | 需要探索式规划 | `decision_plan` / `final_response` | `clarification_fallback` | Phase 4 以后 |
| `ClarificationFallbackWorkflow` | ambiguous / no_result / tool_failure | 信息不足、候选冲突或工具失败 | 澄清问题或可信失败 | 不再往下游硬跑 | Phase 4 以后 |

### 节点级输入输出约束

| 节点 | 输入必须包含 | 输出必须包含 | 不得输出 |
| --- | --- | --- | --- |
| `semantic_parse` | `raw_text`, `top_intent` | `semantic_frame`, `goal_type` | 直接事实结论 |
| `goal_planner` | `semantic_frame`, `context` | `GoalPlan` | 未验证的商家事实 |
| `evidence_planner` | `GoalPlan`, `tool_registry` | `EvidencePlan` | 最终推荐结果 |
| `decision_planner` | `EvidencePack`, `CandidateSet` | `DecisionPlan` | 绕过 evidence 的结论 |
| `answer_plan_build` | `DecisionPlan`, `EvidencePack` | `AnswerPlan` | 新增事实 |
| `answer_generate` | `AnswerPlan`, `EvidencePack` | `final_response` | 未经 verifier 的事实扩写 |

### 路由验收清单

- `top_intent_router` 只决定是否进入本地生活主流程
- `orchestration_router` 只决定 workflow，不直接写答案
- `workflow_runner` 不存在时，主链路不得伪装成多 workflow 已落地
- 任何新增 route 必须先补 policy table，再补测试
