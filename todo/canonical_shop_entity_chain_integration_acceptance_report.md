# 统一门店实体归一化边界全链路接入覆盖验收报告

## 1. 总体结论

**FAIL**

当前仓库已经具备 canonical shop entity 的基础件和部分接入点，但还没有达到“统一事实源”的验收标准。

关键判断：

- `ShopResolutionResult` / `canonical_shop_entity` 已存在，且在部分链路中被写入。
- `deterministic_tool_workflow` 已优先读取 canonical entity，并能在 resolved 时复用同一个 `shop_id`。
- `session_write` 的写回边界总体是收紧的，`resolved` / `ambiguous` / `low_confidence` / `not_found` 的写回方向已明显优于旧版本。
- 但 `planning_subgraph` 的 canonical 分支仍是 shadow：canonical 写了，真正裁决仍主要由 candidate_set / legacy 结果主导。
- 实测 query 仍存在明确回退到澄清的情况，尤其是单店明确门店 + coupon/distance/multi-facet 场景。
- comparison flow 仍有把比较请求误判为缺 slot / clarification 的情况。

因此，这一轮验收不能判定为 PASS，也不能判定为 PARTIAL PASS，只能判定为 FAIL。

## 2. 审查范围

本轮重点检查了以下文件和链路：

- [`local_life_agent/domain/shop_entity.py`](D:/javacode/hm-dianping/local_life_agent/domain/shop_entity.py)
- [`local_life_agent/target/shop_name_normalizer.py`](D:/javacode/hm-dianping/local_life_agent/target/shop_name_normalizer.py)
- [`local_life_agent/target/shop_alias.py`](D:/javacode/hm-dianping/local_life_agent/target/shop_alias.py)
- [`local_life_agent/target/shop_resolution_policy.py`](D:/javacode/hm-dianping/local_life_agent/target/shop_resolution_policy.py)
- [`local_life_agent/target/shop_resolver.py`](D:/javacode/hm-dianping/local_life_agent/target/shop_resolver.py)
- [`local_life_agent/target/candidate_resolver.py`](D:/javacode/hm-dianping/local_life_agent/target/candidate_resolver.py)
- [`local_life_agent/domain/facets.py`](D:/javacode/hm-dianping/local_life_agent/domain/facets.py)
- [`local_life_agent/engine/subgraphs/planning_subgraph.py`](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/planning_subgraph.py)
- [`local_life_agent/engine/workflows/deterministic_tool_workflow.py`](D:/javacode/hm-dianping/local_life_agent/engine/workflows/deterministic_tool_workflow.py)
- [`local_life_agent/engine/session_write.py`](D:/javacode/hm-dianping/local_life_agent/engine/session_write.py)
- [`local_life_agent/planning/plans/state_update_planner.py`](D:/javacode/hm-dianping/local_life_agent/planning/plans/state_update_planner.py)
- [`local_life_agent/planning/orchestration_router.py`](D:/javacode/hm-dianping/local_life_agent/planning/orchestration_router.py)
- [`local_life_agent/target/reference_resolver.py`](D:/javacode/hm-dianping/local_life_agent/target/reference_resolver.py)
- [`local_life_agent/planning/evidence/evidence_builder.py`](D:/javacode/hm-dianping/local_life_agent/planning/evidence/evidence_builder.py)
- [`local_life_agent/answer/answer_plan_builder.py`](D:/javacode/hm-dianping/local_life_agent/answer/answer_plan_builder.py)
- [`local_life_agent/answer/verifier.py`](D:/javacode/hm-dianping/local_life_agent/answer/verifier.py)
- [`local_life_agent/answer/final_response_builder.py`](D:/javacode/hm-dianping/local_life_agent/answer/final_response_builder.py)
- [`local_life_agent/engine/subgraphs/state_update_plan.py`](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/state_update_plan.py)
- [`local_life_agent/engine/subgraphs/understanding_subgraph.py`](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/understanding_subgraph.py)
- [`local_life_agent/planning/plans/execution_plan_builder.py`](D:/javacode/hm-dianping/local_life_agent/planning/plans/execution_plan_builder.py)
- [`local_life_agent/domain/graph_state.py`](D:/javacode/hm-dianping/local_life_agent/domain/graph_state.py)
- [`local_life_agent/domain/state.py`](D:/javacode/hm-dianping/local_life_agent/domain/state.py)

测试与复现范围：

- `pytest local_life_agent/tests/test_candidate_resolver.py local_life_agent/tests/test_deterministic_tool_workflow.py local_life_agent/tests/test_single_coupon_flow.py local_life_agent/tests/test_single_shop_multifacet.py local_life_agent/tests/test_comparison_flow.py local_life_agent/tests/test_recommendation_flow.py local_life_agent/tests/test_p5_session_state_writeback.py local_life_agent/tests/test_p1_single_owner_invariants.py local_life_agent/tests/test_target_resolve_candidate_set.py -q`
- `pytest local_life_agent/tests/test_phase_a_contracts.py local_life_agent/tests/test_phase_e_state_contracts.py local_life_agent/tests/test_p4_evidence_decision_answer_protocol.py local_life_agent/tests/test_phase7_workflows.py local_life_agent/tests/test_p2_router_priority.py -q`
- 临时 fake runtime query 复现脚本，覆盖 8 条关键 query

## 3. 统一边界基础件验收

| 文件 | 是否存在 | 是否符合职责 | 是否被调用 | 发现的问题 | 结论 |
|---|---|---|---|---|---|
| [`local_life_agent/domain/shop_entity.py`](D:/javacode/hm-dianping/local_life_agent/domain/shop_entity.py) | 是 | 基本符合，定义了 canonical result / candidate / status / trace / confidence / source / needs_clarification | 是 | `ShopResolutionResult` 的结构完整，但仍兼容 legacy dict | PASS |
| [`local_life_agent/target/shop_name_normalizer.py`](D:/javacode/hm-dianping/local_life_agent/target/shop_name_normalizer.py) | 是 | 符合，仅做门店文本归一化 | 是 | 当前仅归一化，不裁决；符合设计 | PASS |
| [`local_life_agent/target/shop_alias.py`](D:/javacode/hm-dianping/local_life_agent/target/shop_alias.py) | 是 | 符合，基于真实 record 生成 alias | 是 | 生成 alias 仍需要 resolver 限制在 candidate set 内 | PASS |
| [`local_life_agent/target/shop_resolution_policy.py`](D:/javacode/hm-dianping/local_life_agent/target/shop_resolution_policy.py) | 是 | 基本符合，单点 scoring / decision policy 存在 | 是 | policy 仍依赖 legacy candidate set，且分支上对 explicit/shop 路径仍有多套判定 | PARTIAL |
| [`local_life_agent/target/shop_resolver.py`](D:/javacode/hm-dianping/local_life_agent/target/shop_resolver.py) | 是 | 部分符合，提供 `resolve_shop_entity` / `resolve_shop_entities` facade | 是 | facade 下面仍保留 legacy `_legacy_resolve_shop`、`resolve_shop` adapter，以及 candidate_resolver 后端 | PARTIAL |

结论：

- 基础件已经“存在并可用”
- 但尚未达到“单一事实源、单一路径、单一裁决点”的严格要求

## 4. 全仓库调用与绕过地图

| 文件 / 函数 | 是否调用 canonical resolver | 是否读取 canonical_shop_entity | 是否仍直接调用旧 `resolve_shop` | 是否仍直接读 `merchant_mentions` / `current_shop` 做裁决 | 是否写 `current_shop` / `pending_clarification` | 接入状态 | 风险等级 |
|---|---|---|---|---|---|---|---|
| [`local_life_agent/engine/subgraphs/planning_subgraph.py`](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/planning_subgraph.py) `_h_target_resolve_candidate_set` | 是，先写 canonical，再进 candidate_set | 是 | 是，仍有 legacy/兼容分支 | 是，比较/单店判断仍依赖 legacy 语义和 candidate_set | 是 | PARTIAL / RISKY | P0 |
| [`local_life_agent/engine/workflows/deterministic_tool_workflow.py`](D:/javacode/hm-dianping/local_life_agent/engine/workflows/deterministic_tool_workflow.py) `_resolve_single_shop_target` | 是，canonical 优先 | 是 | 是，canonical 不可用时继续走 facade / legacy reference / `resolve_shop` | 是，仍读 `merchant_mentions` / `branch_mentions` / `current_shop` / `reference_resolution` | 是 | PARTIAL | P1 |
| [`local_life_agent/planning/plans/state_update_planner.py`](D:/javacode/hm-dianping/local_life_agent/planning/plans/state_update_planner.py) `plan_state_update` | 否 | 是 | 否 | 是，写回时仍读 `current_shop` / `comparison_targets` / `last_recommendation_list` | 是 | PARTIAL | P1 |
| [`local_life_agent/planning/orchestration_router.py`](D:/javacode/hm-dianping/local_life_agent/planning/orchestration_router.py) `_has_deterministic_target_hints` | 否 | 间接读取 | 否 | 是，仍靠 `merchant_mentions` / `ordinal_references` / `current_shop` 判断 | 否 | PARTIAL | P1 |
| [`local_life_agent/target/reference_resolver.py`](D:/javacode/hm-dianping/local_life_agent/target/reference_resolver.py) `resolve_comparison_targets` | 是，内部调用 `resolve_shop_entity` | 是 | 是，输出仍是兼容 legacy dict | 是，仍消费 `merchant_mentions` / `comparison_targets` / `ordinal_references` | 是 | PARTIAL | P1 |
| [`local_life_agent/target/candidate_resolver.py`](D:/javacode/hm-dianping/local_life_agent/target/candidate_resolver.py) `resolve_explicit` / `resolve_context` | 否 | 否 | 是，核心仍是旧 resolve/search 后端 | 是，仍读 `current_shop` / `comparison_targets` | 否 | NOT_CONNECTED | P1 |
| [`local_life_agent/domain/facets.py`](D:/javacode/hm-dianping/local_life_agent/domain/facets.py) `normalize_query_facets` / `build_target_resolution_result` | 间接 | 是，但只是 protocol | 否 | 是，仍读取 `current_shop` / `merchant_mentions` / `comparison_targets` 做 minimal target protocol | 否 | PARTIAL / SHADOW | P1 |
| [`local_life_agent/planning/evidence/evidence_builder.py`](D:/javacode/hm-dianping/local_life_agent/planning/evidence/evidence_builder.py) `build_evidence` | 否 | 否 | 否 | 只消费 evidence / candidate / comparison target 结果，不做门店裁决 | 否 | FULL | P2 |
| [`local_life_agent/answer/answer_plan_builder.py`](D:/javacode/hm-dianping/local_life_agent/answer/answer_plan_builder.py) `build_answer_plan` | 否 | 否 | 否 | 不直接回读门店文本裁决 | 否 | FULL | P2 |
| [`local_life_agent/answer/verifier.py`](D:/javacode/hm-dianping/local_life_agent/answer/verifier.py) `verify_answer` | 否 | 否 | 否 | 只验 evidence / answer 一致性 | 否 | FULL | P2 |
| [`local_life_agent/answer/final_response_builder.py`](D:/javacode/hm-dianping/local_life_agent/answer/final_response_builder.py) `build_final_response` | 否 | 否 | 否 | 只是 DTO 封装 | 否 | FULL | P2 |

## 5. planning_subgraph 接入验收

相关位置：

- [`local_life_agent/engine/subgraphs/planning_subgraph.py`](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/planning_subgraph.py#L361)
- [`local_life_agent/engine/subgraphs/planning_subgraph.py`](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/planning_subgraph.py#L494)
- [`local_life_agent/engine/subgraphs/planning_subgraph.py`](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/planning_subgraph.py#L560)
- [`local_life_agent/engine/subgraphs/planning_subgraph.py`](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/planning_subgraph.py#L757)

已接入点：

- `canonical_shop_entity` / `canonical_shop_entities` / `shop_resolution_trace` 已写入 payload
- comparison 场景下会调用 `resolve_shop_entities`
- canonical result 里保留了 `status` / `needs_clarification` / `trace`

未接入点：

- `if False and task_type_value in {TaskType.single_shop_query.value, TaskType.coupon_query.value}` 这一段是死分支，canonical 结果没有成为 live single-shop 判定入口
- live 路径仍是 `_CANDIDATE_CORE.resolve(...)` + `review_candidate_set(...)` + `resolve_shop_result` / `resolved_target` 生成
- `planning_subgraph` 的继续 / 澄清 / fallback 主要还是基于 candidate_set / review，而不是 canonical result 本身

残留旧逻辑：

- 单店解析仍然依赖 candidate_set review 作为主裁决
- 旧的 ambiguous / low_confidence / not_found 仍通过 legacy route 推进

P0 风险：

- canonical 只是写入字段，不是事实源
- resolved canonical 没有真正驱动 live route
- 这会导致“看起来接了 canonical，实际上继续走旧链路”的 shadow 接入

最小修复建议：

- 把 live single-shop / coupon / distance / queue / parking 路径从 candidate_set review 改为直接消费 `ShopResolutionResult`
- 让 `status == resolved` 成为单店任务唯一的继续条件
- 保留 candidate_set 仅作为 backend / 备选候选列表，不再作为主裁决点

## 6. deterministic_tool_workflow 接入验收

相关位置：

- [`local_life_agent/engine/workflows/deterministic_tool_workflow.py`](D:/javacode/hm-dianping/local_life_agent/engine/workflows/deterministic_tool_workflow.py#L251)
- [`local_life_agent/engine/workflows/deterministic_tool_workflow.py`](D:/javacode/hm-dianping/local_life_agent/engine/workflows/deterministic_tool_workflow.py#L398)
- [`local_life_agent/engine/workflows/deterministic_tool_workflow.py`](D:/javacode/hm-dianping/local_life_agent/engine/workflows/deterministic_tool_workflow.py#L463)
- [`local_life_agent/engine/workflows/deterministic_tool_workflow.py`](D:/javacode/hm-dianping/local_life_agent/engine/workflows/deterministic_tool_workflow.py#L742)

验收结论：

- **接入状态：PARTIAL**

已接入点：

- canonical entity 先读
- `status == resolved` 时直接复用同一个 `shop_id` 进入工具调用
- `canonical_shop_entity` / `canonical_shop_entities` / `shop_resolution_trace` 会写回
- tool 目标一致性总体不错，coupon / queue / distance / open_status 都共享同一个 `shop_id`

仍绕过 canonical 层的地方：

- canonical 不可用时，仍会继续走 `resolve_shop_entity`
- 之后还有 `resolve_shop(...)`、`resolve_references(...)`、`comparison_target_resolution` 等兼容路径
- `route_info` 也允许 raw text override，说明还存在第二套主路径

二次解析情况：

- 存在
- canonical -> facade -> legacy reference / explicit mention / current_shop 的多层回退还在

多个 facet 使用不同 `shop_id` 风险：

- 当前实现对 deterministic tool 主路径基本使用单一 shop_id
- 风险主要来自“前置解析不稳定导致根本没进入工具层”，而不是工具层内多 shop_id 分裂

最小修复建议：

- 若 canonical 已 resolved，直接视为工具层唯一目标，不再做额外 shop 目标复算
- canonical 未 resolved 时，仅允许 facade 做一次统一回退，不要再拆成多套目标恢复逻辑

## 7. session_write 写回验收

说明：

- `engine/session_write.py` 本身是策略表，不是最终落盘执行点
- 真正的写回门禁主要在 [`local_life_agent/planning/plans/state_update_planner.py`](D:/javacode/hm-dianping/local_life_agent/planning/plans/state_update_planner.py#L107)

结论：

- **写回规则：总体统一，但仍带兼容性分支**

验证结果：

- `resolved == RESOLVED` 时允许写 `current_shop`
- `resolved == RESOLVED` 后会清 `pending_clarification`
- `ambiguous` / `low_confidence` / `not_found` 不会把 `current_shop` 静默写进去
- `ambiguous` / `low_confidence` / `not_found` 不会在错误条件下把 pending 直接清空
- `no_mention` 继承 `current_shop` 时会带 `source=current_shop` / reference
- 工具失败时不会误写 `current_shop`
- `comparison_targets` 会写标准实体或兼容结构
- `last_recommendation_list` 主要来自真实推荐候选与 evidence，而不是 shop entity fallback

仍可能被旧逻辑写入的字段：

- `comparison_targets` 仍受 session / recovery 兼容路径影响
- `last_recommendation_list` 在 exploration planning 与 recommendation 之间仍有兼容读取
- `canonical_shop_entity` 只在 turn_context 中写入，不等于 session 里已成为唯一事实源

session 污染风险：

- 中等
- 主要风险不是“错写 current_shop”，而是“兼容层 / 恢复层继续携带旧字段，导致后续节点误判门店状态”

P0/P1/P2 缺口：

- P0：无明显错写 current_shop
- P1：兼容字段多源输入仍会造成后续 node 误解读
- P2：可以继续收敛 `comparison_targets` / `last_recommendation_list` 的来源约束

## 8. shop_resolver facade 验收

相关位置：

- [`local_life_agent/target/shop_resolver.py`](D:/javacode/hm-dianping/local_life_agent/target/shop_resolver.py#L219)
- [`local_life_agent/target/shop_resolver.py`](D:/javacode/hm-dianping/local_life_agent/target/shop_resolver.py#L443)
- [`local_life_agent/target/shop_resolver.py`](D:/javacode/hm-dianping/local_life_agent/target/shop_resolver.py#L463)
- [`local_life_agent/target/shop_resolver.py`](D:/javacode/hm-dianping/local_life_agent/target/shop_resolver.py#L491)
- [`local_life_agent/target/shop_resolver.py`](D:/javacode/hm-dianping/local_life_agent/target/shop_resolver.py#L512)

结论：

- **facade 存在，但仍是 facade + adapter + legacy 的混合体**

facade 调用方：

- `planning_subgraph`
- `deterministic_tool_workflow`
- `reference_resolver`
- `candidate_resolver` 的默认 backend
- 测试中的多处 wrapper / fake backend

仍直接调用 `candidate_resolver` / `resolve_shop` 的地方：

- `candidate_resolver` 自身是旧 candidate backend 的核心
- `shop_resolver.resolve_shop` 仍是 backward-compatible function
- `planning_subgraph` / `deterministic_tool_workflow` 都仍有回退到 legacy path 的可能

合理性判断：

- 兼容存在是合理的
- 但当前仍不是“统一单点决策”的最终形态

需要迁移到 facade 的地方：

- 任何仍在做门店事实裁决的模块，都应先走 `resolve_shop_entity` / `resolve_shop_entities`
- `candidate_resolver` 只应做 backend / candidate set 构建，不应成为事实源

## 9. facets.py 职责边界验收

相关位置：

- [`local_life_agent/domain/facets.py`](D:/javacode/hm-dianping/local_life_agent/domain/facets.py#L203)
- [`local_life_agent/domain/facets.py`](D:/javacode/hm-dianping/local_life_agent/domain/facets.py#L387)

当前职责：

- 语义角色识别
- facet 归一
- target_resolution minimal protocol 构建
- current_shop / comparison_targets / ordinal_references 的轻量协议映射

是否越界做实体裁决：

- **部分越界**
- 它不是 canonical entity 的事实源，但 `build_target_resolution_result` 已经承担了部分 target 解释与继承逻辑

下游风险：

- 下游如果直接消费 `facets.py` 的 target_resolution 而不再走 canonical resolver，就会把“语义协议”误当成“实体事实”

结论：

- `facets.py` 仍应保留为语义层
- 不应升级为实体事实源

## 10. recommendation_flow 保护验收

相关位置：

- [`local_life_agent/planning/evidence/evidence_builder.py`](D:/javacode/hm-dianping/local_life_agent/planning/evidence/evidence_builder.py#L1059)
- [`local_life_agent/answer/answer_plan_builder.py`](D:/javacode/hm-dianping/local_life_agent/answer/answer_plan_builder.py#L54)
- [`local_life_agent/answer/verifier.py`](D:/javacode/hm-dianping/local_life_agent/answer/verifier.py#L400)

结论：

- **接入状态：PARTIAL**

ranking_snapshot 来源检查：

- 来自真实 tool result + candidate set + ranking pipeline
- `build_evidence` / `build_answer_plan` / `verify_answer` 都没有把 canonical entity 伪造成 top-3

是否存在实体层误伤推荐链路：

- 存在
- 主要表现为：某些本应进入 recommendation 的单店/明确门店 query 被前置解析打到 clarification

相关测试结果：

- `test_recommendation_flow.py` 相关用例整体通过
- 但 recommendation 仍会受到前置 target resolution 的影响

结论：

- recommendation 主体没有伪造 ranking_snapshot
- 但推荐链路与 entity resolution 之间仍存在耦合风险

## 11. comparison_flow 多实体验收

相关位置：

- [`local_life_agent/target/reference_resolver.py`](D:/javacode/hm-dianping/local_life_agent/target/reference_resolver.py#L188)
- [`local_life_agent/engine/subgraphs/planning_subgraph.py`](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/planning_subgraph.py#L424)
- [`local_life_agent/planning/plans/state_update_planner.py`](D:/javacode/hm-dianping/local_life_agent/planning/plans/state_update_planner.py#L318)

结论：

- **接入状态：PARTIAL / RISKY**

多目标解析缺口：

- comparison 支持 `resolve_shop_entities`
- 但 comparison target 的 success criteria 仍不稳定
- ambiguous target 的澄清与 current_shop 写回仍需要更强约束

实测结果：

- `海底捞水晶城店和万象城店哪个好` 在当前 fake runtime 复现中进入了 clarification_fallback，而不是稳定 comparison
- 这说明 comparison 入口仍会被前置 slot / reference 逻辑误伤

结论：

- comparison 不是 FULL
- 当前仍存在误判为单店 / 缺 slot / clarification 的风险

最小修复建议：

- comparison 的 target_resolution 必须先于单店解析落地
- comparison 只允许在两个或以上 target 明确时进入执行
- ambiguous target 只能局部澄清，不允许污染 current_shop

## 12. evidence / answer 协议验收

相关位置：

- [`local_life_agent/planning/evidence/evidence_builder.py`](D:/javacode/hm-dianping/local_life_agent/planning/evidence/evidence_builder.py#L764)
- [`local_life_agent/planning/evidence/evidence_builder.py`](D:/javacode/hm-dianping/local_life_agent/planning/evidence/evidence_builder.py#L1004)
- [`local_life_agent/answer/answer_plan_builder.py`](D:/javacode/hm-dianping/local_life_agent/answer/answer_plan_builder.py#L54)
- [`local_life_agent/answer/verifier.py`](D:/javacode/hm-dianping/local_life_agent/answer/verifier.py#L108)
- [`local_life_agent/answer/final_response_builder.py`](D:/javacode/hm-dianping/local_life_agent/answer/final_response_builder.py#L6)

结论：

- **PASS**

核查结果：

- 实体解析结果只是工具目标，不是答案证据
- `answer_plan_builder` 读取的是 evidence / ranking_snapshot / comparison_matrix
- `verify_answer` 只校验 answer 与 evidence 的一致性
- `final_response_builder` 只是 DTO 封装，不做事实裁决
- 没有发现“解析成功即回答”的主链路

## 13. 关键 query 复现结果

复现方式：

- 使用 fake runtime + 临时脚本
- 记录 `workflow_name`、`canonical_shop_entity.status`、`resolve_shop_result`、`pending_clarification`、`tool_calls`、`current_shop`、`ranking_snapshot`、`comparison_targets`

### 13.1 复现结果总览

| Query | workflow | canonical status | resolve status | tool calls | pending_clarification | current_shop_after | 结果 |
|---|---|---|---|---|---|---|---|
| 海底捞水晶城店排队久吗，有没有优惠券，停车方便吗 | clarification_fallback | not_found | NOT_FOUND | 无 | true | 空 | 失败，进入澄清 |
| 海底捞水晶城店多久能到 | clarification_fallback | not_found | NOT_FOUND | 无 | true | 空 | 失败，进入澄清 |
| 水晶城海底捞现在要等多久 | clarification_fallback | not_found | NOT_FOUND | 无 | true | 空 | 失败，进入澄清 |
| 海底捞水晶诚店有券吗 | clarification_fallback | not_found | NOT_FOUND | 仅有 search_shops | true | 空 | 失败，进入澄清 |
| 水晶城店怎么样 | discovery_decision | 记录为 recommendation 路径 | RESOLVED | search_shops + multi-tool ranking | false | 空 | 成功，进入推荐 |
| 海底捞水晶城店和万象城店哪个好 | clarification_fallback | 无 | 无 | 无 | true | 空 | 失败，进入澄清 |
| 附近有什么适合朋友聚餐的火锅店，优先评分高一点 | discovery_decision | 影子字段 | RESOLVED | search_shops + ranking pipeline | false | 空 | 成功，推荐结果正常 |
| 这家店有优惠券吗？（前置 current_shop） | deterministic_tool | resolved | RESOLVED | search_shops + get_coupon_list | false | shop_007 | 成功，current_shop 复用正常 |

### 13.2 关键信号

- 单店明确门店查询在当前实现里仍然可能被判成“店名模糊”
- comparison 查询仍可能被澄清掉
- recommendation 查询本身可以正常跑通，并生成真实 ranking_snapshot
- current_shop follow-up 是目前最稳定的 canonical 复用路径

### 13.3 与验收要求的对应

- `status == resolved` 后复用同一 shop_id：部分成立
- `status == resolved` 仍进入 clarification：在 planning_subgraph / 单店链路里仍可能发生，属于不满足项
- `ambiguous / low_confidence / not_found` 不强行执行工具：成立
- `comparison` 不应被误判为单店：当前仍不稳定

## 14. 测试命令与测试结果

### 14.1 命令 1

```bash
pytest local_life_agent/tests/test_candidate_resolver.py local_life_agent/tests/test_deterministic_tool_workflow.py local_life_agent/tests/test_single_coupon_flow.py local_life_agent/tests/test_single_shop_multifacet.py local_life_agent/tests/test_comparison_flow.py local_life_agent/tests/test_recommendation_flow.py local_life_agent/tests/test_p5_session_state_writeback.py local_life_agent/tests/test_p1_single_owner_invariants.py local_life_agent/tests/test_target_resolve_candidate_set.py -q
```

结果：

- `106 passed`
- `8 failed`
- `2 xfailed`

失败项：

- `local_life_agent/tests/test_candidate_resolver.py::TestResolveExplicit::test_not_found_mention_skipped_uses_current_seed_id`
- `local_life_agent/tests/test_single_coupon_flow.py::test_exact_shop_name_reaches_coupon_tool_and_returns_coupon`
- `local_life_agent/tests/test_single_coupon_flow.py::test_empty_coupon_shop_returns_no_coupon_notice`
- `local_life_agent/tests/test_single_coupon_flow.py::test_timeout_coupon_shop_degrades_controlled`
- `local_life_agent/tests/test_single_shop_multifacet.py::test_graph_semantic_parse_uses_llm_call`
- `local_life_agent/tests/test_single_shop_multifacet.py::test_group_buy_query_maps_to_coupon_by_semantic_frame`
- `local_life_agent/tests/test_single_shop_multifacet.py::test_unrecognized_facet_does_not_default_coupon`
- `local_life_agent/tests/test_comparison_flow.py::test_compare_first_item_and_explicit_shop`

与 canonical shop entity 的关系：

- 前 3 个 `single_coupon_flow` 失败和 `comparison_flow` 失败直接相关
- `candidate_resolver` 失败更像是数据 ID / fixture 兼容问题，和 canonical 边界本身的关系较弱
- `single_shop_multifacet` 的 3 个失败与单店解析 / facet 路由耦合有关

### 14.2 命令 2

```bash
pytest local_life_agent/tests/test_phase_a_contracts.py local_life_agent/tests/test_phase_e_state_contracts.py local_life_agent/tests/test_p4_evidence_decision_answer_protocol.py local_life_agent/tests/test_phase7_workflows.py local_life_agent/tests/test_p2_router_priority.py -q
```

结果：

- `28 passed`

### 14.3 结论

- 协议、状态、evidence、answer、phase7 工作流的基础契约是稳定的
- 真正失败集中在门店实体接入边界、单店券/多 facet、comparison 路由三个位置

## 15. 全链路接入矩阵

| 链路 / 模块 | 接入状态 | 是否调用统一 resolver | 是否读取 canonical_shop_entity | 是否仍有旧解析主路径 | 是否统一写回 | 风险等级 | 结论 |
|---|---|---|---|---|---|---|---|
| shop_entity schema | FULL | 否 | 是 | 否 | 否 | P2 | 基础件到位 |
| shop_name_normalizer | FULL | 否 | 否 | 否 | 否 | P2 | 仅 normalization |
| shop_alias | FULL | 否 | 否 | 否 | 否 | P2 | 生成 alias 合理 |
| shop_resolution_policy | PARTIAL | 否 | 否 | 是 | 否 | P1 | 单点 scoring 存在，但主路由未完全收敛 |
| shop_resolver facade | PARTIAL | 是 | 是 | 是 | 否 | P1 | facade 存在，adapter/legacy 也在 |
| candidate_resolver | NOT_CONNECTED | 否 | 否 | 是 | 否 | P1 | 仍是旧 candidate backend |
| facets.py | PARTIAL / SHADOW | 否 | 间接 | 是 | 否 | P1 | 语义层 + minimal protocol，仍有 target 解释 |
| target_resolve | PARTIAL / RISKY | 部分 | 是 | 是 | 是 | P0 | canonical 写了，但 live path 仍旧链路主导 |
| planning_subgraph | PARTIAL / RISKY | 部分 | 是 | 是 | 是 | P0 | canonical 未成为事实源 |
| deterministic_tool_workflow | PARTIAL | 是 | 是 | 是 | 是 | P1 | canonical 优先，但仍有 legacy fallback |
| session_write / state_update_planner | PARTIAL | 间接 | 是 | 是 | 是 | P1 | 写回边界收紧，但兼容字段仍多源 |
| single_shop_multifacet | FAIL | 间接 | 是 | 是 | 是 | P0 | 明确 query 仍澄清掉 |
| single_coupon_flow | FAIL | 间接 | 是 | 是 | 是 | P0 | 明确 coupon 链路仍不稳 |
| coupon / queue / parking / distance / open_status | PARTIAL | 是 | 是 | 是 | 是 | P1 | facet 共享 shop_id 基本成立，但前置解析仍会失败 |
| recommendation_flow | PARTIAL | 否 | 间接 | 否 | 是 | P1 | ranking_snapshot 正常，实体层耦合仍在 |
| comparison_flow | PARTIAL / RISKY | 是 | 是 | 是 | 部分 | P0 | comparison 仍会被误澄清 |
| evidence_builder | FULL | 否 | 否 | 否 | 否 | P2 | evidence 来源正确 |
| answer_plan_builder | FULL | 否 | 否 | 否 | 否 | P2 | 只消费 evidence |
| answer_verify | FULL | 否 | 否 | 否 | 否 | P2 | 能识别缺证据 |
| final_response_build | FULL | 否 | 否 | 否 | 否 | P2 | 纯 DTO 封装 |
| GraphState | FULL | 否 | 是 | 否 | 否 | P2 | 字段契约完整 |
| SessionState | FULL | 否 | 是 | 否 | 是 | P2 | 写回载体可用 |

## 16. P0 / P1 / P2 缺口

### P0

- `planning_subgraph` 的 canonical 分支是死分支，canonical 没有成为 live single-shop 事实源
- 单店明确门店 query 仍会被澄清掉，导致 coupon / distance / multifacet 链路失败
- comparison query 仍可能被误判为缺 slot / clarification，而不是 comparison

### P1

- `shop_resolver` 仍是 facade + adapter + legacy 的混合体
- `candidate_resolver` 仍是旧后端主导
- `facets.py` 仍承担了一部分 target protocol 解释，边界不够薄
- `state_update_planner` 虽然收紧，但仍依赖多源兼容字段

### P2

- `answer_plan_builder` / `evidence_builder` / `verify_answer` / `final_response_build` 协议基本健康
- `GraphState` / `SessionState` 字段契约完整
- recommendation ranking_snapshot 没有伪造迹象

## 17. 最小修复建议

1. 把 `planning_subgraph` 的 live single-shop 路径从 candidate_set review 切到 canonical `ShopResolutionResult`，取消死分支。
2. 让 `status == resolved` 成为单店任务唯一继续条件，`ambiguous / low_confidence / not_found` 只进入澄清或可信 fallback。
3. 收紧 `deterministic_tool_workflow` 的 fallback 层级，避免 canonical 已 resolved 之后还继续走旧解析链。
4. comparison 入口先判 comparison，再判 single-shop；comparison target 不足只澄清对应目标，不污染 `current_shop`。
5. 逐步把 `candidate_resolver` 降级为纯 backend，不再承担事实裁决。
6. `facets.py` 只保留语义角色和 minimal protocol，不继续扩展实体裁决职责。

## 18. 是否允许进入下一阶段

**不允许**

原因：

- canonical shop entity 还没有成为 planning 的唯一事实源
- 关键 query 复现里，单店明确门店、单店多 facet、comparison 仍存在误澄清
- current_shop 写回边界已明显改善，但“统一门店实体边界全链路接入”还未闭环

