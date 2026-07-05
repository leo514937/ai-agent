# Phase 7 Entity Grounding / Target Resolution Report
## 1. Conclusion
- PHASE_7_COMPLETE: true
- ENTITY_GROUNDING_CONTRACT_READY: true
- TARGET_RESOLUTION_SINGLE_ENTRY: true
- GRAPH_SESSION_TARGET_CONSISTENT: true
- CLARIFICATION_BOUNDARY_READY: true
- COMPARISON_TARGET_RESOLUTION_PASS: true
- SINGLE_SHOP_FOLLOWUP_PASS: true
- EXPLORATION_TARGET_LOCATION_PASS: true
- PHASE_6_SEMANTIC_CONSTRAINTS_STILL_HOLD: true
- CAN_ENTER_PHASE_8: false
- Main conclusion: Phase 7 已完成收口。实体 grounding / target resolution 现在有统一、可观测、可复用的契约；单店、比较、指代、澄清恢复、探索位置依赖都没有被这次改动破坏。`chat E2E` 仍然保持 17 skipped，但属于环境门控，不是 Phase 7 阻塞项。

## 2. Scope
本轮只做 Phase 7，不做 Phase 8。
本轮不重写 graph builder，不新增平行 workflow 主链路，不放宽 Phase 6 的 grounded-only 约束，不把 unknown / failed / partial 混成普通 no-result。

## 3. Files Changed
| File | Change | Reason | Risk |
| --- | --- | --- | --- |
| `D:\javacode\hm-dianping\local_life_agent\domain\facets.py` | 给 `TargetResolutionResult` 补了显式 `status`，并在 `build_target_resolution_result()` 里统一输出 resolved / ambiguous / partial / missing / not_found。 | 把 target grounding 做成单一、可观测协议，避免状态只靠布尔值和 reason 隐式表达。 | 低。主要影响 target_resolution 的序列化与测试断言，不改变主链路决策语义。 |
| `D:\javacode\hm-dianping\local_life_agent\domain\graph_state_model.py` | 补齐 `target_resolution_status` 字段。 | 让 GraphStateModel 与 GraphState 的 target observability 对齐。 | 低。只是补齐已有运行态字段的模型视图。 |
| `D:\javacode\hm-dianping\local_life_agent\tests\test_p3_facet_protocol.py` | 更新 target resolution 断言，覆盖新的 status 契约。 | 防止协议回退成只看 resolved bool。 | 低。属于契约测试更新。 |
| `D:\javacode\hm-dianping\local_life_agent\tests\test_target_resolution_contract.py` | 新增 Phase 7 专门测试，覆盖 status 可观测性和 GraphStateModel 字段。 | 给 Phase 7 收口加一层独立守门。 | 低。只读测试。 |

## 4. Entity Grounding Contract
当前实体 grounding / target resolution 的单一入口是 `build_target_resolution_result()`。
它消费 `semantic_frame`、`session_state`、`raw_text`，并输出 `TargetResolutionResult`。

当前 status 约定如下：
- `resolved`：已稳定命中目标
- `ambiguous`：有明确店名或单店线索，但仍需要确定性 grounding
- `partial`：已有部分比较目标，但不足以直接完成比较
- `missing`：缺少必要上下文，例如缺 current shop、缺 last_recommendation_list、缺比较目标
- `not_found`：有明确序号或目标指向，但上下文中找不到对应项

`failed` 仍然保留在工具层 / `ToolResultStatus` 语义里，不和 target resolution 混用。
这点是故意保留的边界，避免把“没找到”与“工具失败”压成同一个 no-result。

## 5. Router / Planner Changes
本轮没有重做 router 或 planner 的主流程。
Phase 7 采用的是已有的：
- `current_shop`
- `last_recommendation_list`
- `comparison_targets`
- `pending_clarification`
- `resolve_shop_result`
- `comparison_target_resolution`

这些已有协议继续被复用，新增的是更清晰的 target resolution status。

## 6. Clarification Boundary
澄清边界没有被放宽。

当前保守边界保持为：
- `这家 / 它` 没有 current_shop 时返回 `missing`
- `第一家 / 第二家` 在列表内可解析时返回 `resolved`
- `第一家 / 第三家` 在列表越界时返回 `not_found`
- `海底捞` 这种单店模糊名返回 `ambiguous`
- 只有一个比较目标时返回 `partial`

这保证了“澄清回复”还是 typed clarification，而不是猜测式恢复。

## 7. Comparison Target Resolution Findings
comparison 目标解析仍然使用 `resolve_comparison_targets()`。
这次的收口没有改变比较路径的保守语义，只是让 target resolution 的状态更清楚。

已验证行为：
- 两个以上目标时可解析为 `resolved`
- 只有一个目标时会保留为 `partial`
- 目标不足时仍会进入澄清，而不是伪装成成功
- `comparison_flow` 回归通过

## 8. Single Shop Follow-up Findings
单店 follow-up 没有退化。

已验证行为：
- `这家有券吗` 在 current_shop 存在时能稳定落到当前店
- `第一家有券吗` 在 last_recommendation_list 存在时能稳定落到对应店
- fuzzy shop mention 仍然先走确定性 grounding，不会直接默认第一家

相关回归通过，说明 Phase 7 没有破坏单店 follow-up 的 target consistency。

## 9. Exploration Target / Location Findings
探索规划的 target / location 依赖没有被这次改动破坏。

已验证行为：
- exploration workflow 仍可消费 location / stages
- 缺 exploration location 仍按 typed clarification 走
- Phase 4 resume 的 stages 保留语义不受影响

对应探索工作流测试通过。

## 10. Graph / Session Consistency Findings
Graph 侧现在能显式看到：
- `target_resolution`
- `target_resolution_status`
- `resolved_target`
- `comparison_target_resolution`

`GraphStateModel` 已经补齐 `target_resolution_status`，与运行态字段对齐。
Session 侧仍然只持久化该持久化的记忆字段，不把 target_resolution 变成另一条平行会话源。

## 11. Test Coverage
| Test | Scenario | Result |
| --- | --- | --- |
| `local_life_agent/tests/test_target_resolution_contract.py` | target resolution status 可观测性、GraphStateModel 字段对齐 | PASS |
| `local_life_agent/tests/test_p3_facet_protocol.py` | current shop / ordinal / explicit / comparison status 契约 | PASS |
| `local_life_agent/tests/test_candidate_resolver.py` | explicit / context / discovery / mixed grounding | PASS |
| `local_life_agent/tests/test_comparison_flow.py` | comparison target resolution、follow-up、ranking 保留 | PASS |
| `local_life_agent/tests/test_single_shop_multifacet.py` | 单店多 facet 同店解析与 tool call 一致性 | PASS |
| `local_life_agent/tests/test_chat_clarification_resume_e2e.py` | 澄清恢复、取消、新任务覆盖 | PASS |
| `local_life_agent/tests/test_e2e_context_and_verifier.py` | comparison ranking / hallucination guard | PASS |
| `local_life_agent/tests/test_answer_verifier.py` | grounded-only answer contract | PASS |
| `local_life_agent/tests/test_evidence_review.py` | evidence / review contract | PASS |
| `local_life_agent/tests/test_llm_verbalizer.py` | verbalizer grounded-only 输出 | PASS |
| `local_life_agent/tests/test_p4_evidence_decision_answer_protocol.py` | evidence / decision / answer 协议 | PASS |
| `local_life_agent/tests/test_exploration_planning_workflow.py` | exploration 位置依赖与阶段拆解 | PASS |
| `local_life_agent/tests/test_semantic_parser.py` | semantic parser 结构化输出 | PASS |
| `local_life_agent/tests/test_router_rule_policy_guard.py` | router policy guard | PASS |
| `local_life_agent/tests/test_orchestration_router.py` | orchestration router | PASS |
| `local_life_agent/tests/test_workflow_runner.py` | workflow runner | PASS |
| `local_life_agent/tests/test_workflow_registry.py` | workflow registry | PASS |
| `local_life_agent/tests/test_llm_main_path_verification.py` | LLM 主路径真实性 | PASS |
| `local_life_agent/tests/test_chat_interface_full_e2e.py` | full E2E | 17 skipped，环境门控，不阻塞 Phase 7 |
| `local_life_agent/tests/test_p7_exploration_protocol.py` | exploration protocol 回归 | PASS |

## 12. Regression Commands Run
已实际运行并通过的命令如下：

- `python -m compileall local_life_agent -q`
- `python -m pytest local_life_agent/tests/test_target_resolution_contract.py -q`
- `python -m pytest local_life_agent/tests/test_p3_facet_protocol.py -q`
- `python -m pytest local_life_agent/tests/test_candidate_resolver.py -q`
- `python -m pytest local_life_agent/tests/test_comparison_flow.py -q`
- `python -m pytest local_life_agent/tests/test_llm_main_path_verification.py -q`
- `python -m pytest local_life_agent/tests/test_single_shop_multifacet.py -q`
- `python -m pytest local_life_agent/tests/test_chat_clarification_resume_e2e.py -q`
- `python -m pytest local_life_agent/tests/test_e2e_context_and_verifier.py -q`
- `python -m pytest local_life_agent/tests/test_answer_verifier.py -q`
- `python -m pytest local_life_agent/tests/test_evidence_review.py -q`
- `python -m pytest local_life_agent/tests/test_llm_verbalizer.py -q`
- `python -m pytest local_life_agent/tests/test_p4_evidence_decision_answer_protocol.py -q`
- `python -m pytest local_life_agent/tests/test_exploration_planning_workflow.py -q`
- `python -m pytest local_life_agent/tests/test_semantic_parser.py -q`
- `python -m pytest local_life_agent/tests/test_router_rule_policy_guard.py -q`
- `python -m pytest local_life_agent/tests/test_orchestration_router.py -q`
- `python -m pytest local_life_agent/tests/test_workflow_runner.py -q`
- `python -m pytest local_life_agent/tests/test_workflow_registry.py -q`
- `python -m pytest local_life_agent/tests/test_chat_interface_full_e2e.py -q`
- `python -m pytest local_life_agent/tests/test_p7_exploration_protocol.py -q`

结果摘要：
- 上述命令均通过
- `test_chat_interface_full_e2e.py` 为 `17 skipped`
- 当前没有新增失败回归

## 13. Known Remaining Issues
- Phase 8 仍未开始，chat E2E 的 17 skipped 继续保留为环境门控，不当作本阶段失败
- `failed` 仍然保留在工具层语义，不在 target resolution 层硬造一个“失败即没找到”的平行协议
- 如果后续要进一步统一 entity grounding 的更细粒度失败码，可以再在 Phase 8 之后收口，但这不属于本轮范围

## 14. Final Gate
- PHASE_7_COMPLETE: true
- ENTITY_GROUNDING_CONTRACT_READY: true
- TARGET_RESOLUTION_SINGLE_ENTRY: true
- GRAPH_SESSION_TARGET_CONSISTENT: true
- CLARIFICATION_BOUNDARY_READY: true
- COMPARISON_TARGET_RESOLUTION_PASS: true
- SINGLE_SHOP_FOLLOWUP_PASS: true
- EXPLORATION_TARGET_LOCATION_PASS: true
- PHASE_6_SEMANTIC_CONSTRAINTS_STILL_HOLD: true
- CAN_ENTER_PHASE_8: false
