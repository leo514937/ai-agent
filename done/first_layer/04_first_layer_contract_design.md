# 第一层契约设计

本文件只描述建议契约和归属，不删除旧字段。

## 契约总览

| 契约 | 类型建议 | 权威归属 | 使用方（基于真实代码） | 说明 |
|---|---|---|---|---|---|
| `ContextualizedTurn` | Domain DTO / GraphState 中间态 | `GraphState` | 生产者：新增 rewrite 节点；消费者：`top_intent_router`（`intake_guard_router.py:220`）、`semantic_parse`（`understanding_subgraph.py:89`） | 表达本轮上下文化改写结果 |
| `FocusContext` | Session / Graph 混合契约 | 优先 `SessionState`，GraphState 持有本轮快照 | 消费者：`context_recovery`（`understanding_subgraph.py:258`）、`slot_extractor`（`slot_extractor.py:564`）、`active_turn_resolver._should_treat_as_topic_switch`（`active_turn_resolver.py:533`）、`merge_clarification.restore`（`merge_clarification.py:83`） | 统一当前焦点 |
| `ErrorEnvelope` | Domain DTO | `GraphState` 中间态 | 生产者：`basic_validate`（`intake_guard_router.py:180`）、`semantic_parse`（`understanding_subgraph.py:89`）、`frame_validator`（`understanding_subgraph.py:231`）、`top_intent_router`（`intake_guard_router.py:220`） | 统一错误来源与级别 |
| `EarlyResponseDirective` | Domain DTO | `GraphState` 中间态 | 生产者：`basic_validate`、`hard_guard`、`top_intent_router`、`merge_clarification` 各分支 | 入口层只写 directive，不直接写最终文本 |
| `FreshnessMeta` | Domain DTO / meta | `SessionState` 的 meta 字段 | 应附着在：`last_recommendation_list`、`comparison_targets`、`current_shop`、`active_constraints` | 描述生成时间、过期时间、策略 |
| `LocationContext` | Domain DTO | `GraphState` + `SessionState` 兼容 | 生产者：`receive_input`（`receiver.py:16`）；消费者：`build_missing_user_context`、`plan_state_update` | 明确位置来源与可信度 |
| `FirstLayerTrace` | Observability / Trace | `GraphState` 观测字段或独立 trace | 涵盖 7 个第一层节点决策：`intake_guard_router` → `merge_clarification` → `understanding_subgraph` → `state_update_plan` | 解释路由、guard、intent、clarification、context recovery |
| `AnchorExtractionResult` | Domain DTO | `GraphState.semantic_frame` 的补充结果 | 生产者：`_h_slot_extractor`（`understanding_subgraph.py:206`）；但当前 `slot_extractor.extract_slots` 还被 `clarification.py:541`、`active_turn_resolver.py:219`、`intent_parser.py:618` 直接调用 | 只输出 anchor，不做业务决策 |
| `ClarificationDelta` | Domain DTO | `GraphState` 临时字段 | 生产者：`merge_clarification._h_check_pending`（`merge_clarification.py:60`）；应与 `clarification.py:533-1046` 的 `handle_clarification_reply` 返回值对齐 | 表达澄清回复相对原帧的增量 |

## 1. `ContextualizedTurn`

### 目的

- 让第一层先产出可解释的上下文化 query，再交给意图 / 语义阶段

### 建议字段

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

### 归属

- `GraphState`：作为本轮中间态和 trace
- 不建议直接替代 `semantic_frame`

## 2. `FocusContext`

### 目的

- 统一单店、推荐列表、对比集合、候选集等焦点状态

### 建议字段

```python
FocusContext:
    focus_type: Literal["none", "single_shop", "recommendation_list", "comparison_set", "candidate_set"]
    focus_items: list[dict]
    primary_focus: dict | None
    source_turn_id: str
    created_at: str
    expires_at: str | None
    freshness_policy: str | None
```

### 归属

- `SessionState`：长期焦点
- `GraphState`：本轮快照
- `context_recovery` 只读这个对象或兼容映射，不直接散读多个旧字段

## 3. `ErrorEnvelope`

### 目的

- 把 stage、code、message、severity、recoverable 拆出来

### 建议字段

```python
ErrorEnvelope:
    stage: str
    code: str
    message: str
    severity: Literal["info", "warning", "error"]
    recoverable: bool
```

### 归属

- `GraphState`：第一层和理解层的统一错误容器
- `error_code` / `error_message` 仅做兼容派生字段，不应作为唯一权威

## 4. `EarlyResponseDirective`

### 目的

- 让第一层只决定“回答模式”，不直接决定完整文本

### 建议字段

```python
EarlyResponseDirective:
    response_mode: Literal["invalid", "greeting", "capability", "reject", "clarify", "answer"]
    reason: str
    payload: dict
```

### 归属

- `GraphState` 中间态
- 最终自然语言文本仍交给 response_subgraph

## 5. `FreshnessMeta`

### 目的

- 给推荐、营业状态、距离、券等字段统一 freshness 语义

### 建议字段

```python
FreshnessMeta:
    generated_at: str
    expires_at: str | None
    source: str
    freshness_policy: str
```

### 归属

- `SessionState` 里的各分区 meta
- 可通过旧字段旁路兼容

## 6. `LocationContext`

### 目的

- 明确位置来源、权限、默认值、mock、时效

### 建议字段

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

### 归属

- `UserContext` / `GraphState.user_location` 兼容演进
- `SessionValueMeta.location_context` 可继续承载旧数据

## 7. `FirstLayerTrace`

### 目的

- 用一个 trace 结构串起入口层所有决策

### 建议字段

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

### 归属

- `Observability / Trace`
- 可挂在 `GraphState` 的 trace 字段，也可独立导出

## 8. `AnchorExtractionResult`

### 目的

- 把 slot extractor 收敛为“只提锚点”，不做业务决策

### 建议字段

```python
AnchorExtractionResult:
    merchant_mentions: list[str]
    ordinal_references: list[str]
    deictic_references: list[str]
    location_anchors: list[str]
    brand_candidates: list[str]
    number_anchors: list[str]
```

### 归属

- `GraphState` 中的语义修复补充字段
- 不应直接覆盖 `semantic_frame.task_type`

## 9. `ClarificationDelta`

### 目的

- 显式表达“澄清回复相对原帧的增量”

### 建议字段

```python
ClarificationDelta:
    base_pending_id: str
    restore_mode: Literal["restore", "restore_with_delta", "topic_switch", "cancelled", "invalid"]
    selected_index: int | None
    selected_candidate: dict | None
    appended_constraints: dict
    appended_facets: list[str]
    new_task_override: bool
    confidence: float
```

### 归属

- `GraphState` 临时中间态
- `merge_clarification` / `active_turn_resolver` 的统一输出候选

## 兼容字段原则

以下字段应视为兼容派生，不应作为未来唯一权威：

- `error_code`
- `error_message`
- `clarification_request`
- `final_response`
- `response_mode`
- `active_turn_route`
- `merge_clarification_route`
- `understanding_route`

原因：

- 它们现在已经被多个节点写入
- 它们能表达流程结果，但不能完整表达原因、上下文和 freshness

## 对现有结构的映射建议

- `GraphState`
  - 保留本轮决策、trace、directive、中间结果
- `SessionState`
  - 保留跨轮焦点、比较集合、澄清状态、推荐列表、freshness meta
- `Domain DTO`
  - `ContextualizedTurn`、`ErrorEnvelope`、`EarlyResponseDirective`、`ClarificationDelta`、`AnchorExtractionResult`
- `Observability / Trace`
  - `FirstLayerTrace`

## 补充契约一：`FocusItem`（FocusContext 的 item 级模型）

### 目的

- 将 `FocusContext.focus_items: list[dict]` 从无约束 dict 变为强类型 DTO

### 建议模型

```python
class FocusItem(BaseModel):
    item_id: str
    focus_type: Literal[
        "shop_entity",              # 单店（映射 current_shop）
        "recommendation_ranked",    # 推荐列表（有序）
        "comparison_set",           # 比较集合
        "candidate_set",            # 候选集
        "general_search",           # 泛搜索（无明确目标）
    ]
    entity: dict                    # 实际实体数据（兼容 ShopEntity / dict）
    entity_source: str              # "tool_result" / "recommendation" / "llm" / "user_input"
    category: str | None            # 品类标签（如 "火锅"）
    reference_priority: int         # 引用优先级（值越大越优先匹配"这家"）
    mention_support: list[str]      # 被用户用哪些 mention 引用过
    generated_at: str               # 生成时间
    expires_at: str | None          # 过期时间
    freshness_policy: str | None    # "reuse_always" / "reuse_if_within_ttl" / "onetime"
```

### 使用规则

- `FocusContext.focus_items` 按 `reference_priority` 降序排列
- `context_recovery` 匹配引用时按此顺序：优先匹配 `reference_priority` 最高的 item
- `focus_type == "shop_entity"` 的 item 默认比 `"recommendation_ranked"` 有更高优先级（用户当前在看）
- `state_update_plan` 更新 FocusContext 时，按 freshness 剪裁过期 items

## 补充契约二：`MixedIntent`

### 目的

- 弥补 `TopIntent` 单标签无法表达混合意图的缺陷
- 不替代 `TopIntent`，只作为补充 DTO

### 建议模型

```python
class MixedIntent(BaseModel):
    primary: TopIntent               # 主意图，路由用
    secondary: list[TopIntent]       # 副意图（可空）
    intent_scores: dict[str, float]  # {"local_life": 0.7, "chat": 0.3}
    routing_hint: str | None         # 告诉路由层 optimal 路由选择
```

### 归属

- `GraphState`：作为本轮中间态
- 从 `parse_top_intent` 输出，随 `top_intent` 一起写入
- 路由层仍按 `primary` 决策，但不丢弃 `secondary` 信息
- `semantic_parse` / `trace` 可读取 `intent_scores` 评估置信度

## 补充契约三：`SessionStore` 抽象接口

### 目的

- 定义 `InMemorySessionStore` → Redis/DB 迁移的统一接口

### 建议模型

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
    def save_partition(self, session_id: str, partition: str, data: dict,
                       ttl: int | None = None) -> None
```

### 实现映射

| 后端 | 分区策略 | TTL 支持 | 序列化 |
|---|---|---|---|
| `InMemorySessionStore` | 进程 dict[分区] | 手动 evict | `model_dump_json()` |
| `RedisSessionStore` | Redis Hash `session:{id}:{partition}` | `EXPIRE` | `model_dump_json()` / `json.dumps` |
| `PostgresJsonbStore` | 表行 + jsonb 列 | 列级 + 定时 | `model_dump_json()` |

### 迁移路径

1. 先提取 `SessionStore(ABC)` + 拆分 `InMemorySessionStore`（保持行为不变）
2. 添加 `load_partition` / `save_partition` 支持（当前 InMemorySessionStore 暂时用全量 load 模拟）
3. 实现 `RedisSessionStore`
4. 替换 `get_session_store()` 为可配置工厂

## 补充契约四：`SemanticFrame` 缩窄清单

### 目的

- 明确 `SemanticFrame` 中应该标记为 deprecated 的字段

### 废弃字段清单（保留兼容，新代码不应依赖）

| 字段 | 原因 | 替代方案 |
|---|---|---|
| `ranking_policy` | 排序策略不是语义级别的事 | 在第二层 execution 阶段决定 |
| `ranking_signals` | 排序信号不应在意图帧里 | 在第二层 execution 阶段采集 |
| `facets` | facet 规划超出语义理解范围 | 第二层 tool planning 阶段处理 |
| `facet_set` | 同上 | 同上 |
| `focused_facets` | 同上 | 同上 |
| `comparison_focus` | 比较焦点应由 comparison_intent 表达 | 使用 `comparison_intent` + `comparison_structure` |

### 保留字段清单（不变）

- `top_intent`, `intent`, `task_type`, `primary_task`, `workflow_hint`
- `comparison_intent`, `comparison_structure`
- `preferences`, `preference_signals`, `hard_constraints`, `soft_preferences`
- `merchant_mentions`, `brand_mentions`, `branch_mentions`
- `shop_target`, `reference`
- `scene`, `time`, `location`, `category`
- `missing_slots`, `need_context`
- `confidence`, `follow_up`
- `constraint_update`, `new_task_override`

## 补充契约五：`ContextualizedTurn` → `SemanticFrame` 的边界规则

### 目的

- 防止 `ContextualizedTurn` 和 `SemanticFrame` 职责重叠

### 数据流

```
raw_text → normalized_text → ContextualizedTurn → SemanticFrame
                                  │                     │
                                  ▼                     ▼
                         自然语言层              意图+槽位层
                         (文本级)               (决策级)
```

### 归属规则

| 信息类别 | 归属 |
|---|---|
| 上下文化的 query 文本 | `ContextualizedTurn.contextualized_query` |
| 改写类型和原因 | `ContextualizedTurn.rewrite_type` + `context_used` |
| 改写置信度 | `ContextualizedTurn.confidence` |
| 意图分类 | `SemanticFrame.top_intent` / `intent` |
| 槽位提取 | `SemanticFrame.merchant_mentions` / `shop_target` / `preferences` |
| 比较结构 | `SemanticFrame.comparison_intent` |
| 任务类型 | `SemanticFrame.task_type` |
| 缺失槽位 | `SemanticFrame.missing_slots` |
| Facet 规划 | ❌ `SemanticFrame` 废弃字段，移至第二层 |
| 排序策略 | ❌ 同上 |

### 使用规则

- `top_intent_router` 可选择消费 `ContextualizedTurn` 或 `raw_text`（当前只读 `normalized_text`）
- `semantic_parse` 的 LLM prompt 应传入 `ContextualizedTurn` 而非原始 `SessionContextSummary`
- `ContextualizedTurn` 低置信度时，`semantic_parse` 应做保守理解而非强制 rewrite

