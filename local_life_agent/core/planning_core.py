"""DEPRECATED_COMPAT: goal / evidence planning 兼容壳。

Canonical path 仍在 planning/goal 与 planning/evidence 的分层模块中。
"""

from __future__ import annotations

from typing import Any


class PlanningCore:
    def plan_goal(self, *args: Any, **kwargs: Any):
        from ..planning.goal.goal_planner import plan_goal

        return plan_goal(*args, **kwargs)

    def plan_goal_with_llm(self, *args: Any, **kwargs: Any):
        from ..planning.goal.goal_planner import plan_goal_with_llm

        return plan_goal_with_llm(*args, **kwargs)

    def plan_evidence(self, *args: Any, **kwargs: Any):
        from ..planning.evidence.evidence_planner import plan_evidence

        return plan_evidence(*args, **kwargs)

    def plan_evidence_with_llm(self, *args: Any, **kwargs: Any):
        from ..planning.evidence.evidence_planner import plan_evidence_with_llm

        return plan_evidence_with_llm(*args, **kwargs)
