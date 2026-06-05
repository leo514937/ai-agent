# Day2：AnswerContract 与 Context Pruning 增强

> 目标：让系统“只回答用户问的内容”，解决问券答环境、问营业自动推荐、评价内容越界等问题。  
> 重点：AnswerContract、最新一轮消息优先、facet 边界、context pruning、输出后置校验。  
> 产出：回答边界清晰，避免 context stuffing 和 facet leak。

---

## 1. 改造背景

本地生活 Agent 常见错误：

```text
用户问“有券吗”，系统自动补充环境；
用户问“营业吗”，系统顺便推荐别的店；
用户问“环境怎么样”，系统开始编券；
用户只想单点信息，系统输出综合长文。
```

这些问题不是单纯 prompt 问题，而是 **Answer Contract 缺失**。

Day2 目标是：  
**把用户问题拆成 facet，并用 AnswerContract 控制检索、工具、上下文注入和最终输出，同时保证最新一轮用户消息决定本轮 contract。**

---

## 2. Facet 定义

建议标准 facet：

```text
coupon：优惠券
open_status：营业状态
environment：环境
taste：口味
service：服务
price：价格/人均
scene_fit：适合场景
queue：排队
distance：距离
recommendation：推荐
general_review：综合评价
```

---

## 3. AnswerContract 结构

建议结构：

```python
class AnswerContract:
    required_facets: list[str]
    optional_facets: list[str]
    forbidden_facets: list[str]
    allowed_tools: list[str]
    allowed_rag_facets: list[str]
    answer_style: str
    allow_recommendation: bool
    allow_extra_context: bool
    realtime_required: bool
    evidence_policy: str
```

`answer_style` 可选：

```text
short_direct
single_facet
multi_facet_blocks
single_shop_review
recommendation_list
clarification
```

---

## 4. Context Engineering 增强

### 4.1 不再把所有上下文塞给 LLM

错误方式：

```text
用户问券，context 中塞入环境评价、服务评价、约会场景、推荐候选。
```

正确方式：

```text
用户问券，只注入 coupon tool result。
用户问环境，只注入 environment/scene_fit RAG evidence。
用户问综合评价，才注入多 facet evidence。
多轮会话下，当前轮 message 优先重算 context pruning，不复用上一轮 contract。
```

---

### 4.2 Context Pruning 规则

根据 AnswerContract 裁剪上下文。

裁剪前必须先由最新一轮消息生成当前轮 contract。历史 summary 只能作为弱补充，不能决定本轮允许哪些 facet。

示例 1：

```text
Query：海底捞水晶城店有券吗？
required_facets：coupon
context 允许：
  - coupon tool result
禁止：
  - environment RAG
  - scene_fit RAG
  - recommendation candidates
```

推荐类 contract 不能因为上一轮单店上下文把 `recommendation_candidates` 压缩成单店主答案；推荐轮次应把单店结果降级为局部 evidence。

示例 2：

```text
Query：这家适合约会吗？
required_facets：scene_fit
context 允许：
  - scene_fit evidence
  - environment evidence
  - noise / crowd evidence
禁止：
  - coupon result
  - open_status result
  - unrelated recommendation
```

---

### 4.3 Evidence Pack 分层

建议组装：

```python
class EvidencePack:
    target_shop_evidence: list[Evidence]
    tool_results: list[ToolResult]
    recommendation_candidates: list[ShopCandidate]
    forbidden_evidence: list[Evidence]
    dropped_context_reason: list[str]
```

其中 `forbidden_evidence` 只用于调试，不进入 LLM prompt。

---

## 5. Harness Engineering 增强

新增：

```text
tests/local_life/context/test_answer_contract_harness.py
tests/local_life/context/test_context_pruning_harness.py
tests/local_life/context/test_answer_linter_harness.py
```

---

### 5.1 Contract 测试矩阵

| 用户问题 | required_facets | forbidden_facets | route |
|---|---|---|---|
| 有券吗 | coupon | environment, recommendation | tool |
| 营业吗 | open_status | environment, recommendation | tool |
| 环境怎么样 | environment | coupon, open_status | rag |
| 适合约会吗 | scene_fit, environment | coupon | rag |
| 怎么样 | general_review | unsupported_realtime_claim | rag |
| 有券吗，现在营业吗，环境怎么样 | coupon, open_status, environment | unrelated_shop | rag_plus_tool |
| 附近推荐几家 | recommendation | single_shop_only | recommendation |

多轮场景要额外覆盖：

```text
上一轮推荐 / 本轮有券吗 → 本轮只用 coupon contract
上一轮问券 / 本轮问环境 → 本轮只用 environment contract
上一轮问 A 店 / 本轮问 B 店 → 本轮 contract 重新生成
```

---

### 5.2 输出 Linter

新增 `answer_linter.py`，检查：

```text
forbidden facet 是否泄露
是否出现无关商家名
是否声称实时但没有 tool result
是否推荐了用户没问的店
是否把 RAG 历史内容当实时信息
是否回答了 Contract 外的内容
是否错误沿用了上一轮 message 的 facet 约束
```

---

## 6. 具体改造任务

### 6.1 Contract 构建位置

建议在：

```text
understand_query 之后
route_gate 之前
```

因为 route 需要知道 required_facets。
而 required_facets 必须优先来源于当前轮 message，不是历史 session 里残留的意图。

---

### 6.2 Contract 影响 route

示例：

```text
required_facets = [coupon] => tool
required_facets = [environment] => rag
required_facets = [coupon, environment] => rag_plus_tool
required_facets = [recommendation] => recommendation
```

多轮会话下：

```text
上一轮是推荐，本轮是单店有券
→ 本轮必须重新生成 coupon contract
→ 不能继续沿用 recommendation contract
上一轮是单店，本轮是“附近有没有适合约会、有券、现在还营业的餐厅？推荐几家”
→ 本轮必须重新生成 recommendation contract
→ 不能继续沿用单店 contract
```

---

### 6.3 Contract 影响 prompt

LLM prompt 中必须明确：

```text
本轮只允许回答：xxx
本轮禁止主动展开：xxx
如果证据不足，必须说明不足
```

---

### 6.4 Contract 影响最终 compose

最终回答前做一次校验：

```text
answer_linter.check(answer, contract, trace)
```

如发现轻微越界：

```text
裁剪或重写
```

如发现严重越界：

```text
记录 COMPOSE_CONTRACT_VIOLATION
返回安全降级回答
```

---

## 7. 验收标准

Day2 完成后必须满足：

```text
1. 问券只答券。
2. 问营业只答营业。
3. 问环境不主动查券。
4. 问综合评价可以多 facet，但不能编实时信息。
5. 复合问题按 facet 分块。
6. LLM prompt 不包含 forbidden context。
7. answer_linter 能发现并阻断 facet leak。
8. 多轮会话时，本轮 contract 一定来自最新一轮消息。
9. 推荐轮次不会继承上一轮单店 answer contract。
```

---

## 8. 给 Codex 的执行提示词

```text
你是资深 Context Engineering / LLM Answer Contract 工程师。

请增强本地生活 Agent 的 AnswerContract、Context Pruning 和 Answer Linter。

必须完成：
1. 排查当前 AnswerContract / response_builder / compose_answer / route_gate。
2. 定义 required_facets、optional_facets、forbidden_facets、allowed_tools、allowed_rag_facets。
3. 让 Contract 影响 route、RAG evidence、tool selection、prompt 和最终 compose。
4. 实现 Context Pruning，禁止把 forbidden facet evidence 注入 LLM。
5. 新增 answer_linter.py，检查：
   - facet leak
   - cross-shop leak
   - unsupported realtime claim
   - unsolicited recommendation
6. 新增测试：
   - 问券不答环境
   - 问营业不推荐
   - 问环境不查券
   - 复合问题分块回答
   - linter 能拦截违规答案
7. 所有测试必须走 /internal/v1/chat/stream。
8. 输出修改文件、测试命令、测试结果、剩余风险。

不要只写计划，必须完成代码修改和测试验证。
```
