# 第一层：入口与上下文层 — 架构报告

> 分析日期: 2026-07-05
> 范围: `local_life_agent/engine/subgraphs/` 及关联模块
> 适用架构: LangGraph StateGraph，9 节点顶层编排

---

## 目录

1. [三层架构概览](#1-三层架构概览)
2. [第一层职责边界](#2-第一层职责边界)
3. [模块总览与数据流](#3-模块总览与数据流)
4. [intake_guard_router — 入口路由](#4-intake_guard_router--入口路由)
   - 4.1 整体输入
   - 4.2 步骤详解（7 步串行）
   - 4.3 最终路由决策
   - 4.4 关键代码位置
5. [merge_clarification — 澄清合并](#5-merge_clarification--澄清合并)
   - 5.1 触发条件
   - 5.2 步骤详解
   - 5.3 路由决策
6. [understanding_subgraph — 语义理解](#6-understanding_subgraph--语义理解)
   - 6.1 触发条件
   - 6.2 步骤详解（4 步串行）
   - 6.3 SemanticFrame 核心字段
7. [state_update_plan — 状态持久化](#7-state_update_plan--状态持久化)
   - 7.1 执行时机
   - 7.2 步骤详解（3 步串行）
   - 7.3 SessionState 核心字段
8. [第一层路由判定总表](#8-第一层路由判定总表)
9. [关键设计决策与注意事项](#9-关键设计决策与注意事项)

---

## 1. 三层架构概览

```
┌──────────────────────────────────────────────────────┐
│  第一层：入口与上下文层                                 │
│                                                       │
│  intake_guard_router   merge_clarification             │
│  understanding_subgraph   state_update_plan            │
│                                                       │
│  职责: 判断是不是本地生活、恢复多轮、生成 SemanticFrame、 │
│        持久化状态                                       │
└──────────────────────┬───────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────┐
│  第二层：任务决策与证据层                               │
│                                                       │
│  orchestration_router   planning_subgraph              │
│  execution_review_subgraph                             │
│                                                       │
│  职责: 决定查什么、调什么工具、收集什么事实、证据够不够    │
└──────────────────────┬───────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────┐
│  第三层：回答层                                        │
│                                                       │
│  response_subgraph   answer_verify                     │
│                                                       │
│  职责: 生成最终回答、校验忠实性、重写或降级              │
└──────────────────────────────────────────────────────┘
```

---

## 2. 第一层职责边界

第一层（Layer 1）是用户请求进入 LangGraph 后的第一站和最后一站。

**做的事**：
- ✅ 接收原始用户文本，做基本校验（空/超长/非法类型）
- ✅ 加载跨轮会话状态（current_shop / pending_clarification / comparison_targets 等）
- ✅ 文本标准化（Unicode NFKC、全角→半角标点、多余空白折叠）
- ✅ 硬安全守卫（区分正常 query / 打招呼 / 能力询问 / 违规）
- ✅ 活跃轮次解析（判断本轮是否在回复上一轮的澄清）
- ✅ 顶层意图路由（调用 LLM 分类：local_life / chat / unsafe / out_of_scope / capability / invalid）
- ✅ 澄清回复处理（用户回复了"A 店"→恢复语义帧继续执行）
- ✅ 语义理解（LLM 解析 → 槽位提取 → 帧校验 → 上下文恢复 → 生成 SemanticFrame）
- ✅ 跨轮上下文恢复（"这家"是哪个店？"第一家"是哪个？对比目标是谁？）
- ✅ 会话状态持久化（本轮结束后写回 session store）

**不做的事**：
- ❌ 不执行任何远程工具调用
- ❌ 不做业务数据的收集和聚合
- ❌ 不生成最终回答文本
- ❌ 不做 LLM 回答验证

---

## 3. 模块总参与数据流

```
输入: raw_text (用户原始文本)
                │
    ┌───────────▼───────────────┐
    │  ① intake_guard_router    │
    │   (engine/subgraphs/      │
    │    intake_guard_router.py) │
    └───────┬───────────────────┘
            │
     ┌──────┴──────────┐
     ▼                  ▼
② merge_            ③ understanding_
  clarification         subgraph
  (engine/subgraphs/    (engine/subgraphs/
   merge_clarification.  understanding_
   py)                   subgraph.py)
     │                  │
     └──────┬───────────┘
            ▼
      (到第二层)
            │
    ┌───────▼───────────────────┐
    │  ④ state_update_plan     │ ← 第三层执行完后执行
    │   (engine/subgraphs/      │
    │    state_update_plan.py)   │
    └───────┬───────────────────┘
            ▼
      final_response → AgentResponse
```

---

## 4. `intake_guard_router` — 入口路由

**文件**: `engine/subgraphs/intake_guard_router.py`

**调用链**: `graph_builder.build_graph()` → `_GRAPH_HANDLERS["intake_guard_router"]` → `h_intake_guard_router`

**LangGraph 位置**: START → `intake_guard_router`（第一条边）

### 4.1 整体输入

模块收到的初始 State 来自 `agent.py:run_agent_graph()` 第 220-278 行的 `initial` 字典：

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `raw_text` | str | `input_text` | 用户原始输入 |
| `session_id` | str | `""` | 会话 ID |
| `trace_id` | str | 自动生成 | 追踪 ID |
| `turn_id` | str | `""` | 轮次 ID |
| `user_id` | str | `""` | 用户 ID |
| `event_log` | list | `[]` | 执行事件日志（append-only） |

其余 60+ 字段初始化为空/None。

### 4.2 步骤详解（7 步串行）

#### 步骤 ①: `_h_receive_input`（第 142-150 行）

| 项目 | 内容 |
|---|---|
| **调用** | `input/receiver.py:receive_input()` |
| **读取** | `raw_text` |
| **写入** | `normalized_text ← raw_text`（暂存，标准化在后面） |
| | `input_type ← "text"`（或异常时 `"invalid"`） |
| | `turn_id ← state.turn_id` |
| **逻辑** | 调用 `receive_input()` 组装初始 TurnInput。该函数内部默认调用 `build_missing_user_context()` 注入 mock 地理位置（见 `receiver.py:24`）——即地理位置注入发生在 receiver 内部，不是 intake_guard_router 直接调用 |
| **文件** | `input/receiver.py:16-40`（核心逻辑），`core/state_core.py`（`build_missing_user_context` 定义） |

#### 步骤 ②: `_h_load_session`（第 153-177 行）

| 项目 | 内容 |
|---|---|
| **调用** | `session/store.py:get_session_store().load(session_id)` |
| **读取** | `session_id` |
| **写入** | `session_state` → 从 store 加载的完整 `SessionState` 对象 |
| | `session_state_before` → 深拷贝快照，供后续 diff |
| | `session_state_after` → `None` |
| | `current_shop` → 上一轮的当前店铺 |
| | `last_recommendation_list` → 上一轮推荐结果 |
| | `active_constraints` → 上一轮筛选条件 |
| | `comparison_result` → 上一轮对比结果 |
| | `pending_clarification` → 上一轮未完成的澄清（如有） |
| | `clarification_request` → 同上 |
| | `comparison_targets` → 上一轮对比目标 |
| | `active_turn_result` → `{}`（清空） |
| | `active_turn_route` → `""`（清空） |
| | `recommendation_candidates` → `[]`（清空） |
| | `pending_check_result` → `"pass"` |
| **存储** | `session/store.py:InMemorySessionStore`（内存字典 `_sessions: dict[str, SessionState]`） |

#### 步骤 ③: `_h_basic_validate`（第 180-196 行）

| 项目 | 内容 |
|---|---|
| **调用** | `input/validator.py:validate_basic_input()` |
| **读取** | `raw_text` |
| **校验规则** | 非字符串 → `INVALID_INPUT_TYPE` |
| | 空/纯空白 → `EMPTY_INPUT` |
| | 超过 2000 字符 → `INPUT_TOO_LONG` |
| **失败写入** | `input_type ← "invalid"` |
| | `error_code ← 对应错误码` |
| | `error_message ← 错误描述` |
| | `final_response ← "请提供一条有效的文本内容。"` |
| **通过写入** | `input_type ← "text"`, `error_code ← ""`, `error_message ← ""` |
| **文件** | `input/validator.py:15-62` |

#### 步骤 ④: `_h_normalize_text`（第 199-204 行）

| 项目 | 内容 |
|---|---|
| **调用** | `input/normalizer.py:normalize_text()` |
| **读取** | `raw_text` |
| **写入** | `normalized_text ← normalize_text(raw_text)` |
| **标准化操作** | Unicode NFKC 归一化 |
| | 全角标点→半角（，→, 。→. ！→! ？→? 等 20+ 映射） |
| | 连续空白→单空格 |
| | 首尾 trim |
| **文件** | `input/normalizer.py:41-50` |

#### 步骤 ⑤: `_h_hard_guard`（第 207-217 行）

| 项目 | 内容 |
|---|---|
| **调用** | `input/hard_guard.py:check_hard_guard()` |
| **读取** | `normalized_text` |
| **判定层级** | 空/纯标点 → `"invalid"` → reply: `"请提供一条有效的文本内容。"` |
| | 命中 `_BUSINESS_PATTERNS`（火锅/优惠/距离/附近/评分/店等 30+ 关键词）→ `"safe"` → 转 `"ok"` |
| | 纯打招呼（你好/Hi/在吗等）→ `"greeting"` → reply: `"你好，我可以帮你查附近门店、优惠和营业状态。"` |
| | 纯能力询问（你能做什么/你是谁等）→ `"capability"` → reply: `"我可以帮你查附近门店、优惠、距离和营业状态。"` |
| | 长度 ≤ 2 → `"invalid"` → reply: `"请换一种更明确的说法。"` |
| | 其他 → `"safe"` → 转 `"ok"` |
| **写入** | `guard_result ← "ok" / "greeting" / "capability" / "invalid"` |
| | `final_response ← 守卫拦截时的预置回答` |
| **提前路由** | 如果 `guard_result` 不是 `"ok"`，则在此处直接返回，**跳过步骤 ⑥ 和 ⑦** |
| **文件** | `input/hard_guard.py:73-132` |

#### 步骤 ⑥: `_h_active_turn_resolver`（第 73 行调用，实现在 `active_turn_resolver.py:603-657`）

| 项目 | 内容 |
|---|---|
| **文件** | `engine/subgraphs/active_turn_resolver.py`（685 行） |
| **职责** | 判断用户本轮输入是否在回复上一轮的澄清 |
| **流水线** | 4 层：规则层 → 模糊匹配层 → 有界 LLM 层（默认关）→ 统一校验层 |

**Layer 0 — 过期检测与语义快速检测**:

```
resolve_active_turn(text, pending)
  ├─ pending 为空 → normal_query
  ├─ 已过期 → pending_expired
  └─ 语义帧检测 → topic_switch（如果 detect 到 new_task_override）
```

**Layer 1 — 确定性规则**（`_rule_recognizer`, 第 132-206 行）：

| 规则 | 匹配方式 | 示例输入 | route |
|---|---|---|---|
| 取消词 | `_CANCEL_TERMS` 精确匹配 | "算了"、"不用了"、"放弃" | `pending_cancelled` |
| 纯数字 | `isdigit()` + 范围检查 | "2"（候选≤2时） | `pending_restored` |
| 纯数字超范围 | `isdigit()` + 超范围 | "5"（只有3候选） | `pending_out_of_range` |
| 中文序数 | `_CHINESE_ORDINAL_MAP` | "第一家"、"第2个" | `pending_restored` |
| 中文序数超范围 | 同上 | "第三家"（只有1候选） | `pending_out_of_range` |
| 指示词单候选 | `_CANDIDATE_POINTERS` + count==1 | "这个"、"选这家" | `pending_restored` |
| 精确名称匹配 | candidate.shop_name == compact | "海底捞(牡丹园店)" | `pending_restored` |

**Layer 2 — 模糊匹配**（`_fuzzy_recognizer`, 第 256-328 行）：

```
1. 提取候选名称变体：base_name, branch, branch_short, address, alias
2. 对用户输入：去掉弱语气词（_strip_weak_words）→ lowercase
3. 依次匹配：精准归一化 → 子串包含 → 变体含用户文本 → token 交集
4. 命中 1 个 → pending_restored；命中多个 → pending_invalid；命中 0 个 → 透传
```

**Layer 3 — 有界 LLM**（`_bounded_llm_recognizer`, 第 339-373 行）：

**默认关闭**（`_ENABLE_BOUNDED_PENDING_LLM = False`），用作用户输入无法被规则和模糊匹配覆盖时的最后兜底。

**Layer 4 — 统一校验**（`_validate_active_turn_result`, 第 381-450 行）：

对所有层的结果做最终校验：
- 过期检查（永远优先）
- pending_restored 必须有合法 index 和 candidate
- pending_out_of_range 确认 index 确实超范围
- topic_switch 必须有 new_query
- 置信度 < 0.5 → 降级为 pending_invalid

**写入字段**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `active_turn_result` | dict | 包含 `route` / `source` / `reason` / `confidence` / `selected_index` / `selected_candidate` |

**路由影响**（intake_guard_router.py 第 74-113 行）：

| active_route | 后续操作 |
|---|---|
| `"topic_switch"` | 清除所有 pending，继续到步骤 ⑦ `top_intent_router` |
| `"normal_query"` | 继续到步骤 ⑦ `top_intent_router` |
| `"pending_restored"` | **提前路由** → merge_clarification |
| `"pending_out_of_range"` | **提前路由** → merge_clarification |
| `"pending_expired"` | **提前路由** → merge_clarification |
| `"pending_invalid"` | **提前路由** → merge_clarification |
| `"pending_cancelled"` | 如果像话题切换→清除 pending 继续；否则→merge_clarification |

#### 步骤 ⑦: `_h_top_intent_router`（第 220-268 行）

| 项目 | 内容 |
|---|---|
| **调用** | `semantic/intent_parser.py:parse_top_intent()` |
| **读取** | `normalized_text` |
| **LLM 调用** | 调用 `call_llm` 对文本做顶层意图分类 |
| **写入** | `top_intent` ← `TopIntent` 枚举: `local_life` / `chat` / `unsafe` / `out_of_scope` / `capability` / `invalid` |
| | `top_intent_source` ← `"llm"` / `"fallback"` |
| | `top_intent_router_llm_available` ← bool |
| | `top_intent_router_backend` ← backend 名称 |
| | `error_code` ← LLM 调用错误码（local_life 时强制清空） |
| | `final_response` ← 非 local_life 时写入预置回答 |

**预置回答映射**：

| top_intent | final_response |
|---|---|
| `invalid` | `"请先输入一条有效的问题。"` |
| `chat` | `"我可以帮你查附近门店、优惠和营业状态。"` |
| `capability` | `"我可以帮你查附近门店、优惠、距离和营业状态。"` |
| `unsafe` / `out_of_scope` | `"抱歉，我主要处理本地生活相关问题。"` |
| `local_life` | 不清除 |

### 4.3 最终路由决策

**代码**: intake_guard_router.py 第 115-137 行

**写入两个路由字段**：

| 字段 | 值域 | 说明 |
|---|---|---|
| `intake_route` | `"terminal"` / `"clarification_reply"` / `"local_life"` | 条件边读取 |
| `response_mode` | `"answer"` / `"reject"` / intent 对应 mode | 传递给 response_subgraph |

**路由优先级表**（从高到低）：

| 优先级 | 条件 | intake_route | response_mode | 下一节点 |
|---|---|---|---|---|
| 1 | `error_code` 非空 | `"terminal"` | `"reject"` | response_subgraph |
| 2 | `guard_result` 非 `ok`/`safe` | `"terminal"` | `"reject"` | response_subgraph |
| 3 | 有 `pending_clarification` | `"clarification_reply"` | `"answer"` | merge_clarification |
| 4 | `top_intent == local_life` | `"local_life"` | `"answer"` | understanding_subgraph |
| 5 | 其他 | `"terminal"` | intent 对应 mode | response_subgraph |

### 4.4 关键代码位置

| 组件 | 文件 | 行号 |
|---|---|---|
| 外层 wrapper `h_intake_guard_router` | `engine/subgraphs/intake_guard_router.py` | 41-139 |
| `_h_receive_input` | 同上 | 142-150 |
| `_h_load_session` | 同上 | 153-177 |
| `_h_basic_validate` | 同上 | 180-196 |
| `_h_normalize_text` | 同上 | 199-204 |
| `_h_hard_guard` | 同上 | 207-217 |
| `_h_top_intent_router` | 同上 | 220-268 |
| `_h_active_turn_resolver` | `engine/subgraphs/active_turn_resolver.py` | 603-657 |
| `resolve_active_turn`（4 层流水线） | 同上 | 458-525 |
| 规则层 `_rule_recognizer` | 同上 | 132-206 |
| 模糊层 `_fuzzy_recognizer` | 同上 | 256-328 |
| 校验层 `_validate_active_turn_result` | 同上 | 381-450 |
| `check_hard_guard` | `input/hard_guard.py` | 73-132 |
| `normalize_text` | `input/normalizer.py` | 41-50 |
| `validate_basic_input` | `input/validator.py` | 60-62 |
| `receive_input` | `input/receiver.py` | 16-40 |
| `get_session_store` | `session/store.py` | 47-49 |
| `InMemorySessionStore.load` | `session/store.py` | 17-24 |
| 条件边路由函数 `_route_intake_guard` | `engine/_routes.py` | 287-288 |
| 路由表 `_GRAPH_INTAKE_ROUTES` | `engine/_routes.py` | 407-413 |

---

## 5. `merge_clarification` — 澄清合并

**文件**: `engine/subgraphs/merge_clarification.py`

**LangGraph 位置**: `intake_guard_router` → `merge_clarification`（当 `intake_route == "clarification_reply"`）

### 5.1 触发条件

```python
# _GRAPH_INTAKE_ROUTES: 当 intake_route == "clarification_reply" 时
# 条件边指向 merge_clarification
```

**进入场景**：上一轮发出了澄清（如"A 店还是 B 店？"），本轮用户回复了选择（数字/店名/序数等），且 active_turn_resolver 判定为 `pending_restored` / `pending_out_of_range` / `pending_expired` / `pending_invalid` / `pending_cancelled`。

### 5.2 步骤详解

#### 步骤: `_h_check_pending`（第 60-194 行）

| 项目 | 内容 |
|---|---|
| **调用** | `target/clarification.py:handle_clarification_reply()` |
| **读取** | `raw_text` — 用户的回复文本 |
| | `pending_clarification` — 上一轮发出的澄清 |
| | `session_state` — 会话状态 |

`handle_clarification_reply` 的处理逻辑（`target/clarification.py`）：

1. 检查过期
2. 检测取消/话题切换倾向
3. 根据 missing_slot_type 和用户输入做匹配
4. 返回 `result.status`

**写入字段**：

| 字段 | 值域 | 说明 |
|---|---|---|
| `pending_check_result` | `"restore"` / `"topic_switch"` / `"pass"` / `"cancelled"` / `"invalid"` / `"expired"` / `"out_of_range"` | 判定结果 |
| `merge_clarification_result` | 同上 | 冗余字段 |
| `clarification_result` | 同上 | 冗余字段 |
| `clarification_resolution` | dict | 解析详情 |

**`"restore"` 时额外恢复的字段**（第 83-122 行）：

| 字段 | 说明 |
|---|---|
| `pending_clarification` → `None` | 清除待处理澄清 |
| `semantic_frame` | 恢复之前保存的语义帧 |
| `task_type` | 恢复之前的任务类型 |
| `resolved_target` | 用户选中的目标 |
| `resolve_shop_result` | 与 resolved_target 相同 |
| `comparison_targets` | 对比目标列表 |
| `selected_candidate` | 选中的候选店铺 |
| `selected_index` | 选中的序号（1-based） |
| `current_shop` | 设为选中候选 |
| `clarification_request` → `None` | 清除澄清请求 |
| `final_response` → `""` | 清除预置回答 |

**`"topic_switch"` 时清除的字段**（第 124-149 行）：

| 清除字段 | 说明 |
|---|---|
| `pending_clarification` → `None` | 清除待处理澄清 |
| `clarification_request` → `None` | |
| `selected_candidate` → `None` | |
| `selected_index` → `0` | |
| `last_candidate_set` → `[]` | |
| `last_candidate_spec` → `None` | |
| `active_goal` → `None` | |
| `resolved_target` → `None` | |
| `resolve_shop_result` → `None` | |

### 5.3 路由决策

**代码**: `h_merge_clarification` 第 36-57 行

| pending_check_result | merge_clarification_route | response_mode | 下一节点 |
|---|---|---|---|
| `"restore"` | `"execute"` | `"answer"` | **planning_subgraph**（第二层） |
| `"topic_switch"` / `"pass"` / `"cancelled"` | `"proceed"` | `"answer"` | **understanding_subgraph** |
| `"invalid"` / `"expired"` / `"out_of_range"` | `"clarify"` | `"clarify"` | **response_subgraph**（第三层） |

---

## 6. `understanding_subgraph` — 语义理解

**文件**: `engine/subgraphs/understanding_subgraph.py`

**LangGraph 位置**: 从 `intake_guard_router`（`local_life`）或 `merge_clarification`（`topic_switch`）进入。

### 6.1 触发条件

```python
# 场景 1: intake_guard_router 判定 top_intent == local_life
_GRAPH_INTAKE_ROUTES["local_life"] → "understanding_subgraph"

# 场景 2: merge_clarification 判定用户切换了话题
_GRAPH_MERGE_ROUTES["proceed"] → "understanding_subgraph"
```

### 6.2 步骤详解（4 步串行）

#### 步骤 ①: `_h_semantic_parse`（第 89-203 行）

| 项目 | 内容 |
|---|---|
| **调用** | `semantic/intent_parser.py:parse_semantic_frame()` |
| **读取** | `normalized_text` — 用户输入 |
| | `top_intent` — 已判定的顶层意图 |
| | `session_state_before` — 用于多轮上下文注入 |
| **LLM 调用** | 调用 `call_llm` 将自然语言解析为 `SemanticFrame` |
| **fallback** | 允许降级（`config.SEMANTIC_FALLBACK_ENABLED`） |
| **写入** | `semantic_frame` — `SemanticFrame` 对象或 None |
| | `semantic_source` — `"llm"` / `"fallback"` |
| | `llm_backend` — LLM backend 名称 |
| | `llm_called` — bool |
| | `dropped_facets` — 校验时过滤掉的 facet 名称（字段名 `dropped_facets`，非 `drop_facets`） |
| | `error_code` — 错误码（`SCHEMA_VALIDATION_FAILED` / `MISSING_TASK_TYPE` / 空） |
| | `error_message` — 错误描述 |
| | `fallback_reason` — 降级原因 |

#### 步骤 ②: `_h_slot_extractor`（第 206-228 行）

| 项目 | 内容 |
|---|---|
| **读取** | `semantic_frame`, `raw_text` |
| **逻辑** | 如果 LLM 未提取 merchant_mentions，从原文用 `_infer_explicit_mentions_from_text` 提取 |
| | 如果 `deictic_references` 为空，从原文搜索"这家/那家/它/这间/那间" |
| | 如果 `ordinal_references` 为空，从原文 regex 搜索"第 X 个/家/间/店" |
| **写入** | 补充后的 `semantic_frame` |

#### 步骤 ③: `_h_frame_validator`（第 231-255 行）

| 项目 | 内容 |
|---|---|
| **调用** | `semantic/frame_validator.py:validate_frame()` |
| **读取** | `semantic_frame` |
| **校验规则** | `missing_task_type` → `error_code = "MISSING_TASK_TYPE"` |
| | `missing_merchant_mentions` → `error_code = "MISSING_MERCHANT_MENTION"` |
| | `invalid_task_type` → `error_code = "INVALID_ARGUMENT"` |
| | `forbidden_field:*` → `error_code = "SCHEMA_VALIDATION_FAILED"` |
| | `needs_context` → `error_code = ""`（允许通过） |
| | 其他 → `error_code = "SEMANTIC_FRAME_INVALID"` |
| **写入** | `error_code`（非空时触发 clarify 路由） |
| | `error_message`（校验失败时的澄清提示） |

#### 步骤 ④: `_h_context_recovery`（第 258-417 行）

| 项目 | 内容 |
|---|---|
| **调用** | `target/context_recovery.py:recover_context()` |
| **读取** | `session_state_before` — 会话记忆 |
| | `semantic_frame` — 当前语义帧 |
| | `raw_text` — 原文 |
| **处理三种情况** | 有显式 `merchant_mentions` → 直接返回，无需上下文恢复 |
| | `task_type == "comparison"` → 调用 `resolve_comparison_targets()` 解析对比目标 |
| | 有指示词/序数/引用 → 调用 `resolve_references()` 从 session 历史中恢复 |
| | 单一商户提及不包含括号/店后缀 → 尝试 `resolve_shop`，模糊时创建 PendingClarification |
| **写入** | `resolved_target` — 解析出的具体目标 |
| | `comparison_targets` — 对比目标列表 |
| | `comparison_target_resolution` — 对比解析详情 dict |
| | `reference_resolution_source` — 引用解析来源描述 |
| | `pending_clarification` — 如果模糊，创建 PendingClarification 对象 |

### 6.3 SemanticFrame 核心字段

**类型**: `domain/schemas.py` — `SemanticFrame` Pydantic 模型

| 字段 | 类型 | 说明 | 示例 |
|---|---|---|---|
| `task_type` | `TaskType` | 任务类型 | `single_shop_query` |
| `primary_task` | str | 主要任务描述 | "查营业状态" |
| `merchant_mentions` | list[str] | 用户提到的商户 | `["海底捞"]` |
| `branch_mentions` | list[str] | 分店名称 | `["牡丹园店"]` |
| `reference_mentions` | list[str] | 引用表达 | `["这家店"]` |
| `deictic_references` | list[str] | 指示词 | `["这家"]` |
| `ordinal_references` | list[str] | 序数引用 | `["第一家"]` |
| `focused_facets` | list[str] | 关注的方面 | `["open_status", "coupon"]` |
| `location` | dict/None | 地理位置 | `{"lat": 39.98, "lng": 116.33}` |
| `hard_constraints` | dict | 硬约束 | `{"category": "火锅"}` |
| `soft_preferences` | dict | 软偏好 | `{"price_range": "100-200"}` |
| `comparison_targets` | list | 对比目标 | |
| `need_context` | bool | 是否需要多轮上下文 | `true` |
| `scene` | str | 场景描述 | |
| `time` | str | 时间描述 | "中午" |
| `follow_up` | `FollowUp`/None | 多轮指代信息 | |

### 6.4 最终路由决策

**代码**: `h_understanding_subgraph` 第 38-81 行

| 条件 | understanding_route | response_mode | 下一节点 |
|---|---|---|---|
| `error_code` 非空（语义解析失败/校验失败/上下文恢复失败） | `"clarify"` | `"clarify"` | **response_subgraph** |
| 全部通过 | `"proceed"` | `"answer"` | **orchestration_router_shadow** → **workflow_runner** → **planning_subgraph**（第二层） |

---

## 7. `state_update_plan` — 状态持久化

**文件**: `engine/subgraphs/state_update_plan.py`

**LangGraph 位置**: **整张图的最后一个节点**，`response_subgraph` → `state_update_plan` → `END`

### 7.1 执行时机

只有第三层 `response_subgraph` 执行完毕（无论走的是正常回答路径还是澄清/降级路径），数据才流入此模块。

### 7.2 步骤详解（3 步串行）

#### 步骤 ①: `_h_state_update_plan`（第 48-135 行）

| 项目 | 内容 |
|---|---|
| **调用** | `core/StateCore.plan_state_update()` → `StateCore.build_state_patch()` |
| **读取** | `resolved_target` — 本轮店铺解析结果（**优先**，来自 context_recovery 或 merge_clarification 的 restore） |
| | `resolve_shop_result` — 相同语义的兜底字段（仅当 `resolved_target` 为空时降级使用） |
| | `pending_clarification` — 本轮待处理澄清 |
| | `task_type` — 本轮任务类型 |
| | `comparison_targets` / `comparison_target_resolution` — 对比信息 |
| | `evidence_pack` — 证据包（对比矩阵等） |
| | `execution_plan` / `validated_plan` — 执行计划 |
| | `tool_result_set` — 工具执行结果 |
| | `workflow_name`, `local_life_goal_draft` 等 |
| **写入** | `state_update_plan` — `SessionWriteDirective` 对象 |
| | 包含 `set_fields: dict`（要更新的字段名→值映射） |
| | 包含 `clear_fields: list`（要重置为默认值的字段名列表） |

#### 步骤 ②: `_h_persist_session`（第 138-190 行）

| 项目 | 内容 |
|---|---|
| **调用** | `session/store.py:get_session_store().save(session_id, updated_state)` |
| **读取** | `session_state` — 当前会话状态 |
| | `state_update_plan` — 更新指令 |
| **操作** | 遍历 `set_fields`：对每个 field_name 设置 `session_state.field_name = value` |
| | 遍历 `clear_fields`：对每个 field_name 重置为 `SessionState()` 默认值 |
| **额外逻辑** | 如果 `comparison_target_resolution` 为空且 `task_type == comparison` 且有 comparison_targets，自动构建 `comparison_target_resolution`（推断 RESOLVED 或 NEED_CLARIFICATION，见 `state_update_plan.py:75-81`） |
| | 如果 `comparison_target_resolution.status == "RESOLVED"`，将 resolved targets 写入 `session_state.comparison_targets` |
| | 如果 `comparison_result.rows` 存在且无 pending，写入 comparison_targets |
| | `comparison_targets` 的优先级来源链：`comparison_target_resolution.targets` > `state.comparison_targets` > `semantic_frame.comparison_targets` |
| **写入** | `session_state` — 更新后的完整状态 |
| | `session_state_after` — 持久化后的深拷贝快照 |
| | `current_shop`, `last_recommendation_list`, `active_constraints`, `comparison_result`, `pending_clarification`, `comparison_targets` — 从 session_state 透出 |

#### 步骤 ③: `_h_emit_response`（第 193-194 行）

| 项目 | 内容 |
|---|---|
| **操作** | 纯日志记录，不修改任何 state 字段 |
| **日志** | `"emit_response"` 事件写入 event_log |

### 7.3 SessionState 核心字段

**类型**: `domain/state.py` — `SessionState` Pydantic BaseModel

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `current_shop` | dict/None | None | 当前查看的店铺 |
| `last_recommendation_list` | list | `[]` | 最后推荐列表 |
| `active_constraints` | dict | `{}` | 活跃筛选条件 |
| `pending_clarification` | PendingClarification/None | None | 待处理澄清 |
| `comparison_targets` | list | `[]` | 对比目标列表 |
| `comparison_result` | dict/None | None | 对比结果 |
| `active_goal` | dict/None | None | 当前活跃目标 |
| `replan_counters` | dict | `{}` | 重规划计数（`replan_evidence` / `expand_search`），跨轮持久化，默认最多各 1 次 |
| `last_candidate_set` | list | `[]` | 最后候选集 |
| `last_candidate_spec` | dict/None | None | 最后候选规格 |
| `review_results` | dict | `{}` | 审查结果记录 |

**持久化存储**：

```python
# session/store.py
class InMemorySessionStore:
    _sessions: dict[str, SessionState]  # 进程内内存字典

    def load(session_id) -> SessionState  # 不存在时返回空 SessionState
    def save(session_id, state) -> None   # 深拷贝后存储
```

---

## 8. 第一层路由判定总表

### intake_guard_router 最终路由

| # | 条件链路 | intake_route | 下一节点 |
|---|---|---|---|
| 1 | basic_validate 失败 | `"terminal"` | response_subgraph |
| 2 | hard_guard 拦截（greeting/capability/invalid） | `"terminal"` | response_subgraph |
| 3 | active_turn_resolver 判定 pending_restored/out_of_range/expired/invalid/cancelled | `"clarification_reply"` | merge_clarification |
| 4 | top_intent_router 判定 local_life | `"local_life"` | understanding_subgraph |
| 5 | top_intent_router 判定 chat/unsafe/out_of_scope/capability/invalid | `"terminal"` | response_subgraph |

### merge_clarification 路由

| pending_check_result | merge_clarification_route | 下一节点 |
|---|---|---|
| `"restore"` | `"execute"` | planning_subgraph |
| `"topic_switch"` / `"pass"` / `"cancelled"` | `"proceed"` | understanding_subgraph |
| `"invalid"` / `"expired"` / `"out_of_range"` | `"clarify"` | response_subgraph |

### understanding_subgraph 路由

| 条件 | understanding_route | 下一节点 |
|---|---|---|
| error_code 非空 | `"clarify"` | response_subgraph |
| 全部成功 | `"proceed"` | orchestration_router_shadow |

---

## 9. 关键设计决策与注意事项

### 9.1 安全守卫的业务关键词优先

`hard_guard` 先检查 `_BUSINESS_PATTERNS`（30+ 本地生活关键词），再检查打招呼/能力询问。这意味着 **"你好，附近有什么火锅店"这样的混合输入会安全通过**，不会被拦截为问候语。

### 9.2 活跃轮次解析采用"规则优先"策略

`active_turn_resolver` 的 4 层流水线从最确定性的规则开始（数字、序数、取消词），逐步过渡到模糊匹配和 LLM。**LLM 层默认关闭**，保证延迟可控且行为可预测。

### 9.3 匿名/无 token 用户的处理

如 `arc/ai_chat_auth_flow_arc.md` 所述，`RefreshTokenInterceptor` 在无 token 时会塞一个 mock 用户（id=1010, nickName="AI_Mock_User"）。这个 mock 用户的 `user_id` 最终通过 Java 端的 `AiRemoteClient` 传到 Python 端的 `run_agent_graph()` 的 `initial["user_id"]`。

### 9.4 会话状态是全内存的

`InMemorySessionStore` 是进程内内存字典，**不是 Redis 或数据库**。这意味着：
- 服务重启后所有会话丢失
- 多实例部署时无法共享会话
- 适用于开发和单实例测试

### 9.5 SemanticFrame 是整个链路的"语义黄金"

`understanding_subgraph` 产出的 `SemanticFrame` 是第一层传递给第二层的最核心数据结构。第二层的 `goal_planner`、`target_resolve`、`evidence_planner` 都依赖它的字段做决策。如果 `semantic_frame` 质量不高，后续所有规划都会偏差。

### 9.6 state_update_plan 是唯一写 session 的地方

全图 9 个节点中，只有 `state_update_plan` 的 `persist_session` 步骤会调用 `session_store.save()`。其他节点读 session 但不写持久化存储，保证写入路径单一可控。

### 9.7 GraphState 字段名约定：`p2_decision_plan`

第二层和第三层间传递的决策计划，在 `GraphState` 中的实际字段名为 **`p2_decision_plan`**（而非 `decision_plan`）。这是由于状态字段按写入方（owner）分组命名的约定。`decision_to_answer_plan()`（第三层 `_h_answer_plan_build` 调用）从 `p2_decision_plan` 读取、写入 `answer_plan`。

同理，`execution_plan` 与 `validated_plan` 也是两个不同字段：`validated_plan` 是 `plan_validator` 校验通过后的输出，`execution_plan` 是 `evidence_planner` 的原始输出。

### 9.8 项目 AGENTS.md 约束对照

| 约束 | 第一层落实情况 |
|---|---|
| 禁止 Mock 数据 | intake_guard_router 使用 `build_missing_user_context()` 注入 mock 地理位置，但仅限于位置缺失时的默认值。生产路径不读静态 mock 列表。 |
| 工具调用必须通过 Gateway | 第一层**不调用任何工具**，因此不涉及 Gateway。 |
| Plan → Execute → Review | 这属于第二层的模式。第一层只做"判断"和"理解"，不做规划和执行。 |
| 回答必须基于 EvidencePack | 第一层不产生最终回答（除了 hard_guard/top_intent_router 的预置回答），不涉及 EvidencePack。 |
