# 复杂意图 Query 架构稳态融合方案

本文件基于当前仓库真实代码与已有方案文档整理，目标是把本地生活 Agent 的复杂 query 处理能力收敛成一份最终稳态方案。

当前项目不做 workflow 级 Map-Reduce。当前项目应采用业界更认可的方式：**Single-owner workflow + facet/stage decomposition + workflow 内部受控并行 + Review/Verify 优先 + 本地生活业务优先**。

---

## 1. 结论

当前仓库的本地生活 Agent 架构方向是正确的，已经具备 workflow-first、agent-assisted 的骨架。

从代码事实看，`direct_response`、`clarification_fallback`、`deterministic_tool`、`discovery_decision`、`exploration_planning` 已经在 `workflow_registry`、`orchestration_router`、`workflow_runner`、`graph_state`、`schemas` 层形成了明确边界。

但当前阶段的目标不是扩展新 workflow，也不是引入 workflow 级 Map-Reduce，而是继续把已实现复杂 query 能力收紧成可验收、可回归、可防退化的工程协议。

当前阶段唯一目标：

- 稳定已实现复杂 query 能力
- 不扩展新能力
- 不做 workflow 级 Map-Reduce
- 不引入 RAG、交易、预约、支付、订单能力
- 不重写整个 `graph_builder`

融合后的核心判断：

- 架构方向通过
- 复杂 query 稳态能力部分通过
- `exploration_planning` 已在 registry 同层注册，但执行外壳不与 `discovery_decision` 同构
- 当前应优先修单路径质量，而不是用 workflow 级并行掩盖质量问题

---

## 2. 业界认可做法与本项目借鉴

### 2.1 Single Owner / Manager owns final answer

业界多 Agent / workflow 编排通常要求明确“谁拥有最终回答”。

如果主 workflow 负责最终合成，那么其他能力应该作为工具、子任务、facet 或 evidence worker，而不是多个平权 workflow 并行抢答。

借鉴到本项目：

- `workflow_runner` 不是 mapper
- `workflow_runner` 是顶层 workflow 分发器
- 每轮只选择一个 `workflow_name`
- 最终回答由一个主 workflow 负责
- 不做 `workflow_names = [...]`
- 不做多个 `final_response` merge

对应代码事实：

- `D:\javacode\hm-dianping\local_life_agent\engine\workflow_runner.py`
- `D:\javacode\hm-dianping\local_life_agent\domain\graph_state.py`
- `D:\javacode\hm-dianping\local_life_agent\domain\schemas.py`

### 2.2 Prompt Chaining / Stage for dependent tasks

有依赖顺序的任务应串行 stage 化，而不是并行 workflow 化。

例如用户问：

“推荐附近火锅，第一家远吗？”

正确做法：

1. 先搜索 / 推荐附近火锅，产生候选列表。
2. 再解析“第一家”。
3. 再查距离。
4. 再合成 `EvidencePack`。
5. 再生成 `AnswerPlan` 和 `final_response`。

错误做法：

- workflow A 并行推荐火锅
- workflow B 并行处理“第一家远吗”

原因：

“第一家”的引用依赖前序候选结果，不能并行。

借鉴到本项目：

- 引用消解必须串行
- `current_shop`、`last_recommendation_list`、`comparison_targets` 的解析依赖必须在 stage 中明确
- 如果没有候选列表或 `current_shop`，必须进入 `clarification_fallback`，不能猜

对应代码事实：

- `D:\javacode\hm-dianping\local_life_agent\engine\subgraphs\planning_subgraph.py`
- `D:\javacode\hm-dianping\local_life_agent\planning\state_update_planner.py`
- `D:\javacode\hm-dianping\local_life_agent\domain\graph_state.py`

### 2.3 Parallelization only for independent subtasks

只有无依赖的事实补充才适合未来并行，例如：

- 对 top-k 店铺查营业状态
- 对 top-k 店铺查优惠
- 对 top-k 店铺查距离
- 对 top-k 店铺查价格 / 人均
- 对 top-k 店铺查评价标签

这些属于 workflow 内部的 evidence/tool 并行，不是 workflow 级并行。

借鉴到本项目：

- P1 可以考虑 batch / parallel tool execution
- 但并行结果只能进入 `EvidencePack`
- 并行 worker 不能写 `current_shop`、`last_recommendation_list`、`comparison_targets`、`pending_clarification`
- 并行 worker 不能生成 `final_response`

对应代码事实：

- `D:\javacode\hm-dianping\local_life_agent\engine\subgraphs\execution_review_subgraph.py`
- `D:\javacode\hm-dianping\local_life_agent\domain\schemas.py`

### 2.4 Reducer / Merge Contract

并行输出必须有明确 reducer contract，不能多个分支随便写同一个 state key。

借鉴到本项目：

未来如果做 tool/evidence 层并行，每个 worker 只能输出结构化 evidence result，例如：

- `facet`
- `target_shop_id`
- `status = answerable | unknown | failed`
- `evidence_items`
- `source`
- `error`
- `sort_key`

统一由 `EvidenceBuilder` / reducer 合并成一个 `EvidencePack`。

对应代码事实：

- `D:\javacode\hm-dianping\local_life_agent\planning\evidence\evidence_builder.py`
- `D:\javacode\hm-dianping\local_life_agent\domain\schemas.py`

### 2.5 Evaluator-Optimizer / Review

复杂 query 质量不靠并行解决，而靠 review / verify / retry / fallback。

借鉴到本项目：

必须优先修：

- `EvidenceReview`
- `DecisionReview`
- `AnswerVerify`
- `state_update_plan`

而不是先做 workflow 级 Map-Reduce。

对应代码事实：

- `D:\javacode\hm-dianping\local_life_agent\planning\evidence\evidence_review.py`
- `D:\javacode\hm-dianping\local_life_agent\planning\decision\decision_review.py`
- `D:\javacode\hm-dianping\local_life_agent\engine\subgraphs\response_subgraph.py`
- `D:\javacode\hm-dianping\local_life_agent\planning\state_update_planner.py`

### 2.6 Streaming 采用 status events + single final stream

不要做多个 workflow token stream 合并。

本项目应采用：

- status event：正在理解需求
- status event：正在搜索候选
- status event：正在检查营业 / 优惠 / 距离
- status event：正在验证回答
- final stream：一个最终回答

禁止：

- workflow_A token stream
- workflow_B token stream
- workflow_C token stream
- merge token stream

### 2.7 Safety 使用 global guard + inherited context + output verify

安全判断必须先看完整 query，不能只对子 query 分别 hard_guard。

借鉴到本项目：

- hard_guard 先处理完整用户输入
- facet / subtask 继承整体 safety context
- final answer 经过 `answer_verify`
- 不能出现“子任务分别安全，但合成后不安全”的绕过

### 2.8 Observability 保持 one turn -> one trace

当前不要引入树状 trace：

- trace_root
  - trace_A
  - trace_B
  - trace_merge

本项目应保持：

- one turn -> one trace
- trace 内部增加 spans：
  - router
  - planning
  - execution
  - evidence_review
  - decision_review
  - answer_verify
  - state_update

P1 再增强字段：

- `workflow_name`
- `task_type` / `route_task`
- `response_mode`
- `facets`
- `tool_call_count`
- `evidence_count`
- `answerable_facets_count`
- `unknown_facets_count`
- `failed_facets_count`
- `verification_status`
- `fallback_reason`
- `final_latency_ms`

### 2.9 Budget / Deadline / Cancellation

不要在当前阶段引入 workflow 级并行，因为会带来：

- 子 workflow deadline 分配
- merge deadline 不足
- 部分 workflow 需要澄清时其他 workflow 是否取消
- 工具 quota 竞争
- 结果部分成功 / 部分失败如何合成

本项目当前应保持单主 workflow，并在单 workflow 内做预算控制：

- `tool_round_budget`
- `retry_budget`
- `expand_search_budget`
- `rewrite_budget`
- `facet_enrich_budget`
- `deadline_remaining_ms`

---

## 3. 为什么本项目当前不做 workflow 级 Map-Reduce

### 3.1 Map-Reduce 的价值

Map-Reduce 的价值在于：当一个 turn 中包含多个真正独立的子目标时，可以让每个子目标拥有完整 Plan -> Execute -> Review，再合成结果。

### 3.2 但当前不做 workflow 级 Map-Reduce 的原因

#### 3.2.1 它解决不了当前核心问题

当前核心问题是：

- 单路径工具调用路径不对等
- 验证链路不对称
- Plan 层 LLM / Rule 边界模糊
- Keyword 覆盖 LLM 分类
- 证据不足无迭代
- 跨意图冲突检测不足
- 状态写回污染风险

这些问题不会因为 workflow 并行自动消失。

必须先修单路径：

- facet 保留
- evidence 构建
- evidence review
- decision review
- answer verify
- `state_update_plan`

#### 3.2.2 它会加剧当前脆弱点

workflow 级 Map-Reduce 会加剧：

- GraphState fork / join
- SessionState merge
- state 字段冲突
- 工具 quota 竞争
- 错误传播
- fallback 决策复杂度
- 测试矩阵指数增长
- trace 复杂度
- streaming 合成复杂度
- deadline 调度复杂度

#### 3.2.3 引用消解必须串行

例如：

“推荐附近火锅，第一家远吗？”

“第一家”依赖前序推荐结果，不能和推荐 workflow 并行。

#### 3.2.4 Streaming 多流合并体验差

交织输出会跳跃，等待全部完成会失去 streaming 低延迟优势。

当前只做 status events + single final stream。

#### 3.2.5 安全存在合成效应

不能让子 query 各自安全但合成后不安全。

必须完整 query 先过 hard_guard。

#### 3.2.6 确定性下降

多个 workflow 完成顺序不同，merge 结果可能不同。

当前需要确定性，尤其是推荐顺序、引用顺序、state 写回顺序。

#### 3.2.7 Cancellation / Clarification 语义不清

如果一个子 workflow 需要澄清，其他子 workflow 是继续、暂停还是取消，没有通用正确答案。

当前通过单 workflow 的 clarify / fallback 路由处理。

#### 3.2.8 Deadline / quota 调度复杂化

多个 workflow 会竞争全局 deadline 和工具 quota。

当前只允许单 workflow 内部受控工具预算。

### 3.3 结论

当前阶段禁止：

- `route_task -> List[str]`
- `workflow_name -> List[str]`
- 多 workflow 并行
- GraphState fork / join
- 多 `final_response` merge
- 多 `state_update_plan` merge

未来如果需要并行，只能从 `ExecutionPlan` 内部的 batch / parallel tool execution 开始，并 reduce 到一个 `EvidencePack`。

对应代码事实：

- `D:\javacode\hm-dianping\local_life_agent\engine\workflow_runner.py`
- `D:\javacode\hm-dianping\local_life_agent\engine\_routes.py`
- `D:\javacode\hm-dianping\local_life_agent\domain\graph_state.py`
- `D:\javacode\hm-dianping\local_life_agent\domain\schemas.py`

---

## 4. 本地生活 workflow 边界

### 4.1 discovery_decision

负责：

- 搜索
- 推荐
- 多店候选
- 多店对比
- 条件筛选
- 场景推荐
- deal compare

不要拆成单独顶层 workflow：

- `recommendation_workflow`
- `search_workflow`
- `comparison_workflow`
- `coupon_workflow`
- `status_workflow`
- `distance_workflow`

这些应在 `discovery_decision` 内通过 facets / stages / tool_calls 表达。

标准处理形态：

用户：

“附近推荐几家适合约会、现在营业、最好有券、人均 100 左右的餐厅”

应该是：

- `workflow_name = discovery_decision`
- facets：
  - nearby
  - restaurant
  - date_scene
  - open_now
  - coupon
  - budget_around_100
- stages：
  1. `search_shops`
  2. enrich top-k candidates by `open_status` / `coupon` / `distance` / `avg_price` / `review_tags`
  3. build `EvidencePack`
  4. `DecisionPlan` ranking
  5. `AnswerPlan` + `AnswerVerify`
  6. `state_update_plan`

对应代码事实：

- `D:\javacode\hm-dianping\local_life_agent\engine\subgraphs\planning_subgraph.py`
- `D:\javacode\hm-dianping\local_life_agent\engine\subgraphs\execution_review_subgraph.py`
- `D:\javacode\hm-dianping\local_life_agent\domain\schemas.py`

### 4.2 deterministic_tool

负责明确单目标事实链：

- 这家有券吗
- 这家现在开着吗
- 这家离我多远
- 这家人均多少
- 这家地址 / 电话 / 评分 / 评价摘要

前提：

- 必须有明确 `current_shop` / shop_id / resolved_target
- 没有明确目标时进入 `clarification_fallback`
- 只在一个明确 `target_shop` 上执行，不做候选召回、不做排序、不做推荐决策
- 可以围绕同一个 `target_shop` 触发多个必要的 fact tool_calls
- 多个 tool results 必须 reduce 成一个单店 `EvidencePack`
- 单店多 facet 也必须显式维护 `answerable_facets` / `unknown_facets` / `failed_facets`
- 如果缺 `target_shop` / `current_shop`，不能执行 `deterministic_tool`，必须 `clarification_fallback`
- 如果部分工具失败，只把对应 facet 标记为 `failed`，不污染 `current_shop`，不影响其他 `answerable_facets`
- 不进入 discovery planning
- 不做推荐排序

> **当前实现局限**：当前 `deterministic_tool_workflow.py` 仅支持单次 `dispatch_tool_call`，每次只查一个 facet。多 facet 并行执行（如同一个 `target_shop` 同时查券和营业状态）依赖 P7（共享 adapter）或 P10（并行工具执行），不在当前实现范围内。

对应代码事实：

- `D:\javacode\hm-dianping\local_life_agent\engine\workflows\deterministic_tool_workflow.py`
- `D:\javacode\hm-dianping\local_life_agent\planning\orchestration_router.py`

### 4.3 exploration_planning

负责组合规划类：

- 先吃饭再喝咖啡
- 约会路线
- 亲子半日活动
- 吃喝玩组合建议
- 多地点组合安排

当前阶段：

- 保持独立 workflow handler
- 不急着抽成新的 subgraph
- 不粗暴合并进 `discovery_decision`
- 强化内部边界：
  - `subgoals`
  - bounded search
  - bounded tool execution
  - `ExplorationPlan`
  - `EvidencePack`
  - `AnswerPlan`
  - `AnswerVerify`
  - `state_update_plan`
- 补 e2e 测试和状态污染测试

对应代码事实：

- `D:\javacode\hm-dianping\local_life_agent\engine\workflows\exploration_planning_workflow.py`
- `D:\javacode\hm-dianping\local_life_agent\domain\schemas.py`
- `D:\javacode\hm-dianping\local_life_agent\tests\test_exploration_planning_workflow.py`

### 4.4 clarification_fallback

负责：

- 缺位置
- 缺店铺目标
- 指代失败
- 比较对象不足
- 工具失败兜底
- 无结果兜底
- 低置信度

要求：

- 最小化追问
- 不猜用户目标
- 不污染 `current_shop` / `comparison_targets`
- 澄清完成后能恢复原 workflow

对应代码事实：

- `D:\javacode\hm-dianping\local_life_agent\engine\workflows\clarification_fallback_workflow.py`
- `D:\javacode\hm-dianping\local_life_agent\engine\_routes.py`

### 4.5 direct_response

负责：

- 闲聊
- 能力说明
- 安全拒答
- 越界说明
- 无工具直答

要求：

- 不查工具
- 不写店铺状态
- 不写推荐列表
- 不进入推荐 / 对比 / 查询链路

对应代码事实：

- `D:\javacode\hm-dianping\local_life_agent\engine\workflows\direct_response_workflow.py`
- `D:\javacode\hm-dianping\local_life_agent\engine\subgraphs\response_subgraph.py`

### 4.6 工具调用路径对比

当前三条 tool call 执行路径并存，各走不同的入口和执行方式：

| 路径 | 入口 workflow | 执行方式 | 并发工具 | Stage 语义 | EvidencePack | 状态写回 |
|---|---|---|---|---|---|---|
| discovery_decision | planning_subgraph → execution_review_subgraph | BatchToolExecutor | ✅ | ✅ | ✅ | state_update_plan |
| deterministic_tool | deterministic_tool_workflow.py | 直调 `dispatch_tool_call()` | ❌ | ❌ | 独立构建 | 直写 GraphState |
| exploration_planning | exploration_planning_workflow.py | 直调 `dispatch_tool_call()` | ❌ | ❌ | 独立构建 | 直写 GraphState |

P3/P4 的目标是让所有路径收敛到统一的 EvidencePack 语义和 state_update_plan 写回协议，不要求统一执行引擎。

---

## 5. 本地生活 facet 协议

复杂 query facet 要尽量贯穿：

- `SemanticFrame`
- `GoalPlan`
- `ExecutionPlan`
- `EvidencePack`
- `DecisionPlan`
- `AnswerPlan`

### 5.1 location facets

- nearby
- distance
- business_area
- travel_time

### 5.2 category facets

- restaurant
- hotpot
- coffee
- dessert
- parent_child
- entertainment
- shopping

### 5.3 scene facets

- date_scene
- family_with_kids
- friends_party
- quiet
- lively
- business_meeting
- work_study
- late_night

### 5.4 status facets

- open_now
- open_late
- reservation_available
- queue_status

### 5.5 deal facets

- coupon
- discount
- group_buy
- cost_performance

### 5.6 price facets

- avg_price
- budget
- budget_around_x
- price_compare

### 5.7 quality facets

- rating
- review_tags
- popularity
- service
- environment
- taste

### 5.8 preference facets

- not_too_noisy
- kid_friendly
- parking
- private_room
- spicy
- light_food
- vegetarian

### 5.9 reference facets

- current_shop
- ordinal_reference
- previous_recommendation
- comparison_targets

对应代码事实：

- `D:\javacode\hm-dianping\local_life_agent\domain\schemas.py`
- `D:\javacode\hm-dianping\local_life_agent\domain\graph_state.py`

如果当前 schema 不足，优先提出最小 schema 改造建议，不要新建大规模 workflow。

---

## 6. Evidence / Decision 协议

复杂 query 的每个 facet 都要落入以下状态：

- `answerable_facets`
- `unknown_facets`
- `failed_facets`

### 6.1 answerable_facets

- 有明确证据
- 可以写入 answer
- 必须能回溯到 `tool_result` / `evidence_item`

### 6.2 unknown_facets

- 数据不存在或无法确认
- 可以在 answer 中说明“不确定 / 暂时没查到”
- 不能编造成确定事实

### 6.3 failed_facets

- 工具失败、超时、接口错误、证据构建失败
- answer 必须显式降级
- 不能污染 SessionState

`DecisionPlan` 必须基于 `EvidencePack` 做：

- ranking
- `selected_targets`
- `omitted_targets`
- `comparison_matrix`
- `winner_shop_id`
- `uncertainty_notes`
- `downgrade_reason`

`AnswerPlan` 必须基于 `DecisionPlan` 做：

- `answer_type`
- `allowed_claims`
- `required_disclaimers`
- `unknown_facets_to_mention`
- `failed_facets_to_mention`

对应代码事实：

- `D:\javacode\hm-dianping\local_life_agent\domain\schemas.py`
- `D:\javacode\hm-dianping\local_life_agent\planning\decision\decision_planner.py`
- `D:\javacode\hm-dianping\local_life_agent\planning\evidence\evidence_builder.py`
- `D:\javacode\hm-dianping\local_life_agent\engine\subgraphs\response_subgraph.py`

如果当前字段不足，应提出最小 schema 改造建议，不要把 route_task 或 workflow_name 列表化。

---

## 7. 引用消解与多轮状态

本地生活强依赖短期状态。必须明确：

### 7.1 current_shop

可以写：

- 用户明确点名某店并解析成功
- 用户选择推荐列表中的某一家
- 单店工具查询确认目标店
- 系统最终推荐一个明确 winner，且产品规则允许设置焦点店

不能写：

- 工具失败
- 搜索无结果
- 指代失败
- 澄清中
- 推荐多家但没有明确 winner
- `answer_verify` 失败

### 7.2 last_recommendation_list

可以写：

- 推荐 / 搜索链路成功返回可回溯候选
- 推荐列表顺序稳定
- evidence / decision 已通过必要 review

不能写：

- 搜索无结果
- 推荐失败
- 工具失败
- 澄清未完成
- verify 失败

### 7.3 comparison_targets

可以写：

- 用户明确比较 A 和 B
- 用户说第一家和第二家，且 `last_recommendation_list` 可用
- 系统成功解析两个以上目标

不能写：

- 指代失败
- 比较对象不足
- 上一轮推荐列表不存在
- 比较未完成

### 7.4 pending_clarification

可以写：

- 缺位置
- 缺店铺目标
- 指代失败
- 比较对象不足
- 必要约束缺失

必须清理：

- 用户补充信息后恢复原任务
- 澄清完成
- 任务取消 / 新任务覆盖

### 7.5 引用顺序规则

必须写入：

- “第一家 / 第二家 / 第三家”必须依赖 `last_recommendation_list` 的稳定顺序
- “这家 / 刚才那家”必须依赖 `current_shop` 或最近明确焦点
- “A 和 B 比一下”必须先稳定解析 `comparison_targets`
- 引用失败只能澄清，不能猜
- 引用解析应该优先复用上一轮候选和证据，避免重新 search

对应代码事实：

- `D:\javacode\hm-dianping\local_life_agent\planning\state_update_planner.py`
- `D:\javacode\hm-dianping\local_life_agent\domain\graph_state.py`
- `D:\javacode\hm-dianping\local_life_agent\tests\test_recommendation_flow.py`
- `D:\javacode\hm-dianping\local_life_agent\tests\test_comparison_flow.py`

---

## 8. 为什么本项目当前不做 workflow 级 Map-Reduce

### 8.1 它解决不了当前核心问题

当前核心问题是：

- 单路径工具调用路径不对等
- 验证链路不对称
- Plan 层 LLM / Rule 边界模糊
- Keyword 覆盖 LLM 分类
- 证据不足无迭代
- 跨意图冲突检测不足
- 状态写回污染风险

这些问题不会因为 workflow 并行自动消失。

必须先修单路径：

- facet 保留
- evidence 构建
- evidence review
- decision review
- answer verify
- `state_update_plan`

### 8.2 它会加剧当前脆弱点

workflow 级 Map-Reduce 会加剧：

- GraphState fork / join
- SessionState merge
- state 字段冲突
- 工具 quota 竞争
- 错误传播
- fallback 决策复杂度
- 测试矩阵指数增长
- trace 复杂度
- streaming 合成复杂度
- deadline 调度复杂度

### 8.3 引用消解必须串行

例如：

“推荐附近火锅，第一家远吗？”

“第一家”依赖前序推荐结果，不能和推荐 workflow 并行。

### 8.4 Streaming 多流合并体验差

交织输出会跳跃，等待全部完成会失去 streaming 低延迟优势。

当前只做 status events + single final stream。

### 8.5 安全存在合成效应

不能让子 query 各自安全但合成后不安全。

必须完整 query 先过 hard_guard。

### 8.6 确定性下降

多个 workflow 完成顺序不同，merge 结果可能不同。

当前需要确定性，尤其是推荐顺序、引用顺序、state 写回顺序。

### 8.7 Cancellation / Clarification 语义不清

如果一个子 workflow 需要澄清，其他子 workflow 是继续、暂停还是取消，没有通用正确答案。

当前通过单 workflow 的 clarify / fallback 路由处理。

### 8.8 Deadline / quota 调度复杂化

多个 workflow 会竞争全局 deadline 和工具 quota。

当前只允许单 workflow 内部受控工具预算。

### 8.9 结论

当前阶段禁止：

- `route_task -> List[str]`
- `workflow_name -> List[str]`
- 多 workflow 并行
- GraphState fork / join
- 多 `final_response` merge
- 多 `state_update_plan` merge

未来如果需要并行，只能从 `ExecutionPlan` 内部的 batch / parallel tool execution 开始，并 reduce 到一个 `EvidencePack`。

对应代码事实：

- `D:\javacode\hm-dianping\local_life_agent\engine\workflow_runner.py`
- `D:\javacode\hm-dianping\local_life_agent\engine\_routes.py`
- `D:\javacode\hm-dianping\local_life_agent\domain\graph_state.py`
- `D:\javacode\hm-dianping\local_life_agent\domain\schemas.py`

---

## 9. 优先级结构（P0-P14）

### 9.0 P0 有限范围事实校准与 ADR 冻结

| 项目 | 内容 |
| --- | --- |
| 目标 | 在有限文件范围内确认当前真实 workflow、router、runner、subgraph、`exploration_planning` 状态，并冻结“不做 workflow 级 Map-Reduce”的 ADR |
| 关键点 | 不要求读完整仓库；限定扫描 `workflow_registry.py`、`workflow_runner.py`、`orchestration_router.py`、`_routes.py`、`graph_builder.py`、`graph_state.py`、`schemas.py`、`exploration_planning_workflow.py`、`planning_subgraph.py`、`execution_review_subgraph.py`、`response_subgraph.py`、`state_update_planner.py` 及相关测试 |
| 输出 | 必须产出可核对事实清单：workflow 白名单、handler、单 dispatch、fan-out、`workflow_names`/`final_responses`/`state_update_plans` 是否存在、`exploration_planning` 是否接入 `execution_review_subgraph`、`orchestration_router_shadow` 状态 |
| 验收 | 只做有限范围自动化扫描 + 少量人工确认；不要求读完整仓库；不确定处写“不确定，需要进一步检查” |

### 9.1 P1 单主 workflow 不变量与单 dispatch 防退化

| 项目 | 内容 |
| --- | --- |
| 目标 | 固化 `workflow_name` 单值、`workflow_runner` 每轮只 dispatch 一个 workflow、单 `EvidencePack` / `DecisionPlan` / `AnswerPlan` / `final_response` / `state_update_plan` |
| 关键点 | 防止出现 `workflow_names`、`final_responses`、`state_update_plans` 之类多主字段；禁止 `workflow_runner` 对 `List[workflow_name]` 循环 dispatch；禁止 `_routes.py` 生成多 workflow fan-out |
| 检查手段 | pytest 单元测试 + 结构扫描测试（grep/AST）+ 关键 schema validate |
| 对应代码事实 | `graph_state.py`、`schemas.py`、`workflow_runner.py`、相关单测 |
| 验收 | 单主不变量被自动化测试锁住，复杂 query 不会被拆成多个顶层 workflow |

### 9.2 P2 Router 决策优先级与 LLM/Rule/Keyword 冲突保护

| 项目 | 内容 |
| --- | --- |
| 目标 | 明确 `orchestration_router` 中 LLM、规则和关键词命中的优先级，避免同一 query 因 keyword 覆盖完整语义而走错 workflow |
| 关键点 | 硬规则最高优先级：`unsafe/forbidden`、`invalid/out_of_scope`、缺必要上下文的引用、缺必要位置/店铺目标/比较对象；LLM/semantic frame 负责 recommendation/comparison/scene_recommendation/condition_refine/deal_compare/exploration_planning/date_plan/family_activity_plan/eat_and_play_plan；keyword 只能作为 signal |
| 例子 | “附近推荐几家有券的餐厅”应进入 `discovery_decision`，`coupon` 只是 facet；“这家有券吗？”有 `current_shop` 才能走 `deterministic_tool`；“第一家有券吗？”有 `last_recommendation_list` 才先解析第一家，否则澄清 |
| 对应代码事实 | `planning/orchestration_router.py`、`domain/schemas.py`、`domain/graph_state.py`、router 相关测试 |
| 验收 | router 决策有明确优先级；keyword 覆盖逻辑不再破坏复杂 query 路由 |

### 9.3 P3 本地生活 facet 协议与全链路保留

| 项目 | 内容 |
| --- | --- |
| 目标 | 标准化 location / category / scene / status / deal / price / quality / preference / reference facets |
| 关键点 | 确保 facet 从 `SemanticFrame -> GoalPlan -> ExecutionPlan -> EvidencePack -> DecisionPlan -> AnswerPlan` 不丢失；不把 facet 当 `route_task` 列表；引入 `TargetResolutionResult` 协议表达 resolved target / unresolved target / reference source / confidence |
| 最小字段 | `target_shop`、`resolved`、`source`、`confidence`、`owner`、`resolution_reason` |
| owner | `planning/orchestration_router.py` 负责生成和判定，`graph_state.py` 负责携带和回写 |
| 对应代码事实 | `schemas.py`、`graph_state.py`、`planning_subgraph.py`、`execution_review_subgraph.py` |
| 验收 | facet 能贯穿全链路并稳定进入后续计划、证据和回答 |

### 9.4 P4 Evidence / Decision / Answer 协议收敛

| 项目 | 内容 |
| --- | --- |
| 目标 | 每个 facet 进入 `answerable_facets` / `unknown_facets` / `failed_facets`，固定 search / evidence / decision / answer / verify 职责边界 |
| 关键点 | answer 只表达，不重新决策；`answer_verify` 失败必须 rewrite 或 fallback；`EvidencePlanner` 不任意创造 facet；`deterministic_tool` 统一按 single-target multi-facet 语义执行；`conflicting_facets` 作为基础能力显式参与 tradeoff 策略；`RankingPolicy` 只是排序约束，不直接选 winner |
| 对应代码事实 | `evidence_builder.py`、`evidence_review.py`、`decision_planner.py`、`decision_review.py`、`response_subgraph.py` |
| 验收 | `final_response` 不输出无证据 claim，且可以回溯到结构化证据和决策计划 |

### 9.5 P5 SessionState 写回安全与引用消解

| 项目 | 内容 |
| --- | --- |
| 目标 | 明确 `current_shop` / `last_recommendation_list` / `comparison_targets` / `pending_clarification` 写回规则 |
| 关键点 | 工具失败、搜索无结果、指代失败、verify 失败不得污染状态；“第一家/第二家/这家/刚才那家”必须依赖稳定上下文，失败只能澄清；补齐 `SessionState.source / ttl / evidence_ref / location_context` 的写回语义 |
| 对应代码事实 | `state_update_planner.py`、`graph_state.py`、推荐 / 对比 / 单店 / exploration 测试 |
| 验收 | `state_update_plan` 是唯一写回入口，失败路径不污染 SessionState |

### 9.6 P6 本地生活复杂 query 测试矩阵

| 项目 | 内容 |
| --- | --- |
| 目标 | 覆盖推荐多约束、多维对比、单店多 facet、引用失败、推荐+引用依赖、工具失败、搜索无结果、verify 失败、澄清恢复、极端异常 |
| 关键点 | 测试必须检查中间状态，不只检查 `final_response`；新增或补齐单元测试 + 结构扫描测试 + schema validate；至少包含 3 条极端异常烟雾测试（所有工具超时、所有 LLM 返回格式异常、前后矛盾多轮 query）；补齐 golden trace 测试夹具，用于回放关键链路和状态演化 |
| 对应代码事实 | `test_recommendation_flow.py`、`test_comparison_flow.py`、`test_deterministic_tool_workflow.py`、`test_exploration_planning_workflow.py`、`test_workflow_runner.py`、`test_workflow_registry.py`、`test_comprehensive_graph_e2e.py` |
| 验收 | 所有已有测试通过；新增复杂 query 测试通过 |

> **扩展：离线评测集** — 当前 P6 不要求，但建议启动离线评测集建设（200+ 标注 query + 期望回答维度），以便在每次架构改动后评估系统输出质量变化，及时发现回归。这是独立于结构扫描和单元测试的另一层质量保障，长期基线工程项。

### 9.7 P7 exploration_planning 协议同构与共享 adapter

| 项目 | 内容 |
| --- | --- |
| 目标 | 保持 `exploration_planning` 独立 workflow handler；统一工具结果 / `EvidencePack` / `AnswerVerify` 语义；优先抽共享组件 / adapter，而不是先改图结构 |
| 关键点 | 不新增 `exploration_planning_subgraph`；不粗暴并入 `discovery_decision`；如有重复逻辑，优先抽 `normalize_tool_result_to_evidence`、`build_evidence_pack`、`verify_answer_plan`、`apply_state_update_plan`、`classify_failed_unknown_answerable_facets` 等共享组件 |
| 对应代码事实 | `exploration_planning_workflow.py`、`workflow_registry.py`、`workflow_runner.py`、`_routes.py` |
| 验收 | exploration 的证据、验证和状态协议与主链路同构表达；不要求统一到同一个 subgraph |

### 9.8 P8 证据不足迭代与降级策略

| 项目 | 内容 |
| --- | --- |
| 目标 | `EvidenceReview` 输出结构化下一步：`proceed / retry / replan_missing_facets / expand_search / clarify / degrade / fallback` |
| 关键点 | retry / expand 必须受预算控制；部分成功可以降级回答；unknown / failed facets 必须显式说明，不能编造；明确 `ToolCapabilitySpec` 与 `ToolFailure` 分类，作为 `EvidenceReview` 选择 retry / degrade / fallback 的依据 |
| 最小字段 | `tool_name`、`supported_facets`、`required_inputs`、`timeout_ms`、`failure_type`、`retryable`、`owner` |
| owner | `planning/evidence/evidence_builder.py` 负责声明能力，`evidence_review.py` 负责依据失败分类决策 |
| 对应代码事实 | `evidence_review.py`、`decision_review.py`、`_routes.py`、`response_subgraph.py` |
| 验收 | 证据不足时有稳定下一步，不会无界循环 |

### 9.9 P9 EvidencePlanner facet 生成 / 裁剪 / 预算

| 项目 | 内容 |
| --- | --- |
| 目标 | 采用 `LLM proposes facets -> taxonomy validator -> rule 补必要项 -> budget controller 裁剪 -> evidence planner 生成 tool_calls` |
| 关键点 | 不让 LLM 任意创造 facet；不让 LLM 直接决定工具执行；低置信度 fallback 到规则模板；优先级按用户显式约束 > 引用消解必需 > 决策必需 > 安全合规必需 > 体验增强；补齐 `ToolCapabilitySpec` 与 `ToolFailure` 结构化输入，避免 planner 把不可用能力误纳入执行计划 |
| 对应代码事实 | `planning_subgraph.py`、`decision_planner.py`、`evidence_builder.py`、`schemas.py` |
| 验收 | facet 生成可控、可裁剪、可预算 |

### 9.10 P10 体验与性能优化

| 项目 | 内容 |
| --- | --- |
| 目标 | SSE / preview / fast preview、top-k evidence enrichment、batch / parallel tool execution、cache reuse |
| 关键点 | 并行只允许在 tool/evidence 层，结果 reduce 到一个 `EvidencePack`；不并行 workflow；preview 必须满足事实一致性约束，不能把未验证事实包装成 final 语气 |
| 对应代码事实 | `events.py`、`app.py`、`execution_review_subgraph.py`、`planning/evidence/evidence_builder.py` |
| 验收 | 体验和性能优化不破坏单主工作流边界 |

### 9.11 P11 Observability / Metrics / Streaming 协议

| 项目 | 内容 |
| --- | --- |
| 目标 | 保持 one turn -> one trace，增加 spans 和 metrics，streaming 采用 status events + single final stream |
| 关键点 | 不做 `trace_root -> trace_A / trace_B / trace_merge`；指标包括 `workflow_name`、`facets`、`tool_call_count`、`evidence_count`、`answerable/unknown/failed facets`、`verification_status`、`fallback_reason`、`latency`；增加业务级质量指标：`answer_verify_pass_rate`、`clarification_rate`、`tool_failure_rate`、`avg_facets_per_query`（与 trace/metrics 分开，在业务层面反映系统输出质量随改动的变化趋势） |
| 对应代码事实 | `graph_state.py`、`events.py`、`app.py`、`trace_spans` / `metrics_tags` 字段 |
| 验收 | 过程可观测，但不引入多流合并复杂度 |

### 9.12 P12 Deadline / Budget / Freshness / TTL

| 项目 | 内容 |
| --- | --- |
| 目标 | 单 workflow 内细化 `tool_round_budget`、`retry_budget`、`expand_search_budget`、`rewrite_budget`、`facet_enrich_budget`、`deadline_remaining_ms`，并补动态事实 freshness / TTL |
| 关键点 | `open_status` / `coupon` / `queue_status` 强时效，`rating` / `review_tags` 弱时效，`distance` 依赖用户位置变化重算；明确 freshness / TTL 具体规则，并规定 tool budget 耗尽后的降级路径 |
| 对应代码事实 | `_routes.py`、`workflow_runner.py`、`state_update_planner.py` |
| 验收 | 预算与 freshness 规则明确，超预算可稳定降级 |

### 9.13 P13 State 类型收敛与 GraphState BaseModel 分阶段迁移评估

| 项目 | 内容 |
| --- | --- |
| 目标 | 不立即全量替换 `GraphState`；先强化关键对象 BaseModel / schema：`OrchestrationDecision`、`ExecutionPlan`、`EvidencePack`、`DecisionPlan`、`AnswerPlan`、`StateUpdatePlan`；再评估 `GraphStateModel` adapter / `validate_graph_state` |
| 关键点 | `TypedDict -> BaseModel` 全量迁移不作为当前验收前提；当前只做边界对象收敛和校验；纳入 GraphState 冗余字段清理评估（100+ 字段中至少 5 组冗余：`tool_results`/`tool_result_set`、`resolved_target`/`resolve_shop_result`、多个 `session_state` 字段、`orchestration_decision` 分布在 6 个顶级字段、多个 error 字段） |
| 对应代码事实 | `graph_state.py`、`schemas.py`、`workflow_runner.py`、`_routes.py` |
| 验收 | 类型迁移不破坏现有 workflow、state writeback 和测试基线 |

### 9.14 P14 长期冻结项与未来可选方向

| 项目 | 内容 |
| --- | --- |
| 目标 | 冻结 workflow 级 Map-Reduce、万能 ReAct Agent、全量 RAG、交易/预约/支付、重写 `graph_builder`、大规模新增业务 workflow |
| 关键点 | 未来可选方向只能在当前协议稳定后评估 |
| 对应代码事实 | `graph_builder.py`、`workflow_registry.py`、`workflow_runner.py` |
| 验收 | 当前阶段不扩展到这些方向 |

说明：

- 上述 P0-P14 是最终优先级结构。
- `P2` 已明确用于 router 决策优先级与冲突保护，不再放在非阻断项。
- `P7` 表示 exploration_planning 协议同构与共享 adapter，不要求先接入 `execution_review_subgraph`。
- `P13` 仅表示类型收敛评估，不是当前全量迁移前提。
- `P14` 表示长期冻结项，不再作为当前实施目标。

## 10. 测试矩阵（按 P0-P14 对齐）

### 10.1 P0-P1：事实校准、单主不变量、单 dispatch

重点验证：

- `workflow_name` 仍是单值
- `workflow_runner` 每轮只 dispatch 一个 workflow
- 不存在 `workflow_names` / `final_responses` / `state_update_plans` 之类多主字段
- 不把复杂 query 拆成多个顶层 workflow

建议测试：

- `test_workflow_registry.py`：有限范围白名单与单 workflow 注册
- `test_workflow_runner.py`：单 dispatch、单 workflow lookup、`exploration_planning` / `discovery_decision` 路由差异
- `test_orchestration_router.py`：router 仍是单值决策，不返回列表型结果
- `test_no_multi_workflow_fields_in_graph_state`：结构扫描 / AST 扫描

### 10.2 P2：router 决策优先级与冲突保护

重点验证：

- 硬规则最高优先级
- LLM / semantic frame 负责复杂意图主分类
- keyword 只作为 signal，不能无条件覆盖完整语义
- 缺 resolved target 的 coupon/status/distance query 必须澄清

建议测试：

- “附近推荐几家有券的餐厅” -> `discovery_decision`
- “这家有券吗？” 无 `current_shop` -> `clarification_fallback`
- “第一家有券吗？” 无 `last_recommendation_list` -> `clarification_fallback`
- “这家有券吗？” 有明确 `current_shop` -> `deterministic_tool`
- `deterministic_tool` 允许在明确 `target_shop` 上执行多个必要 fact tool_calls
- 缺 `target_shop` / `current_shop` 时不得进入 `deterministic_tool`
- keyword 不得无条件覆盖 LLM 复杂意图

### 10.3 P3：facet 协议与全链路保留

重点验证：

- location / category / scene / status / deal / price / quality / preference / reference facets 能从 `SemanticFrame` 贯穿到 `AnswerPlan`
- facet 不丢失，不退化成 `route_task` 列表
- `TargetResolutionResult` 能稳定表达 resolved / unresolved / source / confidence
- `deterministic_tool` 只在单一 target 上执行 single-target multi-facet fact tools
- `conflicting_facets` 会触发可解释的 tradeoff 策略
- `RankingPolicy` 只承担最小排序边界，不承担推荐决策

建议测试：

- 推荐多约束场景
- 多维对比场景中的引用 facet / comparison facets
- 单店多 facet 场景中的 reference facets
- 单店多 facet 必须 reduce 为一个 `EvidencePack`
- 单店多 facet 仍需显式区分 `answerable_facets` / `unknown_facets` / `failed_facets`
- `deterministic_tool` 不得做候选召回、排序或推荐决策

### 10.4 P4：Evidence / Decision / Answer 协议收敛

重点验证：

- `EvidencePack` 能表达 `answerable_facets` / `unknown_facets` / `failed_facets`
- `DecisionPlan` 基于 `EvidencePack`
- `AnswerPlan` 基于 `DecisionPlan`
- `answer_verify` 失败后必须 rewrite 或 fallback
- `deterministic_tool` 的多工具结果必须 reduce 成单店 `EvidencePack`
- `conflicting_facets` 与 tradeoff 策略能被结构化记录
- `RankingPolicy` 不越过最小排序边界去做推荐决策

建议测试：

- 工具失败时不能编造
- 搜索无结果时不能编造
- verify 失败时必须 rewrite / fallback

### 10.5 P5：SessionState 写回安全与引用消解

重点验证：

- `current_shop` / `last_recommendation_list` / `comparison_targets` / `pending_clarification` 写回规则正确
- 工具失败、搜索无结果、指代失败、verify 失败不污染状态
- “第一家/第二家/这家/刚才那家”必须依赖稳定上下文，失败只能澄清
- `SessionState.source / ttl / evidence_ref / location_context` 的生命周期与覆盖策略正确
- `ClarificationPlan` 能驱动 `resume_strategy`，在澄清后复用可用上下文继续原任务
- `SessionState` 的写回只允许以可追踪证据引用为依据

建议测试：

- 引用失败
- 推荐 + 引用依赖
- 澄清恢复
- 单店多 facet 但无明确目标时进入澄清
- 部分工具失败时只标记对应 facet 为 `failed`
- 部分工具失败不得污染 `current_shop`
- 部分工具失败不得影响其他 `answerable_facets`
- golden trace 回放：同一 query 在澄清前后应保持可追踪状态演化

### 10.6 P6：本地生活复杂 query 测试矩阵

重点验证：

- 推荐多约束
- 多维对比
- 单店多 facet
- 推荐 + 引用依赖
- 工具失败
- 搜索无结果
- verify 失败
- 澄清恢复
- golden trace 夹具可稳定回放关键链路
- 澄清后的 resume_strategy 与原任务保持一致

建议测试：

- “附近推荐几家适合约会、现在营业、最好有券、人均 100 左右的餐厅”
- “第一家和第二家哪家更适合带娃，哪家更便宜？”
- “这家有券吗？现在开着吗？离我多远？”
- “推荐附近火锅，第一家远吗？”

### 10.7 P7：exploration_planning 协议同构与共享 adapter

重点验证：

- `exploration_planning` 独立 handler 仍可工作
- 工具结果 / `EvidencePack` / `AnswerVerify` 语义与主链路同构
- 优先抽共享组件 / adapter，而不是先改图结构
- 不粗暴并入 `discovery_decision`

建议测试：

- “帮我安排一个先吃饭再喝咖啡的约会路线”
- `exploration_planning` router / runner / boundary / e2e
- `normalize_tool_result_to_evidence` / `build_evidence_pack` / `verify_answer_plan` / `apply_state_update_plan` 共享协议测试

### 10.8 P8：证据不足迭代与降级策略

重点验证：

- `EvidenceReview` 输出结构化下一步
- `proceed / retry / replan_missing_facets / expand_search / clarify / degrade / fallback` 路由明确
- retry / expand 受预算控制
- 部分成功可降级回答
- `EvidenceReview` 的 retry / degrade / fallback 必须以 `ToolCapabilitySpec` 与 `ToolFailure` 分类为依据

建议测试：

- 候选为空
- 字段缺失
- 部分证据可用
- 工具失败后走 clarify / fallback

### 10.9 P9：EvidencePlanner facet 生成 / 裁剪 / 预算

重点验证：

- `LLM proposes facets -> taxonomy validator -> rule 补必要项 -> budget controller 裁剪 -> evidence planner 生成 tool_calls`
- 不让 LLM 任意创造 facet
- 不让 LLM 直接决定工具执行
- `ToolCapabilitySpec` 可约束 planner 只生成当前能力可支持的 tool_calls
- `ToolFailure` 分类会回流到 facet 裁剪与重试边界

建议测试：

- 多 facet 输入下的保留 / 裁剪行为
- 低置信度 fallback 到规则模板
- facet 优先级按用户显式约束 > 引用消解必需 > 决策必需 > 安全合规必需 > 体验增强

### 10.10 P10-P12：体验、观测、预算

重点验证：

- SSE / preview / fast preview
- top-k evidence enrichment
- batch / parallel tool execution 只在 tool/evidence 层
- one turn -> one trace
- status events + single final stream
- 单 workflow 内预算与 freshness / TTL
- preview 必须满足事实一致性约束，不能把未验证内容输出成 final
- tool budget 耗尽后必须稳定触发降级，不得继续无界扩搜
- freshness / TTL 规则必须区分强时效与弱时效动态事实

建议测试：

- preview 不得写 SessionState
- 并行结果必须 reduce 到一个 `EvidencePack`
- `open_status` / `coupon` / `queue_status` 的时效规则
- `distance` 随用户位置变化重算
- budget 耗尽时稳定降级

### 10.11 P13：State 类型收敛与 BaseModel 分阶段迁移评估

重点验证：

- 先强化关键 schema，再考虑 `GraphState` 迁移
- 迁移过程不破坏现有 workflow、state writeback 和测试基线
- `GraphState` 不要求当前全量迁移，但关键边界对象必须可校验

建议测试：

- `OrchestrationDecision`、`ExecutionPlan`、`EvidencePack`、`DecisionPlan`、`AnswerPlan`、`StateUpdatePlan` 的兼容性
- 读写兼容与默认值兼容

### 10.12 P14：长期冻结项

重点验证：

- 不新增 workflow
- 不新增 tool
- 不引入 RAG
- 不引入交易 / 预约 / 支付
- 不引入 workflow 级 Map-Reduce
- 不重写整个 `graph_builder`

建议测试：

- 以文档和约束测试确认冻结项没有被引入

---

## 11. 更新最终执行顺序（P0-P14 同构）

### 11.0 P0 有限范围事实校准与 ADR 冻结

- 对齐代码事实和文档事实
- 确认 `orchestration_router_shadow` 的 active / shadow 语义
- 确认 `workflow_runner` 是 active dispatch
- 确认 `exploration_planning` 已注册但执行外壳不与 discovery 同构
- 冻结“不做 workflow 级 Map-Reduce”的 ADR
- 仅限于文档中定义的文件和测试范围，不要求读完整仓库

### 11.1 P1 单主 workflow 不变量与单 dispatch 防退化

- 固化 single-owner workflow invariant
- 加测试保护单 dispatch 和无多主字段
- 维持 `workflow_name` 单值、`workflow_runner` 单 dispatch、单 `EvidencePack` / `DecisionPlan` / `AnswerPlan` / `final_response` / `state_update_plan`
- 引入 pytest 单元测试 + 结构扫描测试 + schema validate

### 11.2 P2 Router 决策优先级与冲突保护

- 明确硬规则最高优先级
- 明确 LLM/semantic frame 负责主分类
- 明确 keyword 只作为 signal
- 通过 router 相关测试验证“附近推荐几家有券的餐厅”不会因 keyword 误路由到 `deterministic_tool`

### 11.3 P3 本地生活 facet 协议与全链路保留

- 标准化 location / category / scene / status / deal / price / quality / preference / reference facets
- 保证 facet 从 semantic 到 answer 全链路不丢
- 不把 facet 当 `route_task` 列表
- 引入 `TargetResolutionResult` 作为引用目标的统一协议
- `deterministic_tool` 维持 single-target multi-facet 语义
- `conflicting_facets` 与 `RankingPolicy` 保持最小可解释边界

### 11.4 P4 Evidence / Decision / Answer 协议收敛

- 加 `answerable / unknown / failed facets`
- 固定 search / evidence / decision / answer / verify 边界
- answer 只表达，不重新决策
- verify 失败必须 rewrite 或 fallback
- deterministic_tool 的多 tool results 必须 reduce 成单店 `EvidencePack`
- tradeoff 结果必须可追踪，而不是隐式覆盖

### 11.5 P5 SessionState 写回安全与引用消解

- 修 `current_shop` / `last_recommendation_list` / `comparison_targets` / `pending_clarification`
- 工具失败、搜索无结果、指代失败、verify 失败不污染状态
- “第一家/第二家/这家/刚才那家”必须依赖稳定上下文，失败只能澄清
- 引入 `SessionState.source / ttl / evidence_ref / location_context`
- `ClarificationPlan` 与 `resume_strategy` 形成可恢复链路
- 用 golden trace 夹具固定状态写回顺序

### 11.6 P6 本地生活复杂 query 测试矩阵

- 覆盖推荐多约束、多维对比、单店多 facet、引用失败、推荐+引用依赖、工具失败、搜索无结果、verify 失败、澄清恢复
- 测试必须检查中间状态，不只检查 final_response
- golden trace 夹具用于回放关键 query 与状态变化

### 11.7 P7 exploration_planning 协议同构与共享 adapter

- 保持 exploration_planning 独立 workflow handler
- 优先抽共享组件 / adapter，不先改图结构
- e2e 和状态污染测试补齐
- 未来是否接入 `execution_review_subgraph` 作为后续评估项

### 11.8 P8 证据不足迭代与降级策略

- `EvidenceReview` 输出结构化下一步
- retry / expand 必须受预算控制
- 部分成功可以降级回答
- unknown / failed facets 必须显式说明，不能编造

### 11.9 P9 EvidencePlanner facet 生成 / 裁剪 / 预算

- `LLM proposes facets -> taxonomy validator -> rule 补必要项 -> budget controller 裁剪 -> evidence planner 生成 tool_calls`
- 不让 LLM 任意创造 facet
- 不让 LLM 直接决定工具执行
- 低置信度 fallback 到规则模板

### 11.10 P10 体验与性能优化

- SSE / preview / fast preview
- top-k evidence enrichment
- batch / parallel tool execution
- cache reuse
- 并行只允许在 tool/evidence 层，结果 reduce 到一个 `EvidencePack`

### 11.11 P11 Observability / Metrics / Streaming 协议

- 保持 one turn -> one trace
- 不做 `trace_root -> trace_A / trace_B / trace_merge`
- 增加 spans 和 metrics
- streaming 采用 status events + single final stream，不做多 workflow token stream merge

### 11.12 P12 Deadline / Budget / Freshness / TTL

- 单 workflow 内细化 `tool_round_budget`、`retry_budget`、`expand_search_budget`、`rewrite_budget`、`facet_enrich_budget`、`deadline_remaining_ms`
- `open_status` / `coupon` / `queue_status` 强时效，`rating` / `review_tags` 弱时效，`distance` 依赖用户位置变化重算

### 11.13 P13 State 类型收敛与 GraphState BaseModel 分阶段迁移评估

- 不立即全量替换 `GraphState`
- 先强化关键对象 BaseModel / schema
- `GraphStateModel` adapter / `validate_graph_state` 后续再评估
- `TypedDict -> BaseModel` 全量迁移不作为当前验收前提

### 11.14 P14 长期冻结项与未来可选方向

- 冻结 workflow 级 Map-Reduce、万能 ReAct Agent、全量 RAG、交易/预约/支付、重写 `graph_builder`、大规模新增业务 workflow
- 未来可选方向只能在当前协议稳定后评估

---

## 12. 最终验收标准（按 P0-P14 对齐）

### 12.0 P0 有限范围事实校准与 ADR 冻结

- 有限范围事实清单存在且可核对
- 不要求读完整仓库
- 不确定处写“不确定，需要进一步检查”

### 12.1 P1 单主 workflow 不变量与单 dispatch 防退化

- `workflow_name` 仍是单值 `str`
- `workflow_runner` 每轮只 dispatch 一个 workflow
- 不存在 `workflow_names` / `final_responses` / `state_update_plans` 之类多主字段
- 通过单元测试 + 结构扫描测试 + schema validate 保护

### 12.2 P2 Router 决策优先级与冲突保护

- `workflow_name` 不被 keyword 无条件覆盖
- “附近推荐几家有券的餐厅”进入 `discovery_decision`
- “这家有券吗？”只有在有 `current_shop` 时才能走 `deterministic_tool`
- 缺 resolved target 的 coupon/status/distance query 必须澄清

### 12.3 P3 本地生活 facet 协议与全链路保留

- 推荐 / 搜索 / 对比 / 条件筛选统一进入 `discovery_decision`
- 单店事实进入 `deterministic_tool`
- 组合规划进入 `exploration_planning`
- 复杂 query facet 不丢失，且能贯穿全链路

### 12.4 P4 Evidence / Decision / Answer 协议收敛

- `EvidencePack` 能表达 `answerable / unknown / failed facets`
- `DecisionPlan` 基于 `EvidencePack`
- `AnswerPlan` 基于 `DecisionPlan`
- `final_response` 不输出无证据 claim
- `answer_verify` 失败后必须 rewrite 或 fallback

### 12.5 P5 SessionState 写回安全与引用消解

- `state_update_plan` 是唯一 SessionState 写回入口
- 工具失败、搜索无结果、指代失败、verify 失败不污染 SessionState
- “第一家/第二家/这家/刚才那家”必须依赖稳定上下文，失败只能澄清

### 12.6 P6 本地生活复杂 query 测试矩阵

- 新增 P0-P6 对应测试通过
- 测试必须检查中间状态，不只检查 final_response
- 覆盖推荐多约束、多维对比、单店多 facet、引用失败、推荐+引用依赖、工具失败、搜索无结果、verify 失败、澄清恢复

### 12.7 P7 exploration_planning 协议同构与共享 adapter

- `exploration_planning` 保持独立 workflow handler
- 工具结果 / `EvidencePack` / `AnswerVerify` 语义与主链路同构
- 优先抽共享组件 / adapter，不先改图结构
- e2e 与状态污染测试补齐

### 12.8 P8 证据不足迭代与降级策略

- `EvidenceReview` 输出结构化下一步
- retry / expand 受预算控制
- 部分成功可以降级回答
- unknown / failed facets 显式说明，不能编造
- `ToolCapabilitySpec` 与 `ToolFailure` 分类支撑 retry / degrade / fallback

### 12.9 P9 EvidencePlanner facet 生成 / 裁剪 / 预算

- LLM proposes facets -> validator -> rule -> budget -> planner 流程可用
- 不让 LLM 任意创造 facet
- 不让 LLM 直接决定工具执行
- planner 仅生成当前 `ToolCapabilitySpec` 支持的 tool_calls
- `ToolFailure` 分类回流到裁剪与重试策略

### 12.10 P10 体验与性能优化

- SSE / preview / fast preview
- top-k evidence enrichment
- batch / parallel tool execution 只在 tool/evidence 层
- 并行结果必须 reduce 到一个 `EvidencePack`
- preview 不得违反事实一致性约束
- tool budget 耗尽时应稳定降级

### 12.11 P11 Observability / Metrics / Streaming 协议

- one turn -> one trace
- 不做多 workflow token stream merge
- 支持关键 metrics 与 status events + single final stream

### 12.12 P12 Deadline / Budget / Freshness / TTL

- 单 workflow 内预算化
- 强/弱时效事实规则明确
- 超预算可稳定降级
- freshness / TTL 规则需显式区分强时效、弱时效和位置相关事实
- tool budget 与降级路径需要可测试

### 12.13 P13 State 类型收敛与 GraphState BaseModel 分阶段迁移评估

- 不立即全量替换 `GraphState`
- 关键 schema 先收敛
- `GraphState` 迁移不作为当前验收前提

### 12.14 P14 长期冻结项与未来可选方向

- 不新增 workflow
- 不新增 tool
- 不引入 RAG
- 不引入交易 / 预约 / 支付
- 不引入 workflow 级 Map-Reduce
- 不重写整个 `graph_builder`

---

## 13. 仍需进一步细化的非阻断项与超范围工程项

以下问题标记为当前架构方案不直接解决，但长期影响系统稳定性和输出质量。分为两类：(a) 方案已有 P 项但未穷尽的细化项；(b) 超出本轮架构方案范围但需要单独关注的工程项。

### 13.1 conflicting_facets / facet 冲突检测与降级策略

目标是当复杂 query 中出现互相冲突的 facet 时，系统能显式检测并降级，而不是强行合并成错误结论。

建议补充内容：

- 冲突示例：`quiet` 与 `lively`
- 冲突示例：`budget_around_x` 与明显超出预算的候选
- 冲突示例：`open_now` 与已知关门状态
- 冲突示例：`kid_friendly` 与显式不适合带娃的环境
- 降级策略：进入 `unknown_facets`、`failed_facets` 或 `clarification_fallback`

对应代码事实：

- `D:\javacode\hm-dianping\local_life_agent\domain\schemas.py`
- `D:\javacode\hm-dianping\local_life_agent\planning\evidence\evidence_builder.py`
- `D:\javacode\hm-dianping\local_life_agent\planning\decision\decision_planner.py`

### 13.2 P11 streaming event schema

目标是把业务阶段事件结构化，但仍然保持单主 workflow、单 final stream。

建议补充内容：

- `status`
- `clarification`
- `candidates_preview`
- `evidence_update`
- `comparison_update`
- `plan_preview`
- `final`
- `fallback`
- `error`

要求：

- preview 必须标记 partial
- preview 不得写 SessionState
- preview 不得冒充 final
- 不允许多个 workflow token stream 合并

对应代码事实：

- `D:\javacode\hm-dianping\local_life_agent\streaming\events.py`
- `D:\javacode\hm-dianping\local_life_agent\app.py`

### 13.3 P12 deadline / budget 触发降级规则

目标是在单 workflow 内明确预算耗尽时如何降级，避免 retry、扩搜、补证据无限进行。

建议补充内容：

- `tool_round_budget` 耗尽后降级到 `fallback` 或 `clarification`
- `retry_budget` 耗尽后禁止继续重试
- `expand_search_budget` 耗尽后停止扩搜并收束答案
- `facet_enrich_budget` 耗尽后仅返回已验证 facet
- `deadline_remaining_ms` 低于阈值时优先输出可验证结论

对应代码事实：

- `D:\javacode\hm-dianping\local_life_agent\engine\_routes.py`
- `D:\javacode\hm-dianping\local_life_agent\engine\workflow_runner.py`
- `D:\javacode\hm-dianping\local_life_agent\planning\state_update_planner.py`

### 13.4 P15 LLM 提示词质量与 prompt 版本管理（后续必做工程项）

说明：本轮架构方案只关注结构性不变量和协议收敛，不解决 LLM prompt 层的问题。但这是决定系统输出准确性的**第一因素**——比任何结构性不变量影响更大。

每个 turn 调 5+ 次 LLM（`hard_guard → top_intent_router → semantic_parse → goal_planner → decision_planner → answer_generate`），提示词分散在各 planner 和 router 文件中。LLM 版本升级、prompt 修改都可能导致同一 facet 语义漂移（如 "coupon" vs "voucher" 解析结果不同）。

建议：

- prompt 版本化 + 回归触发机制（prompt 变更自动跑相关测试）
- prompt diff review 流程
- 定期评估 LLM 版本升级对语义提取的影响

对应代码事实：

- `D:\javacode\hm-dianping\local_life_agent\llm\prompts\`
- `D:\javacode\hm-dianping\local_life_agent\llm\llm_client.py`

### 13.5 P16 Java API 契约校验（后续必做工程项）

说明：Python 侧工具 `db_tools.py` / `java_client.py` 依赖 `src/` Java 后端接口格式。如果后端返回值字段变更（如 `coupon_list` 改名为 `deals`），Python 解析将静默返回空列表 → `EvidencePlanner` 标记为 `unknown_facets` → 用户看到"暂无法确认"。

当前无入站 schema 校验，格式不匹配 = 静默降级。

建议：

- Tool result 入站 Pydantic schema 校验
- 格式异常显式 fail tool，标记 `failed_facets`，不走静默空
- Java 侧 + Python 侧建立接口契约文档，纳入 CI

对应代码事实：

- `D:\javacode\hm-dianping\local_life_agent\tools\db_tools.py`
- `D:\javacode\hm-dianping\local_life_agent\tools\java_client.py`
- 后端接口：`D:\javacode\hm-dianping\src\main\java\com\hm\dianping\controller\`

### 13.6 P17 图级错误边界（后续必做工程项）

说明：当前 `graph.invoke()` 无统一异常处理。子图异常直接传播到顶层调用者，无统一 degradation 路径。P1 单 dispatch 不变量覆盖了正常路径，但异常路径未覆盖。

建议：

- `graph_builder` 加 try/except wrapper
- 所有子图异常映射到结构化 fallback（`clarification_fallback` 或降级回答）
- 不允许原始异常传播给调用方

对应代码事实：

- `D:\javacode\hm-dianping\local_life_agent\engine\graph_builder.py`
- `D:\javacode\hm-dianping\local_life_agent\app.py`

