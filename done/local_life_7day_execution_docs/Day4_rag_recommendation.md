# Day4：single_shop_rag + recommendation_rag + 多商铺推荐

> 来源：根据上传的 `local_life_agent_langgraph_7day_refactor_plan_v2_with_chat_stream_acceptance(1).md` 拆分整理。
>
> 总原则：
>
> - 每天都必须有 `/api/ai/chat/stream` 用户视角验收。
> - 每天都必须写清楚：参考架构、修改优先级、改动范围、验收输入、预期输出、完成标准。
> - Day1-Day4 先把业务不变量做硬；Day5-Day7 再把稳定节点迁移进 LangGraph。
> - 不允许只做单元测试；单元测试只能辅助，最终验收看 Chat 接口最终用户可见结果。


---

## 1. 当天目标

```text
1. 把 RAG 拆成 single_shop_rag 和 recommendation_rag。
2. 单店 RAG 必须按 shop_id 强过滤。
3. 推荐 RAG 必须 topK 后按 shop_id 分组。
4. 附近推荐默认输出 3 家不同商铺。
5. Day4 结束后，当前 5 个真实问题必须全部从 Chat 接口验证通过。
```

---

## 2. 修改优先级

| 优先级 | 内容 | 说明 |
|---|---|---|
| P0 | single_shop_rag shop_id 强过滤 | 解决 RAG 错店 |
| P0 | EvidenceScopeGuard 丢弃非目标店证据 | 防止问 A 答 B |
| P1 | recommendation_rag group by shop_id | 解决只推荐一家 |
| P1 | recommendation_count 默认 3 | 符合用户“推荐几家”的预期 |
| P1 | ResponseBuilder 多店推荐模板 | 输出 topN，不是 top1 |
| P2 | RAG trace 暴露 evidence shop_id | 方便 Day5-Day7 回归 |

---

## 3. 参考架构

### 3.1 改造后最终建议总图 (Day4 聚焦部分高亮)

```text
                      ┌──────────────────────┐
                      │    route_gate         │
                      └──────────┬───────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                  │
              ▼                  ▼                  ▼
     ┌────────────────┐ ┌────────────────┐ ┌────────────────────┐
     │ no_rag         │ │[single_shop_rag]│ │[recommendation_rag]│ ==> [Day4 物理划分为两大 RAG 模式]
     │ tool/direct    │ │[单店强过滤检索 ]│ │[多店检索与分组排名]│
     └────────────────┘ └───────┬────────┘ └─────────┬──────────┘
                                │                    │
                                ▼                    ▼
                  ┌──────────────────────┐  ┌──────────────────────┐
                  │[shop_id hard filter ]│  │[retrieve topK chunks ]│ ==> [Day4 隔离过滤规则与 topK 分组]
                  │[ target_shop only   ]│  │[ group by shop_id    ]│
                  └──────────┬───────────┘  └─────────┬────────────┘
                             │                        │
                             ▼                        ▼
                  ┌──────────────────────┐  ┌──────────────────────┐
                  │[ EvidencePack       ]│  │[ ShopGroupEvidence   ]│ ==> [Day4 规范化产出单店证据与多店证据组]
                  │[ 单店证据包         ]│  │[ 多店证据组           ]│
                  └──────────┬───────────┘  └─────────┬────────────┘
                             │                        │
                             └──────────┬─────────────┘
                                        ▼
                         ┌──────────────────────────┐
                         │ [EntityConsistency 对齐] │ ==> [Day4 强力对齐证据、工具与候选店的 shop_id]
                         └────────────┬─────────────┘
                                      ▼
                         ┌──────────────────────────┐
                         │ [Fusion / Rank 融合排序] │ ==> [Day4 单店锁死 target_shop，推荐输出 topN]
                         └────────────┬─────────────┘
                                      ▼
                         ┌──────────────────────────┐
                         │ AnswerContract            │
                         └────────────┬─────────────┘
                                      ▼
                         ┌──────────────────────────┐
                         │ ResponseBuilder          │
                         └──────────────────────────┘
```

### 3.2 当天要完成的架构链路与流转关系

在 Day4 阶段，我们要彻底打通并夯实 **RAG 召回的业务边界**，实现对证据链的强特异性隔离（单店 filter / 多店 group ），实现业务链路的最完美物理修复。

当天核心打通并锁定的链路流转关系如下：
```text
【模式确立】 single_shop_mode 或是 recommendation_mode
                  │
        ┌─────────┴─────────┐
        ▼                   ▼
【single_shop_mode】     【recommendation_mode】
  │                        │
  ▼                        ▼
[single_shop_rag]       [recommendation_rag]
  │                        │
  ├─ 必须强过滤 shop_id      ├─ 广谱召回 topK (如30~50个 chunks)
  │  仅保留 target_shop    ├─ 按 shop_id 物理分桶分组 (group by)
  │                        ├─ 动态解析 recommendation_count 数量 (1/3/5)
  ▼                        ▼
[EvidenceScopeGuard]    [ShopGroupEvidence] (多店证据包组)
  │  (丢弃全部非目标店)       │
  ▼                        ▼
[EvidencePack] (单店包)  [topN shops 候选集]
  │                        │
  └───────────┬────────────┘
              ▼
    【EntityConsistency】 （做三方会审：将 evidence、tool 结果与候选店进行 shop_id 最终强对齐）
              │
              ▼
    【Fusion / Rank】   （单店强行锁死并聚焦 target_shop，推荐多店则并排输出 topN shops 的综合报告）
```

> [!NOTE]
> **当前编排状态**：本阶段开发是业务正确性修复的最后一站（仍运行于 legacy 顺序链路下）。至此，包括“RAG召回不相关商铺、附近推荐只推荐一家”在内的 **5 个真实业务问题已经完全在物理链路上修复通过**！下一天我们将开启向真正的 LangGraph 图编排的大迁移。

---

## 4. 需要修改/新增的文件

可新增：

```text
learning-agent-service/src/learning_agent_service/local_life/rag_modes.py
learning-agent-service/tests/local_life/test_day4_rag_recommendation_chat.py
```

修改：

```text
learning-agent-service/src/learning_agent_service/local_life/subgraph.py
learning-agent-service/src/learning_agent_service/local_life/evidence_scope_guard.py
learning-agent-service/src/learning_agent_service/local_life/fusion.py
learning-agent-service/src/learning_agent_service/local_life/ranker.py
learning-agent-service/src/learning_agent_service/local_life/response_builder.py
learning-agent-service/src/learning_agent_service/local_life/route_review.py
learning-agent-service/src/learning_agent_service/local_life/user_need_parser.py
```

---

## 5. 详细任务

### 5.1 single_shop_rag

必须满足：

```text
single_shop_mode = true
target_shop.shop_id exists
retrieval filter: shop_id == target_shop.shop_id
EvidenceScopeGuard 再过滤一遍 evidence.shop_id
```

如果过滤后没有证据：

```text
回答该店可用信息不足
不得换另一家店回答
```

### 5.2 recommendation_rag

必须满足：

```text
recommendation_mode = true
recommendation_count = 3 / 5 / 1
retrieve topK chunks，建议 topK = 30 或 50
group by shop_id
aggregate evidence per shop
rank shop groups
return topN different shops
```

默认：

```text
附近有没有推荐的餐厅？ → 3 家
附近推荐一家餐厅 → 1 家
附近多推荐几家餐厅 → 5 家
```

---

## 6. Chat/stream 验收用例

### Case D4-1：single_shop_rag evidence 全部属于目标店

请求：

```json
{"sessionId":"day4-single-rag-001","userId":"test-user","message":"海底捞水晶城店环境怎么样？"}
```

预期：

```text
RAG evidence 必须全部属于目标店。
最终答案不得混入其他商铺。
```

断言：

```python
assert_trace_value(result, "single_shop_mode", True)
assert_all_evidence_shop_id_equals_target(result)
assert_not_other_shop_names(answer, allowed=["海底捞", "水晶城"])
```

### Case D4-2：第二家店 RAG 不混入第一家店

第一轮：

```json
{"sessionId":"day4-rag-switch-001","userId":"test-user","message":"海底捞水晶城店环境怎么样？"}
```

第二轮：

```json
{"sessionId":"day4-rag-switch-001","userId":"test-user","message":"巴奴毛肚火锅有啥特色？"}
```

预期：

```text
第二轮 RAG evidence 不得混入海底捞。
最终答案围绕巴奴。
```

断言：

```python
assert "巴奴" in answer2
assert "海底捞水晶城" not in answer2
assert_all_evidence_not_shop_name(result2, "海底捞")
```

### Case D4-3：附近推荐默认 3 家

请求：

```json
{"sessionId":"day4-reco-001","userId":"test-user","message":"附近有没有推荐的餐厅？"}
```

预期：

```text
默认推荐至少 3 家不同商铺。
如果数据不足，trace 必须显示 candidate_count < 3。
```

断言：

```python
shop_names = extract_shop_names(answer)
if len(shop_names) < 3:
    assert_trace_less_than(result, "recommendation.candidate_count", 3)
else:
    assert len(set(shop_names)) >= 3
```

### Case D4-4：用户明确推荐一家

请求：

```json
{"sessionId":"day4-reco-one-001","userId":"test-user","message":"附近推荐一家餐厅"}
```

预期：

```text
可以只推荐 1 家。
但必须有推荐理由。
```

断言：

```python
shop_names = extract_shop_names(answer)
assert len(set(shop_names)) == 1
assert_any_in(answer, ["推荐理由", "因为", "适合", "优点"])
```

### Case D4-5：多推荐几家

请求：

```json
{"sessionId":"day4-reco-many-001","userId":"test-user","message":"附近多推荐几家餐厅"}
```

预期：

```text
推荐 5 家左右。
如果数据不足，trace 必须说明 candidate_count。
```

断言：

```python
shop_names = extract_shop_names(answer)
if len(shop_names) < 5:
    assert_trace_less_than(result, "recommendation.candidate_count", 5)
else:
    assert len(set(shop_names)) >= 5
```

### 回归测试

必须继续运行：

```text
Day1：target_shop / 多轮实体覆盖
Day2：AnswerContract / ResponseBuilder
Day3：CouponResult / 多工具
```

---

## 7. Day4 完成标准

```text
1. D4-1 / D4-2 / D4-3 / D4-4 / D4-5 全部通过。
2. Day1-Day3 测试无回归。
3. 当前 5 个真实业务问题全部通过 Chat 接口验证。
4. RAG trace 中能看到 single_shop_rag / recommendation_rag 的 route。
```

---

## 8. 当天 Codex 执行提示词

```text
你是资深 Python / RAG / Qdrant / 本地生活推荐工程实现代理。今天只做 Day4：

1. 将 RAG 分为 single_shop_rag 和 recommendation_rag。
2. single_shop_rag 必须按 target_shop.shop_id 强过滤。
3. EvidenceScopeGuard 单店模式下必须丢弃非 target_shop 证据。
4. recommendation_rag 必须 topK 后 group by shop_id。
5. recommendation_count 默认 3，“推荐一家”为 1，“多推荐几家”为 5。
6. ResponseBuilder 推荐类输出 topN 商铺列表。
7. 新增 test_day4_rag_recommendation_chat.py。
8. 必须跑 Day1-Day3 回归测试。
```
