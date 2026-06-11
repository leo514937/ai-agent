"""
Retry质量评估器

评估retry前后的答案质量，确保retry确实改善了答案。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RetryQualityMetrics:
    """Retry质量指标"""
    pre_retry_score: float = 0.0
    post_retry_score: float = 0.0
    improvement: float = 0.0
    should_keep_retry: bool = True
    reason: str = ""


def calculate_answer_quality_score(
    answer: str,
    evidence_count: int,
    has_tool_result: bool,
    forbidden_facets_leaked: bool = False,
    cross_shop_leak: bool = False,
) -> float:
    """计算答案质量分数 (0-1)

    Args:
        answer: 答案文本
        evidence_count: 证据数量
        has_tool_result: 是否有工具调用结果
        forbidden_facets_leaked: 是否泄露禁止维度
        cross_shop_leak: 是否串店

    Returns:
        质量分数 (0-1)
    """
    score = 0.5  # 基础分

    # 证据数量加分
    if evidence_count >= 3:
        score += 0.2
    elif evidence_count >= 1:
        score += 0.1

    # 工具调用加分
    if has_tool_result:
        score += 0.1

    # 答案长度合理性
    answer_len = len(answer)
    if 50 <= answer_len <= 500:
        score += 0.1
    elif answer_len > 0:
        score += 0.05

    # 惩罚
    if forbidden_facets_leaked:
        score -= 0.3
    if cross_shop_leak:
        score -= 0.3
    if evidence_count == 0:
        score -= 0.2

    return max(0.0, min(1.0, score))


def evaluate_retry_quality(
    pre_retry_answer: str,
    post_retry_answer: str,
    pre_retry_evidence_count: int,
    post_retry_evidence_count: int,
    has_tool_result: bool,
    forbidden_facets_leaked: bool = False,
    cross_shop_leak: bool = False,
) -> RetryQualityMetrics:
    """评估retry质量

    Args:
        pre_retry_answer: retry前的答案
        post_retry_answer: retry后的答案
        pre_retry_evidence_count: retry前的证据数量
        post_retry_evidence_count: retry后的证据数量
        has_tool_result: 是否有工具调用结果
        forbidden_facets_leaked: 是否泄露禁止维度
        cross_shop_leak: 是否串店

    Returns:
        RetryQualityMetrics
    """
    pre_score = calculate_answer_quality_score(
        pre_retry_answer,
        pre_retry_evidence_count,
        has_tool_result,
        forbidden_facets_leaked,
        cross_shop_leak,
    )

    post_score = calculate_answer_quality_score(
        post_retry_answer,
        post_retry_evidence_count,
        has_tool_result,
        forbidden_facets_leaked,
        cross_shop_leak,
    )

    improvement = post_score - pre_score

    # 决策逻辑
    should_keep = True
    reason = ""

    if improvement < -0.1:
        # 质量明显下降
        should_keep = False
        reason = "quality_degraded"
    elif improvement < 0:
        # 轻微下降
        should_keep = True
        reason = "slight_degradation_tolerated"
    elif improvement == 0:
        # 无变化
        should_keep = True
        reason = "no_change"
    else:
        # 有提升
        should_keep = True
        reason = "improved"

    return RetryQualityMetrics(
        pre_retry_score=pre_score,
        post_retry_score=post_score,
        improvement=improvement,
        should_keep_retry=should_keep,
        reason=reason,
    )
