# 07 观测性 Trace / Metrics / Eval Runner 全面检验

> 适用范围：`observability/trace.py`、`observability/metrics.py`、`eval/eval_runner.py`、`agent.py` 中的 `DebugInfo`、`tests/test_streaming_event_contract.py`、`tests/test_trace_observability.py`、`tests/test_metrics_eval.py`、`tests/test_eval_runner.py`、AI harness、端到端回归。

> 说明：这里没有独立的 `TraceMetricsEval` 单模块；观测性、指标和评测分别由 `observability/*`、`eval/*` 和 `agent.py` 协作提供。

## 0. 命名纠偏与功能判断

| 项目 | 结论 |
|---|---|
| 模块名写错 | `TraceMetricsEval` 不是独立模块；真实拆分是 `observability/trace.py`、`observability/metrics.py`、`eval/eval_runner.py` 和 `agent.py` 的 `DebugInfo`。`ChatDrawer` 也不是仓库里的实际组件名，前端对应的是 `ChatView` / `ChatSidebar` / assistant 相关组件。 |
| 功能等价存在 | 是。trace、metrics、eval runner、streaming contract、调试信息透传都已有对应实现。 |
| 真缺口 / 细节不到位 | 文档中若写死“14 种事件”或 `ChatDrawer`，属于抽象/命名不准，需要以实际测试契约和前端组件名为准；另外 `test_real_llm_probe.py` 并不存在，应改成真实存在的 `test_real_llm_acceptance.py`。 |

## 1. 检验目标

观测性层要证明系统不仅“能跑”，而且“能解释为什么这么跑、哪里失败、是不是 LLM 主路径”。

必须证明：

1. 每一轮请求都有完整 trace_id / turn_id。
2. 每个关键节点都有输入、输出、状态、耗时、fallback reason。
3. AI 相关路径能区分 real_llm、fake_llm、rule_based、fallback。
4. 工具调用、证据、决策、回答校验都有可追踪链路。
5. Eval Runner 能批量跑场景并生成稳定指标。
6. 前端 Streaming Event 能展示关键推理链路，但不泄露敏感内部 prompt。

## 2. 代码走查清单

| 文件/模块 | 检查重点 |
|---|---|
| `observability/trace.py` | trace 字段是否完整；source 推断是否可靠 |
| `observability/metrics.py` | 节点耗时、工具成功率、fallback 率、verifier 通过率 |
| `eval/eval_runner.py` | 是否支持批量场景、断言、报告 |
| `tests/test_streaming_event_contract.py` | 14 种事件是否语义清楚，顺序稳定 |
| `agent.py` 中的 `DebugInfo` | 是否透传必要调试字段，不泄露 prompt/key |
| LangGraph node logging | 每个节点是否记录 stage/status/duration |
| 前端 ChatDrawer | 是否正确解码 SSE 并展示 trace |

## 3. AI Harness 检验重点

AI harness 是检验 Agent 是否可靠的核心。

### 3.1 Harness 分层要求

| 层级 | Harness 类型 |
|---|---|
| 语义层 | fake LLM / poison fallback / malformed JSON |
| 规划层 | fake ToolPlan / invalid tool / empty query / too many targets |
| 工具层 | fake tool executor / timeout / partial / backend unavailable |
| 决策层 | fake evidence / missing facet / degraded candidate |
| 答案层 | hallucinating verbalizer / verifier failover |
| 上下文层 | multi-turn conversation scripts |
| 端到端 | scenario eval runner + real LLM probe |

### 3.2 Harness 必须回答的问题

1. 这次是不是调用了 LLM？
2. 调用的是 real LLM、fake LLM 还是 rule_based？
3. LLM 输出是否通过 schema？
4. fallback 是否发生？为什么？
5. 工具调用是否成功？失败在哪个 backend？
6. 决策依据有哪些 evidence？
7. 最终回答是否通过 verifier？
8. 多轮上下文是从哪里恢复的？

## 4. Trace 字段建议

建议每轮至少包含：

```text
trace_id
session_id
turn_id
user_query
normalized_query
semantic_source
llm_called
llm_backend
parse_status
route_decision
tool_plan_source
tool_plan_validated
tool_plan_fallback_reason
selected_tools
tool_results_summary
evidence_status
decision_status
answer_source
answer_verify_passed
answer_verify_violations
answer_fallback_reason
reference_resolution_source
target_resolution_source
latency_ms_by_stage
final_status
```

工具调用 trace 建议包含：

```text
call_id
tool_name
args_redacted
result_status
tool_backend
backend_source
fallback_from
http_status
endpoint
latency_ms
error_code
error_message
```

## 5. Metrics 检验指标

| 指标 | 说明 |
|---|---|
| semantic_llm_rate | 语义层 LLM 主路径比例 |
| semantic_fallback_rate | 语义 fallback 比例 |
| tool_success_rate | 工具成功率 |
| tool_error_rate | 工具错误率 |
| backend_fallback_rate | Java/db fallback 到 mock 比例 |
| empty_result_rate | 工具空结果比例 |
| verifier_pass_rate | 回答校验通过率 |
| answer_fallback_rate | 模板 fallback 比例 |
| clarification_rate | 澄清率 |
| context_recovery_success_rate | 多轮上下文恢复成功率 |
| e2e_success_rate | 端到端场景通过率 |
| p95_latency_ms | 端到端 P95 延迟 |

## 6. Eval Runner 检验场景

建议 eval 至少包含以下类别：

| 类别 | 场景数建议 |
|---|---:|
| 单店查券/营业/距离/环境 | 10 |
| 多 facet 单店 | 10 |
| 附近推荐 | 15 |
| 场景推荐 | 10 |
| 多店对比 | 10 |
| 多轮指代 | 15 |
| 澄清恢复 | 10 |
| 工具失败降级 | 10 |
| LLM 非法输出 | 10 |
| 答案幻觉拦截 | 10 |

每条 eval case 应包含：

```yaml
id:
name:
turns:
expected_intent:
expected_tools:
expected_context_behavior:
expected_decision_shape:
forbidden_claims:
required_trace_fields:
assertions:
```

## 7. Streaming Event 检验

检查事件是否覆盖：

1. request_received
2. semantic_started / semantic_done
3. planning_started / planning_done
4. tool_call_started / tool_call_done
5. evidence_started / evidence_done
6. decision_started / decision_done
7. answer_started / answer_delta / answer_done
8. verifier_done
9. fallback
10. error
11. trace_summary

要求：

- 事件顺序稳定。
- event 中不泄露 API key、完整 prompt、内部敏感配置。
- 前端能展示用户可理解的推理链路。
- DebugInfo 适合开发环境，生产可关闭或脱敏。

## 8. 建议运行命令

```bash
pytest -q local_life_agent/tests/test_trace_observability.py
pytest -q local_life_agent/tests/test_metrics_eval.py
pytest -q local_life_agent/tests/test_eval_runner.py
pytest -q local_life_agent/tests/test_streaming_event_contract.py
pytest -q local_life_agent/tests/test_comprehensive_graph_e2e.py
```

如果有真实 LLM 探针，可单独运行：

```bash
ENABLE_REAL_LLM=true pytest -q local_life_agent/tests/test_real_llm_acceptance.py
```

## 9. 通过标准

严格通过需要满足：

- 每个关键节点 trace 完整。
- LLM / rule / fallback 路径可区分。
- 工具失败、解析失败、回答 verifier 失败能定位。
- Eval Runner 能批量运行并输出报告。
- 多轮 context 有 snapshots。
- 前端 streaming 展示清晰且不泄露敏感信息。

## 10. 常见 P0/P1/P2

| 等级 | 问题 |
|---|---|
| P0 | trace 泄露 API key / prompt / 隐私 |
| P1 | LLM 主路径和 rule fallback 无法区分 |
| P1 | 工具失败无法定位 backend |
| P1 | Eval 只跑 happy path，没有 poison/failure case |
| P1 | 多轮 context 无 snapshot，无法复盘 |
| P2 | metrics 只有总成功率，没有分层指标 |

## 11. 验收报告模板

```markdown
# 观测性 Trace / Metrics / Eval Runner 验收报告

## 总体结论
- 严格通过 / 基本通过 / 不通过：

## Trace
- trace_id/turn_id：
- 节点字段：
- LLM source：
- tool metadata：
- context source：

## Metrics
- LLM fallback：
- tool success：
- verifier pass：
- context recovery：
- latency：

## Eval Runner
- case 数量：
- 覆盖类别：
- poison/failure：
- 报告输出：

## Streaming
- 事件完整性：
- 顺序：
- 前端展示：
- 脱敏：

## 问题清单
| 等级 | 问题 | 文件 | 修复建议 |
|---|---|---|---|
```
