# 当前未解决问题 (TODO)

## ✅ 已解决：`test_candidate_reference_resolves_first_shop` 集成测试

> **2026-06-16 已关闭。** 问题根因见下方回顾。

### 回顾

四个缺陷叠加导致"第一家有券吗？"回退澄清的链路断裂问题，所有修复已生效：

| # | 文件 | 问题 | 状态 |
|---|---|---|---|
| Bug 1 | `stages_back_core.py` | 推荐响应不写 `last_candidates` | ✅ 已修复，服务已重启 |
| Bug 2 | `builder.py` | SSE payload 不含 `last_candidates` | ⏸️ 暂不修复（已绕过） |
| Bug 3 | `chat_test_client.py` | 客户端不填充 `last_candidates` | ✅ 已修复 |
| Bug 4 | `chat_test_client.py` | 代词覆盖逻辑误杀正确回答 | ✅ 已修复 |

**验证结果**：服务重启后 `test_candidate_reference_resolves_first_shop` 通过 ✅。第二轮"第一家有券吗？"正确解析第一家店铺并返回优惠信息。

---

## 🔴 新发现问题（回归测试暴露）

在运行完整回归测试套件时，发现了 **3 个预存失败测试**，均与上述修复无关，属于独立模块的历史问题。

---

### 问题 A：`test_entity_resolver_with_explicit_name` — `EntityResolver` 缺少 `resolve()` 方法

**文件**：`tests/local_life/test_coreference_resolution.py:257`
**错误**：`AttributeError: 'EntityResolver' object has no attribute 'resolve'`

#### 根因分析

**测试调用了一个不存在的 API。**

`EntityResolver` 类（`entity_resolver.py:78`）当前只暴露了 `resolve_target()` 方法（第 102 行），但测试代码在第 262 行调用的是 `resolver.resolve()`。

```python
# test_coreference_resolution.py:261-262
resolver = EntityResolver()
plan = resolver.resolve(           # ← resolve() 不存在！
    raw_query="海底捞水晶城店怎么样",
    ...
)
```

而实际实现的方法签名是：

```python
# entity_resolver.py:102-112
def resolve_target(
    self,
    *,
    raw_query: str,
    slots: Any,
    user_need: Any | None = None,
    session_context: Mapping[str, Any] | None = None,
    ...
) -> TargetShop:
```

**产生原因**：`EntityResolver` 的接口在重构过程中从 `resolve()` 改名为了 `resolve_target()`，参数也从位置参数改为了仅关键字参数。测试没有同步更新。

**影响范围**：仅此一个测试失败。`EntityResolver` 的其他调用方（如 `target_shop_policy.py`、`_review_impl`）都使用正确的 `resolve_target()`。

---

### 问题 B：`test_entity_reference_follow_up_uses_session_shop_anchor` — "这家"代词未解析为核心锚点

**文件**：`tests/local_life/test_context_four_cases_e2e.py:49`
**错误**：`merged.current_shop` 为 `"这家"`，期望 `"海底捞水晶城店"`

#### 根因分析

这是一个 **`_explicit_entity_from_query` 误将代词当作显式实体** 的问题，发生在 `query_merge.py:83-86`。

**数据流链路：**

```
raw_query = "这家有券吗？"
session_context 中有 current_shop="海底捞水晶城店", current_shop_anchor={...}

1. recover_follow_up_context() → follow_up_kind = "entity_reference" ✅ 正确

2. _explicit_entity_from_query("这家有券吗？")
   → 正则 r'^(?P<name>.+?)(?:有券吗)[？?]*$'
   → 匹配："这家"被捕获为 name → 返回 "这家"    ← ❌ 误判！
   → 期望：应该识别出"这家"是代词，不应作为显式实体返回

3. query_merge.py:83-86:
   if recovery.follow_up_kind == "entity_reference" and explicit_query_shop:
       current_shop = explicit_query_shop          # ← current_shop = "这家"
       merged_slots["shop_name"] = "这家"           # ← 错误！应是"海底捞水晶城店"
       merged_slots["shop_query"] = "这家"
```

**两个层面的缺陷叠加：**

1. **`_explicit_entity_from_query` 层**（`entity_resolver.py:19-53`）：正则捕获了代词"这家"作为"显式实体名"。该函数没有排除代词代指场景，把 `entity_reference` 的指代词当成了 `explicit_entity`。

2. **`merge_local_life_query_context` 层**（`query_merge.py:83-86`）：在 `entity_reference` 分支中，代码逻辑是"如果显式实体存在，就用它覆盖 current_shop"。但在此场景下，正确的做法应该是**从 session anchor 中获取已解析的店铺名**，而不是用从 query 中提取的代词原文。

**正确行为应该是**：当 `follow_up_kind == "entity_reference"` 且代词命中时，`current_shop` 应从 `persistent.current_shop` 或 `session_context` 中的 `current_shop_anchor` 获取，而不是从 query 字符串提取。

---

### 问题 C：`test_booking_query_maps_to_local_life_tool_turn` — 预订意图未触发 tool 路由

**文件**：`tests/test_chat_workflow.py:339`
**错误**：`result.needs_tool` 为 `False`，期望 `True`

#### 根因分析

**`_detect_local_life_intent()` 缺少预订（booking）意图检测分支。**

调用链路：

```
HeuristicModelGateway.classify_turn()
  → HeuristicIntentGate.fallback_decide()
    → _classify_local_life_turn()
      → _detect_local_life_intent("帮我订今晚七点两个人的位置")
        → _looks_like_nearby_recommendation   → False
        → _looks_like_coupon_and_environment   → False
        → compare token check                  → False
        → has_topic check (false: 无 topic_hint, 无 session 上下文)
          → False → return None               ← ❌ 无法路由
      → return None  (整个 local_life 路由被放弃)
  → fallback 到 knowledge 路由
    → intent = EXPLAIN
    → needs_tool = False (EXPLAIN 不需要 tool)  ← ❌
```

**核心缺失**：`domain_rules.py:128` 已经定义了 `booking_tokens = ("预订", "预约", "订位", "订桌", "booking", "reserve", "book")`，且 `_LOCAL_LIFE_TOOL_ACTIONS`（第 93 行）也包含了 `"booking"`。但：

1. **`_detect_local_life_intent()`**（`heuristics.py:438-447`）根本没有预订检测逻辑。
2. 预订词表只用于 `_looks_like_local_life_domain()` 的 domain 判定，但不影响 intent 分类。
3. `_LOCAL_LIFE_TOOL_ACTIONS` 只在 `_turn_result_to_fast_decision()` 中用于路由决策，但代码**永远到不了那一步**，因为 `_detect_local_life_intent` 先返回了 `None`。

**对比：优惠券查询（同测试类）为什么通过？**

| 测试 | 消息 | has_topic | action | 说明 |
|---|---|---|---|---|
| coupon test | "帮我看看这家店的优惠券" | True (有 topic_hint) | "detail" | 走 `has_topic=True → return "detail"` 路径 |
| booking test | "帮我订今晚七点两个人的位置" | False (无 topic_hint，persistent 为空) | None | 没有匹配，失败 |

`test_booking_query_maps_to_local_life_tool_turn` 没有设置 `topic_hint`，且 `persistent = PersistentSessionContext()` 全部为空，导致 `has_topic = False`，所有检测分支都落空。

---

## 回归测试结果总览

### 测试套件执行摘要（2026-06-16）

| 测试套件 | 总数 | 通过 | 失败 | 备注 |
|---|---|---|---|---|
| `test_target_shop_policy_harness.py` | 5 | **5** | 0 | ✅ 全部通过（含核心修复验证） |
| `test_coreference_resolution.py` | 15 | 10 | **1** | ❌ 问题 A：EntityResolver.resolve() 不存在 |
| `test_context_four_cases_e2e.py` | 4 | 2 | **1** | ❌ 问题 B："这家"代词未解析 |
| `test_chat_workflow.py` | 17 | 8 | **1** | ❌ 问题 C：预订意图未检测 |

### 新问题分类

| # | 类型 | 文件 | 预期修复难度 | 影响范围 |
|---|---|---|---|---|
| A | API 不匹配（测试未同步） | `test_coreference_resolution.py` / 测试代码 | 低 — 修复测试或添加 `resolve()` 别名 | 仅该测试 |
| B | 逻辑缺陷（代词误判为显式实体） | `query_merge.py:83-86` / `entity_resolver.py:_explicit_entity_from_query` | 中 — 需在 entity_reference 分支使用 session anchor | 影响代词解析准确性 |
| C | 功能缺失（booking intent 无检测分支） | `heuristics.py:_detect_local_life_intent` | 低 — 添加 booking 检测，类似 coupon 的处理 | 仅 booking 场景 |

### 三个问题的共同模式

1. **测试与实现的同步鸿沟** — A 是接口变更后测试未更新，B 和 C 是逻辑层新增功能后测试覆盖被遗漏。
2. **均不涉及本次 Bug 1-4 修复** — 重启服务前后的行为对这些测试无任何影响。
3. **均可独立修复** — 三个问题之间没有依赖关系。

---

*更新时间: 2026-06-16*
