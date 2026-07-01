# Phase E GraphState / Trace 字段契约报告

## 目标

Phase E 收敛 GraphState / debug / trace 对工具结果主字段的消费顺序：

* `tool_results` 为主字段
* `tool_result_set` 只保兼容兜底

## 实际改动

* `local_life_agent/observability/trace.py`
  * `_infer_tool_backend()` 读取结果集合时改为优先 `tool_results`
  * `_infer_tool_call_count()` 改为优先 `tool_results`
* `local_life_agent/engine/_compat.py`
  * `_trace_output_summary()` 中 `tool_result_count` 改为优先 `tool_results`
* `local_life_agent/tests/test_phase_e_state_contracts.py`
  * 增加回归测试，确认主字段与兼容字段同时存在时，统计逻辑优先使用 `tool_results`

## 验证结果

### Python

* `pytest local_life_agent/tests/test_phase_e_state_contracts.py local_life_agent/tests/test_trace_observability.py -q`
  * 通过，`8 passed`
* `python -m compileall local_life_agent`
  * 通过

## 结论

Phase E 已完成：

* state/debug/trace 的主读取位已切到 `tool_results`
* `tool_result_set` 仍保兼容，但不再抢主优先级

## 留给后续阶段

* 全局 camelCase / compat 字段残留扫尾
* 更大范围回归、Java live / agent E2E、最终验收报告
