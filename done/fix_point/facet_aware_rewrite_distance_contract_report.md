# Facet-Aware Rewrite / Distance Contract 修复报告

## 结论

方案 A 已实施完成。

本次修复把 Answer Rewrite、Verifier、Evidence、Decision、AnswerPlan 之间的 facet contract 打通，避免了 `known fact` 被保守重写成 `unknown`，并把距离 facet 与 `location: null` 的传播链路补齐。

## 根因

1. Answer Rewrite 只看到了较粗粒度的 unknown 提示，缺少 facet 级别的 `facet_statuses` / `grounded_facts` / `facet_reasons`，所以会把已经确认的营业、优惠、距离信息一起降级。
2. Verifier 主要依赖 target 原始字段，没有显式识别“grounded 事实被改写成暂时无法确认”的违规。
3. Evidence/Decision/Answer 之间没有稳定回填 facet contract，导致 `DecisionPlan` 在回答阶段拿不到足够的事实边界。
4. `resolve_shop` 的 legacy 入口会把 `location` 传成 `null`，影响距离分支的稳定性。

## 已完成修复

### 1. facet contract 全链路透传

新增并透传了：

- `facet_statuses`
- `grounded_facts`
- `facet_reasons`

覆盖对象包括：

- `EvidencePack`
- `DecisionPlan`
- `AnswerPlan`
- `EvidenceReviewResult`

涉及文件：

- `/D:/javacode/hm-dianping/local_life_agent/domain/schemas.py`
- `/D:/javacode/hm-dianping/local_life_agent/domain/decision.py`
- `/D:/javacode/hm-dianping/local_life_agent/domain/evidence.py`
- `/D:/javacode/hm-dianping/local_life_agent/answer/answer_plan_builder.py`
- `/D:/javacode/hm-dianping/local_life_agent/answer/generator.py`
- `/D:/javacode/hm-dianping/local_life_agent/planning/evidence/evidence_review.py`

### 2. evidence builder 增强

在证据构建阶段为单店与推荐场景补充了 facet contract，且把 tool result 的 failed/unknown/partial 状态合并回 contract，避免距离被冲回 unknown。

涉及文件：

- `/D:/javacode/hm-dianping/local_life_agent/planning/evidence/evidence_builder.py`

### 3. rewrite / verifier facet-aware

Rewrite 和 Verifier 现在都能识别：

- grounded facts 不能降级成 unknown
- 只有 unknown / failed / partial facet 才允许保守表达
- 距离信息必须按 facet 单独处理

涉及文件：

- `/D:/javacode/hm-dianping/local_life_agent/answer/llm_verbalizer.py`
- `/D:/javacode/hm-dianping/local_life_agent/answer/verifier.py`
- `/D:/javacode/hm-dianping/local_life_agent/answer/b2_mini_verifier.py`
- `/D:/javacode/hm-dianping/local_life_agent/tests/fakes/verifier.py`

### 4. `location: null` 修复

把 legacy resolve 入口改成对 `location` 做 dict 归一化，避免继续传递 `null`。

涉及文件：

- `/D:/javacode/hm-dianping/local_life_agent/target/shop_resolver.py`

### 5. Answer Rewrite prompt / fallback 更新

补充了 grounded facts 保护规则，并让 fallback 输出按 facet 单独表达，不再把整条回答整体保守化。

涉及文件：

- `/D:/javacode/hm-dianping/local_life_agent/llm/prompts/answer_verbalizer.md`
- `/D:/javacode/hm-dianping/local_life_agent/llm/prompts/answer_verifier.md`

## 验证结果

已完成：

- `python -m compileall local_life_agent -q`
- `pytest local_life_agent/tests/test_answer_verifier.py -q`
- `pytest local_life_agent/tests/test_llm_verbalizer.py -q`
- `pytest local_life_agent/tests/test_evidence_review.py -q`
- `pytest local_life_agent/tests/test_single_shop_multifacet.py -q`
- `pytest local_life_agent/tests/test_distance_facet_contract.py -q`
- `pytest local_life_agent/tests/test_p4_evidence_decision_answer_protocol.py -q`

结果：

- 以上测试均通过。

## 关键 gate

- `FACET_AWARE_REWRITE_READY`: PASS
- `KNOWN_TO_UNKNOWN_BLOCKED`: PASS
- `GROUNDED_FACTS_PRESERVED_IN_REWRITE`: PASS
- `UNKNOWN_ONLY_APPLIES_TO_UNKNOWN_FACETS`: PASS
- `FACET_STATUSES_AVAILABLE`: PASS
- `DISTANCE_FACET_CONTRACT_READY`: PASS
- `LOCATION_NULL_SCHEMA_FIXED`: PASS
- `MULTIFACET_PARTIAL_ANSWER_READY`: PASS
- `PHASE_6_CONSTRAINTS_STILL_HOLD`: PASS
- `COMPARISON_FLOW_STILL_GREEN`: PASS
- `PHASE_8_9_GATE_STILL_GREEN`: PASS

## 备注

本次修改以协议和验证链路为主，尽量避免引入新的业务规则分支，重点是让“已确认事实”与“未知/失败事实”在证据、决策、回答三个阶段保持一致。
