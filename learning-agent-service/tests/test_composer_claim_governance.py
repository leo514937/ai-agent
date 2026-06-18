"""Composer Claim Governance Integration Tests"""

import pytest
from learning_agent_service.tools.composer import AnswerComposer
from learning_agent_service.tools.claim_validator import ClaimValidator, Claim, DataSource
from learning_agent_service.rag.claim_types import ClaimType
from learning_agent_service.domain.contracts import AnswerComposeRequest
from types import SimpleNamespace


class TestComposerClaimGovernance:
    """Test claim governance in Composer"""

    def test_realtime_claim_rejected_from_rag_source(self):
        """Test that realtime claims from RAG source are rejected"""
        validator = ClaimValidator()
        claim = Claim(
            type=ClaimType.COUPON,
            content="满100减20优惠券",
            shop_id=5,
            source=DataSource.RAG,  # 错误来源
        )
        result = validator.validate([claim], shop_id=5)
        
        assert len(result.rejected_claims) == 1
        assert result.rejected_claims[0].type == ClaimType.COUPON
        assert any("realtime_claim_not_from_tool" in v for v in result.reasons.values())

    def test_realtime_claim_accepted_from_tool_source(self):
        """Test that realtime claims from Tool source are accepted"""
        validator = ClaimValidator()
        claim = Claim(
            type=ClaimType.COUPON,
            content="满100减20优惠券",
            shop_id=5,
            source=DataSource.TOOL,
        )
        result = validator.validate([claim], shop_id=5)
        
        assert len(result.valid_claims) == 1
        assert len(result.rejected_claims) == 0

    def test_rag_claim_wrong_shop_id_rejected(self):
        """Test that RAG claims with wrong shop_id are rejected"""
        validator = ClaimValidator()
        claim = Claim(
            type=ClaimType.REVIEW,
            content="服务很好，环境不错",
            shop_id=6,  # 不同的 shop_id
            source=DataSource.RAG,
        )
        result = validator.validate([claim], shop_id=5)
        
        assert len(result.rejected_claims) == 1
        assert any("rag_claim_wrong_shop_id" in v for v in result.reasons.values())

    def test_inventory_claim_from_tool_accepted(self):
        """Test that INVENTORY claims from Tool source are accepted"""
        validator = ClaimValidator()
        claim = Claim(
            type=ClaimType.INVENTORY,
            content="库存: 10件",
            shop_id=5,
            source=DataSource.TOOL,
        )
        result = validator.validate([claim], shop_id=5)
        
        assert len(result.valid_claims) == 1
        assert len(result.rejected_claims) == 0

    def test_inventory_claim_from_rag_rejected(self):
        """Test that INVENTORY claims from RAG source are rejected"""
        validator = ClaimValidator()
        claim = Claim(
            type=ClaimType.INVENTORY,
            content="库存: 10件",
            shop_id=5,
            source=DataSource.RAG,
        )
        result = validator.validate([claim], shop_id=5)
        
        assert len(result.rejected_claims) == 1
        assert any("realtime_claim_not_from_tool" in v for v in result.reasons.values())

    def test_multiple_realtime_claims_validation(self):
        """Test validation of multiple realtime claims"""
        validator = ClaimValidator()
        claims = [
            Claim(
                type=ClaimType.COUPON,
                content="满100减20优惠券",
                shop_id=5,
                source=DataSource.TOOL,
            ),
            Claim(
                type=ClaimType.OPEN_STATUS,
                content="营业状态: 营业中",
                shop_id=5,
                source=DataSource.TOOL,
            ),
            Claim(
                type=ClaimType.DISTANCE,
                content="距离: 2.5km, 预计10分钟",
                shop_id=5,
                source=DataSource.RAG,  # 错误来源
            ),
        ]
        result = validator.validate(claims, shop_id=5)
        
        assert len(result.valid_claims) == 2
        assert len(result.rejected_claims) == 1
        assert result.rejected_claims[0].type == ClaimType.DISTANCE

    def test_rag_claims_with_correct_shop_id(self):
        """Test RAG claims with correct shop_id are accepted"""
        validator = ClaimValidator()
        claims = [
            Claim(
                type=ClaimType.REVIEW,
                content="服务很好，环境不错",
                shop_id=5,
                source=DataSource.RAG,
            ),
            Claim(
                type=ClaimType.ENVIRONMENT,
                content="环境安静，适合约会",
                shop_id=5,
                source=DataSource.RAG,
            ),
        ]
        result = validator.validate(claims, shop_id=5)
        
        assert len(result.valid_claims) == 2
        assert len(result.rejected_claims) == 0

    def test_mixed_claims_validation(self):
        """Test validation of mixed claim types"""
        validator = ClaimValidator()
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
                type=ClaimType.OPEN_STATUS,
                content="营业状态: 营业中",
                shop_id=5,
                source=DataSource.RAG,  # 错误来源
            ),
        ]
        result = validator.validate(claims, shop_id=5)
        
        assert len(result.valid_claims) == 2
        assert len(result.rejected_claims) == 1
        assert result.rejected_claims[0].type == ClaimType.OPEN_STATUS
