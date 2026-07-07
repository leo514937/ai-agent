# 第 9 批 6c：ClaimVerifier L2 / L3 报告

## 结论

PASS。

本批已在不重写 L1 ClaimVerifier、不引入平行 verifier 模块、不增加普通单店路径 LLM 调用成本的前提下，补齐：

- L2：deterministic composer 输出文本的 claim span 回填。
- L3：LLM verbalizer 同次返回的 structured claims 校验接入。
- RewriteInstruction：unsupported structured claim 可进入 rewrite instruction。
- ResponseContract V2：优先承载 verifier claim results，再兼容 evidence 原始 claims。

## 前置门禁验收结果

- 第 8 批 5c：已存在 `todo/three_layer_phase8_trace_eval_response_contract_v2_report.md`，报告结论为 PASS。
- 第 9 批 6a / 6b：已存在 `todo/three_layer_phase9_6a_6b_complex_orchestrator_mapreduce_report.md`，报告结论为 PASS。
- 门禁全量测试：执行前已跑 `python -m pytest local_life_agent/tests -q`，结果为 `1391 passed, 37 skipped, 2 xfailed`。
- L1 ClaimVerifier：现有 `test_answer_verifier.py`、`test_phase4b_claim_l1_and_workflow_split.py` 仍通过。

## ClaimVerifier L2 说明

修改位置：

- `local_life_agent/answer/verifier.py`

实现方式：

- 复用现有 `_extract_expected_claims(...)` 生成的 expected claims。
- 在 `_claim_l1_report(...)` 中对每条 claim result 追加文本 span 字段：
  - `span_text`
  - `span_start`
  - `span_end`
  - `span_confidence`
  - `claim_span_level`
- 支持从 `text`、`claim_text`、`shop_name`、`value`、`facet` 等现有字段定位文本 span。
- 能定位时标记 `span_confidence=high`。
- 不能可靠定位时标记 `span_confidence=low`，且 `span_start=-1`，不强行通过或失败。

边界：

- L2 只增强 claim 定位能力。
- 不改变 L1 的事实判定。
- 不重写 deterministic composer 文案。
- 不因为 span 低置信度改变业务 pass / fail。

## ClaimVerifier L3 说明

修改位置：

- `local_life_agent/answer/llm_verbalizer.py`
- `local_life_agent/answer/verifier.py`
- `local_life_agent/engine/subgraphs/response_subgraph.py`

实现方式：

- `VerbalizerResponse` 增加 `structured_claims` 字段。
- verbalizer 只透传同一次 LLM verbalizer 输出里的 structured claims 到 `metadata_out["llm_structured_claims"]`。
- 不额外发起 LLM claim extraction 调用，因此不增加普通单店路径成本。
- `_h_answer_generate` 将 `llm_structured_claims` 写入 graph state。
- `_h_answer_verify` 调用 verifier 时传入 `answer_source` 与 `llm_structured_claims`。
- verifier 将 L3 structured claims 与 L1 expected claims 对齐校验。
- LLM structured claims 只作为文本 claim 抽取结果，不作为事实来源。

边界：

- EvidencePack / DecisionPlan / comparison_matrix / ranking 仍是事实权威。
- LLM 不负责判定 claim 真假。
- L3 unsupported structured claim 会导致 verify fail，并进入 rewrite。

## 与 RewriteInstruction 的衔接

修改后：

- `unsupported_structured_claim` 会写入 verifier `issues`。
- 未被 expected claims 支持的 structured claim 文本会写入 `unsupported_claims`。
- `RewriteInstruction.from_verifier_report(...)` 继续消费 `unsupported_claims`。
- rewrite loop 不绕过现有 `_h_rewrite` / fallback 路径。

覆盖测试：

- `test_unsupported_l3_claim_enters_rewrite_instruction`

## 与 ResponseContract V2 的衔接

修改位置：

- `local_life_agent/engine/subgraphs/response_subgraph.py`

实现方式：

- `_h_answer_verify` 输出：
  - `answer_claim_results`
  - `answer_expected_claims`
  - `answer_claim_extractor`
- `_build_response_contract_v2(...)` 优先使用 `state["answer_claim_results"]` 作为 V2 `claims`。
- 若 verifier claim results 不存在，则回退到 `evidence_pack["claims"]`，保持兼容。

覆盖测试：

- `test_final_response_v2_prefers_verifier_claim_results`

## 实际修改文件清单

- `local_life_agent/answer/verifier.py`
- `local_life_agent/answer/llm_verbalizer.py`
- `local_life_agent/engine/subgraphs/response_subgraph.py`
- `local_life_agent/tests/test_phase4b_claim_l1_and_workflow_split.py`
- `local_life_agent/tests/test_llm_verbalizer.py`
- `local_life_agent/tests/test_third_layer_response_contract.py`

## 明确没有做的内容

- 没有做 ClaimVerifier L4。
- 没有让 LLM claim extraction 取代 EvidencePack / DecisionPlan 验证。
- 没有重写 composer / verbalizer。
- 没有绕过 RewriteInstruction。
- 没有绕过 ResponseContract V2。
- 没有改 recommendation / comparison / single_shop 主决策逻辑。

## 测试结果

聚焦红绿测试：

- `python -m pytest local_life_agent/tests/test_phase4b_claim_l1_and_workflow_split.py::test_claim_l2_backfills_composer_text_spans local_life_agent/tests/test_phase4b_claim_l1_and_workflow_split.py::test_claim_l2_uncertain_span_is_low_confidence local_life_agent/tests/test_phase4b_claim_l1_and_workflow_split.py::test_claim_l3_llm_structured_claims_do_not_override_evidence local_life_agent/tests/test_phase4b_claim_l1_and_workflow_split.py::test_unsupported_l3_claim_enters_rewrite_instruction local_life_agent/tests/test_third_layer_response_contract.py::test_final_response_v2_prefers_verifier_claim_results local_life_agent/tests/test_llm_verbalizer.py::test_verbalizer_preserves_structured_claim_metadata -q`
- 结果：`6 passed`

第三层相关回归：

- `python -m pytest local_life_agent/tests/test_phase4b_claim_l1_and_workflow_split.py local_life_agent/tests/test_answer_verifier.py local_life_agent/tests/test_llm_verbalizer.py local_life_agent/tests/test_third_layer_response_contract.py -q`
- 结果：`49 passed`

Trace / benchmark / 6a-6b 兼容回归：

- `python -m pytest local_life_agent/tests/test_first_layer_trace.py local_life_agent/tests/test_second_layer_trace_contract.py local_life_agent/tests/test_third_layer_trace_contract.py local_life_agent/tests/test_second_layer_latency_budget.py local_life_agent/tests/test_second_layer_cost_benchmark.py local_life_agent/tests/test_second_layer_complex_orchestrator.py local_life_agent/tests/test_second_layer_map_reduce_reducer.py local_life_agent/tests/test_second_layer_conflict_resolver.py local_life_agent/tests/test_second_layer_worker_state_isolation.py -q`
- 结果：`14 passed`

## 是否进入 6d

建议进入 6d。6c 聚焦测试、第三层回归、trace / benchmark / complex_orchestrator 兼容测试均已通过。
