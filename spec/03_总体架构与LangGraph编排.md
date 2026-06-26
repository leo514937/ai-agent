# 03_总体架构与 LangGraph 编排

## 1. 架构定位

本项目不是多个场景 workflow 的集合，而是一个统一的本地生活 Agent。

单店查询、附近推荐、多店对比、多轮追问、候选澄清、条件筛选、场景化推荐，本质上都应被抽象为：

```text
用户目标 Goal
  → 候选对象 CandidateSet
  → 需要获取的证据 EvidencePlan
  → 工具执行 ToolResults
  → 信息充分性 Review
  → 基于证据的回答 Answer
```

因此，LangGraph 的职责不是为每种场景创建一条独立 workflow，而是控制一个统一的 Agent 主循环。

## 2. 顶层路由边界

顶层路由只做粗粒度入口判断，不能继续细分成大量业务 workflow。

顶层路由只允许三类结果：

```text
Direct Answer
Safety / Reject
Local Life Agent
```

### 2.1 Direct Answer

用于处理非本地生活问题、能力说明、普通闲聊、通用技术解释等。

示例：

- “你能做什么？”
- “你是谁？”
- “帮我解释一下 LangGraph。”
- “今天心情不好怎么办？”

Direct Answer 不进入本地生活工具链路。

### 2.2 Safety / Reject

用于处理违法、危险、越权、明显不可处理的问题。

### 2.3 Local Life Agent

只要用户问题涉及本地生活消费决策，都进入同一个 Local Life Agent 主链路。

包括：

- “海底捞怎么样？”
- “附近推荐几家火锅。”
- “这家有券吗？”
- “这三家哪个适合约会？”
- “便宜一点的呢？”
- “第一家和海底捞比呢？”

这些问题不能分别进入 `single_shop_workflow`、`recommend_workflow`、`compare_workflow`。它们都应进入统一的 Plan → Execute → Review 主循环。

## 3. 统一 LangGraph 主链路

推荐主链路如下：

```text
UserInput
  ↓
TopRouter
  ├── DirectAnswer
  ├── SafetyReject
  └── LocalLifeAgent
          ↓
      LoadSession
          ↓
      SemanticFrame
          ↓
      GoalPlan
          ↓
      CandidateDecision
          ↓
      EvidencePlan
          ↓
      PlanValidate
          ↓
      ToolExecute
          ↓
      EvidenceBuild
          ↓
      ReviewSufficiency
          ├── NeedClarify → ClarifyAnswer
          ├── NeedMoreEvidence → Replan / ToolExecute
          ├── CannotAnswerSafely → SafeFailureAnswer
          └── Sufficient → Verbalize
                                ↓
                         AnswerVerify
                                ↓
                         SaveSession
                                ↓
                         FinalAnswer
```

这里的 `CandidateDecision` 不是推荐专用节点，也不是对比专用节点，而是所有本地生活任务共用的候选对象决策层。

## 4. 场景不是分支，场景是计划参数

实现时必须避免以下设计：

```text
LocalLifeRouter
  ├── SingleShopWorkflow
  ├── RecommendWorkflow
  ├── CompareWorkflow
  ├── CouponWorkflow
  ├── DistanceWorkflow
  └── ReviewWorkflow
```

这种设计会把系统重新退化成传统 workflow：每来一个场景就加一个分支，每修一个 bug 就补一个规则，最后 LLM 的语义能力无法贯穿全局。

正确做法是：

```text
LocalLifeAgent
  ↓
统一 GoalPlan
  ↓
统一 CandidateSet
  ↓
统一 EvidencePlan
  ↓
统一 Execute
  ↓
统一 Review
  ↓
统一 Answer
```

不同场景只影响结构化字段，例如：

- `goal_type = single_shop_query | recommendation | comparison | followup | mixed`
- `target_type = explicit_shop | candidate_set | deictic_reference | category_search`
- `requested_facets = coupon | open_status | distance | review_summary | deal | price | rating`
- `decision_mode = describe | rank | compare | filter | clarify`
- `candidate_count.requested / min_required / max_allowed`
- `needs_clarification = true | false`

这些字段影响 Plan 和 Review，但不应该导致新增独立 workflow。

## 5. Candidate Decision 是统一抽象

本地生活任务的核心不是“到底是推荐还是对比”，而是“围绕哪些候选对象做消费决策”。

CandidateSet 应统一承载：

- 单店查询：一个已解析的商家候选。
- 附近推荐：多个搜索候选。
- 多店对比：多个明确对比候选。
- 多轮追问：从 SessionState 恢复出来的上一轮候选。
- 指代查询：“这家”“第一家”“第二个”等解析后的候选。

所以不应存在“推荐候选一套结构、对比候选一套结构、单店解析一套结构”。

## 6. Review 是统一收口点

ReviewSufficiency 必须判断当前证据是否足够回答，而不是只在某些场景生效。

Review 应统一处理：

- 是否找到了目标商家。
- 是否存在多候选歧义。
- 是否缺少关键工具结果。
- 是否候选数量不足。
- 是否对比对象过多。
- 是否工具失败或空结果。
- 是否需要补充工具调用。
- 是否需要向用户澄清。
- 是否可以基于现有证据回答。

Review 的输出不应该是自然语言答案，而是结构化决策：

```text
SUFFICIENT
NEED_CLARIFICATION
NEED_MORE_EVIDENCE
CANNOT_ANSWER_SAFELY
```

## 7. 回答生成边界

最终回答由统一 Verbalizer 生成。

Verbalizer 不区分多个模板 workflow，而是读取：

- GoalPlan
- CandidateSet
- EvidencePack
- ReviewResult
- UserContext

然后生成自然、有消费决策价值、且不越过证据边界的回答。

禁止把单店、推荐、对比分别做成大量模板拼接。模板只允许作为异常兜底，不得成为正常路径。

## 8. 设计结论

本项目正确的架构目标是：

> 顶层路由只决定是否进入本地生活 Agent；进入后，所有本地生活复杂 query 都通过统一的 Plan → Execute → Review 主循环解决。场景差异通过 GoalPlan、CandidateSet、EvidencePlan 和 ReviewResult 表达，而不是通过新增多个 workflow 表达。
