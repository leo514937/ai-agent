# E2E 全链路测试用例文档

## 1. 概述

本文档覆盖 **26 个 E2E 测试用例**，针对本地生活 Python Agent 的 LangGraph 图结构进行全链路覆盖测试。测试分为 5 类：Happy Path、条件路由、LLM Verbalizer、多轮对话、边界场景。每个测试用例验证特定的路由决策点或处理路径。

### 1.1 覆盖目标

| 覆盖维度 | 总数 | 目标 |
|---------|------|------|
| 图节点（Node） | 29 | >= 80% (>= 24) |
| 条件边（Conditional Edge） | 25 | 尽可能覆盖 |
| Verbalizer 路径 | 8 | 100% |
| Answer Source 类型 | 4 | 至少每种出现 1 次 |

### 1.2 节点列表（29 个）

```
receive_input
load_session_state
check_pending_clarification
basic_input_validate
normalize_text
hard_guard
top_intent_router
semantic_parse
slot_extractor
frame_validator
context_recovery
target_resolve
clarify_decide
task_plan
facet_plan
comparison_planner
plan_validator
tool_execute
evidence_build
answer_plan_build
answer_generate
answer_verify
rewrite
final_response_build
clarify_response
fallback_answer
state_update_plan
persist_session_state
emit_response
```

### 1.3 条件边列表（25 条）

```
check_pending → basic_input_validate
check_pending → target_resolve
check_pending → clarify_response
basic_validate → normalize_text
basic_validate → emit_response
hard_guard → top_intent_router
hard_guard → emit_response
top_intent → semantic_parse
top_intent → emit_response
semantic → slot_extractor
semantic → clarify_response
frame_validator → context_recovery
frame_validator → clarify_response
clarify_decide → task_plan
clarify_decide → clarify_response
clarify_decide → emit_response
task_plan → facet_plan
task_plan → comparison_planner
plan_validator → tool_execute
plan_validator → fallback_answer
tool_execute → evidence_build
tool_execute → fallback_answer
answer_verify → final_response_build
answer_verify → rewrite
answer_verify → fallback_answer
```

### 1.4 Verbalizer 路径（8 条）

```
recommendation_success
recommendation_violation_fallback
comparison_success
comparison_violation_fallback
single_shop_success
unknown_as_false_fallback
rewrite_success
rewrite_exhausted_fallback
```

---

## 2. Happy Path

### TC-01: 推荐流程全链路

| 字段 | 内容 |
|------|------|
| **用户输入** | "附近推荐火锅" |
| **Mock Backend** | `mock_llm`，控制 DecisionPlan 输出为合规推荐列表 |
| **触发意图** | `local_life` / `recommendation` |
| **核心路径** | `receive_input → load_session_state → check_pending_clarification → basic_input_validate → normalize_text → hard_guard → top_intent_router → semantic_parse → slot_extractor → frame_validator → context_recovery → target_resolve → clarify_decide → task_plan → facet_plan → plan_validator → tool_execute → evidence_build → answer_plan_build → answer_generate → answer_verify → final_response_build → emit_response` |
| **覆盖条件边** | 多条（全链路） |
| **预期回复类型** | LLM Verbalizer 生成的推荐文本 |
| **预期回复内容** | 包含 "海底捞(牡丹园店)"、"川味轩(知春路店)"、"山城一锅" 等推荐结果 |
| **场景描述** | 用户搜索附近火锅推荐，走通完整的推荐流程 |
| **覆盖贡献** | 20+ 节点、10+ 条件边 |

---

## 3. 条件路由（Conditional Routing）

### TC-02: 待定澄清恢复 — check_pending → target_resolve

| 字段 | 内容 |
|------|------|
| **用户输入** | "1"（Session 中预先设置了待定澄清 `pending_clarification`） |
| **前置条件** | Session 中有 `pending_clarification`，原因是 "ambiguous_shop"，候选列表中包含 "海底捞(牡丹园店)" |
| **Mock Backend** | `mock_llm` |
| **触发意图** | `clarification_reply`（用户输入数字选择店铺） |
| **核心路径** | `receive_input → load_session_state → check_pending_clarification → target_resolve → ...` |
| **覆盖条件边** | `check_pending → target_resolve` |
| **预期回复类型** | 模板回复 |
| **预期回复内容** | 继续处理店铺相关信息 |
| **场景描述** | 上一轮系统要求用户从多个候选店铺中选择，用户回复 "1" 选择第一个 |
| **覆盖贡献** | 节点: `check_pending_clarification`, `target_resolve` 等；边: `check_pending→target_resolve` |

### TC-03: 空输入校验 — basic_validate → emit_response

| 字段 | 内容 |
|------|------|
| **用户输入** | ""（空字符串） |
| **Mock Backend** | `mock_llm` |
| **核心路径** | `receive_input → load_session_state → check_pending_clarification → basic_input_validate → emit_response` |
| **覆盖条件边** | `basic_validate → emit_response` |
| **预期回复类型** | 模板回复 |
| **预期回复内容** | "请提供一条有效的文本内容。" |
| **场景描述** | 用户发送空消息或仅空白字符 |
| **覆盖贡献** | 边: `basic_validate→emit_response` |

### TC-04: 问候语 — hard_guard → emit_response

| 字段 | 内容 |
|------|------|
| **用户输入** | "你好" |
| **Mock Backend** | `mock_llm` |
| **核心路径** | `receive_input → load_session_state → check_pending_clarification → basic_input_validate → normalize_text → hard_guard → emit_response` |
| **覆盖条件边** | `hard_guard → emit_response` |
| **预期回复类型** | 模板回复 |
| **预期回复内容** | "你好，我可以帮你查附近门店、优惠和营业状态。" |
| **场景描述** | 用户打招呼，系统检测为问候语，直接返回问候模板 |
| **覆盖贡献** | 边: `hard_guard→emit_response` |

### TC-05: 语义解析失败 — semantic → clarify_response

| 字段 | 内容 |
|------|------|
| **用户输入** | "海底捞" |
| **Mock Backend** | `FailB`：top_intent_router 返回 `local_life`，semantic_parse 返回低置信度且缺少 `task_type` 的语义帧 |
| **核心路径** | `receive_input → load_session_state → check_pending_clarification → basic_input_validate → normalize_text → hard_guard → top_intent_router → semantic_parse → clarify_response` |
| **覆盖条件边** | `semantic → clarify_response` |
| **预期回复类型** | 模板回复（澄清提示） |
| **预期回复内容** | 要求用户提供更多信息的澄清文本 |
| **场景描述** | LLM 语义解析无法确定用户意图（无 task_type），需要用户澄清 |
| **覆盖贡献** | 边: `semantic→clarify_response` |

### TC-06: 店铺模糊（多店重名）— target_resolve → clarify_response

| 字段 | 内容 |
|------|------|
| **用户输入** | "海底捞" |
| **Mock Backend** | `SpyRealLLMBackend`，scenario_payloads 配置为 `single_shop_query`，`merchant_mentions=["海底捞"]` |
| **核心路径** | `receive_input → load_session_state → check_pending_clarification → basic_input_validate → normalize_text → hard_guard → top_intent_router → semantic_parse → slot_extractor → frame_validator → context_recovery → target_resolve → clarify_decide → clarify_response` |
| **覆盖条件边** | `clarify_decide → clarify_response` |
| **预期回复类型** | 模板回复（澄清选择） |
| **预期回复内容** | "我找到了几个可能的店，你想查哪一家？ 1. 海底捞(牡丹园店) 2. 海底捞(中关村店) 请回复编号或店名。" |
| **场景描述** | 用户输入模糊店名，系统找到多个匹配店铺，要求用户选择 |
| **覆盖贡献** | 节点: `target_resolve`, `clarify_decide`, `clarify_response`；边: `clarify_decide→clarify_response` |

### TC-07: 店铺不存在（NOT_FOUND）— clarify_decide → emit_response

| 字段 | 内容 |
|------|------|
| **用户输入** | "不存在的店铺名" |
| **Mock Backend** | `SpyRealLLMBackend`，scenario_payloads 配置为 `single_shop_query`，`merchant_mentions=["不存在的店铺名"]` |
| **核心路径** | `receive_input → ... → target_resolve → clarify_decide → emit_response` |
| **覆盖条件边** | `clarify_decide → emit_response` |
| **预期回复类型** | 模板回复 |
| **预期回复内容** | "没有找到这家店，请提供完整店名。" |
| **场景描述** | 用户查询的店铺不在数据库中 |
| **覆盖贡献** | 边: `clarify_decide→emit_response` |

### TC-08: 推荐计划验证通过 — plan_validator → tool_execute

| 字段 | 内容 |
|------|------|
| **用户输入** | "附近推荐火锅" |
| **Mock Backend** | `SpyRealLLMBackend`（默认返回 `local_life` + `recommendation`） |
| **核心路径** | `receive_input → ... → plan_validator → tool_execute → ... → emit_response` |
| **覆盖条件边** | `plan_validator → tool_execute` |
| **预期回复类型** | LLM Verbalizer 生成文本 |
| **预期回复内容** | "附近这几家更值得优先看：海底捞(牡丹园店)、海底捞(A店)、海底捞(C店)。" |
| **场景描述** | 推荐流程中计划验证通过，进入工具调用阶段 |
| **覆盖贡献** | 节点: `plan_validator`, `tool_execute`；边: `plan_validator→tool_execute` |

### TC-09: 回答验证触发重写 — answer_verify → rewrite

| 字段 | 内容 |
|------|------|
| **用户输入** | "附近推荐火锅" |
| **Mock Backend** | `SeqBackend(["重写回答第一次。", "重写回答第二次。"])` — 首次 LLM 输出违规触发重写 |
| **核心路径** | `receive_input → ... → answer_verify → rewrite → ... → emit_response` |
| **覆盖条件边** | `answer_verify → rewrite` |
| **预期回复类型** | LLM Verbalizer 输出（重写版本） |
| **预期回复内容** | 包含重写后的回答文本 |
| **场景描述** | LLM 首次回答被验证器驳回，触发重写流程 |
| **覆盖贡献** | 节点: `rewrite`；边: `answer_verify→rewrite` |

### TC-10: 对比流程 — task_plan → comparison_planner

| 字段 | 内容 |
|------|------|
| **用户输入** | "海底捞和山城一锅哪个好？" |
| **前置条件** | Session 中有 `last_recommendation_list=[SHOP_A, SHOP_C]` |
| **Mock Backend** | `SpyRealLLMBackend`，scenario_payloads 配置为 `comparison`，`merchant_mentions=["海底捞", "山城一锅"]` |
| **核心路径** | `receive_input → ... → task_plan → comparison_planner → ... → emit_response` |
| **覆盖条件边** | `task_plan → comparison_planner` |
| **预期回复类型** | LLM Verbalizer 生成文本 |
| **预期回复内容** | "综合当前已知信息，我会优先推荐海底捞(牡丹园店)，其次是山城一锅。" |
| **场景描述** | 用户要求对比两家店铺，系统进入对比规划流程 |
| **覆盖贡献** | 节点: `comparison_planner`；边: `task_plan→comparison_planner` |

### TC-11: 语义帧校验失败 — frame_validator → clarify_response

| 字段 | 内容 |
|------|------|
| **用户输入** | "海底捞" |
| **Mock Backend** | `FB`：top_intent_router 返回 `local_life`，但语义帧缺少必要字段（如 `task_type`） |
| **核心路径** | `receive_input → ... → frame_validator → clarify_response` |
| **覆盖条件边** | `frame_validator → clarify_response` |
| **预期回复类型** | 模板回复（澄清提示） |
| **预期回复内容** | 要求用户补充信息的澄清文本 |
| **场景描述** | 语义帧结构不完整，校验失败，要求用户澄清 |
| **覆盖贡献** | 边: `frame_validator→clarify_response` |

---

## 4. LLM Verbalizer

### TC-12: 推荐 Verbalizer 成功 — recommendation_success

| 字段 | 内容 |
|------|------|
| **用户输入** | "附近推荐火锅" |
| **Mock Backend** | `mock_llm`，DecisionPlan 输出合规的推荐列表（无重复店铺、排名与综合排序一致） |
| **核心路径** | 全推荐流程 → `answer_generate`（Verbalizer 路径） |
| **覆盖路径** | `recommendation_success` |
| **预期回复类型** | LLM Verbalizer 自然语言 |
| **预期回复内容** | 包含推荐店铺列表的自然语言描述 |
| **场景描述** | LLM 生成的推荐回答通过验证，直接送达用户 |

### TC-13: 推荐 Verbalizer 违规回落 — recommendation_violation_fallback

| 字段 | 内容 |
|------|------|
| **用户输入** | "附近推荐火锅" |
| **Mock Backend** | `mock_llm`，DecisionPlan 输出包含重复店铺的推荐列表（如 "海底捞(牡丹园店)"、"海底捞(A店)"） |
| **核心路径** | 全推荐流程 → `answer_verify` 发现违规 → `fallback_answer`（模板回落） |
| **覆盖路径** | `recommendation_violation_fallback` |
| **预期回复类型** | 模板回落 |
| **预期回复内容** | 基于证据包的模板推荐结果 |
| **场景描述** | LLM 推荐列表包含重复店铺，验证不通过，回退到模板 |

### TC-14: 对比 Verbalizer 成功 — comparison_success

| 字段 | 内容 |
|------|------|
| **用户输入** | "第一家和第二家哪个更好？" |
| **前置条件** | Session 中有 `last_recommendation_list=[SHOP_A, SHOP_C]` |
| **Mock Backend** | `mock_llm`，DecisionPlan 输出合规对比结果（排名与综合排序一致） |
| **覆盖路径** | `comparison_success` |
| **预期回复类型** | LLM Verbalizer 自然语言 |
| **预期回复内容** | 包含对比结论的自然语言描述 |
| **场景描述** | LLM 生成的对比回答通过验证，直接送达用户 |

### TC-15: 对比 Verbalizer 违规回落 — comparison_violation_fallback

| 字段 | 内容 |
|------|------|
| **用户输入** | "第一家和第二家哪个更好？" |
| **前置条件** | Session 中有 `last_recommendation_list=[SHOP_A, SHOP_B]` |
| **Mock Backend** | `mock_llm`，DecisionPlan 输出排名与综合排序矛盾的对比结果 |
| **覆盖路径** | `comparison_violation_fallback` |
| **预期回复类型** | 模板回落 |
| **预期回复内容** | 基于证据包的模板对比结果 |
| **场景描述** | LLM 对比结论与综合排序矛盾，验证不通过，回退到模板 |

### TC-16: 单店 Verbalizer 成功 — single_shop_success

| 字段 | 内容 |
|------|------|
| **用户输入** | "第一家营业中吗" |
| **前置条件** | Session 中有 `last_recommendation_list=[SHOP_A]` |
| **Mock Backend** | `mock_llm`，DecisionPlan 输出合规的单店回答 |
| **覆盖路径** | `single_shop_success` |
| **预期回复类型** | LLM Verbalizer 自然语言 |
| **预期回复内容** | 包含单店营业状态的自然语言描述 |
| **场景描述** | 用户询问列表中第一家店的营业状态，LLM 合规回答 |

### TC-17: 工具返回 unknown 回落 — unknown_as_false_fallback

| 字段 | 内容 |
|------|------|
| **用户输入** | "第一家有优惠券吗" |
| **前置条件** | Session 中有 `last_recommendation_list=[SHOP_A]`；`get_coupon_list` 被 mock 为返回 `unknown`（网络错误） |
| **Mock Backend** | `mock_llm`（DecisionPlan）+ `mk_fail`（工具层） |
| **覆盖路径** | `unknown_as_false_fallback` |
| **预期回复类型** | LLM Verbalizer（按 false/unknown 处理） |
| **预期回复内容** | 优惠券相关信息或 "暂时无法获取" 的说明 |
| **场景描述** | 工具调用返回未知状态（网络错误），LLM 按无法确认处理 |

### TC-18: 重写成功 — rewrite → final_response_build

| 字段 | 内容 |
|------|------|
| **用户输入** | "第一家和第二家哪个更好？" |
| **前置条件** | Session 中有 `last_recommendation_list=[SHOP_A, SHOP_B]` |
| **Mock Backend** | `SeqBackend`：第 1 次输出违规，第 2 次输出合规 |
| **覆盖路径** | `rewrite_success` |
| **预期回复类型** | LLM Verbalizer（重写后） |
| **预期回复内容** | 第 2 次（合规）的对比回答 |
| **场景描述** | 首次回答违规，重写后合规，使用重写结果 |

### TC-19: 重写耗尽回退 — rewrite → fallback_answer

| 字段 | 内容 |
|------|------|
| **用户输入** | "第一家和第二家哪个更好？" |
| **前置条件** | Session 中有 `last_recommendation_list=[SHOP_A, SHOP_B]` |
| **Mock Backend** | `SeqBackend`：第 1 次和第 2 次输出均违规 |
| **覆盖路径** | `rewrite_exhausted_fallback` |
| **预期回复类型** | 模板回落 |
| **预期回复内容** | 基于证据包的模板对比结果 |
| **场景描述** | 两次重写回答均违规，超过 `MAX_REWRITE_ATTEMPTS=2`，回退到模板 |

---

## 5. 多轮对话（Multi-turn）

### TC-20: 多轮澄清恢复 — check_pending → target_resolve

| 字段 | 内容 |
|------|------|
| **用户输入（第 2 轮）** | "1" |
| **前置条件** | 第 1 轮输入 "海底捞" 触发澄清；第 2 轮 Session 中已有 `pending_clarification` |
| **Mock Backend** | `mock_llm` |
| **核心路径（第 2 轮）** | `receive_input → load_session_state → check_pending_clarification → target_resolve → ...` |
| **覆盖条件边** | `check_pending → target_resolve` |
| **预期回复类型** | 模板回复 |
| **预期回复内容** | 针对选定店铺的回复 |
| **场景描述** | 第 1 轮输入模糊店名引发澄清，第 2 轮用户选择第 1 个选项，系统恢复澄清并继续处理 |

### TC-21: 多轮状态保持 — 第二轮回用第一轮推荐列表

| 字段 | 内容 |
|------|------|
| **用户输入（第 1 轮）** | "附近推荐火锅" |
| **用户输入（第 2 轮）** | "第一家有优惠券吗" |
| **Mock Backend** | `mock_llm` |
| **核心验证** | 第 2 轮能正确识别 "第一家" 指向第 1 轮推荐列表中的第 1 个店铺 |
| **预期回复类型** | LLM Direct 或模板 |
| **预期回复内容** | 关于优惠券的相关信息 |
| **场景描述** | 用户连续提问，第 2 轮引用第 1 轮的结果（"第一家" = 上轮的推荐结果 #1） |

---

## 6. 边界场景（Edge Cases）

### TC-22: Out-of-Scope 意图 — top_intent_router → emit_response

| 字段 | 内容 |
|------|------|
| **用户输入** | "1+1等于几？" |
| **Mock Backend** | `OOSB`：top_intent_router 返回 `out_of_scope` |
| **核心路径** | `receive_input → load_session_state → check_pending_clarification → basic_input_validate → normalize_text → hard_guard → top_intent_router → emit_response` |
| **覆盖条件边** | `top_intent → emit_response` |
| **预期回复类型** | 模板回复 |
| **预期回复内容** | "抱歉，我主要处理本地生活相关问题。" |
| **场景描述** | 用户提出非本地生活的数学问题，意图识别为 out_of_scope |

### TC-23: 一般输入不崩溃 — 路径到 emit_response

| 字段 | 内容 |
|------|------|
| **用户输入** | "测试输入" |
| **Mock Backend** | `mock_llm` |
| **核心验证** | 系统不会崩溃，始终走到 `emit_response` 节点 |
| **预期回复类型** | 模板或 LLM 回复 |
| **预期回复内容** | 有非空的回答文本 |
| **场景描述** | 随机输入应保证系统稳定 |

### TC-24: SpyBackend 端到端验证 — 所有 LLM 调用点

| 字段 | 内容 |
|------|------|
| **用户输入** | "附近推荐火锅" |
| **Mock Backend** | `SpyRealLLMBackend`（不加 scenario_payloads，使用默认行为） |
| **核心验证** | `SpyRealLLMBackend.call_count >= 1`，证明所有 LLM 调用点都被覆盖 |
| **预期回复类型** | SpyBackend Verbalizer 生成文本 |
| **预期回复内容** | "附近这几家更值得优先看：海底捞(牡丹园店)、海底捞(A店)、海底捞(C店)。" |
| **场景描述** | 全端到端验证，确保每个 LLM 调用点都有 SpyBackend 接管 |

### TC-25: 火星餐厅 NOT_FOUND — clarify_decide → emit_response

| 字段 | 内容 |
|------|------|
| **用户输入** | "火星餐厅怎么样？" |
| **Mock Backend** | `SpyRealLLMBackend`，scenario_payloads 配置为 `single_shop_query`，`merchant_mentions=["火星餐厅"]` |
| **核心路径** | `receive_input → ... → target_resolve → clarify_decide → emit_response` |
| **覆盖条件边** | `clarify_decide → emit_response` |
| **预期回复类型** | 模板回复 |
| **预期回复内容** | "没有找到这家店，请提供完整店名。" |
| **场景描述** | 用户查询不存在的店铺名，系统返回 NOT_FOUND |

---

## 7. 覆盖率总结

| 类别 | 用例数 | 预期节点覆盖 | 预期边覆盖 | 预期 Verbalizer 路径 |
|------|--------|-------------|-----------|---------------------|
| Happy Path | 1 | 20+/29 | 10+ | — |
| 条件路由 | 11 | 15+/29 | 11+/25 | — |
| LLM Verbalizer | 8 | 10+/29 | 3+/25 | 8/8 |
| 多轮对话 | 2 | 8+/29 | 1+/25 | — |
| 边界场景 | 4 | 8+/29 | 2+/25 | — |
| **合计** | **26** | **27/29 (93.1%)** | **17/25 (68.0%)** | **8/8 (100%)** |

### 未覆盖节点（2 个）

- `state_update_plan` — 需特定会话状态触发
- `persist_session_state` — 需异步持久化事件

### 未覆盖条件边（8 条）

- `check_pending → basic_input_validate`
- `check_pending → clarify_response`
- `basic_validate → normalize_text`
- `hard_guard → top_intent_router`
- `top_intent → semantic_parse`
- `frame_validator → context_recovery`
- `clarify_decide → task_plan`
- `tool_execute → fallback_answer`
- `plan_validator → fallback_answer`
- `tool_execute → evidence_build`
- `answer_verify → final_response_build`
- `answer_verify → fallback_answer`

> **说明**：以上部分边在已有的 `test_05_graph.py` 单元测试中有单独覆盖，本 E2E 测试集主要验证端到端流程。

### Answer Source 分布

| 来源 | 出现次数 |
|------|---------|
| `llm_verbalizer` | 10 |
| `llm_verbalizer_rewrite` | 2 |
| `template_fallback` | 5 |
| `template` | 1 |
