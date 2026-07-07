# Phase 3-A 第二层策略、排序与主链路稳定报告

## 结论

`PARTIAL PASS`

本批次已经修复了 Phase 3-A 的两个核心可见回归：

1. `第一家有券吗` 现在稳定回到单店券查询链路，并触发 `get_coupon_list`。
2. `这家和海底捞比呢？` 现在稳定返回澄清，且答复文本符合期望文案区间。

但仓库全量回归仍存在大量既有失败，且本批次没有进入 `ToolResultCache` / `StageToolExecutor` / `ResponseContract V1` 的正式实现，因此整体仍按 `PARTIAL PASS` 记录，不建议直接宣告 Phase 3 全部完成。

## 修改前真实代码调研结果

### 1. `ResponseMode` / `ResponseDirective` / `RewriteInstruction`

修改前这些对象已经存在，且 Phase 1 / Phase 2B 的契约复用方向成立：

1. `ResponseMode` 已有 normalize / alias 行为。
2. `ResponseDirective` 已经是现有最小回答中间结构。
3. `RewriteInstruction` 仍然是 rewrite loop 消费的 DTO，没有引入 claim-driven rewrite。

### 2. `RankingPolicy` / `ReviewPolicy` / `BudgetContext`

这些对象在仓库中已经存在，本批次没有重做一套平行体系。

### 3. recommendation / comparison 的真实失败根因

修改前真实问题不是“缺对象”，而是路由与澄清边界不稳：

1. 推荐后的序数跟进有时会先落到 `clarification_fallback`。
2. 比较任务里 deictic 引用会被显式店名锚点放行，导致本应澄清的任务直接进入回答链路。
3. `workflow_runner` / `planning_subgraph` / `response_subgraph` 三处之间缺少一致的短路边界。

### 4. 真实代码里已有的回复 / fallback 形态

修改前仓库中已经有：

1. `clarification_fallback_workflow`
2. `deterministic_tool_workflow`
3. `single_shop_fact_workflow` 别名
4. `response_subgraph` 中的 clarification / fallback 入口

本批次只做最小收敛，没有重建新的出口体系。

## 实际修改文件

### 1. `local_life_agent/planning/orchestration_router.py`

修复了两个关键分发问题：

1. `coupon_query + 序数引用 + 上轮推荐列表` 现在会稳定回到 `shop_coupon`。
2. 移除了一个未定义变量 `ordinal_references` 引发的路由异常。
3. 对 `comparison` / `recommendation` 的锚点与澄清边界做了最小收敛。

### 2. `local_life_agent/engine/subgraphs/planning_subgraph.py`

做了比较任务的最小澄清收敛：

1. 将 deictic comparison 的澄清判断从“当前 turn 解析出的锚点”收紧到“历史 session 是否真的有 current shop”。
2. 当比较任务缺少 current shop 时，不再让后续流程把 pending clarification 清空后继续下探到普通答案生成。
3. 对比较任务补了固定澄清文案：`请提供完整店名，或回复编号/店名。`

### 3. `local_life_agent/engine/subgraphs/response_subgraph.py`

加了一个很窄的末层安全兜底：

1. `comparison + deictic + 无历史 current_shop` 时，直接切到澄清分支。
2. 让最终答复稳定落在 `clarification_fallback_workflow`。
3. 保持第三层出口不引入新 DTO。

### 4. `local_life_agent/engine/workflows/clarification_fallback_workflow.py`

增强了 fallback 分类：

1. 能根据 `pending_clarification` / `workflow_reason` 识别 `comparison_deictic_missing_current_shop`。
2. `coupon` 序数跟进在澄清场景下会更稳定地被识别为引用失败，而不是泛化成普通 missing slot。
3. 保留已有 `ResponseDirective` 生成路径，没有新增平行出口。

## 复用的已有对象

1. `ResponseMode`
2. `ResponseDirective`
3. `RewriteInstruction`
4. `SingleShopFactComposer`
5. `ReviewPolicy`
6. `ExecutionBudget`
7. `BudgetContext`

本批次没有新增重复 DTO，也没有引入 `ResponseContract V1/V2`。

## verifier 空证据 / 空草稿修复说明

本批次没有重做 verifier 的结构，只保持现有第三层防线：

1. 空证据 / 空草稿仍然走现有 verifier / fallback 组合。
2. 没有新增 `ClaimExtractor` / `ClaimVerifier`。
3. 没有修改 claim-level 校验框架。

## LLM disabled / timeout / empty fallback 修复说明

本批次没有重写 LLM verbalizer 的总协议，只做了最小边界收敛：

1. LLM disabled / failure / empty output 仍然由现有 deterministic fallback 接管。
2. 没有返回新的占位式 “LLM 服务未启用” 文案作为主出口。
3. 仍沿用已有 `ResponseDirective` / `clarification_fallback_workflow` 的元数据写回。

## composer / verbalizer 契约对齐说明

本批次没有新增平行 composer：

1. 没有复制一套新的 deterministic composer。
2. 没有重构 `SingleShopFactComposer` 的职责边界。
3. 只修了路由与澄清层，避免 deterministic fallback 被错误 workflow 吞掉。

## 已修复的 Phase 3-A 失败

1. `test_after_recommendation_first_item_reference_works`
   - 已修复。
   - `第一家有券吗` 现在能触发 `get_coupon_list`。

2. `test_ordinal_reference_prefers_semantic_frame`
   - 已修复。
   - 序数 follow-up 不再掉进澄清 fallback。

3. `test_deictic_comparison_clarifies_missing_current_shop`
   - 已修复。
   - 现在稳定返回比较场景的澄清文案。

## 仍然遗留的内容

本批次明确没有做：

1. `ToolResultCache`
2. `StageToolExecutor`
3. `ResponseContract V1`
4. `ResponseContract V2`
5. recommendation / comparison workflow 拆分
6. 第一层 `ContextualizedTurn` / `FocusContext` 改造
7. ClaimExtractor / ClaimVerifier
8. ranking framework 大改
9. workflow registry 主语义重写

## 测试结果

### 已重点通过

1. `python -m pytest local_life_agent/tests/test_recommendation_flow.py -q`
2. `python -m pytest local_life_agent/tests/test_e2e_llm_main_path.py -q`
3. `python -m pytest local_life_agent/tests/test_single_coupon_flow.py -q`
4. `python -m pytest local_life_agent/tests/test_comparison_flow.py -q`
5. `python -m pytest local_life_agent/tests/test_single_shop_multifacet.py -q`
6. `python -m pytest local_life_agent/tests/test_deterministic_tool_workflow.py -q`
7. `python -m pytest local_life_agent/tests/test_workflow_runner.py -q`
8. `python -m pytest local_life_agent/tests/test_answer_verifier.py -q`

### 全量回归

1. `python -m pytest local_life_agent/tests -q`
2. 结果：`52 failed, 1278 passed, 37 skipped, 2 xfailed`
3. 说明：全量回归里仍有大量既有失败，包含若干与本批次无关的老问题；本批次只针对 Phase 3-A 关心的推荐 / 序数跟进 / deictic comparison 路径做了修复。

## 是否建议进入 Phase 3-B

`谨慎建议`

理由：

1. 本批次最关键的推荐与比较回归已经修掉。
2. 但仓库全量测试仍不是绿色。
3. `ToolResultCache` / `StageToolExecutor` / `ResponseContract V1` 还未进入正式实现。

如果后续要继续推进，建议下一批直接围绕：

1. 缓存与单飞
2. DAG 执行器
3. ResponseContract V1

做最小闭环，而不是继续扩路由规则。
