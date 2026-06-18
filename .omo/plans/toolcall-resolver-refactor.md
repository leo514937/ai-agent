# Plan 1: BusinessObjectResolver + ToolCall 重构

## TL;DR

> **Quick Summary**: 构建统一的 BusinessObjectResolver 服务，将所有单店工具从 shop_name 模糊匹配改为 shop_id 精确绑定，解决 "海底捞水晶城店怎么样" 查询失败的根本原因。
>
> **Deliverables**:
> - `BusinessObjectResolver` 服务（独立模块，支持 0/1/多候选分级策略）
> - 所有单店工具 Input Schema 改为 shop_id 优先
> - `_resolve_catalog_shop` 改为调用 BusinessObjectResolver
> - 路由层 `synthesize_tool_selection` 集成解析器
> - TDD 测试覆盖
>
> **Estimated Effort**: Medium
> **Parallel Execution**: YES - 3 waves
> **Critical Path**: Task 1 → Task 5 → Task 7 → F1-F4

---

## Context

### Original Request
用户要求从 "每个工具用 shop_name 自己模糊匹配" 改成 "统一解析业务对象，单店工具全部用 shop_id，优惠券/营业/距离/预约等再绑定各自必要参数"。

### Interview Summary
**Key Discussions**:
- 解析器位置: 独立服务层 BusinessObjectResolver，入口放在路由/编排层统一调用
- 解析失败策略: 0候选→降级, 1候选→resolved, 多候选→按意图区分
- 测试策略: TDD

**Research Findings**:
- `_resolve_catalog_shop` 在 `builtin.py:308` 是所有工具的 shop 解析入口
- `search_candidates` 在 `java_business.py:695` 将 `shop_query` 传递给 `search_shops_by_name`
- 路由层 `synthesize_tool_selection` 在 `routing_signals/base.py:1108` 已有 EntityResolver 但只做意图解析
- 当前工具 Input Schema 都有 `shop_id | shop_name` 对，但 tool planner 经常只填 shop_name

---

## Work Objectives

### Core Objective
构建 `BusinessObjectResolver` 服务，将所有单店工具的 shop 解析从分散的 `shop_name` 模糊匹配统一为 `shop_id` 精确绑定。

### Concrete Deliverables
- `learning_agent_service/local_life/business_object_resolver.py` - 新模块
- `learning_agent_service/tools/builtin.py` - 修改所有工具
- `learning_agent_service/application/routing_signals/base.py` - 路由层集成
- 完整的 TDD 测试

### Definition of Done
- [ ] `BusinessObjectResolver.resolve()` 返回 `ResolvedShop(id, name, confidence, source)`
- [ ] 所有单店工具（get_coupon_list, check_open_status, get_distance_eta, create_booking, order 等）优先使用 shop_id
- [ ] `_resolve_catalog_shop` 改为调用 BusinessObjectResolver
- [ ] 路由层在 `synthesize_tool_selection` 中调用 resolver 并将 shop_id 注入 slots
- [ ] 0 候选返回友好降级，1 候选自动绑定，多候选按意图处理
- [ ] 所有现有测试通过
- [ ] 新增 TDD 测试覆盖 resolver + 工具改动

### Must Have
- BusinessObjectResolver 作为独立服务模块
- 所有单店工具 Input Schema 中 shop_id 优先于 shop_name
- 路由层统一调用 resolver
- 分级降级策略（0/1/多候选）
- TDD 测试

### Must NOT Have (Guardrails)
- 不修改 Java 后端代码
- 不修改 RAG/Composer 逻辑（留给 Plan2/Plan3）
- 不改变工具的外部 SSE 行为
- 不引入新的外部依赖
- 不过度抽象：resolver 只做 shop 解析，不做意图判断
- 不改变 search_restaurants 的推荐逻辑

---

## Verification Strategy

> **ZERO HUMAN INTERVENTION** - ALL verification is agent-executed.

### Test Decision
- **Infrastructure exists**: YES（pytest）
- **Automated tests**: TDD
- **Framework**: pytest

### QA Policy
Every task MUST include agent-executed QA scenarios.
Evidence saved to `.omo/evidence/task-{N}-{scenario-slug}.{ext}`.

- **Library/Module**: Use Bash (pytest) - Import, call functions, compare output
- **Integration**: Use Bash (pytest) - Run workflow, assert behavior

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Start Immediately - foundation):
├── Task 1: BusinessObjectResolver 核心模块 + Schema 定义 [deep]
├── Task 2: TDD 测试基础设施搭建 [quick]
└── Task 3: 工具 Input Schema 统一改造 (shop_id 优先) [quick]

Wave 2 (After Wave 1 - core integration):
├── Task 4: _resolve_catalog_shop 改为调用 resolver (depends: 1) [deep]
├── Task 5: 路由层 synthesize_tool_selection 集成 resolver (depends: 1, 3) [deep]
└── Task 6: 降级策略实现：0/1/多候选 (depends: 1) [deep]

Wave 3 (After Wave 2 - validation):
├── Task 7: 端到端集成测试 (depends: 4, 5, 6) [unspecified-high]
└── Task 8: 边界场景测试 + 文档 (depends: 7) [quick]

Wave FINAL (After ALL tasks):
├── F1: Plan compliance audit (oracle)
├── F2: Code quality review (unspecified-high)
├── F3: Real manual QA (unspecified-high)
└── F4: Scope fidelity check (deep)
-> Present results -> Get explicit user okay
```

### Dependency Matrix

| Task | Depends On | Blocks |
|------|-----------|--------|
| 1 | - | 4, 5, 6 |
| 2 | - | 7 |
| 3 | - | 5 |
| 4 | 1 | 7 |
| 5 | 1, 3 | 7 |
| 6 | 1 | 7 |
| 7 | 4, 5, 6, 2 | 8, F1-F4 |
| 8 | 7 | F1-F4 |

### Agent Dispatch Summary

- **Wave 1**: 3 tasks - T1 → `deep`, T2 → `quick`, T3 → `quick`
- **Wave 2**: 3 tasks - T4 → `deep`, T5 → `deep`, T6 → `deep`
- **Wave 3**: 2 tasks - T7 → `unspecified-high`, T8 → `quick`
- **FINAL**: 4 tasks - F1 → `oracle`, F2 → `unspecified-high`, F3 → `unspecified-high`, F4 → `deep`

---

## TODOs

- [ ] 1. BusinessObjectResolver 核心模块 + Schema 定义

  **What to do**:
  - 创建 `learning_agent_service/local_life/business_object_resolver.py`
  - 定义 `ResolvedShop` dataclass: `id: int, name: str, confidence: float, source: str, candidates: list[ShopRecord] | None`
  - 定义 `ResolutionStrategy` enum: `EXACT_ID`, `NAME_EXACT`, `NAME_FUZZY`, `BRAND_AREA`, `CLARIFICATION_NEEDED`, `NOT_FOUND`
  - 实现 `BusinessObjectResolver` 类:
    - `__init__(self, client: JavaBusinessClient, catalog: LocalLifeCatalog)`
    - `def resolve(self, *, raw_query: str, shop_id: int | None, shop_name: str | None, brand: str | None, area: str | None, intent_type: str | None) -> ResolvedShop` (同步优先)
  - resolve 内部逻辑:
    1. shop_id 已有 → 直接用 `get_shop_detail` 验证，返回 EXACT_ID
    2. shop_name 精确匹配 → 调用 `search_shops_by_name`，1 候选返回，多候选按意图处理
    3. brand + area → 调用 `search_candidates`，1 候选返回，多候选按意图处理
    4. 全部失败 → NOT_FOUND
  - TDD: 先写 `tests/test_business_object_resolver.py` 的失败测试

  **Must NOT do**:
  - 不修改 JavaBusinessClient
  - 不处理 RAG/Composer 逻辑
  - 不做意图判断（只接收 intent_type 参数做分支）

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 核心新模块，需要理解完整调用链
  - **Skills**: [`test-driven-development`]
    - `test-driven-development`: TDD 要求先写失败测试

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 2, 3)
  - **Blocks**: Tasks 4, 5, 6
  - **Blocked By**: None (can start immediately)

  **References**:

  **Pattern References**:
  - `learning_agent_service/adapters/java_business.py:308-359` - `_resolve_catalog_shop` 当前实现，新 resolver 要替代它
  - `learning_agent_service/adapters/java_business.py:502-568` - `search_shops_by_name` 调用 Java `/shop/of/name`
  - `learning_agent_service/adapters/java_business.py:695-723` - `search_candidates` 调用链
  - `learning_agent_service/local_life/schemas.py` - `ShopRecord`, `LocalLifeSlots` 定义

  **API/Type References**:
  - `learning_agent_service/local_life/entity_resolver.py:EntityResolver` - 已有的意图解析器，BusinessObjectResolver 与它协作但不替代
  - `learning_agent_service/application/routing_signals/base.py:1108-1175` - `synthesize_tool_selection` 中已有的 EntityResolver 调用

  **WHY Each Reference Matters**:
  - `_resolve_catalog_shop` 是要被替代的函数，需要理解它的完整行为
  - `search_shops_by_name` 是底层 Java 调用，resolver 需要调用它
  - `EntityResolver` 做意图解析，BusinessObjectResolver 做 shop 解析，两者职责不同

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: 0 候选返回 NOT_FOUND
    Tool: Bash (pytest)
    Preconditions: mock JavaBusinessClient 返回空列表
    Steps:
      1. 创建 BusinessObjectResolver(mock_client, catalog)
      2. 调用 resolve(raw_query="不存在的店", shop_id=None, shop_name="不存在的店", ...)
      3. 断言 result.source == "NOT_FOUND"
      4. 断言 result.id is None
    Expected Result: ResolvedShop with source="NOT_FOUND", id=None
    Failure Indicators: 异常或返回了错误的 source
    Evidence: .omo/evidence/task-1-resolution-not-found.txt

  Scenario: 1 候选返回 EXACT_ID
    Tool: Bash (pytest)
    Preconditions: mock JavaBusinessClient 返回包含 id=5 的单个 ShopRecord
    Steps:
      1. 创建 resolver
      2. 调用 resolve(shop_name="海底捞水晶城店")
      3. 断言 result.id == 5
      4. 断言 result.confidence >= 0.8
    Expected Result: ResolvedShop with id=5, confidence>=0.8
    Failure Indicators: id 不匹配或 confidence 过低
    Evidence: .omo/evidence/task-1-resolution-single.txt

  Scenario: 多候选 + 单店意图 → CLARIFICATION_NEEDED
    Tool: Bash (pytest)
    Preconditions: mock 返回 3 个候选
    Steps:
      1. 调用 resolve(intent_type="coupon_query", shop_name="海底捞")
      2. 断言 result.source == "CLARIFICATION_NEEDED"
      3. 断言 result.candidates 长度 == 3
    Expected Result: source="CLARIFICATION_NEEDED", candidates 有 3 个
    Failure Indicators: 直接返回了某个候选而没有要求澄清
    Evidence: .omo/evidence/task-1-resolution-multi-clarify.txt

  Scenario: 多候选 + 推荐意图 → 返回候选列表
    Tool: Bash (pytest)
    Preconditions: mock 返回 3 个候选
    Steps:
      1. 调用 resolve(intent_type="recommendation", shop_name="海底捞")
      2. 断言 result.source == "CANDIDATE_LIST"
      3. 断言 result.candidates 长度 == 3
    Expected Result: source="CANDIDATE_LIST"
    Evidence: .omo/evidence/task-1-resolution-multi-recommend.txt
  ```

  **Commit**: YES (groups with 2, 3)
  - Message: `feat(resolver): add BusinessObjectResolver service and unified schemas`
  - Files: `learning_agent_service/local_life/business_object_resolver.py`, `tests/test_business_object_resolver.py`

- [ ] 2. TDD 测试基础设施搭建

  **What to do**:
  - 确认 `tests/` 目录下 pytest 可运行: `python -m pytest tests/ -x --co -q`
  - 创建 `tests/conftest_business_object.py` 共享 fixtures:
    - `mock_java_client`: mock 的 JavaBusinessClient，返回预设数据
    - `mock_catalog`: mock 的 LocalLifeCatalog
    - `sample_shop_records`: 包含海底捞水晶城店等测试数据
  - 编写 Task 1 中所有失败测试用例（RED phase）

  **Must NOT do**:
  - 不修改被测代码
  - 不创建实现代码

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 纯测试文件创建
  - **Skills**: [`test-driven-development`]

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 3)
  - **Blocks**: Task 7
  - **Blocked By**: None

  **References**:
  - `learning-agent-service/tests/` - 现有测试结构
  - `learning_agent_service/local_life/schemas.py:ShopRecord` - 测试数据结构
  - `learning_agent_service/adapters/java_business.py:161-204` - `_KNOWN_FALLBACK_SHOPS_BY_ID` 测试数据来源

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: pytest 基础设施可用
    Tool: Bash
    Steps:
      1. cd learning-agent-service && python -m pytest tests/conftest_business_object.py -v
      2. 断言 exit code == 0
    Expected Result: pytest 收集到 fixtures，无导入错误
    Evidence: .omo/evidence/task-2-pytest-check.txt
  ```

  **Commit**: YES (groups with 1, 3)

- [ ] 3. 工具 Input Schema 统一改造 (shop_id 优先)

  **What to do**:
  - 修改 `learning_agent_service/tools/builtin.py` 中所有单店工具的 Input Schema:
    - `ShopDetailToolInput`: shop_id 设为必选（保留 shop_name 作为可选降级）
    - `CouponListToolInput`: shop_id 设为必选
    - `BlogListToolInput`: shop_id 优先
    - `DistanceEtaToolInput`: shop_id 设为必选
    - `OpenStatusToolInput`: shop_id 设为必选
    - `BookingToolInput`: shop_id 设为必选
    - `OrderToolInput`: shop_id 设为必选
  - 每个 Schema 的 docstring 说明 "shop_id 优先于 shop_name"

  **Must NOT do**:
  - 不修改 SearchRestaurantsToolInput（推荐工具保留 query 驱动）
  - 不修改工具函数实现（留给 Task 4）
  - 不删除 shop_name 字段（降级兼容）

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 纯 Schema 修改，无业务逻辑
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2)
  - **Blocks**: Task 5
  - **Blocked By**: None

  **References**:
  - `learning_agent_service/tools/builtin.py:25-138` - 所有 ToolInput 定义

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: Schema 验证 shop_id 优先
    Tool: Bash (pytest)
    Steps:
      1. CouponListToolInput(shop_id=5) → 无错误
      2. CouponListToolInput(shop_id=None, shop_name="test") → 无错误（降级）
      3. CouponListToolInput() → 无错误（允许空）
    Expected Result: 所有 Schema 构造成功
    Evidence: .omo/evidence/task-3-schema-check.txt
  ```

  **Commit**: YES (groups with 1, 2)

- [ ] 4. _resolve_catalog_shop 改为调用 resolver

  **What to do**:
  - 修改 `learning_agent_service/tools/builtin.py` 中的 `_resolve_catalog_shop` 函数
  - 旧逻辑: `shop_id → get_shop_detail, shop_name → search_shops_by_name + 字符串比较`
  - 新逻辑: 调用 `BusinessObjectResolver.resolve()`
  - 保持函数签名不变（向后兼容）
  - 处理 resolver 返回 NOT_FOUND 时的降级

  **Must NOT do**:
  - 不改变函数的外部接口
  - 不修改调用 `_resolve_catalog_shop` 的工具函数（留给 Task 4 自身）
  - 不处理 RAG/Composer 逻辑

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 核心函数重构，需要理解所有调用者
  - **Skills**: [`test-driven-development`]

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 5, 6)
  - **Blocks**: Task 7
  - **Blocked By**: Task 1

  **References**:
  - `learning_agent_service/tools/builtin.py:308-359` - `_resolve_catalog_shop` 当前实现
  - `learning_agent_service/tools/builtin.py:424-460` - `_search_coupons` 调用示例
  - `learning_agent_service/tools/builtin.py:481-511` - `_search_shop_detail` 调用示例
  - `learning_agent_service/tools/builtin.py:567-606` - `_check_open_status` 调用示例

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: _resolve_catalog_shop 使用 resolver
    Tool: Bash (pytest)
    Preconditions: mock resolver 返回 ResolvedShop(id=5, ...)
    Steps:
      1. 调用 _resolve_catalog_shop(client=mock, catalog=mock, shop_name="海底捞水晶城店")
      2. 断言返回的 ShopRecord.id == 5
      3. 断言 resolver.resolve 被调用
    Expected Result: 返回正确的 ShopRecord
    Evidence: .omo/evidence/task-4-resolve-catalog.txt

  Scenario: resolver 返回 NOT_FOUND 时降级
    Tool: Bash (pytest)
    Preconditions: mock resolver 返回 NOT_FOUND
    Steps:
      1. 调用 _resolve_catalog_shop(shop_name="不存在的店")
      2. 断言返回 None
    Expected Result: 返回 None 而非抛异常
    Evidence: .omo/evidence/task-4-resolve-fallback.txt
  ```

  **Commit**: YES (groups with 5, 6)
  - Message: `refactor(tools): wire resolver into tool chain and routing`
  - Files: `learning_agent_service/tools/builtin.py`

- [ ] 5. 路由层 synthesize_tool_selection 集成 resolver

  **What to do**:
  - 修改 `learning_agent_service/application/routing_signals/base.py:1108-1175` 中的 `synthesize_tool_selection`
  - 在 EntityResolver 之后、`_choose_tool_name` 之前，插入 BusinessObjectResolver 调用
  - resolver 返回的 shop_id 注入 `slots["shop_id"]`
  - resolver 返回 CLARIFICATION_NEEDED 时，设置 routing 为 clarification

  **Must NOT do**:
  - 不修改 EntityResolver 的逻辑
  - 不改变 `_choose_tool_name` 的逻辑
  - 不处理推荐意图的 candidate_list（留给后续）

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 路由层核心改动，影响整个 tool call 链路
  - **Skills**: [`test-driven-development`]

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 4, 6)
  - **Blocks**: Task 7
  - **Blocked By**: Tasks 1, 3

  **References**:
  - `learning_agent_service/application/routing_signals/base.py:1108-1175` - `synthesize_tool_selection` 完整实现
  - `learning_agent_service/application/routing_signals/base.py:1277-1352` - `_build_tool_input` 中 shop_id 注入点

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: 路由层注入 shop_id
    Tool: Bash (pytest)
    Preconditions: mock resolver 返回 ResolvedShop(id=5)
    Steps:
      1. 构造 routing + turn ("海底捞水晶城店怎么样")
      2. 调用 synthesize_tool_selection
      3. 断言返回的 ToolSelection.input_payload 中有 shop_id=5
    Expected Result: shop_id 被注入到工具 input
    Evidence: .omo/evidence/task-5-routing-inject.txt

  Scenario: CLARIFICATION_NEEDED 触发澄清
    Tool: Bash (pytest)
    Preconditions: mock resolver 返回 CLARIFICATION_NEEDED
    Steps:
      1. 构造 routing + turn
      2. 调用 synthesize_tool_selection
      3. 断言返回 None 或 clarification 相关信号
    Expected Result: 不返回工具选择，触发澄清
    Evidence: .omo/evidence/task-5-routing-clarify.txt
  ```

  **Commit**: YES (groups with 4, 6)

- [ ] 6. 降级策略实现：0/1/多候选

  **What to do**:
  - 在 BusinessObjectResolver 中完善降级链:
    - 0 候选: 返回 NOT_FOUND，工具层返回友好提示 "暂时没有查到这家店"
    - 1 候选 + 高置信: 自动绑定 shop_id
    - 1 候选 + 低置信: 返回 CLARIFICATION_NEEDED
    - 多候选 + 单店事实意图: 返回 CLARIFICATION_NEEDED，携带候选列表
    - 多候选 + 推荐意图: 返回 CANDIDATE_LIST
  - 在 `_build_tool_input` 中处理 CLARIFICATION_NEEDED

  **Must NOT do**:
  - 不改变已有的搜索逻辑
  - 不处理 RAG/Composer 逻辑

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 分级策略核心实现
  - **Skills**: [`test-driven-development`]

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 4, 5)
  - **Blocks**: Task 7
  - **Blocked By**: Task 1

  **References**:
  - `learning_agent_service/tools/builtin.py:308-359` - `_resolve_catalog_shop` 降级逻辑参考
  - `learning_agent_service/application/routing_signals/base.py:1142-1144` - 已有的 clarification 逻辑

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: 多候选 + 单店意图 → CLARIFICATION
    Tool: Bash (pytest)
    Steps:
      1. mock 返回 3 个候选
      2. resolve(intent_type="coupon_query")
      3. assert result.source == "CLARIFICATION_NEEDED"
      4. assert len(result.candidates) == 3
    Expected Result: 需要用户澄清
    Evidence: .omo/evidence/task-6-clarify.txt

  Scenario: 多候选 + 推荐意图 → CANDIDATE_LIST
    Tool: Bash (pytest)
    Steps:
      1. mock 返回 3 个候选
      2. resolve(intent_type="recommendation")
      3. assert result.source == "CANDIDATE_LIST"
    Expected Result: 返回候选列表
    Evidence: .omo/evidence/task-6-candidates.txt
  ```

  **Commit**: YES (groups with 4, 5)

- [ ] 7. 端到端集成测试

  **What to do**:
  - 编写完整的集成测试，覆盖 "海底捞水晶城店怎么样" 查询的完整链路:
    1. 用户输入 → 路由解析 → BusinessObjectResolver → shop_id=5
    2. shop_id=5 → get_coupon_list → 返回正确优惠券
    3. shop_id=5 → check_open_status → 返回营业状态
    4. shop_id=5 → get_distance_eta → 返回距离信息
  - 测试降级链路:
    1. 用户输入 → 不存在的店 → NOT_FOUND → 友好提示
    2. 用户输入 → 模糊店名 → 多候选 → clarification

  **Must NOT do**:
  - 不修改实现代码
  - 不测试 RAG/Composer（留给 Plan2/Plan3）

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: 集成测试需要理解完整链路
  - **Skills**: [`test-driven-development`]

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Task 8)
  - **Blocks**: Tasks F1-F4
  - **Blocked By**: Tasks 4, 5, 6, 2

  **References**:
  - 所有前面的 Task 引用

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: "海底捞水晶城店怎么样" 完整链路
    Tool: Bash (pytest)
    Steps:
      1. 构造完整 workflow mock
      2. 输入 "海底捞水晶城店怎么样"
      3. 验证 resolver 返回 shop_id=5
      4. 验证 get_coupon_list 使用 shop_id=5
      5. 验证 check_open_status 使用 shop_id=5
    Expected Result: 整条链路使用 shop_id
    Evidence: .omo/evidence/task-7-e2e-haidilao.txt

  Scenario: 不存在的店 → 友好降级
    Tool: Bash (pytest)
    Steps:
      1. 输入 "不存在的店"
      2. 验证 resolver 返回 NOT_FOUND
      3. 验证最终 answer 包含 "暂时没有查到"
    Expected Result: 友好的降级提示
    Evidence: .omo/evidence/task-7-e2e-not-found.txt
  ```

  **Commit**: YES
  - Message: `test(resolver): add TDD integration tests`
  - Files: `tests/test_toolcall_integration.py`

- [ ] 8. 边界场景测试 + 文档

  **What to do**:
  - 补充边界场景测试:
    - shop_id 存在但 shop_name 不匹配时的行为
    - Java 后端超时时的降级
    - 并发调用 resolver 的线程安全
    - shop_id 为字符串 "5" vs int 5 的类型处理
  - 在 business_object_resolver.py 模块级 docstring 中记录设计决策

  **Must NOT do**:
  - 不修改核心实现
  - 不创建新的公开 API

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 边界测试 + 文档
  - **Skills**: [`test-driven-development`]

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 3 (sequential after Task 7)
  - **Blocks**: Tasks F1-F4
  - **Blocked By**: Task 7

  **References**:
  - Task 7 的测试文件

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: 边界测试全部通过
    Tool: Bash
    Steps:
      1. cd learning-agent-service && python -m pytest tests/ -x -v
      2. 断言 exit code == 0，所有测试通过
    Expected Result: 零失败
    Evidence: .omo/evidence/task-8-all-tests.txt
  ```

  **Commit**: YES
  - Message: `test(resolver): add edge case tests and module docs`
  - Files: `tests/test_toolcall_integration.py`, `learning_agent_service/local_life/business_object_resolver.py`

---

## Final Verification Wave

- [ ] F1. **Plan Compliance Audit** — `oracle`
  Read the plan end-to-end. For each "Must Have": verify implementation exists. For each "Must NOT Have": search codebase for forbidden patterns. Check evidence files exist.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [ ] F2. **Code Quality Review** — `unspecified-high`
  Run pytest. Review all changed files for: type suppression, empty catches, debug logging, commented-out code, unused imports. Check AI slop.
  Output: `Tests [N pass/N fail] | Files [N clean/N issues] | VERDICT`

- [ ] F3. **Real Manual QA** — `unspecified-high`
  Start from clean state. Execute EVERY QA scenario from EVERY task. Test cross-task integration. Save to `.omo/evidence/final-qa/`.
  Output: `Scenarios [N/N pass] | Integration [N/N] | VERDICT`

- [ ] F4. **Scope Fidelity Check** — `deep`
  For each task: read "What to do", read actual diff. Verify 1:1. Check "Must NOT do" compliance. Detect cross-task contamination.
  Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | VERDICT`

---

## Commit Strategy

- **Wave 1**: `feat(resolver): add BusinessObjectResolver service and unified schemas`
- **Wave 2**: `refactor(tools): wire resolver into tool chain and routing`
- **Wave 3**: `test(resolver): add TDD integration tests`

---

## Success Criteria

### Verification Commands
```bash
cd learning-agent-service && python -m pytest tests/ -x -v  # Expected: all pass
python -m pytest tests/test_business_object_resolver.py -v  # Expected: new tests pass
```

### Final Checklist
- [ ] All "Must Have" present
- [ ] All "Must NOT Have" absent
- [ ] All tests pass
- [ ] "海底捞水晶城店怎么样" 查询能正确解析到 shop_id=5
