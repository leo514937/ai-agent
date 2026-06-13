"""LLM 生成失败时的兜底文案"""

FALLBACK_TEXTS: dict[str, str] = {
    "multi_shop_recommendation": "已为你找到相关店铺，建议结合评分、距离和口味偏好综合考虑。",
    "single_shop_review": "已为你查询到店铺信息，建议到店前确认营业状态和排队情况。",
    "comparison": "已为你整理两家店铺的对比信息，可根据自身需求选择。",
    "coupon_only": "已为你查询优惠信息，建议到店前确认券的使用条件和有效期。",
    "open_status_only": "已为你查询营业状态，建议出发前再次确认。",
    "distance_only": "已为你查询距离信息，具体路线可使用导航查看。",
    "facet_multi": "已为你综合查询多个维度的信息，建议结合实际需求判断。",
    "clarification": "请补充一下你想查的具体信息，比如店名或城市。",
}


def get_fallback_text(answer_style: str) -> str:
    """获取兜底文案，未配置时返回通用兜底"""
    return FALLBACK_TEXTS.get(answer_style, "已为你查询到相关信息，建议结合实际情况判断。")
