## 13. P0 验收 Prompt

```text
请你作为资深 Agent 架构师和测试负责人，对当前 P0 改造做严格验收。

验收范围：
P0 只应包含 LocalLifeGoalDraft + CandidateSet + CandidateResolver + CandidateReview，不应包含 P1/P2 内容。

请检查：
1. 是否新增 CandidateSpec / ResolvedCandidate / CandidateSet。
2. 是否新增 LocalLifeGoalDraft。
3. 是否新增 CandidateResolver，并拆分 explicit / context / discovery / mixed。
4. 是否新增 CandidateReview，并输出 SufficiencyCheckResult。
5. CandidateStatus / CandidateSource / GoalType / ReviewStatus / NextAction 是否全部枚举化。
6. P0 CandidateReview 是否只输出 FINISH / CLARIFY / FALLBACK。
7. 是否没有输出 EXPAND_SEARCH / REPLAN_EVIDENCE 等 dangling action。
8. _h_target_resolve 是否变成薄调度层，而不是继续增长 if/else。
9. discovery comparison 是否能通过 CandidateSet，不再要求补充另一家店名。
10. 候选不足是否会被 CandidateReview 拦截。
11. 候选超限是否会裁剪或澄清，并写 trimming trace。
12. mixed candidate 去重后不足是否不能继续比较。
13. review_results.candidate_review 是否写入 GraphState。
14. execution_trace 是否能看到 candidate_review。
15. explicit comparison 是否不回归。
16. recommendation 是否不回归。
17. single_shop_query 是否不回归。
18. 非 local_life 是否仍直接 emit_response。
19. top_intent_router 行为是否未被改动。
20. slot_extractor 是否只补齐字段，不静默覆盖 LLM 核心语义。
21. fallback 是否记录 semantic_source / candidate_source_origin / fallback_reason / trace。
22. ToolResult 是否至少有 status / error_type / retriable / source。
23. 是否存在把旧规则搬家到 CandidateResolver 的迹象。
24. 是否存在只改最终话术而没有改结构化链路的情况。

请输出：
A. 总评分：0-10 分
B. 是否允许进入 P1：允许 / 不允许
C. P0 阻塞问题列表，按 P0/P1/P2 归类
D. 每个问题的文件位置、原因、建议修复方式
E. 必须补充的测试
F. 已通过的关键测试
G. 最终结论：严格通过 / 基本通过但不能进 P1 / 不通过
```

---

## 14. P0 通过标准

```text
[ ] discovery comparison 进入 CandidateSet
[ ] 1 家候选不能强行比较
[ ] 10 家候选触发 max_allowed
[ ] mixed 去重后不足不能比较
[ ] candidate_review 写入 trace
[ ] P0 不输出 EXPAND_SEARCH / REPLAN_EVIDENCE
[ ] explicit comparison 不回归
[ ] recommendation 不回归
[ ] single_shop_query 不回归
[ ] 非 local_life 直达不回归
```


## 14. P1 验收 Prompt

```text
请你作为资深 Agent 架构师和测试负责人，对当前 P1 改造做严格验收。

验收范围：
P1 应包含 EvidencePlanner + EvidenceReview，不应提前进入完整 P2。

请检查：
1. 是否新增 EvidencePlanner。
2. 是否新增 EvidenceReview。
3. facet_plan / comparison_planner 是否已变为 EvidencePlanner 兼容壳，而不是继续各自硬分流。
4. EvidencePlanner 是否基于 CandidateSet + evidence_needs + required_facets + optional_facets 生成 ToolPlan。
5. EvidencePlanner 是否不判断证据 sufficiency。
6. plan_validator 是否仍只做工具合法性校验。
7. ToolCallGateway 是否仍是唯一工具执行入口。
8. ToolResult 是否标准化为 ok / empty / unknown / failed / timeout / unsupported。
9. ToolResult 是否带有 status / error_type / retriable / source / payload。
10. EvidenceBuild / EvidencePack 是否保留 ToolResult.status。
11. EvidenceReview 是否检查 required / optional facet。
12. EvidenceReview 是否区分 empty 和 unknown。
13. EvidenceReview 是否区分 failed 和 empty。
14. EvidenceReview 是否不会把 failed 包装成 empty。
15. EvidenceReview 是否不会把 unknown 当 false。
16. A coupon ok，B coupon unknown 时，是否不会说 A 一定更优惠。
17. get_coupon_list failed 时，是否不会说没有券。
18. check_open_status failed 时，是否不会说未营业。
19. optional facet 缺失时，是否允许降级并说明未知项。
20. required facet unknown 时，是否进入 replan_evidence / degrade_answer / fallback / clarify。
21. EvidenceReview.next_action 是否使用枚举。
22. review_results.evidence_review 是否写入 GraphState。
23. execution_trace 是否能看到 evidence_review。
24. AnswerVerifier 是否仍作为最终事实校验，而不是替代 EvidenceReview。
25. P0 CandidateReview 是否不回归。
26. discovery comparison 是否不回归。
27. explicit comparison 是否不回归。
28. recommendation 是否不回归。
29. single_shop_query 是否不回归。
30. 非 local_life 是否仍直接 emit_response。
31. 是否存在让 LLM 主观判断“信息够了”的实现。
32. 是否存在只改话术、不改证据状态的实现。

请输出：
A. 总评分：0-10 分
B. 是否允许进入 P2：允许 / 不允许
C. P1 阻塞问题列表，按 P0/P1/P2 归类
D. 每个问题的文件位置、原因、建议修复方式
E. 必须补充的测试
F. 已通过的关键测试
G. unknown_as_false / failed_as_empty 是否严格通过
H. 最终结论：严格通过 / 基本通过但不能进 P2 / 不通过
```

---

## 15. P1 通过标准

```text
[ ] EvidencePlanner 统一 ToolPlan
[ ] facet_plan / comparison_planner 成为兼容壳
[ ] required / optional facet 区分
[ ] ToolResult.status 全链路保留
[ ] unknown_as_false 被拦截
[ ] failed_as_empty 被拦截
[ ] open_status failed 不说未营业
[ ] coupon failed 不说没有券
[ ] evidence_review 写入 trace
[ ] P0 回归全部通过
```


## 18. P2 验收 Prompt

```text
请你作为资深 Agent 架构师和测试负责人，对当前 P2 改造做严格验收。

验收范围：
P2 应包含 GoalPlanner + GoalReview + DecisionPlanner + DecisionReview + Replan，并在 P0/P1 已通过基础上接管旧硬分流。

请检查：
1. GoalPlanner 是否真正取代旧 task_type 作为本地生活业务目标抽象主控层。
2. task_type 是否已降级为兼容字段，而不是最高事实源。
3. GoalPlanner 是否不直接生成 ToolPlan。
4. GoalPlanner 是否不执行工具。
5. GoalReview 是否检查目标清晰度、可执行性、能力范围。
6. GoalReview 是否能处理 unsupported，例如“帮我订座”不伪造成功。
7. GoalReview 是否能处理目标不清晰并输出 clarify。
8. CandidateResolver / CandidateReview 是否仍稳定工作。
9. EvidencePlanner / EvidenceReview 是否仍稳定工作。
10. DecisionPlan 是否有明确结构。
11. DecisionPlan 中 claims 是否都能绑定 EvidencePack。
12. DecisionPlan 是否记录 unknown_facets / failed_facets。
13. DecisionPlan 是否不会提到未查询店铺。
14. DecisionPlanner 是否不新增 evidence。
15. DecisionPlanner 是否不直接输出最终自然语言。
16. DecisionReview 是否能判断 finish。
17. DecisionReview 是否能判断 replan_evidence。
18. DecisionReview 是否能判断 expand_search。
19. DecisionReview 是否能判断 degrade_answer。
20. DecisionReview 是否能判断 unsupported_answer。
21. DecisionReview 是否能判断 fallback。
22. DecisionReview 是否能拦截证据不足但给出 winner 的情况。
23. EvidenceReview.need_more_evidence 是否能驱动 replan_evidence。
24. CandidateReview.need_more_candidates 是否能驱动 expand_search 或 clarify。
25. expand_search 是否有最大次数限制。
26. replan_evidence 是否有最大次数限制。
27. rewrite 是否有最大次数限制。
28. 是否不存在 dangling next_action。
29. 所有 next_action 是否都是枚举。
30. SessionState 是否增加 last_candidate_set / active_goal / evidence_cache / review_results / last_decision_plan / replan_counters。
31. 多轮“推荐 → 这两家比一下 → 便宜一点的呢”是否能稳定工作。
32. old route_task / _route_task_plan / task_router 硬分流是否已降级为兼容壳或明确废弃计划。
33. facet_plan / comparison_planner 是否不再各自承担核心决策。
34. AnswerGenerator 是否只基于 DecisionPlan 表达，不新增事实，不改 winner。
35. AnswerVerifier 是否仍拦截 unsupported_fact / shop_id_mismatch / unknown_as_false / failed_as_empty / ranking_changed_by_llm。
36. ToolCallGateway 是否仍是唯一工具执行入口。
37. plan_validator 是否仍能阻止非法 ToolPlan。
38. 非 local_life 是否仍直接 emit_response。
39. CandidateSet / Review 是否没有污染非 local_life。
40. P0/P1 回归测试是否全部通过。
41. 是否存在继续往 graph_builder.py 堆特殊 case 的情况。
42. 是否存在把 Review 完全交给 LLM 主观判断的情况。

请输出：
A. 总评分：0-10 分
B. 是否最终通过：通过 / 不通过
C. 阻塞问题列表，按 Goal / Candidate / Evidence / Decision / Answer / Trace / Session / 非 local_life 分类
D. 每个问题的文件位置、原因、建议修复方式
E. 必须补充的测试
F. 已通过的关键测试
G. 旧节点降级是否安全
H. 是否存在规则堆叠复发
I. 最终结论：严格通过 / 基本通过但需补强 / 不通过
```

---

## 19. P2 通过标准

```text
[ ] GoalPlanner 接管旧 task_type 硬分流
[ ] GoalReview 能 unsupported / clarify / finish
[ ] DecisionPlanner 生成 DecisionPlan
[ ] DecisionReview 能 finish / replan / degrade / fallback
[ ] EvidenceReview.need_more_evidence 驱动 replan_evidence
[ ] CandidateReview.need_more_candidates 驱动 expand_search 或 clarify
[ ] SessionState 扩展稳定落地
[ ] 所有 next_action 有 graph 路由
[ ] 无 dangling action
[ ] 旧节点安全降级
[ ] P0/P1 回归全部通过
```
