import pytest
from learning_agent_service.application.decision_ranker import DecisionRanker, Candidate, RankedCandidate

def test_decision_ranker_basic():
    ranker = DecisionRanker()
    candidates = [
        Candidate(name="店铺A", score=4.5, attributes={"price": "中等"}),
        Candidate(name="店铺B", score=4.0, attributes={"price": "便宜"}),
        Candidate(name="店铺C", score=4.8, attributes={"price": "贵"}),
    ]
    result = ranker.rank_and_explain(
        candidates=candidates,
        evidence=[],
        query="推荐适合约会的餐厅",
    )
    assert len(result) == 3
    assert result[0].name == "店铺C"  # 最高分排第一
    assert all(r.explanation for r in result)  # 每个都有解释