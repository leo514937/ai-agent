# P1 执行与验收 Prompt：EvidencePlanner + EvidenceReview

> 适用对象：opencode / Codex / 代码执行 Agent  
> 适用仓库：`D:\javacode\hm-dianping`  
> 当前阶段：P1  
> 阶段目标：在 P0 CandidateSet 稳定基础上，落地证据规划与证据 sufficiency Review，防止 unknown_as_false / failed_as_empty。

---

## 1. P1 前置条件

只有 P0 满足以下条件后，才能进入 P1：

1. P0 trace 验收通过
2. discovery CandidateSet 正常工作
3. 候选不足不会强行比较
4. 候选超限会裁剪或澄清
5. mixed 去重后不足不能继续比较
6. `candidate_review` 已写入 `review_results`
7. 非 `local_life` 仍直接 `emit_response`
8. P0 不输出 dangling `next_action`

---

## 2. P1 目标

P1 只解决证据 sufficiency 与事实错误收口。

必须实现：

1. `EvidencePlanner`
2. `EvidenceReview`
3. required / optional facet 区分
4. `ToolResult.status` 全链路传递
5. `ok / empty / unknown / failed / timeout / unsupported` 区分
6. `can_degrade`
7. 防止 `unknown_as_false`
8. 防止 `failed_as_empty`
9. `review_results.evidence_review` 写入 trace
10. `facet_plan / comparison_planner` 改为 EvidencePlanner 兼容壳

---

## 3. P1 禁止事项

本阶段不要做：

1. 不做完整 `GoalPlanner` 接管
2. 不删除 `task_router`
3. 不删除 `facet_plan / comparison_planner`
4. 不做完整 `DecisionPlanner`
5. 不做完整 `DecisionReview`
6. 不做完整 `expand_search` loop
7. 不做复杂 `next_goal`
8. 不扩展完整长期 SessionState
9. 不让 LLM 主观判断“信息差不多够了”
10. 不让 AnswerVerifier 替代 EvidenceReview
11. 不让 plan_validator 做证据 sufficiency 判断
12. 不让 ToolCallGateway 做业务判断

---

## 4. P1 新增文件建议

```text
planning/evidence_planner.py
planning/evidence_review.py
domain/evidence.py
domain/tool_result.py
tests/test_evidence_planner.py
tests/test_evidence_review.py
tests/test_evidence_review_in_graph.py
tests/test_tool_result_status.py
tests/test_unknown_failed_handling.py
```

如果已有等价文件，优先复用。

---

## 5. P1 修改文件建议

```text
planning/facet_planner.py
planning/comparison_planner.py
engine/graph_builder.py
tools/tool_gateway.py 或等价 ToolCallGateway 文件
answer/answer_plan_builder.py
answer/verifier.py
domain/graph_state.py
```

---

## 6. ToolResult 标准化要求

所有工具结果必须标准化为：

```python
class ToolStatus(str, Enum):
    OK = "ok"
    EMPTY = "empty"
    UNKNOWN = "unknown"
    FAILED = "failed"
    TIMEOUT = "timeout"
    UNSUPPORTED = "unsupported"


@dataclass
class ToolResult:
    tool_name: str
    status: ToolStatus
    error_type: str | None
    retriable: bool
    source: str
    payload: dict | None = None
```

语义要求：

1. `OK`：工具成功且有有效 payload。
2. `EMPTY`：工具成功执行，确定没有数据。
3. `UNKNOWN`：无法确认，不得表达为“没有”。
4. `FAILED`：工具失败，不得表达为“没有”。
5. `TIMEOUT`：超时，不得表达为“没有”。
6. `UNSUPPORTED`：能力不支持，不得伪造结果。

---

## 7. EvidencePlanner 职责

`EvidencePlanner` 根据以下输入生成统一 `ToolPlan`：

```text
LocalLifeGoalDraft / Goal
CandidateSet
evidence_needs
required_facets
optional_facets
```

职责：

1. 为每个候选生成必要工具调用。
2. 区分 required facet 和 optional facet。
3. 避免重复工具调用。
4. 控制工具预算。
5. 输出给 `plan_validator` 校验。
6. 不判断证据是否足够。
7. 不直接执行工具。
8. 不绕过 ToolCallGateway。

示例：

用户问：

```text
对比附近评分最高的两家KTV，看看谁的优惠券多，营业状态如何
```

EvidencePlanner 应规划：

```text
对候选 A：
- get_coupon_list / get_deal_list
- check_open_status
- 可选 get_shop_review_summary / get_shop_cards

对候选 B：
- get_coupon_list / get_deal_list
- check_open_status
- 可选 get_shop_review_summary / get_shop_cards
```

其中：

```text
coupon_list / deal_list = required
open_status = required
review_summary / shop_cards = optional，除非用户显式要求评价/环境/评分
```

---

## 8. EvidenceReview 职责

`EvidenceReview` 输入：

```text
Goal / LocalLifeGoalDraft
CandidateSet
EvidencePack
ToolResult 列表
required_facets
optional_facets
```

输出：

```text
SufficiencyCheckResult(stage=EVIDENCE_REVIEW, ...)
```

必须判断：

1. required facet 是否都已查询。
2. required facet 是否有 `ok / empty` 这样的确定结果。
3. required facet 是否出现 `unknown / failed / timeout / unsupported`。
4. optional facet 缺失是否允许降级。
5. 工具失败是否被错误包装成 empty。
6. unknown 是否被用于确定性结论。
7. 是否需要 `replan_evidence`。
8. 是否可以 `degrade_answer`。
9. 是否需要 `fallback`。
10. 是否需要 `clarify`。

---

## 9. P1 next_action 允许范围

P1 的 `EvidenceReview.next_action` 允许：

```text
FINISH
REPLAN_EVIDENCE
DEGRADE_ANSWER
FALLBACK
CLARIFY
```

使用原则：

1. `FINISH`：证据足够，可以进入 DecisionPlanner 或旧 AnswerPlan 兼容链路。
2. `REPLAN_EVIDENCE`：缺 required facet，且有可补查工具。
3. `DEGRADE_ANSWER`：部分 optional 或非核心 required 不足，但可以安全说明未知项。
4. `FALLBACK`：核心证据失败，无法安全回答。
5. `CLARIFY`：用户目标或 facet 需求不清楚。

---

## 10. P1 必须防止的错误

### 10.1 unknown_as_false

错误：

```text
B 店优惠券查询 unknown
回答：A 店优惠券更多
```

正确：

```text
A 店查到了优惠券；B 店优惠券信息暂时无法确认，所以不能确定 A 一定更优惠。
```

### 10.2 failed_as_empty

错误：

```text
get_coupon_list failed
回答：这家没有券
```

正确：

```text
优惠券查询失败，不能确认是否有券。
```

### 10.3 open_status failed_as_closed

错误：

```text
check_open_status failed
回答：这家未营业
```

正确：

```text
营业状态暂时无法确认。
```

### 10.4 optional 当 required

错误：

```text
用户只问优惠券，review_summary 失败，直接 fallback
```

正确：

```text
优惠券 required 已满足时，可以回答优惠券；评价摘要失败只作为未知项说明或不展开。
```

---

## 11. P1 Graph 接线要求

P1 新链路应为：

```text
CandidateReview.finish
→ EvidencePlanner
→ plan_validator
→ ToolExecute
→ EvidenceBuild / EvidencePack
→ EvidenceReview
→ old answer_plan_build 兼容链路 或 P2 DecisionPlanner 预留入口
```

要求：

1. `review_results.evidence_review` 写入 GraphState。
2. `execution_trace` 能看到 evidence_review。
3. `ToolResult.status` 必须进入 EvidencePack。
4. `EvidenceReview.need_more_evidence` 不得直接生成确定性回答。
5. `EvidenceReview.can_degrade` 可以进入降级回答，但必须说明未知项。
6. P1 不要求完整 replan loop，但不能把 `REPLAN_EVIDENCE` 写成 dangling action 后直接崩溃。
7. 如 P1 暂不启用真实 replan，必须安全降级为 `DEGRADE_ANSWER / FALLBACK`，并写 trace。

---

## 12. P1 必测场景

1. A coupon ok，B coupon unknown
   - 不能说 A 一定更优惠
2. A coupon ok，B coupon empty
   - 可以说 A 有券、B 暂无券
3. get_coupon_list failed
   - 不能说没有券
4. check_open_status failed
   - 不能说未营业
5. required facet unknown
   - 进入 `can_degrade / fallback / replan_evidence`
6. optional facet 缺失
   - 允许降级回答，但必须说明未查询或无法确认
7. EvidenceReview.need_more_evidence
   - 后续应进入 `replan_evidence` 或 P1 兼容降级，不得直接生成确定性回答
8. ToolExecute retry 后仍失败
   - 标记 `failed / unknown`，交 EvidenceReview
9. AnswerVerifier 仍拦截 unknown_as_false / failed_as_empty
10. P0 的 CandidateReview 能力不回归
11. discovery comparison 不回归
12. explicit comparison 不回归
13. recommendation 不回归
14. single_shop_query 不回归
15. 非 local_life 直达不回归

---

## 13. P1 执行 Prompt

```text
你现在要在 D:\javacode\hm-dianping 仓库中执行 P1：EvidencePlanner + EvidenceReview 改造。

前置条件：
P0 已通过，CandidateSet / CandidateResolver / CandidateReview 已稳定，candidate_review 已写入 trace。

严格要求：
1. 只做 P1，不进入 P2。
2. 不实现完整 GoalPlanner 接管。
3. 不实现完整 DecisionPlanner / DecisionReview。
4. 不删除旧 facet_plan / comparison_planner，只把它们改为 EvidencePlanner 兼容壳或逐步弱化。
5. 不删除 task_router。
6. 不做完整 expand_search loop。
7. 不让 LLM 判断“信息差不多够了”。
8. ToolCallGateway 仍是唯一工具执行入口。
9. plan_validator 仍只做工具计划合法性校验，不做 sufficiency。
10. EvidencePlanner 只负责生成 ToolPlan，不判断证据是否足够。
11. EvidenceReview 只判断证据 sufficiency，不修改 ToolResult / EvidencePack 事实。
12. 必须区分 required / optional facet。
13. 必须区分 ToolResult 的 ok / empty / unknown / failed / timeout / unsupported。
14. 必须防止 unknown_as_false。
15. 必须防止 failed_as_empty。
16. check_open_status failed 时不能说未营业。
17. get_coupon_list failed 时不能说没有券。
18. optional facet 缺失时允许降级，但必须说明未知项。
19. required facet unknown 时必须进入 replan_evidence / degrade_answer / fallback / clarify 中的合理分支。
20. review_results.evidence_review 和 execution_trace 必须可观测。
21. P0 的 CandidateReview 测试必须全部继续通过。
22. 非 local_life 仍不能进入 CandidateSet / EvidencePlanner / EvidenceReview。

完成后输出：
1. 修改文件清单
2. 新增测试清单
3. EvidencePlanner 如何接管 facet_plan / comparison_planner
4. ToolResult 标准化结果
5. EvidenceReview 的 status / next_action 映射
6. unknown_as_false / failed_as_empty 验收结果
7. P0 回归测试结果
8. P1 完成标准逐项勾选
9. 如果有未完成项，明确说明原因和下一步，不要假装完成
```

---

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
