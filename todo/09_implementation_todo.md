# 09 实施任务清单

## 目标

把改造拆成可执行 TODO，并统一 Phase 编号、依赖关系、验收方式和风险控制。

本文件必须和前面文档一致：

- 当前真实主链路仍是单主链路
- 当前只有一级 `top_intent_router`
- 当前没有正式 `orchestration_router`、`workflow_runner` 和正式多 workflow 分流
- Phase 1 只做当前单主链路能力边界收口
- Phase 4 只做 `OrchestrationRouter`
- Phase 5 才做 `workflow_runner` 与 workflow registry

## Phase 统一口径

```text
Phase 0：现状基线与回归测试
Phase 1：当前单主链路能力边界收口
Phase 2：Core 薄封装与可单测边界
Phase 3：固化当前主链路为 DiscoveryDecisionWorkflow 雏形
Phase 4：新增 OrchestrationRouter（二级路由）
Phase 5：新增 workflow_runner 与 workflow registry
Phase 6：新增 DeterministicToolWorkflow
Phase 7：新增 DirectResponseWorkflow 与 ClarificationFallbackWorkflow
Phase 8：新增 ExplorationPlanningWorkflow
Phase 9：清理重复逻辑、补测试、补 trace、同步 README / 文档索引
```

## TODO 总表

### Phase 0：现状基线与回归测试

#### TODO 0.1：建立主链路回归样本

- 所属 Phase：0
- 目标：先知道当前主链路真实行为是什么
- 涉及文件：`local_life_agent/tests/`
- 依赖 TODO：无
- 改动说明：补当前主链路回归样本、关键 query 样本和失败样本
- 不做什么：不改业务逻辑，不改外层图，不改核心决策
- 验收方式：能稳定复现当前主链路结果
- 完成定义：回归样本可运行、可断言、可复现
- 风险：没有基线就直接改核心逻辑
- 测试要求：至少覆盖普通问候、能力说明、推荐、对比、指代、工具失败、证据不足
- 日志要求：样本运行时能看到基础 trace / 日志输出
- 文档回写要求：更新本文件和 `07_testing_and_acceptance.md`

#### TODO 0.2：建立 trace / 日志基线

- 所属 Phase：0
- 目标：能追踪当前节点输入输出和失败原因
- 涉及文件：`local_life_agent/engine/_compat.py`、`local_life_agent/observability/`
- 依赖 TODO：`TODO 0.1`
- 改动说明：补统一 trace 字段、关键节点摘要和失败原因记录
- 不做什么：不改路由逻辑，不改工具语义
- 验收方式：每个关键节点都能追踪到输入、输出、状态变化和 next_action
- 完成定义：trace / 日志能定位失败节点
- 风险：后续定位问题困难
- 测试要求：失败场景要能看到 `error_code`、`error_message`、`next_action`
- 日志要求：写入 `var\\python_service.log`
- 文档回写要求：更新 `05_state_and_schema_design.md`、`07_testing_and_acceptance.md`

#### TODO 0.3：建立 prompt / policy / logging 规范

- 所属 Phase：0
- 目标：统一 prompt structured output、policy table 和日志格式
- 涉及文件：`todo/12_prompt_policy_and_logging_guidelines.md`、`local_life_agent/observability/`、`local_life_agent/answer/`
- 依赖 TODO：`TODO 0.2`
- 改动说明：补日志字段、路由 policy 表、response_style 约束、禁止大量 if/else 堆叠
- 不做什么：不引入新 workflow，不改外层图
- 验收方式：文档中有明确日志字段、policy table 示例和模块职责边界
- 完成定义：规范文档可作为后续实现约束
- 风险：没有规范就容易把大分支堆回去
- 测试要求：日志和 prompt 输出要能对照 schema
- 日志要求：统一结构化输出到 `var\\python_service.log`
- 文档回写要求：更新相关设计文档和本文件

#### TODO 0.4：建立 ToolCall-only 禁止范围测试

- 所属 Phase：0
- 目标：先把当前阶段明确不做的能力锁死
- 涉及文件：`local_life_agent/tests/`
- 依赖 TODO：`TODO 0.1`、`TODO 0.2`
- 改动说明：补 forbidden / future / unknown tool 的不可调用测试
- 不做什么：不实现 RAG、交易、支付、退款、预约、订单 mutation
- 验收方式：forbidden tool 测试能拒绝执行
- 完成定义：禁止范围有显式测试断言
- 风险：范围漂移
- 测试要求：RAG / policy retrieval / mutation tool 不能进入计划或执行
- 日志要求：拒绝原因要有 `error_code`
- 文档回写要求：更新 `06_toolcall_only_scope.md`、`08_risks_and_non_goals.md`

#### TODO 0.5：建立可观测快照

- 所属 Phase：0
- 目标：补当前行为快照，确保后续改动可比较
- 涉及文件：`local_life_agent/tests/`
- 依赖 TODO：`TODO 0.1`、`TODO 0.2`
- 改动说明：保存主链路关键输入输出摘要
- 不做什么：不把快照当作业务逻辑
- 验收方式：快照能反映当前版本行为
- 完成定义：后续 Phase 1 改动可以对比前后差异
- 风险：没有快照就难以识别回归
- 测试要求：至少覆盖成功和失败各一类快照
- 日志要求：快照与日志字段可对应
- 文档回写要求：更新本文件和 `07_testing_and_acceptance.md`

### Phase 1：当前单主链路能力边界收口

#### TODO 1.1：收口 `search_shops`，只做候选召回

- 所属 Phase：1
- 目标：`search_shops` 只做召回，不做最终推荐
- 涉及文件：`local_life_agent/tools/db_tools.py`
- 依赖 TODO：`TODO 0.1`、`TODO 0.2`
- 改动说明：移除最终排序职责和业务级截断职责，保留召回事实字段
- 不做什么：不输出 `final_winner` / `best_shop`，不生成推荐话术
- 验收方式：召回结果不再决定最终推荐
- 完成定义：`search_shops` 输出只能被当作候选输入
- 风险：召回和决策继续混杂
- 测试要求：`search_shops` 返回顺序不能直接决定推荐
- 日志要求：记录 `query_terms`、`query_operator`、`result_status`
- 文档回写要求：更新 `06_toolcall_only_scope.md`、`07_testing_and_acceptance.md`

#### TODO 1.2：收口 `build_evidence`，只做事实补全和证据绑定

- 所属 Phase：1
- 目标：证据层只补事实，不选 winner
- 涉及文件：`local_life_agent/planning/evidence/evidence_builder.py`
- 依赖 TODO：`TODO 1.1`
- 改动说明：把推荐排序从证据层移出去，保留 evidence 绑定和缺失标记
- 不做什么：不做最终排序，不做推荐文案
- 验收方式：`EvidencePack` 不承担最终推荐职责
- 完成定义：`EvidencePack` 只承载事实和缺失信息
- 风险：verifier 无法稳定判断事实来源
- 测试要求：`EvidencePack` 缺关键字段时 `evidence_review` 不通过
- 日志要求：记录 `missing_fields`、`unknowns`、`failed_tools`
- 文档回写要求：更新 `05_state_and_schema_design.md`、`07_testing_and_acceptance.md`

#### TODO 1.3：收口 `candidate_decision`，不依赖 search rank

- 所属 Phase：1
- 目标：决策只基于证据和用户约束
- 涉及文件：`local_life_agent/planning/decision/candidate_decision.py`
- 依赖 TODO：`TODO 1.2`
- 改动说明：取消对上游 rank 的隐式依赖
- 不做什么：不直接依赖召回顺序，不读 DB，不调工具
- 验收方式：排序完全由证据和偏好决定
- 完成定义：推荐不再被 search rank 污染
- 风险：推荐不稳定
- 测试要求：`DecisionCore` 有不依赖 search rank 的测试
- 日志要求：记录决策理由和被拒候选原因
- 文档回写要求：更新 `02_core_module_abstraction.md`、`07_testing_and_acceptance.md`

#### TODO 1.4：收口 `reference_resolver`，多轮指代统一

- 所属 Phase：1
- 目标：推荐 / 对比 / 查店共用统一指代解析口径
- 涉及文件：`local_life_agent/target/context_recovery.py`、`local_life_agent/engine/subgraphs/merge_clarification.py`、`local_life_agent/engine/subgraphs/planning_subgraph.py`
- 依赖 TODO：`TODO 0.1`
- 改动说明：统一指代解析输出，收紧 `trace.py` 只做观测和派生
- 不做什么：不默认选择第一家，不把 trace 当真实解析实现
- 验收方式：同一指代在不同路径中得到一致解析
- 完成定义：无历史候选时不能解析第二家
- 风险：多轮体验不一致
- 测试要求：`last_answer_order` / `current_shop` 能支撑指代解析
- 日志要求：记录解析来源和置信度
- 文档回写要求：更新 `02_core_module_abstraction.md`、`05_state_and_schema_design.md`

#### TODO 1.5：去掉主链路默认 `MOCK_LOCATION`

- 所属 Phase：1
- 目标：去掉静态默认位置污染
- 涉及文件：`local_life_agent/config.py`、`local_life_agent/input/receiver.py`
- 依赖 TODO：`TODO 0.2`
- 改动说明：主链路不再自动注入 mock 用户位置
- 不做什么：不把 `MOCK_LOCATION` 伪装成真实用户位置
- 验收方式：复杂 query 不依赖静态位置仍能进入正确流程
- 完成定义：位置缺失时显式降级或澄清
- 风险：测试 / 主链路边界混淆
- 测试要求：`MOCK_LOCATION` 不能作为真实 provided location
- 日志要求：记录 `location_status`、`location_source`
- 文档回写要求：更新 `05_state_and_schema_design.md`、`06_toolcall_only_scope.md`

#### TODO 1.6：补齐 `SessionState` 多轮字段

- 所属 Phase：1
- 目标：补多轮记忆字段并支持跨轮读取
- 涉及文件：`local_life_agent/domain/state.py`
- 依赖 TODO：`TODO 1.4`
- 改动说明：增加 `last_evidence_pack`、`last_answer_order`、`last_selected_shop_ids` 等字段
- 不做什么：不把路由字段和业务字段混用
- 验收方式：多轮续问能读写这些字段
- 完成定义：状态字段可序列化、可回放
- 风险：状态丢失
- 测试要求：`last_answer_order` 不等于最终推荐排名
- 日志要求：状态变化可记录到 trace
- 文档回写要求：更新 `05_state_and_schema_design.md`

#### TODO 1.7：强化 Review / Verifier

- 所属 Phase：1
- 目标：让 review 真正触发扩召回、补证据、澄清或降级，verifier 能拦截未授权事实
- 涉及文件：
  - `local_life_agent/planning/evidence/evidence_review.py`
  - `local_life_agent/planning/decision/decision_review.py`
  - `local_life_agent/answer/verifier.py`
  - `local_life_agent/answer/llm_verbalizer.py`
- 依赖 TODO：`TODO 1.2`、`TODO 1.3`
- 改动说明：明确 review / verifier 的 next_action 与失败分流
- 不做什么：不把 review 做成形式化通过
- 验收方式：问题场景能正确进入澄清、补证据、降级或 rewrite
- 完成定义：回答不再自由拼接未验证事实
- 风险：事实漂移
- 测试要求：`AnswerVerifier` 能拦截未授权事实
- 日志要求：记录 review_reason、verifier_result、next_action
- 文档回写要求：更新 `07_testing_and_acceptance.md`

#### TODO 1.8：补结构化日志到 `var\\python_service.log`

- 所属 Phase：1
- 目标：把当前主链路、ToolCall、Review、Response、Verifier 的日志统一起来
- 涉及文件：`local_life_agent/observability/`、`local_life_agent/engine/`
- 依赖 TODO：`TODO 0.2`、`TODO 1.7`
- 改动说明：统一日志字段和输出格式
- 不做什么：不记录敏感隐私明文
- 验收方式：日志可定位节点、状态、错误和 next_action
- 完成定义：所有关键节点都能在日志中追踪
- 风险：后续排查困难
- 测试要求：失败场景必须包含 `error_code` / `error_message` / `next_action`
- 日志要求：写入 `var\\python_service.log`
- 文档回写要求：更新 `05_state_and_schema_design.md`、`07_testing_and_acceptance.md`

### Phase 2：Core 薄封装与可单测边界

#### TODO 2.1：定义七个 Core 的输入输出 schema

- 所属 Phase：2
- 目标：冻结 Core 的输入输出边界
- 涉及文件：`local_life_agent/domain/schemas.py`、`local_life_agent/domain/state.py`
- 依赖 TODO：`TODO 1.2`、`TODO 1.6`
- 改动说明：定义 `GoalPlan`、`CandidateSet`、`ToolResultSet`、`EvidencePack`、`DecisionPlan`、`AnswerPlan`、`StatePatch`
- 不做什么：不改外层图，不新增 workflow_runner
- 验收方式：schema 可校验、可序列化
- 完成定义：Core 边界有明确结构定义
- 风险：后续抽象不稳定
- 测试要求：schema 校验测试可通过
- 日志要求：schema 变化可记录 trace
- 文档回写要求：更新 `05_state_and_schema_design.md`

#### TODO 2.2：薄封装 PlanningCore

- 所属 Phase：2
- 目标：把计划能力抽成可单测边界
- 涉及文件：`local_life_agent/planning/goal/goal_planner.py`
- 依赖 TODO：`TODO 2.1`
- 改动说明：薄封装目标理解、证据需求和缺字段判断
- 不做什么：不调工具，不读 DB，不生成最终回答
- 验收方式：plan 输出可单测
- 完成定义：`GoalPlan` / `EvidencePlan` 可独立验证
- 风险：Core 依赖过多
- 测试要求：happy path 和 missing field case 都可测
- 日志要求：记录输入摘要、输出摘要、confidence
- 文档回写要求：更新 `02_core_module_abstraction.md`

#### TODO 2.3：薄封装 CandidateCore

- 所属 Phase：2
- 目标：把候选解析和候选状态收口为可单测边界
- 涉及文件：`local_life_agent/target/candidate_resolver.py`
- 依赖 TODO：`TODO 1.4`、`TODO 2.1`
- 改动说明：统一 `ReferenceResolutionResult` 和 `CandidateSet`
- 不做什么：不最终排序，不默认第一家
- 验收方式：候选解析和指代解析可回放
- 完成定义：无历史候选时不能解析第二家
- 风险：候选解析和决策仍混杂
- 测试要求：有“不能解析第二家”的测试
- 日志要求：记录解析来源和候选来源
- 文档回写要求：更新 `02_core_module_abstraction.md`、`05_state_and_schema_design.md`

#### TODO 2.4：薄封装 ExecutionCore

- 所属 Phase：2
- 目标：把工具执行能力抽成可单测边界
- 涉及文件：`local_life_agent/tools/gateway.py`、`local_life_agent/tools/executor.py`
- 依赖 TODO：`TODO 1.1`、`TODO 1.8`
- 改动说明：统一 ToolCall 执行、错误返回和结果规范化
- 不做什么：不做推荐决策，不生成回答
- 验收方式：工具失败、超时、空结果都有显式状态
- 完成定义：`ToolResultSet` 可独立验证
- 风险：工具语义被改坏
- 测试要求：未知工具、forbidden tool、失败工具都可拒绝
- 日志要求：记录 `tool_name`、`tool_status`、`latency`、`result_count`、`error_code`
- 文档回写要求：更新 `06_toolcall_only_scope.md`

#### TODO 2.5：薄封装 EvidenceCore

- 所属 Phase：2
- 目标：把事实补全、缺失标记和证据绑定抽成边界
- 涉及文件：`local_life_agent/planning/evidence/evidence_builder.py`
- 依赖 TODO：`TODO 2.4`
- 改动说明：输出 `EvidencePack`，不选 winner
- 不做什么：不最终排序，不生成回答
- 验收方式：`EvidencePack` 与工具结果一一可追踪
- 完成定义：证据能明确表示缺失、未知和失败
- 风险：Evidence 和 Decision 边界混乱
- 测试要求：缺关键字段时 evidence review 不通过
- 日志要求：记录 `missing_fields`、`unknowns`、`failed_tools`
- 文档回写要求：更新 `02_core_module_abstraction.md`、`05_state_and_schema_design.md`

#### TODO 2.6：薄封装 DecisionCore

- 所属 Phase：2
- 目标：把综合决策能力抽成边界
- 涉及文件：`local_life_agent/planning/decision/candidate_decision.py`、`local_life_agent/planning/decision/decision_planner.py`
- 依赖 TODO：`TODO 2.5`
- 改动说明：决策只看 evidence、用户约束、用户偏好和 policy
- 不做什么：不调用工具，不读 DB，不盲目依赖 search rank
- 验收方式：决策不依赖召回顺序
- 完成定义：winner 选择有可解释理由
- 风险：推荐不稳定
- 测试要求：有不依赖 search rank 的测试
- 日志要求：记录决策理由和拒绝理由
- 文档回写要求：更新 `02_core_module_abstraction.md`

#### TODO 2.7：薄封装 ResponseCore

- 所属 Phase：2
- 目标：把回答表达和 verifier 收口为边界
- 涉及文件：`local_life_agent/answer/`、`local_life_agent/answer/verifier.py`
- 依赖 TODO：`TODO 2.6`
- 改动说明：ResponseCore 只表达 DecisionPlan，不重新挑店
- 不做什么：不绕过 EvidencePack 编事实，不承诺交易 / 退款 / 支付 / 预约
- 验收方式：回答经过 verifier 后才可出图
- 完成定义：表达策略与事实绑定分离
- 风险：回答漂移
- 测试要求：不能编造 EvidencePack 外事实
- 日志要求：记录 `response_mode`、`response_style`、`verifier_result`
- 文档回写要求：更新 `02_core_module_abstraction.md`、`05_state_and_schema_design.md`

#### TODO 2.8：薄封装 StateCore

- 所属 Phase：2
- 目标：把状态补丁和会话写回收口
- 涉及文件：`local_life_agent/domain/state.py`、`local_life_agent/engine/`
- 依赖 TODO：`TODO 2.1`、`TODO 1.6`
- 改动说明：StateCore 只负责状态补丁、trace 和会话写回
- 不做什么：不做业务决策，不生成回答
- 验收方式：状态补丁可回放
- 完成定义：事件日志和 trace 可对齐
- 风险：状态和推断混写
- 测试要求：`StatePatch` 可序列化且可回放
- 日志要求：记录 `state_keys_changed`
- 文档回写要求：更新 `05_state_and_schema_design.md`

#### TODO 2.9：补 Core 单测

- 所属 Phase：2
- 目标：让 Core 可以脱离 LangGraph 单测
- 涉及文件：`local_life_agent/tests/`
- 依赖 TODO：`TODO 2.2` 到 `TODO 2.8`
- 改动说明：补每个 Core 的 happy path 和 failure / missing field case
- 不做什么：不替代主链路回归
- 验收方式：每个 Core 都有独立单测
- 完成定义：Core 边界可被稳定证明
- 风险：Core 抽象无法落地
- 测试要求：DecisionCore 不依赖 search rank，ResponseCore 不能编造事实
- 日志要求：单测失败时能看到关键断点
- 文档回写要求：更新 `07_testing_and_acceptance.md`

### Phase 3：固化当前主链路为 DiscoveryDecisionWorkflow 雏形

#### TODO 3.1：稳定当前推荐 / 搜索 / 对比 / 筛选主链路

- 所属 Phase：3
- 目标：把当前单主链路稳定成 DiscoveryDecision 雏形
- 涉及文件：`local_life_agent/engine/subgraphs/planning_subgraph.py`、`local_life_agent/engine/subgraphs/execution_review_subgraph.py`、`local_life_agent/engine/subgraphs/response_subgraph.py`
- 依赖 TODO：`TODO 1.1`、`TODO 1.2`、`TODO 1.3`、`TODO 2.5`、`TODO 2.6`
- 改动说明：明确 controlled Plan -> Execute -> Review -> Response
- 不做什么：不引入 orchestration_router，不拆 workflow
- 验收方式：推荐、搜索、对比、筛选稳定
- 完成定义：当前主链路行为可持续回归
- 风险：主链路不稳会影响后续分流
- 测试要求：DiscoveryDecision 雏形回归测试通过
- 日志要求：DecisionPlan / AnswerPlan / EvidencePack 可追踪
- 文档回写要求：更新 `03_workflow_design.md`、`07_testing_and_acceptance.md`

#### TODO 3.2：补 DiscoveryDecision 雏形回归测试

- 所属 Phase：3
- 目标：验证主链路雏形稳定
- 涉及文件：`local_life_agent/tests/`
- 依赖 TODO：`TODO 3.1`
- 改动说明：补推荐、搜索、对比、筛选的稳定回归
- 不做什么：不要求正式 workflow 分流
- 验收方式：主链路能稳定复现
- 完成定义：雏形状态可被测试证明
- 风险：把雏形误写成正式 workflow
- 测试要求：结果可追踪到 `DecisionPlan` / `AnswerPlan` / `EvidencePack`
- 日志要求：可定位到失败节点
- 文档回写要求：更新 `07_testing_and_acceptance.md`

### Phase 4：新增 OrchestrationRouter（二级路由）

#### 本轮已落地的 shadow mode 范围

- 已定义 `OrchestrationDecision`，并将 `orchestration_decision` 作为独立影子字段接入 `GraphState`
- 已在 `planning_subgraph` 的现有主链路后写入 shadow decision，并同步结构化日志
- 已补充 shadow-mode 单测，验证 `SessionState` 不接收该字段，`state_update_plan` 也不会持久化该字段
- 仍未实现 `workflow_runner`、workflow registry、真实 workflow 调度
- 仍未根据 `workflow_name` 改变当前 graph conditional edge
- 仍未让 router 直接调用工具或生成最终回答
- 仍未把 `orchestration_decision` 写入 `SessionState`

#### TODO 4.1：定义 OrchestrationDecision schema

- 所属 Phase：4
- 目标：定义二级路由输出结构
- 涉及文件：`local_life_agent/domain/schemas.py`、`local_life_agent/domain/state.py`
- 依赖 TODO：`TODO 3.1`
- 改动说明：定义 `orchestration_pattern`、`workflow_name`、`workflow_reason`、`next_action`
- 不做什么：不做 workflow 调度，不改主链路
- 验收方式：schema 可校验、可序列化
- 完成定义：二级路由输出有明确边界
- 风险：schema 不稳定时误判
- 测试要求：字段缺失应显式失败
- 日志要求：记录路由理由和置信度
- 文档回写要求：更新 `03_workflow_design.md`、`05_state_and_schema_design.md`

#### TODO 4.2：实现 `orchestration_router`

- 所属 Phase：4
- 目标：根据 semantic / context 选择 workflow
- 涉及文件：`local_life_agent/engine/`
- 依赖 TODO：`TODO 4.1`
- 改动说明：只输出 workflow 选择结果
- 不做什么：不调用工具，不生成最终回答，不做事实判断
- 验收方式：`orchestration_router` 低 confidence 可进入澄清路径
- 完成定义：二级路由只负责分流
- 风险：路由误判
- 测试要求：推荐问题、单店事实、多子目标规划可分流
- 日志要求：写入 `orchestration_pattern`、`workflow_name`、`workflow_reason`
- 文档回写要求：更新 `03_workflow_design.md`、`07_testing_and_acceptance.md`

#### TODO 4.3：建立 policy table / prompt / validator

- 所属 Phase：4
- 目标：让二级路由受控且可验证
- 涉及文件：`todo/10_orchestration_router_design.md`、`local_life_agent/semantic/`、`local_life_agent/planning/`
- 依赖 TODO：`TODO 4.1`
- 改动说明：补 policy table、prompt 输出和 validator 约束
- 不做什么：不把复杂判断堆成 if/else
- 验收方式：policy table 缺项不会静默进入错误 workflow
- 完成定义：router 行为受 schema / policy / validator 约束
- 风险：路由策略漂移
- 测试要求：新增 task_type 先补 policy / schema / 测试
- 日志要求：记录 policy 命中信息
- 文档回写要求：更新 `07_testing_and_acceptance.md`

#### TODO 4.4：补二级路由测试

- 所属 Phase：4
- 目标：验证二级路由正确性
- 涉及文件：`local_life_agent/tests/`
- 依赖 TODO：`TODO 4.2`、`TODO 4.3`
- 改动说明：补 `orchestration_router` 分流测试
- 不做什么：不要求 workflow_runner 已存在
- 验收方式：Phase 4 前后路由行为可测
- 完成定义：二级路由能独立验证
- 风险：路由实现和测试脱节
- 测试要求：低 confidence 进入澄清或 fallback
- 日志要求：记录 `next_action`
- 文档回写要求：更新 `07_testing_and_acceptance.md`

#### TODO 4.5：补 `orchestration_router` 日志

- 所属 Phase：4
- 目标：记录二级路由决策过程
- 涉及文件：`local_life_agent/observability/`、`local_life_agent/engine/`
- 依赖 TODO：`TODO 4.2`
- 改动说明：记录输入摘要、输出摘要、置信度和 next_action
- 不做什么：不记录隐私明文
- 验收方式：日志能定位路由决策
- 完成定义：路由问题可审计
- 风险：无法定位误分流
- 测试要求：失败场景有 `error_code`
- 日志要求：写入 `var\\python_service.log`
- 文档回写要求：更新 `05_state_and_schema_design.md`、`07_testing_and_acceptance.md`

### Phase 5：新增 workflow_runner 与 workflow registry

#### TODO 5.1：定义 WorkflowRegistry

- 所属 Phase：5
- 目标：把 workflow 入口做成白名单注册表
- 涉及文件：`local_life_agent/engine/`
- 依赖 TODO：`TODO 4.2`
- 改动说明：定义 workflow registry / mapping / declarative config
- 不做什么：不写大段 if/elif
- 验收方式：registry 可注册、可查找、可校验
- 完成定义：workflow 名称和实现有稳定映射
- 风险：registry 被分支逻辑取代
- 测试要求：非法 workflow 可拒绝
- 日志要求：记录 workflow 命中
- 文档回写要求：更新 `03_workflow_design.md`

#### TODO 5.2：实现 `workflow_runner`

- 所属 Phase：5
- 目标：根据 `orchestration_router` 输出调度 workflow
- 涉及文件：`local_life_agent/engine/`
- 依赖 TODO：`TODO 5.1`
- 改动说明：实现 workflow 调度入口
- 不做什么：不做业务决策，不生成最终回答
- 验收方式：workflow runner 能按 registry 调度
- 完成定义：多 workflow 分流真正生效
- 风险：workflow_runner 变成业务判断中心
- 测试要求：非法 workflow 和未知 workflow 可拒绝
- 日志要求：记录 `workflow_name`、`next_action`
- 文档回写要求：更新 `03_workflow_design.md`、`07_testing_and_acceptance.md`

#### TODO 5.3：把 DiscoveryDecision 雏形注册为 `discovery_decision`

- 所属 Phase：5
- 目标：把 Phase 3 雏形接入 workflow registry
- 涉及文件：`local_life_agent/engine/`
- 依赖 TODO：`TODO 3.1`、`TODO 5.1`、`TODO 5.2`
- 改动说明：注册 discovery_decision workflow
- 不做什么：不把雏形误写成 Phase 1 当前事实
- 验收方式：雏形可被 workflow_runner 调度
- 完成定义：DiscoveryDecision 进入正式 workflow registry
- 风险：把雏形和正式 workflow 混淆
- 测试要求：路由和 runner 一起通过
- 日志要求：记录 workflow 名称和原因
- 文档回写要求：更新 `03_workflow_design.md`

#### TODO 5.4：实现非法 workflow fallback

- 所属 Phase：5
- 目标：对未知或非法 workflow 做安全降级
- 涉及文件：`local_life_agent/engine/`
- 依赖 TODO：`TODO 5.2`
- 改动说明：补非法 workflow 的 fallback 分支
- 不做什么：不静默吞掉错误
- 验收方式：非法 workflow 可拒绝并返回可信失败
- 完成定义：workflow 入口有安全边界
- 风险：非法 workflow 被硬跑
- 测试要求：未知 workflow 被拒绝
- 日志要求：记录拒绝原因
- 文档回写要求：更新 `07_testing_and_acceptance.md`

#### TODO 5.5：补 workflow_runner 测试和日志

- 所属 Phase：5
- 目标：验证 runner 的分流与审计
- 涉及文件：`local_life_agent/tests/`、`local_life_agent/observability/`
- 依赖 TODO：`TODO 5.2`、`TODO 5.4`
- 改动说明：补 runner 级测试和结构化日志
- 不做什么：不替代 workflow 业务测试
- 验收方式：runner 行为可追踪、可拒绝、可回放
- 完成定义：workflow 调度可审计
- 风险：分流错误无法定位
- 测试要求：runner 测试通过
- 日志要求：写入 `var\\python_service.log`
- 文档回写要求：更新 `07_testing_and_acceptance.md`

### Phase 5 当前状态

- `WorkflowRegistry` 已落地
- `workflow_runner` 已落地并接入当前主链路
- `discovery_decision` 已注册为当前主链路薄适配
- `deterministic_tool` / `clarification_fallback` / `direct_response` / `exploration_planning` 仍为显式占位或 current-chain adapter
- Phase 6 仍保持为独立 `DeterministicToolWorkflow` 拆分阶段，不提前实现

### Phase 6：新增 DeterministicToolWorkflow

#### TODO 6.1：独立单店确定性查询

- 所属 Phase：6
- 目标：单店状态、距离、券、营业时间、评价摘要走独立链路
- 涉及文件：`local_life_agent/tools/`、`local_life_agent/engine/`
- 依赖 TODO：`TODO 5.2`
- 改动说明：从 Discovery 链中拆出确定性工具链
- 不做什么：不改 Phase 1 事实边界，不提前做多 workflow
- 验收方式：单店查询不再走重型发现链
- 完成定义：deterministic_tool workflow 可独立运行
- 风险：过早拆分影响回归
- 测试要求：单店查询专用回归通过
- 日志要求：记录工具事实链路
- 文档回写要求：更新 `03_workflow_design.md`、`07_testing_and_acceptance.md`

### Phase 7：新增 DirectResponseWorkflow 与 ClarificationFallbackWorkflow

#### TODO 7.1：独立直接回答链路

- 所属 Phase：7
- 目标：让简单问答走轻链路
- 涉及文件：`local_life_agent/answer/`、`local_life_agent/engine/`
- 依赖 TODO：`TODO 5.2`
- 改动说明：直接回答不依赖复杂工具链
- 不做什么：不把简单问答误拉进 Discovery
- 验收方式：chat / capability 问题可直接回答
- 完成定义：direct_response workflow 可独立运行
- 风险：路由误判
- 测试要求：简单问答回归通过
- 日志要求：记录 response_mode 和 fallback 情况
- 文档回写要求：更新 `03_workflow_design.md`、`07_testing_and_acceptance.md`

#### TODO 7.2：独立澄清 / 降级链路

- 所属 Phase：7
- 目标：把歧义、无结果、工具失败统一进 fallback
- 涉及文件：`local_life_agent/engine/`
- 依赖 TODO：`TODO 5.2`
- 改动说明：统一输出可信澄清或可信失败
- 不做什么：不硬跑下游链路
- 验收方式：失败场景不胡编
- 完成定义：clarification_fallback workflow 可独立运行
- 风险：推荐类问题被错误降级
- 测试要求：澄清、无结果、工具失败场景可测
- 日志要求：记录 `pending_clarification`
- 文档回写要求：更新 `07_testing_and_acceptance.md`

### Phase 8：新增 ExplorationPlanningWorkflow

#### TODO 8.1：引入探索式规划链路

- 所属 Phase：8
- 目标：支持更复杂的探索式本地生活规划
- 涉及文件：`local_life_agent/planning/`、`local_life_agent/engine/`
- 依赖 TODO：`TODO 5.2`
- 改动说明：支持 trip / date / family / 组合场景规划
- 不做什么：不做交易、不预约、不下单
- 验收方式：探索类问题能单独成链路
- 完成定义：exploration_planning workflow 可独立运行
- 风险：容易膨胀，必须后置
- 测试要求：最多 3 个 subgoal、最多 2 轮工具扩展
- 日志要求：记录规划理由和限制
- 文档回写要求：更新 `03_workflow_design.md`、`07_testing_and_acceptance.md`
- 完成状态：DONE（已按方案 A 落地最小独立 workflow，并完成 Phase 8 专项测试 / 回归）

### Phase 9：清理重复逻辑、补测试、补 trace、同步 README / 文档索引

#### TODO 9.1：清理重复逻辑

- 所属 Phase：9
- 目标：去掉重复路由、重复决策、重复证据处理
- 涉及文件：全仓相关实现
- 依赖 TODO：前面所有相关收口项
- 改动说明：清掉多处相似判断和兜底
- 不做什么：不引入新能力
- 验收方式：没有重复职责
- 完成定义：实现与文档职责一致
- 风险：收尾阶段返工量大
- 测试要求：回归无重复分支副作用
- 日志要求：重复逻辑清理后仍可定位错误节点
- 文档回写要求：同步 README / 文档索引

#### TODO 9.2：补全测试和验收

- 所属 Phase：9
- 目标：把 workflow、Core、review、verifier 全部回归覆盖
- 涉及文件：`local_life_agent/tests/`
- 依赖 TODO：`TODO 2.9`、`TODO 5.5`、`TODO 7.1`、`TODO 7.2`、`TODO 8.1`
- 改动说明：补 workflow 级用例、真实后端验收
- 不做什么：不再用 mock 代替最终验收
- 验收方式：端到端回归稳定
- 完成定义：测试矩阵和实现一致
- 风险：没有测试会导致不可回归
- 测试要求：real LLM / real DB / real Java API / SSE 验收通过
- 日志要求：失败场景可定位
- 文档回写要求：更新 `07_testing_and_acceptance.md`

#### TODO 9.3：同步文档和索引

- 所属 Phase：9
- 目标：让文档、测试、实现一致
- 涉及文件：`todo/`、`doc/`、README
- 依赖 TODO：`TODO 9.2`
- 改动说明：更新索引和引用关系
- 不做什么：不改业务代码
- 验收方式：文档不再与实现冲突
- 完成定义：文档链路闭环
- 风险：文档过时
- 测试要求：引用关系和事实一致
- 日志要求：无新增要求
- 文档回写要求：同步所有受影响文档

## 可执行建议

1. 先做 Phase 0，再做 Phase 1。
2. Phase 4 只做 `OrchestrationRouter`，Phase 5 才做 `workflow_runner`。
3. Phase 2 先薄封装 Core，不要一次性大搬迁。
4. Phase 6-8 都必须后置，不能混进当前近期改造。

## TODO 格式约束

每个 TODO 必须包含以下信息：

| 字段 | 说明 |
| --- | --- |
| TODO 编号 | 唯一编号，如 `0.1`、`1.3` |
| 标题 | 这一项要解决什么问题 |
| 所属 Phase | 属于哪个阶段 |
| 目标 | 具体要达到什么效果 |
| 涉及文件 | 需要改哪些文档或代码 |
| 依赖 TODO | 依赖哪些前置项 |
| 改动说明 | 具体要改什么 |
| 不做什么 | 明确禁止事项 |
| 验收方式 | 怎么确认已完成 |
| 完成定义 | 什么叫真正完成 |
| 风险 | 不做会有什么问题 |
| 测试要求 | 对应测试和回归要求 |
| 日志要求 | 需要记录什么 |
| 文档回写要求 | 完成后要同步哪些文档 |

## TODO 执行顺序

1. 先补测试基线。
2. 再补 trace / 日志 / schema 规范。
3. 再做 Phase 1 边界收口。
4. 再抽 Core 与 Review / Verifier 强化。
5. 再做 Phase 3 雏形固化。
6. 最后才做路由分流和新 workflow。

## 验收清单

- 每个 TODO 都能映射到一条明确的测试或文档验收。
- 每个 TODO 都有明确的完成定义，不能只写“优化”“完善”。
- TODO 之间的依赖关系必须能从 Phase 顺序看出来。
- Phase 4 和 Phase 5 必须严格分开。
- Phase 6-9 必须明确后置，不得混入当前近期改造。
