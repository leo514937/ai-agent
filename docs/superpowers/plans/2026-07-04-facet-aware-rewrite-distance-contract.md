# Facet-Aware Rewrite Distance Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 answer rewrite 过度保守、known fact 被降级为 unknown、distance facet 证据链缺失和 `location: null` schema 失败，同时保留 verifier / rewrite 和 Phase 6 grounded-only 约束。

**Architecture:** 先把 evidence / decision / answer 之间的 facet 状态和 grounded 事实对齐，再让 verifier 识别 known-to-unknown 回退，最后让 verbalizer 的 rewrite 以 facet 为单位保留已知事实、仅对 unknown / failed / partial facet 做保守表达。`location` 和 distance 相关问题只做输入归一化与证据链补齐，不在 answer 阶段补编事实。

**Tech Stack:** Python, Pydantic, pytest, existing local_life_agent answer/planning/domain modules.

---

### Task 1: 补齐 facet 状态与 grounded 事实派生

**Files:**
- Modify: `local_life_agent/domain/evidence.py`
- Modify: `local_life_agent/domain/decision.py`
- Modify: `local_life_agent/domain/schemas.py`
- Modify: `local_life_agent/planning/evidence/evidence_builder.py`
- Modify: `local_life_agent/answer/answer_plan_builder.py`
- Modify: `local_life_agent/answer/generator.py`

- [ ] **Step 1: Write the failing test**

```python
def test_single_shop_plan_carries_facet_statuses_and_grounded_facts():
    ...
    assert plan.facet_statuses["open_status"] == "grounded"
    assert plan.facet_statuses["coupon"] == "grounded"
    assert plan.facet_statuses["distance"] == "unknown"
    assert plan.grounded_facts["open_status"] == "open"
    assert plan.grounded_facts["coupon_count"] == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest local_life_agent/tests/test_p4_evidence_decision_answer_protocol.py -q`
Expected: fail because `facet_statuses` / `grounded_facts` are missing or incomplete.

- [ ] **Step 3: Write minimal implementation**

Add `facet_statuses: dict[str, str]` and `grounded_facts: dict[str, Any]` to the relevant DTOs, populate them from evidence facet results, and keep the existing `unknown_fields / failed_tools / partial_fields` fields intact.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest local_life_agent/tests/test_p4_evidence_decision_answer_protocol.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add local_life_agent/domain/evidence.py local_life_agent/domain/decision.py local_life_agent/domain/schemas.py local_life_agent/planning/evidence/evidence_builder.py local_life_agent/answer/answer_plan_builder.py local_life_agent/answer/generator.py
git commit -m "feat: add facet-aware evidence status plumbing"
```

### Task 2: 修复 verifier 对 known-to-unknown 的判定

**Files:**
- Modify: `local_life_agent/answer/b2_mini_verifier.py`
- Modify: `local_life_agent/answer/verifier.py`
- Modify: `local_life_agent/llm/prompts/answer_verifier.md`

- [ ] **Step 1: Write the failing test**

```python
def test_verify_answer_blocks_known_open_status_downgraded_to_unknown():
    ...
    assert result["passed"] is False
    assert "grounded_fact_downgraded_to_unknown" in result["issues"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest local_life_agent/tests/test_answer_verifier.py -q`
Expected: fail because the verifier currently allows the downgrade.

- [ ] **Step 3: Write minimal implementation**

Teach the heuristic verifier and the structured verifier prompt to flag grounded facets that are rewritten as `暂时无法确认 / 没查到 / 无法判断 / 不确定 / 暂无信息` while leaving unknown / failed facets alone.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest local_life_agent/tests/test_answer_verifier.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add local_life_agent/answer/b2_mini_verifier.py local_life_agent/answer/verifier.py local_life_agent/llm/prompts/answer_verifier.md local_life_agent/tests/test_answer_verifier.py
git commit -m "fix: block grounded facts from being downgraded"
```

### Task 3: 让 rewrite 按 facet 表达而不是一刀切保守

**Files:**
- Modify: `local_life_agent/answer/llm_verbalizer.py`
- Modify: `local_life_agent/llm/prompts/answer_verbalizer.md`
- Modify: `local_life_agent/tests/test_llm_verbalizer.py`

- [ ] **Step 1: Write the failing test**

```python
def test_rewrite_keeps_grounded_open_and_coupon_but_limits_distance():
    ...
    assert "目前营业中" in text
    assert "3 张优惠券" in text
    assert "距离信息暂时无法确认" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest local_life_agent/tests/test_llm_verbalizer.py -q`
Expected: fail because rewrite prompt can still collapse everything to unknown.

- [ ] **Step 3: Write minimal implementation**

Pass facet-level status / grounded facts into the verbalizer, adjust the rewrite instruction to require per-facet handling, and keep verifier-triggered rewrite enabled.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest local_life_agent/tests/test_llm_verbalizer.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add local_life_agent/answer/llm_verbalizer.py local_life_agent/llm/prompts/answer_verbalizer.md local_life_agent/tests/test_llm_verbalizer.py
git commit -m "fix: make answer rewrite facet-aware"
```

### Task 4: 修复 distance 证据链与 `location: null`

**Files:**
- Modify: `local_life_agent/domain/schemas.py`
- Modify: `local_life_agent/target/shop_resolver.py`
- Modify: `local_life_agent/planning/evidence/evidence_builder.py`
- Modify: `local_life_agent/engine/subgraphs/planning_subgraph.py`
- Modify: `local_life_agent/engine/subgraphs/execution_review_subgraph.py`
- Add: `local_life_agent/tests/test_distance_facet_contract.py`

- [ ] **Step 1: Write the failing test**

```python
def test_location_none_is_normalized_and_distance_only_stays_unknown():
    ...
    assert location == {}
    assert facet_statuses["distance"] == "unknown"
    assert blocked_reason
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest local_life_agent/tests/test_distance_facet_contract.py -q`
Expected: fail before the input normalization and blocked-reason plumbing are added.

- [ ] **Step 3: Write minimal implementation**

Normalize `location` to `{}` / structured missing state, keep distance unknown when location coordinates are unavailable, and surface explicit blocked reasons instead of leaving required distance facets hanging.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest local_life_agent/tests/test_distance_facet_contract.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add local_life_agent/domain/schemas.py local_life_agent/target/shop_resolver.py local_life_agent/planning/evidence/evidence_builder.py local_life_agent/engine/subgraphs/planning_subgraph.py local_life_agent/engine/subgraphs/execution_review_subgraph.py local_life_agent/tests/test_distance_facet_contract.py
git commit -m "fix: normalize location and distance evidence"
```

### Task 5: 回归与报告

**Files:**
- Modify: `todo/facet_aware_rewrite_distance_contract_report.md`

- [ ] **Step 1: Run the focused regression set**

Run:
`python -m compileall local_life_agent -q`
`pytest local_life_agent/tests/test_answer_verifier.py -q`
`pytest local_life_agent/tests/test_llm_verbalizer.py -q`
`pytest local_life_agent/tests/test_evidence_review.py -q`
`pytest local_life_agent/tests/test_single_shop_multifacet.py -q`
`pytest local_life_agent/tests/test_p4_evidence_decision_answer_protocol.py -q`

- [ ] **Step 2: Record results and residual risks**

Write the actual pass/fail status, the final gates, and any known remaining issues into the report.

- [ ] **Step 3: Commit**

```bash
git add todo/facet_aware_rewrite_distance_contract_report.md
git commit -m "docs: record facet-aware rewrite and distance contract"
```
