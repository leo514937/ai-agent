# Day 10：完成 Day 4 Tool Harness 与实时信息契约物理验收 进度文档

## 当天目标回顾

```text
1. 确认 Day 4 (Tool Harness 与实时信息契约增强) 改造是否全部落地。
2. 从真实的 `/internal/v1/chat/stream` 流式接口做验收，核实实时数据强隔离、最新意图优先、多商家推荐隔离等关键场景。
3. 执行相关的 Harness 单元测试和流式 Chat 集成测试，保证 100% 绿灯通过。
4. 输出/更新验收报告 Markdown 到 done/rag&toolcall&memory_context_harness_upgrade/ 目录下。
```

---

## 已完成改造与运行清单

### 1. 落地情况排查 (P0)
排查发现 Day 4 的架构与功能已经完整落地到以下模块中：
* `realtime_contract.py`：定义了 `RealtimeContract`，包含了 coupon (get_coupon_list)、open_status (check_open_status)、distance_eta (get_distance_eta) 等强实时的契约配置及标准降级提示文案。
* `tool_planner.py`：实现 `LocalLifeToolPlanner.plan`，输入 `AnswerContract`、`latest_turn_message`、`current_intent` 等，决定所需调用的实时工具，支持单店模式和多商家推荐候选逐店调用模式。
* `tool_result_normalizer.py`：实现 `normalize_tool_result`，将工具输出标准化为包含 `status` (success, empty, timeout, error 等)、`fetched_at`、`is_realtime`、`confidence` 的 `ToolResult` 结构。
* `subgraph.py`：将 tool planner、normalizer 与 Graph 执行流深层结合，在 `per_candidate` 模式下并行拉取推荐店的实时状态与折扣券。

### 2. 执行回归测试与物理验收 (P0)
已执行的本地生活测试组件均完全通过：
* **Day 4 工具/契约独立单元测试** (`pytest tests/local_life/tools/`)：**10 passed**
  * `test_realtime_contract.py`：验证 coupon/open_status 强契约与单店 planning 功能。
  * `test_tool_degradation.py`：验证在 timeout/error 下是否返回标准降级文案。
  * `test_tool_harness_coupon.py` / `test_tool_harness_open_status.py`：验证 coupons 数量、是否有券、营业状态的标准化行为。
  * `test_tool_latest_turn_priority.py`：验证推荐作用域不被前一轮单店所锁定。
* **Day 4 Chat 接口物理验收** (`pytest tests/local_life/test_day4_tool_realtime_contract_chat.py`)：**3 passed**
  * 调用 `/internal/v1/chat/stream` 真实的 API 接口。
  * 证明了从最新消息换店/换意图能够彻底过滤掉前一轮多余的 context facets 干扰。
* **全量 local_life 集成测试** (`pytest tests/local_life/`)：**86 passed**
  * 全部 86 个用例均 100% 绿灯通关，全链路没有 regression 风险。

### 3. 生成与归档验收报告 (P0)
* **文件路径**：[acceptance_report.md](file:///d:/javacode/hm-dianping/done/rag&toolcall&memory_context_harness_upgrade/acceptance_report.md)
* **内容升级**：在原 Day 1 & Day 2 的基础上，融合了 Day 3 RAG 脏数据治理和 Day 4 Tool Harness / 实时契约的所有验收场景与断言指标，以 GitHub Alerts 加以修饰，提供最完整的全栈升级验收证据。

---

## 下一步行动计划

1. **Day 5 状态机图更新筹备**：如有需要，后续可以针对 Day 5 (LangGraph 工作流升级) 进行检查和验收。
