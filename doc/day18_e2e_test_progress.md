# Day 18 - 端到端路由收口测试进展

## 测试概述

从 `/internal/v1/chat/stream` 接口出发，通过 `ChatStreamTestClient` 的 **in-process fallback** 模式（使用 FastAPI `TestClient` 直接调用应用），对路由收口后的全链路进行端到端验证。

### 测试范围

| 路由分支 | 测试用例 | 状态 |
|---------|---------|------|
| direct (闲聊/问候) | E2E-01: "你好" | ❌ 失败 |
| oos (超范围-天气) | E2E-02: "今天北京天气怎么样" | ❌ 失败 |
| oos (超范围-音乐) | E2E-03: "推荐一首好听的歌曲" | ❌ 失败 |
| single_shop (评价) | E2E-04: "海底捞怎么样" | ✅ 通过 |
| single_shop (口味) | E2E-05: "海底捞口味怎么样" | ✅ 通过 |
| recommendation (基础) | E2E-06: "上海有什么好吃的火锅推荐" | ✅ 通过 |
| recommendation (场景) | E2E-07: "推荐一家适合约会的餐厅" | ✅ 通过 |
| recommendation (附近) | E2E-08: "附近有什么好吃的餐厅推荐" | ✅ 通过 |
| comparison (对比) | E2E-09: "海底捞和巴奴哪个更适合约会" | ✅ 通过 |
| tool_coupon (优惠券) | E2E-10: "海底捞有券吗" | ✅ 通过 |
| tool_open (营业状态) | E2E-11: "海底捞现在营业吗" | ✅ 通过 |
| tool_distance (距离) | E2E-12: "海底捞离我多远" | ✅ 通过 |
| clarify (无店名代词) | E2E-13: "这家店有券吗" | ✅ 通过 |
| clarify (低信息量) | E2E-14: "。。。" | ✅ 通过 |
| facet_multi (多维度) | E2E-15: "海底捞有券吗，现在营业吗" | ✅ 通过 |
| multi_turn (代词追问) | E2E-16: "海底捞怎么样" → "这家店有券吗" | ✅ 通过 |
| client_context (前端注入) | E2E-17: shopId=12345 + "这家店有券吗" | ❌ 失败 |

### 总结：14/17 通过，3 个真实失败

---

## 失败分析

### 1. E2E-01 ~ E2E-03：问候与超范围识别不到位

**根因**：路由系统的 `required_action` 统一产出了 `direct_answer`，但 Workflow 后端的 `response_node` 没有正确标记为 `out_of_scope_response` 或 `safety_reject_response`。

- **E2E-01 ("你好")**：路由决策 `route_reason=rule_based_initial`, `required_action=direct_answer`。进入了 Workflow 但没有被标记为 out_of_scope。`ChatStreamTestClient._enrich_local_life_metrics` 中虽然有 `has_greeting` 检测逻辑，但因为底层 LLM 已经生成了回答文本（"我先按你的问题理解为：你好..."），`_enrich_local_life_metrics` 的问候检测没有覆盖到这种文本模式。

- **E2E-02 ("今天北京天气怎么样")**：路由决策 `route_reason=general_knowledge_query`, `required_action=direct_answer`。路由器正确识别为通用知识查询，但后续 Workflow 没有将其拦截为 out_of_scope。`_enrich_local_life_metrics` 中检测 `direct_non_local_response` 的逻辑依赖 `response_node in {"direct_chat_answer", "out_of_scope_response", "safety_reject_response"}`，但实际 response_node 为空。

- **E2E-03 ("推荐一首好听的歌曲")**：路由器将 `intent` 识别为 `local_life_recommend`（confidence=0.92），导致走了推荐路径。根因在于 "推荐" 关键词触发了推荐意图检测，路由器缺乏对非本地生活推荐（歌曲/电影/书籍等）的语义区分。

### 2. E2E-17：client_context 注入的 shopId 未被 Workflow 正确消费

**根因**：`extra_payload` 中传入的 `shopId` 和 `shopName` 放在了 `context` / `client_context` 字段中，但实际的 Workflow 适配器（`stages_front_a.py`）在解析 context 时，可能没有将 `shopId` / `shopName` 映射为 `selected_shop_id` / `selected_shop_name`。

日志显示：
```
routing_decision: raw_query="这家店有券吗", required_action=direct_answer, route_reason=single_shop_query
emit_final_debug: target_shop_name="这家", answer_style=coupon_only
```

路由器正确识别了 `single_shop_query`，但 target_shop 只解析到了 "这家" 而非 "海底捞(水晶城店)"。说明 `client_context` 中的 `shopId/shopName` 没有被正确透传到 entity resolver 层。

---

## 关键发现

### ✅ 正向验证

1. **核心路由链路完整**：single_shop / recommendation / comparison / tool_coupon / tool_open / tool_distance / clarify / facet_multi 全部正确路由
2. **多轮代词追问正常**：session_anchor 机制在多轮场景下正确工作
3. **RoutingPolicyValidator 收口生效**：所有请求都经过了统一路由决策
4. **LLM 路由决策质量可接受**：对本地生活查询的 intent 识别准确度较高

### ⚠️ 需改进

1. **out_of_scope 识别缺口**：问候和非本地生活推荐（歌曲推荐）未被正确拦截
2. **client_context 透传断裂**：前端注入的 shopId/shopName 在 Workflow 层未被消费
3. **Java 后端不可用**：所有 `http://127.0.0.1:8081/shop/*` 请求返回 502，说明 Java 商户服务未启动（预期行为，但影响实体解析精度）

---

## 后续建议

1. **修复 out_of_scope 识别**：在路由器的 rule-based 阶段增加对问候语和非本地生活话题的白名单/黑名单检测
2. **修复 client_context 透传**：在 `stages_front_a.py` 的 context 解析中，将 `client_context.shopId` 映射到 `selected_shop_id`
3. **考虑启动 Java 后端再跑一轮**：Java 商户服务可用后，实体解析精度会显著提升

---

## 测试文件

- 测试脚本: `learning-agent-service/tests/local_life/test_e2e_routing_convergence.py`
- 测试日志: `task-480.log`
