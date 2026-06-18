# LangGraph 节点覆盖矩阵

> 目标：把主图和子图里的每个节点都对应到职责、分支条件和覆盖文档，方便你逐个核对。

> 说明：下面的“覆盖文档”仍然按结构分组；本次新增一层“chat E2E 实测索引”，用来把真实跑过的 case 贴回去。

## 实测图例

- `✅`：chat 接口实测命中
- `🧪`：源码 / 单测验证
- `⚠️`：本次 chat E2E 未自然命中

## 主图节点

| 节点 | 职责 | 典型输入条件 | 输出 / 去向 | 覆盖文档 |
|---|---|---|---|---|
| `load_context` | 载入会话、记忆、上下文 | 任意新 query | `request_legality` | `00_overview.md`, `01_frontdoor_and_intent.md` |
| `request_legality` | 合法性检查 | 进入服务后第一层门禁 | `illegal_request_response` 或 `hard_guard` | `01_frontdoor_and_intent.md` |
| `illegal_request_response` | 违法/阻断类直接回复 | `request_legality` blocked | `final_answer` | `01_frontdoor_and_intent.md` |
| `hard_guard` | 硬规则检查 | 非显式阻断时继续 | `clarification_or_reject` 或 `query_safety` | `01_frontdoor_and_intent.md` |
| `clarification_or_reject` | 硬规则澄清/拒绝 | hard guard blocked | `final_answer` | `01_frontdoor_and_intent.md` |
| `query_safety` | query 安全检查 | 继续理解前 | `safety_reject_response` 或 `understand_turn` | `01_frontdoor_and_intent.md` |
| `safety_reject_response` | 安全拒绝输出 | unsafe / blocked | `final_answer` | `01_frontdoor_and_intent.md` |
| `understand_turn` | 意图、槽位、引用理解 | 通过安全门禁后 | `top_level_intent_router` | `02_understand_turn.md` |
| `top_level_intent_router` | 顶层意图路由 | understand_turn 后 | 身份 / 能力 / 闲聊 / 本地生活 / 直接答 | `01_frontdoor_and_intent.md` |
| `identity_answer` | 身份答复 | 用户问“你是谁” | `final_answer` | `01_frontdoor_and_intent.md` |
| `capability_answer` | 能力答复 | 用户问“你能做什么” | `final_answer` | `01_frontdoor_and_intent.md` |
| `direct_chat_answer` | 闲聊答复 | 闲聊 / 直接答路径 | `final_answer` | `01_frontdoor_and_intent.md` |
| `out_of_scope_response` | 超范围答复 | 超出业务域 | `final_answer` | `01_frontdoor_and_intent.md` |
| `query_merge_for_local_life` | 本地生活 query 合并 | 本地生活域 | `merged_query_safety` | `03_local_life_standard_workflow.md` |
| `merged_query_safety` | 合并后安全检查 | 本地生活域合并完成 | `safety_reject_response` 或 `build_answer_contract` | `03_local_life_standard_workflow.md` |
| `build_answer_contract` | 构造回答合同 | 需要正式回答时 | `target_requirement_router` | `03_local_life_standard_workflow.md` |
| `target_requirement_router` | 选择目标解析策略 | 合同已建立 | `resolve_target_shop` / `resolve_comparison_targets` / `prepare_recommendation_context` / `clarification_node` | `03_local_life_standard_workflow.md` |
| `resolve_target_shop` | 单店目标解析 | 单店场景 | `build_source_contract` | `03_local_life_standard_workflow.md` |
| `resolve_comparison_targets` | 对比目标解析 | 对比场景 | `build_source_contract` | `03_local_life_standard_workflow.md` |
| `prepare_recommendation_context` | 推荐上下文准备 | 推荐场景 | `build_source_contract` | `03_local_life_standard_workflow.md` |
| `clarification_node` | 澄清输出 | 目标缺失 / 复杂度要求澄清 | `final_answer` | `01_frontdoor_and_intent.md`, `03_local_life_standard_workflow.md`, `04_local_life_simple_path.md` |
| `build_source_contract` | 来源约束构造 | 已确定目标/场景 | `complexity_router` | `03_local_life_standard_workflow.md` |
| `complexity_router` | 简单/标准/复杂分流 | source contract 就绪 | `clarification_node` / `direct_executor` / `workflow_executor` / `planner_node` | `03_local_life_standard_workflow.md`, `04_local_life_simple_path.md`, `05_complex_plan_execute.md` |
| `direct_executor` | 简单直答执行 | simple 模式 | `rule_review` | `04_local_life_simple_path.md` |
| `rule_review` | 简单答案规则审查 | direct_executor 后 | `final_answer` | `04_local_life_simple_path.md` |
| `workflow_executor` | 标准执行链入口 | standard 模式 | `select_required_sources` | `03_local_life_standard_workflow.md` |
| `select_required_sources` | 选择需要的来源 | answer contract 已定 | `source_dispatch` | `03_local_life_standard_workflow.md` |
| `source_dispatch` | 分发到 tool/recommendation | 选出 current_source | `tool_executor` / `recommendation_executor` / `merge_or_rank` | `03_local_life_standard_workflow.md` |
| `tool_executor` | 工具子图入口 | current_source = tool | `source_dispatch` / `merge_or_rank` / `collect_step_result` | `03_local_life_standard_workflow.md`, `05_complex_plan_execute.md` |
| `recommendation_executor` | 推荐子图入口 | current_source = recommendation | `source_dispatch` / `merge_or_rank` / `collect_step_result` | `03_local_life_standard_workflow.md`, `05_complex_plan_execute.md` |
| `merge_or_rank` | 合并 / 排序 | 来源结果齐备 | `contract_review` | `03_local_life_standard_workflow.md` |
| `contract_review` | 合同复核 | 标准链末端 | `prepare_retry` 或 `final_answer` | `03_local_life_standard_workflow.md` |
| `prepare_retry` | 准备重试 | contract_review 要 retry | `workflow_executor` | `03_local_life_standard_workflow.md` |
| `planner_node` | 计划生成 | complex 模式 | `plan_validator` | `05_complex_plan_execute.md` |
| `plan_validator` | 计划校验 | plan 已生成 | `plan_executor` | `05_complex_plan_execute.md` |
| `plan_executor` | 计划执行准备 | complex 任务执行期 | `execute_plan_step` | `05_complex_plan_execute.md` |
| `execute_plan_step` | 按 step 执行 | 当前 step 就绪 | `tool_executor` / `recommendation_executor` / `rank_executor` / `merge_executor` / `compose_draft` | `05_complex_plan_execute.md` |
| `rank_executor` | 复杂路径排名 | step 指向 rank | `collect_step_result` | `05_complex_plan_execute.md` |
| `merge_executor` | 复杂路径合并 | step 指向 merge | `collect_step_result` | `05_complex_plan_execute.md` |
| `compose_draft` | 复杂路径草稿生成 | step 指向 compose | `collect_step_result` | `05_complex_plan_execute.md` |
| `collect_step_result` | 收集 step 结果 | 复杂路径 step 完成 | `all_steps_done?` | `05_complex_plan_execute.md` |
| `all_steps_done?` | 判断是否结束 | step 结果累积后 | `execute_plan_step` 或 `complex_review` | `05_complex_plan_execute.md` |
| `complex_review` | 复杂任务终审 | 全部 step 完成 | `final_answer` / `repair_answer` / `final_with_limitations` / `execute_plan_step` / `planner_node` | `05_complex_plan_execute.md` |
| `final_answer` | 最终答案收口 | 所有主路径最终出口前 | `final_answer_safety` | `00_overview.md`, `06_final_output_and_safety.md` |
| `final_answer_safety` | 最终安全审查 | final_answer 后 | `final_safety_fallback` / `response_builder` | `06_final_output_and_safety.md` |
| `final_safety_fallback` | 最终安全兜底 | safety blocked | `response_builder` | `06_final_output_and_safety.md` |
| `repair_answer` | 修复后回流 | safety 或 review 需要修复 | `final_answer` | `05_complex_plan_execute.md`, `06_final_output_and_safety.md` |
| `final_with_limitations` | 有限制答案 | 结果不完整但可答 | `final_answer` | `05_complex_plan_execute.md`, `06_final_output_and_safety.md` |
| `response_builder` | 组装最终回复 | safety 之后 | `persist_session` | `06_final_output_and_safety.md` |
| `persist_session` | 持久化会话 | 回复已定稿 | `emit_final` | `06_final_output_and_safety.md` |
| `emit_final` | 发出最终事件 | 流式输出最后一步 | `END` | `00_overview.md`, `06_final_output_and_safety.md` |

## 本次 Chat E2E 实测索引

### 入口与意图

- `load_context`，`understand_turn`，`top_level_intent_router`
- 代表 case：
  - `D1-1` `海底捞水晶城店怎么样？`
  - `D5-1` `附近有没有推荐的餐厅？`
  - `D8-1` `海底捞水晶城店现在营业吗？`
  - `D10-1` `海底捞和巴奴哪个更适合约会？`
  - `D14-1` `海底捞水晶城店环境怎么样，有券吗，离我多远？`

### 澄清与上下文继承

- `clarification_node`
- 代表 case：
  - `D11-2` `有券吗？`
  - `D42-1` `附近有什么好吃的`（同类澄清）
- `query_merge_for_local_life`
- 代表 case：
  - `D13-1` `海底捞水晶城店怎么样？` -> `有券吗？`
  - `D14-1` 复合 facet 查询

### 标准链

- `build_answer_contract`，`target_requirement_router`，`build_source_contract`
- 代表 case：
  - `D5-1` 推荐
  - `D10-1` 对比
  - `D14-1` 复合 facet
- `tool_executor`
  - `D8-1` 营业状态
  - `D13-1` 券继承
- `recommendation_executor`
  - `D5-1` 附近推荐
  - `D6-1` 场景推荐
  - `D27-1` 推荐 + 券

### 复杂计划

- `planner_node` / `plan_execute` / `complex_review`
- 状态：
  - `🧪` 代码与单测已覆盖
  - `⚠️` 当前 chat E2E 未自然命中
  - 典型 `task_plan_failure_reason`：
    - `not_rag_plus_tool`
    - `missing_dynamic_combo`

## 子图节点

### understand_turn 子图

| 节点 | 职责 | 覆盖文档 |
|---|---|---|
| `parse_intent_slots` | 解析意图与槽位 | `02_understand_turn.md` |
| `resolve_reference` | 引用消解 | `02_understand_turn.md` |
| `ambiguity_check` | 歧义检查 | `02_understand_turn.md` |
| `finalize_understand_turn` | 汇总理解结果 | `02_understand_turn.md` |

### rag 子图

| 节点 | 职责 | 覆盖文档 |
|---|---|---|
| `build_retrieval_plan` | 构造检索计划 | `03_local_life_standard_workflow.md` |
| `hybrid_retrieve` | 混合检索 | `03_local_life_standard_workflow.md` |
| `filter_rag` | 过滤检索结果 | `03_local_life_standard_workflow.md` |
| `rerank_rag` | 重排证据 | `03_local_life_standard_workflow.md` |
| `build_evidence_pack` | 打包证据 | `03_local_life_standard_workflow.md` |
| `finalize_rag` | RAG 结果收尾 | `03_local_life_standard_workflow.md` |

### tool 子图

| 节点 | 职责 | 覆盖文档 |
|---|---|---|
| `tool_plan` | 工具规划 | `03_local_life_standard_workflow.md` |
| `tool_executor` | 工具执行 | `03_local_life_standard_workflow.md` |
| `finalize_tool` | 工具结果收尾 | `03_local_life_standard_workflow.md` |

### recommendation 子图

| 节点 | 职责 | 覆盖文档 |
|---|---|---|
| `prepare_recommendation` | 推荐前准备 | `03_local_life_standard_workflow.md` |
| `dispatch_shop_analysis` | 分发到门店分析 | `03_local_life_standard_workflow.md` |
| `analyze_one_shop` | 单店分析 | `03_local_life_standard_workflow.md` |
| `reduce_shop_results` | 聚合门店结果 | `03_local_life_standard_workflow.md` |
| `finalize_recommendation` | 推荐结果收尾 | `03_local_life_standard_workflow.md` |

### plan_execute 子图

| 节点 | 职责 | 覆盖文档 |
|---|---|---|
| `planner_node` | 生成计划 | `05_complex_plan_execute.md` |
| `plan_validator` | 校验计划 | `05_complex_plan_execute.md` |
| `plan_executor` | 计划执行准备 | `05_complex_plan_execute.md` |
| `execute_plan_step` | 单步执行 | `05_complex_plan_execute.md` |
| `collect_step_result` | 收集步骤结果 | `05_complex_plan_execute.md` |
| `complex_review` | 复杂复盘 | `05_complex_plan_execute.md` |
| `finalize_plan_execute` | plan 子图结束 | `05_complex_plan_execute.md` |

## 直接看测试的话

如果你想把这些节点和真实行为对起来，建议直接看：

- `learning-agent-service/tests/test_workflow_compiled_subgraphs.py`
- `learning-agent-service/tests/test_workflow_rag_gate.py`
- `learning-agent-service/tests/test_tools.py`
