# Phase 2 实施报告: LLM Structured Semantic Parser

## 范围

本阶段只做 `LLM Semantic Capability Enablement` 的 Phase 2，目标是把本地生活语义解析收敛到“结构化输出 + 可回退 + 可验证”的契约上，不修改主路由分发逻辑，不进入 Phase 3。

## 本次改动

### 1. `local_life_agent/llm/prompts/local_life_parser.md`

- 重写为严格结构化 JSON 提示词。
- 明确要求 LLM 输出与 `SemanticFrame` 对齐的字段。
- 补充了本阶段重点语义边界：
  - `性价比高` 应映射为 `value_for_money`
  - `比较便宜` 应映射为 `relative_price_preference`
  - `附近` 应映射为位置偏好/过滤，而不是比较意图
  - `有券`、`团购`、`现在营业` 等应进入筛选语义
  - `第一家和第二家比一下` 这类才算比较意图
  - `不要烧烤了，推荐咖啡` 属于新任务覆盖或约束更新
  - `算了` 属于取消意图

### 2. `local_life_agent/semantic/intent_parser.py`

- 增强了解析后的结构化校验与回退流程。
- 新增并回填了可观测字段：
  - `parse_source`
  - `semantic_parse_source`
  - `schema_validation_result`
  - `grounding_status`
  - `missing_slot_type`
- 支持三类结果：
  - LLM 结构化结果直接通过校验
  - LLM 原始结果修复后通过校验
  - 结构化结果失败后回退到规则槽位抽取
- 回退结果会显式降置信度，避免把 fallback 伪装成高可信 LLM 结果。

### 3. `local_life_agent/semantic/slot_extractor.py`

- 补充了 Phase 2 所需的兜底语义信号：
  - 比较结构
  - 偏好信号
  - 过滤信号
  - 位置引用
  - 店铺引用
  - 指代引用
  - 新任务覆盖
  - 取消意图
  - 缺失槽位类型
- 保持它作为 fallback / recovery 层，不替代 LLM 的结构化理解能力。

### 4. `local_life_agent/domain/schemas.py`

- 已兼容 Phase 2 的结构化语义字段。
- `SemanticFrame` 现在可以承载：
  - 比较结构
  - 多轮探索阶段
  - 偏好 / 过滤 / 引用信号
  - parse source / grounding / missing slot 等观测字段

### 5. 测试补强

新增和调整了以下测试，覆盖 Phase 2 的语义边界：

- `local_life_agent/tests/test_semantic_parser.py`
  - 验证结构化 LLM 输出能通过 `SemanticFrame` 校验
  - 验证 schema 校验失败会触发低置信度回退
  - 验证 `性价比高` 不会被误判成比较意图
  - 验证 `第一家和第二家比一下`、`这家有券吗`、`算了`、新任务覆盖、探索式多阶段等语义
- `local_life_agent/tests/test_semantic_router_policy_alignment.py`
  - 验证语义解析结果与路由策略保持一致
- `local_life_agent/tests/test_llm_semantic_capability_usage_audit.py`
  - 验证结构化解析的可见性
  - 验证 fallback / recovery 分支的低置信度表现

## 关键语义边界

- `性价比高` 是价格偏好，不是比较意图。
- `比较便宜` 是相对价格偏好，不是店铺比较。
- `这家有券吗` 需要店铺指代和上下文，不应硬编店名。
- `第一家和第二家比一下` 才是比较意图。
- `不要烧烤了，推荐咖啡` 应视为任务覆盖或约束更新，而不是简单改写为原任务。
- `算了` 应进入取消/终止语义，而不是继续追问。

## 验证结果

已通过：

- `python -m compileall local_life_agent`
- `pytest local_life_agent/tests/test_semantic_parser.py -q`
- `pytest local_life_agent/tests/test_semantic_router_policy_alignment.py -q`
- `pytest local_life_agent/tests/test_llm_semantic_capability_usage_audit.py -q`

结果：

- `test_semantic_parser.py`: 37 passed
- `test_semantic_router_policy_alignment.py`: 5 passed
- `test_llm_semantic_capability_usage_audit.py`: 9 passed

## 结论

Phase 2 已完成。当前语义解析链路已经具备：

- 结构化 LLM 输出契约
- schema 校验
- 失败回退
- 可观测 parse source
- 更明确的本地生活语义边界

后续如果进入 Phase 3，可以在此基础上继续做路由层语义边界收敛和主流程增强。
