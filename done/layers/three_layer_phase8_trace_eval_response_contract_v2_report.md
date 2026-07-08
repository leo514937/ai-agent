# Phase 8 / 5c Trace + Eval + ResponseContract V2 报告

结论：PASS

## 1. 前置门禁验收结果

进入 5c 前的门禁已通过：

1. `5a-a load_session` 已拆分完成。
2. `5a-b target_resolve` 权威归第二层，第一层不再做实体解析。
3. `5a-c planning_subgraph` 已收缩为兼容 dispatch 层，共享 service 已接入。
4. `5b SessionStore` 抽象、TTL、RedisSessionStore 已完成并通过回归。
5. 当前全量测试无遗留失败。
6. recommendation / comparison / single_shop / coupon / e2e 主链路全部通过。
7. `ResponseContractV1 / final_response` 没有 bypass 回退。

## 2. 修改前真实代码调研结果

修改前已经存在：

* `local_life_agent/observability/trace.py` 的事件级 trace 体系
* `TraceSpanRecord`、`TurnTrace`、`record_span()`、`build_turn_trace()`
* `ResponseContractV1` 与 `ResponseDirective`
* `response_subgraph` 的最终响应构建路径
* `agent.run_agent_graph()` 中对 `build_turn_trace()` 的消费

但缺少：

* 阶段级统一 trace span contract
* `ResponseContractV2`
* latency / cost benchmark 测试

## 3. Trace schema 修改说明

### 3.1 新增阶段级 span

在原有 `events` / `spans` 兼容基础上，新增了 `stage_spans`，用于表达 8 个阶段级视图：

* `intake_span`
* `routing_span`
* `understanding_span`
* `planning_span`
* `execution_span`
* `evidence_span`
* `decision_span`
* `response_span`

### 3.2 stage span 字段

每个 stage span 统一携带：

* `stage`
* `decision`
* `latency_ms`
* `llm_called`
* `tool_called`
* `input_snapshot`
* `output_snapshot`
* `error`

### 3.3 兼容策略

为了不破坏现有回归：

* `events` 保留原始节点级日志
* `spans` 继续保留旧的归一化兼容视图
* `stage_spans` 作为 5c 新增的阶段级契约

同时对 `TurnTrace` 做了 `dict` / dataclass 双兼容，避免 eval / prompt contract 读取旧形态时报错。

## 4. benchmark 覆盖说明

新增了两组基准测试：

* latency benchmark
* cost benchmark

覆盖场景：

* simple fact query
* recommendation
* comparison
* single coupon
* clarification
* exploration

关注指标：

* `latency_ms`
* `tool_call_count`
* `llm_call_count`
* `cache_hit_count`
* `fallback_count`
* `rewrite_count`

说明：

* benchmark 只用于测试与报告
* 没有改业务路由
* 没有为了 benchmark 跳过 verifier 或工具调用

## 5. ResponseContract V2 设计说明

在 `ResponseContractV1` 基础上新增 `ResponseContractV2`，并将其作为新的权威出口承载：

* `claims`
* `citations`
* `cards`
* `confidence_band`
* `response_policy`
* `clarification`
* `safety_notice`
* `trace_summary`

`ResponseContractV2` 仍保留 V1 的基础字段：

* `answer_text`
* `response_mode`
* `preview_text`
* `answer_source`

这样可以直接把旧字段从 V2 派生，而不是再让 workflow 直接写 `final_response`。

## 6. 旧字段由 V2 派生的说明

实现方式：

* `response_subgraph._h_final_response()` 先构建 `ResponseContractV2`
* 再通过 `ResponseContractV2.to_v1()` 反推 `ResponseContractV1`
* `final_response`、`preview_text`、`answer_source` 都从 V2 的权威数据中派生

没有引入新的 workflow bypass。

## 7. 实际修改文件清单

修改：

1. `[local_life_agent/observability/trace.py](../local_life_agent/observability/trace.py)`
2. `[local_life_agent/answer/response_contract.py](../local_life_agent/answer/response_contract.py)`
3. `[local_life_agent/engine/subgraphs/response_subgraph.py](../local_life_agent/engine/subgraphs/response_subgraph.py)`
4. `[local_life_agent/domain/graph_state.py](../local_life_agent/domain/graph_state.py)`
5. `[local_life_agent/domain/graph_state_model.py](../local_life_agent/domain/graph_state_model.py)`
6. `[local_life_agent/agent.py](../local_life_agent/agent.py)`

新增测试：

1. `[local_life_agent/tests/test_first_layer_trace.py](../local_life_agent/tests/test_first_layer_trace.py)`
2. `[local_life_agent/tests/test_second_layer_trace_contract.py](../local_life_agent/tests/test_second_layer_trace_contract.py)`
3. `[local_life_agent/tests/test_third_layer_trace_contract.py](../local_life_agent/tests/test_third_layer_trace_contract.py)`
4. `[local_life_agent/tests/test_second_layer_latency_budget.py](../local_life_agent/tests/test_second_layer_latency_budget.py)`
5. `[local_life_agent/tests/test_second_layer_cost_benchmark.py](../local_life_agent/tests/test_second_layer_cost_benchmark.py)`
6. `[local_life_agent/tests/test_third_layer_response_contract.py](../local_life_agent/tests/test_third_layer_response_contract.py)`

## 8. 明确没有做的第 9 批内容

未做：

* `complex_orchestrator`
* `MapReduce`
* `ClaimVerifier L2/L3`
* 第 9 批复杂任务编排与终验

## 9. 测试结果

### 9.1 关键门禁

* `python -m pytest local_life_agent/tests/test_recommendation_flow.py -q`：通过
* `python -m pytest local_life_agent/tests/test_comparison_flow.py -q`：通过
* `python -m pytest local_life_agent/tests/test_single_coupon_flow.py -q`：通过
* `python -m pytest local_life_agent/tests/test_single_shop_multifacet.py -q`：通过
* `python -m pytest local_life_agent/tests/test_e2e_llm_main_path.py -q`：通过

### 9.2 5c 新增测试

* `test_first_layer_trace.py`：通过
* `test_second_layer_trace_contract.py`：通过
* `test_third_layer_trace_contract.py`：通过
* `test_second_layer_latency_budget.py`：通过
* `test_second_layer_cost_benchmark.py`：通过
* `test_third_layer_response_contract.py`：通过

### 9.3 兼容性回归

* `python -m pytest local_life_agent/tests/test_eval_runner.py -q`：通过
* `python -m pytest local_life_agent/tests/test_prompt_contract.py -q`：通过

### 9.4 全量回归

* `python -m compileall local_life_agent`：通过
* `python -m pytest local_life_agent/tests -q`：`1379 passed, 37 skipped, 2 xfailed`

## 10. 是否建议进入第 9 批复杂任务编排与终验

建议进入。

原因：

* 5c 已完成
* 全量测试通过
* 新的 trace / benchmark / V2 contract 已经可用
* 旧的 `events / spans / V1` 兼容路径保持稳定
