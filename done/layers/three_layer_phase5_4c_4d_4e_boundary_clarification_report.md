# Phase 5 后半段 4c / 4d / 4e 收口报告

结论：PASS

## 1. 前置门禁结果

门禁通过，允许进入 4c / 4d / 4e。

- `test_recommendation_flow.py`：通过
- `test_comparison_flow.py`：通过
- `test_single_coupon_flow.py`：通过
- `test_single_shop_multifacet.py`：通过
- `test_e2e_llm_main_path.py`：通过
- `test_phase3_completion_contracts.py`：通过
- `test_phase7_workflows.py`：通过

## 2. 修改前真实代码调研结果

### 2.1 Error / early response

- `local_life_agent/answer/response_directive.py` 只有 `ResponseDirective`，没有 `ErrorEnvelope` / `EarlyResponseDirective`。
- `local_life_agent/answer/response_contract.py` 只从 `ResponseDirective` 派生 `ResponseContractV1`，不会保留结构化早期错误 / 澄清信息。
- `local_life_agent/engine/subgraphs/intake_guard_router.py` 在 hard guard 失败时直接返回字符串式 `final_response`，没有统一错误载体。

### 2.2 Clarification 收敛状态

- `pending_clarification` 仍是主载体。
- `clarification_request` 只是 graph state / router / merge 节点上的兼容字段，没有统一 DTO。
- `target.clarification` 已有 `PendingClarification` 构建和 prompt 生成，但没有独立的 clarification request 统一形态。

### 2.3 第一层边界

- `hard_guard` 已经只做 allow / deny / reject 的输入守门，不承担实体解析。
- `slot_extractor` 在 `understanding_subgraph` 中只做语义帧补强，不覆盖既有 `task_type / merchant_mentions / ordinals / deictics`。
- `active_turn_resolver` 仍是 pending clarification 的规则化续转器，没有实体搜索职责。

## 3. 4c：ErrorEnvelope / EarlyResponseDirective

### 3.1 新增 DTO

新增了统一错误与早期响应载体：

- `ErrorEnvelope`
- `EarlyResponseDirective`

并将它们接到现有 `ResponseDirective` / `ResponseContractV1` 链路中。

### 3.2 ResponseDirective 变化

`ResponseDirective` 现在可携带：

- `reason`
- `clarification_request`
- `error_envelope`

这不是新的一套 final response，而是给统一出口补充结构化语义。

### 3.3 ResponseContractV1 衔接

`ResponseContractV1.from_response_directive(...)` 现在会把：

- `reason`
- `error_envelope`
- `clarification_request`

保存在 `metadata` 中，保证最终出口和预览文本语义一致。

### 3.4 early response 的实际落点

- `hard_guard` 失败时，`intake_guard_router` 会生成结构化 `ErrorEnvelope` + `EarlyResponseDirective`。
- `response_subgraph` 的澄清分支也改为输出 `EarlyResponseDirective`，不再只靠纯文本。

## 4. 4d：hard_guard / slot_extractor / active_turn_resolver 边界

### 4.1 hard_guard

- 维持纯 allow / deny / reject 职责。
- 失败时输出结构化 `ErrorEnvelope`，并将 `response_mode` 收束为 `reject`。
- 不把 hard_guard 扩成路由权威。

### 4.2 slot_extractor

- 没有改成全局 semantic parser。
- 通过回归测试确认：当 `SemanticFrame` 已经有 `task_type / merchant_mentions / deictic_references / ordinal_references` 时，`_h_slot_extractor` 只补强，不覆盖既有值。

### 4.3 active_turn_resolver

- 未扩大其职责边界。
- 仍保持 ordinal / deictic / topic switch 的续转器定位，不引入实体解析。
- 通过现有单测和全量回归确认没有把它改成第二层实体搜索器。

## 5. 4e：pending_clarification / clarification_request 收敛

### 5.1 新统一 DTO

新增 `ClarificationRequest`，作为澄清链路的统一结构化请求。

字段覆盖：

- `clarification_type`
- `question`
- `missing_slots`
- `candidate_options`
- `resume_context`
- `source_stage`
- `expires_at`
- `freshness_meta`

### 5.2 派生关系

`pending_clarification` 仍保留为兼容主载体，但 `clarification_request` 现在从它派生：

- `intake_guard_router` 载入 session 时，会把 `pending_clarification` 转成 `clarification_request`
- `merge_clarification` 会维持同一份派生请求，直到恢复、取消、过期或切题时清空
- `response_subgraph` 的 clarify 分支会把 `clarification_request` 一起带到 `ResponseDirective`

### 5.3 兼容关系

- 没有删除旧字段。
- 没有改变澄清恢复的主链路。
- 没有把 clarification request 做成另一套独立 workflow。

## 6. 与 ContextualizedTurn / FocusContext 的关系

- 4p / 4a / 4b 相关的 `ContextualizedTurn`、`FocusContext`、`FreshnessMeta`、`LocationContext` 没有被重做。
- 本阶段只在澄清与早期响应边界上补协议，没有回退到第一层上下文设计。

## 7. 与统一 final_response / ResponseContractV1 的衔接

- `final_response` 仍然是统一出口语义。
- `preview_text` 仍用于早期/预览态输出。
- `EarlyResponseDirective` 不新增第二套终局，只是把 early response 的结构化信息带进统一响应层。
- `ResponseContractV1` 仍是最终统一 contract，兼容 `ResponseDirective` 和 `EarlyResponseDirective`。

## 8. 实际修改文件清单

- `local_life_agent/domain/schemas.py`
- `local_life_agent/domain/graph_state.py`
- `local_life_agent/domain/graph_state_model.py`
- `local_life_agent/target/clarification.py`
- `local_life_agent/answer/response_directive.py`
- `local_life_agent/answer/response_contract.py`
- `local_life_agent/engine/subgraphs/intake_guard_router.py`
- `local_life_agent/engine/subgraphs/merge_clarification.py`
- `local_life_agent/engine/subgraphs/response_subgraph.py`
- `local_life_agent/tests/test_phase5_boundary_clarification_contracts.py`

## 9. 明确没有做的后续内容

本阶段没有做：

- 第 6 批 target_resolve 权威迁移
- ContextualizedTurn / FocusContext 的进一步重构
- ClaimVerifier L2 / L3
- ResponseContract V2
- graph_builder 重写
- planning_subgraph 重写
- Redis SessionStore
- complex_orchestrator / MapReduce

## 10. 测试结果

### 10.1 定点测试

- `python -m pytest local_life_agent/tests/test_phase5_boundary_clarification_contracts.py -q` -> `5 passed`
- `python -m pytest local_life_agent/tests/test_third_layer_response_directive.py -q` -> `1 passed`
- `python -m pytest local_life_agent/tests/test_phase3_completion_contracts.py -q` -> `4 passed`
- `python -m pytest local_life_agent/tests/test_router_rule_policy_guard.py -q` -> `46 passed`
- `python -m pytest local_life_agent/tests/test_active_turn_resolver.py -q` -> `30 passed`
- `python -m pytest local_life_agent/tests/test_phase4_state_dto_contracts.py -q` -> `5 passed`
- `python -m pytest local_life_agent/tests/test_recommendation_flow.py -q` -> `17 passed, 2 xfailed`
- `python -m pytest local_life_agent/tests/test_comparison_flow.py -q` -> `26 passed`
- `python -m pytest local_life_agent/tests/test_single_coupon_flow.py -q` -> `6 passed`
- `python -m pytest local_life_agent/tests/test_e2e_llm_main_path.py -q` -> `7 passed, 1 skipped`
- `python -m pytest local_life_agent/tests/test_phase7_workflows.py -q` -> `10 passed`

### 10.2 全量验证

- `python -m compileall local_life_agent` -> 通过
- `python -m pytest local_life_agent/tests -q` -> `1363 passed, 37 skipped, 2 xfailed`

## 11. 是否建议进入第 6 批

建议进入第 6 批。

理由：

- 4c / 4d / 4e 的边界和协议已经收口完成
- 全量测试保持绿色
- 澄清链路已具备统一 DTO 和统一 response contract 的承接能力

