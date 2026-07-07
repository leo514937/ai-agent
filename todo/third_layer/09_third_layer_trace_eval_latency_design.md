# 第三层 Trace / Eval / Latency 设计

本文件设计第三层可观测性、评测和时延目标。

## 1. 当前真实 trace 入口

### `TurnTrace`

`TurnTrace` 已经能收集：

- `response_mode`
- `workflow_name`
- `task_type`
- `decision_type`
- `tool_call_count`
- `answer_source`
- `verifier_result`
- `fallback_reason`
- `rewrite_count`
- `final_safety_status`
- 各类 span 和事件

证据：

- `local_life_agent/observability/trace.py:80-198`
- `local_life_agent/observability/trace.py:386-573`

### `build_turn_trace()`

它从：

- `trace spans`
- `event log`
- `semantic_frame`
- `execution_plan`
- `evidence_pack`
- `pending_clarification`
- `answer_verify_result`

中拼出整条链路。

证据：

- `local_life_agent/observability/trace.py:386-573`

## 2. 当前不足

- 没有独立 `ResponseTrace`
- 没有 claim 级 trace
- 没有 response contract 级 trace
- 没有把 rewrite/fallback 的原因结构化到统一 trace 中
- 没有把 `preview`、`final`、`verify` 的关系完整串起来

## 3. 目标 trace

建议至少记录：

- `answer_plan_build`
- `response_policy_resolve`
- `verbalizer_or_composer`
- `claim_extract`
- `claim_verify`
- `rewrite`
- `fallback`
- `final_response_build`
- `preview_emit`

每个阶段至少包含：

- `stage`
- `decision`
- `reason`
- `source`
- `confidence`
- `input_snapshot`

## 4. latency 评测目标

第三层需要关心：

- 简单事实回答不能明显慢于当前版本
- 复杂回答不能因为新增 verifier/trace 变成不可接受的重链路
- fallback 必须比反复 rewrite 更便宜

## 5. eval case

建议评测维度：

- 单店事实
- 推荐
- 对比
- 探索规划
- 澄清
- fallback

每类都至少看：

- 正确性
- 事实忠实
- 不确定性表达
- 延迟
- LLM 调用成本

## 6. 目标指标

建议记录：

- `llm_calls`
- `rewrite_count`
- `verifier_mode`
- `draft_to_final_latency_ms`
- `preview_latency_ms`
- `fallback_rate`
- `claim_coverage`

## 7. 当前代码可利用的基础

- `preview_policy` 已经支持未验证 claim 过滤
- `TurnTrace` 已经能汇总很多字段
- `event_stream()` 已经能输出 preview / final / status

证据：

- `local_life_agent/streaming/preview_policy.py:29-43`
- `local_life_agent/app.py:120-240`

## 8. 13 个 Eval 场景详细设计

| # | 场景 | 输入示例 | 断言重点 | 覆盖模块 |
|---|---|---|---|---|
| 1 | 单店营业查询 | "美乐园营业了吗" | 营业状态事实准确，无 LLM 编造 | `_compose_single_shop_response` -> verifier |
| 2 | 单店优惠券查询 | "西贝莜面村有优惠券吗" | 券类型/数量事实准确 | `_compose_single_shop_response` -> verifier |
| 3 | 单店距离查询 | "海底捞离我多远" | 距离数值/单位准确 | `_compose_single_shop_response` -> verifier |
| 4 | 单店评分查询 | "外婆家评分多少" | 评分数值准确 | generator -> verifier（当前缺乏独立校验） |
| 5 | 单店多 facet | "星巴克营业吗，人均多少" | 多 facet 组合表达是否整齐 | answer_plan_build -> generator -> verifier |
| 6 | 单店未知 facet | "这家店的 WiFi 密码是什么" | 正确输出"无相关信息"而非编造 | fallback -> `_h_fallback_answer` |
| 7 | 附近推荐 | "附近推荐火锅" | 推荐排序明确，推荐原因可解释 | `exploration_planning_workflow` -> generator |
| 8 | 条件筛选推荐 | "评分 4.5 以上的川菜馆" | 筛选条件被正确反映 | comparison_matrix -> generator |
| 9 | 多店对比 | "海底捞和西贝哪个更近" | trade-off 正确保留，不强制给无依据 winner | comparison_matrix -> `_rule_based_verbalize` |
| 10 | 工具失败 | （关闭某个 Tool） | fallback 文案有意义而非通用"抱歉" | `_h_fallback_answer` |
| 11 | LLM 不可用 | `ENABLE_LLM_VERBALIZER=False` | 输出有意义且事实正确的 deterministic 回答 | generator -> `_h_answer_generate` |
| 12 | 多轮指代澄清 | 用户说"有券吗"-> Agent 问哪家店 -> 用户说"西贝" | 澄清正确地收敛到单店查询 | `pending_clarification` -> `_h_clarify_response` |
| 13 | 探索规划 | "周末先看电影再吃饭再喝咖啡" | 阶段化表达，不完整阶段可识别 | `exploration_planning_workflow` -> verifier |

## 9. 5 个 Benchmark 场景

| # | 场景 | 测量指标 | 目标值 | 当前基线来源 |
|---|---|---|---|---|
| 1 | 单店营业查询（无 LLM 调用） | 第三层延迟 | <=50ms | `response_subgraph.py:44-125`（deterministic composer） |
| 2 | 单店优惠券查询（无 LLM 调用） | 第三层延迟 | <=50ms | `response_subgraph.py:44-125` |
| 3 | 单店多 facet（含 LLM verbalizer） | 第三层延迟 | <=200ms（LLM 延迟不计入） | `llm_verbalizer.py:429-558` |
| 4 | 推荐回答（含 LLM verbalizer） | LLM 调用次数 | <=2 | `generator.py:605-700` |
| 5 | fallback 路径 | 第三层延迟 | <=30ms | `response_subgraph.py:422-491` |

