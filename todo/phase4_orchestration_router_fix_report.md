# Phase 4 OrchestrationRouter 修复报告

## 结论

当前 **不可以重新验收 Phase 4，仍有阻塞项**。

## 已完成修复

1. 新增独立 shadow 节点 `orchestration_router_shadow`
   - 新文件：[local_life_agent/engine/subgraphs/orchestration_router_shadow.py](D:\javacode\hm-dianping\local_life_agent\engine\subgraphs\orchestration_router_shadow.py)
   - 该节点仅负责写入 shadow routing 结果，不改写主链路执行路径。
   - 节点通过 `route_orchestration()` 生成 `orchestration_decision`、`workflow_name`、`response_mode` 等观测字段。

2. 将 shadow 路由从 `planning_subgraph` 中拆出
   - `planning_subgraph` 不再内联生成 orchestration shadow patch。
   - Phase 4 的二级路由现在由独立节点承载。

3. 补强 orchestration policy / normalize / validator / fallback
   - `normalize_route_task()` 增补了 forbidden / clarification / exploration / deterministic / discovery 等分支。
   - `validate_orchestration_decision()` 增强了策略一致性校验。
   - `route_orchestration()` 增加异常安全回退，router 抛错时会落到 `clarification_fallback`，并写入错误码。
   - 补齐 `forbidden` policy，避免禁限域输入被错误归到澄清兜底。

4. 图结构已插入 shadow 节点
   - `understanding_subgraph -> orchestration_router_shadow -> planning_subgraph`
   - 相关 graph handlers、route map、node table、state fields、trace stage 都已同步。

5. 测试已补齐
   - 新增/调整了 orchestration router 单测，覆盖：
     - recommendation
     - deterministic tool
     - exploration planning
     - clarification fallback
     - forbidden scope
     - shadow node 独立性
     - router exception fallback
   - 为全链路覆盖矩阵补上了 `orchestration_router_shadow`。
   - `trace_observability` 的 audit 期望也同步到了新节点。

6. 测试隔离增强
   - 在 `tests/conftest.py` 中加入了 session store 的自动重置，避免全局会话状态互相污染。

## 已验证内容

### 静态编译

命令：

```bash
python -m compileall local_life_agent
```

结果：

- 通过

### 路由单测

命令：

```bash
pytest local_life_agent/tests/test_orchestration_router.py -q
```

结果：

- 9 passed

### 图结构单测

命令：

```bash
pytest local_life_agent/tests/test_05_graph.py -q
```

结果：

- 88 passed

### 观测单测

命令：

```bash
pytest local_life_agent/tests/test_trace_observability.py -q
```

结果：

- 5 passed

## 仍然存在的阻塞项

在以下回归组中，仍然有 3 个失败：

```bash
pytest local_life_agent/tests/test_target_resolve_candidate_set.py \
       local_life_agent/tests/test_comparison_flow.py \
       local_life_agent/tests/test_recommendation_flow.py \
       local_life_agent/tests/test_single_shop_multifacet.py \
       local_life_agent/tests/test_single_coupon_flow.py \
       local_life_agent/tests/test_p2_end_to_end.py \
       local_life_agent/tests/test_comprehensive_graph_e2e.py -q
```

当前结果：

- `3 failed, 96 passed, 1 xfailed, 1 xpassed`

失败点分别是：

- `test_compare_first_item_and_explicit_shop`
- `test_recommendation_failure_does_not_pollute_session`
- `test_fuzzy_shop_does_not_call_coupon_tool`

它们具有明显的顺序相关特征：单独运行时可通过，但串入更大的回归组时会失败。当前已先完成 Phase 4 router 收口与独立 shadow 节点改造，但这 3 个 order-sensitive 失败仍然阻止“重新验收 Phase 4”。

## 备注

- 目前 Phase 4 的路由结构已经按“独立 shadow 节点”完成拆分。
- 但在未消除上述 3 个回归失败前，不应宣布 Phase 4 重新验收通过。
