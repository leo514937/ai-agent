# 10_统一 Plan Execute Review 架构修正版

## 1. 为什么要修正架构表述

之前按“单店、推荐、对比、多轮、澄清”等场景分别列出很多路径，容易让实现者误解为：

```text
每一种场景 = 一条独立 workflow
```

这不是本项目想要的架构。

本项目真正要实现的是：

```text
所有本地生活复杂 query = 一个统一 Agent 主循环处理
```

场景只是用户目标和候选对象的不同形态，不应该变成多个平行 workflow。

## 2. 正确架构一句话

> 顶层路由只判断是否进入本地生活 Agent；一旦进入，所有本地生活场景都通过统一的 Plan → Execute → Review 机制解决。

也就是说：

- 单店查询不是一个独立 workflow。
- 附近推荐不是一个独立 workflow。
- 多店对比不是一个独立 workflow。
- 优惠券查询不是一个独立 workflow。
- 多轮追问不是一个独立 workflow。
- 澄清恢复不是一个独立 workflow。

它们都是统一 Agent 主循环中的不同计划结果。

## 3. 顶层路由应该很薄

顶层路由只做三件事：

```text
Direct Answer
Safety / Reject
Local Life Agent
```

Direct Answer 用于非本地生活问题和普通问答。

Safety / Reject 用于安全拒答。

Local Life Agent 用于所有本地生活消费决策问题。

顶层路由不应该继续细分：

```text
coupon route
recommend route
compare route
distance route
review route
```

这些细分会把系统重新变成 workflow 编排，而不是 Agent。

## 4. Local Life Agent 内部统一流程

统一流程如下：

```text
LoadSession
  ↓
Understand SemanticFrame
  ↓
Build GoalPlan
  ↓
Resolve / Discover CandidateSet
  ↓
Build EvidencePlan
  ↓
Validate Plan
  ↓
Execute Tools
  ↓
Build EvidencePack
  ↓
Review Sufficiency
  ├── need clarification
  ├── need more evidence
  ├── cannot answer safely
  └── sufficient
  ↓
Verbalize Answer
  ↓
Verify Answer
  ↓
SaveSession
```

这个流程可以循环，但不能拆成多条业务 workflow。

## 5. 不同场景如何统一表达

### 5.1 单店查询

用户说：

> “海底捞水晶城店怎么样？”

不是进入 `single_shop_workflow`，而是：

```text
goal_type = single_subject_decision
candidate_set = [海底捞水晶城店]
requested_facets = [shop_detail, review_summary, coupon?]
decision_mode = describe
```

### 5.2 优惠券查询

用户说：

> “这家有券吗？”

不是进入 `coupon_workflow`，而是：

```text
goal_type = single_subject_decision
candidate_set = 从 SessionState 恢复“这家”
requested_facets = [coupon]
decision_mode = describe
```

### 5.3 附近推荐

用户说：

> “附近推荐几家适合约会、现在营业、有券的火锅。”

不是进入 `recommend_workflow`，而是：

```text
goal_type = candidate_discovery
candidate_set = search_shops 结果
constraints = [nearby, hotpot, dating, open_now, has_coupon]
requested_facets = [shop_card, coupon, open_status, distance_eta, review_summary]
decision_mode = rank
```

### 5.4 多店对比

用户说：

> “这三家哪个更适合聚餐？”

不是进入 `compare_workflow`，而是：

```text
goal_type = candidate_comparison
candidate_set = 从上一轮候选恢复三家店
requested_facets = [shop_detail, price, rating, review_summary, distance_eta]
decision_mode = compare
```

### 5.5 多轮追问

用户说：

> “便宜一点的呢？”

不是进入 `followup_workflow`，而是：

```text
goal_type = followup_refinement
candidate_set = 上一轮候选或重新搜索候选
constraints = 继承上一轮 + price lower
decision_mode = filter / rank
```

## 6. 关键统一数据结构

要靠统一协议支撑，而不是靠场景分支支撑。

建议核心协议包括：

```text
SemanticFrame
GoalPlan
CandidateSet
EvidencePlan
ToolPlan
ToolResult
EvidencePack
ReviewResult
AnswerContract
SessionState
```

每个协议都应该是跨场景通用的。

例如 CandidateSet：

- 单店时是 1 个候选。
- 推荐时是 N 个候选。
- 对比时是 N 个待比较候选。
- 澄清时是 N 个歧义候选。
- 多轮时是从 SessionState 恢复的候选。

## 7. Review 的核心作用

Review 是统一 Agent 能处理复杂问题的关键。

它要判断：

- 候选是否明确。
- 数量是否合理。
- 证据是否足够。
- 工具是否失败。
- 是否需要继续调用工具。
- 是否需要向用户澄清。
- 是否可以给出可信回答。

这比按场景写 workflow 更重要。

如果 Review 只是形式化节点，系统就会退化成固定流程。

## 8. 实现约束

实现时必须避免：

- 新增 `recommend_workflow`、`compare_workflow`、`coupon_workflow` 这类平行主链路。
- 用大量 if/else 按 query 类型跳不同路径。
- 让每个场景都有自己的 resolver、planner、verbalizer。
- 把多轮追问做成独立规则链。
- 用 mock 数据或模板 fallback 掩盖链路问题。

实现时应该优先做：

- 统一 GoalPlan。
- 统一 CandidateSet。
- 统一 EvidencePlan。
- 统一 Tool Gateway。
- 统一 ReviewResult。
- 统一 LLM Verbalizer。
- 统一端到端 trace。

## 9. 验收判断

如果一个复杂 query 可以在不新增专用 workflow 的情况下，通过扩展 GoalPlan / EvidencePlan / Review 处理，说明架构方向正确。

例如下面这些 query 都应走同一个主循环：

- “海底捞怎么样？”
- “它有券吗？”
- “附近推荐几家便宜的火锅。”
- “第一家和海底捞比呢？”
- “这三家哪个适合约会？”
- “换个更近一点的。”
- “有券、现在营业、评分高的优先。”

验收时重点看 trace：

```text
TopRouter = LocalLifeAgent
GraphPath = UnifiedPlanExecuteReview
GoalPlan = 根据 query 不同而变化
CandidateSet = 根据 query 不同而变化
EvidencePlan = 根据 query 不同而变化
ReviewResult = 真实判断充分性
Answer = 基于 EvidencePack
```

不能出现：

```text
recommend_workflow_called = true
compare_workflow_called = true
coupon_workflow_called = true
mock_tool_used = true
fake_llm_used = true
```

## 10. 最终结论

本项目不是“很多本地生活 workflow 的集合”，而是“一个能通过统一计划、执行、复盘机制解决多种本地生活问题的 Agent”。

场景越多，越应该证明统一抽象有效，而不是继续增加流程分支。
