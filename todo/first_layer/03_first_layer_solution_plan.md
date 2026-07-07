# 第一层解决方案计划

本计划只定义阶段化收敛路线，不直接改业务代码。

## Phase 1: 事实冻结与边界测试

### 目标

- 固化第一层真实调用链
- 固化字段读写矩阵、路由矩阵、LLM / rule / deterministic 矩阵
- 不改变业务行为

### 要做的事

- 为 `intake_guard_router`、`merge_clarification`、`understanding_subgraph`、`state_update_plan`、`active_turn_resolver`、`top_intent_router`（`intake_guard_router.py:220-268`）画出实测链路（⚠️ 仓库中不存在独立的 `top_intent_router_handler.py`）
- 以现有测试为基础补 architecture boundary tests
- 记录哪些节点提前写 `final_response`、`error_code`、`pending_clarification`、`clarification_request`

### 建议产物

- 第一层 state 字段读写矩阵
- 第一层 route 决策矩阵
- 第一层 session 写入矩阵
- 第一层 LLM / rule / deterministic 调用矩阵

## Phase 2: 引入 `ContextualizedTurn` / Query Contextualizer

### 目标

- 新增明确的上下文化 turn 表示
- 先作为中间字段和 trace，不直接替换 `semantic_parse`
- 让 `top_intent_router` 和 `semantic_parse` 可选择读取 contextualized query

### 约束

- 不允许编造事实
- 必须保留 `raw_text` 和 `normalized_text`
- 必须记录 `context_used`
- 低置信度不能强行 rewrite，应进入 clarification 或保守理解

### 建议模型

```python
ContextualizedTurn:
    original_text: str
    normalized_text: str
    contextualized_query: str
    rewrite_type: Literal[
        "none",
        "followup_refinement",
        "deictic_resolution",
        "constraint_carryover",
        "comparison_followup",
        "clarification_delta"
    ]
    context_used: dict
    confidence: float
    warnings: list[str]
```

## Phase 3: 引入 `FocusContext`

### 目标

- 统一 `current_shop` / `last_recommendation_list` / `comparison_targets` / `last_candidate_set`
- 给“这家 / 这几个 / 第一个”一个明确优先级

### 约束

- `context_recovery` 只消费 `FocusContext` 或兼容映射
- `state_update_plan` 负责从本轮结果生成新的 `FocusContext`
- 旧字段先保留兼容窗口，不做一次性删除

### 建议模型

```python
FocusContext:
    focus_type: Literal[
        "none",
        "single_shop",
        "recommendation_list",
        "comparison_set",
        "candidate_set"
    ]
    focus_items: list[dict]
    primary_focus: dict | None
    source_turn_id: str
    created_at: str
    expires_at: str | None
    freshness_policy: str | None
```

## Phase 4: 收敛第一层错误和响应契约

### 目标

- 第一层不再随意写最终自然语言回答
- 入口层只输出 response directive
- response_subgraph 统一生成最终文本

### 建议模型

```python
ErrorEnvelope:
    stage: str
    code: str
    message: str
    severity: Literal["info", "warning", "error"]
    recoverable: bool

EarlyResponseDirective:
    response_mode: Literal[
        "invalid",
        "greeting",
        "capability",
        "reject",
        "clarify",
        "answer"
    ]
    reason: str
    payload: dict
```

### 约束

- 尽量减少全局 `error_code` / `final_response` 的提前写入
- 若保留兼容字段，必须由新 envelope 派生
- trace 中要能看出错误来源

## Phase 5: 收紧 `active_turn_resolver` / `slot_extractor` / `hard_guard` 边界，并补 Session 分区、freshness、trace

### 目标

- `active_turn_resolver` 只处理 pending clarification 的回复识别
- `slot_extractor` 只输出 anchors / candidates / spans（当前它被 4 处调用：`understanding_subgraph.py:206`、`clarification.py:541`、`active_turn_resolver.py:219`、`intent_parser.py:618`，必须在单点收敛接口后统一抽象调用）
- `hard_guard` 只做安全、无效、问候、能力类判断，业务关键词只能作为 weak signal
- 消除 `_should_treat_as_topic_switch` 在 `active_turn_resolver.py` 和 `clarification.py` 各有一份独立副本的重复
- 消除 `hard_guard` 内部双重 normalize（`intake_guard_router.py:199-204` 已做，`hard_guard.py:82` 又做一次）
- 统一 `pending_clarification` / `clarification_request` 为单一字段（`intake_guard_router.py:167` 将同一对象赋值给两个字段）
- 将 `state_update_plan._h_persist_session` 的额外写逻辑（`state_update_plan.py:160-177` 绕过 `SessionWriteDirective` 直接写 `comparison_targets`）纳入 directive 管控
- `load_session`（`intake_guard_router.py:153-177`）分离"纯加载"与"字段展开"两阶段
- 避免 `SessionState` 继续膨胀
- 给实时字段增加 freshness
- 把第一层 trace 做成可解释结构

### `slot_extractor` 允许

- merchant mention span
- deictic reference anchor
- ordinal reference anchor
- number / location anchor
- brand candidate

### `slot_extractor` 禁止

- 判断 `task_type`
- 判断 `recommendation` / `comparison`
- 判断用户偏好优先级
- 直接决定 `shop_id`
- 覆盖 LLM `semantic_frame` 的关键字段

### 说明

当前真实代码中 `slot_extractor` 已经越过这个边界，因此本阶段的目标是收敛职责，而不是继续堆规则。

### 建议的 SessionState 分区

```python
SessionState:
    conversation_context
    focus_context
    clarification_context
    recommendation_context
    comparison_context
    user_preference_summary
    execution_counters
```

### 建议增加 freshness 与位置上下文

```python
FreshnessMeta:
    generated_at: str
    expires_at: str | None
    source: str
    freshness_policy: str
```

```python
LocationContext:
    lat: float | None
    lng: float | None
    label: str | None
    source: Literal["user_permission", "java_realtime_context", "mock", "default_city", "unknown"]
    generated_at: str | None
    expires_at: str | None
    confidence: float
```

### 建议 trace

```python
FirstLayerTrace:
    intake_decision
    guard_decision
    active_turn_decision
    contextualization_decision
    top_intent_decision
    clarification_decision
    semantic_parse_decision
    context_recovery_decision
    state_update_decision
```

### 每个 decision 至少包含

```python
stage
decision
reason
source
confidence
context_used
input_snapshot
```

## 补充调整：六个关键点的方案校准

以下调整基于代码调研对原有方案的具体修正。

### A. Mixed Intent → 合并到 Phase 2，不做独立 Phase

**改动内容**：在 Phase 2 新增 `MixedIntent` 模型，作为 `TopIntent` 的补充而非替代。

**原因**：
- 代码证实 `TopIntent` 是单标签枚举（`enums.py:6-12`），路由逻辑只判断单一值
- Mixed Intent 不是"重构级别的改动"——只需要新增一个 DTO + 修改 `parse_top_intent` 的 LLM prompt 和字段
- 不应做成独立 Phase，因为这和 `ContextualizedTurn` 是同一批"第一层理解增强"的事

**具体做法**：

```python
# 新增，不删除原有 TopIntent
MixedIntent:
    primary: TopIntent           # 主意图
    secondary: list[TopIntent]   # 副意图（可空）
    intent_scores: dict[str, float]  # { "local_life": 0.7, "chat": 0.3 }
    routing_hint: str | None     # 告诉路由层"虽然 mixed，但按 primary 路由"
```

- `parse_top_intent` 的 LLM 输出改为 `MixedIntent` 格式
- `_h_top_intent_router` 路由决策仍按 `primary` 走，不改变当前路由逻辑
- `secondary` 和 `intent_scores` 传递到下游供 `semantic_parse` 和 trace 使用

### B. ContextualizedTurn 与 SemanticFrame 的边界校准（Phase 2）

**方案缺口**：原方案只定义了 `ContextualizedTurn` 的字段，但没有明确它和 `SemanticFrame` 的边界。

**补充边界规则**：

```
ContextualizedTurn: 自然语言层
  - contextualized_query: str            # 上下文化后的 query（自然语言）
  - rewrite_type: str                    # 改写类型
  - context_used: dict                   # 引用了哪些上下文
  - 不做意图分类，不做槽位提取，不做偏好判断

SemanticFrame: 意图+槽位层（需缩窄）
  - 保留：intent, task_type, preferences, merchant_mentions, missing_slots
  - 去掉：ranking_policy, ranking_signals, facets, facet_set, focused_facets
  - 去掉：comparison_focused_facets（由 comparison_intent 表达即可）
```

**约束增加**：
- `SemanticFrame` 的 `ranking_policy`、`ranking_signals`、`facets`、`facet_set` 标记为废弃（deprecated），保留兼容但不作为新代码依赖
- `ContextualizedTurn.rewrite_type` 新增 `"mixed_intent_primary"` 值，表示 mixed intent 时取 primary 意图做 rewrite

### C. FocusContext 的 item 级字段细化（Phase 3）

**方案缺口**：原方案 `focus_items: list[dict]` 过于宽泛。

**补充**：

```python
class FocusItem(BaseModel):
    item_id: str
    focus_type: Literal[
        "shop_entity",              # 单店 (current_shop)
        "recommendation_ranked",    # 推荐列表（有序）
        "comparison_set",           # 比较集合
        "candidate_set",            # 候选集
        "general_search",           # 泛搜索
    ]
    entity: dict                    # 实体数据
    entity_source: str              # "tool_result" / "recommendation" / "llm" / "user_input"
    category: str | None            # 品类标签
    reference_priority: int         # 引用优先级（越高越优先匹配）
    mention_support: list[str]      # 用户 mention 关键词
    generated_at: str
    expires_at: str | None
    freshness_policy: str | None    # "reuse_always" / "reuse_if_within_ttl" / "onetime"
```

`FocusContext` 加上 `resolve_reference(self, mention_type, mention_value) -> FocusItem | None` 方法，替代当前 `context_recovery` 中手动推导焦点优先级的多段逻辑。

### D. load_session 后移 → 纳入 Phase 5

**方案缺口**：原 Phase 5 提到"分离纯加载与字段展开两阶段"，但没有具体方案。

**补充做法**：

1. 拆分 `_h_load_session` 为两个原子节点：
   - `_h_validate_session`：只校验 session_id 存在性和基本有效性（轻量）
   - `_h_expand_session`：将 SessionState 展开到 GraphState 的 15+ 个字段（重量）
2. 时序调整为：
   ```
   _h_receive_input → _h_validate_session → _h_basic_validate → _h_normalize_text →
   _h_hard_guard → _h_expand_session → _h_active_turn_resolver → _h_top_intent_router
   ```
3. 不移动 `_h_validate_session`（因为它校验 session_id 有效性），只移动 `_h_expand_session`

**约束**：
- `_h_active_turn_resolver` 和 `_h_top_intent_router` 读取展开字段的代码不变，只是展开时机推后了
- `_h_basic_validate` 和 `_h_hard_guard` 不依赖展开字段，不受影响
- 非法输入在 `_h_basic_validate` 即返回，省掉展开 I/O 和 15+ 字段写入

### E. SessionStore 生产迁移 → 新增 Phase 5.5

**方案缺口**：原方案没有独立的 SessionStore 迁移阶段。

**新增 Phase 5.5: SessionStore 生产迁移**

目标：
- 将 `InMemorySessionStore` 抽象为 `SessionStore(ABC)`
- 保留内存实现作为开发/测试默认，新增 Redis 实现
- 按分区支持 TTL 和增量读写

```python
class SessionStore(ABC):
    @abstractmethod
    def load(self, session_id: str) -> SessionState | None
    @abstractmethod
    def save(self, session_id: str, state: SessionState, ttl: int | None = 1800) -> None
    @abstractmethod
    def delete(self, session_id: str) -> None
    @abstractmethod
    def touch(self, session_id: str, ttl: int | None = 1800) -> None
    @abstractmethod
    def load_partition(self, session_id: str, partition: str) -> dict | None
    @abstractmethod
    def save_partition(self, session_id: str, partition: str, data: dict, ttl: int | None = None) -> None
```

**分区 TTL 策略**：

| 分区 | 默认 TTL | 理由 |
|---|---|---|
| `conversation_context` | 30min | 对话基础上下文 |
| `focus_context` | 30min | 焦点状态，随对话 |
| `recommendation_context` | 10min | 推荐列表快速过期 |
| `comparison_context` | 10min | 比较结果相对短暂 |
| `pending_clarification` | 5min | 澄清窗口短 |
| `user_preference_summary` | 24h | 用户偏好可稍长 |
| `execution_counters` | 5min | 计数器窗口 |

**实现优先序**：
1. 提取 `SessionStore(ABC)` + 拆分 `InMemorySessionStore` 实现
2. 添加 `load_partition` / `save_partition` 接口
3. 实现 RedisSessionStore（用 Redis Hash 存分区，主键为 `session:{id}:{partition}`）
4. `get_session_store()` 返回可配置实现（env / config 控制）
5. 按分区设置不同 TTL
6. 删除 session 级 `snapshot` 接口（调试用），改为日志导出

### F. 第一层和第二层 target_resolve 的职责收敛（合并到 Phase 5）

**方案缺口**：原方案没有提到 target_resolve 的跨层重叠收敛。

**补充做法**：

1. **第一层 `context_recovery` 缩窄**：
   - 只做：引用识别（"这家/那家/第一个" → FocusItem）
   - 只做：是否需要澄清（ambiguous → pending_clarification）
   - 不做：实体解析（不再调 `resolve_shop` / `_resolve_comparison_targets`）
   - 输出 `resolved_target` 只携带 `focus_item_id` + `mention_type`，不携带最终 entity 数据

2. **第二层 `target_resolve` 承担全部实体解析**：
   - 接收 `resolved_target` 的引用索引后，始终做完整 entity 解析
   - 移除 `resolved_target.status == "RESOLVED"` 的短路逻辑
   - `resolve_shop_entity` / `resolve_comparison_targets` 只保留在第二层

3. **迁移路径**：
   - Phase 5 内实施：
     a. 先引入 `FocusItem` 作为引用索引载体
     b. 修改 `context_recovery` 产出引用索引
     c. 修改 `planning_subgraph._h_target_resolve` 消费引用索引 + 始终解析
     d. 删除第一层的 `resolve_shop` / `_resolve_comparison_targets` 调用
     e. 验证：确保现有测试覆盖的引用场景在新路径下结果一致

## 推荐落地顺序（更新版）

1. 先做 Phase 1，冻结事实和边界（新增 MixedIntent 字段基线记录）
2. 再做 Phase 2，补上下文化 + MixedIntent + ContextualizedTurn
3. 然后做 Phase 3，补 FocusContext（含 item 级规范）
4. 再然后做 Phase 4，收紧错误和响应契约
5. 然后做 Phase 5，清理职责重叠 + load_session 拆分 + target_resolve 收敛 + trace
6. 再做 Phase 5.5，SessionStore 生产迁移
7. 最后做验收和回归
