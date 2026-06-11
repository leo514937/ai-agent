"""Tests for retry quality evaluator."""
from learning_agent_service.local_life.retry_quality_evaluator import (
    calculate_answer_quality_score,
    evaluate_retry_quality,
)


def test_calculate_answer_quality_score_good():
    score = calculate_answer_quality_score(
        answer="这是一家不错的餐厅，环境优雅，服务周到。人均消费约100元。",
        evidence_count=5,
        has_tool_result=True,
    )
    assert score > 0.7


def test_calculate_answer_quality_score_bad():
    score = calculate_answer_quality_score(
        answer="",
        evidence_count=0,
        has_tool_result=False,
    )
    assert score <= 0.3


def test_calculate_answer_quality_score_leak():
    score = calculate_answer_quality_score(
        answer="推荐其他店铺",
        evidence_count=3,
        has_tool_result=True,
        forbidden_facets_leaked=True,
    )
    assert score <= 0.55


def test_evaluate_retry_quality_improved():
    metrics = evaluate_retry_quality(
        pre_retry_answer="简短回答",
        post_retry_answer="更详细的回答，包含更多信息",
        pre_retry_evidence_count=1,
        post_retry_evidence_count=5,
        has_tool_result=True,
    )
    assert metrics.improvement > 0
    assert metrics.should_keep_retry


def test_evaluate_retry_quality_degraded():
    metrics = evaluate_retry_quality(
        pre_retry_answer="这是一段长度超过五十个字符的详细回答，包含了丰富的店铺信息和消费建议，让用户能够做出更好的消费决策。",
        post_retry_answer="简短回答",
        pre_retry_evidence_count=5,
        post_retry_evidence_count=0,
        has_tool_result=True,
    )
    assert metrics.improvement < -0.1
    assert not metrics.should_keep_retry
