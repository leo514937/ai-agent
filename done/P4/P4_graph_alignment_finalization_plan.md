# P4 图编排最终对齐计划

源文档：

- [../arc_core.md](../arc_core.md)
- [../arc_detail.md](../arc_detail.md)

预计工期：3 天

## 目标

在完成 P3 之后，把当前已经具备的本地生活能力，最终收口到 `arc_core.md` / `arc_detail.md` 描述的显式图编排结构中。

这一阶段不再新增平行能力链路，也不再继续堆叠新的业务修补逻辑，只做最后一次结构对齐：

- 把已经存在的能力节点显式化
- 把主图、标准路径、复杂路径、收口节点的职责边界彻底钉死
- 把“功能存在但节点不透明”的部分，改成“节点可见、流向可追、行为可测”
- 把当前 helper / phase / adapter 里的能力，迁移为图上可观测的节点语义

## 当前实现基线

P4 不是从零开始，而是把现有能力拆得更透明：

- `check_request_legality`、`route_top_level_intent`、`resolve_target_merchant` 已经提供了前置理解和路由能力
- `compose_answer`、`phase7_compose` 已经覆盖了合同构建、来源构建、审查报告等收口能力
- `plan_execute.py` 已经具备复杂路径的规划、执行、重规划和复核能力
- `stages_front_*`、`graphs.py`、`subgraphs.py` 已经有了标准路径和工具/RAG/推荐链路的能力底座

P4 要做的不是继续补新能力，而是把这些能力拆成 arc 目标里能直接看到的节点。

## 必须补全的缺口

以下缺口在 P4 中必须补完，否则不算完成：

- 前端链路必须补齐到 `request_legality -> illegal_request_response`、`query_safety -> safety_reject_response`、`query_merge_for_local_life -> merged_query_safety`
- `understand_turn` 之后的 `top_level_intent_router` 必须显式落图，并把 `identity_answer`、`capability_answer`、`direct_chat_answer`、`out_of_scope_response` 作为可追踪分支输出
- 主图必须从 `route_gate / plan_execute_subgraph / compose_answer` 的黑盒编排，收敛为 `arc_core.md` 要求的显式主链
- 标准路径必须从 helper 语义提升为显式节点链，不能继续依赖 `compose_answer` 内部分支
- 复杂路径必须从 `plan_execute.py` 的单体流程，提升为显式的 `planner_node -> plan_validator -> plan_executor -> execute_plan_step -> collect_step_result -> complex_review`
- 最终出口必须把安全、兜底、响应构建、持久化、发射拆开，不允许再折叠成一个收口大方法
- 兼容别名和旧路径只能作为短期过渡存在，不能作为长期实现

## 能力到节点的映射原则

- `check_request_legality`、`check_hard_guard`、`route_top_level_intent` 只负责前置理解和合法性判断
- `request_legality`、`query_safety`、`query_merge_for_local_life`、`top_level_intent_router` 是前端主链上的显式节点语义，必须能在图上看到
- `illegal_request_response`、`safety_reject_response`、`identity_answer`、`capability_answer`、`direct_chat_answer`、`out_of_scope_response` 不是附属注释，而是明确分支出口
- `resolve_target_merchant`、`merge_local_life_query_context` 只负责目标和上下文解析
- `_build_answer_contract`、`_build_source_contract`、`_build_review_report` 只负责合同/来源/审查对象构建
- `plan_planner`、`plan_validator`、`step_executor`、`progress_checker`、`plan_reviewer` 只负责复杂路径的实现细节
- `lint_answer`、`validate_answer_against_contract`、`audit_final_answer`、`build_response_bundle` 只负责最终回答的质量与收口辅助
- 这些 helper 都可以保留，但不能再替代图节点本身

## P4 结束时的目标拓扑

P4 结束时，当前实现需要尽量贴近 `arc_core.md` / `arc_detail.md` 的下面这条主线：

- `load_context`
- `request_legality`
- `illegal_request_response`
- `hard_guard`
- `clarification_or_reject`
- `query_safety`
- `safety_reject_response`
- `query_merge_for_local_life`
- `merged_query_safety`
- `understand_turn`
- `top_level_intent_router`
- `identity_answer`
- `capability_answer`
- `direct_chat_answer`
- `out_of_scope_response`
- `resolve_target_shop`
- `build_answer_contract`
- `build_source_contract`
- `complexity_router`
- `rule_review`
- `select_required_sources`
- `merge_or_rank`
- `contract_review`
- `planner_node`
- `plan_validator`
- `plan_executor`
- `execute_plan_step`
- `collect_step_result`
- `complex_review`
- `final_answer_safety`
- `final_safety_fallback`
- `response_builder`
- `persist_session`
- `emit_final`

其中：

- 前端链路必须可见地经过 `request_legality -> illegal_request_response`、`query_safety -> safety_reject_response`、`query_merge_for_local_life -> merged_query_safety`、`top_level_intent_router -> identity_answer/capability_answer/direct_chat_answer/out_of_scope_response`
- 标准路径必须可见地经过 `rule_review -> select_required_sources -> rag_executor/tool_executor/recommendation_executor -> merge_or_rank -> contract_review`
- 复杂路径必须可见地经过 `planner_node -> plan_validator -> plan_executor -> execute_plan_step -> collect_step_result -> complex_review`
- 最终出口必须可见地经过 `final_answer_safety -> final_safety_fallback / response_builder -> persist_session -> emit_final`

## 核心原则

- 不要再保留“能力存在但只藏在 helper 里”的双轨实现
- 不要让 `route_gate`、`compose_answer`、`plan_execute_subgraph` 继续承担编排之外的职责
- 不要为了兼容旧路径而长期保留两套并行语义
- 不要在 P4 再引入新的大能力面，P4 只做最终结构对齐
- 不要把标准路径和复杂路径再混回一条黑盒执行链

## 分天文档

1. [day1_standard_path_node_alignment.md](./day1_standard_path_node_alignment.md)
2. [day2_complex_path_node_alignment.md](./day2_complex_path_node_alignment.md)
3. [day3_exit_and_cleanup.md](./day3_exit_and_cleanup.md)

## 统一验收

- `arc_detail.md` 中的关键节点在代码中都能找到明确、可追踪的对应位置
- `arc_core.md` 前端链路的节点也必须在代码中找到明确、可追踪的对应位置
- 标准路径、复杂路径、收口路径的边界清晰，不再混在大节点里
- 图拓扑导出与黄金集回归可以稳定验证最终结构
- 兼容层只保留必要过渡，不再长期依赖旧别名
- `builder.py` 的主图节点清单必须和 `arc_core.md` 的主链一致
- 如果任一显式节点仍然只存在于 helper 或测试里，P4 不能算完成
- 如果 `compose_answer`、`route_gate`、`plan_execute_subgraph` 仍承担编排职责，P4 不能算完成
