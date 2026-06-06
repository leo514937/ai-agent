from .helpers import *  # noqa: F403

from .stream import LocalLifeSubgraphRunMixin


class LocalLifeSubgraph(LocalLifeSubgraphRunMixin):
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
    def _client_context_text(client_context: Mapping[str, Any], *keys: str) -> str | None:
        for key in keys:
            value = client_context.get(key)
            if value in (None, ""):
                continue
            text = str(value).strip()
            if text:
                return text
        return None

    @staticmethod
    def _client_context_int(client_context: Mapping[str, Any], *keys: str) -> int | None:
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
        from ..schemas import EvidenceClaim

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
        evidence_pack: Any | None = None,
        clarification: Mapping[str, Any] | None,
        source_mode: str | None,
        degraded_reason: str | None,
        knowledge_freshness: Mapping[str, Any],
        route_decision: str | None,
        route_reason: str | None,
        safety_result: Mapping[str, Any],
        approval_required: bool,
        answer_contract: Any | None = None,
    ) -> Mapping[str, Any]:
        assistant = getattr(self, "model_assistant", None)
        if assistant is None:
            return {}
        try:
            payload = {
                "raw_query": raw_query,
                "slots": slots.model_dump(mode="json"),
                "ranked_candidates": [
                    item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
                    for item in ranked_candidates
                ],
                "evidence_claims": [
                    item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
                    for item in evidence_claims
                ],
                "evidence_pack": evidence_pack.model_dump(mode="json") if hasattr(evidence_pack, "model_dump") else (dict(evidence_pack) if isinstance(evidence_pack, Mapping) else {}),
                "clarification": clarification,
                "source_mode": source_mode,
                "degraded_reason": degraded_reason,
                "knowledge_freshness": knowledge_freshness,
                "route_decision": route_decision,
                "route_reason": route_reason,
                "safety_result": safety_result,
                "approval_required": approval_required,
                "answer_contract": answer_contract.model_dump(mode="json") if hasattr(answer_contract, "model_dump") else answer_contract,
            }
            if hasattr(assistant, "compose_answer_plan"):
                return assistant.compose_answer_plan(**payload)
            return assistant.suggest_response(**payload)
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
        execution_contract = (state.metrics or {}).get("local_life_execution_contract") or {}
        intent = execution_contract.get("intent") or "local_life_recommend"

        context_data = bundle_data.get("context") or {}
        current_shop = bundle_data.get("current_shop") or context_data.get("current_shop") or context_data.get("selected_shop_name") or persistent.current_shop or persistent.selected_shop_name
        current_shop_id = bundle_data.get("selected_shop_id") or context_data.get("selected_shop_id") or context_data.get("shop_id") or persistent.selected_shop_id

        # Update from target_shop resolved metrics (P0-Fix)
        t_shop = (state.metrics or {}).get("target_shop")
        if isinstance(t_shop, dict):
            t_shop_name = t_shop.get("shop_name")
            t_shop_id = t_shop.get("shop_id")
            if t_shop_name and str(t_shop_name).strip() != str(command.message).strip():
                current_shop = t_shop_name
            if t_shop_id:
                current_shop_id = t_shop_id

        route_gate = (state.metrics or {}).get("route_gate") or {}
        recommendation_mode = str(bundle_data.get("mode") or "").strip().lower() == "recommend" or str(route_gate.get("branch") or "").strip().lower() == "recommendation"
        target_shop_info = (state.metrics or {}).get("target_shop") or {}
        explicit_target_shop = bool(execution_contract.get("resolved_shop_id")) or bool(target_shop_info.get("shop_id")) or str(target_shop_info.get("source") or "").strip() in {"current_query", "pronoun_session", "session"}
        candidate_current_shop = current_shop
        candidate_current_shop_id = current_shop_id
        illegal_state_mutation: list[dict[str, Any]] = []

        if recommendation_mode and not explicit_target_shop:
            if candidate_current_shop not in (None, "", persistent.current_shop, persistent.selected_shop_name) or candidate_current_shop_id not in (None, "", persistent.selected_shop_id):
                illegal_state_mutation.append(
                    {
                        "node": "persist_session",
                        "field": "current_shop",
                        "before": persistent.current_shop,
                        "attempted": candidate_current_shop,
                        "after": persistent.current_shop,
                        "reason": "recommendation_scope_must_not_promote_shop",
                    }
                )
            current_shop = persistent.current_shop
            current_shop_id = persistent.selected_shop_id

        if intent in ("local_life_recommend", "local_life_search"):
            if not ranked_candidates and not explicit_target_shop and not context_data.get("current_shop") and not context_data.get("selected_shop_name") and not (isinstance(t_shop, dict) and t_shop.get("shop_name")):
                current_shop = None
                current_shop_id = None

        next_steps = list(bundle_data.get("next_steps") or persistent.next_steps or ())
        task_chain = list(bundle_data.get("task_chain") or ())
        current_source_mode = bundle_data.get("source_mode") or (
            state.metrics.get("source_mode") if isinstance(state.metrics, dict) else None
        )
        # Populate pending_clarification and clarification_result if clarification is needed (P0-Fix-4)
        pending_clarification = None
        clarification_result = dict(persistent.clarification_result or {})
        pending_user_need = dict(persistent.pending_user_need or {})
        if state.clarification and state.clarification.need_clarification:
            from learning_agent_service.domain.contracts import (
                ClarificationCard,
                ClarificationOption,
            )
            options_payload = []
            for idx, opt in enumerate(state.clarification.options, start=1):
                options_payload.append(
                    ClarificationOption(
                        id=f"opt-{idx}",
                        label=opt.label,
                        value=opt.prompt,
                        description=opt.prompt,
                    )
                )
            pending_clarification = ClarificationCard(
                card_id=f"clarify-{uuid4().hex[:8]}",
                question=state.clarification.question or "你想查看哪个城市或商圈的餐厅？方便提供位置吗？",
                options=options_payload,
                ambiguity_type=state.clarification.ambiguity_type or "location",
                source_turn_id=command.turn_id,
            )
            clarification_result = {
                "original_query": command.message,
                "original_intent": str(state.intent.value if hasattr(state.intent, "value") else state.intent),
                "original_route": state.route_decision or "clarify",
                "question": state.clarification.question,
                "ambiguity_type": state.clarification.ambiguity_type or "location",
            }
            pending_user_need = state.user_need.model_dump(mode="json")

        # If we are completing a pending clarification, preserve the original query as the topic (P0-Fix)
        original_query = (persistent.clarification_result or {}).get("original_query")
        if original_query and persistent.pending_clarification:
            current_topic_val = original_query
        elif state.clarification and state.clarification.need_clarification:
            current_topic_val = command.message
        else:
            current_topic_val = (
                bundle_data.get("current_topic")
                or state.current_topic
                or slots.category
                or slots.scene
            )
        updated = persistent.model_copy(
            update={
                "current_topic": current_topic_val,
                "current_shop": current_shop,
                "current_shop_anchor": {
                    "shop_id": current_shop_id,
                    "shop_name": current_shop,
                    "source": current_source_mode,
                    "confidence": bundle_data.get("confidence") if isinstance(bundle_data, Mapping) else None,
                    "turn_id": command.turn_id,
                },
                "pending_clarification": pending_clarification,
                "clarification_result": clarification_result,
                "pending_user_need": pending_user_need,
                "page": command.page or state.page,
                "current_city": slots.city or state.client_context.get("city") or persistent.current_city,
                "current_location": {
                    "lat": slots.location.lat,
                    "lng": slots.location.lng,
                    "radius_km": slots.location.radius_km,
                },
                "current_constraints": slots.model_dump(mode="json"),
                "last_candidates": [
                    {
                        "id": (c.model_dump(mode="json") if hasattr(c, "model_dump") else dict(c)).get("id") or (c.model_dump(mode="json") if hasattr(c, "model_dump") else dict(c)).get("shop_id"),
                        "shop_id": (c.model_dump(mode="json") if hasattr(c, "model_dump") else dict(c)).get("shop_id") or (c.model_dump(mode="json") if hasattr(c, "model_dump") else dict(c)).get("id"),
                        "name": (c.model_dump(mode="json") if hasattr(c, "model_dump") else dict(c)).get("name"),
                        "city": (c.model_dump(mode="json") if hasattr(c, "model_dump") else dict(c)).get("city"),
                        "category": (c.model_dump(mode="json") if hasattr(c, "model_dump") else dict(c)).get("category"),
                    }
                    for c in (ranked_candidates or [])[:5]
                ],
                "selected_shop_id": current_shop_id,
                "selected_shop_name": current_shop,
                "local_life_preferences": list(slots.preferences),
                "local_life_avoid": list(slots.avoid),
                "current_scene": slots.scene,
                "current_action": current_action,
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
                    "recommendation_mode": recommendation_mode,
                    "metrics": dict(state.metrics),
                },
            }
        )
        state_diff = {
            "current_topic": {"before": persistent.current_topic, "after": updated.current_topic},
            "current_shop": {"before": persistent.current_shop, "after": updated.current_shop},
            "selected_shop_id": {"before": persistent.selected_shop_id, "after": updated.selected_shop_id},
            "selected_shop_name": {"before": persistent.selected_shop_name, "after": updated.selected_shop_name},
            "last_candidates_count": {"before": len(persistent.last_candidates or []), "after": len(updated.last_candidates or [])},
            "pending_clarification": {"before": bool(persistent.pending_clarification), "after": bool(updated.pending_clarification)},
        }
        if recommendation_mode and not explicit_target_shop:
            state_diff["recommendation_scope"] = {
                "branch": route_gate.get("branch"),
                "candidate_shop_id": candidate_current_shop_id,
                "candidate_shop_name": candidate_current_shop,
            }
        try:
            state.metrics.update(
                {
                    "session_current_shop_after": current_shop,
                    "session_current_shop_id_after": current_shop_id,
                    "last_candidates_after": list(updated.last_candidates or []),
                    "session_current_shop_anchor_after": dict(updated.current_shop_anchor or {}),
                    "state_diff": state_diff,
                    "illegal_state_mutation": illegal_state_mutation,
                    "recommendation_mode": recommendation_mode,
                    "recommendation_scope": {
                        "branch": route_gate.get("branch"),
                        "explicit_target_shop": explicit_target_shop,
                        "candidate_shop_id": candidate_current_shop_id,
                        "candidate_shop_name": candidate_current_shop,
                    },
                }
            )
        except Exception:
            pass
        state.state_diff = state_diff
        state.illegal_state_mutation = list(illegal_state_mutation)
        state.node_writes.append(
            {
                "node": "persist_session",
                "writes": [
                    "persistent_context",
                    "state_diff",
                    "illegal_state_mutation",
                    "recommendation_scope",
                ],
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
