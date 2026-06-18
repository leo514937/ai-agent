# Complex Plan Execute 路径分析

> 目标：说明复杂任务为什么会进入计划执行子图，以及执行、重试、复盘、再规划是怎么连起来的。

> 实测结论：`plan_execute` 这条路径在当前 chat 接口实测里还没有自然命中。我们已经在代码和单测里确认它是存在的，但在本次端到端输入集里，复杂查询更多是被归类成 `recommendation`、`rag_plus_tool` 或 `tool`，并在 `phase3_trace` 里显示 `task_plan_status = skipped`。

## 适用节点

- `complexity_router`
- `planner_node`
- `plan_validator`
- `plan_executor`
- `execute_plan_step`
- `collect_step_result`
- `all_steps_done?`
- `complex_review`
- `repair_answer`
- `final_with_limitations`

## 主流程

```text
complexity_router
  -> planner_node
  -> plan_validator
  -> plan_executor
  -> execute_plan_step
  -> collect_step_result
  -> all_steps_done?
       -> execute_plan_step
       -> complex_review
            -> final_answer
            -> repair_answer
            -> final_with_limitations
            -> execute_plan_step
            -> planner_node
```

## 这个路径什么时候出现

当问题需要多步操作、多个子任务、或者需要明确的计划结构时，就会走 `complex`。

典型场景：

- 需要先查再比
- 需要先规划再执行
- 需要一步一步收集结果
- 需要人工审批的流程

但要注意：在当前实现里，`plan_execute` 不是“只要问题复杂就一定进入”。它还需要满足更严格的组合条件。

### `plan_execute` 的代码门槛

从 `learning-agent-service/src/learning_agent_service/application/router/phase4_plan.py` 看，至少要同时满足：

- `execution_mode == plan_execute`，或者
- `required_action == rag_plus_tool`
- `required_facets` 数量足够
- 里边要同时包含 `coupon` 和 `open_status`
- 还要再带上一个静态 facet，比如 `scene_fit`、`recommendation_reason` 或 `shop_detail`

所以“复杂”不等于“会进 plan_execute”。

## 每个节点做什么

### `planner_node`

- 生成执行计划。
- 计划会拆成多个 step。

### `plan_validator`

- 检查计划是否合法、是否可执行。

### `plan_executor`

- 准备开始执行当前 plan。
- 也会处理审批类或状态初始化类逻辑。

### `execute_plan_step`

- 执行当前 step。
- 这个节点会再分到不同类型：

```text
compose -> compose_draft
merge   -> merge_executor
rank    -> rank_executor
recommend / compare / multi -> recommendation_executor
tool / coupon / open / book / reserve / search / lookup -> tool_executor
otherwise -> tool_executor_complex
```

### `collect_step_result`

- 收集每一步的执行结果。

### `all_steps_done?`

- 判断 plan 是否跑完。
- 没跑完就回到 `execute_plan_step`。
- 跑完就进 `complex_review`。

### `complex_review`

- 复杂任务的最终审查节点。
- 它可能输出：
  - `final_answer`
  - `repair_answer`
  - `final_with_limitations`
  - `execute_plan_step`
  - `planner_node`

### `repair_answer`

- 对答案做修复，然后回到 `final_answer`。

### `final_with_limitations`

- 当结果不完整但又能给出有限答案时，输出带限制说明的结论。

## 典型 case

### Case 1: 多步推荐任务

例如：

```text
帮我推荐几家适合约会的火锅店，还要看距离和优惠
```

这种很容易进入 `planner_node`，因为它同时包含：

- 场景
- 多候选
- 距离
- 优惠

### 实测反例：`D5-1` 和 `D14-1`

在当前 chat E2E 中，下面这些 query 都没有真正进入 `plan_execute`：

- `附近有没有推荐的餐厅？`
- `海底捞水晶城店环境怎么样，有券吗，离我多远？`
- `推荐一家适合约会、现在营业、最好有券的火锅店`

它们在 `phase3_trace` 里分别更常见的是：

- `task_plan_status = skipped`
- `task_plan_failure_reason = not_rag_plus_tool`
- `task_plan_failure_reason = missing_dynamic_combo`

也就是说，这些 query 在当前版本里更像是：

```text
recommendation / rag_plus_tool / tool
```

而不是：

```text
plan_execute
```

### Case 2: 需要再规划

如果 `complex_review` 发现当前 plan 不够，`need_replan = true`，就可能回到：

```text
complex_review -> planner_node
```

### Case 3: 需要补步

如果 step 没做完，就会继续：

```text
all_steps_done? -> execute_plan_step
```

### Case 4: 只得到有限答案

如果执行结果部分可用，但不足以给强结论，就会走：

```text
complex_review -> final_with_limitations
```

## 与测试的对应关系

建议看：

- `learning-agent-service/tests/test_workflow_compiled_subgraphs.py`
- `learning-agent-service/tests/test_tools.py`
- `learning-agent-service/tests/test_plan_execution_runtime.py`
- `learning-agent-service/tests/test_phase3_task_plan.py`

其中已经覆盖了：

- plan 子图 topology 是否存在
- step 执行后是否进入 collect/review
- 复杂结果是否会进入 repair / degrade / replan 分支
- `plan_execute` 的单测执行路径

如果你现在只看 chat E2E，结论会更保守：

- `plan_execute` 结构存在
- `plan_execute` 单测存在
- 但本次实测输入集里还没自然命中
