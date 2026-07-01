from __future__ import annotations

from types import SimpleNamespace

from local_life_agent.domain.candidate import CandidateSet, CandidateSource, CandidateStatus, GoalType, LocalLifeGoalDraft, ResolvedCandidate
from local_life_agent.domain.enums import TaskType
from local_life_agent.domain.schemas import ExecutionPlan, ToolCallSpec
from local_life_agent.domain.state import SessionState
from local_life_agent.engine.subgraphs import execution_review_subgraph as ers
from local_life_agent.engine.subgraphs import planning_subgraph as ps
from local_life_agent.engine.subgraphs import state_update_plan as sup


class _Model:
    def __init__(self, **fields):
        self.__dict__.update(fields)

    def model_dump(self):
        return dict(self.__dict__)


def test_goal_planner_subgraph_uses_planning_core(monkeypatch):
    calls: list[tuple[tuple, dict]] = []

    class FakePlanningCore:
        def plan_goal_with_llm(self, *args, **kwargs):
            calls.append((args, kwargs))
            plan = _Model(
                goal_type="recommendation",
                candidate_source="discovery",
                unsupported=False,
                planner_source="llm_goal_planner",
                source_origin="llm_goal_planner",
                model_dump=lambda: {
                    "goal_type": "recommendation",
                    "candidate_source": "discovery",
                    "unsupported": False,
                    "planner_source": "llm_goal_planner",
                    "source_origin": "llm_goal_planner",
                },
            )
            return plan, {"llm_backend": "tests_fake", "error_code": ""}

    monkeypatch.setattr(ps, "_PLANNING_CORE", FakePlanningCore())
    state = {
        "semantic_frame": {},
        "session_state": SessionState(),
        "raw_text": "附近推荐火锅",
    }

    result = ps._h_goal_planner(state)

    assert calls
    assert result["goal_plan"].goal_type == "recommendation"
    assert result["planning_llm_backend"] == "tests_fake"


def test_target_resolve_subgraph_uses_candidate_core(monkeypatch):
    calls: list[tuple[tuple, dict]] = []

    class FakeCandidateCore:
        def resolve(self, *args, **kwargs):
            calls.append((args, kwargs))
            return CandidateSet(
                status=CandidateStatus.RESOLVED,
                source=CandidateSource.DISCOVERY,
                candidates=[
                    ResolvedCandidate(
                        shop_id="shop_sc_01",
                        shop_name="海底捞火锅(水晶城购物中心店)",
                        source=CandidateSource.DISCOVERY,
                        confidence=0.9,
                    )
                ],
                requested_count=1,
                min_required=1,
                max_allowed=5,
            )

    monkeypatch.setattr(ps, "_CANDIDATE_CORE", FakeCandidateCore())
    monkeypatch.setattr(ps, "build_local_life_goal_draft", lambda *_args, **_kwargs: LocalLifeGoalDraft(goal_type=GoalType.RECOMMENDATION, candidate_source=CandidateSource.DISCOVERY))
    monkeypatch.setattr(ps, "build_candidate_spec", lambda *_args, **_kwargs: SimpleNamespace(model_dump=lambda: {"source": "discovery"}))
    monkeypatch.setattr(ps, "review_candidate_set", lambda *_args, **_kwargs: SimpleNamespace(next_action=ps.NextAction.FINISH, status="enough", reason="ok"))

    state = {
        "semantic_frame": {},
        "session_state": SessionState(),
        "raw_text": "附近推荐火锅",
    }

    result = ps._h_target_resolve_candidate_set(state, {})

    assert calls
    assert result["resolve_shop_result"].status == "RESOLVED"
    assert result["candidate_set"].status == CandidateStatus.RESOLVED


def test_target_resolve_subgraph_does_not_pick_first_when_multiple_candidates(monkeypatch):
    calls: list[tuple[tuple, dict]] = []

    class FakeCandidateCore:
        def resolve(self, *args, **kwargs):
            calls.append((args, kwargs))
            return CandidateSet(
                status=CandidateStatus.RESOLVED,
                source=CandidateSource.DISCOVERY,
                candidates=[
                    ResolvedCandidate(
                        shop_id="shop_sc_01",
                        shop_name="川味轩",
                        source=CandidateSource.DISCOVERY,
                        confidence=0.95,
                    ),
                    ResolvedCandidate(
                        shop_id="shop_sc_02",
                        shop_name="海底捞",
                        source=CandidateSource.DISCOVERY,
                        confidence=0.92,
                    ),
                ],
                requested_count=2,
                min_required=1,
                max_allowed=5,
            )

    monkeypatch.setattr(ps, "_CANDIDATE_CORE", FakeCandidateCore())
    monkeypatch.setattr(ps, "build_local_life_goal_draft", lambda *_args, **_kwargs: LocalLifeGoalDraft(goal_type=GoalType.RECOMMENDATION, candidate_source=CandidateSource.DISCOVERY))
    monkeypatch.setattr(ps, "build_candidate_spec", lambda *_args, **_kwargs: SimpleNamespace(model_dump=lambda: {"source": "discovery"}))
    monkeypatch.setattr(ps, "review_candidate_set", lambda *_args, **_kwargs: SimpleNamespace(next_action=ps.NextAction.FINISH, status="enough", reason="ok"))

    state = {
        "semantic_frame": {},
        "session_state": SessionState(),
        "raw_text": "附近推荐火锅",
    }

    result = ps._h_target_resolve_candidate_set(state, {})

    assert calls
    assert result["resolve_shop_result"].status == "RESOLVED"
    assert result["resolve_shop_result"].resolved_shop is not None
    assert result.get("resolved_target") is None
    assert result["target_resolution_status"] == "CANDIDATE_SET_RESOLVED"
    assert result["resolution_stage"] == "candidate_set_resolved"
    assert result["candidate_set"].status == CandidateStatus.RESOLVED


def test_tool_execute_subgraph_uses_execution_core(monkeypatch):
    calls: list[tuple[tuple, dict]] = []

    class FakeExecutionCore:
        def __init__(self, call_fn=None):
            self.call_fn = call_fn

        def execute_batch(self, tool_calls):
            calls.append((tuple(tool_calls), {"call_fn": self.call_fn}))
            return {
                "call_1": {
                    "call_id": "call_1",
                    "shop_id": "shop_sc_01",
                    "tool_name": "get_shop_detail",
                    "success": True,
                    "result_status": "ok",
                    "data": {"shop_id": "shop_sc_01"},
                    "error_code": None,
                    "error_message": "",
                    "source": "tests_fake",
                    "tool_backend": "tests_fake",
                    "backend_source": "tests_fake",
                    "degraded": False,
                }
            }

    monkeypatch.setattr(ers, "ExecutionCore", FakeExecutionCore)
    plan = ExecutionPlan(
        plan_id="plan_1",
        task_type=TaskType.single_shop_query.value,
        tool_calls=[
            ToolCallSpec(
                call_id="call_1",
                tool_name="get_shop_detail",
                args={"shop_id": "shop_sc_01"},
                target_shop_id="shop_sc_01",
                required=True,
                facet="detail",
            )
        ],
        target_shop_ids=["shop_sc_01"],
    )
    state = {
        "validated_plan": plan,
        "session_state": SessionState(),
    }

    result = ers._h_tool_execute(state)

    assert calls
    assert result["tool_results"]["call_1"].result_status == "ok"


def test_state_update_subgraph_uses_state_core(monkeypatch):
    calls: dict[str, bool] = {"plan": False, "patch": False}

    class FakeStateCore:
        def build_session_state(self, **fields):
            return SessionState(**fields)

        def build_state_patch(self, set_fields=None, clear_fields=None):
            calls["patch"] = True
            return SimpleNamespace(set_fields=set_fields or {}, clear_fields=clear_fields or [])

        def plan_state_update(self, turn_context, task_type, resolve_shop_status, pending_check_result=None):
            calls["plan"] = True
            return {"set_fields": {"current_shop": {"shop_id": "shop_sc_01", "shop_name": "海底捞"}}, "clear_fields": []}

    monkeypatch.setattr(sup, "_STATE_CORE", FakeStateCore())
    state = {
        "session_id": "sid_1",
        "task_type": TaskType.single_shop_query.value,
        "resolve_shop_result": {"status": "RESOLVED", "resolved_shop": {"shop_id": "shop_sc_01", "shop_name": "海底捞"}},
        "session_state": SessionState(),
    }

    result = sup._h_state_update_plan(state)

    assert calls["plan"] is True
    assert calls["patch"] is True
    assert result["state_update_plan"].set_fields["current_shop"]["shop_id"] == "shop_sc_01"
