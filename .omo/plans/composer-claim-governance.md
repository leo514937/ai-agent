# Plan 3: Composer claim 校验 + 来源验证

## TL;DR

> **Quick Summary**: 让 Composer 按 claim 类型校验来源，实时事实只信 Tool，同店评价只信同 shop_id RAG，不再 "有啥结果就拼啥"。
>
> **Deliverables**:
> - `ClaimValidator` 服务：按 claim 类型验证数据来源
> - Composer 集成 claim 校验
> - grounding_source 增加 claim-aware 语义
> - TDD 测试覆盖
>
> **Estimated Effort**: Medium
> **Parallel Execution**: YES - 3 waves
> **Critical Path**: Task 1 → Task 3 → Task 5 → F1-F4

---

## Context

### Original Request
用户要求从 "有啥结果就拼啥" 改成 "按 claim 类型校验来源，实时事实只信 Tool，同店评价只信同 shop_id RAG"。

### Interview Summary
**Key Discussions**:
- claim 类型: review, environment, specialty (RAG), coupon, open_status, distance, inventory (Tool)
- 实时事实只信 Tool: 优惠券、营业状态、距离等必须从 Tool 结果获取
- 同店评价只信同 shop_id RAG: 评价必须来自同 shop_id 的 RAG evidence

**Research Findings**:
- `composer.py:1070-1113` - `_compose_tool_answer` 不区分 claim 类型
- `composer.py:1115-1175` - `_compose_rag_plus_tool_answer` 简单拼接
- `orchestrator_components.py:1047` - grounding_source 只有 "business_evidence" 和 "not_grounded"
- `_has_business_evidence` 只检查数据存在性，不验证来源类型

---

## Work Objectives

### Core Objective
让 Composer 按 claim 类型校验数据来源，确保实时事实只来自 Tool，评价只来自同 shop_id RAG。

### Concrete Deliverables
- `learning_agent_service/tools/claim_validator.py` - 新模块
- `learning_agent_service/tools/composer.py` - 集成 claim 校验
- `learning_agent_service/tools/orchestrator_components.py` - grounding_source 增强
- TDD 测试

### Definition of Done
- [ ] `ClaimValidator.validate(claims, sources)` 返回 `ValidationResult`
- [ ] 实时事实 claim 只接受 Tool 来源
- [ ] 评价 claim 只接受同 shop_id RAG 来源
- [ ] Composer 在组合答案前调用 ClaimValidator
- [ ] grounding_source 增加 claim-aware 值
- [ ] 所有现有测试通过

### Must Have
- ClaimValidator 服务
- claim-aware grounding_source
- Composer 集成校验
- TDD 测试

### Must NOT Have (Guardrails)
- 不修改 Java 后端代码
- 不修改 ToolCall/RAG 逻辑
- 不改变 Composer 的外部 SSE 行为
- 不过度抽象：只做来源校验，不做内容质量评估
- 不改变 LLM answerer 的调用方式

---

## Verification Strategy

### Test Decision
- **Infrastructure exists**: YES
- **Automated tests**: TDD
- **Framework**: pytest

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Start Immediately - foundation):
├── Task 1: ClaimValidator 核心模块 + Schema [deep]
├── Task 2: grounding_source 增强 (claim-aware) [quick]
└── Task 3: claim 提取函数（从 tool_result/rag_result 提取） [deep]

Wave 2 (After Wave 1 - integration):
├── Task 4: Composer 集成 ClaimValidator (depends: 1, 3) [deep]
├── Task 5: _compose_tool_answer 增加 claim 校验 (depends: 1) [deep]
└── Task 6: _compose_rag_plus_tool_answer 增加来源验证 (depends: 1, 3) [deep]

Wave FINAL (After ALL tasks):
├── F1: Plan compliance audit (oracle)
├── F2: Code quality review (unspecified-high)
├── F3: Real manual QA (unspecified-high)
└── F4: Scope fidelity check (deep)
```

### Dependency Matrix

| Task | Depends On | Blocks |
|------|-----------|--------|
| 1 | - | 4, 5, 6 |
| 2 | - | 5, 6 |
| 3 | - | 4, 6 |
| 4 | 1, 3 | F1-F4 |
| 5 | 1, 2 | F1-F4 |
| 6 | 1, 2, 3 | F1-F4 |

---

## TODOs

- [ ] 1. ClaimValidator 核心模块 + Schema

  **What to do**:
  - 创建 `learning_agent_service/tools/claim_validator.py`
  - 定义 `ClaimType` enum (复用 Plan2 的定义或导入):
    ```python
    class ClaimType(Enum):
        REVIEW = "review"
        ENVIRONMENT = "environment"
        SPECIALTY = "specialty"
        COUPON = "coupon"
        OPEN_STATUS = "open_status"
        DISTANCE = "distance"
        INVENTORY = "inventory"
    ```
  - 定义 `DataSource` enum: `TOOL`, `RAG`, `UNKNOWN`
  - 定义 `Claim` dataclass: `type: ClaimType, content: str, shop_id: int | None, source: DataSource`
  - 定义 `ValidationResult`: `valid_claims: list[Claim], rejected_claims: list[Claim], reasons: dict[str, str]`
  - 实现 `ClaimValidator` 类:
    ```python
    class ClaimValidator:
        def __init__(self, realtime_claims: set[ClaimType] = REALTIME_CLAIMS, rag_claims: set[ClaimType] = RAG_CLAIMS):
            ...
        def validate(self, claims: list[Claim], expected_source: DataSource | None = None) -> ValidationResult:
            ...
    ```
  - 校验规则:
    - 如果 claim.type in REALTIME_CLAIMS 且 source != TOOL → rejected
    - 如果 claim.type in RAG_CLAIMS 且 source != RAG → rejected
    - 如果 claim.shop_id 不匹配 → rejected

  **Must NOT do**:
  - 不修改 Composer 逻辑（留给 Task 4）
  - 不修改 tool_result/rag_result 结构

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 核心校验逻辑
  - **Skills**: [`test-driven-development`]

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 2, 3)
  - **Blocks**: Tasks 4, 5, 6
  - **Blocked By**: None

  **References**:
  - `learning_agent_service/tools/composer.py:1070-1113` - `_compose_tool_answer` 当前逻辑
  - `learning_agent_service/tools/composer.py:1115-1175` - `_compose_rag_plus_tool_answer` 当前逻辑
  - `learning_agent_service/tools/orchestrator_components.py:1047` - grounding_source 赋值

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: 实时事实 + Tool 来源 → valid
    Tool: Bash (pytest)
    Steps:
      1. 创建 ClaimValidator
      2. 创建 Claim(type=COUPON, source=TOOL, shop_id=5)
      3. 调用 validate([claim])
      4. 断言 claim 在 valid_claims 中
    Expected Result: valid
    Evidence: .omo/evidence/task-1-validate-tool.txt

  Scenario: 实时事实 + RAG 来源 → rejected
    Tool: Bash (pytest)
    Steps:
      1. 创建 Claim(type=COUPON, source=RAG, shop_id=5)
      2. 调用 validate([claim])
      3. 断言 claim 在 rejected_claims 中
      4. 断言 reasons 包含 "realtime_claim_not_from_tool"
    Expected Result: rejected
    Evidence: .omo/evidence/task-1-validate-rejected.txt

  Scenario: 评价 + 同 shop_id RAG → valid
    Tool: Bash (pytest)
    Steps:
      1. 创建 Claim(type=REVIEW, source=RAG, shop_id=5)
      2. 调用 validate([claim], shop_id=5)
      3. 断言 claim 在 valid_claims 中
    Expected Result: valid
    Evidence: .omo/evidence/task-1-validate-review.txt
  ```

  **Commit**: YES
  - Message: `feat(composer): add ClaimValidator service`
  - Files: `learning_agent_service/tools/claim_validator.py`, `tests/test_claim_validator.py`

- [ ] 2. grounding_source 增强 (claim-aware)

  **What to do**:
  - 修改 `learning_agent_service/tools/orchestrator_components.py:1047`
  - 旧: `grounding_source = "business_evidence" if _has_business_evidence(...) else "not_grounded"`
  - 新: 增加 claim-aware 值:
    - `"business_evidence"` - Tool 返回了有效数据
    - `"rag_evidence"` - RAG 返回了有效 evidence
    - `"mixed_evidence"` - Tool + RAG 都有
    - `"not_grounded"` - 都没有
  - 在 `_map_status` 中根据 tool_result 和 rag_result 判断

  **Must NOT do**:
  - 不改变 `_has_business_evidence` 的逻辑
  - 不改变 NormalizedToolResult 的结构

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 小范围修改
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 3)
  - **Blocks**: Tasks 5, 6
  - **Blocked By**: None

  **References**:
  - `learning_agent_service/tools/orchestrator_components.py:1035-1070` - grounding_source 赋值

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: grounding_source 正确分类
    Tool: Bash (pytest)
    Steps:
      1. mock tool_result 有数据 + rag_result 有数据 → "mixed_evidence"
      2. mock tool_result 有数据 + rag_result 无 → "business_evidence"
      3. mock tool_result 无 + rag_result 有 → "rag_evidence"
      4. mock 都无 → "not_grounded"
    Expected Result: 4 种 grounding_source 正确
    Evidence: .omo/evidence/task-2-grounding.txt
  ```

  **Commit**: YES (groups with 1, 3)

- [ ] 3. claim 提取函数

  **What to do**:
  - 实现 `extract_claims_from_tool_result(tool_result) -> list[Claim]`:
    - search_restaurants → 无直接 claim
    - get_coupon_list → Claim(type=COUPON, source=TOOL)
    - check_open_status → Claim(type=OPEN_STATUS, source=TOOL)
    - get_distance_eta → Claim(type=DISTANCE, source=TOOL)
    - get_shop_detail → Claim(type=REVIEW, source=TOOL) (如果有评价数据)
  - 实现 `extract_claims_from_rag_result(rag_result, shop_id) -> list[Claim]`:
    - 从 evidence items 中提取 claim
    - 按 chunk_role 分类:
      - merchant_review_summary → Claim(type=REVIEW, source=RAG)
      - merchant_scene_fit → Claim(type=ENVIRONMENT, source=RAG)
      - merchant_pitfall_summary → Claim(type=REVIEW, source=RAG)
      - package_description → Claim(type=COUPON, source=RAG) (但这是静态信息，应该被校验拒绝)
  - 确保 claim.shop_id 从结果中提取

  **Must NOT do**:
  - 不修改 tool_result/rag_result 结构
  - 不改变 RAG evidence 的提取逻辑

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 需要理解 tool_result 和 rag_result 的结构
  - **Skills**: [`test-driven-development`]

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2)
  - **Blocks**: Tasks 4, 6
  - **Blocked By**: None

  **References**:
  - `learning_agent_service/tools/builtin.py:414-422` - search_restaurants 返回结构
  - `learning_agent_service/tools/builtin.py:452-460` - get_coupon_list 返回结构
  - `learning_agent_service/rag/evidence.py` - evidence pack 结构

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: 从 tool_result 提取 coupon claim
    Tool: Bash (pytest)
    Steps:
      1. 构造 tool_result with get_coupon_list 返回
      2. 调用 extract_claims_from_tool_result
      3. 断言返回 Claim(type=COUPON, source=TOOL)
    Expected Result: 正确提取
    Evidence: .omo/evidence/task-3-extract-tool.txt

  Scenario: 从 rag_result 提取 review claim
    Tool: Bash (pytest)
    Steps:
      1. 构造 rag_result with merchant_review_summary chunk
      2. 调用 extract_claims_from_rag_result(rag_result, shop_id=5)
      3. 断言返回 Claim(type=REVIEW, source=RAG, shop_id=5)
    Expected Result: 正确提取
    Evidence: .omo/evidence/task-3-extract-rag.txt
  ```

  **Commit**: YES (groups with 1, 2)

- [ ] 4. Composer 集成 ClaimValidator

  **What to do**:
  - 修改 `learning_agent_service/tools/composer.py` 的 `compose` 方法
  - 在 `_compose_grounded_answer` 之前插入 claim 校验:
    1. 从 tool_result 和 rag_result 提取 claims
    2. 调用 ClaimValidator.validate()
    3. 只组合 valid_claims 对应的内容
    4. rejected_claims 记录日志
  - 确保校验不影响 LLM answerer 的输入

  **Must NOT do**:
  - 不改变 LLM answerer 的调用方式
  - 不改变 answer 的格式

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Composer 核心改动
  - **Skills**: [`test-driven-development`]

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 5, 6)
  - **Blocks**: F1-F4
  - **Blocked By**: Tasks 1, 3

  **References**:
  - `learning_agent_service/tools/composer.py:750-792` - compose 方法主流程

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: 校验后只组合 valid claims
    Tool: Bash (pytest)
    Steps:
      1. 构造 request with tool_result (coupon) + rag_result (review)
      2. 调用 compose
      3. 断言 answer 包含 coupon 信息
      4. 断言 answer 包含 review 信息
      5. 断言 rejected claims 被记录日志
    Expected Result: 只组合 valid 内容
    Evidence: .omo/evidence/task-4-compose-validate.txt
  ```

  **Commit**: YES
  - Message: `feat(composer): integrate ClaimValidator in answer composition`

- [ ] 5. _compose_tool_answer 增加 claim 校验

  **What to do**:
  - 修改 `learning_agent_service/tools/composer.py:1070-1113` 的 `_compose_tool_answer`
  - 在 `failure_category` 检查之后、返回 tool_answer 之前，验证 claim 类型与来源匹配
  - 如果验证失败，返回 None 而非错误答案

  **Must NOT do**:
  - 不改变 tool_answer 的格式
  - 不改变 failure_category 处理逻辑

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: tool answer 核心改动
  - **Skills**: [`test-driven-development`]

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 4, 6)
  - **Blocks**: F1-F4
  - **Blocked By**: Tasks 1, 2

  **References**:
  - `learning_agent_service/tools/composer.py:1070-1113` - `_compose_tool_answer`

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: 校验通过返回答案
    Tool: Bash (pytest)
    Steps:
      1. 构造 valid tool_result
      2. 调用 _compose_tool_answer
      3. 断言返回非 None
    Expected Result: 返回答案
    Evidence: .omo/evidence/task-5-tool-answer-valid.txt

  Scenario: 校验失败返回 None
    Tool: Bash (pytest)
    Steps:
      1. 构造 invalid tool_result (来源不匹配)
      2. 调用 _compose_tool_answer
      3. 断言返回 None
    Expected Result: 返回 None
    Evidence: .omo/evidence/task-5-tool-answer-invalid.txt
  ```

  **Commit**: YES (groups with 4, 6)

- [ ] 6. _compose_rag_plus_tool_answer 增加来源验证

  **What to do**:
  - 修改 `learning_agent_service/tools/composer.py:1115-1175` 的 `_compose_rag_plus_tool_answer`
  - 分离 RAG 和 Tool 的内容:
    - Tool 部分: 只保留 valid realtime claims
    - RAG 部分: 只保留 valid review/environment claims
  - 确保同店评价只来自同 shop_id RAG

  **Must NOT do**:
  - 不改变答案格式
  - 不改变 section 拼接逻辑

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: rag+tool 组合核心改动
  - **Skills**: [`test-driven-development`]

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 4, 5)
  - **Blocks**: F1-F4
  - **Blocked By**: Tasks 1, 2, 3

  **References**:
  - `learning_agent_service/tools/composer.py:1115-1175` - `_compose_rag_plus_tool_answer`

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: 来源验证后正确分离内容
    Tool: Bash (pytest)
    Steps:
      1. 构造 request with tool_result (coupon) + rag_result (review + coupon chunk)
      2. 调用 _compose_rag_plus_tool_answer
      3. 断言 sections 包含 "券信息" (from Tool)
      4. 断言 sections 包含 "环境评价" (from RAG)
      5. 断言 RAG 中的 coupon chunk 被过滤
    Expected Result: 正确分离来源
    Evidence: .omo/evidence/task-6-rag-tool-separate.txt
  ```

  **Commit**: YES (groups with 4, 5)

---

## Final Verification Wave

- [ ] F1. **Plan Compliance Audit** — `oracle`
- [ ] F2. **Code Quality Review** — `unspecified-high`
- [ ] F3. **Real Manual QA** — `unspecified-high`
- [ ] F4. **Scope Fidelity Check** — `deep`

---

## Commit Strategy

- **Wave 1**: `feat(composer): add ClaimValidator and claim extraction`
- **Wave 2**: `feat(composer): integrate claim validation in answer composition`

---

## Success Criteria

### Verification Commands
```bash
cd learning-agent-service && python -m pytest tests/ -x -v  # Expected: all pass
python -m pytest tests/test_claim_validator.py -v  # Expected: new tests pass
```

### Final Checklist
- [ ] ClaimValidator 按 claim 类型校验来源
- [ ] 实时事实只来自 Tool
- [ ] 评价只来自同 shop_id RAG
- [ ] 所有测试通过
