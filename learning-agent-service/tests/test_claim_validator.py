"""ClaimValidator 测试"""

import pytest
from learning_agent_service.tools.claim_validator import (
    ClaimValidator,
    Claim,
    DataSource,
    ValidationResult,
)
from learning_agent_service.rag.claim_types import ClaimType


@pytest.fixture
def validator():
    """创建 ClaimValidator 实例"""
    return ClaimValidator()


class TestClaimValidator:
    """ClaimValidator 测试"""

    def test_validate_realtime_claim_from_tool(self, validator):
        """测试实时事实 claim 从 Tool 来源 → valid"""
        claim = Claim(
            type=ClaimType.COUPON,
            content="满100减20优惠券",
            shop_id=5,
            source=DataSource.TOOL,
        )
        result = validator.validate([claim], shop_id=5)
        
        assert len(result.valid_claims) == 1
        assert len(result.rejected_claims) == 0
        assert result.valid_claims[0] == claim

    def test_validate_realtime_claim_from_rag_rejected(self, validator):
        """测试实时事实 claim 从 RAG 来源 → rejected"""
        claim = Claim(
            type=ClaimType.COUPON,
            content="满100减20优惠券",
            shop_id=5,
            source=DataSource.RAG,
        )
        result = validator.validate([claim], shop_id=5)
        
        assert len(result.valid_claims) == 0
        assert len(result.rejected_claims) == 1
        assert result.rejected_claims[0] == claim
        assert any("realtime_claim_not_from_tool" in v for v in result.reasons.values())

    def test_validate_rag_claim_from_rag(self, validator):
        """测试评价 claim 从同 shop_id RAG 来源 → valid"""
        claim = Claim(
            type=ClaimType.REVIEW,
            content="服务很好，环境不错",
            shop_id=5,
            source=DataSource.RAG,
        )
        result = validator.validate([claim], shop_id=5)
        
        assert len(result.valid_claims) == 1
        assert len(result.rejected_claims) == 0
        assert result.valid_claims[0] == claim

    def test_validate_rag_claim_from_tool_rejected(self, validator):
        """测试评价 claim 从 Tool 来源 → rejected"""
        claim = Claim(
            type=ClaimType.REVIEW,
            content="服务很好，环境不错",
            shop_id=5,
            source=DataSource.TOOL,
        )
        result = validator.validate([claim], shop_id=5)
        
        assert len(result.valid_claims) == 0
        assert len(result.rejected_claims) == 1
        assert result.rejected_claims[0] == claim
        assert any("rag_claim_not_from_rag" in v for v in result.reasons.values())

    def test_validate_rag_claim_wrong_shop_id(self, validator):
        """测试评价 claim 从不同 shop_id RAG 来源 → rejected"""
        claim = Claim(
            type=ClaimType.REVIEW,
            content="服务很好，环境不错",
            shop_id=6,  # 不同的 shop_id
            source=DataSource.RAG,
        )
        result = validator.validate([claim], shop_id=5)
        
        assert len(result.valid_claims) == 0
        assert len(result.rejected_claims) == 1
        assert result.rejected_claims[0] == claim
        assert any("rag_claim_wrong_shop_id" in v for v in result.reasons.values())

    def test_validate_mixed_claims(self, validator):
        """测试混合 claims"""
        claims = [
            Claim(
                type=ClaimType.COUPON,
                content="满100减20优惠券",
                shop_id=5,
                source=DataSource.TOOL,
            ),
            Claim(
                type=ClaimType.REVIEW,
                content="服务很好，环境不错",
                shop_id=5,
                source=DataSource.RAG,
            ),
            Claim(
                type=ClaimType.COUPON,
                content="8折优惠",
                shop_id=5,
                source=DataSource.RAG,  # 错误来源
            ),
        ]
        result = validator.validate(claims, shop_id=5)
        
        assert len(result.valid_claims) == 2
        assert len(result.rejected_claims) == 1
        assert result.rejected_claims[0].type == ClaimType.COUPON

    def test_validate_empty_claims(self, validator):
        """测试空 claims 列表"""
        result = validator.validate([], shop_id=5)
        
        assert len(result.valid_claims) == 0
        assert len(result.rejected_claims) == 0
        assert len(result.reasons) == 0
