# Phase C Evidence / Answer 字段契约报告

## 目标

Phase C 只收敛 Evidence / Review / Answer 间的字段契约：

* EvidenceItem 补齐正式来源字段
* `field_path` 与当前 payload 形状保持一致
* Answer 只从 `EvidencePack.tool_results` 读取运行结果，不回退兼容字段

## 实际改动

### Evidence

* `local_life_agent/planning/evidence/evidence_builder.py`
  * 在单店与推荐链路生成的 `evidence_items / unknown_items` 中补齐 `backend_source`
  * 继续保持 coupon 列表证据路径为 `data[0].title` 这类列表路径

### Answer

* 代码层未改动 `answer/generator.py`
  * 审计确认 `_get_tool_results_from_evidence()` 只读取 `tool_results`
  * 不会从 `tool_result_set` 偷回退

### 测试

* `local_life_agent/tests/test_phase_c_evidence_contracts.py`
  * 断言 `build_evidence()` 产出的 `EvidenceItem.backend_source` 正确传递
  * 断言 coupon 证据 `field_path == data[0].title`
  * 断言 answer generator 只接受 `tool_results`

## 验证结果

### Python

* `pytest local_life_agent/tests/test_phase_c_evidence_contracts.py local_life_agent/tests/test_evidence_review.py -q`
  * 通过，`21 passed`
* `python -m compileall local_life_agent`
  * 通过

## 结论

Phase C 已完成：

* EvidenceItem 来源字段已补齐
* 证据路径与当前列表/对象 payload 形状一致
* Answer 层对 runtime 结果的正式入口维持为 `EvidencePack.tool_results`

## 留给后续阶段

* `tool_result_set` 在 GraphState / debug / trace 的兼容收敛
* Decision / ranking / candidate 契约进一步统一
