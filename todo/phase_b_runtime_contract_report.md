# Phase B runtime 字段契约报告

## 目标

Phase B 聚焦 ToolResult runtime 主契约，不处理 Evidence / Decision / State：

* 补齐 canonical ToolResult 正式字段
* 明确 `retriable` 行为
* 保留 `source / tool_backend` 兼容输出，不提前删字段
* 增加最小 runtime contract tests

## 实际改动

### runtime 产物

* `local_life_agent/tools/normalizer.py`
  * canonical 结果新增 `retriable`
  * 增加 `_infer_retriable()`：
    * `NETWORK_ERROR / unknown / timeout` 一类默认可重试
    * `SCHEMA_VALIDATION_FAILED / TOOL_NOT_REGISTERED / TOOL_UNSUPPORTED / INVALID_ARGUMENT / SHOP_NOT_FOUND` 一类默认不可重试
    * success 结果默认不可重试
* `local_life_agent/tools/gateway.py`
  * Gateway 异常路径补充 `retriable`
  * `_run_tool()` 输出统一带 `retriable`
  * Batch timeout / batch exception payload 也补充 `retriable`

### 测试

* `local_life_agent/tests/test_phase_b_runtime_contracts.py`
  * `normalize_tool_result()` 对 retryable failure 输出 `retriable=True`
  * `normalize_validation_error()` 输出 `retriable=False`
  * success 输出 `retriable=False`
  * Gateway 返回 payload 包含完整 runtime 主字段

## 验证结果

### Python

* `pytest local_life_agent/tests/test_phase_b_runtime_contracts.py local_life_agent/tests/test_tool_gateway.py -q`
  * 通过，`26 passed, 2 skipped`
* `python -m compileall local_life_agent`
  * 通过

## 结论

Phase B 已完成：

* ToolResult runtime 主契约已补齐 `retriable`
* 可重试/不可重试边界已被最小测试固定
* 兼容字段仍保留，未提前做破坏性收缩

## 留给后续阶段

* `tool_result_set -> tool_results` 的全链路主字段收敛
* Evidence / Answer 对 runtime 契约的读取统一
* `source / tool_backend` 兼容字段的实际下线时机
