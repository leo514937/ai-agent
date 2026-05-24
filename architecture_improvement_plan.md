# Python 本地生活服务架构改进实施文档

> 本文承接 [问题诊断文档](architecture_problem_diagnosis.md)，只回答“怎么改、先改哪里、如何验收”。
>
> 改造原则：按阶段交付，先处理紧急性最高的问题，再逐步计划化和架构收敛。任何阶段都不要求一次性全量改造；阶段 1 不删除 `required_action`，不重写全部 RAG，不重写全部 memory，不合并 runner。

## 1. 目标架构：从用户需求到答案的强约束链路

建议目标不是“把所有组件推翻重写”，而是在现有 routing、RAG、toolcall、memory、compose_answer 之间补上强约束对象：

- `UserNeed`
- `RequiredFacets`
- `TaskPlan`
- `EntityJoinResult`
- `AnswerContract`
- `AnswerVerifier`

目标架构图：

```text
输入
 |
 v
[InputQualityCheck]
 |
 v
[UserNeedParser]
 |  intent / slots / constraints / required_facets
 v
[RouteReview]
 |  防止 direct/clarify/reject 过早短路
 v
[MemoryRelevanceGate]
 |  只注入相关记忆，当前 query 优先于历史记忆
 v
[TaskPlanBuilder]
 |
 +--> clarify_if_needed
 +--> rag_retrieve
 +--> tool_call
 +--> entity_join
 +--> rank_candidates
 v
[AnswerComposer]
 |
 v
[AnswerVerifier]
 |
 +--> final
 +--> slot_clarify
 +--> partial_answer
 +--> no_answer
 |
 v
[persist_session / memory_promotion]
```

关键约束：

- `UserNeedParser` 不替代 routing，而是给 routing 和 compose 提供更细粒度的任务约束。
- `RouteReview` 不等于每轮都上大模型重判，而是对高风险早停场景做轻量复核。
- `MemoryRelevanceGate` 不让历史记忆默认覆盖当前 query。
- `TaskPlanBuilder` 只先覆盖复杂本地生活请求，简单问题继续走旧链路。
- `AnswerVerifier` 先从规则校验开始，不必第一版就做复杂 LLM judge。


### 1.1 受控多 Agent 演进原则

本改造计划不是直接把系统重构为自由多 Agent，而是在现有 LangGraph / workflow 架构内，逐步把关键能力模块演进为固定输入输出的专职 node / subgraph。当前阶段的重点是建立结构化契约、统一状态和可观测能力，而不是一次性把所有模块拆成独立 Agent。

核心原则：

1. 主编排器仍由 LangGraph / Workflow Runner 负责，其他 agent-like 模块作为 node / subgraph 被调度。
2. 所有 agent-like 模块必须读写统一 State，不允许私自维护独立上下文。
3. 在线链路中的模块优先实现为 LangGraph node 或 subgraph。
4. RAG、toolcall、plan_execute 这类多步骤能力可以做成 subgraph。
5. `UserNeedParser`、`RouteReview`、`MemoryRelevanceGate`、`EntityConsistencyMinimal`、`AnswerVerifier` 第一版先做 node。
6. 工具 API 不升级为 Agent，只作为 Tool Adapter，例如 `get_coupon_list`、`check_open_status`、`get_distance_eta`。
7. 离线能力，如知识入库、评价摘要、商家画像、评测回归，可以脱离 LangGraph 独立实现。
8. 阶段 0-2 不做完整多 Agent，只建立输入输出契约、trace 和止血能力。
9. 阶段 3 才允许 `TaskPlan` 试点，且只覆盖复杂本地生活请求。
10. 阶段 4 才允许完整 `EntityJoinResult` 和 `AnswerVerifier`。
11. 禁止多个 Agent 自由互相聊天；所有调度必须通过主编排器和统一 State。
12. 所有新增模块都必须有固定输入、固定输出、字段 owner、失败原因和 trace。

推荐演进方向：

```text
当前工作流节点
  -> 固定输入输出的 LangGraph node
  -> 复杂能力沉淀为 subgraph
  -> 最终形成受控多 Agent / 多专职节点协作系统
```

不推荐演进方向：

```text
多个自由 Agent 互相聊天
  -> 各自调用工具
  -> 各自产生答案片段
  -> 最后再由 compose 强行拼接
```

### 1.2 Agent-like 模块边界表

| 模块 | 当前阶段形态 | 未来形态 | 是否当前独立 | 通信方式 |
| --- | --- | --- | --- | --- |
| `UserNeedParser` | 函数 / node | UserNeedParser Agent | 阶段 1 固定输出结构 | 写入 `state.user_need / state.required_facets` |
| `MemoryRelevanceGate` | 函数 / node | MemoryRelevance Agent | 阶段 1 先做相关性判断 | 写入 `state.memory_relevance / state.resolved_entity` |
| `RouteReview` | 函数 / node | RouteReview Agent | 阶段 1 只做高置信纠错 | 写入 `state.route_review_decision` |
| `RAG` | 现有 `rag_subgraph` | RAG Subgraph | 保持子图，不重写 | 输出 `EvidencePack` |
| `ToolCall` | 现有 `tool_subgraph` | ToolPlanning Subgraph | 保持子图，不把每个工具变 Agent | 输出 `ToolPlan / ToolResult` |
| `EntityConsistencyMinimal` | 规则校验 node | EntityJoin Agent 的前置能力 | 阶段 1 只做最小检查 | 输出 `EntityConsistencyMinimal` |
| `TaskPlanBuilder` | 暂不启用或仅旁路 | Planner Agent | 阶段 3 试点 | 输出 `TaskPlan` |
| `AnswerComposer` | 现有 compose | Composer Node | 阶段 2 增强 response_mode | 输出 `DraftAnswer / final_answer` |
| `AnswerVerifier` | 暂不启用 | Verifier Node | 阶段 4 再做 | 输出 `AnswerVerifierResult` |
| `Persist / MemoryPromotion` | 服务节点 | Persistence Service | 不建议 Agent 化 | 写入 Redis / Postgres |
| 业务工具 API | Tool Adapter | Tool Adapter | 不建议 Agent 化 | 返回结构化 tool result |
| 知识入库 / 商家画像 / 评测 | 离线 job | Offline Agent / Worker | 脱离在线 LangGraph | 写入知识库、画像库、评测报告 |

### 1.3 State 字段所有权

多 Agent / 多节点协作最容易出问题的是字段所有权混乱。每个关键字段必须有唯一写入者，其他节点只能读取或追加 trace，不能随意覆盖。

| State 字段 | 唯一写入者 | 可读取者 | 说明 |
| --- | --- | --- | --- |
| `user_need` | `UserNeedParser` | 后续所有节点 | 当前轮用户需求结构化结果 |
| `required_facets` | `UserNeedParser` | RAG / Tool / Compose / Verifier | 后续能力分工依据 |
| `memory_relevance` | `MemoryRelevanceGate` | RouteReview / TaskPlanBuilder / Compose | 记忆是否参与本轮 |
| `resolved_entity` | `MemoryRelevanceGate` 或显式 slot resolver | RAG / Tool / EntityJoin | 指代消解后的实体 |
| `initial_routing_decision` | 原 routing 节点 | RouteReview / Trace | 初始路由结果 |
| `route_review_decision` | `RouteReview` | Workflow Router / Trace | 复核后的路由建议 |
| `retrieval_plan` | RAG Planner | RAG Subgraph / Trace | 检索计划 |
| `evidence_pack` | RAG Subgraph | EntityJoin / Compose / Verifier | RAG 证据包 |
| `tool_plan` | ToolPlanning | ToolExecutor / Trace | 工具计划 |
| `tool_result` | ToolExecutor / ToolResultNormalizer | EntityJoin / Compose / Verifier | 工具执行结果 |
| `entity_consistency_minimal` | EntityConsistency Node | Compose / Verifier | 阶段 1 最小实体一致性检查 |
| `entity_join_result` | EntityJoin | Compose / Verifier | 阶段 4 完整实体对齐结果 |
| `answer_contract` | AnswerContract Builder | Compose / Verifier | 回答约束 |
| `draft_answer` | AnswerComposer | AnswerVerifier | 草稿答案 |
| `answer_verifier_result` | AnswerVerifier | Finalizer / Trace | 最终校验结果 |
| `final_answer` | Finalizer / Compose 出口 | Persist / SSE | 用户可见答案 |

约束：

- RAG 不写 `final_answer`。
- Tool 不写 `final_answer`。
- Memory 不覆盖当前 query 的显式约束。
- Compose 不覆盖 `tool_result` 或 `evidence_pack`。
- Verifier 不直接调用工具，只给出 `passed / issues / suggested_response_mode / repair_hint`。

### 1.4 Harness Engineering：测试、回放与评估体系

Harness Engineering 是本项目从工作流系统演进为受控多 Agent 系统的基础设施。它不改变线上业务行为，而是提供 trace、replay、mock、golden evidence 和 evaluation 能力，保证每个阶段的改造可观测、可回放、可验证、可回滚。

本项目至少需要 5 类 harness：

1. Trace Harness：记录每轮请求的关键状态变化。
2. Replay Harness：用固定本地生活 case 反复回放，比较改造前后差异。
3. Tool Mock Harness：模拟 `get_coupon_list / check_open_status / get_distance_eta / search_restaurants` 等工具的成功、失败、缺 slot、超时、实体不一致等情况。
4. RAG Mock / Golden Evidence Harness：固定 `EvidencePack`，稳定测试 EvidenceGate、RequiredFacets 覆盖、EntityConsistency、partial_grounded。
5. Evaluation Harness：基于 trace 和答案自动统计路由、RAG、toolcall、回答质量、跨实体拼接等指标。

Harness 与在线链路的关系：

```text
测试 / 回放 / 评估阶段：
  Harness -> Mock RAG / Mock Tool / Replay Cases -> LangGraph MainGraph -> Trace -> Evaluation Report

线上用户请求阶段：
  用户请求 -> LangGraph MainGraph -> Trace / Metrics
```

要求：

- Harness 不参与线上主链路决策。
- 阶段 0 必须优先补 Trace Harness 和 Replay Harness skeleton。
- 阶段 1 的实体一致性测试必须依赖 Tool Mock 和 Golden Evidence。
- 阶段 2 的 partial answer / slot clarify 必须依赖 Replay Harness 回归。
- 阶段 3 的 TaskPlan 试点必须能用同一批 case 对比旧链路和新链路。
- 阶段 4 的 AnswerVerifier 必须把 verifier issue 写入 trace 和 Evaluation Report。
- 每个阶段完成后，必须输出 harness 运行结果，而不只是人工观察回答文本。

### 1.5 代码落点总览

后续实施不要先新建一套完整框架，优先在现有链路上补字段、补 trace、补校验。建议代码落点如下：

| 改造点 | 所属阶段 | 主要代码落点 | 改动边界 |
| --- | --- | --- | --- |
| `route_review` | 阶段 1 | `learning-agent-service/src/learning_agent_service/application/workflow/adapters.py:376` 的 `load_context`，以及 `learning-agent-service/src/learning_agent_service/application/workflow/adapters.py:434` 的 `parse_intent_slots` | 先只在 terminal action 前增加复核结果和 trace，不重写 routing 主逻辑 |
| `UserNeed / RequiredFacets` | 阶段 1 | `learning-agent-service/src/learning_agent_service/domain/contracts.py:332` 的 `RoutingDecision.extra`，`learning-agent-service/src/learning_agent_service/domain/contracts.py:100` 的 `RetrievalPlan.extra`，`learning-agent-service/src/learning_agent_service/domain/contracts.py:580` 的 `AnswerComposeRequest` | 第一版可先放在 `extra`，跑通后再提升为强类型字段 |
| RAG plan facet 透传 | 阶段 1 | `learning-agent-service/src/learning_agent_service/application/routing.py:1101` 的 `ensure_retrieval_plan`，`learning-agent-service/src/learning_agent_service/application/routing_signals.py` 中 synthesis 相关逻辑 | retrieval plan 要记录服务哪些 facets 和使用哪些静态证据 |
| tool plan facet 透传 | 阶段 1 | `learning-agent-service/src/learning_agent_service/application/routing.py:1153` 的 `ensure_tool_plan`，`learning-agent-service/src/learning_agent_service/domain/contracts.py:421` 的 `ToolPlanningRequest` | tool plan 要记录服务哪些动态 facets 和缺失哪些 slots |
| 分级响应 | 阶段 2 | `learning-agent-service/src/learning_agent_service/application/routing.py:898` 的 `build_evidence_quality`，`learning-agent-service/src/learning_agent_service/domain/contracts.py:297` 的 `EvidenceQualityDecision`，`learning-agent-service/src/learning_agent_service/tools/service.py:884` 的 `compose` | 新增 `partial_grounded / ask_clarification`，不要只在 compose 层套模板 |
| slot 化澄清 | 阶段 2 | `ensure_retrieval_plan`、`ensure_tool_plan`、`learning-agent-service/src/learning_agent_service/tools/service.py:884` 的 `compose` | 用 `missing_slots / clarification_slot` 生成最小澄清问题 |
| 最小实体一致性检查 | 阶段 1 | `learning-agent-service/src/learning_agent_service/application/routing.py:898` 的 `build_evidence_quality`，`learning-agent-service/src/learning_agent_service/application/workflow/adapters.py:1096` 附近的 evidence quality gate，`learning-agent-service/src/learning_agent_service/tools/service.py:884` 的 `compose` | 只检查明显的 `shop_id / coupon_id / package_id` 不一致，先不做完整 entity join |
| `rag_plus_tool` 失败可观测 | 阶段 2 | `ensure_retrieval_plan`、`ensure_tool_plan`、`learning-agent-service/src/learning_agent_service/application/workflow/subgraphs.py:355` 的 `route_after_rag` | 记录失败原因并允许 partial answer，不静默退化成泛澄清 |
| `TaskPlan` | 阶段 3 | `learning-agent-service/src/learning_agent_service/domain/contracts.py:184` 的 `PlanStep`，`learning-agent-service/src/learning_agent_service/application/workflow/plan_execute.py`，`learning-agent-service/src/learning_agent_service/application/workflow/subgraphs.py:337` 的 `route_after_understand` | 只让复杂本地生活请求进入，简单请求保持旧链路 |
| 完整实体对齐 | 阶段 4 | 新增或扩展 entity join helper，并接入 `compose_answer` 前 | 阶段 4 再做 `EntityJoinResult`，不要在阶段 1 做成大重构 |
| `AnswerVerifier` | 阶段 4 | `learning-agent-service/src/learning_agent_service/application/workflow/adapters.py:1265` 的 `compose_answer` 后，或 `learning-agent-service/src/learning_agent_service/tools/service.py` 内部 compose 后置校验 | 第一版 deterministic verifier，先拦截跨实体和 facet 缺失 |
| runner 对齐 | 阶段 5 | `learning-agent-service/src/learning_agent_service/application/workflow/builder.py:61`，`learning-agent-service/src/learning_agent_service/application/workflow/runner.py:47` | 先 trace 对比，后决定是否合并 |

## 2. 多阶段改进方案：按紧急性递进

本章把改造拆成可逐阶段交付的方案。每个阶段只完成一部分内容，完成验收后再进入下一阶段；不要把后续阶段的设计提前实现到当前阶段。

阶段划分：

| 阶段 | 紧急性 | 本阶段目标 | 包含内容 | 明确不做 |
| --- | --- | --- | --- | --- |
| 阶段 0：Harness 与观测基线 | 最高 | 先看清楚系统怎么错，并建立可回放、可 mock、可评估的基础设施 | trace、replay、tool mock、RAG golden evidence、指标、失败原因记录 | 不改变 routing、不改回答文本 |
| 阶段 1：止住答非所问和串店 | 最高 | 先处理最影响用户体感的问题 | `route_review`、`RequiredFacets` 数据源约束、最小实体一致性检查 | 不做 TaskPlan、不做完整实体 join、不合并 runner |
| 阶段 2：减少硬拒答和泛澄清 | 高 | 有部分证据时给边界明确的有用回答 | 分级响应、slot 化澄清、`rag_plus_tool` partial answer | 不重写 RAG、不引入 agent loop |
| 阶段 3：复杂任务计划化试点 | 中 | 只让复杂本地生活请求进入 TaskPlan | TaskPlan 试点、plan_execute 小范围接入 | 不替换所有 `required_action` |
| 阶段 4：证据到答案强校验 | 中 | 从“能回答”升级到“回答可验证” | 完整实体对齐、AnswerContract、AnswerVerifier | 不做 runner 合并 |
| 阶段 5：runner 收敛评估 | 低 | 基于 trace 决定是否合并双 runner | LangGraph / Sequential 行为对齐和收敛预研 | 不在无对比数据时强行合并 |

### 阶段 0：Harness 与观测基线，不改变线上行为

阶段 0 是所有后续改造的前置条件。目标是补齐 trace、replay、mock 和基础 evaluation，让后续每个阶段都能验证“改动是否真的有效”。本阶段只增强观测和测试能力，不改变线上行为。

本阶段只做：

- 建立 Trace Harness，记录 `initial_routing_decision / evidence_quality / final_response_mode`
- 建立 Replay Harness skeleton，支持固定本地生活测试 case 回放
- 建立 Tool Mock Harness skeleton，支持模拟工具成功、失败、缺 slot、超时、跨实体返回
- 建立 RAG Mock / Golden Evidence Harness skeleton，支持固定 `EvidencePack` 测试
- 建立 Evaluation Harness skeleton，先统计可观测指标，不做复杂自动评分
- 记录 retrieval / tool plan 是否构造成功
- 记录 `rag_plus_tool` 哪一步失败
- 记录当前回答是否由 direct、RAG、tool、RAG+tool、fallback 产生

代码落点：

- `learning-agent-service/src/learning_agent_service/application/workflow/adapters.py:376`
- `learning-agent-service/src/learning_agent_service/application/workflow/adapters.py:1096`
- `learning-agent-service/src/learning_agent_service/application/workflow/adapters.py:1265`

本阶段不做：

- 不改变 `required_action`
- 不改变最终回答文本
- 不新增 TaskPlan
- 不做 RouteReview 行为改变
- 不做 RequiredFacets 生效
- 不做 EntityJoinResult
- 不做 AnswerVerifier
- 不改 RAG 排序
- 不改 tool 调用策略

完成标准：

- 能看到本地生活 query 中 `direct_answer / clarify / no_answer` 的分布。
- 能看到 `retrieval_plan_missing / tool_plan_missing / tool_slot_missing` 的数量。
- 能对测试集输出稳定 trace，作为阶段 1 的对比基线。
- Replay Harness 能运行至少 10 个本地生活固定 case。
- Tool Mock Harness 能模拟至少：成功、失败、缺 slot、实体不一致四类工具结果。
- RAG Mock / Golden Evidence Harness 能提供至少：相关证据、低分证据、跨实体证据三类 `EvidencePack`。
- Evaluation Harness 能输出基础报告，包括 case 总数、通过数、失败原因分布和关键 trace 字段缺失情况。

### 阶段 1：最高紧急，先止住答非所问和跨实体拼接

阶段 1 只处理最紧急、收益最高、风险可控的问题：过早短路、用户需求未结构化、动态信息来源不受约束、明显跨实体拼接。本阶段的新增模块必须按未来多 Agent node 的输入输出契约实现，但不得引入自由 Agent 间通信。

本阶段包含三件事：

1. `route_review` / second-pass understanding
2. `UserNeed / RequiredFacets`，并增加静态/动态数据源约束
3. 前置最小实体一致性检查

本阶段不做：

- 不做完整 TaskPlan
- 不重写 RAG
- 不重写 memory
- 不合并 runner
- 不做完整 `EntityJoinResult`
- 不引入 LLM judge

#### 2.1 增加 `route_review` / second-pass understanding

不要让 initial routing 一次性决定 `direct_answer / clarify / reject / no_op`。

建议做法：

- 保留 `build_initial_routing_decision`，但在 terminal action 之前插入 `route_review`。
- 当 query 命中本地生活信号时，即使初始路由是 `direct_answer / clarify`，也进入二次复核。
- 本地生活信号包括：附近、商圈、店、套餐、券、营业、排队、距离、评价、环境、适合约会、适合带父母、适合学习、这家、那家、它、刚才那个。
- 二次复核输出不要直接替换全部 routing，只允许把明显误判的 terminal action 提升为 `rag_retrieval / tool_call / rag_plus_tool / task_plan_candidate`。
- `reject` 仍然保留安全优先，但对本地生活正常请求不能因为低信息量就直接拒答。

验收重点：

- `direct_answer -> rag/tool/task_plan` 的纠正比例上升。
- `clarify -> 可回答任务` 的纠正比例上升。
- 本地生活 query 的 terminal early exit 下降。

#### 2.2 增加 `UserNeed / RequiredFacets`

在 `required_action` 之外，显式解析用户到底问了哪些方面。

建议新增结构：

```text
UserNeed
  - intent
  - slots
  - constraints
  - required_facets
  - optional_facets
  - missing_slots
  - context_refs
```

`required_facets` 不只表示“要回答哪些方面”，还必须声明每个 facet 允许使用的数据源、是否需要动态工具、是否允许用静态 RAG 部分回答。建议先覆盖：

- `scene_fit`
- `location`
- `category`
- `price`
- `coupon`
- `open_status`
- `distance_eta`
- `shop_detail`
- `recommendation_reason`

使用原则：

- RAG retrieval plan 必须说明服务哪些 facets。
- tool plan 必须说明服务哪些 facets。
- compose_answer 必须围绕 `required_facets` 组织答案。
- 如果某个 required facet 缺证据，答案里必须显式标注边界。
- 动态 facet 不能只靠静态 RAG 给确定结论。
- 静态 facet 可以由 RAG evidence 支撑，但仍要做实体一致性检查。
- memory 只能用于指代消解和偏好补充，不能替代当前 query 的显式约束。

建议 facet schema：

```text
RequiredFacet
  - name
  - required: bool
  - data_source: slot | static_rag | dynamic_tool | memory | client_context | mixed
  - freshness: static_ok | near_realtime_required
  - entity_keys: shop_id | coupon_id | package_id | location_id | blog_id
  - missing_policy: partial_grounded | ask_clarification | no_answer
```

第一版数据源约束：

| Facet | 推荐数据源 | 是否动态 | 约束 |
| --- | --- | --- | --- |
| `scene_fit` | `static_rag` | 否 | 可来自评价、攻略、店铺详情，但必须和候选 `shop_id` 对齐 |
| `location` | `client_context / memory / slot` | 视情况 | 当前 query 或客户端定位优先，memory 只能补“刚才那家/附近商圈” |
| `category` | `slot / static_rag` | 否 | 用户显式品类优先，不能被历史 memory 覆盖 |
| `price` | `static_rag / dynamic_tool` | 视情况 | 人均、价格带可用 RAG；实时套餐价、券后价优先 tool |
| `coupon` | `dynamic_tool` | 是 | 是否有券、券是否可用、有效期必须优先 tool；RAG 只能做背景 |
| `open_status` | `dynamic_tool` | 是 | “现在营业/今天能不能去”必须 tool；RAG 营业时间只能作为辅助 |
| `distance_eta` | `dynamic_tool / client_context` | 是 | 必须依赖当前位置或商圈；缺定位时 ask_clarification |
| `shop_detail` | `static_rag` | 否 | 推荐菜、环境、服务可用 RAG，但不能跨店拼接 |
| `recommendation_reason` | `mixed` | 视情况 | 理由必须引用已覆盖 facets，不得把未验证动态信息写成理由 |

示例：

```text
用户：附近有没有适合约会、现在营业、最好有券的火锅？

required_facets:
  - name: location
    data_source: client_context
    freshness: near_realtime_required
  - name: category
    data_source: slot
    freshness: static_ok
  - name: scene_fit
    data_source: static_rag
    freshness: static_ok
  - name: open_status
    data_source: dynamic_tool
    freshness: near_realtime_required
  - name: coupon
    data_source: dynamic_tool
    freshness: near_realtime_required
  - name: recommendation_reason
    data_source: mixed
    freshness: static_ok
optional_facets:
  - distance_eta
  - price
missing_slots:
  - location 当 client_context 没有城市/经纬度时才缺失
```

#### 2.6 前置最小实体一致性检查

完整实体对齐可以放到阶段 4，但最小实体一致性检查必须提前到阶段 1。原因是：即使不引入完整 `EntityJoinResult`，也不能允许明显的 A 店评价、B 店券、C 店营业状态被组合成同一家店的推荐理由。

阶段 1 只做低成本检查：

- 如果 RAG evidence 中有 `shop_id`，tool result 中也有 `shop_id`，两者不一致时不能输出确定推荐。
- 如果用户问的是券或套餐，`coupon_id / package_id` 必须和当前 `shop_id` 或最近上下文实体能对齐。
- 如果 RAG evidence 只有 `document_id / parent_shop_id`，先按可获得字段做弱一致性，不要求一次补齐全量实体模型。
- 如果实体不一致但各自证据可用，输出候选对比或 `partial_grounded`，不能合成一个实体。

建议代码落点：

- 在 `learning-agent-service/src/learning_agent_service/application/routing.py:898` 的 `build_evidence_quality` 中增加 `entity_mismatch` / `cross_entity_risk` reason。
- 在 `learning-agent-service/src/learning_agent_service/application/workflow/adapters.py:1096` 附近构造 evidence quality context 时，把 `tool_result` 中的 `shop_id / coupon_id / package_id` 摘出来传入 context。
- 在 `learning-agent-service/src/learning_agent_service/tools/service.py:884` 的 `compose` 中，如果检测到 `cross_entity_risk`，降级为 `partial_grounded` 或 `ask_clarification`。
- 第一版结果可以放在 `EvidenceQualityDecision.details["entity_consistency_minimal"]`，避免新增过多强类型字段。

验收重点：

- A 店评价、B 店券、C 店营业状态不能合成“推荐 A 店，因为它有券且营业”。
- 上下文指代“它”解析不出来时，不能拿最近任意工具结果强行拼接。
- 动态工具结果缺少实体 id 时，回答要明确“不确定是否对应同一家店”。

阶段 1 完成标准：

- 本地生活 query 的 terminal early exit 明显下降。
- `RequiredFacets` 至少覆盖 `scene_fit / location / category / coupon / open_status / distance_eta / shop_detail / recommendation_reason`。
- `coupon / open_status / distance_eta` 被标记为动态数据源，不能只靠静态 RAG 强答。
- 明显跨实体拼接会被拦截或降级为 `partial_grounded / ask_clarification`。
- 阶段 0 Harness 能回放阶段 1 的核心 case。
- Tool Mock Harness 能模拟 A 店评价、B 店券、C 店营业状态。
- RAG Golden Evidence 能模拟相关证据、跨实体证据和弱证据。
- Evaluation Harness 能统计 `cross_entity_risk / dynamic_facet_without_tool / route_review_correction`。

### 阶段 2：高紧急，减少硬拒答和泛澄清

阶段 2 在阶段 1 的基础上处理“有部分证据却拒答”“只缺一个 slot 却泛澄清”“RAG 成功但 tool 失败导致整轮失败”等问题。

本阶段包含：

- 分级响应
- slot 化澄清
- `rag_plus_tool` 失败路径可观测和 partial answer

本阶段不做：

- 不重写 retrieval ranking
- 不引入复杂 agent loop
- 不迁移所有请求到 TaskPlan
- 不做完整 AnswerVerifier

#### 2.7 将 `no_answer` 改成分级响应

不要把证据不足直接等同于拒答。

建议输出等级：

- `grounded`
- `partial_grounded`
- `weak_answer`
- `ask_clarification`
- `no_answer`

推荐判定方式：

- `grounded`：required facets 主要覆盖，实体一致，有足够证据或工具结果。
- `partial_grounded`：至少一个核心 facet 有强证据，但部分 facet 缺失。
- `weak_answer`：有弱相关证据，可提供方向性建议，但不能给确定结论。
- `ask_clarification`：只缺关键 slot，补齐后即可执行。
- `no_answer`：没有可用证据、实体无法确定，或问题超出能力边界。

重要规则：

- 单条强证据可以允许 `partial_grounded`，尤其是具体店铺详情、单个套餐、单条营业状态这类问题。
- 有部分证据时要先给边界明确的有用回答，而不是直接拒答。
- 不确定的部分必须明确说明，不能编。
- `no_answer` 不再承担“证据少、槽位缺、实体冲突、工具失败”的所有职责。

#### 2.8 澄清问题 slot 化

把“请补充更多信息”改成最小澄清问题。

建议规则：

- 缺城市：问“你想看哪个城市或商圈？”
- 缺店名：问“你是问刚才那家店，还是要重新推荐？”
- 缺时间：问“你是想查现在是否营业，还是某个具体时间？”
- 缺人数：问“几个人用餐？我可以据此判断是否适合聚餐/包间。”
- 缺套餐：问“你说的是哪家店的哪个套餐？”
- 缺当前位置：问“你方便提供当前位置或商圈吗？我才能判断距离和附近门店。”

落地建议：

- `ensure_retrieval_plan` 和 `ensure_tool_plan` 不再默认写入“我还差一点信息，能再补充一下吗？”
- 返回 `missing_slots` 和 `clarification_slot`。
- compose 层根据 slot 生成具体问题。

#### 2.9 `rag_plus_tool` 失败路径可观测

当前 `rag_plus_tool` 是脆弱串联，不是真正任务计划。阶段 2 不要求马上重写成 TaskPlan，但必须让失败可观测、可解释、可回归。

必须记录：

- `retrieval_plan_missing`
- `tool_plan_missing`
- `tool_slot_missing`
- `tool_not_allowed`
- `retrieval_not_allowed`
- `rag_gate_blocked`
- `evidence_after_gate_count`
- `tool_candidates`
- `missing_slots`

回答策略：

- 如果 RAG plan 构造失败，说明缺的是检索语义、地点、品类还是目标实体。
- 如果 tool plan 构造失败，说明缺的是工具、店铺、套餐、时间、定位还是用户授权。
- 如果只有一部分能力执行成功，输出 `partial_grounded`，并列出未完成的部分。
- 不允许静默退化成泛澄清。

阶段 2 完成标准：

- 有部分 RAG 证据时能输出 `partial_grounded`。
- 缺一个 slot 时能生成最小澄清问题。
- RAG 成功但 tool 失败时，不丢掉 RAG 已有结果。

### 阶段 3：复杂任务计划化试点，不推翻 required_action

阶段 3 的目标是让复杂本地生活任务计划化，但不推翻现有链路。阶段 3 是受控多 Agent 编排的试点阶段，`TaskPlanBuilder` 可以被视为 Planner Agent，但第一版只输出结构化 `TaskPlan`，不允许自由循环、不允许多个 Agent 互相聊天、不允许所有请求进入 TaskPlan。

明确原则：

- 阶段 3 不要删除 `required_action`。
- 新增 `task_plan` 字段，与 `required_action` 并行。
- 只对复杂本地生活请求启用 `TaskPlan`。
- 简单问题仍可走旧链路。
- 已存在的 `plan_execute_subgraph` 可以作为参考或承载点，但不要直接把所有请求迁进去。

TaskPlan 的价值不是让系统变复杂，而是避免把“推荐 + 环境 + 券 + 营业状态”这种自然组合问题硬塞进单个 `required_action`。

示例：

```text
用户：
推荐一家适合约会、现在营业、最好有券的火锅店。

TaskPlan:
1. resolve_location
2. search_restaurants
3. retrieve_scene_evidence
4. check_open_status
5. get_coupon_list
6. entity_join
7. rank_candidates
8. compose_answer
9. answer_verify
```

建议启用 TaskPlan 的条件：

- required facets 数量 >= 3
- 同时需要 RAG 和 toolcall
- 出现上下文指代且需要工具执行
- 出现“推荐 + 动态状态”：营业、券、距离、排队、库存、套餐可用
- 出现候选排序：最好、最适合、附近、性价比、安静、适合约会

TaskPlan 第一版可以很薄：

- 不做复杂 replanning
- 不做多轮 agent loop
- 不要求所有工具都支持
- 只输出 plan steps、每步输入、每步产物、失败原因

阶段 3 完成标准：

- 只有复杂组合请求进入 TaskPlan。
- 简单问候、单店详情、单工具查询仍走旧链路。
- TaskPlan 的每一步都有输入、产物和失败原因。
- TaskPlan step 的执行结果必须写入统一 State / trace，不允许 step 私自调用其他 Agent。
- Replay Harness 能对比同一 case 在旧链路和 TaskPlan 链路下的 trace 差异。

### 阶段 4：完整实体对齐和回答校验

阶段 4 再处理更深层的证据归因、答案契约和回答校验问题。阶段 4 不只是新增功能，而是为受控多 Agent 输出增加质量守门：`EntityJoin` 负责多来源结果的一致性，`AnswerContract` 负责回答约束，`AnswerVerifier` 负责最终输出校验。

#### 2.10 RAG evidence 和 tool result 做完整实体级对齐

RAG evidence 和 tool result 必须按实体 join：

- `shop_id`
- `coupon_id`
- `blog_id`
- `package_id`
- `location_id`

禁止跨实体拼接：

- A 店评价
- B 店优惠券
- C 店营业状态

不能被 compose 成：

```text
推荐 A 店，因为它有券且现在营业。
```

建议新增 `EntityJoinResult`：

```text
EntityJoinResult
  - entity_id
  - entity_type
  - matched_evidence
  - matched_tool_results
  - covered_facets
  - missing_facets
  - conflicts
```

注意：阶段 1 的最小实体一致性检查只负责拦截明显串店；阶段 4 的完整实体对齐才负责候选聚合、证据归因、冲突解释和排序。

#### 2.11 增加 AnswerContract

`AnswerContract` 用于约束 compose：

- 用户问了什么
- 必须回答哪些 facets
- 每个 facet 需要什么证据或工具结果
- 哪些内容不能无证据生成
- 哪些 facet 可以 partial
- 哪些 slot 缺失时必须澄清

建议先从规则结构开始，不必第一版就由 LLM 生成完整 contract。

#### 2.12 增加 AnswerVerifier

`AnswerVerifier` 用于回答后校验：

- 是否回答原问题
- 是否覆盖 required facets
- 是否存在跨实体拼接
- 是否应该澄清却强答
- 是否把弱证据说成确定结论
- 是否把历史 memory 当成本轮显式约束
- 是否出现泛澄清

第一版可以只做 deterministic verifier：

- required facets 覆盖检查
- entity_id 一致性检查
- missing_slots 与回答模式检查
- response_mode 与措辞强度检查

阶段 4 完成标准：

- compose 前能看到每个候选实体绑定了哪些 evidence 和 tool result。
- `AnswerVerifier` 能检测 required facets 缺失、动态信息无工具结果、跨实体拼接。
- 回答失败能给出可追踪的 verifier reason。
- `answer_verifier_result` 必须至少包含 `passed / issues / suggested_response_mode / repair_hint`。
- Evaluation Harness 能统计 verifier 拦截率、误拦截率和修复建议分布。

### 阶段 5：runner 收敛评估，最后再做

#### 2.13 最后再评估是否合并 LangGraphWorkflowRunner 和 SequentialWorkflowRunner

runner 收敛不是阶段 1 目标。

建议顺序：

1. 先补 trace 字段，让两条路径输出可比。
2. 用同一批本地生活测试集跑 LangGraph 和 Sequential。
3. 对比节点经过顺序、routing decision、task_plan、tool_result、response_mode、final_answer。
4. 找出真实行为差异。
5. 再决定是合并 runner，还是保留一个 runner 加一个薄兼容层。

不建议在阶段 1 直接合并 runner，因为这会把“答非所问修复”和“执行引擎改造”混在一起，风险更高。

## 3. 分阶段落地点

后续工程实施必须按阶段推进。一个阶段验收完成后，再进入下一阶段；不要为了“顺手”把后续阶段内容提前塞进当前 PR。

### 3.1 阶段 0 落地点：先补 Harness 与观测

只做：

1. 增加 trace，不改变行为。
2. 建立 Replay Harness skeleton，用固定 case 回放主链路。
3. 建立 Tool Mock Harness skeleton，mock 工具成功、失败、缺 slot、实体不一致。
4. 建立 RAG Mock / Golden Evidence Harness skeleton，mock 固定 EvidencePack。
5. 建立 Evaluation Harness skeleton，先输出基础统计报告。
6. 记录 retrieval / tool plan 构造是否成功。
7. 记录 `evidence_quality / final_response_mode`。
8. 记录 `rag_plus_tool` 失败在哪一步。

不要做：

- 不改变 `required_action`
- 不改变回答文本
- 不改变 RAG / tool 执行策略

### 3.2 阶段 1 落地点：最高紧急止血

只做：

1. 对本地生活 terminal action 启用 route review，但只允许纠正高置信误判。
2. 增加 `UserNeed.required_facets`，先写入 state / trace。
3. 为 `required_facets` 增加 `data_source / freshness / missing_policy`。
4. 让 retrieval plan / tool plan 记录服务哪些 facets。
5. 增加最小实体一致性检查，先拦截明显跨店拼接。

不要做：

- 不删除 `required_action`
- 不做 TaskPlan
- 不做完整 `EntityJoinResult`
- 不合并两个 runner

### 3.3 阶段 2 落地点：改善回答兜底

只做：

1. 将 `no_answer / weak_answer` 拆成分级响应。
2. 将泛澄清替换为 slot 澄清。
3. 给 `rag_plus_tool` 增加失败原因 trace 和 partial answer。

不要做：

- 不重写 RAG
- 不重写 memory
- 不引入复杂 agent loop
- 不把所有问题迁入 plan_execute

### 3.4 阶段 3 落地点：TaskPlan 小范围试点

只做：

1. 为复杂本地生活请求生成 `task_plan`。
2. 只覆盖“推荐 + 动态状态 + 优惠券”这类组合任务。
3. 保留 `required_action`，让 `task_plan` 与旧链路并行。

不要做：

- 不让简单请求进入 TaskPlan
- 不替换所有 routing
- 不做多轮 agent loop

### 3.5 阶段 4 落地点：证据和答案强校验

只做：

1. 实现完整 `EntityJoinResult`。
2. 增加 `AnswerContract`。
3. 增加 deterministic `AnswerVerifier`。

不要做：

- 不合并 runner
- 不引入 LLM judge 作为第一版 verifier

### 3.6 阶段 5 落地点：runner 收敛评估

只做：

1. 对比 LangGraph 与 Sequential 在同一测试集下的 trace。
2. 找出真实行为差异。
3. 再决定是否合并 runner 或保留薄兼容层。

不要做：

- 不在没有 trace 对比的情况下合并 runner
- 不把 runner 收敛和业务止血混在一个阶段

## 4. 风险提示

### 4.1 route_review 可能增加误触发

如果二次复核过于激进，可能把普通寒暄、个人资料更新、无效输入误判成本地生活任务。

控制方式：

- 只对本地生活信号明显的 query 触发。
- 只允许从 terminal action 提升到可执行 action，不轻易从可执行 action 降级。
- trace 中记录触发原因和纠正前后 action。

### 4.2 partial_grounded 可能诱发过度回答

分级响应不是降低事实要求。它的风险是模型把弱证据说成强结论。

控制方式：

- `partial_grounded` 必须列出已覆盖和未覆盖 facets。
- 不能把未验证的优惠、营业状态、距离说成确定结论。
- 动态信息优先来自 tool result，而不是静态 RAG。

### 4.3 memory 可能污染当前 query

memory 可以帮助理解“它 / 这家”，也可能把新问题带回旧话题。

控制方式：

- 增加 `MemoryRelevanceGate`。
- 当前 query 显式店名、品类、地点优先。
- 新 query 与旧 memory 不一致时，降低旧 memory 注入权重。

### 4.4 TaskPlan 可能被做重

TaskPlan 的目的不是引入复杂 agent，而是表达组合任务。

控制方式：

- 阶段 3 只对复杂本地生活任务启用。
- plan steps 保持可枚举、可测试。
- simple query 保留旧链路。

### 4.5 runner 收敛可能掩盖业务问题

如果过早合并 runner，可能把业务链路问题和执行引擎差异混在一起。

控制方式：

- 阶段 0-3 先通过 trace 把行为差异显性化。
- 阶段 5 再根据测试结果决定收敛方式。

## 5. 修改是否有效：验收指标

### 5.1 路由相关指标

- `initial_action` 分布
- `route_review` 触发率
- `direct_answer` 被纠正为 `rag_retrieval / tool_call / rag_plus_tool / task_plan` 的比例
- `clarify` 被纠正为可回答任务的比例
- terminal early exit 比例
- terminal action 中本地生活 query 占比
- route review 后用户首答可用率

### 5.2 RAG 相关指标

- `retrieval_plan` 构造成功率
- `evidence_after_gate` 数量
- `partial_grounded` 比例
- `weak_answer` 比例
- `no_answer` 比例
- top evidence 与用户 `required_facets` 的覆盖率
- top evidence 与 `required_facets.data_source=static_rag` 的覆盖率
- evidence 的 `shop_id / category / city / role` 一致性
- `entity_mismatch / cross_entity_risk` 触发率
- `required_role_missing` 分布

### 5.3 toolcall 相关指标

- `tool_plan` 构造成功率
- `tool_slot_missing` 原因分布
- `coupon` 调用成功率
- `open_status` 调用成功率
- `distance_eta` 调用成功率
- 动态 facets 使用 tool result 覆盖率
- 动态 facets 被静态 RAG 强答的拦截次数
- `rag_plus_tool` 完整执行率
- tool result 与候选实体 join 成功率
- 工具失败后的 partial answer 比例

### 5.4 回答质量指标

- 是否覆盖用户 `required_facets`
- 是否出现跨实体拼接
- 是否频繁泛澄清
- 首答可用率
- 用户二次追问率
- 用户重复改写同一问题的比例
- `partial_grounded` 是否明确边界
- `ask_clarification` 是否命中最小缺失 slot
- 动态信息是否来自 tool result
- 是否把动态 facet 当成静态证据回答
- 是否触发最小实体一致性拦截

### 5.5 工程可观测指标

- 每轮是否记录 `UserNeed`
- 每轮是否记录 `required_facets`
- 每个 facet 是否记录 `data_source / freshness / missing_policy`
- 每轮是否记录 route review 前后 action
- 每轮是否记录 memory 注入原因
- 每轮是否记录 retrieval / tool plan 失败原因
- 每轮是否记录最小实体一致性检查结果
- 每轮是否记录 answer verifier 结果
- LangGraph 与 Sequential 同测试输入的 trace 差异

## 6. 建议补充的测试集

### 6.1 多意图组合

```text
用户：附近有没有适合约会、现在营业、最好有券的火锅？
期望：RAG + search_restaurants + check_open_status + get_coupon_list
```

验收点：

- 解析出 `location / category / scene_fit / open_status / coupon / recommendation_reason`
- 如果缺当前位置，只问位置，不泛问“请补充更多信息”
- 如果有候选但券缺失，允许 partial answer

### 6.2 上下文指代

```text
第一轮：海底捞怎么样？
第二轮：那它现在有券吗？
期望：能识别“它”指代海底捞，并调用券工具
```

验收点：

- memory / recent_entities 参与指代消解
- 当前 query 的 `coupon` facet 被识别
- 不回答成“海底捞整体评价”

### 6.3 新 query 覆盖旧 memory

```text
第一轮：海底捞有没有券？
第二轮：附近有没有安静适合学习的咖啡店？
期望：不能继续围绕海底捞回答
```

验收点：

- `MemoryRelevanceGate` 判断新 query 与旧实体不一致
- required facets 切换为 `location / category / scene_fit / recommendation_reason`
- 不注入或低权重注入海底捞 memory

### 6.4 只缺一个 slot

```text
用户：这个套餐今天还能用吗？
期望：如果有最近套餐上下文，则直接查；如果没有，则问具体套餐/店名
```

验收点：

- 有上下文时解析 `package_id / shop_id`
- 无上下文时最小澄清：“你说的是哪家店的哪个套餐？”
- 不泛化成“请补充更多上下文”

### 6.5 证据不足但可部分回答

```text
用户：这家店适合带父母吗？
期望：如果只有环境/口味证据，没有停车/包间证据，应 partial_grounded，而不是直接拒答
```

验收点：

- 已覆盖 facets：环境、口味、评价氛围
- 未覆盖 facets：停车、包间、无障碍、排队情况
- 回答给出边界，不编造缺失项

### 6.6 防跨实体拼接

```text
输入数据：A 店有环境证据，B 店有券，C 店营业
期望：不能合成“推荐 A 店，因为它有券且营业”
```

验收点：

- `EntityJoinResult` 标记证据分属不同实体
- `AnswerVerifier` 拦截跨实体推荐理由
- 输出改为候选对比或 partial answer

### 6.7 初始路由误判 direct_answer

```text
用户：附近有什么不踩雷的烤肉，最好人均别太高？
期望：不能 direct_answer，需要进入本地生活推荐链路
```

验收点：

- route review 识别 `附近 / 不踩雷 / 烤肉 / 人均`
- required facets 包含 `location / category / price / recommendation_reason / review_pitfall`
- 进入 RAG 或 TaskPlan

### 6.8 初始路由误判 clarify

```text
用户：刚才那家现在还开着吗？
期望：如果 recent_entities 有候选店，应调用 open_status；如果没有，问“你是问哪家店？”
```

验收点：

- 有上下文时不能继续澄清
- 无上下文时只问店名
- 不回答成泛泛营业时间说明

### 6.9 工具缺 slot 但 RAG 可回答部分

```text
用户：这家店有啥推荐菜？现在能不能去？
期望：推荐菜可用 RAG，营业状态走 tool；工具缺时间时默认“现在”，缺店时澄清
```

验收点：

- `shop_detail / open_status` 被拆成两个 facets
- RAG 成功但 tool 缺 slot 时输出 partial answer
- 不因 tool plan 失败丢掉 RAG 结果

### 6.10 动态信息不得只靠静态 RAG

```text
用户：这张券今天还能用吗？
期望：必须优先工具查询券状态；RAG 只能提供背景，不得给确定可用结论
```

验收点：

- `coupon` 和 `valid_time` 识别为动态 facet
- 无 tool result 时不能强答“能用”
- 有最近券上下文时直接查，无上下文时问具体券/店名

## 7. 后续工程实现建议

### 7.1 推荐的数据结构演进

建议最小新增：

```text
RequiredFacet
  name: str
  required: bool
  data_source: slot | static_rag | dynamic_tool | memory | client_context | mixed
  freshness: static_ok | near_realtime_required
  entity_keys: list[str]
  missing_policy: partial_grounded | ask_clarification | no_answer

UserNeed
  intent: str
  slots: dict
  constraints: dict
  required_facets: list[RequiredFacet]
  optional_facets: list[RequiredFacet]
  missing_slots: list[str]
  context_refs: list[dict]

EntityConsistencyMinimal
  checked: bool
  passed: bool
  entity_keys: dict
  mismatch_reason: str | None
  cross_entity_risk: bool

TaskPlan
  steps: list[TaskStep]
  required_facets: list[RequiredFacet]
  can_fallback_to_legacy: bool

AnswerContract
  original_query: str
  required_facets: list[RequiredFacet]
  evidence_requirements: dict
  tool_requirements: dict
  forbidden_without_evidence: list[str]

AnswerVerifierResult
  passed: bool
  issues: list[str]
  suggested_response_mode: str
```


补充 Harness 相关结构：

```text
HarnessCase
  case_id: str
  query: str
  session_context: dict
  client_context: dict
  mock_rag: dict | None
  mock_tools: dict | None
  expected_trace: dict
  expected_response_mode: str | None
  forbidden_behaviors: list[str]

HarnessRunResult
  case_id: str
  passed: bool
  actual_trace: dict
  actual_response_mode: str
  actual_answer: str
  failures: list[str]

ToolMockResult
  tool_name: str
  status: success | failed | timeout | missing_slot
  payload: dict
  failure_reason: str | None

GoldenEvidencePack
  evidence_items: list[dict]
  covered_facets: list[str]
  missing_facets: list[str]
  entity_keys: dict

EvaluationReport
  total_cases: int
  passed_cases: int
  failed_cases: int
  failure_buckets: dict
  metric_summary: dict
```

### 7.2 推荐的 trace 字段

```text
trace
  trace_id
  case_id | None
  harness_mode: off | replay | mock
  input_quality
  user_need
  initial_routing_decision
  route_review_decision
  memory_relevance
  required_facets
  required_facets_source_constraints
  retrieval_plan
  retrieval_plan_failure_reason
  evidence_quality
  evidence_after_gate_count
  tool_plan
  tool_plan_failure_reason
  tool_slot_missing
  entity_consistency_minimal
  entity_join_result
  answer_contract
  answer_verifier_result
  final_response_mode
  harness_assertions | None
```

### 7.3 推荐的实施顺序

这里的顺序只表示工程依赖，不表示让 Codex 一次性完成。实际执行请按下一章的多轮任务拆分。

1. 阶段 0-Harness：先补 Trace / Replay / Tool Mock / RAG Golden Evidence / Evaluation Harness skeleton，不改变线上行为。
2. 阶段 1-RouteReview：只纠正高置信 early terminal 误判。
3. 阶段 1-Facets：让 `required_facets` 贯穿 retrieval/tool/compose，并带上数据源约束。
4. 阶段 1-MinEntityCheck：前置最小实体一致性检查。
5. 阶段 2-ResponseMode：把 `no_answer` 拆成分级响应。
6. 阶段 2-SlotClarify：将泛澄清改为 slot 澄清。
7. 阶段 2-RagPlusToolPartial：让 RAG 成功但 tool 失败时可以 partial answer。
8. 阶段 3-TaskPlan：仅复杂本地生活请求启用。
9. 阶段 4-EntityJoin：完整实体对齐和候选聚合。
10. 阶段 4-AnswerVerifier：让回答质量可校验。
11. 阶段 5-Runner：基于 trace 差异决定是否收敛 runner。

## 8. 给 Codex 的多轮实施任务拆分

不要让 Codex 一次性全做。每一轮只完成一个可验证的小目标，产出代码、测试和 trace 证据。建议按阶段开多个独立任务；同一阶段内也可以拆成多个 PR，但不能跨阶段夹带后续内容。

### 阶段 0 / 第 1 轮：只补 Harness 与 trace，不改变行为

目标：

- 在不改变线上决策的前提下，把现有 routing、RAG、tool、compose 的关键状态打出来。
- 建立最小可用的 Replay / Tool Mock / RAG Golden Evidence / Evaluation Harness skeleton。
- 建立最小可用的 Replay / Tool Mock / RAG Golden Evidence / Evaluation Harness skeleton。

代码落点：

- `learning-agent-service/src/learning_agent_service/application/workflow/adapters.py:376`
- `learning-agent-service/src/learning_agent_service/application/workflow/adapters.py:1096`
- `learning-agent-service/src/learning_agent_service/application/workflow/adapters.py:1265`

任务边界：

- 只写入 `turn.extra` 或 runtime metrics。
- Harness 只用于测试、回放、mock 和评估，不参与线上主链路决策。
- 不改变 `required_action`。
- 不改变最终回答。
- 不实现阶段 1-5 的任何行为改变。

验收：

- 测试能看到 `initial_routing_decision / evidence_quality / final_response_mode`。
- Replay Harness 能运行固定 case 并输出 trace。
- Tool Mock Harness 能模拟成功、失败、缺 slot、实体不一致。
- RAG Golden Evidence Harness 能注入固定 EvidencePack。
- Evaluation Harness 能输出基础统计报告。
- 原有测试不因回答文本变化失败。

### 阶段 1 / 第 2 轮：增加 RequiredFacets 解析和数据源约束

目标：

- 为本地生活请求生成 `required_facets`，并区分静态和动态数据源。

代码落点：

- `learning-agent-service/src/learning_agent_service/domain/contracts.py:332`
- `learning-agent-service/src/learning_agent_service/application/workflow/adapters.py:434`
- `learning-agent-service/src/learning_agent_service/application/routing.py:386`

任务边界：

- 第一版可写入 `RoutingDecision.extra["user_need"]`。
- 不要求修改所有 planner。
- 不要求引入新数据库或新工具。

验收：

- “附近有没有适合约会、现在营业、最好有券的火锅？”能解析出 `scene_fit / location / category / open_status / coupon / recommendation_reason`。
- `open_status / coupon / distance_eta` 被标记为 `dynamic_tool`。
- `scene_fit / shop_detail` 被标记为 `static_rag`。

### 阶段 1 / 第 3 轮：route_review 只纠正高置信 early terminal 误判

目标：

- 避免本地生活请求被 `direct_answer / clarify / no_op` 过早短路。

代码落点：

- `learning-agent-service/src/learning_agent_service/application/workflow/adapters.py:376`
- `learning-agent-service/src/learning_agent_service/application/workflow/adapters.py:434`
- `learning-agent-service/src/learning_agent_service/application/workflow/subgraphs.py:337`

任务边界：

- 只对本地生活信号明显的 query 触发。
- 只允许 terminal action 提升为可执行 action。
- 不做大模型 agent loop。

验收：

- “附近有什么不踩雷的烤肉，最好人均别太高？”不能停在 `direct_answer`。
- “刚才那家现在还开着吗？”有 recent entity 时不能停在泛澄清。

### 阶段 1 / 第 4 轮：retrieval/tool plan 透传 RequiredFacets

目标：

- 让 RAG 和 tool plan 都知道自己服务哪些 facets。

代码落点：

- `learning-agent-service/src/learning_agent_service/application/routing.py:1101`
- `learning-agent-service/src/learning_agent_service/application/routing.py:1153`
- `learning-agent-service/src/learning_agent_service/domain/contracts.py:100`
- `learning-agent-service/src/learning_agent_service/domain/contracts.py:421`

任务边界：

- 可先写入 `RetrievalPlan.extra["required_facets"]` 和 tool selection extra。
- 不要求重写 retrieval ranking。

验收：

- RAG plan 只承诺 `scene_fit / shop_detail / recommendation_reason` 等静态 facets。
- tool plan 只承诺 `coupon / open_status / distance_eta` 等动态 facets。
- 缺 slot 时能记录具体 `tool_slot_missing`。

### 阶段 1 / 第 5 轮：前置最小实体一致性检查

目标：

- 先拦住明显跨实体拼接，不等阶段 4 完整 entity join。

代码落点：

- `learning-agent-service/src/learning_agent_service/application/routing.py:898`
- `learning-agent-service/src/learning_agent_service/application/workflow/adapters.py:1096`
- `learning-agent-service/src/learning_agent_service/tools/service.py:884`

任务边界：

- 只检查 `shop_id / coupon_id / package_id` 等已有字段。
- 不新增复杂实体图谱。
- 不做候选聚合排序。

验收：

- A 店评价、B 店券、C 店营业状态不能合成同一家店。
- 检测到不一致时 response mode 降级为 `partial_grounded` 或 `ask_clarification`。

### 阶段 2 / 第 6 轮：分级响应替代硬 no_answer

目标：

- 将 `no_answer / weak_answer` 扩展为 `grounded / partial_grounded / weak_answer / ask_clarification / no_answer`。

代码落点：

- `learning-agent-service/src/learning_agent_service/domain/contracts.py:297`
- `learning-agent-service/src/learning_agent_service/application/routing.py:898`
- `learning-agent-service/src/learning_agent_service/tools/service.py:884`
- `learning-agent-service/src/learning_agent_service/tools/service.py:1258`

任务边界：

- 不降低证据门控。
- 只改变输出分级和边界表达。

验收：

- “这家店适合带父母吗？”在只有环境/口味证据时输出 `partial_grounded`。
- 缺动态工具结果时不能把券/营业说成确定结论。

### 阶段 2 / 第 7 轮：slot 化澄清

目标：

- 把泛澄清改成最小缺失 slot 问题。

代码落点：

- `learning-agent-service/src/learning_agent_service/application/routing.py:1101`
- `learning-agent-service/src/learning_agent_service/application/routing.py:1153`
- `learning-agent-service/src/learning_agent_service/tools/service.py:884`

任务边界：

- 不做复杂多轮表单。
- 只处理城市、商圈、店名、套餐、时间、人数、当前位置等本地生活常见 slot。

验收：

- 缺城市问城市或商圈。
- 缺店名问“你是问刚才那家店，还是要重新推荐？”
- 缺时间问“现在还是某个具体时间？”

### 阶段 2 / 第 8 轮：rag_plus_tool 失败路径 partial answer

目标：

- 避免 RAG 成功但 tool 失败时把整轮退化为泛澄清。

代码落点：

- `learning-agent-service/src/learning_agent_service/application/routing.py:1101`
- `learning-agent-service/src/learning_agent_service/application/routing.py:1153`
- `learning-agent-service/src/learning_agent_service/application/workflow/subgraphs.py:355`
- `learning-agent-service/src/learning_agent_service/tools/service.py:884`

任务边界：

- 不引入 TaskPlan。
- 只对 `rag_plus_tool` 当前串联链路做可观测和 partial answer。

验收：

- RAG 有推荐理由、tool 缺券结果时，先给推荐理由，并明确“券信息暂未确认”。
- tool plan missing 时 trace 中有具体原因。

### 阶段 3 / 第 9 轮：TaskPlan 试点

目标：

- 只让复杂本地生活请求进入 `TaskPlan`，不要替换所有 `required_action`。

代码落点：

- `learning-agent-service/src/learning_agent_service/domain/contracts.py:184`
- `learning-agent-service/src/learning_agent_service/application/workflow/plan_execute.py`
- `learning-agent-service/src/learning_agent_service/application/workflow/subgraphs.py:337`

任务边界：

- 简单请求继续走旧链路。
- 第一版 TaskPlan 只覆盖推荐 + 动态状态 + 优惠券组合场景。

验收：

- “推荐一家适合约会、现在营业、最好有券的火锅店”生成 `resolve_location / search_restaurants / retrieve_scene_evidence / check_open_status / get_coupon_list / entity_join / rank_candidates / compose_answer / answer_verify`。
- 普通问候、单店详情不进入 TaskPlan。

### 阶段 4 / 第 10 轮：AnswerVerifier 试点

目标：

- 先让回答质量可校验，拦截 required facets 缺失、动态信息无工具结果、最小实体不一致。

代码落点：

- `learning-agent-service/src/learning_agent_service/application/workflow/adapters.py:1265`
- `learning-agent-service/src/learning_agent_service/tools/service.py:884`

任务边界：

- 不引入 LLM judge。
- 不合并 runner。
- 不做完整端到端评分系统。

验收：

- AnswerVerifier 能检测 required facets 缺失、动态信息无工具结果、最小实体不一致。
- verifier 失败时能写入 trace reason。

### 阶段 5 / 第 11 轮：runner 对齐预研

目标：

- 在不合并 runner 的前提下，先让两条 runner 路径可比较。

代码落点：

- `learning-agent-service/src/learning_agent_service/application/workflow/builder.py:61`
- `learning-agent-service/src/learning_agent_service/application/workflow/runner.py:47`

任务边界：

- 不直接合并 runner。
- 不改业务策略。
- 不和阶段 1-4 的业务修复混在同一个 PR。

验收：

- 同一测试集能输出 LangGraph 和 Sequential 的 trace 差异。
- 基于差异报告再决定是否合并 runner。


## 9. Feature Flag 与回滚策略

所有会改变线上行为的阶段都必须支持 feature flag 或配置关闭。阶段 0 的 harness / trace 可以默认在测试环境打开；阶段 1 起的行为改变必须支持灰度和快速回滚。

建议配置：

```text
enable_trace_harness
enable_replay_harness
enable_tool_mock_harness
enable_rag_golden_evidence_harness
enable_evaluation_harness
enable_required_facets
enable_route_review
enable_required_facets_to_plans
enable_min_entity_consistency_check
enable_partial_grounded
enable_slot_clarify
enable_rag_plus_tool_partial_answer
enable_task_plan_for_local_life
enable_answer_verifier
```

启用规则：

1. 阶段 0 默认只打开 harness / trace，不改变线上行为。
2. 阶段 1 起任何行为改变都必须可通过 flag 关闭。
3. `route_review` 必须能单独关闭，避免误触发影响普通问答。
4. `min_entity_consistency_check` 必须能单独关闭，但默认建议在测试环境打开。
5. `partial_grounded` 和 `slot_clarify` 必须能分别灰度。
6. `TaskPlan` 必须有独立 flag，且只允许复杂本地生活请求进入。
7. `AnswerVerifier` 必须支持 `warn_only` 和 `enforce` 两种模式。
8. runner 收敛不通过 feature flag 直接上线，必须先做阶段 5 trace 差异对比。

回滚要求：

- 每个阶段的 PR 必须说明新增了哪些 flag。
- 每个 flag 必须有默认值、测试环境建议值、生产环境建议值。
- 如果线上出现误路由、误澄清、过度 partial 或 verifier 误拦截，应优先关闭对应 flag，而不是回滚全部代码。

## 10. 实施结论

建议路线是：

- 阶段 0 先建立 Harness 与观测基线：补 Trace / Replay / Tool Mock / RAG Golden Evidence / Evaluation Harness，不改变行为。
- 阶段 1 处理最高紧急问题：route review、RequiredFacets 数据源约束、最小实体一致性检查。
- 阶段 2 再改善回答兜底：分级响应、slot 澄清、`rag_plus_tool` partial answer。
- 阶段 3 再计划化：引入 TaskPlan，但与 required_action 并行。
- 阶段 4 做证据到答案强校验：完整实体对齐、AnswerContract、AnswerVerifier。
- 阶段 5 最后评估 runner 收敛：先对齐 trace，再决定是否合并。

只要阶段 1 改对，用户应该先感受到三件事：

- 不再那么容易答非所问
- 不再把动态信息只靠静态 RAG 强答
- 不再把 A 店证据、B 店券、C 店营业状态拼成同一家店

这比第一版就合并 runner、重写全部 RAG、重写全部 memory 更稳，也更容易通过指标证明有效。


## 修改摘要：多 Agent 演进与 Harness Engineering 补充

本次版本在不推翻原阶段 0-5 主线的前提下，新增了两条横向工程约束：

1. 受控多 Agent 演进原则：明确主编排器仍由 LangGraph / Workflow Runner 负责，其他 agent-like 能力作为固定输入输出的 node / subgraph，不允许自由 Agent 互相聊天。
2. Harness Engineering：明确阶段 0 不只是 trace，而是要建立 Trace、Replay、Tool Mock、RAG Golden Evidence、Evaluation 五类测试与评估能力。

本次特别强化：

- 新增 Agent-like 模块边界表。
- 新增 State 字段所有权表。
- 将阶段 0 升级为“Harness 与观测基线”。
- 新增 Harness 数据结构建议。
- 新增 Feature Flag 与回滚策略。
- 强化阶段 1、阶段 3、阶段 4 的多 Agent 演进边界和 harness 验收要求。

后续 Codex 第一次执行时，仍然只允许做阶段 0：补 Harness 与 trace，不改变任何线上行为。禁止第一次就做 RouteReview 行为改变、TaskPlan、EntityJoinResult、AnswerVerifier、runner 合并、全量 RAG 重写、全量 memory 重写、删除 `required_action` 或把所有请求迁入 `plan_execute_subgraph`。
