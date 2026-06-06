from __future__ import annotations

import re
from typing import Any, Mapping

from ....domain.contracts import PersistentSessionContext
from ...routing_primitives import (
    _compact,
    normalize_query,
)
from ...routing_signals.base import (
    DomainSignalRegistry,
    _extract_shop_name,
)
from ....local_life.target_shop_policy import _resolve_alias_from_contexts
from .types import (
    IntentCandidate,
    MerchantMatch,
    PronounMatch,
    SignalPolicyResult,
)

_PRONOUNS_THIS = ("这家", "这店", "这间", "它", "他", "她", "这商家", "这个商家", "这几家")
_PRONOUNS_THAT = ("那家", "那个", "刚才那家", "刚才那个", "上面那家", "刚推荐的")
_PRONOUNS_PREV = ("前一个", "上一个")
_PRONOUNS_NEXT = ("后一个", "下一个")

def check_signal_policy(
    raw_query: str,
    persistent: PersistentSessionContext,
    client_context: Mapping[str, Any] | None = None,
) -> SignalPolicyResult:
    normalized = normalize_query(raw_query)
    compact = _compact(raw_query)
    client_ctx_map = dict(client_context or {})
    session_ctx_map = persistent.model_dump()

    # 1. Match signals using DomainSignalRegistry
    registry = DomainSignalRegistry()
    candidates = registry.match(raw_query, persistent=persistent, client_context=client_context)

    intent_candidates: list[IntentCandidate] = []
    matched_signals: list[str] = []
    for cand in candidates:
        matched_signals.append(cand.spec_name)
        intent_candidates.append(
            IntentCandidate(
                intent_name=cand.intent,
                confidence=cand.confidence,
                route=cand.required_action,
                matched_signal=cand.spec_name,
                slots=dict(cand.slots),
                preferred_chunk_roles=list(cand.preferred_chunk_roles),
                tool_candidates=list(cand.tool_candidates),
                missing_slots=list(cand.missing_slots),
            )
        )

    # 2. Match merchant
    merchant_hit: MerchantMatch | None = None
    shop_name_extracted = _extract_shop_name(normalized, compact)
    if shop_name_extracted:
        shop_id, full_name, source_label = _resolve_alias_from_contexts(
            shop_name_extracted,
            client_ctx_map,
            session_ctx_map,
        )
        if full_name:
            merchant_hit = MerchantMatch(
                merchant_name=full_name,
                merchant_id=str(shop_id) if shop_id is not None else None,
                match_type="alias",
                confidence=0.9,
            )
        else:
            merchant_hit = MerchantMatch(
                merchant_name=shop_name_extracted,
                merchant_id=None,
                match_type="fuzzy",
                confidence=0.75,
            )

    # 3. Match pronoun
    pronoun_hit: PronounMatch | None = None
    query_lower = normalized.lower()

    # Check for ordinal pronoun first: "第二个", "第二家", etc.
    ordinal_match = re.search(r"第([一二三四五六七八九十1-9])(?:个|家|间|店|名|商户|商家)", query_lower)
    if ordinal_match:
        val = ordinal_match.group(1)
        mapping = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
        try:
            ordinal_idx = int(val)
        except ValueError:
            ordinal_idx = mapping.get(val)
        
        pronoun_hit = PronounMatch(
            pronoun=ordinal_match.group(0),
            reference_type="ordinal",
            ordinal=ordinal_idx,
            confidence=0.85,
        )
    else:
        # Check other pronouns
        found_pronoun = None
        ref_type = None
        for p in _PRONOUNS_THIS:
            if p in query_lower:
                found_pronoun = p
                ref_type = "this"
                break
        if not found_pronoun:
            for p in _PRONOUNS_THAT:
                if p in query_lower:
                    found_pronoun = p
                    ref_type = "that"
                    break
        if not found_pronoun:
            for p in _PRONOUNS_PREV:
                if p in query_lower:
                    found_pronoun = p
                    ref_type = "previous"
                    break
        if not found_pronoun:
            for p in _PRONOUNS_NEXT:
                if p in query_lower:
                    found_pronoun = p
                    ref_type = "next"
                    break

        if found_pronoun and ref_type:
            pronoun_hit = PronounMatch(
                pronoun=found_pronoun,
                reference_type=ref_type,
                confidence=0.8,
            )

    top_confidence = intent_candidates[0].confidence if intent_candidates else 0.0

    return SignalPolicyResult(
        candidates=intent_candidates,
        top_confidence=top_confidence,
        matched_signals=matched_signals,
        merchant_hit=merchant_hit,
        pronoun_hit=pronoun_hit,
    )
