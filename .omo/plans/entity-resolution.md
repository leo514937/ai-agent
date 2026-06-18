# 实体解析链路重构：从不透明 shop_name 到结构化多策略召回

## TL;DR

> **Quick Summary**: 将本地生活服务的实体解析从"单个 shop_name 字符串 + 严格 LIKE 查询"重构为"结构化实体分解 → 多策略数据库召回 → 候选列表暴露 → shop_id 绑定 → 工具执行 → RAG 补充 → 自然语言回答"的完整链路。
>
> **Deliverables**:
> - 实体分解模块（brand/area/category 从自然语言提取）
> - 多策略召回服务（exact → brand+area → brand → fuzzy → catalog）
> - 候选列表澄清机制（clarification_card SSE 事件）
> - 集中式 shop_id 绑定（tool planning 前一次性解析）
> - Java 后端多参数查询接口
>
> **Estimated Effort**: Large
> **Parallel Execution**: YES - 4 waves
> **Critical Path**: Task 1 → Task 5 → Task 9 → Task 12 → Task 15

---

## Context

### Original Request
用户输入"海底捞水晶城店怎么样"时，Java 后端 `LIKE '%海底捞水晶城%'` 无法匹配到实际店铺名"海底捞火锅(水晶城购物中心店）"，导致空结果 → RAG_NO_ANSWER:empty_pack 错误。根本原因是 shop_name 被当作不透明字符串处理，缺乏品牌/区域的结构化分解和多策略召回能力。

### Interview Summary
**Key Discussions**:
- 实体解析位置：Python 侧负责实体分解和策略选择，Java 侧负责按参数查询，Python 调用多个 Java 接口组合召回
- 映射数据来源：从 Java 后端查询品牌/区域数据，Python 侧缓存 + 增量更新
- 多候选处理：返回候选店铺列表让用户在前端选择，需要新的 SSE 事件类型

**Research Findings**:
- Java Shop 实体字段：id, name, typeId, images, area, address, x, y, avgPrice, sold, comments, score, openHours
- 无品牌字段，无城市字段。品牌需从 name 中提取（如"海底捞火锅(水晶城购物中心店）" → brand="海底捞"）
- area 是商圈（如"水晶城"），typeId 是分类
- Java 现有接口：`GET /shop/{id}`, `GET /shop/of/name?name=`, `GET /shop/of/type?typeId=`
- SSE 已有 `CLARIFICATION_CARD` 事件类型，`ClarificationOption` 结构：id, label, value, description
- `EntityResolver` 已有 CandidateGenerator → SemanticSelector → TargetShopPolicy 流程
- `_resolve_catalog_shop` 在 builtin.py 中做 Java→catalog 降级，但分散在每个 tool handler 中

---

## Work Objectives

### Core Objective
将实体解析从"单个不透明字符串"升级为"结构化分解 + 多策略召回 + 候选暴露"的完整链路，彻底解决模糊店名查询失败的问题。

### Concrete Deliverables
- `entity_decomposer.py` — 实体分解模块
- `recall_service.py` — 多策略召回服务
- Java `ShopController` 新增多参数查询接口
- `clarification_card` 候选列表 SSE 事件
- 集中式 shop_id 绑定逻辑
- 完整的单元测试和集成测试

### Definition of Done
- [ ] "海底捞水晶城店怎么样" 能正确返回候选列表并最终给出友好回答
- [ ] 精确匹配（如"海底捞火锅(水晶城购物中心店）"）仍能直接命中
- [ ] 完全不存在的店铺能给出"没找到"的友好降级
- [ ] 所有现有测试通过，无回归

### Must Have
- 实体分解：从自然语言提取 brand、area、category
- 多策略召回：exact → brand+area → brand → fuzzy → catalog 的策略链
- 候选暴露：多候选时返回 clarification_card 让用户选择
- 集中绑定：tool planning 前一次性解析 shop_id，所有 tool 共享结果
- Java 接口：支持 brand+area 多参数查询
- 缓存机制：品牌/区域映射从 Java 后端加载并缓存

### Must NOT Have (Guardrails)
- 不修改现有的 `CLARIFICATION_CARD` SSE 事件结构（只复用）
- 不改变 tool handler 的输入契约（shop_id/shop_name 字段保持不变）
- 不引入新的外部依赖（如 NLP 库）
- 不修改 Java Shop 实体结构（不加字段）
- 不改变 RAG 检索流程
- 不做 LLM 调用来做实体分解（纯规则）

---

## Verification Strategy

> **ZERO HUMAN INTERVENTION** - ALL verification is agent-executed.

### Test Decision
- **Infrastructure exists**: YES
- **Automated tests**: Tests-after
- **Framework**: pytest (existing)

### QA Policy
Every task MUST include agent-executed QA scenarios.
Evidence saved to `.omo/evidence/task-{N}-{scenario-slug}.{ext}`.

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Foundation — 实体分解 + Java 接口):
├── Task 1: 实体分解模块 entity_decomposer.py [deep]
├── Task 2: Java 多参数查询接口 [unspecified-high]
├── Task 3: 品牌/区域映射加载与缓存 [quick]
├── Task 4: 实体分解单元测试 [quick]

Wave 2 (Core — 多策略召回 + 集中绑定):
├── Task 5: 多策略召回服务 recall_service.py (depends: 1, 2, 3) [deep]
├── Task 6: 集中式 shop_id 绑定 (depends: 5) [unspecified-high]
├── Task 7: 候选列表 clarification_card 生成 (depends: 5) [unspecified-high]
├── Task 8: 多策略召回单元测试 (depends: 5) [quick]

Wave 3 (Integration — 接入现有链路):
├── Task 9: 接入 tool planning 流程 (depends: 6, 7) [deep]
├── Task 10: 更新 composer 降级逻辑 (depends: 9) [unspecified-high]
├── Task 11: 清理旧的 hardcoded fallback (depends: 9) [quick]

Wave 4 (Validation — 端到端验证):
├── Task 12: 端到端集成测试 [unspecified-high]
├── Task 13: 回归测试 [quick]
├── Task 14: 性能验证 [quick]

Wave FINAL (After ALL tasks):
├── F1: Plan compliance audit (oracle)
├── F2: Code quality review (unspecified-high)
├── F3: Real manual QA (unspecified-high)
├── F4: Scope fidelity check (deep)
```

### Dependency Matrix

| Task | Depends On | Blocks |
|------|-----------|--------|
| 1 | — | 5 |
| 2 | — | 5 |
| 3 | — | 5 |
| 4 | 1 | — |
| 5 | 1, 2, 3 | 6, 7, 8 |
| 6 | 5 | 9 |
| 7 | 5 | 9 |
| 8 | 5 | — |
| 9 | 6, 7 | 10, 11 |
| 10 | 9 | 12 |
| 11 | 9 | 12 |
| 12 | 10, 11 | F1-F4 |
| 13 | 12 | F1-F4 |
| 14 | 12 | F1-F4 |

### Agent Dispatch Summary

- **Wave 1**: T1→`deep`, T2→`unspecified-high`, T3→`quick`, T4→`quick`
- **Wave 2**: T5→`deep`, T6→`unspecified-high`, T7→`unspecified-high`, T8→`quick`
- **Wave 3**: T9→`deep`, T10→`unspecified-high`, T11→`quick`
- **Wave 4**: T12→`unspecified-high`, T13→`quick`, T14→`quick`
- **FINAL**: F1→`oracle`, F2→`unspecified-high`, F3→`unspecified-high`, F4→`deep`

---

## TODOs

- [ ] 1. 实体分解模块 entity_decomposer.py

  **What to do**:
  - 创建 `learning-agent-service/src/learning_agent_service/local_life/entity_decomposer.py`
  - 实现 `ShopEntity` 数据类：brand, area, category, city, full_query, raw_query
  - 实现 `decompose_shop_query(raw_query: str, slots: LocalLifeSlots | None) -> ShopEntity` 函数
  - 规则 1：从 raw_query 中提取品牌名（如"海底捞"、"新白鹿"、"蔡馬洪涛"）
  - 规则 2：从 raw_query 中提取区域/商圈（如"水晶城"、"运河上街"、"万达"）
  - 规则 3：从 raw_query 中提取分类意图（如"火锅"、"日料"、"西餐"）
  - 规则 4：从 slots.city 中提取城市信息
  - 规则 5：处理前缀匹配（如"海底捞火锅(水晶城购物中心店）" → brand="海底捞", area="水晶城"）
  - 规则 6：处理简写（如"海底捞水晶城" → brand="海底捞", area="水晶城"）
  - 品牌列表从 `JavaBusinessClient.get_brand_list()` 动态加载（Task 3 提供）
  - 区域列表从 `JavaBusinessClient.get_area_list()` 动态加载（Task 3 提供）

  **Must NOT do**:
  - 不使用 LLM 做实体分解（纯规则）
  - 不引入外部 NLP 库
  - 不修改 LocalLifeSlots 结构

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 2, 3, 4)
  - **Blocks**: Task 5
  - **Blocked By**: None

  **References**:
  - `learning-agent-service/src/learning_agent_service/local_life/entity_resolver.py:16-50` — 现有的 `_explicit_entity_from_query` 函数，展示了从 query 提取实体名的规则模式
  - `learning-agent-service/src/learning_agent_service/local_life/candidate_generator.py:72-80` — 现有的 `_explicit_entity_from_query` 函数，展示了 suffix stripping 和实体提取
  - `learning-agent-service/src/learning_agent_service/local_life/schemas.py:63-69` — `LocalLifeSlots` 结构，包含 category, city, location 等字段
  - `learning-agent-service/src/learning_agent_service/adapters/java_business.py:478-492` — 现有的 hardcoded 品牌/区域匹配，展示了需要替代的逻辑
  - `src/main/java/com/hmdp/entity/Shop.java` — Shop 实体字段：name, area, typeId

  **Acceptance Criteria**:
  - [ ] `decompose_shop_query("海底捞水晶城店怎么样")` 返回 `ShopEntity(brand="海底捞", area="水晶城", ...)`
  - [ ] `decompose_shop_query("海底捞火锅(水晶城购物中心店）")` 返回 `ShopEntity(brand="海底捞", area="水晶城", ...)`
  - [ ] `decompose_shop_query("推荐一家火锅店")` 返回 `ShopEntity(brand=None, area=None, category="火锅")`
  - [ ] `decompose_shop_query("海底捞")` 返回 `ShopEntity(brand="海底捞", area=None, ...)`

  **QA Scenarios**:
  ```
  Scenario: 从简写中提取品牌和区域
    Tool: Bash (python)
    Steps:
      1. python -c "from learning_agent_service.local_life.entity_decomposer import decompose_shop_query; r = decompose_shop_query('海底捞水晶城店怎么样', None); print(r.brand, r.area)"
    Expected Result: brand="海底捞", area="水晶城"
    Evidence: .omo/evidence/task-1-brand-area.txt

  Scenario: 从全称中提取品牌和区域
    Tool: Bash (python)
    Steps:
      1. python -c "from learning_agent_service.local_life.entity_decomposer import decompose_shop_query; r = decompose_shop_query('海底捞火锅(水晶城购物中心店）怎么样', None); print(r.brand, r.area)"
    Expected Result: brand="海底捞", area="水晶城"
    Evidence: .omo/evidence/task-1-full-name.txt

  Scenario: 无品牌信息的泛查询
    Tool: Bash (python)
    Steps:
      1. python -c "from learning_agent_service.local_life.entity_decomposer import decompose_shop_query; r = decompose_shop_query('推荐一家好吃的火锅店', None); print(r.brand, r.area, r.category)"
    Expected Result: brand=None, area=None, category="火锅"
    Evidence: .omo/evidence/task-1-generic-query.txt
  ```

  **Commit**: YES
  - Message: `feat(local-life): add entity decomposition module for brand/area extraction`
  - Files: `learning-agent-service/src/learning_agent_service/local_life/entity_decomposer.py`

---

- [ ] 2. Java 多参数查询接口

  **What to do**:
  - 在 `ShopController.java` 中新增 `GET /shop/search` 接口
  - 参数：`name`（可选）、`area`（可选）、`typeId`（可选）、`current`（默认1）
  - 使用 MyBatis-Plus 的条件查询，按 name LIKE + area LIKE + typeId 精确匹配
  - 返回 `Result.ok(List<Shop>)`，按 score DESC 排序
  - 支持任意参数组合（name+area、area+typeId、仅 name 等）
  - 无需修改 Shop 实体结构

  **Must NOT do**:
  - 不修改现有 `/shop/of/name` 和 `/shop/of/type` 接口
  - 不修改 Shop 实体
  - 不引入新的数据表

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 3, 4)
  - **Blocks**: Task 5
  - **Blocked By**: None

  **References**:
  - `src/main/java/com/hmdp/controller/ShopController.java:85-96` — 现有的 `/shop/of/name` 接口，展示了查询模式
  - `src/main/java/com/hmdp/entity/Shop.java` — Shop 实体字段
  - `src/main/java/com/hmdp/dto/Result.java` — Result 返回结构

  **Acceptance Criteria**:
  - [ ] `GET /shop/search?name=海底捞&area=水晶城` 返回匹配的店铺列表
  - [ ] `GET /shop/search?area=水晶城` 返回该区域所有店铺
  - [ ] `GET /shop/search?typeId=1` 返回该类型所有店铺
  - [ ] 空参数返回空列表（不报错）

  **QA Scenarios**:
  ```
  Scenario: 按品牌+区域查询
    Tool: Bash (curl)
    Steps:
      1. curl -s "http://127.0.0.1:8081/shop/search?name=海底捞&area=水晶城"
    Expected Result: 返回包含"海底捞火锅(水晶城购物中心店）"的列表
    Evidence: .omo/evidence/task-2-brand-area.json

  Scenario: 仅按区域查询
    Tool: Bash (curl)
    Steps:
      1. curl -s "http://127.0.0.1:8081/shop/search?area=水晶城"
    Expected Result: 返回该区域的所有店铺
    Evidence: .omo/evidence/task-2-area-only.json
  ```

  **Commit**: YES
  - Message: `feat(api): add multi-parameter shop search endpoint`
  - Files: `src/main/java/com/hmdp/controller/ShopController.java`

---

- [ ] 3. 品牌/区域映射加载与缓存

  **What to do**:
  - 在 `JavaBusinessClient` 中新增 `get_brand_list()` 和 `get_area_list()` 方法
  - `get_brand_list()`：调用 Java 后端获取所有品牌名（可从 `/shop/of/name` 遍历或新增接口）
  - `get_area_list()`：调用 Java 后端获取所有区域名（可从 `/shop/search` 聚合或新增接口）
  - 实现简单的内存缓存（dict + TTL），避免每次请求都调用 Java
  - 缓存 TTL 默认 300 秒
  - 如果 Java 后端不可用，fallback 到 `java_business.py:479` 中的 hardcoded 列表

  **Must NOT do**:
  - 不引入 Redis 或其他外部缓存
  - 不修改 Java 后端（如果无法新增接口，用现有接口聚合）

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2, 4)
  - **Blocks**: Task 5
  - **Blocked By**: None

  **References**:
  - `learning-agent-service/src/learning_agent_service/adapters/java_business.py:370-393` — `_request_json` 方法，展示了 Java API 调用模式
  - `learning-agent-service/src/learning_agent_service/adapters/java_business.py:478-492` — hardcoded 品牌列表，作为 fallback 数据源

  **Acceptance Criteria**:
  - [ ] `get_brand_list()` 返回至少 10 个品牌名
  - [ ] `get_area_list()` 返回至少 5 个区域名
  - [ ] 第二次调用命中缓存（不重复请求 Java）
  - [ ] Java 不可用时返回 hardcoded fallback

  **QA Scenarios**:
  ```
  Scenario: 品牌列表加载
    Tool: Bash (python)
    Steps:
      1. python -c "from learning_agent_service.adapters.java_business import JavaBusinessClient; c = JavaBusinessClient(base_url='http://127.0.0.1:8081', enabled=True); print(c.get_brand_list()[:5])"
    Expected Result: 包含"海底捞"等品牌名
    Evidence: .omo/evidence/task-3-brand-list.txt
  ```

  **Commit**: YES (groups with Task 1)
  - Message: `feat(adapters): add brand/area list loading with cache`
  - Files: `learning-agent-service/src/learning_agent_service/adapters/java_business.py`

---

- [ ] 4. 实体分解单元测试

  **What to do**:
  - 创建 `learning-agent-service/tests/local_life/test_entity_decomposer.py`
  - 测试用例：
    - 简写提取（"海底捞水晶城" → brand="海底捞", area="水晶城"）
    - 全称提取（"海底捞火锅(水晶城购物中心店）" → brand="海底捞", area="水晶城"）
    - 泛查询（"推荐一家火锅店" → category="火锅"）
    - 单品牌（"海底捞" → brand="海底捞"）
    - 无匹配（"随便吃吃" → 全 None）
    - 多品牌冲突（"海底捞和新白鹿哪个好" → 可能需要特殊处理）

  **Must NOT do**:
  - 不测试 Java 接口（那是 Task 2 的事）

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2, 3)
  - **Blocks**: None
  - **Blocked By**: Task 1

  **References**:
  - `learning-agent-service/tests/local_life/` — 现有测试目录结构
  - Task 1 的 entity_decomposer.py — 被测模块

  **Acceptance Criteria**:
  - [ ] `pytest tests/local_life/test_entity_decomposer.py` 全部通过
  - [ ] 覆盖至少 6 种查询模式

  **Commit**: YES (groups with Task 1)
  - Message: `test(local-life): add entity decomposition unit tests`
  - Files: `learning-agent-service/tests/local_life/test_entity_decomposer.py`

---

- [ ] 5. 多策略召回服务 recall_service.py

  **What to do**:
  - 创建 `learning-agent-service/src/learning_agent_service/local_life/recall_service.py`
  - 实现 `RecallResult` 数据类：candidates (list[ShopRecord]), strategy_used, confidence, fallback_level
  - 实现 `multi_strategy_recall(entity: ShopEntity, client: JavaBusinessClient, catalog: LocalLifeCatalog) -> RecallResult` 函数
  - 策略链（按优先级）：
    1. **exact**: 调用 `/shop/search?name={full_name}` 精确匹配
    2. **brand+area**: 调用 `/shop/search?name={brand}&area={area}` 品牌+区域匹配
    3. **brand_only**: 调用 `/shop/search?name={brand}` 仅品牌匹配
    4. **fuzzy**: 调用 `/shop/of/name?name={raw_query}` 原始模糊匹配
    5. **catalog**: 从本地 catalog 搜索
  - 每个策略返回候选列表，按 score DESC 排序
  - 第一个返回非空结果的策略即为最终结果
  - 记录使用的策略和 fallback 层级（用于日志和降级判断）
  - 如果所有策略都返回空，返回空候选列表

  **Must NOT do**:
  - 不修改 JavaBusinessClient 的现有方法签名
  - 不在召回阶段做 LLM 调用

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 2 (sequential after Wave 1)
  - **Blocks**: Tasks 6, 7, 8
  - **Blocked By**: Tasks 1, 2, 3

  **References**:
  - `learning-agent-service/src/learning_agent_service/adapters/java_business.py:465-497` — 现有的 `search_shops_by_name` 方法，展示了 Java API 调用和 fallback 模式
  - `learning-agent-service/src/learning_agent_service/tools/builtin.py:308-359` — 现有的 `_resolve_catalog_shop` 函数，展示了多策略解析的雏形
  - Task 1 的 entity_decomposer.py — ShopEntity 输入
  - Task 2 的 `/shop/search` 接口 — 品牌+区域查询
  - Task 3 的 get_brand_list/get_area_list — 映射数据

  **Acceptance Criteria**:
  - [ ] "海底捞水晶城" 走 brand+area 策略，返回匹配店铺
  - [ ] "海底捞" 走 brand_only 策略，返回该品牌所有店铺
  - [ ] 不存在的品牌返回空列表
  - [ ] 策略链正确记录 fallback_level

  **QA Scenarios**:
  ```
  Scenario: brand+area 策略命中
    Tool: Bash (python)
    Steps:
      1. python -c "from learning_agent_service.local_life.recall_service import multi_strategy_recall; from learning_agent_service.local_life.entity_decomposer import ShopEntity; r = multi_strategy_recall(ShopEntity(brand='海底捞', area='水晶城'), client=None, catalog=None); print(r.strategy_used, len(r.candidates))"
    Expected Result: strategy_used="brand+area", candidates >= 1
    Evidence: .omo/evidence/task-5-brand-area.txt

  Scenario: 无匹配返回空
    Tool: Bash (python)
    Steps:
      1. python -c "from learning_agent_service.local_life.recall_service import multi_strategy_recall; from learning_agent_service.local_life.entity_decomposer import ShopEntity; r = multi_strategy_recall(ShopEntity(brand='不存在的品牌', area='某区域'), client=None, catalog=None); print(r.strategy_used, len(r.candidates))"
    Expected Result: strategy_used 为最后一个策略, candidates = 0
    Evidence: .omo/evidence/task-5-no-match.txt
  ```

  **Commit**: YES
  - Message: `feat(local-life): add multi-strategy shop recall service`
  - Files: `learning-agent-service/src/learning_agent_service/local_life/recall_service.py`

---

- [ ] 6. 集中式 shop_id 绑定

  **What to do**:
  - 在 `orchestrator_components.py` 中新增 `resolve_shop_before_tools()` 函数
  - 在 tool planning 阶段（phase6_tool.py 之后、tool execution 之前）调用
  - 流程：
    1. 从 slots 中提取 raw_query
    2. 调用 `decompose_shop_query()` 获取 ShopEntity
    3. 调用 `multi_strategy_recall()` 获取候选列表
    4. 如果只有 1 个候选 → 直接绑定 shop_id
    5. 如果有多个候选 → 标记为 "needs_clarification"，暂不绑定
    6. 如果 0 个候选 → 标记为 "no_match"
    7. 将结果写入 turn.extra：`resolved_shop_id`, `resolved_shop_name`, `recall_strategy`, `candidates_count`, `needs_clarification`
  - 后续所有 tool handler 从 turn.extra 读取 resolved_shop_id，不再重复解析

  **Must NOT do**:
  - 不修改 tool handler 的输入签名
  - 不在 tool execution 阶段做实体解析

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 2 (after Task 5)
  - **Blocks**: Task 9
  - **Blocked By**: Task 5

  **References**:
  - `learning-agent-service/src/learning_agent_service/tools/orchestrator_components.py:380-465` — 现有的 `_build_local_life_tool_input`，展示了 tool input 构建
  - `learning-agent-service/src/learning_agent_service/application/router/phase6_tool.py` — tool planning 入口
  - Task 5 的 recall_service.py — 多策略召回

  **Acceptance Criteria**:
  - [ ] turn.extra 中包含 resolved_shop_id（当唯一候选时）
  - [ ] turn.extra 中包含 needs_clarification=True（当多候选时）
  - [ ] tool handler 不再重复调用 _resolve_catalog_shop

  **Commit**: YES
  - Message: `feat(orchestrator): add centralized shop_id binding before tool execution`
  - Files: `learning-agent-service/src/learning_agent_service/tools/orchestrator_components.py`

---

- [ ] 7. 候选列表 clarification_card 生成

  **What to do**:
  - 在 `orchestrator_components.py` 或 `composer.py` 中新增 `build_shop_clarification_card()` 函数
  - 当 `needs_clarification=True` 且 candidates 数量 > 1 时触发
  - 生成 `ClarificationCard`：
    - `card_id`: 唯一 ID
    - `question`: "我找到了几家可能的店铺，你想看哪一家？"
    - `options`: 每个候选店铺一个 ClarificationOption
      - `id`: shop_id
      - `label`: shop_name（如"海底捞火锅(水晶城购物中心店）"）
      - `value`: shop_id 作为字符串
      - `description`: 区域 + 评分（如"水晶城 | 评分 4.5"）
    - `ambiguity_type`: "multiple_shop_candidates"
  - 返回的 ClarificationCard 通过 SSE `clarification_card` 事件发送
  - 用户选择后，下一轮 turn 的 slots 中注入 selected_shop_id

  **Must NOT do**:
  - 不修改 ClarificationCard 或 ClarificationOption 的数据结构
  - 不修改前端代码（前端已有 clarification_card 处理逻辑）

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Task 6)
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 9
  - **Blocked By**: Task 5

  **References**:
  - `learning-agent-service/src/learning_agent_service/domain/contracts.py:68-81` — ClarificationOption 和 ClarificationCard 结构
  - `learning-agent-service/src/learning_agent_service/api/contracts.py:57` — CLARIFICATION_CARD 事件类型
  - 现有的 clarification 生成逻辑（在 phase2_slots.py 或 hybrid_router.py 中）

  **Acceptance Criteria**:
  - [ ] 多候选时生成 ClarificationCard，options 数量 == 候选数量
  - [ ] 每个 option 的 label 是店铺名，value 是 shop_id
  - [ ] 单候选时不触发 clarification

  **Commit**: YES (groups with Task 6)
  - Message: `feat(local-life): add shop candidate clarification card generation`
  - Files: `learning-agent-service/src/learning_agent_service/tools/orchestrator_components.py`

---

- [ ] 8. 多策略召回单元测试

  **What to do**:
  - 创建 `learning-agent-service/tests/local_life/test_recall_service.py`
  - 测试用例：
    - brand+area 策略命中
    - brand_only 策略命中
    - 所有策略失败返回空
    - fallback_level 记录正确
    - Java 不可用时降级到 catalog

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 6, 7)
  - **Parallel Group**: Wave 2
  - **Blocks**: None
  - **Blocked By**: Task 5

  **Acceptance Criteria**:
  - [ ] `pytest tests/local_life/test_recall_service.py` 全部通过

  **Commit**: YES (groups with Task 5)
  - Message: `test(local-life): add multi-strategy recall unit tests`
  - Files: `learning-agent-service/tests/local_life/test_recall_service.py`

---

- [ ] 9. 接入 tool planning 流程

  **What to do**:
  - 修改 `phase6_tool.py` 或 `orchestrator_components.py`，在 tool execution 前调用 `resolve_shop_before_tools()`
  - 修改 `_build_local_life_tool_input()`，优先从 turn.extra 读取 resolved_shop_id
  - 确保当 `needs_clarification=True` 时，tool execution 被跳过，直接返回 clarification_card
  - 确保当 `no_match=True` 时，tool execution 被跳过，返回友好降级消息

  **Must NOT do**:
  - 不改变现有 tool planning 的整体流程结构
  - 不修改 tool handler 的业务逻辑

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 3
  - **Blocks**: Tasks 10, 11
  - **Blocked By**: Tasks 6, 7

  **References**:
  - `learning-agent-service/src/learning_agent_service/application/router/phase6_tool.py` — tool planning 入口
  - `learning-agent-service/src/learning_agent_service/tools/orchestrator_components.py:380-465` — tool input 构建
  - Task 6 的 resolve_shop_before_tools() — 集中绑定

  **Acceptance Criteria**:
  - [ ] tool execution 前 turn.extra 已有 resolved_shop_id
  - [ ] 多候选时 tool execution 被跳过，返回 clarification_card
  - [ ] 无匹配时 tool execution 被跳过，返回降级消息

  **Commit**: YES
  - Message: `feat(router): integrate centralized shop resolution into tool planning`
  - Files: `learning-agent-service/src/learning_agent_service/application/router/phase6_tool.py`, `learning-agent-service/src/learning_agent_service/tools/orchestrator_components.py`

---

- [ ] 10. 更新 composer 降级逻辑

  **What to do**:
  - 修改 `composer.py` 中的 `_compose_no_result_answer()` 和 `_compose_tool_answer()`
  - 当 `failure_category == "no_result"` 且 `recall_strategy` 可用时，提供更精确的降级消息
  - 例如："我找到了几家可能的店铺（brand+area 召回），但无法确定你要看哪一家。"
  - 当 `no_match=True` 时，提供："我暂时没找到匹配的店铺。你可以补充更具体的店名、区域，或者告诉我你想看的品牌。"

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Task 11)
  - **Parallel Group**: Wave 3
  - **Blocks**: Task 12
  - **Blocked By**: Task 9

  **References**:
  - `learning-agent-service/src/learning_agent_service/tools/composer.py:1228-1290` — 现有的 `_compose_no_result_answer`
  - `learning-agent-service/src/learning_agent_service/tools/composer.py:1070-1113` — 现有的 `_compose_tool_answer`

  **Acceptance Criteria**:
  - [ ] no_result 时降级消息包含召回策略信息
  - [ ] no_match 时降级消息引导用户补充信息

  **Commit**: YES
  - Message: `feat(composer): improve fallback messages with recall strategy context`
  - Files: `learning-agent-service/src/learning_agent_service/tools/composer.py`

---

- [ ] 11. 清理旧的 hardcoded fallback

  **What to do**:
  - 清理 `java_business.py:478-492` 中的 hardcoded 品牌/区域匹配逻辑
  - 替换为调用新的 `multi_strategy_recall()` 服务
  - 保留 hardcoded 列表作为 `get_brand_list()` 的 fallback 数据源
  - 清理 `_resolve_catalog_shop()` 中的重复逻辑，改为调用集中式绑定

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Task 10)
  - **Parallel Group**: Wave 3
  - **Blocks**: Task 12
  - **Blocked By**: Task 9

  **References**:
  - `learning-agent-service/src/learning_agent_service/adapters/java_business.py:465-497` — 现有的 search_shops_by_name
  - `learning-agent-service/src/learning_agent_service/tools/builtin.py:308-359` — 现有的 _resolve_catalog_shop

  **Acceptance Criteria**:
  - [ ] java_business.py 中不再有 hardcoded 品牌/区域 if/else
  - [ ] _resolve_catalog_shop 调用集中式绑定
  - [ ] 现有测试通过

  **Commit**: YES
  - Message: `refactor(adapters): replace hardcoded brand/area fallback with recall service`
  - Files: `learning-agent-service/src/learning_agent_service/adapters/java_business.py`, `learning-agent-service/src/learning_agent_service/tools/builtin.py`

---

- [ ] 12. 端到端集成测试

  **What to do**:
  - 创建 `learning-agent-service/tests/local_life/test_entity_resolution_e2e.py`
  - 测试场景：
    - "海底捞水晶城店怎么样" → 候选列表 → 选择 → 回答
    - "海底捞火锅(水晶城购物中心店）" → 直接命中 → 回答
    - "不存在的店" → 降级消息
    - "推荐一家火锅店" → 推荐结果（不触发实体解析）

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 4
  - **Blocks**: F1-F4
  - **Blocked By**: Tasks 10, 11

  **Acceptance Criteria**:
  - [ ] `pytest tests/local_life/test_entity_resolution_e2e.py` 全部通过
  - [ ] 覆盖 4 种场景

  **Commit**: YES
  - Message: `test(local-life): add end-to-end entity resolution integration tests`
  - Files: `learning-agent-service/tests/local_life/test_entity_resolution_e2e.py`

---

- [ ] 13. 回归测试

  **What to do**:
  - 运行完整测试套件 `python -m pytest learning-agent-service/tests/ -x`
  - 确保无回归
  - 修复任何失败的测试

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 4 (after Task 12)
  - **Blocks**: F1-F4
  - **Blocked By**: Task 12

  **Acceptance Criteria**:
  - [ ] 所有测试通过

  **Commit**: NO (only if fixes needed)

---

- [ ] 14. 性能验证

  **What to do**:
  - 测量多策略召回的延迟（5 个策略串行执行的总耗时）
  - 如果超过 200ms，考虑优化（如并行执行、提前终止）
  - 验证缓存命中率

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Task 13)
  - **Parallel Group**: Wave 4
  - **Blocks**: F1-F4
  - **Blocked By**: Task 12

  **Acceptance Criteria**:
  - [ ] 多策略召回总耗时 < 200ms（缓存命中时 < 50ms）

  **Commit**: NO

---

## Final Verification Wave

- [ ] F1. **Plan Compliance Audit** — `oracle`
  Read the plan end-to-end. For each "Must Have": verify implementation exists. For each "Must NOT Have": search codebase for forbidden patterns. Check evidence files exist. Compare deliverables against plan.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [ ] F2. **Code Quality Review** — `unspecified-high`
  Run build, lint, test commands. Review all changed files for: type suppression, empty catches, debug logging, commented-out code, unused imports. Check AI slop.
  Output: `Build [PASS/FAIL] | Lint [PASS/FAIL] | Tests [N pass/N fail] | Files [N clean/N issues] | VERDICT`

- [ ] F3. **Real Manual QA** — `unspecified-high`
  Start from clean state. Execute EVERY QA scenario from EVERY task. Test cross-task integration. Test edge cases. Save to `.omo/evidence/final-qa/`.
  Output: `Scenarios [N/N pass] | Integration [N/N] | Edge Cases [N tested] | VERDICT`

- [ ] F4. **Scope Fidelity Check** — `deep`
  For each task: read "What to do", read actual diff. Verify 1:1. Check "Must NOT do" compliance. Detect cross-task contamination. Flag unaccounted changes.
  Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Commit Strategy

| Task | Commit | Message | Files |
|------|--------|---------|-------|
| 1 | YES | `feat(local-life): add entity decomposition module` | entity_decomposer.py |
| 2 | YES | `feat(api): add multi-parameter shop search endpoint` | ShopController.java |
| 3 | YES | `feat(adapters): add brand/area list loading with cache` | java_business.py |
| 4 | YES | `test(local-life): add entity decomposition unit tests` | test_entity_decomposer.py |
| 5 | YES | `feat(local-life): add multi-strategy shop recall service` | recall_service.py |
| 6+7 | YES | `feat(orchestrator): add centralized shop_id binding` | orchestrator_components.py |
| 8 | YES | `test(local-life): add multi-strategy recall unit tests` | test_recall_service.py |
| 9 | YES | `feat(router): integrate centralized shop resolution` | phase6_tool.py, orchestrator_components.py |
| 10 | YES | `feat(composer): improve fallback messages` | composer.py |
| 11 | YES | `refactor(adapters): replace hardcoded fallback` | java_business.py, builtin.py |
| 12 | YES | `test(local-life): add e2e integration tests` | test_entity_resolution_e2e.py |
| 13 | NO | — | — |
| 14 | NO | — | — |

---

## Success Criteria

### Verification Commands
```bash
# Java 编译
cd D:\javacode\hm-dianping && mvn compile -q

# Python 测试
cd D:\javacode\hm-dianping\learning-agent-service && python -m pytest tests/ -x -q

# 端到端验证
curl -s "http://127.0.0.1:8081/shop/search?name=海底捞&area=水晶城" | python -m json.tool
```

### Final Checklist
- [ ] "海底捞水晶城店怎么样" 返回候选列表或友好回答
- [ ] 精确匹配仍能直接命中
- [ ] 不存在的店铺给出降级提示
- [ ] 所有现有测试通过
- [ ] 无 hardcoded 品牌/区域 if/else 残留
- [ ] 多策略召回延迟 < 200ms
