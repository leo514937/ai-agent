from __future__ import annotations

import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = TESTS_DIR.parent
SRC_ROOT = PROJECT_ROOT / "src"
for candidate in (str(TESTS_DIR), str(PROJECT_ROOT), str(SRC_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import _bootstrap  # noqa: F401

from learning_agent_service.domain import ChatTurnCommand, PersistentSessionContext
from learning_agent_service.local_life.answer_sanitizer import sanitize_local_life_output, sanitize_local_life_text
from learning_agent_service.local_life.context_arbitration import ContextArbitration
from learning_agent_service.local_life.evidence_scope_guard import EvidenceScopeGuard
from learning_agent_service.local_life.response_builder import build_response_bundle
from learning_agent_service.local_life.entity_resolver import EntityResolver
from learning_agent_service.local_life.query_router import LocalLifeRouteDecision
from learning_agent_service.local_life.schemas import (
    LocalLifeIntentType,
    LocalLifeSlots,
    LocationNorm,
    PriceNorm,
    QueryUnderstandingResult,
    EvidenceClaim,
    RankedCandidate,
    ShopRecord,
    TimeNorm,
)
from learning_agent_service.local_life.slot_extractor import extract_slots
from learning_agent_service.local_life.subgraph import LocalLifeSubgraph
from learning_agent_service.local_life.user_need_parser import UserNeedParser
from learning_agent_service.rag.local_life_retrieval import LocalLifeEvidencePack, ParentEvidence, RetrievedChunk


def _understanding(query: str) -> QueryUnderstandingResult:
    return QueryUnderstandingResult(
        normalized_query=query.strip(),
        semantic_query=query.strip(),
        keyword_query=query.strip(),
        time_norm=TimeNorm(),
        location_norm=LocationNorm(),
        confidence=0.93,
    )


def _shop(
    *,
    shop_id: int,
    name: str,
    area: str = "水晶城",
    avg_price: float = 104.0,
    score: float = 4.7,
    source: str = "java",
) -> ShopRecord:
    return ShopRecord(
        id=shop_id,
        name=name,
        type_id=1,
        type_name="火锅",
        area=area,
        address=f"{area}测试路1号",
        x=116.4,
        y=39.9,
        avg_price=avg_price,
        sold=88,
        comments=2764,
        score=score,
        open_hours="10:00-07:00",
        distance_km=1.2,
        parking=True,
        quiet_score=0.82,
        family_friendly=True,
        elder_friendly=True,
        tags=["quiet", "parking_available"],
        review_summary="环境相对安静，适合家庭聚餐。",
        evidence_texts=["环境安静，停车条件在部分时段还能接受。"],
        source=source,
    )


def _evidence_pack_for(shop: ShopRecord, query: str) -> LocalLifeEvidencePack:
    parent = ParentEvidence(
        parent_id=f"parent-{shop.id}",
        parent_title=shop.name,
        entity_type="shop",
        entity_id=str(shop.id),
        shop_id=shop.id,
        shop_name=shop.name,
        city="北京",
        area=shop.area,
        category="火锅",
        parent_score=0.94,
        matched_chunks=[
            RetrievedChunk(
                point_id=f"pt-{shop.id}-review",
                chunk_id=f"review-{shop.id}",
                parent_id=f"parent-{shop.id}",
                chunk_role="review_summary",
                source_type="review_summary",
                title="口碑摘要",
                text="环境相对安静，适合家庭一起吃饭。",
                score=0.93,
                payload={"shop_id": shop.id, "shop_name": shop.name},
            ),
            RetrievedChunk(
                point_id=f"pt-{shop.id}-scene",
                chunk_id=f"scene-{shop.id}",
                parent_id=f"parent-{shop.id}",
                chunk_role="merchant_scene_fit",
                source_type="scene_fit",
                title="场景适配",
                text="适合约会、家庭聚餐和带长辈。",
                score=0.91,
                payload={"shop_id": shop.id, "shop_name": shop.name},
            ),
        ],
        sibling_chunks=[
            RetrievedChunk(
                point_id=f"pt-{shop.id}-coupon",
                chunk_id=f"coupon-{shop.id}",
                parent_id=f"parent-{shop.id}",
                chunk_role="package_description",
                source_type="coupon",
                title="优惠券",
                text="满100减20，可参考。",
                score=0.9,
                payload={"shop_id": shop.id, "shop_name": shop.name},
            )
        ],
        parent_context=None,
        role_coverage=["review_summary", "merchant_scene_fit", "package_description"],
        score_breakdown={"scene_fit": 0.9},
        business_facts={"shop_id": shop.id, "shop_name": shop.name, "score": shop.score, "avg_price": shop.avg_price},
        debug_info={},
    )
    return LocalLifeEvidencePack(
        query=query,
        filters={"city": "北京", "candidate_shop_ids": [shop.id]},
        parent_evidences=[parent],
        total_child_hits=3,
        retrieval_strategy="parent_child_rag->shop_rerank",
        route="structured_first",
        route_reason="test",
    )


class _FakeAssistant:
    def suggest_understanding(self, *, raw_query: str, **_: object) -> dict[str, object]:
        return {
            "normalized_query": raw_query.strip(),
            "semantic_query": raw_query.strip(),
            "keyword_query": raw_query.strip(),
            "confidence": 0.93,
        }

    def compose_answer_plan(self, **_: object) -> dict[str, object]:
        return {}

    def suggest_response(self, **_: object) -> dict[str, object]:
        return {}


class _FakeSessionStore:
    def __init__(self) -> None:
        self.saved_contexts: list[PersistentSessionContext] = []

    def save(self, context: PersistentSessionContext, runtime: object) -> None:
        self.saved_contexts.append(context)


class _FakeRetriever:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def retrieve_local_life_evidence(self, query: str, **kwargs: object) -> LocalLifeEvidencePack:
        self.calls.append({"query": query, **kwargs})
        candidate_ids = list(kwargs.get("candidate_shop_ids") or [])
        shop_id = candidate_ids[0] if candidate_ids else 5
        shop = _shop(shop_id=shop_id, name="海底捞火锅(水晶城购物中心店）" if shop_id == 5 else "INLOVE KTV(水晶城店)")
        return _evidence_pack_for(shop, query)


class _FakeBusinessClient:
    enabled = True
    enable_fallback = False

    def __init__(self) -> None:
        self.search_calls: list[str] = []
        self.detail_calls: list[int] = []
        self.coupon_calls: list[int] = []

    def search_candidates(self, *, query: str, slots: LocalLifeSlots, limit: int = 5):
        self.search_calls.append(query)
        if "INLOVE" in query.upper():
            return [_shop(shop_id=9, name="INLOVE KTV(水晶城店)", area="水晶城", avg_price=128.0, score=4.8)]
        if "海底捞" in query:
            return [_shop(shop_id=5, name="海底捞火锅(水晶城购物中心店）", area="水晶城", avg_price=104.0, score=4.6)]
        return [
            _shop(shop_id=5, name="海底捞火锅(水晶城购物中心店）", area="水晶城"),
            _shop(shop_id=9, name="INLOVE KTV(水晶城店)", area="水晶城", avg_price=128.0, score=4.8),
        ][:limit]

    def get_shop_detail(self, shop_id: int):
        self.detail_calls.append(int(shop_id))
        if int(shop_id) == 9:
            return _shop(shop_id=9, name="INLOVE KTV(水晶城店)", area="水晶城", avg_price=128.0, score=4.8)
        return _shop(shop_id=5, name="海底捞火锅(水晶城购物中心店）", area="水晶城", avg_price=104.0, score=4.6)

    def get_coupon_list(self, shop_id: int):
        self.coupon_calls.append(int(shop_id))
        return []

    def check_open_status(self, shop):
        return {"open_status": "open", "open_now": True, "open_hours": getattr(shop, "open_hours", None)}

    def get_distance_eta(self, shop, *, lat, lng):
        return {"distance_km": getattr(shop, "distance_km", 1.2), "eta_minutes": 12, "lat": lat, "lng": lng}

    def get_blog_hot(self, current: int = 1):
        return []


class P0ContextContractTestCase(unittest.TestCase):
    def test_explicit_entity_beats_session_anchor(self) -> None:
        query = "INLOVE KTV(水晶城店) 这家现在有券吗？"
        session_context = {
            "current_shop": "海底捞火锅(水晶城购物中心店）",
            "selected_shop_id": 5,
            "selected_shop_name": "海底捞火锅(水晶城购物中心店）",
            "last_candidates": [{"shop_id": 5, "name": "海底捞火锅(水晶城购物中心店）"}],
        }
        slots, clarification, intent = extract_slots(
            _understanding(query),
            query,
            client_context={"city": "北京"},
            session_context=session_context,
        )
        self.assertEqual(slots.shop_query, "INLOVE KTV(水晶城店)")
        self.assertEqual(intent, LocalLifeIntentType.COUPON)
        self.assertFalse(clarification.need_clarification)

        user_need = UserNeedParser.parse(
            query,
            slots=slots,
            intent=intent,
            client_context={"city": "北京"},
            session_context=session_context,
        )
        self.assertEqual(user_need.context_refs[0].source, "explicit_entity")

        contract = EntityResolver().resolve(
            raw_query=query,
            slots=slots,
            user_need=user_need,
            session_context=session_context,
            client_context={"city": "北京"},
        )
        self.assertEqual(contract.resolved_shop_name, "INLOVE KTV(水晶城店)")
        self.assertNotEqual(contract.resolved_shop_id, 5)
        self.assertNotIn(5, contract.candidate_shop_ids)
        self.assertTrue(contract.forbid_global_fallback)

    def test_pronoun_without_context_requests_clarification(self) -> None:
        query = "这家适合约会吗？"
        slots, clarification, intent = extract_slots(
            _understanding(query),
            query,
            client_context={"city": "北京"},
            session_context={},
        )
        self.assertIsNone(slots.shop_query)
        self.assertEqual(intent, LocalLifeIntentType.DETAIL)
        self.assertFalse(clarification.need_clarification)

        user_need = UserNeedParser.parse(
            query,
            slots=slots,
            intent=intent,
            client_context={"city": "北京"},
            session_context={},
        )
        contract = EntityResolver().resolve(
            raw_query=query,
            slots=slots,
            user_need=user_need,
            session_context={},
            client_context={"city": "北京"},
        )
        self.assertEqual(contract.clarification_action, "reference_clarify")
        self.assertTrue(contract.forbid_global_fallback)

    def test_pronoun_with_context_uses_current_shop(self) -> None:
        query = "这家适合约会吗？"
        session_context = {
            "current_shop": "海底捞火锅(水晶城购物中心店）",
            "selected_shop_id": 5,
            "selected_shop_name": "海底捞火锅(水晶城购物中心店）",
            "last_candidates": [{"shop_id": 5, "name": "海底捞火锅(水晶城购物中心店）"}],
        }
        slots, clarification, intent = extract_slots(
            _understanding(query),
            query,
            client_context={"city": "北京"},
            session_context=session_context,
        )
        self.assertIsNone(slots.shop_query)
        user_need = UserNeedParser.parse(
            query,
            slots=slots,
            intent=intent,
            client_context={"city": "北京"},
            session_context=session_context,
        )
        contract = EntityResolver().resolve(
            raw_query=query,
            slots=slots,
            user_need=user_need,
            session_context=session_context,
            client_context={"city": "北京"},
        )
        self.assertFalse(clarification.need_clarification)
        self.assertEqual(contract.resolved_shop_id, 5)
        self.assertEqual(contract.candidate_shop_ids[:1], [5])
        self.assertEqual(contract.reason, "pronoun_reference")

    def test_sanitizer_rewrites_internal_ids_and_status_words(self) -> None:
        text = "shop:5 / shop_id=5 / open / closed / 0.49000000000000005"
        sanitized = sanitize_local_life_text(text, shop_lookup={5: "海底捞火锅(水晶城购物中心店）"})
        self.assertNotIn("shop:5", sanitized)
        self.assertNotIn("shop_id=5", sanitized)
        self.assertIn("海底捞火锅(水晶城购物中心店）", sanitized)
        self.assertIn("营业中", sanitized)
        self.assertIn("未营业", sanitized)
        self.assertIn("0.5", sanitized)

    def test_pending_user_need_is_restored_by_context_arbitration(self) -> None:
        query = "北京"
        base_query = "附近有没有人均100以内、适合朋友聚餐的烤肉？"
        slots, _, intent = extract_slots(
            _understanding(query),
            query,
            client_context={"city": "北京"},
            session_context={
                "pending_user_need": {
                    "raw_query": base_query,
                    "slots": {
                        "category": "烤肉",
                        "price": {"per_person_max": 100, "target": 100},
                        "scene": "friends",
                        "preferences": ["friends"],
                    },
                    "required_facets": [{"name": "location"}, {"name": "category"}],
                }
            },
        )
        user_need = UserNeedParser.parse(
            query,
            slots=slots,
            intent=intent,
            client_context={"city": "北京"},
            session_context={
                "pending_user_need": {
                    "raw_query": base_query,
                    "slots": {
                        "category": "烤肉",
                        "price": {"per_person_max": 100, "target": 100},
                        "scene": "friends",
                        "preferences": ["friends"],
                    },
                    "required_facets": [{"name": "location"}, {"name": "category"}],
                }
            },
        )
        result = ContextArbitration().arbitrate(
            raw_query=query,
            slots=slots,
            user_need=user_need,
            session_context={
                "pending_user_need": {
                    "raw_query": base_query,
                    "slots": {
                        "category": "烤肉",
                        "price": {"per_person_max": 100, "target": 100},
                        "scene": "friends",
                        "preferences": ["friends"],
                    },
                    "required_facets": [{"name": "location"}, {"name": "category"}],
                }
            },
            client_context={"city": "北京"},
        )
        merged_need = result["user_need"]
        self.assertEqual(merged_need.slots.city, "北京")
        self.assertEqual(merged_need.slots.category, "烤肉")
        self.assertEqual(merged_need.slots.price.per_person_max, 100)
        self.assertEqual(merged_need.slots.scene, "friends")
        self.assertTrue(result["restored_pending_need"])
        self.assertEqual(result["clarification_action"], "resume_pending_need")

    def test_evidence_scope_guard_filters_out_of_scope_citations(self) -> None:
        citations = [
            {"document_id": "5", "title": "海底捞"},
            {"document_id": "9", "title": "INLOVE"},
        ]
        filtered = EvidenceScopeGuard.filter_evidence_claims(
            [
                {"shop_id": 5, "chunk_id": "c1", "claim": "海底捞"},
                {"shop_id": 9, "chunk_id": "c2", "claim": "INLOVE"},
            ],
            ranked_candidates=[{"shop_id": 5, "name": "海底捞火锅(水晶城购物中心店）"}],
            evidence_pack={"ranked_candidates": [{"shop_id": 5, "name": "海底捞火锅(水晶城购物中心店）"}]},
        )
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["shop_id"], 5)
        self.assertEqual(citations[0]["document_id"], "5")

    def test_facet_driven_template_prefers_requested_facets(self) -> None:
        query = "这家现在有券吗？"
        slots, _, intent = extract_slots(
            _understanding(query),
            query,
            client_context={"city": "北京"},
            session_context={
                "current_shop": "海底捞火锅(水晶城购物中心店）",
                "selected_shop_id": 5,
                "selected_shop_name": "海底捞火锅(水晶城购物中心店）",
            },
        )
        user_need = UserNeedParser.parse(
            query,
            slots=slots,
            intent=intent,
            client_context={"city": "北京"},
            session_context={
                "current_shop": "海底捞火锅(水晶城购物中心店）",
                "selected_shop_id": 5,
                "selected_shop_name": "海底捞火锅(水晶城购物中心店）",
            },
        )
        bundle = build_response_bundle(
            raw_query=query,
            slots=slots,
            ranked_candidates=[
                RankedCandidate(
                    shop_id=5,
                    name="海底捞火锅(水晶城购物中心店）",
                    matched_requirements=["coupon", "open_status"],
                    structured_features={"distance_km": 1.2, "avg_price": 104.0, "score": 4.6, "open_hours": "10:00-07:00"},
                    evidence_features={},
                    risk_flags=[],
                    explainable_reasons=["有券", "营业中"],
                    vouchers=[{"id": 1, "title": "满100减20", "pay_value": 100, "actual_value": 80}],
                    blog_snippets=[],
                    score_breakdown={},
                    rank_score=0.9,
                )
            ],
            evidence_claims=[EvidenceClaim(chunk_id="c1", shop_id=5, claim="有券", support_text="有券", source_type="coupon", confidence=0.9)],
            page="meituan_search_box",
            current_topic="海底捞火锅(水晶城购物中心店）",
            selected_shop_id=5,
            current_shop="海底捞火锅(水晶城购物中心店）",
            mode="coupon",
            source="local-life-agent",
            client_context={"city": "北京"},
            user_need=user_need,
            evidence_pack=None,
            source_mode="java_business",
            knowledge_freshness={},
        )
        self.assertIn("券信息", bundle.answer_text)
        self.assertNotIn("环境评价", bundle.answer_text)

    def test_subgraph_round_trip_keeps_explicit_entity_and_session_anchor_separate(self) -> None:
        business_client = _FakeBusinessClient()
        retriever = _FakeRetriever()
        session_store = _FakeSessionStore()
        subgraph = LocalLifeSubgraph(
            business_client=business_client,
            model_assistant=_FakeAssistant(),
            local_life_retriever=retriever,
            session_context_store=session_store,
        )
        initial_context = PersistentSessionContext(
            current_shop="海底捞火锅(水晶城购物中心店）",
            current_shop_anchor={"shop_id": 5, "shop_name": "海底捞火锅(水晶城购物中心店）"},
            selected_shop_id=5,
            selected_shop_name="海底捞火锅(水晶城购物中心店）",
            last_candidates=[{"shop_id": 5, "name": "海底捞火锅(水晶城购物中心店）"}],
        )
        events = list(
            subgraph.run_stream(
                ChatTurnCommand(
                    trace_id="trace-explicit-entity",
                    session_id="session-explicit-entity",
                    turn_id="turn-explicit-entity",
                    user_id="user-explicit-entity",
                    message="INLOVE KTV(水晶城店) 这家现在有券吗？",
                    page="meituan_search_box",
                    client_context={"city": "北京"},
                ),
                persistent_context=initial_context,
            )
        )
        final_payload = next(event.payload for event in events if event.event_type == "final")
        self.assertEqual(final_payload["context"]["selected_shop_id"], 9)
        self.assertEqual(business_client.coupon_calls[:1], [9])
        self.assertEqual(retriever.calls[0]["candidate_shop_ids"], [9])
        self.assertNotIn("shop:5", final_payload["answer_text"])
        self.assertEqual(session_store.saved_contexts[-1].current_shop_anchor.get("shop_id"), 9)
        self.assertEqual(session_store.saved_contexts[-1].selected_shop_id, 9)
