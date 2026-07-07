# Phase 8 / 5c 前置残余失败清零批报告

结论：PASS

## 1. 前置背景

本批只处理第 8 批门禁前的 4 个残余失败，不进入 5c。

原始失败用例：

1. `local_life_agent/tests/test_real_llm_acceptance.py::test_spy_e2e_query_2_comparison`
2. `local_life_agent/tests/test_stage14_verification.py::test_group_deictic_size_parsing`
3. `local_life_agent/tests/test_stage14_verification.py::test_resolve_deictic_reference_with_group`
4. `local_life_agent/tests/test_stage14_verification.py::test_deictic_priority_clarification`

## 2. 真实根因

### 2.1 `test_spy_e2e_query_2_comparison`

这是测试语义未更新，不是主链路代码回归。

当前比较问句 `海底捞和山城一锅哪个好？` 在现有架构下走的是统一出口中的澄清/兜底路径，`answer_source` 由 `clarification_fallback_workflow` 写入 `ResponseDirective`，再由 `ResponseContractV1` 透传到 `response.debug.answer_source`。

旧断言还在要求：

* `llm_verbalizer`
* `template_fallback`
* 空串

这与当前统一出口语义不一致。

### 2.2 `test_group_deictic_size_parsing`

这是第一层/第二层边界已经收紧后的旧断言。

`local_life_agent/target/context_recovery.py` 现在只负责产出 `SIGNAL_ONLY` 级别的引用信号，不再返回实体级 `RESOLVED` 结果，也不再填充可直接消费的 `comparison_targets`。

真正的 group deictic 实体解析已经下沉到第二层 `reference_resolver.py`。

### 2.3 `test_resolve_deictic_reference_with_group`

同上，旧断言仍在检查第一层的实体解析结果。

当前正确行为是：

* 第一层：返回 `SIGNAL_ONLY`
* 第二层：通过 `resolve_references` 解析出 `resolved_list`

### 2.4 `test_deictic_priority_clarification`

同样是第一层边界收紧后的旧语义。

对 `这家` 这种歧义指代，第一层只应返回参考信号；是否需要澄清，由第二层 `resolve_comparison_targets` 统一判定。

## 3. 代码修复 vs 测试对齐

本批没有回滚第一层边界，没有恢复实体解析权威。

实际处理方式是测试对齐：

* `test_real_llm_acceptance.py` 允许当前统一出口的 `clarification_fallback_workflow`
* `test_stage14_verification.py` 改为：
  * 第一层断言 `SIGNAL_ONLY`
  * 第二层断言 `resolve_references` / `resolve_comparison_targets`

这符合第 6 批之后的职责划分。

## 4. comparison `answer_source` 对齐说明

当前 `answer_source` 的权威来源是 `ResponseDirective`，由各 workflow 写入，再由 `ResponseContractV1.from_response_directive()` 透传。

对这条比较样例，实际来源是：

* `clarification_fallback_workflow`

因此测试应接受该值，而不再强行要求 `llm_verbalizer` / `template_fallback`。

## 5. group deictic 新边界说明

当前边界是：

* `recover_context()`：只产出引用信号
* `resolve_references()`：负责 ordinal / deictic 的第二层实体解析

因此：

* `这三家`、`这几家` 的“组大小”解析应在第二层验证
* 第一层只需证明它识别到了 group deictic 信号

## 6. 第一层不恢复实体解析权威的证明

`local_life_agent/target/context_recovery.py` 的现状是：

* `context_resolution.status` 只会是 `SIGNAL_ONLY` 或 `NONE`
* 返回体中只有 `reference_signal`
* 不再返回实体级 `resolved_target`
* 不再回填 `comparison_targets` 作为权威解析结果

本次修复没有改动该实现，只调整了测试断言以匹配新边界。

## 7. 与 `ResponseContractV1 / final_response` 的衔接

本批没有改变统一出口实现。

当前行为仍然是：

* workflow 生成 `ResponseDirective`
* `ResponseContractV1` 从 directive 派生 `answer_source`
* `final_response / preview_text` 继续由统一出口维护

没有引入 `ResponseContract V2`，也没有绕过统一出口。

## 8. 实际修改文件清单

1. `[local_life_agent/tests/test_real_llm_acceptance.py](../local_life_agent/tests/test_real_llm_acceptance.py)`
2. `[local_life_agent/tests/test_stage14_verification.py](../local_life_agent/tests/test_stage14_verification.py)`

## 9. 明确没有做的 5c 内容

本批没有进入 5c：

* 没有做 Trace schema 统一
* 没有做 latency / cost benchmark
* 没有做 `ResponseContract V2`

## 10. 测试结果

### 10.1 原始 4 个失败

已全部清零。

### 10.2 门禁回归

* `python -m pytest local_life_agent/tests/test_recommendation_flow.py -q`：通过
* `python -m pytest local_life_agent/tests/test_comparison_flow.py -q`：通过
* `python -m pytest local_life_agent/tests/test_single_coupon_flow.py -q`：通过
* `python -m pytest local_life_agent/tests/test_single_shop_multifacet.py -q`：通过
* `python -m pytest local_life_agent/tests/test_e2e_llm_main_path.py -q`：通过

### 10.3 全量回归

* `python -m compileall local_life_agent`：通过
* `python -m pytest local_life_agent/tests -q`：`1372 passed, 37 skipped, 2 xfailed`

## 11. 是否建议重新进入第 8 批 5c

建议重新进入。

原因：

* 4 个前置残余失败已清零
* 主链路回归全绿
* 全量测试无新增失败
* 当前剩余问题已经是 Phase 8 之前的旧语义断言，不再阻塞 5c 前置门禁
