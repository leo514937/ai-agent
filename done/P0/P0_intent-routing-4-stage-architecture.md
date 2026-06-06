# 多段式意图路由架构设计

> 设计日期：2026-06-05
> 目标：替代现有以 if-else 为主的启发式路由，实现 8 段式智能路由管线

---

## 一、架构总览

```
User Query
  │
  ▼
┌─────────────────────────────────────────────────────────────────┐
│ Stage 1: Hard Guard                                              │
│  ├─ 空输入                                                       │
│  ├─ 纯标点                                                       │
│  ├─ 低信息量                                                     │
│  ├─ 不支持请求                                                   │
│  └─ 安全/权限边界                                                │
│ Output: blocked=True/False + reason                               │
└──────────────────────────────┬──────────────────────────────────┘
                               │ (通过则继续)
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│ Stage 2: Signal Policy                                           │
│  ├─ 关键词信号                                                   │
│  ├─ 商家名识别                                                   │
│  ├─ 指代词识别                                                   │
│  ├─ 场景词识别                                                   │
│  ├─ 多店/推荐/比较信号                                           │
│  └─ 候选 intent 打分                                            │
│ Output: SignalPolicyResult (candidates + confidence + signals)    │
└──────────────────────────────┬──────────────────────────────────┘
                               │ (candidates → LLM hint)
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│ Stage 3: LLM Semantic Parser                                     │
│  ├─ 复杂语义理解                                                 │
│  ├─ 多轮上下文理解                                               │
│  ├─ 用户需求 facet 抽取                                          │
│  └─ JSON Schema 输出                                             │
│ Output: LLMParserResult (intent + slots + needs_rag/tool/clarify) │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│ Stage 4: Target Resolution                                       │
│  ├─ 显式商家解析                                                 │
│  ├─ 候选店选择                                                   │
│  ├─ 指代继承（这家/那家/第二个）                                  │
│  ├─ 禁止继承场景（新意图重置上下文）                              │
│  └─ 缺失澄清（无目标时是否需要问）                               │
│ Output: ResolvedTarget (shop_id / shop_name / confidence / source) │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│ Stage 5: Decision Merger                                         │
│  ├─ 规则信号 + LLM 输出 + context 融合                           │
│  ├─ intent 置信度加权                                            │
│  ├─ route 决策（rag / tool / rag+tool / clarify / direct）       │
│  └─ clarification 决策（缺什么、怎么问）                          │
│ Output: RoutingDecision (intent + required_action + confidence)   │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│ Stage 6: Contract Builder                                        │
│  ├─ AnswerContract（答案约束：证据要求、引用策略）               │
│  ├─ RetrievalContract（检索约束：chunk_roles、filters）          │
│  ├─ ToolContract（工具约束：tool_name、payload、fallback）       │
│  └─ SourceOfTruthPolicy（事实来源优先级：tool > RAG > LLM）     │
│ Output: ExecutionContracts (answer + retrieval + tool)            │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│ Stage 7: Execution Router                                        │
│  ├─ Clarify（缺信息）                                             │
│  ├─ RAG Only（只需检索）                                          │
│  ├─ Tool Only（只需调工具）                                       │
│  ├─ RAG + Tool（检索引擎都要）                                    │
│  └─ Direct Answer（问候/感谢/自我介绍）                           │
│ Output: ExecutionPath + 分派到对应 subgraph                       │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│ Stage 8: Trace / Eval / Replay                                   │
│  ├─ 全链路 trace 记录（每个 stage 的输入/输出/耗时）              │
│  ├─ golden case 录制 & 自动比对                                  │
│  ├─ 决策回放（debug 模式逐 stage 回放）                          │
│  └─ 指标上报（各 stage 准确率/召回率/延迟）                      │
│ Output: RoutingTrace (可序列化，用于离线 eval)                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 二、各 Stage 详细设计

### Stage 1: Hard Guard

**职责**：快速拦截无效输入，不进入后续智能处理。

**规则**：

| 规则 | 条件 | 输出 |
|------|------|------|
| 空输入 | `raw_query.strip() == ""` | `blocked=True`, `reason="empty_input"` |
| 纯标点 | `re.match(r"^[\s\W_]+$")` | `blocked=True`, `reason="pure_punctuation"` |
| 重复噪声 | `re.match(r"^(.)\1{5,}$")` | `blocked=True`, `reason="repeated_noise"` |
| 低信息量 | token < 2 或全为低信息词 | `blocked=True`, `reason="low_information"` |
| 不支持请求 | 非本地生活领域（全局知识等） | `blocked=True`, `reason="unsupported_domain"` |
| 安全/权限 | 敏感/非法内容正则命中 | `blocked=True`, `reason="safety_block"` |

**设计要点**：
- O(1) / O(n) 极速判断，无 IO
- 所有拦截给出明确中文 reason，用于回复用户
- Guard 结果不可被后续 stage 推翻

---

### Stage 2: Signal Policy

**职责**：纯规则信号匹配，生成候选意图列表。不负责最终决策。

**信号注册表**：

| 信号 | 匹配方式 | 置信度 | 推荐 route |
|------|---------|--------|-----------|
| `signal.nearby` | 附近 / 周边 / 离我 | 0.7~0.9 | `rag_plus_tool` |
| `signal.recommend` | 推荐 / 有啥好吃的 | 0.6~0.85 | `rag_retrieval` |
| `signal.coupon` | 券 / 团购 / 套餐 / 优惠 | 0.8~0.95 | `tool_call` |
| `signal.open_status` | 营业 / 开门 / 排队 | 0.8~0.95 | `tool_call` |
| `signal.scene_fit` | 适合约会 / 带父母 / 安静 | 0.6~0.8 | `rag_retrieval` |
| `signal.pitfall` | 避坑 / 踩雷 / 值不值 | 0.6~0.8 | `rag_retrieval` |
| `signal.merchant_detail` | 怎么样 / 评价 / 人均 | 0.7~0.85 | `rag_retrieval` |
| `signal.merchant_name` | 商家名词典匹配 | 0.6~0.9 | `rag_retrieval` |
| `signal.pronoun` | 这家 / 那家 / 第二个 / 它 | 0.5~0.7 | `follow_up_reference` |
| `signal.greeting` | 你好 / 嗨 / hello | 0.9+ | `direct_answer` |
| `signal.thanks` | 谢谢 / 辛苦了 | 0.9+ | `direct_answer` |
| `signal.profile` | 你有什么功能 / 你是谁 | 0.9+ | `direct_answer` |
| `signal.memory_update` | 记住 / 以后 / 习惯 | 0.75~0.9 | `memory_update` |
| `signal.booking` | 订座 / 预约 / 下单 | 0.7~0.9 | `tool_call` |
| `signal.multi_shop_compare` | 对比 / 哪个好 / 区别 | 0.7~0.85 | `rag_retrieval` |

**输出格式**：
```python
@dataclass
class SignalPolicyResult:
    candidates: list[IntentCandidate]
    top_confidence: float
    matched_signals: list[str]
    merchant_hit: MerchantMatch | None    # 商家名匹配结果
    pronoun_hit: PronounMatch | None      # 指代词匹配结果
    conflict_resolution: str | None

@dataclass
class IntentCandidate:
    intent_name: str
    confidence: float
    route: str
    matched_signal: str
    slots: dict[str, Any]
    preferred_chunk_roles: list[str]
    tool_candidates: list[str]

@dataclass
class MerchantMatch:
    merchant_name: str
    merchant_id: str | None
    match_type: Literal["exact", "fuzzy", "alias"]
    confidence: float

@dataclass
class PronounMatch:
    pronoun: str
    reference_type: Literal["this", "that", "next", "previous", "ordinal"]
    ordinal: int | None  # 第几个
    confidence: float
```

**设计要点**：
- 信号匹配器独立注册、可插拔、可配置开关
- 多信号同时命中时按优先级 + 置信度初步消解
- 商家名识别信息传给 Stage 3 和 Stage 4
- 指代词信息传给 Stage 4（Target Resolution）

---

### Stage 3: LLM Semantic Parser

**职责**：理解复杂语义、多轮上下文、隐式意图、用户需求 facet 抽取。

**输入**：
- `raw_query`: 用户原始输入
- `session_context`: 多轮上下文
- `signal_policy_result`: Stage 2 的候选意图 + 商家名 + 指代词

**Prompt 模板**：
```
System: 你是本地生活意图解析助手。根据用户输入、历史上下文、规则引擎信号，输出结构化 JSON。

[Signal Hints]
  规则引擎识别到以下候选意图：
  {candidates_json}
  商家名匹配：{merchant_hint}
  指代词：{pronoun_hint}
  如果合理请参考，如果不合理请忽略。

[Session Context]
  上一轮 intent: {last_intent}
  当前店铺: {current_shop}
  已选店铺: {selected_shops}
  已填槽位: {slots}

[User Input]
  {raw_query}

输出 JSON (严格遵循以下 schema):
{
  "intent": "string (意图名称)",
  "confidence": "float (0-1)",
  "slots": {
    "shop_name": "string | null",
    "location": "string | null",
    "category": "string | null",
    "scene": "string | null",
    "price_range": "string | null"
  },
  "facet_needs": ["scene_fit", "coupon", "open_status", "distance_eta", ...],
  "needs_rag": "bool",
  "needs_tool": "bool",
  "needs_clarify": "bool",
  "target_shop": {
    "shop_name": "string | null",
    "reference_type": "explicit | pronoun_inherit | context_inherit | none",
    "clarify_if_missing": "bool"
  },
  "reason": "string (简短说明)"
}
```

**输出格式**：
```python
@dataclass
class LLMParserResult:
    intent: str
    confidence: float
    slots: dict[str, Any]
    facet_needs: list[str]
    needs_rag: bool
    needs_tool: bool
    needs_clarify: bool
    target_shop: LLMTargetShop | None
    reason: str
    raw_llm_output: dict | None

@dataclass
class LLMTargetShop:
    shop_name: str | None
    reference_type: str  # explicit | pronoun_inherit | context_inherit | none
    clarify_if_missing: bool
```

**设计要点**：
- 超时熔断 1.5s，超时返回 None
- 不可用时 Decision Merger 走纯规则 fallback
- Signal Hints 作为 few-shot 注入，降低 LLM 幻觉
- facet_needs 直接指导 Contract Builder

---

### Stage 4: Target Resolution

**职责**：解析用户目标商家/实体，处理指代继承。

**处理流程**：
```
LLM target_shop + Signal merchant_hit + pronoun_hit
  │
  ▼
┌─────────────────────────────────────────────┐
│ 4.1 显式商家                                 │
│   LLM 输出 shop_name 或 Signal 匹配商家名    │
│   → 直接锁定，高置信度                       │
├─────────────────────────────────────────────┤
│ 4.2 候选店选择                               │
│   上一轮有多家候选，本轮选择"第二个"/"那家"  │
│   → 从 session.last_candidates 中按 ordinal  │
├─────────────────────────────────────────────┤
│ 4.3 指代继承                                 │
│   "它呢"/"这家怎么样" → 继承 current_shop    │
│   需检查调用方 context_has_anchor             │
├─────────────────────────────────────────────┤
│ 4.4 禁止继承场景                             │
│   "附近有什么推荐" + 当前有 shop →           │
│   新意图不应继承旧 shop，需澄清              │
├─────────────────────────────────────────────┤
│ 4.5 缺失澄清                                 │
│   需要 shop 但无目标 → clarify_if_missing    │
│   生成 clarification_question                │
└─────────────────────────────────────────────┘
```

**输出格式**：
```python
@dataclass
class ResolvedTarget:
    shop_id: str | None
    shop_name: str | None
    confidence: float
    source: str  # explicit | candidate_selection | pronoun_inherit | context_inherit | none
    resolved_references: list[str]
    missing: bool
    clarification_question: str | None
```

---

### Stage 5: Decision Merger

**职责**：融合 Signal Policy、LLM Parser、Target Resolution 的结果，做出最终路由决策。

**融合策略**：

| 场景 | Signal | LLM | Target | 融合结果 |
|------|--------|-----|--------|---------|
| 一致 | 高置信度 | 高置信度且一致 | 已解析 | 加权平均，走 route |
| 规则主导 | 高置信度 | 低/超时/None | — | 走规则，标记 `source=signal_policy` |
| LLM 主导 | 低/无匹配 | 高置信度 | — | 走 LLM，标记 `source=llm` |
| 冲突 | 高(A) | 高(B) | — | 置信度比较，差异 < 0.15 → clarify |
| 都低 | 低 | 低 | — | required_action=clarify |
| Target 缺失 | — | — | missing=True | 叠加 clarification |

**输出**：`RoutingDecision`
```python
@dataclass
class RoutingDecision:
    raw_query: str
    normalized_query: str
    domain: str
    confidence: float
    intent: IntentRoutingDecision      # name + confidence + routes
    required_action: str               # rag_retrieval / tool_call / rag_plus_tool / direct_answer / clarify / reject / memory_update
    blocked: bool
    blocked_reason: str | None
    should_retrieve: bool
    should_call_tool: bool
    preferred_chunk_roles: list[str]
    tool_candidates: list[str]
    should_use_memory: bool
    should_persist_memory: bool
    clarification_question: str | None
    missing_slots: list[str]
    resolved_references: list[str]
    target: ResolvedTarget | None
    decision_source: str               # "hard_guard" | "signal_policy" | "llm" | "merged"
    decision_trace: dict               # 各 stage 中间输出
```

---

### Stage 6: Contract Builder

**职责**：根据路由决策，生成可执行的执行契约。

**三个契约**：

```python
@dataclass
class AnswerContract:
    evidence_requirements: list[FacetRequirement]   # 需要什么证据
    forbidden_without_evidence: list[str]           # 没有证据禁止说
    citation_policy: str                            # must / prefer / optional / none
    answer_mode: str                                # grounded / partial / clarify / fallback

@dataclass
class RetrievalContract:
    semantic_query: str
    preferred_chunk_roles: list[str]
    filters: dict[str, Any]                         # shop_id, city, category 等
    max_results: int
    min_score: float

@dataclass
class ToolContract:
    tool_name: str
    payload: dict[str, Any]
    required_slots: list[str]
    fallback_action: str | None                     # LLM 回答 / 澄清
    timeout_ms: int
```

**SourceOfTruthPolicy**：事实来源优先级

```
Tool 实时数据 > RAG 静态数据 > LLM 生成
```

当 tool 和 RAG 都可用时，tool 结果优先用于动态信息（营业状态/价格/排队），RAG 结果用于静态信息（评价/场景/口碑）。

---

### Stage 7: Execution Router

**职责**：根据 Contract 分派到对应执行子图。

```
ExecutionContracts
  │
  ▼
┌──────────────────────────────────────────────┐
│ required_action 分派                           │
│                                                │
│ clarify ────────→ ClarifySubgraph              │
│                  生成澄清问题，回复用户          │
│                                                │
│ rag_retrieval ──→ RAGSubgraph                  │
│                  按 RetrievalContract 执行检索  │
│                                                │
│ tool_call ──────→ ToolSubgraph                 │
│                  按 ToolContract 调用工具       │
│                                                │
│ rag_plus_tool ──→ RAGThenToolSubgraph          │
│                  先 RAG 检索，再 tool 补充      │
│                  TaskPlan 若存在则走 plan       │
│                                                │
│ direct_answer ──→ DirectAnswerSubgraph         │
│                  问候/感谢/自我介绍等          │
│                                                │
│ memory_update ──→ MemorySubgraph               │
│                  保存偏好/习惯到记忆            │
└──────────────────────────────────────────────┘
```

---

### Stage 8: Trace / Eval / Replay

**职责**：全链路可观测性，支持离线评估和在线调试。

```python
@dataclass
class RoutingTrace:
    query: str
    session_id: str
    timestamp: str

    # 每个 stage 的输入/输出/耗时
    stages: dict[str, StageTrace]

    # 最终决策
    final_decision: RoutingDecision

    # 是否正确（eval 时标注）
    ground_truth: dict | None = None
    is_correct: bool | None = None

@dataclass
class StageTrace:
    input: Any
    output: Any
    duration_ms: float
    error: str | None = None
```

**功能**：
- **Golden Case 录制**：每次请求记录完整 trace，人工标注后可成为 golden case
- **自动回放**：debug 模式逐 stage 回放，对比新老架构输出
- **指标上报**：每个 stage 的准确率、召回率、平均延迟、P99 延迟
- **Diff 测试**：新旧架构并行运行，diff 不一致时告警

---

## 三、与现有架构的映射

| 新 Stage | 现有代码位置 | 关系 |
|----------|-------------|------|
| Stage 1 Hard Guard | `router/phase0_quality.py:build_initial_routing_decision` 中的质量检查部分 | 提取独立 |
| Stage 2 Signal Policy | `routing_signals.py:route_semantic_query` + `_fallback_semantic_route` | 重构为注册式 |
| Stage 3 LLM Parser | `adapters/stages_front_a.py:parse_intent_slots` 中的 `model_gateway.classify_turn` | 提取独立 + 加 Signal Hints |
| Stage 4 Target Resolution | 散落在 `routing_primitives.py` + `phase0_quality.py` 的引用解析 | 集中为独立 stage |
| Stage 5 Decision Merger | `phase0_quality.py:build_initial_routing_decision` 的覆盖逻辑 + `phase3_review.py` | 重构为显式融合 |
| Stage 6 Contract Builder | `phase7_compose.py` + `phase5_retrieval.py` + `phase6_tool.py` | 由分散的 builder 聚合 |
| Stage 7 Execution Router | `application/workflow/runner.py` + `subgraphs.py` 中的 graph 路由 | 逻辑存在，需抽象 |
| Stage 8 Trace/Eval | `local_life/eval/run_golden_cases.py` + 散落 trace | 统一框架 |

---

## 四、文件结构

```
application/router/
├── __init__.py
├── base.py                             # 公共类型（RoutingDecision 等）
│
├── stages/
│   ├── __init__.py
│   ├── hard_guard.py                   # Stage 1
│   ├── signal_policy.py                # Stage 2
│   ├── signal_policy_registry.py       # 信号注册表
│   ├── llm_parser.py                   # Stage 3
│   ├── llm_prompt.py                   # Prompt 模板
│   ├── target_resolution.py            # Stage 4
│   ├── decision_merger.py              # Stage 5
│   ├── contract_builder.py             # Stage 6
│   ├── execution_router.py             # Stage 7
│   ├── trace.py                        # Stage 8
│   └── types.py                        # 各 stage 的 dataclass
│
├── phase0_quality.py      → 删除（逻辑并入 stages/）
├── phase1_intent.py       → 删除（逻辑并入 stages/）
├── phase2_slots.py        → 保留（证据质量评估，post-retrieval）
├── phase3_review.py       → 删除（逻辑并入 decision_merger）
├── phase4_plan.py         → 保留（复杂任务规划，rag_plus_tool 场景）
├── phase5_retrieval.py    → 保留（检索执行逻辑）
├── phase6_tool.py         → 保留（工具执行逻辑）
├── phase7_compose.py      → 保留（答案编排，调用 contract 输出）
│
├── routing_primitives.py  → 大幅缩减（信号逻辑移入 stages/）
├── routing_signals.py     → 大幅缩减（信号注册表移入 stages/）
│
├── tests/
│   ├── test_hard_guard.py
│   ├── test_signal_policy.py
│   ├── test_target_resolution.py
│   ├── test_decision_merger.py
│   └── test_contract_builder.py
│
└── eval/
    ├── golden_cases.json               # 标注的 golden case 集
    ├── run_golden_cases.py
    └── diff_tester.py                  # 新旧架构并行 diff 工具
```

---

## 五、示例流程

**用户输入**："带女朋友去吃饭，推荐个环境好的地方"

```
Stage 1: Hard Guard
  → 非空 ✓ / 非标点 ✓ / 有信息量 ✓
  → 非敏感 ✓ / 非非法 ✓
  → 通过

Stage 2: Signal Policy
  → signal.scene_fit: "适合" + "女朋友" → 约会场景 → 0.75
  → signal.nearby: 无 "附近/周边" → 不命中
  → signal.recommend: "推荐" → 0.6
  → candidates = [
      IntentCandidate("local_life_recommend", 0.75, "rag_retrieval", "scene_fit", slots={scene:"约会"}),
      IntentCandidate("local_life_recommend", 0.60, "rag_retrieval", "recommend"),
    ]
  → merchant_hit=None, pronoun_hit=None

Stage 3: LLM Semantic Parser
  输入: raw_query + session + signal_hints
  输出: {
    intent: "local_life_recommend",
    confidence: 0.88,
    slots: {scene: "约会", location: null, category: "餐厅"},
    facet_needs: ["scene_fit", "recommendation_reason", "shop_detail"],
    needs_rag: true,
    needs_tool: false,
    needs_clarify: true,
    target_shop: {shop_name: null, reference_type: "none", clarify_if_missing: false},
    reason: "用户想找适合约会的餐厅，需要场景推荐"
  }

Stage 4: Target Resolution
  → LLM target=none, Signal merchant=none, 无指代词
  → 无上下文 shop（新 session）
  → target = ResolvedTarget(missing=false)
  → 用户要的是"推荐"而非指定商家，不需要 target

Stage 5: Decision Merger
  → Signal: scene_fit(0.75) → rag_retrieval
  → LLM: local_life_recommend(0.88) → rag_retrieval
  → 一致性校验：通过
  → confidence = max(0.75, 0.88) = 0.88
  → decision_source = "merged"

Stage 6: Contract Builder
  → AnswerContract: evidence=[scene_fit, recommendation_reason, shop_detail],
                     citation_policy=must,
                     answer_mode=grounded
  → RetrievalContract: chunk_roles=[merchant_review_summary, merchant_profile],
                        filters={category: "餐厅"}
  → ToolContract: none（needs_tool=false）

Stage 7: Execution Router
  → required_action=rag_retrieval
  → 分派到 RAGSubgraph

Stage 8: Trace
  → 记录 7 个 stage 的输入/输出/耗时
  → 上报指标
```

**用户输入**："嗯"

```
Stage 1: Hard Guard
  → "嗯" ∈ _LOW_INFO_TOKENS → low_information
  → blocked=True, reason="low_information"
  → 直接返回，不进入 Stage 2-8
```

**用户输入**："第二个呢"

```
Stage 1: Hard Guard → 通过
Stage 2: Signal Policy
  → signal.pronoun: "第二个" → ordinal=2 → 0.7
  → candidates = [IntentCandidate("follow_up_reference", 0.7, "rag_retrieval")]
  → pronoun_hit = PronounMatch("第二个", "ordinal", 2, 0.7)
Stage 3: LLM Semantic Parser
  → 输出: {intent: "merchant_detail", target_shop: {reference_type: "pronoun_inherit"}}
Stage 4: Target Resolution
  → pronoun_hit.ordinal=2
  → session.last_candidates = ["店A", "店B", "店C"]
  → 选择候选第 2 个 = "店B"
  → ResolvedTarget(shop_name="店B", source="candidate_selection", confidence=0.85)
Stage 5: Decision Merger → 通过
Stage 6: Contract Builder → RetrievalContract(filters={shop_name: "店B"})
Stage 7: Execution Router → RAGSubgraph
Stage 8: Trace
```
