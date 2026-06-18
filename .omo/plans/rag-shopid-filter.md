# Plan 2: RAG 过滤 + shop_id 对齐

## TL;DR

> **Quick Summary**: 让 RAG 在单店问题时按 shop_id 精确过滤，只补充评价/环境/特色信息，不再回答优惠券、营业状态等实时事实。
>
> **Deliverables**:
> - Qdrant chunk 的 shop_id 字段验证和补全
> - RAG 检索增加 shop_id 过滤条件
> - EvidenceGovernance 增加 claim 类型过滤
> - TDD 测试覆盖
>
> **Estimated Effort**: Medium
> **Parallel Execution**: YES - 3 waves
> **Critical Path**: Task 1 → Task 3 → Task 5 → F1-F4

---

## Context

### Original Request
用户要求从 "shop_name/alias/向量容错召回" 改成 "单店问题必须按 shop_id 过滤，RAG 只补充评价/环境/特色，不回答优惠券、营业状态、库存、距离等实时事实"。

### Interview Summary
**Key Discussions**:
- RAG 数据: 需先检查 Qdrant chunk 是否有 shop_id 字段
- 如果没有或不完整 → 必须同步修改数据导入脚本
- 测试策略: TDD

**Research Findings**:
- `recall_service.py` 使用 entity decomposition (brand/area) 而非 shop_id
- Qdrant chunk payload 中可能包含 `shop_id` 字段（需验证）
- `evidence.py` 的 `EvidenceGovernanceService` 不区分 claim 类型
- `hybrid_retrieval.py` 的 metadata filter 不按 shop_id 过滤

---

## Work Objectives

### Core Objective
让 RAG 在单店问题时按 shop_id 精确过滤，只返回评价/环境/特色的 evidence，不返回实时事实。

### Concrete Deliverables
- Qdrant chunk shop_id 字段验证脚本
- `learning_agent_service/rag/retrieval.py` - 增加 shop_id 过滤
- `learning_agent_service/rag/evidence.py` - 增加 claim 类型过滤
- `learning_agent_service/rag/local_life_retrieval.py` - 本地生活检索增加 shop_id
- TDD 测试

### Definition of Done
- [ ] Qdrant chunk 中 shop_id 字段已验证（如有缺失则补全）
- [ ] 单店 RAG 查询按 shop_id 过滤
- [ ] EvidenceGovernance 过滤掉非评价类 chunk（优惠券、营业状态等）
- [ ] 所有现有测试通过
- [ ] 新增 TDD 测试

### Must Have
- shop_id 过滤逻辑
- claim 类型过滤（只保留评价/环境/特色）
- 数据完整性验证
- TDD 测试

### Must NOT Have (Guardrails)
- 不修改 Java 后端代码
- 不修改 ToolCall/Composer 逻辑
- 不改变 RAG 的通用检索能力（只改单店场景）
- 不重新 embedding（只补全 payload 或改过滤逻辑）
- 不删除现有 chunk 数据

---

## Verification Strategy

### Test Decision
- **Infrastructure exists**: YES
- **Automated tests**: TDD
- **Framework**: pytest

### QA Policy
Evidence saved to `.omo/evidence/task-{N}-{scenario-slug}.{ext}`.

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Start Immediately - data audit):
├── Task 1: Qdrant chunk shop_id 字段验证 + 补全 [deep]
├── Task 2: claim 类型定义 + 分类规则 [quick]
└── Task 3: shop_id 过滤函数实现 [deep]

Wave 2 (After Wave 1 - integration):
├── Task 4: EvidenceGovernance 增加 claim 过滤 (depends: 2) [deep]
├── Task 5: local_life_retrieval 集成 shop_id 过滤 (depends: 1, 3) [deep]
└── Task 6: recall_service 优先使用 shop_id (depends: 1) [deep]

Wave FINAL (After ALL tasks):
├── F1: Plan compliance audit (oracle)
├── F2: Code quality review (unspecified-high)
├── F3: Real manual QA (unspecified-high)
└── F4: Scope fidelity check (deep)
```

### Dependency Matrix

| Task | Depends On | Blocks |
|------|-----------|--------|
| 1 | - | 5, 6 |
| 2 | - | 4 |
| 3 | - | 5 |
| 4 | 2 | F1-F4 |
| 5 | 1, 3 | F1-F4 |
| 6 | 1 | F1-F4 |

---

## TODOs

- [ ] 1. Qdrant chunk shop_id 字段验证 + 补全

  **What to do**:
  - 编写验证脚本检查 `local_life_hybrid_chunks` 和 `local_life_parent_child_chunks` collection 中每个 chunk 的 shop_id 字段
  - 输出统计: 有 shop_id 的 chunk 数量 / 总数量 / 缺失的 chunk 列表
  - 如果缺失率 > 5%，编写补全脚本:
    - 对于单店 chunk（chunk_role 为 merchant_*），从 Java 后端查询 shop_id 并回填 payload
    - 对于非单店 chunk，设置 shop_id = null
  - TDD: 先写验证脚本的测试

  **Must NOT do**:
  - 不删除现有 chunk
  - 不重新 embedding
  - 不修改非单店 chunk 的 payload

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 需要理解 Qdrant 数据结构
  - **Skills**: [`test-driven-development`]

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 2, 3)
  - **Blocks**: Tasks 5, 6
  - **Blocked By**: None

  **References**:
  - `learning_agent_service/rag/local_life_seed.py` - 数据导入脚本
  - `learning_agent_service/rag/retrieval_service.py` - 检索逻辑
  - `learning_agent_service/rag/models.py` - KnowledgeChunk 定义

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: 验证脚本输出统计
    Tool: Bash
    Steps:
      1. 运行验证脚本
      2. 断言输出包含 "total_chunks", "with_shop_id", "missing_shop_id"
    Expected Result: 统计信息完整
    Evidence: .omo/evidence/task-1-audit.txt
  ```

  **Commit**: YES
  - Message: `feat(rag): add shop_id audit and backfill script`
  - Files: `learning_agent_service/rag/shop_id_audit.py`

- [ ] 2. claim 类型定义 + 分类规则

  **What to do**:
  - 在 `learning_agent_service/rag/models.py` 或新建 `claim_types.py` 中定义:
    ```python
    class ClaimType(Enum):
        REVIEW = "review"           # 评价、口碑
        ENVIRONMENT = "environment" # 环境、氛围
        SPECIALTY = "specialty"     # 特色、推荐菜
        COUPON = "coupon"           # 优惠券（实时事实）
        OPEN_STATUS = "open_status" # 营业状态（实时事实）
        DISTANCE = "distance"       # 距离（实时事实）
        INVENTORY = "inventory"     # 库存（实时事实）
    ```
  - 定义 `REALTIME_CLAIMS` 集合: `{COUPON, OPEN_STATUS, DISTANCE, INVENTORY}`
  - 定义 `RAG_CLAIMS` 集合: `{REVIEW, ENVIRONMENT, SPECIALTY}`
  - 定义 chunk_role → ClaimType 映射规则

  **Must NOT do**:
  - 不修改现有 chunk_role 定义
  - 不改变 RAG 检索逻辑

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 纯定义文件
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 3)
  - **Blocks**: Task 4
  - **Blocked By**: None

  **References**:
  - `learning_agent_service/rag/models.py` - KnowledgeChunk 定义

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: claim 类型定义正确
    Tool: Bash (pytest)
    Steps:
      1. 导入 ClaimType, REALTIME_CLAIMS, RAG_CLAIMS
      2. 断言 REVIEW in RAG_CLAIMS
      3. 断言 COUPON in REALTIME_CLAIMS
      4. 断言 REALTIME_CLAIMS ∩ RAG_CLAIMS == ∅
    Expected Result: 类型定义完整且不重叠
    Evidence: .omo/evidence/task-2-claim-types.txt
  ```

  **Commit**: YES (groups with 1, 3)

- [ ] 3. shop_id 过滤函数实现

  **What to do**:
  - 在 `learning_agent_service/rag/retrieval.py` 或 `local_life_retrieval.py` 中实现:
    ```python
    def filter_chunks_by_shop_id(chunks: list[KnowledgeChunk], shop_id: int) -> list[KnowledgeChunk]:
        """只保留 shop_id 匹配的 chunk"""
    ```
  - 实现 claim 类型过滤:
    ```python
    def filter_chunks_by_claim_type(chunks: list[KnowledgeChunk], allowed: set[ClaimType]) -> list[KnowledgeChunk]:
        """只保留指定 claim 类型的 chunk"""
    ```
  - 集成到 hybrid retrieval 的 metadata filter 中

  **Must NOT do**:
  - 不改变通用检索逻辑
  - 不删除非单店检索路径

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 核心检索逻辑改动
  - **Skills**: [`test-driven-development`]

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2)
  - **Blocks**: Task 5
  - **Blocked By**: None

  **References**:
  - `learning_agent_service/rag/retrieval.py` - 检索服务
  - `learning_agent_service/rag/hybrid_retrieval.py` - 混合检索

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: shop_id 过滤正确
    Tool: Bash (pytest)
    Steps:
      1. 构造 chunks: [shop_id=5, shop_id=5, shop_id=3]
      2. 调用 filter_chunks_by_shop_id(chunks, 5)
      3. 断言返回 2 个 chunk
    Expected Result: 只返回 shop_id=5 的 chunk
    Evidence: .omo/evidence/task-3-shopid-filter.txt
  ```

  **Commit**: YES (groups with 1, 2)

- [ ] 4. EvidenceGovernance 增加 claim 过滤

  **What to do**:
  - 修改 `learning_agent_service/rag/evidence.py` 中的 `EvidenceGovernanceService`
  - 在 evidence selection 阶段增加 claim 类型过滤:
    - 单店问题: 只保留 RAG_CLAIMS (review, environment, specialty)
    - 推荐问题: 不过滤 claim 类型
  - 确保 filtered_evidence 不包含实时事实

  **Must NOT do**:
  - 不改变 evidence quality 评估逻辑
  - 不改变 citation 构建逻辑

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: evidence governance 核心改动
  - **Skills**: [`test-driven-development`]

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 5, 6)
  - **Blocks**: F1-F4
  - **Blocked By**: Task 2

  **References**:
  - `learning_agent_service/rag/evidence.py` - EvidenceGovernanceService
  - `learning_agent_service/rag/governance.py` - GovernanceConfig

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: 单店 evidence 过滤实时事实
    Tool: Bash (pytest)
    Steps:
      1. 构造 evidence 包含 review + coupon + environment chunks
      2. 调用 governance with claim_filter=RAG_CLAIMS
      3. 断言结果只包含 review 和 environment
      4. 断言 coupon 被过滤
    Expected Result: 实时事实被过滤
    Evidence: .omo/evidence/task-4-claim-filter.txt
  ```

  **Commit**: YES
  - Message: `feat(rag): add claim type filtering to evidence governance`

- [ ] 5. local_life_retrieval 集成 shop_id 过滤

  **What to do**:
  - 修改本地生活检索链路:
    - `learning_agent_service/local_life/subgraph.py` 中的 RAG 调用
    - 如果有 shop_id，传递给 retrieval 层
    - retrieval 层在 hybrid retrieval 后增加 shop_id 过滤
  - 确保推荐场景不受影响

  **Must NOT do**:
  - 不改变推荐场景的检索逻辑
  - 不改变通用 RAG 链路

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 本地生活 RAG 链路核心改动
  - **Skills**: [`test-driven-development`]

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 2 (after Task 1)
  - **Blocks**: F1-F4
  - **Blocked By**: Tasks 1, 3

  **References**:
  - `learning_agent_service/local_life/subgraph.py` - 本地生活子图

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: 单店 RAG 按 shop_id 过滤
    Tool: Bash (pytest)
    Steps:
      1. mock Qdrant 返回 shop_id=5 和 shop_id=3 的 chunks
      2. 调用 retrieval with shop_id=5
      3. 断言结果只包含 shop_id=5 的 chunks
    Expected Result: shop_id 过滤生效
    Evidence: .omo/evidence/task-5-retrieval-filter.txt
  ```

  **Commit**: YES
  - Message: `feat(rag): integrate shop_id filtering in local life retrieval`

- [ ] 6. recall_service 优先使用 shop_id

  **What to do**:
  - 修改 `learning_agent_service/local_life/recall_service.py`
  - 如果 entity 中有 shop_id，跳过 brand/area 搜索，直接用 shop_id 查询
  - 保留现有的 5 策略链作为降级

  **Must NOT do**:
  - 不删除现有策略链
  - 不改变策略链的优先级（只是在最前面插入 shop_id 快速路径）

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: recall service 核心改动
  - **Skills**: [`test-driven-development`]

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 4, 5)
  - **Blocks**: F1-F4
  - **Blocked By**: Task 1

  **References**:
  - `learning_agent_service/local_life/recall_service.py` - 多策略召回服务

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: 有 shop_id 时跳过 brand/area 搜索
    Tool: Bash (pytest)
    Steps:
      1. 构造 entity with shop_id=5
      2. 调用 recall_candidates
      3. 断言直接用 shop_id 查询，未走 brand/area 策略
    Expected Result: shop_id 快速路径生效
    Evidence: .omo/evidence/task-6-recall-shopid.txt
  ```

  **Commit**: YES
  - Message: `feat(rag): add shop_id fast path in recall service`

---

## Final Verification Wave

- [ ] F1. **Plan Compliance Audit** — `oracle`
- [ ] F2. **Code Quality Review** — `unspecified-high`
- [ ] F3. **Real Manual QA** — `unspecified-high`
- [ ] F4. **Scope Fidelity Check** — `deep`

---

## Commit Strategy

- **Wave 1**: `feat(rag): add shop_id audit, claim types, and filter functions`
- **Wave 2**: `feat(rag): integrate shop_id filtering and claim governance`

---

## Success Criteria

### Verification Commands
```bash
cd learning-agent-service && python -m pytest tests/ -x -v  # Expected: all pass
```

### Final Checklist
- [ ] Qdrant chunk shop_id 字段已验证
- [ ] 单店 RAG 查询按 shop_id 过滤
- [ ] 实时事实不在 RAG evidence 中出现
- [ ] 所有测试通过
