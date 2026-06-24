# P2 执行与验收 Prompt：GoalPlanner + DecisionPlanner + DecisionReview + Replan

> 适用对象：opencode / Codex / 代码执行 Agent  
> 适用仓库：`D:\javacode\hm-dianping`  
> 当前阶段：P2  
> 阶段目标：在 P0/P1 稳定基础上，完整接管旧 task_type 硬分流，落地 Goal / Decision / Replan 闭环。

---

## 1. P2 前置条件

只有 P1 满足以下条件后，才能进入 P2：

1. P0 CandidateSet / CandidateReview 不回归
2. EvidencePlanner 接管工具计划生成
3. EvidenceReview 能识别 required / optional facet
4. ToolResult.status 全链路传递
5. unknown_as_false 被拦截
6. failed_as_empty 被拦截
7. `evidence_review` 写入 trace
8. P1 端到端验收通过

---

## 2. P2 目标

P2 才开始完整接管旧硬分流。

必须实现：

1. `GoalPlanner`
2. `GoalReview`
3. `DecisionPlanner`
4. `DecisionReview`
5. `DecisionPlan`
6. `replan_evidence`
7. `expand_search`
8. `next_goal`
9. SessionState 扩展
10. 旧 `task_type` 硬分流降级
11. 旧 `facet_plan / comparison_planner / answer_plan_build` 降级为兼容壳或逐步废弃
12. `review_results.goal_review / decision_review` 写入 trace

---

## 3. P2 禁止事项

本阶段不要做：

1. 不直接删除旧节点后再补新链路
2. 不一次性移除所有兼容壳
3. 不让 DecisionPlanner 新增未查询事实
4. 不让 DecisionReview 新增 evidence
5. 不让 AnswerGenerator 改 winner
6. 不让 LLM 直接输出 tool_calls
7. 不让非 local_life 进入 GoalPlanner / CandidateSet / EvidencePlanner
8. 不把 replan 做成无限循环
9. 不把 expand_search 做成无限循环
10. 不让 rewrite 无限循环
11. 不让 validator 改写语义
12. 不让 plan_validator 判断 sufficiency

---

## 4. P2 新增文件建议

```text
planning/goal_planner.py
planning/goal_review.py
planning/decision_planner.py
planning/decision_review.py
planning/replan_policy.py
domain/goal.py
domain/decision.py
domain/session_state.py
tests/test_goal_planner.py
tests/test_goal_review.py
tests/test_decision_planner.py
tests/test_decision_review.py
tests/test_replan_policy.py
tests/test_session_state_review.py
tests/test_p2_end_to_end.py
```

如果项目已有等价文件，优先复用。

---

## 5. P2 修改文件建议

```text
engine/graph_builder.py
planning/task_router.py
planning/facet_planner.py
planning/comparison_planner.py
answer/answer_plan_builder.py
answer/llm_verbalizer.py
answer/verifier.py
domain/graph_state.py
session/session_store.py 或等价 SessionState 文件
```

---

## 6. P2 最终目标链路

最终目标链路：

```text
SemanticFrame
→ GoalPlanner
→ GoalReview
→ CandidateResolver
→ CandidateReview
→ EvidencePlanner
→ plan_validator
→ ToolExecute
→ EvidenceBuild / EvidencePack
→ EvidenceReview
→ DecisionPlanner
→ DecisionReview
→ AnswerGenerate
→ AnswerVerifier
→ final_response
→ state_update / trace
```

要求：

1. `ToolCallGateway` 仍是唯一工具执行入口。
2. LLM 不允许绕过注册层直接调用工具。
3. `plan_validator` 只校验工具计划合法性，不判断信息是否足够。
4. Review 负责过程中的 sufficiency 判断。
5. AnswerVerifier 只做最终自然语言事实校验。
6. 非 `local_life` 必须继续直接 `emit_response`。

---

## 7. GoalPlanner 职责

`GoalPlanner` 取代旧 `task_type` 作为本地生活业务目标抽象的主控层。

输入：

```text
SemanticFrame
SessionState
用户当前输入
上下文
```

输出：

```text
Goal / LocalLifeGoal
candidate_source
candidate_limit
evidence_needs
required_facets
optional_facets
constraints
unsupported_reason
```

职责：

1. 生成可执行目标。
2. 明确 goal_type。
3. 明确候选来源。
4. 明确证据需求。
5. 明确 required / optional facet。
6. 明确是否 unsupported。
7. 不直接生成 ToolPlan。
8. 不执行工具。
9. 不决定候选是否足够。
10. 不决定证据是否足够。

---

## 8. GoalReview 职责

位置：

```text
GoalPlanner 之后，CandidateResolver 之前
```

职责：

1. 检查目标是否清晰。
2. 检查目标是否可执行。
3. 检查是否在当前工具能力范围内。
4. 检查是否有足够候选来源描述。
5. 判断是否需要澄清。
6. 判断是否 unsupported。
7. 判断是否可以进入 CandidateResolver。

典型场景：

```text
帮我订座
→ 当前无 booking 工具
→ GoalReview.status = unsupported
→ next_action = unsupported_answer
```

```text
对比两家 KTV
→ 没有店名，也没有默认附近策略
→ GoalReview.status = need_clarification
→ next_action = clarify
```

```text
附近评分最高的两家 KTV 谁优惠券多
→ 目标清晰
→ status = enough
→ next_action = finish
```

---

## 9. DecisionPlan 结构建议

```python
@dataclass
class DecisionPlan:
    goal_id: str
    decision_type: str
    candidates: list[str]
    answerable_facets: list[str]
    unknown_facets: list[str]
    failed_facets: list[str]
    winner_shop_id: str | None
    ranking: list[dict]
    claims: list[dict]
    caveats: list[str]
    next_goal: dict | None = None
```

要求：

1. 所有 claims 必须能绑定 EvidencePack。
2. winner 必须基于 evidence，不允许 LLM 改 winner。
3. unknown facet 必须显式记录。
4. failed facet 必须显式记录。
5. 不允许提到未查询候选。
6. 不允许新增未绑定 shop_id 的店铺。

---

## 10. DecisionPlanner 职责

输入：

```text
Goal
CandidateSet
EvidencePack
EvidenceReview
```

输出：

```text
DecisionPlan
```

职责：

1. 基于 EvidencePack 生成结构化决策。
2. 汇总可回答 facet。
3. 汇总 unknown / failed facet。
4. 在证据足够时给出 ranking / winner。
5. 在证据不足时不强行给 winner。
6. 生成 answer plan 所需结构。
7. 不判断证据是否足够。
8. 不新增 evidence。
9. 不直接输出自然语言最终回答。

---

## 11. DecisionReview 职责

位置：

```text
DecisionPlanner 之后，AnswerGenerator 之前
```

职责：

1. 判断 DecisionPlan 是否覆盖用户核心问题。
2. 判断每个 required facet 是否有结论或 unknown 说明。
3. 判断是否错误地产生确定性 winner。
4. 判断是否需要 next_goal。
5. 判断是否需要 replan_evidence。
6. 判断是否需要 expand_search。
7. 判断是否可以 finish。
8. 判断是否需要 degrade_answer。
9. 判断是否需要 fallback。
10. 判断是否进入 AnswerGenerator。

判断原则：

1. 证据核心未知时，不允许输出确定性 winner。
2. 部分信息不足但核心问题可回答时，允许降级回答。
3. `EvidenceReview.need_more_evidence` 应转发为 `replan_evidence`，不能硬答。
4. `CandidateReview.need_more_candidates` 可以驱动 `expand_search` 或 `clarify`。
5. DecisionReview 不能新增 evidence。

---

## 12. P2 next_action 允许范围

P2 可以真正启用：

```text
FINISH
EXPAND_SEARCH
REPLAN_EVIDENCE
CLARIFY
DEGRADE_ANSWER
UNSUPPORTED_ANSWER
FALLBACK
```

要求：

1. 所有 next_action 必须是枚举。
2. 每个 next_action 必须有 graph 路由落地。
3. 不允许 dangling action。
4. `expand_search` 必须有最大次数限制。
5. `replan_evidence` 必须有最大次数限制。
6. rewrite 必须有最大次数限制。
7. 循环次数必须写 trace。

---

## 13. Replan 策略

### 13.1 expand_search

触发：

```text
CandidateReview.need_more_candidates
```

允许：

1. 放宽筛选条件
2. 扩大候选数量
3. 改用备用排序
4. 询问用户是否放宽条件

不允许：

1. 无限扩搜
2. 绕过 CandidateReview
3. 伪造候选

最大次数建议：

```text
max_expand_search_rounds = 1 或 2
```

### 13.2 replan_evidence

触发：

```text
EvidenceReview.need_more_evidence
DecisionReview 发现 required facet 缺失
```

允许：

1. 补查缺失 required facet
2. 替换失败工具的备用工具
3. 重试 transient failure 后仍失败时降级

不允许：

1. 把 unknown 说成 false
2. 把 failed 说成 empty
3. 无限补查

最大次数建议：

```text
max_replan_evidence_rounds = 1 或 2
```

### 13.3 degrade_answer

触发：

```text
EvidenceReview.can_degrade
DecisionReview.can_degrade
```

要求：

1. 明确说明哪些信息已确认。
2. 明确说明哪些信息无法确认。
3. 不输出确定性 winner，除非核心证据足够。
4. 不隐藏工具失败。
5. 不新增事实。

---

## 14. SessionState 扩展

P2 需要增加：

```text
last_candidate_spec
last_candidate_set
active_goal
evidence_cache
review_results
last_decision_plan
replan_counters
```

用途：

1. 多轮复用候选集。
2. 支持“这两家 / 刚才那几家 / 便宜一点的呢”。
3. 支持 evidence_cache，避免重复查。
4. 支持 replan 计数，防止无限循环。
5. 支持 trace 回放。

---

## 15. 旧节点降级策略

P2 稳定后逐步降级：

```text
route_task
_route_task_plan
task_router.py 中按 task_type 的硬分流
facet_plan
comparison_planner
answer_plan_build 旧逻辑
target_resolve 中大量 recommendation / comparison 特判
```

保留：

```text
hard_guard
top_intent_router
semantic_parse
frame_validator
plan_validator
ToolCallGateway
tool_execute
evidence_build
answer_verify
state_update_plan
persist_session_state
emit_response
```

原则：

1. 先兼容壳，后删除。
2. 先测试覆盖，后删除。
3. 不要先删路由再重构。
4. 不要让新旧职责混乱。

---

## 16. P2 必测场景

1. `这两家谁优惠券多？` 且一方 unknown
   - DecisionReview 阻止确定性 winner
2. `这家现在营业吗？` 且工具 failed
   - 不能说未营业，只能降级或 fallback
3. `附近评分最高的10家火锅都详细对比一下`
   - CandidateReview 触发 max_allowed
   - P2 可 expand_search / clarify，但不能直接规划 10 家详细 ToolPlan
4. `帮我订座`
   - GoalReview 返回 unsupported
   - 不伪造成功
5. EvidenceReview.need_more_evidence
   - 能驱动 replan_evidence
6. CandidateReview.need_more_candidates
   - 能驱动 expand_search 或 clarify
7. DecisionPlan 给出 winner 但证据不足
   - DecisionReview 拦截
8. Candidate 足够但 required facet 全 unknown
   - 不能进入确定性回答
9. 多轮：
   - 第一轮推荐
   - 第二轮“这两家比一下”
   - 第三轮“便宜一点的呢”
   - SessionState 能稳定保留 last_candidate_set / active_goal / evidence_cache
10. 非 local_life
   - 仍直接 emit_response

---

## 17. P2 执行 Prompt

```text
你现在要在 D:\javacode\hm-dianping 仓库中执行 P2：GoalPlanner + GoalReview + DecisionPlanner + DecisionReview + Replan 改造。

前置条件：
P0 CandidateSet / CandidateReview 已通过。
P1 EvidencePlanner / EvidenceReview 已通过。
unknown_as_false / failed_as_empty 已被 EvidenceReview 和 AnswerVerifier 拦截。

严格要求：
1. 只在 P0/P1 已通过基础上做 P2。
2. 不要直接删除旧节点后再补新链路。
3. 先做兼容壳，再逐步弱化旧 task_type 硬分流。
4. GoalPlanner 取代旧 task_type 作为本地生活业务目标抽象主控层。
5. GoalReview 检查目标是否清晰、可执行、受支持。
6. DecisionPlanner 只能基于 EvidencePack 生成 DecisionPlan，不能新增证据。
7. DecisionReview 判断 finish / replan_evidence / expand_search / degrade_answer / unsupported_answer / fallback。
8. DecisionReview 不能新增 evidence。
9. AnswerGenerator 只能基于 DecisionPlan 表达，不能新增事实，不能改 winner。
10. AnswerVerifier 仍做最终事实校验，不能替代过程 Review。
11. expand_search 必须有最大次数限制。
12. replan_evidence 必须有最大次数限制。
13. rewrite 必须有最大次数限制。
14. 所有 next_action 都必须是枚举，并且必须有 graph 路由落地。
15. 不允许 dangling action。
16. SessionState 必须扩展 last_candidate_set / active_goal / evidence_cache / review_results / last_decision_plan / replan_counters。
17. 非 local_life 不得进入 GoalPlanner / CandidateSet / EvidencePlanner / DecisionPlanner。
18. ToolCallGateway 仍是唯一工具执行入口。
19. plan_validator 仍负责工具计划合法性，不负责 sufficiency。
20. 不允许 LLM 判断“信息差不多够了”。
21. 不允许把 unknown 当 false。
22. 不允许把 failed 当 empty。
23. 不允许提到未查询、未绑定 shop_id 的店铺。
24. 不允许旧 route_task / facet_plan / comparison_planner 与新链路职责混乱。
25. 必须补充 GoalPlanner / GoalReview / DecisionPlanner / DecisionReview / Replan / SessionState 的单测与端到端测试。
26. 必须跑 P0/P1 回归测试。

完成后输出：
1. 修改文件清单
2. 新增测试清单
3. GoalPlanner 如何接管旧 task_type
4. GoalReview 的 unsupported / clarify / finish 规则
5. DecisionPlan 结构
6. DecisionReview 的 status / next_action 映射
7. expand_search / replan_evidence 的最大次数和 trace 记录
8. SessionState 扩展字段
9. 旧节点降级情况
10. P0/P1 回归结果
11. P2 完成标准逐项勾选
12. 如果有未完成项，明确说明原因和下一步，不要假装完成
```

---

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
