# 9. Review / Observe / Sufficiency Check 设计

> 本文档是本次整改的主文档。
>
> LocalLifeAgent 的目标架构应从：
>
> `CandidateSet 驱动的 Plan-Execute`
>
> 升级为：
>
> `CandidateSet 驱动的受控 Plan-Execute-Review`

---

## 9.1 目标架构与不变边界

最终主链路：

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

必须强调：

1. `Plan-Execute` 不能只做 plan 和 execute
2. `Review` 是执行过程中的观察与决策阶段
3. `AnswerVerifier` 不能替代过程 Review
4. `ToolCallGateway` 仍是唯一工具执行入口
5. LLM 不允许直接调用工具
6. `top_intent_router` 在 P0 不修改
7. 非 `local_life` 仍必须直接 `emit_response`
8. `CandidateSet / CandidateReview` 只作用于 `local_life` 分支

---

## 9.2 Review 不是一个大节点，而是一组 Gate

Review 不应设计成一个大一统 `review_node`，也不应形成新的 300 行规则堆叠函数。

Review 必须拆成分阶段 Gate：

1. `GoalReview`
2. `CandidateReview`
3. `EvidenceReview`
4. `DecisionReview`
5. `AnswerReview / AnswerVerifier`

统一原则：

1. 每个 Review 只检查自己阶段的输入输出
2. Review 只能输出结构化判断和 `next_action`
3. Review 不允许修改 `ToolResult / EvidencePack` 的事实值

---

## 9.3 SufficiencyCheckResult 与 ToolResult

```python
class ReviewStage(str, Enum):
    GOAL_REVIEW = "goal_review"
    CANDIDATE_REVIEW = "candidate_review"
    EVIDENCE_REVIEW = "evidence_review"
    DECISION_REVIEW = "decision_review"
    ANSWER_REVIEW = "answer_review"


class ReviewStatus(str, Enum):
    ENOUGH = "enough"
    NEED_MORE_CANDIDATES = "need_more_candidates"
    NEED_MORE_EVIDENCE = "need_more_evidence"
    NEED_CLARIFICATION = "need_clarification"
    CAN_DEGRADE = "can_degrade"
    UNSUPPORTED = "unsupported"
    FALLBACK = "fallback"


class NextAction(str, Enum):
    FINISH = "finish"
    EXPAND_SEARCH = "expand_search"
    REPLAN_EVIDENCE = "replan_evidence"
    CLARIFY = "clarify"
    DEGRADE_ANSWER = "degrade_answer"
    UNSUPPORTED_ANSWER = "unsupported_answer"
    FALLBACK = "fallback"


@dataclass
class SufficiencyCheckResult:
    stage: ReviewStage
    status: ReviewStatus
    next_action: NextAction
    missing_facets: list[str]
    unknown_facets: list[str]
    failed_tools: list[str]
    affected_candidates: list[str]
    reason: str
    confidence: Literal["high", "medium", "low"]
    trace_payload: dict
```

`ToolResult` 至少要求：

```python
@dataclass
class ToolResult:
    tool_name: str
    status: ToolStatus
    error_type: str | None
    retriable: bool
    source: str
    payload: dict | None = None
```

```python
class ToolStatus(str, Enum):
    OK = "ok"
    EMPTY = "empty"
    UNKNOWN = "unknown"
    FAILED = "failed"
    TIMEOUT = "timeout"
    UNSUPPORTED = "unsupported"
```

---

## 9.4 轻量 LocalLifeGoalDraft（P0）

P0 不完整重写 `GoalPlanner`，但也不能继续完全依赖旧 `task_type`。

因此在 `SemanticFrame → CandidateSpec` 之间增加轻量目标抽象：

```python
@dataclass
class LocalLifeGoalDraft:
    goal_type: GoalType
    candidate_source: CandidateSource
    candidate_category: str | None
    candidate_limit: int | None
    evidence_needs: list[str]
    required_facets: list[str]
    optional_facets: list[str]
    max_candidates: int = 5
    source_origin: str = "llm"
```

要求：

1. P0 不完整重写 `GoalPlanner`
2. P0 需要用 `LocalLifeGoalDraft` 承接 LLM 语义帧
3. `task_type` 只能作为兼容字段，不能继续作为唯一事实源
4. `candidate_source / candidate_limit / evidence_needs` 应优先来自 LLM `SemanticFrame`
5. 规则 fallback 只能补齐字段，不能静默覆盖 LLM 核心语义

---

## 9.5 Candidate / Goal 枚举设计

```python
class CandidateStatus(str, Enum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not_found"
    PARTIAL = "partial"
    TOO_MANY = "too_many"
    NEED_CLARIFICATION = "need_clarification"


class CandidateSource(str, Enum):
    EXPLICIT = "explicit"
    CONTEXT = "context"
    DISCOVERY = "discovery"
    MIXED = "mixed"


class GoalType(str, Enum):
    RECOMMENDATION = "recommendation"
    COMPARISON = "comparison"
    SINGLE_SHOP_QUERY = "single_shop_query"
    REFINEMENT = "refinement"
    UNSUPPORTED = "unsupported"
```

要求：

1. `CandidateSet.status` 必须使用 `CandidateStatus`
2. `CandidateSet.source` 必须使用 `CandidateSource`
3. `ReviewStatus / NextAction` 继续使用枚举
4. 文档中不要继续使用自由字符串描述关键状态

---

## 9.6 candidate_limit 默认值策略

统一为：

```python
candidate_limit: int | None = None
```

默认策略由 `GoalPolicy / LocalLifeGoalDraft` 决定：

1. comparison 默认 2
2. recommendation 默认 3
3. single_shop_query 默认 1
4. `max_allowed` 默认 5
5. 用户显式指定数量时，先尊重用户数量，再由 `CandidateReview` 检查是否超过 `max_allowed`
6. 超过 `max_allowed` 时，不能直接规划全部候选，只能裁剪并说明、澄清或降级

---

## 9.7 slot_extractor fallback 边界

LLM 是 `SemanticFrame` 的主事实源。

`slot_extractor` 只能做：

1. 字段补齐
2. 别名标准化
3. 序号引用提取
4. 明显缺失字段的 fallback

`slot_extractor` 不允许静默改写：

1. `task_type / goal_type`
2. `candidate_source`
3. `candidate_limit`
4. `required_facets`
5. comparison / recommendation 的核心意图

如果 fallback 参与补齐，必须写入：

1. `semantic_source`
2. `candidate_source_origin`
3. `fallback_reason`
4. `execution_trace`

---

## 9.8 CandidateReview 设计与 P0 边界

### CandidateReview 职责

1. 判断 `CandidateSet.status`
2. 判断候选数量是否满足 `min_required`
3. 判断候选数量是否超过 `max_allowed`
4. 去重 `shop_id`
5. mixed candidate 去重后重新检查数量
6. 输出统一 `SufficiencyCheckResult`

### P0 的 next_action 边界

P0 阶段 `CandidateReview.next_action` 只允许：

1. `finish`
2. `clarify`
3. `fallback`

如果文档保留 `expand_search` 枚举，也只允许作为后续阶段预留，不允许 P0 graph 真正跳转到未实现节点。

这里的 `finish` 只表示候选阶段通过，可以进入 `EvidencePlanner` 或旧 planner 兼容链路，不表示直接生成最终回答。

### P0 典型判断

1. 候选足够 -> `finish`
2. 候选不足：
   - `status = NEED_MORE_CANDIDATES`
   - P0 中 `next_action = CLARIFY` 或 `FALLBACK`
   - P2 才允许 `next_action = EXPAND_SEARCH`
3. 候选超限：
   - 如果允许自动裁剪，则 `next_action = finish`
   - `trace_payload` 写入 `trimmed=true / original_count / kept_count`
   - 如果不允许自动裁剪，则 `next_action = clarify`
4. 不建议在 CandidateReview 阶段直接 `degrade_answer`，除非无法继续执行
5. 结构异常 -> `fallback`

---

## 9.9 EvidenceReview / DecisionReview / AnswerVerifier 的阶段边界

### P1：EvidenceReview

负责：

1. required / optional facet
2. `ok / empty / unknown / failed`
3. `unknown_as_false / failed_as_empty`

### P2：DecisionReview

负责：

1. `finish / replan / degrade / fallback`
2. `need_more_evidence / need_more_candidates` 真正驱动 graph

### AnswerVerifier

只负责最终自然语言事实校验：

1. `unsupported_fact`
2. `shop_id_mismatch`
3. `unknown_as_false`
4. `tool_failure_hidden`
5. `ranking_changed_by_llm`

它不替代过程 Review。

---

## 9.10 Failure Handling / Retry Policy

核心原则：

1. Retry 只处理 transient failure
2. Review / Replan 处理信息不足
3. P0 不输出未实现 `next_action`

阶段级策略摘要：

| 阶段 | 是否 retry | 失败处理 |
|---|---|---|
| P0 CandidateReview | 不 retry | `finish / clarify / fallback` |
| P1 EvidenceReview | 不直接 retry | `replan_evidence / can_degrade / fallback` |
| P2 DecisionReview | 不 retry | `finish / replan / degrade / fallback` |
| AnswerVerifier | 有限 rewrite | 最多 1-2 次，仍失败 fallback |

---

## 9.11 禁止规则堆叠式修 bug

禁止做法：

1. 不要继续在 `_h_target_resolve` 中增加大量 `if/elif` 特判
2. 不要把 discovery comparison、context comparison、mixed comparison 都塞回 `target_resolve`
3. 不要用关键词规则覆盖 LLM 语义帧
4. 不要让 `validator` 改写语义
5. 不要新增 legacy fallback 静默覆盖主链路
6. 不要把 bug 修成“针对某句测试样例”的硬编码

正确分类：

1. 语义解析问题 -> 修 `SemanticFrame / prompt / schema`
2. 轻量目标抽象问题 -> 修 `LocalLifeGoalDraft`
3. 候选解析问题 -> 修 `CandidateSpec / CandidateResolver`
4. 候选 sufficiency 问题 -> 修 `CandidateReview`
5. 证据 unknown / failed 问题 -> 修 `EvidenceReview`
6. 决策问题 -> 修 `DecisionReview`
7. 回答越界问题 -> 修 `AnswerVerifier / AnswerGenerator prompt`

---

## 9.12 P0 / P1 / P2 阶段验收边界

### P0

1. 必须进入 discovery CandidateSet
2. 不能强行比较 1 家
3. 不能直接规划 10 家详细 ToolPlan
4. 非 `local_life` 不进入 `CandidateResolver`
5. 不输出 dangling `next_action`

### P1

1. `unknown_as_false` 被拦截
2. `failed_as_empty` 被拦截
3. `ToolResult.status` 进入 `EvidenceReview`

### P2

1. `GoalPlanner / DecisionPlanner / DecisionReview` 真正接管旧硬分流
2. `need_more_evidence / need_more_candidates` 真正驱动 graph
3. `SessionState` 扩展稳定落地

---

## 9.13 最终验收标准

1. CandidateSet 不足时不会强行比较
2. required evidence unknown 时不会输出确定性结论
3. 不会把 `failed` 当 `empty`
4. `next_action` 使用枚举，不是自由字符串
5. P0 不输出未实现 `next_action`
6. CandidateReview 的 `finish` 不表示最终回答完成
6. `task_type` 不再作为本地生活新链路唯一事实源
7. fallback 不静默覆盖 LLM 核心语义
8. 非 `local_life` 仍直达 `emit_response`
9. `CandidateSet / CandidateReview` 不污染非本地生活分支
10. `ToolCallGateway` 仍是唯一工具执行入口

---

## 9.14 本次整改结论

本次整改后，LocalLifeAgent 的文档边界应理解为：

1. P0 是“候选发现 + 候选 sufficiency 收口”
2. P1 是“证据 sufficiency 与事实错误收口”
3. P2 才是“完整 Plan-Execute-Review 控制链接管旧硬分流”

也就是说，当前目标不是一次性完成完整 Replan 架构，而是按阶段稳定落地。
