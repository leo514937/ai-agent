# local_life_agent 效果提升改造计划

## 1. 调研结论

基于当前仓库实际情况，这个项目已经不是“只有工具结果拼回答”的早期原型了，而是一个已经具备较完整主链的本地生活 Agent：

```text
Input
-> SemanticFrame
-> Goal / Plan
-> ToolCallGateway
-> ToolResult
-> EvidencePack
-> DecisionPlan / AnswerPlan
-> Review / Verifier
-> Response
```

因此，效果提升的正确方向不是重写架构，而是继续在现有主链里补“默认证据完整性、决策表达质量、推荐解释能力、多轮偏好承接、结果展示结构化”。

一句话总结：

```text
不推翻 LangGraph 主图
不改成 Prompt-first demo agent
不引入 MCP 依赖作为当前主修复
先把现有可信 ToolCall 架构里的推荐 / 对比能力做深、做完整、做像顾问
```

---

## 2. 当前真实现状

### 2.1 已经具备的能力

当前仓库里已经有这些基础，不需要重复建设：

- `SemanticFrame`、`ExecutionPlan`、`EvidencePack`、`AnswerPlan` 等结构化协议
- `ToolRegistry` / `ToolCallGateway` / typed `ToolResult`
- recommendation / comparison / single-shop 三条主链
- deterministic ranking policy
- evidence review / answer verify
- clarification / fallback / response mode 机制
- recommendation 品牌级多样性裁剪
- recommendation 动态数量 `candidate_limit`
- nearby/location 缺失前置澄清

也就是说，很多“应该有”的东西现在并不是从 0 开始做，而是要在已有骨架上补强。

### 2.2 已经解决的近期问题

这些问题已经在当前分支里被解决或部分解决：

- 缺位置的“附近推荐”不再继续空跑 `Plan -> Execute -> Review`
- `search_shops(location=None/{})` 不再静默 empty，而是 `LOCATION_REQUIRED`
- `semantic` 对 `ranking_policy=""`、`preferences=dict/list[str]` 的 normalize 已补齐
- recommendation 默认展示数量已从 3 调整为 5
- recommendation 已支持用户显式说“推荐 3 家 / 5 家”
- recommendation 已增加品牌级去重与补位逻辑

所以这份计划不再把这些当成“待修复核心”，而是把它们视为当前基础能力。

### 2.3 当前仍然真实存在的效果短板

基于仓库与测试现状，当前更值得做的效果问题主要是：

1. recommendation / comparison 默认补证据策略还不够明确
2. 最终回答仍然偏“结果列举”，不够像顾问式决策输出
3. 排序解释和备选方案表达不够结构化
4. recommendation refine follow-up 目前仍偏轻量展示，不是真正的二次决策
5. 前端展示层如果要提升产品感，还缺卡片化 / 偏好 chip / 比较表格这些承接

---

## 3. 架构判断

### 3.1 当前不建议做的事

当前不建议优先做：

- 重写 `graph_builder`
- 拆成多 Agent team
- 引入新的平行 workflow runner
- 让 LLM 直接负责最终事实回答
- 用 MCP / 外部地图平台重构当前工具体系

原因很简单：

- 现有问题更多是“效果层”和“证据层”不够完整，不是主编排已经失效
- 当前仓库已有较多 typed contract，不适合为了“更聪明”去丢掉可信边界
- 多 Agent / MCP 接入会显著增加状态同步、工具协议和调试复杂度

### 3.2 当前建议做的事

建议走“现有架构上的能力包增强”：

```text
Semantic / Plan 不重写
ToolCall 不绕开
EvidencePack 更完整
DecisionPlan 更像决策
Answer 更像顾问
```

---

## 4. 优先级总表

| 项目 | 是否建议做 | 优先级 | 说明 |
|---|---|---:|---|
| recommendation/comparison 默认补齐核心证据 | 是 | P0 | 当前最值得做 |
| 增加 EvidenceCompletenessPolicy | 是 | P0 | 效果提升的主抓手 |
| 增加 DecisionCard / RankingExplanation | 是 | P0 | 把“列结果”变成“给方案” |
| 优化 verbalizer 为顾问式表达 | 是 | P0 | 用户体感提升明显 |
| recommendation refine 变成真正的二次筛选 | 是 | P1 | 当前只是轻量承接 |
| 前端偏好 chip / 卡片化 / 比较表 | 是 | P1 | 产品感增强 |
| 增加 ScenarioPlan | 可做 | P2 | 适合 recommendation/comparison 稳定后 |
| 接入 MCP / 外部地图 | 暂不优先 | P2 | 架构成本高 |
| 多 Agent team | 不建议 | - | 当前收益远低于成本 |

---

## 5. P0 方案：优先做什么

## 5.1 EvidenceCompletenessPolicy

### 为什么值得先做

当前 recommendation / comparison 虽然已经有 evidence build，但“默认至少该补齐哪些证据”并没有被独立收紧成一个显式策略层。

这会带来两个问题：

- 不同推荐场景下证据要求不稳定
- review 能判断“不够”，但 planner/executor 不一定提前知道“必须补什么”

### 当前仓库里可复用的基础

已存在的相关能力：

- `planning/evidence/evidence_builder.py`
- `planning/evidence/evidence_review.py`
- `planning/plans/execution_plan_builder.py`
- `planning/policies/ranking_policy.py`
- `facet_statuses / grounded_facts / missing_inputs`

所以不需要新造大层，只需要新增一个轻量策略模块，把 recommendation / comparison 的最低证据标准显式化。

### 建议落点

建议新增：

```text
local_life_agent/planning/evidence/evidence_completeness_policy.py
```

### 建议策略

#### single_shop

- 默认只要求用户明确问到的 facet
- 不强制补齐 recommendation 风格的全量证据

#### recommendation

默认至少要求：

- `get_shop_detail`
- `check_open_status`
- coupon 状态
- distance / ETA
- rating / price / tags
- scene fit 所需字段

#### comparison

默认至少要求：

- 所有候选商家横向补齐同一组 facet
- 显式标注 unknown / missing / failed
- 不允许 A 有价格、B 没价格时还直接输出强结论且不说明缺口

### 接入点

- planning：根据 task_type 产出 completeness policy
- execution plan builder：按 policy 补工具
- review：按 policy 判断是否“足够回答”

### 预期收益

- recommendation 输出更稳定
- comparison 输出更公平
- answer 层不再被迫自己猜哪些信息该讲

---

## 5.2 DecisionCard

### 为什么值得做

当前 recommendation 的输出虽然已经比纯工具结果更好，但仍然偏“排序列表 + 若干 facet”。

如果想更像本地生活顾问，应该先形成结构化“决策卡”，再 verbalize。

### 当前仓库现状

仓库里已经有：

- `DecisionPlan`
- `best_for`
- `overall_ranking`
- `ranking_snapshot`
- `uncertainty_notes`

这意味着完全可以不新建庞大协议，而是在 decision / answer 之间增加一个轻量决策对象。

### 建议结构

```text
DecisionCard:
- shop_id
- shop_name
- rank
- recommendation_type
- distance_eta
- open_status
- coupon_summary
- price_summary
- scene_fit_reason
- review_highlights
- tradeoffs
- missing_evidence
- next_actions
- evidence_refs
```

### 实现建议

先不必把它做成新的强 schema 层级，也可以先在 `DecisionPlan.response_sections` 或 `metadata` 中结构化生成，再逐步收敛成独立模型。

### 预期收益

- recommendation 回答从“列结果”升级成“给建议”
- comparison 可以更自然地输出“首推 / 备选 / 更便宜 / 更近 / 更稳妥”

---

## 5.3 RankingExplanation

### 为什么值得做

现在 recommendation 已经有排序逻辑，但“为什么第一名是它”这件事没有被单独固化成可消费结构。

这导致：

- verbalizer 要从散乱证据里拼理由
- 用户追问“为什么这家排第一”时，可解释性不稳定

### 建议结构

```text
RankingExplanation:
- why_top_1
- why_not_others
- hard_constraints_satisfied
- soft_preferences_satisfied
- missing_or_uncertain_facts
```

### 建议落点

建议在：

- `planning/evidence/evidence_builder.py`
- 或 `planning/decision/decision_planner.py`

中把 explanation 作为 recommendation / comparison 的结构化附属产物生成。

### 预期收益

- recommendation 更可解释
- comparison 的胜负结论更透明
- answer 层更容易做到顾问式表达

---

## 5.4 顾问式 Verbalizer

### 为什么值得做

当前 deterministic + LLM verbalizer 已经存在，但表达风格仍偏：

- 结果列举
- facet 罗列
- 解释不够“像建议”

### 当前约束

这里必须坚持：

- LLM 只负责表达和组织
- 事实必须来自 `EvidencePack`
- 不允许 LLM 自行补距离、营业、券、评分

### 建议改造点

- `answer/composers/deterministic.py`
- verbalizer prompt / few-shot
- verifier 对顾问式表达做轻约束

### 建议风格

把：

```text
推荐这几家：A、B、C
```

升级成：

```text
我会优先推荐 A，因为它最符合你提到的条件：离得更近、现在营业、而且有券。
如果你更看重便宜，B 更合适；如果你更看重环境，C 可以作为备选。
```

### 预期收益

- 不改主架构，体感提升明显
- recommendation / comparison 的“决策感”更强

---

## 5.5 Recommendation / Comparison 默认证据补齐

### 当前真实情况

仓库现在已经有：

- ranking policy
- coupon / open / detail 的 enrichment
- location / distance 相关处理

但“默认补齐哪些字段”仍没有被系统性收紧成一个稳定合同。

### 推荐的最小执行集

#### recommendation

- detail
- open_status
- coupon
- distance / ETA
- rating
- price
- scene-related tags

#### comparison

- 两边必须尽量同维度对齐
- unknown / failed 要显式写出来
- 不够支持唯一赢家时，不强行宣称唯一最优

### 说明

这条本质上和 `EvidenceCompletenessPolicy` 是同一方向，只是这里强调“业务效果”。

---

## 6. P1 方案：产品体验增强

## 6.1 Recommendation refine 从“轻展示”升级成“二次筛选”

### 当前真实情况

当前 `response_subgraph.py` 里已经支持 recommendation refine follow-up，例如：

- “便宜一点的呢”

但它更偏基于上轮结果的轻量重排 / 轻展示，并不总是触发真正的新一轮检索与结构化比较。

### 建议方向

- 对明确的偏好更新，优先触发二次 ranking
- 对证据不足的偏好更新，允许触发补工具
- 保持不破坏现有短路路径

### 优先级

P1，比 P0 稍后，因为当前已有可用承接，不是完全缺失。

---

## 6.2 前端偏好 chip

### 建议项

```text
[现在营业]
[有券]
[近一点]
[便宜]
[适合约会]
[评分高]
```

### 原则

- 前端传结构化偏好
- 后端注入 `SemanticFrame.preferences / soft_preferences / ranking_signals`
- 不绕开现有 semantic schema

---

## 6.3 结果卡片化 / 比较表

### 当前价值

如果前端需要更强产品感，这一层非常值得做，但它主要是承接已有 `DecisionCard` / `RankingExplanation`。

### 建议字段

#### 推荐卡片

- 店名
- 推荐标签
- 距离 / ETA
- 是否营业
- 是否有券
- 人均 / 评分
- 适合原因
- 风险提示

#### 比较表

- 商家
- 距离
- 营业状态
- 券
- 人均
- 场景适配
- 优点
- 缺点
- 推荐结论

---

## 7. P2 方案：更大的能力扩展

## 7.1 ScenarioPlan

### 什么时候值得做

等 recommendation / comparison 的主效果稳定后，再做“吃饭 + 逛街 + 路线 + 备选”这类场景规划。

### 当前判断

这是“从问答 Agent 升级成场景决策 Agent”的方向，但不该抢在 P0/P1 前面。

---

## 7.2 MCP / 外部地图工具

### 当前判断

这属于架构级扩展，不适合现在优先推进。

原因：

- 鉴权与超时复杂度会明显上升
- 现有 `ToolResult` / `EvidencePack` 适配要做完整
- 当前主要问题不是“没有外部平台”，而是“已有能力的效果没打满”

---

## 8. 分阶段落地顺序

## 阶段 1：不动主架构，提升回答质量

1. 增加 `EvidenceCompletenessPolicy`
2. recommendation / comparison 默认补齐核心证据
3. 增加 `DecisionCard`
4. 增加 `RankingExplanation`
5. verbalizer 改成顾问式表达

### 验收标准

- recommendation 能说明首推理由
- comparison 能说明胜出理由和不确定性
- unknown / missing 会显式表达
- 不编造工具未返回事实

## 阶段 2：多轮筛选与前端体验增强

1. recommendation refine 做成二次筛选
2. 偏好 chip
3. 推荐卡片化
4. 比较表格化

### 验收标准

- “便宜一点 / 近一点 / 有券的呢”可稳定承接
- 多轮结果变化原因可解释
- 展示层不只是平铺文本

## 阶段 3：复杂场景规划

1. `ScenarioPlan`
2. 时间窗口 / 备选路径 / 吃完去哪

### 验收标准

- 不只推荐单店，而是能给组合方案

## 阶段 4：外部工具生态

1. MCPToolAdapter
2. 外部地图 / 搜索 / POI 能力接入

### 验收标准

- 仍然走 ToolResult -> EvidencePack -> Review 的可信路径

---

## 9. 建议的最小可行改造

如果当前只想用最小改动换最大效果，建议先只做这四件事：

1. `EvidenceCompletenessPolicy`
2. `DecisionCard`
3. `RankingExplanation`
4. 顾问式 verbalizer

这是当前最值得做的 P0 组合。

原因：

- 不用推翻架构
- 不依赖新平台
- 直接改善 recommendation / comparison 体感
- 最符合现在仓库的成熟度

---

## 10. 验收建议

## 10.1 recommendation

输入示例：

```text
附近有没有适合约会、现在营业、最好有券的火锅？
```

期望：

- 查到候选商家
- 查营业状态
- 查距离 / ETA
- 查券
- 说明首推理由
- 给出备选理由
- 明确指出缺失或不确定信息

## 10.2 comparison

输入示例：

```text
海底捞和山城一锅哪个更适合约会？
```

期望：

- 绑定两个明确对象
- 横向补齐同维度证据
- 输出明确比较结论
- 显式说明 unknown / failed / missing

## 10.3 多轮 refine

输入示例：

```text
附近推荐几家火锅
便宜一点的呢
和第一家比呢
```

期望：

- 承接上轮 recommendation context
- 解析“便宜一点”“第一家”
- 说明排序或推荐变化原因

## 10.4 事实约束

期望：

- 距离来自 distance tool / grounded evidence
- 券来自 coupon tool
- 营业状态来自 open status tool
- 缺失时允许说不确定，不允许编造

---

## 11. 最终建议

当前最优路径不是“重构成本地生活 MCP Planner”，而是：

```text
保留现有可信 ToolCall 架构
把 recommendation / comparison 的证据默认补齐
把 decision 结构化
把 verbalizer 做成顾问式表达
再逐步升级前端承接和场景规划
```

换句话说：

```text
先把现有系统从“会答”升级到“会给可解释的本地生活建议”
再考虑更大的场景规划和外部工具生态
```
