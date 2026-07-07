# Full Failure Chain P1/P2 Implementation Report

## 1. Summary

本轮在已完成的 P0 收口基础上，继续做了 P1 / P2 的实现与验证，目标不是重写主链路，而是把高频长尾耗时、重复重试、以及证据校验层的可观测性和稳定性补齐。

本次实际落地的重点是：

- 让 `semantic_parse` 在一次失败后切换到更短的 repair prompt，避免同样的大 prompt 重试两次。
- 让 `evidence_review` 先做 deterministic precheck，再决定是否走 LLM review，减少不必要的 LLM 参与。
- 让 `decision_planner`、`EvidenceReviewResult`、`SemanticFrame` 增加结构化元数据，便于追踪 retry / fallback / preserved evidence。
- 让 `answer/verifier` 的 deterministic 路径直接消费本地证据扫描结果，避免验证层本身再制造误判。

这次的核心原则仍然是：

- LLM 继续负责理解与表达。
- deterministic 逻辑负责收口 retry / review / decision / verification 的边界。
- 事实继续通过 EvidencePack / structured schema 贯通，不再在 fallback 中丢失。

## 2. Files Changed

本轮实际修改文件：

- [local_life_agent/config.py](/D:/javacode/hm-dianping/local_life_agent/config.py)
- [local_life_agent/domain/decision.py](/D:/javacode/hm-dianping/local_life_agent/domain/decision.py)
- [local_life_agent/domain/evidence.py](/D:/javacode/hm-dianping/local_life_agent/domain/evidence.py)
- [local_life_agent/domain/schemas.py](/D:/javacode/hm-dianping/local_life_agent/domain/schemas.py)
- [local_life_agent/planning/llm_utils.py](/D:/javacode/hm-dianping/local_life_agent/planning/llm_utils.py)
- [local_life_agent/semantic/intent_parser.py](/D:/javacode/hm-dianping/local_life_agent/semantic/intent_parser.py)
- [local_life_agent/planning/evidence/evidence_review.py](/D:/javacode/hm-dianping/local_life_agent/planning/evidence/evidence_review.py)
- [local_life_agent/planning/decision/decision_planner.py](/D:/javacode/hm-dianping/local_life_agent/planning/decision/decision_planner.py)
- [local_life_agent/answer/generator.py](/D:/javacode/hm-dianping/local_life_agent/answer/generator.py)
- [local_life_agent/answer/verifier.py](/D:/javacode/hm-dianping/local_life_agent/answer/verifier.py)
- [local_life_agent/answer/b2_mini_verifier.py](/D:/javacode/hm-dianping/local_life_agent/answer/b2_mini_verifier.py)
- [local_life_agent/tests/test_full_failure_chain_p1_p2_regression.py](/D:/javacode/hm-dianping/local_life_agent/tests/test_full_failure_chain_p1_p2_regression.py)
- [todo/full_failure_chain_p1_p2_implementation_report.md](/D:/javacode/hm-dianping/todo/full_failure_chain_p1_p2_implementation_report.md)

## 3. P1: Latency / Retry Strategy

### 3.1 Semantic Parse Two-Stage Flow

`semantic_parse` 现在不再把第一次失败直接交给同样的大 prompt 重试。

改动点：

- 第一次调用仍使用完整 prompt。
- 如果失败，会切换到更短的 repair prompt。
- repair prompt 的目标是把 schema 修复，而不是重新做一次完整推理。
- 失败 / 修复 / fallback 的状态会被写回到结构化元数据中。

新增的可观测字段包括：

- `semantic_parse_status`
- `semantic_parse_mode`
- `semantic_parse_retry_count`
- `semantic_parse_attempts`
- `semantic_parse_reason`

### 3.2 Evidence Review Precheck

`evidence_review_with_llm(...)` 现在先做 deterministic precheck。

核心策略：

- 如果 precheck 已经足够判断为 finish / degrade / insufficient，就不再默认进入 LLM review。
- 只有在确实需要 replan / expand search 时才保留 LLM review。
- LLM review 使用压缩后的 evidence summary，而不是把冗余大对象原样塞进去。
- 失败时回退到 precheck 结果，避免 review 再次把流程拖入重复失败。

这样做的目标是：

- 降低 evidence review 的长上下文成本。
- 避免“同样的证据、同样的 prompt、同样的失败条件”反复重试。

### 3.3 Decision Planner Metadata

`decision_planner` 现在把 fallback / mode / evidence preservation 相关信息显式写入 `DecisionPlan`。

新增字段包括：

- `decision_mode`
- `fallback_used`
- `candidate_count_before_decision`
- `candidate_count_after_decision`
- `evidence_preserved`
- `decision_reason`

这样做的收益是：

- 可以明确区分 deterministic、llm、deterministic_fallback。
- 可以追踪是不是因为证据不足、schema 失败、还是 unsupported 决策导致退化。
- 后续做耗时分析时能更准确定位是 prompt、schema 还是 fallback 造成的长尾。

## 4. P2: Observability / Verification

### 4.1 Verifier 收口

`answer/verifier.py` 的 deterministic 路径现在直接基于本地证据扫描，而不是只依赖外部 heuristic。

补上的能力包括：

- coupon / open_status / distance / rating / avg_price 的本地一致性扫描。
- 对 unknown / failed / partial 证据的保守表达检查。
- 对推荐 / 比较中的 shop mismatch、omitted targets、forbidden claims 的明确告警。
- 对 grounded fact 被写成“暂时无法确认”的场景给出显式问题标签。

这样做是为了避免：

- verifier 反过来把已经拿到的事实打散。
- deterministic verification 因为缺少基础覆盖而误放行。

### 4.2 Metadata and Regression Coverage

本轮补了新的回归测试：

- `local_life_agent/tests/test_full_failure_chain_p1_p2_regression.py`

覆盖点：

- semantic parser 的 repair prompt 是否真的更短。
- evidence review 是否使用 compact summary 且不再内层重复重试。
- simple evidence 是否优先走 deterministic verifier。

同时对既有测试做了回归验证，确保没有把主链路打歪。

## 5. Validation

已执行验证：

- `python -m compileall local_life_agent`
- `python -m pytest local_life_agent/tests/test_full_failure_chain_p1_p2_regression.py -q`
- `python -m pytest local_life_agent/tests/test_semantic_parser.py -q`
- `python -m pytest local_life_agent/tests/test_evidence_review.py -q`
- `python -m pytest local_life_agent/tests/test_decision_planner.py -q`
- `python -m pytest local_life_agent/tests/test_answer_verifier.py -q`
- `python -m pytest local_life_agent/tests/test_comparison_flow.py -q`
- `python -m pytest local_life_agent/tests/test_single_coupon_flow.py -q`
- `python -m pytest local_life_agent/tests/test_single_shop_multifacet.py -q`
- `python -m pytest local_life_agent/tests/test_recommendation_flow.py -q`
- `python -m pytest local_life_agent/tests/test_full_failure_chain_p0_regression.py -q`

结果摘要：

- 新增 P1/P2 回归：`3 passed`
- verifier 相关回归：`23 passed`
- semantic parser 回归：`38 passed`
- evidence review 回归：`22 passed`
- decision planner 回归：`25 passed`
- comparison flow：`24 passed`
- single coupon flow：`6 passed`
- recommendation flow：`17 passed, 2 xfailed`
- single shop multifacet：`7 passed`
- P0 full failure chain regression：`5 passed`

## 6. Result

本轮修复后，当前链路的关键变化是：

- `semantic_parse` 不再在同样失败条件下做无效重复重试。
- `evidence_review` 更偏向 deterministic precheck，避免把已经结构化的事实再交给 LLM 反复判断。
- `decision_planner` 的 fallback / mode / evidence 关系更清晰。
- `answer/verifier` 的 deterministic 路径不再依赖脆弱的外部 heuristic。

对原始故障链来说，P1 目标已经实现了“把重复失败变成单次失败，把长尾变成可解释 fallback”。

## 7. Residual Risks

仍然保留的风险主要是：

- 日志轮转在 Windows 下会有 `python_service.log` 占用告警，这是本地环境问题，不是本次逻辑回归。
- `evidence_review` / `decision_planner` 仍然保留 LLM 路径，因此 prompt 质量和模型延迟仍可能影响尾延迟。
- deterministic verifier 已覆盖主测试，但后续如果增加新的 facet 类型，仍需要同步扩展本地扫描规则。

## 8. Next Step

如果继续推进，建议顺序是：

1. 进一步压缩 `evidence_review` 的输入体积，继续降低长上下文成本。
2. 给 LLM stage 加更细的 span / counters，方便定位是哪一层最常超时。
3. 继续收敛重复的 state 适配代码，减少后续维护成本。

---

如果需要，我下一步可以继续补一份 `todo/full_failure_chain_p1_p2_audit_addendum.md`，专门把这次新增的 deterministic scan / metadata 字段 / 回归测试再整理成更适合评审的清单版。
