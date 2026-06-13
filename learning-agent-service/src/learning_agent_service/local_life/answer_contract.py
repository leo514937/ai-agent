from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AnswerContract(BaseModel):
    original_query: str = ""
    allowed_facets: list[str]
    forbidden_facets: list[str]
    required_sections: list[str] = Field(default_factory=list)
    forbidden_sections: list[str] = Field(default_factory=list)
    allowed_cards: list[str] = Field(default_factory=list)
    forbidden_cards: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    allowed_rag_facets: list[str] = Field(default_factory=list)
    forbidden_rag_facets: list[str] = Field(default_factory=list)
    realtime_facets: list[str] = Field(default_factory=list)
    allow_recommendation: bool = False
    allow_extra_context: bool = False
    realtime_required: bool = False
    evidence_policy: Literal["strict", "balanced", "lenient"] = "balanced"
    answer_style: Literal[
        "coupon_only",
        "open_status_only",
        "distance_only",
        "single_shop_review",
        "facet_multi",
        "multi_shop_recommendation",
        "comparison",
        "clarification",
    ]
    missing_info_policy: Literal[
        "say_unknown",
        "ask_clarify",
        "partial_answer",
    ] = "say_unknown"

    def facet_set(self) -> set[str]:
        return {str(facet).strip() for facet in self.allowed_facets if str(facet).strip()}

    def forbidden_facet_set(self) -> set[str]:
        return {str(facet).strip() for facet in self.forbidden_facets if str(facet).strip()}

    def as_pruning_hint(self) -> dict[str, Any]:
        return {
            "allowed_facets": list(self.allowed_facets),
            "forbidden_facets": list(self.forbidden_facets),
            "allowed_tools": list(self.allowed_tools),
            "allowed_rag_facets": list(self.allowed_rag_facets),
            "forbidden_rag_facets": list(self.forbidden_rag_facets),
            "realtime_facets": list(self.realtime_facets),
            "allow_recommendation": bool(self.allow_recommendation),
            "allow_extra_context": bool(self.allow_extra_context),
            "realtime_required": bool(self.realtime_required),
            "evidence_policy": self.evidence_policy,
            "answer_style": self.answer_style,
            "missing_info_policy": self.missing_info_policy,
        }

    @classmethod
    def build_contract(cls, user_need, target_shop=None) -> AnswerContract:
        req_facet_names = [f.name for f in getattr(user_need, "required_facets", []) or []]
        user_focused_facets = [f for f in req_facet_names if f not in ("location", "category")]
        raw_query = str(getattr(user_need, "raw_query", "") or "")
        compact_query = raw_query.replace(" ", "")
        user_slots = getattr(user_need, "slots", None)
        slot_shop_id = getattr(user_slots, "shop_id", None) if user_slots is not None else None
        slot_shop_name = getattr(user_slots, "shop_name", None) if user_slots is not None else None
        slot_shop_query = getattr(user_slots, "shop_query", None) if user_slots is not None else None
        has_explicit_shop_hint = bool(target_shop and (target_shop.shop_id is not None or target_shop.shop_name is not None)) or bool(slot_shop_id not in (None, "")) or bool(str(slot_shop_name or "").strip()) or bool(str(slot_shop_query or "").strip())
        intent_name = str(getattr(user_need, "intent", "") or "").strip()
        inferred_coupon = any(token in compact_query for token in ("券", "优惠", "领券", "打折", "代金券", "折扣", "有券", "团购"))
        inferred_open = any(token in compact_query for token in ("营业", "开门", "开着", "营业时间", "现在营业吗", "现在开吗", "营业吗"))
        inferred_distance = any(token in compact_query for token in ("离我多远", "距离", "有多远", "导航", "路线", "怎么走", "怎么去"))
        inferred_comparison = (
            intent_name in ("restaurant_comparison", "comparison", "local_life_comparison")
            or (
                any(token in compact_query for token in ("对比", "比较", "区别", "差别", "哪家更", "哪个更", "更便宜", "更适合", "更好"))
                and any(token in compact_query for token in ("和", "比", "vs"))
            )
        )
        
        # Determine base allowed and forbidden facets
        # Default facets to consider: "coupon", "open_status", "distance_eta", "price", "scene_fit", "environment", "taste", "service", "recommendation", "recommendation_reason", "shop_detail"
        if len(user_focused_facets) == 1 and user_focused_facets[0] == "coupon":
            allowed_facets = ["coupon"]
            forbidden_facets = ["environment", "taste", "service", "recommendation", "scene_fit", "open_status", "distance_eta", "price"]
            answer_style = "coupon_only"
        elif len(user_focused_facets) == 1 and user_focused_facets[0] == "open_status":
            allowed_facets = ["open_status"]
            forbidden_facets = ["environment", "taste", "service", "recommendation", "scene_fit", "coupon", "distance_eta", "price"]
            answer_style = "open_status_only"
        elif len(user_focused_facets) == 1 and user_focused_facets[0] == "distance_eta":
            allowed_facets = ["distance_eta", "distance"]
            forbidden_facets = ["environment", "taste", "service", "recommendation", "scene_fit", "coupon", "open_status", "price"]
            answer_style = "distance_only"
        elif inferred_coupon and not inferred_open and not inferred_distance:
            allowed_facets = ["coupon"]
            forbidden_facets = ["environment", "taste", "service", "recommendation", "scene_fit", "open_status", "distance_eta", "price"]
            answer_style = "coupon_only"
        elif inferred_open and not inferred_coupon and not inferred_distance:
            allowed_facets = ["open_status"]
            forbidden_facets = ["environment", "taste", "service", "recommendation", "scene_fit", "coupon", "distance_eta", "price"]
            answer_style = "open_status_only"
        elif inferred_distance and not inferred_coupon and not inferred_open:
            allowed_facets = ["distance_eta", "distance"]
            forbidden_facets = ["environment", "taste", "service", "recommendation", "scene_fit", "coupon", "open_status", "price"]
            answer_style = "distance_only"
        elif sum(1 for flag in (inferred_coupon, inferred_open, inferred_distance) if flag) > 1:
            if target_shop and (target_shop.shop_id is not None or target_shop.shop_name is not None):
                allowed_facets = ["environment", "taste", "service", "coupon", "open_status", "distance_eta", "distance", "price", "shop_detail", "recommendation_reason"]
                forbidden_facets = ["recommendation"]
                answer_style = "facet_multi"
            else:
                allowed_facets = ["environment", "taste", "service", "coupon", "open_status", "distance_eta", "distance", "price", "shop_detail", "recommendation_reason"]
                forbidden_facets = []
                answer_style = "multi_shop_recommendation"
        elif inferred_comparison:
            allowed_facets = ["environment", "taste", "service", "recommendation", "scene_fit", "coupon", "open_status", "distance_eta", "distance", "price", "shop_detail", "recommendation_reason"]
            forbidden_facets = []
            answer_style = "comparison"
        elif getattr(user_need, "intent", None) == "clarify":
            allowed_facets = []
            forbidden_facets = ["environment", "taste", "service", "recommendation", "coupon", "open_status", "distance_eta", "price"]
            answer_style = "clarification"
        elif len([name for name in user_focused_facets if name in {"coupon", "open_status", "distance_eta"}]) > 1:
            if intent_name == "restaurant_recommendation" and target_shop is None:
                allowed_facets = ["coupon", "open_status", "distance_eta", "distance", "price", "scene_fit", "recommendation_reason", "shop_detail"]
                forbidden_facets = []
                answer_style = "multi_shop_recommendation"
            else:
                allowed_facets = ["environment", "taste", "service", "coupon", "open_status", "distance_eta", "distance", "price", "shop_detail", "recommendation_reason"]
                forbidden_facets = ["recommendation"]
                answer_style = "facet_multi"
        elif intent_name == "restaurant_recommendation" and target_shop is None:
            allowed_facets = ["environment", "taste", "service", "recommendation", "scene_fit", "coupon", "open_status", "distance_eta", "price", "shop_detail", "recommendation_reason"]
            forbidden_facets = []
            answer_style = "multi_shop_recommendation"
        elif "shop_detail" in user_focused_facets or "recommendation_reason" in user_focused_facets or not user_focused_facets:
            allowed_facets = ["environment", "taste", "service", "recommendation", "scene_fit", "coupon", "open_status", "distance_eta", "price", "shop_detail", "recommendation_reason"]
            forbidden_facets = []
            if has_explicit_shop_hint:
                answer_style = "single_shop_review"
            else:
                answer_style = "multi_shop_recommendation"
        else:
            allowed_facets = ["environment", "taste", "service", "recommendation", "scene_fit", "coupon", "open_status", "distance_eta", "price", "shop_detail", "recommendation_reason"]
            forbidden_facets = []
            if getattr(user_need, "intent", None) == "restaurant_comparison":
                answer_style = "comparison"
            else:
                answer_style = "multi_shop_recommendation"

        realtime_facet_set = {"coupon", "open_status", "distance_eta"}
        allowed_rag_facets = [facet for facet in allowed_facets if facet not in realtime_facet_set]
        realtime_facets = [facet for facet in allowed_facets if facet in realtime_facet_set]
        forbidden_rag_facets = list(
            dict.fromkeys(
                [
                    *forbidden_facets,
                    *realtime_facets,
                ]
            )
        )
        allowed_tools: list[str] = []
        if "coupon" in allowed_facets:
            allowed_tools.append("get_coupon_list")
        if "open_status" in allowed_facets:
            allowed_tools.extend(["check_open_status", "getShopDetail", "getBusinessStatus"])
        if "distance_eta" in allowed_facets:
            allowed_tools.append("get_distance_eta")
        if "recommendation" in allowed_facets or answer_style in {"multi_shop_recommendation", "comparison", "facet_multi"}:
            allowed_tools.extend(["search_restaurants", "getShopDetail", "recommendShops"])
        allowed_tools = list(dict.fromkeys(allowed_tools))
        allow_recommendation = answer_style in {"multi_shop_recommendation", "comparison", "facet_multi"}
        allow_extra_context = allow_recommendation or answer_style == "single_shop_review"
        realtime_required = any(facet in {"coupon", "open_status", "distance_eta"} for facet in allowed_facets)
        evidence_policy = "strict" if not allow_extra_context else "balanced"

        return cls(
            original_query=raw_query,
            allowed_facets=allowed_facets,
            forbidden_facets=forbidden_facets,
            allowed_tools=allowed_tools,
            allowed_rag_facets=allowed_rag_facets,
            forbidden_rag_facets=forbidden_rag_facets,
            realtime_facets=realtime_facets,
            allow_recommendation=allow_recommendation,
            allow_extra_context=allow_extra_context,
            realtime_required=realtime_required,
            evidence_policy=evidence_policy,
            answer_style=answer_style,
            missing_info_policy="say_unknown"
        )
