# Claim Governance Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enhance claim governance in the Composer to ensure realtime facts claims only come from ToolResult, rejected claims cannot enter LLM answerer input, and RAG claims are properly validated.

**Architecture:** Add comprehensive claim validation across all compose methods, enhance claim extraction to cover all claim types, and enforce strict governance rules.

**Tech Stack:** Python, Pydantic models, custom ClaimValidator service

---

## Task 1: Enhance Claim Extraction for INVENTORY Claims

**Files:**
- Modify: `src/learning_agent_service/tools/composer.py:1133-1181`

- [ ] **Step 1: Add INVENTORY claim extraction**

```python
def _extract_claims_from_tool_result(self, tool_result: Any) -> list[Claim]:
    """从 tool_result 提取 claims"""
    claims: list[Claim] = []
    tool_name = tool_result.tool_name
    data = tool_result.normalized_output.get("data", {}) if hasattr(tool_result, "normalized_output") else {}
    
    if tool_name == "get_coupon_list":
        coupons = data.get("coupons", [])
        for coupon in coupons[:3]:  # 只取前3个
            claims.append(Claim(
                type=ClaimType.COUPON,
                content=coupon.get("title", ""),
                shop_id=data.get("shop_id"),
                source=DataSource.TOOL,
            ))
    elif tool_name == "check_open_status":
        if data.get("open_status"):
            claims.append(Claim(
                type=ClaimType.OPEN_STATUS,
                content=f"营业状态: {data['open_status']}",
                shop_id=data.get("shop_id"),
                source=DataSource.TOOL,
            ))
    elif tool_name == "get_distance_eta":
        if data.get("distance_km"):
            claims.append(Claim(
                type=ClaimType.DISTANCE,
                content=f"距离: {data['distance_km']}km, 预计{data.get('eta_minutes', '')}分钟",
                shop_id=data.get("shop_id"),
                source=DataSource.TOOL,
            ))
    elif tool_name == "booking":
        if data.get("booking_id") or data.get("status"):
            claims.append(Claim(
                type=ClaimType.BOOKING,
                content=f"预约状态: {data.get('status', '已确认')}",
                shop_id=data.get("shop_id"),
                source=DataSource.TOOL,
            ))
    elif tool_name == "order":
        if data.get("order_id") or data.get("status"):
            claims.append(Claim(
                type=ClaimType.ORDER,
                content=f"订单状态: {data.get('status', '已确认')}",
                shop_id=data.get("shop_id"),
                source=DataSource.TOOL,
            ))
    elif tool_name == "get_inventory":
        if data.get("inventory_count") is not None:
            claims.append(Claim(
                type=ClaimType.INVENTORY,
                content=f"库存: {data.get('inventory_count', 0)}件",
                shop_id=data.get("shop_id"),
                source=DataSource.TOOL,
            ))
    
    return claims
```

- [ ] **Step 2: Run tests to verify no regressions**

Run: `python -m pytest tests/test_claim_validator.py -v`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
git add src/learning_agent_service/tools/composer.py
git commit -m "feat: add INVENTORY claim extraction to _extract_claims_from_tool_result"
```

## Task 2: Enhance RAG Claim Validation in _compose_rag_plus_tool_answer

**Files:**
- Modify: `src/learning_agent_service/tools/composer.py:1189-1225`

- [ ] **Step 1: Add RAG claim validation with rejection**

```python
def _compose_rag_plus_tool_answer(self, request: AnswerComposeRequest) -> str | None:
    routing = request.routing_decision
    action = str(getattr(routing, "required_action", "") or "").strip().lower()
    if action != "rag_plus_tool":
        return None

    sections: list[str] = []
    coupon_answer = self._compose_tool_answer(request)
    if coupon_answer:
        sections.append(f"券信息：{coupon_answer}")

    environment_answer = self._compose_environment_answer(request)
    if environment_answer:
        sections.append(f"环境评价：{environment_answer}")

    if not sections:
        return None
    
    # 添加来源验证：确保同店评价只来自同 shop_id RAG
    tool_result = request.tool_result
    rag_result = request.rag_result
    if tool_result and rag_result:
        shop_id = self._extract_shop_id_from_tool_result(tool_result)
        if shop_id:
            # 校验 RAG evidence 的 shop_id
            evidence_pack = rag_result.evidence_pack
            if evidence_pack:
                items = list(evidence_pack.items or [])
                rag_claims: list[Claim] = []
                for item in items:
                    item_shop_id = getattr(item, "shop_id", None)
                    content = str(getattr(item, "content", "") or "").strip()
                    if content and item_shop_id:
                        # 创建 RAG claim 进行验证
                        rag_claims.append(Claim(
                            type=ClaimType.REVIEW,
                            content=content[:100],
                            shop_id=int(item_shop_id) if item_shop_id else None,
                            source=DataSource.RAG,
                        ))
                
                # 使用 ClaimValidator 验证 RAG claims
                if rag_claims:
                    validator = ClaimValidator()
                    validation_result = validator.validate(rag_claims, shop_id=shop_id)
                    if validation_result.rejected_claims:
                        import logging
                        logging.getLogger(__name__).warning(
                            f"RAG claim validation rejected {len(validation_result.rejected_claims)} claims: "
                            f"{validation_result.reasons}"
                        )
                        # 返回错误信息，不进入 LLM answerer 输入
                        return "查询结果中包含无法验证的评价信息，暂时无法给出可靠答案。请稍后重试或补充更多信息。"
    
    return "\n".join(sections)
```

- [ ] **Step 2: Run tests to verify no regressions**

Run: `python -m pytest tests/test_claim_validator.py -v`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
git add src/learning_agent_service/tools/composer.py
git commit -m "feat: add RAG claim validation with rejection in _compose_rag_plus_tool_answer"
```

## Task 3: Add Claim Validation in _compose_grounded_strict_answer

**Files:**
- Modify: `src/learning_agent_service/tools/composer.py:830-877`

- [ ] **Step 1: Add claim validation before answer generation**

```python
def _compose_grounded_strict_answer(self, request: AnswerComposeRequest) -> str:
    ranked_candidates = _build_ranked_candidates(request.ranked_candidates)
    facet_bundle = _build_facet_result_bundle(request)
    local_contract = _build_local_life_contract(request)
    if local_contract is None:
        return self._compose_no_answer(request, request.evidence_quality)

    strict_ready, fallback_mode = _strict_preflight_check(
        request,
        local_contract=local_contract,
        ranked_candidates=ranked_candidates,
        facet_bundle=facet_bundle,
    )
    if not strict_ready:
        if fallback_mode == "ask_clarification":
            return self._compose_clarify_response(request, request.routing_decision)
        return self._compose_no_answer(request, request.evidence_quality)

    topic_name = _resolved_strict_topic_name(request, ranked_candidates)
    evidence_claims = _build_evidence_claims(request)
    user_need = _build_user_need_proxy(request, ranked_candidates)
    
    # 添加 claim 校验：确保 realtime facts 只信 ToolResult
    if facet_bundle is not None:
        tool_results = getattr(facet_bundle, "tool_results", []) or []
        realtime_claims: list[Claim] = []
        for tool_result in tool_results:
            source = str(getattr(tool_result, "source", "") or "").lower().strip()
            if source in {"catalog", "fallback"}:
                continue
            # 从 tool_result 提取 claims
            if hasattr(tool_result, "tool_name") and hasattr(tool_result, "data"):
                claims_from_tool = self._extract_claims_from_tool_result(tool_result)
                realtime_claims.extend(claims_from_tool)
        
        if realtime_claims:
            validator = ClaimValidator()
            validation_result = validator.validate(realtime_claims)
            if validation_result.rejected_claims:
                import logging
                logging.getLogger(__name__).warning(
                    f"Realtime claim validation rejected {len(validation_result.rejected_claims)} claims: "
                    f"{validation_result.reasons}"
                )
                # 返回错误信息，不进入 LLM answerer 输入
                return "查询结果中包含无法验证的实时信息，暂时无法给出可靠答案。请稍后重试或补充更多信息。"
    
    template_answer = self._build_strict_template_answer(
        local_contract=local_contract,
        topic_name=topic_name,
        ranked_candidates=ranked_candidates,
        evidence_claims=evidence_claims,
        facet_bundle=facet_bundle,
        user_need=user_need,
    )
    if not template_answer:
        if fallback_mode == "ask_clarification":
            return self._compose_clarify_response(request, request.routing_decision)
        return self._compose_no_answer(request, request.evidence_quality)
    answer_text = validate_answer_against_contract(
        template_answer,
        local_contract,
        topic_name,
        ranked_candidates,
        evidence_claims,
        facet_result_bundle=facet_bundle,
        user_need=user_need,
        answer_context=request.answer_context,
    )
    if not answer_text:
        if fallback_mode == "ask_clarification":
            return self._compose_clarify_response(request, request.routing_decision)
        return self._compose_no_answer(request, request.evidence_quality)
    return answer_text
```

- [ ] **Step 2: Run tests to verify no regressions**

Run: `python -m pytest tests/test_claim_validator.py -v`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
git add src/learning_agent_service/tools/composer.py
git commit -m "feat: add claim validation in _compose_grounded_strict_answer"
```

## Task 4: Add Claim Validation in _compose_grounded_strict_natural_answer

**Files:**
- Modify: `src/learning_agent_service/tools/composer.py:879-948`

- [ ] **Step 1: Add claim validation before answer generation**

```python
def _compose_grounded_strict_natural_answer(self, request: AnswerComposeRequest) -> str:
    ranked_candidates = _build_ranked_candidates(request.ranked_candidates)
    facet_bundle = _build_facet_result_bundle(request)
    local_contract = _build_local_life_contract(request)
    if local_contract is None:
        return self._compose_no_answer(request, request.evidence_quality)

    strict_ready, fallback_mode = _strict_preflight_check(
        request,
        local_contract=local_contract,
        ranked_candidates=ranked_candidates,
        facet_bundle=facet_bundle,
    )
    if not strict_ready:
        if fallback_mode == "ask_clarification":
            return self._compose_clarify_response(request, request.routing_decision)
        return self._compose_no_answer(request, request.evidence_quality)

    topic_name = _resolved_strict_topic_name(request, ranked_candidates)
    evidence_claims = _build_evidence_claims(request)
    user_need = _build_user_need_proxy(request, ranked_candidates)
    
    # 添加 claim 校验：确保 realtime facts 只信 ToolResult
    if facet_bundle is not None:
        tool_results = getattr(facet_bundle, "tool_results", []) or []
        realtime_claims: list[Claim] = []
        for tool_result in tool_results:
            source = str(getattr(tool_result, "source", "") or "").lower().strip()
            if source in {"catalog", "fallback"}:
                continue
            # 从 tool_result 提取 claims
            if hasattr(tool_result, "tool_name") and hasattr(tool_result, "data"):
                claims_from_tool = self._extract_claims_from_tool_result(tool_result)
                realtime_claims.extend(claims_from_tool)
        
        if realtime_claims:
            validator = ClaimValidator()
            validation_result = validator.validate(realtime_claims)
            if validation_result.rejected_claims:
                import logging
                logging.getLogger(__name__).warning(
                    f"Realtime claim validation rejected {len(validation_result.rejected_claims)} claims: "
                    f"{validation_result.reasons}"
                )
                # 返回错误信息，不进入 LLM answerer 输入
                return "查询结果中包含无法验证的实时信息，暂时无法给出可靠答案。请稍后重试或补充更多信息。"
    
    clean_count = len(evidence_claims)
    strong_count = sum(1 for claim in evidence_claims if str(getattr(claim, "source_type", "") or "").strip().lower() in {"tool", "realtime_tool"})
    medium_count = max(0, clean_count - strong_count)
    answer_depth_policy = derive_answer_depth_policy(
        local_contract,
        clean_evidence_count=clean_count,
        strong_evidence_count=strong_count,
        medium_evidence_count=medium_count,
    )
    structure = AnswerStructureComposer().compose(
        answer_contract=local_contract,
        topic_name=topic_name,
        ranked_candidates=ranked_candidates,
        evidence_claims=evidence_claims,
        answer_depth_policy=answer_depth_policy,
        user_need=user_need,
        facet_result_bundle=facet_bundle,
    )
    draft_answer = str(structure.answer_text or "").strip()
    if not draft_answer:
        if fallback_mode == "ask_clarification":
            return self._compose_clarify_response(request, request.routing_decision)
        return self._compose_no_answer(request, request.evidence_quality)

    # strict_natural 也必须保持强约束：这里只使用确定性草稿，不再调用通用 LLM 生成正文。
    answer_text = draft_answer

    required_terms = _strict_required_terms(
        topic_name=topic_name,
        ranked_candidates=ranked_candidates,
        answer_style=str(getattr(local_contract, "answer_style", "") or "").strip().lower(),
    )
    if not _strict_natural_answer_is_valid(
        candidate_answer=answer_text,
        draft_answer=draft_answer,
        required_terms=required_terms,
        local_contract=local_contract,
        topic_name=topic_name,
        ranked_candidates=ranked_candidates,
        evidence_claims=evidence_claims,
        facet_bundle=facet_bundle,
        user_need=user_need,
        answer_context=request.answer_context,
    ):
        if fallback_mode == "ask_clarification":
            return self._compose_clarify_response(request, request.routing_decision)
        return self._compose_no_answer(request, request.evidence_quality)

    return answer_text
```

- [ ] **Step 2: Run tests to verify no regressions**

Run: `python -m pytest tests/test_claim_validator.py -v`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
git add src/learning_agent_service/tools/composer.py
git commit -m "feat: add claim validation in _compose_grounded_strict_natural_answer"
```

## Task 5: Add Integration Tests for Enhanced Claim Governance

**Files:**
- Create: `tests/test_composer_claim_governance.py`

- [ ] **Step 1: Create integration tests**

```python
"""Composer Claim Governance Integration Tests"""

import pytest
from learning_agent_service.tools.composer import AnswerComposer
from learning_agent_service.tools.claim_validator import ClaimValidator, Claim, DataSource
from learning_agent_service.rag.claim_types import ClaimType
from learning_agent_service.domain.contracts import AnswerComposeRequest
from types import SimpleNamespace


class TestComposerClaimGovernance:
    """Test claim governance in Composer"""

    def test_realtime_claim_rejected_from_rag_source(self):
        """Test that realtime claims from RAG source are rejected"""
        validator = ClaimValidator()
        claim = Claim(
            type=ClaimType.COUPON,
            content="满100减20优惠券",
            shop_id=5,
            source=DataSource.RAG,  # 错误来源
        )
        result = validator.validate([claim], shop_id=5)
        
        assert len(result.rejected_claims) == 1
        assert result.rejected_claims[0].type == ClaimType.COUPON
        assert any("realtime_claim_not_from_tool" in v for v in result.reasons.values())

    def test_realtime_claim_accepted_from_tool_source(self):
        """Test that realtime claims from Tool source are accepted"""
        validator = ClaimValidator()
        claim = Claim(
            type=ClaimType.COUPON,
            content="满100减20优惠券",
            shop_id=5,
            source=DataSource.TOOL,
        )
        result = validator.validate([claim], shop_id=5)
        
        assert len(result.valid_claims) == 1
        assert len(result.rejected_claims) == 0

    def test_rag_claim_wrong_shop_id_rejected(self):
        """Test that RAG claims with wrong shop_id are rejected"""
        validator = ClaimValidator()
        claim = Claim(
            type=ClaimType.REVIEW,
            content="服务很好，环境不错",
            shop_id=6,  # 不同的 shop_id
            source=DataSource.RAG,
        )
        result = validator.validate([claim], shop_id=5)
        
        assert len(result.rejected_claims) == 1
        assert any("rag_claim_wrong_shop_id" in v for v in result.reasons.values())

    def test_inventory_claim_from_tool_accepted(self):
        """Test that INVENTORY claims from Tool source are accepted"""
        validator = ClaimValidator()
        claim = Claim(
            type=ClaimType.INVENTORY,
            content="库存: 10件",
            shop_id=5,
            source=DataSource.TOOL,
        )
        result = validator.validate([claim], shop_id=5)
        
        assert len(result.valid_claims) == 1
        assert len(result.rejected_claims) == 0

    def test_inventory_claim_from_rag_rejected(self):
        """Test that INVENTORY claims from RAG source are rejected"""
        validator = ClaimValidator()
        claim = Claim(
            type=ClaimType.INVENTORY,
            content="库存: 10件",
            shop_id=5,
            source=DataSource.RAG,
        )
        result = validator.validate([claim], shop_id=5)
        
        assert len(result.rejected_claims) == 1
        assert any("realtime_claim_not_from_tool" in v for v in result.reasons.values())
```

- [ ] **Step 2: Run integration tests**

Run: `python -m pytest tests/test_composer_claim_governance.py -v`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
git add tests/test_composer_claim_governance.py
git commit -m "test: add integration tests for enhanced claim governance"
```

## Task 6: Update Documentation and Final Verification

**Files:**
- Modify: `README.md` (if needed for documentation)

- [ ] **Step 1: Update documentation if needed**

- [ ] **Step 2: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "docs: update claim governance documentation"
```

## Verification Checklist

- [ ] All realtime facts claims only come from ToolResult
- [ ] Rejected claims cannot enter LLM answerer input
- [ ] RAG claims are validated for correct shop_id
- [ ] All compose methods have proper claim validation
- [ ] Integration tests pass
- [ ] Full test suite passes
- [ ] Documentation updated if needed
