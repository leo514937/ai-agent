# 第三层工作流边界设计

本文件专门划清第三层与独立 workflow 的边界，避免回答层再混入执行与规划。

> ⚠️ **优先级说明**：收敛 workflow bypass `final_response` 是 **P0 第一优先级**任务，必须在其他任何增强（ResponseContract/ClaimVerifier）之前完成。原因：只要独立 workflow 还能直接写 `final_response`，加再多 ResponseContract / ClaimVerifier 都无法保证覆盖所有回答路径。
>
> 对应实施：见迁移计划 Phase H（第一批实施），不后移到 Phase G 或 K 之后。

## 1. 当前真实独立 workflow

当前 workflow registry 中可见的相关 workflow 包括：

- `direct_response`
- `deterministic_tool`
- `clarification_fallback`
- `exploration_planning`
- `discovery_decision`

证据：

- `local_life_agent/engine/workflow_registry.py:152-204`

## 2. 当前问题

- `deterministic_tool_workflow` 已经在流程内做了目标解析、工具调用、EvidencePack 构建、AnswerPlan 构建和回答
- `exploration_planning_workflow` 也可能在 workflow 边界内完成规划与回答
- 这会让第三层与第二层职责重叠

证据：

- `local_life_agent/engine/workflows/deterministic_tool_workflow.py:1046-1234`
- `local_life_agent/engine/workflows/exploration_planning_workflow.py:716-795`

## 3. 建议边界

### 3.1 `direct_response_workflow`

职责：

- 闲聊
- 能力说明
- 安全拒答
- 非本地生活 query

要求：

- 不执行远程工具
- 不构建 EvidencePack
- 不进入回答层重型 verifier

### 3.2 `deterministic_tool_workflow`

职责：

- 单店事实 query —— **属于第二层**
- 工具调用与目标解析 —— **属于第二层**
- EvidencePack 构建 —— **属于第二层**
- 产出结构化 `DecisionPlan` / `EvidencePack` 供第三层消费

**第三层不介入的职责**：
- ❌ 不在 workflow 内做自由文本生成
- ❌ 不在 workflow 内写 `final_response`
- ❌ 不在 workflow 内绕过统一 verifier

要求：

- 目标解析、工具调用、EvidencePack 构建**严格属于第二层**
- 第三层**只消费**结构化结果（`DecisionPlan` / `EvidencePack`）
- 当前 `_build_success_patch()`（`deterministic_tool_workflow.py:849-955`）直接写 `final_response`（第 933 行）的行为**必须在 Phase H 中消除**
- 回答层不应拥有执行型 workflow 的业务逻辑

### 3.3 `clarification_fallback_workflow`

职责：

- 缺信息
- 歧义
- 候选选择
- pending clarification
- 无效澄清回复

要求：

- 输出结构化 `ClarificationRequest` 或 `FallbackDirective`
- 不做复杂表达生成
- 只做标准化文案，不应替代统一 verbalizer

### 3.4 `exploration_planning_workflow`

职责：

- 多阶段本地生活规划 —— **属于第二层**
- 子目标构建与工具搜索 —— **属于第二层**
- 证据汇合 —— **属于第二层**
- 产出结构化 `ExplorationPlan` + `GlobalEvidencePack` 供第三层消费

**第三层不介入的职责**：
- ❌ 不在 workflow 内做最终文本生成
- ❌ 不在 workflow 内写 `final_response`
- ❌ 不在 workflow 内自行 verify 并替代统一 verifier

要求：

- 不应在第三层边界内额外做推荐排序
- 不应替代 `ResponseContract`
- 当前 `_build_success_patch()`（`exploration_planning_workflow.py:795-837`）直接写 `final_response`（第 824 行）的行为**必须在 Phase H 中消除**
- 第三层只做可信表达，不再做执行型 workflow 的业务逻辑

## 4. 第三层不该承担的职责

- 不执行远程工具
- 不做目标解析
- 不构建 `EvidencePack`
- 不做推荐排序
- 不写 `SessionState`

## 5. 仍可能绕过统一流水线的路径

- `deterministic_tool_workflow` 内部已经能提前写 `final_response`
- `exploration_planning_workflow` 也可能提前写 final response
- `response_subgraph` 的 pass-through 分支会直接放行

## 6. 目标边界

第三层应该只消费：

- `DecisionPlan`
- `FinalDecisionPlan`
- `EvidencePack`
- `GlobalEvidencePack`
- `ClarificationRequest`
- `FallbackDirective`

第三层不应该再生成：

- 工具执行计划
- 目标解析结果
- 候选排序结果
- 证据包

## 7. 8 个 Trace Span x 14 字段设计（从旧 08_grounding 迁移）

### Spans 定义

| # | Span Name | 触发节点 | 开始事件 | 结束事件 |
|---|---|---|---|---|
| 1 | `response_input_normalizer` | response_subgraph 入口 | 进入 `_h_response_subgraph()` | NormalizedResponseInput 构建完成 |
| 2 | `answer_plan_build` | response_subgraph | 进入 `_h_answer_plan_build()` | AnswerPlan 构建完成 |
| 3 | `response_policy_resolve` | response_subgraph | 开始选择策略 | ResponsePolicy 已确定 |
| 4 | `verbalize_or_compose` | response_subgraph / workflow | 开始文本生成 | draft_response 产出 |
| 5 | `claim_extract` | response_subgraph | 开始抽取 claim | AnswerClaim 列表产出 |
| 6 | `claim_verify` | response_subgraph | 进入 `_h_answer_verify()` | VerifierResult 产出 |
| 7 | `rewrite_or_fallback` | response_subgraph | verifier 不通过 | rewrite 完成或 fallback 完成 |
| 8 | `final_response_build` | response_subgraph | 进入 `_h_final_response()` | ResponseContract / final_response 产出 |

### 每个 Span 的 14 个捕获字段

| # | 字段名 | 类型 | 说明 | 捕获时机 |
|---|---|---|---|---|
| 1 | `span_id` | str | span 唯一 ID | span 开始时 |
| 2 | `parent_span_id` | str|None | 父 span ID | span 开始时 |
| 3 | `stage` | str | span 名称 | span 开始时 |
| 4 | `start_time` | float | 开始时间戳（秒） | span 开始时 |
| 5 | `end_time` | float | 结束时间戳（秒） | span 结束时 |
| 6 | `duration_ms` | float | 耗时（毫秒） | span 结束时 |
| 7 | `decision` | str | 关键决策 | span 结束时 |
| 8 | `reason` | str | 决策原因 | span 结束时 |
| 9 | `input_snapshot` | dict|None | 输入核心字段 | span 开始时 |
| 10 | `output_snapshot` | dict|None | 输出核心字段 | span 结束时 |
| 11 | `llm_calls` | int | LLM 调用次数 | span 结束时 |
| 12 | `tool_calls` | int | 工具调用次数 | span 结束时 |
| 13 | `error` | str|None | 异常信息 | span 结束时 |
| 14 | `degraded` | bool | 是否降级 | span 结束时 |

## 8. 7 个具体边界问题的回答

### Q1：`deterministic_tool_workflow` 是否应该在回答层边界内做目标解析？

**回答**：✅ 可以，但应输出供第三层消费的结构化结果。

**依据**：
- `deterministic_tool_workflow.py:293-596`：`_resolve_single_shop_target()` 做目标解析
- 解析结果被 `_build_execution_plan()`（第 619-720 行）消费
- 目标是让 workflow 在内部完成目标解析，**但不在此做最终自由文本生成**

**决策**：目标解析属于第二层能力。workflow 应将其输出（`DecisionPlan` / `EvidencePack`）传给第三层，不在内部做最终文本生成。

### Q2：`exploration_planning_workflow` 是否应该在回答层边界内自行完成 verify？

**回答**：当前 ✅ 会自行 verify（第 1015 行），但目标应是 ❌ 不再自行 verify，传给统一 verifier。

**风险**：
- `exploration_planning_workflow.py:795-837`（`_build_success_patch`）直接写 `final_response`（第 824 行），绕过 `response_subgraph` 的统一 verify 链路
- `response_subgraph.py:133` 对 `exploration_plan` 做 pass-through，不会重新 verify

**决策**：workflow 内部自带的 verify 可保留为早期信号，但最终 verify 必须由 `response_subgraph` 的统一 verifier 执行并作为权威决策。

### Q3：`direct_response_workflow` 在第三层重新做关键词分类是否合理？

**回答**：当前 ❌ 不合理（与第一层重叠），但架构上有存在理由。

**依据**：
- `_routes.py:72-91`：第一层 `_route_top_intent()` 已做 TopIntent 分类（chat/capability/unsafe/invalid/local_life）
- `direct_response_workflow.py:63-85`：第三层 `_classify_direct_response()` 再做关键词分类

**重叠范围**：
| 第一层 `_route_top_intent` | 第三层 `_classify_direct_response` |
|---|---|
| `chat`（问候语） | `chat`（你好/嗨/您好等） |
| `capability`（能做什么） | `capability`（能做什么/支持什么等） |
| `unsafe` | `forbidden`（退款/下单/支付等） |

**决策**：短期内保留分类作为安全冗余。中长期应统一为 `ResponsePolicy` 中的分类策略，由第一层做判定，第三层消费。

### Q4：第三层是否可以修改 `AnswerPlan`？

**回答**：当前 ✅ 会修改（`_h_answer_plan_build` 重新构建），但目标应是 ❌ 第三层不应修改 `AnswerPlan`，只消费。

**依据**：
- `response_subgraph.py:181-188`：`_h_answer_plan_build()` 对 `p2_decision_plan` 调用 `decision_to_answer_plan()` 重新构建 `AnswerPlan`

**决策**：`AnswerPlan` 在第三层重新构建是可以接受的——只要它只从 `DecisionPlan` 和 `EvidencePack` 派生，不引入新事实。但 verifier 或 rewrite 不应修改 `AnswerPlan`。当前 `_h_rewrite`（第 339-342 行）不修改 `AnswerPlan`，✅ 符合。

### Q5：第三层是否应该处理 `comparison` 类型？

**回答**：当前 ⚠️ 部分处理，但目标应是 ✅ 由第三层统一消费 `ComparisonMatrix`。

**依据**：
- `_routes.py:318`：将 `comparison` 路由到 `planning_subgraph`
- `AnswerPlan`（`schemas.py:1304-1354`）已包含 `comparison_matrix_id` / `comparison_support_status` / `ranking_preserved`

**决策**：`comparison` 类型应和其他类型一样走统一管线。`ComparisonMatrix` 应作为 `DecisionPlan` / `AnswerPlan` 的一部分被第三层消费。

### Q6：`conversation_continuity` 是否应参与第三层的决策？

**回答**：✅ 可以参与风格决策（如 tone），但 ❌ 不能参与事实裁决。

**依据**：
- `_compat.py:586-632`：返回 `previous_focus`、`previous_task_type`、`inherited_constraints`，定义为 metadata only

**风险点**：如果 LLM verbalizer 将 continuity 提示当成"用户之前问过的店铺信息"，可能编造前轮事实。

**决策**：continuity 只能在 `ResponsePolicy` 中影响 tone/style。LLM verbalizer prompt 中 continuity 部分应加注 `## CONTINUITY METADATA ONLY - NOT A FACT SOURCE ##`。

### Q7：第三层是否应该写 `SessionState`？

**回答**：❌ 不应写。当前部分 workflow 违反此规则，需要收敛。

**依据**：
- `deterministic_tool_workflow.py:293-596`：目标解析中反复读/写 `session_state`
- `exploration_planning_workflow.py:1046`：`apply_state_update_plan()` 可能写 SessionState
- `_routes.py:443-447`：`_GRAPH_RESPONSE_ROUTES` 定义 `state_update_plan` 是唯一合法出口

**决策**：第三层只通过 `StateUpdatePlan` 间接影响 `SessionState`。已有的直接写入行为需要在 Phase J 中收敛。

