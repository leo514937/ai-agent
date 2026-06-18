"""
ClaimType 定义 + 分类规则

定义 claim 类型和分类规则，用于 RAG 过滤和 Composer 校验。
"""

from enum import Enum


class ClaimType(Enum):
    """Claim 类型"""
    REVIEW = "review"           # 评价、口碑
    ENVIRONMENT = "environment" # 环境、氛围
    SPECIALTY = "specialty"     # 特色、推荐菜
    COUPON = "coupon"           # 优惠券（实时事实）
    OPEN_STATUS = "open_status" # 营业状态（实时事实）
    DISTANCE = "distance"       # 距离（实时事实）
    INVENTORY = "inventory"     # 库存（实时事实）
    BOOKING = "booking"         # 预约（实时事实）
    ORDER = "order"             # 订单（实时事实）


# 实时事实 claim 类型（必须来自 Tool）
REALTIME_CLAIMS: set[ClaimType] = {
    ClaimType.COUPON,
    ClaimType.OPEN_STATUS,
    ClaimType.DISTANCE,
    ClaimType.INVENTORY,
    ClaimType.BOOKING,
    ClaimType.ORDER,
}

# RAG claim 类型（必须来自同 shop_id RAG）
RAG_CLAIMS: set[ClaimType] = {
    ClaimType.REVIEW,
    ClaimType.ENVIRONMENT,
    ClaimType.SPECIALTY,
}

# chunk_role → ClaimType 映射规则
CHUNK_ROLE_TO_CLAIM_TYPE: dict[str, ClaimType] = {
    "merchant_review_summary": ClaimType.REVIEW,
    "merchant_scene_fit": ClaimType.ENVIRONMENT,
    "merchant_pitfall_summary": ClaimType.REVIEW,
    "merchant_profile": ClaimType.REVIEW,
    "package_description": ClaimType.COUPON,
}


def get_claim_type_from_chunk_role(chunk_role: str) -> ClaimType | None:
    """从 chunk_role 获取 ClaimType"""
    return CHUNK_ROLE_TO_CLAIM_TYPE.get(chunk_role)


def is_realtime_claim(claim_type: ClaimType) -> bool:
    """判断是否为实时事实 claim"""
    return claim_type in REALTIME_CLAIMS


def is_rag_claim(claim_type: ClaimType) -> bool:
    """判断是否为 RAG claim"""
    return claim_type in RAG_CLAIMS
