"""
业务指标收集器

收集本地生活服务的核心业务指标，用于量化系统效果。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any


@dataclass
class QueryMetrics:
    """单次查询的指标"""
    query: str
    intent: str
    route: str
    answer_style: str
    single_shop_mode: bool = False
    recommendation_mode: bool = False
    tool_called: bool = False
    tools_called: list[str] = field(default_factory=list)
    evidence_count: int = 0
    target_shop_id: int | None = None
    answer_shop_ids: list[int] = field(default_factory=list)
    forbidden_facets: list[str] = field(default_factory=list)
    realtime_facets: list[str] = field(default_factory=list)
    degraded: bool = False
    degraded_reason: str | None = None
    fallback: bool = False
    clarification_asked: bool = False
    clarification_needed: bool = False
    answer_text: str = ""
    failure_modes_detected: list[str] = field(default_factory=list)
    retry_count: int = 0
    retry_improved: bool | None = None
    freshness_status: str | None = None
    staleness_detected: bool = False
    scene_violation: bool = False
    dialog_state: str | None = None


@dataclass
class MetricsSummary:
    """指标汇总"""
    total_queries: int = 0

    # 串店率/错店率
    cross_shop_count: int = 0
    wrong_shop_count: int = 0

    # 过度追问率
    over_clarification_count: int = 0

    # 兜底率
    fallback_count: int = 0

    # 工具调用命中率
    tool_call_count: int = 0
    tool_hit_count: int = 0

    # 空召回率
    empty_recall_count: int = 0

    # 实时信息错误率
    realtime_error_count: int = 0

    # 禁止维度泄露率
    forbidden_facet_leak_count: int = 0

    # 降级率
    degraded_count: int = 0

    # 按 intent 分类统计
    intent_counts: Counter = field(default_factory=Counter)
    intent_cross_shop: Counter = field(default_factory=Counter)
    intent_fallback: Counter = field(default_factory=Counter)
    intent_degraded: Counter = field(default_factory=Counter)

    # 按 answer_style 分类统计
    style_counts: Counter = field(default_factory=Counter)
    style_fallback: Counter = field(default_factory=Counter)

    # 失败模式统计
    failure_mode_counts: Counter = field(default_factory=Counter)

    retry_count: int = 0
    retry_improved_count: int = 0
    retry_degraded_count: int = 0

    staleness_count: int = 0
    scene_violation_count: int = 0

    dialog_state_counts: Counter = field(default_factory=Counter)

    # 按 freshness 分类
    freshness_counts: Counter = field(default_factory=Counter)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_queries": self.total_queries,
            "cross_shop_rate": self.cross_shop_count / max(1, self.total_queries),
            "wrong_shop_rate": self.wrong_shop_count / max(1, self.total_queries),
            "over_clarification_rate": self.over_clarification_count / max(1, self.total_queries),
            "fallback_rate": self.fallback_count / max(1, self.total_queries),
            "tool_hit_rate": self.tool_hit_count / max(1, max(1, self.tool_call_count)),
            "empty_recall_rate": self.empty_recall_count / max(1, self.total_queries),
            "realtime_error_rate": self.realtime_error_count / max(1, self.total_queries),
            "forbidden_facet_leak_rate": self.forbidden_facet_leak_count / max(1, self.total_queries),
            "degraded_rate": self.degraded_count / max(1, self.total_queries),
            "intent_distribution": dict(self.intent_counts),
            "failure_mode_distribution": dict(self.failure_mode_counts),
            "retry_rate": self.retry_count / max(1, self.total_queries),
            "retry_improvement_rate": self.retry_improved_count / max(1, self.retry_count),
            "staleness_rate": self.staleness_count / max(1, self.total_queries),
            "scene_violation_rate": self.scene_violation_count / max(1, self.total_queries),
            "dialog_state_distribution": dict(self.dialog_state_counts),
            "freshness_distribution": dict(self.freshness_counts),
        }


class BusinessMetricsCollector:
    """业务指标收集器"""

    def __init__(self) -> None:
        self._queries: list[QueryMetrics] = []
        self._summary = MetricsSummary()

    def record_query(self, metrics: QueryMetrics) -> None:
        """记录一次查询的指标"""
        self._queries.append(metrics)
        self._summary.total_queries += 1

        # 串店检测
        if metrics.target_shop_id and metrics.answer_shop_ids:
            if metrics.target_shop_id not in metrics.answer_shop_ids and metrics.answer_shop_ids:
                self._summary.cross_shop_count += 1
                self._summary.intent_cross_shop[metrics.intent] += 1

        # 错店检测 (更宽泛: answer_shop_ids 与预期不符)
        if metrics.target_shop_id and len(metrics.answer_shop_ids) == 1:
            if metrics.answer_shop_ids[0] != metrics.target_shop_id:
                self._summary.wrong_shop_count += 1

        # 过度追问检测
        if metrics.clarification_asked and not metrics.clarification_needed:
            self._summary.over_clarification_count += 1

        # 兜底检测
        if metrics.fallback:
            self._summary.fallback_count += 1
            self._summary.intent_fallback[metrics.intent] += 1
            self._summary.style_fallback[metrics.answer_style] += 1

        # 工具调用统计
        if metrics.tools_called or metrics.tool_called:
            self._summary.tool_call_count += 1
            if metrics.tool_called:
                self._summary.tool_hit_count += 1

        # 空召回检测
        if metrics.evidence_count == 0 and not metrics.fallback:
            self._summary.empty_recall_count += 1

        # 实时信息错误检测
        if metrics.realtime_facets and not metrics.tool_called:
            has_realtime_claim = any(
                kw in metrics.answer_text
                for kw in ("实时", "刚查", "最新", "当前券", "现在营业")
            )
            if has_realtime_claim:
                self._summary.realtime_error_count += 1

        # 禁止维度泄露检测
        if metrics.forbidden_facets and metrics.answer_text:
            for facet in metrics.forbidden_facets:
                if facet in metrics.answer_text:
                    self._summary.forbidden_facet_leak_count += 1
                    break

        # 降级检测
        if metrics.degraded:
            self._summary.degraded_count += 1
            self._summary.intent_degraded[metrics.intent] += 1

        # intent 统计
        self._summary.intent_counts[metrics.intent] += 1
        self._summary.style_counts[metrics.answer_style] += 1

        # 失败模式统计
        for mode in metrics.failure_modes_detected:
            self._summary.failure_mode_counts[mode] += 1

        # 重试统计
        if metrics.retry_count > 0:
            self._summary.retry_count += metrics.retry_count
            if metrics.retry_improved is True:
                self._summary.retry_improved_count += 1
            elif metrics.retry_improved is False:
                self._summary.retry_degraded_count += 1

        # 新鲜度统计
        if metrics.freshness_status:
            self._summary.freshness_counts[metrics.freshness_status] += 1

        # 过时检测统计
        if metrics.staleness_detected:
            self._summary.staleness_count += 1

        # 场景违禁词统计
        if metrics.scene_violation:
            self._summary.scene_violation_count += 1

        # 对话状态统计
        if metrics.dialog_state:
            self._summary.dialog_state_counts[metrics.dialog_state] += 1

    def get_summary(self) -> MetricsSummary:
        return self._summary

    def get_intent_breakdown(self) -> dict[str, dict[str, Any]]:
        """按 intent 分类的详细统计"""
        breakdown: dict[str, dict[str, Any]] = {}
        for intent, count in self._summary.intent_counts.items():
            breakdown[intent] = {
                "total": count,
                "cross_shop": self._summary.intent_cross_shop.get(intent, 0),
                "fallback": self._summary.intent_fallback.get(intent, 0),
                "degraded": self._summary.intent_degraded.get(intent, 0),
                "cross_shop_rate": self._summary.intent_cross_shop.get(intent, 0) / max(1, count),
                "fallback_rate": self._summary.intent_fallback.get(intent, 0) / max(1, count),
            }
        return breakdown

    def reset(self) -> None:
        self._queries.clear()
        self._summary = MetricsSummary()


business_metrics_collector = BusinessMetricsCollector()
