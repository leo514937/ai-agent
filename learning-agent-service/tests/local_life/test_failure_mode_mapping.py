"""Tests for failure mode mapping detection."""
from learning_agent_service.local_life.failure_mode_mapping import FailureModeDetector


def test_detect_realtime_facet_issues():
    detector = FailureModeDetector()
    
    # 有tool调用 - 正常
    issues = detector.detect_realtime_facet_issues(
        answer_text="有优惠券",
        realtime_facets=["coupon"],
        tools_called=["get_coupon_list"],
    )
    assert len(issues) == 0
    
    # 无tool调用 - 问题
    issues = detector.detect_realtime_facet_issues(
        answer_text="有优惠券",
        realtime_facets=["coupon"],
        tools_called=[],
    )
    assert "realtime_facet_rag_source" in issues


def test_detect_comparison_issues():
    detector = FailureModeDetector()
    
    # 对比但只有一家店 - 问题
    issues = detector.detect_comparison_issues(
        answer_style="comparison",
        answer_text="海底捞不错",
        shop_count=1,
    )
    assert "comparison_single_shop" in issues
    
    # 对比有两家店 - 正常
    issues = detector.detect_comparison_issues(
        answer_style="comparison",
        answer_text="海底捞和呷哺呷哺对比",
        shop_count=2,
    )
    assert len(issues) == 0


def test_detect_staleness_issues():
    detector = FailureModeDetector()
    
    # 有过时证据 - 问题
    issues = detector.detect_staleness_issues(
        evidence_metadata_list=[{"deprecated": True}]
    )
    assert "stale_evidence_used" in issues
    
    # 无过时证据 - 正常
    issues = detector.detect_staleness_issues(
        evidence_metadata_list=[{"fresh": True}]
    )
    assert len(issues) == 0