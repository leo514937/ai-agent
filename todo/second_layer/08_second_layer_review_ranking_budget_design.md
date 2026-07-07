# 第二层 Review / Ranking / ExpandSearch / Budget 设计

本文件只定义策略契约，不修改业务代码。目标是把 review、排序、搜索放宽和预算控制从“散落在链路里”收敛成可配置策略。

## 1. ReviewPolicy

### 1.1 目标

不同 workflow 的 review 强度应该不同，不能所有场景都走同样的 LLM review。

### 1.2 建议策略

```text
single_shop_fact:
  goal_review = skip / deterministic
  evidence_review = deterministic
  decision_planner = deterministic
  decision_review = skip

recommendation:
  goal_review = conditional
  evidence_review = required
  decision_planner = hybrid
  decision_review = deterministic sanity check

comparison:
  goal_review = conditional
  evidence_review = required
  decision_planner = LLM
  decision_review = deterministic sanity check

complex_orchestrator:
  evidence_review = per subtask optional
  final_decision_review = required
```

### 1.3 与当前代码的关系

当前 `execution_review_subgraph` 已经串起了：

- `_h_tool_execute`（[execution_review_subgraph.py:111-207](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/execution_review_subgraph.py#L111)）
- `_h_evidence_build`（[execution_review_subgraph.py:210-241](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/execution_review_subgraph.py#L210)）
- `_h_evidence_review`（[execution_review_subgraph.py:244-292](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/execution_review_subgraph.py#L244)）
- `_h_decision_planner`（[execution_review_subgraph.py:295-342](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/execution_review_subgraph.py#L295)）
- `_h_decision_review`（[execution_review_subgraph.py:345-377](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/execution_review_subgraph.py#L345)）

路由信号通过 `next_action` 传递（[execution_review_subgraph.py:57-103](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/execution_review_subgraph.py#L57)）：

| next_action | 路由目标 | 对应 _routes.py |
|---|---|---|
| `FINISH` | `response_subgraph` | 默认 |
| `REPLAN_EVIDENCE` | `planning_subgraph`（retry） | [_route_decision_review:174-185](D:/javacode/hm-dianping/local_life_agent/engine/_routes.py#L174) |
| `EXPAND_SEARCH` | `expand_search`（relax constraints） | [_route_decision_review:187-197](D:/javacode/hm-dianping/local_life_agent/engine/_routes.py#L187) |
| `CLARIFY` | `clarify_response` | [_route_decision_review:205-206](D:/javacode/hm-dianping/local_life_agent/engine/_routes.py#L205) |
| `FALLBACK` | `fallback_answer` | [_route_decision_review:201-202](D:/javacode/hm-dianping/local_life_agent/engine/_routes.py#L201) |

但它还不是按 workflow 分类的策略系统——无论简单单店事实还是复杂推荐，都进同一个 `execution_review_subgraph` 的同一个 `_h_evidence_review` 和 `_h_decision_planner` 节点。

## 2. RankingPolicy

### 2.1 目标

本地生活推荐排序不能完全依赖 LLM，必须有确定性排序权威。

### 2.2 排序链路

```text
hard constraints filter
→ objective scoring
→ soft preference scoring
→ scene fit scoring
→ LLM explanation / trade-off
```

### 2.3 硬约束示例

- 品类
- 位置范围
- 必须营业
- 明确预算上限
- 明确不能接受的条件

### 2.4 软偏好示例

- 有券
- 环境好
- 安静
- 适合约会
- 适合长辈
- 性价比高

### 2.5 与现有字段关系

`RankingPolicy` 在 `domain/facets.py:102-105` 已定义，但当前只有 3 个字段：

```python
class RankingPolicy(BaseModel):
    primary_facets: list[str] = Field(default_factory=list)    # 主要排序依据
    secondary_facets: list[str] = Field(default_factory=list)  # 次要排序依据
    tradeoff_notes: list[str] = Field(default_factory=list)    # 权衡说明
```

证据：[facets.py:102-105](D:/javacode/hm-dianping/local_life_agent/domain/facets.py#L102)

当前 `RankingPolicy` 被引用到多个 DTO 中：`ExecutionPlan.ranking_policy`（[schemas.py:995](D:/javacode/hm-dianping/local_life_agent/domain/schemas.py#L995)）、`EvidencePack.ranking_policy`（[schemas.py:1110](D:/javacode/hm-dianping/local_life_agent/domain/schemas.py#L1110)）、`DecisionPlan.ranking_policy`（[decision.py:293](D:/javacode/hm-dianping/local_life_agent/domain/decision.py#L293)）、`GoalPlan.ranking_policy`（[goal.py:53](D:/javacode/hm-dianping/local_life_agent/domain/goal.py#L53)）。

**关键发现**：当前 RankingPolicy 只定义了排序维度（primary_facets / secondary_facets），但缺少以下能力：
- 硬约束（hard_constraints）过滤规则
- 客观评分（objective scoring）权重
- 场景适配（scene fit）评分
- 排序结果的置信度追认

`SemanticFrame` 中的 `hard_constraints` 和 `soft_preferences` 字段（[schemas.py:293-295](D:/javacode/hm-dianping/local_life_agent/domain/schemas.py#L293)）当前只是承载数据，没有和 RankingPolicy 形成闭环。

## 3. ExpandSearchPolicy

### 3.1 目标

扩搜不能直接 `filters = {}`，否则会把硬约束全抹掉。

### 3.2 放宽顺序

```text
1. 增加 limit
2. 扩大 radius
3. 放宽 soft preferences
4. 保留 hard constraints
5. 在回答里说明放宽了哪些条件
```

### 3.3 设计原则

- 只放宽可放宽项
- 不突破硬约束
- 每次放宽都要可追踪
- 放宽必须进入 trace

### 3.4 与现有执行 review 的关系

当前 `expand_search` 的真实实现在 `planning_subgraph._h_expand_search`（[planning_subgraph.py:1304-1346](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/planning_subgraph.py#L1304)）。

**已确认的风险**：当前代码中 `_h_expand_search` 执行：
```python
relaxed.filters = {}      # 清空所有过滤条件（硬约束丢失）
relaxed.sort_by = []      # 清空排序条件
```
证据：[planning_subgraph.py:1319-1325](D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/planning_subgraph.py#L1319)

这意味着用户设置的品类、位置范围、预算上限等硬约束在扩搜时全部丢失。`ExpandSearchPolicy` 的目标就是纠正这个行为。

当前 `_h_expand_search` 的 relax 策略仅做两件事：
1. 增加 limit（`old_limit * 2 + 5`）
2. 清空 filters 和 sort_by

没有 radius 放宽、没有硬约束保留、没有 relax 过程追踪。

路由进入 `expand_search` 的路径：
- `_route_evidence_review`（[_routes.py:212-257](D:/javacode/hm-dianping/local_life_agent/engine/_routes.py#L212)）：当 evidence_review 返回 `EXPAND_SEARCH` 时
- `_route_decision_review`（[_routes.py:187-197](D:/javacode/hm-dianping/local_life_agent/engine/_routes.py#L187)）：当 decision_review 返回 `EXPAND_SEARCH` 时
- 计数都通过 `SessionState.replan_counters["expand_search"]` 控制（[state.py:136-140](D:/javacode/hm-dianping/local_life_agent/domain/state.py#L136)），上限 `MAX_EXPAND_SEARCH_ROUNDS=1`（[config.py:213](D:/javacode/hm-dianping/local_life_agent/config.py#L213)）

## 4. BudgetPolicy

### 4.1 建议预算字段

- `max_llm_calls`
- `max_tool_calls`
- `max_parallel_workers`
- `max_total_latency_ms`
- `max_replan_rounds`
- `max_expand_rounds`
- `max_subtask_count`

### 4.2 与现有预算对象的关系

- `BudgetContext`（[budget_context.py:8-62](D:/javacode/hm-dianping/local_life_agent/planning/budget/budget_context.py#L8)）负责运行时剩余预算，默认值：`tool_round_budget=2`、`retry_budget=1`、`expand_search_budget=1`、`rewrite_budget=1`、`facet_enrich_budget=6`
- `FacetBudgetPlan`（[facet_budget.py:21-43](D:/javacode/hm-dianping/local_life_agent/planning/evidence/facet_budget.py#L21)）负责 facet 层限额
- `SessionState.replan_counters`（[state.py:136-140](D:/javacode/hm-dianping/local_life_agent/domain/state.py#L136)）负责 retry/expand_search/rewrite 的轮次计数——**但跨轮持久化**，存在计数跨轮污染风险
- `config.py` 中的全局上限：`MAX_EXPAND_SEARCH_ROUNDS=1`（[config.py:213](D:/javacode/hm-dianping/local_life_agent/config.py#L213)）、`MAX_REPLAN_EVIDENCE_ROUNDS=1`（[config.py:215](D:/javacode/hm-dianping/local_life_agent/config.py#L215)）、`MAX_TOOL_CALLS=40`（[config.py:35](D:/javacode/hm-dianping/local_life_agent/config.py#L35)）
- 新的 `ExecutionBudget` 应该成为 workflow 级统一预算入口，将 `BudgetContext` + `replan_counters` + `config` 中的预算语义合并为一个契约

### 4.3 预算执行规则

1. 先判预算够不够
2. 再决定是否进入重链路
3. 执行中不允许静默超支
4. 超支时必须进入明确 degrade / fallback / clarify

## 5. 设计落点

### 5.1 simple workflow

轻量事实路径应当尽量减少：

- LLM review
- 重型 rerank
- 不必要的扩搜

### 5.2 recommendation / comparison

推荐与对比 workflow 才应该使用更强的 review 和 ranking。

### 5.3 complex orchestrator

超复杂 query 的 review 发生在：

- 子任务级 review
- reduce 级 review
- final decision review

而不是每个 worker 都重复做自然语言总结。

---

## 6. RankingPolicy 客观评分权重设计

### 6.1 评分权重

```text
ranking_weight_schema:
  distance_score:      weight=0.30  # 距离越近越好（归一化到 0-1）
  rating_score:        weight=0.25  # 评分越高越好
  coupon_availability: weight=0.15  # 有券加分
  deal_availability:   weight=0.10  # 有团购加分
  scene_fit_score:     weight=0.10  # 场景匹配度（LLM 评估）
  preference_match:    weight=0.10  # 软偏好匹配度
```

### 6.2 硬约束过滤

```text
hard_constraint_filter:
  - category_match:        required  # 品类必须匹配
  - location_in_range:     required  # 位置必须在范围内
  - is_open:               required  # 必须营业（如果用户要求）
  - budget_within_limit:   required  # 预算上限
  - must_have_coupon:      optional  # 仅当用户明确要求券时
  - must_have_deal:        optional  # 仅当用户明确要求团购时
```

### 6.3 排序流程

```text
1. hard_constraint_filter     — 确定性过滤，通过 filter 列表
2. objective_scoring          — distance + rating + coupon/deal（确定性计算）
3. soft_preference_scoring    — scene_fit + preference_match（LLM 辅助）
4. weighted_sum               — 按权重加权求和
5. LLM_explanation            — 仅解释排序结果，不改变排序
```

### 6.4 RankingPolicy 配置样例

以下配置供实现时直接参考，可根据业务场景调整权重：

```python
RankingPolicyConfig:
    # 硬约束过滤：不满足任一条件的店铺直接排除
    hard_filters: list[str] = [
        "category",       # 品类必须匹配
        "open_now",       # 必须营业（当用户要求时）
        "max_distance",   # 位置必须在范围内
        "max_price",      # 预算上限
        "must_have_coupon",   # 必须有券（仅当用户明确要求）
    ]
    
    # 客观评分权重：加权求和，所有权重之和 = 1.0
    objective_weights: dict[str, float] = {
        "distance":        0.25,  # 距离越近越高（归一化 0-1）
        "rating":          0.20,  # 评分越高越高（原始分 / 5.0）
        "coupon_available": 0.15,  # 有券加分
        "review_count":    0.10,  # 评价数越多越高（对数归一化）
        "price_fit":       0.15,  # 价格匹配度
        "scene_fit":       0.15,  # 场景匹配度（LLM 评估）
    }
    
    # 平局决胜策略：按字段顺序依次比较
    tie_breakers: list[str] = [
        "open_now",       # 营业中优先
        "distance",       # 近的优先
        "rating",         # 评分高的优先
    ]
    
    # 软偏好配置（由 SemanticFrame.soft_preferences 驱动）
    soft_preference_boost: float = 0.1   # 每匹配一项软偏好加 0.1
    max_soft_preference_boost: float = 0.3  # 软偏好总分上限
```

**评分计算步骤**：

```text
1. hard_constraint_filter:
   foreach shop in candidates:
     if not match_all(shop, hard_filters):
         remove(shop)

2. objective_scoring:
   foreach remaining_shop:
     score = 0
     for facet, weight in objective_weights.items():
         score += normalize(facet_value(shop, facet)) * weight
     shop.raw_score = score

3. soft_preference_boost:
   foreach remaining_shop:
     match_count = count_matches(shop.attributes, soft_preferences)
     shop.soft_boost = min(match_count * 0.1, 0.3)
     shop.final_score = shop.raw_score + shop.soft_boost

4. tie_break:
   sort by final_score DESC
   foreach tie_group (same final_score):
     sort by tie_breakers[0], tie_breakers[1], tie_breakers[2]

5. LLM_explanation (read-only):
   LLM 仅解释排序理由，不改变排序顺序
```

**与当前代码的关系**：

- 当前 `RankingPolicy`（`facets.py:102-105`）只有 3 个字段（primary_facets / secondary_facets / tradeoff_notes），缺少硬约束过滤、客观评分权重、平局决胜逻辑
- 当前 `SemanticFrame.hard_constraints` 和 `soft_preferences`（`schemas.py:293-295`）承载了约束数据但未闭环到排序
- 实现时建议在现有 `RankingPolicy` 基础上扩展字段，不新建类以确保兼容

---

## 7. ExpandSearchPolicy 分层放宽操作细节

### 7.1 五步放宽流程

```text
step_1: increase_limit
  action: limit = old_limit * 2 + 5
  preserves: filters, sort_by, hard_constraints
  
step_2: expand_radius
  action: radius = old_radius * 1.5（max 5000m）
  preserves: filters, sort_by, hard_constraints
  
step_3: relax_soft_preferences
  action: 移除 optional facet 约束
  preserves: required facets, hard_constraints
  
step_4: retain_hard_constraints
  action: 显式保留 category, budget, open_status 等硬约束
  preserves: ALL hard constraints from original query
  
step_5: report_relaxations
  action: 生成结构化 relax_log
  output: list of what was relaxed, what was preserved
```

### 7.2 与当前代码的对比

当前 `_h_expand_search`（`planning_subgraph.py:1304-1346`）只做两件事：
1. `limit = old_limit * 2 + 5`
2. `filters = {}`、`sort_by = []`（**清空所有约束**）

目标 `ExpandSearchPolicy` 改为：
1. 增加 limit
2. 扩大 radius
3. 仅放宽 soft preferences
4. **保留 hard constraints**
5. 在回答中说明放宽了哪些条件

---

## 8. Workflow 级 BudgetPolicy 配额表

| 预算项 | single_shop_fact | recommendation | comparison | complex_orchestrator |
|---|---|---|---|---|
| max_llm_calls | 0~1 | 1~3 | 2~4 | 3~6 |
| max_tool_calls | 1~3 | 5~15 | N shops x facets | per subtask aggregate |
| max_replan_rounds | 0 | 1 | 1 | per subtask configurable |
| max_expand_rounds | 0 | 1 | 0 | 0 |
| max_parallel_workers | 1 | 1 | 1 | 3~5 |
| max_subtask_count | N/A | N/A | N/A | 5~8 |
| max_total_latency_ms | 2000 | 8000 | 10000 | 15000 |

### 预算执行规则

1. 先校验预算是否足以执行当前 workflow
2. 再把预算传给 compiler / validator / executor
3. 执行中只允许在预算边界内 degrade，不允许静默超支
4. 超支时必须进入明确 degrade / fallback / clarify

---

## 9. ReviewPolicy per-review 判定标准

### 9.1 goal_review

| 模式 | 条件 | 行为 |
|---|---|---|
| skip | direct_response, single_shop_fact | 不 review goal |
| deterministic | single_shop_fact（推荐） | 仅检查完整性和合法性 |
| conditional | recommendation, comparison | 仅当有歧义/缺失时才 review |
| required | complex_orchestrator | 必须 review subtask 分解 |

### 9.2 evidence_review

| 模式 | 条件 | 行为 |
|---|---|---|
| deterministic | single_shop_fact | 仅检查证据完整性和 freshness |
| required | recommendation, comparison | LLM 检查证据质量和覆盖 |
| per_subtask_optional | complex_orchestrator | 子任务级可选，reduce 级最终 review |

### 9.3 decision_planner

| 模式 | 条件 | 行为 |
|---|---|---|
| deterministic | single_shop_fact | 模板化决策，无 LLM |
| hybrid | recommendation | RankingPolicy 规则 + LLM 偏好解释 |
| LLM | comparison, exploration_planning | LLM 分析 trade-off |
| reduce_LLM | complex_orchestrator | reduce 后才调用 LLM 做最终决策 |

### 9.4 decision_review

| 模式 | 条件 | 行为 |
|---|---|---|
| skip | single_shop_fact, direct_response | 不 review |
| deterministic_sanity_check | recommendation, comparison | 验证决策是否基于证据，无 LLM |
| required | complex_orchestrator | 最终决策 review（可调 LLM） |

---

## 10. 各 workflow 的策略配置汇总

| Workflow | goal_review | evidence_review | decision_planner | decision_review | expand_rounds | llm_calls |
|---|---|---|---|---|---|---|
| direct_response | skip | skip | N/A | skip | 0 | 1 |
| clarification | skip | skip | N/A | skip | 0 | 1 |
| single_shop_fact | skip | deterministic | deterministic | skip | 0 | 0~1 |
| recommendation | conditional | required | hybrid | sanity_check | 1 | 1~3 |
| comparison | conditional | required | LLM | sanity_check | 0 | 2~4 |
| exploration | conditional | conditional | LLM | conditional | 1 | 3~5 |
| complex_orchestrator | required | per_subtask_optional | reduce_LLM | required | 0 | 3~6 |

---

## 11. RankingPolicy 可执行数据结构（新增）

### 11.1 为什么现有设计不可执行

当前文档 §2 的排序链路（hard filter → objective scoring → soft preference → scene fit → LLM explanation）方向正确，但缺少可编码的数据结构。要实现排序引擎而不是排序描述，需要以下 5 个 DTO。

### 11.2 `HardConstraintFilterRule`

```python
class HardConstraintFilterRule(BaseModel):
    """一条硬约束过滤规则。满足任一规则即保留，全部不满足即排除。"""
    field: str                                   # 约束字段名
    # field 取值映射：
    #   "category"       -> SemanticFrame.category / shop.category
    #   "max_distance"   -> SemanticFrame.location 中的范围
    #   "open_now"       -> check_open_status 结果
    #   "max_price"      -> SemanticFrame.hard_constraints["budget"]
    #   "must_have_coupon" -> 用户明确要求有券
    operator: Literal["eq", "ne", "le", "ge", "lt", "gt", "in", "not_in", "exists", "not_exists"]
    value: Any                                  # 比较值
    source: str = "semantic_frame"             # 约束来源（semantic_frame / user_explicit / session_default）
    required: bool = True                       # True=硬性排除，False=仅标记不排除
    reason: str = ""                            # 约束来源说明（trace 用）

class HardConstraintFilterSet(BaseModel):
    """硬约束过滤集合：所有 rule 都通过（AND 逻辑）才能保留。"""
    rules: list[HardConstraintFilterRule] = Field(default_factory=list)
    logic: Literal["and", "or"] = "and"        # 规则间逻辑
    on_violation: Literal["exclude", "mark", "fallback"] = "exclude"
```

**使用方式**：
```python
# 由 GoalPlan / SemanticFrame 编译产生：
filters = HardConstraintFilterSet(rules=[
    HardConstraintRule(field="category", operator="eq", value="火锅"),
    HardConstraintRule(field="max_distance", operator="le", value=3000),
    HardConstraintRule(field="open_now", operator="eq", value=True, required=False),
])
for shop in candidates:
    if not filters.passes(shop):    # 确定性排除
        candidates.remove(shop)
```

### 11.3 `ObjectiveWeight` + `ObjectiveScoringSpec`

```python
class ObjectiveWeight(BaseModel):
    """一条客观评分权重。"""
    facet: str                                   # 评分维度
    # facet 取值映射：
    #   "distance"     -> get_distance_eta / calculate_distance_km 结果
    #   "rating"       -> get_shop_detail / get_shop_cards 结果
    #   "review_count" -> get_shop_review_summary / get_shop_detail 结果
    #   "coupon"       -> get_coupon_list 结果（有券=1，无券=0）
    #   "deal"         -> get_deal_list 结果
    #   "price_fit"    -> shop_detail.price vs user_budget 匹配度
    #   "scene_fit"    -> LLM 评估的场景匹配度
    weight: float                                # 权重（所有权重之和应=1.0）
    normalization: Literal[                      # 归一化策略
        "identity",       # 原值（如 rating 已经是 0-5）
        "minmax",         # (v-min)/(max-min)
        "log",            # log(1+v)/log(1+max)
        "zscore",         # (v-mean)/std
        "boolean",        # 0 或 1（如有券）
        "inverse_rank",   # 1/rank（距离排名倒数）
    ]
    fallback_value: float = 0.0                 # 数据缺失时的默认分
    source_field: str = ""                       # 从工具结果的哪个字段取值

class ObjectiveScoringSpec(BaseModel):
    """客观评分规格：定义了所有评分维度和权重。"""
    weights: list[ObjectiveWeight] = Field(default_factory=list)
    # 使用前校验 sum(weights) ≈ 1.0

    def score(self, shop_data: dict[str, Any]) -> dict[str, float]:
        """对单个 shop 的 facet 数据执行确定性评分。
        返回 {facet_name: score} 和最终总分。
        """
        scores = {}
        total = 0.0
        for w in self.weights:
            raw = self._get_value(shop_data, w.facet)
            normalized = self._normalize(raw, w.normalization, shop_data)
            scores[w.facet] = normalized * w.weight
            total += scores[w.facet]
        scores["_total"] = total
        return scores
```

### 11.4 `TieBreakerChain`

```python
class TieBreakerRule(BaseModel):
    """平局决胜规则：同分时按此字段依次比较。"""
    facet: str
    direction: Literal["desc", "asc"] = "desc"  # 降序（越高越好）或升序（越低越好）

class TieBreakerChain(BaseModel):
    """平局决胜链：先按第一个规则比，还平再按第二个，以此类推。"""
    rules: list[TieBreakerRule] = Field(default_factory=list)

    def break_ties(self, ranked: list[ShopScore]) -> list[ShopScore]:
        """确定性平局决胜。"""
        for rule in reversed(self.rules):
            ranked.sort(
                key=lambda s: s.facet_scores.get(rule.facet, 0),
                reverse=(rule.direction == "desc"),
            )
        return ranked
```

### 11.5 `ScoringProvenance`

```python
class ScoreProvenance(BaseModel):
    """单个 facet 分数的来源追溯。"""
    shop_id: str
    facet: str                                   # 评分维度
    score: float                                 # 最终得分
    raw_value: Any                               # 原始值
    normalized_value: float                      # 归一化后的值
    weight_applied: float                        # 使用的权重
    source: Literal[                             # 分数来源
        "tool_result",          # 来自工具返回的数据
        "llm_estimate",         # 来自 LLM 估计
        "rule_default",         # 规则默认值
        "missing_fallback",     # 数据缺失的兜底值
    ]
    tool_name: str | None = None                 # 如果来自工具，是哪个工具
    tool_call_id: str | None = None              # 如果来自工具，是哪次调用
    confidence: float = 1.0                      # 置信度（工具=1.0，LLM 估计=0.5~0.8）

class ScoringProvenanceSet(BaseModel):
    """一次排序的完整评分溯源。"""
    provenances: list[ScoreProvenance] = Field(default_factory=list)
    ranking_policy_id: str = ""                  # 使用的 RankingPolicy 标识
    executed_at: str = ""                        # 排序执行时间
    execution_order: list[str] = Field(default_factory=list)  # 执行顺序

    def get_shop_scores(self, shop_id: str) -> dict[str, float]:
        return {p.facet: p.score for p in self.provenances if p.shop_id == shop_id}
```

### 11.6 整合后的排序执行流程

```python
def execute_ranking(
    candidates: list[ShopEntity],
    hard_filters: HardConstraintFilterSet,
    objective_spec: ObjectiveScoringSpec,
    soft_preferences: list[str],
    tie_breaker: TieBreakerChain,
    max_soft_boost: float = 0.3,
    llm_explain: bool = False,
) -> tuple[list[RankedShop], ScoringProvenanceSet]:
    """
    1. Hard filter: 确定性排除不满足硬约束的 shop
    2. Objective scoring: 对每个 shop 做确定性的加权评分
    3. Soft preference boost: LLM 评估软偏好匹配度，有限加分
    4. Tie break: 同分时按链决胜
    5. LLM explanation（只读）: 仅解释排序结果，不改变排序
    """
    provenances = ScoringProvenanceSet()

    # Step 1: Hard constraint filter
    filtered = [s for s in candidates if hard_filters.passes(s)]
    # 记录被排除的 shop 和原因

    # Step 2: Objective scoring
    scored = []
    for shop in filtered:
        shop_data = gather_evidence(shop)  # 从 EvidencePack 聚合 facet 数据
        scores = objective_spec.score(shop_data)
        for facet, val in scores.items():
            if facet != "_total":
                provenances.provenances.append(ScoreProvenance(
                    shop_id=shop.shop_id, facet=facet, score=val,
                    raw_value=shop_data.get(facet), normalized_value=val,
                    weight_applied=0, source="tool_result",
                ))
        scored.append(ShopScore(shop=shop, total=scores["_total"], facet_scores=scores))

    # Step 3: Soft preference boost (capped)
    for s in scored:
        match_count = count_preference_matches(s.shop, soft_preferences)
        boost = min(match_count * 0.1, max_soft_boost)
        s.total += boost
        provenances.provenances.append(ScoreProvenance(
            shop_id=s.shop.shop_id, facet="soft_preference",
            score=boost, raw_value=match_count,
            normalized_value=boost, weight_applied=0,
            source="rule_default",
        ))

    # Step 4: Tie break
    ranked = sorted(scored, key=lambda s: s.total, reverse=True)
    ranked = tie_breaker.break_ties(ranked)

    # Step 5: LLM explanation (read-only)
    if llm_explain:
        explanation = llm_explain_ranking(ranked, soft_preferences)
        # LLM 只返回解释文本，不改变排名

    return ranked, provenances
```

### 11.7 对当前 `RankingPolicy` 的扩展方案

直接在 `facets.py:102-105` 的 `RankingPolicy` 上扩展字段，不新建类以确保兼容：

```python
class RankingPolicy(BaseModel):
    # 原有字段（保留兼容）
    primary_facets: list[str] = Field(default_factory=list)
    secondary_facets: list[str] = Field(default_factory=list)
    tradeoff_notes: list[str] = Field(default_factory=list)

    # 新增可执行字段
    hard_filters: HardConstraintFilterSet = Field(default_factory=HardConstraintFilterSet)
    objective_scoring: ObjectiveScoringSpec = Field(default_factory=ObjectiveScoringSpec)
    tie_breakers: TieBreakerChain = Field(default_factory=TieBreakerChain)
    max_soft_boost: float = 0.3
    enable_llm_explanation: bool = False
```

