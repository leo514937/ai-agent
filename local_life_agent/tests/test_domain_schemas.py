"""Comprehensive tests for domain schemas, enums, and state.

Covers every DTO defined in `todo/03_定义全局Schema_DTO_枚举.md`:

  §1 — Core DTOs: TurnInput, SemanticFrame, PendingClarification, ToolResult
  §2 — Complex DTOs (placeholders): ExecutionPlan, EvidencePack, ResolveShopResult, AnswerPlan
  §3 — Orchestration: GlobalTurnContext
  §4 — SessionState
  §5 — Enums: TopIntent, TaskType, Facet, ToolResultStatus, ErrorCode

Each test verifies:
  - Construction with defaults and custom values
  - JSON serialisation → deserialisation round-trip
  - Type / enum enforcement
"""

import json
import pytest
from datetime import datetime
from pydantic import ValidationError

from ..domain.enums import (
    TopIntent,
    TaskType,
    Facet,
    ToolResultStatus,
    ErrorCode,
    ComparisonStructure,
    FilterType,
    GroundingStatus,
    MissingSlotType,
    MultiTurnSignalType,
    PreferenceType,
    ReferenceType,
    SemanticParseSource,
)
from ..domain.schemas import (
    SourceType,
    MatchedBy,
    SemanticPreference,
    SemanticFilter,
    SemanticReference,
    MultiTurnSemanticSignal,
    ExplorationStageSpec,
    UserContext,
    TurnInput,
    SemanticFrame,
    PendingClarification,
    ToolResult,
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
)
from ..domain.graph_state_model import GraphStateModel
from ..domain.state_validation import validate_graph_state
from ..domain.state import SessionState, SessionWriteDirective


# ===================================================================
# §1 — Core DTOs
# ===================================================================


class TestUserContext:
    def test_defaults(self):
        ctx = UserContext()
        assert ctx.location_name == "北京邮电大学"
        assert ctx.lat == 39.9609
        assert ctx.lng == 116.3581

    def test_custom(self):
        ctx = UserContext(location_name="清华大学", lat=40.0, lng=116.3)
        assert ctx.location_name == "清华大学"

    def test_json_roundtrip(self):
        ctx = UserContext()
        data = ctx.model_dump_json()
        restored = UserContext.model_validate_json(data)
        assert restored == ctx


class TestTurnInput:
    def test_defaults(self):
        ti = TurnInput()
        assert ti.input_type == "text"
        assert ti.raw_text == ""
        assert ti.user_context is None

    def test_with_user_context(self):
        uc = UserContext()
        ti = TurnInput(raw_text="hello", user_context=uc)
        assert ti.raw_text == "hello"
        assert ti.user_context == uc

    def test_json_roundtrip(self):
        ti = TurnInput(raw_text="测试", user_context=UserContext())
        data = ti.model_dump_json()
        restored = TurnInput.model_validate_json(data)
        assert restored == ti


class TestSemanticFrame:
    def test_defaults(self):
        sf = SemanticFrame()
        assert sf.top_intent is None
        assert sf.facets == []
        assert sf.merchant_mentions == []
        assert sf.confidence == 0.0

    def test_with_enums(self):
        sf = SemanticFrame(
            top_intent=TopIntent.local_life,
            task_type=TaskType.recommendation,
            facets=[Facet.coupon, Facet.distance],
            merchant_mentions=["咖啡厅"],
            confidence=0.95,
        )
        assert sf.top_intent == TopIntent.local_life
        assert sf.task_type == TaskType.recommendation
        assert {facet.name for facet in sf.facets} == {"coupon", "distance"}
        assert sf.confidence == 0.95

    def test_json_roundtrip(self):
        sf = SemanticFrame(
            top_intent=TopIntent.local_life,
            task_type=TaskType.single_shop_query,
            facets=[Facet.coupon],
            confidence=0.85,
            hard_constraints={"max_price": 50},
        )
        data = sf.model_dump_json()
        restored = SemanticFrame.model_validate_json(data)
        assert restored == sf

    def test_core_semantic_axes_are_supported(self):
        sf = SemanticFrame(
            intent=TopIntent.local_life,
            task_type=TaskType.recommendation,
            primary_task="recommendation",
            comparison_intent=True,
            comparison_structure=ComparisonStructure.pairwise,
            comparison_targets=[{"shop_name": "A店"}, {"shop_name": "B店"}],
            preference_signals=[
                SemanticPreference(
                    preference_type=PreferenceType.value_for_money,
                    value="value_for_money",
                    text="性价比高",
                ),
                SemanticPreference(
                    preference_type=PreferenceType.relative_price_preference,
                    value="relative_price_preference",
                    text="便宜一点",
                ),
            ],
            location_reference=SemanticReference(
                reference_type=ReferenceType.location_reference,
                text="附近",
                value={"scope": "nearby"},
            ),
            shop_reference=SemanticReference(
                reference_type=ReferenceType.shop_reference,
                text="这家",
                value={"shop_name": "A店"},
            ),
            ordinal_reference=SemanticReference(
                reference_type=ReferenceType.ordinal_reference,
                text="第一家",
                value=["第一家"],
            ),
            deictic_reference=SemanticReference(
                reference_type=ReferenceType.deictic_reference,
                text="这家",
                value=["这家"],
            ),
            constraint_update=True,
            new_task_override=False,
            cancel_intent=False,
            discourse_marker="先",
            parse_source=SemanticParseSource.real_llm,
            semantic_parse_source=SemanticParseSource.real_llm,
            grounding_status=GroundingStatus.grounded,
            confidence=0.77,
        )

        assert sf.intent == TopIntent.local_life
        assert sf.top_intent == TopIntent.local_life
        assert sf.comparison_intent is True
        assert sf.comparison_structure == ComparisonStructure.pairwise
        assert sf.preference_signals[0].preference_type == PreferenceType.value_for_money
        assert sf.preference_signals[1].preference_type == PreferenceType.relative_price_preference
        assert sf.location_reference is not None and sf.location_reference.reference_type == ReferenceType.location_reference
        assert sf.shop_reference is not None and sf.shop_reference.reference_type == ReferenceType.shop_reference
        assert sf.ordinal_reference is not None and sf.ordinal_reference.reference_type == ReferenceType.ordinal_reference
        assert sf.deictic_reference is not None and sf.deictic_reference.reference_type == ReferenceType.deictic_reference
        assert sf.constraint_update is True
        assert sf.cancel_intent is False
        assert sf.discourse_marker == "先"
        assert sf.parse_source == SemanticParseSource.real_llm
        assert sf.semantic_parse_source == SemanticParseSource.real_llm
        assert sf.grounding_status == GroundingStatus.grounded

    def test_exploration_and_missing_slot_types_are_supported(self):
        sf = SemanticFrame(
            top_intent=TopIntent.local_life,
            task_type=TaskType.recommendation,
            exploration_stages=[
                ExplorationStageSpec(stage_type="scene", scene="约会"),
                ExplorationStageSpec(stage_type="time", time="晚上"),
                ExplorationStageSpec(stage_type="constraints", constraints={"budget": 50}),
            ],
            missing_slot_type=MissingSlotType.missing_location,
            missing_slots=["missing_location"],
            parse_source=SemanticParseSource.diagnostic_rules,
            semantic_parse_source=SemanticParseSource.diagnostic_rules,
        )

        assert [stage.stage_type for stage in sf.exploration_stages] == ["scene", "time", "constraints"]
        assert sf.missing_slot_type == MissingSlotType.missing_location
        assert sf.missing_slots == ["missing_location"]

    def test_roundtrip_preserves_parse_and_grounding_metadata(self):
        sf = SemanticFrame(
            top_intent=TopIntent.local_life,
            task_type=TaskType.single_shop_query,
            parse_source=SemanticParseSource.fallback_rules,
            semantic_parse_source=SemanticParseSource.fallback_rules,
            grounding_status=GroundingStatus.partially_grounded,
            confidence=0.6,
        )
        data = sf.model_dump_json()
        restored = SemanticFrame.model_validate_json(data)
        assert restored.parse_source == SemanticParseSource.fallback_rules
        assert restored.semantic_parse_source == SemanticParseSource.fallback_rules
        assert restored.grounding_status == GroundingStatus.partially_grounded

    def test_invalid_top_intent_string_fails(self):
        """Pydantic must reject strings not in the TopIntent enum."""
        with pytest.raises(ValidationError):
            SemanticFrame.model_validate({"top_intent": "invalid_intent"})

    def test_invalid_comparison_without_targets_fails(self):
        with pytest.raises(ValidationError):
            SemanticFrame.model_validate(
                {
                    "top_intent": "local_life",
                    "comparison_intent": True,
                    "confidence": 0.8,
                }
            )

    def test_cancel_intent_cannot_coexist_with_new_task_override(self):
        with pytest.raises(ValidationError):
            SemanticFrame.model_validate(
                {
                    "top_intent": "local_life",
                    "cancel_intent": True,
                    "new_task_override": True,
                }
            )


class TestPendingClarification:
    def test_defaults(self):
        pc = PendingClarification()
        assert pc.pending_id == ""

    def test_with_candidates(self):
        pc = PendingClarification(
            pending_id="pc_001",
            original_task_type="single_shop_query",
            candidate_targets=[{"shop_id": "s1", "name": "Shop A"}],
            expected_reply_type="shop_selection",
        )
        assert pc.pending_id == "pc_001"
        assert len(pc.candidate_targets) == 1

    def test_json_roundtrip(self):
        pc = PendingClarification(pending_id="pc_001", original_task_type="recommendation")
        data = pc.model_dump_json()
        restored = PendingClarification.model_validate_json(data)
        assert restored == pc

    def test_datetime_optional(self):
        pc = PendingClarification(created_at=datetime(2026, 6, 19))
        assert pc.created_at is not None
        data = pc.model_dump_json()
        restored = PendingClarification.model_validate_json(data)
        assert restored == pc


class TestToolResult:
    def test_defaults(self):
        with pytest.raises(ValidationError):
            ToolResult()

    def test_with_enums(self):
        tr = ToolResult(
            call_id="call_001",
            shop_id="shop_001",
            tool_name="get_coupon_list",
            success=True,
            result_status=ToolResultStatus.ok,
            data={"coupons": ["c1"]},
            error_code=None,
        )
        assert tr.result_status == ToolResultStatus.ok
        assert tr.data == {"coupons": ["c1"]}

    def test_with_error(self):
        tr = ToolResult(
            call_id="call_002",
            tool_name="search_shops",
            success=False,
            result_status=ToolResultStatus.failed,
            error_code=ErrorCode.TOOL_TIMEOUT,
            error_message="Request timed out",
        )
        assert tr.error_code == ErrorCode.TOOL_TIMEOUT
        assert tr.result_status == ToolResultStatus.failed

    def test_json_roundtrip(self):
        tr = ToolResult(
            call_id="call_001",
            shop_id="shop_001",
            tool_name="get_shop_detail",
            success=True,
            result_status=ToolResultStatus.ok,
            data={"name": "Test Shop"},
        )
        data = tr.model_dump_json()
        restored = ToolResult.model_validate_json(data)
        assert restored == tr

    def test_invalid_status_string_fails(self):
        with pytest.raises(ValidationError):
            ToolResult.model_validate({
                "call_id": "call_999",
                "tool_name": "search_shops",
                "result_status": "bogus_status",
            })


# ===================================================================
# §2 — Complex DTO placeholders
# ===================================================================


class TestToolCallSpec:
    def test_defaults(self):
        spec = ToolCallSpec()
        assert spec.required is True
        assert spec.timeout_ms == 2000

    def test_json_roundtrip(self):
        spec = ToolCallSpec(
            call_id="tc_001",
            tool_name="get_shop_detail",
            args={"shop_id": "s1"},
            depends_on=["search_shops"],
        )
        data = spec.model_dump_json()
        restored = ToolCallSpec.model_validate_json(data)
        assert restored == spec


class TestExecutionPlan:
    def test_defaults(self):
        plan = ExecutionPlan()
        assert plan.tool_calls == []

    def test_with_tool_calls(self):
        plan = ExecutionPlan(
            plan_id="plan_001",
            task_type="single_shop_query",
            tool_calls=[
                ToolCallSpec(call_id="t1", tool_name="get_shop_detail", args={"shop_id": "shop_sc_01"}),
                ToolCallSpec(call_id="t2", tool_name="get_coupon_list", args={"shop_id": "shop_sc_01"}),
            ],
        )
        assert len(plan.tool_calls) == 2

    def test_json_roundtrip(self):
        plan = ExecutionPlan(plan_id="plan_001")
        data = plan.model_dump_json()
        restored = ExecutionPlan.model_validate_json(data)
        assert restored == plan


class TestEvidenceItem:
    def test_defaults(self):
        item = EvidenceItem()
        assert item.source_type == SourceType.TOOL

    def test_invalid_source_type_fails(self):
        with pytest.raises(ValidationError):
            EvidenceItem.model_validate({"source_type": "bogus"})

    def test_json_roundtrip(self):
        item = EvidenceItem(
            evidence_id="ev_001",
            shop_id="s1",
            shop_name="Test Shop",
            facet="coupon",
            value=10,
        )
        data = item.model_dump_json()
        restored = EvidenceItem.model_validate_json(data)
        assert restored == item


class TestEvidencePack:
    def test_defaults(self):
        pack = EvidencePack()
        assert pack.evidence_items == []
        assert pack.unknown_items == []

    def test_with_items(self):
        pack = EvidencePack(
            target_shop_ids=["s1"],
            evidence_items=[EvidenceItem(evidence_id="ev_001", shop_id="s1")],
        )
        assert len(pack.evidence_items) == 1

    def test_json_roundtrip(self):
        pack = EvidencePack(target_shop_ids=["s1"])
        data = pack.model_dump_json()
        restored = EvidencePack.model_validate_json(data)
        assert restored == pack


class TestShopRef:
    def test_json_roundtrip(self):
        ref = ShopRef(shop_id="s1", shop_name="Shop One")
        data = ref.model_dump_json()
        restored = ShopRef.model_validate_json(data)
        assert restored == ref


class TestShopCandidate:
    def test_defaults(self):
        sc = ShopCandidate()
        assert sc.matched_by == MatchedBy.FUZZY  # default changed in 01.5 deepen
        assert sc.match_score == 0.0


class TestResolveShopResult:
    def test_defaults(self):
        rsr = ResolveShopResult()
        assert rsr.status == ""
        assert rsr.resolved_shop is None
        assert rsr.candidates == []

    def test_resolved(self):
        rsr = ResolveShopResult(
            status="RESOLVED",
            resolved_shop=ShopRef(shop_id="s1", shop_name="Shop A"),
            confidence=0.95,
            matched_by="exact",
        )
        assert rsr.resolved_shop is not None
        assert rsr.resolved_shop.shop_id == "s1"

    def test_ambiguous(self):
        rsr = ResolveShopResult(
            status="AMBIGUOUS",
            candidates=[
                ShopCandidate(shop=ShopRef(shop_id="s1"), match_score=0.9),
                ShopCandidate(shop=ShopRef(shop_id="s2"), match_score=0.7),
            ],
        )
        assert len(rsr.candidates) == 2

    def test_json_roundtrip(self):
        rsr = ResolveShopResult(
            status="RESOLVED",
            resolved_shop=ShopRef(shop_id="s1", shop_name="Test"),
            confidence=0.9,
        )
        data = rsr.model_dump_json()
        restored = ResolveShopResult.model_validate_json(data)
        assert restored == rsr

    def test_invalid_matched_by_fails(self):
        with pytest.raises(ValidationError):
            ResolveShopResult.model_validate(
                {
                    "status": "RESOLVED",
                    "resolved_shop": {"shop_id": "s1", "shop_name": "Shop A"},
                    "matched_by": "bogus",
                }
            )


class TestAllowedClaim:
    def test_defaults(self):
        ac = AllowedClaim()
        assert ac.claim_id == ""
        assert ac.evidence_ids == []


class TestAnswerPlan:
    def test_defaults(self):
        ap = AnswerPlan()
        assert ap.answer_type == ""
        assert ap.response_sections == []

    def test_with_claims(self):
        ap = AnswerPlan(
            answer_type="single_shop",
            target_shop_ids=["s1"],
            allowed_claims=[
                AllowedClaim(claim_id="c1", shop_id="s1", facet="coupon", value="8折"),
            ],
            tone="friendly",
        )
        assert len(ap.allowed_claims) == 1
        assert ap.tone == "friendly"

    def test_json_roundtrip(self):
        ap = AnswerPlan(answer_type="recommendation")
        data = ap.model_dump_json()
        restored = AnswerPlan.model_validate_json(data)
        assert restored == ap


# ===================================================================
# §3 — GlobalTurnContext
# ===================================================================


class TestGlobalTurnContext:
    def test_defaults(self):
        ctx = GlobalTurnContext()
        assert ctx.trace_id == ""
        assert ctx.semantic_frame is None
        assert ctx.resolved_target is None

    def test_with_artifacts(self):
        ctx = GlobalTurnContext(
            trace_id="trace_001",
            turn_id="turn_001",
            session_id="sess_001",
            raw_text="hello",
            normalized_text="hello",
            user_context=UserContext(),
            semantic_frame=SemanticFrame(top_intent=TopIntent.local_life),
        )
        assert ctx.semantic_frame is not None
        assert ctx.semantic_frame.top_intent == TopIntent.local_life

    def test_full_turn_evolution(self):
        """Simulate how GlobalTurnContext accumulates artifacts across a turn."""
        ctx = GlobalTurnContext(
            trace_id="t1", turn_id="turn_1", session_id="s1",
            raw_text="推荐附近咖啡厅",
        )
        # After semantic parse
        ctx.semantic_frame = SemanticFrame(
            top_intent=TopIntent.local_life,
            task_type=TaskType.recommendation,
            facets=[Facet.coupon],
        )
        # After resolve
        ctx.resolved_target = ResolveShopResult(
            status="RESOLVED",
            resolved_shop=ShopRef(shop_id="s1", shop_name="Test"),
        )
        # After planning
        ctx.execution_plan = ExecutionPlan(
            plan_id="plan_1",
            tool_calls=[ToolCallSpec(call_id="t1", tool_name="search_shops", args={"query": "火锅"})],
        )
        assert ctx.execution_plan is not None
        assert len(ctx.execution_plan.tool_calls) == 1

    def test_json_roundtrip(self):
        ctx = GlobalTurnContext(
            trace_id="trace_001",
            session_id="sess_001",
            semantic_frame=SemanticFrame(top_intent=TopIntent.chat),
        )
        data = ctx.model_dump_json()
        restored = GlobalTurnContext.model_validate_json(data)
        assert restored == ctx


class TestSemanticSignalModels:
    def test_preference_filter_reference_and_multiturn_models_roundtrip(self):
        preference = SemanticPreference(
            preference_type=PreferenceType.scene_preference,
            value="scene_preference",
            text="适合约会",
        )
        filter_signal = SemanticFilter(
            filter_type=FilterType.open_now_filter,
            value=True,
            required=True,
            text="现在营业",
        )
        reference = SemanticReference(
            reference_type=ReferenceType.ordinal_reference,
            text="第一家",
            value=["第一家"],
        )
        signal = MultiTurnSemanticSignal(
            signal_type=MultiTurnSignalType.new_task_override,
            text="不要烧烤了，推荐咖啡",
            from_state=False,
        )

        assert SemanticPreference.model_validate_json(preference.model_dump_json()) == preference
        assert SemanticFilter.model_validate_json(filter_signal.model_dump_json()) == filter_signal
        assert SemanticReference.model_validate_json(reference.model_dump_json()) == reference
        assert MultiTurnSemanticSignal.model_validate_json(signal.model_dump_json()) == signal


class TestGraphStateModel:
    def test_validation_adapts_semantic_observability(self):
        payload = {
            "trace_id": "trace_001",
            "semantic_frame": SemanticFrame(
                top_intent=TopIntent.local_life,
                semantic_source="real_llm",
                parse_source=SemanticParseSource.real_llm,
                semantic_parse_source=SemanticParseSource.real_llm,
                grounding_status=GroundingStatus.grounded,
                missing_slot_type=MissingSlotType.missing_location,
            ),
        }

        result = validate_graph_state(payload)
        assert result.is_valid is True
        assert result.model.semantic_parse_source == "real_llm"
        assert result.model.grounding_status == "grounded"
        assert result.model.missing_slot_type == "missing_location"

    def test_json_roundtrip(self):
        model = GraphStateModel(
            trace_id="trace_001",
            semantic_parse_source="diagnostic_rules",
            grounding_status="partially_grounded",
            missing_slot_type="missing_shop_target",
            schema_validation_result={"ok": True},
        )
        data = model.model_dump_json()
        restored = GraphStateModel.model_validate_json(data)
        assert restored.semantic_parse_source == "diagnostic_rules"
        assert restored.grounding_status == "partially_grounded"
        assert restored.missing_slot_type == "missing_shop_target"


# ===================================================================
# §4 — SessionState
# ===================================================================


class TestSessionState:
    def test_defaults(self):
        ss = SessionState()
        assert ss.current_shop is None
        assert ss.last_recommendation_list == []
        assert ss.pending_clarification is None

    def test_with_values(self):
        ss = SessionState(
            current_shop={"shop_id": "s1", "name": "Test"},
            last_recommendation_list=[{"shop_id": "s1"}, {"shop_id": "s2"}],
        )
        assert ss.current_shop["shop_id"] == "s1"
        assert len(ss.last_recommendation_list) == 2

    def test_json_roundtrip(self):
        ss = SessionState(
            active_constraints={"max_price": 50},
            comparison_targets=[{"shop_id": "s1"}],
        )
        data = ss.model_dump_json()
        restored = SessionState.model_validate_json(data)
        assert restored == ss


class TestSessionWriteDirective:
    def test_defaults(self):
        d = SessionWriteDirective()
        assert d.set_fields == {}
        assert d.clear_fields == []

    def test_clone_isolation(self):
        d1 = SessionWriteDirective(set_fields={"current_shop": None})
        d2 = d1.clone()
        d2.set_fields["current_shop"] = {"shop_id": "test"}
        assert d1.set_fields["current_shop"] is None


# ===================================================================
# §5 — Enums
# ===================================================================


class TestEnums:
    def test_top_intent_values(self):
        assert TopIntent.local_life.value == "local_life"
        assert TopIntent.capability.value == "capability"
        assert TopIntent.chat.value == "chat"
        assert TopIntent.invalid.value == "invalid"
        assert TopIntent.unsafe.value == "unsafe"
        assert TopIntent.out_of_scope.value == "out_of_scope"
        assert len(TopIntent) == 6

    def test_task_type_values(self):
        assert TaskType.recommendation.value == "recommendation"
        assert TaskType.single_shop_query.value == "single_shop_query"
        assert TaskType.coupon_query.value == "coupon_query"
        assert TaskType.comparison.value == "comparison"
        assert TaskType.clarification_reply.value == "clarification_reply"
        assert TaskType.general_chat.value == "general_chat"
        assert len(TaskType) == 6

    def test_facet_values(self):
        assert Facet.coupon.value == "coupon"
        assert Facet.open_status.value == "open_status"
        assert Facet.distance.value == "distance"
        assert Facet.price.value == "price"
        assert Facet.rating.value == "rating"
        assert Facet.category.value == "category"
        assert Facet.environment.value == "environment"
        assert Facet.taste.value == "taste"
        assert Facet.service.value == "service"
        assert Facet.review_summary.value == "review_summary"
        assert Facet.scene_fit.value == "scene_fit"
        assert Facet.ordinal_reference.value == "ordinal_reference"
        assert Facet.comparison_targets.value == "comparison_targets"
        assert len(Facet) >= 13

    def test_tool_result_status_values(self):
        assert ToolResultStatus.ok.value == "ok"
        assert ToolResultStatus.partial.value == "partial"
        assert ToolResultStatus.empty.value == "empty"
        assert ToolResultStatus.unknown.value == "unknown"
        assert ToolResultStatus.failed.value == "failed"
        assert ToolResultStatus.error.value == "error"
        assert ToolResultStatus.circuit_open.value == "circuit_open"
        assert ToolResultStatus.backend_unavailable.value == "backend_unavailable"
        assert len(ToolResultStatus) == 10

    def test_error_code_values(self):
        codes = [
            ErrorCode.TOOL_TIMEOUT,
            ErrorCode.NETWORK_ERROR,
            ErrorCode.CIRCUIT_OPEN,
            ErrorCode.BACKEND_UNAVAILABLE,
            ErrorCode.INVALID_ARGUMENT,
            ErrorCode.SHOP_NOT_FOUND,
            ErrorCode.AMBIGUOUS_SHOP,
            ErrorCode.LOW_CONFIDENCE,
            ErrorCode.TOOL_NOT_REGISTERED,
            ErrorCode.SCHEMA_VALIDATION_FAILED,
            ErrorCode.LLM_JSON_PARSE_ERROR,
            ErrorCode.LLM_ENUM_OUT_OF_RANGE,
            ErrorCode.ANSWER_VERIFIER_FAILED,
        ]
        assert len(codes) == 13
        assert ErrorCode.TOOL_TIMEOUT.value == "TOOL_TIMEOUT"
        assert ErrorCode.BACKEND_UNAVAILABLE.value == "BACKEND_UNAVAILABLE"
        assert ErrorCode.ANSWER_VERIFIER_FAILED.value == "ANSWER_VERIFIER_FAILED"

    def test_semantic_parse_source_values(self):
        assert SemanticParseSource.real_llm.value == "real_llm"
        assert SemanticParseSource.diagnostic_rules.value == "diagnostic_rules"
        assert SemanticParseSource.fallback_rules.value == "fallback_rules"
        assert SemanticParseSource.test.value == "test"

    def test_grounding_status_values(self):
        assert GroundingStatus.grounded.value == "grounded"
        assert GroundingStatus.partially_grounded.value == "partially_grounded"
        assert GroundingStatus.ungrounded.value == "ungrounded"

    def test_missing_slot_type_values(self):
        assert MissingSlotType.missing_location.value == "missing_location"
        assert MissingSlotType.missing_shop_target.value == "missing_shop_target"
        assert MissingSlotType.missing_comparison_targets.value == "missing_comparison_targets"
