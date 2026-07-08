# 第三层渐进式迁移计划

> ℹ️ **合并说明**：本文件已从旧的 09_third_layer_migration_plan.md 中合并 Phase H（收敛 workflow 边界）和 Phase I（trace/eval/latency 统一验收）。旧文件已删除。本文件为迁移计划权威版本。

本文件只描述迁移路线，不修改业务代码。

> ⚠️ **优先级重排说明**：原有 Phase 顺序将"ResponseContract 成为唯一权威出口"（旧 Phase G）置于"收敛 workflow bypass final_response"（旧 Phase H）之前——这是错误的。只要 workflow 还能直接写 `final_response`，加再多 ResponseContract/ClaimVerifier 也无法保证覆盖所有回答路径。
>
> 重新排序后的核心原则：
> 1. **先堵 bypass 再搭合同**：收敛 workflow 边界放在 Phase H（而非 Phase G 之后）
> 2. **先修已知缺陷再建新能力**：修 verify 空 evidence pass 和 LLM disabled fallback 在 ClaimExtractor 之前
> 3. **先枚举再扩展**：ResponseMode Enum 在 ResponseContract 之前
> 4. **先最小后增强**：ResponseContract 从 V1（最小字段集）开始，逐步增强
> 5. **ClaimExtractor 分三级落地**：不要求一次性完成"任意自然语言→完美 claim 抽取"

## Phase A：事实冻结与边界测试

### 目标

- 固化真实回答链
- 固化 response_mode 分支
- 固化 verifier / rewrite / fallback 的现状

### 要冻结的事实

- `response_subgraph` 是第三层主入口
- `generate_answer()` 仍是 LLM verbalizer 主导
- `build_final_response()` 不是当前主出口

## Phase B：统一 ResponseMode Enum

### 目标

- 将散落字符串值统一为枚举，明确语义

### 关键设计决策

- `REJECT` 与 `DIRECT` 保持独立枚举（`reject` 是安全拒答，非普通直接回答）
- `COMPARISON` 与 `ANSWER` 保持独立（comparison 有 `ComparisonMatrix`/`winner`/`trade-off` 约束）
- `TOOL_ANSWER` 保留为独立值（确定性工具回答路径）
- 旧字符串值通过 `str, Enum` 的 alias 映射兼容

### 相关文件

- 见 `12_third_layer_file_change_plan.md` Phase C（文件级实施），以及 `04_third_layer_contract_design.md` 第 2 节

## Phase C：引入 ResponseContract V1（最小兼容版本）

### 目标

- 不一次性引入全部字段，采用 V1 最小版本
- `ResponseContract` V1 只包含 6 个核心字段：`answer_text`、`answer_type`、`response_mode`、`trace_id`、`verifier_result`、`fallback_reason`、`uncertainty_notices`
- 后续增强字段（`claims`、`citations`、`cards`、`confidence_band`、`response_policy`）在 Phase K 再添加
- 所有路径（pass-through/clarify/fallback/answer）都输出 `ResponseContract`

## Phase D：修 verify 空 evidence / 空 draft pass

### 目标

- **P0 风险修复**：`response_subgraph.py:290-298` 中，当 `evidence` 为空或 `draft_response` 为空时，verifier 直接返回 `verify_result="pass"`——这意味着空回答或零证据回答直接进入 `final_response`
- 改为：空 evidence 或空 draft 时标记 `unverifiable`，要求至少走 `_h_fallback_answer` 给出有意义兜底，不能直接 pass

## Phase E：LLM disabled 时提供有意义 fallback

### 目标

- **P0 风险修复**：`generator.py:664-670` 在 `config.ENABLE_LLM_VERBALIZER == False` 时返回固定占位符 `"【LLM 服务未启用】无法生成自然语言回答。"`
- 改为：根据 `AnswerPlan` / `EvidencePack` 走 deterministic composer 输出有意义回答，而不是硬编码占位符

## Phase F：引入 RewriteInstruction

### 目标

- 将 `_h_rewrite` 从 `rewrite_count += 1` 升级为结构化 `RewriteInstruction`
- 让 rewrite 能精确修复特定 claim，而非整体重生成

## Phase G：引入 ClaimExtractor + ClaimVerifier（分三级落地）

### 目标

- 从文本走向 claim 对齐
- 把 verifier 从纯文本规则逐步升级为 claim-based verification

### ClaimExtractor 三级落地策略

> **难度说明**：本地生活中文回答中混有事实 claim（"有 3 张优惠券"）、偏好 claim（"更适合约会"）、排序 claim（"A 比 B 好"）、unknown notice（"券的信息我没查到"）、trade-off claim（"A 评分高但 B 距离近"）等多种类型，无法通过简单正则一次覆盖。因此分三级实施：

| 级别 | 策略 | 覆盖范围 | 前置依赖 |
|---|---|---|---|
| **Level 1** | 从 `AnswerPlan` / `DecisionPlan` 的 `allowed_claims` / `required_claims` 直接生成 `expected claims` | 单店事实 claim（coupon/open_status/distance/rating/price） | Phase F（RewriteInstruction） |
| **Level 2** | 从 deterministic composer 输出的文本中回填 claim span（位置标注） | 单店 + 推荐排序 claim | Phase I（多类型 composer） |
| **Level 3** | 对 LLM verbalizer 输出使用 LLM structured extraction，再由 deterministic verifier 对齐 EvidencePack | 全部类型（comparison/exploration/LLM generated） | Phase C（ResponseContract V1）+ Phase K（增强版） |

- Level 1 在 Phase G 启动时就绪
- Level 2 在 Phase I 之后
- Level 3 在 Phase K 之前

## Phase H：收敛 workflow bypass final_response（⚠️ 重要 — P0 第一优先级）

### 核心原则

> 此 Phase 必须在 Phase G（最终收敛）之前完成。因为只要独立 workflow 还能直接写 `final_response`，加再多 ResponseContract / ClaimVerifier 都无法保证覆盖所有回答路径。这是第一批优先实施的能力。

### 背景

当前 `final_response` 从 8 个位置写入（P0-2），独立 workflow 绕过统一 verifier（P0-8）。

### 具体任务

1. `deterministic_tool_workflow.py:933` 的 `_build_success_patch()` 不再直接写 `final_response`，改为写 `answer_plan` + `evidence_pack` -> 走统一管线
2. `exploration_planning_workflow.py:824` 的 `_build_success_patch()` 同上
3. `direct_response_workflow.py:159` 的 `final_response` 写入改为写 `direct_response_payload` + 走统一 `ResponseContract`
4. `clarification_fallback_workflow.py:233` 同上
5. `response_subgraph.py:382-418` 的 `_h_clarify_response` 输出统一为 `ResponseContract` 中的 clarification 字段
6. `response_subgraph.py:422-491` 的 `_h_fallback_answer` 输出统一为 `ResponseContract` 中的 fallback 结构
7. 所有 bypass 路径写 `response_route` = `"bypass"` 信号，确保 trace 可识别

### 验收标准

- `final_response` 只有 1 个写入位置：`_h_final_response`（`response_subgraph.py:348`）
- 所有 bypass 路径的 `response_route` 被 trace 正确记录
- 回归测试全量通过

## Phase I：多类型 DeterministicComposer

### 目标

- 从单一单店 composer 扩展到 6 类 composer（单店/推荐/对比/探索/澄清/兜底）
- 减少对 LLM verbalizer 的依赖，确定性回答路径优先

## Phase J：统一 trace / eval / latency

### 目标

- 把生成、验证、重写、降级、预览、最终输出纳入统一 trace
- 第三层 trace 从 1 个粗粒度 span 拆分为 8 个阶段级 span
- 每个 span 捕获 14 个字段
- preview 层从纯文本过滤升级为结构化 `PreviewPolicyResult`
- 新增 35 个 test case（详见 11_test_plan）
- 新增 5 个 benchmark 场景

### 验收标准

- trace 能解释每个阶段的耗时和决策原因
- preview 层结构化输出已验证
- 所有新增 test case 在 CI 中运行通过
- benchmark 不超过当前基线 +20%

## Phase K：最终收敛（ResponseContract 增强版）

### 目标

- `ResponseContract` 从 V1 最小版本升级为增强版（增加 `claims`、`citations`、`cards`、`confidence_band`、`response_policy`）
- `ResponseContract` 成为唯一权威出口
- `build_final_response()` 要么升级为权威 helper，要么仅保留兼容层
- 所有回答路径（pass-through/clarify/fallback/answer）统一输出 `ResponseContract`
- 旧字段（`final_response`、`preview_text`、`answer_source`）标记 deprecated，仍写但不再消费

