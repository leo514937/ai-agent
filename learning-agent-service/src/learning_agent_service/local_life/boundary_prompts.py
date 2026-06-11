"""
统一边界提示策略

定义用户友好的降级消息，替代技术性错误信息。
"""
from __future__ import annotations


# 边界提示字典
BOUNDARY_PROMPTS: dict[str, str] = {
    # 位置相关
    "no_location": "我需要知道您所在的位置才能推荐附近的商家，请告诉我您的城市或位置。",
    "location_unavailable": "抱歉，该位置暂时无法提供服务。请尝试切换到其他城市。",
    
    # 商家相关
    "no_shop_found": "我没有找到您询问的商家信息，请确认店名是否正确。",
    "shop_name_ambiguous": "您提到的店名有多个匹配，请告诉我具体是哪一家。",
    
    # 信息相关
    "no_coupon_evidence": "我暂时无法确认这家店的优惠券信息，建议以店铺页面显示为准。",
    "no_open_status": "我暂时无法确认这家店当前是否营业，建议以店铺页面实时状态为准。",
    "no_distance_info": "我暂时无法确认这家店与你的实时距离信息，建议以地图页面显示为准。",
    
    # 数据新鲜度
    "outdated_info": "这家店的信息可能不是最新的，建议您直接联系商家确认。",
    "stale_evidence": "这部分信息可能已过时，建议以商家页面最新信息为准。",
    
    # 系统相关
    "evidence_insufficient": "我目前没有足够的信息来回答这个问题，您可以尝试换一种问法。",
    "service_unavailable": "抱歉，服务暂时不可用，请稍后再试。",
    "query_too_complex": "您的问题比较复杂，我可能无法完整回答，建议您分步提问。",
    
    # 意图相关
    "out_of_scope": "抱歉，我主要提供本地生活服务信息，其他问题我可能帮不上忙。",
    "comparison_insufficient": "对比信息不足，无法给出有效建议，您可以分别查询两家店的详细信息。",
    
    # 追问相关
    "clarify_shop_name": "请问您想了解哪一家店的具体信息呢？可以告诉我店名或品牌。",
    "clarify_location": "为了给您提供更准确的信息，请问您目前在哪个城市或商圈附近？",
    "clarify_category": "请问您具体想找什么类型的店呢？比如火锅、烧烤、粤菜、还是咖啡甜点？",
}


def get_boundary_prompt(key: str, shop_name: str | None = None, **kwargs: str) -> str:
    """获取边界提示消息
    
    Args:
        key: 提示键名
        shop_name: 商家名称（可选）
        **kwargs: 额外的替换参数
        
    Returns:
        用户友好的提示消息
    """
    template = BOUNDARY_PROMPTS.get(key, BOUNDARY_PROMPTS["evidence_insufficient"])
    
    # 替换商家名称
    if shop_name:
        template = template.replace("这家店", shop_name, 1)
    
    # 替换其他参数
    for k, v in kwargs.items():
        template = template.replace(f"{{{k}}}", v)
    
    return template


def get_freshness_prompt(freshness_status: str, shop_name: str | None = None) -> str | None:
    """根据数据新鲜度状态获取提示
    
    Args:
        freshness_status: 新鲜度状态 (realtime/historical/mixed/unavailable)
        shop_name: 商家名称
        
    Returns:
        提示消息或None
    """
    if freshness_status == "historical":
        return get_boundary_prompt("outdated_info", shop_name)
    elif freshness_status == "unavailable":
        return get_boundary_prompt("evidence_insufficient", shop_name)
    return None