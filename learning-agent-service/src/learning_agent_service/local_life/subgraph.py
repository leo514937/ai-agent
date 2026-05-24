from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional
from uuid import uuid4

from learning_agent_service.api.contracts import (
    AckPayload,
    ApprovalRequiredPayload,
    ClarificationCardPayload,
    ClarificationOptionPayload,
    ErrorPayload,
    EventType,
    RetrievalResultPayload,
    RetrievalStartedPayload,
    SseEnvelope,
    ToolCallPayload,
    ToolResultPayload,
)
from learning_agent_service.config import Settings, get_settings
from learning_agent_service.domain.contracts import ChatTurnCommand, GraphRuntimeMeta, PersistentSessionContext

from ..adapters.java_business import JavaBusinessClient
from .assistant import LocalLifeModelAssistant
from .catalog import LocalLifeCatalog, get_default_catalog
from .fusion import fuse_candidates, merge_business_facts_with_semantic_evidence
from .query_router import LocalLifeQueryRouter
from .query_rewriter import normalize_query
from .ranker import rank_candidates
from .response_builder import build_response_bundle
from .schemas import LocalLifeIntentType, LocalLifeSlots, LocalLifeTurnState, QueryUnderstandingResult, SuggestedReply, VoucherRecord
from .slot_extractor import extract_slots
from ..safety.guards import LocalLifeSafetyGuard


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return dict(dumped)
    return {}


def _clean_source(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower().replace("-", "_")
    return text or None


def _event(
    event_type: EventType,
    *,
    trace_id: str,
    session_id: str,
    turn_id: str,
    workflow_version: str,
    payload: dict[str, Any],
) -> SseEnvelope:
    return SseEnvelope(
        event_type=event_type.value,
        trace_id=trace_id,
        session_id=session_id,
        turn_id=turn_id,
        timestamp=datetime.now(timezone.utc),
        workflow_version=workflow_version,
        payload=payload,
    )


def _runtime(command: ChatTurnCommand, workflow_version: str) -> GraphRuntimeMeta:
    return GraphRuntimeMeta(
        trace_id=command.trace_id,
        session_id=command.session_id,
        turn_id=command.turn_id,
        workflow_version=workflow_version,
        request_ts=datetime.now(timezone.utc),
        user_id=command.user_id,
        response_mode=command.response_mode,
        topic_hint=command.topic_hint,
        history_summary=command.history_summary,
        client_context=command.client_context,
    )


def _clarification_payload(decision) -> dict[str, Any]:
    return ClarificationCardPayload(
        card_id=f"clarify-{uuid4().hex[:8]}",
        question=decision.question or "你能再补充一点偏好吗？",
        options=[
            ClarificationOptionPayload(
                id=f"opt-{index}",
                label=item.label,
                value=item.prompt,
                description=item.prompt,
            )
            for index, item in enumerate(decision.options, start=1)
        ],
        ambiguity_type=decision.ambiguity_type or "local_life",
    ).model_dump(mode="json")


def _route_decision_from_intent(intent: LocalLifeIntentType) -> str:
    mapping = {
        LocalLifeIntentType.RESTAURANT_RECOMMENDATION: "retrieve_then_answer",
        LocalLifeIntentType.RESTAURANT_COMPARISON: "retrieve_then_answer",
        LocalLifeIntentType.COUPON: "retrieve_then_answer",
        LocalLifeIntentType.DETAIL: "retrieve_then_answer",
        LocalLifeIntentType.BOOKING: "tool_then_answer",
        LocalLifeIntentType.ORDER_STATUS: "tool_then_answer",
        LocalLifeIntentType.NAVIGATION: "retrieve_then_answer",
        LocalLifeIntentType.CLARIFY: "clarify",
    }
    return mapping.get(intent, "retrieve_then_answer")


def _tool_name_for_intent(intent: LocalLifeIntentType) -> str:
    mapping = {
        LocalLifeIntentType.RESTAURANT_RECOMMENDATION: "search_restaurants",
        LocalLifeIntentType.RESTAURANT_COMPARISON: "search_restaurants",
        LocalLifeIntentType.DETAIL: "get_shop_detail",
        LocalLifeIntentType.NAVIGATION: "get_distance_eta",
    }
    return mapping.get(intent, "search_restaurants")


def _tool_input_summary(
    intent: LocalLifeIntentType,
    *,
    filters: Mapping[str, Any],
    slots: LocalLifeSlots,
) -> dict[str, Any]:
    if intent in {LocalLifeIntentType.RESTAURANT_RECOMMENDATION, LocalLifeIntentType.RESTAURANT_COMPARISON}:
        return dict(filters)
    if intent == LocalLifeIntentType.DETAIL:
        return {
            "shop_id": slots.shop_ids[0] if slots.shop_ids else None,
            "shop_name": slots.shop_query or slots.category or slots.city,
            "query": slots.shop_query or slots.category or slots.city,
        }
    if intent == LocalLifeIntentType.NAVIGATION:
        return {
            "shop_id": slots.shop_ids[0] if slots.shop_ids else None,
            "shop_name": slots.shop_query or slots.category or slots.city,
            "lat": slots.location.lat,
            "lng": slots.location.lng,
            "mode": "drive",
        }
    return dict(filters)


def _stage_entry(
    stage: str,
    status: str,
    *,
    route_decision: str | None = None,
    route_reason: str | None = None,
    detail: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "stage": stage,
        "status": status,
        "route_decision": route_decision,
        "route_reason": route_reason,
        "detail": dict(detail or {}),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _mark_stage(
    state: "LocalLifeTurnState",
    stage: str,
    status: str,
    *,
    route_decision: str | None = None,
    route_reason: str | None = None,
    detail: Mapping[str, Any] | None = None,
) -> None:
    if route_decision is not None:
        state.route_decision = route_decision
    if route_reason is not None:
        state.route_reason = route_reason
    state.current_stage = stage
    state.stage_status = status
    state.stage_timeline.append(
        _stage_entry(
            stage,
            status,
            route_decision=state.route_decision,
            route_reason=state.route_reason,
            detail=detail,
        )
    )


class LocalLifeSubgraph:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        catalog: LocalLifeCatalog | None = None,
        business_client: JavaBusinessClient | None = None,
        model_assistant: LocalLifeModelAssistant | None = None,
        local_life_retriever: Any | None = None,
        local_life_query_router: LocalLifeQueryRouter | None = None,
        session_context_store: Any | None = None,
        safety_guard: LocalLifeSafetyGuard | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.catalog = catalog or get_default_catalog()
        self.business_client = business_client or JavaBusinessClient(self.settings, self.catalog)
        self.model_assistant = model_assistant or LocalLifeModelAssistant()
        self.local_life_retriever = local_life_retriever
        self.local_life_query_router = local_life_query_router or LocalLifeQueryRouter()
        self.session_context_store = session_context_store
        self.safety_guard = safety_guard or LocalLifeSafetyGuard()

    def run_stream(
        self,
        command: ChatTurnCommand,
        persistent_context: Optional[PersistentSessionContext] = None,
    ) -> Iterable[SseEnvelope]:
        persistent = persistent_context or PersistentSessionContext()
        client_context = _as_mapping(command.client_context)
        session_context = persistent.model_dump(mode="json")
        understanding_hint = self._build_understanding_hint(
            raw_query=command.message,
            client_context=client_context,
            session_context=session_context,
        )

        understanding = normalize_query(
            command.message,
            client_context=client_context,
            session_context=session_context,
            model_hint=understanding_hint,
        )
        slots, clarification, intent = extract_slots(
            understanding,
            command.message,
            client_context=client_context,
            session_context=session_context,
            model_hint=understanding_hint,
        )
        state = LocalLifeTurnState(
            trace_id=command.trace_id,
            session_id=command.session_id,
            turn_id=command.turn_id,
            user_id=command.user_id,
            page=command.page,
            raw_query=command.message,
            client_context=client_context,
            persistent_context=session_context,
            understanding=understanding,
            slots=slots,
            clarification=clarification,
            intent=intent,
        )
        query_route = self.local_life_query_router.route(
            command.message,
            slots=slots,
            intent=intent,
            client_context=client_context,
            session_context=session_context,
        )
        state.metrics.update(
            {
                "local_life_route": query_route.route,
                "local_life_route_reason": query_route.route_reason,
                "local_life_retrieval_strategy": query_route.retrieval_strategy,
            }
        )
        _mark_stage(
            state,
            "understand",
            "completed",
            route_decision=_route_decision_from_intent(intent),
            route_reason=f"intent:{intent.value}",
            detail={
                "normalized_query": understanding.normalized_query,
                "semantic_query": understanding.semantic_query,
                "keyword_query": understanding.keyword_query,
                "confidence": understanding.confidence,
                "local_life_route": query_route.route,
                "local_life_retrieval_strategy": query_route.retrieval_strategy,
            },
        )

        if clarification.need_clarification:
            _mark_stage(
                state,
                "clarify",
                "completed",
                route_decision=_route_decision_from_intent(intent),
                route_reason=clarification.question or "need_clarification",
                detail={
                    "ambiguity_type": clarification.ambiguity_type,
                    "mode": "plain_text",
                },
            )

        filters = {
            "city": slots.city,
            "radius_km": slots.location.radius_km,
            "category": slots.category,
            "scene": slots.scene,
            "preferences": list(slots.preferences),
            "avoid": list(slots.avoid),
            "page": command.page,
        }
        _mark_stage(
            state,
            "retrieval",
            "running",
            detail=filters,
        )
        yield _event(
            EventType.RETRIEVAL_STARTED,
            trace_id=command.trace_id,
            session_id=command.session_id,
            turn_id=command.turn_id,
            workflow_version=self.settings.workflow_version,
            payload=RetrievalStartedPayload(
                semantic_query=understanding.semantic_query,
                keyword_query=understanding.keyword_query,
                retrieval_filters=filters,
                current_stage=state.current_stage,
                stage_status=state.stage_status,
                route_decision=state.route_decision,
                route_reason=state.route_reason,
            ).model_dump(mode="json"),
        )

        tool_name = _tool_name_for_intent(intent)
        tool_input_summary = _tool_input_summary(intent, filters=filters, slots=slots)
        search_call_id = f"call-{uuid4().hex[:8]}"
        _mark_stage(
            state,
            "tool",
            "running",
            detail={"tool_name": tool_name, "tool_call_id": search_call_id},
        )
        yield _event(
            EventType.TOOL_CALL,
            trace_id=command.trace_id,
            session_id=command.session_id,
            turn_id=command.turn_id,
            workflow_version=self.settings.workflow_version,
            payload=ToolCallPayload(
                tool_name=tool_name,
                tool_call_id=search_call_id,
                input_summary=tool_input_summary,
                current_stage=state.current_stage,
                stage_status=state.stage_status,
                route_decision=state.route_decision,
                route_reason=state.route_reason,
            ).model_dump(mode="json"),
        )

        structured_candidates: list[Any] = []
        if query_route.use_business_candidates:
            structured_candidates = self.business_client.search_candidates(
                query=understanding.semantic_query or understanding.keyword_query or command.message,
                slots=slots,
                limit=getattr(self.settings, "local_life_candidate_limit", 5),
            )
        state.structured_candidates = structured_candidates
        _mark_stage(
            state,
            "tool",
            "completed",
            detail={"tool_name": tool_name, "candidate_count": len(structured_candidates)},
        )

        vouchers_by_shop_id: dict[int, list[dict[str, Any]]] = {}
        blog_claims = []
        hot_blogs = self.business_client.get_blog_hot(current=1)
        for shop in structured_candidates[:3]:
            vouchers = self.business_client.get_coupon_list(shop.id)
            vouchers_by_shop_id[int(shop.id)] = list(vouchers)
            shop_blogs = [blog for blog in hot_blogs if blog.shop_id == shop.id]
            for blog in shop_blogs[:2]:
                blog_claims.append(
                    {
                        "chunk_id": f"blog-{blog.id}",
                        "shop_id": shop.id,
                        "claim": "探店笔记提到口碑不错",
                        "support_text": f"{blog.title}：{blog.content}",
                        "source_type": "探店笔记",
                        "confidence": 0.72,
                        "metadata": {"shop_name": shop.name},
                    }
                )

        retrieval_strategy = query_route.retrieval_strategy
        qdrant_pack = None
        qdrant_claims: list[Any] = []
        if self.local_life_retriever is not None and query_route.use_qdrant:
            try:
                candidate_shop_ids = [shop.id for shop in structured_candidates] or list(query_route.candidate_shop_ids)
                if not candidate_shop_ids and slots.shop_ids:
                    candidate_shop_ids = list(slots.shop_ids)
                qdrant_pack = self.local_life_retriever.retrieve_local_life_evidence(
                    understanding.semantic_query or understanding.keyword_query or command.message,
                    route=query_route.route,
                    city=slots.city or self._client_context_text(client_context, "city"),
                    area=self._client_context_text(client_context, "area", "district", "region"),
                    category=slots.category,
                    shop_type_id=self._client_context_int(client_context, "shop_type_id", "typeId", "shopTypeId"),
                    candidate_shop_ids=candidate_shop_ids or None,
                    child_top_k=query_route.child_top_k or getattr(self.settings, "local_life_child_top_k", 30),
                    parent_top_k=query_route.parent_top_k or getattr(self.settings, "local_life_parent_top_k", 5),
                    sibling_limit_per_parent=query_route.sibling_limit_per_parent
                    or getattr(self.settings, "local_life_sibling_limit_per_parent", 6),
                )
                retrieval_strategy = getattr(qdrant_pack, "retrieval_strategy", retrieval_strategy)
                qdrant_claims = merge_business_facts_with_semantic_evidence(
                    structured_candidates,
                    qdrant_pack,
                    vouchers_by_shop_id=vouchers_by_shop_id,
                    limit=8,
                )
            except Exception:
                _LOGGER.exception("local_life_parent_child_retriever_failed")

        catalog_evidence_claims = self.catalog.build_evidence(
            query=understanding.semantic_query or understanding.keyword_query or command.message,
            shop_ids=[shop.id for shop in structured_candidates],
            slots=slots,
            limit=8,
        )
        evidence_claims = self._merge_evidence_claims(qdrant_claims, catalog_evidence_claims)
        if blog_claims:
            from .schemas import EvidenceClaim

            evidence_claims = [
                *evidence_claims,
                *[EvidenceClaim.model_validate(item) for item in blog_claims],
            ]
        evidence_claims = self._dedupe_evidence_claims(evidence_claims)
        evidence_claims = sorted(evidence_claims, key=lambda item: (-item.confidence, item.chunk_id))[:8]
        state.evidence_claims = list(evidence_claims)
        source_summary = self._summarize_sources(
            structured_candidates=structured_candidates,
            vouchers_by_shop_id=vouchers_by_shop_id,
            hot_blogs=hot_blogs,
        )
        state.metrics.update(
            {
                "local_life_route": query_route.route,
                "local_life_route_reason": query_route.route_reason,
                "local_life_retrieval_strategy": retrieval_strategy,
            }
        )
        _mark_stage(
            state,
            "grounding",
            "completed",
            detail={"evidence_count": len(evidence_claims), "candidate_count": len(structured_candidates)},
        )
        yield _event(
            EventType.RETRIEVAL_RESULT,
            trace_id=command.trace_id,
            session_id=command.session_id,
            turn_id=command.turn_id,
            workflow_version=self.settings.workflow_version,
            payload=RetrievalResultPayload(
                retrieval_strategy=retrieval_strategy,
                retrieval_hit_count=int(getattr(qdrant_pack, "total_child_hits", 0) or 0)
                if qdrant_pack is not None
                else len(structured_candidates),
                evidence_used_count=len(evidence_claims),
                current_stage=state.current_stage,
                stage_status=state.stage_status,
                route_decision=state.route_decision,
                route_reason=state.route_reason,
            ).model_dump(mode="json"),
        )
        candidate_profiles = fuse_candidates(
            structured_candidates,
            evidence_claims,
            slots=slots,
            vouchers_by_shop_id={shop_id: self._coerce_vouchers(vouchers) for shop_id, vouchers in vouchers_by_shop_id.items()},
        )
        ranked_candidates = rank_candidates(candidate_profiles, slots)

        top_shop = ranked_candidates[0] if ranked_candidates else None
        selected_shop = next(
            (shop for shop in structured_candidates if top_shop is not None and shop.id == top_shop.shop_id),
            None,
        ) or (structured_candidates[0] if structured_candidates else None)
        if tool_name == "get_shop_detail":
            if selected_shop is not None:
                detail_shop = self.business_client.get_shop_detail(selected_shop.id)
                tool_output = {
                    "shop_id": detail_shop.id,
                    "shop": detail_shop.model_dump(mode="json"),
                    "open_status": self.business_client.check_open_status(detail_shop),
                    "distance_eta": self.business_client.get_distance_eta(
                        detail_shop,
                        lat=slots.location.lat,
                        lng=slots.location.lng,
                    ),
                    "source": _clean_source(getattr(detail_shop, "source", None)) or "catalog",
                }
            else:
                tool_output = {
                    "status": "not_found",
                    "shop_id": None,
                    "shop": None,
                    "source": "catalog",
                }
        elif tool_name == "get_distance_eta":
            if selected_shop is not None:
                distance_eta = self.business_client.get_distance_eta(
                    selected_shop,
                    lat=slots.location.lat,
                    lng=slots.location.lng,
                )
                tool_output = {
                    "shop_id": selected_shop.id,
                    "shop_name": selected_shop.name,
                    **distance_eta,
                    "source": _clean_source(getattr(selected_shop, "source", None)) or "catalog",
                }
            else:
                tool_output = {
                    "distance_km": None,
                    "eta_minutes": None,
                    "mode": "drive",
                    "source": "catalog",
                }
        else:
            tool_output = {
                "candidate_count": len(structured_candidates),
                "candidate_ids": [shop.id for shop in structured_candidates],
                "shops": [shop.model_dump(mode="json") for shop in structured_candidates[:5]],
            }
        yield _event(
            EventType.TOOL_RESULT,
            trace_id=command.trace_id,
            session_id=command.session_id,
            turn_id=command.turn_id,
            workflow_version=self.settings.workflow_version,
            payload=ToolResultPayload(
                tool_name=tool_name,
                tool_call_id=search_call_id,
                status="success",
                degraded=False,
                retryable=False,
                output=tool_output,
                current_stage=state.current_stage,
                stage_status="completed",
                route_decision=state.route_decision,
                route_reason=state.route_reason,
            ).model_dump(mode="json"),
        )
        safety_result = self.safety_guard.evaluate(
            raw_query=command.message,
            slots=slots,
            ranked_candidates=ranked_candidates,
            evidence_claims=evidence_claims,
            intent=intent,
            selected_shop_id=top_shop.shop_id if top_shop else None,
            selected_shop_name=top_shop.name if top_shop else None,
            client_context=client_context,
        )
        state.approval_required = safety_result.approval_required
        state.approval_request = dict(safety_result.approval_request)
        state.transaction_draft = safety_result.transaction_draft.model_dump(mode="json") if safety_result.transaction_draft else {}
        state.safety_result = safety_result.model_dump(mode="json")
        if safety_result.approval_required:
            _mark_stage(
                state,
                "approval",
                "blocked",
                route_decision=state.route_decision,
                route_reason=safety_result.reason,
                detail={"approval_request": state.approval_request, "risk_level": safety_result.risk_level},
            )
        else:
            _mark_stage(
                state,
                "approval",
                "completed",
                route_decision=state.route_decision,
                route_reason=safety_result.reason,
                detail={"risk_level": safety_result.risk_level},
            )
        if safety_result.approval_required and safety_result.approval_request:
            yield _event(
                EventType.APPROVAL_REQUIRED,
                trace_id=command.trace_id,
                session_id=command.session_id,
                turn_id=command.turn_id,
                workflow_version=self.settings.workflow_version,
                payload=ApprovalRequiredPayload(
                    step_id="local-life-transaction-approval",
                    reason=safety_result.reason,
                    approval_request=safety_result.approval_request,
                    risk_level=safety_result.risk_level,
                    current_stage=state.current_stage,
                    stage_status=state.stage_status,
                    route_decision=state.route_decision,
                    route_reason=state.route_reason,
                ).model_dump(mode="json"),
            )
        _mark_stage(
            state,
            "compose",
            "running",
            detail={"selected_shop_id": top_shop.shop_id if top_shop else None},
        )
        response_hint = self._build_response_hint(
            raw_query=command.message,
            slots=slots,
            ranked_candidates=ranked_candidates,
            evidence_claims=evidence_claims,
            clarification=clarification if clarification.need_clarification else None,
            source_mode=source_summary["source_mode"],
            degraded_reason=source_summary["degraded_reason"],
            knowledge_freshness=source_summary["knowledge_freshness"],
            route_decision=state.route_decision,
            route_reason=state.route_reason,
            safety_result=state.safety_result,
            approval_required=safety_result.approval_required,
        )
        bundle = build_response_bundle(
            raw_query=command.message,
            slots=slots,
            ranked_candidates=ranked_candidates,
            evidence_claims=evidence_claims,
            page=command.page,
            current_topic=top_shop.name if top_shop else slots.category or slots.scene,
            selected_shop_id=top_shop.shop_id if top_shop else None,
            source="local-life-agent",
            fallback=source_summary["source_mode"] != "java_business" or bool(source_summary["degraded_reason"]),
            mode=(safety_result.transaction_draft.action if safety_result.transaction_draft else _mode_from_intent(intent)),
            client_context=client_context,
            approval_required=safety_result.approval_required,
            approval_request=safety_result.approval_request,
            transaction_draft=state.transaction_draft,
            safety_result=state.safety_result,
            route_decision=state.route_decision,
            route_reason=state.route_reason,
            current_stage=state.current_stage,
            stage_status=state.stage_status,
            stage_timeline=list(state.stage_timeline),
            model_hint=response_hint,
            source_mode=source_summary["source_mode"],
            degraded_reason=source_summary["degraded_reason"],
            knowledge_freshness=source_summary["knowledge_freshness"],
        )
        bundle_metrics = {**dict(bundle.metrics), **dict(state.metrics)}
        bundle_context = {**dict(bundle.context), "metrics": dict(bundle_metrics)}
        bundle = bundle.model_copy(
            update={
                "metrics": bundle_metrics,
                "context": bundle_context,
            }
        )
        state.current_topic = bundle.current_topic
        state.selected_shop_id = bundle.selected_shop_id
        state.mode = bundle.mode
        state.source = bundle.source
        state.answer_text = bundle.answer_text
        state.cards = list(bundle.cards)
        state.suggested_replies = list(bundle.suggested_replies)
        state.metrics = dict(bundle.metrics)
        state.route_decision = bundle.route_decision or state.route_decision
        state.route_reason = bundle.route_reason or state.route_reason
        state.current_stage = bundle.current_stage or state.current_stage
        state.stage_status = bundle.stage_status or state.stage_status
        state.stage_timeline = list(bundle.stage_timeline or state.stage_timeline)
        _mark_stage(
            state,
            "final",
            "completed",
            route_decision=state.route_decision,
            route_reason=state.route_reason,
            detail={"selected_shop_id": state.selected_shop_id, "approval_required": state.approval_required},
        )
        bundle = bundle.model_copy(
            update={
                "route_decision": state.route_decision,
                "route_reason": state.route_reason,
                "current_stage": state.current_stage,
                "stage_status": state.stage_status,
                "stage_timeline": list(state.stage_timeline),
                "context": {
                    **dict(bundle.context),
                    "route_decision": state.route_decision,
                    "route_reason": state.route_reason,
                    "current_stage": state.current_stage,
                    "stage_status": state.stage_status,
                    "stage_timeline": list(state.stage_timeline),
                },
            }
        )
        self._persist_context(
            persistent,
            state,
            command,
            slots=slots,
            ranked_candidates=ranked_candidates,
            bundle=bundle,
        )
        yield _event(
            EventType.FINAL,
            trace_id=command.trace_id,
            session_id=command.session_id,
            turn_id=command.turn_id,
            workflow_version=self.settings.workflow_version,
            payload=bundle.model_dump(mode="json"),
        )

    def _build_understanding_hint(
        self,
        *,
        raw_query: str,
        client_context: Mapping[str, Any],
        session_context: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        assistant = getattr(self, "model_assistant", None)
        if assistant is None:
            return {}
        try:
            return assistant.suggest_understanding(
                raw_query=raw_query,
                client_context=client_context,
                session_context=session_context,
            )
        except Exception:
            return {}

    @staticmethod
    def _client_context_text(client_context: Mapping[str, Any], *keys: str) -> Optional[str]:
        for key in keys:
            value = client_context.get(key)
            if value in (None, ""):
                continue
            text = str(value).strip()
            if text:
                return text
        return None

    @staticmethod
    def _client_context_int(client_context: Mapping[str, Any], *keys: str) -> Optional[int]:
        for key in keys:
            value = client_context.get(key)
            if value in (None, ""):
                continue
            try:
                return int(value)
            except Exception:
                continue
        return None

    @staticmethod
    def _dedupe_evidence_claims(evidence_claims: Sequence[Any]) -> list[Any]:
        deduped: dict[str, Any] = {}
        for item in evidence_claims:
            chunk_id = getattr(item, "chunk_id", None)
            if chunk_id is None and isinstance(item, Mapping):
                chunk_id = item.get("chunk_id")
            deduped[str(chunk_id or id(item))] = item
        return list(deduped.values())

    @staticmethod
    def _merge_evidence_claims(*claim_groups: Sequence[Any]) -> list[Any]:
        merged: list[Any] = []
        for group in claim_groups:
            merged.extend(list(group))
        return merged

    @staticmethod
    def _local_life_evidence_claims_from_pack(pack: Any) -> list[Any]:
        if pack is None:
            return []
        from .schemas import EvidenceClaim

        claims: list[EvidenceClaim] = []
        seen_chunk_ids: set[str] = set()
        for parent in getattr(pack, "parent_evidences", []) or []:
            matched_chunks = list(getattr(parent, "matched_chunks", []) or [])
            sibling_chunks = list(getattr(parent, "sibling_chunks", []) or [])
            for chunk in [*matched_chunks, *sibling_chunks]:
                chunk_id = getattr(chunk, "chunk_id", None)
                if not chunk_id or chunk_id in seen_chunk_ids:
                    continue
                seen_chunk_ids.add(chunk_id)
                payload = getattr(chunk, "payload", {}) or {}
                title = getattr(chunk, "title", None) or str(payload.get("title") or chunk_id)
                support_text = getattr(chunk, "text", None) or str(payload.get("text") or "")
                claims.append(
                    EvidenceClaim(
                        chunk_id=str(chunk_id),
                        shop_id=getattr(parent, "shop_id", None),
                        claim=f"{getattr(chunk, 'chunk_role', None) or '本地生活证据'}：{title}",
                        support_text=support_text,
                        source_type=str(getattr(chunk, "chunk_role", None) or getattr(chunk, "source_type", None) or "local_life"),
                        confidence=float(getattr(chunk, "score", None) or getattr(parent, "parent_score", 0.0) or 0.0),
                        metadata={
                            **dict(payload),
                            "parent_id": getattr(parent, "parent_id", None),
                            "parent_title": getattr(parent, "parent_title", None),
                            "parent_score": getattr(parent, "parent_score", None),
                            "retrieval_strategy": getattr(pack, "retrieval_strategy", None),
                        },
                    )
                )
        return claims

    def _build_response_hint(
        self,
        *,
        raw_query: str,
        slots: LocalLifeSlots,
        ranked_candidates: Sequence[Any],
        evidence_claims: Sequence[Any],
        clarification: Mapping[str, Any] | None,
        source_mode: str | None,
        degraded_reason: str | None,
        knowledge_freshness: Mapping[str, Any],
        route_decision: str | None,
        route_reason: str | None,
        safety_result: Mapping[str, Any],
        approval_required: bool,
    ) -> Mapping[str, Any]:
        assistant = getattr(self, "model_assistant", None)
        if assistant is None:
            return {}
        try:
            return assistant.suggest_response(
                raw_query=raw_query,
                slots=slots.model_dump(mode="json"),
                ranked_candidates=[
                    item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
                    for item in ranked_candidates
                ],
                evidence_claims=[
                    item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
                    for item in evidence_claims
                ],
                clarification=clarification,
                source_mode=source_mode,
                degraded_reason=degraded_reason,
                knowledge_freshness=knowledge_freshness,
                route_decision=route_decision,
                route_reason=route_reason,
                safety_result=safety_result,
                approval_required=approval_required,
            )
        except Exception:
            return {}

    def _summarize_sources(
        self,
        *,
        structured_candidates: Sequence[Any],
        vouchers_by_shop_id: Mapping[int, Sequence[Any]],
        hot_blogs: Sequence[Any],
    ) -> dict[str, Any]:
        candidate_sources = sorted(
            {
                _clean_source(getattr(shop, "source", None))
                for shop in structured_candidates
                if _clean_source(getattr(shop, "source", None))
            }
        )
        voucher_sources = sorted(
            {
                _clean_source(getattr(voucher, "source", None))
                for vouchers in vouchers_by_shop_id.values()
                for voucher in vouchers
                if _clean_source(getattr(voucher, "source", None))
            }
        )
        blog_sources = sorted(
            {
                _clean_source(getattr(blog, "source", None))
                for blog in hot_blogs
                if _clean_source(getattr(blog, "source", None))
            }
        )
        all_sources = sorted({*candidate_sources, *voucher_sources, *blog_sources})
        if not all_sources:
            if self.business_client.enabled:
                source_mode = "java_business"
                degraded_reason = None
            else:
                source_mode = "catalog"
                degraded_reason = "java_business_not_configured"
        elif all(source == "catalog" for source in all_sources):
            source_mode = "catalog"
            degraded_reason = "java_business_fallback_to_catalog" if self.business_client.enabled else "java_business_not_configured"
        elif all(source == "java" for source in all_sources):
            source_mode = "java_business"
            degraded_reason = None
        elif "java" in all_sources and "catalog" in all_sources:
            source_mode = "mixed_java_catalog"
            degraded_reason = "partial_java_business_fallback"
        else:
            source_mode = "catalog"
            degraded_reason = "java_business_fallback_to_catalog"

        knowledge_freshness = {
            "source_mode": source_mode,
            "business_client_enabled": self.business_client.enabled,
            "candidate_sources": candidate_sources,
            "voucher_sources": voucher_sources,
            "blog_sources": blog_sources,
            "candidate_count": len(structured_candidates),
            "voucher_count": sum(len(vouchers) for vouchers in vouchers_by_shop_id.values()),
            "blog_count": len(hot_blogs),
        }
        return {
            "source_mode": source_mode,
            "degraded_reason": degraded_reason,
            "knowledge_freshness": knowledge_freshness,
        }

    def _coerce_vouchers(self, vouchers: list[dict[str, Any]]) -> list[Any]:
        coerced: list[Any] = []
        for voucher in vouchers:
            if hasattr(voucher, "model_dump"):
                coerced.append(voucher)
            else:
                coerced.append(VoucherRecord.model_validate(voucher))
        return coerced

    def _persist_context(
        self,
        persistent: PersistentSessionContext,
        state: LocalLifeTurnState,
        command: ChatTurnCommand,
        *,
        slots: LocalLifeSlots | None = None,
        ranked_candidates: list[Any] | None = None,
        bundle: Any | None = None,
    ) -> None:
        slots = slots or state.slots
        ranked_candidates = ranked_candidates or []
        bundle_data = _as_mapping(bundle)
        current_action = bundle_data.get("mode") or (
            slots.action.value if hasattr(slots.action, "value") else slots.action
        )
        next_steps = list(bundle_data.get("next_steps") or persistent.next_steps or ())
        task_chain = list(bundle_data.get("task_chain") or ())
        updated = persistent.model_copy(
            update={
                "current_topic": bundle_data.get("current_topic") or state.current_topic or slots.category or slots.scene,
                "page": command.page or state.page,
                "current_city": slots.city or state.client_context.get("city") or persistent.current_city,
                "current_location": {
                    "lat": slots.location.lat,
                    "lng": slots.location.lng,
                    "radius_km": slots.location.radius_km,
                },
                "current_constraints": slots.model_dump(mode="json"),
                "last_candidates": [candidate.model_dump(mode="json") if hasattr(candidate, "model_dump") else dict(candidate) for candidate in ranked_candidates],
                "selected_shop_id": bundle_data.get("selected_shop_id") or (ranked_candidates[0].shop_id if ranked_candidates else persistent.selected_shop_id),
                "selected_shop_name": bundle_data.get("current_topic") or (ranked_candidates[0].name if ranked_candidates else persistent.selected_shop_name),
                "local_life_preferences": list(slots.preferences),
                "local_life_avoid": list(slots.avoid),
                "current_scene": slots.scene,
                "current_action": current_action,
                "page": command.page or state.page,
                "route_decision": state.route_decision or persistent.route_decision,
                "route_reason": state.route_reason or persistent.route_reason,
                "current_stage": state.current_stage or persistent.current_stage,
                "stage_status": state.stage_status or persistent.stage_status,
                "stage_timeline": list(state.stage_timeline or persistent.stage_timeline),
                "next_steps": list(next_steps),
                "extra": {
                    **dict(persistent.extra),
                    "approval_required": state.approval_required,
                    "approval_request": state.approval_request,
                    "transaction_draft": state.transaction_draft,
                    "safety_result": state.safety_result,
                    "route_decision": state.route_decision,
                    "route_reason": state.route_reason,
                    "current_stage": state.current_stage,
                    "stage_status": state.stage_status,
                    "stage_timeline": list(state.stage_timeline),
                    "next_steps": list(next_steps),
                    "task_chain": task_chain,
                    "source_mode": bundle_data.get("source_mode")
                    or (state.metrics.get("source_mode") if isinstance(state.metrics, dict) else None),
                    "degraded_reason": bundle_data.get("degraded_reason")
                    or (state.metrics.get("degraded_reason") if isinstance(state.metrics, dict) else None),
                    "knowledge_freshness": dict(
                        bundle_data.get("knowledge_freshness")
                        or (state.metrics.get("knowledge_freshness") if isinstance(state.metrics, dict) else {})
                        or {}
                    ),
                    "metrics": dict(state.metrics),
                },
            }
        )
        runtime = _runtime(command, self.settings.workflow_version)
        try:
            state.persistent_context = updated.model_dump(mode="json")
        except Exception:
            pass
        if self.session_context_store is not None:
            try:
                self.session_context_store.save(updated, runtime)
            except Exception:
                pass


def _mode_from_intent(intent: LocalLifeIntentType) -> str:
    mapping = {
        LocalLifeIntentType.RESTAURANT_RECOMMENDATION: "recommend",
        LocalLifeIntentType.RESTAURANT_COMPARISON: "compare",
        LocalLifeIntentType.COUPON: "coupon",
        LocalLifeIntentType.DETAIL: "detail",
        LocalLifeIntentType.BOOKING: "booking",
        LocalLifeIntentType.ORDER_STATUS: "order_status",
        LocalLifeIntentType.NAVIGATION: "navigation",
        LocalLifeIntentType.CLARIFY: "clarify",
    }
    return mapping.get(intent, "recommend")
