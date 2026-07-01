# 04 迁移阶段

## 目标

按阶段推进，从当前单主链路收口，逐步走向 Core 抽象、DiscoveryDecision 固化、二级路由和多 workflow。

本文件是后续所有实现任务的阶段总纲。
Phase 顺序唯一、稳定、可执行。
正文 Phase 编号和补充表格 Phase 编号必须完全一致。

## Phase 0：现状基线与回归测试

### 目标

- 建立测试和 trace 基线
- 先能观察当前行为，再改核心逻辑

### 涉及文件

- `local_life_agent/tests/`
- `local_life_agent/engine/_compat.py`
- `var\python_service.log` 相关日志路径约定

### 改动内容

- 补测试基线
- 补 trace 基线
- 固化当前主链路回归样本
- 固化结构化日志字段
- 固化当前行为快照

### 不做什么

- 不改 `search_shops`
- 不改 `build_evidence`
- 不改 `candidate_decision`
- 不改外层图

### 验收标准

- 能复现当前行为
- 能看到关键节点输入输出摘要
- 日志能写入 `var\python_service.log`
- 能定位一次完整请求经过哪些节点

### 风险

- 没有基线就改核心逻辑，后续难以定位回归

### 退出条件

- 至少有当前主链路回归样本
- 至少能定位一次完整请求经过哪些节点

## Phase 1：当前单主链路能力边界收口

### 目标

- 收口现有混杂职责，但不改外层图

### 涉及文件

- `local_life_agent/tools/db_tools.py`
- `local_life_agent/planning/evidence/evidence_builder.py`
- `local_life_agent/planning/decision/candidate_decision.py`
- `local_life_agent/input/receiver.py`
- `local_life_agent/config.py`
- `local_life_agent/domain/state.py`

### 改动内容

- `search_shops` 只做召回
- `build_evidence` 只做事实补全和证据绑定
- `candidate_decision` 基于 `EvidencePack` 综合决策
- `reference_resolver` 作为指代解析主要收口点
- 去掉主链路默认 `MOCK_LOCATION`
- 补齐 `SessionState`
- 强化 Review / Verifier
- 补结构化日志

### 不做什么

- 不引入 `orchestration_router`
- 不引入 `workflow_runner`
- 不新增多 workflow
- 不改外层图
- 不做 RAG
- 不做交易

### 验收标准

- 推荐不再依赖 `search_shops` 返回顺序
- `EvidenceCore` 不选择最终 winner
- `DecisionCore` / `candidate_decision` 不盲目依赖上游 rank
- 无历史候选时不能解析“第二家”
- 主链路不再把 `MOCK_LOCATION` 当真实位置默认注入
- Review / Verifier 能拦截证据不足和未授权事实

### 风险

- 如果边界没收口就继续加路由，会让复杂度失控

### 退出条件

- 当前单主链路职责边界清晰
- 核心回归样本通过
- 日志能支撑定位 search / evidence / decision / response 的问题

## Phase 2：Core 薄封装与可单测边界

### 目标

- 把 Phase 1 收口后的逻辑薄封装成 Core 边界

### 涉及文件

- `local_life_agent/planning/`
- `local_life_agent/answer/`
- `local_life_agent/domain/`

### 改动内容

- 抽 `PlanningCore`
- 抽 `CandidateCore`
- 抽 `ExecutionCore`
- 抽 `EvidenceCore`
- 抽 `DecisionCore`
- 抽 `ResponseCore`
- 抽 `StateCore`

### 不做什么

- 不改外层图
- 不引入 workflow_runner
- 不新增多 workflow

### 验收标准

- 每个 Core 有输入输出 schema
- 每个 Core 至少有 happy path 和 failure / missing field 测试
- `DecisionCore` 有不依赖 `search rank` 的测试
- `CandidateCore` 有无历史候选不能解析第二家的测试
- `ResponseCore` 有不能编造 `EvidencePack` 外事实的测试

### 风险

- 抽象过宽会导致重复封装

### 退出条件

- Core 可以在不启动 LangGraph 的情况下单测
- subgraph 到 Core 的调用边界清晰

## Phase 3：固化当前主链路为 DiscoveryDecisionWorkflow 雏形

### 目标

- 不新增 `workflow_runner`，只把当前主链路稳定收敛为 `DiscoveryDecisionWorkflow` 的雏形

### 涉及文件

- `local_life_agent/engine/subgraphs/planning_subgraph.py`
- `local_life_agent/engine/subgraphs/execution_review_subgraph.py`
- `local_life_agent/engine/subgraphs/response_subgraph.py`

### 改动内容

- 明确当前推荐 / 对比 / 搜索 / 筛选仍走主链路
- 固化 `Controlled Plan -> Tool Execute -> Evidence Review -> Decision Review -> Response`
- 让推荐决策由 `DecisionCore` 基于 `EvidencePack` 做
- 强化 prompt / policy / schema 驱动

### 不做什么

- 不引入 `orchestration_router`
- 不引入 `workflow_runner`
- 不拆 `DeterministicToolWorkflow`
- 不拆 `DirectResponseWorkflow`
- 不拆 `ClarificationFallbackWorkflow`
- 不拆 `ExplorationPlanningWorkflow`

### 验收标准

- 搜索、推荐、对比、条件筛选可稳定回归
- 推荐不会由 search rank 或 `ResponseCore` 临时决定
- `DecisionPlan` 和 `AnswerPlan` 可追踪

### 风险

- 主链路不稳定会导致后续路由失真

### 退出条件

- 当前主链路可以被清晰描述为 `DiscoveryDecisionWorkflow` 雏形
- 但代码仍不伪装成多 workflow 已落地

## Phase 4：新增 OrchestrationRouter（二级路由）

### 目标

- 在 `understanding_subgraph` 之后引入二级 workflow 路由

### 涉及文件

- `local_life_agent/engine/`
- `local_life_agent/domain/`

### 改动内容

- 引入 `orchestration_router`
- 输出 `orchestration_pattern / workflow_name / workflow_reason`
- 使用 policy table + prompt + validator

### 不做什么

- 不把一级路由和二级路由合并
- 不引入交易 / RAG
- 不让 router 写最终回答

### 验收标准

- 能正确分到 5 条 workflow
- 低置信度能进入澄清或保守路径

### 风险

- schema 不稳定时误判严重

### 退出条件

- 二级路由 schema、policy、validator、日志、测试稳定

## Phase 5：新增 workflow_runner 与 workflow registry

### 目标

- 根据 `orchestration_router` 输出调度具体 workflow

### 涉及文件

- `local_life_agent/engine/`
- `local_life_agent/domain/`

### 改动内容

- 引入 `workflow_runner`
- 引入 `workflow registry`
- 用 registry / mapping / declarative config 调度 workflow

### 不做什么

- 不把 `workflow_runner` 写成业务判断中心
- 不绕过 Core

### 验收标准

- `workflow_runner` 能基于 `workflow_name` 调度
- 非法 `workflow_name` 会进入 fallback
- 日志能记录 `workflow_name`、`next_action`、`latency_ms`

### 当前状态

- Phase 5 已落地 `workflow_runner` 与 workflow registry
- `discovery_decision` 已作为当前主链路薄适配注册
- `deterministic_tool` / `clarification_fallback` / `direct_response` / `exploration_planning` 仍是显式占位或 current-chain adapter，不代表独立 workflow 已拆完

### 风险

- 不稳定的 registry 会让分流逻辑难以回归

### 退出条件

- workflow 调度机制稳定
- 不会因为新增 workflow 改坏旧路由

## Phase 6：新增 DeterministicToolWorkflow

### 目标

- 把单店确定性查询从重型主链路拆出

### 涉及文件

- `local_life_agent/tools/`
- `local_life_agent/engine/`

### 改动内容

- 独立处理店铺状态、距离、券、营业时间、评价摘要

### 不做什么

- 不处理多候选推荐
- 不无历史候选强行解析“第二家”
- 不引入交易能力

### 验收标准

- 明确单店 target 时可以轻链路回答
- target 不明确时进入 `clarification_fallback`

### 风险

- 过早拆分可能造成主链路测试不足

### 退出条件

- 单店查询不再必须走完整发现决策主链路

## Phase 7：新增 DirectResponseWorkflow 与 ClarificationFallbackWorkflow

### 目标

- 拆出直接回答和澄清 / 降级链路

### 涉及文件

- `local_life_agent/answer/`
- `local_life_agent/engine/`

### 改动内容

- 直接回答场景走轻链路
- 歧义 / 无结果 / 失败走澄清或降级链路

### 不做什么

- 不查真实商家事实
- 不引入 RAG
- 不引入交易
- 不硬跑下游链路

### 验收标准

- 简单问答能轻量直答
- 指代失败 / 信息不足能澄清
- 能力外请求能可信降级

### 风险

- 推荐类问题被错误降级

### 退出条件

- direct response 和 fallback 不再混在重型推荐链路中

## Phase 8：新增 ExplorationPlanningWorkflow

### 目标

- 支持更复杂的探索式规划
- 状态：已完成最小独立 `ExplorationPlanningWorkflow`（方案 A），仅做 Phase 8 边界内的探索规划与回退，不引入 RAG / 交易 / mutation

### 涉及文件

- `local_life_agent/planning/`
- `local_life_agent/engine/`

### 改动内容

- 支持 trip / date / family / 组合规划类问题

### 不做什么

- 不引入开放式 multi-agent handoff

### 验收标准

- 探索式问题能单独成链路
- 不会执行交易动作
- 不会无限扩展

### 风险

- 容易膨胀，必须后置

### 退出条件

- 探索式规划稳定，且不影响普通推荐主链路
- 当前最小独立实现已落地，可进入 Phase 9 收尾与一致性整理

## Phase 9：清理重复逻辑、补测试、补 trace、同步 README / 文档索引

### 目标

- 文档、测试、实现三者对齐

### 涉及文件

- 全仓相关文档和测试

### 改动内容

- 清理重复路由
- 清理重复决策
- 补 trace 字段
- 同步 README
- 同步 todo 文档索引
- 更新 0000 总控进度

### 不做什么

- 不再新增新的核心范式
- 不再新增未经文档化的 workflow

### 验收标准

- 文档、测试、实现一致
- 全量回归稳定

### 风险

- 前面阶段没固化时，最后清理会变成大返工

### 退出条件

- 阶段文档、实现代码、测试报告、README 互相不冲突

## 可执行建议

1. Phase 0 必须先补测试和 trace 基线，然后再改 `search_shops` / `build_evidence`。
2. Phase 1 先做边界收口，保持外层图不动。
3. Phase 4 才考虑 `orchestration_router`。
4. Phase 5 才考虑 `workflow_runner`。

## 可执行版补充

### 阶段完成定义

| Phase | 完成条件 | 退出条件 | 典型验证 |
| --- | --- | --- | --- |
| Phase 0 | 有稳定测试基线和 trace 基线 | 能复现当前行为并观察节点变化 | 运行主链路回归样本 |
| Phase 1 | `search_shops` / `build_evidence` / `MOCK_LOCATION` / `SessionState` 收口完成 | 单主链路能力边界明确 | 复杂 query 不再依赖静态默认值 |
| Phase 2 | 7 个 Core 抽离完成 | 候选与指代可复用 | 多轮指代一致 |
| Phase 3 | Review / Verifier / Grounding 强化完成 | 证据不足时能正确转向 | 失败场景不胡编 |
| Phase 4 | 二级路由 schema / policy / validator 落地 | 路由可解释 | 搜索 / 推荐 / 对比可正确分流 |
| Phase 5 | `workflow_runner` 落地 | 有稳定 registry 与调度 | 5 条 workflow 可分流 |
| Phase 6 | `DeterministicToolWorkflow` 独立 | 单店查询可轻链路回答 | 明确 target 不再走重链路 |
| Phase 7 | `DirectResponseWorkflow` / `ClarificationFallbackWorkflow` 独立 | 直答和降级链路清晰 | 简单问答和 fallback 稳定 |
| Phase 8 | `ExplorationPlanningWorkflow` 独立 | 探索式规划稳定，最小独立实现已完成 | 组合规划可回归 |
| Phase 9 | 收尾清理、测试和文档同步 | 文档与实现一致 | 全量回归稳定 |

### 阶段依赖顺序

1. 先 Phase 0。
2. 再 Phase 1。
3. Phase 2-3 完成后再看是否具备引入二级路由的条件。
4. Phase 4 之后才允许 workflow 分流进入实现。
5. Phase 5 之后才允许把 workflow registry 写进实现。

### 阶段验收清单

- 每一阶段必须有对应测试或回归样例
- 每一阶段必须有对应文档状态更新
- 任何阶段如果出现“靠人工判断完成”的情况，都必须补成可验证标准后再收口
