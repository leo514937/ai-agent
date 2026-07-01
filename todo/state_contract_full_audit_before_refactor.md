# GraphState / SessionState / CoreSchema 全量契约审计报告

审计时间：2026-06-30  
审计范围：`local_life_agent/` 当前单主链路、状态层、核心 schema、节点读写契约、会话持久化边界  
审计目的：在任何业务改造前，先把“什么状态属于哪一层、谁能读写、谁负责持久化、哪些字段绝不能混用”说清楚

## 结论摘要

当前项目已经形成了比较清晰的三层结构：

1. `GraphState` 承担单轮图执行状态和少量会话镜像字段。
2. `SessionState` 承担跨轮持久化记忆。
3. `CandidateSet` / `ResolveShopResult` / `EvidencePack` / `DecisionPlan` / `AnswerPlan` / `SessionWriteDirective` 承担各阶段核心 schema。

但现阶段仍然存在几个需要在 refactor 前明确锁死的风险点：

1. `GraphState` 里同时混有运行态、候选态、证据态、决策态、回答态和会话镜像态，边界已经能用，但还不够“强约束”。
2. `target_resolution_status`、`resolve_shop_result`、`resolution_stage` 仍在承载过渡语义，虽然已经比早期好很多，但仍然需要把“候选集解析”“单目标解析”“胜者决策”彻底拆开。
3. `ranking_snapshot` 依然是证据层的有效输入输出，不应被误当成最终 winner 状态。
4. `state_update_plan` 是唯一可靠的会话持久化出口，不能再出现绕过它直接写 session 的新路径。
5. `schemas.py` 里存在重复的 `ComparisonTurnArtifact` 定义，属于容易引起维护歧义的契约噪音。

整体判断：**当前实现已经具备 refactor 所需的契约雏形，但还没有达到“字段语义完全单一化”的程度。**  
下一步改造应当优先收口状态语义，而不是先扩路由、扩 workflow 或堆业务分支。

## 状态分层现状

### 1. GraphState

`GraphState` 是 LangGraph 单轮执行状态，定义在 [local_life_agent/domain/graph_state.py](/D:/javacode/hm-dianping/local_life_agent/domain/graph_state.py#L31)。

它当前承担的内容可以分成几组：

- 输入与路由：`trace_id`、`turn_id`、`session_id`、`user_id`、`raw_text`、`normalized_text`、`top_intent`、`task_type`
- 候选与目标：`candidate_spec`、`candidate_set`、`effective_candidate_set`、`resolved_target`、`resolve_shop_result`、`target_resolution_status`、`resolution_stage`
- 会话镜像：`current_shop`、`last_recommendation_list`、`active_constraints`、`comparison_targets`、`comparison_result`、`pending_clarification`
- 执行与证据：`execution_plan`、`validated_plan`、`tool_results`、`tool_result_set`、`evidence_pack`
- 决策与回答：`p2_decision_plan`、`decision_review_result`、`answer_plan`、`final_response`
- 状态更新：`state_update_plan`

这说明 `GraphState` 已经不是纯“临时变量容器”，而是一个混合型运行态对象。  
这个设计在 LangGraph 下是可行的，但前提是各字段的语义边界必须非常稳定。

### 2. SessionState

`SessionState` 是跨轮持久化模型，定义在 [local_life_agent/domain/state.py](/D:/javacode/hm-dianping/local_life_agent/domain/state.py#L15)。

当前关键字段包括：

- `current_shop`
- `last_recommendation_list`
- `active_constraints`
- `pending_clarification`
- `comparison_targets`
- `comparison_result`
- `suggested_shop`
- `last_candidate_spec`
- `last_candidate_set`
- `active_goal`
- `review_results`
- `last_decision_plan`
- `replan_counters`

这个层级的核心职责是“跨轮记忆”，不是“当前轮推理”。

### 3. Core Schema

核心 schema 主要定义在 [local_life_agent/domain/schemas.py](/D:/javacode/hm-dianping/local_life_agent/domain/schemas.py#L163) 之后的各段：

- `PendingClarification`
- `EvidencePack`
- `ResolveShopResult`
- `AnswerPlan`
- `ComparisonTurnArtifact`
- `DecisionPlan`

这些 schema 已经把系统切成了“澄清、候选、证据、决策、回答”五个阶段。  
这部分是当前实现里最接近正确架构的地方，后续 refactor 应该尽量沿着这些结构收口，而不是另起一套新状态。

## 节点读写契约

### 1. intake_guard_router

它负责会话加载和首轮镜像，通常会把 session 内容铺到 `GraphState` 中。  
从 `GraphState` 的字段设计看，它会读取并初始化 `current_shop`、`last_recommendation_list`、`comparison_targets`、`pending_clarification` 这一类会话记忆。

这一步的契约要点是：

- 只做“加载”和“镜像”
- 不做新事实推导
- 不把 session 记忆伪装成当前轮结论

### 2. merge_clarification

它负责把“待澄清结果”恢复成当前可继续执行的任务上下文。  
这里最重要的是避免把 pending clarification 误升级成已确认事实。

### 3. understanding_subgraph

这个子图会处理上下文恢复、引用解析、比较目标恢复等语义。  
它能写入 `resolved_target`、`comparison_targets`、`comparison_target_resolution` 一类字段。

这一步的契约重点是：

- 解析结果可以进入候选/目标层
- 解析结果不等于最终 winner
- 比较目标和单店目标不能混成一个“解析成功”状态

### 4. planning_subgraph

这是当前最关键的状态分岔节点之一，定义在 [local_life_agent/engine/subgraphs/planning_subgraph.py](/D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/planning_subgraph.py#L346)。

它的职责已经比较明确：

- 产生 `candidate_set`
- 产生 `effective_candidate_set`
- 写入 `resolve_shop_result`
- 写入 `resolution_stage`
- 在需要时写入 `pending_clarification`
- 为后续 evidence / decision 提供输入

从当前实现看，`planning_subgraph` 已经区分了几种场景：

- `CANDIDATE_SET_RESOLVED`
- `TARGET_RESOLVED`
- `TARGET_NOT_FOUND`
- `AMBIGUOUS`

这说明系统已经开始从“一个 resolved 状态包打天下”转向“三段式状态”。

### 5. execution_review_subgraph

定义在 [local_life_agent/engine/subgraphs/execution_review_subgraph.py](/D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/execution_review_subgraph.py#L103)。

它的职责顺序非常清楚：

1. 执行工具，产出 `tool_results` / `tool_result_set`
2. 构建 `evidence_pack`
3. 做 `evidence_review`
4. 产出 `p2_decision_plan`
5. 做 `decision_review`

这里最重要的契约是：

- 工具结果不能直接跳到回答层
- 证据包先于决策
- 决策先于回答

### 6. response_subgraph

定义在 [local_life_agent/engine/subgraphs/response_subgraph.py](/D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/response_subgraph.py#L93)。

它负责：

- 从 `p2_decision_plan` + `evidence_pack` 构造 `answer_plan`
- 生成最终回答
- 进行 verifier 校验
- fallback / clarify / rewrite

这一步的契约核心是：

- `answer_plan` 只能表达决策，不能重选 winner
- `final_response` 不能新增 `EvidencePack` 外事实
- verifier 是回答出图的最后一道边界

### 7. state_update_plan

这是本次审计里最重要的持久化边界，定义在 [local_life_agent/engine/subgraphs/state_update_plan.py](/D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/state_update_plan.py#L1)。

它会调用 [local_life_agent/planning/plans/state_update_planner.py](/D:/javacode/hm-dianping/local_life_agent/planning/plans/state_update_planner.py#L1)，再把结果写回 session store。

这意味着：

- `state_update_planner` 决定“哪些字段该持久化”
- `state_update_plan` 决定“什么时候真正落盘”
- 其他节点不应再直接写 session 存储

这个边界是正确的，后续 refactor 应该围绕它展开，而不是绕开它另起持久化逻辑。

## 关键字段契约盘点

### 1. `current_shop`

当前结论：

- 它是跨轮会话记忆字段。
- 它应当只代表“当前单一目标店”。
- 它不应该被推荐列表、比较列表、候选集列表代替。

当前代码里已经尽量把它限制在 true single target 场景。  
在 [local_life_agent/planning/plans/state_update_planner.py](/D:/javacode/hm-dianping/local_life_agent/planning/plans/state_update_planner.py#L146) 附近能看到明确约束：`RESOLVED` 与 `CANDIDATE_SET_RESOLVED` 被区别处理，只有真单目标才写 `current_shop`。

### 2. `last_recommendation_list`

当前结论：

- 它是推荐结果的多轮记忆。
- 它应服务于“第二家”“第一家”“刚才那家”这类多轮指代。
- 它不能等同最终排名，也不能当作唯一 winner。

### 3. `comparison_targets` / `comparison_result`

当前结论：

- 它们是比较场景的跨轮记忆。
- 它们应在比较流中持久化。
- 它们不能覆盖推荐流记忆，也不能反过来污染单店流。

### 4. `pending_clarification`

当前结论：

- 它表示待澄清，不表示已确认事实。
- 它可跨轮保留，但必须可被 topic switch / topic restore 清理。
- 它是 fallback / review 的输出，不是决策结果。

### 5. `candidate_set` / `effective_candidate_set`

当前结论：

- `candidate_set` 表示候选召回结果。
- `effective_candidate_set` 表示后续执行真正使用的候选集合。
- 它们都不应直接等价为最终目标。

### 6. `resolved_target` / `resolve_shop_result`

当前结论：

- 它们代表目标解析结果。
- 它们应和 `candidate_set` 区分。
- 它们不能自动等于 winner。

### 7. `resolution_stage`

当前结论：

- 它是目前最适合承接“候选集已找到 / 单目标已确认 / 胜者已决策”这类阶段语义的字段。
- 它应该逐步成为比 `target_resolution_status` 更稳定的阶段表示。

### 8. `p2_decision_plan`

当前结论：

- 它是决策层的结构化输出。
- 它才是 `winner_shop_id`、`ranking`、`claims`、`caveats` 的载体。
- 它不应被 candidate 或 evidence 语义取代。

### 9. `answer_plan`

当前结论：

- 它只管回答结构与表达策略。
- 它不应改变决策。
- 它不能新增证据外事实。

### 10. `tool_results` / `tool_result_set`

当前结论：

- 它们是工具执行结果。
- 它们不能直接越过 evidence 层进入最终回答。
- `tool_result_set` 只是兼容 / 旧命名载体，不应成为新的事实来源。

## 关键 schema 审计

### 1. `EvidencePack`

定义在 [local_life_agent/domain/schemas.py](/D:/javacode/hm-dianping/local_life_agent/domain/schemas.py#L507)。

它目前已经承担了：

- `ranking_snapshot`
- `comparison_matrix`
- `tool_results`

审计判断：

- 它仍然是事实依据层。
- 它不应直接选择 winner。
- 它是 answer / verifier 的事实输入，而不是最终答复本身。

### 2. `ResolveShopResult`

定义在 [local_life_agent/domain/schemas.py](/D:/javacode/hm-dianping/local_life_agent/domain/schemas.py#L541)。

它的状态已经区分了：

- `RESOLVED`
- `AMBIGUOUS`
- `LOW_CONFIDENCE`
- `NOT_FOUND`

审计判断：

- 这比早期“只有 resolved / not_found”要强很多。
- 但仍要防止它被直接升格为 winner。

### 3. `DecisionPlan`

定义在 [local_life_agent/domain/schemas.py](/D:/javacode/hm-dianping/local_life_agent/domain/schemas.py#L694)。

审计判断：

- 它是 winner / ranking / claim 的真正承载体。
- `winner_shop_id` 属于 decision 层，不属于 candidate 层。
- 这里是“胜者语义”的正确落点。

### 4. `AnswerPlan`

定义在 [local_life_agent/domain/schemas.py](/D:/javacode/hm-dianping/local_life_agent/domain/schemas.py#L604)。

审计判断：

- 它是回答控制层。
- 它应该控制表达方式，而不是控制事实选择。

### 5. 重复定义问题

`ComparisonTurnArtifact` 在 [local_life_agent/domain/schemas.py](/D:/javacode/hm-dianping/local_life_agent/domain/schemas.py#L634) 和 [local_life_agent/domain/schemas.py](/D:/javacode/hm-dianping/local_life_agent/domain/schemas.py#L650) 出现了重复定义。

这不是立即致命的问题，但属于明显的契约噪音：

- 容易让后续维护者误判哪一个是生效定义
- 容易在重构时引入 shadow / 覆盖理解错误
- 说明 schema 文档和实现还没有完全收敛

建议在 refactor 前先清掉这个重复项。

## 当前最重要的语义边界

以下边界现在已经“能用”，但必须在后续改造中继续固化：

| 语义 | 正确载体 | 不应混用为 |
| --- | --- | --- |
| 候选召回 | `candidate_set` | `resolved_target` / `winner_shop_id` |
| 单目标解析 | `resolved_target` / `resolve_shop_result` | `current_shop`（除非真单店且要持久化） |
| 胜者决策 | `p2_decision_plan.winner_shop_id` | `candidate_set` |
| 推荐记忆 | `last_recommendation_list` | `current_shop` |
| 比较记忆 | `comparison_targets` / `comparison_result` | `last_recommendation_list` |
| 回答结构 | `answer_plan` | `DecisionPlan` |
| 最终回答 | `final_response` | `EvidencePack` / `tool_results` |

## 现有实现的优点

审计过程中也确认了几个值得保留的点：

1. `planning_subgraph` 已经开始显式区分 `CANDIDATE_SET_RESOLVED` 和 `TARGET_RESOLVED`。
2. `state_update_planner` 已经明确区分了 `ResolveShopResult.status` 和 `ToolResult` 失败状态，不再把两者混成一类。
3. `execution_review_subgraph` 已经把“工具 → 证据 → 决策 → 回答”串成了稳定顺序。
4. `response_subgraph` 已经把 verifier 作为最终出图边界，而不是仅做摆设。

这些点说明系统并不是“从零乱到尾”，而是已经有了正确方向，只是还需要继续把边界收紧。

## 高风险混用点

### 1. `GraphState` 的兼容字段过多

`GraphState` 里既有运行态字段，又有 session 镜像字段，又有决策和回答字段。  
这意味着只要后续新增节点，就很容易把“临时中间态”写成“跨轮事实”。

风险等级：高

### 2. `target_resolution_status` 还承担阶段语义

当前它已经被用来表达：

- `RESOLVED`
- `CANDIDATE_SET_RESOLVED`
- `NOT_FOUND`
- `AMBIGUOUS`

它的问题不是“不能用”，而是“它仍然太像一个总开关”。  
在 refactor 中应逐步把阶段语义收敛到 `resolution_stage`，把 `target_resolution_status` 降级为兼容输出或 trace 兼容项。

风险等级：高

### 3. `resolve_shop_result` 和 `resolved_target` 的过渡语义还未完全切干净

这两个字段在多个节点里都可能出现。  
只要未来某个节点不小心把它们当成 winner，就会把“候选解析成功”误写成“最终推荐已定”。

风险等级：高

### 4. `ranking_snapshot` 仍然可能影响理解而不是纯 trace

它已经不再是唯一决策源，但仍被 evidence / answer / verifier 多处读取。  
这本身可以接受，但必须明确它是“证据附带的排序快照”，不是“最终决策真理”。

风险等级：中

### 5. `state_update_plan` 是唯一持久化口，但要防绕路

当前结构很好，但只要后续有人在别的节点直接写 session store，就会破坏整个契约体系。  
因此 refactor 阶段应把“只能通过 state_update_plan 落盘”写成强约束。

风险等级：高

## 推荐的 refactor 顺序

为了最小化风险，建议按以下顺序收口：

1. 先冻结状态语义，明确 `candidate_set`、`resolved_target`、`winner_shop_id` 三层边界。
2. 再继续压缩 `GraphState` 中的兼容镜像字段，避免新字段继续扩散。
3. 清理 `schemas.py` 中重复的 schema 定义。
4. 继续统一 `target_resolution_status` / `resolution_stage` 的职责。
5. 最后才考虑更大的 workflow、路由或架构拆分。

## 最终判断

当前项目的状态契约已经从“混乱”进入“可收口”阶段。  
真正需要警惕的不是有没有字段，而是字段之间是否还在互相抢语义。

如果把本次审计压成一句话，那就是：

**现在可以开始做 refactor，但前提是先把候选集、目标、胜者、回答、持久化这五层契约分清楚，任何改造都不能再把它们重新揉回一个字段里。**

