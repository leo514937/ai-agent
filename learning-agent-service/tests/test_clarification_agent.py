import pytest
from learning_agent_service.application.clarification_agent import ClarificationAgent

def test_clarification_agent_basic():
    agent = ClarificationAgent()
    result = agent.generate_clarification(
        query="这家店怎么样",
        missing_info=["shop_id"],
        context={},
    )
    assert isinstance(result, str)
    assert len(result) > 0

def test_clarification_agent_multiple_missing():
    agent = ClarificationAgent()
    result = agent.generate_clarification(
        query="推荐一家店",
        missing_info=["shop_id", "price_range"],
        context={},
    )
    assert isinstance(result, str)
    assert "店" in result  # 应该提到店铺