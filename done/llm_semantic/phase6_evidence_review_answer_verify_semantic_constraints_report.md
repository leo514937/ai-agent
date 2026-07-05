# Phase 6 Evidence Review / Answer Verify Semantic Constraints Report
## 1. Conclusion
- PHASE_6_STATUS: PARTIAL
- EVIDENCE_REVIEW_SEMANTIC_READY: true
- ANSWER_VERIFY_SEMANTIC_READY: true
- ANSWER_VERBALIZER_GROUNDED_ONLY: true
- UNKNOWN_FAILED_EMPTY_PARTIAL_STABLE: true
- COMPARISON_UNSUPPORTED_WINNER_BLOCKED: true
- EXPLORATION_STAGE_EVIDENCE_REVIEW_READY: true
- CAN_ENTER_PHASE_7: false
- CAN_ENTER_PHASE_8: false
- Main conclusion: 本轮已把 Phase 1-5 的语义约束贯通到 evidence review / answer verifier / answer verbalizer，unknown / failed / empty / partial 的边界已经可观测且可拦截；但仓库里仍保留 1 个 `llm_main_path_verification` 失败和 `comparison_flow` 的 2 个既有失败，因此本阶段只能判定为 PARTIAL，而不是全量 PASS。

## 2. Scope
说明本轮只做 Phase 6，不做 Phase 7/8。

## 3. Files Changed
| File | Change | Reason | Risk |
| --- | --- | --- | --- |
| `local_life_agent/planning/evidence/evidence_review.py` | 让 review 消费 `SemanticFrame`、`grounding_status`、`missing_slot_type`、`exploration_stages`、`stage_statuses`、`comparison_support_status` 等语义侧车字段，并写入 trace payload | 让 review 能判断是否需要澄清、是否支持 comparison / exploration 的不完整阶段 | 中：review 现在更保守，部分场景会更早转澄清 |
| `local_life_agent/planning/evidence/evidence_builder.py` | 推荐证据分支也补齐语义侧车字段，避免 evidence 断流 | 让 recommendation / comparison / exploration 的证据形态保持一致 | 中：payload 变宽，但已有单测覆盖 |
| `local_life_agent/planning/shared/evidence_adapter.py` | answer plan 与 evidence pack 传递语义字段 | 让 answer verifier / verbalizer 统一消费语义约束 | 低：纯字段透传 |
| `local_life_agent/answer/answer_plan_builder.py` | answer plan 从 evidence 中继承 `semantic_parse_source`、`stage_statuses`、`ranking_preserved` 等 | 让 answer plan 不再丢失 Phase 6 所需语义上下文 | 低 |
| `local_life_agent/answer/generator.py` | `_build_decision_plan()` 继续向下透传语义侧车与 evidence 状态 | 让 verifier / verbalizer 拿到同一份语义上下文 | 低 |
| `local_life_agent/answer/b2_mini_verifier.py` | 扩展 verifier 输入、输出和 heuristic fallback，加入 exploration / comparison / unknown / failed / partial 约束 | 拦截 unsupported winner、ranking changed、partial as complete、unknown as false、failed as no | 中：规则更严格，可能暴露更多不完整回答 |
| `local_life_agent/answer/llm_verbalizer.py` | verbalizer prompt 和 boundary check 增加语义约束，支持 exploration partial 的保守自然语言 | 保证最终回复 grounded-only | 中：更倾向于保守表述 |
| `local_life_agent/llm/prompts/evidence_sufficiency_review.md` | 增加语义字段说明与 unknown/failed/partial 规范 | 让 review prompt 与代码契约一致 | 低 |
| `local_life_agent/llm/prompts/answer_verifier.md` | 增加语义字段、comparison support、stage status 等 verifier 约束 | 让 LLM verifier 看到完整语义约束 | 低 |
| `local_life_agent/llm/prompts/answer_verbalizer.md` | 明确 only grounded response、unknown/failed/partial 不能硬说成确定事实 | 防止 answer 阶段补编事实 | 低 |
| `local_life_agent/domain/schemas.py` / `local_life_agent/domain/evidence.py` / `local_life_agent/domain/decision.py` / `local_life_agent/domain/graph_state.py` / `local_life_agent/domain/graph_state_model.py` | 为 EvidencePack / EvidenceReviewResult / DecisionPlan / GraphState 补齐语义侧车字段 | 让上下游共享同一套可观测协议 | 中：schema 扩展面较大，但已通过编译与回归 |
| `local_life_agent/tests/test_evidence_review.py` / `test_answer_verifier.py` / `test_llm_verbalizer.py` / `test_p4_evidence_decision_answer_protocol.py` | 新增 Phase 6 约束测试 | 验证 unknown/failed/partial/comparison winner/exploration partial 的拦截 | 低 |

## 4. Evidence Review Contract
`EvidenceReview` 现在会消费 `SemanticFrame` 及其语义侧车字段，而不是只看 facet 结果。
- 读取：`semantic_frame`、`semantic_parse_source`、`grounding_status`、`missing_slot_type`、`router_policy_decision`、`router_policy_conflicts`、`conversation_continuity`、`exploration_stages`、`stage_queries`、`stage_evidence_requirements`、`stage_statuses`、`scene`、`time`、`location`
- 判定：`missing_slot_type` 属于缺槽时直接进入 `CLARIFY`，`grounding_status`/`comparison_support_status` 不足时标记不安全，`stage_statuses` 含 `unknown/failed/empty/partial` 时把 exploration 标记为不完整
- 输出：`evidence_status`、`comparison_support_status`、`ranking_preserved`、`unsupported_reasons`、`unknown_fields`、`failed_tools`、`partial_fields` 都进入 `trace_payload`

## 5. Answer Verifier Contract
verifier 的输入现在显式包含：
- `SemanticFrame`
- `DecisionPlan`
- `EvidencePack`
- `ConversationContinuity`
- `grounding_status`
- `semantic_parse_source`
- `router_policy_decision`
- `stage_statuses`
- `final answer draft`

verifier 现在会拦截：
- 把 `unknown` 说成 `false`
- 把 `failed` 说成 `no`
- 把 `partial` 说成 `complete`
- comparison winner 证据不足时硬给 winner
- ranking 在 answer 阶段被改写
- exploration 某个 stage 不完整却被说成整体成功

## 6. Answer Verbalizer Contract
`answer_verbalizer` 现在只允许输出 grounded response。
- 输入来源只来自 `DecisionPlan` / `EvidencePack` / `EvidenceReview` / `ConversationContinuity`
- 不允许补店铺、优惠、营业状态、评分、距离、人均等事实
- `unknown / failed / partial` 必须以不确定或部分信息的方式表达
- exploration 场景下如果某个 stage 失败，只能按 stage 说明，不能把整段路线写成完整成功

## 7. Unknown / Failed / Empty / Partial Mapping
| Status | Meaning | Allowed Answer | Forbidden Answer | Tests |
| --- | --- | --- | --- | --- |
| `unknown` | 工具或证据没有给出确定信息 | “暂时无法确认” | “没有券”“不营业” | `test_answer_verifier.py`、`test_llm_verbalizer.py` |
| `failed` | 工具调用失败 | “获取失败，暂时无法确认” | “没有券”“不营业” | `test_answer_verifier.py`、`test_evidence_review.py` |
| `empty` | 查询成功但无结果 | “未找到符合条件的结果” | “肯定没有” | `test_answer_verifier.py` |
| `partial` | 部分证据有、部分没有 | “部分信息已确认，其余暂时不完整” | “已经完整确认” | `test_answer_verifier.py`、`test_llm_verbalizer.py` |
| `grounded` | 证据覆盖语义需求 | 正常输出 | 编造额外事实 | 全链路回归 |

## 8. Comparison Evidence Findings
- comparison winner 现在必须有证据支撑
- `comparison_support_status` 非 grounded 时，verifier 会阻断 `更好 / 最推荐 / 胜出 / 领先 / 综合来看` 这类 winner 断言
- `ranking_preserved` 为 false 时，answer 阶段不能改排序
- `comparison_flow` 仍有 2 个既有失败，说明 graph-level comparison 收口还没完全完成，继续留给后续阶段

## 9. Exploration Stage Evidence Findings
- exploration 的 stage-level `partial / empty / failed / unknown` 不再被抹平成整体成功
- `stage_statuses` 和 `stage_evidence_requirements` 已进入 review / verifier / verbalizer
- 只要某个 stage 不完整，answer 就必须保留不确定性或部分成功的表达

## 10. Recommendation / Single Shop Fact Findings
- coupon / open_now 只有证据支持时才能说“有券 / 营业”
- `unknown` 不能被说成 “没有券 / 不营业”
- `failed` 不能被说成 “没有券 / 不营业”
- `empty` 只能说“未找到”，不能升级成确定否定
- `value_for_money` / `relative_price` 不能在证据不足时被绝对化

## 11. Observability
本轮对齐或新增的可观测字段：
- `evidence_status`
- `evidence_review_result`
- `answer_verify_result`
- `unsupported_reasons`
- `unknown_fields`
- `failed_tools`
- `partial_fields`
- `stage_statuses`
- `comparison_support_status`
- `ranking_preserved`
- `semantic_parse_source`
- `grounding_status`

## 12. Test Coverage
| Test | Scenario | Result |
| --- | --- | --- |
| `local_life_agent/tests/test_evidence_review.py` | missing exploration location / comparison support / trace payload | pass |
| `local_life_agent/tests/test_answer_verifier.py` | unknown as false / failed as no / partial as complete / unsupported comparison winner | pass |
| `local_life_agent/tests/test_llm_verbalizer.py` | exploration partial notice / unknown fact stays uncertain | pass |
| `local_life_agent/tests/test_p4_evidence_decision_answer_protocol.py` | semantic sidecar fields preserved into answer plan | pass |
| `local_life_agent/tests/test_exploration_planning_workflow.py` | exploration stage plan generation | pass |
| `local_life_agent/tests/test_llm_main_path_verification.py` | LLM failure fallback metadata | fail 1 case |
| `local_life_agent/tests/test_comparison_flow.py` | graph-level comparison follow-up | fail 2 cases |
| `local_life_agent/tests/test_chat_interface_full_e2e.py` | chat E2E regression | 17 skipped |

## 13. Regression Commands Run
- `python -m compileall local_life_agent -q` -> 通过
- `python -m pytest local_life_agent/tests/test_answer_verifier.py -q` -> 21 passed
- `python -m pytest local_life_agent/tests/test_evidence_review.py -q` -> 21 passed
- `python -m pytest local_life_agent/tests/test_llm_verbalizer.py -q` -> 13 passed
- `python -m pytest local_life_agent/tests/test_p4_evidence_decision_answer_protocol.py -q` -> 4 passed
- `python -m pytest local_life_agent/tests/test_exploration_planning_workflow.py -q` -> 11 passed
- `python -m pytest local_life_agent/tests/test_llm_main_path_verification.py -q` -> 12 passed, 1 failed
- `python -m pytest local_life_agent/tests/test_e2e_context_and_verifier.py -q` -> 5 passed
- `python -m pytest local_life_agent/tests/test_semantic_parser.py -q` -> 38 passed
- `python -m pytest local_life_agent/tests/test_router_rule_policy_guard.py -q` -> 46 passed
- `python -m pytest local_life_agent/tests/test_chat_clarification_resume_e2e.py -q` -> 11 passed
- `python -m pytest local_life_agent/tests/test_orchestration_router.py -q` -> 9 passed
- `python -m pytest local_life_agent/tests/test_workflow_runner.py -q` -> 3 passed
- `python -m pytest local_life_agent/tests/test_workflow_registry.py -q` -> 5 passed
- `python -m pytest local_life_agent/tests/test_candidate_resolver.py -q` -> 23 passed
- `python -m pytest local_life_agent/tests/test_chat_interface_full_e2e.py -q` -> 17 skipped
- `python -m pytest local_life_agent/tests/test_comparison_flow.py -q` -> 22 passed, 2 failed

## 14. Known Remaining Issues
- Phase 7：entity grounding / target resolution 仍需稳定
- Phase 8：chat E2E gate 仍需完整收口
- `local_life_agent/tests/test_comparison_flow.py` 仍有 2 个既有失败
- `local_life_agent/tests/test_chat_interface_full_e2e.py` 仍有 17 skipped
- `local_life_agent/tests/test_llm_main_path_verification.py` 仍有 1 个 fallback metadata 失败，当前不在 Phase 6 主目标内

## 15. Final Gate
- PHASE_6_COMPLETE: false
- EVIDENCE_REVIEW_SEMANTIC_READY: true
- ANSWER_VERIFY_SEMANTIC_READY: true
- ANSWER_VERBALIZER_GROUNDED_ONLY: true
- UNKNOWN_AS_FALSE_BLOCKED: true
- FAILED_AS_NO_BLOCKED: true
- PARTIAL_AS_COMPLETE_BLOCKED: true
- EMPTY_UNKNOWN_DISTINGUISHED: true
- COMPARISON_WINNER_REQUIRES_EVIDENCE: true
- RANKING_PRESERVED: true
- EXPLORATION_STAGE_PARTIAL_SUPPORTED: true
- CAN_START_PHASE_7: false
- CAN_START_PHASE_8: false
