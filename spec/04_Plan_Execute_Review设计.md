# 04_Plan_Execute_Review 统一设计

## 1. 设计目标

Plan → Execute → Review 是本地生活 Agent 的统一任务解决模式，不是某一个推荐场景的专用流程。

系统必须用同一套机制处理：

- 单店查询
- 附近推荐
- 优惠券查询
- 营业状态查询
- 距离 ETA 查询
- 评价摘要
- 多店对比
- 条件筛选
- 场景化推荐
- 多轮追问
- 指代恢复
- 候选澄清
- 组合复杂问题

这些场景不能被拆成多个平行 workflow。它们都应进入同一个主循环，只是 Plan 的字段不同、需要调用的工具不同、Review 的充分性判断不同。

## 2. 统一主循环

统一主循环如下：

```text
SemanticFrame
  ↓
Plan
  ↓
Validate
  ↓
Execute
  ↓
BuildEvidence
  ↓
Review
  ├── sufficient → Answer
  ├── need_clarification → Clarify
  ├── need_more_evidence → Replan / Execute
  └── cannot_answer → SafeFailure
```

这个循环允许多次执行，但每次执行都必须由 Review 给出明确原因。

## 2.1 找不到目标时的恢复策略

当系统在 `resolve_shop`、`get_coupon_list` 或相关目标工具里没有命中用户要找的精确对象时，不应直接把结果等同为最终失败或直接进入澄清。统一恢复策略如下：

1. 先做一次重试。
   - 可以使用同义词、别名、上下文补全、宽查询或更宽松的候选检索。
   - 目标是区分“临时没命中”与“真的没有对应目标”。
2. 如果重试后仍然没有精确目标，则走“相似店铺推荐”逻辑。
   - 例如：找不到指定店铺，就推荐同类别、同区域、同场景的替代候选。
   - 如果是找不到某店的券，则可以推荐“同类且有券”的替代候选。
3. 相似推荐必须重新进入 `Plan → Execute → Review` 主循环。
   - 不能在 fallback 文本里直接假装已经回答了原目标事实。
   - 不能把精确目标找不到误写成默认澄清，除非用户输入本身确实歧义且无法构造替代候选。

这个策略的语义是：系统优先保证“给出可用选择”，其次才是“追问补充信息”，最后才是“可信失败”。

## 3. Plan 阶段

Plan 阶段负责把用户输入和上下文转成结构化任务计划。

Plan 不直接区分“推荐 workflow / 对比 workflow / 单店 workflow”，而是输出统一结构。

建议核心结构包括：

```text
GoalPlan
- goal_type
- user_intent_summary
- target_type
- target_refs
- requested_facets
- constraints
- decision_mode
- candidate_policy
- evidence_requirements
- clarification_requirements
```

### 3.1 goal_type

`goal_type` 只描述用户目标形态，不决定跳转到独立 workflow。

可选值示例：

- `single_subject_decision`
- `candidate_discovery`
- `candidate_comparison`
- `followup_refinement`
- `mixed_decision`
- `direct_local_life_qa`

### 3.2 requested_facets

用于描述需要哪些事实维度。

示例：

- `shop_detail`
- `coupon`
- `deal`
- `open_status`
- `distance_eta`
- `review_summary`
- `price`
- `rating`
- `scene_fit`

### 3.3 decision_mode

用于描述最终要做什么决策。

示例：

- `describe`：解释某家店怎么样。
- `filter`：按条件筛选候选。
- `rank`：推荐排序。
- `compare`：多店对比。
- `clarify`：需要用户选择或补充条件。

这些 mode 只影响后续 EvidencePlan 和 Review，不等于不同 workflow。

## 4. CandidateSet 阶段

CandidateSet 是本地生活任务的统一对象集合。

它应覆盖所有场景：

```text
CandidateSet
- candidates
- source
- requested_count
- min_required
- max_allowed
- ambiguity_status
- unresolved_refs
- resolved_refs
- need_clarification
```

### 4.1 单店查询

单店查询是 CandidateSet 中只有一个明确候选的情况。

如果解析出多个同名店，CandidateSet 的状态应是 `AMBIGUOUS`，进入澄清，而不是默认第一家。

如果精确店铺解析结果为 `NOT_FOUND`，应先尝试重试；若重试后仍无精确目标，但能从类别、位置或场景中构造相似候选，则切换为“相似店铺推荐”并重新进入主循环，而不是直接结束为澄清或失败。

### 4.2 推荐

推荐是 CandidateSet 中包含多个搜索候选的情况。

Plan 需要明确 requested_count、min_required、max_allowed。

如果用户原始目标是某个具体店铺，但该店铺找不到或券信息为空，且系统能构造替代候选，则推荐路径应切换为“相似店铺推荐”，继续执行统一主循环。

### 4.3 对比

对比是 CandidateSet 中包含多个待比较候选的情况。

如果候选过多，Review 应要求裁剪或澄清。

### 4.4 多轮指代

“这家”“第一家”“第二个”“便宜一点”都应转成 CandidateSet 的更新，而不是新增追问 workflow。

## 5. EvidencePlan 阶段

EvidencePlan 根据 GoalPlan 和 CandidateSet 生成工具调用计划。

示例：

- 用户问“有券吗” → 需要 `get_coupon_list`。
- 用户问“现在营业吗” → 需要 `check_open_status`。
- 用户问“离我近吗” → 需要 `get_distance_eta`。
- 用户问“适合约会吗” → 需要详情、评价摘要、可能还需要价格和环境相关证据。
- 用户问“哪个好” → 多个候选需要尽量拉齐同一组对比维度。

EvidencePlan 可以并行多个工具调用，但必须经过 PlanValidate。

## 6. Execute 阶段

Execute 阶段只执行通过校验的工具计划。

要求：

- 只能调用 ToolRegistry 中注册的工具。
- 只能通过 ToolCallGateway 执行。
- 不能绕过 Gateway 直接查数据库或读静态文件。
- 不能使用 mock 工具作为正常链路。
- 工具失败、空结果、超时必须结构化返回。

Execute 不负责生成最终答案。

## 7. EvidencePack 阶段

EvidencePack 统一沉淀事实证据。

它应记录：

- 哪些工具被调用。
- 每个工具返回了哪些事实。
- 事实绑定哪个 shop_id。
- 哪些事实缺失。
- 哪些工具失败。
- 哪些候选被过滤。
- 哪些判断仍不确定。

后续 Review 和 Verbalizer 只能基于 EvidencePack 进行判断和表达。

## 8. Review 阶段

Review 是统一收口点。

Review 不属于某个场景，而是所有本地生活任务都必须经过的充分性判断。

Review 需要输出：

```text
ReviewResult
- status
- reason
- missing_evidence
- required_clarification
- replan_suggestion
- answer_boundary
```

status 可选：

- `SUFFICIENT`
- `NEED_CLARIFICATION`
- `NEED_MORE_EVIDENCE`
- `CANNOT_ANSWER_SAFELY`

### 8.1 sufficient

证据足够，可以回答。

### 8.2 need_clarification

用户目标、候选对象或指代不清，需要追问。

### 8.3 need_more_evidence

已知下一步缺哪些工具证据，可以重新规划并继续执行。

如果缺失的是“精确目标本身”，并且重试后仍无法命中，但存在可替代的相似候选，则 Review 不应直接停在 `need_clarification`，而应建议进入相似店铺推荐并重新 Plan → Execute → Review。

### 8.4 cannot_answer_safely

工具失败、数据缺失或证据不足，无法可信回答，只能降级说明。

仅当重试、相似候选构造、以及必要的补充工具执行都无法形成可信结果时，才允许进入该状态。

## 9. Answer 阶段

Answer 阶段统一由 LLM Verbalizer 基于 EvidencePack 输出。

它应做到：

- 结论明确。
- 解释推荐或对比理由。
- 保留消费决策价值。
- 对缺失信息表达不确定。
- 不编造工具没有返回的事实。
- 不把工具结果机械堆给用户。

Answer 不应该回到多模板 workflow。

## 10. 反模式

禁止以下实现：

```text
if intent == coupon: run_coupon_workflow()
if intent == compare: run_compare_workflow()
if intent == recommend: run_recommend_workflow()
if intent == distance: run_distance_workflow()
```

也禁止：

- 为测试句子硬编码分支。
- 为某些店名写特殊规则。
- 让 ambiguous 默认取第一家。
- 让 fallback 覆盖 LLM 主路径。
- 用 mock 结果填充 EvidencePack。
- 用模板拼接替代 Verbalizer 主路径。

## 11. 正确实现判断标准

如果系统新增一个场景时，需要新增一个独立 workflow，说明架构方向错了。

正确目标是：新增场景主要通过扩展以下内容实现：

- GoalPlan 字段
- CandidateSet 表达
- EvidencePlan 生成策略
- Tool schema
- Review 充分性规则
- Verbalizer few-shot / 输出约束
- 端到端测试用例

而不是新增一条业务 workflow。
