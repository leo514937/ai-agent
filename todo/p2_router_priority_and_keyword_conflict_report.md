# P2 Router 决策优先级与 LLM/Rule/Keyword 冲突保护报告

## 1. 结论

PASS with note

## 2. 结论说明

本轮只收口 `planning/orchestration_router.py` 的决策优先级，不改 workflow registry、workflow_runner、graph_builder，也没有新增 workflow / tool。

已验证：

- 硬规则优先于关键词信号
- 单店引用缺少 `current_shop` 或 `last_recommendation_list` 时进入澄清，而不是误进 `deterministic_tool`
- 只有在引用目标可解析时，单店事实查询才进入 `deterministic_tool`
- 比较类 query 在目标数足够时进入 `discovery_decision`
- 比较类 query 在目标数不足时进入 `clarification_fallback`
- 组合推荐类 query 中的 `coupon` / `status` / `price` / `distance` 等关键词只作为 facet signal，不覆盖主路由

## 3. Note

P2 禁止的是 `workflow-level fan-out / multi-workflow merge` 语义，而不是单个 workflow 内部的语义解析、引用消解或关键词信号辅助。

当前实现保持了：

- `keyword` 只是 signal，不是主分类器
- `LLM / semantic frame` 负责 recommendation / comparison / exploration 等主意图
- 单店引用必须回到单个 workflow-owned 目标锚点，不会产生多个 `final_response`
- 不会产生多个 `state_update_plan`
- 没有引入 workflow 级 Map-Reduce

## 4. 本轮修改范围

实际修改文件：

- [`local_life_agent/planning/orchestration_router.py`](D:/javacode/hm-dianping/local_life_agent/planning/orchestration_router.py)
- [`local_life_agent/tests/test_p2_router_priority.py`](D:/javacode/hm-dianping/local_life_agent/tests/test_p2_router_priority.py)
- [`local_life_agent/tests/test_orchestration_router.py`](D:/javacode/hm-dianping/local_life_agent/tests/test_orchestration_router.py)

未修改文件：

- `local_life_agent/engine/workflow_registry.py`
- `local_life_agent/engine/workflow_runner.py`
- `local_life_agent/engine/graph_builder.py`
- `local_life_agent/engine/_routes.py`

## 5. 已锁定行为

- “附近推荐几家有券的餐厅” -> `discovery_decision`
- “附近推荐几家适合约会、现在营业、最好有券、人均100左右的餐厅” -> `discovery_decision`
- “这家有券吗” 且无 `current_shop` -> `clarification_fallback`
- “这家有券吗” 且有 `current_shop` -> `deterministic_tool`
- “第一家有券吗” 且无 `last_recommendation_list` -> `clarification_fallback`
- “第一家有券吗” 且可解析 `last_recommendation_list` -> `deterministic_tool`
- “海底捞和巴奴哪个更适合聚餐” -> `discovery_decision`
- “第一家和第二家哪家更适合带娃” 且目标不足 -> `clarification_fallback`
- `date_plan` / `exploration_planning` 仍保持原优先级

## 6. 关键实现点

- 新增比较类与引用类的优先级判断
- 比较类优先检查语义帧 / 顶层 state 中是否已有足够目标
- 单店引用先做引用消解，再决定是否进入事实型工具路由
- 保留原有探索规划、直接回复和 forbidden 最高优先级逻辑

## 7. 验证

执行命令：

```bash
python -m compileall local_life_agent
pytest local_life_agent/tests/test_orchestration_router.py \
       local_life_agent/tests/test_p1_single_owner_invariants.py \
       local_life_agent/tests/test_p2_router_priority.py -q
```

结果：

- `compileall` 成功
- `pytest` 通过：`30 passed in 34.21s`

## 8. 风险边界

- 未引入 workflow 级 Map-Reduce
- 未改 workflow registry / runner / graph_builder
- 未处理 P3-P14 的 facet / evidence / answer 协议收敛问题
