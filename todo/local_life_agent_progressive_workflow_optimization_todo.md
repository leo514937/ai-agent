# Local Life Agent Progressive Workflow Optimization TODO

## 1. 总结结论

当前 `local_life_agent` 的 workflow 分类方向基本正确，已经形成了 `direct_response`、`clarification_fallback`、`deterministic_tool`、`discovery_decision`、`exploration_planning` 这五条核心承接面。下一阶段不应该做全量重写，而应该优先把核心 workflow 做得更快、更可控、更可观测、更状态安全。

当前架构更适合继续走 `workflow-first, agent-assisted` 路线：简单任务走快速确定性链路，单店事实查询走 `deterministic_tool`，搜索/推荐/对比走受控的 `discovery_decision`，复杂本地生活组合规划走 bounded plan-execute-review，LLM 只参与语义理解、规划辅助、review 和回答生成，代码负责硬路由、预算、状态写入和安全边界。

已确认的一个重要事实是：`discovery_decision` 并不是一个独立的自由 agent，而是被 registry / runner 映射到 `planning_subgraph -> execution_review_subgraph -> response_subgraph` 这条受控主链；`exploration_planning` 则是独立的受限 workflow handler。这个方向是对的，下一步重点不是加新大脑，而是把现有 workflow 的边界、SSE 协议、状态协议、工具预算、retry、证据质量和可观测性补齐。

## 2. 当前架构发现

### 2.1 workflow registry 与 workflow 名称

- 文件路径：`D:\javacode\hm-dianping\local_life_agent\engine\workflow_registry.py`
- 当前行为：`LEGAL_WORKFLOW_NAMES` 只允许 `direct_response`、`deterministic_tool`、`discovery_decision`、`exploration_planning`、`clarification_fallback`；`discovery_decision` 注册到 `planning_subgraph`，其余几个注册到 `response_subgraph`。
- 为什么重要：这说明 workflow 分类已经不是“临时拼出来的 if/else”，而是受白名单约束的显式 dispatch。
- 如果不改有什么风险：新增 workflow 容易失控，或者同一业务意图被多个入口重复承接，导致路由歧义和状态语义漂移。

### 2.2 orchestration router 的角色

- 文件路径：`D:\javacode\hm-dianping\local_life_agent\planning\orchestration_router.py`
- 当前行为：`build_orchestration_decision()` 通过 policy table 把 `recommendation` / `comparison` / `condition_refine` / `scene_recommendation` / `deal_compare` 归到 `discovery_decision`，把 `local_trip_plan` / `date_plan` / `family_activity_plan` / `coffee_then_dinner` / `eat_and_play_plan` 归到 `exploration_planning`；单店查询可走 `deterministic_tool`，缺槽、指代失败、低置信度、无结果、工具失败会落到 `clarification_fallback`，chat/capability/unsafe/out_of_scope/invalid 会落到 `direct_response`。
- 为什么重要：这是 workflow-first 架构的“总分流口”，决定后续是否进入复杂链路。
- 如果不改有什么风险：router 继续膨胀会把 workflow-first 退化成一个大脑式调度器，后续所有 workflow 的边界都会被冲淡。

### 2.3 workflow runner / route 行为

- 文件路径：`D:\javacode\hm-dianping\local_life_agent\engine\workflow_runner.py`
- 当前行为：`h_workflow_runner()` 只做 registry lookup + handler dispatch + fallback；`_route_workflow_runner()` 只根据 `workflow_name` 把 `discovery_decision` 送去 `planning_subgraph`，其余 workflow 送去 `response_subgraph`。
- 为什么重要：runner 是真正的执行闸门，决定 router 的 shadow decision 是否落地。
- 如果不改有什么风险：runner 如果继续承担太多业务语义，会变成第二个 router，造成职责重叠与难以排查的分叉行为。

### 2.4 discovery_decision 链路

- 文件路径：`D:\javacode\hm-dianping\local_life_agent\engine\graph_builder.py`
- 文件路径：`D:\javacode\hm-dianping\local_life_agent\engine\_routes.py`
- 文件路径：`D:\javacode\hm-dianping\local_life_agent\engine\subgraphs\planning_subgraph.py`
- 文件路径：`D:\javacode\hm-dianping\local_life_agent\engine\subgraphs\execution_review_subgraph.py`
- 当前行为：`workflow_runner` 把 `discovery_decision` 送到 `planning_subgraph`，随后进入 `execution_review_subgraph` 做工具执行、证据构建、evidence review、decision planner、decision review，再进入 `response_subgraph` 生成最终答案。
- 为什么重要：这是搜索/推荐/对比的主链路，属于最容易出质量问题但也最适合做 budgeted workflow 的区域。
- 如果不改有什么风险：候选过多时会补太多证据，retry 可能失控，review 也可能变成不受限的软判断。

### 2.5 deterministic_tool 链路

- 文件路径：`D:\javacode\hm-dianping\local_life_agent\engine\workflows\deterministic_tool_workflow.py`
- 当前行为：对明确单店事实查询进行受限执行，尝试解析单店目标后只调用一个必要工具，随后构造 `ExecutionPlan`、`ToolResult`、`EvidencePack`、`AnswerPlan`，再用 verifier 检查；缺目标或多目标时直接回落到澄清/失败，不进入 discovery planning。
- 为什么重要：这是“最快、最稳、最省工具”的链路，适合承接营业状态、优惠券、距离、人均、地址、电话、评价摘要等单店事实。
- 如果不改有什么风险：follow-up 容易误回到搜索链路，或者把本应一次工具完成的请求升级成复杂规划。

### 2.6 exploration_planning 链路

- 文件路径：`D:\javacode\hm-dianping\local_life_agent\engine\workflows\exploration_planning_workflow.py`
- 当前行为：当前实现是独立的受限 workflow，按模板、分句或 facet hints 拆出最多 2-3 个 subgoal，做两轮以内的工具执行，组装 `ExplorationPlan`、`EvidencePack`、`AnswerPlan`，再做最终 verifier 检查；失败则回落到 `clarification_fallback`。
- 为什么重要：它承担咖啡后吃饭、约会、亲子、吃喝玩乐等组合规划任务，目标是“受控 itinerary”，不是无限开放问答。
- 如果不改有什么风险：如果边界变松，它会很快退化成一个万能复杂问答 agent。

### 2.7 clarification / direct response 链路

- 文件路径：`D:\javacode\hm-dianping\local_life_agent\engine\workflows\clarification_fallback_workflow.py`
- 文件路径：`D:\javacode\hm-dianping\local_life_agent\engine\workflows\direct_response_workflow.py`
- 当前行为：`direct_response` 直接给能力说明、安全拒答、超范围回答或轻量闲聊回复，不走工具、不进 planner、不做 evidence review；`clarification_fallback` 用于缺槽、低置信度、指代失败、无结果和工具失败等情况，倾向于只问一个清晰问题或给可信失败。
- 为什么重要：这两条链路是主流程的安全出口，也是延迟最低的两类响应。
- 如果不改有什么风险：direct response 误调用工具会拖慢首屏；clarification fallback 如果回问过多或重新 search 过度，会把用户体验变差。

### 2.8 evidence review / decision review / retry 行为

- 文件路径：`D:\javacode\hm-dianping\local_life_agent\engine\subgraphs\execution_review_subgraph.py`
- 文件路径：`D:\javacode\hm-dianping\local_life_agent\planning\evidence\evidence_review.py`
- 文件路径：`D:\javacode\hm-dianping\local_life_agent\planning\decision\decision_review.py`
- 文件路径：`D:\javacode\hm-dianping\local_life_agent\engine\_routes.py`
- 当前行为：`evidence_review` 和 `decision_review` 已经是结构化 review 节点；`_route_evidence_review()`、`_route_decision_review()` 能根据 review 结果在 `evidence_planner`、`expand_search`、`answer_plan_build`、`clarify_response`、`fallback_answer` 之间切换，并受到 `MAX_REPLAN_EVIDENCE_ROUNDS`、`MAX_EXPAND_SEARCH_ROUNDS` 等预算约束。
- 为什么重要：这是控制 retry 和重规划的核心闸门。
- 如果不改有什么风险：如果 review 结果不够结构化，LLM 建议可能会绕过预算控制，导致无限 retry 或不必要的重算。

### 2.9 当前与 workflow、response_mode、evidence、decision、retry、routing 相关的状态字段

- 文件路径：`D:\javacode\hm-dianping\local_life_agent\domain\graph_state.py`
- 文件路径：`D:\javacode\hm-dianping\local_life_agent\domain\schemas.py`
- 当前行为：GraphState 里已经有 `workflow_name`、`orchestration_pattern`、`workflow_reason`、`task_complexity`、`requires_tool`、`requires_clarification`、`response_mode`、`next_action`、`workflow_run_status`、`workflow_runner_error`、`workflow_runner_reason`、`workflow_started_at`、`workflow_finished_at`、`workflow_registered`、`workflow_callable`、`answer_plan`、`exploration_plan`、`final_response`、`evidence_pack`、`review_results`、`decision_review_result`、`rewrite_count`、`expand_search_count`、`replan_evidence_count`、`event_log`、`metrics_tags`、`trace_spans` 等字段；`OrchestrationDecision` 里有 `workflow_name`、`workflow_reason`、`task_complexity`、`requires_tool`、`requires_clarification`、`response_mode`、`confidence`、`missing_fields`、`next_action`。
- 为什么重要：这些字段已经构成了当前协议骨架，是后续做 preview/final、SSE、retry budget 和 observability 的基础。
- 如果不改有什么风险：字段继续叠加但语义不收敛，会出现多个节点覆盖同一字段、review 依据不一致、state 读写责任不清的情况。

### 2.10 当前 streaming / SSE 现状

- 文件路径：`D:\javacode\hm-dianping\local_life_agent\streaming\events.py`
- 文件路径：`D:\javacode\hm-dianping\local_life_agent\app.py`
- 当前行为：已有 `StreamEventEnvelope` 和 `StreamEventType`，但 `app.py` 当前 SSE 事件输出主要是 `trace_started`、`input_normalized`、`answer_delta`、`final`；`events.py` 里虽然定义了更多类型，但 `status`、`clarification`、`candidates_preview`、`evidence_update`、`comparison_update`、`plan_preview`、`fallback`、`error` 这些业务层阶段事件在当前 app 流里未确认落地。
- 为什么重要：这说明当前已经有“事件信封”，但还没有形成完整的业务阶段性响应协议。
- 如果不改有什么风险：前端只能做 token streaming，无法稳定消费 workflow 阶段事件，也就无法做真正的首屏预览和过程可视化。

### 2.11 当前测试覆盖现状

- 文件路径：`D:\javacode\hm-dianping\local_life_agent\tests\test_workflow_registry.py`
- 文件路径：`D:\javacode\hm-dianping\local_life_agent\tests\test_workflow_runner.py`
- 文件路径：`D:\javacode\hm-dianping\local_life_agent\tests\test_orchestration_router.py`
- 文件路径：`D:\javacode\hm-dianping\local_life_agent\tests\test_deterministic_tool_workflow.py`
- 文件路径：`D:\javacode\hm-dianping\local_life_agent\tests\test_exploration_planning_workflow.py`
- 文件路径：`D:\javacode\hm-dianping\local_life_agent\tests\test_comparison_flow.py`
- 文件路径：`D:\javacode\hm-dianping\local_life_agent\tests\test_recommendation_flow.py`
- 文件路径：`D:\javacode\hm-dianping\local_life_agent\tests\test_phase7_workflows.py`
- 文件路径：`D:\javacode\hm-dianping\local_life_agent\tests\test_streaming_event_contract.py`
- 文件路径：`D:\javacode\hm-dianping\local_life_agent\tests\test_app_streaming.py`
- 文件路径：`D:\javacode\hm-dianping\local_life_agent\tests\test_comprehensive_graph_e2e.py`
- 文件路径：`D:\javacode\hm-dianping\local_life_agent\tests\test_05_graph.py`
- 当前行为：现有测试已经覆盖了 workflow registry、workflow runner、router、deterministic tool、exploration planning、comparison / recommendation 以及 streaming contract / app streaming 的部分行为。
- 为什么重要：这意味着后续改动可以以这些文件作为验收基线，而不是从零建立测试语义。
- 如果不改有什么风险：如果只改文档不对齐测试矩阵，后续优化很容易出现“设计写得很好，但没人知道怎么验收”的问题。

### 2.12 当前已有架构报告

- 文件路径：`D:\javacode\hm-dianping\todo\state1\discovery_decision_mapreduce_semantics_report.md`
- 文件路径：`D:\javacode\hm-dianping\todo\state1\discovery_vs_exploration_workflow_design_report.md`
- 文件路径：`D:\javacode\hm-dianping\todo\state1\local_life_agent_architecture_industry_research_report.md`
- 当前行为：这些报告已经分别说明了 discovery 的 MapReduce-style 执行、discovery 与 exploration 的 sibling workflow 边界，以及与业界 workflow-first / bounded agent 范式的对齐。
- 为什么重要：这些文档可直接作为本 TODO 的背景证据，不需要重新发明结论。
- 如果不改有什么风险：如果忽略这些已有结论，后续计划容易重复讨论已经确认过的边界问题。

## Exploration Planning Workflow Alignment

### 1. 当前事实

| 维度 | 代码事实 | 文件路径 |
| --- | --- | --- |
| workflow 白名单 / registry | `exploration_planning` 已经存在于 `LEGAL_WORKFLOW_NAMES`，并且在 default registry 中显式注册 | `D:\javacode\hm-dianping\local_life_agent\engine\workflow_registry.py` |
| 注册信息 | `workflow_name="exploration_planning"`，`handler=run_exploration_planning_workflow`，`entry_node="response_subgraph"`，`description="Phase 8 exploration planning workflow."` | `D:\javacode\hm-dianping\local_life_agent\engine\workflow_registry.py` |
| orchestration_router 是否会路由到它 | 会。`local_trip_plan`、`date_plan`、`family_activity_plan`、`coffee_then_dinner`、`eat_and_play_plan` 被映射到 `exploration_planning` | `D:\javacode\hm-dianping\local_life_agent\planning\orchestration_router.py` |
| workflow_runner / route 层如何处理 | `h_workflow_runner()` 通过 registry 直接 dispatch；`_route_workflow_runner()` 对除 `discovery_decision` 之外的 registered workflow 一律返回 `response_subgraph` | `D:\javacode\hm-dianping\local_life_agent\engine\workflow_runner.py`、`D:\javacode\hm-dianping\local_life_agent\engine\_routes.py` |
| 最终进入的入口 | 当前是先经过 `workflow_runner`，然后直接进入 `response_subgraph`；不是单独的 `exploration_planning_subgraph` | `D:\javacode\hm-dianping\local_life_agent\engine\workflow_runner.py`、`D:\javacode\hm-dianping\local_life_agent\engine\_routes.py`、`D:\javacode\hm-dianping\local_life_agent\engine\graph_builder.py` |
| 是否复用了 discovery_decision 主链路 | 当前没有复用 `discovery_decision` 的 `planning_subgraph -> execution_review_subgraph -> response_subgraph` 主链；`exploration_planning_workflow` 是独立 handler，自行做 subgoal、search、expand、evidence、verify | `D:\javacode\hm-dianping\local_life_agent\engine\workflows\exploration_planning_workflow.py`、`D:\javacode\hm-dianping\local_life_agent\engine\subgraphs\planning_subgraph.py`、`D:\javacode\hm-dianping\local_life_agent\engine\subgraphs\execution_review_subgraph.py` |
| 是否有独立 subgraph | 当前代码未确认存在独立 `exploration_planning_subgraph`；现有代码只看到独立 workflow handler | `D:\javacode\hm-dianping\local_life_agent\engine\graph_builder.py`、`D:\javacode\hm-dianping\local_life_agent\engine\workflows\exploration_planning_workflow.py` |
| 当前测试覆盖情况 | 已有测试覆盖 registry 注册、workflow_runner dispatch、workflow 直接执行；`test_exploration_planning_workflow.py` 和 `test_workflow_runner.py` 明确覆盖 `exploration_planning`，但当前代码未确认有专门的 graph e2e 用例来验证它在完整图上的外层链路 | `D:\javacode\hm-dianping\local_life_agent\tests\test_workflow_registry.py`、`D:\javacode\hm-dianping\local_life_agent\tests\test_workflow_runner.py`、`D:\javacode\hm-dianping\local_life_agent\tests\test_exploration_planning_workflow.py`、`D:\javacode\hm-dianping\local_life_agent\tests\test_comprehensive_graph_e2e.py` |

### 2. 注册层与执行链路的判断

- 注册层是否对齐：是。`exploration_planning` 已经和其他核心 workflow 一起注册在同一个 whitelist / registry 层。
- 执行链路是否对齐：否。当前它没有像 `discovery_decision` 那样形成外层的 `workflow_runner -> planning_subgraph -> execution_review_subgraph -> response_subgraph` 清晰链路，而是由 `workflow_runner` 直接 dispatch 到独立 workflow handler，再回到 `response_subgraph`。
- 更精确的表述应该是：当前 `exploration_planning` 已经在 workflow registry 同层注册，但 route / execution 层仍未形成和 `discovery_decision` 同等清晰的外层 plan-execute-review 链路。

### 3. 为什么这件事重要

`exploration_planning` 面向的不是普通闲聊，而是更接近受限 itinerary 的本地生活组合任务，例如：

- coffee then dinner
- date plan
- family activity
- eat and play plan
- 多地点组合
- 轻量路线 / 顺序规划

这类任务通常需要：

- 子目标拆解
- 多候选搜索
- 候选组合
- 距离 / 时间 / 营业状态校验
- 整体计划 review
- 阶段性 plan preview / final answer

因此它不应该长期只表现得像普通 response workflow。

但也不能把它做成万能复杂问答 Agent。它需要的是受限的、可预算的、可预览的执行模型，而不是开放式无限 ReAct loop。

### 4. 目标形态

优先目标可以写成两档：

```text
orchestration_router
  -> workflow_runner
  -> exploration_planning_subgraph
  -> response_subgraph
  -> state_update_plan
```

如果第一阶段不新增 subgraph，至少应明确成：

```text
orchestration_router
  -> workflow_runner
  -> run_exploration_planning_workflow
  -> response_subgraph
```

其中 `run_exploration_planning_workflow` 或未来的 `exploration_planning_subgraph` 应承担：

- plan_preview
- subgoal planning
- bounded candidate search
- bounded tool execution
- evidence build
- plan review
- final answer draft

### 5. 改造 TODO

### P1. Exploration Planning Execution Alignment

- 目标：让 `exploration_planning` 在 registry 层保持与其他 workflow 同层可见，同时在 route / execution 层拥有比“直接 dispatch 到 response_subgraph”更清晰的受限执行链路；优先保证它的子目标拆解、候选搜索、工具预算和阶段性 preview 能被显式表达。
- 可能涉及的文件：
  - `D:\javacode\hm-dianping\local_life_agent\engine\workflow_registry.py`
  - `D:\javacode\hm-dianping\local_life_agent\engine\workflow_runner.py`
  - `D:\javacode\hm-dianping\local_life_agent\engine\_routes.py`
  - `D:\javacode\hm-dianping\local_life_agent\engine\graph_builder.py`
  - `D:\javacode\hm-dianping\local_life_agent\engine\workflows\exploration_planning_workflow.py`
  - `D:\javacode\hm-dianping\local_life_agent\engine\subgraphs\response_subgraph.py`
  - `D:\javacode\hm-dianping\local_life_agent\streaming\events.py`
- 实现说明：第一阶段可以只保留现有独立 workflow handler，但把它的执行边界、preview/final、候选和工具预算、fallback 语义写清楚；如果后续代码审查证明最小改动安全，再评估是否抽成 `exploration_planning_subgraph`。无论哪条路径，都要避免把 `discovery_decision` 的主链路粗暴挪用过来。
- 验收标准：
  - `exploration_planning` 与其他 workflow 在 registry / whitelist 层保持同层可见
  - route 层不再把所有非 `discovery_decision` workflow 简单等同处理
  - `exploration_planning` 有明确执行入口
  - 不破坏 `discovery_decision`、`deterministic_tool`、`direct_response`、`clarification_fallback` 的现有路径
  - 不把 `exploration_planning` 变成万能 ReAct Agent
  - 不把所有复杂问题都路由到 `exploration_planning`
  - 有测试计划覆盖 router 选择、workflow_runner 路由、bounded subgoal / tool budget、fallback / clarification、不误伤 recommendation / comparison / deterministic_tool
- 风险 / 非目标：
  - 本轮只更新 TODO 文档，不修改运行时代码
  - 不要整体重写 `graph_builder`
  - 不要把 `exploration_planning` 粗暴接入 `discovery_decision` 的 `planning_subgraph`，除非代码审查证明这是安全且符合现有设计的最小改动
  - 不要新增万能 `complex_agent`
  - 不要引入开放式无限 ReAct loop
  - 不要新增交易、订单、退款、预约、支付能力
  - 不要破坏当前已通过的 recommendation、comparison、single coupon、deterministic tool 链路

## 3. 目标 Workflow 模型

### 3.1 direct_response

用途：

- 能力说明
- 安全拒答
- 超出范围回答
- 轻量闲聊

目标行为：

- 不查 DB
- 不调工具
- 不进 planner
- 不做 evidence review
- 最快生成 final response

### 3.2 clarification_fallback

用途：

- 缺少必要槽位
- 指代不清
- 低置信度
- 无结果
- 工具失败兜底

目标行为：

- 只问一个清晰的澄清问题
- 保留有用上下文
- 不无意义重新 search
- 不进入复杂规划链路

### 3.3 deterministic_tool

用途：

- 单店事实查询
- 目标店铺明确
- 工具意图明确

示例：

- 营业状态
- 优惠券
- 距离
- 人均
- 地址
- 电话
- 评价摘要

目标行为：

- 从 `current_shop` / `last_recommendation_list` / 显式店名中解析目标
- 只调用一个必要工具，或在合适时调用一个 batch lookup
- 做 hard evidence check
- 直接生成 final answer
- 不进入 discovery planning
- 不做多步骤 recommendation review

### 3.4 discovery_decision

用途：

- 搜索
- 推荐
- 条件筛选
- 对比
- 优惠对比
- 场景化推荐

目标行为：

- 搜索候选
- 初始候选召回后快速产出 fast preview
- 只对 TopK 候选补证据
- 工具尽量 batch / parallel
- 仅在必要时做 evidence review 和 decision review
- 支持有预算限制的 retry / expand search
- 支持阶段性响应事件

### 3.5 exploration_planning

用途：

- 多步骤本地生活计划
- 咖啡后吃饭
- 约会计划
- 亲子活动
- 吃饭 + 逛街
- 轻量路线 / 顺序规划

目标行为：

- 子目标数量受限
- 每个子目标候选数量受限
- 先输出 plan preview
- 独立子目标尽量并行搜索
- 只组合少量候选方案
- 验证整体计划一致性
- 不做开放式无限 ReAct loop

## 4. 关键优化工作流

### P0. Workflow 边界清理

- 目标：确保每条 workflow 有清晰职责边界；确保 `direct_response` 和 `clarification_fallback` 不会误调工具；确保 `deterministic_tool` 不会进入推荐规划；确保 `discovery_decision` 仍然是搜索 / 推荐 / 对比主链路；确保 `exploration_planning` 是受控本地生活规划链路，而不是万能复杂问答 Agent。
- 可能涉及的文件：
  - `D:\javacode\hm-dianping\local_life_agent\engine\workflow_registry.py`
  - `D:\javacode\hm-dianping\local_life_agent\engine\workflow_runner.py`
  - `D:\javacode\hm-dianping\local_life_agent\engine\_routes.py`
  - `D:\javacode\hm-dianping\local_life_agent\planning\orchestration_router.py`
  - `D:\javacode\hm-dianping\local_life_agent\engine\workflows\direct_response_workflow.py`
  - `D:\javacode\hm-dianping\local_life_agent\engine\workflows\clarification_fallback_workflow.py`
  - `D:\javacode\hm-dianping\local_life_agent\engine\workflows\deterministic_tool_workflow.py`
  - `D:\javacode\hm-dianping\local_life_agent\engine\workflows\exploration_planning_workflow.py`
  - `D:\javacode\hm-dianping\local_life_agent\engine\subgraphs\planning_subgraph.py`
  - `D:\javacode\hm-dianping\local_life_agent\engine\subgraphs\execution_review_subgraph.py`
- 实现说明：先写 workflow matrix 和 route matrix，再逐条检查 router / registry / runner / workflow 之间是否存在职责越界；把“该 workflow 绝不做什么”写成协议；保留当前五条核心 workflow，不新增 generic catch-all agent。
- 验收标准：
  - 现有测试通过
  - TODO 中存在 workflow matrix，说明每类任务由哪条 workflow 承接
  - 不新增 generic catch-all agent
- 风险 / 非目标：
  - 非目标是重写整张图
  - 非目标是把所有能力合并为一个自由 agent

### P0. State Protocol 清理

- 目标：识别用于 routing、workflow decision、evidence、answer、retry、response mode 的字段；识别重复字段或语义重叠字段；识别可能被多个节点覆盖的字段；提出 state ownership table。
- 可能涉及的文件：
  - `D:\javacode\hm-dianping\local_life_agent\domain\graph_state.py`
  - `D:\javacode\hm-dianping\local_life_agent\domain\schemas.py`
  - `D:\javacode\hm-dianping\local_life_agent\engine\workflow_runner.py`
  - `D:\javacode\hm-dianping\local_life_agent\engine\subgraphs\planning_subgraph.py`
  - `D:\javacode\hm-dianping\local_life_agent\engine\subgraphs\execution_review_subgraph.py`
  - `D:\javacode\hm-dianping\local_life_agent\engine\subgraphs\response_subgraph.py`
  - `D:\javacode\hm-dianping\local_life_agent\engine\workflows\deterministic_tool_workflow.py`
  - `D:\javacode\hm-dianping\local_life_agent\engine\workflows\exploration_planning_workflow.py`
- 实现说明：先做字段盘点，再做 ownership table；特别关注 `fast_answer_preview`、`final_answer`、`answer_drafts`、`stream_events`、`evidence_level`、`is_partial`、`retry_count`、`tool_round_count`、`latency_budget_ms`、`candidate_recall_limit`、`candidate_enrich_limit`、`final_display_limit` 这些候选字段是否已经存在、是否需要规范化，当前本轮只写计划，不实现字段。
- 验收标准：
  - 表格明确每个字段的写入节点、读取节点、生命周期、覆盖策略、风险
  - 明确哪些字段是现有字段，哪些只是候选字段
  - 不在此阶段改运行时逻辑
- 风险 / 非目标：
  - 非目标是一次性清空所有旧字段
  - 非目标是把所有状态压缩成单一 DTO

### P1. 阶段性 SSE 响应协议

- 目标：定义业务层 SSE 事件，而不是只做 LLM token streaming；提出 StreamEvent schema；定义每条 workflow 可以发出的事件类型。
- 可能涉及的文件：
  - `D:\javacode\hm-dianping\local_life_agent\streaming\events.py`
  - `D:\javacode\hm-dianping\local_life_agent\app.py`
  - `D:\javacode\hm-dianping\local_life_agent\engine\workflows\*.py`
  - `D:\javacode\hm-dianping\local_life_agent\engine\subgraphs\*.py`
- 实现说明：定义 `status`、`clarification`、`candidates_preview`、`evidence_update`、`comparison_update`、`plan_preview`、`final`、`fallback`、`error` 这些事件的触发时机、必填字段、partial/final 标识、可见内容边界；明确 preview 不能把未验证的优惠、营业状态、距离、评价当成最终事实。
- 验收标准：
  - 不同 workflow 的事件类型表清晰
  - preview 与 final 的内容边界清晰
  - SSE 事件 schema 可以被前端稳定消费
- 风险 / 非目标：
  - 非目标是把 token streaming 伪装成阶段性业务事件
  - 非目标是让 preview 越权替代 final answer

### P1. discovery_decision 的 Fast Preview

- 目标：在初始 search candidate recall 后新增 `fast_candidate_summary` 阶段，只使用 `search_shops` 返回的基础字段，产出 Top 3 初筛候选、简短安全理由、缺失证据字段。
- 可能涉及的文件：
  - `D:\javacode\hm-dianping\local_life_agent\engine\subgraphs\planning_subgraph.py`
  - `D:\javacode\hm-dianping\local_life_agent\engine\subgraphs\execution_review_subgraph.py`
  - `D:\javacode\hm-dianping\local_life_agent\planning\decision\candidate_decision.py`
  - `D:\javacode\hm-dianping\local_life_agent\planning\evidence\evidence_builder.py`
  - `D:\javacode\hm-dianping\local_life_agent\streaming\events.py`
- 实现说明：先把 preview 和 final 分离，preview 只能描述“初筛候选”和“暂缺证据”，不能写 verified evidence；final answer 再基于补证据后的结果修正或细化 preview。
- 验收标准：
  - TODO 中明确 preview / final separation
  - preview 不写 verified evidence
  - 有对应测试矩阵要求
- 风险 / 非目标：
  - 非目标是让 preview 直接取代 final
  - 非目标是让 preview 变成新的 truth source

### P1. TopK Evidence Enrichment

- 目标：把“给所有候选补证据”改为“召回多，精补少”。
- 可能涉及的文件：
  - `D:\javacode\hm-dianping\local_life_agent\engine\subgraphs\execution_review_subgraph.py`
  - `D:\javacode\hm-dianping\local_life_agent\planning\evidence\evidence_builder.py`
  - `D:\javacode\hm-dianping\local_life_agent\planning\evidence\evidence_review.py`
  - `D:\javacode\hm-dianping\local_life_agent\planning\decision\decision_review.py`
- 实现说明：推荐默认值为 `candidate_recall_limit=10..20`、`candidate_enrich_limit=3..5`、`final_display_limit=3`、`max_retry=1`、`max_tool_rounds=2`；只给可能进入最终答案的候选补证据，对比场景只补 comparison targets 和缺失字段，多轮追问尽量复用 cached evidence。
- 验收标准：
  - 只对 TopK 候选做证据补齐
  - 不同任务类型有不同 evidence 优先级
  - 对比场景只补被比较店铺和缺失字段
- 风险 / 非目标：
  - 非目标是默认 enrich 所有候选
  - 非目标是把 fallback 当成补证据捷径

### P1. Batch / Parallel Tool Execution

- 目标：识别当前工具执行形态；如果缺失，提出 batch tool interface。
- 可能涉及的文件：
  - `D:\javacode\hm-dianping\local_life_agent\core\execution_core.py`
  - `D:\javacode\hm-dianping\local_life_agent\tools\gateway.py`
  - `D:\javacode\hm-dianping\local_life_agent\engine\subgraphs\execution_review_subgraph.py`
  - `D:\javacode\hm-dianping\local_life_agent\tools\registry.py`
  - `D:\javacode\hm-dianping\local_life_agent\tools\retry.py`
- 实现说明：梳理哪些工具可以并行，哪些工具依赖 search 结果；如果需要，定义 batch 接口，例如 `batch_get_shop_status(shop_ids)`、`batch_get_coupon_summary(shop_ids)`、`batch_get_review_summary(shop_ids)`、`batch_get_distance(shop_ids)`；统一超时和 fallback 策略，统一 evidence shape。
- 验收标准：
  - 除非必要，不允许按“每家店 x 每个字段”串行调工具
  - 工具调用有 timeout 和 fallback 策略
  - 工具结果统一归一化成一致的 evidence shape
- 风险 / 非目标：
  - 非目标是绕过 gateway 直连数据源
  - 非目标是把 batch 设计成无限并发

### P1. Budgeted Retry and Review

- 目标：区分 hard review 和 semantic review；retry 决策必须由代码根据结构化 review result + budget 决定。
- 可能涉及的文件：
  - `D:\javacode\hm-dianping\local_life_agent\planning\evidence\evidence_review.py`
  - `D:\javacode\hm-dianping\local_life_agent\planning\decision\decision_review.py`
  - `D:\javacode\hm-dianping\local_life_agent\engine\_routes.py`
  - `D:\javacode\hm-dianping\local_life_agent\engine\subgraphs\execution_review_subgraph.py`
- 实现说明：hard review 用规则判断工具失败、超时、候选为空、缺少必要字段、schema 不合法、retry 次数超过上限；semantic review 可判断场景适配、推荐理由是否被证据支持、对比结论是否成立、计划是否连贯；LLM 可以建议 retry，但不能单方面触发无限 retry。
- 验收标准：
  - `retry_count` 和 `tool_round_count` 必须在 retry 前检查
  - review 输出必须结构化
  - 必须有明确 route：`proceed`、`retry`、`clarify`、`degrade`、`fallback`
- 风险 / 非目标：
  - 非目标是把 retry 交给 LLM 自由裁决
  - 非目标是无限 replan

### P1. 缓存和上下文复用

- 目标：说明 session 内应缓存哪些内容；提出多轮追问复用规则。
- 可能涉及的文件：
  - `D:\javacode\hm-dianping\local_life_agent\domain\state.py`
  - `D:\javacode\hm-dianping\local_life_agent\engine\subgraphs\merge_clarification.py`
  - `D:\javacode\hm-dianping\local_life_agent\engine\subgraphs\planning_subgraph.py`
  - `D:\javacode\hm-dianping\local_life_agent\engine\workflows\deterministic_tool_workflow.py`
  - `D:\javacode\hm-dianping\local_life_agent\engine\workflows\exploration_planning_workflow.py`
- 实现说明：至少考虑 `last_search_results`、`last_recommendation_list`、`current_shop`、`comparison_targets`、`shop_evidence_cache`、`tool_result_cache`、`last_user_constraints`；明确“第二家有券吗”不应重新 search，“第一家和第三家比呢”应从上一轮候选解析目标，dynamic 字段需要 freshness / validity 说明。
- 验收标准：
  - follow-up 能复用上一轮结果
  - deterministic follow-up 只调用缺失事实工具
  - 缓存字段有时效说明
- 风险 / 非目标：
  - 非目标是把缓存当成永不过期事实
  - 非目标是为了复用而牺牲正确性

### P2. Exploration Planning Bounded Agent

- 目标：把 `exploration_planning` 明确定义为受控本地生活规划 workflow，而不是万能复杂问答 agent。
- 可能涉及的文件：
  - `D:\javacode\hm-dianping\local_life_agent\engine\workflows\exploration_planning_workflow.py`
  - `D:\javacode\hm-dianping\local_life_agent\streaming\events.py`
  - `D:\javacode\hm-dianping\local_life_agent\engine\workflows\clarification_fallback_workflow.py`
- 实现说明：增加子目标和方案预算，推荐默认值为 `subgoal_limit=2..3`、`per_subgoal_candidate_limit=3..5`、`plan_option_limit=1 个主方案 + 1 个备选方案`、`max_retry=1`；阶段性事件应包括 `plan_preview`、`subgoal status`、`candidates_preview`、`evidence_update`、`final`。
- 验收标准：
  - 能处理 coffee+dinner、date、family、eat-and-play 类任务
  - 不尝试回答 policy、order、refund、开放域复杂问答
  - 候选或证据不足时可以优雅降级
- 风险 / 非目标：
  - 非目标是把 exploration 变成泛化问答入口
  - 非目标是突破预算上限

### P2. Comparison Path 优化

- 目标：如果当前代码没有单独 comparison workflow，则将 comparison 作为 `discovery_decision` 下的 specialized mode；复用上一轮推荐结果；先解析 comparison targets，再决定是否 search；只补被比较店铺和缺失比较字段；必要时发出 `comparison_update`。
- 可能涉及的文件：
  - `D:\javacode\hm-dianping\local_life_agent\planning\decision\comparison_planner.py`
  - `D:\javacode\hm-dianping\local_life_agent\engine\subgraphs\planning_subgraph.py`
  - `D:\javacode\hm-dianping\local_life_agent\engine\subgraphs\execution_review_subgraph.py`
  - `D:\javacode\hm-dianping\local_life_agent\streaming\events.py`
- 实现说明：简单对比不重新跑完整推荐搜索；对比理由必须基于已有 evidence；缺失 evidence 时做 targeted enrichment，而不是重启完整 workflow。
- 验收标准：
  - 简单对比不重跑完整推荐
  - 对比结论可追溯到 evidence
  - 缺失证据时只做定向补齐
- 风险 / 非目标：
  - 非目标是让 comparison 独立膨胀成新大 workflow
  - 非目标是每次对比都从头搜索

### P2. 可观测性和指标

- 目标：定义 trace 字段和 metrics。
- 可能涉及的文件：
  - `D:\javacode\hm-dianping\local_life_agent\observability\trace.py`
  - `D:\javacode\hm-dianping\local_life_agent\observability\metrics.py`
  - `D:\javacode\hm-dianping\local_life_agent\observability\file_logger.py`
  - `D:\javacode\hm-dianping\local_life_agent\engine\workflow_runner.py`
  - `D:\javacode\hm-dianping\local_life_agent\engine\subgraphs\*.py`
  - `D:\javacode\hm-dianping\local_life_agent\engine\workflows\*.py`
- 实现说明：必须包含 `workflow_name`、`route_reason`、`response_mode`、`tool_call_count`、`tool_round_count`、`retry_count`、`candidate_count_recalled`、`candidate_count_enriched`、`first_event_latency_ms`、`final_latency_ms`、`fallback_reason`、`evidence_level`、`semantic_review_called`、`cache_hit_count`；失败原因要能通过 trace 定位，而不是只能人工读日志。
- 验收标准：
  - 每条 workflow 都能按 latency、tool cost、retry rate、fallback rate、answer quality 评估
  - 阶段性响应是否成功可以通过 `first_event_latency_ms` 衡量
  - 失败原因可以通过 trace 定位
- 风险 / 非目标：
  - 非目标是把观测只留在日志里
  - 非目标是无区分地把所有字段都打进 trace

### P2. 测试和验收矩阵

- 目标：创建测试矩阵，覆盖 `direct_response`、`clarification_fallback`、`deterministic_tool`、`discovery_decision`、`comparison`、`exploration_planning`。
- 可能涉及的文件：
  - `D:\javacode\hm-dianping\local_life_agent\tests\test_workflow_registry.py`
  - `D:\javacode\hm-dianping\local_life_agent\tests\test_workflow_runner.py`
  - `D:\javacode\hm-dianping\local_life_agent\tests\test_orchestration_router.py`
  - `D:\javacode\hm-dianping\local_life_agent\tests\test_deterministic_tool_workflow.py`
  - `D:\javacode\hm-dianping\local_life_agent\tests\test_exploration_planning_workflow.py`
  - `D:\javacode\hm-dianping\local_life_agent\tests\test_comparison_flow.py`
  - `D:\javacode\hm-dianping\local_life_agent\tests\test_recommendation_flow.py`
  - `D:\javacode\hm-dianping\local_life_agent\tests\test_phase7_workflows.py`
  - `D:\javacode\hm-dianping\local_life_agent\tests\test_streaming_event_contract.py`
  - `D:\javacode\hm-dianping\local_life_agent\tests\test_app_streaming.py`
  - `D:\javacode\hm-dianping\local_life_agent\tests\test_comprehensive_graph_e2e.py`
- 实现说明：每条 workflow 至少包含 happy path、missing slot、ambiguous reference、tool failure、empty result、cache reuse、retry budget reached；如果适用，再加 preview / final separation；不要用会掩盖 DB / tool 集成问题的 fake 行为，除非明确标注为 unit-level。
- 验收标准：
  - TODO 中列出需要新增或更新的测试
  - 关键现有测试保持绿色
  - 单测和集成验收层次清晰
- 风险 / 非目标：
  - 非目标是只加单测不做验收矩阵
  - 非目标是用 fake 覆盖真实集成问题

### P3. 未来 Workflow 扩展规则

- 目标：定义什么时候才应该新增 workflow。
- 可能涉及的文件：
  - `D:\javacode\hm-dianping\local_life_agent\engine\workflow_registry.py`
  - `D:\javacode\hm-dianping\local_life_agent\planning\orchestration_router.py`
  - `D:\javacode\hm-dianping\local_life_agent\domain\schemas.py`
- 实现说明：只有同时满足工具集合明显不同、状态协议明显不同、安全/权限边界明显不同、SLA 明显不同、fallback 策略明显不同、验收测试明显不同、高频且有明确业务价值时，才建议新增 workflow；可作为未来候选的 workflow 包括 `policy_rag_workflow`、`coupon_rule_workflow`、`order_support_workflow`、`booking_workflow`、`route_planning_workflow`、`personalized_recommendation_workflow`。
- 验收标准：
  - 新增 workflow 有明确门槛
  - 当前不新增这些候选 workflow
  - 不引入交易 / 订单 mutation
- 风险 / 非目标：
  - 非目标是为未来可能用到的场景提前造路由
  - 非目标是引入开放式万能 ReAct Agent

## 5. 推荐执行顺序

### Phase A

- 范围：workflow matrix、state ownership table、metrics / trace plan
- 预计涉及代码区域：
  - `D:\javacode\hm-dianping\local_life_agent\domain\graph_state.py`
  - `D:\javacode\hm-dianping\local_life_agent\domain\schemas.py`
  - `D:\javacode\hm-dianping\local_life_agent\observability\trace.py`
  - `D:\javacode\hm-dianping\local_life_agent\observability\metrics.py`
  - `D:\javacode\hm-dianping\local_life_agent\planning\orchestration_router.py`
- 风险：如果字段和责任表没先收敛，后面的 preview / SSE / retry 都会建立在不稳定协议上。
- 验收标准：每条 workflow 的职责、字段、指标和路由都能在文档中一眼读清。

### Phase B

- 范围：fast preview 协议、SSE event schema、preview / final 状态隔离
- 预计涉及代码区域：
  - `D:\javacode\hm-dianping\local_life_agent\streaming\events.py`
  - `D:\javacode\hm-dianping\local_life_agent\app.py`
  - `D:\javacode\hm-dianping\local_life_agent\engine\workflows\*.py`
  - `D:\javacode\hm-dianping\local_life_agent\engine\subgraphs\*.py`
- 风险：如果 preview 没有明确边界，前端会把未验证事实误当最终答案。
- 验收标准：事件类型、必填字段、partial/final 边界、可见性规则全部明确。

### Phase C

- 范围：TopK enrichment、batch / parallel tool execution、cache reuse
- 预计涉及代码区域：
  - `D:\javacode\hm-dianping\local_life_agent\engine\subgraphs\execution_review_subgraph.py`
  - `D:\javacode\hm-dianping\local_life_agent\core\execution_core.py`
  - `D:\javacode\hm-dianping\local_life_agent\tools\gateway.py`
  - `D:\javacode\hm-dianping\local_life_agent\domain\state.py`
- 风险：如果不限制补证据范围，工具成本和延迟会迅速上升。
- 验收标准：工具调用预算明确，缓存复用规则明确，证据 shape 统一。

### Phase D

- 范围：budgeted retry / review、comparison 优化、exploration_planning bounded 优化
- 预计涉及代码区域：
  - `D:\javacode\hm-dianping\local_life_agent\planning\evidence\evidence_review.py`
  - `D:\javacode\hm-dianping\local_life_agent\planning\decision\decision_review.py`
  - `D:\javacode\hm-dianping\local_life_agent\engine\workflows\exploration_planning_workflow.py`
  - `D:\javacode\hm-dianping\local_life_agent\planning\decision\comparison_planner.py`
- 风险：review 和 retry 若没预算化，系统会出现循环、超时和不可解释降级。
- 验收标准：retry / fallback / clarify 路径结构化且可观测。

### Phase E

- 范围：tests and acceptance suite、performance baseline、final cleanup
- 预计涉及代码区域：
  - `D:\javacode\hm-dianping\local_life_agent\tests\*.py`
  - `D:\javacode\hm-dianping\local_life_agent\eval\*.py`
  - `D:\javacode\hm-dianping\local_life_agent\observability\*.py`
- 风险：如果没有验收矩阵，前面做的优化无法稳定回归。
- 验收标准：核心 workflow 的 happy path、失败 path、缓存复用、preview/final separation 都有稳定覆盖。

## 6. 非目标

- 不要整体重写 `graph_builder`。
- 不要把 `top_intent_router` 改成全局 LLM 大脑。
- 不要创建万能自由 ReAct Agent。
- 不要新增交易、支付、退款、预约、mutation workflow。
- 除非未来 policy workflow 明确需要，否则不要引入 RAG。
- 当前核心 workflow 稳定前，不要新增大量用户能力。
- preview 不能覆盖 final answer。
- 不允许 LLM 直接控制无限 retry。
- 默认不要 enrich 所有候选。
- 不要破坏现有 `single_coupon`、`comparison`、`deterministic_tool`、`recommendation` 链路。

## 7. 最终建议

当前架构方向适合非交易型本地生活助手。下一步应该做 progressive workflow optimization：

- 更快的首屏响应
- 有预算的工具执行
- 状态安全的 preview / final 协议
- 结构化 evidence
- 可观测的 retry / review 行为

不要急着扩展很多新 workflow。先把现有五条核心 workflow 做快、做稳、做可测、做可观测。
