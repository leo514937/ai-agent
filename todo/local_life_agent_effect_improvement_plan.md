# 本地生活 Agent 效果增强改造建议总结

## 1. 总体结论

你的项目当前架构更工程化、更可信：

```text
SemanticFrame
→ ToolPlan / DecisionPlan
→ ToolCallGateway
→ ToolResult
→ EvidencePack
→ Review / Verifier
→ Answer
```

MCP Travel Planner 更强的地方在于：

```text
用户输入
→ 主动补齐住宿 / 距离 / 时间 / 价格 / 餐饮 / 景点 / 预算 / 实用信息
→ 输出完整可执行旅行方案
```

所以推荐路线是：

```text
不重写架构
不引入 MCP
不拆多 Agent Team
先把推荐 / 对比输出从“工具结果回答”升级成“证据驱动的本地生活决策方案”
```

---

## 2. 是否需要架构层修改

### 简短判断

大部分建议 **不需要架构级重构**，属于现有主链路上的效果增强。

真正属于架构级或接近架构级的改动只有：

1. 接 MCP / 外部地图 / 外部 POI 工具生态
2. 把本地生活从“推荐 / 对比”升级成完整“场景规划 Agent”

当前阶段不建议优先做这些。

---

## 3. 改动量分级表

| 改动建议 | 改动量 | 是否架构级修改 | 优先级 |
|---|---:|---:|---:|
| 推荐 / 对比默认补齐距离、营业、券、评价、人均 | 中 | 否 | P0 |
| 增加 `EvidenceCompletenessPolicy` | 中 | 否，但属于框架增强 | P0 |
| 增加 `DecisionCard`，让结果更像决策方案 | 中 | 否 | P0 |
| 增加 `RankingExplanation` | 中 | 否 | P0 |
| Verbalizer 改成顾问式表达 | 小 ~ 中 | 否 | P0 |
| 推荐排序加入 ETA、有券、场景适配、价格等综合分 | 中 | 否 | P0 |
| 前端增加偏好 chip / 快捷筛选 | 小 ~ 中 | 否 | P1 |
| 前端结果卡片化展示 | 中 | 否 | P1 |
| 增加 `ScenarioPlan`，支持“吃饭 + 逛街 + 路线 + 备选” | 中 ~ 大 | 轻架构增强 | P1 / P2 |
| 接 MCP 工具适配器 | 大 | 是 | P2 |

---

## 4. 最值得优先做的 P0 改动

## 4.1 增加 EvidenceCompletenessPolicy

### 目标

不同类型 query 默认补齐不同证据，避免推荐 / 对比只查到部分信息就回答。

### 建议策略

```text
单店问答：
- shop_detail
- 用户显式问到的 facet，例如券、营业状态、环境、距离

推荐：
- shop_detail
- open_status
- coupon_list
- distance_eta
- price / rating / tags
- scene_fit

对比：
- 所有对比商家的 shop_detail
- 同一组 facet 横向补齐
- 缺失项显式标注
```

### 建议新增模块

```text
local_life_agent/planning/evidence_policy.py
```

### 接入点

```text
planner / decision planner:
  根据 intent 选择 evidence policy

executor:
  根据 policy 扩展工具调用

review:
  判断 EvidencePack 是否满足最低证据要求
```

### 价值

这是效果提升的核心。  
它能保证推荐 / 对比时默认综合考虑：

```text
距离
营业状态
优惠券
价格
评价
场景适配
```

---

## 4.2 增加 DecisionCard

### 目标

不要让最终回答直接从散乱工具结果生成，而是先形成结构化决策对象。

### 建议结构

```text
DecisionCard:
- shop_id
- shop_name
- rank
- recommendation_type: primary / alternative / budget / nearby / coupon
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

### 推荐链路

```text
ToolResult
→ EvidencePack
→ DecisionCard
→ Answer
```

### 价值

让回答从：

```text
附近推荐这三家：A、B、C。
```

升级为：

```text
我更建议你优先看 A。它离你最近，现在营业，而且有券，比较符合“约会 + 火锅 + 不想太远”的条件。

如果你更看重便宜，B 更合适；如果你更看重环境，C 可以作为备选。
```

---

## 4.3 增加 RankingExplanation

### 目标

让排序可解释，而不是黑盒列表。

### 建议结构

```text
RankingExplanation:
- why_top_1
- why_not_others
- hard_constraints_satisfied
- soft_preferences_satisfied
- missing_or_uncertain_facts
```

### 价值

用户问：

```text
附近有没有适合约会、现在营业、最好有券的火锅？
```

回答应该明确：

```text
为什么第一家排第一
为什么第二家只是备选
哪家更便宜
哪家更近
哪家券更多
哪家环境更适合约会
哪些信息缺失或不确定
```

---

## 4.4 顾问式 Verbalizer

### 目标

在不放松事实约束的前提下，让回答更像“本地生活顾问”，而不是模板拼接。

### 改动点

```text
answer/verbalizer prompt
few-shot examples
AnswerContract
AnswerVerifier
```

### 表达风格

不要只说：

```text
推荐 A、B、C。
```

而要说：

```text
我会优先推荐 A，因为它最符合你提到的“近一点、现在营业、有券、适合约会”。

如果你更看重便宜，可以选 B；如果你更看重环境，可以把 C 作为备选。
```

### 注意事项

LLM 可以负责：

```text
语气
组织方式
取舍解释
自然语言表达
```

但不能负责：

```text
编造距离
编造营业状态
编造优惠券
编造评分
编造商家信息
```

所有事实必须来自 `EvidencePack / ToolResult`。

---

## 4.5 推荐排序加入综合特征

### 目标

把距离、营业、券、价格、评价、场景适配变成排序核心，而不是回答时临时提一下。

### 推荐排序特征

```text
score =
  hard_constraint_score
  + distance_eta_score
  + open_status_score
  + coupon_score
  + price_match_score
  + rating_review_score
  + scene_fit_score
```

### 示例

对于 query：

```text
附近有没有适合约会、现在营业、最好有券的火锅？
```

排序不能只按评分，而要综合：

```text
是否火锅
是否现在营业
是否距离近
是否有券
是否适合约会
价格是否合适
评价是否稳定
```

---

## 5. P1 改动：产品体验增强

## 5.1 前端偏好 chip

### 目标

降低用户表达成本，让用户快速补充偏好。

### 建议 chip

```text
[现在营业]
[有券]
[近一点]
[便宜]
[环境好]
[适合约会]
[适合带长辈]
[不排队]
[评分高]
```

### 后端处理

前端可以把 chip 作为结构化偏好传给后端：

```text
message + selected_preferences
```

后端注入：

```text
SemanticFrame.constraints
SemanticFrame.preferences
```

---

## 5.2 结果卡片化展示

### 目标

把 `DecisionCard` 展示为可感知的商家决策卡。

### 建议字段

```text
店名
推荐标签
距离 / ETA
是否营业
是否有券
人均 / 券后价
适合原因
风险提示
操作按钮：查券 / 导航 / 对比 / 换一家
```

### 价值

用户会感觉 Agent 不只是“回答问题”，而是真的在帮他做决策。

---

## 5.3 对比表格

### 目标

多店对比时，优先用结构化表格展示。

### 示例字段

```text
商家
距离
营业状态
优惠券
人均
适合场景
优点
缺点
推荐结论
```

### 注意

对比表格必须来自 `EvidencePack`，缺失字段要显式标注：

```text
暂无数据
工具未返回
需要进一步查询
```

不能让 LLM 补齐。

---

## 6. P2 改动：轻架构增强与后期扩展

## 6.1 增加 ScenarioPlan

### 目标

支持更复杂的本地生活场景规划。

例如：

```text
今晚约会吃火锅，吃完想附近逛逛，别太贵
```

不要只推荐火锅店，而是输出：

```text
18:30 出发
18:45 到店
推荐 A 火锅
吃完可以去附近商场 / 公园
如果排队，备选 B
```

### 建议结构

```text
ScenarioPlan:
- intent_scene: dating / family / friends / solo / elder
- time_window
- route_start
- primary_shop
- backup_shops
- after_meal_options
- estimated_timeline
- risks
```

### 改动性质

这属于轻架构增强。  
可以等推荐 / 对比稳定后再做。

---

## 6.2 MCPToolAdapter

### 目标

未来如果要接 Google Maps、外部搜索、POI、第三方点评数据，可以通过 MCP 适配进现有工具体系。

### 正确接法

不要让 LLM 直接调 MCP：

```text
LLM 直接调 MCP
```

而应该是：

```text
LLM 产 ToolPlan
→ Validator 校验
→ Gateway 调 MCPToolAdapter
→ 标准 ToolResult
→ EvidencePack
→ Review
→ Answer
```

### 建议结构

```text
MCP Server
→ MCP Client
→ MCPToolAdapter
→ ToolRegistry
→ ToolCallGateway
→ ToolResult
```

### 改动性质

这是架构级增强，当前不建议优先做。

---

## 7. 不建议当前做的事情

## 7.1 不建议重构成多 Agent Team

不要现在拆成：

```text
推荐 Agent
距离 Agent
优惠 Agent
评价 Agent
对比 Agent
回答 Agent
```

这样会增加：

```text
状态同步成本
工具权限边界复杂度
证据合并复杂度
调试复杂度
LLM 调用成本
错误传播风险
```

更好的方式是：

```text
一个主图
多个 capability / policy / node
统一 EvidencePack
统一 Review
统一 Answer
```

也就是：

```text
能力包化，不是多 Agent 化
```

---

## 7.2 不建议让 LLM 直接生成最终事实答案

MCP Travel Planner 的问题在于它允许 LLM 直接输出完整 Markdown。  
旅行 demo 可以接受，但本地生活事实更敏感：

```text
营业状态
距离
优惠券
团购
评分
人均
商家是否存在
```

这些都不能让 LLM 猜。

---

## 7.3 不建议缺信息时用 general knowledge fallback

本地生活场景中，工具查不到时应该：

```text
明确说明缺失
请求澄清
补工具查询
可信失败
```

不应该：

```text
LLM 根据常识补齐事实
```

---

## 8. 推荐落地顺序

## 阶段一：效果增强，不动架构

```text
1. 增加 EvidenceCompletenessPolicy
2. 推荐 / 对比默认补齐详情、券、营业、距离、评价 / 价格
3. 增加 DecisionCard
4. 增加 RankingExplanation
5. Verbalizer 改成顾问式表达
6. Verifier 检查回答是否引用 EvidencePack 外事实
```

### 预期收益

```text
推荐更综合
对比更清晰
回答更像顾问
用户感知明显提升
不破坏现有架构
```

---

## 阶段二：前端体验增强

```text
1. 增加偏好 chip
2. 推荐结果卡片化
3. 对比表格化
4. 增加一键继续追问：
   - 便宜一点
   - 近一点
   - 有券的
   - 和第一个比
   - 换一家
```

### 预期收益

```text
用户操作成本下降
产品感增强
多轮追问更自然
```

---

## 阶段三：场景规划

```text
1. 新增 ScenarioPlan
2. 支持“吃饭 + 逛街 + 路线 + 备选”
3. 支持时间窗口、路线、备选店
```

### 预期收益

```text
从本地生活问答升级为本地生活决策 Agent
```

---

## 阶段四：外部工具 / MCP

```text
1. 设计 MCPToolAdapter
2. 接地图 / 搜索 / POI
3. 统一转成 ToolResult
4. 接入 EvidencePack
```

### 预期收益

```text
工具生态更开放
外部实时能力更强
```

### 风险

```text
依赖复杂
鉴权复杂
超时和错误分类复杂
工具 schema 对齐复杂
```

---

## 9. 最小可行改造方案

如果只想用较小改动快速提升效果，建议只做以下四件事：

```text
1. EvidenceCompletenessPolicy
2. DecisionCard
3. RankingExplanation
4. 顾问式 Verbalizer
```

这四个不需要推翻架构，但能显著提升：

```text
推荐质量
回答完整度
对比清晰度
用户感知
```

---

## 10. 验收标准建议

## 10.1 推荐场景验收

输入：

```text
附近有没有适合约会、现在营业、最好有券的火锅？
```

期望：

```text
必须查候选商家
必须查营业状态
必须查距离 ETA
必须查优惠券
必须说明首推理由
必须说明备选理由
必须说明不满足条件或缺失信息
不能编造工具未返回的事实
```

---

## 10.2 对比场景验收

输入：

```text
海底捞和山城一锅哪个更适合约会？
```

期望：

```text
必须绑定两个 shop_id
必须横向补齐相同 facet
必须输出明确推荐结论
必须说明各自优缺点
缺失信息必须显式标注
不能默认选择第一个
```

---

## 10.3 多轮场景验收

输入：

```text
附近推荐几家火锅
便宜一点的呢
和第一个比呢
```

期望：

```text
必须继承上一轮候选
必须解析“便宜一点”
必须解析“第一个”
必须绑定 shop_id
必须重新计算或复用证据
必须说明推荐变化原因
```

---

## 10.4 事实约束验收

期望：

```text
回答中的距离必须来自 get_distance_eta
回答中的券必须来自 get_coupon_list
回答中的营业状态必须来自 check_open_status
回答中的商家详情必须来自 get_shop_detail 或候选召回结果
缺失时不得编造
```

---

## 11. 最终建议

当前最优路线不是重构，而是增强：

```text
保留：
LangGraph
ToolCallGateway
EvidencePack
Review / Verifier

新增：
EvidenceCompletenessPolicy
DecisionCard
RankingExplanation
顾问式 Verbalizer
前端偏好 chip
结果卡片
```

一句话总结：

```text
不要把系统改成 MCP Travel Planner 那种轻量 Prompt Agent；
要把它的“完整方案感、主动补证据、顾问式表达”吸收到你现有的可信 ToolCall 架构里。
```
