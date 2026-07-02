# P3 Facet Protocol and Retention Report

## 1. Conclusion

PASS with note

## 2. Inputs

- P0 report: [`todo/p0_fact_calibration_and_adr_freeze_report.md`](D:/javacode/hm-dianping/todo/p0_fact_calibration_and_adr_freeze_report.md)
- ADR: [`todo/adr_p0_single_owner_workflow_no_map_reduce.md`](D:/javacode/hm-dianping/todo/adr_p0_single_owner_workflow_no_map_reduce.md)
- P1 report: [`todo/p1_single_owner_workflow_invariants_report.md`](D:/javacode/hm-dianping/todo/p1_single_owner_workflow_invariants_report.md)
- P2 report: [`todo/p2_router_priority_and_keyword_conflict_report.md`](D:/javacode/hm-dianping/todo/p2_router_priority_and_keyword_conflict_report.md)
- Inherited invariants:
  - `workflow_name` 仍是单值
  - `workflow_runner` 仍是单 dispatch
  - registry 仍是单 lookup
  - `_routes.py` 无 workflow fan-out
  - 未新增 workflow / tool
  - 未引入 workflow 级 Map-Reduce
  - keyword 仍只是 signal，不是主分类器
  - 缺 resolved target 的单店事实 query 仍进入澄清

## 3. Scope

本轮修改 / 检查的文件：

- [`local_life_agent/domain/facets.py`](D:/javacode/hm-dianping/local_life_agent/domain/facets.py)
- [`local_life_agent/domain/enums.py`](D:/javacode/hm-dianping/local_life_agent/domain/enums.py)
- [`local_life_agent/domain/schemas.py`](D:/javacode/hm-dianping/local_life_agent/domain/schemas.py)
- [`local_life_agent/domain/goal.py`](D:/javacode/hm-dianping/local_life_agent/domain/goal.py)
- [`local_life_agent/domain/decision.py`](D:/javacode/hm-dianping/local_life_agent/domain/decision.py)
- [`local_life_agent/domain/graph_state.py`](D:/javacode/hm-dianping/local_life_agent/domain/graph_state.py)
- [`local_life_agent/planning/orchestration_router.py`](D:/javacode/hm-dianping/local_life_agent/planning/orchestration_router.py)
- [`local_life_agent/planning/goal/goal_planner.py`](D:/javacode/hm-dianping/local_life_agent/planning/goal/goal_planner.py)
- [`local_life_agent/planning/plans/execution_plan_builder.py`](D:/javacode/hm-dianping/local_life_agent/planning/plans/execution_plan_builder.py)
- [`local_life_agent/planning/evidence/evidence_builder.py`](D:/javacode/hm-dianping/local_life_agent/planning/evidence/evidence_builder.py)
- [`local_life_agent/planning/decision/decision_planner.py`](D:/javacode/hm-dianping/local_life_agent/planning/decision/decision_planner.py)
- [`local_life_agent/answer/answer_plan_builder.py`](D:/javacode/hm-dianping/local_life_agent/answer/answer_plan_builder.py)
- [`local_life_agent/engine/subgraphs/planning_subgraph.py`](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/planning_subgraph.py)
- [`local_life_agent/engine/workflows/deterministic_tool_workflow.py`](D:/javacode/hm-dianping/local_life_agent/engine/workflows/deterministic_tool_workflow.py)
- [`local_life_agent/tests/test_p3_facet_protocol.py`](D:/javacode/hm-dianping/local_life_agent/tests/test_p3_facet_protocol.py)

## 4. Facet Taxonomy

已标准化的 facet groups 与 facets：

- `location`: `nearby`, `distance`, `business_area`, `travel_time`
- `category`: `restaurant`, `hotpot`, `coffee`, `dessert`, `parent_child`, `entertainment`, `shopping`
- `scene`: `date_scene`, `family_with_kids`, `friends_party`, `quiet`, `lively`, `business_meeting`, `work_study`, `late_night`
- `status`: `open_now`, `open_late`, `reservation_available`, `queue_status`
- `deal`: `coupon`, `discount`, `group_buy`, `cost_performance`
- `price`: `avg_price`, `budget`, `budget_around_x`, `price_compare`
- `quality`: `rating`, `review_tags`, `popularity`, `service`, `environment`, `taste`
- `preference`: `not_too_noisy`, `kid_friendly`, `parking`, `private_room`, `spicy`, `light_food`, `vegetarian`
- `reference`: `current_shop`, `ordinal_reference`, `previous_recommendation`, `comparison_targets`

## 5. TargetResolutionResult Protocol

已引入最小 `TargetResolutionResult`，字段与语义如下：

- `target_shop`: 已解析到的目标店铺
- `resolved`: 是否已解析出单目标或明确比较目标
- `source`: 解析来源，如 `current_shop`、`last_recommendation_list`、`explicit_shop_name`、`comparison_targets`
- `confidence`: 解析置信度
- `owner`: 协议产生者，当前主要是 `orchestration_router`
- `resolution_reason`: 成功或失败原因
- `reference_type`: 引用类型，如 `current_shop`、`ordinal_reference`、`previous_recommendation`、`comparison_targets`
- `unresolved_reason`: 未解析原因，如 `missing_current_shop`、`missing_last_recommendation_list`、`ordinal_out_of_range`、`ambiguous_target`

说明：

- `orchestration_router` 负责初始化和产出 target resolution 结果
- `planning_subgraph` / 后续链路只消费和传递，不再重复猜目标
- 未解析时仍会回到 `clarification_fallback`

## 6. Full-chain Retention

- `SemanticFrame`
  - 现在可携带标准化 `facets`、`facet_set`、`target_resolution`、`conflicting_facets`、`ranking_policy`
  - `current_shop`、`ordinal_reference`、`previous_recommendation`、`comparison_targets` 都能作为 reference facets 传递
- `GoalPlan`
  - 已从 `SemanticFrame` 接收 facets，并保留到 `GoalPlan.facets`
  - 同步保留 `target_resolution`、`conflicting_facets`、`ranking_policy`
  - 不再把 facets 丢成仅有文本摘要
- `ExecutionPlan`
  - 已携带 `facets`、`target_resolution`、`conflicting_facets`、`ranking_policy`
  - recommendation 计划保留了 facets，并继续沿用现有分 stage 执行结构
  - deterministic single-target fact query 仍然只在 resolved target 上执行
- `EvidencePack`
  - 已携带 query facets 元信息，以及 `target_resolution` / `conflicting_facets` / `ranking_policy`
  - 当前只是协议元数据保留，不进入 P4 的完整 answerable / unknown / failed 语义
- `DecisionPlan`
  - 已携带 facets、comparison facets、ranking policy 和 target resolution
  - 仍然是单一决策对象，没有变成多主 merge
- `AnswerPlan`
  - 已携带 facets / target resolution / conflicting facets / ranking policy
  - 只负责回答计划元数据，不做 P4 的无证据 claim 校验

## 7. deterministic_tool Boundary

- 单目标多 facet 现在可以通过一个 `TargetResolutionResult` 表达
- 缺 target 时仍会澄清，不会进入 deterministic_tool
- deterministic_tool 只处理 resolved single target 上的 single-target fact query
- 不做候选召回
- 不做推荐排序
- 不写多个候选列表
- 当前仍保持单次 dispatch_tool_call，不强行引入多工具并行

## 8. Conflicting Facets and RankingPolicy

P3 只做结构准备：

- `ConflictingFacet` 可记录 facet 冲突和原因
- `RankingPolicy` 只表达排序约束和 tradeoff notes
- 当前不做 winner 选择
- 当前不做复杂降级策略
- 复杂 tradeoff 处理保留到后续阶段

## 9. Code Changes

- [`local_life_agent/domain/facets.py`](D:/javacode/hm-dianping/local_life_agent/domain/facets.py)
  - 新增 taxonomy、`QueryFacet`、`FacetSet`、`TargetResolutionResult`、`ConflictingFacet`、`RankingPolicy`
  - 收紧 `current_shop` / `previous_recommendation`，只在明确引用时回填
  - 增强 `distance` / `price_compare` 的中文触发词
- [`local_life_agent/domain/enums.py`](D:/javacode/hm-dianping/local_life_agent/domain/enums.py)
  - 扩展 Facet 枚举以承接标准化 facet 名称
- [`local_life_agent/domain/schemas.py`](D:/javacode/hm-dianping/local_life_agent/domain/schemas.py)
  - `SemanticFrame` / `ExecutionPlan` / `EvidencePack` / `AnswerPlan` 增加 facet 协议字段
- [`local_life_agent/domain/goal.py`](D:/javacode/hm-dianping/local_life_agent/domain/goal.py)
  - `GoalPlan` 保留 facets / target resolution / conflict / ranking metadata
- [`local_life_agent/domain/decision.py`](D:/javacode/hm-dianping/local_life_agent/domain/decision.py)
  - `DecisionPlan` 与 `AnswerPlan` 的协议字段对齐
- [`local_life_agent/domain/graph_state.py`](D:/javacode/hm-dianping/local_life_agent/domain/graph_state.py)
  - GraphState 增加 facets / target_resolution / conflicting_facets / ranking_policy
- [`local_life_agent/planning/orchestration_router.py`](D:/javacode/hm-dianping/local_life_agent/planning/orchestration_router.py)
  - 路由 shadow patch 传递 facet / target-resolution 协议字段
- [`local_life_agent/planning/goal/goal_planner.py`](D:/javacode/hm-dianping/local_life_agent/planning/goal/goal_planner.py)
  - GoalPlan 保留 facets，并继续输出 candidate / evidence 相关元信息
- [`local_life_agent/planning/plans/execution_plan_builder.py`](D:/javacode/hm-dianping/local_life_agent/planning/plans/execution_plan_builder.py)
  - execution plan 与 recommendation execution plan 都携带 facets / target resolution metadata
- [`local_life_agent/planning/evidence/evidence_builder.py`](D:/javacode/hm-dianping/local_life_agent/planning/evidence/evidence_builder.py)
  - EvidencePack 读取执行计划中的 facet 协议元数据，包含嵌套 recommendation plan
- [`local_life_agent/planning/decision/decision_planner.py`](D:/javacode/hm-dianping/local_life_agent/planning/decision/decision_planner.py)
  - DecisionPlan 保留 facets / ranking metadata
- [`local_life_agent/answer/answer_plan_builder.py`](D:/javacode/hm-dianping/local_life_agent/answer/answer_plan_builder.py)
  - AnswerPlan 继续携带 facets / target resolution 元数据
- [`local_life_agent/engine/subgraphs/planning_subgraph.py`](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/planning_subgraph.py)
  - 将 facet 协议带入 planning subgraph 的 state patch
- [`local_life_agent/engine/workflows/deterministic_tool_workflow.py`](D:/javacode/hm-dianping/local_life_agent/engine/workflows/deterministic_tool_workflow.py)
  - 读取 target resolution，缺 target 时澄清，不做候选召回或排序

## 10. Test Changes

新增测试：

- [`local_life_agent/tests/test_p3_facet_protocol.py`](D:/javacode/hm-dianping/local_life_agent/tests/test_p3_facet_protocol.py)

覆盖点：

- taxonomy groups / facets 存在性
- `TargetResolutionResult` 默认值、resolved / unresolved、ordinal / current_shop / comparison source
- 推荐多约束 query 的 facets 保留
- 推荐 + ordinal reference 的 facets 显式保留
- 单店多 facet query 有 / 无 `current_shop` 的分流
- comparison query 的 reference / preference facets 保留
- exploration planning query 的 facets 保留
- facet 不退化成主路由列表
- deterministic_tool 仍只在 resolved target 上执行

## 11. Test Results

执行命令：

```bash
python -m compileall local_life_agent
pytest local_life_agent/tests/test_p1_single_owner_invariants.py \
       local_life_agent/tests/test_p2_router_priority.py \
       local_life_agent/tests/test_orchestration_router.py \
       local_life_agent/tests/test_p3_facet_protocol.py -q
```

结果：

- `compileall` 成功
- `pytest` 通过：`44 passed in 34.29s`

## 12. Acceptance Judgment

- 标准 facet taxonomy 存在：PASS
- `TargetResolutionResult` 存在且可序列化：PASS
- 推荐多约束 facet 不丢：PASS
- 单店多 facet 不丢：PASS
- 多维对比 facet 不丢：PASS
- exploration planning facet 不丢：PASS
- facet 不退化成 `route_task` 列表：PASS
- deterministic_tool 不做候选召回 / 排序：PASS
- P1 / P2 回归未破坏：PASS

## 13. Remaining Risks

- P3 只解决 facet 协议和保留，不是完整决策重构
- `answerable` / `unknown` / `failed` facets 留到 P4
- State 写回污染防护留到 P5
- 复杂 query 全矩阵留到 P6
- exploration_planning 共享 adapter 留到 P7

## 14. Deferred to Later Phases

- P4 Evidence / Decision / Answer
- P5 SessionState 写回
- P6 复杂 query 测试矩阵
- P7 exploration_planning 协议同构
- P8 证据不足迭代
