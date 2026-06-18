# 本地生活标准链路分析

> 目标：说明本地生活问题如何从“query 合并”进入“answer contract”，再进入标准执行链，最后产出答案。

> 实测提示：本页里的“标准链”不是指每次都必须跑完整个 workflow，而是指在 chat 接口里，`tool`、`recommendation`、`rag_plus_tool` 这些真实分支是怎么落下来的。主图里的 `rag_executor` 已移除，只保留独立 RAG 实现作为参考。

## 适用节点

- `query_merge_for_local_life`
- `merged_query_safety`
- `build_answer_contract`
- `target_requirement_router`
- `resolve_target_shop`
- `resolve_comparison_targets`
- `prepare_recommendation_context`
- `clarification_node`
- `build_source_contract`
- `complexity_router`
- `workflow_executor`
- `select_required_sources`
- `source_dispatch`
- `tool_executor`
- `recommendation_executor`
- `merge_or_rank`
- `contract_review`
- `prepare_retry`

## 主流程

```text
top_level_intent_router
  -> query_merge_for_local_life
  -> merged_query_safety
  -> build_answer_contract
  -> target_requirement_router
       -> resolve_target_shop
       -> resolve_comparison_targets
       -> prepare_recommendation_context
       -> clarification_node
  -> build_source_contract
  -> complexity_router
       -> clarification_node
       -> direct_executor
       -> workflow_executor
       -> planner_node
```

本文件重点讲 `workflow_executor` 这条标准链。

## 标准链的核心思想

标准链不是一次性把所有东西都查完，而是：

1. 先确定答案合同
2. 再选需要哪些来源
3. 然后按来源逐个执行
4. 再做合并或排序
5. 再做合同审查
6. 必要时 retry

## 节点说明

### `query_merge_for_local_life` ([代码位置](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_main_graph.py#L539))

- 做本地生活 query 合并。
- 可能结合历史上下文、上一次提问、当前商家等信息。

### `merged_query_safety` ([代码位置](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_main_graph.py#L574))

- 对合并后的 query 再做安全检查。
- 如果 merged query 被判定 blocked，会直接回到 `safety_reject_response`。

### `build_answer_contract` ([代码位置](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_main_graph.py#L371))

- 构造最终回答合同。
- 这里会写入：
  - `answer_style`
  - `required_facets`
  - `allowed_facets`
  - `selected_entity`
  - `evidence_requirements`

### `target_requirement_router` ([代码位置](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_main_graph.py#L393))

- 根据合同和语义上下文决定：
  - 单店
  - 对比
  - 推荐
  - 澄清

### `resolve_target_shop` ([代码位置](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_main_graph.py#L303))

- 单店场景时用。
- 负责把目标店解析到更具体的实体信息。

### `resolve_comparison_targets` ([代码位置](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_main_graph.py#L333))

- 对比场景时用。
- 负责把两家或多家店的比较对象装进 state。

### `prepare_recommendation_context` ([代码位置](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_main_graph.py#L347))

- 推荐场景时用。
- 负责把场景、偏好、候选列表写进 state。

### `build_source_contract` ([代码位置](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_main_graph.py#L451))

- 把“允许哪些来源、允许哪些证据、允许哪些工具”整理成后续执行约束。

### `complexity_router` ([代码位置](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_main_graph.py#L485))

- 决定后续走：
  - `clarification_node`
  - `direct_executor`
  - `workflow_executor`
  - `planner_node`

### `workflow_executor` ([代码位置](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_main_graph.py#L768))

- 进入标准执行链。
- 这条链通常会跑：
  - `select_required_sources`
  - `source_dispatch`
  - `tool_executor` / `recommendation_executor`
  - `merge_or_rank`
  - `contract_review`

### `select_required_sources` ([代码位置](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_main_graph.py#L799))

- 选择本轮需要执行的来源。
- 会从 answer contract、tool requirement、evidence requirement 里推导需要哪些 source。

### `source_dispatch` ([代码位置](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_main_graph.py#L845))

- 按当前 source 分发：
  - `tool`
  - `recommendation`
  - 或者回到 `merge_or_rank`

### `rag_executor`（独立 RAG 子图，不再由主图直连）

- 进入独立 RAG 子图。
- 典型内部链路：

```text
build_retrieval_plan -> hybrid_retrieve -> filter_rag -> rerank_rag -> build_evidence_pack -> finalize_rag
```

### `tool_executor` ([代码位置](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_front_b.py#L521))

- 进入工具子图。
- 典型内部链路：

```text
tool_plan -> tool_executor -> finalize_tool
```

### `recommendation_executor` ([代码位置](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/graphs.py#L1147))

- 进入推荐子图。
- 典型内部链路：

```text
prepare_recommendation -> dispatch_shop_analysis -> analyze_one_shop -> reduce_shop_results -> finalize_recommendation
```

### `merge_or_rank` ([代码位置](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_main_graph.py#L919))

- 汇总各来源结果。
- 可能排序、去重、挑选主候选。

### `contract_review` ([代码位置](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_main_graph.py#L937))

- 最终合同审查。
- 审查结果通常会决定：
  - `prepare_retry`
  - `final_answer`

### `prepare_retry` ([代码位置](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_main_graph.py#L949))

- 为下一轮 retry 做准备。
- 主要是把路由状态、重试计数和上下文修正好。

## 实测 case

### `D5-1` 附近推荐

```text
附近有没有推荐的餐厅？
```

实际结果：

- `route_gate.branch = recommendation`
- `required_action = rag_plus_tool`
- `answer_style = multi_shop_recommendation`
- 最终答案以“候选店 A / B + 推荐理由”的形式返回

### `D8-1` 营业状态查询

```text
海底捞水晶城店现在营业吗？
```

实际结果：

- `route_gate.branch = tool`
- `required_action = tool_call`
- `answer_style = open_status_only`
- 最终答案直接收敛到“是否营业”

### `D9-1` 距离查询

```text
海底捞水晶城店离我多远？
```

实际结果：

- `route_gate.branch = rag`
- `required_action = rag_retrieval`
- `answer_style = distance_only`

### `D14-1` 多维度复合查询

```text
海底捞水晶城店环境怎么样，有券吗，离我多远？
```

实际结果：

- `route_gate.branch = rag_plus_tool`
- `required_action = rag_plus_tool`
- `answer_style = facet_multi`
- 这类查询会同时带上静态评价和动态 facet 的约束

### `D13-1` 多轮继承

```text
海底捞水晶城店怎么样？
有券吗？
```

实际结果：

- 第二轮会带着 session 里的店铺语境继续走
- `priority_source = session_context`
- `answer_style = coupon_only`
- 说明 query 合并与 session 记忆确实参与了路由

## 典型 case

### Case 1: 单店点评

例如：

```text
海底捞怎么样
```

常见路径：

```text
query_merge_for_local_life
  -> merged_query_safety
  -> build_answer_contract
  -> target_requirement_router
  -> resolve_target_shop
  -> build_source_contract
  -> complexity_router
  -> workflow_executor
  -> select_required_sources
  -> source_dispatch
  -> tool_executor / recommendation_executor
  -> merge_or_rank
  -> contract_review
  -> final_answer
```

### Case 2: 推荐 + 场景

例如：

```text
适合带爸妈吃饭的餐厅推荐
```

常见路径：

```text
query_merge_for_local_life
  -> merged_query_safety
  -> build_answer_contract
  -> target_requirement_router
  -> prepare_recommendation_context
  -> build_source_contract
  -> complexity_router
  -> workflow_executor
  -> select_required_sources
  -> source_dispatch
  -> recommendation_executor
  -> merge_or_rank
  -> contract_review
  -> final_answer
```

### Case 3: 对比

例如：

```text
海底捞和凑凑哪个好
```

常见路径：

```text
query_merge_for_local_life
  -> merged_query_safety
  -> build_answer_contract
  -> target_requirement_router
  -> resolve_comparison_targets
  -> build_source_contract
  -> complexity_router
  -> workflow_executor
  -> select_required_sources
  -> source_dispatch
  -> tool_executor / recommendation_executor
  -> merge_or_rank
  -> contract_review
  -> final_answer
```

## 重点验证点

下面这些测试最值得看：

- `learning-agent-service/tests/test_workflow_compiled_subgraphs.py`
- `learning-agent-service/tests/test_phase2_response_modes.py`
- `learning-agent-service/tests/test_tools.py`

它们能帮助你确认：

- 本地生活主图节点是否都在 topology 里
- 标准链路是否真的会走到 `workflow_executor`
- `source_dispatch` 是否能按 source 分发到 rag/tool/recommendation
