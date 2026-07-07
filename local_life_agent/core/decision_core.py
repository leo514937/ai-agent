"""DEPRECATED_COMPAT: decision planning 兼容壳。

Phase 1 仅保留旧调用方，不扩展新的导出或业务判断。
"""

from __future__ import annotations

from typing import Any


class DecisionCore:
    def build_candidate_decision_plan(self, *args: Any, **kwargs: Any):
        from ..planning.decision.candidate_decision import build_candidate_decision_plan

        return build_candidate_decision_plan(*args, **kwargs)

    def map_candidate_decision_plan(self, *args: Any, **kwargs: Any):
        from ..planning.decision.candidate_decision import map_candidate_decision_plan_to_decision_plan

        return map_candidate_decision_plan_to_decision_plan(*args, **kwargs)

    def plan_decision(self, *args: Any, **kwargs: Any):
        from ..planning.decision.decision_planner import plan_decision

        return plan_decision(*args, **kwargs)

    def plan_decision_with_llm(self, *args: Any, **kwargs: Any):
        from ..planning.decision.decision_planner import plan_decision_with_llm

        return plan_decision_with_llm(*args, **kwargs)

    def review_decision(self, *args: Any, **kwargs: Any):
        from ..planning.decision.decision_review import review_decision

        return review_decision(*args, **kwargs)
