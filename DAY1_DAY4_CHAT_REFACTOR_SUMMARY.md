# Day1-Day4 Chat 验收收口改动说明

这份文档记录本轮 local life 的 Day1-Day4 收口改动，重点是：
- 统一 `context` 的目标店优先级，避免旧店串入新店。
- 统一 `harness` 与 chat `stream` 的验收语义，让旧验收键和新 `phase*trace` 同时可用。
- 只以用户端 `/internal/v1/chat/stream` 作为最终验收入口。

## 一、改动目标

本轮不是新增业务能力，而是把 Day1-Day4 的 chat 验收完全收口：
- Day1 关注目标店继承和显式覆盖。
- Day2 关注 answer contract 和 facet 串味控制。
- Day3 关注 coupon / open-status 的工具执行和澄清恢复。
- Day4 关注 single-shop RAG 和 recommendation RAG 的模式稳定性。

## 二、主要改动点

### 1. 工作流入口改成统一 graph 主路径

- `[chat_workflow.py](D:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/use_cases/chat_workflow.py)`  
  现在 local life chat 默认走统一 workflow runner，而不是继续把主路径挂在 legacy `LocalLifeSubgraph` 上。
- `[builder.py](D:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/builder.py)`  
  LangGraph runner 继续负责主编排，并在最终阶段写回 `phase5_trace.runner_kind = langgraph` 等运行时信息。
- `[settings.py](D:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/config/settings.py)`  
  补了 local life graph 的开关配置，保持 graph 主路径可控。

### 2. 在最终 chat SSE 里补兼容指标

- `[adapters.py](D:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters.py)`  
  在 `compose_answer` 和 `emit_final` 的出口层统一组装最终 metrics。
- 本轮回写的关键兼容字段包括：
  - `target_shop.source`
  - `single_shop_mode`
  - `answer_contract`
  - `rag_mode`
  - `coupon_result`
  - `facet_result_bundle`
  - `local_life_execution_contract`
- 保留的新主记录仍然是：
  - `phase0_trace`
  - `phase1_trace`
  - `phase2_trace`
  - `phase4_trace`
  - `phase5_trace`

### 3. 收紧上下文优先级

- `[target_shop_policy.py](D:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/local_life/target_shop_policy.py)`  
  统一目标店优先级：
  - 显式店名/ID
  - 指代词会话继承
  - 当前 session topic
  - RAG fallback
- `[entity_resolver.py](D:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/local_life/entity_resolver.py)`  
  进一步把显式实体、上下文引用、session 历史和候选店的解析链路收束起来，减少“上一轮店名污染下一轮”的情况。
- `[route_review.py](D:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/local_life/route_review.py)`  
  调整 coupon / open-status / nearby recommendation 的路由顺序，避免显式店名场景被误澄清。

### 4. 收敛回答模式

- `[answer_contract.py](D:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/local_life/answer_contract.py)`  
  把 coupon-only、open-status-only、distance-only、single-shop-review、facet-multi、recommendation 等模式固定下来。
- `[response_builder.py](D:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/local_life/response_builder.py)`  
  在最终回答层严格按 answer contract 做输出约束，减少 facet 串味。

### 5. 统一 chat 验收 harness

- `[harness.py](D:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/testing/harness.py)`  
  统一 phase trace 的抽取语义，让 chat 验收和离线 harness 读到同一套 trace 约定。
- `[chat_test_client.py](D:/javacode/hm-dianping/learning-agent-service/tests/local_life/chat_test_client.py)`  
  保持所有 Day1-Day4 验收都从 `/internal/v1/chat/stream` 走，不再只看内部函数。

## 三、验收结果

本轮已通过的 chat 级验收：
- Day1-Day4 全量测试：`23 passed`
- 验收入口：`/internal/v1/chat/stream`

已验证的重点场景包括：
- 显式单店查询
- 多轮显式换店
- 指代词继承旧店
- coupon-only
- open-status-only
- coupon + open-status 双工具
- 澄清与记忆恢复
- single-shop RAG
- recommendation RAG

## 四、补充说明

- 这轮的核心不是“把 legacy 代码删掉”，而是让 graph 主路径与旧验收语义对齐。
- 旧验收键保留为兼容层，新规范仍以 `phase*trace` 为主。
- 当前仓库里还有很多与本任务无关的既有改动和日志文件，这份说明只覆盖本次 Day1-Day4 收口工作。
