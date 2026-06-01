from __future__ import annotations

from typing import List, Literal, Optional
from pydantic import BaseModel, Field

class AnswerContract(BaseModel):
    allowed_facets: List[str]
    forbidden_facets: List[str]
    required_sections: List[str] = Field(default_factory=list)
    forbidden_sections: List[str] = Field(default_factory=list)
    allowed_cards: List[str] = Field(default_factory=list)
    forbidden_cards: List[str] = Field(default_factory=list)
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

    @classmethod
    def build_contract(cls, user_need, target_shop=None) -> AnswerContract:
        req_facet_names = [f.name for f in getattr(user_need, "required_facets", []) or []]
        user_focused_facets = [f for f in req_facet_names if f not in ("location", "category")]
        raw_query = str(getattr(user_need, "raw_query", "") or "")
        compact_query = raw_query.replace(" ", "")
        inferred_coupon = any(token in compact_query for token in ("券", "优惠", "领券", "打折", "代金券", "折扣", "有券", "团购"))
        inferred_open = any(token in compact_query for token in ("营业", "开门", "开着", "营业时间", "现在营业吗", "现在开吗", "营业吗"))
        inferred_distance = any(token in compact_query for token in ("距离", "有多远", "导航", "路线", "怎么走", "怎么去"))
        
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
        elif getattr(user_need, "intent", None) == "clarify":
            allowed_facets = []
            forbidden_facets = ["environment", "taste", "service", "recommendation", "coupon", "open_status", "distance_eta", "price"]
            answer_style = "clarification"
        elif len([name for name in user_focused_facets if name in {"coupon", "open_status", "distance_eta"}]) > 1:
            allowed_facets = ["coupon", "open_status", "distance_eta", "distance", "price", "shop_detail", "recommendation_reason"]
            forbidden_facets = ["recommendation"]
            answer_style = "facet_multi"
        elif "shop_detail" in user_focused_facets or "recommendation_reason" in user_focused_facets or not user_focused_facets:
            allowed_facets = ["environment", "taste", "service", "recommendation", "scene_fit", "coupon", "open_status", "distance_eta", "price", "shop_detail", "recommendation_reason"]
            forbidden_facets = []
            if target_shop and (target_shop.shop_id is not None or target_shop.shop_name is not None):
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

        return cls(
            allowed_facets=allowed_facets,
            forbidden_facets=forbidden_facets,
            answer_style=answer_style,
            missing_info_policy="say_unknown"
        )
