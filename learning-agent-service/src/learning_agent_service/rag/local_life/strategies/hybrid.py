from __future__ import annotations

from collections.abc import Sequence

_DEFAULT_ROLE_WEIGHTS = {
    "merchant_profile": 1.0,
    "merchant_review_summary": 1.0,
    "merchant_scene_fit": 1.0,
    "merchant_pitfall_summary": 0.92,
    "package_description": 0.92,
    "merchant_blog_note": 0.88,
    "local_guide": 0.84,
    "platform_rule": 0.72,
}

_ROLE_KEYWORDS = {
    "merchant_scene_fit": ("适合", "约会", "聚餐", "家庭", "长辈", "朋友", "商务", "学生", "夜宵"),
    "merchant_pitfall_summary": ("坑", "排队", "吵", "停车", "贵", "服务慢", "不好", "避雷", "拥挤", "等位"),
    "package_description": ("套餐", "券", "优惠", "团购", "几人", "划算", "价格", "折扣"),
    "merchant_review_summary": ("怎么样", "评价", "口碑", "推荐", "好吃吗"),
    "merchant_profile": ("地址", "营业", "商圈", "类型", "介绍"),
    "local_guide": ("攻略", "规则", "平台", "怎么选", "怎么用", "注意事项", "指南"),
    "platform_rule": ("规则", "平台", "活动", "说明", "条款", "限制", "规则说明"),
}


def _compact_query(query: str) -> str:
    return "".join(str(query or "").split()).lower()


def infer_role_weights(query: str, *, route: str | None = None) -> dict[str, float]:
    weights = dict(_DEFAULT_ROLE_WEIGHTS)
    compact = _compact_query(query)
    for role, keywords in _ROLE_KEYWORDS.items():
        if any(keyword in compact for keyword in keywords):
            weights[role] = max(weights.get(role, 1.0), 1.4)
    route_value = str(route or "").strip().lower()
    if route_value == "guide_rule_rag":
        weights["local_guide"] = max(weights.get("local_guide", 1.0), 1.55)
        weights["platform_rule"] = max(weights.get("platform_rule", 1.0), 1.5)
    elif route_value == "compare_multi_parent":
        weights["merchant_review_summary"] = max(weights.get("merchant_review_summary", 1.0), 1.25)
        weights["merchant_scene_fit"] = max(weights.get("merchant_scene_fit", 1.0), 1.2)
    if not any(keyword in compact for keyword in _ROLE_KEYWORDS["merchant_scene_fit"]):
        weights["merchant_scene_fit"] = max(weights["merchant_scene_fit"], 0.98)
    if not any(keyword in compact for keyword in _ROLE_KEYWORDS["merchant_review_summary"]):
        weights["merchant_review_summary"] = max(weights["merchant_review_summary"], 0.98)
    if not any(keyword in compact for keyword in _ROLE_KEYWORDS["merchant_profile"]):
        weights["merchant_profile"] = max(weights["merchant_profile"], 0.98)
    return weights
