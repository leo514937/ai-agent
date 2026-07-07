# 三层改造统一执行计划

> **核心原则**：先堵 bypass 再搭合同，先修安全漏洞再建能力，先稳定单店再扩推荐对比，先确定性再 LLM，第一层理解增强可以晚于第二三层。
>
> **全局约束**：`final_response` 权威写入点缩减到 **1 个**；旧字段兼容赋值只能由统一出口派生（不可由 8 个不同节点直接写）。

---

## 索引说明

每批包含若干可独立实施和验证的步骤，编号格式为 `{批号}{序号}`。

每个步骤标注：
- **引用**：对应 `todo/first_layer/`、`todo/second_layer/`、`todo/third_layer/` 中的 Phase
- **涉及文件**：需要新增或修改的核心文件路径（相对 `local_life_agent/`）
- **验收标准**：该步骤完成后的可验证条件

---

## 第 0 步：事实冻结（只读，不改业务代码）

> 三步可并行，不提交业务代码。产出的矩阵文档作为后续改造的基线依据。

### 0a：第一层事实冻结

| 项目 | 内容 |
|---|---|
| **引用** | `todo/first_layer/01_first_layer_fact_baseline.md`（已补充）<br>`todo/first_layer/02_first_layer_problem_analysis.md`（已补充） |
| **产出** | 6 个技术点基线报告：Mixed Intent / ContextualizedTurn vs SemanticFrame / FocusContext 粒度 / load_session 位置 / InMemorySessionStore / target_resolve 跨层重叠 |
| **不动** | 不修改任何业务代码 |

### 0b：第二层事实冻结

| 项目 | 内容 |
|---|---|
| **引用** | `todo/second_layer/01_second_layer_fact_baseline.md`<br>`todo/second_layer/02_second_layer_problem_analysis.md`（已重写 P0-2/3/4/5/7/8） |
| **产出** | workflow registry 矩阵、route 字段矩阵、review/retry/fallback 矩阵、EvidencePlan 真实结构 |
| **不动** | 不修改任何业务代码 |

### 0c：第三层事实冻结

| 项目 | 内容 |
|---|---|
| **引用** | `todo/third_layer/01_third_layer_fact_baseline.md`（已补充）<br>`todo/third_layer/02_third_layer_problem_analysis.md`（已补充） |
| **产出** | 8 个 `final_response` 写入位置清单、response_mode 分散字符串清单、verifier/rewrite/fallback 真实调用链 |
| **不动** | 不修改任何业务代码 |

---

## 第 1 批：统一出口 + 安全漏洞 + RewriteInstruction（P0 集中攻坚）— 拆为 4 个子批

> ⚠️ **核心顺序原则**：先统一出口再改路由，先修安全漏洞再动 workflow。因此拆为 4 个可独立验证的子批，按 1A → 1B → 1C → 1D 顺序执行，每子批完成后运行全量回归才能进入下一子批。

---

### ▎第 1A 子批：回答契约 + 安全修复（不改路由）

> **不改路由、不改 workflow、不改 registry**。只做：枚举统一、安全漏洞修复、最小出口结构。

#### 1A-a：ResponseMode Enum

| 项目 | 内容 |
|---|---|
| **引用** | `todo/third_layer/10_third_layer_migration_plan.md Phase B` |
| **涉及文件** | `domain/enums.py`（追加 `ResponseMode`）、`engine/subgraphs/response_subgraph.py`、`engine/_routes.py`、`engine/workflows/*`、`observability/trace.py` |
| **关键设计** | `DIRECT`、`REJECT`、`CLARIFY`、`FALLBACK`、`ANSWER`、`TOOL_ANSWER`、`COMPARISON`、`EXPLORATION_PLAN` 各为独立枚举值 |
| **兼容** | 旧字符串通过 `str, Enum` 值映射兼容 |
| **验收** | 所有路径写入 Enum；未匹配时正确 fallback |
| **测试文件** | `tests/test_third_layer_response_mode_enum.py` |
| **回滚** | 撤销 Enum 定义 |

#### 1A-b：verify 空 evidence / 空 draft 不 pass

| 项目 | 内容 |
|---|---|
| **引用** | `todo/third_layer/10_third_layer_migration_plan.md Phase D` |
| **涉及文件** | `engine/subgraphs/response_subgraph.py:290-298`、`answer/verifier.py` |
| **改法** | 空 evidence 或空 draft 时标记 `unverifiable`，走 `_h_fallback_answer` 输出有意义兜底 |
| **验收** | 不返回 `"pass"`；走 fallback |
| **测试文件** | `tests/test_third_layer_verifier_no_empty_pass.py` |
| **回滚** | 恢复旧 `verify_result = "pass"` 逻辑 |

#### 1A-c：minimal ResponseDirective

| 项目 | 内容 |
|---|---|
| **引用** | `todo/third_layer/04_third_layer_contract_design.md §3` |
| **涉及文件** | 新增 `answer/response_directive.py` |
| **设计** | 极简结构：`answer_text`、`answer_type`、`response_mode`、`fallback_reason`、`trace_id`。所有回答路径统一目标格式，旧 `final_response` 从它派生 |
| **验收** | 所有回答路径产出 ResponseDirective |
| **测试文件** | `tests/test_third_layer_response_contract.py`（覆盖 ResponseDirective） |
| **回滚** | 删文件，恢复旧直写 |

#### ▎第 1A 子批验收

| 验收项 | 标准 | 验证方式 |
|---|---|---|
| ResponseMode 统一 | 8 枚举值，无字符串散落 | Enum 单测 |
| 空 evidence/draft | 不 pass，走 fallback | 安全单测 |
| ResponseDirective | 所有路径按统一格式输出 | 合约测试 |
| **回归** | 已有 query 不退化 | `pytest local_life_agent/tests -q` |

---

### ▎第 1B 子批：确定性表达 + 重写基础设施（不改路由）

> **前提**：第 1A 子批已验收通过。
>
> **不改路由、不改 workflow、不改 registry**。只做：composer、LLM fallback 修复、RewriteInstruction 结构定义。

#### 1B-a：minimal DeterministicComposer（4 个）

| 项目 | 内容 |
|---|---|
| **引用** | `todo/third_layer/12_third_layer_file_change_plan.md Phase I（minimal）` |
| **涉及文件** | 新增 `answer/composers/direct_response_composer.py`、`answer/composers/clarification_composer.py`、`answer/composers/system_fallback_composer.py`、`answer/composers/single_shop_fact_composer.py` |
| **设计** | - `DirectResponseComposer`：闲聊/能力说明/安全拒答<br>- `ClarificationComposer`：缺信息/歧义/候选项选择<br>- `SystemFallbackComposer`：工具失败/熔断/unknown<br>- `SingleShopFactComposer`：单店 coupon/open_status/distance/rating/price（覆盖 5 个 facet） |
| **验收** | 每个 composer 输出有意义文案；延迟 ≤ LLM verbalizer 路径的 20% |
| **测试文件** | `tests/test_third_layer_deterministic_composers.py` |
| **回滚** | 删 composer 文件，恢复旧 keyword composer |

#### 1B-b：LLM disabled / timeout / empty output 走 composer

| 项目 | 内容 |
|---|---|
| **引用** | `todo/third_layer/10_third_layer_migration_plan.md Phase E` |
| **涉及文件** | `answer/generator.py:664-670`、`answer/llm_verbalizer.py:487-514` |
| **改法** | LLM 不可用或异常时走 1B-a 的 composer，不走硬编码占位符 |
| **验收** | LLM 禁用时输出基于证据的确定性回答 |
| **测试文件** | `tests/test_third_layer_llm_disabled_fallback.py`（覆盖 disabled / timeout / empty） |
| **回滚** | 恢复旧占位符逻辑 |

#### 1B-c：RewriteInstruction 结构定义

| 项目 | 内容 |
|---|---|
| **引用** | `todo/third_layer/10_third_layer_migration_plan.md Phase F` |
| **涉及文件** | 新增 `answer/rewrite_instruction.py` |
| **设计** | 结构化重写指令：`violation_codes`、`unsupported_claims`、`contradicted_claims`、`required_additions`、`claims_to_keep`。仅定义结构和序列化，不接入 rewrite 循环（留到 1C 接入） |
| **验收** | 结构可创建、可序列化、可被 verifier 产出消费 |
| **测试文件** | `tests/test_third_layer_rewrite_instruction.py` |
| **回滚** | 删文件，恢复旧计数逻辑 |

#### ▎第 1B 子批验收

| 验收项 | 标准 | 验证方式 |
|---|---|---|
| 4 个 composer | 输出有意义文案，覆盖 5+ facet | composer 单测 |
| LLM disabled | 确定性回答，无占位符 | 场景测试 |
| RewriteInstruction | 结构完整、可序列化 | DTO 单测 |
| **回归** | 已有 query 不退化 | `pytest local_life_agent/tests -q` |

---

### ▎第 1C 子批：出口收敛 + workflow 改造（此时才改路由和 registry）

> **前提**：第 1B 子批已验收通过。出口契约（ResponseDirective）、表达能力（composer）、重写结构（RewriteInstruction）全部就绪后才动 workflow。
>
> **改动路由和 registry**：收敛 bypass、集成 RewriteInstruction、改 workflow 注册名。

#### 1C-a：收敛 workflow bypass final_response + RewriteInstruction 集成

| 项目 | 内容 |
|---|---|
| **引用** | `todo/third_layer/10_third_layer_migration_plan.md Phase H（P0）` + `Phase F（集成）` |
| **涉及文件** | `engine/workflows/deterministic_tool_workflow.py:933`、`exploration_planning_workflow.py:824`、`direct_response_workflow.py:159`、`clarification_fallback_workflow.py:233`、`response_subgraph.py:382-418`、`response_subgraph.py:422-491`、`_routes.py:311-320`、`answer/verifier.py`（_h_rewrite 接入 RewriteInstruction） |
| **设计** | 1. 4 个 workflow 不再自写 `final_response`，改为写中间字段<br>2. `_h_final_response` 成为唯一权威写入点<br>3. _h_rewrite 消费 RewriteInstruction：violation → instruction → 走 composer 或带 instruction 重走 LLM<br>4. `_routes.py` 路由条件简化（不再依赖 `response_mode == comparison` 兜底） |
| **验收** | final_response 写入点只剩 `_h_final_response` 1 个；RewriteInstruction 驱动 rewrite 而非裸计数；路由不再使用 response_mode 兜底 |
| **测试文件** | `tests/test_third_layer_workflow_boundary.py`、扩展 `tests/test_third_layer_rewrite_instruction.py` |
| **回滚** | 恢复各 workflow 旧 `_build_success_patch` 直写；_h_rewrite 切回裸计数 |

#### 1C-b：deterministic_tool → single_shop_fact_workflow（此时才改 registry）

| 项目 | 内容 |
|---|---|
| **引用** | `todo/second_layer/09_second_layer_migration_plan.md Phase C` |
| **涉及文件** | `engine/workflows/deterministic_tool_workflow.py`（升级）、`engine/workflow_registry.py`（注册新名和 alias） |
| **改法** | 出口已统一，registry 改名安全：产出 `DecisionPlan` / `EvidencePack` 给统一管线消费；LLM review 改为 deterministic verify |
| **验收** | 单店事实查工具、产 EvidencePack、走统一出口、低 LLM 调用 |
| **测试文件** | `tests/test_second_layer_single_shop_fact_workflow.py` |
| **回滚** | registry 切回 `deterministic_tool` |

#### ▎第 1C 子批验收

| 验收项 | 标准 | 验证方式 |
|---|---|---|
| bypass 收敛 | final_response 写入点只剩 1 个 | code search + 测试 |
| RewriteInstruction 集成 | violation → instruction → 精确修复 | rewrite 集成测试 |
| single_shop_fact | registry 改名，出口走统一管线 | workflow 测试 |
| **回归** | 已有 query 不退化 | `pytest local_life_agent/tests -q` |

---

### ▎第 1D 子批：第二层策略层（最小版）

> **前提**：第 1C 子批已验收通过。出口和 workflow 稳定后加策略约束。

#### 1D-a：ReviewPolicy / ExecutionBudget 最小版

| 项目 | 内容 |
|---|---|
| **引用** | `todo/second_layer/09_second_layer_migration_plan.md Phase B（minimal）` |
| **涉及文件** | 新增 `planning/policy/review_policy.py`、`planning/policy/execution_budget.py` |
| **设计** | 最小接口 + 默认值：`ReviewPolicy.max_review_rounds=2`、`ExecutionBudget.max_tool_calls=10`、`ExecutionBudget.max_llm_calls=3` |
| **验收** | 可创建、可序列化、可被 `_h_review_decision` 读取 |
| **测试文件** | `tests/test_second_layer_execution_budget.py` |
| **回滚** | 删文件，保留旧 BudgetContext |

#### ▎第 1D 子批验收

| 验收项 | 标准 | 验证方式 |
|---|---|---|
| 策略对象 | 最小接口 + 默认值 | DTO 单测 |
| **回归** | 已有 query 不退化 | `pytest local_life_agent/tests -q` |

---

## 第 2a 批：第二层策略 + 排序 + 缓存 + 执行器 + 出口升级 — 拆为 4 个子批

> ⚠️ **核心顺序原则**：先修硬约束和 RankingPolicy，再接缓存，再接执行器，最后升级出口契约。因此拆为 4 个按序执行的子批。
>
> **范围说明**：第一层上下文 V0（ContextualizedTurn / FocusContext）不在此批——等第三层出口和第二层单店事实稳定后再进入（见后续批次）。

---

### ▎第 2a-A 子批：策略完整 + 排序权威（先修硬约束）

> **前提**：第 1D 子批（策略最小版）已验收通过。
>
> **先修 RankingPolicy 和 ExpandSearch**，确保推荐排序有硬约束过滤，expand_search 不清空用户条件。此阶段不改执行器。

#### 2a-Aa：ReviewPolicy / ExecutionBudget / ExpandSearchPolicy 完整版

| 项目 | 内容 |
|---|---|
| **引用** | `todo/second_layer/09_second_layer_migration_plan.md Phase B` |
| **涉及文件** | `planning/policy/review_policy.py`（完整）、`planning/policy/execution_budget.py`（完整）、新增 `planning/policy/expand_search_policy.py` |
| **设计** | 完整策略表（按 answer_type 区分）、策略读取入口、运行时覆写机制 |
| **验收** | 三类策略可在 planning_subgraph 和独立 workflow 中统一读取 |
| **测试文件** | `tests/test_second_layer_review_policy.py`、`tests/test_second_layer_execution_budget.py`、`tests/test_second_layer_expand_search_policy.py` |
| **回滚** | 撤销策略代码，保留旧路由和旧预算计数 |

#### 2a-Ab：RankingPolicy 可执行化

| 项目 | 内容 |
|---|---|
| **引用** | `todo/second_layer/08_second_layer_review_ranking_budget_design.md §11` |
| **涉及文件** | `domain/facets.py`（扩展）、新增 `planning/ranking/ranking_executor.py` |
| **设计** | `HardConstraintFilterRule/Set` → `ObjectiveWeight/ScoringSpec` → `TieBreakerRule/Chain` → `ScoreProvenance/Set`，全部可编码 |
| **验收** | 推荐排序有 `feature_scores` / `failed_constraints` / `score provenance` |
| **测试文件** | `tests/test_second_layer_ranking_policy.py` |
| **回滚** | 旧 RankingPolicy 保留，新扩展可独立撤销 |

#### 2a-Ac：ExpandSearchPolicy 修复：不清空 hard constraints

| 项目 | 内容 |
|---|---|
| **引用** | `todo/second_layer/09_second_layer_migration_plan.md Phase F（部分）` |
| **涉及文件** | `engine/subgraphs/planning_subgraph.py:1304-1346`（`_h_expand_search`） |
| **改法** | expand_search 保留已有 `hard_constraints` |
| **验收** | 用户指定硬约束始终保留 |
| **测试文件** | 扩展 `tests/test_second_layer_expand_search_policy.py` |
| **回滚** | 恢复旧 `filters = {}` |

#### ▎第 2a-A 子批验收

| 验收项 | 标准 | 验证方式 |
|---|---|---|
| 策略完整版 | 三类策略统一读取 | 策略单测 |
| RankingPolicy | feature_scores / failed_constraints 完整 | ranking 单测 |
| expand_search | 不清空 hard constraints | 策略单测 |
| **回归** | 已有 query 不退化 | `pytest local_life_agent/tests -q` |

---

### ▎第 2a-B 子批：工具结果缓存

> **前提**：第 2a-A 子批已验收通过。排序/策略稳定后加缓存。

#### 2a-Ba：ToolResultCache + single-flight

| 项目 | 内容 |
|---|---|
| **引用** | `todo/second_layer/09_second_layer_migration_plan.md Phase E（部分）` |
| **涉及文件** | 新增 `planning/execution/tool_result_cache.py` |
| **设计** | 缓存在 GraphState 内（本轮），key = `(shop_id, facet)`，同轮同店同 facet 第二次查直接返回 |
| **验收** | 同轮同店同 facet 不重复执行工具；cache hit 不增加 LLM/工具调用 |
| **测试文件** | `tests/test_second_layer_tool_result_cache.py`（cache hit/miss + single-flight） |
| **回滚** | 删缓存文件，恢复直接工具调用 |

#### ▎第 2a-B 子批验收

| 验收项 | 标准 | 验证方式 |
|---|---|---|
| 工具缓存 | 同轮同店同 facet 不重复查 | 缓存单测 |
| **回归** | 已有 query 不退化 | `pytest local_life_agent/tests -q` |

---

### ▎第 2a-C 子批：StageToolExecutor（RankingPolicy 稳定后才接）

> **前提**：第 2a-B 子批已验收通过。RankingPolicy 和缓存都稳定后，再切换执行模型。

#### 2a-Ca：StageToolExecutor v1

| 项目 | 内容 |
|---|---|
| **引用** | `todo/second_layer/09_second_layer_migration_plan.md Phase E（部分）` |
| **涉及文件** | 新增 `planning/execution/stage_tool_executor.py`、修改 `engine/subgraphs/execution_review_subgraph.py` |
| **设计** | 从平铺 batch 并发升级为按 `ExecutionPlan.stages` 拓扑执行，支持 `depends_on` |
| **验收** | `ExecutionPlan.stages` 被实际消费；有 `depends_on` 的工具组在前序完成后才执行 |
| **测试文件** | `tests/test_second_layer_stage_executor.py`（DAG 拓扑排序 + stage 级并行） |
| **回滚** | 切回 BatchToolExecutor 平铺并发 |

> **门禁**：StageToolExecutor 先在单测中独立验证，再集成到 execution_review_subgraph。集成后运行全量回归，确保新旧执行路径结果一致。

#### ▎第 2a-C 子批验收

| 验收项 | 标准 | 验证方式 |
|---|---|---|
| StageToolExecutor | DAG 拓扑正确，depends_on 生效 | 执行器单测 |
| **回归** | 已有 query 不退化 | `pytest local_life_agent/tests -q` |

---

### ▎第 2a-D 子批：出口契约升级（最后统一出口格式）

> **前提**：第 2a-C 子批已验收通过。执行器稳定后，升级 ResponseDirective → ResponseContract V1。

#### 2a-Da：ResponseContract V1

| 项目 | 内容 |
|---|---|
| **引用** | `todo/third_layer/04_third_layer_contract_design.md §3`<br>`todo/third_layer/12_third_layer_file_change_plan.md Phase C` |
| **涉及文件** | 新增 `answer/response_contract.py`、修改 `answer/final_response_builder.py`、`engine/subgraphs/response_subgraph.py` |
| **设计** | 7 字段：`answer_text`、`answer_type`、`response_mode`、`trace_id`、`verifier_result`、`fallback_reason`、`uncertainty_notices` |
| **验收** | 所有出口路径输出 ResponseContractV1；1A-c 的 ResponseDirective 升级为此版本 |
| **测试文件** | 扩展 `tests/test_third_layer_response_contract.py`（V1 全字段） |
| **回滚** | 消费方退回到 ResponseDirective 读取 |

#### ▎第 2a-D 子批验收

| 验收项 | 标准 | 验证方式 |
|---|---|---|
| ResponseContract V1 | 所有出口都有 | 合约测试 |
| **回归** | 已有 query 不退化 | `pytest local_life_agent/tests -q` |

---

## 第 3 批：RewriteInstruction 集成 + 完整 composer + Claim 验证 + 推荐/对比拆分

> 目标是：Rewrite 从裸计数升级为结构化修复指令；composer 覆盖全部 answer_type；回答有 claim 级验证；推荐和对比有独立 workflow。
>
> **门禁条件**：RewriteInstruction 集成（3a）必须先于 ClaimExtractor（3c），因为 ClaimVerifier 产出 violation 后需结构化指令驱动 rewrite。

### 3a：RewriteInstruction 集成（在 rewrite 循环中消费）

| 项目 | 内容 |
|---|---|
| **引用** | `todo/third_layer/10_third_layer_migration_plan.md Phase F（续 1B-c 结构定义）` |
| **涉及文件** | `answer/verifier.py`（`_h_rewrite` 改造）、`answer/generator.py`（rewrite 循环改造） |
| **设计** | verifier 产出 violation 后：<br>1. 构建 `RewriteInstruction`（violation_codes / unsupported_claims / required_additions）<br>2. rewrite 循环消费 instruction 而非裸计数<br>3. 基于 instruction 选择目标路径：<br>   - 简单事实违规 → 直接走 deterministic composer<br>   - 复杂回答违规 → 带 instruction 重走 LLM verbalizer<br>4. 超过 `MAX_REWRITE_ATTEMPTS` 后走对应 composer fallback |
| **验收** | verifier violation 正确映射到 RewriteInstruction；rewrite 循环按 instruction 精确修复而非整体重生成；超限后进入 composer fallback |
| **测试文件** | 扩展 `tests/test_third_layer_rewrite_instruction.py`（集成场景）<br>新增 `tests/test_third_layer_llm_disabled_fallback.py`（rewrite 超限→fallback 场景） |
| **回滚** | `_h_rewrite` 切回裸 `rewrite_count += 1`，保留 RewriteInstruction 定义 |

### 3b：完整 composer（3 个新增 + 4 个已有升级）

| 项目 | 内容 |
|---|---|
| **引用** | `todo/third_layer/12_third_layer_file_change_plan.md Phase I` |
| **涉及文件** | 新增 `answer/composers/recommendation_composer.py`、`answer/composers/comparison_composer.py`、`answer/composers/exploration_plan_composer.py`；升级 1d 的 4 个 composer |
| **验收** | 7 类 composer 覆盖全部 answer_type；composer 路径在所有场景下都有可用输出 |
| **测试文件** | 扩展 `tests/test_third_layer_deterministic_composers.py`（7 个 composer 各 ≥3 条用例） |
| **回滚** | 删除新增 composer 文件，保留 1B-a 的 4 个 composer |

### 3c：ClaimExtractor + ClaimVerifier L1

| 项目 | 内容 |
|---|---|
| **引用** | `todo/third_layer/10_third_layer_migration_plan.md Phase G`<br>`todo/third_layer/03_third_layer_target_architecture.md §模块3`<br>`todo/third_layer/12_third_layer_file_change_plan.md Phase G` |
| **涉及文件** | 新增 `answer/claim_extractor.py`、`answer/claim_verifier.py`；修改 `answer/verifier.py` |
| **设计** | L1：从 `AnswerPlan.allowed_claims` / `DecisionPlan.factual_points` 直接生成 `expected claims`。产出 violation 后由 3a 的 RewriteInstruction 驱动精确修复 |
| **校验范围** | coupon / open_status / distance / rating / ranking / winner |
| **验收** | ClaimExtractor L1 从 DecisionPlan 正确生成 expected claims；ClaimVerifier 正确定位 supported/unsupported/contradicted；violation 正确输出到 RewriteInstruction |
| **测试文件** | 新增 `tests/test_third_layer_claim_extractor.py`<br>新增 `tests/test_third_layer_claim_verifier_coupon.py`<br>新增 `tests/test_third_layer_claim_verifier_open_status.py`<br>新增 `tests/test_third_layer_claim_verifier_distance.py`<br>新增 `tests/test_third_layer_claim_verifier_recommendation.py`<br>新增 `tests/test_third_layer_claim_verifier_comparison.py` |
| **回滚** | 删除新增文件，恢复旧 keyword-based verifier |

### 3d：discovery_decision 拆分为独立 workflow

| 项目 | 内容 |
|---|---|
| **引用** | `todo/second_layer/09_second_layer_migration_plan.md Phase D` |
| **涉及文件** | 新增 `engine/workflows/recommendation_decision_workflow.py`、`engine/workflows/comparison_decision_workflow.py`；修改 `engine/workflow_registry.py`、`engine/_routes.py` |
| **兼容** | 保留 `discovery_decision` 作为 legacy alias，路由优先走新 workflow |
| **验收** | `discovery_decision` 不再作为推荐/对比主入口；recommendation 和 comparison 各有独立 workflow |
| **测试文件** | 新增 `tests/test_second_layer_workflow_routing.py`（验证推荐/对比/单店 workflow 路由正确） |
| **回滚** | 切换 `_route_workflow_runner` 回旧的三重判定 + `discovery_decision` 入口 |

> **3d 门禁**：推荐/对比 workflow 先在单测中独立验证，再接入 `_routes.py` 路由。切换路由后运行全量回归确保兼容 alias 工作。

### 3e：comparison_matrix → winner 强约束

| 项目 | 内容 |
|---|---|
| **引用** | `todo/second_layer/08_second_layer_review_ranking_budget_design.md §11（RankingPolicy 可执行化）` |
| **涉及文件** | `domain/schemas.py`（`ComparisonMatrix` 扩展）、`planning/ranking/ranking_executor.py` |
| **改法** | `ComparisonMatrix` 内的 winner 字段必须由 `RankingPolicy` + `feature_scores` 决定，LLM 只做 trade-off 解释 |
| **验收** | winner 必须来自 `comparison_matrix` / `DecisionPlan.statistical_winner`；LLM verbalizer 不能自主决定 winner |
| **测试文件** | 扩展 `tests/test_second_layer_ranking_policy.py`（添加 winner 约束断言） |
| **回滚** | 保留旧 ComparisonMatrix，新约束可独立撤销 |

### 3f：exploration_planning_workflow 接入共享能力

| 项目 | 内容 |
|---|---|
| **引用** | `todo/second_layer/09_second_layer_migration_plan.md Phase G` |
| **涉及文件** | `engine/workflows/exploration_planning_workflow.py` |
| **改法** | 替换内部 `_resolve_target`、`_build_evidence`、`_build_execution_plan` 为共享 `TargetResolver` / `EvidencePlanner`；出口走统一管线 |
| **验收** | exploration workflow 不再自包含目标解析/证据构建；复用第二层共享能力包 |
| **测试文件** | 新增 `tests/test_second_layer_exploration_workflow.py`（跨阶段协调测试） |
| **回滚** | 切回旧 exploration_planning_workflow 实现 |

### 第 3 批验收总表

| 验收项 | 标准 | 验证方式 |
|---|---|---|
| RewriteInstruction 集成 | violation 正确映射为指令，rewrite 精确修复 | rewrite 单测 |
| discovery_decision | 不再作为推荐/对比主入口 | 路由测试 |
| recommendation | 有独立 workflow | workflow 测试 |
| comparison | 有独立 workflow | workflow 测试 |
| winner | 来自 comparison_matrix / DecisionPlan，非 LLM | ranking 单测 |
| claim verifier | 能校验 coupon/open_status/distance/ranking/winner | claim 单测 |
| **回归** | **已有单店/推荐/对比/澄清 query 不退化** | `pytest local_life_agent/tests -q` |

---

## 第 4 批前置：第一层上下文 V0 + 基础合同对象

> **执行时机**：第三层出口（批 1C）和第二层单店事实 workflow（批 1C-b）稳定后再进入。不要提前做。
>
> **约束**：V0 只产出 trace 字段，**不修改** `semantic_parse`、`current_shop`、`last_recommendation_list` 的消费逻辑。所有改动为 trace-only / 新增文件。

### 4p-a：ContextualizedTurn V0

| 项目 | 内容 |
|---|---|
| **引用** | `todo/first_layer/03_first_layer_solution_plan.md Phase 2` |
| **涉及文件** | 新增 `domain/contextualized_turn.py`、修改 `engine/subgraphs/understanding_subgraph.py` |
| **设计** | V0 只产出 `ContextualizedTurn` 作为 trace 字段。字段：`original_text`、`normalized_text`、`contextualized_query`、`rewrite_type`、`context_used`、`confidence` |
| **验收** | "便宜一点的呢""第二个怎么样"能产出 trace；原有 `semantic_parse` 行为不变 |
| **测试文件** | `tests/test_first_layer_contextualization.py` |
| **回滚** | 删新增文件，understanding_subgraph 修改可逆 |

### 4p-b：FocusContext V0

| 项目 | 内容 |
|---|---|
| **引用** | `todo/first_layer/03_first_layer_solution_plan.md Phase 3` |
| **涉及文件** | 新增 `domain/focus_context.py`、修改 `engine/_compat.py` |
| **设计** | V0 只产出 `FocusContext` 作为 trace 字段，不替换现有 `current_shop` / `last_recommendation_list` |
| **验收** | "第二个"能产出 trace；旧字段行为不变 |
| **测试文件** | `tests/test_first_layer_focus_context.py` |
| **回滚** | 删新增文件，_compat.py 修改可逆 |

### 4p-c：FreshnessMeta + LocationContext 基础定义

| 项目 | 内容 |
|---|---|
| **引用** | `todo/first_layer/04_first_layer_contract_design.md` |
| **涉及文件** | 新增 `domain/freshness.py`、`domain/location_context.py` |
| **设计** | - `FreshnessMeta`：`generated_at`、`expires_at`、`source`、`freshness_policy`<br>- `LocationContext`：`lat`、`lng`、`label`、`source`、`confidence` |
| **验收** | 可创建、可序列化；FreshnessMeta 可附加到证据字段；LocationContext 可 trace |
| **测试文件** | `tests/test_first_layer_contracts.py` |
| **回滚** | 删新增文件 |

### 第 4 批前置验收

| 验收项 | 标准 | 验证方式 |
|---|---|---|
| ContextualizedTurn | "便宜一点的呢"能产出 trace | 单测 |
| FocusContext | "第二个"能产出 trace | 单测 |
| FreshnessMeta + LocationContext | 可序列化可 trace | DTO 单测 |
| **回归** | 已有测试不退化 | `pytest local_life_agent/tests -q` |

---

## 第 4 批：第一层完整收敛 V1

> 目标是：第一层从 V0 trace-only 升级为 V1 完整功能，替代散落字段。
>
> **前提**：第 4 批前置（第一层 V0）已验收通过。

### 4a：ContextualizedTurn V1 + MixedIntent terminal policy

| 项目 | 内容 |
|---|---|
| **引用** | `todo/first_layer/03_first_layer_solution_plan.md Phase 2` |
| **涉及文件** | `domain/contextualized_turn.py`（V1 完整）、`engine/subgraphs/understanding_subgraph.py`（`context_recovery` 升级）、`engine/_routes.py`（MixedIntent 路由策略） |
| **设计** | MixedIntent 不能 terminal 掉 `local_life` 路由；ContextualizedTurn 被 `semantic_parse` 消费 |
| **验收** | MixedIntent 不会导致非 local_life query 进入 local_life 路径或反向丢失 |

### 4b：FocusContext V1 + FocusResolver

| 项目 | 内容 |
|---|---|
| **引用** | `todo/first_layer/03_first_layer_solution_plan.md Phase 3` |
| **涉及文件** | `domain/focus_context.py`（V1 完整，含 item 级 `FocusItem` 规范）、新增 `domain/focus_resolver.py` |
| **验收** | `FocusContext` 替代散落 `current_shop` / `last_recommendation_list` / `comparison_targets` 的引用解析 |

### 4c：ErrorEnvelope / EarlyResponseDirective

| 项目 | 内容 |
|---|---|
| **引用** | `todo/first_layer/03_first_layer_solution_plan.md Phase 4` |
| **涉及文件** | 新增 `domain/error_envelope.py`；修改 `engine/subgraphs/understanding_subgraph.py`（`_h_hard_guard`、`_h_slot_extractor`） |
| **验收** | error_code 统一出口；EarlyResponseDirective 不绕过后续校验 |

### 4d：hard_guard / slot_extractor / active_turn_resolver 边界收紧

| 项目 | 内容 |
|---|---|
| **引用** | `todo/first_layer/03_first_layer_solution_plan.md Phase 4` |
| **涉及文件** | `engine/subgraphs/intake_guard_router.py`、`engine/subgraphs/understanding_subgraph.py` |
| **约束** | `hard_guard` 只做 allow/deny，不做 `local_life` 路由权威；`slot_extractor` 不覆盖 `task_type` / `shop_id` / `preference` |
| **验收** | hard_guard 不决定路由去向；slot_extractor 不覆盖已有决议 |

### 4e：pending_clarification / clarification_request 收敛

| 项目 | 内容 |
|---|---|
| **引用** | `todo/first_layer/03_first_layer_solution_plan.md Phase 4（部分）` |
| **涉及文件** | `domain/schemas.py`（`PendingClarification` 规范化）、`engine/subgraphs/response_subgraph.py:375-419` |
| **验收** | 所有澄清路径使用同一 DTO，不再散落纯文本 + `pending_check_result` 字段 |

### 第 4 批验收总表

| 验收项 | 标准 |
|---|---|
| MixedIntent | 不会 terminal 掉 local_life |
| FocusContext | 替代散落字段的引用解析 |
| hard_guard | 只做 allow/deny，不做路由权威 |
| slot_extractor | 不覆盖 task_type / shop_id / preference |

---

## 第 5a 批：跨层职责收敛（架构）

> 目标是：三层职责不重叠——第一层不做实体解析、第二层负责 target_resolve/evidence/decision、第三层负责表达/验证/降级。
>
> **批次说明**：本批仅处理**架构收敛**（load_session 拆分 + target_resolve 搬迁 + planning_subgraph 收缩）。基础设施（Redis）和观测（Trace/Benchmark）拆分到后续 5b/5c 批，避免架构改动与基础设施替换互相干扰。
>
> ⚠️ **核心风险**：5a-a、5a-b、5a-c 三个步骤都修改 `understanding_subgraph → planning_subgraph` 核心管道。**必须按顺序串行执行，每步完成后运行全量回归才能进入下一步。** 不可并行。

### 5a-a：load_session 拆分（pure load + expand）

| 项目 | 内容 |
|---|---|
| **引用** | `todo/first_layer/03_first_layer_solution_plan.md Phase 5（A 项）` |
| **涉及文件** | `engine/subgraphs/understanding_subgraph.py`（拆分 `_h_load_session` → `_h_validate_session` + `_h_expand_session`） |
| **设计** | 当前 `_h_load_session` 同时做验证和字段展开。拆分为两阶段：<br>1. `_h_validate_session`：仅做输入合法性检查（空/超长/非法字符）<br>2. `_h_expand_session`：在确认合法后进行 session I/O 和 15+ 字段写入 |
| **验收** | 非法输入在 `_h_basic_validate` 即返回，省掉展开 I/O 和 15+ 字段写入 |
| **测试文件** | 新增 `tests/test_first_layer_session_split.py` |
| **回滚** | 合并回单一 `_h_load_session`，恢复旧行为 |

### 5a-b：target_resolve 权威归第二层

| 项目 | 内容 |
|---|---|
| **引用** | `todo/first_layer/03_first_layer_solution_plan.md Phase 5（F 项）` |
| **涉及文件** | `engine/subgraphs/understanding_subgraph.py`（`context_recovery` 缩窄）、`engine/subgraphs/planning_subgraph.py`（`_h_target_resolve` 升级） |
| **改法** | 第一层 `context_recovery` 只做引用识别（"这家/第一个"→ `FocusItem`），不做实体解析；移除 `resolved_target.status == "RESOLVED"` 短路逻辑 |
| **验收** | 第一层不做实体解析，只做引用/上下文；第二层负责全部 target_resolve/evidence/decision |
| **测试文件** | 扩展 `tests/test_first_layer_contextualization.py`（context_recovery 缩窄后行为验证） |
| **回滚** | 恢复 context_recovery 旧逻辑，恢复 `resolved_target.status` 短路 |

> **5a-b 门禁**：5a-a 全量回归通过后才能启动 5a-b。

### 5a-c：planning_subgraph 收缩

| 项目 | 内容 |
|---|---|
| **引用** | `todo/second_layer/09_second_layer_migration_plan.md Phase I` |
| **涉及文件** | `engine/subgraphs/planning_subgraph.py`（按职责提取为共享模块） |
| **设计** | 按职责提取共享模块，每个模块保持函数签名兼容：<br>- `goal_planner` → 共享 `GoalPlanner` service<br>- `target_resolve` → 共享 `TargetResolver` service<br>- `evidence_planner` → 共享 `EvidencePlanner` service<br>- `plan_validator` → 共享 `PlanValidator` service<br>`planning_subgraph` 保留为旧 workflow 的 dispatch 兼容层 |
| **验收** | planning_subgraph 不再承载 discovery_decision 的默认调度逻辑；所有新 workflow 直接调用共享模块 |
| **测试文件** | 新增/扩展 `tests/test_goal_planner.py`、`tests/test_evidence_planner.py`、`tests/test_execution_plan_validator.py`（提取后行为一致） |
| **回滚** | 保留 planning_subgraph 入口，新 workflow 切回旧 dispatch |

> **5a-c 门禁**：5a-b 全量回归通过后才能启动 5a-c。

### 第 5a 批验收总表

| 验收项 | 标准 | 验证方式 |
|---|---|---|
| load_session 拆分 | 非法输入早返回，省 I/O | session 拆分单测 |
| context_recovery 缩窄 | 只做引用识别，不做实体解析 | context 单测 |
| target_resolve 归第二层 | 第一层无实体解析; 第二层全权负责 | 跨层集成测试 |
| planning_subgraph 收缩 | 仅做 dispatch，逻辑委托共享模块 | 模块提取验证 |
| **回归** | **已有单店/推荐/对比/澄清 query 不退化** | `pytest local_life_agent/tests -q` |

---

## 第 5b 批：SessionStore 基础设施升级

> 目标是：从 InMemorySessionStore 升级为可配置的 Redis 实现，分区 TTL 按场景差异化。
>
> **批次说明**：本批与 5a 批**无代码依赖**。但如果 5a 批改了 `understanding_subgraph.py` 的 session 读写路径，5b 批的 Redis 实现需要与之对齐。建议 5a 批验收通过后再启动本批。

### 5b-a：SessionStore 接口抽象 + InMemorySessionStore 重构

| 项目 | 内容 |
|---|---|
| **引用** | `todo/first_layer/03_first_layer_solution_plan.md Phase 5.5` |
| **涉及文件** | 新增 `infrastructure/session/session_store.py`（抽象接口）<br>重构 `infrastructure/session/in_memory_session_store.py`（实现接口） |
| **设计** | `SessionStore` 抽象接口：`load(session_id) → SessionState`、`save(session_id, state)`、`delete(session_id)`、`partition_ttl(partition) → int`。现有所有 session 读写调用改为通过接口。 |
| **验收** | 现有 InMemorySessionStore 实现接口；所有 session 消费方通过接口访问而非直接 new |
| **回滚** | 删除接口文件，恢复直接调用旧 InMemorySessionStore |

### 5b-b：分区 TTL 实现

| 项目 | 内容 |
|---|---|
| **设计** | 分 7 个分区，TTL 策略：conversation_context=30min、focus_context=30min、recommendation_context=10min、comparison_context=10min、pending_clarification=5min、user_preference_summary=24h、execution_counters=5min |
| **涉及文件** | `infrastructure/session/session_store.py`（分区枚举 + TTL 配置表）<br>`domain/state.py`（SessionState 字段映射到分区） |
| **验收** | 分区枚举可配置；TTL 策略可通过 config 覆写；无分区字段映射到默认分区 |
| **测试文件** | 扩展 `tests/test_p12_deadline_budget_freshness_ttl.py`（分区 TTL 验证） |
| **回滚** | 移除分区逻辑，回退到统一 TTL |

### 5b-c：RedisSessionStore 实现

| 项目 | 内容 |
|---|---|
| **引用** | `todo/first_layer/03_first_layer_solution_plan.md Phase 5.5` |
| **涉及文件** | 新增 `infrastructure/session/redis_session_store.py` |
| **设计** | Redis 实现，每个分区不同 key prefix + TTL。连接池配置通过 `config.py` 注入。序列化使用已有的 JSON serializer。 |
| **验收** | 可配置实现（env/config 控制 Redis host/port/db）；分区 TTL 正确生效；Redis 不可用时 fallback 到 InMemory |
| **测试文件** | 新增 `tests/test_infrastructure_redis_session_store.py`（mock Redis） |
| **回滚** | 切换回 InMemorySessionStore，Redis 实现保留但不激活 |

> **5b-c 门禁**：RedisSessionStore 先在单测中用 mock Redis 验证，再切一个 staging session 做集成测试。不直接切 production 流量。

### 第 5b 批验收总表

| 验收项 | 标准 | 验证方式 |
|---|---|---|
| 接口抽象 | 所有 session 读写走接口 | 代码审计 |
| 分区 TTL | 7 个分区，TTL 按场景差异化 | 分区单测 |
| Redis 实现 | 可用、可回退、可配置 | mock Redis 单测 |
| **回归** | **已有 session 读写路径不退化** | `pytest local_life_agent/tests -q` |

---

## 第 5c 批：Trace + Eval + ResponseContract V2

> 目标是：三层 trace 统一；性能/成本基准建立；ResponseContract V2 成为唯一权威出口。
>
> **批次说明**：本批在架构收敛（5a）和基础设施（5b）之后，依赖前三层工作流程稳定。

### 5c-a：Trace schema 三层统一

| 项目 | 内容 |
|---|---|
| **引用** | `todo/third_layer/10_third_layer_migration_plan.md Phase J`<br>`todo/third_layer/12_third_layer_file_change_plan.md Phase J` |
| **涉及文件** | `observability/trace.py`（扩展 `TurnTrace` 为 8 个阶段级 span） |
| **设计** | 8 个阶段级 span：`intake_span` → `routing_span` → `understanding_span` → `planning_span` → `execution_span` → `evidence_span` → `decision_span` → `response_span`。每个 span 包含：`stage`、`decision`、`latency_ms`、`llm_called`、`input_snapshot` |
| **验收** | trace 串起 intake → routing → evidence → decision → response；每个阶段有独立 span 和耗时拆分 |
| **测试文件** | 新增 `tests/test_first_layer_trace.py`、`tests/test_second_layer_trace_contract.py`、`tests/test_third_layer_trace_contract.py` |
| **回滚** | 保留旧 TurnTrace，新 span 可独立移除 |

### 5c-b：Eval / latency / cost benchmark

| 项目 | 内容 |
|---|---|
| **引用** | `todo/second_layer/09_second_layer_migration_plan.md Phase J`<br>`todo/third_layer/11_third_layer_test_plan.md` |
| **涉及文件** | 新增 `tests/test_second_layer_latency_budget.py`、`tests/test_second_layer_cost_benchmark.py`<br>新增 `tests/test_third_layer_latency_budget.py` |
| **覆盖场景** | simple fact query p95 ≤ 2000ms（含工具调用）<br>recommendation p95 ≤ 8000ms<br>comparison p95 ≤ 10000ms<br>LLM 调用次数：single_shop_fact 0~1, recommendation 1~3, comparison 2~4 |
| **验收** | 简单 fact query 延迟不显著慢于基线；复杂 query 不丢失工具结果；LLM 调用次数不增加 |
| **回滚** | 测试文件可独立删除，不影响业务代码 |

### 5c-c：ResponseContract V2 唯一权威出口

| 项目 | 内容 |
|---|---|
| **引用** | `todo/third_layer/10_third_layer_migration_plan.md Phase K`<br>`todo/third_layer/12_third_layer_file_change_plan.md Phase K` |
| **涉及文件** | `answer/response_contract.py`（V1 → V2 增强）、`answer/final_response_builder.py`、`app.py:194-226` |
| **设计** | V2 = V1 + `claims` / `citations` / `cards` / `confidence_band` / `response_policy` / `clarification` / `safety_notice` |
| **验收** | `ResponseContract V2` 标记旧字段 deprecated（`final_response`、`preview_text`、`answer_source`）；所有消费方从 V2 派生而非直接读旧字段 |
| **测试文件** | 扩展 `tests/test_third_layer_response_contract.py`（V2 全字段） |
| **回滚** | 保留 V2 定义，消费方退回到 V1 字段 |

### 第 5c 批验收总表

| 验收项 | 标准 | 验证方式 |
|---|---|---|
| trace | 串起 intake → routing → evidence → decision → response | trace 合约测试 |
| latency benchmark | simple fact ≤ 2000ms, recommendation ≤ 8000ms | benchmark 测试 |
| cost benchmark | LLM 调用次数不增加 | benchmark 测试 |
| ResponseContract V2 | 标记旧字段 deprecated；消费方从 V2 派生 | 合约测试 |
| **回归** | **已有全部测试通过** | `pytest local_life_agent/tests -q` |

---

## 第 6 批：复杂能力 + ClaimVerifier L2/L3 + 全量验收

> 硬约束：`complex_orchestrator` 不能作为不确定 query 的兜底入口。只有 `TaskComplexity=super_complex` 时才进入。
>
> **批次说明**：本批三个子系统（complex_orchestrator / ClaimVerifier 升级 / 全量回归）之间无依赖，可并行开发但应各自独立验证后再合入。

### 6a：complex_orchestrator_workflow

| 项目 | 内容 |
|---|---|
| **引用** | `todo/second_layer/09_second_layer_migration_plan.md Phase H` |
| **涉及文件** | 新增 `engine/workflows/complex_orchestrator_workflow.py`；修改 `engine/workflow_registry.py`、`engine/_routes.py` |
| **入口约束** | 只有 `TaskComplexity=super_complex` 才能进入 |
| **验收** | 复杂多阶段 query 能正确拆分子任务并合并结果；普通 query 不错误进入 |
| **测试文件** | 新增 `tests/test_second_layer_complex_orchestrator.py` |
| **回滚** | Router 中屏蔽 `complex_orchestrator` 路由分支 |

### 6b：SubTaskDAG + WorkerResult + EvidenceReducer + DecisionReducer

| 项目 | 内容 |
|---|---|
| **引用** | `todo/second_layer/09_second_layer_migration_plan.md Phase H` |
| **涉及文件** | 新增 `planning/orchestrator/sub_task_dag.py`、`planning/orchestrator/worker_result.py`、`planning/orchestrator/evidence_reducer.py`、`planning/orchestrator/decision_reducer.py`、`planning/orchestrator/conflict_resolver.py` |
| **验收** | DAG 正确执行拓扑排序；reducer 正确合并证据；conflict resolver 处理矛盾证据 |
| **测试文件** | 新增 `tests/test_second_layer_map_reduce_reducer.py`、`tests/test_second_layer_conflict_resolver.py`、`tests/test_second_layer_worker_state_isolation.py` |
| **回滚** | 删除新增文件，超复杂 query 仍走旧 planning_subgraph |

> **6a+6b 增量验证策略**：
> 1. 先实现 SubTaskDAG 拓扑排序 → 独立单测通过
> 2. 再实现 WorkerResult + EvidenceReducer → reduce 单测通过
> 3. 再实现 ConflictResolver → 冲突裁决单测通过
> 4. 最后组装 complex_orchestrator_workflow → 端到端测试通过

### 6c：ClaimVerifier Level 2/3

| 项目 | 内容 |
|---|---|
| **引用** | `todo/third_layer/03_third_layer_target_architecture.md §模块3（三级落地表）`<br>`todo/third_layer/12_third_layer_file_change_plan.md Phase G（补充说明）` |
| **涉及文件** | `answer/claim_extractor.py`（L2: composer 文本 span 回填；L3: LLM structured extraction）、`answer/claim_verifier.py` |
| **验收** | L2 正确标注 composer 输出中的 claim span；L3 对 LLM verbalizer 输出正确抽取 claim 并对齐 EvidencePack |
| **测试文件** | 扩展已有 claim_verifier 测试（添加 L2/L3 场景） |
| **回滚** | 保留 L1 实现，L2/L3 可独立移除 |

### 6d：全量回归 + 测试文件检查 + 线上指标准备

| 项目 | 内容 |
|---|---|
| **引用** | `todo/second_layer/09_second_layer_migration_plan.md Phase J`<br>`todo/first_layer/03_first_layer_solution_plan.md §推荐落地顺序 7` |
| **涉及** | `pytest local_life_agent/tests -q`、端到端回归、latency/cost benchmark、trace 合约测试 |
| **测试文件清单（终验）** | 确认以下测试文件已创建且通过：<br>**第一层**：`test_first_layer_contextualization.py`、`test_first_layer_focus_context.py`、`test_first_layer_contracts.py`、`test_first_layer_trace.py`、`test_first_layer_session_split.py`<br>**第二层**：`test_second_layer_workflow_routing.py`、`test_second_layer_single_shop_fact_workflow.py`、`test_second_layer_review_policy.py`、`test_second_layer_ranking_policy.py`、`test_second_layer_expand_search_policy.py`、`test_second_layer_execution_budget.py`、`test_second_layer_stage_executor.py`、`test_second_layer_tool_result_cache.py`、`test_second_layer_complex_orchestrator.py`、`test_second_layer_map_reduce_reducer.py`、`test_second_layer_conflict_resolver.py`、`test_second_layer_worker_state_isolation.py`、`test_second_layer_trace_contract.py`、`test_second_layer_latency_budget.py`、`test_second_layer_cost_benchmark.py`、`test_second_layer_exploration_workflow.py`<br>**第三层**：`test_third_layer_response_mode_enum.py`、`test_third_layer_response_contract.py`、`test_third_layer_verifier_no_empty_pass.py`、`test_third_layer_llm_disabled_fallback.py`、`test_third_layer_claim_extractor.py`、`test_third_layer_claim_verifier_coupon.py`、`test_third_layer_claim_verifier_open_status.py`、`test_third_layer_claim_verifier_distance.py`、`test_third_layer_claim_verifier_recommendation.py`、`test_third_layer_claim_verifier_comparison.py`、`test_third_layer_rewrite_instruction.py`、`test_third_layer_deterministic_composers.py`、`test_third_layer_workflow_boundary.py`、`test_third_layer_trace_contract.py`、`test_third_layer_latency_budget.py` |
| **验收** | 所有测试通过；benchmark 不超过基线 +20%；上面清单中的测试文件全部存在 |

---

## 附录 A：三层 Phase 对照索引

> 批号已按 2026-07 版本调整：第 1 批→1A/1B/1C/1D 四个子批次；第 2a 批→2a-A/B/C/D 四个子批次；旧 2b→4p（第 4 批前置）。

| 统一批 | 步骤 | first_layer | second_layer | third_layer |
|---|---|---|---|---|
| 0 | a/b/c | Phase 1 | Phase A | Phase A |
| 1A | a | — | — | Phase B（ResponseMode Enum） |
| 1A | b | — | — | Phase D（verify_empty_evidence） |
| 1A | c | — | — | ResponseDirective（新增） |
| 1B | a | — | — | Phase I（minimal—4 deterministic composers） |
| 1B | b | — | — | Phase E（LLMDisabled fallback） |
| 1B | c | — | — | Phase F（RewriteInstruction struct） |
| 1C | a | — | — | Phase H（收敛绕过修复） |
| 1C | b | — | Phase B（minimal—ReviewPolicy） | — |
| 1C | c | — | Phase C（single_shop_fact workflow） | — |
| 1C | d | — | Phase D（discovery_decision 拆分+路由） | — |
| 1D | a | — | Phase B（完整—RingPolicy + RankingRing） | — |
| 1D | b | — | Phase E（ExecutionBudget + expanded_search） | — |
| 1D | c | — | Phase E 续（Search/expand/rerank 策略） | — |
| 2a-A | a | — | Phase G（exploration 完整） | — |
| 2a-A | b | — | Phase G 续（exploration 策略） | — |
| 2a-B | a | — | Phase F（ToolResultCache） | — |
| 2a-B | b | — | Phase F 续（cache 策略+TTL） | — |
| 2a-C | a | — | Phase E（StageToolExecutor 完整） | — |
| 2a-C | b | — | Phase E 续（execution 策略+budget） | — |
| 2a-D | a | — | — | Phase C（ResponseContract V1） |
| 2a-D | b | — | — | Phase C 续（contract 消费方适配） |
| 3 | a | — | — | Phase F（RewriteInstruction 集成） |
| 3 | b | — | — | Phase I（完整—7 个 composer） |
| 3 | c | — | — | Phase G（L1—ClaimExtractor） |
| 3 | d | — | Phase D（完整—workflow 拆分） | — |
| 3 | e | — | Phase F（扩展—winner 约束） | — |
| 3 | f | — | Phase G（exploration 升级） | — |
| 4p | a | Phase 2（ContextualizedTurn V0） | — | — |
| 4p | b | Phase 3（FocusContext V0） | — | — |
| 4p | c | Phase 4（FreshnessMeta + LocationContext） | — | — |
| 4 | a/b | Phase 2+3（V1） | — | — |
| 4 | c/d/e | Phase 4（V1） | — | — |
| 5a | a | Phase 5（部分—load_session 拆分） | — | — |
| 5a | b | Phase 5（部分—context_recovery 缩窄） | Phase I（部分—target_resolve） | — |
| 5a | c | — | Phase I（planning_subgraph 收缩） | — |
| 5b | a/b/c | Phase 5.5（SessionStore） | — | — |
| 5c | a | — | — | Phase J（trace 三层） |
| 5c | b | 验收 | Phase J（benchmark） | Phase J（benchmark） |
| 5c | c | — | — | Phase K（ResponseContract V2） |
| 6 | a/b | — | Phase H（complex orchestrator） | — |
| 6 | c | — | — | Phase G（L2/L3—ClaimVerifier） |
| 6 | d | 验收 | Phase J | 验收 |

## 附录 B：关键约束清单

| # | 约束 | 适用范围 | 违反后果 |
|---|---|---|---|
| 1 | `final_response` 权威写入点只有 1 个；旧字段兼容赋值只能由统一出口派生 | 第 1 批起 | bypass 路径成为永久后门 |
| 2 | `complex_orchestrator` 不能作为不确定 query 的兜底入口，只有 `TaskComplexity=super_complex` 才能进入 | 第 6 批 | 普通 query 被错误路由导致延迟爆炸 |
| 3 | `REJECT` 与 `DIRECT` 保持独立枚举 | 第 1 批 | 安全拒答和普通回答无法区分 |
| 4 | `COMPARISON` 与 `ANSWER` 保持独立枚举 | 第 1 批 | comparison 的 winner/trade-off 约束丢失 |
| 5 | `hard_guard` 只做 allow/deny，不做 `local_life` 路由权威 | 第 4 批 | 路由决策分散，无法集中审计 |
| 6 | 第一层不做实体解析，只做引用/上下文 | 第 5 批 | target_resolve 跨层重叠无限期存在 |
| 7 | ClaimExtractor 分三级落地，不要求一次完成全部 | 第 3-6 批 | 中文 claim 抽取准确率不足导致验证失败 |
| 8 | `Winner` 必须来自 `comparison_matrix` / `DecisionPlan` 而非 LLM | 第 3 批 | 对比回答的 winner 不锚定证据 |

---

## 附录 C：批级回滚策略

> 每批实施时，如果某步验收不通过，按如下策略回退——**优先回退单步，而非整批回退**。

| 批 | 步 | 回退策略 | 影响范围 |
|---|---|---|---|---|
| 1A | a (ResponseMode Enum) | 撤销 Enum 定义，恢复字符串比较代码 | 仅 Enum 消费方 |
| 1A | b (verify_empty_evidence) | 恢复旧 `verify_result = "pass"` 逻辑 | response_subgraph + verifier |
| 1A | c (ResponseDirective + SafeResponse) | 删新增文件，恢复旧 final_response 直接写入 | 回答路径 |
| 1B | a (4 个 deterministic composer) | 删 composer 文件，恢复旧 keyword composer | LLM fallback 路径 |
| 1B | b (LLMDisabled fallback) | 恢复旧占位符逻辑 | generator + llm_verbalizer |
| 1B | c (RewriteInstruction 结构) | 删新增文件，恢复旧 rewrite 计数逻辑 | rewrite 循环 |
| 1C | a (收敛绕过修复) | 恢复 workflow 旧 `_build_success_patch` | 4 个 workflow + response_subgraph |
| 1C | b (ReviewPolicy minimal) | 删新增文件，保留旧 BudgetContext | planning 策略 |
| 1C | c (single_shop_fact workflow) | registry 切回 `deterministic_tool` | workflow 路由 |
| 1C | d (discovery_decision 路由拆分) | 合并回旧路由判定 | workflow 路由 |
| 1D | a (FullPolicy + RankingRing) | 撤销新增策略代码 | 策略 + 排序模块 |
| 1D | b (ExecutionBudget) | 恢复旧固定 budget 逻辑 | planning 预算 |
| 1D | c (Search/expand/rerank 策略) | 恢复旧 `filters = {}` 清空逻辑 | planning_subgraph |
| 2a-A | a (exploration 完整) | 切回旧 exploration_planning 实现 | exploration 路径 |
| 2a-A | b (exploration 策略) | 撤销新增策略代码 | 策略模块 |
| 2a-B | a (ToolResultCache) | 删缓存文件，恢复直接工具调用 | 工具执行 |
| 2a-B | b (cache 策略+TTL) | 保留 cache 基础设施，策略可独立撤销 | 缓存策略 |
| 2a-C | a (StageToolExecutor 完整) | 切回 BatchToolExecutor 平铺并发 | execution_review_subgraph |
| 2a-C | b (execution 策略+budget) | 恢复旧 stage 固定调度策略 | execution 策略 |
| 2a-D | a (ResponseContract V1) | 消费方退回到 ResponseDirective 读取 | 回答契约 |
| 2a-D | b (contract 消费方适配) | 逐步恢复旧字段读取路径 | 回答路径 |
| 3 | a (RewriteInstruction 集成) | `_h_rewrite` 切回裸计数 | rewrite 循环 |
| 3 | b (完整 composer) | 删新增 composer，保留 1B-a 的 4 个 | composer 路径 |
| 3 | c (ClaimExtractor L1) | 删新增文件，恢复旧 keyword verifier | verifier |
| 3 | d (workflow 拆分) | `_route_workflow_runner` 切回旧三重判定 | workflow 路由 |
| 3 | e (winner 约束) | 保留旧 ComparisonMatrix，新约束可撤 | 对比决策 |
| 3 | f (exploration 升级) | 切回旧 exploration_planning 实现 | exploration workflow |
| 4p | a (ContextualizedTurn V0) | 删新增 trace 文件 | 仅影响 trace |
| 4p | b (FocusContext V0) | 删新增 trace 文件 | 仅影响 trace |
| 4p | c (FreshnessMeta+LocationContext) | 删新增 DTO 文件 | 仅 DTO 定义 |
| 4 | a→e (第一层 V1) | 逐个撤销 V1 消费接入，4p trace 文件保留 | 第一层理解 |
| 5a | a (load_session 拆分) | 合并回单一 `_h_load_session` | session 加载 |
| 5a | b (target_resolve) | 恢复 context_recovery 旧逻辑 + 短路 | 实体解析 |
| 5a | c (planning_subgraph) | 保留旧 dispatch 兼容层，新 workflow 切回 | planning 模块 |
| 5b | a/b/c (SessionStore) | 切回 InMemorySessionStore | 全部 session 读写 |
| 5c | a (trace 三层) | 保留旧 TurnTrace，新 span 可独立移除 | 观测层 |
| 5c | b (benchmark) | 删测试文件，不影响业务代码 | 测试 |
| 5c | c (ResponseContract V2) | 消费方退回到 V1 字段 | 回答契约 |
| 6 | a/b (complex orchestrator) | Router 屏蔽 `complex_orchestrator` 分支 | 路由 |
| 6 | c (ClaimVerifier L2/L3) | 保留 L1 实现，L2/L3 独立移除 | verifier |
| 6 | d (终验) | 不通过时清单中对应文件逐个修复 | 全部 |
