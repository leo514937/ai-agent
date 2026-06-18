"""
ClaimValidator - Claim 校验服务

按 claim 类型校验数据来源，实时事实只信 Tool，同店评价只信同 shop_id RAG。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from ..rag.claim_types import ClaimType, REALTIME_CLAIMS, RAG_CLAIMS


class DataSource(Enum):
    """数据来源"""
    TOOL = "tool"
    RAG = "rag"
    UNKNOWN = "unknown"


@dataclass
class Claim:
    """Claim 数据结构"""
    type: ClaimType
    content: str
    shop_id: int | None
    source: DataSource


@dataclass
class ValidationResult:
    """校验结果"""
    valid_claims: list[Claim]
    rejected_claims: list[Claim]
    reasons: dict[str, str]


class ClaimValidator:
    """
    Claim 校验服务
    
    按 claim 类型校验数据来源：
    - 实时事实 claim 只接受 Tool 来源
    - 评价 claim 只接受同 shop_id RAG 来源
    """

    def __init__(
        self,
        realtime_claims: set[ClaimType] | None = None,
        rag_claims: set[ClaimType] | None = None,
    ):
        self._realtime_claims = realtime_claims or REALTIME_CLAIMS
        self._rag_claims = rag_claims or RAG_CLAIMS

    def validate(
        self,
        claims: list[Claim],
        expected_source: DataSource | None = None,
        shop_id: int | None = None,
    ) -> ValidationResult:
        """
        校验 claims
        
        Args:
            claims: 要校验的 claims 列表
            expected_source: 预期的数据来源（可选）
            shop_id: 预期的 shop_id（用于校验 RAG 来源）
        
        Returns:
            ValidationResult: 校验结果
        """
        valid_claims: list[Claim] = []
        rejected_claims: list[Claim] = []
        reasons: dict[str, str] = {}

        for claim in claims:
            is_valid, reason = self._validate_single_claim(
                claim, expected_source, shop_id
            )
            
            if is_valid:
                valid_claims.append(claim)
            else:
                rejected_claims.append(claim)
                reasons[f"{claim.type.value}_{claim.content[:20]}"] = reason

        return ValidationResult(
            valid_claims=valid_claims,
            rejected_claims=rejected_claims,
            reasons=reasons,
        )

    def _validate_single_claim(
        self,
        claim: Claim,
        expected_source: DataSource | None,
        shop_id: int | None,
    ) -> tuple[bool, str]:
        """校验单个 claim"""
        # 1. 实时事实 claim 必须来自 Tool
        if claim.type in self._realtime_claims:
            if claim.source != DataSource.TOOL:
                return False, "realtime_claim_not_from_tool"
            return True, "valid_realtime_claim"

        # 2. RAG claim 必须来自同 shop_id RAG
        if claim.type in self._rag_claims:
            if claim.source != DataSource.RAG:
                return False, "rag_claim_not_from_rag"
            
            # 检查 shop_id 匹配
            if shop_id is not None and claim.shop_id is not None:
                if claim.shop_id != shop_id:
                    return False, "rag_claim_wrong_shop_id"
            
            return True, "valid_rag_claim"

        # 3. 其他类型 claim
        if expected_source is not None and claim.source != expected_source:
            return False, "unexpected_source"

        return True, "valid_claim"
