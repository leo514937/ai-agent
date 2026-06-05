from __future__ import annotations


def infer_intent_hint(query: str) -> str | None:
    text = "".join(str(query or "").split()).lower()
    if any(token in text for token in ("套餐", "团购", "券", "优惠券")):
        return "package_or_coupon"
    if any(token in text for token in ("营业", "开门", "开业", "还能去")):
        return "merchant_status"
    if any(token in text for token in ("适合", "带父母", "带长辈", "约会", "家庭聚餐")):
        return "scene_fit"
    if any(token in text for token in ("避坑", "踩雷", "排队", "停车", "服务怎么样")):
        return "pitfall"
    return None
