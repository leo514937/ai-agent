# Phase 6 / 5a-b unknown facet coupon regression fix report

## 结论
PASS

## 当前失败测试真实根因
`local_life_agent/tests/test_single_shop_multifacet.py::test_unrecognized_facet_does_not_default_coupon` 的真实问题，不是 coupon facet 被误识别，而是单店确定性工作流在 `single_shop_query` 场景下把原文本里的“多久”也当成了距离类工具触发词。

具体链路是：
- 语义帧中 `facets=[]`
- `task_type=single_shop_query`
- `primary_task=distance_query`
- `deterministic_tool_workflow._task_to_tool()` 本来已经会在空 facet 的单店场景回落到 `detail`
- 但 `run_deterministic_tool_workflow()` 之后又用 `_route_info_from_raw_text()` 覆盖了分派结果
- 原先 `_route_info_from_raw_text()` 把“多久”映射成 `calculate_distance_km`
- 结果未知 facet 场景没有回落到 `get_shop_detail`，而是被误导到距离工具分支

这和本阶段要求一致：未知 facet 不应默认落到 coupon，也不应被其他隐式兜底强行压成专门工具。

## coupon facet 识别规则修复说明
这次没有扩大 coupon 识别，也没有改 recommendation / comparison / coupon 主链路。

本次收口只做了一个边界收紧：
- 在 `local_life_agent/engine/workflows/deterministic_tool_workflow.py` 中，保留显式 coupon 语义触发
- 对未知 facet 的单店场景，不再让“多久”这种口语时长线索直接压成距离工具
- 空 facet 的 `single_shop_query` 继续回落到 `detail`

## unknown / unsupported facet 处理说明
未知或无法稳定判断的 facet 仍然保持为：
- `detail` 默认单店事实查询
- 或进入澄清 / fallback 路径

不会默认映射到：
- `coupon`
- `distance`
- 其他专门事实工具

这样可以避免“语义帧没给出明确 facet，但工作流却因为原文里某个泛化词过度分派”的问题。

## comparison follow-up coupon 是否保持通过
保持通过。

验证结果：
- `python -m pytest local_life_agent/tests/test_comparison_flow.py::test_after_comparison_second_item_reference_still_works -q`
- `python -m pytest local_life_agent/tests/test_comparison_flow.py -q`

这次改动没有触碰 comparison 目标解析或 coupon follow-up 的引用路径。

## recommendation follow-up coupon 是否保持通过
保持通过。

验证结果：
- `python -m pytest local_life_agent/tests/test_recommendation_flow.py -q`

## 第一层不承担实体解析权威的证明
本次修复没有把实体解析迁回第一层，也没有改 `context_recovery` / `reference_resolver` 的权威边界。

本次只在第二层单店确定性工作流中收紧了工具分派规则：
- 语义帧无明确 facet 时，不再由原文“多久”直接触发距离工具
- 单店空 facet 仍保持 `detail` 兜底

这说明问题是工作流路由兜底，而不是第一层引用解析。

## 实际修改文件清单
- `local_life_agent/engine/workflows/deterministic_tool_workflow.py`
- `todo/three_layer_phase6_5a_b_unknown_facet_coupon_regression_fix_report.md`

## 明确没有做的 5a-c 内容
未做：
- 5a-c `planning_subgraph` 收缩
- `GoalPlanner / TargetResolver / EvidencePlanner / PlanValidator` 拆分
- 第一层实体解析权威回迁
- Redis SessionStore
- ResponseContract V2
- complex_orchestrator / MapReduce

## 测试结果
已通过：
- `python -m pytest local_life_agent/tests/test_single_shop_multifacet.py::test_unrecognized_facet_does_not_default_coupon -q`
- `python -m pytest local_life_agent/tests/test_single_shop_multifacet.py -q`
- `python -m pytest local_life_agent/tests/test_comparison_flow.py::test_after_comparison_second_item_reference_still_works -q`
- `python -m pytest local_life_agent/tests/test_comparison_flow.py -q`
- `python -m pytest local_life_agent/tests/test_recommendation_flow.py -q`
- `python -m pytest local_life_agent/tests/test_single_coupon_flow.py -q`
- `python -m pytest local_life_agent/tests/test_e2e_llm_main_path.py -q`
- `python -m pytest local_life_agent/tests/test_phase3_completion_contracts.py -q`
- `python -m compileall local_life_agent`

## 是否建议进入 5a-c
建议可以继续进入 5a-c。
当前剩余这个阻塞已经收口，推荐 / comparison / coupon / e2e / 阶段合同都已回归通过。
