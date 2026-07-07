# Phase 6 / 5a-b comparison follow-up coupon fix report

## 结论

PARTIAL PASS

本次只修复了 `local_life_agent/tests/test_comparison_flow.py::test_after_comparison_second_item_reference_still_works` 的比较后续二次引用 coupon 路由问题，已恢复 `get_coupon_list` 触发。

但在收口验证时，`local_life_agent/tests/test_single_shop_multifacet.py::test_unrecognized_facet_does_not_default_coupon` 仍然失败，因此本次不能写成全绿 PASS。

## 当前失败测试的真实根因

原始失败点不是 comparison_result 写回，而是比较后续第三轮 `"第二家有券吗"` 被路由提前短路：

1. `active_turn_resolver` 识别到 ordinal reference，输出了 `pending_restored`。
2. `intake_guard_router` 把 `pending_restored` 直接当成 clarification reply 处理，导致请求没有进入 `planning_subgraph`。
3. 结果是后续只走了回复兜底，没有进入真正的单店 coupon 规划与工具调用。

本次修复后：

1. `intake_guard_router` 只在真实存在 `pending_clarification` 时才把 `pending_restored` 短路到 clarification reply。
2. `planning_subgraph` 在存在 comparison context 时，会把 `"第二家有券吗"` 这类二次引用保留为单店券事实诉求，避免 facet 在转换层被丢掉。
3. 该链路已恢复 `get_coupon_list`。

## comparison_result 字段形态说明

`comparison_result` 继续作为比较后的上下文写回，承载 comparison targets 及其排序信息。

本次不改变其主结构，只是让后续二次引用优先读取 comparison context，而不是误落到 clarification-only 分支。

## “第二家”引用解析路径说明

当前路径是：

1. `active_turn_resolver` 识别 ordinal reference。
2. `intake_guard_router` 不再无条件短路。
3. `planning_subgraph` 读取 comparison context。
4. comparison follow-up 的单店目标进入 evidence planning。
5. `coupon` facet 被保留并触发 `get_coupon_list`。

这条链路没有回退到第一层实体解析权威，实体解析仍然在第二层继续处理。

## coupon intent / facet 保留路径说明

保留策略是：

1. 比较后上下文优先于 `last_recommendation_list` 和 `current_shop`。
2. 单店后续中的 `有券 / 优惠券 / coupon / 团购 / 套餐` 继续作为事实诉求。
3. 不把 `"第二家有券吗"` 误降级成普通 detail-only 查询。

## 为什么之前会落到错误单店详情 / 空工具路径

之前有两类问题叠加：

1. 路由层把 `pending_restored` 误当成 clarification reply，提前跳过 planning。
2. 在比较后续的单店目标里，facet 信息在转换链路里不够稳，导致后续没有进入 coupon 工具。

本次已经修掉第 1 条，并把比较上下文下的 facet 保留收紧到 `planning_subgraph`。

## 修复后是否触发 `get_coupon_list`

是。

`test_after_comparison_second_item_reference_still_works` 已恢复通过。

## recommendation follow-up 是否保持通过

是。

`local_life_agent/tests/test_recommendation_flow.py` 全绿。

## 第一层不再承担实体解析权威的证明

本次改动没有把实体解析权威拉回第一层：

1. 第一层仍然只做 active turn / reference 信号识别。
2. 第二层仍然负责 comparison context 到真实目标的解析。
3. 路由修复只是避免把有上下文的后续请求过早截断。

## 与统一 final_response / ResponseContractV1 的衔接

本次没有改统一出口协议。

comparison follow-up 仍然沿用现有 response 层与 `ResponseContractV1` 的出口语义，只是前面的规划链路恢复了 `get_coupon_list` 的证据输入。

## 实际修改文件清单

本次收口实际触及的文件：

1. `[local_life_agent/engine/subgraphs/intake_guard_router.py](/D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/intake_guard_router.py)`
2. `[local_life_agent/engine/subgraphs/planning_subgraph.py](/D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/planning_subgraph.py)`
3. `[local_life_agent/domain/facets.py](/D:/javacode/hm-dianping/local_life_agent/domain/facets.py)`
4. `[local_life_agent/engine/workflows/deterministic_tool_workflow.py](/D:/javacode/hm-dianping/local_life_agent/engine/workflows/deterministic_tool_workflow.py)`
5. `[local_life_agent/planning/goal/goal_draft.py](/D:/javacode/hm-dianping/local_life_agent/planning/goal/goal_draft.py)`
6. `[local_life_agent/domain/goal.py](/D:/javacode/hm-dianping/local_life_agent/domain/goal.py)`

其中，真正保留在最终方案里的关键修复点是 `intake_guard_router.py` 与 `planning_subgraph.py`。

## 明确没有做的 5a-c 内容

本次没有进入 5a-c，也没有做以下内容：

1. `target_resolve` 权威全面迁移到第二层的收口重构。
2. `planning_subgraph` 的服务化拆分。
3. `GoalPlanner / TargetResolver / EvidencePlanner / PlanValidator` 的正式拆分收敛。
4. `ResponseContract V2`。
5. `ContextualizedTurn / FocusContext` 的新一轮扩展。
6. `RedisSessionStore`。
7. `complex_orchestrator / MapReduce`。

## 测试结果

已通过：

1. `python -m pytest local_life_agent/tests/test_comparison_flow.py::test_after_comparison_second_item_reference_still_works -q`
2. `python -m pytest local_life_agent/tests/test_comparison_flow.py -q`
3. `python -m pytest local_life_agent/tests/test_recommendation_flow.py -q`
4. `python -m pytest local_life_agent/tests/test_e2e_llm_main_path.py -q`
5. `python -m pytest local_life_agent/tests/test_single_coupon_flow.py -q`
6. `python -m pytest local_life_agent/tests/test_phase3_completion_contracts.py -q`
7. `python -m compileall local_life_agent`

仍失败：

1. `python -m pytest local_life_agent/tests/test_single_shop_multifacet.py::test_unrecognized_facet_does_not_default_coupon -q`

## 是否建议进入 5a-c

暂不建议。

原因：

1. 当前 comparison follow-up 已修好，但单店多维测试仍有独立回归。
2. 5a-c 会扩大 `planning_subgraph` 收缩面，不适合在当前未收口前继续推进。

