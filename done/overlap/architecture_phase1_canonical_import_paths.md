# Architecture Overlap Phase 1 Canonical Import Paths

> 目标：把当前仓库里真正可走的权威导入面冻结下来，明确哪些旧入口只是 `DEPRECATED_COMPAT`，哪些还属于 `NEEDS_DECISION`。

## 1. 冻结原则

- `CANONICAL` 表示 Phase 1 后的新代码默认必须走的路径
- `DEPRECATED_COMPAT` 表示旧导入面仍保留，但只允许现有调用方继续使用
- `NEEDS_DECISION` 表示当前仍存在双入口或职责边界未最终定版
- `TEST_ONLY` 表示只允许测试或 fake backend 使用
- `LEGACY_REMOVE_IN_PHASE6` 表示已确认可删，但要等 Phase 6 的 import 扫描通过后再处理

## 2. Canonical Path Table

| 能力 | Canonical Path | Deprecated Path | 当前使用情况 | Phase 1 动作 | 备注 |
|---|---|---|---|---|---|
| semantic parsing | `local_life_agent.semantic.intent_parser.parse_semantic_frame` / `parse_top_intent` | `local_life_agent.semantic.top_intent_router` | `CANONICAL` | 冻结新 import，旧 wrapper 只读 | 语义解析的权威入口应回到 `intent_parser.py` |
| context recovery | `local_life_agent.target.context_recovery.recover_context` | `engine.graph_builder` 兼容导出 | `CANONICAL` | 只允许现有调用方继续使用旧面 | 上下文恢复属于 target 层职责 |
| orchestration routing | `local_life_agent.planning.orchestration_router.build_orchestration_decision` / `route_orchestration` | `local_life_agent.engine._routes`、`local_life_agent.engine.subgraphs.orchestration_router_shadow` | `CANONICAL` | 冻结新 import，继续把 `_routes` 当边转换层 | 路由判断不再向其他层扩散 |
| goal planning | `local_life_agent.planning.goal.goal_planner.plan_goal` / `plan_goal_with_llm` | `local_life_agent.planning.goal_planner`、`local_life_agent.core.planning_core` | `CANONICAL` | 旧路径标记为兼容壳，不再新增调用 | 目标规划应留在 `planning/goal/` 分层 |
| evidence building | `local_life_agent.planning.evidence.evidence_builder.build_evidence` | `local_life_agent.planning.evidence_planner`、`local_life_agent.core.evidence_core` | `CANONICAL` | 新代码改走 nested path | 证据构建和 review 要分层收口 |
| decision planning | `local_life_agent.planning.decision.decision_planner.plan_decision` | `local_life_agent.planning.decision_planner`、`local_life_agent.core.decision_core` | `CANONICAL` | 冻结顶层 shim 的扩散 | 决策规划保持单一 canonical 实现 |
| review policy | `local_life_agent.planning.policies.review_policy` | `local_life_agent.planning.review_policy` | `CANONICAL` | 顶层 shim 只保留兼容读 | `domain/*` 仍可短期依赖旧路径 |
| replan policy | `local_life_agent.planning.policies.replan_policy` | `local_life_agent.planning.replan_policy` | `CANONICAL` | 冻结顶层 shim，不扩写 | 只允许现有 `_routes.py` 继续消费 |
| ranking policy | `local_life_agent.planning.policies.ranking_policy` | `local_life_agent.planning.ranking_policy` | `CANONICAL` | 冻结顶层 shim | 排序策略不再向旧壳扩散 |
| plan validation | `local_life_agent.planning.plans.plan_validator` | `local_life_agent.planning.plan_validator` | `CANONICAL` | 冻结顶层 shim | 校验逻辑回到 plans 层 |
| state update planning | `local_life_agent.planning.plans.state_update_planner.plan_state_update` | `local_life_agent.planning.state_update_planner`、`local_life_agent.core.state_core` | `NEEDS_DECISION` | 先冻结写回边界，不改责任归属 | `SessionState` 写回责任仍需 Phase 4/5 定版 |
| candidate / shop resolving | `local_life_agent.target.candidate_resolver.CandidateResolver` + `local_life_agent.target.shop_resolver.resolve_shop` | `local_life_agent.core.candidate_core`、`local_life_agent.engine.graph_builder`、`local_life_agent.tools.db_tools.resolve_shop` | `NEEDS_DECISION` | 只冻结，不迁移调用方 | 这里仍存在 target / graph_builder / DB 工具三方耦合 |
| tool gateway | `local_life_agent.tools.gateway.dispatch_tool_call` / `ToolCallGateway` | `local_life_agent.engine.graph_builder` 兼容导出 | `CANONICAL` | 冻结新导出，继续由 gateway 统一执行 | 工具注册和执行边界留在 gateway |
| answer generation | `local_life_agent.answer.generator.generate_answer` | `local_life_agent.core.response_core`、`local_life_agent.engine.graph_builder` 兼容导出 | `CANONICAL` | 只冻结旧面，不改生成逻辑 | 生成器是答复权威入口 |
| answer verification | `local_life_agent.answer.verifier.verify_answer` | `local_life_agent.core.response_core`、`local_life_agent.engine.graph_builder` 兼容导出 | `CANONICAL` | 只冻结旧面，不改验证逻辑 | verifier 继续只做可信校验 |
| session state | `local_life_agent.domain.state.SessionState` / `SessionWriteDirective` | `local_life_agent.core.state_core` | `NEEDS_DECISION` | 先冻结边界，后续再收写回责任 | 这是 Phase 4/5 的重点风险项 |
| graph build entry | `local_life_agent.engine.graph_builder.build_graph` / `verify_graph_completeness` | `local_life_agent.engine.__init__` 旧 re-export | `CANONICAL` | 冻结新增兼容导出，只保留现有 API | 图构建入口本身仍是当前执行主入口 |
| observability trace | `local_life_agent.observability.trace` | `local_life_agent.engine.graph_builder` 兼容导出 | `CANONICAL` | 新代码直接走 observability 层 | 轨迹和执行逻辑不要再混写 |
| streaming events | `local_life_agent.streaming.events` | `TEST_ONLY` fake/status event 变体 | `CANONICAL` | 只允许测试注入，不进生产路径 | 事件协议要与 trace 分开看 |

## 3. Deprecated Path Registry

以下模块被本阶段显式视为 `DEPRECATED_COMPAT`：

- `local_life_agent.core`
- `local_life_agent.core.candidate_core`
- `local_life_agent.core.decision_core`
- `local_life_agent.core.evidence_core`
- `local_life_agent.core.execution_core`
- `local_life_agent.core.planning_core`
- `local_life_agent.core.response_core`
- `local_life_agent.core.state_core`
- `local_life_agent.planning.candidate_review`
- `local_life_agent.planning.comparison_planner`
- `local_life_agent.planning.decision_planner`
- `local_life_agent.planning.decision_review`
- `local_life_agent.planning.evidence_planner`
- `local_life_agent.planning.evidence_review`
- `local_life_agent.planning.execution_plan_builder`
- `local_life_agent.planning.facet_planner`
- `local_life_agent.planning.goal_draft`
- `local_life_agent.planning.goal_planner`
- `local_life_agent.planning.goal_review`
- `local_life_agent.planning.plan_validator`
- `local_life_agent.planning.ranking_policy`
- `local_life_agent.planning.replan_policy`
- `local_life_agent.planning.review_policy`
- `local_life_agent.planning.state_update_planner`
- `local_life_agent.semantic.top_intent_router`

Phase 1 只做冻结，不做删除。

## 4. Phase 1 结论

- 新代码默认应走 canonical path
- 旧入口只允许现有 caller
- `DEPRECATED_COMPAT` 标记已经补齐
- boundary tests 已准备好作为后续 Phase 2/6 的拦截器

