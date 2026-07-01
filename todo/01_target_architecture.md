# 01 目标架构

## 目标

定义最终目标结构，但明确当前第一阶段仍然只做单主链路的能力边界收口，不提前引入二级路由和多 workflow。

本文件定义的是目标方向，不代表当前阶段全部落地。
当前可开工范围仍以 Phase 1 为准，Phase 1 只做单主链路能力边界收口。

## 当前产品范围

当前阶段只覆盖 ToolCall-only 的本地生活非交易能力：

- 店铺查询
- 店铺状态
- 距离 / ETA
- 优惠券 / 团购
- 评价摘要
- 附近推荐
- 条件筛选
- 场景化推荐
- 多店对比
- 多轮指代
- 候选澄清

当前阶段不做：

- RAG
- 平台政策问答
- 商家入驻规则问答
- 退款规则问答
- 交易
- 下单
- 支付
- 退款
- 预约提交
- 取消订单
- 订单 mutation tool
- 自由 ReAct loop
- 开放式 multi-agent handoff

## 两级路由

### 一级路由：`top_intent_router`

- 当前已存在
- 位置：`intake_guard_router`
- 职责：只负责粗粒度意图判断，决定是否进入本地生活主流程
- 语义范围：`chat / capability / local_life / unsafe / out_of_scope / invalid`
- 输出：`top_intent`

### 二级路由：`orchestration_router`

- 当前未实现
- 后续阶段引入
- 位置：`understanding_subgraph` 之后
- 职责：只负责 workflow 分流
- 不生成回答
- 不调用工具
- 输出：
  - `orchestration_pattern`
  - `workflow_name`
  - `workflow_reason`
  - `task_complexity`
  - `requires_tool`
  - `requires_clarification`
  - `response_mode`

二级路由不能和一级路由合并。当前一级路由没有足够语义上下文，不能判断具体 workflow。
当前没有二级 `orchestration_router`，也没有 `workflow_runner`。

## 最终目标外层图

```text
START
  ↓
intake_guard_router
  ↓
merge_clarification
  ↓
understanding_subgraph
  ↓
orchestration_router
      ├── direct_response
      ├── deterministic_tool
      ├── discovery_decision
      ├── exploration_planning
      └── clarification_fallback
  ↓
workflow_runner
  ↓
response_subgraph
  ↓
state_update_plan
  ↓
END
```

但要强调：

- 这是最终目标图，不是当前实现图
- Phase 1 不按这个图改代码
- Phase 1 不改外层图
- Phase 1 不引入 `orchestration_router`
- Phase 1 不引入 `workflow_runner`

## 目标原则

1. `search_shops` 只做召回。
2. `Evidence` 只补事实，不做最终排序。
3. `Decision` 只做综合决策。
4. `ReferenceResolution` 对推荐 / 对比 / 查店共用。
5. `ResponseCore` 负责自然语言表达，但不能改事实。
6. Review / Verifier 必须阻止未验证事实进入最终回答。
7. 节点实现应优先依赖 prompt / schema / policy / registry，而不是大段 `if / elif / else`。
8. 回复要允许多样性，不能总套固定模板。
9. 每个节点都要有结构化日志，统一写入 `var\\python_service.log`。

## 能力包到 Core 映射

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

## 目标能力包

### IntentPlanningAbility

- 输出结构化任务意图。

### ContextMemoryAbility

- 保存多轮对话目标、候选、证据、答案顺序、澄清状态。

### ReferenceResolutionAbility

- 统一处理“这家 / 它 / 那家 / 第一个 / 第二个 / 便宜一点 / 近一点”。

### ExactShopQueryAbility

- 统一单店查询能力。

### SearchRecallAbility

- 只负责召回候选。

### EvidenceEnrichmentAbility

- 把事实补齐到可验证状态。

### CandidateDecisionAbility

- 基于证据和偏好做综合排序与选择。

### ComparisonDecisionAbility

- 专门处理多店对比。

### AnswerGroundingAbility

- 把决策结果转成可说、可验的自然语言。

### ReviewSufficiencyAbility

- 判断当前信息是否足够。

### AnswerVerifierAbility

- 校验回答是否与 evidence / decision 对齐。

### TraceObservabilityAbility

- 每个阶段都能回溯输入、输出、状态、耗时和失败原因。

## 当前事实、近期改造、最终目标、future work

### 当前事实

- 当前只有一级路由 `top_intent_router`。
- 当前主链路已经存在。
- 当前 `Review` / `Verifier` 已参与主链路。
- 当前没有 `orchestration_router`。
- 当前没有 `workflow_runner`。
- 当前没有 5 条 workflow 的真实实现。

### 近期改造

- Phase 1 收口 `search_shops` / `build_evidence` / `candidate_decision` / `reference_resolver` / `MOCK_LOCATION` / `SessionState` / `Review` / `Verifier`。
- Phase 2 再抽 Core 或公共模块。
- Phase 3 再固化当前主链路为 `DiscoveryDecisionWorkflow` 雏形。

### 最终目标

- 再引入 `orchestration_router`
- 再引入 `workflow_runner`
- 再分流 5 条 workflow

### future work

- 更复杂的 exploration planning
- future tool
- 更完整的 trace 派生与可观测性增强

future work 不包含 RAG，也不包含交易类能力，不应被写成当前阶段任务。

## 可执行建议

1. 先把当前事实和最终目标分开写。
2. 第一批改造不要碰外层图。
3. 后续 workflow 只在后续阶段引入，不在 Phase 1 开工。

## 可执行版补充

### 目标架构验收清单

| 项目 | 验收方式 | 通过标准 |
| --- | --- | --- |
| 一级路由 | 查看 `top_intent_router` 输出 | 只负责是否进入本地生活主流程 |
| 二级路由 | 查看 `orchestration_router` 设计 | 只负责 workflow 分流，不写答案 |
| 外层图 | 对照 `START -> ... -> END` | Phase 1 不改外层图 |
| 模块边界 | 对照 Core 映射表 | 每个 Core 都有唯一职责 |
| 状态字段 | 对照 `05_state_and_schema_design.md` | 字段语义不互相替代 |
| 响应约束 | 对照 `12_prompt_policy_and_logging_guidelines.md` | 回复多样性与事实一致性同时满足 |

### 近期改造落点

- Phase 1 先收口 `search_shops`、`build_evidence`、`MOCK_LOCATION` 和 `SessionState`。
- Phase 2 再抽 `ReferenceResolution` 与 `CandidateCore`。
- Phase 3 再强化 Review / Verifier / Grounding。

### 最终目标落点

- 二级路由只做 workflow 分流。
- workflow 层只负责把任务送进正确的 Core 组合。
- 回答层只负责表达，不负责编事实。
