from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Mapping

from ....domain.contracts import PersistentSessionContext
from ....local_life.entity_resolver import _explicit_entity_from_query
from ....local_life.target_shop_policy import TargetShopPolicy
from .query_merge import LocalLifeQueryMergeResult
from .types import LLMParserResult, ResolvedTarget, SignalPolicyResult


def resolve_target_merchant(
    raw_query: str,
    parser_result: LLMParserResult,
    signal_result: SignalPolicyResult,
    persistent: PersistentSessionContext,
    client_context: Mapping[str, Any] | None = None,
    merged_query: LocalLifeQueryMergeResult | None = None,
) -> ResolvedTarget:
    client_context_map = dict(client_context or {})
    session_context_map = persistent.model_dump()

    explicit_entity = _explicit_entity_from_query(raw_query)

    merged_slots = dict(merged_query.merged_slots if merged_query is not None else {})
    shop_ids = merged_slots.get("shop_ids") or parser_result.slots.get("shop_ids") or []
    shop_query = (
        merged_slots.get("shop_name")
        or merged_slots.get("shop_query")
        or parser_result.slots.get("shop_name")
        or parser_result.slots.get("shop_query")
    )
    if not shop_query and signal_result.merchant_hit:
        shop_query = signal_result.merchant_hit.merchant_name

    slots_obj = SimpleNamespace(
        shop_ids=shop_ids,
        shop_query=shop_query,
    )

    policy = TargetShopPolicy()
    target_shop = policy.resolve_target(
        raw_query=raw_query,
        slots=slots_obj,
        client_context=client_context_map,
        session_context=session_context_map,
        explicit_entity=explicit_entity,
    )

    source_map = {
        "explicit_query": "explicit",
        "candidate_reference": "candidate_selection",
        "pronoun_session_current": "pronoun_inherit",
        "client_selected_shop": "pronoun_inherit",
        "session_current": "context_inherit",
        "ambiguous": "none",
        "missing": "none",
        "rag_fallback": "none",
    }

    source = source_map.get(target_shop.resolution_source or "", "none")
    if source == "none" and target_shop.source in ("current_query", "session"):
        if target_shop.is_explicit_in_current_turn:
            source = "explicit"
        elif target_shop.is_pronoun_inherited:
            source = "pronoun_inherit"
        elif target_shop.is_candidate_reference:
            source = "candidate_selection"
        elif target_shop.shop_id or target_shop.shop_name:
            source = "context_inherit"

    missing = bool(target_shop.should_clarify or (target_shop.resolution_source in ("missing", "ambiguous") and not target_shop.shop_id and not target_shop.shop_name))
    if parser_result.target_shop and parser_result.target_shop.clarify_if_missing:
        if not target_shop.shop_id and not target_shop.shop_name:
            missing = True

    resolved_references: list[str] = []
    if target_shop.shop_name:
        resolved_references.append(target_shop.shop_name)
    elif target_shop.raw_mention:
        resolved_references.append(target_shop.raw_mention)
    if merged_query is not None and merged_query.target_reference:
        if merged_query.target_reference not in resolved_references:
            resolved_references.append(merged_query.target_reference)

    shop_id_str = str(target_shop.shop_id) if target_shop.shop_id is not None else None

    clarification_question = None
    if missing:
        if "coupon" in parser_result.facet_needs or parser_result.intent == "package_or_coupon":
            clarification_question = "你想查询哪家店的优惠券？请告诉我具体门店名称。"
        else:
            clarification_question = "你问的是哪家店？请告诉我具体店名或选择刚才提到的商家。"

    return ResolvedTarget(
        shop_id=shop_id_str,
        shop_name=target_shop.shop_name,
        confidence=target_shop.confidence,
        source=source,
        resolved_references=resolved_references,
        missing=missing,
        clarification_question=clarification_question,
    )
