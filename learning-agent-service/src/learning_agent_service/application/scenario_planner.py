"""ScenarioPlanner — 复杂需求拆解。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class PlannedStep:
    """计划步骤。"""
    action: str
    target: str | None = None
    params: dict[str, Any] | None = None
    description: str = ""


class ScenarioPlanner:
    """复杂需求拆解。

    将用户的复杂需求拆解为多个可执行步骤。
    """

    def plan(
        self,
        query: str,
        context: dict[str, Any] | None = None,
    ) -> list[PlannedStep]:
        """将复杂需求拆解为多个步骤。"""
        steps: list[PlannedStep] = []
        context = context or {}

        if "推荐" in query or "附近" in query:
            steps.append(PlannedStep(
                action="search",
                target="shops",
                params={"query": query},
                description="搜索附近店铺",
            ))
        elif "优惠" in query or "券" in query:
            steps.append(PlannedStep(
                action="search",
                target="coupons",
                params={"query": query},
                description="搜索优惠券",
            ))
        elif "营业" in query or "开门" in query:
            steps.append(PlannedStep(
                action="check",
                target="open_status",
                params={"query": query},
                description="检查营业状态",
            ))
        elif "距离" in query or "多远" in query or "导航" in query:
            steps.append(PlannedStep(
                action="check",
                target="distance",
                params={"query": query},
                description="查询距离",
            ))
        else:
            steps.append(PlannedStep(
                action="query",
                target="shop_info",
                params={"query": query},
                description="查询店铺信息",
            ))

        return steps