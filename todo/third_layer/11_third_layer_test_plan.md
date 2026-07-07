# 第三层测试计划

本文件只列测试覆盖和验收标准，不编造现有测试文件内容。

## 1. 现有可复用测试

当前仓库里已经有下面这些相关测试，可以优先复用：

- `local_life_agent/tests/test_answer_verifier.py`
- `local_life_agent/tests/test_llm_verbalizer.py`
- `local_life_agent/tests/test_p4_evidence_decision_answer_protocol.py`
- `local_life_agent/tests/test_p10_experience_performance.py`
- `local_life_agent/tests/test_phase7_workflows.py`
- `local_life_agent/tests/test_e2e_llm_main_path.py`

## 2. 建议新增测试

- `TODO_ADD_TEST: local_life_agent/tests/test_third_layer_response_contract.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_third_layer_claim_extractor.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_third_layer_claim_verifier.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_third_layer_rewrite_instruction.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_third_layer_fallback_policy.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_third_layer_workflow_boundary.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_third_layer_trace_contract.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_third_layer_latency_budget.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_third_layer_preview_policy.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_third_layer_unified_final_response.py`

## 3. 必覆盖 case

### 1. `response_mode` 分支正确

- direct / reject / clarify / fallback / answer / exploration_plan 的分支行为正确

### 2. `generate_answer()` 主要走 LLM verbalizer

- LLM 开启时调用 verbalizer
- LLM 不可用时走 deterministic fallback

### 3. `verify_answer()` 在 evidence 为空或 draft 为空时不会误判复杂场景

- 空回答、空证据路径要有明确策略

### 4. `ClaimExtractor` 能抽取单店 / 推荐 / 对比 / 探索 claims

### 5. `ClaimVerifier` 能区分 supported / unsupported / contradicted / unknown

### 6. `RewriteInstruction` 能生成结构化重写指令

### 7. fallback 能覆盖推荐 / 对比 / 探索

### 8. `direct_response_workflow` 不会误走回答重型链路

### 9. `deterministic_tool_workflow` / `exploration_planning_workflow` 不再绕过统一 ResponseContract

### 10. `final_response`、`preview_text`、`answer_text` 一致可解释

### 11. 第三层 trace 能解释生成、校验、重写、降级的耗时和原因

### 12. 第三层不写 SessionState

## 4. P0 测试优先级

以下 6 个测试必须在最短迭代内先通过，确保系统不炸。

| P0 # | 测试名 | 验证点 | 违反后果 | 对应 Phase |
|---|---|---|---|---|
| 1 | `test_final_response_unified_exit` | `final_response` 只有 `_h_final_response` 一个写入位置 | 部分回答绕过统一直出管线 | Phase H |
| 2 | `test_response_mode_enum_covers_all_strings` | `ResponseMode` Enum 覆盖全部旧字符串值 | 路由可能中断 | Phase C |
| 3 | `test_verify_empty_evidence_not_pass` | evidence 空或 draft 空时 verifier 返回 fail 而非 pass | 空回答或编造回答通过校验 | Phase D |
| 4 | `test_generator_llm_disabled_meaningful_output` | `ENABLE_LLM_VERBALIZER=False` 时不返回"【LLM 服务未启用】"占位符，而是有意义的 deterministic 回答 | LLM 关闭时系统零表达能力 | Phase F |
| 5 | `test_workflow_not_bypass_response_contract` | `deterministic_tool_workflow` 和 `exploration_planning_workflow` 不绕过 `ResponseContract` 直接写 `final_response` | 第三层合同无法统一审计 | Phase H |
| 6 | `test_claim_verifier_blocks_unsupported` | `ClaimVerifier` 能识别 unsupported 和 contradicted claim | verifier 关键词规则对复杂句式失效 | Phase D |

### 执行顺序

```text
迭代 1：P0-1 + P0-2（出口统一 + Enum 覆盖）→ 确保路由不断、出口唯一
迭代 2：P0-3 + P0-6（空证据拦截 + claim 校验）→ 确保不编造
迭代 3：P0-4（LLM 关闭保底）→ 确保可用
迭代 4：P0-5（workflow 不绕过）→ 确保合同完整
```

## 5. 验收标准

- 不能把未验证 claim 放进 final_response
- 不能把 unsupported claim 包装成事实
- 不能让 fallback 只覆盖单店模板
- 不能让 workflow 直接绕过统一 response contract
- preview / final / trace 必须一致可解释

## 5. 与 10 的合并说明

> ⚠️ **重复文件标记**：`10_third_layer_test_plan.md` 与本文内容高度重叠（都是测试计划）。建议以本文为权威版本，将 10 的测试计划标记为重复后删除。

## 6. 35 个测试 Case 完整列表

合并 10 和 11 中的所有测试 case，去重后共计 35 个。

### 覆盖率统计

| 模块 | case 数 | 已有测试 | 新增 TODO_ADD_TEST |
|---|---|---|---|
| `ResponseContract` | 5 | 0 | 5 |
| `ClaimExtractor` / `ClaimVerifier` | 4 | 0 | 4 |
| `RewriteInstruction` / `RewritePolicy` | 3 | 0 | 3 |
| `FallbackPolicy` | 3 | 0 | 3 |
| `WorkflowBoundary` | 5 | 0 | 5 |
| `TraceContract` | 4 | 0 | 4 |
| `PreviewPolicy` | 3 | 0 | 3 |
| `LatencyBudget` | 3 | 0 | 3 |
| `FinalResponse` / `StreamingOutput` | 5 | 0 | 5 |
| **总计** | **35** | **0** | **35** |

### TODO_ADD_TEST 完整清单

（按模块分组，共 35 个）

**ResponseContract（5 个）**
```
TODO_ADD_TEST: local_life_agent/tests/test_third_layer_response_contract.py
TODO_ADD_TEST: local_life_agent/tests/test_third_layer_answer_envelope.py
TODO_ADD_TEST: local_life_agent/tests/test_third_layer_confidence_band.py
TODO_ADD_TEST: local_life_agent/tests/test_third_layer_uncertainty_notice.py
TODO_ADD_TEST: local_life_agent/tests/test_third_layer_final_response_contract.py
```

**ClaimExtractor / ClaimVerifier（4 个）**
```
TODO_ADD_TEST: local_life_agent/tests/test_third_layer_claim_extractor.py
TODO_ADD_TEST: local_life_agent/tests/test_third_layer_claim_verifier.py
TODO_ADD_TEST: local_life_agent/tests/test_third_layer_claim_citation.py
TODO_ADD_TEST: local_life_agent/tests/test_third_layer_verifier_contract.py
```

**RewriteInstruction / RewritePolicy（3 个）**
```
TODO_ADD_TEST: local_life_agent/tests/test_third_layer_rewrite_instruction.py
TODO_ADD_TEST: local_life_agent/tests/test_third_layer_rule_based_verbalizer.py
TODO_ADD_TEST: local_life_agent/tests/test_third_layer_fallback_policy.py
```

**WorkflowBoundary（5 个）**
```
TODO_ADD_TEST: local_life_agent/tests/test_third_layer_response_subgraph_boundary.py
TODO_ADD_TEST: local_life_agent/tests/test_third_layer_workflow_boundary.py
TODO_ADD_TEST: local_life_agent/tests/test_third_layer_unified_final_response.py
TODO_ADD_TEST: local_life_agent/tests/test_third_layer_streaming_output.py
TODO_ADD_TEST: local_life_agent/tests/test_third_layer_preview_policy.py
```

**TraceContract（4 个）**
```
TODO_ADD_TEST: local_life_agent/tests/test_third_layer_trace_contract.py
TODO_ADD_TEST: local_life_agent/tests/test_third_layer_latency_budget.py
TODO_ADD_TEST: local_life_agent/tests/test_third_layer_trace_span.py
TODO_ADD_TEST: local_life_agent/tests/test_third_layer_verifier_mode_switch.py
```

**存量测试（10 个已有文件不改动）**
```
local_life_agent/tests/test_answer_verifier.py（已有，复用）
local_life_agent/tests/test_llm_verbalizer.py（已有，复用）
local_life_agent/tests/test_p4_evidence_decision_answer_protocol.py（已有，复用）
local_life_agent/tests/test_p10_experience_performance.py（已有，复用）
local_life_agent/tests/test_phase7_workflows.py（已有，复用）
local_life_agent/tests/test_e2e_llm_main_path.py（已有，复用）
```

