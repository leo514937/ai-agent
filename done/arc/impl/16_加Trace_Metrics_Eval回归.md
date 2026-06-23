# 10. 加 Trace、Metrics、Eval 回归 (已与代码同步)

## 目标
建立全局追踪与调试诊断能力，构建自动化、结构化的效果评估闭环与回归体系，以保障在后续维护和真实 LLM 切换中系统链路不退化。

## 当前实现机制与代码结构

### 1. 全局追踪与调试 DTO (DebugInfo & AgentResponse)
- **位置**: [agent.py](file:///d:/javacode/hm-dianping/local_life_agent/agent.py)
- **实现细节**:
  - `run_agent()` 统一返回 `AgentResponse` 结构体，其中包含 `answer_text`, `trace_id`, `session_id`, `clarification`, `cards`。
  - 在 `config.DEBUG_ENABLED` 开启时，`AgentResponse.to_dict()` 会额外传出结构化的调试快照 `debug` 字段 (`DebugInfo`)，包括：
    - `execution_trace`: 完整记录本轮交互中流经的所有 Graph 节点名称与状态快照（来自于 state 中的 `event_log`）。
    - `semantic_frame`: 语义解析后的结构化槽位与意图快照。
    - `execution_plan`: 工具调用执行计划结构快照。
    - `tool_results`: 详细工具结果集。
    - `evidence_pack`: 提炼出的证据包事实结构。
    - `session_state_before` & `session_state_after`: 执行前后的会话 Session State 快照。
    - Verbalizer/Verifier 调试指标: 包括 `answer_source` ("llm_verbalizer", "template_fallback", "template"), `answer_fallback_reason`, `llm_verbalizer_error`, `llm_verbalizer_violation` (拦截违规标记)。

### 2. 节点级事件日志生成 (_log)
- **位置**: [graph_builder.py](file:///d:/javacode/hm-dianping/local_life_agent/engine/graph_builder.py)
- **实现细节**:
  - 设计了统一的辅助记录函数 `_log(state, node, **extra)`，每次 Graph 节点处理器执行时，自动将本节点产生的事件与特有字段（例如 `status`, `query`, `tool_calls`, `decision` 等）追加到 `event_log` 列表中。这为整条执行链路的追溯和 Debug 提供了不可磨灭的可检索证据链。

### 3. 流式事件流与跟踪协议 (Streaming Event Protocol)
- **位置**: Java 端的 `AiAssistantStreamService`
- **事件细节**:
  - 已经接入并补全了标准的 14 种流式事件发射方法，可在 Agent 运行的生命周期中逐一对外发出事件推送，满足前端的实时加载与追踪展示需求：
    - `input_normalized` / `pending_clarification_checked` / `hard_guard_hit`
    - `semantic_frame_ready` / `target_resolved` / `clarify_requested`
    - `task_planned` / `tool_call_started` / `tool_call_finished`
    - `evidence_built` / `answer_plan_built` / `answer_delta` / `final`

### 4. 结构化评估案例集 (Eval Cases)
- **位置**: [eval/local_life/](file:///d:/javacode/hm-dianping/eval/local_life/) 目录下
- **用例细节**:
  - 提供了 `rag_eval_cases.jsonl` 和 `rag_dirty_cases.jsonl`，用于驱动 RAG/Tool 的自动化场景效果评估。
  - 用例规定了 `case_id`、用户查询 `query`、上下文 turns、期望路由 `expected_route`、期望 RAG 模式 `expected_rag_mode`、期望命中的 `expected_shop_id`、期望分析的 `expected_facets` 以及禁止透露的商户 `forbidden_shop_ids`、期望包含的关键词 `expected_keywords` 等。这套结构化断言体系支持对系统的槽位提炼和 RAG 防安全泄露能力进行全量自动化回归审计。

### 5. 测试回归覆盖
- **自动化测试文件**:
  - [test_streaming_event_contract.py](file:///d:/javacode/hm-dianping/local_life_agent/tests/test_streaming_event_contract.py): 验证 trace started, ack 等各种 streaming event 传输协议序列化与内容完整性。
  - [test_tool_backend_observability.py](file:///d:/javacode/hm-dianping/local_life_agent/tests/test_tool_backend_observability.py): 验证工具返回结果中正确记录了使用的 tool backend 和 backend source ("mock" / "java_api")。
  - [test_real_llm_contract.py](file:///d:/javacode/hm-dianping/local_life_agent/tests/test_real_llm_contract.py): 验证真实大模型客户端的 metadata trace 追踪是否工作，检验 answer source、llm used、fallback 标志以及 reference resolver source 是否如实透传。
