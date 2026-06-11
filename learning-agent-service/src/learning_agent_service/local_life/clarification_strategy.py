from __future__ import annotations

class ClarificationStrategy:
    """
    Unified manager for clarification decisions to avoid redundant questions
    and centralize logic from phase3_review, target_shop_policy, top_level_intent_router.
    """

    @staticmethod
    def should_clarify_target_shop(
        raw_query: str,
        is_low_info: bool,
        has_explicit_shop_hint: bool,
        has_pronoun: bool,
        has_resolved_ref: bool,
    ) -> tuple[bool, str | None, str | None]:
        """
        Decides if we need to clarify which shop the user is referring to.
        Returns (should_clarify, missing_slot, reason)
        """
        # Rule 1: Pronoun but no reference resolved -> clarify
        if has_pronoun and not has_resolved_ref:
            return True, "shop_name", "reference_resolution_failed"
        
        # Rule 2: Low info query (like "1", "...") and no explicit hint and no resolved ref -> clarify
        if is_low_info and not has_explicit_shop_hint and not has_resolved_ref:
            return True, "shop_name", "low_information_query"
            
        return False, None, None

    @staticmethod
    def requires_current_shop_for_ref(normalized_query: str, has_context_shop: bool) -> bool:
        """
        Checks if the query is a bare follow-up that requires a current shop to be present.
        If it requires one but we don't have it, we should clarify.
        """
        ref_tokens = ("这家", "它", "那个", "这个", "那家")
        bare_followup = ("地址在哪", "在哪", "有券吗", "有券", "几点开门", "几点关门", "营业时间", "营业时间是什么")
        
        has_ref_token = any(token in normalized_query for token in ref_tokens)
        stripped = normalized_query.rstrip("？?。. ")
        is_bare = stripped in bare_followup or normalized_query in bare_followup
        
        if (has_ref_token or is_bare) and not has_context_shop:
            return True
            
        return False

    @staticmethod
    def should_clarify_location(
        is_recommendation: bool,
        has_location_slot: bool,
        has_explicit_shop: bool,
    ) -> bool:
        """
        Decides if we need to clarify location.
        """
        # If it's a recommendation and no location is provided, and we didn't specify a shop
        if is_recommendation and not has_location_slot and not has_explicit_shop:
            return True
        return False

    @staticmethod
    def should_avoid_repeat_clarification(
        current_slot: str,
        asked_slots: list[str] | tuple[str, ...],
        context_shop: str | None = None,
        last_clarification_turn: int | None = None,
        current_turn: int | None = None,
    ) -> bool:
        """判断是否应该避免重复追问。"""
        normalized_slot = str(current_slot or "").strip()
        normalized_asked = {str(slot or "").strip() for slot in asked_slots if str(slot or "").strip()}

        if normalized_slot and normalized_slot in normalized_asked:
            return True

        if normalized_slot == "shop_name" and str(context_shop or "").strip():
            return True

        if last_clarification_turn is not None and current_turn is not None:
            if current_turn - last_clarification_turn < 2:
                return True

        return False

    @staticmethod
    def get_clarification_priority(
        missing_slots: list[str] | tuple[str, ...],
        intent: str,
        has_context_shop: bool,
    ) -> str | None:
        """根据 intent 和上下文选择优先追问的 slot。"""
        normalized_missing = [str(slot or "").strip() for slot in missing_slots if str(slot or "").strip()]
        normalized_intent = str(intent or "").strip().lower()

        priority_rules = {
            "recommendation": ["location", "category", "shop_name"],
            "restaurant_recommendation": ["location", "category", "shop_name"],
            "comparison": ["shop_name", "location"],
            "restaurant_comparison": ["shop_name", "location"],
            "merchant_detail": ["shop_name"],
            "coupon_query": ["shop_name"],
            "open_status": ["shop_name"],
            "distance": ["shop_name"],
            "address": ["shop_name"],
        }

        priority_list = priority_rules.get(normalized_intent, ["shop_name", "location", "category"])
        for slot in priority_list:
            if slot not in normalized_missing:
                continue
            if slot == "shop_name" and has_context_shop:
                continue
            return slot

        return normalized_missing[0] if normalized_missing else None
