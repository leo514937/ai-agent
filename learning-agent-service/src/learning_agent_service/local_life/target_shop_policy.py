from __future__ import annotations

import re
from typing import Any, Literal
from pydantic import BaseModel, Field

from learning_agent_service.local_life.schemas import CandidateShop, SemanticSelectionResult, ShopResolveResult

def _resolve_alias_from_contexts(
    shop_name_extracted: str,
    client_ctx_map: dict[str, Any],
    session_ctx_map: dict[str, Any],
) -> tuple[int | None, str | None, str | None]:
    if not shop_name_extracted:
        return None, None, None

    def extract_shop(ctx: dict[str, Any]) -> tuple[int | None, str | None]:
        shop_id = ctx.get("selected_shop_id") or ctx.get("current_shop_id") or ctx.get("shopId") or ctx.get("shop_id")
        shop_name = ctx.get("selected_shop_name") or ctx.get("current_shop") or ctx.get("shopName") or ctx.get("shop_name")
        try:
            return int(shop_id) if shop_id else None, str(shop_name) if shop_name else None
        except (ValueError, TypeError):
            return None, str(shop_name) if shop_name else None

    # Handle positional pronouns
    last_candidates = session_ctx_map.get("last_candidates") or []
    if isinstance(last_candidates, list) and last_candidates:
        pos_map = {"第一家": 0, "第二家": 1, "第三家": 2, "刚才那家": 0, "上面那家": 0, "刚推荐的": 0}
        if shop_name_extracted in pos_map:
            idx = pos_map[shop_name_extracted]
            if idx < len(last_candidates):
                cand = last_candidates[idx]
                if isinstance(cand, dict):
                    c_id = cand.get("shop_id") or cand.get("id")
                    c_name = str(cand.get("shop_name") or cand.get("name") or "")
                    try:
                        c_id_int = int(c_id) if c_id else None
                        if c_id_int:
                            return c_id_int, c_name, "candidate_reference"
                    except (ValueError, TypeError):
                        pass

    # If pronoun, map to context
    if any(p == shop_name_extracted for p in _PRONOUNS):
        for ctx, source in [(client_ctx_map, "client_selected_shop"), (session_ctx_map, "session_current")]:
            sid, sname = extract_shop(ctx)
            if sid and sname:
                return sid, sname, source

    # If partial name / alias, check if it matches the current shop
    for ctx, source in [(client_ctx_map, "client_selected_shop"), (session_ctx_map, "session_current")]:
        sid, sname = extract_shop(ctx)
        if sid and sname and shop_name_extracted in sname:
            return sid, sname, source

    # Check last_candidates in session
    if isinstance(last_candidates, list):
        for cand in last_candidates:
            if not isinstance(cand, dict):
                continue
            c_id = cand.get("shop_id") or cand.get("id")
            c_name = str(cand.get("shop_name") or cand.get("name") or "")
            if c_name and shop_name_extracted in c_name:
                try:
                    c_id_int = int(c_id) if c_id else None
                    if c_id_int:
                        return c_id_int, c_name, "candidate_reference"
                except (ValueError, TypeError):
                    pass

    return None, None, None

_PRONOUNS = ("这家", "这店", "这间", "它", "他", "她", "刚才那家", "刚才那个", "这商家", "这个商家", "这几家", "第一家", "第二家", "第三家", "上面那家", "刚推荐的", "那家", "那个")

class TargetShop(BaseModel):
    shop_id: int | None = None
    shop_name: str | None = None
    status: ShopResolveResult | None = None
    raw_mention: str | None = None
    source: Literal[
        "current_query",
        "pronoun_session",
        "candidate_selection",
        "session",
        "rag_fallback",
    ]
    resolution_source: Literal[
        "explicit_query",
        "explicit_not_found",
        "client_selected_shop",
        "pronoun_session_current",
        "candidate_reference",
        "session_current",
        "ambiguous",
        "missing",
        "rag_fallback",
    ] | None = None
    confidence: float = 0.0
    is_explicit_in_current_turn: bool = False
    is_pronoun_inherited: bool = False
    is_candidate_reference: bool = False
    should_clarify: bool = False
    reason: str | None = None
    candidate_shop_ids: list[int] = Field(default_factory=list)
    comparison_targets: list[dict[str, Any]] = Field(default_factory=list)

def is_low_information_query(text: str) -> bool:
    compact = (text or "").strip()
    if not compact:
        return True
    stripped = re.sub(r"[\s，,。.!！？?；;：:…]+", "", compact)
    if not stripped:
        return True
    return stripped in ("，", "。", "?", "？", "啊", "嗯", "1", "...")

class TargetShopPolicy:
    def validate(
        self,
        raw_query: str,
        candidates: list[CandidateShop],
        selection: SemanticSelectionResult,
        session_context: dict[str, Any] | None = None,
        client_context: dict[str, Any] | None = None,
    ) -> TargetShop:
        low_info = is_low_information_query(raw_query)
        session_ctx = session_context or {}
        client_ctx = client_context or {}

        from learning_agent_service.local_life.entity_resolver import _explicit_entity_from_query
        explicit_mention = _explicit_entity_from_query(raw_query)

        # 1. First, try to resolve exact pronouns / aliases strictly from context
        if explicit_mention:
            sid, sname, source_label = _resolve_alias_from_contexts(explicit_mention, client_ctx, session_ctx)
            if sid and sname:
                return TargetShop(
                    shop_id=sid,
                    shop_name=sname,
                    status=ShopResolveResult.RESOLVED,
                    raw_mention=explicit_mention,
                    source="pronoun_session" if source_label == "candidate_reference" else "session",
                    resolution_source=source_label,
                    confidence=0.9,
                    is_explicit_in_current_turn=False,
                    is_pronoun_inherited=True,
                    is_candidate_reference=(source_label == "candidate_reference"),
                    reason=f"Resolved strictly from context: {source_label}",
                    candidate_shop_ids=[sid]
                )

            # If it's an explicit mention but not found in context, check candidates directly
            matched_cand = next((c for c in candidates if c.match_type in ("exact", "alias", "fuzzy") and c.matched_text == explicit_mention), None)
            if matched_cand:
                return TargetShop(
                    shop_id=matched_cand.shop_id,
                    shop_name=matched_cand.canonical_name,
                    status=ShopResolveResult.RESOLVED,
                    raw_mention=explicit_mention,
                    source="current_query",
                    resolution_source="explicit_query",
                    confidence=0.95,
                    is_explicit_in_current_turn=True,
                    is_pronoun_inherited=False,
                    reason="explicit_match_candidate",
                    candidate_shop_ids=[matched_cand.shop_id]
                )
                
            # If explicit mention is present but not in candidates or context, it's a failed lookup.
            # Do NOT fallback to LLM semantic selection because it might hallucinate comparisons.
            return TargetShop(
                shop_id=None,
                shop_name=explicit_mention,
                status=ShopResolveResult.NOT_FOUND,
                raw_mention=explicit_mention,
                source="current_query",
                resolution_source="explicit_not_found",
                confidence=0.1,
                is_explicit_in_current_turn=True,
                is_pronoun_inherited=False,
                reason="explicit_not_found_in_candidates",
                candidate_shop_ids=[]
            )

        # 2. Handle explicit anchor shop returned by LLM semantic selection
        if selection.anchor_shop_id is not None:
            # Validate if the selected shop exists in our candidates
            matched_cand = next((c for c in candidates if c.shop_id == selection.anchor_shop_id), None)
            if matched_cand:
                source = "current_query" if matched_cand.match_type in ("exact", "alias", "fuzzy") else "session"
                resolution_source = "explicit_query" if source == "current_query" else "session_current"
                is_explicit = source == "current_query"
                is_pronoun = selection.follow_up_kind == "entity_reference" and source == "session"

                return TargetShop(
                    shop_id=matched_cand.shop_id,
                    shop_name=matched_cand.canonical_name,
                    status=ShopResolveResult.RESOLVED,
                    raw_mention=matched_cand.matched_text,
                    source=source,
                    resolution_source=resolution_source,
                    confidence=selection.confidence,
                    is_explicit_in_current_turn=is_explicit,
                    is_pronoun_inherited=is_pronoun,
                    reason=f"LLM semantic selection: {selection.follow_up_kind}",
                    candidate_shop_ids=[matched_cand.shop_id] if matched_cand.shop_id else []
                )

        # 3. Check for comparison logic
        if selection.follow_up_kind == "comparison_completion":
            return TargetShop(
                shop_id=None,
                shop_name=None,
                status=ShopResolveResult.AMBIGUOUS,
                source="session",
                resolution_source="ambiguous",
                confidence=selection.confidence,
                should_clarify=False,
                reason="comparison_completion",
                candidate_shop_ids=[],
                comparison_targets=selection.comparison_targets
            )

        # 4. If LLM didn't pick anything but we have high-confidence exact matches
        exact_cands = [c for c in candidates if c.match_type == "exact"]
        if exact_cands:
            best = exact_cands[0]
            return TargetShop(
                shop_id=best.shop_id,
                shop_name=best.canonical_name,
                status=ShopResolveResult.RESOLVED,
                raw_mention=best.matched_text,
                source="current_query",
                resolution_source="explicit_query",
                confidence=best.score,
                is_explicit_in_current_turn=True,
                reason="fallback to exact match",
                candidate_shop_ids=[best.shop_id] if best.shop_id else []
            )

        # 5. If we have an explicit mention but it didn't match context or candidates
        if explicit_mention and not any(p == explicit_mention for p in _PRONOUNS):
            return TargetShop(
                shop_id=None,
                shop_name=explicit_mention,
                status=ShopResolveResult.NOT_FOUND,
                raw_mention=explicit_mention,
                source="current_query",
                resolution_source="explicit_query",
                confidence=0.5,
                is_explicit_in_current_turn=True,
                reason="explicit mention not in catalog or context",
                candidate_shop_ids=[]
            )

        # 6. Fallback missing / clarification
        should_clarify = False
        if not low_info and candidates:
            # We have candidates but LLM couldn't decide
            should_clarify = True

        return TargetShop(
            status=ShopResolveResult.AMBIGUOUS if should_clarify else ShopResolveResult.LOW_CONFIDENCE,
            source="session",
            resolution_source="missing" if low_info else "ambiguous",
            confidence=0.0,
            should_clarify=should_clarify,
            reason="low info or ambiguity",
            raw_mention=explicit_mention,
            candidate_shop_ids=[c.shop_id for c in candidates if c.shop_id]
        )
