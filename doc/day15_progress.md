# Day15 进展 - P1-Day2 路由合同 + Checkpointer + 证据评估 改造完成

> 日期：2026-06-06

## 完成事项

### 1. P1-Day2 改造落地（01:30 - 02:00）

**改造内容已全面完成开发并通过所有测试验证：**

#### 1.1 路由合同（RoutingContract）开发与传递
- 在 [contracts.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/domain/contracts.py) 中新增了 `RoutingContract` 核心模型，承载 `required_facets`、`forbidden_facets`、`target_shop_id`、`compose_allowed_facets` 以及 RAG/Tool 准入标志（`rag_allowed`, `tool_allowed`）。
- 并在 `TurnRuntimeState` 增加 `routing_contract` 字段。
- 在 [subgraphs.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/subgraphs.py) 的 `route_gate` 网关节点中构建并写入 `RoutingContract`。
- 在 `run_rag_subgraph` 和 `run_tool_subgraph` 头部读取 `routing_contract.rag_allowed` / `tool_allowed` 进行精准分支限制。
- 重构 [phase7_compose.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/router/phase7_compose.py) 中的 `_build_answer_contract`，使生成的 `AnswerContract` 继承 `RoutingContract` 中约定的 `compose_allowed_facets` 与 `forbidden_facets`。

#### 1.2 Checkpointer 真实启用与调试支持
- 在 [builder.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/builder.py) 中将 `_CheckpointAwareGraphProxy.get_state()` 改为优先查询真实持久化状态（即 `self._graph.get_state(config)`），异常或空值时才降级使用内存备用缓存 `_CHECKPOINT_FALLBACKS`。
- 使用验证脚本确认 `SqliteSaver` 能够成功持久化包含新增 `RoutingContract` 与修改 `AnswerContract` 的 `GraphState`，无序列化报错，状态恢复正常。

#### 1.3 证据评估与合同过滤
- 在 [subgraphs.py](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/subgraphs.py) 中实现统一的证据评估过滤逻辑 `_filter_evidence_by_contract(state)`。
- 该函数在 `evaluate_evidence`（评估）之后、`citation_builder`（引用生成）之前挂载。
- 过滤机制：
  1. **商铺一致性**：剔除与 `routing_contract.target_shop_id` 不一致的商铺证据。
  2. **合同 facet 约束**：剔除包含在 `routing_contract.forbidden_facets` 内的限制面证据。
  3. **评估联动**：根据过滤后的结果，动态调整 `evidence_quality`（如 `covered_facets` 扣除、`is_valid` 状态修正、`response_mode` 重定位）并向后级传递，避免了私改合同或多层质量重复计算的风险。

---

## 测试验证结果

| 测试套件 | 结果 | 耗时 | 备注 |
|---|---|---|---|
| `test_workflow_runner.py` | ✅ 4 passed | 3.12s | 核心流程验证 |
| `test_langgraph_checkpointing.py` | ✅ 3 passed | 6.81s | Checkpointer 校验 |
| `test_phase1_routing.py` | ✅ 7 passed | 2.76s | 基础路由回归 |
| `test_phase0_core_replay.py` | ✅ 6 passed | 3.20s | 核心重演回归 |
| `test_day2_answer_contract_context_pruning.py` | ✅ 1 passed | 2.40s | 限制面剪枝校验 |
| `test_day2_answer_contract_chat.py` | ✅ 7 passed | 3305.97s | 包含 D2-1 至 D2-4 各项 chat 场景 & D1 回归测试 |

---

## 下一步建议

1. 继续推进下一个里程碑的任务。
2. 保持对 Context 大小的关注，避免上下文溢出。
