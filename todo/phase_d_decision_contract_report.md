# Phase D Decision / Ranking 字段契约报告

## 目标

Phase D 收敛 Decision / ranking 主字段优先级：

* ranking 主字段固定为 `ranking_snapshot.ranked`
* `ranked_shops` 仅作为兼容兜底
* 不在本阶段删除兼容字段写出，只先统一 reader 优先级

## 实际改动

* `local_life_agent/planning/decision/decision_planner.py`
  * `_extract_ranking()` 改为显式优先读取 `ranked`
  * 只有在 `ranked` 缺失或为空时，才回退 `ranked_shops / shops`
* `local_life_agent/tests/test_phase_d_decision_contracts.py`
  * 增加回归测试，确认主字段与兼容字段同时存在时，DecisionPlanner 选择 `ranked`

## 验证结果

### Python

* `pytest local_life_agent/tests/test_phase_d_decision_contracts.py local_life_agent/tests/test_decision_planner.py -q`
  * 通过，`24 passed`
* `python -m compileall local_life_agent`
  * 通过

## 结论

Phase D 已完成：

* ranking 主语义已明确为 `ranked`
* 兼容字段仍保留，但不再与主字段竞争优先级

## 留给后续阶段

* GraphState / debug / trace 对 `tool_results` 与 `tool_result_set` 的主次收敛
* 最终阶段再评估是否可以删除 `ranked_shops` 等兼容写出
