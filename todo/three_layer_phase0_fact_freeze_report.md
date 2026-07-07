# 三层改造统一执行计划 - 第 0 批：事实冻结报告

## 结论
- 批次结论：`PARTIAL PASS`
- 当前分支：`toolcall`
- 当前提交：`0852816`
- 结论依据：事实链路已核对完成，关键边界与绕行路径已定位，但若按当前回归期望看，`llm_verbalizer`、部分推荐流和少量 e2e 仍有真实失败，暂不满足“完全冻结且全绿”。

## 调研范围
- 只做事实冻结，不改业务逻辑。
- 重点核对了顶层路由、理解子图、规划子图、执行/审查子图、回答子图、workflow registry / runner、会话存储、证据缓存、工具网关、答案生成与验证相关模块。
- 已确认本次仅新增本报告文件，未修改业务代码。

## 第一层事实冻结
- 顶层输入链路是 `receive_input -> load_session -> basic_validate -> normalize_text -> hard_guard -> active_turn_resolver -> top_intent_router`，`load_session` 明确发生在基础校验之前。见 [`intake_guard_router.py`](/D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/intake_guard_router.py#L46)。
- `hard_guard` 只拦纯问候、纯能力问答、空文本、纯标点、超短噪声；包含任何本地生活业务意图时会直接放行。见 [`hard_guard.py`](/D:/javacode/hm-dianping/local_life_agent/input/hard_guard.py)。
- `top_intent_router` 对非 `local_life` 意图会直接终止，不进入本地生活主图；`local_life` 才进入理解子图。见 [`intake_guard_router.py`](/D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/intake_guard_router.py#L115)。
- `merge_clarification` 只负责 pending clarification 的恢复/切换/继续，不是通用答案生成器。见 [`merge_clarification.py`](/D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/merge_clarification.py)。
- `active_turn_resolver` 存在独立的澄清回复解析、topic switch、ordinal / deictic 识别，不只是“是否继续当前任务”的布尔判断。见 [`active_turn_resolver.py`](/D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/active_turn_resolver.py)。

## 第二层事实冻结
- `semantic/slot_extractor.py` 不只是补 merchant_mentions，还会推导 `task_type`、`comparison_targets`、`preferences`、`filters`、`new_task_override`、`constraint_update` 等结构化信号。见 [`slot_extractor.py`](/D:/javacode/hm-dianping/local_life_agent/semantic/slot_extractor.py)。
- `target/context_recovery.py` 会根据会话态和语义帧恢复 `resolved_target` / `comparison_targets`，并可直接返回比较澄清结果。见 [`context_recovery.py`](/D:/javacode/hm-dianping/local_life_agent/target/context_recovery.py)。
- `target/reference_resolver.py` 同时处理显式店名、序号引用、指代引用、列表引用，且会读取 `last_recommendation_list` 和 `current_shop`。见 [`reference_resolver.py`](/D:/javacode/hm-dianping/local_life_agent/target/reference_resolver.py)。
- `planning_subgraph` 不是单纯的“出计划”节点，它同时承接目标解析、澄清分流、candidate set、解释性兜底、`pending_clarification` 维护和 `final_response` 早写。见 [`planning_subgraph.py`](/D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/planning_subgraph.py)。
- `execution_review_subgraph` 负责工具执行、证据构建、证据审查、决策计划、决策审查，并在 `REPLAN_EVIDENCE` / `EXPAND_SEARCH` / `CLARIFY` / `FALLBACK` 间路由。见 [`execution_review_subgraph.py`](/D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/execution_review_subgraph.py)。
- `response_subgraph` 在 `direct / reject / exploration_plan / clarify / fallback` 等分支上会直接短路，不一定走统一 answer loop。见 [`response_subgraph.py`](/D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/response_subgraph.py#L163)。
- `response_subgraph._h_answer_verify` 仍存在高风险短路：当 `evidence` 为空或 `draft_response` 为空时会直接进入通过路径。见 [`response_subgraph.py`](/D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/response_subgraph.py#L304)。
- `workflow_runner` 不是单一入口，它会结合 `workflow_name`、`workflow_callable`、`response_mode` 决定最终走 `planning_subgraph` 还是 `response_subgraph`。见 [`workflow_runner.py`](/D:/javacode/hm-dianping/local_life_agent/engine/workflow_runner.py)。
- `workflow_registry` 里 `discovery_decision` 以 `planning_subgraph` 为入口，`direct_response`、`deterministic_tool`、`clarification_fallback`、`exploration_planning` 都是正式注册工作流。见 [`workflow_registry.py`](/D:/javacode/hm-dianping/local_life_agent/engine/workflow_registry.py)。
- `orchestration_router_shadow` 名义上是 shadow，但它会写 `orchestration_decision`，不是纯旁路观察。见 [`orchestration_router_shadow.py`](/D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/orchestration_router_shadow.py)。

## 第三层事实冻结
- `SessionState` 已经包含 `current_shop`、`pending_clarification`、`comparison_targets`、`last_candidate_spec`、`last_candidate_set`、`active_goal`、`review_results`、`replan_counters` 等字段。见 [`state.py`](/D:/javacode/hm-dianping/local_life_agent/domain/state.py#L95)。
- `GraphState` 里同时存在 `pending_clarification` / `clarification_request`、`current_shop`、`last_recommendation_list`、`comparison_targets`、`tool_results` / `tool_result_set`、`evidence_pack`、`state_update_plan`、`workflow_*`、`answer_verify_result`、`final_response` 等跨层字段。见 [`graph_state.py`](/D:/javacode/hm-dianping/local_life_agent/domain/graph_state.py)。
- `InMemorySessionStore` 是当前会话存储实现，没有看到 Redis / DB 版本参与主链路。见 [`session/store.py`](/D:/javacode/hm-dianping/local_life_agent/session/store.py)。
- `BudgetContext` 已存在，包含 tool round / retry / expand search / rewrite / facet enrich 的预算和已消费计数。见 [`budget_context.py`](/D:/javacode/hm-dianping/local_life_agent/planning/budget/budget_context.py)。
- `EvidenceCache` 是进程内缓存，按 `scope + payload fingerprint` 命中，不是外部持久化缓存。见 [`evidence_cache.py`](/D:/javacode/hm-dianping/local_life_agent/planning/evidence/evidence_cache.py)。
- `ToolCallGateway` 是统一工具入口，工具注册、参数校验、熔断、重试、规范化结果都在 Gateway 内完成。见 [`gateway.py`](/D:/javacode/hm-dianping/local_life_agent/tools/gateway.py)。
- `ToolBatchExecutor` 只是 execution 层的并发批执行包装，不是 LangGraph 原生 Send/reducer 图。见 [`tool_batch_executor.py`](/D:/javacode/hm-dianping/local_life_agent/planning/evidence/tool_batch_executor.py)。
- `review_policy.py` 已把 P0 的 next_action 收敛到 `FINISH / CLARIFY / FALLBACK`，`EXPAND_SEARCH / REPLAN_EVIDENCE / DEGRADE_ANSWER` 被标为 P1/P2 语义。见 [`review_policy.py`](/D:/javacode/hm-dianping/local_life_agent/planning/policies/review_policy.py)。
- `ranking_policy.py` 仍是确定性的评分与排序，不依赖 LLM。见 [`ranking_policy.py`](/D:/javacode/hm-dianping/local_life_agent/planning/policies/ranking_policy.py)。

## 契约与 DTO 事实
- `ResponseDirective` 已存在。见 [`response_directive.py`](/D:/javacode/hm-dianping/local_life_agent/answer/response_directive.py)。
- `RewriteInstruction` 已存在。见 [`rewrite_instruction.py`](/D:/javacode/hm-dianping/local_life_agent/answer/rewrite_instruction.py)。
- `GraphStateModel` 已存在，且明确标注为 validation-only adapter。见 [`graph_state_model.py`](/D:/javacode/hm-dianping/local_life_agent/domain/graph_state_model.py)。
- 当前代码库中未找到 `FocusContext`、`ContextualizedTurn`、`FreshnessMeta`、`LocationContext`、`ResponseContract`、`ClaimExtractor`、`ClaimVerifier` 这几类独立 DTO / 类实现。
- `ResponseMode` 枚举已经存在，且包含 `direct`、`direct_response`、`reject`、`clarify`、`fallback`、`answer`、`tool_answer`、`comparison`、`exploration_plan` 等值。见 [`enums.py`](/D:/javacode/hm-dianping/local_life_agent/domain/enums.py)。

## 关键实现事实
- `direct_response_workflow` 会直接写 `final_response`、`draft_response`、`answer_source`、`answer_verify_passed`，并跳过通用回答链路。见 [`direct_response_workflow.py`](/D:/javacode/hm-dianping/local_life_agent/engine/workflows/direct_response_workflow.py)。
- `clarification_fallback_workflow` 也会直接写 `final_response`、`draft_response`、`pending_clarification`、`answer_verify_passed`。见 [`clarification_fallback_workflow.py`](/D:/javacode/hm-dianping/local_life_agent/engine/workflows/clarification_fallback_workflow.py)。
- `exploration_planning_workflow` 同样可直接产出 `final_response`，并在 `clarify` / `fallback` 两侧自带分支。见 [`exploration_planning_workflow.py`](/D:/javacode/hm-dianping/local_life_agent/engine/workflows/exploration_planning_workflow.py)。
- `deterministic_tool_workflow` 也存在直接写 `final_response` / `draft_response` 的路径，属于绕开通用 answer 子图的正式工作流。见 [`deterministic_tool_workflow.py`](/D:/javacode/hm-dianping/local_life_agent/engine/workflows/deterministic_tool_workflow.py)。
- `answer/generator.py` 在 LLM 关闭时会写 `answer_source=llm_disabled`，不是纯 composer 输出。见 [`generator.py`](/D:/javacode/hm-dianping/local_life_agent/answer/generator.py#L670)。
- `llm_verbalizer.py` 的失败回退仍会走 `_mark_template_fallback_metadata` 和 `_rule_based_verbalize`，而不是完全无模板/无规则的统一 composer。见 [`llm_verbalizer.py`](/D:/javacode/hm-dianping/local_life_agent/answer/llm_verbalizer.py)。
- `composers/deterministic.py` 已引入 `SingleShopFactComposer`，而且会读取 `fallback_template_type`。见 [`deterministic.py`](/D:/javacode/hm-dianping/local_life_agent/answer/composers/deterministic.py#L114)。

## 文档与源码偏差
- 文档侧如果把“新增 ResponseDirective / RewriteInstruction / GraphStateModel”当作后续计划，这一批事实显示它们在源码中已经存在。
- 文档侧如果把第 0 批理解为“所有答案链路都统一到 composer 且完全去模板化”，当前源码并不满足：`generator.py`、`llm_verbalizer.py`、`response_subgraph.py` 仍存在多条 fallback / deterministic / template 路径。
- 文档侧如果把 `orchestration_router_shadow` 当作纯观察节点，这不符合源码，因其确实写入并传播 `orchestration_decision`。
- 文档侧如果把 `session` 视作跨进程持久化，这不符合当前实现；主实现仍是 `InMemorySessionStore`。

## 已运行测试
- `python -m pytest local_life_agent/tests/test_answer_verifier.py -q`，结果：`23 passed`。
- `python -m pytest local_life_agent/tests/test_llm_verbalizer.py -q`，结果：`6 failed, 8 passed`。
- `python -m pytest local_life_agent/tests/test_p4_evidence_decision_answer_protocol.py -q`，结果：`4 passed`。
- `python -m pytest local_life_agent/tests/test_phase7_workflows.py -q`，结果：`10 passed`。
- `python -m pytest local_life_agent/tests/test_e2e_llm_main_path.py -q`，结果：`2 failed, 5 passed, 1 skipped`。
- `python -m pytest local_life_agent/tests/test_comprehensive_graph_e2e.py -q`，结果：`27 passed`。
- `python -m pytest local_life_agent/tests/test_single_coupon_flow.py -q`，结果：`6 passed`。
- `python -m pytest local_life_agent/tests/test_comparison_flow.py -q`，结果：`24 passed`。
- `python -m pytest local_life_agent/tests/test_recommendation_flow.py -q`，结果：`4 failed, 13 passed, 2 xfailed`。
- `python -m pytest local_life_agent/tests/test_single_shop_multifacet.py -q`，结果：`7 passed`。

## 失败集中点
- `test_llm_verbalizer.py` 失败集中在 `DecisionPlan` 缺少 `fallback_template_type`、LLM disabled / failure 期望与当前 metadata 不一致、以及确定性 composer 的 fallback 路径。
- `test_e2e_llm_main_path.py` 失败集中在指代/序号跟随主路径时，实际走到了 `clarification_fallback_workflow`，没有保持期望的 deterministic / tool workflow。
- `test_recommendation_flow.py` 失败集中在推荐结果过滤、`last_recommendation_list` 写回、以及后续“第一家”引用仍未触发预期工具链。

## 进入第 1 批前的风险
- `response_subgraph` 的空证据/空草稿验证短路需要重点处理，否则会产生“没证据也通过”的假阳性。
- `llm_verbalizer` 与 `deterministic composer` 的契约还没对齐，`fallback_template_type` 相关失败已经在测试中暴露。
- 推荐流对 closed / failed shop 的过滤与后续跟随引用不稳定，可能影响多轮对话的正确性。
- 当前会话存储还是进程内内存，实现上适合单机测试，不适合作为“已冻结”的跨进程事实基础。
- 当前 Pydantic 仍有 location 字段的序列化 warning，说明部分 schema / payload 形状还存在边界不一致。

## 是否建议进入第 1 批
- 建议：`可以进入，但只能以最小安全边界进入`。
- 最小安全边界：优先修 `llm_verbalizer` / `deterministic composer` 对齐问题、`response_subgraph` 的空证据验证短路、推荐流的写回与过滤，再碰更大范围的三层重构。

## 业务代码修改情况
- 本批次未修改业务代码。
- 本批次仅新增事实冻结报告文件：`todo/three_layer_phase0_fact_freeze_report.md`。
