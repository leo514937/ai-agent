# LLM Semantic Capability Enablement Phase 0 审计报告

## Conclusion

本次 Phase 0 只做语义能力现状审计，不做路由重构和实现扩展。结论是：

- 当前仓库已经具备 `LLM` 参与语义解析、受限解释、证据审阅和答案校验的基础链路。
- 但语义能力边界仍然不完整，关键位置仍保留了明显的关键词、子串、规则和兜底推断。
- 因此，`LLM Semantic Capability Enablement` 的底座已存在，但仍处于“可推进、未完成”的状态。

### Final Gate

- `PHASE_0_AUDIT_STATUS`: `PASS`
- `PHASE_1_IMPLEMENTATION_READY`: `YES`
- `PHASE_2_IMPLEMENTATION_READY`: `NO`
- `PHASE_3_IMPLEMENTATION_READY`: `NO`

说明：
- Phase 0 的目标是把事实边界、语义责任边界和风险边界审清楚，这部分已完成。
- 但系统整体仍有多处确定性规则参与语义判断，故不应误判为“语义能力已完全启用”。

## Scope

本次审计只覆盖当前仓库 `ai-agent / toolcall` 分支下与本地生活 Agent 语义能力相关的链路，重点关注：

- 顶层意图解析
- 语义槽位抽取
- 路由规则与语义边界
- 指代解析与澄清恢复
- 探索型规划
- 证据审阅与答案校验
- 状态写回

不包含：

- Phase 1 之后的实现改造
- 大规模代码重构
- 业务逻辑迁移
- 新增平行执行链路

## Files Audited

| Area | Audited File | Result |
|---|---|---|
| 顶层语义入口 | `/D:/javacode/hm-dianping/local_life_agent/semantic/intent_parser.py` | 发现 LLM 解析 + 规则兜底并存 |
| 槽位抽取 | `/D:/javacode/hm-dianping/local_life_agent/semantic/slot_extractor.py` | 仍有大量关键词/子串语义推断 |
| 路由决策 | `/D:/javacode/hm-dianping/local_life_agent/planning/orchestration_router.py` | 仍以规则信号驱动，语义边界未完全收敛 |
| 指代解析 | `/D:/javacode/hm-dianping/local_life_agent/target/reference_resolver.py` | 依赖语义帧 + 原文回退，存在确定性解析层 |
| 澄清恢复 | `/D:/javacode/hm-dianping/local_life_agent/target/clarification.py` | 多分支规则判断仍然明显 |
| 状态写回 | `/D:/javacode/hm-dianping/local_life_agent/planning/plans/state_update_planner.py` | 是安全写回点，但仍强依赖确定性分支 |
| 活跃轮次恢复 | `/D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/active_turn_resolver.py` | 确认存在多层确定性恢复器 |
| 决定性工具工作流 | `/D:/javacode/hm-dianping/local_life_agent/engine/workflows/deterministic_tool_workflow.py` | 以事实校验和明确补丁为主 |
| 路由总线 | `/D:/javacode/hm-dianping/local_life_agent/engine/_routes.py` | 实际主路由入口，非附件中提到的路径 |
| 语义解析提示词 | `/D:/javacode/hm-dianping/local_life_agent/llm/prompts/local_life_parser.md` | LLM 输出结构已较完整 |
| 证据审阅提示词 | `/D:/javacode/hm-dianping/local_life_agent/llm/prompts/evidence_sufficiency_review.md` | 已具备结构化 review 输出 |
| 答案校验提示词 | `/D:/javacode/hm-dianping/local_life_agent/llm/prompts/answer_verifier.md` | 已明确 unknown 不应被当作 false |
| 回答生成提示词 | `/D:/javacode/hm-dianping/local_life_agent/llm/prompts/answer_verbalizer.md` | 仅允许 grounded facts |

### Repository path note

你附件里出现的以下路径在本仓库中不存在：

- `/D:/javacode/hm-dianping/local_life_agent/engine/orchestration_router.py`
- `/D:/javacode/hm-dianping/local_life_agent/engine/active_turn_resolver.py`
- `/D:/javacode/hm-dianping/local_life_agent/understanding`
- `/D:/javacode/hm-dianping/local_life_agent/state`
- `/D:/javacode/hm-dianping/local_life_agent/review`
- `/D:/javacode/hm-dianping/local_life_agent/response`
- `/D:/javacode/hm-dianping/local_life_agent/evidence`

对应的真实实现分别位于：

- `/D:/javacode/hm-dianping/local_life_agent/planning/orchestration_router.py`
- `/D:/javacode/hm-dianping/local_life_agent/engine/subgraphs/active_turn_resolver.py`
- `/D:/javacode/hm-dianping/local_life_agent/target/`
- `/D:/javacode/hm-dianping/local_life_agent/planning/`
- `/D:/javacode/hm-dianping/local_life_agent/engine/workflows/`

## LLM Semantic Responsibility Matrix

| Capability | Current Owner | Evidence | Judgment |
|---|---|---|---|
| 顶层意图理解 | LLM + fallback rules | `semantic/intent_parser.py` | 部分由 LLM 承担，失败时仍规则兜底 |
| 细粒度槽位理解 | LLM + keyword extraction | `semantic/slot_extractor.py` | 仍明显依赖启发式 |
| 路由语义决策 | Router rules + semantic frame | `planning/orchestration_router.py` | 语义帧参与，但规则主导 |
| 指代消解 | Resolver + semantic frame | `target/reference_resolver.py` | 支持语义输入，但仍有确定性回退 |
| 澄清意图识别 | Clarification handler + rules | `target/clarification.py` | 规则分支较重 |
| 探索规划 | Planner + LLM prompts | `engine/workflows/exploration_planning_workflow.py` | 已有结构，但仍需更强语义统一 |
| 证据审阅 | LLM review + policy gates | `llm/prompts/evidence_sufficiency_review.md` | 边界明确，属于正确分层 |
| 答案验证 | LLM verifier + rule gates | `llm/prompts/answer_verifier.md` | 已能约束输出，但依赖上游证据质量 |
| 最终表述 | LLM verbalizer | `llm/prompts/answer_verbalizer.md` | 基本符合 grounded 输出原则 |

## Deterministic Boundary Matrix

| Boundary | Should be Deterministic? | Current State | Risk |
|---|---|---|---|
| 工具调用合法性 | Yes | 已由 registry/gateway 约束 | 低 |
| 证据充分性门控 | Yes | review prompt + 结构化返回 | 中 |
| 失败/空结果/超时处理 | Yes | 明确返回，不伪装成功 | 低 |
| 状态写回 | Yes | `StateUpdatePlan` 负责 | 中 |
| 单店目标解析 | Mostly yes | 仍带规则解析与回退 | 中 |
| 多候选澄清 | Yes | 规则明确，但上游输入质量影响大 | 中 |
| 路由安全边界 | Yes | 有 policy guard | 中 |

## Keyword Semantic Misuse Matrix

| Location | Misuse Pattern | Why It Is a Misuse | Severity |
|---|---|---|---|
| `semantic/slot_extractor.py` | 用推荐/附近/找/搜/探店等词直接推断 workflow hint | 这是表层词面信号，不等于真实语义意图 | High |
| `semantic/slot_extractor.py` | 用“性价比”“划算”“值不值”等词直接进入比较/偏好路径 | 这些词更像偏好或排序信号，不应被简单当成比较任务 | High |
| `planning/orchestration_router.py` | 结构化文本信号与硬词表共同决定路由 | 容易把语义相近但任务不同的请求误分流 | High |
| `target/clarification.py` | 用主题切换关键词判断是否换题 | 词面判断可能误杀真实续问 | Medium |
| `engine/subgraphs/active_turn_resolver.py` | 多层规则恢复优先于语义理解 | 适合兜底，不适合承载主语义判断 | Medium |
| `target/reference_resolver.py` | 原文回退解析补足语义帧缺失 | 这是安全兜底，但会持续保留规则依赖 | Medium |

## SemanticFrame Gap Matrix

| SemanticFrame Field | Expected Role | Current Observation | Gap |
|---|---|---|---|
| `top_intent` | 顶层语义分类 | 已有 LLM 解析与 fallback | 仍受规则影响 |
| `task_type` | 细任务类型 | 已较结构化 | 仍需统一枚举边界 |
| `merchant_mentions` | 实体候选 | 有解析结果 | 仍需减少原文规则补足 |
| `comparison_targets` | 比较对象集合 | 已进入路由和澄清链路 | 语义与规则混用 |
| `comparison_focus` | 比较侧重点 | 已支持但可进一步语义化 | 中 |
| `focused_facets` | 关注维度 | 与 slot extractor 紧耦合 | 中 |
| `soft_preferences` | 弱偏好 | 仍由规则推断较多 | 高 |
| `ranking_signals` | 排序信号 | 仍明显依赖词面特征 | 高 |
| `need_context` | 是否需要更多上下文 | 已作为澄清依据 | 低 |
| `follow_up` | 后续动作 | 已能输出结构化字段 | 中 |

## Router Policy Findings

1. 实际路由总线在 `/D:/javacode/hm-dianping/local_life_agent/engine/_routes.py`，不是附件中提到的 `engine/orchestration_router.py`。
2. 路由已经分出 `direct_response`、`deterministic_tool`、`discovery_decision`、`exploration_planning`、`clarification_fallback` 等工作流名称。
3. 但 `planning/orchestration_router.py` 仍以规则信号和文本词面驱动，未完全转向纯语义分流。
4. 语义帧虽然被消费，但不是唯一决策源。
5. 安全和禁限域是硬规则守门，这部分是必要的，不应移除。

## Grounding Findings

1. `intent_parser.py` 已经不是纯规则 parser，确实在调用 LLM，并把结果约束到结构化 payload。
2. 失败时仍会使用 `_fallback_semantic_frame` 和 `_safe_extract_slots`，这意味着语义理解没有完全交给模型。
3. `answer_verbalizer.md` 限制最终回答只能使用 grounded facts，这是正确方向。
4. `answer_verifier.md` 与 `evidence_sufficiency_review.md` 已形成“先证据、后表达”的安全网。
5. 但如果上游 slot / router 继续大量依赖关键词，grounding 再强也只能兜底，不能替代语义理解。

## Clarification Resume Findings

1. `target/clarification.py` 已支持取消、换题、恢复、越界和无效输入等多种状态。
2. `engine/subgraphs/active_turn_resolver.py` 采用多层恢复逻辑，先规则、再模糊、再可选 LLM。
3. 这套设计对稳定性有帮助，但也说明当前“恢复语义”并不是纯 LLM 负责。
4. `topic switch`、`cancel`、`selection` 这些判断仍有显著词面依赖。
5. 澄清恢复链路总体可用，但语义边界还未完全收敛。

## Exploration Planning Findings

1. 探索式任务已经有专门的 planning workflow。
2. 规划输入中包含场景、位置、约束、排序维度等结构化信息。
3. 当前问题不是“没有规划”，而是“规划前的语义理解还混有规则特征”。
4. 这会导致 `先吃饭再...`、`附近...`、`推荐...` 一类请求在边界上被过早归类。

## Evidence Review / Answer Verify Findings

1. `evidence_sufficiency_review.md` 的设计方向正确，具备 FINISH / REPLAN_EVIDENCE / CLARIFY / DEGRADE_ANSWER / UNSUPPORTED_ANSWER / FALLBACK / EXPAND_SEARCH 等输出。
2. `answer_verifier.md` 明确区分 unknown 与 false，这一点很关键。
3. 这两层是当前链路里最接近“语义治理层”的部分。
4. 风险在于：如果输入证据本身已被规则偏置，review/verifier 只能校验“偏置后的结果”，不能自动修复上游误判。

## State Update Findings

1. `planning/plans/state_update_planner.py` 是状态写回的中心。
2. 它负责 `current_shop`、`last_recommendation_list`、`comparison_targets`、`pending_clarification` 等关键状态的 set/clear。
3. 当前状态更新是“显式计划写回”，这一点很好，避免了散落式副作用。
4. 但状态字段较多，且和比较、澄清、推荐列表强耦合，后续需要更清晰的语义来源标记。

## Test Findings

已运行的最小回归：

- `python -m compileall local_life_agent`
- `pytest local_life_agent/tests/test_semantic_router_policy_alignment.py -q`
- `pytest local_life_agent/tests/test_router_rule_policy_guard.py -q`
- `pytest local_life_agent/tests/test_chat_interface_full_e2e.py -q`

结果：

- `compileall` 通过
- `test_semantic_router_policy_alignment.py`: `4 passed`
- `test_router_rule_policy_guard.py`: `40 passed`
- `test_chat_interface_full_e2e.py`: `17 skipped`, 1 warning

补充观察：

- 当前回归没有暴露新的语法错误或明显路由回退崩溃。
- 但 e2e 测试大量跳过，说明完整链路验证仍不够充分。

## Required Phase 1 Inputs

Phase 1 建议补齐的输入项：

1. 明确的语义责任清单，区分“LLM 必须负责”和“规则只能做安全守门”的边界。
2. 语义帧字段规范，尤其是 `comparison_targets`、`soft_preferences`、`ranking_signals` 的语义定义。
3. 路由决策基准集，包含推荐、比较、探索、澄清、指代、多轮追问的真实样例。
4. 关键词兜底黑名单，明确哪些词不能再直接驱动业务分支。

## Required Phase 2 Inputs

Phase 2 建议补齐的输入项：

1. 统一的 `SemanticFrame -> DecisionPlan` 转换契约。
2. 路由到 planner 的最小语义特征集。
3. 指代恢复的优先级规则说明。
4. 状态写回的字段所有权表。

## Required Phase 3 Inputs

Phase 3 建议补齐的输入项：

1. 端到端对照集，覆盖“同义表达、委婉表达、口语表达、打断表达”。
2. 误路由样本集，用于回归 keyword/substring 误判。
3. 证据不足、候选过多、指代不清、换题恢复等失败样本集。
4. 线上/本地一致的验收口径。

## Risks

1. 关键词/子串信号仍会持续污染语义层，导致“看起来像理解，实际上是规则分类”。
2. 规则兜底过多会掩盖 LLM 真实短板，测试容易高估语义能力。
3. 澄清恢复、比较对象和探索规划之间的边界仍可能交叉污染。
4. 如果后续不把语义责任和确定性责任拆清楚，路由层会继续膨胀。

## Regression Commands Run

```bash
python -m compileall local_life_agent
pytest local_life_agent/tests/test_semantic_router_policy_alignment.py -q
pytest local_life_agent/tests/test_router_rule_policy_guard.py -q
pytest local_life_agent/tests/test_chat_interface_full_e2e.py -q
```

## Final Gate

### Current State

- `PHASE_0_AUDIT_COMPLETE`: `true`
- `SEMANTIC_MODELING_READY_FOR_NEXT_PHASE`: `true`
- `ROUTER_RULES_STILL_REQUIRE_REDUCTION`: `true`
- `DIRECT_IMPLEMENTATION_ALLOWED_NOW`: `false`

### Audit Verdict

本次审计确认：

- 语义能力已经进入“LLM + 规则守门”的混合阶段。
- 但当前混合并不是最终目标形态，关键词和硬规则仍在承担过多语义工作。
- 因此建议进入下一阶段的前提是先收敛语义责任边界，再逐步削减规则兜底。

