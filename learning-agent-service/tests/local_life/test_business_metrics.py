from learning_agent_service.local_life.business_metrics import (
    BusinessMetricsCollector,
    MetricsSummary,
    QueryMetrics,
)


def test_retry_metrics():
    collector = BusinessMetricsCollector()

    metrics = QueryMetrics(
        query="test",
        intent="test",
        route="test",
        answer_style="test",
        retry_count=2,
        retry_improved=True,
    )
    collector.record_query(metrics)

    summary = collector.get_summary()
    assert summary.retry_count == 2
    assert summary.retry_improved_count == 1


def test_staleness_metrics():
    collector = BusinessMetricsCollector()

    metrics = QueryMetrics(
        query="test",
        intent="test",
        route="test",
        answer_style="test",
        staleness_detected=True,
        freshness_status="historical",
    )
    collector.record_query(metrics)

    summary = collector.get_summary()
    assert summary.staleness_count == 1
    assert summary.freshness_counts["historical"] == 1


def test_retry_degraded():
    collector = BusinessMetricsCollector()

    metrics = QueryMetrics(
        query="test",
        intent="test",
        route="test",
        answer_style="test",
        retry_count=1,
        retry_improved=False,
    )
    collector.record_query(metrics)

    summary = collector.get_summary()
    assert summary.retry_count == 1
    assert summary.retry_degraded_count == 1


def test_scene_violation():
    collector = BusinessMetricsCollector()

    metrics = QueryMetrics(
        query="test",
        intent="test",
        route="test",
        answer_style="test",
        scene_violation=True,
    )
    collector.record_query(metrics)

    summary = collector.get_summary()
    assert summary.scene_violation_count == 1


def test_dialog_state():
    collector = BusinessMetricsCollector()

    metrics = QueryMetrics(
        query="test",
        intent="test",
        route="test",
        answer_style="test",
        dialog_state="clarification",
    )
    collector.record_query(metrics)

    summary = collector.get_summary()
    assert summary.dialog_state_counts["clarification"] == 1


def test_to_dict_includes_new_fields():
    collector = BusinessMetricsCollector()

    metrics = QueryMetrics(
        query="test",
        intent="test",
        route="test",
        answer_style="test",
        retry_count=3,
        retry_improved=True,
        staleness_detected=True,
        freshness_status="realtime",
        scene_violation=True,
        dialog_state="search",
    )
    collector.record_query(metrics)

    d = collector.get_summary().to_dict()
    assert "retry_rate" in d
    assert "retry_improvement_rate" in d
    assert "staleness_rate" in d
    assert "scene_violation_rate" in d
    assert "dialog_state_distribution" in d
    assert "freshness_distribution" in d
    assert d["retry_rate"] == 3
    assert d["retry_improvement_rate"] == 1 / 3
    assert d["freshness_distribution"] == {"realtime": 1}
