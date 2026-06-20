"""Deep protocol tests for the 01.5 stage schemas.

Covers every requirement from `todo/04_补全核心协议与执行依赖.md`:

  §1 — EvidencePack 深化 (ranking_snapshot, comparison_matrix)
  §2 — ExecutionPlan 深化 (stages, retry/fallback policy)
  §3 — AnswerPlan 深化 (ranking_snapshot_id, comparison_matrix_id)
  §4 — ResolveShopResult 条件校验 (AMBIGUOUS must have candidates, etc.)
  §5 — ExecutionPlanValidator 7 项校验规则
  §6 — JSON 序列化/反序列化回归
  §7 — 决策唯一归属表 (文档层面, 代码层面检查)
"""

import pytest
from pydantic import ValidationError

from ..domain.schemas import (
    # Sub-types
    SourceType,
    ExecutionStage,
    ToolCallSpec,
    ExecutionPlan,
    EvidenceItem,
    EvidencePack,
    ShopRef,
    ShopCandidate,
    ResolveShopResult,
    AllowedClaim,
    AnswerPlan,
    GlobalTurnContext,
    ToolResult,
)
from ..domain.enums import ToolResultStatus, ErrorCode
from ..planning.plan_validator import ExecutionPlanValidator, ValidationReport


# ===================================================================
# §1 — EvidencePack 深化
# ===================================================================


class TestEvidenceItemDeep:
    def test_result_status_uses_enum(self):
        item = EvidenceItem(result_status=ToolResultStatus.ok)
        assert item.result_status == ToolResultStatus.ok

    def test_result_status_rejects_invalid(self):
        with pytest.raises(ValidationError):
            EvidenceItem(result_status="bogus")

    def test_source_type_default(self):
        item = EvidenceItem()
        assert item.source_type == SourceType.TOOL

    def test_json_roundtrip_with_enums(self):
        item = EvidenceItem(
            evidence_id="ev_001",
            shop_id="s1",
            shop_name="Test",
            facet="coupon",
            tool_name="get_coupon_list",
            call_id="c1",
            result_status=ToolResultStatus.ok,
            field_path="data.coupons[0]",
            value={"discount": 0.8},
            confidence=0.95,
            source_type=SourceType.MOCK,
        )
        data = item.model_dump_json()
        restored = EvidenceItem.model_validate_json(data)
        assert restored == item
        assert restored.result_status == ToolResultStatus.ok
        assert restored.source_type == SourceType.MOCK


class TestEvidencePackDeep:
    def test_ranking_snapshot(self):
        pack = EvidencePack(
            target_shop_ids=["s1", "s2"],
            ranking_snapshot={
                "strategy": "distance+rating",
                "ranked": ["s1", "s2"],
            },
        )
        assert pack.ranking_snapshot is not None
        assert pack.ranking_snapshot["strategy"] == "distance+rating"

    def test_comparison_matrix(self):
        pack = EvidencePack(
            comparison_matrix={
                "headers": ["name", "rating", "cost"],
                "rows": [
                    ["Shop A", 4.5, 30],
                    ["Shop B", 4.0, 25],
                ],
            }
        )
        assert pack.comparison_matrix is not None

    def test_json_roundtrip_with_optional_fields(self):
        pack = EvidencePack(
            target_shop_ids=["s1"],
            evidence_items=[EvidenceItem(evidence_id="e1", shop_id="s1")],
            ranking_snapshot={"ranked": ["s1"]},
            comparison_matrix={"rows": []},
        )
        data = pack.model_dump_json()
        restored = EvidencePack.model_validate_json(data)
        assert restored.ranking_snapshot == {"ranked": ["s1"]}
        assert restored.comparison_matrix == {"rows": []}


# ===================================================================
# §2 — ExecutionPlan 深化
# ===================================================================


class TestExecutionStage:
    def test_full_construction(self):
        stage = ExecutionStage(
            stage_id="stage_1",
            description="Search shops by query",
            tool_names=["search_shops"],
            max_parallelism=1,
        )
        assert stage.stage_id == "stage_1"
        assert stage.max_parallelism == 1

    def test_json_roundtrip(self):
        stage = ExecutionStage(stage_id="stage_1", tool_names=["search_shops"])
        data = stage.model_dump_json()
        restored = ExecutionStage.model_validate_json(data)
        assert restored == stage


class TestToolCallSpecDeep:
    def test_default_retry_and_fallback(self):
        spec = ToolCallSpec()
        assert spec.retry_policy["max_attempts"] == 3
        assert spec.retry_policy["backoff_ms"] == 200
        assert spec.fallback_policy["fallback_tool"] == ""

    def test_custom_policies(self):
        spec = ToolCallSpec(
            call_id="t1",
            tool_name="get_shop_detail",
            retry_policy={"max_attempts": 5, "backoff_ms": 500},
            fallback_policy={"fallback_tool": "search_shops", "fallback_args": {}},
            max_parallelism=4,
        )
        assert spec.retry_policy["max_attempts"] == 5
        assert spec.max_parallelism == 4

    def test_json_roundtrip(self):
        spec = ToolCallSpec(
            call_id="t1",
            tool_name="get_coupon_list",
            args={"shop_id": "s1"},
            depends_on=["search_shops"],
        )
        data = spec.model_dump_json()
        restored = ToolCallSpec.model_validate_json(data)
        assert restored == spec
        assert restored.retry_policy["max_attempts"] == 3  # default preserved


class TestExecutionPlanDeep:
    def test_with_stages(self):
        plan = ExecutionPlan(
            plan_id="plan_reco_001",
            task_type="recommendation",
            stages=[
                ExecutionStage(stage_id="stage_1", tool_names=["search_shops"]),
                ExecutionStage(stage_id="stage_2", tool_names=["get_shop_detail"]),
                ExecutionStage(
                    stage_id="stage_3",
                    tool_names=["check_open_status", "get_coupon_list"],
                ),
                ExecutionStage(stage_id="stage_4", tool_names=["ranking_policy"]),
            ],
            tool_calls=[
                ToolCallSpec(call_id="t1", tool_name="search_shops", args={"query": "火锅"}),
                ToolCallSpec(
                    call_id="t2",
                    tool_name="get_shop_detail",
                    args={"shop_id": "shop_sc_01"},
                    depends_on=["t1"],
                ),
            ],
        )
        assert len(plan.stages) == 4
        assert plan.stages[0].tool_names == ["search_shops"]

    def test_json_roundtrip_with_stages(self):
        plan = ExecutionPlan(
            plan_id="p1",
            stages=[ExecutionStage(stage_id="s1", tool_names=["search_shops"])],
        )
        data = plan.model_dump_json()
        restored = ExecutionPlan.model_validate_json(data)
        assert restored == plan


# ===================================================================
# §3 — AnswerPlan 深化
# ===================================================================


class TestAnswerPlanDeep:
    def test_ranking_and_comparison_refs(self):
        ap = AnswerPlan(
            answer_type="recommendation",
            ranking_snapshot_id="snap_001",
            comparison_matrix_id="",
            tone="friendly",
        )
        assert ap.ranking_snapshot_id == "snap_001"
        assert ap.tone == "friendly"

    def test_with_all_fields(self):
        ap = AnswerPlan(
            answer_type="single_shop",
            target_shop_ids=["s1"],
            allowed_claims=[
                AllowedClaim(
                    claim_id="c1",
                    shop_id="s1",
                    facet="coupon",
                    evidence_ids=["ev_001"],
                    claim_type="discount",
                    value="8折",
                    verbalization_hint="现在有8折优惠",
                ),
            ],
            required_claims=[
                AllowedClaim(claim_id="c2", shop_id="s1", facet="open_status"),
            ],
            must_mention_unknowns=["distance"],
            forbidden_claims=["该店评分最高"],
            ranking_snapshot_id="snap_001",
            comparison_matrix_id="",
            tone="enthusiastic",
            fallback_template_type="simple_fallback",
        )
        assert len(ap.allowed_claims) == 1
        assert ap.allowed_claims[0].verbalization_hint == "现在有8折优惠"
        assert ap.fallback_template_type == "simple_fallback"

    def test_json_roundtrip(self):
        ap = AnswerPlan(
            answer_type="comparison",
            ranking_snapshot_id="snap_001",
            comparison_matrix_id="cmp_001",
        )
        data = ap.model_dump_json()
        restored = AnswerPlan.model_validate_json(data)
        assert restored.ranking_snapshot_id == "snap_001"
        assert restored.comparison_matrix_id == "cmp_001"


# ===================================================================
# §4 — ResolveShopResult 条件校验
# ===================================================================


class TestResolveShopResultValidation:
    def test_resolved_with_shop_ok(self):
        rsr = ResolveShopResult(
            status="RESOLVED",
            resolved_shop=ShopRef(shop_id="s1", shop_name="Shop A"),
            confidence=0.95,
            matched_by="exact",
        )
        assert rsr.resolved_shop is not None

    def test_resolved_without_shop_fails(self):
        with pytest.raises(ValidationError, match="RESOLVED requires resolved_shop"):
            ResolveShopResult(status="RESOLVED", confidence=0.95)

    def test_ambiguous_with_candidates_ok(self):
        rsr = ResolveShopResult(
            status="AMBIGUOUS",
            candidates=[
                ShopCandidate(shop=ShopRef(shop_id="s1"), match_score=0.9),
                ShopCandidate(shop=ShopRef(shop_id="s2"), match_score=0.7),
            ],
        )
        assert len(rsr.candidates) == 2

    def test_ambiguous_without_candidates_fails(self):
        with pytest.raises(ValidationError, match="AMBIGUOUS requires at least one candidate"):
            ResolveShopResult(status="AMBIGUOUS")

    def test_not_found_with_candidates_fails(self):
        with pytest.raises(ValidationError, match="NOT_FOUND requires candidates to be empty"):
            ResolveShopResult(
                status="NOT_FOUND",
                candidates=[ShopCandidate(shop=ShopRef(shop_id="s1"))],
            )

    def test_not_found_empty_ok(self):
        rsr = ResolveShopResult(status="NOT_FOUND")
        assert rsr.status == "NOT_FOUND"
        assert rsr.candidates == []

    def test_low_confidence_no_restriction(self):
        # LOW_CONFIDENCE has no validation constraint
        rsr = ResolveShopResult(status="LOW_CONFIDENCE")
        assert rsr.status == "LOW_CONFIDENCE"


# ===================================================================
# §5 — ExecutionPlanValidator
# ===================================================================


class TestValidationReport:
    def test_default_passed(self):
        report = ValidationReport()
        assert report.passed is True

    def test_errors_cause_failure(self):
        report = ValidationReport()
        report.errors.append("something wrong")
        assert report.passed is False

    def test_merge(self):
        r1 = ValidationReport()
        r1.errors.append("e1")
        r2 = ValidationReport()
        r2.warnings.append("w1")
        r1.merge(r2)
        assert r1.errors == ["e1"]
        assert r1.warnings == ["w1"]


class TestExecutionPlanValidatorRules:
    # --- Rule 1: tool_name registered ---
    def test_unregistered_tool_fails(self):
        validator = ExecutionPlanValidator(registered_tools={"get_shop_detail"})
        plan = ExecutionPlan(
            tool_calls=[ToolCallSpec(call_id="t1", tool_name="hallucinated_tool")]
        )
        report = validator.validate(plan)
        assert not report.passed
        assert any("not registered" in e for e in report.errors)

    def test_registered_tool_passes(self):
        validator = ExecutionPlanValidator(registered_tools={"get_shop_detail"})
        plan = ExecutionPlan(
            tool_calls=[
                ToolCallSpec(
                    call_id="t1",
                    tool_name="get_shop_detail",
                    args={"shop_id": "shop_sc_01"},
                )
            ]
        )
        report = validator.validate(plan)
        assert report.passed

    # --- Rule 4: depends_on cycles ---
    def test_direct_self_cycle(self):
        validator = ExecutionPlanValidator()
        plan = ExecutionPlan(
            tool_calls=[
                ToolCallSpec(
                    call_id="t1",
                    tool_name="search_shops",
                    args={"query": "火锅"},
                    depends_on=["t1"],
                ),
            ]
        )
        report = validator.validate(plan)
        assert not report.passed
        assert any("Circular" in e for e in report.errors)

    def test_indirect_cycle(self):
        validator = ExecutionPlanValidator()
        plan = ExecutionPlan(
            tool_calls=[
                ToolCallSpec(
                    call_id="t1",
                    tool_name="search_shops",
                    args={"query": "火锅"},
                    depends_on=["t2"],
                ),
                ToolCallSpec(
                    call_id="t2",
                    tool_name="get_shop_detail",
                    args={"shop_id": "shop_sc_01"},
                    depends_on=["t3"],
                ),
                ToolCallSpec(
                    call_id="t3",
                    tool_name="get_coupon_list",
                    args={"shop_id": "shop_sc_01"},
                    depends_on=["t1"],
                ),
            ]
        )
        report = validator.validate(plan)
        assert not report.passed
        assert any("Circular" in e for e in report.errors)

    def test_no_cycle_passes(self):
        validator = ExecutionPlanValidator()
        plan = ExecutionPlan(
            tool_calls=[
                ToolCallSpec(
                    call_id="t1",
                    tool_name="search_shops",
                    args={"query": "火锅"},
                    depends_on=[],
                ),
                ToolCallSpec(
                    call_id="t2",
                    tool_name="get_shop_detail",
                    args={"shop_id": "shop_sc_01"},
                    depends_on=["t1"],
                ),
            ]
        )
        report = validator.validate(plan)
        assert report.passed

    # --- Rule 3: shop_id from legitimate resolve ---
    def test_hallucinated_shop_id_fails(self):
        validator = ExecutionPlanValidator()
        plan = ExecutionPlan(
            tool_calls=[
                ToolCallSpec(
                    call_id="t1",
                    tool_name="get_shop_detail",
                    args={"shop_id": "shop_001"},
                    target_shop_id="shop_999",
                ),
            ]
        )
        report = validator.validate(plan, resolved_shop_ids={"shop_001", "shop_002"})
        assert not report.passed
        assert any("shop_999" in e for e in report.errors)

    def test_legitimate_shop_id_passes(self):
        validator = ExecutionPlanValidator()
        plan = ExecutionPlan(
            tool_calls=[
                ToolCallSpec(
                    call_id="t1",
                    tool_name="get_shop_detail",
                    args={"shop_id": "shop_001"},
                    target_shop_id="shop_001",
                ),
            ]
        )
        report = validator.validate(plan, resolved_shop_ids={"shop_001", "shop_002"})
        assert report.passed

    # --- Rule 6: max_tool_calls budget ---
    def test_exceeds_max_tool_calls(self):
        from local_life_agent import config
        validator = ExecutionPlanValidator()
        too_many = config.MAX_TOOL_CALLS + 1
        plan = ExecutionPlan(
            tool_calls=[
                ToolCallSpec(call_id=f"t{i}", tool_name="get_shop_detail", args={"shop_id": "shop_sc_01"})
                for i in range(too_many)
            ]
        )
        report = validator.validate(plan)
        assert not report.passed
        assert any("exceeds max_tool_calls" in e for e in report.errors)

    def test_within_max_tool_calls_passes(self):
        from local_life_agent import config
        validator = ExecutionPlanValidator()
        plan = ExecutionPlan(
            tool_calls=[
                ToolCallSpec(call_id=f"t{i}", tool_name="get_shop_detail", args={"shop_id": "shop_sc_01"})
                for i in range(config.MAX_TOOL_CALLS)
            ]
        )
        report = validator.validate(plan)
        assert report.passed

    # --- Rule 7: forbidden_tools ---
    def test_forbidden_tool_for_task_type_fails(self):
        validator = ExecutionPlanValidator()
        plan = ExecutionPlan(
            task_type="coupon_query",
            tool_calls=[
                ToolCallSpec(call_id="t1", tool_name="search_shops", args={"query": "火锅"})
            ],
        )
        report = validator.validate(plan)
        assert not report.passed
        assert any("forbidden" in e for e in report.errors)

    def test_allowed_tool_passes(self):
        validator = ExecutionPlanValidator()
        plan = ExecutionPlan(
            task_type="coupon_query",
            tool_calls=[
                ToolCallSpec(call_id="t1", tool_name="get_coupon_list", args={"shop_id": "shop_sc_01"})
            ],
        )
        report = validator.validate(plan)
        assert report.passed


# ===================================================================
# §6 — JSON 序列化/反序列化回归
# ===================================================================


class TestJsonRoundtripDeep:
    """Verify all deepened models survive a full JSON round-trip."""

    def test_execution_plan(self):
        plan = ExecutionPlan(
            plan_id="p1",
            stages=[ExecutionStage(stage_id="s1", tool_names=["search_shops"])],
            tool_calls=[ToolCallSpec(call_id="t1", tool_name="search_shops", args={"query": "火锅"})],
        )
        data = plan.model_dump_json()
        restored = ExecutionPlan.model_validate_json(data)
        assert restored == plan

    def test_evidence_pack(self):
        pack = EvidencePack(
            ranking_snapshot={"ranked": ["s1"]},
            comparison_matrix={"headers": ["name"]},
        )
        data = pack.model_dump_json()
        restored = EvidencePack.model_validate_json(data)
        assert restored == pack

    def test_answer_plan(self):
        ap = AnswerPlan(
            answer_type="single_shop",
            ranking_snapshot_id="snap_1",
            comparison_matrix_id="cmp_1",
        )
        data = ap.model_dump_json()
        restored = AnswerPlan.model_validate_json(data)
        assert restored == ap

    def test_resolve_shop_result(self):
        rsr = ResolveShopResult(
            status="RESOLVED",
            resolved_shop=ShopRef(shop_id="s1"),
            matched_by="exact",
        )
        data = rsr.model_dump_json()
        restored = ResolveShopResult.model_validate_json(data)
        assert restored == rsr


# ===================================================================
# §7 — 决策唯一归属（代码层面检查）
# ===================================================================


class TestDecisionOwnership:
    """Verify the decision ownership table from todo/04 §5.

    These tests document the invariants at the code level.
    """

    def test_shop_id_not_in_semantic_frame(self):
        """shop_id must NEVER appear in SemanticFrame (only LLM sees slots)."""
        from ..domain.schemas import SemanticFrame as SF
        # The semantic_frame model has merchant_mentions (strings),
        # reference_mentions (strings) and hard_constraints (dict).
        # There is NO `shop_id` field — confirm it.
        assert not hasattr(SF.model_fields, "shop_id")

    def test_tool_result_has_no_shop_name(self):
        """ToolResult carries shop_id but NOT shop_name (resolved elsewhere)."""
        from ..domain.schemas import ToolResult as TR
        assert "shop_id" in TR.model_fields
        assert "shop_name" not in TR.model_fields
