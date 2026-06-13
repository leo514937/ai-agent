from datetime import datetime, timezone

from types import SimpleNamespace

from learning_agent_service.application.workflow.builder import (
    _apply_retry_quality_evaluation,
    _collect_query_metrics,
    _prepare_retry_node,
)
from learning_agent_service.domain.contracts import GraphRuntimeMeta, PersistentSessionContext, ReviewReport, TurnRuntimeState
from learning_agent_service.application.workflow.adapters.stages_main_graph import WorkflowNodeAdapterMainGraphMixin
from learning_agent_service.tools.models import NormalizedToolResult
from learning_agent_service.local_life.business_metrics import business_metrics_collector


def _build_state(*, turn: TurnRuntimeState):
    return {
        "persistent": PersistentSessionContext(),
        "turn": turn,
        "runtime": GraphRuntimeMeta(
            trace_id="trace",
            session_id="session",
            turn_id="turn",
            workflow_version="test",
            request_ts=datetime.now(timezone.utc),
            user_id="user",
        ),
        "runtime_context": {},
        "sse_events": [],
        "errors": [],
        "stage_timeline": [],
        "retrieval_traces": [],
        "tool_results": [],
        "shop_analyses": [],
    }


def test_prepare_retry_node_stores_retry_snapshot():
    turn = TurnRuntimeState(
        raw_query="海底捞怎么样",
        final_answer="这是一段较完整的原始回答，包含环境和服务信息。",
        extra={
            "evidence_claims": [{"claim": "环境不错"}, {"claim": "服务很好"}],
            "tool_results": [{"tool_name": "get_coupon_list"}],
            "review_report": ReviewReport(decision="repair_answer", retry_count=0, max_retry_count=1, repair_hint="补充更多对比维度"),
        },
    )
    state = _build_state(turn=turn)

    services = SimpleNamespace(main_graph=WorkflowNodeAdapterMainGraphMixin())
    updated = _prepare_retry_node(state, services)
    turn_extra = updated["turn"].extra

    assert turn_extra["retry_snapshot"]["answer_text"].startswith("这是一段较完整的原始回答")
    assert turn_extra["retry_snapshot"]["evidence_count"] == 2
    assert turn_extra["review_report"].retry_count == 1
    assert turn_extra["rewrite_decision"].should_retrieve is True


def test_prepare_retry_node_handles_retryable_tool_failure():
    turn = TurnRuntimeState(
        raw_query="????????",
        tool_result={
            "status": "failed",
            "tool_name": "get_coupon_list",
            "normalized_output": {},
            "used_tools": ["get_coupon_list"],
            "approval_required": False,
            "approval_status": None,
            "approval_request": {},
            "extra": {
                "retryable": True,
                "degraded": True,
                "failure_category": "timeout",
                "retry_reason": "timeout",
            },
        },
        extra={
            "tool_results": [{"tool_name": "get_coupon_list"}],
            "review_report": ReviewReport(
                decision="retry_tool",
                reason="timeout",
                retry_target="get_coupon_list",
                retry_count=0,
                max_retry_count=1,
                extra={"failure_category": "timeout"},
            ),
        },
    )
    state = _build_state(turn=turn)

    services = SimpleNamespace(main_graph=WorkflowNodeAdapterMainGraphMixin())
    updated = _prepare_retry_node(state, services)
    turn_extra = updated["turn"].extra

    assert turn_extra["review_report"].retry_count == 1
    assert turn_extra["retry_snapshot"]["retry_origin"] == "tool"
    assert turn_extra["retry_snapshot"]["tool_name"] == "get_coupon_list"
    assert turn_extra["retry_snapshot"]["failure_category"] == "timeout"
    assert turn_extra["rewrite_decision"].reason == "retry_tool_failure"
    assert turn_extra["rewrite_decision"].should_retrieve is True


def test_apply_retry_quality_evaluation_reverts_degraded_answer():
    turn = TurnRuntimeState(raw_query="海底捞怎么样", final_answer="简短回答")
    turn_extra = {
        "retry_snapshot": {
            "answer_text": "这是一段长度超过五十个字符的详细回答，包含环境、服务、口味和消费建议，信息更完整。",
            "evidence_count": 5,
        },
        "review_report": ReviewReport(decision="repair_answer", retry_count=1, max_retry_count=1),
    }

    updated_turn, updated_extra = _apply_retry_quality_evaluation(
        turn,
        turn_extra,
        answer_text="简短回答",
        evidence_claims=[],
        tool_results=[],
    )

    assert updated_turn.final_answer.startswith("这是一段长度超过五十个字符的详细回答")
    assert updated_extra["retry_quality"]["reverted_to_pre_retry"] is True
    assert updated_extra["retry_quality"]["should_keep_retry"] is False


def test_collect_query_metrics_records_retry_quality():
    business_metrics_collector.reset()
    turn = TurnRuntimeState(
        raw_query="海底捞怎么样",
        final_answer="更详细的重试后回答，包含更多信息。",
        extra={
            "answer_contract": type("Contract", (), {"intent": "merchant_detail", "answer_style": "single_shop_review", "forbidden_facets": [], "realtime_facets": []})(),
            "review_report": ReviewReport(decision="repair_answer", retry_count=1, max_retry_count=1),
            "retry_quality": {"improvement": 0.2},
            "evidence_claims": [{"claim": "环境不错"}],
        },
    )
    state = _build_state(turn=turn)

    _collect_query_metrics(state)
    summary = business_metrics_collector.get_summary()

    assert summary.retry_count == 1
    assert summary.retry_improved_count == 1

    business_metrics_collector.reset()
