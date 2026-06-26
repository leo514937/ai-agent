# 09_端到端验收标准：Real LLM + Real ToolCall + 真实效果验收

## 1. 验收目标

本验收标准用于判断“问小团类本地生活助手 Agent”是否真正具备端到端产品可用性，而不是只在单元测试、fake LLM、mock 数据或模板兜底下跑通。

验收重点不是“代码有没有执行完”，而是验证系统是否能在真实链路中完成以下目标：

1. 用户问题能被正确路由到 Direct Answer / Safety / Local Life Agent。
2. 本地生活复杂 query 能通过 LangGraph 主链路完成 Plan → Execute → Review → Answer。
3. LLM 真实参与语义理解、任务规划辅助和最终表达，不能走 fake_llm / rule_based 主路径。
4. 商家、券、营业、距离、评价、团购等事实必须来自真实 ToolCall，不能来自 mock 数据或静态假数据。
5. 最终回答要对用户有实际消费决策价值，不能只是模板拼接或工具结果堆叠。
6. 多轮、省略、指代、候选澄清、多店对比、复杂条件筛选等场景必须端到端可用。

---

## 2. 一票否决项

只要出现以下任意一项，本轮验收直接判定为不通过。

| 编号 | 一票否决项 | 判定方式 |
| --- | --- | --- |
| F-01 | 主链路使用 fake_llm、rule_based_llm、SpyRealLLMBackend、FakeLLMBackend | Trace 中 `llm_backend`、`semantic_source`、`llm_called`、provider 标记检查 |
| F-02 | 正常运行链路使用 mock tool、mock data、静态商家列表、静态券列表 | ToolResult 中 `backend_source` / `data_source` 检查，代码扫描 `_MOCK`、`_DEAL_CATALOG` 等 |
| F-03 | 工具失败后伪造成功结果 | 注入工具失败用例，检查是否返回明确 failure / degraded |
| F-04 | 多候选商家默认选第一家 | 同名/相似店名 query 端到端测试 |
| F-05 | 最终回答出现工具未返回的商家、券、距离、评分、营业状态、团购 | AnswerVerifier + 人工抽检 |
| F-06 | Local Life query 绕过 LangGraph 主链路直接生成答案 | Trace 中缺少 graph node sequence |
| F-07 | 推荐 / 对比主要由模板 fallback 拼接完成 | Trace 中 `answer_mode=template_fallback` 或等价字段检查 |
| F-08 | 复杂 query 只靠关键词 if/else 特判通过 | 变体 query 对照测试失败或 trace 中缺少语义帧 / plan |
| F-09 | 端到端只测接口返回 200，不检查回答事实正确性 | 验收报告缺少 case-level fact check |
| F-10 | 用测试 fake 数据冒充真实工具结果 | ToolResult source 与测试环境标记不一致 |

---

## 3. 验收环境要求

### 3.1 LLM 环境

验收必须使用真实 LLM provider。

最低要求：

```bash
ENABLE_REAL_LLM=true
LOCAL_LIFE_LLM_BACKEND=openai_compatible
ENABLE_FAKE_LLM=false
ENABLE_RULE_BASED_LLM=false
ENABLE_LLM_VERBALIZER=true
```

Trace 必须满足：

- `llm_called=true`
- `semantic_source=llm`
- `llm_backend` 不得包含 `fake`、`stub`、`spy`、`rule_based`
- `provider` 必须是实际 provider，例如 `openrouter`、`openai_compatible` 或项目配置中的真实中转服务
- `model` 必须有实际模型名
- LLM 调用失败时，不能自动静默切回 fake / rule_based 主链路

### 3.2 工具与数据环境

验收必须使用真实 ToolCall 链路。

最低要求：

- Java 后端服务正常启动。
- Python Agent 通过 ToolCallGateway 访问 Java / 后端工具。
- 工具数据来自真实数据库或真实后端接口。
- ToolResult 中必须标记 `backend_source` / `data_source`。
- `backend_source` 不得为 `mock`、`fake`、`static`、`fixture`。
- 允许使用固定验收位置，但该位置必须作为测试用户画像或请求上下文显式输入，不能作为隐藏 mock 逻辑散落在代码中。

示例允许：

```text
验收用户位置 = 北京邮电大学海淀校区
source = test_profile.location
```

示例禁止：

```text
代码内部硬编码：如果没有位置，就默认北京邮电大学
```

### 3.3 Trace 环境

每个端到端 case 必须产出可审计 trace。

Trace 至少包含：

- `trace_id`
- `session_id`
- `top_route`
- `semantic_source`
- `llm_backend`
- `llm_called`
- `graph_nodes_visited`
- `goal_plan`
- `tool_plan`
- `plan_validation_result`
- `tool_calls`
- `tool_result_sources`
- `evidence_pack_id`
- `review_result`
- `answer_mode`
- `answer_verify_result`
- `fallback_reason`
- `final_answer`

---

## 4. 端到端验收总体指标

| 维度 | 指标 | 通过标准 |
| --- | --- | --- |
| 顶层路由 | Direct / Safety / Local Life 分类正确率 | 核心验收集 100%，扩展集 ≥ 95% |
| 真实 LLM | Local Life 主链路真实 LLM 调用率 | 100% |
| 真实工具 | 需要事实的 case 真实 ToolCall 覆盖率 | 100% |
| Mock 排除 | mock/fake/static 数据出现次数 | 0 |
| 商家绑定 | 涉及商家的回答 shop_id 绑定率 | 100% |
| 幻觉控制 | 工具未返回事实被回答使用次数 | 0 |
| 推荐有效性 | 推荐回答包含排序、理由、约束匹配说明 | ≥ 90% case 达标 |
| 对比有效性 | 对比回答包含共同维度、优劣、结论 | ≥ 90% case 达标 |
| 多轮恢复 | 指代 / 省略恢复正确率 | 核心验收集 100%，扩展集 ≥ 90% |
| 澄清正确性 | 歧义时澄清而非默认选择 | 100% |
| 失败降级 | 工具失败 / 空结果时可信降级 | 100% |
| 回答体验 | 人工评分 ≥ 4/5 | 核心 case 平均 ≥ 4.0 |
| 主链路完整性 | Local Life case 经过 Plan → Execute → Review | 100% |

---

## 5. 核心端到端 Case 矩阵

### 5.1 Direct Answer 验收

| Case | 用户输入 | 期望路由 | 必须满足 |
| --- | --- | --- | --- |
| D-01 | 你能做什么？ | Direct Answer | 不调用本地生活工具；说明能力边界 |
| D-02 | 你是谁？ | Direct Answer | 不误入商家推荐 |
| D-03 | 帮我解释一下 LangGraph | Direct Answer | 不调用商家工具 |
| D-04 | 我有点饿，你能帮我找吃的吗？ | Local Life Agent | 能识别为本地生活意图 |

通过标准：

- D-01 ~ D-03 不得出现 ToolCall。
- D-04 必须进入 Local Life Agent。
- Trace 中 `top_route` 必须与期望一致。

### 5.2 单店查询验收

| Case | 用户输入 | 期望行为 | 必须调用工具 |
| --- | --- | --- | --- |
| S-01 | 海底捞水晶城店怎么样？ | 解析目标店，输出综合评价 | resolve_shop / get_shop_detail / review_summary |
| S-02 | 山城一锅这家店有券吗？ | 查询券并说明是否有 | resolve_shop / get_coupon_list |
| S-03 | 这家店现在营业吗？ | 结合上下文查营业状态 | check_open_status |
| S-04 | 它离我多远？ | 基于上一轮店铺查距离 ETA | get_distance_eta |
| S-05 | 海底捞有券吗？ | 多候选时澄清具体门店 | resolve_shop |

通过标准：

- 涉及具体商家的回答必须有 `shop_id`。
- S-05 如果存在多个海底捞门店，必须澄清，不得默认第一家。
- 回答中的券、营业、距离、评价必须逐项来自 ToolResult。

### 5.3 附近推荐验收

| Case | 用户输入 | 期望行为 | 必须验证 |
| --- | --- | --- | --- |
| R-01 | 附近有什么好吃的？ | 推荐若干附近商家 | 有候选、有理由、有距离或位置依据 |
| R-02 | 推荐几家附近的火锅 | 按品类推荐 | 候选品类匹配火锅 |
| R-03 | 找几家便宜点、评分高、现在营业的店 | 多条件筛选 | 价格/评分/营业证据齐全或说明缺失 |
| R-04 | 附近有没有适合约会、现在营业、最好有券的火锅？ | 复杂场景推荐 | 场景、营业、券、品类均进入 plan/review |
| R-05 | 便宜一点的呢？ | 基于上一轮候选或目标重排 | 不误判新话题 |

通过标准：

- 推荐数量不得超过配置上限。
- 每个推荐候选必须有真实 shop_id。
- 推荐理由至少包含 2 个证据维度；证据不足时必须说明不确定。
- R-04 必须产生结构化 plan，不允许只靠模板回答。

### 5.4 多店对比验收

| Case | 用户输入 | 期望行为 | 必须验证 |
| --- | --- | --- | --- |
| C-01 | 海底捞和山城一锅哪个好？ | 两店对比并给建议 | 两店均 resolve 成 shop_id |
| C-02 | 这家和海底捞比呢？ | 先解析“这家”，再解析海底捞 | 指代恢复正确 |
| C-03 | 这三家哪个更适合聚餐？ | 基于上一轮候选比较 | comparison 链路，不走单店 |
| C-04 | 这六家哪个好？ | 超出上限时裁剪或澄清 | 不硬比较过多对象 |
| C-05 | 哪个性价比最高？ | 根据价格、券、评分等综合判断 | 结论有证据 |

通过标准：

- 对比对象必须明确，不能缺 shop_id。
- 对比必须包含共同维度，例如距离、价格、评分、券、营业、评价摘要。
- C-04 必须触发数量上限策略。
- 不能把 comparison 误走成单店详情查询。

### 5.5 多轮上下文验收

建议使用同一个 `session_id` 连续执行。

| Turn | 用户输入 | 期望状态变化 |
| --- | --- | --- |
| M-01 | 附近推荐几家火锅 | 保存候选列表、用户位置、品类偏好 |
| M-02 | 便宜一点的呢 | 继承火锅和附近约束，按价格/优惠重排 |
| M-03 | 第一家有券吗 | 解析第一家 shop_id，调用券工具 |
| M-04 | 这家和海底捞比呢 | 解析“这家”并进入 comparison |
| M-05 | 换个适合约会的 | 继承位置，更新场景偏好 |

通过标准：

- 每一轮都必须读写 SessionState。
- “第一家”“这家”“它”等指代解析正确率必须为 100%。
- 追问不能被错误判定为完全新话题。
- 如果上下文不足，必须澄清，不能猜测。

### 5.6 异常与降级验收

| Case | 注入条件 | 期望行为 |
| --- | --- | --- |
| E-01 | resolve_shop 无结果 | 先重试；若仍无精确目标，则推荐相似店铺并重新进入 Plan → Execute → Review |
| E-02 | coupon 工具空结果 | 先重试；若仍无该店券信息，则推荐同类有券店铺并重新进入 Plan → Execute → Review |
| E-03 | open_status 工具超时 | 明确说明营业状态暂时无法确认 |
| E-04 | distance 工具失败 | 不输出伪距离，提示距离不可用 |
| E-05 | review_summary 缺数据 | 说明评价信息不足，不生成虚假口碑 |
| E-06 | LLM provider 短暂失败 | 返回可控失败或重试，不静默切 fake_llm |

通过标准：

- 所有异常必须进入明确 error/degraded 分支。
- 最终回答不得伪装为完整成功。
- 对于店铺或券的精确目标找不到，系统应优先通过相似候选继续服务，而不是直接结束为澄清或失败。
- Trace 中必须记录失败节点和失败原因。

---

## 6. 真实效果人工评分标准

每个端到端 case 除自动断言外，还需要人工按 5 分制评分。

| 分数 | 标准 |
| --- | --- |
| 5 | 回答自然、结论明确、事实准确、理由充分、对消费决策很有帮助 |
| 4 | 回答基本自然，事实准确，理由较完整，有实际帮助 |
| 3 | 能回答问题，但理由弱、结构一般、消费决策价值有限 |
| 2 | 有明显遗漏、表达机械、推荐或对比价值较差 |
| 1 | 答非所问、事实错误、幻觉、错误路由或不可用 |

通过要求：

- 核心验收集平均分 ≥ 4.0。
- 任一 P0 case 低于 4 分，需要复盘。
- 任一 case 出现事实幻觉，直接判定该 case 不通过。

人工评分重点：

1. 用户是否能看懂结论。
2. 推荐理由是否具体。
3. 对比是否真正帮助选择。
4. 回答是否自然，不像模板拼接。
5. 不确定信息是否说清楚。
6. 是否避免把工具原始字段机械堆出。

---

## 7. 自动断言要求

每个端到端 case 至少需要以下断言。

### 7.1 路由断言

```text
top_route == expected_route
```

Local Life case 必须满足：

```text
graph_nodes_visited contains semantic_understanding
graph_nodes_visited contains plan
graph_nodes_visited contains execute
graph_nodes_visited contains review
graph_nodes_visited contains answer
```

### 7.2 LLM 断言

```text
llm_called == true
semantic_source == "llm"
llm_backend not in ["fake", "stub", "spy", "rule_based"]
```

### 7.3 工具断言

```text
for each tool_result:
    backend_source not in ["mock", "fake", "static", "fixture"]
    tool_name in ToolRegistry
    called_by == ToolCallGateway
```

### 7.4 证据断言

```text
for each factual_claim in final_answer:
    factual_claim must be supported by EvidencePack
```

事实类 claim 包括：

- 商家存在
- 门店名称
- 优惠券
- 团购套餐
- 营业状态
- 距离
- ETA
- 评分
- 人均
- 评价摘要
- 推荐理由中的客观事实

### 7.5 回答模式断言

```text
answer_mode != "template_fallback"
answer_verify_result == "passed"
fallback_reason is empty or non_blocking
```

### 7.6 多轮断言

```text
session_loaded == true
session_saved == true
resolved_references are correct
last_candidate_set is updated when needed
```

---

## 8. 验收报告格式

每次验收必须输出报告，不允许只贴测试 passed 数量。

报告至少包含：

```markdown
# E2E 验收报告

## 环境
- LLM Provider:
- LLM Model:
- ENABLE_REAL_LLM:
- ENABLE_FAKE_LLM:
- Java Backend:
- Python Agent:
- Database:
- User Location Source:

## 总体结果
- 总 case 数:
- 通过:
- 失败:
- 阻塞项:
- 平均人工评分:

## 一票否决检查
| 项 | 结果 | 证据 |
| -- | -- | -- |

## Case 明细
| Case | Route | LLM | Tool Source | Review | Verifier | 人工评分 | 结果 |
| -- | -- | -- | -- | -- | -- | -- | -- |

## 失败详情
- Case:
- 现象:
- Trace ID:
- 根因节点:
- 是否 mock/fake:
- 修复建议:

## 结论
- 是否通过端到端验收:
- 是否允许进入下一阶段:
```

---

## 9. 进入下一阶段的门槛

只有同时满足以下条件，才能判定通过端到端验收并进入下一阶段。

1. 一票否决项全部为 0。
2. P0 核心 case 全部通过。
3. Local Life case 真实 LLM 调用率为 100%。
4. 需要事实的 case 真实 ToolCall 覆盖率为 100%。
5. Mock / fake / static 数据在正常链路中出现次数为 0。
6. AnswerVerifier 幻觉检出为 0。
7. 多候选默认第一家次数为 0。
8. 工具失败伪装成功次数为 0。
9. 多轮核心链路 5 轮连续 case 全部通过。
10. 核心验收集人工平均分 ≥ 4.0。
11. 每个失败或降级 case 都能在 trace 中定位到具体节点。
12. 验收报告完整记录环境、case、trace、失败原因和结论。

---

## 10. 最终验收结论定义

### 通过

满足所有进入下一阶段门槛，且无 P0 / P1 阻塞问题。

### 有条件通过

允许存在少量 P2 体验问题，例如表达不够自然、排序解释不够充分，但不得存在 fake/mock、事实幻觉、错误路由、错误工具数据等可信问题。

### 不通过

出现以下任意情况即为不通过：

- fake_llm / mock 数据进入正常主链路。
- 本地生活复杂 query 未经过 Plan → Execute → Review。
- 工具结果为空却编造事实。
- 多候选默认第一家。
- 对比链路错误走成单店链路。
- 多轮指代核心 case 失败。
- 最终回答不能帮助用户做消费决策。

本验收标准强调真实端到端效果。测试 passed 数量只能作为辅助依据，不能替代真实 LLM、真实工具、真实数据、真实回答质量的验收。
