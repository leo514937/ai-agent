# 0. 冻结 MVP 范围和测试用例

## 目标
明确当前版本的边界与约束，定义系统的代码目录结构、主执行总控流程，并提供验收测试用例，作为全量系统的基准参考。

## 实现细节要求

### 0. 实施边界说明
- 这份计划描述的是一个**独立的本地生活 Agent 运行时**，逻辑目录以 `local_life_agent/` 为主。
- 当前仓库里的 `com.hmdp.ai` 代码只是既有接入壳和兼容层，不应把这份计划直接混写进现有远端代理实现。
- 如果必须落在同一仓库，也应当以独立子模块或独立包隔离，避免和现有 `AiAssistantService` / `AiAssistantStreamService` 的职责混叠。

### 1. 核心约束与边界
- **输入边界**：当前仅支持纯文本输入。不支持语音、图片、地图选点、卡片等。预留 `pending_clarification` 支持文本序号（如回复“1”）。
- **位置边界**：使用全局固定 Mock 数据（"北京邮电大学", lat: 39.9609, lng: 116.3581）。
- **用户边界**：使用固定 Mock 数据。禁止大模型编造用户真实消费历史。
- **数据获取边界（核心防幻觉约束）**：所有店铺、券、营业状态、距离等事实**仅能通过 ToolCall 获取**，不使用 RAG。禁止大模型编造店铺与相关事实信息。

### 2. 代码目录结构和模块落点建议
为保证工程规范，建议建立以下统一目录架构：
```text
local_life_agent/
  config.py               # 统一配置（并发、超时、限制、重试、预算等）
  domain/                 # 第1步：全局Schema
    schemas.py
    enums.py
    state.py
  llm/                    # 第3步：大模型统一防腐层与提示词
    client.py
    json_parser.py
    prompts/
  input/                  # 第3步：接入与基础校验
    receiver.py
    normalizer.py
    hard_guard.py
  semantic/               # 第3-6步：语义理解与槽位抽取
    intent_parser.py
    slot_extractor.py
    frame_validator.py
  target/                 # 第3-7步：目标解析与多轮指代
    context_recovery.py
    reference_resolver.py
    shop_resolver.py
    clarification.py
  planning/               # 第4-8步：任务决策与工具编排
    task_router.py
    facet_planner.py
    execution_plan_builder.py
    ranking_policy.py
    comparison_planner.py
  tools/                  # 第2步：工具执行层
    registry.py
    gateway.py
    executor.py
    mock_tools.py
    normalizer.py
    retry.py
    circuit_breaker.py
  answer/                 # 第4-9步：回答与校验
    evidence_builder.py
    answer_plan_builder.py
    generator.py
    verifier.py           # 基础(步骤4)与增强(步骤9)校验
    final_response_builder.py
    state_update_planner.py
  observability/          # 第10步：观测与评测
    trace.py
    metrics.py
    eval_runner.py
  tests/
    cases/
  mock_data/              # 测试依赖的静态假数据
    shops.json
    coupons.json
```

### 3. 系统总控执行顺序 (主流程图)
系统真实运行时的节点顺序如下（**特注：`pending_clarification` 优先级极高，避免被 HardGuard 拦截**）：
```text
receive_input
  ↓
load_session_state
  ↓
check_pending_clarification  <-- 必须优先检查，若命中直接跳过常规解析进入恢复流程
  ↓
basic_input_validate
  ↓
normalize_text
  ↓
hard_guard
  ↓
top_intent_router
  ↓
local_life_semantic_parse & slot_extract
  ↓
context_recovery
  ↓
target_resolve (如 resolve_shop)
  ↓
clarify_decide
  ↓
task_plan & facet_plan (生成 ExecutionPlan)
  ↓
tool_execute (Gateway 发起单次或批量并发)
  ↓
evidence_build
  ↓
answer_plan_build
  ↓
answer_generate
  ↓
answer_verify (若失败则 rewrite/fallback)
  ↓
final_response_build
  ↓
state_update_plan
  ↓
persist_session_state
  ↓
emit_response
```

### 4. 统一配置管理 (config.py)
所有工程与预算参数**严禁写死在代码中**，集中管理：
- `max_concurrency = 8`
- `deadline_ms = 6000`
- `max_tool_calls = 40`
- `search_limit = 20`
- `recommendation_candidate_top_k = 8`
- `recommendation_final_top_k = 3`
- `recommendation_enrich_tools = ["get_shop_detail", "check_open_status", "get_coupon_list"]`
- `comparison_full_detail_shop_limit = 3`
- `comparison_focused_shop_limit = 5`
- `comparison_max_shop_limit = 5`
- `max_rewrite_attempts = 2`
- `llm_timeout_ms = 3000`
- `tool_default_timeout_ms = 2000`
- `mock_location = {"name": "北京邮电大学", "lat": 39.9609, "lng": 116.3581}`
- `llm_confidence_threshold = 0.8`
- `clarification_ttl_seconds = 300`
- `debug_enabled = True`  # 生产环境置为 false

### 5. 主流程返回 DTO 设计与状态转移
系统主流程除了遵循[Agent 状态转移与路由决策表](./02_状态转移与路由决策表.md)，`run_agent(input_text, session_id)` 的返回必须是标准 DTO，为后续调试和前端预留空间：
```json
{
  "answer_text": "...",
  "trace_id": "...",
  "session_id": "...",
  "clarification": null,
  "cards": [],
  "debug": {
    "semantic_frame": {},
    "execution_plan": {},
    "tool_results": []
  }
}
```
**注**：`debug` 字段仅在 `config.debug_enabled == True`（开发环境）时全量返回，生产环境只返回 `trace_id` 及空字典，防止数据外泄。

## 本阶段完成标准 (Definition of Done)
1. 项目代码目录框架 `local_life_agent/` 初始化完毕，包含所需的 `llm`, `mock_data`, `config.py` 等。
2. 明确主流程编排函数 `run_agent` 的空壳占位与返回 DTO。
3. `config.py` 内定义好了所有要求的常量约束。

## 阶段完成后的收尾

- 冻结边界和验收口径，确认这次 Agent 的输入、输出、能力范围不会再变。
- 如果范围还不清楚，先改文档，不要进代码。
