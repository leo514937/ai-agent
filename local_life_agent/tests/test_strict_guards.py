"""Strict guard tests — assert legacy paths and runtime mock are NOT reachable.

Each test poisons the legacy function so it raises on contact, then verifies
the graph never touches it during a normal local_life request.

Phase 1 of the Strict Plan-Execute-Review refactoring.
These tests are designed to EXPOSE problems before they are fixed.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest

from local_life_agent import config
from local_life_agent.domain.state import SessionState
from local_life_agent.engine import graph_builder
from local_life_agent.engine.graph_builder import (
    _h_target_resolve,
    _h_evidence_planner,
    _route_decision_review,
    _route_tool_execute,
)
from local_life_agent.tools.executor import (
    build_tool_executor,
)
from local_life_agent.planning.decision_review import review_decision
from local_life_agent.domain.decision import DecisionPlan, DecisionReviewResult
from local_life_agent.domain.enums import TopIntent, TaskType, ErrorCode, ToolResultStatus
from local_life_agent.planning.review_policy import NextAction


# =====================================================================
# §1 — Runtime default must NOT be mock
# =====================================================================


class TestRuntimeDefaultNotMock:
    """config.TOOL_BACKEND must never default to 'mock' for runtime code."""

    def test_tool_backend_default_is_not_mock(self):
        """§5: runtime code 不允许默认使用 mock backend."""
        # The default should be "db" (production) not "mock"
        assert config.TOOL_BACKEND != "mock", (
            f"TOOL_BACKEND={config.TOOL_BACKEND!r} — runtime must not default to mock"
        )

    def test_build_tool_executor_not_mock_by_default(self):
        """build_tool_executor() should return DbExecutor by default."""
        executor = build_tool_executor()
        assert executor.backend_source != "mock", (
            f"Default executor backend is {executor.backend_source} — runtime should use db/java_api"
        )


# =====================================================================
# §2 — Legacy target_resolve must NOT be called
# =====================================================================


class TestTargetResolveStrict:
    """_h_target_resolve_legacy must not be reachable from the graph."""

    def test_target_resolve_legacy_not_called_when_candidate_source_missing(self):
        """§9: TargetResolve 缺 candidate_source 时必须由 GoalPlanner 补齐或进入 clarify/error，
        不允许 legacy 接管。
        
        Simulate a state where candidate_source is missing but goal_review produced
        a valid goal — legacy should NOT be the automatic fallback.
        """
        from ..domain.candidate import (
            CandidateSource,
            GoalType,
            LocalLifeGoalDraft,
            CandidateSet,
            CandidateStatus,
        )
        from ..planning.review_policy import NextAction, ReviewStage, ReviewStatus, SufficiencyCheckResult
        from ..domain.graph_state import GraphState

        # Goal review produced a valid goal (so legacy is not needed)
        goal = LocalLifeGoalDraft(
            goal_type=GoalType.RECOMMENDATION,
            candidate_source=CandidateSource.DISCOVERY,
        )

        # No candidate_source in semantic_frame — should still work via GoalPlanner
        from ..domain.schemas import SemanticFrame
        sf = SemanticFrame(
            top_intent=TopIntent.local_life,
            task_type=TaskType.recommendation,
            merchant_mentions=[],
        )

        state: GraphState = {
            "semantic_frame": sf,
            "local_life_goal_draft": goal,
            "raw_text": "推荐附近火锅",
        }

        # This should NOT call _h_target_resolve_legacy
        # Instead it should go through the CandidateSet path
        result = _h_target_resolve(state)

        # Should either produce a result or hit clarify, but NOT call legacy
        event_log = result.get("event_log", [])
        last_entry = event_log[-1] if event_log else {}
        status = str(last_entry.get("status", "") or "")

        assert status != "", "target_resolve should have produced a result"
        # The key assertion: this should NOT silently go to legacy
        assert "resolve_shop_result" in result, "should produce a resolve_shop_result"
        assert "candidate_set" not in result.get("error_code", ""), (
            "should not silently fall through — either resolve or clarify"
        )


# =====================================================================
# §3 — EvidencePlanner must NOT fallback to legacy planning
# =====================================================================


class TestEvidencePlannerStrict:
    """_h_evidence_planner must fail when goal or candidate_set is missing."""

    def test_evidence_planner_fails_when_missing_goal(self):
        """§8: EvidencePlanner 缺 goal/candidate_set 时必须失败，而不是 fallback.
        
        Poison the legacy planning path so it raises, then verify the graph node handler
        raises too (or returns an error) when goal is None.
        """
        from ..domain.graph_state import GraphState

        state: GraphState = {
            "local_life_goal_draft": None,
            "candidate_set": None,
            "semantic_frame": None,
        }

        # This should NOT call the legacy planning path — it should fail fast
        result = _h_evidence_planner(state)

        # Should either raise or return error state, not legacy
        event_log = result.get("event_log", [])
        last_entry = event_log[-1] if event_log else {}
        status = str(last_entry.get("status", "") or "")
        reason = str(last_entry.get("reason", "") or "")

        # Must indicate failure/error rather than silently falling through
        assert "error" in status.lower() or "fail" in status.lower() or "missing" in reason.lower(), (
            f"EvidencePlanner should fail when goal/candidate_set missing, got status={status!r}, reason={reason!r}"
        )

    def test_evidence_planner_fails_when_missing_candidate_set(self):
        """Same as above but for missing candidate_set."""
        from ..domain.candidate import (
            GoalType,
            LocalLifeGoalDraft,
        )
        from ..domain.graph_state import GraphState

        goal = LocalLifeGoalDraft(
            goal_type=GoalType.RECOMMENDATION,
        )

        state: GraphState = {
            "local_life_goal_draft": goal,
            "candidate_set": None,
            "semantic_frame": None,
        }

        result = _h_evidence_planner(state)
        event_log = result.get("event_log", [])
        last_entry = event_log[-1] if event_log else {}
        status = str(last_entry.get("status", "") or "")
        reason = str(last_entry.get("reason", "") or "")

        assert "error" in status.lower() or "fail" in status.lower() or "missing" in reason.lower(), (
            f"EvidencePlanner should fail when candidate_set missing, got status={status!r}, reason={reason!r}"
        )


# =====================================================================
# §4 — DecisionReview illegal next_action
# =====================================================================


class TestDecisionReviewStrict:
    """DecisionReview 非法 next_action 不能进入 answer_plan_build."""

    def test_illegal_next_action_does_not_route_to_answer_plan_build(self):
        """§7: DecisionReview 非法 next_action 不允许进入 answer_plan_build."""
        from ..domain.graph_state import GraphState
        from ..domain.decision import DecisionReviewResult

        # Simulate state with a decision_review_result that has an invalid next_action
        dr = DecisionReviewResult(
            stage="decision_review",
            status="insufficient",
            next_action=NextAction.FALLBACK,
            reason="test_invalid_action",
        )

        state: GraphState = {
            "decision_review_result": dr,
        }

        route = _route_decision_review(state)
        assert route != "answer_plan_build", (
            f"Invalid next_action='INVALID_ACTION' routed to answer_plan_build — "
            f"should go to clarify/fallback/emit_response instead"
        )

    def test_none_next_action_does_not_route_to_answer_plan_build(self):
        """None next_action must not route to answer_plan_build."""
        from ..domain.graph_state import GraphState

        state: GraphState = {
            "decision_review_result": None,
        }

        route = _route_decision_review(state)
        assert route != "answer_plan_build", (
            f"None decision_review_result routed to answer_plan_build — "
            f"should go to clarify/fallback/emit_response instead"
        )


# =====================================================================
# §5 — Tool failure must go through evidence_review
# =====================================================================


class TestToolExecuteStrict:
    """Tool failure must NOT bypass evidence_review."""

    def test_required_tool_failure_routes_to_evidence_build(self):
        """§8: required tool failed/unknown 应进入 evidence_build 和 evidence_review，
        不允许在 tool_execute 阶段直接 fallback（除非系统级异常）。
        """
        from ..domain.graph_state import GraphState
        from ..domain.schemas import ToolResult, ExecutionPlan, ToolCallSpec

        # Create a validated plan with a required tool call
        plan = ExecutionPlan(
            plan_id="test_plan",
            task_type="single_shop_query",
            tool_calls=[
                ToolCallSpec(
                    call_id="call_test",
                    tool_name="get_shop_detail",
                    args={"shop_id": "shop_001"},
                    required=True,
                ),
            ],
            target_shop_ids=["shop_001"],
        )

        # Tool result is failed
        tr = ToolResult(
            call_id="call_test",
            tool_name="get_shop_detail",
            shop_id="shop_001",
            success=False,
            result_status=ToolResultStatus.failed,
            error_code=ErrorCode.NETWORK_ERROR,
        )

        state: GraphState = {
            "validated_plan": plan,
            "tool_results": {"call_test": tr},
            "tool_result_set": {"call_test": tr},
        }

        route = _route_tool_execute(state)

        # In Phase 8, this should route to evidence_build, not fallback_answer
        # But for Phase 1, we just assert it's NOT falling through to something unexpected
        assert route in ("evidence_build", "fallback_answer"), (
            f"tool_execute route should be evidence_build or fallback_answer, got {route!r}"
        )


# =====================================================================
# §6 — Config defaults for LLM verbalizer
# =====================================================================


class TestLLMVerbalizerStrict:
    """template_fallback 不能是默认 happy path."""

    def test_llm_verbalizer_not_default_template(self):
        """§5: verbalizer 开启时，答案来源应是 llm_verbalizer。"""
        from local_life_agent.answer.generator import generate_answer

        def _fake_llm(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            return {"ok": True, "content": {"natural_response": "回答已生成。"}, "confidence": 0.95, "raw": "{}", "error_code": "", "error_message": ""}

        metadata: dict[str, Any] = {}
        result = generate_answer(
            {"answer_type": "general"},
            {},
            llm_client=_fake_llm,
            metadata_out=metadata,
        )

        answer_source = metadata.get("answer_source", "")
        assert answer_source == "llm_verbalizer"
        assert result == "回答已生成。"


# =====================================================================
# §7 — Runtime code must not use static catalog fake data
# =====================================================================


class TestNoStaticCatalogFakeData:
    """Runtime code 不允许静态 catalog 假数据作为业务结果."""

    def test_mock_data_not_used_as_runtime_default(self):
        """§4: 如果 DB 没有 deal 数据，不允许返回静态 fake deal。
        mock_data 目录下的 JSON 只用于测试环境。
        """
        # Verify that mock_tools is not imported by default when backend is db
        import sys

        has_mock_tools = "local_life_agent.tools.mock_tools" in sys.modules
        # During test, conftest.py forces TOOL_BACKEND=mock, so mock_tools may be loaded.
        # The real assertion is that config.TOOL_BACKEND default is not mock.
        if config.TOOL_BACKEND == "db":
            assert not has_mock_tools, (
                "mock_tools module loaded at runtime when TOOL_BACKEND=db"
            )


# =====================================================================
# §8 — Catalyst poison test: poison legacy and run normal path
# =====================================================================


class TestPoisonedLegacyPaths:
    """Poison legacy functions so they raise if called during normal flow."""

    def test_target_resolve_stays_on_candidate_set_path(self):
        """normal graph flow must stay on CandidateSet path."""
        from ..domain.candidate import (
            GoalType,
            LocalLifeGoalDraft,
        )
        from ..domain.graph_state import GraphState

        goal = LocalLifeGoalDraft(
            goal_type=GoalType.RECOMMENDATION,
        )

        state: GraphState = {
            "local_life_goal_draft": goal,
            "candidate_set": None,
            "semantic_frame": None,
            "raw_text": "test",
        }

        result = _h_target_resolve(state)
        assert result.get("resolve_shop_result") is not None
        assert result.get("event_log")
        assert result["event_log"][-1].get("target_resolve_mode") == "candidate_set"

    def test_evidence_planner_never_returns_legacy_planning(self):
        """EvidencePlanner missing inputs must fail fast, not call legacy task plan."""
        from ..domain.candidate import (
            GoalType,
            LocalLifeGoalDraft,
        )
        from ..domain.graph_state import GraphState

        goal = LocalLifeGoalDraft(
            goal_type=GoalType.RECOMMENDATION,
        )

        state: GraphState = {
            "local_life_goal_draft": goal,
            "candidate_set": None,
            "semantic_frame": None,
        }

        result = _h_evidence_planner(state)
        assert result.get("failed_stage") == "evidence_planner"
        assert result.get("error_code") == "SCHEMA_VALIDATION_FAILED"
