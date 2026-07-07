# 第一层测试计划

本计划只列测试覆盖和验收标准，不编造已存在的新增测试文件内容。

## 现有可复用测试

当前仓库里已经有下面这些相关测试文件，可以优先复用：

- `local_life_agent/tests/test_input_layer.py`
- `local_life_agent/tests/test_hard_guard.py`
- `local_life_agent/tests/test_top_intent_router.py`
- `local_life_agent/tests/test_active_turn_resolver.py`
- `local_life_agent/tests/test_context_recovery_clarification.py`
- `local_life_agent/tests/test_slot_extractor_boundaries.py`
- `local_life_agent/tests/test_p5_session_state_writeback.py`
- `local_life_agent/tests/test_trace_observability.py`
- `local_life_agent/tests/test_phase1_architecture_boundaries.py`
- `local_life_agent/tests/test_p12_deadline_budget_freshness_ttl.py`

> ⚠️ 注意：仓库中不存在 `top_intent_router_handler.py`。`_h_top_intent_router` 实际定义在 `intake_guard_router.py:220-268`，`test_top_intent_router.py` 测试文件实际测试的是此函数。

这些文件中已经能看到与 pending、topic_switch、greeting、capability、session、trace、slot_extractor、freshness 相关的用例痕迹。

## 建议新增测试

如果当前没有对应的更细粒度测试，建议补以下文件：

- `TODO_ADD_TEST: local_life_agent/tests/test_first_layer_contextualization.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_first_layer_focus_context.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_first_layer_contracts.py`
- `TODO_ADD_TEST: local_life_agent/tests/test_first_layer_trace.py`

## 必覆盖 case

### 1. 空输入

- 目标：空输入不会继续进入理解链路
- 断言：
  - `receive_input` / `basic_validate` 返回 `EMPTY_INPUT`
  - 不应触发后续理解、规划、执行
  - 不应错误写入会话

### 2. “你好，附近有火锅吗”

- 目标：不能被 greeting terminal 掉
- 断言：
  - `hard_guard` 因包含业务词而放行
  - `top_intent` 进入 local_life 分支，而不是纯 greeting

### 3. “你能做什么，顺便查海底捞有券吗”

- 目标：不能被 capability terminal 掉
- 断言：
  - `hard_guard` 因业务词放行
  - `top_intent` 不应把整句直接终止为 capability-only

### 4. 上一轮推荐火锅后，用户说“便宜一点的呢”

- 目标：生成 contextualized turn
- 断言：
  - contextualizer 识别为 follow-up refinement / constraint carryover
  - 保留原始文本和 normalized_text
  - 不得编造店铺事实

### 5. 上一轮推荐列表后，用户说“第二个怎么样”

- 目标：通过 FocusContext 定位第二个
- 断言：
  - 能从当前焦点集合中解析 ordinal reference
  - 选择顺序明确、可解释

### 6. 上一轮澄清 A/B 店后，用户说“第二个吧，看看有没有券”

- 目标：识别为 `restore_with_delta`
- 断言：
  - 先恢复到 pending clarification 的候选
  - 再追加 coupon facet / constraint delta
  - 不应把新增 facet 丢掉

### 7. `slot_extractor` 不应输出最终 `shop_id`

- 断言：
  - 只输出 anchor / mention / reference，不直接决策 shop_id

### 8. `slot_extractor` 不应覆盖 `task_type`

- 断言：
  - slot extractor 只补充锚点或提示，不直接重写业务路由

### 9. `hard_guard` 的 business_patterns 不应成为本地生活路由权威

- 断言：
  - 命中业务词只代表“允许继续”，不能代表“已经是 local_life”

### 10. `final_response` 应主要由 response_subgraph 生成

- 断言：
  - 第一层最多写 directive / short fallback
  - 不能让入口层把最终自然语言文本当成权威回答

### 11. `error_code` 应能追踪到具体 stage

- 断言：
  - 同一个错误在 `basic_validate`、`top_intent_router`、`semantic_parse`、`frame_validator` 中应能带 stage 来源

### 12. 营业状态、距离、券等实时结果跨轮复用时必须有 freshness 判断

- 断言：
  - 结果对象或 session meta 必须带 freshness 信息
  - 过期结果不能直接复用

### 13. `state_update_plan` 是唯一 session 写入口

- 断言：
  - 运行时只有 `_h_persist_session` 调用 `store.save(...)`
  - 其他第一层节点只改 GraphState，不直接改 session store

### 14. 第一层 trace 能解释每个路由决策

- 断言：
  - 能看到 intake、guard、active_turn、top_intent、clarification、context_recovery 的决策原因
  - trace 里能重建"为什么进 local_life / 为什么进 clarification / 为什么终止"

### 15. `_should_treat_as_topic_switch` 双份实现行为一致

- 背景：`active_turn_resolver.py:539-595` 和 `clarification.py:478-531` 各有一份独立副本
- 断言：
  - 对相同输入，两处 `_should_treat_as_topic_switch` 返回结果一致
  - 关键列表的任何修改需同步两处（或重构为单一共享函数）

### 16. `slot_extractor` 跨层调用边界可审计

- 背景：`slot_extractor.extract_slots` 被 `understanding_subgraph.py:206`、`clarification.py:541`、`active_turn_resolver.py:219`、`intent_parser.py:618` 四处调用
- 断言：
  - 每一处调用记录调用来源到 trace
  - `understanding_subgraph._h_slot_extractor` 的调用不覆盖 `task_type`
  - 其他三处调用如果覆盖 `task_type`，需有显式记录

### 17. `state_update_plan._h_persist_session` 额外写逻辑应可见

- 背景：`state_update_plan.py:160-177` 有两段不受 `SessionWriteDirective` 管控的 `comparison_targets` 写操作
- 断言：
  - 测试验证 `_h_persist_session` 执行后 `session_state.comparison_targets` 的变化可追溯
  - 额外写逻辑应记录到 trace

### 18. `hard_guard` 不应双重 normalize

- 背景：`_h_hard_guard`（`intake_guard_router.py:207-217`）传入 `normalized_text`，但 `check_hard_guard`（`hard_guard.py:82`）内部重新调用 `normalize_text`
- 断言：
  - 当 input 已经是 `normalized_text` 结果时，`check_hard_guard` 不应产生不同的判定结果
  - 若设计需保留内部 normalize，需注释说明理由

### 19. `pending_clarification` 与 `clarification_request` 同步一致性

- 背景：`_h_load_session`（`intake_guard_router.py:167`）将同一对象赋值给两个字段
- 断言：
  - 任何节点清空 `pending_clarification` 时，必须同时清空 `clarification_request`
  - 反向同理
  - 测试覆盖 restore/topic_switch/cancelled/expired/invalid/out_of_range 六种分支

### 20. `load_session` 副作用隔离

- 背景：`_h_load_session`（`intake_guard_router.py:153-177`）除了从 store 读取 session 外，还直接写 15+ 个 GraphState 字段（`session_state`、`current_shop`、`last_recommendation_list`、`pending_clarification`、`clarification_request` 等）
- 断言：
  - 测试能区分"纯加载"vs"字段展开"两个阶段
  - 空 session（新用户）不应产生非预期的字段默认值

## 建议回归顺序

1. 先跑现有测试里与第一层最接近的文件：
   - `test_input_layer.py`
   - `test_hard_guard.py`
   - `test_top_intent_router.py`
   - `test_active_turn_resolver.py`
   - `test_context_recovery_clarification.py`
   - `test_p5_session_state_writeback.py`
   - `test_trace_observability.py`
2. 再补 `TODO_ADD_TEST` 列出的第一层专用测试
3. 最后把 architecture boundary tests 接到 CI / 回归入口

## 验收标准

- 空输入不进入理解链路
- mixed greeting / business intent 不被误终止
- follow-up / ordinal / clarification delta 有明确上下文恢复路径
- `slot_extractor` 边界收敛为 anchor-only
- `final_response` 和 `error_code` 的来源可追踪
- session 写回只有一个入口
- 第一层 trace 可解释每个路由决策
- `_should_treat_as_topic_switch` 双份实现行为一致
- `slot_extractor` 跨层调用边界可审计
- `state_update_plan` 额外写 comparison_targets 的逻辑可追溯
- `hard_guard` 无双重 normalize
- `pending_clarification` 与 `clarification_request` 始终同步
- `load_session` 副作用与纯加载阶段隔离

