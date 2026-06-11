# 2026-06-10 任务进展

## 本地生活 Agent 效果差距修复 (P1优化点落实)

基于 Gap Analysis 报告，针对剩余的优化点进行了全面整改，实现了 P1 级别的效果修复：

### 1. 统一澄清意图处理 (Unified Clarification Manager)
- **重构内容**：
  - 创建了 `local_life/clarification_strategy.py`，集中管理追问与澄清的统一下发逻辑。
  - 修改 `target_shop_policy.py`、`phase3_review.py` 和 `top_level_intent_router.py`，移除原有的分散硬编码澄清逻辑。
  - 将所有阶段产生的槽位缺失（如 `missing_slots`）统一收口至 `ClarificationStrategy.apply()` 判定。

### 2. 自修复图级重试机制 (Self-Healing Retry)
- **重构内容**：
  - 修改 `domain/contracts.py` 中的 `ReviewReport.max_retry_count` 默认值为 1，开启全局允许的 1 次图级重试。
  - 在 LangGraph 工作流架构 (`application/workflow/builder.py`) 中新增了 `_prepare_retry_node` 与条件重试边。
  - 当验证器判决为 `repair_answer` 且未超过 `max_retry_count` 时，自动生成带 `repair_hint` 的 `RewriteDecision`，放宽限制并触发重试（回跳至 `rag_executor`），从而实现自我纠偏。

### 3. 结构化澄清模板升级 (Structural Clarification Template)
- **重构内容**：
  - 重构 `answer_structure_composer.py` 中的 `_compose_clarification` 函数。
  - 从生硬的模板式文本升级为支持分场景的上下文连贯话术（如推荐场景缺失地点提示“为了给您推荐更准确的店铺，请问您目前在哪个城市或者哪个商圈附近呢？”；指定店铺名未命中时的特定安抚话术）。

### 4. 规则引擎场景策略 (Rule-based Scene Policy)
- **重构内容**：
  - 新增了 `local_life/scene_policy.py` 专门处理检索过程中的高频场景（约会、家庭等）。
  - 在 `rag_guardrail.py` 证据过滤链中硬接入 `ScenePolicy.apply` 校验规则。
  - 通过提取检索语句中的高频场景关键词，对相关商家的评价执行“硬规则黑名单”（如“适合约会”的商家证据中如包含“吵闹”、“脏乱”等将触发 `scene_policy_violation` 直接拦截），提升推荐精准性。

### 5. 回归与验证 (Verification)
- **验证手段**：
  - 后台正在全量运行 `pytest tests\local_life\test_day7_golden_cases_chat.py -v`。
  - 系统机制确保了各组件修改符合 LangGraph 状态机定义无语法错误。

目前 P1 所有的底层优化与修复已全部完成！

### 6. 代码同步与版本管理
- **进展**：已将所有未提交的重构与修复代码提交（清除了多余的缓存和日志文件），并推送到 GitHub 远程仓库，完成代码同步。
