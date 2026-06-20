# 10. 加 Trace、Metrics、Eval 回归

## 目标
建立全局追踪能力，构建自动化、结构化的效果评估闭环 (EvalCaseRunner)，以保障在后续维护中系统链路执行不错位、能力不退化。

## 实现细节要求

### 1. 全局追踪 TraceLogger 与返回值 DTO
- 保证最初在 Step 00 定义的 `run_agent()` 返回的 DTO 里能包含 `trace_id` 及 Debug 用的 `execution_plan`, `semantic_frame`, `tool_results` 结构快照。这为前端预留调试窗口。
- 日志文件必须结构化、可搜索。

### 2. 结构化断言体系 (Eval 用例标准)
禁止单纯只做“生成的文本符合大意”的模糊评估。必须在 `tests/cases/` 目录下提供结构化的断言期望 (YAML 或 JSON 驱动)：
```yaml
id: single_coupon_ok
input: "海底捞水晶城店有券吗"
expect:
  top_intent: "local_life"
  task_type: "coupon_query"
  merchant_mentions: ["海底捞水晶城店"]
  resolved_target_status: "RESOLVED"
  required_tools: ["resolve_shop", "get_coupon_list"]
  forbidden_tools: ["search_shops"]  # 严禁错乱调用了全局搜索
  answer_must_contain_any:
    - "有券"
    - "暂无可用券"
    - "暂时无法确认"
  answer_must_not_contain:
    - "我猜"
    - "应该有"
```

### 3. 指标采集 (MetricsCollector)
监控各项 `error_code` 在大样本下的占比分布，重点观测 `TOOL_TIMEOUT`, `AMBIGUOUS_SHOP`, `ANSWER_VERIFIER_FAILED` 的频次。

## 本阶段完成标准 (Definition of Done)
1. `TraceLogger` 完善生效，每一笔交互都能串起一个完整的树状流转文件或记录。
2. 结构化用例集合加载工具搭建完成，支持上述 YAML 配置的精确断言解析。
3. **完成测试**：`tests/test_eval_runner.py` 跑通。全量运行基准测试集覆盖以上断言需求，验证 `forbidden_tools` 拦截有效，全部 Pass 即宣告 10 阶段及本版本 Agent 的整体验收完毕。

## 阶段完成后的收尾

- 跑全量回归和 trace 完整性检查。
- 确认每轮都有可追踪链路、指标能采集、eval case 能稳定断言。
