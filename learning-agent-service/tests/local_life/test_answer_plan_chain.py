from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

TESTS_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = TESTS_DIR.parent
SRC_ROOT = PROJECT_ROOT / "src"
for candidate in (str(TESTS_DIR), str(PROJECT_ROOT), str(SRC_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import _bootstrap  # noqa: F401

from learning_agent_service.domain import ChatTurnCommand, PersistentSessionContext
from learning_agent_service.local_life.answer_planner import (
    CandidateEvidenceSummary,
    CouponAdvice,
    EvidenceItem,
    GroundedVerificationResult,
    LocalLifeAnswerPlan,
    NextAction,
    SceneFitSummary,
)
from learning_agent_service.local_life.assistant import LocalLifeModelAssistant
from learning_agent_service.local_life.evidence_pack import build_evidence_pack
from learning_agent_service.local_life.grounded_verifier import GroundedVerifier
from learning_agent_service.local_life.response_builder import build_response_bundle
from learning_agent_service.local_life.schemas import EvidenceClaim, LocalLifeIntentType, LocalLifeSlots, RankedCandidate, ShopRecord, VoucherRecord
from learning_agent_service.local_life.subgraph import LocalLifeSubgraph
from learning_agent_service.rag.local_life_retrieval import LocalLifeEvidencePack, ParentEvidence, RetrievedChunk


def _ranked_candidate(
    *,
    shop_id: int,
    name: str,
    score: float = 4.8,
    distance_km: float = 1.2,
    avg_price: float = 98.0,
    vouchers: list[dict[str, object]] | None = None,
    risk_flags: list[str] | None = None,
    explainable_reasons: list[str] | None = None,
) -> RankedCandidate:
    return RankedCandidate(
        shop_id=shop_id,
        name=name,
        matched_requirements=["quiet", "parking"],
        structured_features={
            "score": score,
            "distance_km": distance_km,
            "avg_price": avg_price,
            "parking": True,
            "family_friendly": True,
            "elder_friendly": True,
            "quiet_score": 0.86,
            "open_hours": "10:00-22:00",
        },
        evidence_features={"quiet": 0.86},
        risk_flags=list(risk_flags or ["高峰期可能排队"]),
        explainable_reasons=list(explainable_reasons or ["安静", "有停车"]),
        vouchers=list(
            vouchers
            or [
                {
                    "id": 101,
                    "title": "满100减20",
                    "pay_value": 100,
                    "actual_value": 80,
                    "stock": 50,
                    "rules": "限工作日",
                }
            ]
        ),
        blog_snippets=["环境安静，适合约会。"],
        score_breakdown={"retrieval": 0.6, "fit": 0.2},
        rank_score=0.93,
    )


def _evidence_claim(
    *,
    chunk_id: str,
    shop_id: int,
    claim: str,
    source_type: str,
    confidence: float = 0.9,
) -> EvidenceClaim:
    return EvidenceClaim(
        chunk_id=chunk_id,
        shop_id=shop_id,
        claim=claim,
        support_text=claim,
        source_type=source_type,
        confidence=confidence,
        metadata={"shop_name": f"店铺{shop_id}", "shop_id": shop_id},
    )


class _FakeResponses:
    def __init__(self, output_text: str) -> None:
        self.output_text = output_text

    def create(self, **_: object) -> object:
        return SimpleNamespace(output_text=self.output_text)


class _FakeAssistantRuntime:
    def __init__(self, output_text: str) -> None:
        self.client = SimpleNamespace(responses=_FakeResponses(output_text))
        self.default_model = "fake-model"


class _FakeAssistantWithPlan(LocalLifeModelAssistant):
    def __init__(self, answer_plan: LocalLifeAnswerPlan) -> None:
        super().__init__(runtime=None)
        self._answer_plan = answer_plan

    def suggest_understanding(self, *, raw_query: str, **_: object) -> dict[str, object]:
        return {
            "normalized_query": raw_query.strip(),
            "semantic_query": raw_query.strip(),
            "keyword_query": raw_query.strip(),
            "confidence": 0.93,
        }

    def compose_answer_plan(self, **_: object) -> dict[str, object]:
        return self._answer_plan.model_dump(mode="json")

    def suggest_response(self, **_: object) -> dict[str, object]:
        return self._answer_plan.model_dump(mode="json")


class _FakeBusinessClient:
    enabled = True
    enable_fallback = False

    def search_candidates(self, *, query: str, slots: LocalLifeSlots, limit: int = 5):
        return [
            ShopRecord(
                id=1,
                name="卷卷烤肉",
                type_id=1,
                type_name="烤肉",
                area="朝阳",
                address="朝阳区测试路1号",
                x=116.4,
                y=39.9,
                avg_price=128.0,
                sold=88,
                comments=120,
                score=4.7,
                open_hours="10:00-22:00",
                distance_km=1.1,
                parking=True,
                quiet_score=0.85,
                family_friendly=True,
                elder_friendly=True,
                tags=["quiet", "parking_available"],
                review_summary="环境安静，适合约会和家庭聚餐。",
                evidence_texts=["店里环境比较安静。"],
                source="java",
            )
        ][:limit]

    def get_shop_detail(self, shop_id: int):
        return self.search_candidates(query="", slots=LocalLifeSlots())[0]

    def get_coupon_list(self, shop_id: int):
        return [
            VoucherRecord(
                id=101,
                shop_id=int(shop_id),
                shop_name="卷卷烤肉",
                title="满100减20",
                sub_title="家庭聚餐券",
                pay_value=100.0,
                actual_value=80.0,
                stock=50,
                source="java",
            )
        ]

    def check_open_status(self, shop):
        return {"open_status": "open", "open_now": True, "open_hours": getattr(shop, "open_hours", None)}

    def get_distance_eta(self, shop, *, lat, lng):
        return {"distance_km": getattr(shop, "distance_km", 1.1), "eta_minutes": 12, "lat": lat, "lng": lng}

    def get_blog_hot(self, current: int = 1):
        return []


class _FakeRetriever:
    def retrieve_local_life_evidence(self, query: str, **kwargs: object) -> LocalLifeEvidencePack:
        parent = ParentEvidence(
            parent_id="parent-1",
            parent_title="卷卷烤肉",
            entity_type="shop",
            entity_id="1",
            shop_id=1,
            shop_name="卷卷烤肉",
            city="北京",
            area="朝阳",
            category="烤肉",
            parent_score=0.93,
            matched_chunks=[
                RetrievedChunk(
                    point_id="pt-1",
                    chunk_id="evidence-review-1",
                    parent_id="parent-1",
                    chunk_role="review_summary",
                    source_type="review_summary",
                    title="评价摘要",
                    text="环境比较安静，适合家庭聚餐。",
                    score=0.93,
                    payload={"shop_id": 1, "shop_name": "卷卷烤肉"},
                ),
                RetrievedChunk(
                    point_id="pt-2",
                    chunk_id="evidence-scene-1",
                    parent_id="parent-1",
                    chunk_role="merchant_scene_fit",
                    source_type="scene_fit",
                    title="场景适配",
                    text="适合约会和带爸妈吃饭。",
                    score=0.91,
                    payload={"shop_id": 1, "shop_name": "卷卷烤肉"},
                ),
            ],
            sibling_chunks=[
                RetrievedChunk(
                    point_id="pt-3",
                    chunk_id="evidence-coupon-1",
                    parent_id="parent-1",
                    chunk_role="package_description",
                    source_type="coupon",
                    title="优惠券",
                    text="满100减20，工作日可用。",
                    score=0.89,
                    payload={"shop_id": 1, "shop_name": "卷卷烤肉"},
                )
            ],
            parent_context=None,
            role_coverage=["review_summary", "merchant_scene_fit", "package_description"],
            score_breakdown={"scene_fit": 0.9},
            business_facts={"shop_id": 1, "shop_name": "卷卷烤肉", "score": 4.7, "avg_price": 128},
            debug_info={},
        )
        return LocalLifeEvidencePack(
            query=query,
            filters={"city": kwargs.get("city"), "category": kwargs.get("category")},
            parent_evidences=[parent],
            total_child_hits=3,
            retrieval_strategy="parent_child_rag->shop_rerank",
            route=str(kwargs.get("route") or "merchant_reasoning"),
            route_reason="test",
        )


class _FakeSafetyResult:
    approval_required = False
    reason = "ok"
    risk_level = "low"
    approval_request = {}
    transaction_draft = None

    def model_dump(self, mode: str = "json") -> dict[str, object]:
        return {
            "approval_required": self.approval_required,
            "reason": self.reason,
            "risk_level": self.risk_level,
            "approval_request": self.approval_request,
            "transaction_draft": self.transaction_draft,
        }


class AnswerPlanChainTestCase(unittest.TestCase):
    def test_evidence_pack_is_compact_and_groups_evidence_by_shop(self) -> None:
        ranked_candidates = [
            _ranked_candidate(shop_id=1, name="卷卷烤肉"),
            _ranked_candidate(shop_id=2, name="朴朴家常菜", vouchers=[], explainable_reasons=["家常菜"]),
        ]
        evidence_claims = [
            _evidence_claim(chunk_id="c1", shop_id=1, claim="环境安静", source_type="review_summary"),
            _evidence_claim(chunk_id="c2", shop_id=1, claim="适合家庭聚餐", source_type="scene_fit"),
            _evidence_claim(chunk_id="c3", shop_id=2, claim="价格实惠", source_type="shop_fact"),
        ]

        pack = build_evidence_pack(
            raw_query="附近适合带爸妈吃饭的店，安静一点，有停车最好",
            ranked_candidates=ranked_candidates,
            evidence_claims=evidence_claims,
            slots=LocalLifeSlots(category="烤肉", scene="family_dinner", city="北京", preferences=["quiet", "parking_available"]),
            source_summary={"source_mode": "mixed", "degraded_reason": None, "knowledge_freshness": {"source_mode": "mixed"}},
            safety_result={"approval_required": False, "reason": "ok"},
        )

        self.assertLessEqual(len(pack.candidate_summaries), 3)
        self.assertTrue(all(item.evidence_used for item in pack.candidate_summaries))
        self.assertIn("1", pack.shop_evidence_map)
        self.assertLessEqual(len(pack.items), 6)
        self.assertTrue(all(item.evidence_id for item in pack.items))

    def test_assistant_returns_empty_plan_when_runtime_is_missing(self) -> None:
        assistant = LocalLifeModelAssistant(runtime=None)

        plan = assistant.compose_answer_plan(
            raw_query="这家店怎么样",
            slots=LocalLifeSlots(category="烤肉"),
            ranked_candidates=[],
            evidence_pack=None,
            safety_result={},
        )

        self.assertEqual(plan, {})

    def test_assistant_rejects_invalid_json_response(self) -> None:
        assistant = LocalLifeModelAssistant(runtime=_FakeAssistantRuntime("not json at all"))

        plan = assistant.compose_answer_plan(
            raw_query="这家店怎么样",
            slots=LocalLifeSlots(category="烤肉"),
            ranked_candidates=[],
            evidence_pack=None,
            safety_result={},
        )

        self.assertEqual(plan, {})

    def test_verifier_rejects_unknown_evidence_ids(self) -> None:
        plan = LocalLifeAnswerPlan(
            answer_text="这家店很适合约会。",
            decision_type="recommend",
            recommendation_summary="适合约会",
            top_choice=CandidateEvidenceSummary(
                shop_id=1,
                name="卷卷烤肉",
                rank=1,
                fit_score=0.93,
                why=["安静"],
                risks=["排队"],
                coupon_summary="有券",
                scene_fit=SceneFitSummary(scene="date", fit="high", reason="适合约会"),
                evidence_used=["missing-evidence"],
            ),
            candidate_reasons=[],
            scene_fit_summary=SceneFitSummary(scene="date", fit="high", reason="适合约会"),
            coupon_advice=CouponAdvice(has_coupon=True, worth_it="high", reason="值得", risk="无"),
            risk_points=["排队"],
            missing_info=[],
            next_actions=[NextAction(label="看详情", action="view_detail", shop_id=1)],
            suggested_replies=["看看别家"],
            evidence_used=["missing-evidence"],
            confidence="high",
            source_mode="mixed",
            degraded_reason=None,
            knowledge_freshness={},
        )
        pack = build_evidence_pack(
            raw_query="这家店怎么样",
            ranked_candidates=[_ranked_candidate(shop_id=1, name="卷卷烤肉")],
            evidence_claims=[_evidence_claim(chunk_id="c1", shop_id=1, claim="环境安静", source_type="review_summary")],
            slots=LocalLifeSlots(category="烤肉"),
            source_summary={"source_mode": "mixed", "degraded_reason": None, "knowledge_freshness": {}},
            safety_result={"approval_required": False},
        )

        result = GroundedVerifier().verify(
            answer_plan=plan,
            evidence_pack=pack,
            ranked_candidates=[_ranked_candidate(shop_id=1, name="卷卷烤肉")],
            safety_result={},
        )

        self.assertFalse(result.passed)
        self.assertIn("unknown_evidence_id", result.issues)

    def test_verifier_corrects_false_positive_coupon_advice(self) -> None:
        plan = LocalLifeAnswerPlan(
            answer_text="这家店有券，值得领。",
            decision_type="coupon_advice",
            recommendation_summary="优惠券建议",
            top_choice=None,
            candidate_reasons=[],
            scene_fit_summary=SceneFitSummary(scene="unknown", fit="unknown", reason=""),
            coupon_advice=CouponAdvice(has_coupon=True, worth_it="high", reason="值得", risk="无"),
            risk_points=[],
            missing_info=[],
            next_actions=[],
            suggested_replies=["帮我看看别家"],
            evidence_used=["c1"],
            confidence="high",
            source_mode="mixed",
            degraded_reason=None,
            knowledge_freshness={},
        )
        pack = build_evidence_pack(
            raw_query="这家店的券值得买吗",
            ranked_candidates=[_ranked_candidate(shop_id=1, name="卷卷烤肉", vouchers=[])],
            evidence_claims=[_evidence_claim(chunk_id="c1", shop_id=1, claim="只有评价，没有优惠信息", source_type="review_summary")],
            slots=LocalLifeSlots(category="烤肉"),
            source_summary={"source_mode": "mixed", "degraded_reason": None, "knowledge_freshness": {}},
            safety_result={"approval_required": False},
        )

        result = GroundedVerifier().verify(
            answer_plan=plan,
            evidence_pack=pack,
            ranked_candidates=[_ranked_candidate(shop_id=1, name="卷卷烤肉", vouchers=[])],
            safety_result={},
        )

        self.assertTrue(result.passed)
        self.assertIn("coupon_evidence_missing", result.warnings)
        self.assertEqual(result.normalized_plan["coupon_advice"]["has_coupon"], False)

    def test_response_builder_prefers_valid_answer_plan_and_keeps_legacy_shape(self) -> None:
        ranked_candidates = [_ranked_candidate(shop_id=1, name="卷卷烤肉")]
        evidence_claims = [_evidence_claim(chunk_id="c1", shop_id=1, claim="环境安静", source_type="review_summary")]
        pack = build_evidence_pack(
            raw_query="附近适合带爸妈吃饭的店，安静一点，有停车最好",
            ranked_candidates=ranked_candidates,
            evidence_claims=evidence_claims,
            slots=LocalLifeSlots(category="烤肉", scene="family_dinner", city="北京"),
            source_summary={"source_mode": "mixed", "degraded_reason": None, "knowledge_freshness": {"source_mode": "mixed"}},
            safety_result={"approval_required": False},
        )
        plan = LocalLifeAnswerPlan(
            answer_text="推荐卷卷烤肉，适合带爸妈去，安静且有停车。",
            decision_type="recommend",
            recommendation_summary="适合家庭聚餐",
            top_choice=CandidateEvidenceSummary(
                shop_id=1,
                name="卷卷烤肉",
                rank=1,
                fit_score=0.93,
                why=["安静", "有停车"],
                risks=["高峰排队"],
                coupon_summary="有券",
                scene_fit=SceneFitSummary(scene="family_dinner", fit="high", reason="适合带爸妈"),
                evidence_used=["c1"],
            ),
            candidate_reasons=[
                CandidateEvidenceSummary(
                    shop_id=1,
                    name="卷卷烤肉",
                    rank=1,
                    fit_score=0.93,
                    why=["安静", "有停车"],
                    risks=["高峰排队"],
                    coupon_summary="有券",
                    scene_fit=SceneFitSummary(scene="family_dinner", fit="high", reason="适合带爸妈"),
                    evidence_used=["c1"],
                )
            ],
            scene_fit_summary=SceneFitSummary(scene="family_dinner", fit="high", reason="适合带爸妈"),
            coupon_advice=CouponAdvice(has_coupon=True, worth_it="medium", reason="券能省一点", risk="限时"),
            risk_points=["高峰排队"],
            missing_info=[],
            next_actions=[NextAction(label="看详情", action="view_detail", shop_id=1)],
            suggested_replies=["帮我对比前两家", "只看有停车的"],
            evidence_used=["c1"],
            confidence="high",
            source_mode="mixed",
            degraded_reason=None,
            knowledge_freshness={"source_mode": "mixed"},
        )
        verification = GroundedVerificationResult(
            passed=True,
            issues=[],
            warnings=[],
            suggested_response_mode="grounded",
            normalized_plan=plan.model_dump(mode="json"),
        )

        bundle = build_response_bundle(
            raw_query="附近适合带爸妈吃饭的店，安静一点，有停车最好",
            slots=LocalLifeSlots(category="烤肉", scene="family_dinner", city="北京"),
            ranked_candidates=ranked_candidates,
            evidence_claims=evidence_claims,
            page="assistant",
            current_topic="卷卷烤肉",
            selected_shop_id=1,
            source="local-life-agent",
            fallback=False,
            mode="recommend",
            approval_required=False,
            safety_result={"approval_required": False},
            source_mode="mixed",
            degraded_reason=None,
            knowledge_freshness={"source_mode": "mixed"},
            answer_plan=plan,
            verification_result=verification,
            evidence_pack=pack,
        )

        self.assertIn("适合带爸妈", bundle.answer_text)
        self.assertTrue(bundle.metrics["answer_plan_enabled"])
        self.assertTrue(bundle.metrics["answer_plan_valid"])
        self.assertTrue(bundle.metrics["verifier_passed"])
        self.assertEqual(bundle.metrics["evidence_pack_item_count"], len(pack.items))
        self.assertEqual(bundle.suggested_replies[0]["label"], "帮我对比前两家")
        self.assertEqual(bundle.citations[0]["chunk_id"], "c1")

    def test_response_builder_blocks_direct_booking_when_approval_is_required(self) -> None:
        ranked_candidates = [_ranked_candidate(shop_id=1, name="卷卷烤肉")]
        plan = LocalLifeAnswerPlan(
            answer_text="这是订座草案，确认后我再继续执行。",
            decision_type="booking",
            recommendation_summary="订座前确认",
            top_choice=CandidateEvidenceSummary(
                shop_id=1,
                name="卷卷烤肉",
                rank=1,
                fit_score=0.91,
                why=["离得近"],
                risks=["需要确认"],
                coupon_summary="无券",
                scene_fit=SceneFitSummary(scene="date", fit="medium", reason="适合约会"),
                evidence_used=["c1"],
            ),
            candidate_reasons=[],
            scene_fit_summary=SceneFitSummary(scene="date", fit="medium", reason="适合约会"),
            coupon_advice=CouponAdvice(has_coupon=False, worth_it="unknown", reason="无券", risk="未知"),
            risk_points=["需要确认"],
            missing_info=[],
            next_actions=[NextAction(label="确认继续", action="confirm"), NextAction(label="先不执行", action="cancel")],
            suggested_replies=["确认继续", "先不执行"],
            evidence_used=["c1"],
            confidence="medium",
            source_mode="mixed",
            degraded_reason=None,
            knowledge_freshness={},
        )
        verification = GroundedVerificationResult(
            passed=True,
            issues=[],
            warnings=[],
            suggested_response_mode="grounded",
            normalized_plan=plan.model_dump(mode="json"),
        )

        bundle = build_response_bundle(
            raw_query="帮我订这家",
            slots=LocalLifeSlots(category="烤肉", scene="date", city="北京"),
            ranked_candidates=ranked_candidates,
            evidence_claims=[_evidence_claim(chunk_id="c1", shop_id=1, claim="环境不错", source_type="review_summary")],
            page="assistant",
            current_topic="卷卷烤肉",
            selected_shop_id=1,
            source="local-life-agent",
            fallback=False,
            mode="booking",
            approval_required=True,
            safety_result={"approval_required": True, "reason": "需要确认"},
            source_mode="mixed",
            degraded_reason=None,
            knowledge_freshness={},
            answer_plan=plan,
            verification_result=verification,
        )

        self.assertIn("确认后我再继续执行", bundle.answer_text)
        self.assertEqual(bundle.suggested_replies[0]["label"], "确认继续")
        self.assertTrue(bundle.approval_required)

    def test_response_builder_uses_coupon_evidence_when_realtime_vouchers_are_empty(self) -> None:
        ranked_candidates = [
            RankedCandidate(
                shop_id=5,
                name="海底捞火锅(水晶城购物中心店）",
                matched_requirements=["quiet", "parking"],
                structured_features={
                    "score": 4.5,
                    "distance_km": 1.8,
                    "avg_price": 104.0,
                    "parking": True,
                    "family_friendly": True,
                    "elder_friendly": True,
                    "quiet_score": 0.74,
                    "open_hours": "10:00-07:00",
                },
                evidence_features={"quiet": 0.74},
                risk_flags=[],
                explainable_reasons=["适合家庭"],
                vouchers=[],
                blog_snippets=[],
                score_breakdown={"retrieval": 0.5},
                rank_score=0.81,
            )
        ]
        evidence_claims = [
            _evidence_claim(
                chunk_id="voucher-evidence-1",
                shop_id=5,
                claim="有优惠券和套餐描述",
                source_type="voucher_rule",
            )
        ]

        bundle = build_response_bundle(
            raw_query="这家店有券吗",
            slots=LocalLifeSlots(category="火锅", scene="date", city="杭州"),
            ranked_candidates=ranked_candidates,
            evidence_claims=evidence_claims,
            page="assistant",
            current_topic="海底捞火锅(水晶城购物中心店）",
            selected_shop_id=5,
            source="local-life-agent",
            fallback=False,
            mode="coupon",
            approval_required=False,
            safety_result={"approval_required": False},
            route_decision="rag_plus_tool",
            source_mode="mixed",
            degraded_reason=None,
            knowledge_freshness={"source_mode": "mixed"},
        )

        self.assertIn("知识库里有优惠或套餐线索", bundle.answer_text)
        self.assertNotIn("暂时没看到可用券", bundle.answer_text)

    def test_subgraph_uses_answer_plan_and_verifier_in_final_payload(self) -> None:
        answer_plan = LocalLifeAnswerPlan(
            answer_text="推荐卷卷烤肉，适合带爸妈吃饭，安静且有停车。券也值得顺手领。",
            decision_type="recommend",
            recommendation_summary="适合家庭聚餐",
            top_choice=CandidateEvidenceSummary(
                shop_id=1,
                name="卷卷烤肉",
                rank=1,
                fit_score=0.94,
                why=["安静", "有停车"],
                risks=["高峰排队"],
                coupon_summary="有券且值得领",
                scene_fit=SceneFitSummary(scene="family_dinner", fit="high", reason="适合带爸妈"),
                evidence_used=["evidence-review-1", "evidence-scene-1"],
            ),
            candidate_reasons=[
                CandidateEvidenceSummary(
                    shop_id=1,
                    name="卷卷烤肉",
                    rank=1,
                    fit_score=0.94,
                    why=["安静", "有停车"],
                    risks=["高峰排队"],
                    coupon_summary="有券且值得领",
                    scene_fit=SceneFitSummary(scene="family_dinner", fit="high", reason="适合带爸妈"),
                    evidence_used=["evidence-review-1", "evidence-scene-1"],
                )
            ],
            scene_fit_summary=SceneFitSummary(scene="family_dinner", fit="high", reason="适合带爸妈"),
            coupon_advice=CouponAdvice(has_coupon=True, worth_it="high", reason="券能省钱", risk="限时"),
            risk_points=["高峰排队"],
            missing_info=[],
            next_actions=[NextAction(label="看详情", action="view_detail", shop_id=1)],
            suggested_replies=["帮我对比前两家", "只看有停车的"],
            evidence_used=["evidence-review-1", "evidence-scene-1"],
            confidence="high",
            source_mode="mixed",
            degraded_reason=None,
            knowledge_freshness={"source_mode": "mixed"},
        )
        subgraph = LocalLifeSubgraph(
            business_client=_FakeBusinessClient(),
            model_assistant=_FakeAssistantWithPlan(answer_plan),
            local_life_retriever=_FakeRetriever(),
        )

        events = list(
            subgraph.run_stream(
                ChatTurnCommand(
                    trace_id="trace-answer-plan",
                    session_id="session-answer-plan",
                    turn_id="turn-answer-plan",
                    user_id="user-answer-plan",
                    message="附近适合带爸妈吃饭的店，安静一点，有停车最好",
                    page="assistant",
                    client_context={"city": "北京", "lat": 39.9, "lng": 116.4},
                ),
                persistent_context=PersistentSessionContext(),
            )
        )
        final_payload = next(event.payload for event in events if event.event_type == "final")

        self.assertIn("适合带爸妈吃饭", final_payload["answer_text"])
        self.assertTrue(final_payload["metrics"]["answer_plan_enabled"])
        self.assertTrue(final_payload["metrics"]["answer_plan_valid"])
        self.assertEqual(final_payload["context"]["metrics"]["answer_plan_enabled"], True)
        self.assertGreaterEqual(final_payload["metrics"]["evidence_pack_item_count"], 1)
        self.assertTrue(final_payload["suggested_replies"])


if __name__ == "__main__":
    unittest.main()
